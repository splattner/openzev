from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .geocoding import get_cached_building_footprint
from .grid_operators import grid_operator_ids
from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment, VatMode
from accounts.models import UserRole
from .services import create_zev_with_owner_setup, ensure_participant_account
from .tasks import trigger_geocode_if_address_present


class MeteringPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeteringPoint
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MeteringPointAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeteringPointAssignment
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        candidate = self.instance or MeteringPointAssignment()
        for field_name, value in attrs.items():
            setattr(candidate, field_name, value)

        try:
            candidate.full_clean()
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages)

        return attrs

class ParticipantSerializer(serializers.ModelSerializer):
    account_username = serializers.CharField(source="user.username", read_only=True)
    initial_password = serializers.SerializerMethodField()
    full_name = serializers.ReadOnlyField()
    metering_points = serializers.SerializerMethodField()
    has_metering_point_assignment = serializers.SerializerMethodField()
    building_footprint = serializers.SerializerMethodField()

    def get_initial_password(self, obj):
        return getattr(obj, "_initial_password", None)

    def get_building_footprint(self, obj):
        return get_cached_building_footprint(obj.address_line1, obj.postal_code, obj.city)

    def get_has_metering_point_assignment(self, obj):
        return obj.metering_point_assignments.exists()

    def get_metering_points(self, obj):
        metering_points = (
            MeteringPoint.objects.filter(assignments__participant=obj)
            .distinct()
            .order_by("meter_id")
        )
        return MeteringPointSerializer(metering_points, many=True, context=self.context).data

    def validate(self, attrs):
        if "user" in attrs:
            raise serializers.ValidationError({"user": "Participant accounts are created automatically."})

        email = attrs.get("email", getattr(self.instance, "email", "")).strip()
        if not email:
            raise serializers.ValidationError({"email": "Participant email is required."})

        request = self.context.get("request")
        is_admin = bool(request and request.user.is_admin)
        user = getattr(self.instance, "user", None)
        if user is not None and user.role != UserRole.PARTICIPANT and not is_admin:
            raise serializers.ValidationError({"user": "Linked account must have participant role."})

        return attrs

    def create(self, validated_data):
        participant = super().create(validated_data)
        _, initial_password = ensure_participant_account(participant)
        participant._initial_password = initial_password
        trigger_geocode_if_address_present(participant)
        return participant

    def update(self, instance, validated_data):
        participant = super().update(instance, validated_data)
        _, initial_password = ensure_participant_account(participant)
        participant._initial_password = initial_password
        trigger_geocode_if_address_present(participant)
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
            "allocation_weight",
            "metering_points",
            "has_metering_point_assignment",
            "building_footprint",
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
            "has_metering_point_assignment",
            "building_footprint",
            "created_at",
            "updated_at",
        ]


class GridOperatorSerializer(serializers.Serializer):
    """One entry of the ElCom grid-operator list. Read-only reference data."""

    id = serializers.IntegerField(help_text="ElCom operator id")
    name = serializers.CharField()
    uid = serializers.CharField(allow_blank=True, help_text="Swiss company UID (CHE-...)")
    website = serializers.CharField(allow_blank=True)


class GridOperatorListSerializer(serializers.Serializer):
    """The fixture as served: the operator list plus its provenance."""

    source = serializers.CharField()
    cube = serializers.CharField()
    licence = serializers.CharField()
    period = serializers.CharField()
    fetched_on = serializers.DateField()
    operators = GridOperatorSerializer(many=True)


class ZevSerializer(serializers.ModelSerializer):
    def validate_grid_operator_elcom_id(self, value):
        """Only ids from the shipped ElCom list are accepted.

        The field exists to make ``grid_operator`` resolvable back to a real
        utility; an arbitrary integer would defeat that while looking like it
        had worked. ``None`` stays valid — that is the hand-typed case.
        """
        if value is not None and value not in grid_operator_ids():
            raise serializers.ValidationError(
                "Unknown ElCom operator id. Leave it empty when the grid operator "
                "was entered by hand."
            )
        return value

    def validate_owner(self, value):
        request = self.context.get("request")
        if not request or request.user.is_admin:
            return value
        if value != request.user:
            raise serializers.ValidationError("Only admins can assign a different owner.")
        return value

    def validate(self, attrs):
        def resolved(field):
            if field in attrs:
                return attrs[field]
            if self.instance is not None:
                return getattr(self.instance, field)
            return Zev._meta.get_field(field).get_default()

        vat_mode = resolved("vat_mode")
        vat_number = resolved("vat_number")
        if vat_mode == VatMode.REGISTERED and not vat_number:
            raise serializers.ValidationError(
                {"vat_number": "A VAT-registered ZEV must have a VAT number (UID)."}
            )
        if vat_mode != VatMode.REGISTERED and vat_number:
            raise serializers.ValidationError(
                {"vat_number": "Only a VAT-registered ZEV carries a VAT number. "
                 "Clear it, or set the VAT mode to registered."}
            )
        return attrs

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
    location_description = serializers.CharField(required=False, allow_blank=True, max_length=200)


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
    vat_mode = serializers.ChoiceField(
        choices=Zev._meta.get_field('vat_mode').choices, required=False
    )
    vat_number = serializers.CharField(required=False, allow_blank=True, max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True)
    owner = ZevOwnerAccountSerializer()
    metering_points = OwnerMeteringPointInputSerializer(many=True, min_length=1)

    def validate(self, attrs):
        vat_mode = attrs.get("vat_mode", VatMode.NOT_REGISTERED)
        if vat_mode == VatMode.REGISTERED and not attrs.get("vat_number"):
            raise serializers.ValidationError(
                {"vat_number": "A VAT-registered ZEV must have a VAT number (UID)."}
            )
        if vat_mode != VatMode.REGISTERED and attrs.get("vat_number"):
            raise serializers.ValidationError(
                {"vat_number": "Only a VAT-registered ZEV carries a VAT number."}
            )
        return attrs

    def create(self, validated_data):
        owner_data = validated_data.pop('owner')
        metering_points_data = validated_data.pop('metering_points')
        return create_zev_with_owner_setup(
            zev_data=validated_data,
            owner_data=owner_data,
            metering_points_data=metering_points_data,
        )
