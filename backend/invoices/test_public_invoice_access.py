"""Coverage for unauthenticated invoice access (spec §5.1, §9, §12).

The tests that matter most here are the negative ones. This endpoint is served
without a session on the strength of a single claim — that a response describes
only the invoice the reader is holding — so the suite spends most of its effort
asserting the response stays that narrow and that every failure is
indistinguishable from every other.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventSource
from testing.helpers import make_user

from . import access_tokens
from .models import InvoiceItem, InvoiceStatus
from .test_helpers import make_invoice, make_participant, make_zev

PUBLIC_URL = "/api/v1/public/invoices/{prefix}/"
PUBLIC_PDF_URL = "/api/v1/public/invoices/{prefix}/pdf/"


class PublicInvoiceTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("pia_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Access ZEV")
        self.zev.participant_invoice_access = True
        self.zev.save()

        self.participant = make_participant(self.zev, first="Anna", last="Muster")
        self.invoice = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        self.invoice.total_local_kwh = Decimal("320.5000")
        self.invoice.total_grid_kwh = Decimal("180.0000")
        self.invoice.total_chf = Decimal("238.87")
        self.invoice.save()
        InvoiceItem.objects.create(
            invoice=self.invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            description="Solarstrom ZEV", quantity_kwh=Decimal("320.5000"),
            unit="kWh", total_chf=Decimal("72.11"),
        )

        self.token = access_tokens.get_or_create_for_invoice(self.invoice)
        self.secret = self.token.secret

    def _get(self, prefix=None, secret=None, url=PUBLIC_URL):
        return self.client.get(
            url.format(prefix=prefix or self.token.prefix),
            {"s": self.secret if secret is None else secret},
        )


class PublicInvoiceAccessTests(PublicInvoiceTestCase):
    def test_valid_token_returns_the_invoice(self):
        resp = self._get()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["invoice_number"], self.invoice.invoice_number)
        self.assertEqual(resp.json()["total_chf"], "238.87")

    def test_wrong_secret_is_indistinguishable_from_unknown_prefix(self):
        """The one leak that would make walking the keyspace worth starting."""
        wrong_secret = self._get(secret="not-the-secret")
        unknown_prefix = self._get(prefix="ffffffffffffffff")

        self.assertEqual(wrong_secret.status_code, 404)
        self.assertEqual(unknown_prefix.status_code, 404)
        self.assertEqual(wrong_secret.json(), unknown_prefix.json())

    def test_missing_secret_is_404(self):
        resp = self.client.get(PUBLIC_URL.format(prefix=self.token.prefix))
        self.assertEqual(resp.status_code, 404)

    def test_revoked_token_is_404(self):
        access_tokens.revoke(self.token)
        self.assertEqual(self._get().status_code, 404)

    def test_zev_not_opted_in_is_404(self):
        self.zev.participant_invoice_access = False
        self.zev.save()
        self.assertEqual(self._get().status_code, 404)

    def test_no_session_is_created(self):
        """The endpoint authenticates nobody; it resolves a bearer to one row."""
        self._get()
        self.assertNotIn("sessionid", self.client.cookies)


class PublicInvoicePayloadTests(PublicInvoiceTestCase):
    """§9: the response must stay narrow, or the reason it needs no login dies."""

    def test_carries_no_other_invoice(self):
        other = make_invoice(self.zev, self.participant, InvoiceStatus.SENT)
        other.invoice_number = "OTHER-999"
        other.save()

        body = self._get().content.decode()

        self.assertNotIn("OTHER-999", body)

    def test_carries_no_other_participant(self):
        neighbour = make_participant(self.zev, first="Beat", last="Nachbar")
        make_invoice(self.zev, neighbour, InvoiceStatus.SENT)

        body = self._get().content.decode()

        self.assertNotIn("Nachbar", body)
        self.assertNotIn("Beat", body)

    def test_omits_contact_detail(self):
        self.participant.email = "anna@example.com"
        self.participant.save()

        body = self._get().content.decode()

        self.assertNotIn("anna@example.com", body)

    def test_reports_whether_the_invoice_is_paid(self):
        """The one field that can change after the paper was printed."""
        self.assertFalse(self._get().json()["is_paid"])

        self.invoice.status = InvoiceStatus.PAID
        self.invoice.save()

        self.assertTrue(self._get().json()["is_paid"])

    def test_carries_the_consumption_figures(self):
        summary = self._get().json()["energy_summary"]

        self.assertEqual(summary["local_kwh"], "320.5")
        self.assertEqual(summary["grid_kwh"], "180.0")
        self.assertEqual(summary["local_share_pct"], "64")

    def test_energy_summary_is_null_without_consumption(self):
        """The same condition that prints no QR in the first place."""
        self.invoice.total_local_kwh = Decimal("0")
        self.invoice.total_grid_kwh = Decimal("0")
        self.invoice.save()

        self.assertIsNone(self._get().json()["energy_summary"])

    def test_carries_the_line_items(self):
        items = self._get().json()["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["description"], "Solarstrom ZEV")


class PublicInvoicePdfTests(PublicInvoiceTestCase):
    def test_404_when_no_stored_pdf(self):
        """An unauthenticated caller must not be able to trigger a render."""
        resp = self._get(url=PUBLIC_PDF_URL)
        self.assertEqual(resp.status_code, 404)

    def test_streams_the_stored_pdf(self):
        from django.core.files.base import ContentFile

        self.invoice.pdf_file.save("x.pdf", ContentFile(b"%PDF-1.7\n"), save=True)

        resp = self._get(url=PUBLIC_PDF_URL)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_wrong_secret_is_404(self):
        self.assertEqual(self._get(secret="wrong", url=PUBLIC_PDF_URL).status_code, 404)


class InvoiceAccessTokenTests(PublicInvoiceTestCase):
    def test_token_is_stable_across_regeneration(self):
        """A regenerated PDF must carry the same QR as the copy in the post."""
        again = access_tokens.get_or_create_for_invoice(self.invoice)

        self.assertEqual(again.pk, self.token.pk)
        self.assertEqual(again.secret, self.secret, "the link must be reprintable")

    def test_revoke_then_mint_produces_a_new_token(self):
        access_tokens.revoke(self.token)

        fresh = access_tokens.get_or_create_for_invoice(self.invoice)

        self.assertNotEqual(fresh.prefix, self.token.prefix)
        self.assertNotEqual(fresh.secret, self.secret)
        self.assertEqual(self._get().status_code, 404, "the printed link is dead")

    def test_public_url_carries_prefix_and_secret(self):
        url = access_tokens.public_url(self.token)

        self.assertIn(f"/i/{self.token.prefix}", url)
        self.assertIn("s=", url)
        # Round-trips: what is printed is what resolves.
        from urllib.parse import parse_qs, urlparse

        presented = parse_qs(urlparse(url).query)["s"][0]
        self.assertIsNotNone(access_tokens.resolve(self.token.prefix, presented))


class PublicInvoiceAuditTests(PublicInvoiceTestCase):
    def _events(self):
        return AuditEvent.objects.filter(action_type="invoice_link.viewed")

    def test_opening_records_an_event(self):
        self._get()

        event = self._events().get()
        self.assertEqual(event.source, AuditEventSource.INVOICE_LINK)
        self.assertEqual(event.target_display, self.invoice.invoice_number)

    def test_refreshing_does_not_flood_the_log(self):
        """One entry per reading session, not one per refresh."""
        for _ in range(4):
            self._get()

        self.assertEqual(self._events().count(), 1)

    def test_a_later_visit_records_again(self):
        self._get()
        self.token.refresh_from_db()
        self.token.last_used_at = timezone.now() - access_tokens.USE_RECORD_INTERVAL * 2
        self.token.save(update_fields=["last_used_at"])

        self._get()

        self.assertEqual(self._events().count(), 2)

    def test_a_refused_link_records_nothing(self):
        self._get(secret="wrong")

        self.assertEqual(self._events().count(), 0)


class InvoiceAccessQrTests(PublicInvoiceTestCase):
    """The QR on the insights page (spec §6)."""

    def _context(self):
        from .pdf import _build_template_context

        return _build_template_context(self.invoice)

    def test_opted_in_invoice_with_consumption_gets_a_qr(self):
        ctx = self._context()

        self.assertIsNotNone(ctx["access_qr_svg"])
        self.assertIn("<svg", ctx["access_qr_svg"])

    def test_no_qr_when_the_zev_has_not_opted_in(self):
        self.zev.participant_invoice_access = False
        self.zev.save()
        self.invoice.refresh_from_db()

        self.assertIsNone(self._context()["access_qr_svg"])

    def test_no_qr_without_an_insights_page(self):
        """Same condition, not a second one that could drift.

        A fee-only invoice renders no insights page, and the link leads to
        consumption detail it does not have.
        """
        self.invoice.total_local_kwh = Decimal("0")
        self.invoice.total_grid_kwh = Decimal("0")
        self.invoice.save()

        ctx = self._context()

        self.assertIsNone(ctx["energy_summary"])
        self.assertIsNone(ctx["access_qr_svg"])

    def test_rendering_twice_reuses_one_token(self):
        """The printed QR must survive a re-render, so no second token."""
        from .models import InvoiceAccessToken

        self._context()
        self._context()

        self.assertEqual(
            InvoiceAccessToken.objects.filter(invoice=self.invoice).count(), 1
        )

    def test_a_qr_failure_does_not_lose_the_invoice(self):
        """A missing QR costs a convenience; raising would cost the document."""
        from unittest.mock import patch

        with patch("invoices.access_tokens.qr_svg", side_effect=RuntimeError("boom")):
            ctx = self._context()

        self.assertIsNone(ctx["access_qr_svg"])
        self.assertEqual(ctx["invoice"], self.invoice)


class MagicLinkTests(PublicInvoiceTestCase):
    """Tier 2: the escalation from one invoice to the whole account."""

    REQUEST_URL = "/api/v1/public/magic-link/request/"
    CONSUME_URL = "/api/v1/public/magic-link/consume/"

    def setUp(self):
        super().setUp()
        self.participant.email = "anna@example.com"
        self.participant.save()

    def _request(self, prefix=None, secret=None):
        return self.client.post(
            self.REQUEST_URL,
            {"prefix": prefix or self.token.prefix, "s": self.secret if secret is None else secret},
            format="json",
        )

    def _link_token(self):
        from accounts.models import MagicLinkToken

        return MagicLinkToken.objects.filter(user__isnull=False).latest("created_at")

    def test_sends_to_the_address_on_file(self):
        from django.core import mail

        resp = self._request()

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(mail.outbox[-1].to, ["anna@example.com"])

    def test_the_caller_cannot_choose_the_destination(self):
        """The trust anchor: the requester never names the address."""
        from django.core import mail

        self.client.post(
            self.REQUEST_URL,
            {"prefix": self.token.prefix, "s": self.secret, "email": "attacker@example.com"},
            format="json",
        )

        self.assertEqual(mail.outbox[-1].to, ["anna@example.com"])

    def test_a_bad_link_is_still_202(self):
        """Never a signal about which invoices or accounts exist."""
        from django.core import mail

        ok = self._request()
        bad = self._request(secret="wrong")

        self.assertEqual(bad.status_code, 202)
        self.assertEqual(bad.json(), ok.json())
        self.assertEqual(len(mail.outbox), 1, "nothing sent for the bad link")

    def test_a_participant_without_an_address_is_still_202(self):
        from django.core import mail

        self.participant.email = ""
        self.participant.save()

        self.assertEqual(self._request().status_code, 202)
        self.assertEqual(mail.outbox, [])

    def test_consume_issues_a_session(self):
        self._request()

        resp = self.client.post(
            self.CONSUME_URL, {"token": self._link_token().token}, format="json"
        )

        from accounts.cookies import ACCESS_COOKIE, REFRESH_COOKIE

        self.assertEqual(resp.status_code, 200)
        self.assertIn(ACCESS_COOKIE, resp.cookies)
        self.assertIn(REFRESH_COOKIE, resp.cookies)

    def test_consume_is_one_time(self):
        self._request()
        token = self._link_token().token

        self.client.post(self.CONSUME_URL, {"token": token}, format="json")
        second = self.client.post(self.CONSUME_URL, {"token": token}, format="json")

        self.assertEqual(second.status_code, 400)

    def test_expired_link_is_rejected(self):
        from accounts.models import MAGIC_LINK_LIFETIME, MagicLinkToken

        self._request()
        link = self._link_token()
        MagicLinkToken.objects.filter(pk=link.pk).update(
            created_at=timezone.now() - MAGIC_LINK_LIFETIME * 2
        )

        resp = self.client.post(self.CONSUME_URL, {"token": link.token}, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_a_new_request_supersedes_the_previous_link(self):
        """Two taps must not leave a spare key in the inbox."""
        self._request()
        first = self._link_token().token
        self._request()

        resp = self.client.post(self.CONSUME_URL, {"token": first}, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_the_user_is_not_trapped_in_a_password_form(self):
        """Nobody invents a password anywhere in this flow."""
        self._request()
        self.client.post(self.CONSUME_URL, {"token": self._link_token().token}, format="json")

        self.participant.refresh_from_db()
        self.participant.user.refresh_from_db()
        self.assertFalse(self.participant.user.must_change_password)
        self.assertFalse(self.participant.user.has_usable_password())

    def test_consuming_kills_an_outstanding_invitation_password(self):
        """An emailed temporary password must not outlive its purpose."""
        from zev.services import send_participant_invitation

        send_participant_invitation(self.participant, self.owner)
        self.participant.refresh_from_db()
        self.assertTrue(self.participant.user.must_change_password)

        self._request()
        self.client.post(self.CONSUME_URL, {"token": self._link_token().token}, format="json")

        self.participant.user.refresh_from_db()
        self.assertFalse(self.participant.user.has_usable_password())
