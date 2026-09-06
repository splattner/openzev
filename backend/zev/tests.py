from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole, VatRate
from audit.models import AuditActionCategory, AuditEvent
from audit.services import record_audit_event
from zev.management.commands.seed_demo import (
	Command as SeedDemoCommand,
	DEMO_ZEV_LEGACY_NAME,
	DEMO_ZEV_NAME,
	SECOND_DEMO_ZEV_NAME,
	previous_month,
	previous_quarter,
	quarter_start,
	years_before,
)
from invoices.models import ContractIssue, EmailLog, Invoice, InvoiceStatus
from metering.models import ImportLog, MeterReading, ReadingDirection, ReadingResolution
from tariffs.models import BillingMode, PeriodType, Tariff
from tariffs.series import active_version, find_gaps
from zev.models import (
	AllocationMode,
	BillingInterval,
	InvoiceLanguage,
	MeteringPoint,
	MeteringPointAssignment,
	MeteringPointType,
	Participant,
	VatMode,
	Zev,
	ZevType,
)


from testing.helpers import authenticate as auth, make_user


def _seed_sparse_window_readings(*, start_date, end_date, meters, sample_days=(1, 15)):
	"""Insert a few hourly rows per sample day per meter.

	Helper-level tests that assert statuses, period sets or window hygiene —
	never consumption volume — use this in place of the seeder's dense window
	readings, which would dwarf the actual assertions with tens of thousands
	of rows.
	"""
	rows = []
	day = start_date
	while day <= end_date:
		if day.day in sample_days:
			for hour in range(24):
				timestamp = datetime.combine(day, time(hour), tzinfo=timezone.utc)
				for meter, direction, _profile in meters:
					rows.append(
						MeterReading(
							metering_point=meter,
							timestamp=timestamp,
							energy_kwh="0.5000",
							direction=direction,
							resolution=ReadingResolution.HOURLY,
						)
					)
		day += timedelta(days=1)
	MeterReading.objects.bulk_create(rows, batch_size=5000)


class ZevPaymentTermTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("payterm_admin", UserRole.ADMIN)
		self.owner = make_user("payterm_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="PayTerm ZEV", owner=self.owner)

	def test_payment_term_days_defaults_to_30(self):
		self.assertEqual(self.zev.payment_term_days, 30)

	def test_payment_term_days_validators_reject_out_of_range(self):
		for invalid in (0, 366):
			self.zev.payment_term_days = invalid
			with self.assertRaises(ValidationError):
				self.zev.full_clean()
		self.zev.payment_term_days = 14
		self.zev.full_clean()  # in range - should not raise

	def test_api_patch_accepts_valid_payment_term(self):
		auth(self.client, self.admin)
		resp = self.client.patch(
			f"/api/v1/zev/zevs/{self.zev.id}/",
			{"payment_term_days": 14},
			format="json",
		)
		self.assertEqual(resp.status_code, 200)
		self.zev.refresh_from_db()
		self.assertEqual(self.zev.payment_term_days, 14)

	def test_api_patch_rejects_out_of_range_payment_term(self):
		auth(self.client, self.admin)
		for invalid in (0, 366):
			resp = self.client.patch(
				f"/api/v1/zev/zevs/{self.zev.id}/",
				{"payment_term_days": invalid},
				format="json",
			)
			self.assertEqual(resp.status_code, 400)
		self.zev.refresh_from_db()
		self.assertEqual(self.zev.payment_term_days, 30)


class ZevVatModeTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("vatmode_admin", UserRole.ADMIN)
		self.owner = make_user("vatmode_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="VAT Mode ZEV", owner=self.owner)

	def test_defaults_to_not_registered(self):
		self.assertEqual(self.zev.vat_mode, VatMode.NOT_REGISTERED)

	def test_clean_requires_number_for_registered(self):
		self.zev.vat_mode = VatMode.REGISTERED
		with self.assertRaises(ValidationError):
			self.zev.full_clean()
		self.zev.vat_number = "CHE-123.456.789"
		self.zev.full_clean()  # ok

	def test_clean_rejects_number_without_registered_mode(self):
		self.zev.vat_mode = VatMode.INCLUSIVE
		self.zev.vat_number = "CHE-123.456.789"
		with self.assertRaises(ValidationError):
			self.zev.full_clean()

	def test_api_patch_to_inclusive_is_accepted(self):
		auth(self.client, self.admin)
		resp = self.client.patch(
			f"/api/v1/zev/zevs/{self.zev.id}/",
			{"vat_mode": VatMode.INCLUSIVE},
			format="json",
		)
		self.assertEqual(resp.status_code, 200, resp.content)
		self.zev.refresh_from_db()
		self.assertEqual(self.zev.vat_mode, VatMode.INCLUSIVE)

	def test_api_patch_to_registered_without_number_is_rejected(self):
		auth(self.client, self.admin)
		resp = self.client.patch(
			f"/api/v1/zev/zevs/{self.zev.id}/",
			{"vat_mode": VatMode.REGISTERED},
			format="json",
		)
		self.assertEqual(resp.status_code, 400)
		self.zev.refresh_from_db()
		self.assertEqual(self.zev.vat_mode, VatMode.NOT_REGISTERED)


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
		self.assertEqual(participant.user.role, UserRole.PARTICIPANT)

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
		self.owner.refresh_from_db()
		self.assertEqual(self.owner.role, UserRole.ZEV_OWNER)
		auth(self.client, self.owner)
		self.assertEqual(self.client.get(f"/api/v1/zev/zevs/{self.zev.id}/").status_code, 200)

	@mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
	def test_profile_sync_preserves_privileged_roles(self, mock_geocode_delay):
		admin = make_user("admin_edit_privileged", UserRole.ADMIN)
		for role in (UserRole.ZEV_OWNER, UserRole.ADMIN):
			with self.subTest(role=role):
				self.owner.role = role
				self.owner.save(update_fields=["role"])
				auth(self.client, admin)
				resp = self.client.patch(
					f"/api/v1/zev/participants/{self.owner_participant.id}/",
					{"first_name": "Updated", "last_name": "Owner", "email": "updated.owner@example.com"},
					format="json",
				)
				self.assertEqual(resp.status_code, 200)
				self.owner.refresh_from_db()
				self.assertEqual(self.owner.role, role)
				self.assertEqual(self.owner.first_name, "Updated")
				self.assertEqual(self.owner.last_name, "Owner")
				self.assertEqual(self.owner.email, "updated.owner@example.com")
				auth(self.client, self.owner)
				self.assertEqual(self.client.get(f"/api/v1/zev/zevs/{self.zev.id}/").status_code, 200)

	def test_invitation_preserves_privileged_roles_and_promotes_guests(self):
		admin = make_user("admin_invite_privileged", UserRole.ADMIN)
		auth(self.client, admin)
		for role in (UserRole.ZEV_OWNER, UserRole.ADMIN, UserRole.PARTICIPANT, UserRole.GUEST):
			with self.subTest(role=role):
				account = make_user(f"invite_{role}", role)
				participant = Participant.objects.create(
					zev=self.zev, user=account, first_name="Invited", last_name="Person",
					email=account.email, valid_from=date(2026, 1, 1),
				)
				resp = self.client.post(f"/api/v1/zev/participants/{participant.id}/send-invitation/")
				self.assertEqual(resp.status_code, 200)
				account.refresh_from_db()
				expected_role = UserRole.PARTICIPANT if role == UserRole.GUEST else role
				self.assertEqual(account.role, expected_role)
				self.assertTrue(account.check_password(resp.data["temporary_password"]))
				self.assertTrue(account.must_change_password)
				self.assertEqual(mail.outbox[-1].to, [participant.email])
				self.assertIn(resp.data["temporary_password"], mail.outbox[-1].body)

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


class AssignmentSaveOverlapGuardTests(TestCase):
	"""The non-overlap rule runs on save(), not only where full_clean() is
	invoked (API/admin), so programmatic writes cannot create overlapping
	windows (ADR 0013 follow-up)."""

	def setUp(self):
		self.owner = make_user("ovguard_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="OV ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="OV")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=make_user("ovguard_p1", UserRole.PARTICIPANT),
			first_name="Anna",
			last_name="One",
			email="anna@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.participant2 = Participant.objects.create(
			zev=self.zev,
			user=make_user("ovguard_p2", UserRole.PARTICIPANT),
			first_name="Beat",
			last_name="Two",
			email="beat@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.mp = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="CH-OV-001",
			meter_type=MeteringPointType.CONSUMPTION,
		)

	def test_save_rejects_overlapping_assignment(self):
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
		)
		with self.assertRaises(ValidationError):
			MeteringPointAssignment.objects.create(
				metering_point=self.mp,
				participant=self.participant2,
				valid_from=date(2026, 6, 1),
			)

	def test_save_allows_adjacent_windows(self):
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
			valid_to=date(2026, 5, 31),
		)
		second = MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant2,
			valid_from=date(2026, 6, 1),
			valid_to=date(2026, 10, 31),
		)
		self.assertIsNotNone(second.pk)

	def test_save_allows_updating_own_window(self):
		assignment = MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
		)
		assignment.valid_to = date(2026, 12, 31)
		assignment.save()  # must not flag itself
		assignment.refresh_from_db()
		self.assertEqual(assignment.valid_to, date(2026, 12, 31))

	def test_save_rejects_update_that_creates_an_overlap(self):
		first = MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant,
			valid_from=date(2026, 3, 1),
			valid_to=date(2026, 5, 31),
		)
		MeteringPointAssignment.objects.create(
			metering_point=self.mp,
			participant=self.participant2,
			valid_from=date(2026, 6, 1),
			valid_to=date(2026, 10, 31),
		)
		first.valid_to = date(2026, 12, 31)  # now overlaps the second window
		with self.assertRaises(ValidationError):
			first.save()

	def test_validate_no_overlap_tolerates_a_half_built_instance(self):
		# The guard mirrors clean()'s early return so a half-built instance
		# does not reach the overlap query with incomplete state.
		assignment = MeteringPointAssignment()
		assignment._validate_no_overlap()  # must not raise or query


