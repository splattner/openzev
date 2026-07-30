from functools import partial

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev
from .models import Tariff, TariffPeriod
from zev.scoping import ZevScopedQuerySetMixin
from .serializers import TariffSerializer, TariffPeriodSerializer
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
