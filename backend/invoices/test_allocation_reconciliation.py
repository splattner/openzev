"""Cross-consumer reconciliation: engine, PDF stats, and dashboards must agree.

Every consumer of the per-timestamp local-pool allocation (ADR 0013) must
attribute the same kWh to the same participant for the same fixture, including
a metering point handed over mid-period. The engine is the source of truth —
``pdf_stats`` feeds the period overview, ``analytics`` feeds the dashboards —
so all three are compared here on shared scenarios.

Energy values cross the analytics/PDF JSON boundary as floats, so comparisons
are done at the settlement quantum (``0.0001`` kWh, the invoice precision):
``Decimal(str(value))`` converted back, then compared exactly. That makes the
reconciliation claim "equal to the billed amount at billing precision", not
"approximately equal".
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models.functions import TruncDay
from django.test import TestCase

from accounts.models import UserRole
from invoices.annual_statement import _compute_monthly_data
from invoices.engine import generate_invoice
from invoices.pdf_stats import _compute_period_participant_stats
from metering.analytics import owner_dashboard_summary
from metering.models import MeterReading, ReadingDirection
from testing.helpers import make_named_participant
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType, Zev

User = get_user_model()

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)

ENERGY_QUANTUM = Decimal("0.0001")


class _ReconciliationBase(TestCase):
    """Shared fixture builders and consumers for reconciliation scenarios."""

    def _mp(self, meter_type, meter_id):
        return MeteringPoint.objects.create(
            zev=self.zev, meter_type=meter_type, meter_id=meter_id,
        )

    def _assign(self, metering_point, participant, valid_from, valid_to=None, mode=AllocationMode.PERSONAL):
        return MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=participant,
            valid_from=valid_from, valid_to=valid_to, allocation_mode=mode,
        )

    def _reading(self, metering_point, day, kwh, direction):
        return MeterReading.objects.create(
            metering_point=metering_point,
            timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal(kwh),
            direction=direction,
        )

    def _consumption(self, metering_point, day, kwh):
        self._reading(metering_point, day, kwh, ReadingDirection.IN)

    def _production(self, metering_point, day, kwh):
        self._reading(metering_point, day, kwh, ReadingDirection.OUT)

    def _invoices(self):
        alice_invoice = generate_invoice(self.alice, PERIOD_START, PERIOD_END)
        bob_invoice = generate_invoice(self.bob, PERIOD_START, PERIOD_END)
        return alice_invoice, bob_invoice

    @staticmethod
    def _invoice_consumed(invoice) -> Decimal:
        return invoice.total_local_kwh + invoice.total_grid_kwh

    @staticmethod
    def _invoice_produced(invoice) -> Decimal:
        """Reconstruct metered production from invoice fields.

        Returns ``total_local_kwh + total_feed_in_kwh``. This equals metered
        production only for participants whose consumption-side local share
        equals their production-side local-sold (true for sole participants
        and producer-only participants). For a consumer-producer with
        asymmetric consumption/production, the consumption-side local share
        stored in ``total_local_kwh`` differs from the production-side
        ``local_sold``, so this helper would undercount. The fixtures in this
        module avoid that case.
        """
        return invoice.total_local_kwh + invoice.total_feed_in_kwh

    def _pdf_stats(self, invoice):
        _, stats = _compute_period_participant_stats(invoice)
        return {s["participant_name"]: s for s in stats}

    def _analytics(self):
        from datetime import datetime as dt_cls, timezone

        from metering.models import MeterReading as MR
        qs = MR.objects.filter(
            metering_point__zev_id=self.zev.id,
            timestamp__gte=dt_cls(2026, 1, 1, tzinfo=timezone.utc),
            timestamp__lt=dt_cls(2026, 2, 1, tzinfo=timezone.utc),
        )
        return owner_dashboard_summary(qs, TruncDay, None)

    def _analytics_selected(self, participant):
        from datetime import datetime as dt_cls, timezone

        from metering.models import MeterReading as MR
        qs = MR.objects.filter(
            metering_point__zev_id=self.zev.id,
            timestamp__gte=dt_cls(2026, 1, 1, tzinfo=timezone.utc),
            timestamp__lt=dt_cls(2026, 2, 1, tzinfo=timezone.utc),
        )
        return owner_dashboard_summary(qs, TruncDay, str(participant.id))

    def assertSameEnergy(self, expected, actual, msg=None):
        """Assert two energy values are equal at the settlement quantum.

        ``expected`` is a ``Decimal`` (invoice field); ``actual`` is a JSON
        float from the analytics/PDF boundary, converted back to ``Decimal``
        before the exact comparison."""
        self.assertEqual(
            Decimal(str(expected)).quantize(ENERGY_QUANTUM),
            Decimal(str(actual)).quantize(ENERGY_QUANTUM),
            msg=msg,
        )


class EnginePdfStatsAnalyticsReconciliationTests(_ReconciliationBase):
    """One scenario, three consumers: mid-period transfer + gap reading.

    Jan 5  – Alice consumes 4 kWh, the ZEV produces 6 kWh (Alice owns the
             production metering point): Alice self-consumes 4 kWh.
    Jan 15 – gap reading of 3 kWh (no assignment active): billed to nobody,
             and must not appear in any consumer's stats.
    Jan 20 – Bob (new holder from Jan 16) consumes 8 kWh, no production:
             Bob imports all 8 kWh from the grid.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username="recon_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Recon ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="RC",
        )
        self.zev.refresh_from_db()
        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START, date(2026, 1, 14))
        self.bob = make_named_participant(self.zev, "Bob Beispiel", date(2026, 1, 16))

        self.consumption_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-RC-CONS-1")
        self._assign(self.consumption_mp, self.alice, PERIOD_START, date(2026, 1, 14))
        self._assign(self.consumption_mp, self.bob, date(2026, 1, 16))
        self.production_mp = self._mp(MeteringPointType.PRODUCTION, "CH-RC-PROD-1")
        self._assign(self.production_mp, self.alice, PERIOD_START)

        self._consumption(self.consumption_mp, date(2026, 1, 5), "4")   # Alice
        self._consumption(self.consumption_mp, date(2026, 1, 15), "3")  # gap
        self._consumption(self.consumption_mp, date(2026, 1, 20), "8")  # Bob
        self._production(self.production_mp, date(2026, 1, 5), "6")     # Alice

    def test_engine_bills_each_holder_exactly_their_readings(self):
        alice_invoice, bob_invoice = self._invoices()
        # Gap reading (3 kWh) is billed to nobody.
        self.assertSameEnergy(self._invoice_consumed(alice_invoice), "4")
        self.assertSameEnergy(alice_invoice.total_local_kwh, "4")
        self.assertSameEnergy(alice_invoice.total_grid_kwh, "0")
        self.assertSameEnergy(self._invoice_consumed(bob_invoice), "8")
        self.assertSameEnergy(bob_invoice.total_local_kwh, "0")
        self.assertSameEnergy(bob_invoice.total_grid_kwh, "8")

    def test_pdf_stats_reconcile_with_engine_invoices(self):
        alice_invoice, bob_invoice = self._invoices()
        alice_stats = self._pdf_stats(alice_invoice)
        bob_stats = self._pdf_stats(bob_invoice)

        row = alice_stats["Alice Muster"]
        self.assertSameEnergy(self._invoice_consumed(alice_invoice), row["total_consumed_kwh"])
        self.assertSameEnergy(self._invoice_produced(alice_invoice), row["total_produced_kwh"])
        self.assertSameEnergy(alice_invoice.total_local_kwh, row["from_zev_kwh"])
        self.assertSameEnergy(alice_invoice.total_grid_kwh, row["from_grid_kwh"])

        row = bob_stats["Bob Beispiel"]
        self.assertSameEnergy(self._invoice_consumed(bob_invoice), row["total_consumed_kwh"])
        self.assertSameEnergy(bob_invoice.total_local_kwh, row["from_zev_kwh"])
        self.assertSameEnergy(bob_invoice.total_grid_kwh, row["from_grid_kwh"])

    def test_analytics_reconcile_with_engine_invoices(self):
        alice_invoice, bob_invoice = self._invoices()
        result = self._analytics()
        by_id = {s["participant_id"]: s for s in result["participant_stats"]}

        row = by_id[str(self.alice.id)]
        self.assertSameEnergy(self._invoice_consumed(alice_invoice), row["total_consumed_kwh"])
        self.assertSameEnergy(self._invoice_produced(alice_invoice), row["total_produced_kwh"])
        self.assertSameEnergy(alice_invoice.total_local_kwh, row["from_zev_kwh"])
        self.assertSameEnergy(alice_invoice.total_grid_kwh, row["from_grid_kwh"])

        row = by_id[str(self.bob.id)]
        self.assertSameEnergy(self._invoice_consumed(bob_invoice), row["total_consumed_kwh"])
        self.assertSameEnergy(bob_invoice.total_local_kwh, row["from_zev_kwh"])
        self.assertSameEnergy(bob_invoice.total_grid_kwh, row["from_grid_kwh"])

        # ZEV-wide dashboard totals are physical pool totals: they still
        # include the gap reading (3 kWh), which only the per-participant
        # bills exclude (ADR 0013 decision).
        self.assertSameEnergy(result["totals"]["consumed_kwh"], "15")
        self.assertSameEnergy(result["totals"]["produced_kwh"], "6")
        # Per-timestamp import: Jan 5 → 0, gap Jan 15 → 3, Jan 20 → 8.
        self.assertSameEnergy(result["totals"]["imported_kwh"], "11")

        # The selected-participant view must also reconcile exported (feed-in)
        # with the invoice: Alice produces 6, community self-consumes 4 → bill 2.
        selected = self._analytics_selected(self.alice)
        self.assertSameEnergy(alice_invoice.total_feed_in_kwh, selected["totals"]["exported_kwh"])
        self.assertEqual(len(selected["timeline"]), 1)
        self.assertSameEnergy(
            alice_invoice.total_feed_in_kwh,
            selected["timeline"][0]["exported_kwh"],
        )

    def test_analytics_and_pdf_stats_agree_on_participant_splits(self):
        alice_invoice, _ = self._invoices()
        pdf = self._pdf_stats(alice_invoice)
        analytics = {s["participant_name"]: s for s in self._analytics()["participant_stats"]}
        for name in ("Alice Muster", "Bob Beispiel"):
            for field in ("total_consumed_kwh", "total_produced_kwh", "from_zev_kwh", "from_grid_kwh"):
                self.assertSameEnergy(
                    pdf[name][field], analytics[name][field],
                    msg=f"{name}.{field}",
                )


