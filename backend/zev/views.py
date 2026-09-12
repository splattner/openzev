import logging
import tempfile

from django.conf import settings as django_settings
from django.db.models import Count, Max, Min
from django.http import FileResponse, HttpResponse
from django.utils import timezone as dj_timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from accounts.permissions import IsAdmin
from accounts.throttling import ApiKeyRateThrottle, TransferArchiveThrottle
from accounts.models import User, UserRole
from allocation.validity import period_window
from metering.models import MeterReading
from . import onboarding
from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment
from .scoping import ZevScopedQuerySetMixin
from .serializers import (
    GridOperatorListSerializer,
    GridOperatorSuggestionSerializer,
    ZevSerializer,
    ZevDetailSerializer,
    ZevCreateWithOwnerSerializer,
    ParticipantSerializer,
    MeteringPointSerializer,
    MeteringPointReadingsDeleteSerializer,
    MeteringPointAssignmentSerializer,
)
from .permissions import (
    BaseZevScopedPermission,
    MeteringPointAssignmentPermission,
    MeteringPointPermission,
    ZevManagementPermission,
)
from .grid_operators import load_grid_operators, grid_operators_for_postal_code
from .services import (
    create_zev_for_existing_owner,
    get_participant_onboarding_link,
    send_participant_onboarding_link,
)
from .transfer import (
    SECTION_DEPENDENCIES,
    SECTIONS,
    ArchiveError,
    ImportFailed,
    archive_filename,
    build_archive,
    import_archive,
    inspect_archive,
)
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedCreateDestroyMixin, AuditedUpdateMixin
from audit.services import record_audit_event

logger = logging.getLogger(__name__)