class SeedDemoAssignmentReseedTests(TestCase):
	"""Running ``seed_demo`` again must not trip the assignment non-overlap
	guard: the seed window moves every quarter, and ``_ensure_assignment``
	drops the prior open-ended window before creating the next one."""

	def setUp(self):
		self.owner = make_user("seed_assign_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="Seed Assign ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="SA")
		self.participant = Participant.objects.create(
			zev=self.zev,
			user=make_user("seed_assign_p1", UserRole.PARTICIPANT),
			first_name="Cara",
			last_name="Three",
			email="cara@example.com",
			valid_from=date(2026, 1, 1),
		)
		self.mp = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="CH-SA-001",
			meter_type=MeteringPointType.CONSUMPTION,
		)

	def test_reseed_moves_the_window_without_overlapping(self):
		command = SeedDemoCommand()
		command._ensure_assignment(self.mp, self.participant, date(2026, 4, 1))
		command._ensure_assignment(self.mp, self.participant, date(2026, 7, 1))
		windows = list(MeteringPointAssignment.objects.filter(metering_point=self.mp))
		self.assertEqual(len(windows), 1)
		self.assertEqual(windows[0].valid_from, date(2026, 7, 1))
		self.assertIsNone(windows[0].valid_to)


class SeedDemoSecondCommunityTests(TestCase):
	"""The second demo community exists so one owner can exercise the community
	switcher. Seeding it must be idempotent and migrate databases that still
	carry a legacy name: the two demo communities must never duplicate or
	collide on re-runs."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_second_zev_owner", UserRole.ZEV_OWNER)

	def _upsert_demo_zevs(self):
		self.command._upsert_zev(
			owner=self.owner,
			name=DEMO_ZEV_NAME,
			zev_type=ZevType.ZEV,
			start_date=date(2026, 1, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0001",
			billing_interval=BillingInterval.QUARTERLY,
			invoice_prefix="OZV",
			invoice_language=InvoiceLanguage.DE,
			bank_iban="CH9300762011623852957",
			bank_name="Demo Energy Bank",
			vat_mode=VatMode.INCLUSIVE,
			vat_number="",
		)
		self.command._upsert_zev(
			owner=self.owner,
			name=SECOND_DEMO_ZEV_NAME,
			zev_type=ZevType.VZEV,
			start_date=date(2026, 1, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0002",
			billing_interval=BillingInterval.MONTHLY,
			invoice_prefix="OZ2",
			invoice_language=InvoiceLanguage.EN,
			bank_iban="CH4431999123000889012",
			bank_name="Demo Energy Bank",
			vat_mode=VatMode.REGISTERED,
			vat_number="CHE-987.654.321",
		)

	def test_upsert_zev_is_idempotent_and_refreshes_config_drift(self):
		self._upsert_demo_zevs()
		# A second run must not duplicate the ZEV, and must pull a row back
		# onto the canonical config (here: a start date that moved on).
		self.command._upsert_zev(
			owner=self.owner,
			name=SECOND_DEMO_ZEV_NAME,
			zev_type=ZevType.VZEV,
			start_date=date(2026, 4, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0002",
			billing_interval="monthly",
			invoice_prefix="OZ2",
			invoice_language="en",
			bank_iban="CH4431999123000889012",
			bank_name="Demo Energy Bank",
			vat_mode=VatMode.REGISTERED,
			vat_number="CHE-987.654.321",
		)
		self.assertEqual(Zev.objects.filter(name=SECOND_DEMO_ZEV_NAME).count(), 1)
		second = Zev.objects.get(name=SECOND_DEMO_ZEV_NAME)
		self.assertEqual(second.owner, self.owner)
		self.assertEqual(second.start_date, date(2026, 4, 1))
		self.assertEqual(second.billing_interval, "monthly")
		self.assertEqual(second.invoice_language, "en")
		self.assertEqual(second.invoice_prefix, "OZ2")
		self.assertEqual(second.vat_mode, VatMode.REGISTERED)
		self.assertEqual(second.vat_number, "CHE-987.654.321")

	def test_legacy_flagship_name_is_renamed_not_duplicated(self):
		# A database seeded under the name the base branch shipped.
		Zev.objects.create(
			name=DEMO_ZEV_LEGACY_NAME,
			owner=self.owner,
			start_date=date(2026, 1, 1),
			zev_type="vzev",
			invoice_prefix="OZV",
		)
		self.command._migrate_legacy_demo_zev_names(owner=self.owner)
		self._upsert_demo_zevs()
		self.assertFalse(Zev.objects.filter(name=DEMO_ZEV_LEGACY_NAME).exists())
		# The legacy row was refreshed in place, not shadowed by a new one.
		self.assertEqual(Zev.objects.filter(name=DEMO_ZEV_NAME).count(), 1)
		self.assertEqual(Zev.objects.filter(owner=self.owner).count(), 2)

	def test_legacy_name_of_another_owner_is_untouched(self):
		# Identification is scoped to the demo owner: a tenant community that
		# happens to share the display name must never be renamed or deleted.
		stranger = make_user("seed_legacy_stranger", UserRole.ZEV_OWNER)
		tenant = Zev.objects.create(
			name=DEMO_ZEV_LEGACY_NAME,
			owner=stranger,
			start_date=date(2026, 1, 1),
			zev_type="vzev",
			invoice_prefix="TEN",
		)
		self.command._migrate_legacy_demo_zev_names(owner=self.owner)
		self._upsert_demo_zevs()
		self.assertTrue(Zev.objects.filter(pk=tenant.pk).exists())
		self.assertEqual(Zev.objects.get(pk=tenant.pk).name, DEMO_ZEV_LEGACY_NAME)

	def test_each_community_carries_the_config_its_name_implies(self):
		self._upsert_demo_zevs()
		stweg = Zev.objects.get(name=DEMO_ZEV_NAME)
		self.assertEqual(stweg.zev_type, ZevType.ZEV)
		self.assertEqual(stweg.billing_interval, "quarterly")
		self.assertEqual(stweg.invoice_language, InvoiceLanguage.DE)
		self.assertEqual(stweg.vat_mode, VatMode.INCLUSIVE)
		self.assertEqual(stweg.vat_number, "")
		company = Zev.objects.get(name=SECOND_DEMO_ZEV_NAME)
		self.assertEqual(company.zev_type, ZevType.VZEV)
		self.assertEqual(company.billing_interval, "monthly")
		self.assertEqual(company.invoice_language, InvoiceLanguage.EN)
		self.assertEqual(company.vat_mode, VatMode.REGISTERED)
		self.assertEqual(company.vat_number, "CHE-987.654.321")

	def test_previous_month_returns_the_complete_prior_month(self):
		self.assertEqual(previous_month(date(2026, 9, 6)), (date(2026, 8, 1), date(2026, 8, 31)))
		self.assertEqual(previous_month(date(2026, 3, 1)), (date(2026, 2, 1), date(2026, 2, 28)))


class SeedDemoSecondCommunitySeedTests(TestCase):
	"""``_seed_second_community`` must produce a closed (paid/cancelled) month
	and an open draft/approved/sent month, and re-seeding must reproduce that
	exactly instead of piling invoices up."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_second_seed_owner", UserRole.ZEV_OWNER)
		self.clara_user = make_user("seed_second_clara", UserRole.PARTICIPANT)
		self.zev = self.command._upsert_zev(
			owner=self.owner,
			name="Seeded Second ZEV",
			zev_type=ZevType.VZEV,
			start_date=date(2026, 7, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0002",
			billing_interval=BillingInterval.MONTHLY,
			invoice_prefix="OZ2",
			invoice_language=InvoiceLanguage.EN,
			bank_iban="CH4431999123000889012",
			bank_name="Demo Energy Bank",
			vat_mode=VatMode.REGISTERED,
			vat_number="CHE-987.654.321",
		)
		self.command._upsert_vat_rates()

	def _seed(self):
		# Only statuses and counts are under test, never consumption volume:
		# swap the dense window readings for a few hourly days per month so
		# the fixture stays small (see ``_seed_sparse_window_readings``).
		with mock.patch.object(
			self.command,
			"_seed_meter_readings",
			side_effect=_seed_sparse_window_readings,
		):
			return self.command._seed_second_community(
				owner=self.owner,
				clara_user=self.clara_user,
				zev=self.zev,
				start_date=date(2026, 7, 1),
				end_date=date(2026, 9, 6),
			)

	def test_seeds_a_closed_and_an_open_month(self):
		invoices, open_start, open_end, closed_invoices, closed_start, closed_end = self._seed()
		self.assertEqual((closed_start, closed_end), (date(2026, 7, 1), date(2026, 7, 31)))
		self.assertEqual((open_start, open_end), (date(2026, 8, 1), date(2026, 8, 31)))
		self.assertTrue(invoices)
		self.assertTrue(closed_invoices)
		# Open month: the normal draft/approved/sent progression only.
		self.assertFalse(
			Invoice.objects.filter(
				zev=self.zev,
				period_start=open_start,
				status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELLED],
			).exists()
		)
		# Closed month: everything settled, at most one invoice cancelled.
		closed_statuses = set(
			Invoice.objects.filter(zev=self.zev, period_start=closed_start).values_list("status", flat=True)
		)
		self.assertTrue(closed_statuses.issubset({InvoiceStatus.PAID, InvoiceStatus.CANCELLED}))
		self.assertLessEqual(
			Invoice.objects.filter(zev=self.zev, period_start=closed_start, status=InvoiceStatus.CANCELLED).count(),
			1,
		)

	def test_re_seeding_the_second_community_is_idempotent(self):
		first = self._seed()
		second = self._seed()
		self.assertEqual(len(first[0]), len(second[0]))
		self.assertEqual(len(first[3]), len(second[3]))
		self.assertEqual(
			set(Invoice.objects.filter(zev=self.zev).values_list("period_start", flat=True)),
			{date(2026, 7, 1), date(2026, 8, 1)},
		)


