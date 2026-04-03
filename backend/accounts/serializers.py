from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from urllib.parse import urlparse
from .models import AppSettings, FeatureFlag, OAuthProvider, SocialAccount, User, UserRole, VatRate


class UserSerializer(serializers.ModelSerializer):
    def validate_role(self, value):
        request = self.context.get("request")
        if not request or not self.instance:
            return value

        if request.user.pk == self.instance.pk:
            if self.instance.role == UserRole.ADMIN and value != UserRole.ADMIN:
                raise serializers.ValidationError("Admin users cannot change their own role.")
            if not request.user.is_admin and value != self.instance.role:
                raise serializers.ValidationError("You cannot change your own role.")

        if not request.user.is_admin and value != self.instance.role:
            raise serializers.ValidationError("Only admins can change user roles.")

        return value

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "must_change_password", "is_active", "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "password", "password2", "role"]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.must_change_password = False
        user.save()
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    email = serializers.EmailField(required=False, allow_blank=True, write_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Phase 1 migration: allow email-only login while keeping username fallback.
        self.fields[self.username_field].required = False
        self.fields[self.username_field].allow_blank = True

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip()
        username = (attrs.get(self.username_field) or "").strip()

        if email:
            user_model = get_user_model()
            matches = list(
                user_model.objects.filter(email__iexact=email).values_list(self.username_field, flat=True)[:2]
            )
            # Keep login failure generic and avoid ambiguous email authentication.
            if len(matches) != 1:
                self.fail("no_active_account")
            attrs[self.username_field] = matches[0]
        elif username:
            attrs[self.username_field] = username
        else:
            self.fail("no_active_account")

        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        token["full_name"] = user.get_full_name()
        token["must_change_password"] = user.must_change_password
        return token


class AppSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppSettings
        fields = ["date_format_short", "date_format_long", "date_time_format", "updated_at"]
        read_only_fields = ["updated_at"]


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ["id", "name", "description", "enabled", "updated_at"]
        read_only_fields = ["id", "name", "description", "updated_at"]


class OAuthProviderSerializer(serializers.ModelSerializer):
    """Full serializer for admin CRUD — includes client_secret."""

    # Use CharField to allow internal hostnames like "keycloak:8080" while
    # still enforcing a scheme/netloc via custom validators below.
    authorization_url = serializers.CharField(max_length=500)
    token_url = serializers.CharField(max_length=500)
    userinfo_url = serializers.CharField(max_length=500)
    redirect_url = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_name(self, value):
        normalized = slugify((value or "").strip())
        if not normalized:
            raise serializers.ValidationError("Provider slug cannot be empty.")
        return normalized

    def _validate_endpoint_url(self, value: str) -> str:
        url = (value or "").strip()
        if "://" not in url:
            url = f"https://{url}"

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Enter a valid URL (http:// or https://).")
        return url

    def validate_authorization_url(self, value):
        return self._validate_endpoint_url(value)

    def validate_token_url(self, value):
        return self._validate_endpoint_url(value)

    def validate_userinfo_url(self, value):
        return self._validate_endpoint_url(value)

    def validate_redirect_url(self, value):
        return self._validate_endpoint_url(value)

    def _build_default_redirect_url(self, provider_name: str) -> str:
        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173").rstrip("/")
        return f"{frontend_url}/api/v1/auth/oauth/callback/{provider_name}/"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        provider_name = attrs.get("name") or getattr(self.instance, "name", "")
        redirect_url = attrs.get("redirect_url")

        if provider_name and (redirect_url is None or redirect_url == ""):
            attrs["redirect_url"] = self._build_default_redirect_url(provider_name)

        return attrs

    def validate_display_name(self, value):
        text = (value or "").strip()
        if not text:
            raise serializers.ValidationError("Display name cannot be empty.")
        return text

    class Meta:
        model = OAuthProvider
        fields = [
            "id", "name", "display_name", "client_id", "client_secret",
            "authorization_url", "token_url", "userinfo_url", "redirect_url", "scope",
            "enabled", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class OAuthProviderPublicSerializer(serializers.ModelSerializer):
    """Public serializer — never exposes client_secret."""

    class Meta:
        model = OAuthProvider
        fields = ["id", "name", "display_name", "enabled"]


class SocialAccountSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    provider_display_name = serializers.CharField(source="provider.display_name", read_only=True)

    class Meta:
        model = SocialAccount
        fields = ["id", "provider_name", "provider_display_name", "uid", "created_at"]
        read_only_fields = ["id", "provider_name", "provider_display_name", "uid", "created_at"]


class VatRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatRate
        fields = ["id", "rate", "valid_from", "valid_to", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class VatRateInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatRate
        fields = ["rate", "valid_from", "valid_to"]
