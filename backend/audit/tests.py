from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from metering.models import MeterReading
from invoices.models import Invoice, InvoiceStatus
from tariffs.models import Tariff, TariffCategory, BillingMode
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev

from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
from audit.services import (
    build_diff,
    build_instance_snapshot,
    infer_zev,
    record_audit_event,
    redact_metadata,
)
from zev.serializers import ParticipantSerializer


from testing.helpers import authenticate as auth, make_user


class AuditEventModelTests(TestCase):
    def setUp(self):
        self.owner = make_user("audit_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("audit_admin", UserRole.ADMIN)
        self.zev = Zev.objects.create(name="Audit ZEV", owner=self.owner)

    def test_audit_event_orders_by_newest_first(self):
        old_event = AuditEvent.objects.create(
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.old",
            target_type="system.Event",
            summary="old",
            zev=self.zev,
        )
        new_event = AuditEvent.objects.create(
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.new",
            target_type="system.Event",
            summary="new",
            zev=self.zev,
        )

        AuditEvent.objects.filter(pk=old_event.pk).update(created_at=timezone.now() - timedelta(days=1))
        AuditEvent.objects.filter(pk=new_event.pk).update(created_at=timezone.now())

        events = list(AuditEvent.objects.all())
        self.assertEqual(events[0].pk, new_event.pk)
        self.assertEqual(events[1].pk, old_event.pk)

    def test_audit_event_persists_actor_and_target_snapshots(self):
        event = record_audit_event(
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="zev.update",
            target_type="zev.Zev",
            target_id=str(self.zev.id),
            target_display=self.zev.name,
            summary="Updated zev",
            user=self.admin,
            zev=self.zev,
        )

        self.admin.username = "changed_name"
        self.admin.save(update_fields=["username"])
        self.zev.name = "Changed ZEV"
        self.zev.save(update_fields=["name"])

        event.refresh_from_db()
        self.assertIn("audit_admin", event.actor_display)
        self.assertEqual(event.target_display, "Audit ZEV")

    def test_redaction_omits_secret_fields(self):
        redacted = redact_metadata(
            {
                "password": "secret",
                "client_secret": "very-secret",
                "bank_iban": "CH9300762011623852957",
                "safe_field": "safe",
            }
        )
        self.assertNotIn("password", redacted)
        self.assertNotIn("client_secret", redacted)
        self.assertEqual(redacted["bank_iban"], "****2957")
        self.assertEqual(redacted["safe_field"], "safe")

    def test_redaction_truncates_large_strings_and_caps_collections(self):
        redacted = redact_metadata(
            {
                "notes": "x" * 800,
                "items": list(range(25)),
                "nested": {"value": "y" * 900},
                "deep_list": [{"value": "z" * 700} for _ in range(22)],
            }
        )

        self.assertEqual(len(redacted["notes"]), 500)
        self.assertTrue(redacted["notes"].endswith("..."))
        self.assertEqual(len(redacted["items"]), 21)
        self.assertEqual(redacted["items"][-1], "...(+5 more)")
        self.assertEqual(len(redacted["nested"]["value"]), 500)
        self.assertTrue(redacted["nested"]["value"].endswith("..."))
        self.assertEqual(len(redacted["deep_list"]), 21)
        self.assertEqual(redacted["deep_list"][-1], "...(+2 more)")

    def test_record_audit_event_truncates_reason(self):
        event = record_audit_event(
            action_category=AuditActionCategory.SYSTEM,
            action_type="system.long_reason",
            target_type="system.Event",
            summary="Long reason event",
            reason="r" * 2500,
            user=self.admin,
            zev=self.zev,
        )

        self.assertEqual(len(event.reason), 2000)
        self.assertTrue(event.reason.endswith("..."))

    def test_build_diff_uses_allowed_fields_only(self):
        diff = build_diff(
            before={"status": "draft", "total": "10.00", "secret": "nope"},
            after={"status": "approved", "total": "10.00", "secret": "changed"},
            allowed_fields=["status", "total"],
        )
        self.assertEqual(diff, {"status": {"before": "draft", "after": "approved"}})

    def test_build_instance_snapshot_reads_fks_without_extra_queries(self):
        participant = Participant.objects.create(
            zev=self.zev,
            first_name="Snap",
            last_name="Shot",
            email="snap@example.com",
            valid_from=timezone.localdate(),
        )
        # Re-fetch so the FK is not already cached on the instance.
        participant = Participant.objects.get(pk=participant.pk)

        with self.assertNumQueries(0):
            snapshot = build_instance_snapshot(participant, ["zev", "first_name", "user"])

        self.assertEqual(snapshot["zev"], str(self.zev.pk))
        self.assertEqual(snapshot["first_name"], "Snap")
        self.assertIsNone(snapshot["user"])

    def test_audited_update_mixin_tracks_every_writable_serializer_field(self):
        """The mixin derives tracked fields from the serializer rather than a
        hand-written list, so a newly added writable field is audited without
        anyone remembering to update a second list."""
        from zev.views import ParticipantViewSet

        view = ParticipantViewSet()
        serializer = ParticipantSerializer()
        tracked = set(view.get_audit_tracked_fields(serializer))
        writable = {name for name, field in serializer.fields.items() if not field.read_only}

        self.assertEqual(tracked, writable)
        # Spot-check the fields whose absence caused the original bug.
        self.assertTrue({"phone", "address_line1", "postal_code", "city", "notes"} <= tracked)

    def test_infer_zev_resolves_nested_objects(self):
        participant = Participant.objects.create(
            zev=self.zev,
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            valid_from=timezone.localdate(),
        )
        metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH1230000000000000000000000000001",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        assignment = MeteringPointAssignment.objects.create(
            metering_point=metering_point,
            participant=participant,
            valid_from=timezone.localdate(),
        )
        invoice = Invoice.objects.create(
            invoice_number="AUD-00001",
            zev=self.zev,
            participant=participant,
            period_start=timezone.localdate(),
            period_end=timezone.localdate(),
            status=InvoiceStatus.DRAFT,
        )

        self.assertEqual(infer_zev(self.zev), self.zev)
        self.assertEqual(infer_zev(participant), self.zev)
        self.assertEqual(infer_zev(assignment), self.zev)
        self.assertEqual(infer_zev(invoice), self.zev)


class AuditEventApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("audit_admin_api", UserRole.ADMIN)
        self.owner1 = make_user("audit_owner1_api", UserRole.ZEV_OWNER)
        self.owner2 = make_user("audit_owner2_api", UserRole.ZEV_OWNER)
        self.participant_user = make_user("audit_participant_api", UserRole.PARTICIPANT)

        self.zev1 = Zev.objects.create(name="ZEV 1", owner=self.owner1)
        self.zev2 = Zev.objects.create(name="ZEV 2", owner=self.owner2)

        self.owner1_event = AuditEvent.objects.create(
            zev=self.zev1,
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.approve",
            target_type="invoices.Invoice",
            target_id="inv-1",
            summary="Owner1 invoice approved",
            status=AuditEventStatus.SUCCESS,
        )
        self.owner2_event = AuditEvent.objects.create(
            zev=self.zev2,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="zev.update",
            target_type="zev.Zev",
            target_id="zev-2",
            summary="Owner2 zev updated",
            status=AuditEventStatus.FAILED,
        )
        self.global_event = AuditEvent.objects.create(
            zev=None,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.login",
            target_type="accounts.User",
            target_id=str(self.admin.id),
            summary="Admin login",
            status=AuditEventStatus.SUCCESS,
            changes_json={"status": {"before": "x", "after": "y"}},
            metadata_json={"safe": "value"},
        )

    def test_admin_can_list_all_audit_events(self):
        auth(self.client, self.admin)
        response = self.client.get("/api/v1/audit/events/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(str(self.owner1_event.id), ids)
        self.assertIn(str(self.owner2_event.id), ids)
        self.assertIn(str(self.global_event.id), ids)

    def test_zev_owner_sees_only_owned_zev_events(self):
        auth(self.client, self.owner1)
        response = self.client.get("/api/v1/audit/events/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(str(self.owner1_event.id), ids)
        self.assertNotIn(str(self.owner2_event.id), ids)
        self.assertNotIn(str(self.global_event.id), ids)

    def test_owner_cannot_access_global_event_with_null_zev(self):
        auth(self.client, self.owner1)
        response = self.client.get(f"/api/v1/audit/events/{self.global_event.id}/")
        self.assertEqual(response.status_code, 404)

    def test_participant_cannot_access_audit_api(self):
        auth(self.client, self.participant_user)
        response = self.client.get("/api/v1/audit/events/")
        self.assertEqual(response.status_code, 403)

    def test_list_filters_by_category_status_and_date_range(self):
        AuditEvent.objects.filter(pk=self.owner1_event.pk).update(created_at=timezone.now() - timedelta(days=2))
        auth(self.client, self.admin)
        response = self.client.get(
            "/api/v1/audit/events/",
            {
                "action_category": AuditActionCategory.GOVERNANCE,
                "status": AuditEventStatus.FAILED,
                "date_from": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(self.owner2_event.id))

    def test_detail_returns_full_diff_and_metadata(self):
        auth(self.client, self.admin)
        response = self.client.get(f"/api/v1/audit/events/{self.global_event.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("changes_json", response.data)
        self.assertIn("metadata_json", response.data)
        self.assertEqual(response.data["metadata_json"]["safe"], "value")


class AuditInstrumentationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("phase2_admin", UserRole.ADMIN)
        self.owner = make_user("phase2_owner", UserRole.ZEV_OWNER)
        self.participant_user = make_user("phase2_participant", UserRole.PARTICIPANT)
        self.zev = Zev.objects.create(name="Phase2 ZEV", owner=self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev,
            user=self.participant_user,
            first_name="Pat",
            last_name="User",
            email="pat@example.com",
            valid_from=timezone.localdate(),
        )
        self.invoice = Invoice.objects.create(
            invoice_number="P2-0001",
            zev=self.zev,
            participant=self.participant,
            period_start=timezone.localdate(),
            period_end=timezone.localdate(),
            status=InvoiceStatus.DRAFT,
        )

    def test_invoice_approve_emits_audit_event(self):
        auth(self.client, self.owner)
        response = self.client.post(f"/api/v1/invoices/invoices/{self.invoice.id}/approve/")

        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(action_type="invoice.approve", target_id=str(self.invoice.id)).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.action_category, AuditActionCategory.INVOICE)
        self.assertEqual(event.zev_id, self.zev.id)

    def test_feature_flag_update_emits_audit_event(self):
        flag = FeatureFlag.objects.create(name="phase2_test_flag", enabled=False)
        auth(self.client, self.admin)

        response = self.client.patch(
            f"/api/v1/auth/feature-flags/{flag.id}/",
            {"enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(action_type="feature_flag.update", target_id=str(flag.id)).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.action_category, AuditActionCategory.GOVERNANCE)
        self.assertEqual(event.changes_json.get("enabled", {}).get("before"), False)
        self.assertEqual(event.changes_json.get("enabled", {}).get("after"), True)

    def test_impersonation_denied_for_non_admin_emits_audit_event(self):
        auth(self.client, self.owner)
        response = self.client.post(f"/api/v1/auth/users/{self.participant_user.id}/impersonate/")

        self.assertEqual(response.status_code, 403)
        event = AuditEvent.objects.filter(
            action_type="impersonation.issue_token",
            target_id=str(self.participant_user.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.action_category, AuditActionCategory.AUTH)


class AuditPhase3InstrumentationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("phase3_admin", UserRole.ADMIN)
        self.owner = make_user("phase3_owner", UserRole.ZEV_OWNER)
        self.participant_user = make_user("phase3_participant", UserRole.PARTICIPANT)
        self.guest_user = make_user("phase3_guest", UserRole.GUEST)
        self.zev = Zev.objects.create(name="Phase3 ZEV", owner=self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev,
            user=self.participant_user,
            first_name="Phase",
            last_name="Three",
            email="phase3@example.com",
            valid_from=timezone.localdate(),
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH9990000000000000000000000000001",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.metering_point,
            participant=self.participant,
            valid_from=timezone.localdate(),
        )

    def test_participant_link_account_emits_audit_event(self):
        auth(self.client, self.admin)
        response = self.client.post(
            f"/api/v1/zev/participants/{self.participant.id}/link-account/",
            {"user_id": self.guest_user.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="participant.link_account",
            target_id=str(self.participant.id),
        ).latest("created_at")
        self.assertEqual(event.action_category, AuditActionCategory.PARTICIPANT)
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)

    @mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
    def test_participant_update_emits_audit_event_with_field_changes(self, mock_geocode_delay):
        auth(self.client, self.admin)
        response = self.client.patch(
            f"/api/v1/zev/participants/{self.participant.id}/",
            {
                "first_name": "Updated",
                "phone": "+41 79 123 45 67",
                "address_line1": "Musterstrasse 1",
                "postal_code": "8000",
                "city": "Zurich",
                "notes": "Prefers e-mail contact.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="participant.update",
            target_id=str(self.participant.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("first_name", {}).get("before"), "Phase")
        self.assertEqual(event.changes_json.get("first_name", {}).get("after"), "Updated")
        self.assertEqual(event.changes_json.get("phone", {}).get("after"), "+41 79 123 45 67")
        self.assertEqual(event.changes_json.get("address_line1", {}).get("after"), "Musterstrasse 1")
        self.assertEqual(event.changes_json.get("postal_code", {}).get("after"), "8000")
        self.assertEqual(event.changes_json.get("city", {}).get("after"), "Zurich")
        self.assertEqual(event.changes_json.get("notes", {}).get("after"), "Prefers e-mail contact.")
        self.assertNotIn("last_name", event.changes_json)

    def test_metering_delete_readings_emits_audit_event(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=timezone.now(),
            energy_kwh="1.2300",
            direction="in",
            resolution="hourly",
            import_source="manual",
        )
        auth(self.client, self.admin)
        response = self.client.post(
            f"/api/v1/zev/metering-points/{self.metering_point.id}/delete-readings/",
            {"delete_all": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(
            action_type="metering_point.delete_readings",
            target_id=str(self.metering_point.id),
        ).latest("created_at")
        self.assertEqual(event.action_category, AuditActionCategory.METERING)
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)

    def test_tariff_create_emits_audit_event(self):
        auth(self.client, self.owner)
        response = self.client.post(
            "/api/v1/tariffs/tariffs/",
            {
                "zev": str(self.zev.id),
                "name": "Phase3 Tariff",
                "category": TariffCategory.ENERGY,
                "billing_mode": BillingMode.ENERGY,
                "energy_type": "local",
                "valid_from": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        tariff_id = response.data["id"]
        event = AuditEvent.objects.filter(action_type="tariff.create", target_id=str(tariff_id)).latest("created_at")
        self.assertEqual(event.action_category, AuditActionCategory.TARIFF)
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)

    def test_import_without_file_emits_failed_audit_event(self):
        auth(self.client, self.owner)
        response = self.client.post("/api/v1/metering/import/csv/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        event = AuditEvent.objects.filter(action_type="import.upload").latest("created_at")
        self.assertEqual(event.action_category, AuditActionCategory.IMPORT)
        self.assertEqual(event.status, AuditEventStatus.FAILED)

    def test_metering_point_update_emits_audit_event_with_field_changes(self):
        auth(self.client, self.admin)
        response = self.client.patch(
            f"/api/v1/zev/metering-points/{self.metering_point.id}/",
            {"meter_id": "CH9990000000000000000000000000099", "location_description": "Basement"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="metering_point.update",
            target_id=str(self.metering_point.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("meter_id", {}).get("after"), "CH9990000000000000000000000000099")
        self.assertEqual(event.changes_json.get("location_description", {}).get("after"), "Basement")

    def test_metering_assignment_update_emits_audit_event_with_field_changes(self):
        other_metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH9990000000000000000000000000002",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        assignment = MeteringPointAssignment.objects.get(
            metering_point=self.metering_point,
            participant=self.participant,
        )
        auth(self.client, self.admin)
        response = self.client.patch(
            f"/api/v1/zev/metering-point-assignments/{assignment.id}/",
            {"metering_point": str(other_metering_point.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="metering_assignment.update",
            target_id=str(assignment.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("metering_point", {}).get("after"), str(other_metering_point.id))

    def test_tariff_update_emits_audit_event_with_field_changes(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Phase3 Grid Tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type="grid",
            valid_from=timezone.localdate(),
        )
        auth(self.client, self.owner)
        response = self.client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.id}/",
            {"name": "Updated Grid Tariff", "notes": "Renegotiated rate."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="tariff.update",
            target_id=str(tariff.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("name", {}).get("after"), "Updated Grid Tariff")
        self.assertEqual(event.changes_json.get("notes", {}).get("after"), "Renegotiated rate.")

    def test_tariff_period_update_emits_audit_event_with_field_changes(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Phase3 Flat Tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type="local",
            valid_from=timezone.localdate(),
        )
        period = tariff.periods.create(period_type="flat", price_chf_per_kwh="0.20000")
        auth(self.client, self.owner)
        response = self.client.patch(
            f"/api/v1/tariffs/periods/{period.id}/",
            {"price_chf_per_kwh": "0.25000"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="tariff_period.update",
            target_id=str(period.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("price_chf_per_kwh", {}).get("after"), "0.25000")

    def test_user_update_emits_audit_event_with_field_changes(self):
        auth(self.client, self.admin)
        response = self.client.patch(
            f"/api/v1/auth/users/{self.participant_user.id}/",
            {"first_name": "Updated", "last_name": "Name", "must_change_password": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        event = AuditEvent.objects.filter(
            action_type="user.update",
            target_id=str(self.participant_user.id),
        ).latest("created_at")
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.changes_json.get("first_name", {}).get("after"), "Updated")
        self.assertEqual(event.changes_json.get("last_name", {}).get("after"), "Name")
        self.assertEqual(event.changes_json.get("must_change_password", {}).get("after"), True)