class SeedDemoQualityGapTests(TestCase):
	"""The intentional reading gap must delete exactly its window — and must be
	skipped while the current period is still too young to hold one."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_gap_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="Gap ZEV", owner=self.owner)
		self.meter = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="GAP-CONS-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)
		first_day = date(2026, 8, 1)
		for offset in range(36):  # 2026-08-01 .. 2026-09-05
			MeterReading.objects.create(
				metering_point=self.meter,
				timestamp=datetime.combine(
					first_day + timedelta(days=offset), time(12, 0), tzinfo=timezone.utc
				),
				energy_kwh="0.5000",
				direction=ReadingDirection.IN,
			)

	def test_punch_quality_gap_deletes_only_the_recent_window(self):
		gap_start, gap_end = self.command._punch_quality_gap(
			meter=self.meter,
			after=date(2026, 8, 24),
			end_date=date(2026, 9, 6),
		)
		self.assertEqual((gap_start, gap_end), (date(2026, 8, 25), date(2026, 9, 5)))
		remaining = MeterReading.objects.filter(metering_point=self.meter).count()
		self.assertEqual(remaining, 24)
		# The hole never reaches back past the billed period end.
		self.assertTrue(
			MeterReading.objects.filter(
				metering_point=self.meter,
				timestamp__lt=datetime.combine(gap_start, time.min, tzinfo=timezone.utc),
			).exists()
		)

	def test_punch_quality_gap_is_skipped_when_the_period_is_too_young(self):
		gap_start, gap_end = self.command._punch_quality_gap(
			meter=self.meter,
			after=date(2026, 8, 31),
			end_date=date(2026, 9, 6),
		)
		self.assertEqual((gap_start, gap_end), (None, None))
		self.assertEqual(MeterReading.objects.filter(metering_point=self.meter).count(), 36)


class SeedDemoVatRateTests(TestCase):
	"""The demo bills real VAT figures only when VatRate rows exist; the seed
	must install the standard Swiss history. Its contract is "install missing
	defaults": rates an admin added or edited in a shared development database
	are left alone, because deleting and recreating the canonical rows on top
	of a preserved custom open-ended rate could collide with it."""

	def setUp(self):
		self.command = SeedDemoCommand()

	def test_upsert_vat_rates_installs_the_swiss_history(self):
		self.command._upsert_vat_rates()
		rates = list(VatRate.objects.order_by("valid_from"))
		self.assertEqual([str(rate.rate) for rate in rates], ["0.0770", "0.0810"])
		self.assertEqual(rates[0].valid_to, date(2023, 12, 31))
		self.assertIsNone(rates[1].valid_to)

	def test_upsert_vat_rates_is_idempotent(self):
		self.command._upsert_vat_rates()
		self.command._upsert_vat_rates()
		self.assertEqual(VatRate.objects.count(), 2)

	def test_upsert_vat_rates_leaves_foreign_rates_alone(self):
		# A dev database may carry VAT rates an admin added on top of the
		# standard Swiss history; the seed installs only the missing defaults.
		self.command._upsert_vat_rates()
		foreign = VatRate.objects.create(
			rate="0.0260",
			valid_from=date(2017, 1, 1),
			valid_to=date(2017, 12, 31),
		)
		self.command._upsert_vat_rates()
		self.assertTrue(VatRate.objects.filter(pk=foreign.pk).exists())
		self.assertEqual(VatRate.objects.filter(valid_from=date(2018, 1, 1)).count(), 1)
		self.assertEqual(VatRate.objects.filter(valid_from=date(2024, 1, 1)).count(), 1)

	def test_upsert_vat_rates_keeps_an_admin_edited_canonical_row(self):
		# An admin who corrected the canonical 2024 rate in place keeps their
		# edit; the seed adds only what is missing (no canonical row exists
		# yet here, so it installs the other one and leaves the edit alone).
		VatRate.objects.create(
			rate="0.0850",
			valid_from=date(2024, 1, 1),
			valid_to=None,
		)
		self.command._upsert_vat_rates()
		self.assertEqual(
			str(VatRate.objects.get(valid_from=date(2024, 1, 1)).rate),
			"0.0850",
		)
		self.assertEqual(VatRate.objects.filter(valid_from=date(2018, 1, 1)).count(), 1)

	def test_upsert_vat_rates_preserves_overlapping_custom_dates(self):
		custom = VatRate.objects.create(rate="0.0850", valid_from=date(2025, 1, 1))
		self.command._upsert_vat_rates()
		self.command._upsert_vat_rates()
		custom.refresh_from_db()
		self.assertEqual(custom.rate, Decimal("0.0850"))
		self.assertEqual(VatRate.objects.count(), 2)
		self.assertFalse(VatRate.objects.filter(valid_from=date(2024, 1, 1)).exists())


class SeedDemoCounterRefreshTests(TestCase):
	"""Re-seeding must pull leftover rows back onto the canonical config —
	including the invoice counter, which would otherwise climb (and skip
	numbers) across re-seeds because the seed deletes the invoices it
	generated last time. The contract counter is the exception: issued
	contract snapshots survive a re-seed, so resetting it could mint
	duplicate CTR-YYYY-NNNN document numbers."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_counter_owner", UserRole.ZEV_OWNER)

	def _upsert(self):
		return self.command._upsert_zev(
			owner=self.owner,
			name=DEMO_ZEV_NAME,
			zev_type=ZevType.ZEV,
			start_date=date(2026, 1, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0001",
			billing_interval=BillingInterval.QUARTERLY,
			invoice_prefix="OZV",
			invoice_language=InvoiceLanguage.DE,
			bank_iban="CH9300762011623852957",
			bank_name="Demo Energy Bank",
			vat_mode=VatMode.INCLUSIVE,
			vat_number="",
		)

	def test_reseed_resets_the_invoice_counter(self):
		zev = self._upsert()
		Zev.objects.filter(pk=zev.pk).update(invoice_counter=9)
		self._upsert()
		zev.refresh_from_db()
		self.assertEqual(zev.invoice_counter, 1)

	def test_reseed_keeps_the_contract_counter(self):
		zev = self._upsert()
		Zev.objects.filter(pk=zev.pk).update(contract_counter=3)
		self._upsert()
		zev.refresh_from_db()
		self.assertEqual(zev.contract_counter, 3)


class SeedDemoHourlyHistoryTests(TestCase):
	"""The hourly history year gives the reports pages a complete year. It
	must be hourly, stop exactly where the 15-minute window takes over, and
	keep volumes consistent with the profile: one row sums the four
	quarter-hour samples it replaces."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_history_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="History ZEV",
			owner=self.owner,
			zev_type="vzev",
			start_date=date(2026, 1, 1),
			invoice_prefix="HIS",
		)
		self.meter = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="HIST-METER-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)

	def _seed(self, history_start, stop_date):
		self.command._seed_history_readings(
			history_start=history_start,
			stop_date=stop_date,
			meters=[(self.meter, ReadingDirection.IN, self.command._consumer_one_kwh)],
		)

	def test_history_fills_the_range_hourly_and_stops_before_the_window(self):
		self._seed(date(2025, 1, 1), date(2025, 1, 3))
		readings = MeterReading.objects.filter(metering_point=self.meter).order_by("timestamp")
		self.assertEqual(readings.count(), 2 * 24)
		self.assertEqual(
			readings.filter(resolution=ReadingResolution.HOURLY).count(),
			readings.count(),
		)
		self.assertEqual(readings.first().timestamp, datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc))
		self.assertEqual(readings.last().timestamp, datetime(2025, 1, 2, 23, 0, tzinfo=timezone.utc))

	def test_an_hourly_row_sums_the_four_quarter_samples_it_replaces(self):
		self._seed(date(2025, 1, 1), date(2025, 1, 2))
		row = MeterReading.objects.get(
			metering_point=self.meter,
			timestamp=datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc),
		)
		total = sum(
			float(self.command._consumer_one_kwh(datetime(2025, 1, 1, 13, minute, tzinfo=timezone.utc), 0))
			for minute in (0, 15, 30, 45)
		)
		self.assertEqual(row.energy_kwh, Decimal(str(round(total, 4))))

	def test_history_is_skipped_when_the_window_precedes_it(self):
		self._seed(date(2025, 6, 1), date(2025, 1, 1))
		self.assertEqual(MeterReading.objects.filter(metering_point=self.meter).count(), 0)


class SeedDemoReadingResolutionTests(TestCase):
	"""The seed window keeps 15-minute rows only for the recent tail; everything
	older is hourly, each hour summing the four quarter samples it replaces, so
	volumes stay consistent across the boundary and the dataset stays small
	enough to re-seed quickly. The boundary is derived from the end date once
	and shared by every meter."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_resolution_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Resolution ZEV",
			owner=self.owner,
			zev_type="vzev",
			start_date=date(2026, 1, 1),
			invoice_prefix="RES",
		)
		self.meter = MeteringPoint.objects.create(
			zev=self.zev,
			meter_id="RES-METER-1",
			meter_type=MeteringPointType.CONSUMPTION,
		)

	def _seed_window(self, start_date, end_date):
		return self.command._seed_meter_readings(
			start_date=start_date,
			end_date=end_date,
			meters=[(self.meter, ReadingDirection.IN, self.command._consumer_one_kwh)],
		)

	def test_window_is_hourly_until_the_fine_tail_then_15_minute(self):
		fine_from = self._seed_window(date(2026, 1, 1), date(2026, 1, 20))
		self.assertEqual(fine_from, date(2026, 1, 7))
		readings = MeterReading.objects.filter(metering_point=self.meter)
		# Jan 1-6 hourly (6 days x 24h), Jan 7-20 at 15-minute resolution (14 days x 96).
		self.assertEqual(readings.filter(resolution=ReadingResolution.HOURLY).count(), 6 * 24)
		self.assertEqual(readings.filter(resolution=ReadingResolution.FIFTEEN_MIN).count(), 14 * 96)
		self.assertTrue(
			readings.filter(
				timestamp=datetime(2026, 1, 6, 23, 0, tzinfo=timezone.utc),
				resolution=ReadingResolution.HOURLY,
			).exists()
		)
		self.assertTrue(
			readings.filter(
				timestamp=datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc),
				resolution=ReadingResolution.FIFTEEN_MIN,
			).exists()
		)

	def test_the_last_hourly_row_sums_its_four_quarter_samples(self):
		self._seed_window(date(2026, 1, 1), date(2026, 1, 20))
		row = MeterReading.objects.get(
			metering_point=self.meter,
			timestamp=datetime(2026, 1, 6, 23, 0, tzinfo=timezone.utc),
		)
		total = sum(
			float(
				self.command._consumer_one_kwh(
					datetime(2026, 1, 6, 23, minute, tzinfo=timezone.utc), 5
				)
			)
			for minute in (0, 15, 30, 45)
		)
		self.assertEqual(row.energy_kwh, Decimal(str(round(total, 4))))

	def test_short_windows_stay_entirely_15_minute(self):
		fine_from = self._seed_window(date(2026, 2, 1), date(2026, 2, 10))
		self.assertEqual(fine_from, date(2026, 2, 1))
		self.assertEqual(MeterReading.objects.filter(metering_point=self.meter).count(), 10 * 96)
		self.assertFalse(
			MeterReading.objects.filter(
				metering_point=self.meter, resolution=ReadingResolution.HOURLY
			).exists()
		)


