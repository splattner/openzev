"""Tests for the allocation read-model (ADR 0013 follow-up).

``read_model`` composes ``split`` and ``windows`` into the fetch/resolve/split
iteration every consumer shares. These tests pin that the per-timestamp
community totals are *physical* (they include a never-assigned meter) and that
each (metering point, timestamp) group is resolved to the holder active at its
timestamp — including a mid-period transfer and an assignment gap — and split
against those totals.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserRole
from allocation.read_model import (
    CONSUMPTION,
    PRODUCTION,
    community_totals_by_timestamp,
    eligible_participant_shares,
    iter_allocated_readings,
)
from allocation.split import split_consumption, split_production
from allocation.windows import AssignmentWindows
from metering.models import MeterReading, ReadingDirection
from testing.helpers import make_named_participant
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType, Zev

User = get_user_model()

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)
START_DT = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
END_DT = datetime(2026, 2, 1, tzinfo=dt_timezone.utc)


def D(value) -> Decimal:
    return Decimal(str(value))


def _ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc)


class ReadModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="readmodel_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="ReadModel ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=PERIOD_START,
            billing_interval="monthly",
            invoice_prefix="RM",
        )
        self.zev.refresh_from_db()

        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START, date(2026, 1, 14))
        self.bob = make_named_participant(self.zev, "Bob Beispiel", date(2026, 1, 16))

        # Consumption meter transferred Alice -> Bob with a gap (Jan 15).
        self.consumption_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-RM-CONS-1")
        self._assign(self.consumption_mp, self.alice, PERIOD_START, date(2026, 1, 14))
        self._assign(self.consumption_mp, self.bob, date(2026, 1, 16))

        # Production meter held by Alice for the whole period.
        self.production_mp = self._mp(MeteringPointType.PRODUCTION, "CH-RM-PROD-1")
        self._assign(self.production_mp, self.alice, PERIOD_START)

        # Never-assigned consumption meter: feeds the physical pool, billed to nobody.
        self.orphan_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-RM-ORPHAN-1")

        self._consumption(self.consumption_mp, date(2026, 1, 5), "4")    # Alice
        self._consumption(self.consumption_mp, date(2026, 1, 15), "3")   # gap
        self._consumption(self.consumption_mp, date(2026, 1, 20), "8")   # Bob
        self._consumption(self.orphan_mp, date(2026, 1, 5), "5")         # nobody
        self._production(self.production_mp, date(2026, 1, 5), "6")      # Alice

        self.windows = AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)

    # ── fixture builders ──

    def _mp(self, meter_type, meter_id):
        return MeteringPoint.objects.create(zev=self.zev, meter_type=meter_type, meter_id=meter_id)

    def _assign(self, metering_point, participant, valid_from, valid_to=None):
        return MeteringPointAssignment.objects.create(
            metering_point=metering_point, participant=participant,
            valid_from=valid_from, valid_to=valid_to,
        )

    def _reading(self, metering_point, day, kwh, direction):
        return MeterReading.objects.create(
            metering_point=metering_point, timestamp=_ts(day),
            energy_kwh=Decimal(kwh), direction=direction,
        )

    def _consumption(self, metering_point, day, kwh):
        self._reading(metering_point, day, kwh, ReadingDirection.IN)

    def _production(self, metering_point, day, kwh):
        self._reading(metering_point, day, kwh, ReadingDirection.OUT)

    # ── community_totals_by_timestamp ─────────────────────────────────────

    def test_community_totals_are_physical(self):
        """Totals cover every meter, including the never-assigned one."""
        cons_by_ts, prod_by_ts = community_totals_by_timestamp(self.zev, START_DT, END_DT)
        # Jan 5 consumption = 4 (assigned meter) + 5 (orphan) = 9.
        self.assertEqual(cons_by_ts[_ts(date(2026, 1, 5))], D(9))
        self.assertEqual(cons_by_ts[_ts(date(2026, 1, 15))], D(3))
        self.assertEqual(cons_by_ts[_ts(date(2026, 1, 20))], D(8))
        self.assertEqual(prod_by_ts[_ts(date(2026, 1, 5))], D(6))

    def test_totals_pair_meter_type_with_direction(self):
        """A consumption meter's OUT reading leaves the production totals and
        a production meter's IN reading leaves the consumption totals: the
        pool is paired by (meter type, direction), not grouped by direction
        alone."""
        self._reading(self.consumption_mp, date(2026, 1, 20), "6", ReadingDirection.OUT)
        self._reading(self.production_mp, date(2026, 1, 20), "6", ReadingDirection.IN)

        cons_by_ts, prod_by_ts = community_totals_by_timestamp(self.zev, START_DT, END_DT)

        # Jan 20 consumption is Bob's 8 kWh only; the production meter's IN
        # reading must not feed the consumed side.
        self.assertEqual(cons_by_ts[_ts(date(2026, 1, 20))], D(8))
        # Jan 20 production is absent: the consumption meter's OUT reading must
        # not feed the produced side.
        self.assertNotIn(_ts(date(2026, 1, 20)), prod_by_ts)
        # Sanity: the valid readings still land where they belong.
        self.assertEqual(cons_by_ts[_ts(date(2026, 1, 5))], D(9))
        self.assertEqual(prod_by_ts[_ts(date(2026, 1, 5))], D(6))

    # ── iter_allocated_readings: consumption ──────────────────────────────

    def _by_mp_ts(self, kind):
        return {
            (r.metering_point_id, r.timestamp): r
            for r in iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=kind, windows=self.windows
            )
        }

    def test_consumption_resolves_holder_per_timestamp(self):
        readings = self._by_mp_ts(CONSUMPTION)
        cons_mp = self.consumption_mp.id

        alice = readings[(cons_mp, _ts(date(2026, 1, 5)))]
        self.assertEqual(alice.holder_id, self.alice.id)
        self.assertEqual(alice.energy_kwh, D(4))

        gap = readings[(cons_mp, _ts(date(2026, 1, 15)))]
        self.assertIsNone(gap.holder_id)  # assignment gap -> nobody

        bob = readings[(cons_mp, _ts(date(2026, 1, 20)))]
        self.assertEqual(bob.holder_id, self.bob.id)
        self.assertEqual(bob.energy_kwh, D(8))

    def test_consumption_orphan_meter_belongs_to_nobody(self):
        readings = self._by_mp_ts(CONSUMPTION)
        orphan = readings[(self.orphan_mp.id, _ts(date(2026, 1, 5)))]
        self.assertIsNone(orphan.holder_id)
        self.assertEqual(orphan.energy_kwh, D(5))

    def test_consumption_split_uses_physical_totals(self):
        """Alice's Jan 5 split is computed against the physical total (9), not
        just her own meter (4) — the orphan meter feeds the pool."""
        readings = self._by_mp_ts(CONSUMPTION)
        alice = readings[(self.consumption_mp.id, _ts(date(2026, 1, 5)))]
        self.assertEqual(alice.zev_consumption_kwh, D(9))
        self.assertEqual(alice.zev_production_kwh, D(6))
        expected = split_consumption(D(4), D(9), D(6))
        self.assertEqual(alice.split, expected)

    def test_consumption_split_without_production_is_all_grid(self):
        readings = self._by_mp_ts(CONSUMPTION)
        bob = readings[(self.consumption_mp.id, _ts(date(2026, 1, 20)))]
        # No production on Jan 20 -> nothing local to share.
        self.assertEqual(bob.split.local_kwh, D(0))
        self.assertEqual(bob.split.grid_kwh, D(8))

    # ── iter_allocated_readings: production ───────────────────────────────

    def test_production_resolves_holder_and_split(self):
        readings = self._by_mp_ts(PRODUCTION)
        prod = readings[(self.production_mp.id, _ts(date(2026, 1, 5)))]
        self.assertEqual(prod.holder_id, self.alice.id)
        self.assertEqual(prod.energy_kwh, D(6))
        # Community consumed 9, produced 6 -> whole 6 kWh pool is used locally.
        self.assertEqual(prod.split, split_production(D(6), D(6), D(9)))
        self.assertEqual(prod.split.local_sold_kwh, D(6))
        self.assertEqual(prod.split.exported_kwh, D(0))

    def test_production_with_split_false_skips_fail_fast_on_negative(self):
        """A negative production reading (a meter correction or bad import —
        ``energy_kwh`` has no ``MinValueValidator``) must not break the PDF
        stats production loop, which only wants holder-attributed totals. With
        ``with_split=False`` the reading is attributed to its holder and
        ``split`` is ``None``; the default (``with_split=True``) still fails
        fast per ``allocation.split``'s non-negative contract.
        """
        from allocation.errors import InvalidAllocationInputError

        neg_mp = self._mp(MeteringPointType.PRODUCTION, "CH-RM-PROD-NEG")
        self._assign(neg_mp, self.alice, PERIOD_START)
        self._production(neg_mp, date(2026, 1, 10), "-2")

        windows = AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)

        # Opting out of the split: no exception, split is None, the (negative)
        # energy is attributed to the holder unchanged — matching the pre-PR
        # pdf_stats production loop, which just summed produced_kwh.
        readings = list(iter_allocated_readings(
            self.zev, START_DT, END_DT, kind=PRODUCTION, windows=windows,
            with_split=False,
        ))
        neg = next(r for r in readings if r.metering_point_id == neg_mp.id)
        self.assertEqual(neg.holder_id, self.alice.id)
        self.assertEqual(neg.energy_kwh, D(-2))
        self.assertIsNone(neg.split)

        # The default runs split_production, which rejects the negative input.
        with self.assertRaises(InvalidAllocationInputError):
            list(iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=PRODUCTION, windows=windows,
            ))


    # ── contract ──────────────────────────────────────────────────────────

    def test_precomputed_totals_are_reused(self):
        """Passing totals bypasses the fetch and drives the split."""
        # Cover every consumption timestamp so the fail-fast contract
        # (participant draw <= community total) holds for the groups we don't
        # assert on; the Jan 5 value (100) is deliberately not the physical
        # total (9) so reuse is observable.
        bogus_cons = {
            _ts(date(2026, 1, 5)): D(100),
            _ts(date(2026, 1, 15)): D(100),
            _ts(date(2026, 1, 20)): D(100),
        }
        bogus_prod = {
            _ts(date(2026, 1, 5)): D(0),
            _ts(date(2026, 1, 15)): D(0),
            _ts(date(2026, 1, 20)): D(0),
        }
        readings = {
            (r.metering_point_id, r.timestamp): r
            for r in iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=CONSUMPTION, windows=self.windows,
                consumption_by_ts=bogus_cons, production_by_ts=bogus_prod,
            )
        }
        alice = readings[(self.consumption_mp.id, _ts(date(2026, 1, 5)))]
        self.assertEqual(alice.split, split_consumption(D(4), D(100), D(0)))

    def test_invalid_kind_raises(self):
        with self.assertRaises(ValueError):
            list(iter_allocated_readings(
                self.zev, START_DT, END_DT, kind="bogus", windows=self.windows
            ))


class SharedReadModelTests(TestCase):
    """Pins the read-model contract for community-allocated readings (shared
    metering points, docs/specs/2026-08-shared-metering-points.md §7.7)."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="shared_readmodel_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Shared ReadModel ZEV", owner=self.owner, zev_type="vzev",
            start_date=PERIOD_START, billing_interval="monthly", invoice_prefix="SR",
        )
        self.zev.refresh_from_db()

        self.alice = make_named_participant(self.zev, "Alice Muster", PERIOD_START)
        self.community_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION, meter_id="CH-SR-COMMUNITY-1",
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.community_mp, participant=self.alice,
            valid_from=PERIOD_START, allocation_mode=AllocationMode.COMMUNITY,
        )
        MeterReading.objects.create(
            metering_point=self.community_mp, timestamp=_ts(date(2026, 1, 5)),
            energy_kwh=Decimal("4"), direction=ReadingDirection.IN,
        )

        self.windows = AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)

    def test_community_readings_carry_mode_and_literal_holder(self):
        """A community reading resolves to its literal holder (provenance)
        and carries allocation_mode='community' — the two things a consumer
        needs to distribute it instead of attributing it to the holder."""
        readings = {
            (r.metering_point_id, r.timestamp): r
            for r in iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=CONSUMPTION, windows=self.windows,
            )
        }
        reading = readings[(self.community_mp.id, _ts(date(2026, 1, 5)))]

        self.assertEqual(reading.holder_id, self.alice.id)
        self.assertEqual(reading.allocation_mode, "community")

    def test_community_readings_split_against_the_physical_pool(self):
        """Split math is unchanged for community meters: allocation_mode only
        changes how a consumer attributes the reading, never the physical
        split against the community pool."""
        cons_by_ts, prod_by_ts = community_totals_by_timestamp(self.zev, START_DT, END_DT)
        readings = {
            (r.metering_point_id, r.timestamp): r
            for r in iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=CONSUMPTION, windows=self.windows,
                consumption_by_ts=cons_by_ts, production_by_ts=prod_by_ts,
            )
        }
        reading = readings[(self.community_mp.id, _ts(date(2026, 1, 5)))]
        expected = split_consumption(
            Decimal("4"), cons_by_ts[_ts(date(2026, 1, 5))], prod_by_ts.get(_ts(date(2026, 1, 5)), Decimal("0")),
        )

        self.assertEqual(reading.split, expected)

    def test_community_readings_are_distinct_from_gap_readings(self):
        """A community reading and a gap reading both carry a non-attributing
        signal, but consumers must be able to tell them apart: a gap has
        holder_id=None, a community reading has a real holder_id and
        allocation_mode='community'."""
        gap_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_type=MeteringPointType.CONSUMPTION, meter_id="CH-SR-GAP-1",
        )
        MeterReading.objects.create(
            metering_point=gap_mp, timestamp=_ts(date(2026, 1, 5)),
            energy_kwh=Decimal("2"), direction=ReadingDirection.IN,
        )
        windows = AssignmentWindows.for_zev(self.zev, PERIOD_START, PERIOD_END)
        readings = {
            (r.metering_point_id, r.timestamp): r
            for r in iter_allocated_readings(
                self.zev, START_DT, END_DT, kind=CONSUMPTION, windows=windows,
            )
        }

        gap = readings[(gap_mp.id, _ts(date(2026, 1, 5)))]
        community = readings[(self.community_mp.id, _ts(date(2026, 1, 5)))]

        self.assertIsNone(gap.holder_id)
        self.assertIsNone(gap.allocation_mode)
        self.assertIsNotNone(community.holder_id)
        self.assertEqual(community.allocation_mode, "community")