class ZevViewSet(ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ZevManagementPermission]
    zev_owner_filter = "owner"
    participant_filter = "participants__user"
    participant_distinct = True

    def get_permissions(self):
        # self_setup is a POST by non-admins — skip ZevManagementPermission
        if self.action == "self_setup":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        return self.scope_queryset(Zev.objects.all())

    def get_serializer_class(self):
        if self.action == "create_with_owner":
            return ZevCreateWithOwnerSerializer
        if self.action == "retrieve":
            return ZevDetailSerializer
        return ZevSerializer

    def create(self, request, *args, **kwargs):
        if not request.user.is_admin:
            return Response({"detail": "Only admins can create a new ZEV."}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="create-with-owner")
    def create_with_owner(self, request):
        if not request.user.is_admin:
            return Response({"detail": "Only admins can create a new ZEV."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="self-setup")
    def self_setup(self, request):
        """Create a ZEV for the authenticated self-registered zev_owner."""
        user = request.user
        if not user.is_zev_owner:
            return Response({"detail": "Only ZEV owners can use this endpoint."}, status=status.HTTP_403_FORBIDDEN)
        if Zev.objects.filter(owner=user).exists():
            return Response({"detail": "You already have a ZEV."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ZevSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        zev_data = {k: v for k, v in serializer.validated_data.items() if k != 'owner'}
        result = create_zev_for_existing_owner(owner_user=user, zev_data=zev_data)
        return Response(result, status=status.HTTP_201_CREATED)

    # ── Transfer: whole-ZEV export and import ──────────────────────────────
    #
    # Who may do what follows the rules already in force rather than inventing
    # new ones. Export is a detail action, so ``get_object()`` scopes it: an
    # admin exports any ZEV, an owner only their own. Import is a POST, which
    # ``ZevManagementPermission`` restricts to admins — the same rule as
    # ``create()``, because importing an archive *is* creating a ZEV and a ZEV
    # owner going through this endpoint would otherwise sidestep ``self_setup``
    # and its "you already have a ZEV" guard.

    @action(detail=False, methods=["get"], url_path="transfer-sections")
    def transfer_sections(self, request):
        """The section list and its dependency graph.

        Served rather than hard-coded in the frontend so the rule that
        assignments need participants lives in exactly one place.
        """
        return Response(
            {
                "sections": [
                    {"name": name, "requires": list(SECTION_DEPENDENCIES[name])}
                    for name in SECTIONS
                ]
            }
        )

    def _record_transfer_audit(self, request, **kwargs):
        """Record a transfer audit event without failing the operation.

        On import the ZEV is already committed by the time this runs, and on
        export the archive is already built — an audit failure must not turn a
        completed transfer into an error (or, worse, into a duplicate import
        when the client retries what looked like a failure).
        """
        try:
            record_audit_event(request=request, **kwargs)
        except Exception:  # noqa: BLE001 - the audit is a log line, not the operation
            logger.exception("Failed to record transfer audit event")

    @action(detail=True, methods=["get"], url_path="export")
    def export_archive(self, request, pk=None):
        """Download the ZEV as a transfer archive."""
        zev = self.get_object()
        sections = self._parse_sections(request.query_params.getlist("sections"))

        # Spooled: a structure-only export never touches the disk, while a
        # community with years of readings rolls over instead of being held in
        # memory. Building the archive off the request path is a matter of
        # calling ``build_archive`` from a task and handing back an artefact
        # URL — the builder streams either way.
        buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            manifest = build_archive(
                zev,
                sections,
                buffer,
                instance_name=getattr(django_settings, "INSTANCE_NAME", ""),
            )
        except ValueError as exc:
            buffer.close()
            self._record_transfer_audit(
                request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type="zev.export",
                target_type="zev.Zev",
                target=zev,
                target_id=str(zev.id),
                target_display=zev.name,
                zev=zev,
                summary=f"ZEV export failed for {zev.name}: {exc}",
                status=AuditEventStatus.FAILED,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        buffer.seek(0)
        self._record_transfer_audit(
            request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="zev.export",
            target_type="zev.Zev",
            target=zev,
            target_id=str(zev.id),
            target_display=zev.name,
            zev=zev,
            # An export is a personal-data extract — names, addresses, emails
            # and consumption profiles in one file — so the event records
            # exactly which sections left the instance.
            summary=f"Exported ZEV {zev.name} ({', '.join(manifest['sections'])}).",
            metadata={"sections": manifest["sections"], "counts": manifest["counts"]},
        )

        response = FileResponse(
            buffer,
            content_type="application/zip",
            as_attachment=True,
            filename=archive_filename(zev, today=dj_timezone.localdate()),
        )
        return response

    @action(
        detail=False,
        methods=["post"],
        url_path="inspect-archive",
        parser_classes=[MultiPartParser, FormParser],
        throttle_classes=[ApiKeyRateThrottle, TransferArchiveThrottle],
    )
    def inspect_archive_action(self, request):
        """Read an archive's manifest without importing anything."""
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "A ZIP archive is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            manifest = inspect_archive(upload)
        except (ArchiveError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(manifest)

    @action(
        detail=False,
        methods=["post"],
        url_path="import-archive",
        parser_classes=[MultiPartParser, FormParser],
        throttle_classes=[ApiKeyRateThrottle, TransferArchiveThrottle],
    )
    def import_archive_action(self, request):
        """Create a new ZEV from an uploaded transfer archive.

        Never touches an existing ZEV: the import is not idempotent, so running
        it twice yields two communities rather than merging into one.
        """
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "A ZIP archive is required."}, status=status.HTTP_400_BAD_REQUEST)

        sections = self._parse_sections(request.data.getlist("sections"))
        name_override = (request.data.get("name") or "").strip()

        def _failed(summary, payload, http_status=status.HTTP_400_BAD_REQUEST):
            self._record_transfer_audit(
                request,
                action_category=AuditActionCategory.IMPORT,
                action_type="zev.import",
                target_type="zev.Zev",
                target_display=name_override or upload.name,
                summary=summary,
                status=AuditEventStatus.FAILED,
                metadata={"filename": upload.name},
            )
            return Response(payload, status=http_status)

        try:
            result = import_archive(
                upload,
                owner=request.user,
                sections=sections,
                name_override=name_override,
            )
        except ImportFailed as failure:
            return _failed(
                f"ZEV import failed: {failure.summary}",
                {
                    "detail": failure.summary,
                    "errors": failure.errors,
                    "total_errors": failure.total_errors,
                },
            )
        except (ArchiveError, ValueError) as exc:
            return _failed(f"ZEV import failed: {exc}", {"detail": str(exc)})

        self._record_transfer_audit(
            request,
            action_category=AuditActionCategory.IMPORT,
            action_type="zev.import",
            target_type="zev.Zev",
            target_id=result["zev_id"],
            target_display=result["zev_name"],
            zev=Zev.objects.filter(pk=result["zev_id"]).first(),
            summary=f"Imported ZEV {result['zev_name']} ({', '.join(result['sections'])}).",
            metadata={
                "filename": upload.name,
                "sections": result["sections"],
                "counts": result["counts"],
            },
        )
        return Response(result, status=status.HTTP_201_CREATED)

    @staticmethod
    def _parse_sections(raw):
        """Repeated form fields and/or comma-separated values -> a list, or None for all."""
        if raw is None:
            return None
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        names = []
        for item in raw:
            if item is None:
                continue
            names.extend(part.strip() for part in str(item).split(","))
        names = [name for name in names if name]
        return names or None


class ParticipantViewSet(AuditedCreateDestroyMixin, AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = ParticipantSerializer
    permission_classes = [IsAuthenticated, BaseZevScopedPermission]
    zev_owner_filter = "zev__owner"
    participant_filter = "user"
    scope_parent_path = ("zev",)

    audit_action_category = AuditActionCategory.PARTICIPANT
    audit_action_type = "participant.update"
    audit_target_type = "zev.Participant"
    audit_target_label = "participant"

    def get_audit_target_display(self, instance):
        return instance.full_name

    def get_queryset(self):
        return self.scope_queryset(
            Participant.objects.prefetch_related("metering_point_assignments", "onboarding_tokens")
        )

    def get_audit_create_summary(self, instance):
        return f"Created participant {instance.full_name}."

    def get_audit_destroy_summary(self, instance):
        return f"Deleted participant {instance.full_name}."

    def get_audit_create_metadata(self, instance):
        return {"zev_id": str(instance.zev_id)}

    def get_audit_destroy_metadata(self, instance):
        return {"zev_id": str(instance.zev_id)}

    def _contract_pdf_access_denied(self, request, participant):
        """True when the caller may not reach this participant's contract."""
        if request.user.is_admin or request.user.is_zev_owner:
            return False
        return participant.user != request.user

    @staticmethod
    def _stream_contract_issue(participant, issue):
        filename = f"contract_{participant.last_name}_{participant.first_name}_v{issue.version}.pdf"
        response = HttpResponse(issue.pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def _audit_contract_download(self, request, participant, issue):
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="contract.download",
            target_type="zev.Participant",
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Downloaded participation contract v{issue.version} ({issue.document_number}).",
            metadata={
                "zev_id": str(participant.zev_id),
                "version": issue.version,
                "document_number": issue.document_number,
                "reused_snapshot": True,
            },
        )

    # Issuance is a POST, not a GET, because it writes: it mints a per-ZEV
    # document number under a row lock, creates a ContractIssue and attributes
    # a contract.issue audit event to the caller. A GET that does that is
    # forgeable — SameSite=Lax still sends the auth cookies on a cross-site
    # top-level navigation, and CSRF enforcement deliberately exempts safe
    # methods (see CookieJWTAuthentication.authenticate), so a link on an
    # external page clicked by a logged-in owner would issue a contract in
    # their name. Keeping the write on POST puts it back inside CSRF
    # protection; GET stays a true read of what was already issued.
    @action(detail=True, methods=["get", "post"], url_path="contract-pdf",
            permission_classes=[IsAuthenticated])
    def contract_pdf(self, request, pk=None):
        """Read (GET) or issue (POST) the participation-contract PDF.

        ``GET`` streams the latest existing snapshot and never mints one; it
        404s when the contract has not been issued yet. ``POST`` issues
        version 1 on first use, reuses the frozen snapshot when nothing
        changed, and mints a new numbered version when the data or template
        did.
        """
        participant = self.get_object()
        if self._contract_pdf_access_denied(request, participant):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        if request.method == "GET":
            from invoices.models import ContractIssue

            issue = (
                ContractIssue.objects.filter(participant=participant)
                .order_by("-version")
                .first()
            )
            if issue is None:
                return Response(
                    {"detail": "No contract has been issued for this participant yet."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            self._audit_contract_download(request, participant, issue)
            return self._stream_contract_issue(participant, issue)

        from invoices.contract_pdf import issue_contract_pdf

        issue, created = issue_contract_pdf(participant, issued_by=request.user)
        if created:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="contract.issue",
                target_type="zev.Participant",
                target_id=str(participant.pk),
                target_display=participant.full_name,
                summary=f"Issued participation contract v{issue.version} ({issue.document_number}).",
                metadata={
                    "zev_id": str(participant.zev_id),
                    "version": issue.version,
                    "document_number": issue.document_number,
                },
            )
        else:
            self._audit_contract_download(request, participant, issue)
        return self._stream_contract_issue(participant, issue)

    def _deny_non_admin(self, request, pk, *, action_suffix: str, summary: str, detail: str):
        """Audit and reject a non-admin call to an admin-only account action."""
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type=f"participant.{action_suffix}",
            target_type="zev.Participant",
            target_id=str(pk or ""),
            target_display=str(pk or ""),
            summary=summary,
            status=AuditEventStatus.DENIED,
        )
        return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)

    @action(detail=True, methods=["post"], url_path="link-account")
    def link_account(self, request, pk=None):
        if not request.user.is_admin:
            return self._deny_non_admin(
                request, pk,
                action_suffix="link_account",
                summary="Denied participant account link by non-admin.",
                detail="Only admins can link accounts.",
            )

        participant = self.get_object()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"detail": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            account = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if account.role not in (UserRole.PARTICIPANT, UserRole.GUEST):
            return Response({"detail": "Only participant or guest accounts can be linked."}, status=status.HTTP_400_BAD_REQUEST)

        already_linked_elsewhere = Participant.objects.filter(user=account).exclude(pk=participant.pk).exists()
        if already_linked_elsewhere:
            return Response({"detail": "This account is already linked to another participant."}, status=status.HTTP_400_BAD_REQUEST)

        participant.user = account
        participant.save(update_fields=["user", "updated_at"])
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.link_account",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Linked account {account.username} to participant {participant.full_name}.",
            changes={"user": {"before": None, "after": str(account.id)}},
        )
        serializer = self.get_serializer(participant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unlink-account")
    def unlink_account(self, request, pk=None):
        if not request.user.is_admin:
            return self._deny_non_admin(
                request, pk,
                action_suffix="unlink_account",
                summary="Denied participant account unlink by non-admin.",
                detail="Only admins can unlink accounts.",
            )

        participant = self.get_object()
        if participant.user is None:
            return Response({"detail": "Participant has no linked account."}, status=status.HTTP_400_BAD_REQUEST)

        if participant.zev.owner_id == participant.user_id:
            return Response({"detail": "Cannot unlink the owner account from the owner participant."}, status=status.HTTP_400_BAD_REQUEST)

        unlinked_account = participant.user
        unlinked_account.role = UserRole.GUEST
        unlinked_account.save(update_fields=["role"])

        participant.user = None
        participant.save(update_fields=["user", "updated_at"])
        # Detaching the account must also kill any outstanding onboarding
        # link — otherwise whoever holds it can simply click it again and be
        # handed a freshly recreated account, and this action would not have
        # cut anything.
        onboarding.revoke_active_for_participant(participant)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.unlink_account",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Unlinked account {unlinked_account.username} from participant {participant.full_name}.",
            changes={"user": {"before": str(unlinked_account.id), "after": None}},
        )
        serializer = self.get_serializer(participant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="onboarding-link")
    def onboarding_link(self, request, pk=None):
        """Ensure an account and onboarding link exist, without emailing it.

        Backs the "copy onboarding link" action on the participants page, and
        the admin console's account-linking action, which never required an
        email address either — an operator handing the link over in person or
        by some other channel needs no address on file.
        """
        participant = self.get_object()
        onboarding_url = get_participant_onboarding_link(participant)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.onboarding_link_created",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Created an onboarding link for participant {participant.full_name}.",
        )
        serializer = self.get_serializer(participant)
        return Response({"onboarding_url": onboarding_url, "participant": serializer.data})

    @action(detail=True, methods=["post"], url_path="send-onboarding-link")
    def send_onboarding_link(self, request, pk=None):
        participant = self.get_object()
        try:
            onboarding_url = send_participant_onboarding_link(participant, request.user)
        except ValueError as exc:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="participant.send_onboarding_link",
                target_type="zev.Participant",
                target=participant,
                target_id=str(participant.pk),
                target_display=participant.full_name,
                summary=f"Failed onboarding email for participant {participant.full_name}.",
                status=AuditEventStatus.FAILED,
                metadata={"error": str(exc)},
            )
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.send_onboarding_link",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Sent onboarding link to {participant.email}.",
        )
        return Response(
            {
                "detail": f"Onboarding email sent to {participant.email}.",
                "onboarding_url": onboarding_url,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="revoke-onboarding-link")
    def revoke_onboarding_link(self, request, pk=None):
        """Kill the active link without touching the linked account.

        Distinct from ``unlink-account``: a participant may already have set
        their own password and still want an old, possibly leaked link
        invalidated.
        """
        participant = self.get_object()
        onboarding.revoke_active_for_participant(participant)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.revoke_onboarding_link",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Revoked the onboarding link for participant {participant.full_name}.",
        )
        serializer = self.get_serializer(participant)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MeteringPointViewSet(AuditedCreateDestroyMixin, AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = MeteringPointSerializer
    permission_classes = [IsAuthenticated, MeteringPointPermission]
    zev_owner_filter = "zev__owner"
    participant_filter = "assignments__participant__user"
    participant_distinct = True
    scope_parent_path = ("zev",)

    audit_action_category = AuditActionCategory.METERING
    audit_action_type = "metering_point.update"
    audit_target_type = "zev.MeteringPoint"
    audit_target_label = "metering point"

    def get_audit_target_display(self, instance):
        return instance.meter_id

    def get_queryset(self):
        # Annotate the cascade a delete would take with it (readings +
        # assignment history), so the serializer can surface it without an
        # N+1 query per metering point. `distinct=True` on each Count keeps
        # the two independent reverse relations (readings, assignments) from
        # inflating each other via the join; Min/Max are unaffected by that
        # same join fan-out since duplicate rows don't change a min or max.
        # Annotating drops the model's Meta.ordering (Django does not carry
        # it into a GROUP BY query), so it has to be requested explicitly
        # again or list responses come back in undefined order.
        return self.scope_queryset(MeteringPoint.objects.select_related("zev")).annotate(
            reading_count=Count("readings", distinct=True),
            assignment_count=Count("assignments", distinct=True),
            first_reading_at=Min("readings__timestamp"),
            last_reading_at=Max("readings__timestamp"),
        ).order_by("meter_id")

    def get_audit_create_summary(self, instance):
        return f"Created metering point {instance.meter_id}."

    def get_audit_destroy_summary(self, instance):
        return f"Deleted metering point {instance.meter_id}."

    def get_audit_create_metadata(self, instance):
        return {"zev_id": str(instance.zev_id), "meter_type": instance.meter_type}

    def get_audit_destroy_metadata(self, instance):
        return {"zev_id": str(instance.zev_id)}

    @action(
        detail=True,
        methods=["post"],
        url_path="delete-readings",
        permission_classes=[IsAuthenticated, IsAdmin],
    )
    def delete_readings(self, request, pk=None):
        metering_point = self.get_object()
        serializer = MeteringPointReadingsDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_all = serializer.validated_data["delete_all"]
        date_from = serializer.validated_data.get("date_from")
        date_to = serializer.validated_data.get("date_to")

        readings_qs = MeterReading.objects.filter(metering_point=metering_point)

        if not delete_all:
            start_dt, end_dt_exclusive = period_window(date_from, date_to)
            readings_qs = readings_qs.filter(timestamp__gte=start_dt, timestamp__lt=end_dt_exclusive)

        deleted_count = readings_qs.count()
        readings_qs.delete()

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.METERING,
            action_type="metering_point.delete_readings",
            target_type="zev.MeteringPoint",
            target=metering_point,
            target_id=str(metering_point.pk),
            target_display=metering_point.meter_id,
            summary=f"Deleted {deleted_count} meter readings for {metering_point.meter_id}.",
            metadata={
                "delete_all": delete_all,
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
            },
        )

        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)