class SeedDemoInvoiceSettlementTests(TestCase):
	"""The closed-period run settles every invoice (paid, the last one
	cancelled as if issued in error) — the counterpart for the UI's
	paid/cancelled badges, filters and period totals. Re-seeding must
	reproduce it exactly instead of piling invoices up."""

	PERIOD_START = date(2026, 7, 1)
	PERIOD_END = date(2026, 7, 31)

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_settle_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(
			name="Settlement ZEV",
			owner=self.owner,
			zev_type="vzev",
			start_date=self.PERIOD_START,
			invoice_prefix="SET",
		)
		for name, meter_id in (("Alice", "SET-CONS-1"), ("Bob", "SET-CONS-2")):
			participant = self.command._upsert_participant(
				zev=self.zev,
				user=None,
				title=Participant.Title.MS,
				first_name=name,
				last_name="Household",
				email=f"{name.lower()}@settlement.local",
				phone="+41 31 555 00 00",
				address_line1="Testgasse 1",
				postal_code="3000",
				city="Bern",
				valid_from=self.PERIOD_START,
			)
			meter = self.command._upsert_metering_point(
				zev=self.zev,
				meter_id=meter_id,
				meter_type=MeteringPointType.CONSUMPTION,
				location_description=f"{name}'s consumption meter",
			)
			self.command._ensure_assignment(meter, participant, self.PERIOD_START)
		self.command._seed_tariffs(self.zev, self.PERIOD_START)
		# The status transitions are what these tests assert, never the billed
		# consumption volume, so a couple of hourly days of readings suffice.
		_seed_sparse_window_readings(
			start_date=self.PERIOD_START,
			end_date=self.PERIOD_END,
			meters=[
				(
					MeteringPoint.objects.get(zev=self.zev, meter_id="SET-CONS-1"),
					ReadingDirection.IN,
					self.command._consumer_one_kwh,
				),
				(
					MeteringPoint.objects.get(zev=self.zev, meter_id="SET-CONS-2"),
					ReadingDirection.IN,
					self.command._consumer_two_kwh,
				),
			],
		)

	def test_closed_run_marks_every_invoice_paid_and_the_last_cancelled(self):
		invoices = self.command._seed_invoices(
			self.zev, self.PERIOD_START, self.PERIOD_END, closed=True,
		)
		self.assertEqual(len(invoices), 2)
		cancelled = [invoice for invoice in invoices if invoice.status == InvoiceStatus.CANCELLED]
		paid = [invoice for invoice in invoices if invoice.status == InvoiceStatus.PAID]
		self.assertEqual(len(cancelled), 1)
		self.assertEqual(len(paid), 1)
		# The cancelled one is the highest invoice number — the one issued last.
		self.assertEqual(cancelled[0].invoice_number, max(invoice.invoice_number for invoice in invoices))
		# Settled invoices carry a sent date, like really-sent mail would.
		for invoice in invoices:
			self.assertIsNotNone(invoice.sent_at)

	def test_closed_run_survives_a_reseed(self):
		self.command._seed_invoices(self.zev, self.PERIOD_START, self.PERIOD_END, closed=True)
		# ``_seed_invoices`` never deletes: its callers wipe the ZEV's earlier
		# invoices first (the engine refuses to regenerate past draft).
		Invoice.objects.filter(zev=self.zev).delete()
		self.command._seed_invoices(self.zev, self.PERIOD_START, self.PERIOD_END, closed=True)
		self.assertEqual(Invoice.objects.filter(zev=self.zev).count(), 2)
		self.assertEqual(
			set(Invoice.objects.filter(zev=self.zev).values_list("status", flat=True)),
			{InvoiceStatus.PAID, InvoiceStatus.CANCELLED},
		)


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
		self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 3)

	def test_string_false_uses_bounded_deletion(self):
		resp = self.admin_client.post(
			f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
			{
				"delete_all": "false",
				"date_from": "2026-01-15",
				"date_to": "2026-01-31",
			},
			format="json",
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["deleted_count"], 1)
		self.assertEqual(
			list(
				MeterReading.objects.filter(metering_point=self.metering_point)
				.order_by("timestamp")
				.values_list("energy_kwh", flat=True)
			),
			[Decimal("1.0000"), Decimal("3.0000")],
		)

	def test_other_false_inputs_and_omission_never_delete_all(self):
		url = f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/"
		for delete_all in ("0", "off", None):
			with self.subTest(delete_all=delete_all):
				payload = {"date_from": "2026-03-01", "date_to": "2026-03-01"}
				if delete_all is not None:
					payload["delete_all"] = delete_all
				resp = self.admin_client.post(url, payload)
				self.assertEqual(resp.status_code, 200)
				self.assertEqual(resp.data["deleted_count"], 0)
				self.assertEqual(
					MeterReading.objects.filter(metering_point=self.metering_point).count(), 3
				)

	def test_invalid_delete_all_values_are_rejected_without_writes(self):
		url = f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/"
		for invalid in ("definitely", 2, [], {}):
			with self.subTest(invalid=invalid):
				resp = self.admin_client.post(
					url,
					{"delete_all": invalid, "date_from": "2026-01-01", "date_to": "2026-01-31"},
					format="json",
				)
				self.assertEqual(resp.status_code, 400)
				self.assertIn("delete_all", resp.data)
				self.assertEqual(
					MeterReading.objects.filter(metering_point=self.metering_point).count(), 3
				)

	def test_invalid_or_incomplete_ranges_are_rejected_without_writes(self):
		url = f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/"
		for payload, error_field in (
			({"delete_all": False, "date_from": "invalid", "date_to": "2026-01-31"}, "date_from"),
			({"delete_all": False, "date_from": "2026-01-01", "date_to": "invalid"}, "date_to"),
			({"delete_all": False, "date_from": "2026-02-01", "date_to": "2026-01-01"}, "date_to"),
			({"delete_all": False, "date_from": "2026-01-01"}, "date_to"),
			({"delete_all": False, "date_to": "2026-01-31"}, "date_from"),
		):
			with self.subTest(payload=payload):
				resp = self.admin_client.post(url, payload, format="json")
				self.assertEqual(resp.status_code, 400)
				self.assertIn(error_field, resp.data)
				self.assertEqual(
					MeterReading.objects.filter(metering_point=self.metering_point).count(), 3
				)

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

	def test_years_before_steps_back_whole_years(self):
		self.assertEqual(years_before(date(2026, 4, 1), 1), date(2025, 4, 1))
		self.assertEqual(years_before(date(2026, 4, 1), 2), date(2024, 4, 1))
		self.assertEqual(years_before(date(2026, 1, 1), 0), date(2026, 1, 1))

	def test_years_before_clamps_a_leap_day_onto_a_common_year(self):
		"""Reachable only via --start-date; date.replace would raise instead."""
		self.assertEqual(years_before(date(2024, 2, 29), 1), date(2023, 2, 28))


