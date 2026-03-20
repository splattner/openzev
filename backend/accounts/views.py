from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
import secrets
from urllib.parse import urlencode
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import User, UserRole, EmailVerificationToken
from .serializers import (
    UserSerializer, UserCreateSerializer,
    ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    AppSettingsSerializer,
    VatRateSerializer,
)
from .models import AppSettings, VatRate
from .permissions import IsAdmin


class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login — includes role, email and full_name in the token."""
    serializer_class = CustomTokenObtainPairSerializer


class UserListCreateView(generics.ListCreateAPIView):
    """Admin: create users. Admin/ZEV owner: list participant accounts for linking."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return User.objects.all().order_by("username")
        if user.is_zev_owner:
            return User.objects.filter(role=UserRole.PARTICIPANT, is_active=True).order_by("username")
        raise PermissionDenied("Permission denied.")

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == "POST" else UserSerializer

    def create(self, request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied("Only admins can create users.")
        return super().create(request, *args, **kwargs)


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Admin: retrieve / update / delete a user."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.participations.exists():
            raise PermissionDenied("Linked participant accounts cannot be edited here.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.participations.exists():
            raise PermissionDenied("Linked participant accounts cannot be deleted.")
        instance.delete()


class VatRateListCreateView(generics.ListCreateAPIView):
    queryset = VatRate.objects.all().order_by("-valid_from", "-created_at")
    permission_classes = [IsAdmin]

    serializer_class = VatRateSerializer

    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))


class VatRateDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = VatRate.objects.all()
    permission_classes = [IsAdmin]
    serializer_class = VatRateSerializer

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    """Current user: retrieve or partial-update own profile."""
    if request.method == "GET":
        return Response(UserSerializer(request.user).data)
    serializer = UserSerializer(request.user, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response({"detail": "Password updated successfully."})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def app_settings(request):
    settings_instance = AppSettings.load()

    if request.method == "GET":
        return Response(AppSettingsSerializer(settings_instance).data)

    if not request.user.is_admin:
        raise PermissionDenied("Only admins can update application settings.")

    serializer = AppSettingsSerializer(settings_instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def impersonate_participant(request, user_id: int):
    if not request.user.is_admin:
        raise PermissionDenied("Only admins can impersonate participants.")

    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    if target_user.role not in (UserRole.PARTICIPANT, UserRole.ZEV_OWNER):
        return Response({"detail": "Only participant or ZEV owner users can be impersonated."}, status=status.HTTP_400_BAD_REQUEST)

    refresh = RefreshToken.for_user(target_user)
    refresh["role"] = target_user.role
    refresh["email"] = target_user.email
    refresh["full_name"] = target_user.get_full_name()
    refresh["must_change_password"] = target_user.must_change_password
    refresh["impersonated_by"] = request.user.id

    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "impersonated_user": UserSerializer(target_user).data,
            "impersonator": UserSerializer(request.user).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """Self-registration: create a pending zev_owner account and send a verification email."""
    username = request.data.get("username", "").strip()
    email = request.data.get("email", "").strip()

    errors = {}
    if not username:
        errors["username"] = "Username is required."
    if not email:
        errors["email"] = "Email is required."
    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({"username": "This username is already taken."}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email__iexact=email).exists():
        return Response({"email": "An account with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        username=username,
        email=email,
        role=UserRole.ZEV_OWNER,
        is_active=False,
        must_change_password=True,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])

    token = EmailVerificationToken.objects.create(
        user=user,
        token=secrets.token_urlsafe(48),
    )

    frontend_url = settings.FRONTEND_URL.rstrip("/")
    verify_url = f"{frontend_url}/verify-email?token={token.token}"

    EmailMessage(
        subject="Verify your OpenZEV account",
        body=(
            f"Hello {username},\n\n"
            f"Thank you for registering with OpenZEV.\n"
            f"Please verify your email address by clicking the link below:\n\n"
            f"{verify_url}\n\n"
            f"This link is valid for 24 hours.\n\n"
            f"If you did not register for OpenZEV, please ignore this email.\n\n"
            f"Best regards,\nOpenZEV"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    ).send(fail_silently=False)

    return Response({"detail": "Verification email sent. Please check your inbox."}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_email(request):
    """Consume a one-time verification token and return JWT tokens to auto-login the user."""
    token_value = request.data.get("token", "").strip()
    if not token_value:
        return Response({"detail": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token = EmailVerificationToken.objects.select_related("user").get(token=token_value)
    except EmailVerificationToken.DoesNotExist:
        return Response({"detail": "Invalid or expired verification link."}, status=status.HTTP_400_BAD_REQUEST)

    if not token.is_valid():
        return Response(
            {"detail": "This verification link has expired or already been used."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])

    user = token.user
    user.is_active = True
    user.save(update_fields=["is_active"])

    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_initial_password(request):
    """Set a password for a freshly verified account that has no usable password yet."""
    new_password = request.data.get("new_password", "")
    if not new_password:
        return Response({"detail": "new_password is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not (user.must_change_password or not user.has_usable_password()):
        return Response(
            {"detail": "Use the change-password endpoint instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])

    # Return fresh tokens so the frontend can stay logged in
    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    })
