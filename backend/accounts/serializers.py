import secrets
import string

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from urllib.parse import urlparse
from . import mfa
from .jwt_utils import add_custom_claims
from .models import ApiKey, AppSettings, FeatureFlag, OAuthProvider, SocialAccount, TotpDevice, User, UserRole, VatRate, WebAuthnCredential
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

    def validate_is_active(self, value):
        """An admin cannot deactivate their own account.

        Deactivating revokes every session (``UserDetailView.perform_update``),
        so doing it to yourself through the admin console would sign you out
        mid-edit with no way back in except another administrator. There is
        no equivalent "last active admin" case beyond this one: reaching zero
        active admins any other way requires an *inactive* admin to act, which
        cannot happen.
        """
        request = self.context.get("request")
        if request and self.instance and not value and request.user.pk == self.instance.pk:
            raise serializers.ValidationError("You cannot deactivate your own account.")
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


class SelfUserSerializer(UserSerializer):
    """What ``PATCH /auth/me/`` may change: first name, last name and default
    community.

    The rest of the account is not the person's to edit here — the email is the
    sign-in identifier and has its own verified flow, ``must_change_password``
    can only be cleared by a password change, and role/``is_active`` are an
    admin's. A payload that tries to *change* one of them is rejected with a 400
    naming it (silently ignoring it would hide an attempted privilege change);
    one that merely repeats the current value is accepted and ignored, so a
    client that sends the whole object back keeps working.
    """

    PROTECTED_FIELDS = ("username", "email", "role", "must_change_password", "is_active")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        errors = {}
        for name in self.PROTECTED_FIELDS:
            if name in self.initial_data and not self._same(self.initial_data[name], getattr(self.instance, name)):
                errors[name] = ["This cannot be changed here."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @staticmethod
    def _same(submitted, current) -> bool:
        return str(submitted).strip().lower() == str(current).strip().lower()

    class Meta(UserSerializer.Meta):
        read_only_fields = [
            name for name in UserSerializer.Meta.fields if name not in ("first_name", "last_name", "preferred_zev")
        ]


class AdminUserSerializer(UserSerializer):
    """The admin accounts list: the account plus where it belongs and which
    second factors it has.

    Kept apart from ``UserSerializer`` so ``/auth/me`` and impersonation, which
    reuse that one, do not pay for (or leak) the extra relations. Every added
    field is read-only and derived from prefetched data — see
    ``UserListCreateView.get_queryset`` — so the list stays a fixed number of
    queries however many accounts there are.
    """

    memberships = serializers.SerializerMethodField()
    mfa_methods = serializers.SerializerMethodField()
    mfa_compliance = serializers.SerializerMethodField()

    def get_memberships(self, user):
        """One entry per community the account is tied to.

        ``Zev.owner`` and ``Participant.user`` are separate relations, but an
        owner is normally also their own community's owner-participant, so the
        two are merged per ZEV: showing "Owner · Sonnenberg" and
        "Participant · Sonnenberg" for one person would read as two roles.
        """
        by_zev: dict = {}
        for zev in user.owned_zevs.all():
            by_zev[zev.pk] = {"zev": str(zev.pk), "zev_name": zev.name, "is_owner": True, "participant": None}
        for participant in user.participations.all():
            entry = by_zev.setdefault(
                participant.zev_id,
                {"zev": str(participant.zev_id), "zev_name": participant.zev.name, "is_owner": False, "participant": None},
            )
            entry["participant"] = str(participant.pk)
        return sorted(by_zev.values(), key=lambda entry: entry["zev_name"].lower())

    def get_mfa_methods(self, user):
        methods = []
        try:
            device = user.totp_device
        except ObjectDoesNotExist:
            device = None
        if device is not None and device.confirmed_at is not None:
            methods.append("totp")
        if user.webauthn_credentials.all():
            methods.append("passkey")
        return methods

    def get_mfa_compliance(self, user):
        """Where this account stands against ``AppSettings.mfa_required_roles``,
        or ``None`` when the policy does not name its role.

        ``AppSettings`` is loaded once per request (cached on ``self``, the one
        child serializer instance a ``many=True`` list reuses for every row —
        see ``test_query_count_does_not_grow_with_the_number_of_accounts``), not
        once per account.
        """
        if not hasattr(self, "_app_settings"):
            self._app_settings = AppSettings.load()
        return mfa.compliance_status(user, app_settings=self._app_settings, has_factor=bool(self.get_mfa_methods(user)))

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["memberships", "mfa_methods", "mfa_compliance"]


def generate_temporary_password(length: int = 16) -> str:
    """A random password for an account created on someone else's behalf.

    Never chosen by the admin and never reused — the account must set its own
    at first sign-in (``must_change_password``), the same escape hatch
    ``zev.services.create_zev_with_owner_setup`` uses for a self-setup owner.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class UserCreateSerializer(serializers.ModelSerializer):
    """Admin: create an account (``POST /auth/users/``).

    ``password``/``password2`` are optional. The admin console's "New account"
    action never sends one: leaving both out makes ``create()`` generate a
    random temporary password, returned exactly once in the response
    (``UserListCreateView.create`` reads ``generated_password`` off this
    serializer) — mirroring how a passkey's recovery codes or a fresh API key
    are shown once and never stored in the clear. A caller that does supply a
    password (existing API consumers) keeps working unchanged. Either way the
    account is created with ``must_change_password=True``: nobody but the
    account holder should keep a password an admin picked or generated.
    """

    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "password", "password2", "role"]

    def validate(self, attrs):
        password = attrs.pop("password", None)
        password2 = attrs.pop("password2", None)
        if password or password2:
            if password != password2:
                raise serializers.ValidationError({"password": ["Passwords do not match."]})
            try:
                validate_password(password)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": exc.messages}) from None
            self.generated_password = None
        else:
            password = generate_temporary_password()
            self.generated_password = password
        attrs["password"] = password
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(must_change_password=True, **validated_data)


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
        fields = [
            "date_format_short",
            "date_format_long",
            "date_time_format",
            "mfa_required_roles",
            "mfa_grace_period_days",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate_mfa_required_roles(self, value):
        # The model's clean() is not run by a DRF serializer; share its rules
        # so an API write cannot save a policy the instance cannot honour.
        try:
            return AppSettings.validate_mfa_required_roles(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


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


class WebAuthnCredentialSerializer(serializers.ModelSerializer):
    """A passkey as the account page lists it. ``credential_id`` and
    ``public_key`` are never exposed; only ``name`` is writable."""

    class Meta:
        model = WebAuthnCredential
        fields = ["id", "name", "aaguid", "transports", "created_at", "last_used_at"]
        read_only_fields = ["id", "aaguid", "transports", "created_at", "last_used_at"]


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