class SeedDemoTariffVersionTests(TestCase):
	"""The demo ZEV carries versioned tariffs, so the Tariffs page shows the
	version history and the price chart at all — both need more than one version
	to appear, and the previous seed produced exactly one per name."""

	def setUp(self):
		self.owner = make_user("seed_tariffs_owner", UserRole.ZEV_OWNER)
		self.zev = Zev.objects.create(name="Seed Tariffs ZEV", owner=self.owner)
		self.valid_from = date(2026, 4, 1)

	def _seed(self, valid_from=None):
		SeedDemoCommand()._seed_tariffs(self.zev, valid_from or self.valid_from)

	def _versions(self, name):
		return list(Tariff.objects.filter(zev=self.zev, name=name).order_by("valid_from"))

	def test_seeds_several_versions_of_a_tariff(self):
		self._seed()
		self.assertEqual(len(self._versions("Grid Energy HT/NT")), 3)
		self.assertEqual(len(self._versions("Local Solar Energy")), 3)
		self.assertEqual(len(self._versions("Levies on Grid Energy")), 3)

	def test_leaves_a_single_version_tariff_for_contrast(self):
		self._seed()
		self.assertEqual(len(self._versions("Feed-in Credit")), 1)
		self.assertEqual(len(self._versions("Metering Service Fee")), 1)

	def test_all_tariffs_cover_the_paid_history_year(self):
		history_start = date(2025, 1, 1)
		SeedDemoCommand()._seed_tariffs(self.zev, self.valid_from, history_start=history_start)
		for name in Tariff.objects.filter(zev=self.zev).values_list("name", flat=True).distinct():
			with self.subTest(name=name):
				self.assertIsNotNone(active_version(self._versions(name), history_start))
				self.assertIsNotNone(active_version(self._versions(name), date(2025, 12, 31)))

	def test_the_version_timeline_is_continuous(self):
		"""A gap bills the energy inside it at nothing, so demo data must not
		ship one — the point of the versioning UI is to prevent them."""
		self._seed()
		for name in ("Local Solar Energy", "Grid Energy HT/NT", "Levies on Grid Energy"):
			with self.subTest(name=name):
				self.assertEqual(find_gaps(self._versions(name)), [])

	def test_only_the_newest_version_is_open_ended(self):
		self._seed()
		versions = self._versions("Grid Energy HT/NT")
		self.assertEqual([version.valid_from for version in versions], [
			date(2024, 4, 1), date(2025, 4, 1), date(2026, 4, 1),
		])
		self.assertEqual([version.valid_to for version in versions], [
			date(2025, 3, 31), date(2026, 3, 31), None,
		])

	def test_the_active_version_carries_the_current_prices(self):
		"""History is added behind the billed window, so invoices generated from
		the seed bill exactly what they billed before it existed."""
		self._seed()
		active = self._versions("Grid Energy HT/NT")[-1]
		prices = {period.period_type: period.price_chf_per_kwh for period in active.periods.all()}
		self.assertEqual(prices[PeriodType.HIGH], Decimal("0.29500"))
		self.assertEqual(prices[PeriodType.LOW], Decimal("0.22500"))

	def test_historical_versions_reuse_the_band_structure_at_older_prices(self):
		self._seed()
		oldest = self._versions("Grid Energy HT/NT")[0]
		bands = {period.period_type: period for period in oldest.periods.all()}
		self.assertEqual(bands[PeriodType.HIGH].price_chf_per_kwh, Decimal("0.24500"))
		self.assertEqual(bands[PeriodType.LOW].price_chf_per_kwh, Decimal("0.19500"))
		# The HT window itself does not change when its price does.
		self.assertEqual(bands[PeriodType.HIGH].weekdays, "0,1,2,3,4")
		self.assertEqual(bands[PeriodType.HIGH].time_from, time(7, 0))

	def test_a_percentage_tariff_versions_its_percentage(self):
		self._seed()
		versions = self._versions("Levies on Grid Energy")
		self.assertEqual(versions[0].billing_mode, BillingMode.PERCENTAGE_OF_ENERGY)
		self.assertEqual(
			[version.percentage for version in versions],
			[Decimal("15.00"), Decimal("16.50"), Decimal("18.00")],
		)

	def test_re_seeding_the_same_window_is_idempotent(self):
		self._seed()
		self._seed()
		self.assertEqual(len(self._versions("Grid Energy HT/NT")), 3)
		self.assertEqual(active_version(self._versions("Grid Energy HT/NT"), date(2026, 5, 1)).valid_to, None)

	def test_re_seeding_after_the_window_moves_does_not_collide(self):
		"""The seed window advances a quarter at a time and the history is
		anchored to it, so the second run's windows overlap the first run's. The
		overlap guard raises on save, so the old versions have to go first."""
		self._seed(date(2026, 1, 1))
		self._seed(date(2026, 4, 1))
		versions = self._versions("Grid Energy HT/NT")
		self.assertEqual([version.valid_from for version in versions], [
			date(2024, 4, 1), date(2025, 4, 1), date(2026, 4, 1),
		])

	def test_re_seeding_leaves_a_hand_added_tariff_alone(self):
		self._seed()
		Tariff.objects.create(
			zev=self.zev, name="Hand Added Levy", category="levies",
			billing_mode=BillingMode.MONTHLY_FEE, fixed_price_chf=Decimal("3.00"),
			valid_from=date(2026, 4, 1),
		)
		self._seed()
		self.assertTrue(Tariff.objects.filter(zev=self.zev, name="Hand Added Levy").exists())