class EligibleParticipantSharesTests(TestCase):
    """Unit tests for eligible_participant_shares — the shared "who's
    eligible and at what weight, per date" primitive every community-reading
    consumer uses."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="shares_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Shares ZEV", owner=self.owner, zev_type="vzev",
            start_date=PERIOD_START, billing_interval="monthly", invoice_prefix="SH",
        )
        self.zev.refresh_from_db()

    def _participant(self, name, valid_from, valid_to=None, weight="1"):
        p = make_named_participant(self.zev, name, valid_from, valid_to)
        p.allocation_weight = Decimal(weight)
        p.save(update_fields=["allocation_weight"])
        return p

    def test_default_weights_split_evenly(self):
        self._participant("Alice Muster", PERIOD_START)
        self._participant("Bob Beispiel", PERIOD_START)

        shares = eligible_participant_shares(self.zev, PERIOD_START, PERIOD_END)

        day_shares = shares[date(2026, 1, 5)]
        self.assertEqual(set(day_shares.values()), {Decimal("0.5")})
        self.assertEqual(sum(day_shares.values()), Decimal("1"))

    def test_unequal_weights_produce_proportional_shares(self):
        alice = self._participant("Alice Muster", PERIOD_START, weight="3")
        bob = self._participant("Bob Beispiel", PERIOD_START, weight="1")

        shares = eligible_participant_shares(self.zev, PERIOD_START, PERIOD_END)

        day_shares = shares[date(2026, 1, 5)]
        self.assertEqual(day_shares[alice.id], Decimal("0.75"))
        self.assertEqual(day_shares[bob.id], Decimal("0.25"))
        self.assertEqual(sum(day_shares.values()), Decimal("1"))

    def test_joiner_only_appears_from_their_join_date(self):
        alice = self._participant("Alice Muster", PERIOD_START)
        bob = self._participant("Bob Beispiel", date(2026, 1, 16))

        shares = eligible_participant_shares(self.zev, PERIOD_START, PERIOD_END)

        self.assertEqual(shares[date(2026, 1, 15)], {alice.id: Decimal("1")})
        self.assertEqual(shares[date(2026, 1, 16)], {alice.id: Decimal("0.5"), bob.id: Decimal("0.5")})

    def test_date_with_no_eligible_participant_is_absent(self):
        self._participant("Alice Muster", date(2026, 1, 10), date(2026, 1, 20))

        shares = eligible_participant_shares(self.zev, PERIOD_START, PERIOD_END)

        self.assertIn(date(2026, 1, 10), shares)
        self.assertNotIn(date(2026, 1, 1), shares)
        self.assertNotIn(date(2026, 1, 31), shares)

    def test_a_zev_with_no_participants_returns_empty(self):
        self.assertEqual(eligible_participant_shares(self.zev, PERIOD_START, PERIOD_END), {})
