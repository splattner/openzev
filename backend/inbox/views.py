"""Participant inbox and manager outbox (SPEC-2026-11-participant-document-inbox §5.1)."""

import uuid

from django.db.models import Q
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from config.http import sanitize_filename
from invoices.models import ContractIssue
from notifications import producers as notification_producers
from zev.access import can_manage
from zev.models import Participant, Zev
from zev.scoping import ZevScopedQuerySetMixin, assert_zev_not_disabled

from .emails import queue_document_emails
from .models import DeliveredDocument, DocumentKind
from . import issuing
from .serializers import (
    DeliveredDocumentSerializer,
    DeliverContractSerializer,
    DeliveryResultSerializer,
    IssueSerializer,
    IssueYearSerializer,
    UploadDocumentSerializer,
)
from .services import deliver, discard_file, store_file
from .services import withdraw as withdraw_document

_TRUE = {"1", "true", "yes"}


def manageable_zev(request, zev_id) -> Zev:
    """The ZEV the caller may write to, else 404: the same answer for "no such ZEV" and
    "not yours", so ids cannot be probed. A disabled ZEV refuses everyone but an admin."""
    zev = Zev.objects.filter(pk=zev_id).first()
    if zev is None or not can_manage(request.user, zev):
        raise NotFound()
    assert_zev_not_disabled(request.user, zev)
    return zev


def delivery_response(
    delivery: issuing.Delivery, context, *, notify=False, created_status=status.HTTP_201_CREATED
):
    """The response of every write that delivers documents (spec §5.2).

    The participants are told here, once the documents are written: the one
    place every route that delivers passes through. The bell always rings; the
    email only when the operator asked for it (``notify``).
    """
    notification_producers.notify_documents_delivered(delivery.fresh)
    emailed, without_email = queue_document_emails(delivery.fresh) if notify else (0, 0)
    payload = {
        "batch_id": delivery.batch_id,
        "delivered": delivery.created,
        "without_account": delivery.without_account,
        "emailed": emailed,
        "without_email": without_email,
        "documents": delivery.documents,
    }
    return Response(
        DeliveryResultSerializer(payload, context=context).data,
        status=created_status if delivery.created else status.HTTP_200_OK,
    )


def _participants_of(zev, ids, field="participant_ids"):
    """The named participants, which must all belong to ``zev``."""
    rows = list(Participant.objects.filter(zev=zev, pk__in=ids).select_related("zev", "user"))
    if len(rows) != len(set(ids)):
        raise ValidationError({field: ["Every participant must belong to this ZEV."]})
    return rows


