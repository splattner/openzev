"""Buildings between a ZEV and its metering points (#890, ADR 0029, SPEC-2026-10-buildings-and-sites)."""

from datetime import date
from importlib import import_module
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from testing.helpers import authenticate, create_managed_zev, make_user

from .buildings import (
    address_key,
    assign_buildings_from_participants,
    building_name_for,
    default_building,
    ensure_initial_building,
    initial_building_fields,
)
from .models import (
    Building,
    MeteringPoint,
    MeteringPointAssignment,
    Participant,
    Party,
    PartyRole,
    ZevAccessGrant,
    ZevAccessRole,
    ZevPartyRole,
)
from .parties import assign_role, ensure_initial_roles, set_landowner_building

START = date(2026, 1, 1)
BUILDINGS = "/api/v1/zev/buildings/"
POINTS = "/api/v1/zev/metering-points/"
ROLES = "/api/v1/zev/party-roles/"


def make_zev(name="Building ZEV", zev_type="vzev", **fields):
    owner = make_user(f"owner_{name.replace(' ', '_').lower()}", UserRole.USER)
    return create_managed_zev(name=name, owner=owner, zev_type=zev_type, invoice_prefix="B", start_date=START, **fields)


def person(zev, last_name, address_line1="", postal_code="", city="", **fields):
    return Participant.objects.create(
        zev=zev, first_name="P", last_name=last_name, email=f"{last_name.lower()}@example.com",
        address_line1=address_line1, postal_code=postal_code, city=city, valid_from=START, **fields,
    )


def make_building(zev, name="Haus A", **fields):
    return Building.objects.create(zev=zev, name=name, **fields)


class BuildingModelTests(TestCase):
    def setUp(self):
        self.zev = make_zev()

    def test_an_egid_is_unique_within_a_zev_only(self):
        make_building(self.zev, "A", egid=1234)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_building(self.zev, "B", egid=1234)
        make_building(self.zev, "C")
        make_building(self.zev, "D")  # no EGID: any number
        make_building(make_zev("Other ZEV"), "E", egid=1234)

    def test_an_egid_has_at_most_nine_digits(self):
        with self.assertRaises(ValidationError) as caught:
            Building(zev=self.zev, name="X", egid=1_000_000_000).full_clean()
        self.assertIn("egid", caught.exception.message_dict)

    def test_address_lines_drop_blanks(self):
        building = Building(zev=self.zev, name="X", address_line1="Weg 1", postal_code="3000", city="Bern")
        self.assertEqual(building.address_lines, ["Weg 1", "3000 Bern"])

    def test_a_metering_point_without_a_building_gets_the_default_one_created(self):
        self.assertFalse(Building.objects.filter(zev=self.zev).exists())
        point = MeteringPoint.objects.create(zev=self.zev, meter_id="M-1")
        building = Building.objects.get(zev=self.zev)
        self.assertEqual(point.building, building)
        self.assertEqual(building.name, self.zev.name)

    def test_a_metering_point_without_a_building_uses_the_oldest_one(self):
        first = make_building(self.zev, "First")
        make_building(self.zev, "Second")
        self.assertEqual(MeteringPoint.objects.create(zev=self.zev, meter_id="M-1").building, first)
        self.assertEqual(Building.objects.filter(zev=self.zev).count(), 2)

    def test_a_building_of_another_zev_is_rejected(self):
        other = make_building(make_zev("Other ZEV"), "Elsewhere")
        point = MeteringPoint(zev=self.zev, meter_id="M-1", building=other)
        with self.assertRaises(ValidationError) as caught:
            point.full_clean()
        self.assertEqual(caught.exception.message_dict["building"], ["The building belongs to another ZEV."])

    def test_a_building_with_metering_points_cannot_be_deleted_in_the_database(self):
        point = MeteringPoint.objects.create(zev=self.zev, meter_id="M-1")
        from django.db.models import RestrictedError

        with self.assertRaises(RestrictedError):
            point.building.delete()