class AllocationModelAndApiTests(TestCase):
	"""Model defaults and API round-trip for allocation_mode / allocation_weight
	(shared metering points, docs/specs/2026-08-shared-metering-points.md)."""

	def setUp(self):
		self.client = APIClient()
		self.admin = make_user("alloc_admin", UserRole.ADMIN)
		self.zev = Zev.objects.create(
			name="Alloc ZEV", owner=self.admin, zev_type="vzev", invoice_prefix="A",
		)
		self.participant = Participant.objects.create(
			zev=self.zev, first_name="Alloc", last_name="Participant",
			email="alloc@example.com", valid_from=date(2026, 1, 1),
		)
		self.mp = MeteringPoint.objects.create(
			zev=self.zev, meter_id="ALLOC-MP-1", meter_type=MeteringPointType.CONSUMPTION,
		)
		auth(self.client, self.admin)

	def test_assignment_allocation_mode_defaults_to_personal(self):
		assignment = MeteringPointAssignment.objects.create(
			metering_point=self.mp, participant=self.participant, valid_from=date(2026, 1, 1),
		)
		self.assertEqual(assignment.allocation_mode, AllocationMode.PERSONAL)

	def test_assignment_accepts_community_allocation_mode_via_api(self):
		resp = self.client.post(
			"/api/v1/zev/metering-point-assignments/",
			{
				"metering_point": str(self.mp.id),
				"participant": str(self.participant.id),
				"valid_from": "2026-01-01",
				"allocation_mode": "community",
			},
			format="json",
		)
		self.assertEqual(resp.status_code, 201, resp.content)
		self.assertEqual(resp.data["allocation_mode"], "community")

	def test_participant_allocation_weight_defaults_to_one(self):
		self.assertEqual(self.participant.allocation_weight, Decimal("1"))

	def test_zero_and_negative_allocation_weight_rejected(self):
		for bad_weight in ("0", "-1"):
			with self.subTest(bad_weight=bad_weight):
				resp = self.client.patch(
					f"/api/v1/zev/participants/{self.participant.id}/",
					{"allocation_weight": bad_weight},
					format="json",
				)
				self.assertEqual(resp.status_code, 400)
				self.assertIn("allocation_weight", resp.data)

	def test_allocation_mode_exposed_in_assignment_serializer(self):
		assignment = MeteringPointAssignment.objects.create(
			metering_point=self.mp, participant=self.participant, valid_from=date(2026, 1, 1),
			allocation_mode=AllocationMode.COMMUNITY,
		)
		resp = self.client.get(f"/api/v1/zev/metering-point-assignments/{assignment.id}/")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data["allocation_mode"], "community")

	def test_allocation_weight_exposed_and_writable_in_participant_serializer(self):
		get_resp = self.client.get(f"/api/v1/zev/participants/{self.participant.id}/")
		self.assertEqual(get_resp.data["allocation_weight"], "1.0000")

		patch_resp = self.client.patch(
			f"/api/v1/zev/participants/{self.participant.id}/",
			{"allocation_weight": "2.5000"},
			format="json",
		)
		self.assertEqual(patch_resp.status_code, 200, patch_resp.content)
		self.participant.refresh_from_db()
		self.assertEqual(self.participant.allocation_weight, Decimal("2.5000"))


