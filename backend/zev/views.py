import logging
import tempfile
from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from django.conf import settings as django_settings
from django.http import FileResponse, HttpResponse
from django.utils import timezone as dj_timezone
from django.utils.crypto import get_random_string
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsAdmin
from accounts.models import User, UserRole
from accounts.serializers import UserSerializer
from metering.models import MeterReading
from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment
from .scoping import ZevScopedQuerySetMixin
from .serializers import (
    ZevSerializer,
    ZevDetailSerializer,
    ZevCreateWithOwnerSerializer,
    ParticipantSerializer,
    MeteringPointSerializer,
    MeteringPointAssignmentSerializer,
)
from .permissions import (
    BaseZevScopedPermission,
    MeteringPointAssignmentPermission,
    MeteringPointPermission,
    ZevManagementPermission,
)
from .services import send_participant_invitation, create_zev_for_existing_owner
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
from audit.mixins import AuditedUpdateMixin
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


class ParticipantViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
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
        return self.scope_queryset(Participant.objects.prefetch_related("metering_point_assignments"))

    def perform_create(self, serializer):
        participant = super().perform_create(serializer)
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.create",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Created participant {participant.full_name}.",
            metadata={"zev_id": str(participant.zev_id)},
        )

    def perform_destroy(self, instance):
        participant_id = str(instance.pk)
        participant_display = instance.full_name
        zev_id = str(instance.zev_id)
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.delete",
            target_type="zev.Participant",
            target_id=participant_id,
            target_display=participant_display,
            summary=f"Deleted participant {participant_display}.",
            metadata={"zev_id": zev_id},
        )

    @action(detail=True, methods=["get"], url_path="contract-pdf",
            permission_classes=[IsAuthenticated])
    def contract_pdf(self, request, pk=None):
        """Stream the issued participation-contract PDF for this participant.

        The first download issues version 1; unchanged re-downloads reuse the
        frozen snapshot, and data changes produce a new numbered version.
        """
        from invoices.contract_pdf import issue_contract_pdf
        participant = self.get_object()
        if not request.user.is_admin and not request.user.is_zev_owner:
            if participant.user != request.user:
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
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
        filename = f"contract_{participant.last_name}_{participant.first_name}_v{issue.version}.pdf"
        response = HttpResponse(issue.pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=["post"], url_path="link-account")
    def link_account(self, request, pk=None):
        if not request.user.is_admin:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="participant.link_account",
                target_type="zev.Participant",
                target_id=str(pk or ""),
                target_display=str(pk or ""),
                summary="Denied participant account link by non-admin.",
                status=AuditEventStatus.DENIED,
            )
            return Response({"detail": "Only admins can link accounts."}, status=status.HTTP_403_FORBIDDEN)

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
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="participant.unlink_account",
                target_type="zev.Participant",
                target_id=str(pk or ""),
                target_display=str(pk or ""),
                summary="Denied participant account unlink by non-admin.",
                status=AuditEventStatus.DENIED,
            )
            return Response({"detail": "Only admins can unlink accounts."}, status=status.HTTP_403_FORBIDDEN)

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

    @action(detail=True, methods=["post"], url_path="create-account")
    def create_account(self, request, pk=None):
        if not request.user.is_admin:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="participant.create_account",
                target_type="zev.Participant",
                target_id=str(pk or ""),
                target_display=str(pk or ""),
                summary="Denied participant account creation by non-admin.",
                status=AuditEventStatus.DENIED,
            )
            return Response({"detail": "Only admins can create participant accounts."}, status=status.HTTP_403_FORBIDDEN)

        participant = self.get_object()
        if participant.user is not None:
            return Response({"detail": "Participant already has a linked account."}, status=status.HTTP_400_BAD_REQUEST)

        requested_username = (request.data.get("username") or "").strip()
        if requested_username and User.objects.filter(username=requested_username).exists():
            return Response({"detail": "Username is already taken."}, status=status.HTTP_400_BAD_REQUEST)

        base_username = requested_username or self._build_username_candidate(participant)
        username = self._find_available_username(base_username)
        temporary_password = get_random_string(14)

        account = User.objects.create_user(
            username=username,
            password=temporary_password,
            role=UserRole.PARTICIPANT,
            first_name=participant.first_name,
            last_name=participant.last_name,
            email=(request.data.get("email") or participant.email or "").strip(),
        )
        account.must_change_password = True
        account.save(
            update_fields=[
                "must_change_password",
            ]
        )

        participant.user = account
        participant.save(update_fields=["user", "updated_at"])
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.create_account",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Created and linked account {account.username} for participant {participant.full_name}.",
            changes={"user": {"before": None, "after": str(account.id)}},
        )

        serializer = self.get_serializer(participant)
        return Response(
            {
                "participant": serializer.data,
                "account": UserSerializer(account).data,
                "temporary_password": temporary_password,
            },
            status=status.HTTP_201_CREATED,
        )

    def _build_username_candidate(self, participant: Participant) -> str:
        parts = [participant.first_name.strip().lower(), participant.last_name.strip().lower()]
        candidate = ".".join([part for part in parts if part])
        return candidate or "participant"

    def _find_available_username(self, candidate: str) -> str:
        normalized = candidate[:150] or "participant"
        if not User.objects.filter(username=normalized).exists():
            return normalized

        for suffix in range(1, 10000):
            suffix_text = str(suffix)
            base = normalized[: 150 - len(suffix_text)]
            value = f"{base}{suffix_text}"
            if not User.objects.filter(username=value).exists():
                return value

        return f"participant{get_random_string(6).lower()}"

    @action(detail=True, methods=["post"], url_path="send-invitation")
    def send_invitation(self, request, pk=None):
        participant = self.get_object()
        try:
            username, temporary_password = send_participant_invitation(participant, request.user)
        except ValueError as exc:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="participant.send_invitation",
                target_type="zev.Participant",
                target=participant,
                target_id=str(participant.pk),
                target_display=participant.full_name,
                summary=f"Failed invitation email for participant {participant.full_name}.",
                status=AuditEventStatus.FAILED,
                metadata={"error": str(exc)},
            )
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.send_invitation",
            target_type="zev.Participant",
            target=participant,
            target_id=str(participant.pk),
            target_display=participant.full_name,
            summary=f"Sent participant invitation to {participant.email}.",
            metadata={"username": username},
        )
        return Response(
            {
                "detail": f"Invitation email sent to {participant.email}.",
                "username": username,
                "temporary_password": temporary_password,
            },
            status=status.HTTP_200_OK,
        )


class MeteringPointViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
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
        return self.scope_queryset(MeteringPoint.objects.select_related("zev"))

    def perform_create(self, serializer):
        metering_point = super().perform_create(serializer)
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.METERING,
            action_type="metering_point.create",
            target_type="zev.MeteringPoint",
            target=metering_point,
            target_id=str(metering_point.pk),
            target_display=metering_point.meter_id,
            summary=f"Created metering point {metering_point.meter_id}.",
            metadata={"zev_id": str(metering_point.zev_id), "meter_type": metering_point.meter_type},
        )

    def perform_destroy(self, instance):
        meter_id = instance.meter_id
        metering_point_id = str(instance.pk)
        zev_id = str(instance.zev_id)
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.METERING,
            action_type="metering_point.delete",
            target_type="zev.MeteringPoint",
            target_id=metering_point_id,
            target_display=meter_id,
            summary=f"Deleted metering point {meter_id}.",
            metadata={"zev_id": zev_id},
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="delete-readings",
        permission_classes=[IsAuthenticated, IsAdmin],
    )
    def delete_readings(self, request, pk=None):
        metering_point = self.get_object()
        delete_all = bool(request.data.get("delete_all", False))
        date_from = request.data.get("date_from")
        date_to = request.data.get("date_to")

        readings_qs = MeterReading.objects.filter(metering_point=metering_point)

        if not delete_all:
            if not date_from or not date_to:
                return Response(
                    {"error": "date_from and date_to are required when delete_all is false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                parsed_from = date_type.fromisoformat(date_from)
                parsed_to = date_type.fromisoformat(date_to)
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if parsed_to < parsed_from:
                return Response(
                    {"error": "date_to must be on or after date_from."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            start_dt = datetime.combine(parsed_from, datetime.min.time(), tzinfo=dt_timezone.utc)
            end_dt_exclusive = datetime.combine(parsed_to, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1)
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
            metadata={"delete_all": delete_all, "date_from": date_from, "date_to": date_to},
        )

        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)


class MeteringPointAssignmentViewSet(AuditedUpdateMixin, ZevScopedQuerySetMixin, viewsets.ModelViewSet):
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

    def perform_create(self, serializer):
        assignment = super().perform_create(serializer)
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.METERING,
            action_type="metering_assignment.create",
            target_type="zev.MeteringPointAssignment",
            target=assignment,
            target_id=str(assignment.pk),
            target_display=str(assignment.pk),
            summary=f"Created metering point assignment for {assignment.metering_point.meter_id}.",
            metadata={
                "metering_point_id": str(assignment.metering_point_id),
                "participant_id": str(assignment.participant_id),
            },
        )

    def perform_destroy(self, instance):
        assignment_id = str(instance.pk)
        meter_id = instance.metering_point.meter_id
        participant_id = str(instance.participant_id)
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.METERING,
            action_type="metering_assignment.delete",
            target_type="zev.MeteringPointAssignment",
            target_id=assignment_id,
            target_display=assignment_id,
            summary=f"Deleted metering point assignment for {meter_id}.",
            metadata={"participant_id": participant_id},
        )
