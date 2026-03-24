from django.db.models import Q
from django.http import HttpResponse
from django.utils.crypto import get_random_string
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.models import User, UserRole
from accounts.serializers import UserSerializer
from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment
from .serializers import (
    ZevSerializer,
    ZevDetailSerializer,
    ZevCreateWithOwnerSerializer,
    ParticipantSerializer,
    MeteringPointSerializer,
    MeteringPointAssignmentSerializer,
)
from .permissions import (
    MeteringPointAssignmentPermission,
    MeteringPointPermission,
    ParticipantManagementPermission,
    ZevManagementPermission,
)
from .services import send_participant_invitation, create_zev_for_existing_owner


class ZevViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ZevManagementPermission]

    def get_permissions(self):
        # self_setup is a POST by non-admins — skip ZevManagementPermission
        if self.action == "self_setup":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Zev.objects.all()
        if user.is_zev_owner:
            return Zev.objects.filter(owner=user)
        return Zev.objects.filter(participants__user=user).distinct()

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


class ParticipantViewSet(viewsets.ModelViewSet):
    serializer_class = ParticipantSerializer
    permission_classes = [IsAuthenticated, ParticipantManagementPermission]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Participant.objects.prefetch_related("metering_point_assignments")
        if user.is_zev_owner:
            return Participant.objects.filter(zev__owner=user).prefetch_related("metering_point_assignments")
        return Participant.objects.filter(user=user).prefetch_related("metering_point_assignments")

    @action(detail=True, methods=["get"], url_path="contract-pdf",
            permission_classes=[IsAuthenticated])
    def contract_pdf(self, request, pk=None):
        """Generate and stream a participation contract PDF for this participant."""
        from invoices.contract_pdf import generate_contract_pdf
        participant = self.get_object()
        if not request.user.is_admin and not request.user.is_zev_owner:
            if participant.user != request.user:
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        pdf_bytes = generate_contract_pdf(participant)
        filename = f"contract_{participant.last_name}_{participant.first_name}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=True, methods=["post"], url_path="link-account")
    def link_account(self, request, pk=None):
        if not request.user.is_admin:
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
        serializer = self.get_serializer(participant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unlink-account")
    def unlink_account(self, request, pk=None):
        if not request.user.is_admin:
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
        serializer = self.get_serializer(participant)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="create-account")
    def create_account(self, request, pk=None):
        if not request.user.is_admin:
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
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "detail": f"Invitation email sent to {participant.email}.",
                "username": username,
                "temporary_password": temporary_password,
            },
            status=status.HTTP_200_OK,
        )


class MeteringPointViewSet(viewsets.ModelViewSet):
    serializer_class = MeteringPointSerializer
    permission_classes = [IsAuthenticated, MeteringPointPermission]

    def get_queryset(self):
        user = self.request.user
        qs = MeteringPoint.objects.select_related("zev")
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            return qs.filter(zev__owner=user)
        return qs.filter(assignments__participant__user=user).distinct()


class MeteringPointAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = MeteringPointAssignmentSerializer
    permission_classes = [IsAuthenticated, MeteringPointAssignmentPermission]

    def get_queryset(self):
        user = self.request.user
        qs = MeteringPointAssignment.objects.select_related(
            "metering_point",
            "metering_point__zev",
            "participant",
        )
        if user.is_admin:
            pass
        elif user.is_zev_owner:
            qs = qs.filter(metering_point__zev__owner=user)
        else:
            qs = qs.filter(participant__user=user)

        # Optional filter: ?metering_point=<uuid>
        mp_id = self.request.query_params.get("metering_point")
        if mp_id:
            qs = qs.filter(metering_point_id=mp_id)

        return qs