class InitialBuildingFieldsTests(TestCase):
    def issuer_zev(self, issuer_postal="3000", zev_postal="3000", address="Solarweg 1"):
        zev = make_zev(postal_code=zev_postal)
        participant = person(zev, "Issuer", address, issuer_postal, "Bern")
        ensure_initial_roles(zev, participant.party, START)
        return zev

    def test_the_issuer_address_is_copied_when_the_postal_codes_match(self):
        fields = initial_building_fields(self.issuer_zev())
        self.assertEqual(fields["name"], "Solarweg 1")
        self.assertEqual((fields["address_line1"], fields["postal_code"], fields["city"]), ("Solarweg 1", "3000", "Bern"))

    def test_the_issuer_address_is_copied_when_the_zev_has_no_postal_code(self):
        fields = initial_building_fields(self.issuer_zev(zev_postal=""))
        self.assertEqual(fields["address_line1"], "Solarweg 1")

    def test_only_the_zev_postal_code_is_used_when_the_issuer_lives_elsewhere(self):
        zev = self.issuer_zev(issuer_postal="8000", zev_postal="3000")
        fields = initial_building_fields(zev)
        self.assertEqual(fields, {
            "name": zev.name, "address_line1": "", "address_line2": "", "postal_code": "3000", "city": "",
        })

    def test_without_an_issuer_it_is_named_after_the_zev(self):
        zev = make_zev(postal_code="3000")
        self.assertEqual(initial_building_fields(zev)["name"], zev.name)
        self.assertEqual(initial_building_fields(zev)["postal_code"], "3000")

    def test_an_issuer_without_a_street_line_does_not_count(self):
        zev = self.issuer_zev(address="")
        self.assertEqual(initial_building_fields(zev)["address_line1"], "")

    def test_names(self):
        self.assertEqual(building_name_for("Weg 1", "3000", "Bern", "Z"), "Weg 1")
        self.assertEqual(building_name_for("", "3000", "Bern", "Z"), "3000 Bern")
        self.assertEqual(building_name_for("", "", "", "Z"), "Z")

    def test_address_keys_ignore_case_and_blanks(self):
        zev = make_zev()
        a = Party(zev=zev, last_name="A", address_line1=" Weg 1 ", postal_code="3000", city="BERN")
        b = Party(zev=zev, last_name="B", address_line1="weg 1", postal_code="3000", city="Bern")
        self.assertEqual(address_key(a), address_key(b))
        self.assertIsNone(address_key(Party(zev=zev, last_name="C")))


class ParticipantAddressRuleTests(TestCase):
    """The rule shared with the transfer importer (SPEC §4.5), on live models."""

    def setUp(self):
        self.zev = make_zev()
        self.anna = person(self.zev, "Anna", "Weg 1", "3000", "Bern")
        self.ben = person(self.zev, "Ben", "Weg 2", "3000", "Bern")
        self.clara = person(self.zev, "Clara", "weg 2", "3000", "BERN")  # shares Ben's building
        self.dora = person(self.zev, "Dora")  # no address
        ensure_initial_roles(self.zev, self.anna.party, START)

    def point(self, meter_id, *holders, valid_from=START):
        point = MeteringPoint.objects.create(zev=self.zev, meter_id=meter_id)
        # bulk_create: the model refuses overlapping assignments, data from before that rule may not.
        MeteringPointAssignment.objects.bulk_create(
            MeteringPointAssignment(metering_point=point, participant=holder, valid_from=valid_from) for holder in holders
        )
        return point

    def assign(self, *points):
        assign_buildings_from_participants(self.zev, points)
        return {point.meter_id: Building.objects.get(pk=point.building_id) for point in points}

    def test_a_building_per_distinct_participant_address(self):
        placed = self.assign(self.point("A", self.anna), self.point("B", self.ben), self.point("C", self.clara))
        self.assertEqual(placed["A"].address_line1, "Weg 1")
        self.assertEqual(placed["B"], placed["C"])
        self.assertEqual(placed["B"].address_line1, "Weg 2")
        self.assertEqual(Building.objects.filter(zev=self.zev).count(), 2)

    def test_a_point_shared_across_buildings_goes_to_the_default_building(self):
        placed = self.assign(self.point("S", self.anna, self.ben))
        # The issuer (Anna) lives at Weg 1: her building is the default.
        self.assertEqual(placed["S"].address_line1, "Weg 1")

    def test_an_unassigned_point_and_an_assignee_without_address_go_to_the_default_building(self):
        placed = self.assign(self.point("U"), self.point("D", self.dora))
        self.assertEqual(placed["U"].address_line1, "Weg 1")
        self.assertEqual(placed["D"], placed["U"])

    def test_the_latest_assignment_decides(self):
        point = self.point("L", self.anna, valid_from=START)
        MeteringPointAssignment.objects.filter(metering_point=point).update(valid_to=date(2026, 3, 31))
        MeteringPointAssignment.objects.create(metering_point=point, participant=self.ben, valid_from=date(2026, 4, 1))
        self.assertEqual(self.assign(point)["L"].address_line1, "Weg 2")

    def test_without_an_issuer_address_the_default_building_carries_the_zev_postal_code(self):
        ZevPartyRole.objects.all().delete()
        self.zev.postal_code = "3000"
        self.zev.save()
        placed = self.assign(self.point("U"))
        self.assertEqual(placed["U"].name, self.zev.name)
        self.assertEqual(placed["U"].address_line1, "")
        self.assertEqual(placed["U"].postal_code, "3000")

    def test_a_zev_keeps_everything_in_one_building(self):
        self.zev.zev_type = "zev"
        self.zev.save()
        placed = self.assign(self.point("A", self.anna), self.point("B", self.ben))
        self.assertEqual(placed["A"], placed["B"])
        self.assertEqual(Building.objects.filter(zev=self.zev).count(), 1)

    def test_a_vzev_without_addresses_or_points_still_gets_a_building(self):
        zev = make_zev("Empty vZEV")
        assign_buildings_from_participants(zev, [])
        self.assertEqual(Building.objects.filter(zev=zev).count(), 1)