class MultiMeterBidirectionalReconciliationTests(_ReconciliationBase):
    """Richer fixture: two consumption meters for one participant at one
    timestamp, two producers (one a bidirectional meter), a producer-meter
    transfer, two transfers of one consumption meter (Alice → Bob → Alice),
    and an unassigned consumption meter that feeds the community pool and the
    physical dashboard totals but is billed to nobody (ADR 0013 pool decision).

    Jan  5 – Alice: CONS-1 IN 4 + CONS-2 IN 4; PROD-1 OUT 6.
              Unassigned: CONS-3 IN 2.  Pool 6 (consumed 10 incl. CONS-3)
              → Alice local 4.8, grid 3.2.
    Jan 15 – CONS-3 IN 1 (unassigned, nobody billed).
    Jan 20 – Bob: CONS-1 IN 4 + BI-1 IN 2; PROD-1 OUT 2 + BI-1 OUT 8.
              Pool 6 → Bob local 6, grid 0; feed-in 4 (local-sold 6, export 4).
    Jan 25 – Alice (second transfer of CONS-1 back): CONS-1 IN 3. No
              production → grid 3.

    Alice billed: consumed 11 (4.8 local / 6.2 grid), produced 6, feed-in 0.
    Bob billed:   consumed 6 (6 local / 0 grid), produced 10, feed-in 4.
    Physical:     consumed 20 (17 billed + 3 unassigned), produced 16,
                  imported 8, exported 4.
    """

    def setUp(self):
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

    def test_all_consumers_reconcile_on_the_multi_meter_scenario(self):
        alice_invoice, bob_invoice = self._invoices()

        # Engine: per-holder billed amounts (unassigned readings excluded,
        # but their energy still shapes the pool). Feed-in is the exported
        # part only: local-sold production is credited under the local energy
        # type and has no stored kWh total.
        self.assertSameEnergy(alice_invoice.total_local_kwh, "4.8")
        self.assertSameEnergy(alice_invoice.total_grid_kwh, "6.2")
        self.assertSameEnergy(self._invoice_consumed(alice_invoice), "11")
        self.assertSameEnergy(alice_invoice.total_feed_in_kwh, "0")
        self.assertSameEnergy(bob_invoice.total_local_kwh, "6")
        self.assertSameEnergy(bob_invoice.total_grid_kwh, "0")
        self.assertSameEnergy(self._invoice_consumed(bob_invoice), "6")
        self.assertSameEnergy(bob_invoice.total_feed_in_kwh, "4")

        # PDF stats match the engine exactly.
        alice_pdf = self._pdf_stats(alice_invoice)["Alice Muster"]
        bob_pdf = self._pdf_stats(bob_invoice)["Bob Beispiel"]
        self.assertSameEnergy(alice_pdf["total_consumed_kwh"], "11")
        self.assertSameEnergy(alice_pdf["from_zev_kwh"], "4.8")
        self.assertSameEnergy(alice_pdf["from_grid_kwh"], "6.2")
        self.assertSameEnergy(alice_pdf["total_produced_kwh"], "6")
        self.assertSameEnergy(bob_pdf["total_consumed_kwh"], "6")
        self.assertSameEnergy(bob_pdf["from_zev_kwh"], "6")
        self.assertSameEnergy(bob_pdf["from_grid_kwh"], "0")
        self.assertSameEnergy(bob_pdf["total_produced_kwh"], "10")

        # Analytics match too.
        result = self._analytics()
        by_id = {s["participant_id"]: s for s in result["participant_stats"]}
        alice_row = by_id[str(self.alice.id)]
        bob_row = by_id[str(self.bob.id)]
        self.assertSameEnergy(alice_row["total_consumed_kwh"], "11")
        self.assertSameEnergy(alice_row["from_zev_kwh"], "4.8")
        self.assertSameEnergy(alice_row["from_grid_kwh"], "6.2")
        self.assertSameEnergy(alice_row["total_produced_kwh"], "6")
        self.assertSameEnergy(bob_row["total_consumed_kwh"], "6")
        self.assertSameEnergy(bob_row["from_zev_kwh"], "6")
        self.assertSameEnergy(bob_row["from_grid_kwh"], "0")
        self.assertSameEnergy(bob_row["total_produced_kwh"], "10")

        # The unassigned meter is billed to nobody but feeds the pool and the
        # physical totals: its 3 kWh (2 on Jan 5, 1 on Jan 15) lift the
        # physical consumed above the sum of all billed consumption (17 kWh).
        self.assertSameEnergy(result["totals"]["consumed_kwh"], "20")
        self.assertSameEnergy(result["totals"]["produced_kwh"], "16")
        self.assertSameEnergy(result["totals"]["imported_kwh"], "8")
        self.assertSameEnergy(result["totals"]["exported_kwh"], "4")

        # Selected view: Bob's exported energy reconciles with his invoice.
        selected = self._analytics_selected(self.bob)
        self.assertSameEnergy(selected["totals"]["exported_kwh"], "4")
        self.assertEqual(len(selected["timeline"]), 1)

    def _expected_producer_split(self, participant):
        """Reconstruct a producer's per-timestamp ``split_production`` shares —

        local-sold and exported — from raw meter data, independent of the
        engine's priced line items."""
        from collections import defaultdict

        from allocation.split import split_production
        from allocation.windows import AssignmentWindows

        produced_at = defaultdict(Decimal)
        consumed_at = defaultdict(Decimal)
        for reading in MeterReading.objects.filter(metering_point__zev=self.zev):
            if reading.direction == ReadingDirection.OUT:
                produced_at[reading.timestamp] += reading.energy_kwh
            else:
                consumed_at[reading.timestamp] += reading.energy_kwh

        windows = AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)
        # Iterate the participant's distinct production meters rather than their
        # assignment rows: a meter reassigned to the same participant in two
        # ranges would otherwise re-fetch and re-count its readings.
        meters = {}
        for assignment in participant.metering_point_assignments.all():
            meter = assignment.metering_point
            if meter.meter_type in (
                MeteringPointType.PRODUCTION,
                MeteringPointType.BIDIRECTIONAL,
            ):
                meters.setdefault(meter.pk, meter)
        local_sold = Decimal("0")
        exported = Decimal("0")
        for meter in meters.values():
            for reading in MeterReading.objects.filter(
                metering_point=meter, direction=ReadingDirection.OUT
            ):
                if not windows.is_held_by(participant.id, meter.id, reading.timestamp):
                    continue
                local, exported_share = split_production(
                    reading.energy_kwh,
                    produced_at[reading.timestamp],
                    consumed_at[reading.timestamp],
                )
                local_sold += local
                exported += exported_share
        return local_sold, exported

    def test_producer_local_credits_reconcile_with_the_per_timestamp_splits(self):
        """A producer's local credit is the billed image of the allocation:
        summing the negative local-energy lines back out must reproduce the
        per-timestamp ``split_production`` local shares at the settlement
        quantum, and the francs must match at the local tariff (ADR 0013
        producer-conservation verification)."""
        from invoices.models import InvoiceItem
        from tariffs.models import EnergyType
        from testing import factories

        local_price = "0.20000"
        factories.flat_tariff(self.zev, energy_type=EnergyType.LOCAL, price=local_price)
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.08000")

        alice_invoice, bob_invoice = self._invoices()

        for participant, invoice in ((self.alice, alice_invoice), (self.bob, bob_invoice)):
            expected_local, expected_exported = self._expected_producer_split(participant)

            # Local-sold half: the negative local-energy lines reconstruct the
            # per-timestamp local shares, in kWh and in CHF at the local tariff.
            credit_items = list(
                invoice.items.filter(
                    item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
                    total_chf__lt=0,
                )
            )
            reconstructed_kwh = sum(
                (item.quantity_kwh for item in credit_items), Decimal("0")
            )
            self.assertSameEnergy(
                expected_local, reconstructed_kwh,
                msg=f"{participant.full_name}.local_sold_kwh",
            )
            reconstructed_chf = -sum(
                (item.total_chf for item in credit_items), Decimal("0")
            )
            self.assertEqual(
                reconstructed_chf,
                (expected_local * Decimal(local_price)).quantize(Decimal("0.01")),
                msg=f"{participant.full_name}.local_credit_chf",
            )

            # Exported half of the same split: the feed-in lines reconstruct the
            # per-timestamp exported shares. A producer with nothing to export
            # (Alice) gets no feed-in line at all.
            feed_in_items = list(
                invoice.items.filter(item_type=InvoiceItem.ItemType.FEED_IN)
            )
            self.assertSameEnergy(
                expected_exported,
                sum((item.quantity_kwh for item in feed_in_items), Decimal("0")),
                msg=f"{participant.full_name}.feed_in_kwh",
            )
            if expected_exported == 0:
                self.assertEqual(
                    feed_in_items, [], msg=f"{participant.full_name}.feed_in_lines",
                )


