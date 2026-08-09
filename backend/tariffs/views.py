from functools import partial

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from accounts.permissions import IsZevOwnerOrAdmin
from .models import Tariff, TariffPeriod
from zev.scoping import ZevScopedQuerySetMixin
from .serializers import TariffSerializer, TariffPeriodSerializer
from .series import active_version, find_gaps, plan_new_version, series_key, sort_versions
from audit.models import AuditActionCategory
from audit.mixins import AuditedUpdateMixin
from audit.services import record_audit_event


# Every audit event in this module is a tariff event; bind the category once.
_record_tariff_event = partial(record_audit_event, action_category=AuditActionCategory.TARIFF)


def _parse_required_date(raw, field: str):
    """Parse an ISO date, raising a DRF error the client can act on."""
    parsed = parse_date(str(raw)) if raw else None
    if parsed is None:
        raise DRFValidationError({field: [f'{field} is required as an ISO date (YYYY-MM-DD).']})
    return parsed


def _apply_price_overrides(tariff, data: dict) -> None:
    """Carry an explicit ``fixed_price_chf`` / ``percentage`` onto a copied tariff.

    Absent keys leave the copied value in place; a new version that only shifts
    its validity window should not have to restate its price.
    """
    for field in ('fixed_price_chf', 'percentage'):
        if field in data:
            setattr(tariff, field, data[field])


def _copy_or_replace_periods(source, target, periods_data) -> None:
    """Give ``target`` the price bands of ``source``, or the supplied ones.

    Prices live on ``TariffPeriod``, not on the tariff, so a copy that skipped
    the bands would produce a version priced at nothing.
    """
    if periods_data is None:
        TariffPeriod.objects.bulk_create([
            TariffPeriod(
                tariff=target,
                period_type=period.period_type,
                price_chf_per_kwh=period.price_chf_per_kwh,
                time_from=period.time_from,
                time_to=period.time_to,
                weekdays=period.weekdays,
            )
            for period in source.periods.all()
        ])
        return

    for period_data in periods_data:
        payload = dict(period_data)
        payload.pop('id', None)
        payload['tariff'] = str(target.pk)
        serializer = TariffPeriodSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save()


class TariffViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = TariffSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    zev_owner_filter = "zev__owner"
    participant_filter = None
    scope_parent_path = ("zev",)

    audit_action_category = AuditActionCategory.TARIFF
    audit_action_type = "tariff.update"
    audit_target_type = "tariffs.Tariff"
    audit_target_label = "tariff"

    def get_audit_target_display(self, instance):
        return instance.name

    def get_queryset(self):
        return self.scope_queryset(Tariff.objects.all())

    def perform_create(self, serializer):
        tariff = super().perform_create(serializer)
        _record_tariff_event(
            request=self.request,
            action_type="tariff.create",
            target_type="tariffs.Tariff",
            target=tariff,
            target_id=str(tariff.pk),
            target_display=tariff.name,
            summary=f"Created tariff {tariff.name}.",
            metadata={"zev_id": str(tariff.zev_id), "category": tariff.category},
        )

    def perform_destroy(self, instance):
        tariff_id = str(instance.pk)
        name = instance.name
        zev_id = str(instance.zev_id)
        instance.delete()
        _record_tariff_event(
            request=self.request,
            action_type="tariff.delete",
            target_type="tariffs.Tariff",
            target_id=tariff_id,
            target_display=name,
            summary=f"Deleted tariff {name}.",
            metadata={"zev_id": zev_id},
        )

    # ── Versioning ───────────────────────────────────────────────────────────
    #
    # Tariffs sharing a name within a ZEV are versions of one another; the model
    # already guarantees their windows do not overlap, and the engine already
    # resolves the right one per day. These endpoints add the missing
    # affordances: grouping them for display, and editing the timeline without
    # hand-computing end dates.

    @action(detail=False, methods=['get'], url_path='series')
    def list_series(self, request):
        """Tariffs grouped into series, newest version first, with gaps flagged."""
        today = timezone.localdate()
        tariffs = self.get_queryset().prefetch_related('periods')

        zev_id = request.query_params.get('zev_id')
        if zev_id:
            tariffs = tariffs.filter(zev_id=zev_id)

        grouped: dict[tuple, list] = {}
        for tariff in tariffs:
            grouped.setdefault(series_key(tariff), []).append(tariff)

        payload = []
        for versions in grouped.values():
            ordered = sort_versions(versions)
            newest = ordered[-1]
            active = active_version(ordered, today)
            payload.append({
                'zev': str(newest.zev_id),
                'name': newest.name,
                # Identity fields are invariant across a series (enforced in
                # Tariff.clean), so reading them off any version is safe.
                'category': newest.category,
                'billing_mode': newest.billing_mode,
                'energy_type': newest.energy_type,
                'version_count': len(ordered),
                'active_version_id': str(active.pk) if active else None,
                'gaps': [
                    {'start': gap.start.isoformat(), 'end': gap.end.isoformat()}
                    for gap in find_gaps(ordered)
                ],
                'versions': TariffSerializer(
                    list(reversed(ordered)), many=True, context={'request': request},
                ).data,
            })

        payload.sort(key=lambda series: (series['category'], series['name'].lower()))
        return Response(payload)

    @action(detail=True, methods=['post'], url_path='new-version')
    def new_version(self, request, pk=None):
        """Start a new version of this tariff, closing the previous one.

        Copies the source version's configuration and price bands, then lets the
        payload override the prices — which is the whole point, since a new
        version almost always exists because the price changed.
        """
        source = self.get_object()
        valid_from = _parse_required_date(request.data.get('valid_from'), 'valid_from')

        siblings = list(
            Tariff.objects.filter(zev_id=source.zev_id, name=source.name).prefetch_related('periods')
        )
        if any(version.valid_from == valid_from for version in siblings):
            return Response(
                {'valid_from': [
                    f'A version of "{source.name}" already starts on {valid_from.isoformat()}.'
                ]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        window = plan_new_version(siblings, valid_from)

        with transaction.atomic():
            # Truncate first: saving the new version while the predecessor still
            # covers this date would trip the overlap guard.
            if window.predecessor_valid_to is not None:
                predecessor = next(v for v in siblings if v.pk == window.predecessor_id)
                predecessor.valid_to = window.predecessor_valid_to
                predecessor.save()

            new_version = Tariff(
                zev_id=source.zev_id,
                name=source.name,
                category=source.category,
                billing_mode=source.billing_mode,
                energy_type=source.energy_type,
                fixed_price_chf=source.fixed_price_chf,
                percentage=source.percentage,
                notes=source.notes,
                valid_from=valid_from,
                valid_to=window.valid_to,
            )
            _apply_price_overrides(new_version, request.data)
            new_version.save()
            _copy_or_replace_periods(source, new_version, request.data.get('periods'))

        _record_tariff_event(
            request=request,
            action_type="tariff.new_version",
            target_type="tariffs.Tariff",
            target=new_version,
            target_id=str(new_version.pk),
            target_display=new_version.name,
            summary=f"Created a new version of {new_version.name} from {valid_from.isoformat()}.",
            metadata={
                "zev_id": str(new_version.zev_id),
                "source_version_id": str(source.pk),
                "closed_previous_on": (
                    window.predecessor_valid_to.isoformat()
                    if window.predecessor_valid_to else None
                ),
                "valid_to": window.valid_to.isoformat() if window.valid_to else None,
            },
        )
        return Response(
            TariffSerializer(new_version, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate(self, request, pk=None):
        """Copy this tariff under a new name, starting a separate series.

        Unlike ``new-version`` this does not touch the source's timeline: the
        copy is a different tariff that happens to start from the same numbers.
        """
        source = self.get_object()
        name = str(request.data.get('name') or '').strip()
        if not name:
            return Response({'name': ['A name is required.']}, status=status.HTTP_400_BAD_REQUEST)
        if name == source.name:
            return Response(
                {'name': ['Use new-version to add another version under the same name.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_from_raw = request.data.get('valid_from')
        valid_from = (
            _parse_required_date(valid_from_raw, 'valid_from') if valid_from_raw
            else source.valid_from
        )

        with transaction.atomic():
            copy = Tariff(
                zev_id=source.zev_id,
                name=name,
                category=source.category,
                billing_mode=source.billing_mode,
                energy_type=source.energy_type,
                fixed_price_chf=source.fixed_price_chf,
                percentage=source.percentage,
                notes=source.notes,
                valid_from=valid_from,
                valid_to=source.valid_to,
            )
            _apply_price_overrides(copy, request.data)
            copy.save()
            _copy_or_replace_periods(source, copy, request.data.get('periods'))

        _record_tariff_event(
            request=request,
            action_type="tariff.duplicate",
            target_type="tariffs.Tariff",
            target=copy,
            target_id=str(copy.pk),
            target_display=copy.name,
            summary=f"Duplicated tariff {source.name} as {copy.name}.",
            metadata={"zev_id": str(copy.zev_id), "source_id": str(source.pk)},
        )
        return Response(
            TariffSerializer(copy, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='rename-series')
    def rename_series(self, request, pk=None):
        """Rename every version of this tariff at once.

        The name is what groups versions, so renaming a single version would
        silently fork the series and leave a hole in the original timeline.
        Renaming is therefore only offered for the series as a whole.
        """
        source = self.get_object()
        name = str(request.data.get('name') or '').strip()
        if not name:
            return Response({'name': ['A name is required.']}, status=status.HTTP_400_BAD_REQUEST)

        old_name = source.name
        if name == old_name:
            return Response(
                TariffSerializer(source, context={'request': request}).data,
                status=status.HTTP_200_OK,
            )

        versions = list(Tariff.objects.filter(zev_id=source.zev_id, name=old_name))
        clash = Tariff.objects.filter(zev_id=source.zev_id, name=name).exclude(
            pk__in=[version.pk for version in versions]
        )
        if clash.exists():
            return Response(
                {'name': [f'A tariff named "{name}" already exists in this ZEV.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # bulk_update bypasses full_clean() deliberately: renaming the whole
            # series preserves every invariant, but validating each row against
            # its not-yet-renamed siblings would report a false name clash.
            for version in versions:
                version.name = name
            Tariff.objects.bulk_update(versions, ['name'])

        _record_tariff_event(
            request=request,
            action_type="tariff.rename_series",
            target_type="tariffs.Tariff",
            target=source,
            target_id=str(source.pk),
            target_display=name,
            summary=f'Renamed tariff series "{old_name}" to "{name}".',
            changes={"name": {"before": old_name, "after": name}},
            metadata={"zev_id": str(source.zev_id), "versions_renamed": len(versions)},
        )
        source.refresh_from_db()
        return Response(TariffSerializer(source, context={'request': request}).data)

class TariffPeriodViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = TariffPeriodSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    zev_owner_filter = "tariff__zev__owner"
    participant_filter = None
    scope_parent_path = ("tariff", "zev")

    audit_action_category = AuditActionCategory.TARIFF
    audit_action_type = "tariff_period.update"
    audit_target_type = "tariffs.TariffPeriod"

    def get_audit_target_display(self, instance):
        return instance.period_type

    def get_audit_summary(self, instance):
        return f"Updated tariff period {instance.period_type} for tariff {instance.tariff.name}."

    def get_queryset(self):
        return self.scope_queryset(TariffPeriod.objects.all())

    def perform_create(self, serializer):
        period = super().perform_create(serializer)
        _record_tariff_event(
            request=self.request,
            action_type="tariff_period.create",
            target_type="tariffs.TariffPeriod",
            target=period,
            target_id=str(period.pk),
            target_display=period.period_type,
            summary=f"Created tariff period {period.period_type} for tariff {period.tariff.name}.",
            metadata={"tariff_id": str(period.tariff_id)},
        )

    def perform_destroy(self, instance):
        period_id = str(instance.pk)
        period_type = instance.period_type
        tariff_name = instance.tariff.name
        instance.delete()
        _record_tariff_event(
            request=self.request,
            action_type="tariff_period.delete",
            target_type="tariffs.TariffPeriod",
            target_id=period_id,
            target_display=period_type,
            summary=f"Deleted tariff period {period_type} for tariff {tariff_name}.",
        )
