"""One-off charges (#924): the owner records a cost once and says who bears it."""
from decimal import Decimal

from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasZevAccess
from audit.mixins import AuditedCreateDestroyMixin, AuditedUpdateMixin
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event
from zev.scoping import ZevScopedQuerySetMixin

from . import charges as charge_rules
from .models import Charge
from .serializers import ChargeSerializer

LOCKED_MESSAGE = (
    "An invoice of this period has already been approved, so its charges can no longer change. "
    "Correct the invoice instead."
)


class ChargeViewSet(AuditedCreateDestroyMixin, AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = ChargeSerializer
    permission_classes = [IsAuthenticated, HasZevAccess]
    zev_lookup = "zev"
    participant_path = None
    scope_parent_path = ("zev",)

    audit_action_category = AuditActionCategory.INVOICE
    audit_action_type = "charge.update"
    audit_target_type = "invoices.Charge"
    audit_target_label = "charge"

    def get_audit_target_display(self, instance):
        return instance.description

    def get_audit_create_summary(self, instance):
        return f"Created charge {instance.description} ({instance.amount_chf} CHF)."

    def get_audit_create_metadata(self, instance):
        return {"zev_id": str(instance.zev_id), "charge_date": instance.charge_date.isoformat()}

    def get_audit_destroy_metadata(self, instance):
        return {"zev_id": str(instance.zev_id), "charge_date": instance.charge_date.isoformat()}

    def get_queryset(self):
        return self.scope_queryset(Charge.objects.select_related("zev").prefetch_related("participants"))

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        for name, lookup in (("period_start", "charge_date__gte"), ("period_end", "charge_date__lte")):
            raw = params.get(name)
            if raw:
                parsed = parse_date(raw)
                if parsed is None:
                    raise ValidationError({name: ["Must be an ISO date (YYYY-MM-DD)."]})
                queryset = queryset.filter(**{lookup: parsed})
        participant = params.get("participant")
        if participant:
            queryset = queryset.filter(
                Q(allocation="all_participants") | Q(participants=participant)
            ).distinct()
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        charges = list(page if page is not None else queryset)
        serializer = self.get_serializer(
            charges, many=True,
            context={**self.get_serializer_context(), "locked_ids": charge_rules.locked_charge_ids(charges)},
        )
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    def _refuse_if_locked(self, request, charge, verb):
        invoice = charge_rules.charge_lock(charge)
        if invoice is None:
            return None
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.INVOICE,
            action_type=f"charge.{verb}_denied",
            summary=f"Denied {verb} of charge {charge.description}: invoice {invoice.invoice_number} is issued.",
            target_type="invoices.Charge",
            target=charge,
            target_id=str(charge.pk),
            target_display=charge.description,
            status=AuditEventStatus.DENIED,
            metadata={"zev_id": str(charge.zev_id), "invoice_number": invoice.invoice_number},
        )
        return Response(
            {"code": "charge_locked", "detail": LOCKED_MESSAGE, "invoice_number": invoice.invoice_number},
            status=status.HTTP_409_CONFLICT,
        )

    def update(self, request, *args, **kwargs):
        charge = self.get_object()
        self.assert_target_not_disabled(charge)
        return self._refuse_if_locked(request, charge, "update") or super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        charge = self.get_object()
        self.assert_target_not_disabled(charge)
        return self._refuse_if_locked(request, charge, "delete") or super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """Who would pay what for a charge as entered, without saving it.

        Takes the create payload and answers with the exact split the invoice
        engine will bill. A date an issued invoice already covers is refused
        like a create would be.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self.assert_within_scope(data)
        zev = data["zev"]
        bearers = charge_rules.bearers_for(
            zev, data["charge_date"], data.get("allocation", "all_participants"), data.get("participants", []),
        )
        shares = charge_rules.split_charge(data["amount_chf"], data.get("split_key", "equal"), bearers)
        billed = sum(shares.values(), Decimal("0"))
        return Response({
            "bearers": [
                {"participant": str(p.pk), "name": p.full_name, "share_chf": str(shares[p.pk])}
                for p in bearers if p.pk in shares
            ],
            "total_billed_chf": str(billed),
            "unrecovered_chf": str(data["amount_chf"] - billed),
        })
