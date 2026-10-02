"""Pins who sees and may change what, for accounts with one relationship (#761).

#761 phase 1 rewrites access from a platform-wide role (``User.role`` plus
``Zev.owner``) to per-ZEV grants and the union of an account's relationships
(SPEC-2026-10-zev-access-grants, ADR 0027). Its first promise is that an
account holding exactly one relationship — every account today — sees and can
do exactly what it did before. This module records that behaviour *before* the
rewrite, so every later step has to keep it green unchanged.

The world: two communities with different owners. Alpha's owner is also a
participant of Alpha (as self-setup creates them); a tenant is a participant of
Alpha only; a guest relates to nothing. Expected sets are computed from the
database ("everything in Alpha"), never hard-coded ids.

When a later phase changes one of these answers on purpose, change the
expectation here in the same PR and say why in a comment.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from audit.models import AuditActionCategory, AuditEvent
from audit.services import record_audit_event
from invoices.models import Invoice, InvoiceStatus
from mcp_server.tests.conftest import call_tool, client_for
from metering.models import ImportLog, MeterReading, ReadingResolution
from tariffs.models import Tariff, TariffPeriod
from testing.helpers import authenticate, make_user
from zev.models import MeteringPoint, MeteringPointAssignment, Participant, Zev
from zev.test_transfer import build_populated_zev

ROLES = ("admin", "owner", "tenant", "guest")

LISTS = {
    "zevs": ("/api/v1/zev/zevs/", Zev, ""),
    "participants": ("/api/v1/zev/participants/", Participant, "zev"),
    "metering_points": ("/api/v1/zev/metering-points/", MeteringPoint, "zev"),
    "assignments": ("/api/v1/zev/metering-point-assignments/", MeteringPointAssignment, "metering_point__zev"),
    "tariffs": ("/api/v1/tariffs/tariffs/", Tariff, "zev"),
    "tariff_periods": ("/api/v1/tariffs/periods/", TariffPeriod, "tariff__zev"),
    "invoices": ("/api/v1/invoices/invoices/", Invoice, "zev"),
    "readings": ("/api/v1/metering/readings/", MeterReading, "metering_point__zev"),
    "import_logs": ("/api/v1/metering/import-logs/", ImportLog, "zev"),
    "audit_events": ("/api/v1/audit/events/", AuditEvent, "zev"),
}


def _ids(response):
    data = response.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {str(row["id"]) for row in rows}


class AccessWorldMixin:
    """Builds the two-community world once per test class."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("acc_admin", UserRole.ADMIN)
        cls.owner = make_user("acc_owner_a", UserRole.USER, may_create_zev=True)
        cls.owner_b = make_user("acc_owner_b", UserRole.USER, may_create_zev=True)
        cls.tenant = make_user("acc_tenant", UserRole.USER)
        cls.guest = make_user("acc_guest", UserRole.USER)

        cls.alpha = build_populated_zev(cls.owner, name="Alpha", meter_prefix="ALPHA")
        cls.beta = build_populated_zev(cls.owner_b, name="Beta", meter_prefix="BETA")
        # Self-setup onboards an owner as their own community's participant.
        cls.owner_participant = Participant.objects.create(
            zev=cls.alpha, user=cls.owner, first_name="Olivia", last_name="Owner",
            email="olivia@example.com", valid_from=date(2026, 1, 1),
        )
        # Bob holds Alpha's consumption meter; the tenant is Bob.
        cls.tenant_participant = Participant.objects.get(zev=cls.alpha, party__first_name="Bob")
        cls.tenant_participant.user = cls.tenant
        cls.tenant_participant.save()
        cls.tenant_meter = MeteringPoint.objects.get(meter_id="ALPHA-CONS-1")
        cls.tenant_sent = Invoice.objects.create(
            zev=cls.alpha, participant=cls.tenant_participant, invoice_number="ALPHA-BOB-SENT",
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            status=InvoiceStatus.SENT, total_chf=Decimal("10.00"),
        )
        cls.tenant_draft = Invoice.objects.create(
            zev=cls.alpha, participant=cls.tenant_participant, invoice_number="ALPHA-BOB-DRAFT",
            period_start=date(2026, 3, 1), period_end=date(2026, 3, 31),
            status=InvoiceStatus.DRAFT, total_chf=Decimal("11.00"),
        )
        cls.beta_draft = Invoice.objects.create(
            zev=cls.beta, participant=Participant.objects.get(zev=cls.beta, party__first_name="Bob"),
            invoice_number="BETA-BOB-DRAFT", period_start=date(2026, 3, 1), period_end=date(2026, 3, 31),
            status=InvoiceStatus.DRAFT, total_chf=Decimal("12.00"),
        )
        # Beta produces far more than Alpha, so a leak of Beta's totals shows.
        MeterReading.objects.create(
            metering_point=MeteringPoint.objects.get(meter_id="BETA-PROD-1"),
            timestamp=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("100.0000"), direction="out", resolution=ReadingResolution.HOURLY,
        )
        for zev, owner in ((cls.alpha, cls.owner), (cls.beta, cls.owner_b)):
            ImportLog.objects.create(zev=zev, imported_by=owner, source="csv", filename=f"{zev.name}.csv")
            record_audit_event(
                action_category=AuditActionCategory.INVOICE, action_type="regression.marker",
                target_type="zev.Zev", target_id=str(zev.pk), summary="marker", user=owner, zev=zev,
            )

    def user_for(self, role):
        return {"admin": self.admin, "owner": self.owner, "tenant": self.tenant, "guest": self.guest}[role]

    def client_as(self, role):
        client = APIClient()
        authenticate(client, self.user_for(role))
        return client

    @staticmethod
    def all_ids(model):
        return {str(pk) for pk in model.objects.values_list("pk", flat=True)}

    def alpha_ids(self, model, zev_path):
        lookup = f"{zev_path}" if zev_path else "pk"
        return {str(pk) for pk in model.objects.filter(**{lookup: self.alpha.pk}).values_list("pk", flat=True)}


