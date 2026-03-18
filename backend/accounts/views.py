from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import User, UserRole
from .serializers import (
    UserSerializer, UserCreateSerializer,
    ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    AppSettingsSerializer,
)
from .models import AppSettings
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