class BuildingMigrationTests(TransactionTestCase):
    BEFORE = [("zev", "0039_end_grants_covered_by_roles")]
    AFTER = [("zev", "0042_meteringpoint_building_required")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        self.tearDown()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_zevs_get_one_building_and_vzevs_one_per_participant_address(self):
        old = self.migrate(self.BEFORE)
        Zev, Party_, Participant_ = (old.get_model("zev", name) for name in ("Zev", "Party", "Participant"))
        Point, Assignment, Role = (old.get_model("zev", name) for name in ("MeteringPoint", "MeteringPointAssignment", "ZevPartyRole"))

        def member(zev, last_name, address, postal="3000", city="Bern"):
            party = Party_.objects.create(
                zev=zev, last_name=last_name, sort_name=last_name, address_line1=address, postal_code=postal, city=city,
            )
            return Participant_.objects.create(zev=zev, party=party, valid_from=START)

        def point(zev, meter_id, *holders):
            row = Point.objects.create(zev=zev, meter_id=meter_id)
            for holder in holders:
                Assignment.objects.create(metering_point=row, participant=holder, valid_from=START)
            return row

        zev = Zev.objects.create(name="One property", zev_type="zev", postal_code="3000")
        owner = member(zev, "Owner", "Solarweg 1")
        Role.objects.create(zev=zev, party=owner.party, role="issuer", valid_from=START)
        one, two = point(zev, "Z-1", owner), point(zev, "Z-2")

        vzev = Zev.objects.create(name="Several", zev_type="vzev", postal_code="3000")
        anna, ben = member(vzev, "Anna", "Weg 1"), member(vzev, "Ben", "Weg 2")
        clara, dora = member(vzev, "Clara", "WEG 2"), member(vzev, "Dora", "")
        Role.objects.create(zev=vzev, party=anna.party, role="issuer", valid_from=START)
        points = {
            "own": point(vzev, "V-ANNA", anna),
            "shared house": point(vzev, "V-BEN", ben, clara),
            "split": point(vzev, "V-SPLIT", anna, ben),
            "none": point(vzev, "V-NONE"),
            "no address": point(vzev, "V-DORA", dora),
        }
        empty = Zev.objects.create(name="Empty vZEV", zev_type="vzev", postal_code="8000")

        new = self.migrate(self.AFTER)
        Building_, Point_ = new.get_model("zev", "Building"), new.get_model("zev", "MeteringPoint")
        where = lambda row: Building_.objects.get(pk=Point_.objects.get(pk=row.pk).building_id)  # noqa: E731

        # A ZEV: one building with the issuer's address, every point in it.
        self.assertEqual(Building_.objects.filter(zev_id=zev.pk).count(), 1)
        self.assertEqual(where(one), where(two))
        self.assertEqual(where(one).address_line1, "Solarweg 1")

        # A vZEV: a building per distinct address (Ben and Clara share one).
        self.assertEqual(
            sorted(Building_.objects.filter(zev_id=vzev.pk).values_list("address_line1", flat=True)),
            ["Weg 1", "Weg 2"],
        )
        self.assertEqual(where(points["own"]).address_line1, "Weg 1")
        self.assertEqual(where(points["shared house"]).address_line1, "Weg 2")
        # Latest assignees in several buildings, nobody, or no address: the issuer's building.
        for name in ("split", "none", "no address"):
            self.assertEqual(where(points[name]), where(points["own"]), name)

        # No address and no point: still a building, from the ZEV's postal code.
        building = Building_.objects.get(zev_id=empty.pk)
        self.assertEqual((building.name, building.postal_code, building.address_line1), ("Empty vZEV", "8000", ""))


class BuildingApiTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.other_zev = make_zev("Other ZEV")
        self.admin = make_user("b_admin", UserRole.ADMIN)
        self.manager = make_user("b_manager")
        self.viewer = make_user("b_viewer")
        self.stranger = make_user("b_stranger")
        ZevAccessGrant.objects.create(zev=self.zev, user=self.manager, role=ZevAccessRole.MANAGER, valid_from=START)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER, valid_from=START)
        self.building = make_building(self.zev, "Haus A", egid=11)
        self.foreign = make_building(self.other_zev, "Fremd")

    def client_for(self, user):
        client = APIClient()
        authenticate(client, user)
        return client

    def payload(self, **fields):
        return {"zev": str(self.zev.pk), "name": "Haus B", **fields}

    def test_admin_and_manager_create_update_and_delete(self):
        for user in (self.admin, self.manager):
            client = self.client_for(user)
            created = client.post(BUILDINGS, self.payload(name=f"B {user.username}", address_line1="Weg 1"), format="json")
            self.assertEqual(created.status_code, 201, created.data)
            self.assertEqual(created.data["metering_point_count"], 0)
            url = f"{BUILDINGS}{created.data['id']}/"
            self.assertEqual(client.patch(url, {"city": "Bern"}, format="json").data["city"], "Bern")
            self.assertEqual(client.delete(url).status_code, 204)

    def test_a_viewer_reads_but_cannot_write(self):
        client = self.client_for(self.viewer)
        listing = client.get(BUILDINGS, {"zev_id": str(self.zev.pk)})
        self.assertEqual([row["name"] for row in listing.data["results"]], ["Haus A"])
        self.assertEqual(client.get(f"{BUILDINGS}{self.building.pk}/").status_code, 200)
        self.assertEqual(client.post(BUILDINGS, self.payload(), format="json").status_code, 403)
        self.assertEqual(client.patch(f"{BUILDINGS}{self.building.pk}/", {"city": "X"}, format="json").status_code, 403)
        self.assertEqual(client.delete(f"{BUILDINGS}{self.building.pk}/").status_code, 403)

    def test_a_participant_has_no_building_endpoint(self):
        participant = person(self.zev, "Resident")
        participant.user = self.stranger
        participant.save(update_fields=["user"])
        client = self.client_for(self.stranger)
        self.assertIn(client.get(BUILDINGS).status_code, (403, 404))
        self.assertIn(client.get(f"{BUILDINGS}{self.building.pk}/").status_code, (403, 404))

    def test_an_unrelated_account_sees_nothing(self):
        client = self.client_for(self.stranger)
        self.assertIn(client.get(BUILDINGS).status_code, (200, 403))
        self.assertNotEqual(client.get(f"{BUILDINGS}{self.building.pk}/").status_code, 200)
        self.assertIn(client.post(BUILDINGS, self.payload(), format="json").status_code, (400, 403))
        self.assertFalse(Building.objects.filter(name="Haus B").exists())

    def test_a_manager_cannot_reach_another_zev(self):
        client = self.client_for(self.manager)
        self.assertEqual(client.get(f"{BUILDINGS}{self.foreign.pk}/").status_code, 404)
        self.assertEqual(client.post(BUILDINGS, {"zev": str(self.other_zev.pk), "name": "X"}, format="json").status_code, 400)

    def test_a_building_cannot_move_to_another_zev(self):
        response = self.client_for(self.admin).patch(
            f"{BUILDINGS}{self.building.pk}/", {"zev": str(self.other_zev.pk)}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["zev"][0], "A building cannot move to another ZEV.")

    def test_deleting_a_building_with_metering_points_is_refused(self):
        MeteringPoint.objects.create(zev=self.zev, meter_id="M-1", building=self.building)
        response = self.client_for(self.manager).delete(f"{BUILDINGS}{self.building.pk}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "This building still has metering points.")
        self.assertTrue(Building.objects.filter(pk=self.building.pk).exists())

    def test_deleting_a_building_unlinks_its_landowner_roles(self):
        party = person(self.zev, "Land").party
        row = assign_role(self.zev, party, PartyRole.LANDOWNER, START, building=self.building)
        self.assertEqual(self.client_for(self.manager).delete(f"{BUILDINGS}{self.building.pk}/").status_code, 204)
        row.refresh_from_db()
        self.assertIsNone(row.building_id)

    def test_a_duplicate_egid_is_refused(self):
        client = self.client_for(self.manager)
        response = client.post(BUILDINGS, self.payload(egid=11), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["egid"][0], "Another building of this ZEV has this EGID.")
        second = make_building(self.zev, "Haus C", egid=12)
        patched = client.patch(f"{BUILDINGS}{second.pk}/", {"egid": 11}, format="json")
        self.assertEqual(patched.status_code, 400)
        self.assertEqual(client.patch(f"{BUILDINGS}{second.pk}/", {"egid": 12}, format="json").status_code, 200)

    def test_the_list_counts_metering_points(self):
        MeteringPoint.objects.create(zev=self.zev, meter_id="M-1", building=self.building)
        MeteringPoint.objects.create(zev=self.zev, meter_id="M-2", building=self.building)
        rows = self.client_for(self.manager).get(BUILDINGS, {"zev_id": str(self.zev.pk)}).data["results"]
        self.assertEqual(rows[0]["metering_point_count"], 2)

    def test_a_disabled_zev_is_read_only_for_a_manager(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save()
        client = self.client_for(self.manager)
        self.assertEqual(client.get(f"{BUILDINGS}{self.building.pk}/").status_code, 200)
        self.assertEqual(client.patch(f"{BUILDINGS}{self.building.pk}/", {"city": "X"}, format="json").status_code, 403)
        self.assertEqual(client.post(BUILDINGS, self.payload(), format="json").status_code, 400)
        self.assertEqual(self.client_for(self.admin).patch(
            f"{BUILDINGS}{self.building.pk}/", {"city": "X"}, format="json").status_code, 200)

    def test_writes_are_audited(self):
        client = self.client_for(self.manager)
        created = client.post(BUILDINGS, self.payload(), format="json")
        client.patch(f"{BUILDINGS}{created.data['id']}/", {"city": "Bern"}, format="json")
        client.delete(f"{BUILDINGS}{created.data['id']}/")
        types = list(AuditEvent.objects.filter(target_type="zev.Building").values_list("action_type", flat=True))
        self.assertEqual(len(types), 3)
        self.assertIn("building.update", types)


class MeteringPointBuildingApiTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.admin = make_user("mp_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def body(self, meter_id="M-NEW", **fields):
        return {"zev": str(self.zev.pk), "meter_id": meter_id, "meter_type": "consumption", **fields}

    def test_the_only_building_is_used_implicitly(self):
        building = make_building(self.zev)
        response = self.client.post(POINTS, self.body(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["building"]), str(building.pk))
        self.assertEqual(response.data["building_name"], "Haus A")

    def test_a_zev_without_buildings_gets_its_default_building(self):
        response = self.client.post(POINTS, self.body(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Building.objects.filter(zev=self.zev).count(), 1)

    def test_a_refused_write_creates_no_building_in_a_foreign_zev(self):
        # Validation runs before the scope check: it must not write into a ZEV
        # the caller cannot manage, even one with no building yet.
        manager = make_user("mp_other_manager", UserRole.USER)
        create_managed_zev(
            name="Manager ZEV", owner=manager, invoice_prefix="M", start_date=START,
        )
        client = APIClient()
        authenticate(client, manager)
        response = client.post(POINTS, self.body(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Building.objects.filter(zev=self.zev).exists())

    def test_several_buildings_require_a_choice(self):
        first, second = make_building(self.zev, "Haus A"), make_building(self.zev, "Haus B")
        refused = self.client.post(POINTS, self.body(), format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.data["building"][0], "Choose the building of this metering point.")
        created = self.client.post(POINTS, self.body(building=str(second.pk)), format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(str(created.data["building"]), str(second.pk))
        moved = self.client.patch(f"{POINTS}{created.data['id']}/", {"building": str(first.pk)}, format="json")
        self.assertEqual(moved.data["building_name"], "Haus A")

    def test_a_building_of_another_zev_is_rejected(self):
        other = make_building(make_zev("Other ZEV"), "Fremd")
        make_building(self.zev)
        response = self.client.post(POINTS, self.body(building=str(other.pk)), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["building"][0], "The building belongs to another ZEV.")
        point = MeteringPoint.objects.create(zev=self.zev, meter_id="M-OWN")
        patched = self.client.patch(f"{POINTS}{point.pk}/", {"building": str(other.pk)}, format="json")
        self.assertEqual(patched.status_code, 400)

    def test_the_list_filters_by_building(self):
        first, second = make_building(self.zev, "Haus A"), make_building(self.zev, "Haus B")
        MeteringPoint.objects.create(zev=self.zev, meter_id="M-1", building=first)
        MeteringPoint.objects.create(zev=self.zev, meter_id="M-2", building=second)
        rows = self.client.get(POINTS, {"building": str(second.pk)}).data["results"]
        self.assertEqual([row["meter_id"] for row in rows], ["M-2"])


class LandownerBuildingTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.house_a, self.house_b = make_building(self.zev, "Haus A"), make_building(self.zev, "Haus B")
        self.party = Party.objects.create(zev=self.zev, last_name="Land")
        self.admin = make_user("lo_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def assign(self, role=PartyRole.LANDOWNER, **fields):
        return self.client.post(ROLES, {
            "zev": str(self.zev.pk), "party": str(self.party.pk), "role": role, "valid_from": "2026-01-01", **fields,
        }, format="json")

    def test_a_landowner_can_name_its_building(self):
        response = self.assign(building=str(self.house_a.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((str(response.data["building"]), response.data["building_name"]), (str(self.house_a.pk), "Haus A"))

    def test_no_building_stays_not_specified(self):
        response = self.assign()
        self.assertEqual((response.data["building"], response.data["building_name"]), (None, None))

    def test_another_role_cannot_name_a_building(self):
        response = self.assign(role=PartyRole.REPRESENTATIVE, building=str(self.house_a.pk))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["building"][0], "Only a landowner role names a building.")
        with self.assertRaises(ValidationError):
            assign_role(self.zev, self.party, PartyRole.ISSUER, START, building=self.house_a)

    def test_a_building_of_another_zev_is_refused(self):
        other = make_building(make_zev("Other ZEV"), "Fremd")
        self.assertEqual(self.assign(building=str(other.pk)).status_code, 400)

    def test_one_party_can_own_two_buildings_but_not_one_twice(self):
        self.assertEqual(self.assign(building=str(self.house_a.pk)).status_code, 201)
        self.assertEqual(self.assign(building=str(self.house_b.pk)).status_code, 201)
        twice = self.assign(building=str(self.house_a.pk))
        self.assertEqual(twice.status_code, 400)
        self.assertEqual(twice.data["party"][0], "The party already owns this building.")
        self.assertEqual(self.assign().status_code, 201)  # "not specified" is its own slot
        self.assertEqual(self.assign().status_code, 400)

    def test_the_database_allows_one_open_row_per_party_and_building(self):
        ZevPartyRole.objects.create(zev=self.zev, party=self.party, role="landowner", valid_from=START, building=self.house_a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZevPartyRole.objects.create(zev=self.zev, party=self.party, role="landowner", valid_from=START, building=self.house_a)
        ZevPartyRole.objects.create(zev=self.zev, party=self.party, role="landowner", valid_from=START)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ZevPartyRole.objects.create(zev=self.zev, party=self.party, role="landowner", valid_from=START)

    def test_the_building_action_changes_the_building_and_is_audited(self):
        row = assign_role(self.zev, self.party, PartyRole.LANDOWNER, START)
        response = self.client.post(f"{ROLES}{row.pk}/building/", {"building": str(self.house_b.pk)}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["building_name"], "Haus B")
        row.refresh_from_db()
        self.assertEqual((row.building_id, row.valid_from, row.valid_to), (self.house_b.pk, START, None))
        event = AuditEvent.objects.get(action_type="party_role.building")
        self.assertEqual(event.metadata_json["building"], str(self.house_b.pk))
        cleared = self.client.post(f"{ROLES}{row.pk}/building/", {"building": None}, format="json")
        self.assertIsNone(cleared.data["building"])

    def test_the_building_action_refuses_other_roles_and_duplicates(self):
        issuer = assign_role(self.zev, self.party, PartyRole.ISSUER, START)
        refused = self.client.post(f"{ROLES}{issuer.pk}/building/", {"building": str(self.house_a.pk)}, format="json")
        self.assertEqual(refused.status_code, 400)
        assign_role(self.zev, self.party, PartyRole.LANDOWNER, START, building=self.house_a)
        free = assign_role(self.zev, self.party, PartyRole.LANDOWNER, START)
        with self.assertRaises(ValidationError):
            set_landowner_building(free, self.house_a)
        duplicate = self.client.post(f"{ROLES}{free.pk}/building/", {"building": str(self.house_a.pk)}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_a_viewer_cannot_change_a_building(self):
        viewer = make_user("lo_viewer")
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=START)
        row = assign_role(self.zev, self.party, PartyRole.LANDOWNER, START)
        client = APIClient()
        authenticate(client, viewer)
        self.assertEqual(client.post(f"{ROLES}{row.pk}/building/", {"building": str(self.house_a.pk)}, format="json").status_code, 403)


class CreationFlowTests(TestCase):
    def setUp(self):
        self.admin = make_user("flow_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def test_the_admin_wizard_creates_one_building_with_the_issuer_address_and_attaches_the_points(self):
        with mock.patch("zev.tasks.warm_building_geocode_cache_task.delay"):
            response = self.client.post("/api/v1/zev/zevs/create-with-owner/", {
                "name": "Wizard", "start_date": "2026-03-01", "zev_type": "vzev", "billing_interval": "monthly",
                "postal_code": "8000",
                "owner": {
                    "first_name": "Oscar", "last_name": "Owner", "email": "oscar@example.com",
                    "address_line1": "Owner Street 1", "postal_code": "8000", "city": "Zurich",
                },
                "metering_points": [
                    {"meter_id": "W-1", "meter_type": "consumption"},
                    {"meter_id": "W-2", "meter_type": "production"},
                ],
            }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        building = Building.objects.get(zev_id=response.data["zev"]["id"])
        self.assertEqual((building.name, building.address_line1, building.postal_code, building.city),
                         ("Owner Street 1", "Owner Street 1", "8000", "Zurich"))
        self.assertEqual(set(building.metering_points.values_list("meter_id", flat=True)), {"W-1", "W-2"})

    def test_self_setup_creates_one_building_with_the_owner_address(self):
        owner = make_user("flow_owner", may_create_zev=True)
        client = APIClient()
        authenticate(client, owner)
        response = client.post("/api/v1/zev/zevs/self-setup/", {
            "name": "Self", "start_date": "2026-04-01", "zev_type": "zev", "billing_interval": "annual",
            "owner_address_line1": "Example 1", "owner_postal_code": "8000", "owner_city": "Zurich",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        building = Building.objects.get(zev_id=response.data["zev"]["id"])
        self.assertEqual((building.address_line1, building.postal_code, building.city), ("Example 1", "8000", "Zurich"))

    def test_a_different_issuer_postal_code_leaves_only_the_zev_postal_code(self):
        owner = make_user("flow_owner2", may_create_zev=True)
        client = APIClient()
        authenticate(client, owner)
        response = client.post("/api/v1/zev/zevs/self-setup/", {
            "name": "Self 2", "start_date": "2026-04-01", "zev_type": "zev", "billing_interval": "annual",
            "postal_code": "3000",
            "owner_address_line1": "Example 1", "owner_postal_code": "8000", "owner_city": "Zurich",
        }, format="json")
        building = Building.objects.get(zev_id=response.data["zev"]["id"])
        self.assertEqual((building.name, building.address_line1, building.postal_code), ("Self 2", "", "3000"))

    def test_admin_create_makes_one_building_from_the_postal_code(self):
        response = self.client.post("/api/v1/zev/zevs/", {
            "name": "Plain", "start_date": "2026-04-01", "zev_type": "vzev", "billing_interval": "monthly",
            "postal_code": "3000",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        building = Building.objects.get(zev_id=response.data["id"])
        self.assertEqual((building.name, building.postal_code), ("Plain", "3000"))

    def test_ensure_initial_building_is_idempotent(self):
        zev = make_zev()
        self.assertEqual(ensure_initial_building(zev), ensure_initial_building(zev))
        self.assertEqual(default_building(zev), ensure_initial_building(zev))
        self.assertEqual(Building.objects.filter(zev=zev).count(), 1)

    def test_the_default_building_helper_module_is_importable_by_the_migration_rule(self):
        # The data migration re-implements the rule on historical models; keep the file there.
        self.assertTrue(hasattr(import_module("zev.migrations.0041_buildings_from_existing_data"), "to_buildings"))


class BuildingMapTests(TestCase):
    """The participants map draws buildings (ADR 0012 amended, SPEC §7.7)."""

    def setUp(self):
        self.zev = make_zev()
        self.admin = make_user("map_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        self.house = make_building(self.zev, "Haus A", address_line1="Weg 1", postal_code="3000", city="Bern")
        self.empty = make_building(self.zev, "Haus B")

    def rows(self):
        results = self.client.get(BUILDINGS, {"zev_id": str(self.zev.pk)}).data["results"]
        return {row["name"]: row for row in results}

    def test_current_participants_are_those_assigned_today_to_its_points(self):
        anna, ben, old = person(self.zev, "Anna"), person(self.zev, "Ben"), person(self.zev, "Alt")
        p1 = MeteringPoint.objects.create(zev=self.zev, meter_id="MAP-1", building=self.house)
        p2 = MeteringPoint.objects.create(zev=self.zev, meter_id="MAP-2", building=self.house)
        MeteringPointAssignment.objects.create(metering_point=p1, participant=ben, valid_from=START)
        MeteringPointAssignment.objects.create(metering_point=p2, participant=anna, valid_from=START)
        MeteringPointAssignment.objects.create(
            metering_point=p2, participant=old, valid_from=date(2025, 1, 1), valid_to=date(2025, 12, 31))
        rows = self.rows()
        self.assertEqual([p["display_name"] for p in rows["Haus A"]["current_participants"]], ["P Anna", "P Ben"])
        self.assertEqual(rows["Haus B"]["current_participants"], [])

    def test_no_n_plus_one_for_participants(self):
        for i in range(4):
            building = make_building(self.zev, f"X{i}")
            point = MeteringPoint.objects.create(zev=self.zev, meter_id=f"N-{i}", building=building)
            MeteringPointAssignment.objects.create(metering_point=point, participant=person(self.zev, f"N{i}"), valid_from=START)
        with self.assertNumQueries(self.count_queries()):
            self.rows()

    def count_queries(self):
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            self.rows()
        for i in range(3):
            building = make_building(self.zev, f"Y{i}")
            point = MeteringPoint.objects.create(zev=self.zev, meter_id=f"Y-{i}", building=building)
            MeteringPointAssignment.objects.create(metering_point=point, participant=person(self.zev, f"Y{i}"), valid_from=START)
        return len(small)

    def test_the_footprint_comes_from_the_cache_only(self):
        polygon = {"type": "Polygon", "coordinates": [[[7, 46], [7.1, 46], [7.1, 46.1], [7, 46]]]}
        with mock.patch("zev.serializers.get_cached_building_footprint", return_value=polygon) as cached:
            self.assertEqual(self.rows()["Haus A"]["building_footprint"], polygon)
        cached.assert_any_call("Weg 1", "3000", "Bern")

    def test_creating_and_updating_a_building_enqueues_a_lookup(self):
        from accounts.models import FeatureFlag

        FeatureFlag.objects.update_or_create(name=FeatureFlag.PARTICIPANT_GEOCODING_ENABLED, defaults={"enabled": True})
        with mock.patch("zev.tasks.warm_building_geocode_cache_task.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(BUILDINGS, {
                "zev": str(self.zev.pk), "name": "Neu", "address_line1": "Gasse 2", "city": "Thun"}, format="json")
            self.client.patch(f"{BUILDINGS}{created.data['id']}/", {"city": "Bern"}, format="json")
            ensure_initial_building(make_zev("Fresh ZEV", postal_code="3000"))
        self.assertEqual(delay.call_count, 2)  # the initial building has no street line

    def test_participant_addresses_are_no_longer_geocoded(self):
        from accounts.models import FeatureFlag

        FeatureFlag.objects.update_or_create(name=FeatureFlag.PARTICIPANT_GEOCODING_ENABLED, defaults={"enabled": True})
        with mock.patch("zev.tasks.warm_building_geocode_cache_task.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/v1/zev/participants/", {
                "zev": str(self.zev.pk), "first_name": "N", "last_name": "New", "email": "n@example.com",
                "address_line1": "Weg 9", "postal_code": "3000", "city": "Bern", "valid_from": "2026-01-01"}, format="json")
        delay.assert_not_called()
        self.assertNotIn("building_footprint", self.client.get("/api/v1/zev/participants/").data["results"][0])
