from rest_framework import serializers
from rest_framework.exceptions import NotFound
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.core.validators import RegexValidator
from django.db import transaction
from .geocoding import get_cached_building_footprint
from .grid_operators import grid_operator_ids
from django.utils import timezone

from .models import Building, Zev, Participant, Party, PartyKind, PartyTitle, MeteringPoint, MeteringPointAssignment, MeteringPointType, VatMode, PartyRole, ZevPartyRole
from .services import (
    account_for_email, create_zev_with_owner_setup, ensure_participant_account, existing_owner_problem,
    lock_participant_account, requires_independent_login,
)
from .tasks import trigger_building_geocode_if_address_present
from accounts import email_change
from .iban import (
    IBAN_ADDRESS_REQUIRED_MESSAGE,
    INVALID_IBAN_MESSAGE,
    has_required_iban_address,
    is_valid_iban,
    normalize_iban,
)


def django_validation_error(exc):
    errors = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
    return serializers.ValidationError(errors)


class BankIbanValidationMixin:
    """Normalize + validate `bank_iban` identically on every ZEV write path.

    Blank stays allowed (no IBAN configured); a non-blank value is stored in
    canonical compact-uppercase form and must pass the MOD-97 checksum.
    """

    def validate_bank_iban(self, value):
        normalized = normalize_iban(value or "")
        if normalized and not is_valid_iban(normalized):
            raise serializers.ValidationError(INVALID_IBAN_MESSAGE)
        return normalized


class MeteringPointSerializer(serializers.ModelSerializer):
    """
    ``reading_count``/``assignment_count``/``first_reading_at``/``last_reading_at``
    describe what a delete of this metering point would cascade to (both
    MeterReading and MeteringPointAssignment CASCADE on metering_point) so
    the frontend can show it before the user confirms.

    They read from queryset annotations when available (MeteringPointViewSet
    annotates its queryset for exactly this) and fall back to a live count
    otherwise, so the fields stay correct for instances not fetched through
    that queryset (e.g. the instance returned by create()/update()).
    """

    reading_count = serializers.SerializerMethodField()
    assignment_count = serializers.SerializerMethodField()
    first_reading_at = serializers.SerializerMethodField()
    last_reading_at = serializers.SerializerMethodField()
    building = serializers.PrimaryKeyRelatedField(queryset=Building.objects.all(), required=False)
    building_name = serializers.CharField(source="building.name", read_only=True)
    supplementary_source_status = serializers.SerializerMethodField()

    class Meta:
        model = MeteringPoint
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_supplementary_source_status(self, obj) -> str | None:
        """Status of the energy data source on this meter, for those who may see sources (SPEC §5.1).

        ``None`` while the feature is off, when there is no source, and for anyone who could not
        read the source itself: another participant must not learn that a neighbour has one.
        """
        from metering.supplementary import permissions

        if not permissions.feature_enabled():
            return None
        try:
            source = obj.supplementary_source
        except ObjectDoesNotExist:
            return None
        request = self.context.get("request")
        user = getattr(request, "user", None)
        source.metering_point = obj  # already loaded; saves role_for a query
        if user is None or not user.is_authenticated or permissions.role_for(user, source) == "none":
            return None
        return source.status

    def get_reading_count(self, obj):
        if hasattr(obj, "reading_count"):
            return obj.reading_count
        return obj.readings.count()

    def get_assignment_count(self, obj):
        if hasattr(obj, "assignment_count"):
            return obj.assignment_count
        return obj.assignments.count()

    def get_first_reading_at(self, obj):
        if hasattr(obj, "first_reading_at"):
            return obj.first_reading_at
        return obj.readings.order_by("timestamp").values_list("timestamp", flat=True).first()

    def get_last_reading_at(self, obj):
        if hasattr(obj, "last_reading_at"):
            return obj.last_reading_at
        return obj.readings.order_by("-timestamp").values_list("timestamp", flat=True).first()

    def validate(self, attrs):
        def resolved(field):
            if field in attrs:
                return attrs[field]
            if self.instance is not None:
                return getattr(self.instance, field)
            return MeteringPoint._meta.get_field(field).get_default()

        has_behind_meter_generation = resolved("has_behind_meter_generation")
        meter_type = resolved("meter_type")
        if has_behind_meter_generation and meter_type not in (
            MeteringPointType.BIDIRECTIONAL,
            MeteringPointType.PRODUCTION,
        ):
            raise serializers.ValidationError(
                {
                    "has_behind_meter_generation": (
                        "Only bidirectional or production metering points can have "
                        "generation behind the meter."
                    )
                }
            )
        if (
            not has_behind_meter_generation
            and self.instance is not None
            and getattr(self.instance, "supplementary_source", None) is not None
        ):
            raise serializers.ValidationError(
                {"has_behind_meter_generation": "Disconnect the energy data source first."}
            )
        building = attrs.get("building")
        zev = attrs.get("zev") or (self.instance.zev if self.instance is not None else None)
        if building is not None and zev is not None and building.zev_id != zev.pk:
            raise serializers.ValidationError({"building": "The building belongs to another ZEV."})
        if self.instance is None and building is None and zev is not None:
            buildings = list(Building.objects.filter(zev=zev)[:2])
            if len(buildings) > 1:
                raise serializers.ValidationError({"building": "Choose the building of this metering point."})
            if buildings:
                attrs["building"] = buildings[0]
            # With none, ``MeteringPoint.save()`` creates the default building:
            # only once the view's scope check has passed, never in validation.
        return attrs


