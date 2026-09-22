"""ZEV lifecycle phase 2 follow-up, part 2: every action on an *existing*
invoice under a disabled ZEV (as opposed to creating a new one — see
test_disabled_zev_invoice_generation.py). ``IsZevOwnerOrAdmin`` has no
``has_object_permission`` the way ``BaseZevScopedPermission`` gives
``Participant``/``MeteringPoint``, so each of these needed its own check
(``invoices.views._deny_if_zev_disabled``) rather than inheriting one.

``revoke-access`` and the two PDF-download reads are deliberately not
covered: revoking reduces exposure, which is fine on a disabled ZEV, and
downloads are reads — the owner keeps read access everywhere else too.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from invoices.models import EmailLog, Invoice, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from testing.helpers import authenticate as auth


class _DisabledZevWithInvoice(TestCase):
    def setUp(self):
        self.owner = make_user("dzw_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("dzw_admin", UserRole.ADMIN)
        self.zev = make_zev(self.owner, "Disabled-write ZEV")
        self.participant = make_participant(self.zev)
        self.invoice = make_invoice(self.zev, self.participant, InvoiceStatus.DRAFT)
        self.zev.disabled_at = timezone.now()
        self.zev.save()

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)

    def _action(self, client, invoice, url_path):
        return client.post(f"/api/v1/invoices/invoices/{invoice.pk}/{url_path}/")

    def assertDisabledDenial(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("disabled", response.json()["error"].lower())


class DestroyTests(_DisabledZevWithInvoice):
    def test_owner_cannot_delete_a_draft_invoice(self):
        response = self.owner_client.delete(f"/api/v1/invoices/invoices/{self.invoice.pk}/")
        self.assertDisabledDenial(response)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())

    def test_admin_can_still_delete_a_draft_invoice(self):
        response = self.admin_client.delete(f"/api/v1/invoices/invoices/{self.invoice.pk}/")
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())

    def test_denial_is_audited(self):
        self.owner_client.delete(f"/api/v1/invoices/invoices/{self.invoice.pk}/")
        event = AuditEvent.objects.filter(action_type="invoice.delete").latest("created_at")
        self.assertEqual(event.status, "denied")


class StatusTransitionTests(_DisabledZevWithInvoice):
    def test_owner_cannot_approve(self):
        response = self._action(self.owner_client, self.invoice, "approve")
        self.assertDisabledDenial(response)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.DRAFT)

    def test_admin_can_still_approve(self):
        response = self._action(self.admin_client, self.invoice, "approve")
        self.assertEqual(response.status_code, 200, response.content)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.APPROVED)

    def test_owner_cannot_cancel(self):
        response = self._action(self.owner_client, self.invoice, "cancel")
        self.assertDisabledDenial(response)


class GeneratePdfTests(_DisabledZevWithInvoice):
    def test_owner_cannot_regenerate_pdf(self):
        response = self._action(self.owner_client, self.invoice, "generate-pdf")
        self.assertDisabledDenial(response)

    def test_admin_can_still_regenerate_pdf(self):
        with mock.patch("invoices.views.save_invoice_pdf"):
            response = self._action(self.admin_client, self.invoice, "generate-pdf")
        self.assertNotEqual(response.status_code, 400)


class SendEmailTests(_DisabledZevWithInvoice):
    def test_owner_cannot_send_email(self):
        with mock.patch("invoices.views.send_invoice_email_task") as task:
            response = self._action(self.owner_client, self.invoice, "send-email")
        self.assertDisabledDenial(response)
        task.delay.assert_not_called()

    def test_admin_can_still_send_email(self):
        with mock.patch("invoices.views.send_invoice_email_task") as task:
            response = self._action(self.admin_client, self.invoice, "send-email")
        self.assertNotEqual(response.status_code, 400)
        task.delay.assert_called_once()


class RetryEmailTests(_DisabledZevWithInvoice):
    def setUp(self):
        super().setUp()
        self.email_log = EmailLog.objects.create(
            invoice=self.invoice, recipient="paula@example.com",
            subject="Invoice", status=EmailLog.Status.FAILED,
        )

    def _retry(self, client):
        return client.post(
            f"/api/v1/invoices/invoices/{self.invoice.pk}/retry-email/{self.email_log.pk}/"
        )

    def test_owner_cannot_retry(self):
        with mock.patch("invoices.views.send_invoice_email_task") as task:
            response = self._retry(self.owner_client)
        self.assertDisabledDenial(response)
        task.delay.assert_not_called()

    def test_admin_can_still_retry(self):
        with mock.patch("invoices.views.send_invoice_email_task") as task:
            response = self._retry(self.admin_client)
        self.assertNotEqual(response.status_code, 400)
        task.delay.assert_called_once()


class BatchActionTests(_DisabledZevWithInvoice):
    def _batch(self, client, url_path):
        return client.post(f"/api/v1/invoices/invoices/{url_path}/", {
            "zev_id": str(self.zev.id),
            "period_start": str(self.invoice.period_start),
            "period_end": str(self.invoice.period_end),
        }, format="json")

    def test_owner_cannot_approve_all(self):
        response = self._batch(self.owner_client, "approve-all")
        self.assertDisabledDenial(response)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.DRAFT)

    def test_owner_cannot_send_all(self):
        with mock.patch("invoices.views.send_invoice_email_task") as task:
            response = self._batch(self.owner_client, "send-all")
        self.assertDisabledDenial(response)
        task.delay.assert_not_called()

    def test_owner_cannot_generate_pdfs_all(self):
        with mock.patch("invoices.views.generate_zev_pdfs_task") as task:
            response = self._batch(self.owner_client, "generate-pdfs-all")
        self.assertDisabledDenial(response)
        task.delay.assert_not_called()

    def test_admin_can_still_approve_all(self):
        response = self._batch(self.admin_client, "approve-all")
        self.assertEqual(response.status_code, 200, response.content)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.APPROVED)

    def test_download_pdfs_is_not_blocked_for_the_owner(self):
        """The one read among the batch actions — exempt, matching every
        other disabled-ZEV rule (the owner keeps read access)."""
        response = self._batch(self.owner_client, "download-pdfs")
        # No PDF on this invoice, so a 404 ("no PDFs for this period") — the
        # point is it is *not* the disabled-ZEV 400.
        self.assertEqual(response.status_code, 404, response.content)


class RevokeAccessIsNotBlockedTests(_DisabledZevWithInvoice):
    """Revoking is protective, not something the disabled-ZEV rule should
    stand in the way of."""

    def test_owner_can_still_revoke_access(self):
        from invoices import access_tokens

        access_tokens.get_or_create_for_invoice(self.invoice)
        response = self._action(self.owner_client, self.invoice, "revoke-access")
        self.assertEqual(response.status_code, 200, response.content)
