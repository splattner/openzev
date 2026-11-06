"""Issuing statements, summaries and the tariff overview (SPEC-2026-11-participant-document-inbox §5.3)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.storage import default_storage
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from inbox.models import DeliveredDocument, DocumentKind
from invoices.models import InvoiceItem, InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import authenticate, make_user
from zev.models import Participant

STATEMENT = "/api/v1/inbox/issue/annual-statement/"
SUMMARY = "/api/v1/inbox/issue/financial-summary/"
TARIFFS = "/api/v1/inbox/issue/tariff-overview/"
YEAR = 2026


def sent_invoice(zev, participant, *, status=InvoiceStatus.SENT, month=3):
    invoice = make_invoice(
        zev, participant, status, period=(date(YEAR, month, 1), date(YEAR, month, 28))
    )
    invoice.approved_at = invoice.sent_at = timezone.now()
    invoice.save(update_fields=["approved_at", "sent_at"])
    return invoice


def add_item(invoice, item_type, total):
    return InvoiceItem.objects.create(
        invoice=invoice, item_type=item_type, description="x", quantity_kwh=Decimal("10"),
        unit_price_chf=Decimal("0.10"), total_chf=Decimal(total),
    )


class IssueBase(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_is_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.account = make_user("inbox_is_account", UserRole.USER)
        self.anna = make_participant(self.zev, user=self.account, first="Anna", last="A")
        self.ben = make_participant(self.zev, first="Ben", last="B")
        self.client = APIClient()
        authenticate(self.client, self.owner)
        patches = [
            mock.patch("inbox.issuing.generate_annual_statement_pdf", side_effect=self._render),
            mock.patch("inbox.issuing.generate_financial_summary_pdf", side_effect=self._render),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    @staticmethod
    def _render(*args, **kwargs):
        participant = next(a for a in args if isinstance(a, Participant))
        return b"%PDF-1.4 for " + str(participant.pk).encode()

    def post(self, url, user=None, **fields):
        client = self.client
        if user is not None:
            client = APIClient()
            authenticate(client, user)
        return client.post(url, {"zev": str(self.zev.pk), **fields}, format="json")


class AnnualStatementTests(IssueBase):
    def test_issues_to_participants_with_sent_invoices_of_the_year(self):
        sent_invoice(self.zev, self.anna)
        # A draft, a cancelled invoice and another year do not make a statement.
        make_invoice(self.zev, self.ben, InvoiceStatus.DRAFT, period=(date(YEAR, 4, 1), date(YEAR, 4, 28)))

        response = self.post(STATEMENT, year=YEAR)

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["delivered"], body["without_account"]), (1, 0))
        document = DeliveredDocument.objects.get()
        self.assertEqual(document.kind, DocumentKind.ANNUAL_STATEMENT)
        self.assertEqual(document.participant, self.anna)
        self.assertEqual((document.period_start, document.period_end), (date(YEAR, 1, 1), date(YEAR, 12, 31)))
        self.assertEqual(document.delivered_by, self.owner)
        self.assertIn(str(YEAR), document.title)
        with document.open_file() as handle:
            self.assertEqual(handle.read(), b"%PDF-1.4 for " + str(self.anna.pk).encode())

    def test_statement_is_rendered_for_the_participant_only_with_sent_invoices(self):
        sent_invoice(self.zev, self.anna)
        self.post(STATEMENT, year=YEAR)

        from inbox import issuing

        issuing.generate_annual_statement_pdf.assert_called_once()
        self.assertTrue(issuing.generate_annual_statement_pdf.call_args.kwargs["sent_only"])

    def test_a_cancelled_or_unsent_invoice_alone_is_not_eligible(self):
        sent_invoice(self.zev, self.anna, status=InvoiceStatus.CANCELLED)
        make_invoice(self.zev, self.ben, InvoiceStatus.DRAFT)

        response = self.post(STATEMENT, year=YEAR)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_issue_annual_statement_supersedes_on_reissue(self):
        sent_invoice(self.zev, self.anna)
        first = self.post(STATEMENT, year=YEAR).json()["documents"][0]["id"]

        second = self.post(STATEMENT, year=YEAR)

        self.assertEqual(second.status_code, 201)
        new_id = second.json()["documents"][0]["id"]
        old = DeliveredDocument.objects.get(pk=first)
        self.assertIsNotNone(old.superseded_at)
        self.assertEqual(str(old.superseded_by_id), new_id)
        self.assertEqual(DeliveredDocument.objects.filter(superseded_at__isnull=True).count(), 1)

    def test_another_year_is_a_separate_document(self):
        sent_invoice(self.zev, self.anna)
        self.post(STATEMENT, year=YEAR)
        other = make_invoice(self.zev, self.anna, InvoiceStatus.SENT, period=(date(2025, 3, 1), date(2025, 3, 28)))
        other.sent_at = other.approved_at = timezone.now()
        other.save(update_fields=["sent_at", "approved_at"])

        self.post(STATEMENT, year=2025)

        self.assertEqual(DeliveredDocument.objects.filter(superseded_at__isnull=True).count(), 2)

    def test_named_participants_must_belong_to_the_zev_and_have_something_to_report(self):
        sent_invoice(self.zev, self.anna)
        stranger = make_participant(make_zev(self.owner, "Other"), first="Eve", last="E")

        self.assertEqual(self.post(STATEMENT, year=YEAR, participant_ids=[str(stranger.pk)]).status_code, 400)
        refused = self.post(STATEMENT, year=YEAR, participant_ids=[str(self.ben.pk)])
        self.assertEqual(refused.status_code, 400)
        self.assertIn("participant_ids", refused.json())
        ok = self.post(STATEMENT, year=YEAR, participant_ids=[str(self.anna.pk)])
        self.assertEqual(ok.status_code, 201)

    def test_year_is_required_and_bounded(self):
        self.assertEqual(self.post(STATEMENT).status_code, 400)
        self.assertEqual(self.post(STATEMENT, year=99999).status_code, 400)

    def test_only_a_manager_may_issue(self):
        sent_invoice(self.zev, self.anna)

        self.assertEqual(self.post(STATEMENT, user=self.account, year=YEAR).status_code, 404)
        self.assertEqual(APIClient().post(STATEMENT, {"zev": str(self.zev.pk), "year": YEAR}, format="json").status_code, 401)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_a_disabled_zev_refuses_a_manager(self):
        sent_invoice(self.zev, self.anna)
        self.zev.disabled_at = timezone.now()
        self.zev.save(update_fields=["disabled_at"])

        self.assertEqual(self.post(STATEMENT, year=YEAR).status_code, 400)

    def test_a_failing_render_delivers_nothing(self):
        sent_invoice(self.zev, self.anna)
        sent_invoice(self.zev, self.ben)
        from inbox import issuing

        issuing.generate_annual_statement_pdf.side_effect = [b"%PDF-ok", RuntimeError("render failed")]
        before = _stored(self.zev)

        with self.assertRaises(RuntimeError):
            self.post(STATEMENT, year=YEAR)

        self.assertFalse(DeliveredDocument.objects.exists())
        self.assertEqual(_stored(self.zev), before)

    def test_counts_recipients_without_account(self):
        sent_invoice(self.zev, self.anna)
        sent_invoice(self.zev, self.ben)

        body = self.post(STATEMENT, year=YEAR).json()

        self.assertEqual((body["delivered"], body["without_account"]), (2, 1))


class FinancialSummaryTests(IssueBase):
    def test_issues_only_to_producers(self):
        producer = sent_invoice(self.zev, self.anna)
        add_item(producer, InvoiceItem.ItemType.FEED_IN, "-5.00")
        consumer = sent_invoice(self.zev, self.ben)
        add_item(consumer, InvoiceItem.ItemType.LOCAL_ENERGY, "7.00")

        response = self.post(SUMMARY, year=YEAR)

        self.assertEqual(response.status_code, 201, response.content)
        document = DeliveredDocument.objects.get()
        self.assertEqual((document.kind, document.participant), (DocumentKind.FINANCIAL_SUMMARY, self.anna))

    def test_a_credit_for_local_energy_makes_a_producer(self):
        invoice = sent_invoice(self.zev, self.ben)
        add_item(invoice, InvoiceItem.ItemType.LOCAL_ENERGY, "-3.00")

        self.assertEqual(self.post(SUMMARY, year=YEAR).status_code, 201)

    def test_nobody_producing_is_a_validation_error(self):
        add_item(sent_invoice(self.zev, self.ben), InvoiceItem.ItemType.GRID_ENERGY, "9.00")

        self.assertEqual(self.post(SUMMARY, year=YEAR).status_code, 400)
        self.assertFalse(DeliveredDocument.objects.exists())

    def test_naming_a_consumer_is_refused(self):
        add_item(sent_invoice(self.zev, self.ben), InvoiceItem.ItemType.LOCAL_ENERGY, "7.00")

        response = self.post(SUMMARY, year=YEAR, participant_ids=[str(self.ben.pk)])

        self.assertEqual(response.status_code, 400)
        self.assertIn("participant_ids", response.json())

    def test_reissuing_a_financial_summary_supersedes_the_earlier_one(self):
        add_item(sent_invoice(self.zev, self.anna), InvoiceItem.ItemType.FEED_IN, "-5.00")
        first = self.post(SUMMARY, year=YEAR).json()["documents"][0]["id"]

        self.post(SUMMARY, year=YEAR)

        self.assertIsNotNone(DeliveredDocument.objects.get(pk=first).superseded_at)
        self.assertEqual(DeliveredDocument.objects.filter(superseded_at__isnull=True).count(), 1)

    def test_statement_and_summary_of_one_year_coexist(self):
        invoice = sent_invoice(self.zev, self.anna)
        add_item(invoice, InvoiceItem.ItemType.FEED_IN, "-5.00")

        self.post(STATEMENT, year=YEAR)
        self.post(SUMMARY, year=YEAR)

        self.assertEqual(DeliveredDocument.objects.filter(superseded_at__isnull=True).count(), 2)


class TariffOverviewTests(IssueBase):
    def setUp(self):
        super().setUp()
        patch = mock.patch("inbox.issuing.generate_tariff_overview_pdf", return_value=b"%PDF-1.4 tariffs")
        patch.start()
        self.addCleanup(patch.stop)

    def test_delivers_one_shared_file_to_every_current_participant(self):
        Participant.objects.create(
            zev=self.zev, first_name="Old", last_name="Gone", email="old@example.com",
            valid_from=date(2020, 1, 1), valid_to=timezone.localdate() - timedelta(days=1),
        )

        response = self.post(TARIFFS)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()["delivered"], response.json()["without_account"]), (2, 1))
        rows = DeliveredDocument.objects.all()
        self.assertEqual({row.participant_id for row in rows}, {self.anna.pk, self.ben.pk})
        self.assertEqual({row.kind for row in rows}, {DocumentKind.TARIFF_OVERVIEW})
        self.assertEqual(len({row.file.name for row in rows}), 1)
        self.assertIsNone(rows[0].period_start)

    def test_a_person_with_two_participant_rows_gets_one_overview(self):
        make_participant(self.zev, user=self.anna.user, first="Anna", last="Second")

        response = self.post(TARIFFS)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["delivered"], 2)
        self.assertEqual(DeliveredDocument.objects.filter(participant__user=self.anna.user).count(), 1)

    def test_reissuing_supersedes_the_earlier_overview_per_participant(self):
        self.post(TARIFFS)
        self.post(TARIFFS)

        self.assertEqual(DeliveredDocument.objects.count(), 4)
        self.assertEqual(DeliveredDocument.objects.filter(superseded_at__isnull=True).count(), 2)
        for old in DeliveredDocument.objects.filter(superseded_at__isnull=False):
            self.assertIsNotNone(old.superseded_by)
            # The superseded document keeps its own bytes.
            self.assertTrue(default_storage.exists(old.file.name))

    def test_a_zev_without_participants_is_refused_and_leaves_no_file(self):
        empty = make_zev(self.owner, "Empty")
        before = _stored(empty)

        response = self.client.post(TARIFFS, {"zev": str(empty.pk)}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(_stored(empty), before)

    def test_only_a_manager_may_issue(self):
        self.assertEqual(self.post(TARIFFS, user=self.account).status_code, 404)

    def test_the_real_generator_renders_a_pdf(self):
        mock.patch.stopall()
        response = self.post(TARIFFS)

        self.assertEqual(response.status_code, 201, response.content)
        document = DeliveredDocument.objects.first()
        with document.open_file() as handle:
            self.assertEqual(handle.read(5), b"%PDF-")


def _stored(zev):
    folder = f"inbox/documents/{zev.pk}"
    return set(default_storage.listdir(folder)[1]) if default_storage.exists(folder) else set()


class AnnouncementTests(IssueBase):
    """Every route that delivers also tells the participant, once (spec §6.5)."""

    def notifications(self):
        from notifications.models import Notification

        return Notification.objects.filter(type="document.delivered")

    def upload(self, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            "/api/v1/inbox/documents/",
            {"zev": self.zev.pk, "title": "House rules", "file": SimpleUploadedFile("r.pdf", b"%PDF-1.7\n"), **extra},
            format="multipart",
        )

    def test_an_uploaded_document_notifies_participants_with_a_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.upload().status_code, 201)
        row = self.notifications().get()
        document = DeliveredDocument.objects.get(participant=self.anna)
        self.assertEqual(row.recipient, self.account)
        self.assertEqual(row.payload, {"document_id": str(document.pk), "kind": "operator", "title": "House rules"})
        self.assertEqual(row.target_id, str(document.pk))

    def test_the_tariff_overview_notifies_each_row_it_wrote(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(TARIFFS, {"zev": self.zev.pk}, format="json").status_code, 201)
        self.assertEqual(self.notifications().count(), 1)

    def test_a_contract_delivered_twice_notifies_once(self):
        from inbox.test_helpers import make_contract_issue

        issue = make_contract_issue(self.anna, self.owner)
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post("/api/v1/inbox/documents/deliver-contract/", {"contract_issue": issue.pk}, format="json")
        self.assertEqual(self.notifications().count(), 1)

    def test_a_refused_delivery_notifies_nobody(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.upload(audience="selected", participant_ids=[99999])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.notifications().count(), 0)

    def test_a_re_issued_statement_notifies_again_because_it_is_a_new_document(self):
        sent_invoice(self.zev, self.anna)
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(STATEMENT, {"zev": self.zev.pk, "year": YEAR}, format="json")
        self.assertEqual(self.notifications().count(), 2)