class MeteringPointReadingsDeleteSerializer(serializers.Serializer):
    delete_all = serializers.BooleanField(required=False, default=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if attrs["delete_all"]:
            return attrs

        errors = {}
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from is None:
            errors["date_from"] = "This field is required when delete_all is false."
        if date_to is None:
            errors["date_to"] = "This field is required when delete_all is false."
        if date_from is not None and date_to is not None and date_to < date_from:
            errors["date_to"] = "Must be on or after date_from."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


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

def current_roles(party) -> list[dict]:
    """``party``'s roles active today or later (#761); reads ``party.roles``
    from a prefetch when there is one."""
    today = timezone.localdate()
    rows = [row for row in party.roles.all() if row.valid_to is None or row.valid_to >= today]
    rows.sort(key=lambda row: (row.role, row.valid_from))
    return [{"id": str(row.pk), "role": row.role, "valid_from": row.valid_from, "valid_to": row.valid_to} for row in rows]


class ParticipantSerializer(serializers.ModelSerializer):
    account_username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.ReadOnlyField()
    display_name = serializers.ReadOnlyField()
    # Names, contact data and address belong to the participant's party and are
    # written through to it (ADR 0028): every participation of that party shows
    # the change. ``party`` attaches a new participation to an existing party.
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all(), required=False)
    kind = serializers.ChoiceField(choices=PartyKind.choices, required=False)
    title = serializers.ChoiceField(choices=PartyTitle.choices, required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    organisation_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    name_addition = serializers.CharField(max_length=200, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    address_line1 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    address_line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    metering_points = serializers.SerializerMethodField()
    has_metering_point_assignment = serializers.SerializerMethodField()
    onboarding_status = serializers.SerializerMethodField()
    onboarding_link_expires_at = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def get_roles(self, obj):
        return current_roles(obj.party)

    def _latest_token(self, obj):
        if "_onboarding_token_cache" not in obj.__dict__:
            obj._onboarding_token_cache = (
                obj.onboarding_tokens.order_by("-created_at", "id").first()
            )
        return obj._onboarding_token_cache

    def get_onboarding_status(self, obj):
        """One of ``not_sent`` / ``sent`` / ``active`` / ``revoked`` / ``expired``.

        Read from the participant's most recent onboarding link: an account
        is created eagerly whether or not anyone was invited yet, so its
        mere existence says nothing about progress.
        """
        token = self._latest_token(obj)
        if token is None:
            return "not_sent"
        if token.revoked_at is not None:
            return "revoked"
        if token.is_expired:
            return "expired"
        if token.last_used_at is not None:
            return "active"
        return "sent"

    def get_onboarding_link_expires_at(self, obj):
        """Expiry of the most recent onboarding link, if not revoked."""
        token = self._latest_token(obj)
        if token is None or token.revoked_at is not None:
            return None
        return token.expires_at

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

        party = attrs.get("party")
        if party is not None:
            if self.instance is not None and party.pk != self.instance.party_id:
                raise serializers.ValidationError({"party": "A participation cannot move to another party."})
            zev = attrs.get("zev", getattr(self.instance, "zev", None))
            if zev is not None and party.zev_id != zev.pk:
                raise serializers.ValidationError({"party": "The party belongs to another ZEV."})

        def current(name):
            """The value the party will have: the payload's, else today's."""
            if name in attrs:
                return attrs[name] or ""
            source = self.instance if self.instance is not None else party
            return getattr(source, name, "") if source is not None else ""

        kind = current("kind") or PartyKind.PERSON
        if kind == PartyKind.ORGANISATION and not current("organisation_name").strip():
            raise serializers.ValidationError({"organisation_name": "An organisation needs a name."})
        if kind == PartyKind.PERSON and not current("last_name").strip():
            raise serializers.ValidationError({"last_name": "A person needs a last name."})

        email = current("email").strip()
        if not email:
            raise serializers.ValidationError({"email": "Participant email is required."})

        self._require_admin_for_protected_account(getattr(self.instance, "user", None))
        # The address identifies an account, and the row would join the one that holds it.
        holder = account_for_email(email)
        if holder is not None and holder.pk != getattr(self.instance, "user_id", None):
            self._require_admin_for_protected_account(holder)
        return attrs

    def _require_admin_for_protected_account(self, user):
        # Rows linked to an account with its own login stay admin-only (#761),
        # although saving them no longer syncs the account's email or name.
        request = self.context.get("request")
        is_admin = bool(request and request.user.is_admin)
        if user is not None and not is_admin and requires_independent_login(user):
            raise serializers.ValidationError(
                {"user": "This participant is linked to an account with its own login; only an admin can edit it."}
            )

    @transaction.atomic
    def create(self, validated_data):
        try:
            participant = super().create(validated_data)
            ensure_participant_account(participant)
        except DjangoValidationError as exc:
            raise django_validation_error(exc) from exc
        return participant

    @transaction.atomic
    def update(self, instance, validated_data):
        try:
            lock_participant_account(instance)
            if "party" in validated_data and validated_data["party"].pk != instance.party_id:
                raise serializers.ValidationError({"party": "A participation cannot move to another party."})
            # Promotion or relinking may have happened since validate().
            self._require_admin_for_protected_account(instance.user if instance.user_id else None)
            participant = super().update(instance, validated_data)
            ensure_participant_account(participant)
        except Participant.DoesNotExist as exc:
            raise NotFound from exc
        except DjangoValidationError as exc:
            raise django_validation_error(exc) from exc
        return participant

    class Meta:
        model = Participant
        fields = [
            "id",
            "zev",
            "user",
            "account_username",
            "onboarding_status",
            "onboarding_link_expires_at",
            "full_name",
            "display_name",
            "party",
            "kind",
            "title",
            "first_name",
            "last_name",
            "organisation_name",
            "name_addition",
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
            "roles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "account_username",
            "onboarding_status",
            "onboarding_link_expires_at",
            "full_name",
            "display_name",
            "roles",
            "metering_points",
            "has_metering_point_assignment",
            "created_at",
            "updated_at",
        ]


class PartySerializer(serializers.ModelSerializer):
    """A person or organisation of a ZEV with its participations and roles (#761)."""

    display_name = serializers.ReadOnlyField()
    participations = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    accounts = serializers.SerializerMethodField()

    def get_accounts(self, obj):
        """The logins that belong to the party: its own, then its participations'.
        The issuer and representative roles make each of them a manager (ADR
        0028, amended). Read from the prefetched participations."""
        accounts = []
        if obj.user_id is not None:
            accounts.append(obj.user)
        for participation in obj.participations.all():
            if participation.user_id is not None and participation.user not in accounts:
                accounts.append(participation.user)
        return [
            {"id": account.pk, "email": account.email, "full_name": account.get_full_name(), "is_active": account.is_active}
            for account in accounts
        ]

    def get_participations(self, obj):
        return [
            {"id": str(row.pk), "valid_from": row.valid_from, "valid_to": row.valid_to}
            for row in sorted(obj.participations.all(), key=lambda row: (row.valid_from, str(row.pk)))
        ]

    def get_roles(self, obj):
        return current_roles(obj)

    def validate(self, attrs):
        if self.instance is not None and "zev" in attrs and attrs["zev"].pk != self.instance.zev_id:
            raise serializers.ValidationError({"zev": "A party cannot move to another ZEV."})

        def current(name):
            if name in attrs:
                return attrs[name] or ""
            return getattr(self.instance, name, "") if self.instance is not None else ""

        kind = current("kind") or PartyKind.PERSON
        if kind == PartyKind.ORGANISATION and not current("organisation_name").strip():
            raise serializers.ValidationError({"organisation_name": "An organisation needs a name."})
        if kind == PartyKind.PERSON and not current("last_name").strip():
            raise serializers.ValidationError({"last_name": "A person needs a last name."})
        return attrs

    class Meta:
        model = Party
        fields = [
            "id", "zev", "kind", "title", "first_name", "last_name", "organisation_name", "name_addition",
            "email", "phone", "address_line1", "address_line2", "postal_code", "city", "notes",
            "display_name", "participations", "roles", "accounts", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "display_name", "participations", "roles", "accounts", "created_at", "updated_at"]


class BuildingSerializer(serializers.ModelSerializer):
    """A site of a ZEV: where its metering points are (#890)."""

    metering_point_count = serializers.SerializerMethodField()
    # Cache read only, never a Nominatim call (ADR 0012, amended).
    building_footprint = serializers.SerializerMethodField()
    current_participants = serializers.SerializerMethodField()

    def get_building_footprint(self, obj):
        return get_cached_building_footprint(obj.address_line1, obj.postal_code, obj.city)

    def get_current_participants(self, obj):
        """Participants with an assignment active today on one of the building's
        metering points; read from the viewset's prefetch."""
        today = timezone.localdate()
        found = {}
        for point in obj.metering_points.all():
            for assignment in point.assignments.all():
                if assignment.valid_from <= today and (assignment.valid_to is None or assignment.valid_to >= today):
                    found[assignment.participant_id] = assignment.participant.display_name
        return [{"id": str(pk), "display_name": name} for pk, name in sorted(found.items(), key=lambda item: (item[1], str(item[0])))]

    def create(self, validated_data):
        building = super().create(validated_data)
        trigger_building_geocode_if_address_present(building)
        return building

    def update(self, instance, validated_data):
        building = super().update(instance, validated_data)
        trigger_building_geocode_if_address_present(building)
        return building

    def get_metering_point_count(self, obj):
        if hasattr(obj, "metering_point_count"):
            return obj.metering_point_count
        return obj.metering_points.count()

    def validate(self, attrs):
        if self.instance is not None and "zev" in attrs and attrs["zev"].pk != self.instance.zev_id:
            raise serializers.ValidationError({"zev": "A building cannot move to another ZEV."})
        egid = attrs.get("egid")
        if egid is not None:
            zev_id = attrs["zev"].pk if "zev" in attrs else self.instance.zev_id
            clash = Building.objects.filter(zev_id=zev_id, egid=egid)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"egid": "Another building of this ZEV has this EGID."})
        return attrs

    class Meta:
        model = Building
        fields = [
            "id", "zev", "name", "address_line1", "address_line2", "postal_code", "city", "egid", "notes",
            "metering_point_count", "building_footprint", "current_participants", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "metering_point_count", "building_footprint", "current_participants", "created_at", "updated_at",
        ]
        # The EGID rule is checked in ``validate`` with a message on the field.
        validators = []


