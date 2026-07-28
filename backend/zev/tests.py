from datetime import date, datetime, timezone
from unittest import mock

from django.test import TestCase
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from zev.management.commands.seed_demo import previous_quarter, quarter_start
from metering.models import MeterReading
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev


from testing.helpers import authenticate as auth, make_user


class ParticipantEndpointRestrictionTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("zev_owner_case", UserRole.ZEV_OWNER)
		self.participant_user = make_user("participant_case", UserRole.PARTICIPANT)

		self.zev = Zev.objects.create(
			name="Owner ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="Z",
		)
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Alice",
			last_name="Tenant",
			email="alice@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="MP-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)
		self.assignment = MeteringPointAssignment.objects.create(
			metering_point=self.metering_point,
			participant=self.participant,
			valid_from=date(2026, 1, 1),
		)
		auth(self.client, self.participant_user)

	def test_participant_cannot_access_zev_app(self):
		resp = self.client.get("/api/v1/zev/zevs/")
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_access_participant_app(self):
		resp = self.client.get("/api/v1/zev/participants/")
		self.assertEqual(resp.status_code, 403)

	def test_participant_can_list_own_metering_points(self):
		resp = self.client.get("/api/v1/zev/metering-points/")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(resp.data["results"]), 1)
		self.assertEqual(str(resp.data["results"][0]["id"]), str(self.metering_point.id))

	def test_participant_cannot_create_metering_point(self):
		resp = self.client.post(
			"/api/v1/zev/metering-points/",
			{
				"zev": str(self.zev.id),
				"meter_id": "MP-2",
				"meter_type": MeteringPointType.CONSUMPTION,
				"is_active": True,
			},
			format="json",
		)
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_update_metering_point(self):
		resp = self.client.patch(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/",
			{"meter_id": "MP-1A"},
			format="json",
		)
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_delete_metering_point(self):
		resp = self.client.delete(f"/api/v1/zev/metering-points/{self.metering_point.id}/")
		self.assertEqual(resp.status_code, 403)

	def test_participant_cannot_access_assignment_endpoint(self):
		resp = self.client.get("/api/v1/zev/metering-point-assignments/")
		self.assertEqual(resp.status_code, 403)


class ZevCreationWizardTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("admin_creator", UserRole.ADMIN)
		self.owner = make_user("owner_creator", UserRole.ZEV_OWNER)

	def test_non_admin_cannot_create_zev(self):
		auth(self.client, self.owner)
		resp = self.client.post(
			"/api/v1/zev/zevs/",
			{
				"name": "Blocked Create",
				"start_date": "2026-01-01",
				"zev_type": "vzev",
				"billing_interval": "monthly",
			},
			format="json",
		)
		self.assertEqual(resp.status_code, 403)

	@mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
	def test_admin_can_create_zev_with_owner_and_metering_points(self, mock_geocode_delay):
		auth(self.client, self.admin)
		resp = self.client.post(
			"/api/v1/zev/zevs/create-with-owner/",
			{
				"name": "Wizard ZEV",
				"start_date": "2026-03-01",
				"zev_type": "vzev",
				"billing_interval": "monthly",

				"grid_operator": "EWZ",
				"owner": {
					"title": "mr",
					"first_name": "Oscar",
					"last_name": "Owner",
					"email": "oscar.owner@example.com",
					"phone": "+41 79 555 55 55",
					"address_line1": "Owner Street 1",
					"postal_code": "8000",
					"city": "Zurich",
				},
				"metering_points": [
					{
						"meter_id": "CH0000000000000000000000000000001",
						"meter_type": "consumption",
					},
					{
						"meter_id": "CH0000000000000000000000000000002",
						"meter_type": "production",
					},
				],
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 201)
		self.assertIn("owner", resp.data)
		self.assertTrue(resp.data["owner"]["temporary_password"])

		created_zev = Zev.objects.get(name="Wizard ZEV")
		self.assertEqual(created_zev.owner.role, UserRole.ZEV_OWNER)
		self.assertTrue(created_zev.owner.check_password(resp.data["owner"]["temporary_password"]))

		owner_participant = Participant.objects.get(zev=created_zev, user=created_zev.owner)
		self.assertEqual(owner_participant.first_name, "Oscar")
		self.assertEqual(owner_participant.valid_from, date(2026, 3, 1))

		metering_points = MeteringPoint.objects.filter(zev=created_zev).order_by("meter_id")
		self.assertEqual(metering_points.count(), 2)

		assignments = MeteringPointAssignment.objects.filter(participant=owner_participant)
		self.assertEqual(assignments.count(), 2)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ParticipantAccountLifecycleTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("participant_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Lifecycle ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="L",
		)
		auth(self.client, self.owner)

	@mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
	def test_create_participant_creates_account_and_initial_password(self, mock_geocode_delay):
		resp = self.client.post(
			"/api/v1/zev/participants/",
			{
				"zev": str(self.zev.id),
				"title": "ms",
				"first_name": "Paula",
				"last_name": "Person",
				"email": "paula@example.com",
				"phone": "+41 79 000 00 00",
				"address_line1": "Main Street 1",
				"postal_code": "8000",
				"city": "Zurich",
				"valid_from": "2026-01-01",
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 201)
		participant = Participant.objects.get(pk=resp.data["id"])
		self.assertIsNotNone(participant.user)
		self.assertEqual(participant.user.role, UserRole.PARTICIPANT)
		self.assertEqual(resp.data["account_username"], participant.user.username)
		self.assertTrue(resp.data["initial_password"])
		self.assertTrue(participant.user.check_password(resp.data["initial_password"]))
		self.assertTrue(participant.user.must_change_password)
		self.assertEqual(resp.data["title"], "ms")

	@mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
	def test_update_participant_saves_contact_details(self, mock_geocode_delay):
		participant = Participant.objects.create(
			zev=self.zev,
			first_name="Nina",
			last_name="Tenant",
			email="nina@example.com",
			valid_from=date(2026, 1, 1),
		)
		from .services import ensure_participant_account
		ensure_participant_account(participant)

		resp = self.client.patch(
			f"/api/v1/zev/participants/{participant.id}/",
			{
				"phone": "+41 79 111 11 11",
				"address_line1": "Updated 2",
				"postal_code": "3000",
				"city": "Bern",
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		participant.refresh_from_db()
		self.assertEqual(participant.phone, "+41 79 111 11 11")
		self.assertEqual(participant.address_line1, "Updated 2")
		self.assertEqual(participant.city, "Bern")

	def test_send_invitation_mail_resets_temporary_password(self):
		resp_create = self.client.post(
			"/api/v1/zev/participants/",
			{
				"zev": str(self.zev.id),
				"first_name": "Ivy",
				"last_name": "Invitee",
				"email": "ivy@example.com",
				"valid_from": "2026-01-01",
			},
			format="json",
		)
		self.assertEqual(resp_create.status_code, 201)
		created_id = resp_create.data["id"]

		resp = self.client.post(f"/api/v1/zev/participants/{created_id}/send-invitation/")

		self.assertEqual(resp.status_code, 200)
		created = Participant.objects.get(pk=created_id)
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn(created.user.username, mail.outbox[0].body)
		self.assertIn(resp.data["temporary_password"], mail.outbox[0].body)
		self.assertTrue(created.user.check_password(resp.data["temporary_password"]))
		self.assertTrue(created.user.must_change_password)


class AdminCanEditOwnerParticipantTests(TestCase):
	"""The owner's own participant record (linked to a zev_owner-role account,
	not a participant-role one) is invoice-critical — it's the creditor
	address on generated PDFs — so an admin must be able to edit it, even
	though a regular participant edit is normally blocked for non-participant
	accounts."""

	def setUp(self):
		self.client = APIClient()
		self.owner = make_user("owner_for_edit_test", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Owner Edit ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="O",
		)
		self.owner_participant = Participant.objects.create(
			zev=self.zev,
			user=self.owner,
			first_name="Olivia",
			last_name="Owner",
			email="olivia.owner@example.com",
			address_line1="Old Street 1",
			postal_code="8000",
			city="Zurich",
			valid_from=date(2026, 1, 1),
		)

	@mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
	def test_admin_can_edit_the_owner_participant_address(self, mock_geocode_delay):
		admin = make_user("admin_edit_owner", UserRole.ADMIN)
		auth(self.client, admin)

		resp = self.client.patch(
			f"/api/v1/zev/participants/{self.owner_participant.id}/",
			{"address_line1": "New Street 5", "postal_code": "3000", "city": "Bern"},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.owner_participant.refresh_from_db()
		self.assertEqual(self.owner_participant.address_line1, "New Street 5")
		self.assertEqual(self.owner_participant.city, "Bern")

	def test_zev_owner_cannot_edit_their_own_owner_participant_record(self):
		auth(self.client, self.owner)

		resp = self.client.patch(
			f"/api/v1/zev/participants/{self.owner_participant.id}/",
			{"address_line1": "New Street 5", "postal_code": "3000", "city": "Bern"},
			format="json",
		)

		self.assertEqual(resp.status_code, 400)
		self.assertIn("user", resp.data)
		self.owner_participant.refresh_from_db()
		self.assertEqual(self.owner_participant.address_line1, "Old Street 1")


class ParticipantAccountLinkingTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("admin_linker", UserRole.ADMIN)
		self.zev_owner = make_user("owner_linker", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Linking ZEV",
			owner=self.zev_owner,
			zev_type="vzev",
			invoice_prefix="A",
		)
		self.participant_no_account = Participant.objects.create(
			zev=self.zev,
			first_name="No",
			last_name="Account",
			email="no.account@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.participant_with_account = Participant.objects.create(
			zev=self.zev,
			first_name="With",
			last_name="Account",
			email="with.account@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.linkable_account = make_user("linkable.participant", UserRole.PARTICIPANT)
		self.linked_account = make_user("already.linked", UserRole.PARTICIPANT)
		self.participant_with_account.user = self.linked_account
		self.participant_with_account.save(update_fields=["user", "updated_at"])
		auth(self.client, self.admin)

	def test_admin_can_link_existing_participant_account(self):
		resp = self.client.post(
			f"/api/v1/zev/participants/{self.participant_no_account.id}/link-account/",
			{"user_id": self.linkable_account.id},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.participant_no_account.refresh_from_db()
		self.assertEqual(self.participant_no_account.user_id, self.linkable_account.id)

	def test_linking_rejects_already_linked_account(self):
		resp = self.client.post(
			f"/api/v1/zev/participants/{self.participant_no_account.id}/link-account/",
			{"user_id": self.linked_account.id},
			format="json",
		)

		self.assertEqual(resp.status_code, 400)

	def test_admin_can_unlink_non_owner_account(self):
		resp = self.client.post(
			f"/api/v1/zev/participants/{self.participant_with_account.id}/unlink-account/",
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.participant_with_account.refresh_from_db()
		self.linked_account.refresh_from_db()
		self.assertIsNone(self.participant_with_account.user_id)
		self.assertEqual(self.linked_account.role, UserRole.GUEST)

	def test_admin_can_create_and_link_participant_account(self):
		resp = self.client.post(
			f"/api/v1/zev/participants/{self.participant_no_account.id}/create-account/",
			{"username": "created.from.participant"},
			format="json",
		)

		self.assertEqual(resp.status_code, 201)
		self.assertIn("temporary_password", resp.data)
		self.participant_no_account.refresh_from_db()
		self.assertIsNotNone(self.participant_no_account.user)
		self.assertEqual(self.participant_no_account.user.username, "created.from.participant")
		self.assertTrue(self.participant_no_account.user.must_change_password)

	def test_non_admin_cannot_link_or_create_accounts(self):
		owner_client = APIClient()
		auth(owner_client, self.zev_owner)

		link_resp = owner_client.post(
			f"/api/v1/zev/participants/{self.participant_no_account.id}/link-account/",
			{"user_id": self.linkable_account.id},
			format="json",
		)
		create_resp = owner_client.post(
			f"/api/v1/zev/participants/{self.participant_no_account.id}/create-account/",
			{"username": "owner.should.fail"},
			format="json",
		)

		self.assertEqual(link_resp.status_code, 403)
		self.assertEqual(create_resp.status_code, 403)
class ZevOwnerRoleSyncTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("admin_role_sync", UserRole.ADMIN)
		self.owner = make_user("owner_role_sync", UserRole.ZEV_OWNER)
		self.participant_user = make_user("participant_role_sync", UserRole.PARTICIPANT)
		self.zev = Zev.objects.create(
			name="Role Sync ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="R",
		)
		Participant.objects.create(
			zev=self.zev,
			user=self.participant_user,
			first_name="Role",
			last_name="Candidate",
			email="candidate@example.com",
			valid_from=date(2026, 1, 1),
		)
		auth(self.client, self.admin)

	def test_owner_change_promotes_new_owner_and_demotes_previous_owner(self):
		resp = self.client.patch(
			f"/api/v1/zev/zevs/{self.zev.id}/",
			{"owner": self.participant_user.id},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.participant_user.refresh_from_db()
		self.owner.refresh_from_db()
		self.assertEqual(self.participant_user.role, UserRole.ZEV_OWNER)
		self.assertEqual(self.owner.role, UserRole.PARTICIPANT)


class MeteringPointAssignmentValidationTests(TestCase):
	"""Tests for metering point assignment validation rules."""

	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("admin_assign_val", UserRole.ADMIN)
		self.zev = Zev.objects.create(
			name="Validation ZEV",
			owner=self.admin,
			zev_type="vzev",
			invoice_prefix="V",
		)
		# Participant valid 2026-03-01 → 2026-12-31
		self.participant = Participant.objects.create(
			zev=self.zev,
			first_name="Val",
			last_name="Participant",
			email="val@example.com",
			valid_from=date(2026, 3, 1),
			valid_to=date(2026, 12, 31),
		)
		# Second participant for duplicate-assignment test
		self.participant2 = Participant.objects.create(
			zev=self.zev,
			first_name="Second",
			last_name="Participant",
			email="second@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.mp = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="VAL-MP-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)
		auth(self.client, self.admin)

	def _post_assignment(self, payload):
		return self.client.post(
			"/api/v1/zev/metering-point-assignments/",
			payload,
			format="json",
		)

	# ------------------------------------------------------------------ #
	# Rule 1: only one active assignment per metering point                #
	# ------------------------------------------------------------------ #

	def test_first_assignment_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
		})
		self.assertEqual(resp.status_code, 201)

	def test_second_overlapping_assignment_to_same_metering_point_is_rejected(self):
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
		)
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-06-01",
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("one active assignment", str(resp.data).lower())

	# ------------------------------------------------------------------ #
	# Rule 2: historical non-overlapping assignments are allowed           #
	# ------------------------------------------------------------------ #

	def test_non_overlapping_historical_assignment_is_accepted(self):
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
			valid_to=date(2026, 5, 31),
		)
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-06-01",
			"valid_to": "2026-10-31",
		})
		self.assertEqual(resp.status_code, 201)

	def test_open_assignment_blocks_future_overlapping_assignment(self):
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
		)
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-08-01",
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("one active assignment", str(resp.data).lower())

	# ------------------------------------------------------------------ #
	# Rule 4 & 5: assignment dates within participant validity             #
	# ------------------------------------------------------------------ #

	def test_assignment_valid_from_before_participant_valid_from_is_rejected(self):
		# participant starts 2026-03-01
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-02-15",
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_from", resp.data)

	def test_assignment_valid_from_equal_to_participant_valid_from_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",  # exactly participant.valid_from
		})
		self.assertEqual(resp.status_code, 201)

	def test_assignment_valid_to_after_participant_valid_to_is_rejected(self):
		# participant ends 2026-12-31
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
			"valid_to": "2027-01-31",
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_to", resp.data)

	def test_assignment_valid_to_equal_to_participant_valid_to_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
			"valid_to": "2026-12-31",
		})
		self.assertEqual(resp.status_code, 201)

	def test_update_assignment_does_not_conflict_with_itself(self):
		assignment = MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
		)
		resp = self.client.patch(
			f"/api/v1/zev/metering-point-assignments/{assignment.id}/",
			{"valid_to": "2026-09-30"},
			format="json",
		)
		self.assertEqual(resp.status_code, 200)