class SingleRelationshipVisibilityMatrixTests(AccessWorldMixin, TestCase):
    """What each account sees on every ZEV-scoped list today."""

    def expected(self, name, role):
        """A set of ids, or an HTTP status code for a refused list."""
        _, model, zev_path = LISTS[name]
        if role == "admin":
            return self.all_ids(model)
        if role == "owner":
            return self.alpha_ids(model, zev_path)
        tenant_sees = {
            # Only the meter the tenant holds an assignment for.
            "metering_points": {str(self.tenant_meter.pk)},
            # Only their own invoices, and only once sent (#861).
            "invoices": {str(self.tenant_sent.pk)},
        }
        if name in tenant_sees:
            return tenant_sees[name] if role == "tenant" else set()
        return 403

    def test_list_matrix(self):
        for name, (url, _, _) in LISTS.items():
            for role in ROLES:
                with self.subTest(list=name, role=role):
                    response = self.client_as(role).get(url)
                    expected = self.expected(name, role)
                    if isinstance(expected, int):
                        self.assertEqual(response.status_code, expected, response.content[:200])
                    else:
                        self.assertEqual(response.status_code, 200, response.content[:200])
                        self.assertEqual(_ids(response), expected)

    def test_owner_cannot_open_another_communitys_rows(self):
        beta_bob = Participant.objects.get(zev=self.beta, party__first_name="Bob")
        beta_rows = {
            "zev": f"/api/v1/zev/zevs/{self.beta.pk}/",
            "participant": f"/api/v1/zev/participants/{beta_bob.pk}/",
            "metering_point": f"/api/v1/zev/metering-points/{MeteringPoint.objects.get(meter_id='BETA-CONS-1').pk}/",
            "tariff": f"/api/v1/tariffs/tariffs/{Tariff.objects.get(zev=self.beta).pk}/",
            "invoice": f"/api/v1/invoices/invoices/{self.beta_draft.pk}/",
        }
        client = self.client_as("owner")
        for label, url in beta_rows.items():
            with self.subTest(row=label):
                self.assertEqual(client.get(url).status_code, 404)

    def test_tenant_opens_only_their_own_sent_invoice(self):
        client = self.client_as("tenant")
        alice_invoice = Invoice.objects.get(zev=self.alpha, participant__party__first_name="Alice")
        self.assertEqual(client.get(f"/api/v1/invoices/invoices/{self.tenant_sent.pk}/").status_code, 200)
        self.assertEqual(client.get(f"/api/v1/invoices/invoices/{self.tenant_draft.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/api/v1/invoices/invoices/{alice_invoice.pk}/").status_code, 404)

    def test_zev_scoped_reports_matrix(self):
        period = {"period_start": "2026-01-01", "period_end": "2026-01-31"}
        expected = {
            # role: (Alpha, Beta)
            "admin": (200, 200),
            "owner": (200, 403),
            "tenant": (403, 403),
            "guest": (403, 403),
        }
        for role, (alpha_status, beta_status) in expected.items():
            client = self.client_as(role)
            for label, zev, status in (("alpha", self.alpha, alpha_status), ("beta", self.beta, beta_status)):
                with self.subTest(role=role, zev=label, endpoint="readiness"):
                    response = client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": zev.pk})
                    self.assertEqual(response.status_code, status)
                with self.subTest(role=role, zev=label, endpoint="period-overview"):
                    response = client.get(
                        "/api/v1/invoices/invoices/period-overview/", {"zev_id": zev.pk, **period}
                    )
                    self.assertEqual(response.status_code, status)

    def test_dashboard_summary_matrix(self):
        url = "/api/v1/metering/readings/dashboard-summary/"
        with self.subTest(role="admin"):
            response = self.client_as("admin").get(url, {"zev_id": self.beta.pk})
            self.assertEqual((response.status_code, response.json()["summary_kind"]), (200, "zev"))
            self.assertEqual(self.client_as("admin").get(url).status_code, 400)
        with self.subTest(role="owner"):
            client = self.client_as("owner")
            self.assertEqual(client.get(url).json()["summary_kind"], "zev")
            self.assertEqual(client.get(url, {"zev_id": self.alpha.pk}).status_code, 200)
            self.assertEqual(client.get(url, {"zev_id": self.beta.pk}).status_code, 403)
        for role in ("tenant", "guest"):
            client = self.client_as(role)
            for zev_id in (None, self.alpha.pk, self.beta.pk):
                with self.subTest(role=role, zev_id=zev_id):
                    response = client.get(url, {"zev_id": zev_id} if zev_id else {})
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["summary_kind"], "participant")
                    # Beta produced 104 kWh; a participant must never get it.
                    self.assertLess(body["zev_totals"]["produced_kwh"], 100)
                    if role == "guest":
                        self.assertEqual(body["zev_totals"]["produced_kwh"], 0)

    def test_self_service_statement_matrix(self):
        url = "/api/v1/invoices/invoices/annual-statement/"
        beta_bob = Participant.objects.get(zev=self.beta, party__first_name="Bob")
        with mock.patch("invoices.views_reports.generate_annual_statement_pdf", return_value=b"%PDF-stub"):
            self.assertEqual(self.client_as("tenant").get(url, {"year": 2026}).status_code, 200)
            # A guest is not treated as self-service (that keys on the
            # participant role), so it lands in the manager branch, which
            # demands zev_id and participant_id.
            self.assertEqual(self.client_as("guest").get(url, {"year": 2026}).status_code, 400)
            owner = self.client_as("owner")
            self.assertEqual(
                owner.get(url, {"year": 2026, "zev_id": self.alpha.pk,
                                "participant_id": self.tenant_participant.pk}).status_code,
                200,
            )
            self.assertEqual(
                owner.get(url, {"year": 2026, "zev_id": self.beta.pk, "participant_id": beta_bob.pk}).status_code,
                403,
            )

    def test_mcp_list_zevs_matrix(self):
        FeatureFlag.objects.update_or_create(name=FeatureFlag.MCP_SERVER_ENABLED, defaults={"enabled": True})
        expected = {"admin": {str(self.alpha.pk), str(self.beta.pk)}, "owner": {str(self.alpha.pk)}}
        for role, zev_ids in expected.items():
            with self.subTest(role=role):
                response = call_tool(client_for(self.user_for(role)), "list_zevs")
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]["structuredContent"]
                self.assertEqual({row["id"] for row in result["zevs"]}, zev_ids)
        # The MCP endpoint itself refuses accounts that manage nothing, before
        # any tool runs (ADR 0025's transport-level role gate).
        for role in ("tenant", "guest"):
            with self.subTest(role=role):
                response = call_tool(client_for(self.user_for(role)), "list_zevs")
                self.assertEqual(response.status_code, 403)