class MeteringPointAssignmentViewSet(AuditedCreateDestroyMixin, AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = MeteringPointAssignmentSerializer
    permission_classes = [IsAuthenticated, MeteringPointAssignmentPermission]
    zev_owner_filter = "metering_point__zev__owner"
    participant_filter = "participant__user"
    scope_parent_path = ("metering_point", "zev")

    audit_action_category = AuditActionCategory.METERING
    audit_action_type = "metering_assignment.update"
    audit_target_type = "zev.MeteringPointAssignment"

    def get_audit_target_display(self, instance):
        return str(instance.pk)

    def get_audit_summary(self, instance):
        return f"Updated metering point assignment for {instance.metering_point.meter_id}."

    def get_queryset(self):
        qs = self.scope_queryset(
            MeteringPointAssignment.objects.select_related(
                "metering_point",
                "metering_point__zev",
                "participant",
            )
        )

        # Optional filter: ?metering_point=<uuid>
        mp_id = self.request.query_params.get("metering_point")
        if mp_id:
            qs = qs.filter(metering_point_id=mp_id)

        return qs

    def get_audit_create_summary(self, instance):
        return f"Created metering point assignment for {instance.metering_point.meter_id}."

    def get_audit_destroy_summary(self, instance):
        return f"Deleted metering point assignment for {instance.metering_point.meter_id}."

    def get_audit_create_metadata(self, instance):
        return {
            "metering_point_id": str(instance.metering_point_id),
            "participant_id": str(instance.participant_id),
        }

    def get_audit_destroy_metadata(self, instance):
        return {"participant_id": str(instance.participant_id)}


class GridOperatorListView(APIView):
    """The official ElCom list of Swiss grid operators, for the ZEV form picker.

    A static reference list served whole rather than paginated: the picker
    filters client-side, and 553 entries is ~82 KB. Read from a checked-in
    fixture, so creating a ZEV never depends on an external SPARQL endpoint
    being reachable — see ``zev.grid_operators`` and
    ``manage.py fetch_grid_operators``.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=GridOperatorListSerializer)
    def get(self, request):
        return Response(load_grid_operators())


class GridOperatorSuggestionView(APIView):
    """Operator suggestion(s) for a postal code, from the same checked-in fixture.

    A separate, lightweight endpoint rather than a query param on the list
    above: the picker needs the whole 553-entry list once and caches it
    forever, while this is looked up fresh whenever the postal-code field
    changes and returns only what matched — usually zero or one entry.

    An empty or unrecognised postal code returns ``{"operators": []}``, not
    an error — the caller falls back to the free-text picker, which is the
    correct outcome for a postal code the register does not cover.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=GridOperatorSuggestionSerializer)
    def get(self, request):
        postal_code = request.query_params.get("postal_code", "")
        operators = grid_operators_for_postal_code(postal_code)
        return Response(GridOperatorSuggestionSerializer({"operators": operators}).data)
