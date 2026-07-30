from functools import partial

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev
from .models import Tariff, TariffPeriod
from zev.scoping import ZevScopedQuerySetMixin
from .serializers import TariffSerializer, TariffPeriodSerializer
from .series import active_version, find_gaps, plan_new_version, series_key, sort_versions
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedUpdateMixin
from audit.services import record_audit_event


# Every audit event in this module is a tariff event; bind the category once.
_record_tariff_event = partial(record_audit_event, action_category=AuditActionCategory.TARIFF)


def _normalise_validation_errors(exc) -> dict:
    """Flatten a DRF or Django ValidationError into ``{field: [messages]}``.

    The two exception types expose their contents differently, and nested
    serializer errors arrive as lists of dicts; callers want one predictable
    shape they can render.
    """
    if isinstance(exc, DjangoValidationError):
        return {
            field: [str(message) for message in messages]
            for field, messages in (
                exc.message_dict if hasattr(exc, 'message_dict')
                else {'non_field_errors': exc.messages}
            ).items()
        }

    detail = exc.detail
    if not isinstance(detail, dict):
        return {'non_field_errors': [str(item) for item in (detail if isinstance(detail, list) else [detail])]}
    return {
        field: [str(message) for message in (messages if isinstance(messages, list) else [messages])]
        for field, messages in detail.items()
    }


def _describe_failure(failure: dict) -> str:
    fields = '; '.join(
        f"{field}: {' '.join(messages)}" for field, messages in failure['errors'].items()
    )
    label = f'"{failure["name"]}"' if failure['name'] else 'unnamed'
    return f'#{failure["position"]} {label} — {fields}'


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


class _TariffImportFailed(Exception):
    """Raised to roll the import back once every entry has been checked."""

    def __init__(self, failures: list[dict], *, attempted: int):
        self.failures = failures
        self.attempted = attempted
        details = ' | '.join(_describe_failure(failure) for failure in failures)
        self.summary = (
            f'{len(failures)} of {attempted} tariffs could not be imported, '
            f'so nothing was saved: {details}'
        )
        super().__init__(self.summary)


class TariffViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = TariffSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    zev_owner_filter = "zev__owner"
    participant_filter = None

    audit_action_category = AuditActionCategory.TARIFF
    audit_action_type = "tariff.update"
    audit_target_type = "tariffs.Tariff"
    audit_target_label = "tariff"

    def get_audit_target_display(self, instance):
        return instance.name

    def get_queryset(self):
        return self.scope_queryset(Tariff.objects.all())

    def perform_create(self, serializer):
        tariff = serializer.save()
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

    def _get_accessible_zev(self, zev_id):
        user = self.request.user
        if user.is_admin:
            return Zev.objects.filter(id=zev_id).first()
        return Zev.objects.filter(id=zev_id, owner=user).first()

    def _serialize_tariff_preset(self, tariff):
        return {
            'name': tariff.name,
            'category': tariff.category,
            'billing_mode': tariff.billing_mode,
            'energy_type': tariff.energy_type,
            'fixed_price_chf': str(tariff.fixed_price_chf) if tariff.fixed_price_chf is not None else None,
            'percentage': str(tariff.percentage) if tariff.percentage is not None else None,
            'valid_from': tariff.valid_from.isoformat(),
            'valid_to': tariff.valid_to.isoformat() if tariff.valid_to else None,
            'notes': tariff.notes,
            'periods': [
                {
                    'period_type': period.period_type,
                    'price_chf_per_kwh': str(period.price_chf_per_kwh),
                    'time_from': period.time_from.isoformat() if period.time_from else None,
                    'time_to': period.time_to.isoformat() if period.time_to else None,
                    'weekdays': period.weekdays,
                }
                for period in tariff.periods.all()
            ],
        }

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

    @action(detail=False, methods=['get'], url_path='export')
    def export_tariffs(self, request):
        """Export all tariffs for a ZEV as JSON."""
        zev_id = request.query_params.get('zev_id')
        if not zev_id:
            _record_tariff_event(
                request=request,
                action_type="tariff.export",
                target_type="zev.Zev",
                summary="Tariff export failed: missing zev_id.",
                status=AuditEventStatus.FAILED,
            )
            return Response({'error': 'zev_id query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        zev = self._get_accessible_zev(zev_id)
        if not zev:
            _record_tariff_event(
                request=request,
                action_type="tariff.export",
                target_type="zev.Zev",
                target_id=str(zev_id),
                target_display=str(zev_id),
                summary="Tariff export failed: ZEV not accessible.",
                status=AuditEventStatus.FAILED,
            )
            return Response({'error': 'ZEV not found or not accessible.'}, status=status.HTTP_404_NOT_FOUND)

        tariffs = self.get_queryset().filter(zev_id=zev_id)
        if not tariffs.exists():
            return Response({'error': 'No tariffs found for this ZEV.'}, status=status.HTTP_404_NOT_FOUND)

        _record_tariff_event(
            request=request,
            action_type="tariff.export",
            target_type="zev.Zev",
            target=zev,
            target_id=str(zev.id),
            target_display=zev.name,
            summary=f"Exported {tariffs.count()} tariffs for ZEV {zev.name}.",
            metadata={"tariff_count": tariffs.count()},
        )

        return Response([self._serialize_tariff_preset(tariff) for tariff in tariffs])

    @action(detail=False, methods=['post'], url_path='import')
    def import_tariffs(self, request):
        """Import tariffs and periods from JSON data."""
        zev_id = request.data.get('zev_id')
        tariffs_data = request.data.get('tariffs', [])

        if not zev_id:
            _record_tariff_event(
                request=request,
                action_type="tariff.import",
                target_type="zev.Zev",
                summary="Tariff import failed: missing zev_id.",
                status=AuditEventStatus.FAILED,
            )
            return Response({'error': 'zev_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not tariffs_data:
            _record_tariff_event(
                request=request,
                action_type="tariff.import",
                target_type="zev.Zev",
                target_id=str(zev_id),
                target_display=str(zev_id),
                summary="Tariff import failed: missing tariffs payload.",
                status=AuditEventStatus.FAILED,
            )
            return Response({'error': 'tariffs array is required.'}, status=status.HTTP_400_BAD_REQUEST)

        zev = self._get_accessible_zev(zev_id)
        if not zev:
            _record_tariff_event(
                request=request,
                action_type="tariff.import",
                target_type="zev.Zev",
                target_id=str(zev_id),
                target_display=str(zev_id),
                summary="Tariff import failed: ZEV not accessible.",
                status=AuditEventStatus.FAILED,
            )
            return Response({'error': 'ZEV not found or not accessible.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            with transaction.atomic():
                created_tariffs, failures = self._import_tariff_batch(zev, tariffs_data)

                if failures:
                    # Every entry is reported in one response rather than only the
                    # first, so a preset with several problems takes one round trip
                    # to fix instead of one per problem. The import stays
                    # all-or-nothing: a partially applied tariff set would price
                    # invoices against an incomplete structure, which is worse than
                    # importing nothing.
                    raise _TariffImportFailed(failures, attempted=len(tariffs_data))

                _record_tariff_event(
                    request=request,
                    action_type="tariff.import",
                    target_type="zev.Zev",
                    target=zev,
                    target_id=str(zev.id),
                    target_display=zev.name,
                    summary=f"Imported {len(created_tariffs)} tariffs for ZEV {zev.name}.",
                    metadata={"created": len(created_tariffs)},
                )

                return Response(
                    {'created': len(created_tariffs), 'tariffs': created_tariffs},
                    status=status.HTTP_201_CREATED
                )

        except _TariffImportFailed as failure:
            _record_tariff_event(
                request=request,
                action_type="tariff.import",
                target_type="zev.Zev",
                target=zev,
                target_id=str(zev.id),
                target_display=zev.name,
                summary=f"Tariff import failed for ZEV {zev.name}: {failure.summary}",
                status=AuditEventStatus.FAILED,
                metadata={"attempted": failure.attempted, "rejected": len(failure.failures)},
            )
            # ``detail`` carries the human-readable summary; ``errors`` keeps the
            # per-entry breakdown for API consumers.
            return Response(
                {'detail': failure.summary, 'errors': failure.failures},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            _record_tariff_event(
                request=request,
                action_type="tariff.import",
                target_type="zev.Zev",
                target=zev,
                target_id=str(zev.id),
                target_display=zev.name,
                summary=f"Tariff import failed for ZEV {zev.name}.",
                status=AuditEventStatus.FAILED,
                metadata={"error": str(e)},
            )
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _import_tariff_batch(self, zev, tariffs_data):
        """Create every tariff in ``tariffs_data``, collecting failures as it goes.

        Each entry runs in its own savepoint so one rejection cannot poison the
        surrounding transaction, letting the remaining entries still be checked.
        The caller decides what to do with the failures.
        """
        created_tariffs = []
        failures = []

        for index, raw in enumerate(tariffs_data):
            payload = dict(raw)
            periods_data = payload.pop('periods', [])
            for ignored in ('id', 'zev', 'created_at', 'updated_at'):
                payload.pop(ignored, None)
            payload['zev'] = str(zev.id)

            try:
                with transaction.atomic():  # savepoint
                    tariff_serializer = TariffSerializer(data=payload)
                    tariff_serializer.is_valid(raise_exception=True)
                    # The overlap guard lives in the model's full_clean(), which
                    # the serializer only reaches on save() — so this can raise
                    # even though is_valid() passed.
                    tariff = tariff_serializer.save()

                    for period_data in periods_data:
                        period_payload = dict(period_data)
                        period_payload.pop('id', None)
                        period_payload['tariff'] = str(tariff.id)
                        period_serializer = TariffPeriodSerializer(data=period_payload)
                        period_serializer.is_valid(raise_exception=True)
                        period_serializer.save()
            except (DRFValidationError, DjangoValidationError) as exc:
                failures.append({
                    'position': index + 1,
                    'name': str(raw.get('name') or ''),
                    'errors': _normalise_validation_errors(exc),
                })
                continue

            created_tariffs.append(tariff_serializer.data)

        return created_tariffs, failures


class TariffPeriodViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = TariffPeriodSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    zev_owner_filter = "tariff__zev__owner"
    participant_filter = None

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
        period = serializer.save()
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