class MeteringPointReadingsDeletionTests(TestCase):
	def setUp(self):
		self.admin_client = APIClient()
		self.owner_client = APIClient()

		self.admin = make_user("admin_delete_readings", UserRole.ADMIN)
		self.owner = make_user("owner_delete_readings", UserRole.ZEV_OWNER)

		self.zev = Zev.objects.create(
			name="Delete Readings ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="DR",
		)
		self.metering_point = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="MP-DELETE-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)

		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc),
			energy_kwh="1.0000",
			direction="in",
		)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 1, 20, 10, 0, tzinfo=timezone.utc),
			energy_kwh="2.0000",
			direction="in",
		)
		MeterReading.objects.create(
			metering_point=self.metering_point,
			timestamp=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
			energy_kwh="3.0000",
			direction="in",
		)

		auth(self.admin_client, self.admin)
		auth(self.owner_client, self.owner)

	def test_admin_can_delete_all_readings_for_metering_point(self):
		resp = self.admin_client.post(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
			{"delete_all": True},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["deleted_count"], 3)
		self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 0)

	def test_admin_can_delete_readings_in_date_range(self):
		resp = self.admin_client.post(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
			{
				"delete_all": False,
				"date_from": "2026-01-15",
				"date_to": "2026-01-31",
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["deleted_count"], 1)
		remaining = MeterReading.objects.filter(metering_point=self.metering_point).order_by("timestamp")
		self.assertEqual(remaining.count(), 2)
		self.assertEqual(remaining[0].timestamp.date().isoformat(), "2026-01-10")
		self.assertEqual(remaining[1].timestamp.date().isoformat(), "2026-02-01")

	def test_delete_range_requires_dates_when_delete_all_false(self):
		resp = self.admin_client.post(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
			{"delete_all": False},
			format="json",
		)

		self.assertEqual(resp.status_code, 400)

	def test_non_admin_cannot_delete_readings(self):
		resp = self.owner_client.post(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
			{"delete_all": True},
			format="json",
		)

		self.assertEqual(resp.status_code, 403)


class NextInvoiceNumberTests(TestCase):
	"""Guards the F()-expression counter increment used during invoice generation."""

	def setUp(self):
		self.owner = make_user("inv_num_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Counter ZEV",
			owner=self.owner,
			zev_type="vzev",
			invoice_prefix="C",
			invoice_counter=1,
		)

	def test_format_uses_prefix_and_zero_padded_counter(self):
		self.assertEqual(self.zev.next_invoice_number(), "C-00001")

	def test_counter_increments_without_gaps_or_repeats(self):
		numbers = [self.zev.next_invoice_number() for _ in range(5)]

		self.assertEqual(numbers, ["C-00001", "C-00002", "C-00003", "C-00004", "C-00005"])
		# All numbers are unique (no repeats) and strictly monotonic.
		self.assertEqual(len(set(numbers)), len(numbers))
		self.zev.refresh_from_db()
		self.assertEqual(self.zev.invoice_counter, 6)

	def test_counter_persists_across_instances(self):
		first = self.zev.next_invoice_number()
		# A freshly-loaded instance must continue from the persisted counter.
		reloaded = Zev.objects.get(pk=self.zev.pk)
		second = reloaded.next_invoice_number()

		self.assertEqual(first, "C-00001")
		self.assertEqual(second, "C-00002")


class SeedDemoPeriodHelpersTests(TestCase):
	"""``seed_demo`` derives its window from today, so the quarter maths must
	hold across year boundaries — a fixed window silently goes stale and leaves
	the dashboard, charts and invoice pages empty."""

	def test_quarter_start_snaps_to_the_containing_quarter(self):
		self.assertEqual(quarter_start(date(2026, 7, 9)), date(2026, 7, 1))
		self.assertEqual(quarter_start(date(2026, 4, 1)), date(2026, 4, 1))
		self.assertEqual(quarter_start(date(2026, 3, 31)), date(2026, 1, 1))
		self.assertEqual(quarter_start(date(2026, 12, 31)), date(2026, 10, 1))

	def test_previous_quarter_is_the_last_complete_quarter(self):
		self.assertEqual(previous_quarter(date(2026, 7, 9)), (date(2026, 4, 1), date(2026, 6, 30)))
		self.assertEqual(previous_quarter(date(2026, 4, 1)), (date(2026, 1, 1), date(2026, 3, 31)))

	def test_previous_quarter_crosses_the_year_boundary(self):
		self.assertEqual(previous_quarter(date(2026, 1, 5)), (date(2025, 10, 1), date(2025, 12, 31)))

	def test_previous_quarter_handles_a_leap_day(self):
		self.assertEqual(previous_quarter(date(2024, 2, 29)), (date(2023, 10, 1), date(2023, 12, 31)))