class SeedDemoLegacyNameCollisionTests(TestCase):
	"""Legacy-name migration must deduplicate the demo owner's rows that would
	collide on the current flagship name: ``Zev.name`` carries no unique
	constraint, so two rows renamed onto one name would make the later upsert
	raise ``MultipleObjectsReturned`` and roll the whole seed back. Only the
	demo owner's rows are ever candidates — identification by display name
	alone must never touch another tenant's community."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_legacy_collision_owner", UserRole.ZEV_OWNER)
		self.stranger = make_user("seed_legacy_collision_stranger", UserRole.ZEV_OWNER)

	def _create(self, name, owner=None):
		return Zev.objects.create(
			name=name, owner=owner or self.owner, start_date=date(2026, 1, 1),
			zev_type="vzev", invoice_prefix="OZV",
		)

	def _flagship_upsert(self):
		return self.command._upsert_zev(
			owner=self.owner,
			name=DEMO_ZEV_NAME,
			zev_type=ZevType.ZEV,
			start_date=date(2026, 1, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0001",
			billing_interval="quarterly",
			invoice_prefix="OZV",
			invoice_language="de",
			bank_iban="CH9300762011623852957",
			bank_name="Demo Energy Bank",
			vat_mode="inclusive",
			vat_number="",
		)

	def test_legacy_row_next_to_an_already_migrated_row_is_dropped(self):
		self._create(DEMO_ZEV_NAME)
		self._create(DEMO_ZEV_LEGACY_NAME)
		self.command._migrate_legacy_demo_zev_names(owner=self.owner)
		self._flagship_upsert()
		self.assertEqual(Zev.objects.filter(name=DEMO_ZEV_NAME, owner=self.owner).count(), 1)
		self.assertFalse(Zev.objects.filter(name=DEMO_ZEV_LEGACY_NAME).exists())

	def test_duplicate_legacy_rows_keep_the_newest_one(self):
		self._create(DEMO_ZEV_LEGACY_NAME)
		newer = self._create(DEMO_ZEV_LEGACY_NAME)
		self.command._migrate_legacy_demo_zev_names(owner=self.owner)
		self._flagship_upsert()
		rows = list(Zev.objects.filter(name=DEMO_ZEV_NAME, owner=self.owner))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].pk, newer.pk)
		self.assertFalse(Zev.objects.filter(name=DEMO_ZEV_LEGACY_NAME).exists())

	def test_current_name_upsert_does_not_take_over_another_owners_community(self):
		tenant = self._create(DEMO_ZEV_NAME, owner=self.stranger)
		self._flagship_upsert()
		self._flagship_upsert()
		tenant.refresh_from_db()
		self.assertEqual(tenant.owner_id, self.stranger.pk)
		self.assertEqual(Zev.objects.filter(name=DEMO_ZEV_NAME).count(), 2)

	def test_only_the_demo_owner_is_affected(self):
		# A tenant sharing the legacy display name keeps their row untouched
		# even when the demo owner's own rows collide on the current name.
		tenant = self._create(DEMO_ZEV_LEGACY_NAME, owner=self.stranger)
		self._create(DEMO_ZEV_LEGACY_NAME)
		self._create(DEMO_ZEV_NAME)
		self.command._migrate_legacy_demo_zev_names(owner=self.owner)
		self.assertFalse(Zev.objects.filter(name=DEMO_ZEV_LEGACY_NAME, owner=self.owner).exists())
		self.assertTrue(Zev.objects.filter(pk=tenant.pk, name=DEMO_ZEV_LEGACY_NAME).exists())


class SeedDemoWindowShiftTests(TestCase):
	"""A re-seed with a moved window must not leave stale readings behind: the
	flagship wipes all of its meters' readings each run, and the second
	community has to do the same — wiping only the window used to leave the
	previous run's rows on disk once the window moved on."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_window_owner", UserRole.ZEV_OWNER)
		self.clara_user = make_user("seed_window_clara", UserRole.PARTICIPANT)
		self.zev = self.command._upsert_zev(
			owner=self.owner,
			name="Seeded Second ZEV",
			zev_type=ZevType.VZEV,
			start_date=date(2026, 7, 1),
			grid_operator="Stadtwerk Demo AG",
			grid_connection_point="CH-DEMO-GRID-0002",
			billing_interval="monthly",
			invoice_prefix="OZ2",
			invoice_language="en",
			bank_iban="CH4431999123000889012",
			bank_name="Demo Energy Bank",
			vat_mode="registered",
			vat_number="CHE-987.654.321",
		)
		self.command._upsert_vat_rates()

	def _seed(self, start_date, end_date):
		# Window hygiene, not consumption volume, is under test here: keep the
		# fixture small with a few hourly days per month.
		with mock.patch.object(
			self.command,
			"_seed_meter_readings",
			side_effect=_seed_sparse_window_readings,
		):
			return self.command._seed_second_community(
				owner=self.owner,
				clara_user=self.clara_user,
				zev=self.zev,
				start_date=start_date,
				end_date=end_date,
			)

	def test_shifted_window_leaves_no_readings_outside_it(self):
		self._seed(date(2026, 7, 1), date(2026, 9, 6))
		self._seed(date(2026, 8, 1), date(2026, 10, 6))

		all_readings = MeterReading.objects.filter(metering_point__zev=self.zev)
		self.assertTrue(all_readings.exists())
		# July rows from the first window fall outside the second window and
		# must be gone, not just the rows inside the new window replaced.
		self.assertFalse(
			all_readings.filter(
				timestamp__lt=datetime.combine(date(2026, 8, 1), time.min, tzinfo=timezone.utc)
			).exists()
		)


