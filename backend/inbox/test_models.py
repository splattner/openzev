from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import UserRole
from inbox.models import DeliveredDocument, DocumentKind
from inbox.test_helpers import make_contract_issue
from invoices.test_helpers import make_invoice, make_participant, make_zev
from testing.helpers import make_user


class DeliveredDocumentModelTests(TestCase):
    def setUp(self):
        self.owner = make_user("inbox_model_owner", UserRole.USER)
        self.zev = make_zev(self.owner)
        self.participant = make_participant(self.zev)

    def _row(self, **kwargs):
        defaults = dict(participant=self.participant, kind=DocumentKind.OPERATOR, title="Rules", file="inbox/x.pdf")
        return DeliveredDocument.objects.create(**{**defaults, **kwargs})

    def test_contract_row_has_no_file_and_references_issue(self):
        issue = make_contract_issue(self.participant, self.owner)
        self._row(kind=DocumentKind.CONTRACT, file="", contract_issue=issue)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.CONTRACT, file="inbox/y.pdf", contract_issue=issue)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.CONTRACT, file="", contract_issue=None)

    def test_a_contract_without_an_issue_holds_its_own_file(self):
        """A contract that arrived through a transfer archive has no ContractIssue."""
        row = self._row(kind=DocumentKind.CONTRACT, file="inbox/z.pdf", contract_issue=None)
        self.assertEqual(row.contract_issue_id, None)
        issue = make_contract_issue(self.participant, self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.INVOICE, file="inbox/w.pdf", contract_issue=issue)

    def test_other_kinds_require_a_file(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(file="")

    def test_one_row_per_invoice(self):
        invoice = make_invoice(self.zev, self.participant)
        self._row(kind=DocumentKind.INVOICE, invoice=invoice)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.INVOICE, invoice=invoice)

    def test_one_current_report_per_participant_kind_period(self):
        period = dict(period_start=date(2026, 1, 1), period_end=date(2026, 12, 31))
        first = self._row(kind=DocumentKind.ANNUAL_STATEMENT, **period)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.ANNUAL_STATEMENT, **period)
        # A superseded row no longer counts, and another year or kind is independent.
        DeliveredDocument.objects.filter(pk=first.pk).update(superseded_at=first.delivered_at)
        self._row(kind=DocumentKind.ANNUAL_STATEMENT, **period)
        self._row(kind=DocumentKind.FINANCIAL_SUMMARY, **period)
        self._row(kind=DocumentKind.ANNUAL_STATEMENT, period_start=date(2025, 1, 1), period_end=date(2025, 12, 31))

    def test_one_current_tariff_overview_per_participant(self):
        self._row(kind=DocumentKind.TARIFF_OVERVIEW)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(kind=DocumentKind.TARIFF_OVERVIEW)

    def test_zev_is_derived_from_participant(self):
        other_zev = make_zev(make_user("inbox_model_other", UserRole.USER), "Other")
        row = self._row(zev=other_zev)
        self.assertEqual(row.zev_id, self.zev.pk)

    def test_participant_delete_keeps_the_row(self):
        row = self._row()
        self.participant.delete()
        row.refresh_from_db()
        self.assertIsNone(row.participant_id)
        self.assertEqual(row.zev_id, self.zev.pk)

    def test_open_file_reads_the_stored_copy_or_the_contract_bytes(self):
        issue = make_contract_issue(self.participant, self.owner)
        contract = self._row(kind=DocumentKind.CONTRACT, file="", contract_issue=issue)
        with contract.open_file() as handle:
            self.assertEqual(handle.read(), b"%PDF-contract")
