from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from urllib.parse import urlparse
from .jwt_utils import add_custom_claims
from .models import ApiKey, AppSettings, FeatureFlag, OAuthProvider, SocialAccount, TotpDevice, User, UserRole, VatRate
from zev.models import Zev


class UserSerializer(serializers.ModelSerializer):
    # UUID primary key of the default community, or null. Exposed read-write
    # so the frontend can persist the community a user lands on.
    preferred_zev = serializers.PrimaryKeyRelatedField(
        queryset=Zev.objects.all(),
        required=False,
        allow_null=True,
    )

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

    def validate_preferred_zev(self, value):
        """A default community must be one the user manages.

        The preference is meaningless for roles without a community switcher
        (participant, guest), and an owner must not point their default at a
        community they do not own. Admins may set any community.
        """
        user = self.instance
        if value is None or user is None:
            return value
        if not user.is_zev_owner:
            raise serializers.ValidationError(
                "Only ZEV owners and admins can set a default community."
            )
        if not user.is_admin and value.owner_id != user.pk:
            raise serializers.ValidationError(
                "You can only set one of your own communities as the default."
            )
        return value

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "must_change_password", "is_active", "date_joined",
            "preferred_zev",
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
        add_custom_claims(token, user)
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


class TotpDeviceSerializer(serializers.ModelSerializer):
    """Never exposes ``secret`` or ``secret_encrypted`` — the secret is
    returned separately, once, only from the enrolment-begin endpoint."""

    class Meta:
        model = TotpDevice
        fields = ["id", "confirmed_at", "created_at"]
        read_only_fields = fields


class OAuthProviderSerializer(serializers.ModelSerializer):
    """Admin CRUD serializer; ``client_secret`` is write-only and a blank
    value on update leaves the stored secret untouched."""

    # Use CharField to allow internal hostnames like "keycloak:8080" while
    # still enforcing a scheme/netloc via custom validators below.
    authorization_url = serializers.CharField(max_length=500)
    token_url = serializers.CharField(max_length=500)
    userinfo_url = serializers.CharField(max_length=500)
    redirect_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    client_secret = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    has_client_secret = serializers.SerializerMethodField()

    def get_has_client_secret(self, obj) -> bool:
        return bool(obj.client_secret)

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
        secret = (attrs.get("client_secret") or "").strip()
        if self.instance is None and not secret:
            raise serializers.ValidationError(
                {"client_secret": "A client secret is required when creating a provider."}
            )
        if self.instance is not None and not secret:
            attrs.pop("client_secret", None)

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
            "has_client_secret",
            "authorization_url", "token_url", "userinfo_url", "redirect_url", "scope",
            "enabled", "require_mfa_claim", "created_at", "updated_at",
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


class ApiKeySerializer(serializers.ModelSerializer):
    """A key as it appears in the list — never including the secret."""

    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id", "name", "prefix", "read_only",
            "created_at", "expires_at", "last_used_at", "is_expired",
        ]
        read_only_fields = fields


class ApiKeyCreateSerializer(serializers.ModelSerializer):
    """Input for creating a key.

    ``expires_at`` is optional: left out, the key gets
    ``API_KEY_DEFAULT_EXPIRY_DAYS``. An expiry that has already passed is
    refused rather than silently accepted — a key that is dead on arrival is
    always a mistake, and the failure would otherwise look like a broken
    credential rather than a bad request.
    """

    class Meta:
        model = ApiKey
        fields = ["name", "read_only", "expires_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A name is required so the key can be recognised later.")
        return value

    def validate_expires_at(self, value):
        from django.utils import timezone

        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("Expiry must be in the future.")
        return value


class AdminApiKeySerializer(serializers.ModelSerializer):
    """A key as an admin sees it: the same fields plus who owns it.

    Deliberately never exposes ``hashed_key`` — there is no admin path to a
    key's secret.
    """

    username = serializers.CharField(source="user.username", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_role = serializers.CharField(source="user.role", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id", "name", "prefix", "read_only",
            "user", "username", "user_email", "user_role",
            "created_at", "expires_at", "last_used_at", "revoked_at",
            "is_expired", "is_revoked",
        ]
        read_only_fields = fields
