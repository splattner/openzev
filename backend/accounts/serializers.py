from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import AppSettings, User, UserRole, VatRate


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


class VatRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatRate
        fields = ["id", "rate", "valid_from", "valid_to", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class VatRateInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = VatRate
        fields = ["rate", "valid_from", "valid_to"]