class SingleRelationshipWriteMatrixTests(AccessWorldMixin, TestCase):
    """Which writes each account may make today.

    Every attempt runs in a savepoint that is rolled back, so one role's
    successful write (an approval, a deletion) cannot change what the next
    role finds.
    """

    def attempt(self, role, method, url, data=None):
        with transaction.atomic():
            response = getattr(self.client_as(role), method)(url, data, format="json")
            transaction.set_rollback(True)
        return response.status_code

    def assert_matrix(self, method, url, expected, data=None):
        for role, status in zip(ROLES, expected):
            with self.subTest(method=method, url=url, role=role):
                self.assertEqual(self.attempt(role, method, url, data), status)

    def test_zev_settings(self):
        self.assert_matrix("patch", f"/api/v1/zev/zevs/{self.alpha.pk}/", (200, 200, 403, 403), {"notes": "x"})
        self.assert_matrix("patch", f"/api/v1/zev/zevs/{self.beta.pk}/", (200, 404, 403, 403), {"notes": "x"})

    def test_participant_edit(self):
        alice = Participant.objects.get(zev=self.alpha, party__first_name="Alice")
        beta_alice = Participant.objects.get(zev=self.beta, party__first_name="Alice")
        self.assert_matrix("patch", f"/api/v1/zev/participants/{alice.pk}/", (200, 200, 403, 403), {"city": "Bern"})
        self.assert_matrix("patch", f"/api/v1/zev/participants/{beta_alice.pk}/", (200, 404, 403, 403), {"city": "Bern"})

    def test_create_metering_point(self):
        url = "/api/v1/zev/metering-points/"
        self.assert_matrix("post", url, (201, 201, 403, 403), {"zev": str(self.alpha.pk), "meter_id": "ALPHA-NEW-1"})
        # Filing a row under another community is refused as a field error.
        self.assert_matrix("post", url, (201, 400, 403, 403), {"zev": str(self.beta.pk), "meter_id": "BETA-NEW-1"})

    def test_create_tariff(self):
        url = "/api/v1/tariffs/tariffs/"
        body = {
            "name": "New", "category": "energy", "billing_mode": "energy", "energy_type": "local",
            "valid_from": "2026-01-01",
        }
        self.assert_matrix("post", url, (201, 201, 403, 403), {**body, "zev": str(self.alpha.pk)})
        self.assert_matrix("post", url, (201, 400, 403, 403), {**body, "zev": str(self.beta.pk)})

    def test_invoice_workflow(self):
        draft = f"/api/v1/invoices/invoices/{self.tenant_draft.pk}/"
        beta_draft = f"/api/v1/invoices/invoices/{self.beta_draft.pk}/"
        self.assert_matrix("post", f"{draft}approve/", (200, 200, 403, 403))
        self.assert_matrix("post", f"{beta_draft}approve/", (200, 404, 403, 403))
        # The tenant cannot see their own draft (#861), so its delete 404s.
        self.assert_matrix("delete", draft, (204, 204, 404, 404))
        self.assert_matrix("delete", beta_draft, (204, 404, 404, 404))

    def test_export_job_creation(self):
        url = "/api/v1/exports/jobs/"
        body = {"export_type": "annual_statements", "params": {"year": 2026}}
        with mock.patch("exports.views.run_export_job.delay"):
            # 202: the job is accepted and runs asynchronously.
            self.assert_matrix("post", url, (202, 202, 403, 403), {**body, "zev_id": str(self.alpha.pk)})
            self.assert_matrix("post", url, (202, 403, 403, 403), {**body, "zev_id": str(self.beta.pk)})

    def test_disable_zev(self):
        self.assert_matrix("post", f"/api/v1/zev/zevs/{self.alpha.pk}/disable/", (200, 200, 403, 403), {"reason": "x"})
        self.assert_matrix("post", f"/api/v1/zev/zevs/{self.beta.pk}/disable/", (200, 404, 403, 403), {"reason": "x"})

    def test_account_linking_is_admin_only(self):
        alice = Participant.objects.get(zev=self.alpha, party__first_name="Alice")
        self.assert_matrix(
            "post", f"/api/v1/zev/participants/{alice.pk}/link-account/",
            (200, 403, 403, 403), {"user_id": self.guest.pk},
        )

    def test_impersonation(self):
        # Changed on purpose in #761 step 5: any non-admin account may be
        # impersonated (impersonation is on the account), so a guest is 200 now.
        for target, admin_status in ((self.tenant, 200), (self.owner_b, 200), (self.guest, 200), (self.admin, 400)):
            with self.subTest(target=target.username):
                url = f"/api/v1/auth/users/{target.pk}/impersonate/"
                self.assertEqual(self.attempt("admin", "post", url), admin_status)
                self.assertEqual(self.attempt("owner", "post", url), 403)

    def test_self_setup_needs_an_owner_account(self):
        body = {"name": "Mine", "start_date": "2026-01-01"}
        self.assertEqual(self.attempt("tenant", "post", "/api/v1/zev/zevs/self-setup/", body), 403)
        self.assertEqual(self.attempt("guest", "post", "/api/v1/zev/zevs/self-setup/", body), 403)
        # The owner already has an active community.
        self.assertEqual(self.attempt("owner", "post", "/api/v1/zev/zevs/self-setup/", body), 400)
