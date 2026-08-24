"""Per-consumer query-count guards for the shared allocation service (ADR 0013).

The allocation pattern is "single fetch, then resolve in Python": each
consumer runs one ``AssignmentWindows`` query and resolves holders in Python.
The actual invariant — one fetch, not one per reading or per participant — is
pinned exactly in ``test_assignment_windows_resolved_in_a_single_fetch``.

The whole-consumer counts that follow assert *upper bounds*: they catch a
future change silently adding queries (N+1) to the billing path while leaving
room to *remove* a query (an improvement) without churning this file.

Counts are measured on the shared multi-meter reconciliation fixture and
verified to be identical on SQLite and PostgreSQL.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import UserRole
from allocation.windows import AssignmentWindows
from invoices.annual_statement import ANNUAL_TRANSLATIONS, _compute_monthly_data
from invoices.engine import generate_invoice
from invoices.pdf_charts import _build_hourly_profile_chart_svg
from invoices.pdf_stats import _compute_period_participant_stats
from invoices.pdf_translations import INVOICE_TRANSLATIONS
from invoices.test_allocation_reconciliation import (
    PERIOD_END,
    PERIOD_START,
    _ReconciliationBase,
)
from testing.helpers import make_named_participant
from zev.models import MeteringPointType, Zev

User = get_user_model()


class AllocationQueryCountTests(_ReconciliationBase):
    """Each allocation consumer must issue no more than a known number of queries."""

    def setUp(self):
        # Same multi-meter scenario as
        # ``MultiMeterBidirectionalReconciliationTests.setUp``: two consumption
        # meters plus an unassigned one, two producers (one bidirectional), and
        # multiple mid-period transfers.
        self.owner = User.objects.create_user(
            username="recon_multi", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Multi ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="MM",
        )
        self.zev.refresh_from_db()
        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)
        self.bob = make_named_participant(self.zev, "Bob Beispiel", date(2026, 1, 16))

        self.cons1 = self._mp(MeteringPointType.CONSUMPTION, "CH-MM-CONS-1")
        self.cons2 = self._mp(MeteringPointType.CONSUMPTION, "CH-MM-CONS-2")
        self.cons3 = self._mp(MeteringPointType.CONSUMPTION, "CH-MM-CONS-3")
        self.prod1 = self._mp(MeteringPointType.PRODUCTION, "CH-MM-PROD-1")
        self.bi1 = self._mp(MeteringPointType.BIDIRECTIONAL, "CH-MM-BI-1")

        self._assign(self.cons1, self.alice, PERIOD_START, date(2026, 1, 14))
        self._assign(self.cons1, self.bob, date(2026, 1, 16), date(2026, 1, 20))
        self._assign(self.cons1, self.alice, date(2026, 1, 21))
        self._assign(self.cons2, self.alice, PERIOD_START)
        self._assign(self.prod1, self.alice, PERIOD_START, date(2026, 1, 14))
        self._assign(self.prod1, self.bob, date(2026, 1, 16))
        self._assign(self.bi1, self.bob, date(2026, 1, 16))

        self._consumption(self.cons1, date(2026, 1, 5), "4")    # Alice
        self._consumption(self.cons2, date(2026, 1, 5), "4")    # Alice
        self._consumption(self.cons3, date(2026, 1, 5), "2")    # unassigned
        self._consumption(self.cons3, date(2026, 1, 15), "1")   # unassigned
        self._consumption(self.cons1, date(2026, 1, 20), "4")   # Bob
        self._consumption(self.bi1, date(2026, 1, 20), "2")     # Bob
        self._consumption(self.cons1, date(2026, 1, 25), "3")   # Alice again
        self._production(self.prod1, date(2026, 1, 5), "6")     # Alice
        self._production(self.prod1, date(2026, 1, 20), "2")    # Bob
        self._production(self.bi1, date(2026, 1, 20), "8")      # Bob

    def _call_at_most(self, n, func, *args, **kwargs):
        """Run ``func`` and assert it issues no more than ``n`` DB queries."""
        with CaptureQueriesContext(connection) as ctx:
            result = func(*args, **kwargs)
        self.assertLessEqual(
            len(ctx.captured_queries),
            n,
            f"expected at most {n} DB queries, got {len(ctx.captured_queries)}",
        )
        return result

    def test_assignment_windows_resolved_in_a_single_fetch(self):
        # The ADR 0013 invariant: one AssignmentWindows query per consumer,
        # then holders are resolved in Python. Any per-reading or
        # per-participant query here is an N+1 regression.
        with self.assertNumQueries(1):
            AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)
        with self.assertNumQueries(1):
            AssignmentWindows.for_participant(self.alice, PERIOD_START, PERIOD_END)

    def test_engine_generate_invoice_query_count(self):
        # Windows fetch + readings fetch + tariff lookup + invoice writes.
        # 13 -> 17: shared metering points (#387) add four queries — a
        # community consumption and a community production reading fetch,
        # plus one Participant fetch each for the date- and month-granular
        # allocation-weight sums (_allocation_weight_sum_by_date/_by_month) —
        # still a single query each regardless of how many community
        # readings or how many months the period spans.
        self._call_at_most(
            17, generate_invoice, self.alice, PERIOD_START, PERIOD_END
        )

    def test_pdf_stats_query_count(self):
        # 6 -> 7: eligible_participant_shares (shared metering points, #387)
        # adds one Participant fetch, still a single query regardless of how
        # many readings or how many months the period spans.
        invoice = generate_invoice(self.alice, PERIOD_START, PERIOD_END)
        self._call_at_most(7, _compute_period_participant_stats, invoice)

    def test_pdf_charts_hourly_profile_query_count(self):
        # 4 -> 7: shared metering points (#387) adds the personal/community
        # metering-point-id split (two queries, replacing one) plus
        # eligible_participant_shares (one query) — all still single
        # fetches, not per-reading.
        invoice = generate_invoice(self.alice, PERIOD_START, PERIOD_END)
        self._call_at_most(
            7, _build_hourly_profile_chart_svg, invoice, INVOICE_TRANSLATIONS["de"]
        )

    def test_annual_statement_monthly_data_query_count(self):
        self._call_at_most(
            6, _compute_monthly_data, self.alice, self.zev, 2026,
            ANNUAL_TRANSLATIONS["de"],
        )

    def test_owner_dashboard_query_count(self):
        # 6 -> 8: _community_shares_by_zev (shared metering points, #387) adds
        # two queries — a metering-point-to-ZEV mapping, then one
        # eligible_participant_shares fetch per distinct ZEV touched (this
        # fixture has one) — both still single fetches, not per-reading.
        self._call_at_most(8, self._analytics)
