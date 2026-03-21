from rest_framework import serializers
from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment
from accounts.models import UserRole
from .services import create_zev_with_owner_setup, ensure_participant_account


class MeteringPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeteringPoint
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "participant": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        zev = attrs.get("zev") or getattr(self.instance, "zev", None)
        participant = attrs.get("participant", getattr(self.instance, "participant", None))
        if participant and zev and participant.zev_id != zev.id:
            raise serializers.ValidationError({"participant": "Participant must belong to selected ZEV."})
        return attrs


class MeteringPointAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeteringPointAssignment
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        metering_point = attrs.get("metering_point") or getattr(self.instance, "metering_point", None)
        participant = attrs.get("participant") or getattr(self.instance, "participant", None)
        valid_from = attrs.get("valid_from") or getattr(self.instance, "valid_from", None)
        valid_to = attrs.get("valid_to", getattr(self.instance, "valid_to", None))

        if metering_point and participant and metering_point.zev_id != participant.zev_id:
            raise serializers.ValidationError({"participant": "Participant must belong to the metering point's ZEV."})

        if valid_to and valid_from and valid_to < valid_from:
            raise serializers.ValidationError({"valid_to": "valid_to must be on or after valid_from."})

        # Only one assignment per metering point is allowed.
        if metering_point:
            existing = MeteringPointAssignment.objects.filter(metering_point=metering_point)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    "A metering point can only have one participant assignment."
                )

        # Assignment dates must fall within the metering point's validity window.
        if metering_point and valid_from:
            if valid_from < metering_point.valid_from:
                raise serializers.ValidationError(
                    {
                        "valid_from": (
                            "Assignment valid_from cannot be before the metering point's "
                            f"valid_from ({metering_point.valid_from})."
                        )
                    }
                )
            if valid_to and metering_point.valid_to and valid_to > metering_point.valid_to:
                raise serializers.ValidationError(
                    {
                        "valid_to": (
                            "Assignment valid_to cannot be after the metering point's "
                            f"valid_to ({metering_point.valid_to})."
                        )
                    }
                )

        # Assignment dates must fall within the participant's validity window.
        if participant and valid_from:
            if valid_from < participant.valid_from:
                raise serializers.ValidationError(
                    {
                        "valid_from": (
                            "Assignment valid_from cannot be before the participant's "
                            f"valid_from ({participant.valid_from})."
                        )
                    }
                )
            if valid_to and participant.valid_to and valid_to > participant.valid_to:
                raise serializers.ValidationError(
                    {
                        "valid_to": (
                            "Assignment valid_to cannot be after the participant's "
                            f"valid_to ({participant.valid_to})."
                        )
                    }
                )

        return attrs

    def _sync_current_participant(self, metering_point_id: int) -> None:
        open_assignment = (
            MeteringPointAssignment.objects.filter(
                metering_point_id=metering_point_id,
                valid_to__isnull=True,
            )
            .order_by("-valid_from")
            .first()
        )
        MeteringPoint.objects.filter(pk=metering_point_id).update(
            participant=open_assignment.participant if open_assignment else None
        )

    def create(self, validated_data):
        assignment = super().create(validated_data)
        self._sync_current_participant(assignment.metering_point_id)
        return assignment

    def update(self, instance, validated_data):
        assignment = super().update(instance, validated_data)
        self._sync_current_participant(assignment.metering_point_id)
        return assignment


class ParticipantSerializer(serializers.ModelSerializer):
    account_username = serializers.CharField(source="user.username", read_only=True)
    initial_password = serializers.SerializerMethodField()
    full_name = serializers.ReadOnlyField()
    metering_points = MeteringPointSerializer(many=True, read_only=True)

    def get_initial_password(self, obj):
        return getattr(obj, "_initial_password", None)

    def validate(self, attrs):
        if "user" in attrs:
            raise serializers.ValidationError({"user": "Participant accounts are created automatically."})

        email = attrs.get("email", getattr(self.instance, "email", "")).strip()
        if not email:
            raise serializers.ValidationError({"email": "Participant email is required."})

        user = getattr(self.instance, "user", None)
        if user is not None and user.role != UserRole.PARTICIPANT:
            raise serializers.ValidationError({"user": "Linked account must have participant role."})

        return attrs

    def create(self, validated_data):
        participant = super().create(validated_data)
        _, initial_password = ensure_participant_account(participant)
        participant._initial_password = initial_password
        return participant

    def update(self, instance, validated_data):
        participant = super().update(instance, validated_data)
        _, initial_password = ensure_participant_account(participant)
        participant._initial_password = initial_password
        return participant

    class Meta:
        model = Participant
        fields = [
            "id",
            "zev",
            "user",
            "account_username",
            "initial_password",
            "full_name",
            "title",
            "first_name",
            "last_name",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "postal_code",
            "city",
            "valid_from",
            "valid_to",
            "notes",
            "metering_points",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "account_username",
            "initial_password",
            "full_name",
            "metering_points",
            "created_at",
            "updated_at",
        ]