class DocumentViewSet(
    ZevScopedQuerySetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """What was delivered to the caller (a participant), or by the ZEVs they manage (the outbox).

    One access rule instead of per-resource exceptions: the inbox follows the
    participant row, has no end date, and survives a disabled ZEV (ADR 0045).
    """

    serializer_class = DeliveredDocumentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    zev_lookup = "zev"
    participant_path = "participant"
    participant_access_survives_end = True
    participant_survives_disabled_zev = True
    # A participant never sees a withdrawn document; grants and admins do.
    participant_visible = Q(withdrawn_at__isnull=True)

    def get_queryset(self):
        queryset = DeliveredDocument.objects.select_related(
            "zev", "participant__party", "invoice", "delivered_by"
        )
        return self.filter_documents(self.scope_queryset(queryset))

    def filter_documents(self, queryset):
        """Narrow-only filters; they never widen what ``scope_queryset`` allows."""
        if getattr(self, "action", None) != "list":
            return queryset
        params = self.request.query_params
        kinds = [value for raw in params.getlist("kind") for value in raw.split(",") if value]
        if kinds:
            unknown = [kind for kind in kinds if kind not in DocumentKind.values]
            if unknown:
                raise ValidationError({"kind": [f"Unknown kind(s): {', '.join(unknown)}."]})
            queryset = queryset.filter(kind__in=kinds)
        if participant_id := params.get("participant_id"):
            try:
                participant_uuid = uuid.UUID(str(participant_id))
            except ValueError:
                raise ValidationError({"participant_id": ["Must be a valid UUID."]}) from None
            queryset = queryset.filter(participant_id=participant_uuid)
        if year := params.get("year"):
            if not year.isdigit():
                raise ValidationError({"year": ["Must be a year."]})
            queryset = queryset.filter(
                Q(period_start__year=int(year)) | Q(period_start__isnull=True, delivered_at__year=int(year))
            )
        if params.get("include_superseded", "true").lower() not in _TRUE:
            queryset = queryset.filter(superseded_at__isnull=True)
        if params.get("include_withdrawn", "").lower() not in _TRUE:
            queryset = queryset.filter(withdrawn_at__isnull=True)
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, many=True),
            OpenApiParameter("participant_id", str),
            OpenApiParameter("zev_id", str),
            OpenApiParameter("year", int),
            OpenApiParameter("include_superseded", bool),
            OpenApiParameter("include_withdrawn", bool),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request={"multipart/form-data": UploadDocumentSerializer}, responses={201: DeliveryResultSerializer})
    def create(self, request, *args, **kwargs):
        """Deliver one operator document to the whole ZEV or to chosen participants.

        The file is stored once and every recipient's row points at it. Whoever
        joins the ZEV later gets nothing: the audience is fixed at delivery.
        """
        serializer = UploadDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        zev = manageable_zev(request, data["zev"])
        if data["audience"] == "selected":
            participants = _participants_of(zev, data["participant_ids"])
        else:
            participants = list(issuing.current_participants(zev))
            if not participants:
                raise ValidationError({"audience": ["This ZEV has no participants to deliver to."]})
        upload = data["file"]
        stored = store_file(zev, upload.read(), upload.name or "")
        batch_id = uuid.uuid4()
        try:
            with transaction.atomic():
                results = [
                    deliver(
                        participant=participant, kind=DocumentKind.OPERATOR, title=data["title"],
                        stored=stored, file_name=stored.file_name,
                        delivered_by=request.user, batch_id=batch_id,
                    )
                    for participant in participants
                ]
        except BaseException:
            discard_file(stored.name)
            raise
        delivery = issuing.delivery_of(batch_id, results)
        return delivery_response(delivery, self.get_serializer_context(), notify=data["notify"])

    @extend_schema(request=None, responses=DeliveredDocumentSerializer)
    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        """Take an operator document back from participants. The row and file are kept."""
        document = self.get_object()
        if not can_manage(request.user, document.zev):
            raise NotFound()
        assert_zev_not_disabled(request.user, document.zev)
        if document.kind != DocumentKind.OPERATOR:
            raise ValidationError({"detail": "Only operator documents can be withdrawn; corrections are issued again."})
        withdraw_document(document, request.user)
        return Response(self.get_serializer(document).data)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        document = self.get_object()
        response = FileResponse(
            document.open_file(),
            content_type=document.content_type,
            as_attachment=True,
            filename=sanitize_filename(document.file_name or f"{document.title}.pdf"),
        )
        # A delivered document is personal: never cached, never sniffed into something else.
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(request=DeliverContractSerializer, responses={201: DeliveryResultSerializer, 200: DeliveryResultSerializer})
    @action(detail=False, methods=["post"], url_path="deliver-contract")
    def deliver_contract(self, request):
        """Hand a stored contract version to its participant, by reference (no copy).

        Delivered explicitly: a ``ContractIssue`` is also minted when a manager
        previews the contract, which must not reach the participant. Only the
        participant's latest version can be delivered, so an outdated contract
        is not handed over by mistake.
        """
        serializer = DeliverContractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issues = ContractIssue.objects.select_related("zev", "participant__party", "participant__zev")
        if "participant" in serializer.validated_data:
            # The participant's latest issued version: what a manager sees as "the contract".
            issue = (
                issues.filter(participant_id=serializer.validated_data["participant"])
                .order_by("-version")
                .first()
            )
        else:
            issue = issues.filter(pk=serializer.validated_data["contract_issue"]).first()
        # The same answer for "no such issue", "no contract issued yet" and "not yours", so ids cannot be probed.
        if issue is None or issue.zev is None or not can_manage(request.user, issue.zev):
            raise NotFound()
        participant = issue.participant
        if participant is None:
            raise ValidationError({"contract_issue": ["This contract's participant no longer exists."]})
        assert_zev_not_disabled(request.user, issue.zev)
        latest = ContractIssue.objects.filter(participant=participant).order_by("-version").first()
        if latest is not None and latest.pk != issue.pk:
            return Response(
                {"detail": f"Version {issue.version} is outdated: the latest contract is version {latest.version}."},
                status=status.HTTP_409_CONFLICT,
            )
        batch_id = uuid.uuid4()
        document, created = deliver(
            participant=participant,
            kind=DocumentKind.CONTRACT,
            title=issue.document_number,
            document_number=issue.document_number,
            contract_issue=issue,
            delivered_by=request.user,
            batch_id=batch_id,
        )
        delivery = issuing.delivery_of(document.batch_id or batch_id, [(document, created)])
        return delivery_response(delivery, self.get_serializer_context(), notify=serializer.validated_data["notify"])