class ZevPartyRoleAssignSerializer(serializers.Serializer):
    """``POST /zev/party-roles/``: give a party a role from a date (#761)."""

    zev = serializers.PrimaryKeyRelatedField(queryset=Zev.objects.all())
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.all())
    role = serializers.ChoiceField(choices=PartyRole.choices)
    valid_from = serializers.DateField()
    valid_to = serializers.DateField(required=False, allow_null=True)
    building = serializers.PrimaryKeyRelatedField(queryset=Building.objects.all(), required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["party"].zev_id != attrs["zev"].pk:
            raise serializers.ValidationError({"party": "The party belongs to another ZEV."})
        building = attrs.get("building")
        if building is not None:
            if attrs["role"] != PartyRole.LANDOWNER:
                raise serializers.ValidationError({"building": "Only a landowner role names a building."})
            if building.zev_id != attrs["zev"].pk:
                raise serializers.ValidationError({"building": "The building belongs to another ZEV."})
        return attrs


class ZevPartyRoleBuildingSerializer(serializers.Serializer):
    """``POST /zev/party-roles/{id}/building/``: the building a landowner owns."""

    building = serializers.PrimaryKeyRelatedField(queryset=Building.objects.all(), allow_null=True)


class ZevPartyRoleEndSerializer(serializers.Serializer):
    """``POST /zev/party-roles/{id}/end/``: the role's last day."""

    last_day = serializers.DateField()


class ZevPartyRoleSerializer(serializers.ModelSerializer):
    """A party's dated role in a ZEV: issuer, representative or landowner (#761)."""

    party_display_name = serializers.CharField(source="party.display_name", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True, default=None)

    class Meta:
        model = ZevPartyRole
        fields = [
            "id", "zev", "party", "party_display_name", "role", "valid_from", "valid_to",
            "building", "building_name", "created_at", "updated_at",
        ]
        read_only_fields = fields


class GridOperatorSerializer(serializers.Serializer):
    """One entry of the ElCom grid-operator list. Read-only reference data."""

    id = serializers.IntegerField(help_text="ElCom operator id")
    name = serializers.CharField()
    uid = serializers.CharField(allow_blank=True, help_text="Swiss company UID (CHE-...)")
    website = serializers.CharField(allow_blank=True)
    tariff_url = serializers.CharField(
        allow_blank=True,
        help_text="ElCom's registered address for this operator's machine-readable tariffs "
                  "(Art. 7b StromVV). A suggestion only — fetch it before saving it as "
                  "tariff_source_url; see zev.grid_operators.",
    )
    tariff_url_is_direct = serializers.BooleanField(
        help_text="Whether tariff_url looks like the tariff file itself rather than a page about it.",
    )


class GridOperatorListSerializer(serializers.Serializer):
    """The fixture as served: the operator list plus its provenance."""

    source = serializers.CharField()
    cube = serializers.CharField()
    licence = serializers.CharField()
    period = serializers.CharField()
    fetched_on = serializers.DateField()
    operators = GridOperatorSerializer(many=True)


class GridOperatorSuggestionSerializer(serializers.Serializer):
    """Operator suggestion(s) for a postal code: zero, one, or a short list."""

    operators = GridOperatorSerializer(many=True)


INVOICE_PREFIX_MESSAGE = "Invoice prefix must contain only A-Z, 0-9, or hyphens (1 to 10 characters)."
INVOICE_PREFIX_VALIDATOR = RegexValidator(r"\A[A-Z0-9-]{1,10}\Z", INVOICE_PREFIX_MESSAGE)


class ZevSerializer(BankIbanValidationMixin, serializers.ModelSerializer):
    issuer = serializers.SerializerMethodField()
    # Preserve unchanged legacy values, including blanks and surrounding whitespace.
    invoice_prefix = serializers.CharField(required=False, allow_blank=True, max_length=10, trim_whitespace=False)

    def validate_invoice_prefix(self, value):
        # The settings form PATCHes every field; a legacy prefix that predates
        # the pattern must not block saving something unrelated.
        if self.instance is not None and value == self.instance.invoice_prefix:
            return value
        try:
            INVOICE_PREFIX_VALIDATOR(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    credit_note_prefix = serializers.CharField(required=False, allow_blank=True, max_length=10, trim_whitespace=False)

    def validate_credit_note_prefix(self, value):
        if self.instance is not None and value == self.instance.credit_note_prefix:
            return value
        try:
            INVOICE_PREFIX_VALIDATOR(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

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

    def get_issuer(self, obj):
        """Today's issuer, ``{party, display_name}``, or ``None`` (#761).

        Reads ``issuer_roles`` when the viewset prefetched them, so a list
        costs one query for all its ZEVs.
        """
        today = timezone.localdate()
        rows = getattr(obj, "issuer_roles", None)
        if rows is None:
            rows = obj.party_roles.filter(role=PartyRole.ISSUER).select_related("party")
        for row in rows:
            if row.role == PartyRole.ISSUER and row.valid_from <= today and (row.valid_to is None or row.valid_to >= today):
                return {"party": str(row.party_id), "display_name": row.party.display_name}
        return None

    class Meta:
        model = Zev
        fields = "__all__"
        # disabled_at/disabled_by/disabled_reason are read-only here so a
        # PATCH cannot re-enable a ZEV (or disable one) outside
        # ZevViewSet.disable/enable, which carry the admin-only rule on
        # enable that a writable field on this serializer would bypass.
        read_only_fields = [
            "id", "created_at", "updated_at",
            "disabled_at", "disabled_by", "disabled_reason",
        ]


class ZevDetailSerializer(ZevSerializer):
    participants = ParticipantSerializer(many=True, read_only=True)


class ZevOwnerAccountSerializer(serializers.Serializer):
    """The responsible person: a new account, or ``account`` — the id of an existing one.

    With ``account`` the name and email come from that account, which is left
    as it is; ``username``, ``first_name``, ``last_name`` and ``email`` are then ignored.
    """

    account = serializers.IntegerField(required=False, min_value=1)
    username = serializers.CharField(required=False, allow_blank=True, max_length=150)
    title = serializers.ChoiceField(choices=Participant.Title.choices, required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, max_length=100)
    last_name = serializers.CharField(required=False, max_length=100)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    address_line1 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    address_line2 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def to_internal_value(self, data):
        # An existing account is used as it is, so the new-person checks below
        # (taken email or username) must not reject what is merely ignored.
        if isinstance(data, dict) and data.get('account') not in (None, ''):
            data = {key: value for key, value in data.items() if key not in {'username', 'first_name', 'last_name', 'email'}}
        return super().to_internal_value(data)

    def validate_email(self, value: str) -> str:
        if email_change.address_in_use(value):
            raise serializers.ValidationError(email_change.ADDRESS_IN_USE_MESSAGE)
        return value

    def validate_username(self, value: str) -> str:
        username = value.strip()
        if not username:
            return username
        user_model = self.context['request'].user.__class__
        if user_model.objects.filter(username=username).exists():
            raise serializers.ValidationError('This username is already taken.')
        return username

    def validate_account(self, value: int):
        user = self.context['request'].user.__class__.objects.filter(pk=value).first()
        if user is None:
            raise serializers.ValidationError('This account no longer exists.')
        problem = existing_owner_problem(user)
        if problem:
            raise serializers.ValidationError(problem)
        return user

    def validate(self, attrs):
        if 'account' not in attrs:
            missing = {
                field: 'This field is required.'
                for field in ('first_name', 'last_name', 'email') if not attrs.get(field)
            }
            if missing:
                raise serializers.ValidationError(missing)
        return attrs


class SelfSetupOwnerAddressSerializer(serializers.Serializer):
    """The address copied to the participant created by self-setup."""

    address_line1 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    address_line2 = serializers.CharField(required=False, allow_blank=True, max_length=200)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)


class OwnerMeteringPointInputSerializer(serializers.Serializer):
    meter_id = serializers.CharField(max_length=100)
    meter_type = serializers.ChoiceField(choices=MeteringPoint._meta.get_field('meter_type').choices)
    is_active = serializers.BooleanField(required=False, default=True)
    location_description = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ZevCreateWithOwnerSerializer(BankIbanValidationMixin, serializers.Serializer):
    name = serializers.CharField(max_length=200)
    start_date = serializers.DateField()
    zev_type = serializers.ChoiceField(choices=Zev._meta.get_field('zev_type').choices)
    billing_interval = serializers.ChoiceField(choices=Zev._meta.get_field('billing_interval').choices)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=10)
    grid_operator = serializers.CharField(required=False, allow_blank=True, max_length=200)
    grid_connection_point = serializers.CharField(required=False, allow_blank=True, max_length=200)
    # The wizard sends an empty prefix when the field is left alone; that means "use the default".
    invoice_prefix = serializers.CharField(
        required=False, allow_blank=True, max_length=10, validators=[INVOICE_PREFIX_VALIDATOR]
    )
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
        owner = attrs.get("owner", {})
        if not has_required_iban_address(
            attrs.get("bank_iban"),
            address_line1=owner.get("address_line1"),
            postal_code=owner.get("postal_code"),
            city=owner.get("city"),
        ):
            raise serializers.ValidationError({"owner": IBAN_ADDRESS_REQUIRED_MESSAGE})
        return attrs

    def create(self, validated_data):
        owner_data = validated_data.pop('owner')
        metering_points_data = validated_data.pop('metering_points')
        if not validated_data.get('invoice_prefix'):
            validated_data.pop('invoice_prefix', None)
        try:
            return create_zev_with_owner_setup(
                zev_data=validated_data,
                owner_data=owner_data,
                metering_points_data=metering_points_data,
            )
        except DjangoValidationError as exc:
            raise django_validation_error(exc)