class UnassignedProductionReconciliationTests(_ReconciliationBase):
    """An unassigned production meter feeds the community pool but bills nobody.

    Jan 5 – Alice: CONS-1 IN 10, PROD-1 OUT 4 (assigned).
            Unassigned: PROD-2 OUT 6 (never assigned).

    Without PROD-2 the pool would be min(4, 10) = 4 and Alice would draw
    6 kWh from the grid.  With PROD-2 the physical pool is min(10, 10) = 10,
    so Alice's entire consumption is local.  PROD-2's 6 kWh are billed to
    nobody but lift the pool for every assigned consumer (ADR 0013 pool
    decision — physical totals cover every meter regardless of assignment).

    Alice billed: consumed 10 (10 local / 0 grid), produced 4, feed-in 0.
    Physical:     consumed 10, produced 10 (4 assigned + 6 unassigned),
                  imported 0, exported 0.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username="recon_unprod", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Unprod ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="UP",
        )
        self.zev.refresh_from_db()
        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)
        self.bob = make_named_participant(self.zev, "Bob Beispiel", PERIOD_START)

        self.cons1 = self._mp(MeteringPointType.CONSUMPTION, "CH-UP-CONS-1")
        self.prod1 = self._mp(MeteringPointType.PRODUCTION, "CH-UP-PROD-1")
        self.prod2 = self._mp(MeteringPointType.PRODUCTION, "CH-UP-PROD-2")

        self._assign(self.cons1, self.alice, PERIOD_START)
        self._assign(self.prod1, self.alice, PERIOD_START)
        # prod2 is never assigned — its production feeds the pool but bills nobody.

        self._consumption(self.cons1, date(2026, 1, 5), "10")   # Alice
        self._production(self.prod1, date(2026, 1, 5), "4")     # Alice
        self._production(self.prod2, date(2026, 1, 5), "6")     # unassigned

    def test_unassigned_production_lifts_the_pool_for_assigned_consumers(self):
        alice_invoice, _bob_invoice = self._invoices()

        # The unassigned 6 kWh lift the pool from 4 to 10, so Alice's entire
        # consumption is local.  Without the physical-pool rule she would have
        # local 4, grid 6.
        self.assertSameEnergy(alice_invoice.total_local_kwh, "10")
        self.assertSameEnergy(alice_invoice.total_grid_kwh, "0")
        self.assertSameEnergy(alice_invoice.total_feed_in_kwh, "0")

        # PDF stats agree with the engine.
        pdf = self._pdf_stats(alice_invoice)["Alice Muster"]
        self.assertSameEnergy(pdf["total_consumed_kwh"], "10")
        self.assertSameEnergy(pdf["from_zev_kwh"], "10")
        self.assertSameEnergy(pdf["from_grid_kwh"], "0")
        self.assertSameEnergy(pdf["total_produced_kwh"], "4")

        # Analytics agree too.
        result = self._analytics()
        by_id = {s["participant_id"]: s for s in result["participant_stats"]}
        alice_row = by_id[str(self.alice.id)]
        self.assertSameEnergy(alice_row["total_consumed_kwh"], "10")
        self.assertSameEnergy(alice_row["from_zev_kwh"], "10")
        self.assertSameEnergy(alice_row["from_grid_kwh"], "0")
        self.assertSameEnergy(alice_row["total_produced_kwh"], "4")

        # Physical totals include the unassigned production.
        self.assertSameEnergy(result["totals"]["consumed_kwh"], "10")
        self.assertSameEnergy(result["totals"]["produced_kwh"], "10")
        self.assertSameEnergy(result["totals"]["imported_kwh"], "0")
        self.assertSameEnergy(result["totals"]["exported_kwh"], "0")


class AnnualStatementPhysicalPoolTests(_ReconciliationBase):
    """The annual statement's local pool must be *physical* — it includes
    inactive metering points, exactly like the engine and the dashboards
    (ADR 0013). An inactive meter is still a physical meter whose readings fed
    the community pool during the year; dropping it shrinks the pool and makes
    the annual statement disagree with the invoices for the same period.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username="annual_pool_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Annual Pool ZEV", owner=self.owner, zev_type="vzev",
            start_date=PERIOD_START, billing_interval="monthly", invoice_prefix="AP",
        )
        self.zev.refresh_from_db()

        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)

        self.consumption_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-AP-CONS")
        self._assign(self.consumption_mp, self.alice, PERIOD_START)
        self.active_prod_mp = self._mp(MeteringPointType.PRODUCTION, "CH-AP-PROD-ACTIVE")
        self._assign(self.active_prod_mp, self.alice, PERIOD_START)
        # Inactive producer: decommissioned now, but its January readings are
        # real physical energy that fed the pool during the year.
        self.inactive_prod_mp = self._mp(MeteringPointType.PRODUCTION, "CH-AP-PROD-INACTIVE")
        self.inactive_prod_mp.is_active = False
        self.inactive_prod_mp.save()
        self._assign(self.inactive_prod_mp, self.alice, PERIOD_START)

        self._consumption(self.consumption_mp, date(2026, 1, 5), "10")
        self._production(self.active_prod_mp, date(2026, 1, 5), "4")
        self._production(self.inactive_prod_mp, date(2026, 1, 5), "6")

    def test_annual_statement_pool_matches_the_engine_for_inactive_meters(self):
        invoice = generate_invoice(self.alice, PERIOD_START, PERIOD_END)

        tr = {"months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
        _months, totals = _compute_monthly_data(self.alice, self.zev, 2026, tr)

        # Physical pool on Jan 5: production 4 (active) + 6 (inactive) = 10,
        # consumption 10 -> Alice's whole 10 kWh draw is local.
        self.assertSameEnergy(invoice.total_local_kwh, "10")
        self.assertSameEnergy(invoice.total_grid_kwh, "0")
        # The annual statement must agree with the engine. Before the fix it
        # reported from_zev 4 (it dropped the inactive producer from the pool).
        self.assertSameEnergy(invoice.total_local_kwh, totals["from_zev_kwh"])
        self.assertSameEnergy(invoice.total_grid_kwh, totals["from_grid_kwh"])
        # The production side agrees with the engine invoice too: both producers
        # (active 4 + inactive 6) are Alice's assigned meters. (Participant
        # production never filtered on is_active — the fix touched only the pool
        # queries — so this pins cross-consumer agreement, not the regression.)
        self.assertSameEnergy(self._invoice_produced(invoice), totals["total_produced_kwh"])


class AnnualStatementDirectionTypePairingTests(_ReconciliationBase):
    """The annual-statement pool is paired by (meter type, direction), exactly
    like the engine: a consumption meter's OUT reading leaves the production
    pool and a production meter's IN reading leaves the consumption pool
    (ADR 0013). The pre-read-model union pivot grouped by direction only, so
    either leak inflated the statement's local share and made the statement
    disagree with the invoices for the same period.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username="pairing_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Pairing ZEV", owner=self.owner, zev_type="vzev",
            start_date=PERIOD_START, billing_interval="monthly", invoice_prefix="PZ",
        )
        self.zev.refresh_from_db()

        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)

        self.consumption_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-PZ-CONS")
        self._assign(self.consumption_mp, self.alice, PERIOD_START)
        self.production_mp = self._mp(MeteringPointType.PRODUCTION, "CH-PZ-PROD")
        self._assign(self.production_mp, self.alice, PERIOD_START)

        # Jan 5: Alice draws 10 kWh while the ZEV produces 4 kWh.
        self._consumption(self.consumption_mp, date(2026, 1, 5), "10")
        self._production(self.production_mp, date(2026, 1, 5), "4")

    def _assert_statement_agrees_with_engine(self):
        invoice = generate_invoice(self.alice, PERIOD_START, PERIOD_END)
        tr = {"months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
        _months, totals = _compute_monthly_data(self.alice, self.zev, 2026, tr)

        # Engine, type/direction-paired on every branch: local 4, grid 6.
        self.assertSameEnergy(invoice.total_local_kwh, "4")
        self.assertSameEnergy(invoice.total_grid_kwh, "6")
        # The statement must report the same split. Before the read-model the
        # direction-only pivot inflated the local share (10.00/0.00 or
        # 2.50/7.50 depending on the leak), disagreeing with the invoices.
        self.assertSameEnergy(invoice.total_local_kwh, totals["from_zev_kwh"])
        self.assertSameEnergy(invoice.total_grid_kwh, totals["from_grid_kwh"])
        self.assertEqual(_months[0]["from_zev_kwh"], "4.00")
        self.assertEqual(_months[0]["from_grid_kwh"], "6.00")

    def test_out_reading_on_a_consumption_meter_leaves_the_production_pool(self):
        """A consumption-typed meter that later gets PV and is never re-typed
        to bidirectional carries OUT readings; they must not feed the
        production pool (nothing validates direction against meter type)."""
        self._reading(self.consumption_mp, date(2026, 1, 5), "6", ReadingDirection.OUT)
        self._assert_statement_agrees_with_engine()

    def test_in_reading_on_a_production_meter_leaves_the_consumption_pool(self):
        """A production-typed meter carrying an IN reading must not feed the
        consumption pool."""
        self._reading(self.production_mp, date(2026, 1, 5), "6", ReadingDirection.IN)
        self._assert_statement_agrees_with_engine()


class CommunityMeterReconciliationTests(_ReconciliationBase):
    """Every consumer must agree once a metering point is community-allocated
    (#387): the engine, ``pdf_stats``, and ``analytics`` must attribute the
    same weighted share to each participant, and no single holder — including
    the meter's holder of record — may be attributed the full amount.
    """

    def setUp(self):
        self.owner = User.objects.create_user(
            username="recon_community", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Community Recon ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="CR",
        )
        self.zev.refresh_from_db()
        # Equal weights (the default): a straightforward 50/50 split makes the
        # cross-consumer comparison easy to state exactly.
        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)
        self.bob = make_named_participant(self.zev, "Bob Beispiel", PERIOD_START)

        self.community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-CR-COMM-1")
        # Alice is the holder of record, but that must not make her liable
        # for more than her weight share (§1.1: no holder special case).
        self._assign(self.community_mp, self.alice, PERIOD_START, mode=AllocationMode.COMMUNITY)

        self._consumption(self.community_mp, date(2026, 1, 5), "10")

    def test_all_consumers_reconcile_with_a_community_meter(self):
        alice_invoice, bob_invoice = self._invoices()

        # Engine: split 50/50, no production anywhere so it is all grid.
        self.assertSameEnergy(alice_invoice.total_grid_kwh, "5")
        self.assertSameEnergy(bob_invoice.total_grid_kwh, "5")

        alice_pdf = self._pdf_stats(alice_invoice)["Alice Muster"]
        bob_pdf = self._pdf_stats(bob_invoice)["Bob Beispiel"]
        self.assertSameEnergy(alice_invoice.total_grid_kwh, alice_pdf["from_grid_kwh"])
        self.assertSameEnergy(bob_invoice.total_grid_kwh, bob_pdf["from_grid_kwh"])
        self.assertSameEnergy(self._invoice_consumed(alice_invoice), alice_pdf["total_consumed_kwh"])
        self.assertSameEnergy(self._invoice_consumed(bob_invoice), bob_pdf["total_consumed_kwh"])

        result = self._analytics()
        by_id = {s["participant_id"]: s for s in result["participant_stats"]}
        self.assertSameEnergy(alice_invoice.total_grid_kwh, by_id[str(self.alice.id)]["from_grid_kwh"])
        self.assertSameEnergy(bob_invoice.total_grid_kwh, by_id[str(self.bob.id)]["from_grid_kwh"])

        # The physical pool total is unsplit: the dashboard's ZEV-wide figure
        # is still the full 10 kWh (ADR 0013), only the per-participant
        # attribution is weighted.
        self.assertSameEnergy(result["totals"]["consumed_kwh"], "10")

    def test_community_meter_energy_is_attributed_to_no_single_holder(self):
        alice_invoice, bob_invoice = self._invoices()

        # The holder of record (Alice) is billed exactly her weight share,
        # not the full reading — in every consumer, not just the engine.
        self.assertSameEnergy(alice_invoice.total_grid_kwh, "5")

        alice_pdf = self._pdf_stats(alice_invoice)["Alice Muster"]
        self.assertSameEnergy(alice_pdf["from_grid_kwh"], "5")

        result = self._analytics()
        by_id = {s["participant_id"]: s for s in result["participant_stats"]}
        self.assertSameEnergy(by_id[str(self.alice.id)]["from_grid_kwh"], "5")

        # Bob, who never holds the meter, is billed the same share.
        self.assertSameEnergy(bob_invoice.total_grid_kwh, "5")
        self.assertSameEnergy(by_id[str(self.bob.id)]["from_grid_kwh"], "5")