class IssueView(APIView):
    """Base of the three issue endpoints: authorise the ZEV, pick the audience, deliver."""

    permission_classes = [IsAuthenticated]
    serializer_class = IssueSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        zev = manageable_zev(request, data["zev"])
        delivery = self.issue(zev, data, request.user)
        return delivery_response(delivery, {"request": request}, notify=data["notify"])

    def audience(self, zev, data, eligible: set):
        """The named participants, or every eligible one; always limited to the eligible."""
        if "participant_ids" in data:
            participants = _participants_of(zev, data["participant_ids"])
            ineligible = [p for p in participants if p.pk not in eligible]
            if ineligible:
                raise ValidationError({"participant_ids": ["Some participants have nothing to report for this year."]})
        else:
            participants = list(
                Participant.objects.filter(zev=zev, pk__in=eligible).select_related("zev", "user")
            )
        if not participants:
            raise ValidationError({"detail": "No participant has anything to report for this year."})
        return participants


class IssueAnnualStatementView(IssueView):
    serializer_class = IssueYearSerializer

    @extend_schema(request=IssueYearSerializer, responses={201: DeliveryResultSerializer})
    def post(self, request):
        return super().post(request)

    def issue(self, zev, data, user):
        year = data["year"]
        participants = self.audience(zev, data, issuing.statement_participant_ids(zev, year))
        return issuing.issue_annual_statements(zev, participants, year, user)


class IssueFinancialSummaryView(IssueView):
    serializer_class = IssueYearSerializer

    @extend_schema(request=IssueYearSerializer, responses={201: DeliveryResultSerializer})
    def post(self, request):
        return super().post(request)

    def issue(self, zev, data, user):
        year = data["year"]
        participants = self.audience(zev, data, issuing.summary_participant_ids(zev, year))
        return issuing.issue_financial_summaries(zev, participants, year, user)


class IssueTariffOverviewView(IssueView):
    """The tariff overview reaches every current participant; it has no per-person content."""

    @extend_schema(request=IssueSerializer, responses={201: DeliveryResultSerializer})
    def post(self, request):
        return super().post(request)

    def issue(self, zev, data, user):
        participants = list(issuing.current_participants(zev))
        if "participant_ids" in data:
            participants = _participants_of(zev, data["participant_ids"])
        if not participants:
            raise ValidationError({"detail": "This ZEV has no participants to deliver to."})
        return issuing.issue_tariff_overview(zev, participants, user)
