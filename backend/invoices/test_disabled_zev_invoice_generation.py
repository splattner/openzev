"""ZEV lifecycle phase 2 follow-up: generate/generate-all bypass
ZevScopedQuerySetMixin entirely (a direct Participant/Zev lookup, not a
ModelViewSet create), so assert_within_scope's disabled-ZEV rule never
reaches them. This is their own equivalent check.

Deliberately not covered here: every other invoice action operates on an
*existing* invoice (send-email, approve, mark-sent, mark-paid, cancel,
retry-email, generate-pdf, and the *-all batch variants built on the same
_get_period_invoices helper) — that is the same already-documented gap as
Tariff/TariffPeriod/MeterReading existing-row edits (see
BaseZevScopedPermission.has_object_permission), left for a follow-up rather
than fixed piecemeal here.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from testing.helpers import authenticate as auth


class GenerateSingleInvoiceTests(TestCase):
    def setUp(self):
        self.owner = make_user("dzg_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("dzg_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Disabled-gen ZEV")
        self.participant = make_participant(self.zev)
        self.zev.disabled_at = timezone.now()
        self.zev.save()

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)

    def _generate(self, client):
        return client.post("/api/v1/invoices/invoices/generate/", {
            "participant_id": str(self.participant.pk),
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        })

    def test_owner_cannot_generate_for_a_disabled_zev(self):
        response = self._generate(self.owner_client)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("disabled", response.json()["error"].lower())
        self.assertFalse(Invoice.objects.filter(participant=self.participant).exists())

    def test_admin_is_not_blocked_by_the_disabled_check(self):
        """Reaches the engine rather than the disabled-ZEV 400 — the engine
        call itself is mocked out (returning a real, separately-created
        invoice) so this stays a permission test, not an engine/allocation
        test."""
        stand_in = make_invoice(self.zev, self.participant)
        with mock.patch("invoices.views.generate_invoice", return_value=stand_in) as mocked:
            response = self._generate(self.admin_client)
        mocked.assert_called_once()
        self.assertNotEqual(response.status_code, 400)


class GenerateAllInvoicesTests(TestCase):
    def setUp(self):
        self.owner = make_user("dzga_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("dzga_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Disabled-gen-all ZEV")
        make_participant(self.zev)
        self.zev.disabled_at = timezone.now()
        self.zev.save()

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)

    def _generate_all(self, client):
        return client.post("/api/v1/invoices/invoices/generate-all/", {
            "zev_id": str(self.zev.id),
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        })

    def test_owner_cannot_batch_generate_for_a_disabled_zev(self):
        with mock.patch("invoices.views.generate_zev_invoices_task") as task:
            response = self._generate_all(self.owner_client)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("disabled", response.json()["error"].lower())
        task.delay.assert_not_called()

    def test_admin_is_not_blocked_by_the_disabled_check(self):
        with mock.patch("invoices.views.preflight_dynamic_prices"), \
             mock.patch("invoices.views.generate_zev_invoices_task") as task:
            response = self._generate_all(self.admin_client)
        self.assertNotEqual(response.status_code, 400)
        task.delay.assert_called_once()