class SeedDemoAuditResetTests(TestCase):
	"""The demo audit reset is scoped: it clears the two demo ZEVs' events and
	the demo actors' events without a ZEV, but must not delete those actors'
	events on *other* communities in a shared dev database."""

	def setUp(self):
		self.command = SeedDemoCommand()
		self.owner = make_user("seed_audit_owner", UserRole.ZEV_OWNER)
		self.admin = make_user("seed_audit_admin", UserRole.ADMIN)
		self.anna_user = make_user("seed_audit_anna", UserRole.PARTICIPANT)
		self.stranger = make_user("seed_audit_stranger", UserRole.PARTICIPANT)
		self.demo_one = Zev.objects.create(name="Demo One", owner=self.owner)
		self.demo_two = Zev.objects.create(name="Demo Two", owner=self.owner)
		self.other_zev = Zev.objects.create(name="Other Community", owner=self.owner)

	def _event(self, user, zev=None):
		return record_audit_event(
			user=user,
			zev=zev,
			action_category=AuditActionCategory.GOVERNANCE,
			action_type="demo.seed.test",
			target_type="zev.Zev",
			summary="Demo audit test event.",
		)

	def _reset(self):
		self.command._reset_demo_audit_trail(
			owner=self.owner,
			admin=self.admin,
			anna_user=self.anna_user,
			zev=self.demo_one,
			second_zev=self.demo_two,
		)

	def test_reset_clears_demo_trails_but_keeps_other_communities(self):
		removed = [
			self._event(self.owner, zev=self.demo_one),
			self._event(self.anna_user, zev=self.demo_two),
			self._event(self.stranger, zev=self.demo_one),  # actor irrelevant on a demo ZEV
			self._event(self.owner),  # demo actor without a ZEV (e.g. vat_rate.create)
			self._event(self.admin),
			self._event(self.anna_user),
		]
		survivors = [
			self._event(self.owner, zev=self.other_zev),
			self._event(self.stranger, zev=self.other_zev),
			self._event(self.stranger),  # non-demo actor, no ZEV
		]

		self._reset()

		for event in removed:
			with self.subTest(pk=event.pk):
				self.assertFalse(AuditEvent.objects.filter(pk=event.pk).exists())
		for event in survivors:
			with self.subTest(pk=event.pk):
				self.assertTrue(AuditEvent.objects.filter(pk=event.pk).exists())


class SeedDemoEndToEndTests(TestCase):
	"""The whole ``seed_demo`` command must run on a small deterministic window
	and re-run identically — the integration check none of the helper-level
	tests cover: every wipe/replace step and the operational-history seeding
	working together."""

	WINDOW = ["--start-date=2025-11-01", "--end-date=2026-01-15"]

	def _run(self):
		buf = StringIO()
		with mock.patch(
			"zev.management.commands.seed_demo.issue_contract_pdf",
			return_value=(None, False),
		):
			call_command("seed_demo", *self.WINDOW, stdout=buf, stderr=buf)

	def _snapshot(self):
		return {
			"readings": MeterReading.objects.count(),
			"invoices": Invoice.objects.count(),
			"invoice_numbers": set(Invoice.objects.values_list("invoice_number", flat=True)),
			"email_logs": EmailLog.objects.count(),
			"import_logs": ImportLog.objects.count(),
			"audit_events": AuditEvent.objects.count(),
			"contracts": ContractIssue.objects.count(),
			"zevs": Zev.objects.count(),
		}

	def test_seed_runs_end_to_end_and_re_seeding_is_identical(self):
		self._run()
		flagship = Zev.objects.get(name=DEMO_ZEV_NAME)
		self.assertEqual(Zev.objects.count(), 2)
		# The settled previous year feeds the reports page, which defaults to
		# the prior calendar year and reads paid invoices only.
		self.assertTrue(
			Invoice.objects.filter(
				zev=flagship,
				status=InvoiceStatus.PAID,
				period_end__year=2025,
			).exists()
		)

		first = self._snapshot()
		self.assertEqual(first["zevs"], 2)
		self.assertGreater(first["readings"], 0)
		self.assertGreater(first["invoices"], 0)
		self.assertGreater(first["email_logs"], 0)
		self.assertEqual(first["import_logs"], 2)
		self.assertGreater(first["audit_events"], 0)
		self.assertEqual(first["contracts"], 0)  # PDF issuance is mocked

		# Every invoice status the UI renders badges for is present.
		have_statuses = set(Invoice.objects.values_list("status", flat=True))
		self.assertTrue({"draft", "approved", "sent", "paid", "cancelled"} <= have_statuses)

		self._run()
		second = self._snapshot()

		self.assertEqual(second["readings"], first["readings"])
		self.assertEqual(second["invoices"], first["invoices"])
		self.assertEqual(second["invoice_numbers"], first["invoice_numbers"])
		self.assertEqual(second["email_logs"], first["email_logs"])
		self.assertEqual(second["import_logs"], first["import_logs"])
		self.assertEqual(second["audit_events"], first["audit_events"])
		self.assertEqual(second["contracts"], first["contracts"])
		self.assertEqual(second["zevs"], 2)
