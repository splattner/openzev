from datetime import date

from django.test import TestCase
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev


def make_user(username, role, password="pass1234"):
	return User.objects.create_user(username=username, password=password, role=role)


def auth(client, user, password="pass1234"):
	resp = client.post("/api/v1/auth/token/", {"username": user.username, "password": password})
	client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


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
			participant=self.participant,
			meter_id="MP-1",
			meter_type=MeteringPointType.CONSUMPTION,
			valid_from=date(2026, 1, 1),
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
				"participant": str(self.participant.id),
				"meter_id": "MP-2",
				"meter_type": MeteringPointType.CONSUMPTION,
				"is_active": True,
				"valid_from": "2026-01-01",
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

	def test_admin_can_create_zev_with_owner_and_metering_points(self):
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
						"valid_from": "2026-03-01",
					},
					{
						"meter_id": "CH0000000000000000000000000000002",
						"meter_type": "production",
						"valid_from": "2026-03-01",
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
		self.assertTrue(all(mp.participant_id == owner_participant.id for mp in metering_points))

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

	def test_create_participant_creates_account_and_initial_password(self):
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

	def test_update_participant_saves_contact_details(self):
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
		# Metering point valid 2026-02-01 → 2026-11-30
		self.mp = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="VAL-MP-1",
			meter_type=MeteringPointType.CONSUMPTION,
			valid_from=date(2026, 2, 1),
			valid_to=date(2026, 11, 30),
		)
		auth(self.client, self.admin)

	def _post_assignment(self, payload):
		return self.client.post(
			"/api/v1/zev/metering-point-assignments/",
			payload,
			format="json",
		)

	# ------------------------------------------------------------------ #
	# Rule 1: only one assignment per metering point                       #
	# ------------------------------------------------------------------ #

	def test_first_assignment_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
		})
		self.assertEqual(resp.status_code, 201)

	def test_second_assignment_to_same_metering_point_is_rejected(self):
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
		self.assertIn("one participant assignment", str(resp.data).lower())

	# ------------------------------------------------------------------ #
	# Rule 2 & 3: assignment dates within metering point validity          #
	# ------------------------------------------------------------------ #

	def test_assignment_valid_from_before_mp_valid_from_is_rejected(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-01-01",  # mp starts 2026-02-01
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_from", resp.data)

	def test_assignment_valid_from_equal_to_mp_valid_from_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-02-01",  # exactly mp.valid_from
		})
		self.assertEqual(resp.status_code, 201)

	def test_assignment_valid_to_after_mp_valid_to_is_rejected(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-02-01",
			"valid_to": "2026-12-31",  # mp ends 2026-11-30
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_to", resp.data)

	def test_assignment_valid_to_equal_to_mp_valid_to_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-02-01",
			"valid_to": "2026-11-30",  # exactly mp.valid_to
		})
		self.assertEqual(resp.status_code, 201)

	def test_assignment_open_end_when_mp_has_valid_to_is_accepted(self):
		# valid_to not set on assignment → no upper-bound check against mp
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant2.id),
			"valid_from": "2026-02-01",
		})
		self.assertEqual(resp.status_code, 201)

	# ------------------------------------------------------------------ #
	# Rule 4 & 5: assignment dates within participant validity             #
	# ------------------------------------------------------------------ #

	def test_assignment_valid_from_before_participant_valid_from_is_rejected(self):
		# participant starts 2026-03-01; mp starts 2026-02-01
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-02-15",  # after mp start, but before participant start
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
		# participant ends 2026-12-31; mp ends 2026-11-30
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
			"valid_to": "2027-01-31",  # after participant.valid_to
		})
		self.assertEqual(resp.status_code, 400)
		self.assertIn("valid_to", resp.data)

	def test_assignment_valid_to_equal_to_participant_valid_to_is_accepted(self):
		resp = self._post_assignment({
			"metering_point": str(self.mp.id),
			"participant": str(self.participant.id),
			"valid_from": "2026-03-01",
			"valid_to": "2026-11-30",  # within both mp (ends 11-30) and participant (ends 12-31)
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
			{"valid_to": "2026-11-30"},
			format="json",
		)
		self.assertEqual(resp.status_code, 200)