class ZevSerializer(serializers.ModelSerializer):
    def validate_owner(self, value):
        request = self.context.get("request")
        if not request or request.user.is_admin:
            return value
        if value != request.user:
            raise serializers.ValidationError("Only admins can assign a different owner.")
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        if request and "owner" not in validated_data:
            validated_data["owner"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        previous_owner = instance.owner
        new_owner = validated_data.get("owner", previous_owner)

        updated = super().update(instance, validated_data)

        if new_owner != previous_owner:
            if new_owner.role != UserRole.ADMIN and new_owner.role != UserRole.ZEV_OWNER:
                new_owner.role = UserRole.ZEV_OWNER
                new_owner.save(update_fields=["role"])

            if (
                previous_owner.role == UserRole.ZEV_OWNER
                and not previous_owner.owned_zevs.exists()
                and not previous_owner.is_superuser
            ):
                previous_owner.role = UserRole.PARTICIPANT
                previous_owner.save(update_fields=["role"])

        return updated

    class Meta:
        model = Zev
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "owner": {"required": False},
        }


class ZevDetailSerializer(ZevSerializer):
    participants = ParticipantSerializer(many=True, read_only=True)


class ZevOwnerAccountSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True, max_length=150)
    title = serializers.ChoiceField(choices=Participant.Title.choices, required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    address_line1 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    address_line2 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_username(self, value: str) -> str:
        username = value.strip()
        if not username:
            return username
        user_model = self.context['request'].user.__class__
        if user_model.objects.filter(username=username).exists():
            raise serializers.ValidationError('This username is already taken.')
        return username


class OwnerMeteringPointInputSerializer(serializers.Serializer):
    meter_id = serializers.CharField(max_length=100)
    meter_type = serializers.ChoiceField(choices=MeteringPoint._meta.get_field('meter_type').choices)
    is_active = serializers.BooleanField(required=False, default=True)
    valid_from = serializers.DateField(required=False)
    valid_to = serializers.DateField(required=False, allow_null=True)
    location_description = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        valid_from = attrs.get('valid_from')
        valid_to = attrs.get('valid_to')
        if valid_from and valid_to and valid_to < valid_from:
            raise serializers.ValidationError({'valid_to': 'valid_to must be on or after valid_from.'})
        return attrs


class ZevCreateWithOwnerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    start_date = serializers.DateField()
    zev_type = serializers.ChoiceField(choices=Zev._meta.get_field('zev_type').choices)
    billing_interval = serializers.ChoiceField(choices=Zev._meta.get_field('billing_interval').choices)
    grid_operator = serializers.CharField(required=False, allow_blank=True, max_length=200)
    grid_connection_point = serializers.CharField(required=False, allow_blank=True, max_length=200)
    invoice_prefix = serializers.CharField(required=False, allow_blank=True, max_length=10)
    bank_iban = serializers.CharField(required=False, allow_blank=True, max_length=34)
    bank_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    vat_number = serializers.CharField(required=False, allow_blank=True, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    owner = ZevOwnerAccountSerializer()
    metering_points = OwnerMeteringPointInputSerializer(many=True, min_length=1)

    def create(self, validated_data):
        owner_data = validated_data.pop('owner')
        metering_points_data = validated_data.pop('metering_points')
        return create_zev_with_owner_setup(
            zev_data=validated_data,
            owner_data=owner_data,
            metering_points_data=metering_points_data,
        )
