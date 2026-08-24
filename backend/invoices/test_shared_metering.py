"""Tests for community-allocated metering points (shared metering, #387).

A ``COMMUNITY``-mode assignment does not change who holds a metering point —
the holder of record is unchanged, for provenance — but it changes who pays:
the meter's energy and per-metering-point fees are split across every
eligible participant by ``Participant.allocation_weight`` instead of being
billed to the holder alone.

``§7.3`` (personal vs. community is a per-timestamp decision) is the
load-bearing rule: a queryset filter cannot separate a meter's personal
readings from its community readings when the mode changes mid-period, so the
engine gates each *reading* individually via ``assignment_at``.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import pytest

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserRole
from invoices.models import InvoiceItem
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, TariffCategory
from testing import factories
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType, Zev

from .engine import generate_invoice

pytestmark = pytest.mark.django_db

User = get_user_model()

JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)


class _SharedMeteringBase:
    """Shared fixture builders for the community-metering scenarios."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username=f"shared_owner_{id(self)}", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="Shared Metering ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=JAN,
            billing_interval="monthly",
            invoice_prefix=f"SM{id(self) % 10000}",
        )
        self.zev.refresh_from_db()

    def _participant(self, name, valid_from=JAN, valid_to=None, weight="1"):
        first, last = name.split(" ", 1)
        return factories.ParticipantFactory(
            zev=self.zev, first_name=first, last_name=last,
            email=f"{name.replace(' ', '').lower()}@example.com",
            valid_from=valid_from, valid_to=valid_to,
            allocation_weight=Decimal(weight),
        )

    def _mp(self, meter_type, meter_id):
        return MeteringPoint.objects.create(zev=self.zev, meter_type=meter_type, meter_id=meter_id)

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

    def _grid_tariff(self, price="0.20000"):
        return factories.flat_tariff(self.zev, energy_type=EnergyType.GRID, price=price)

    def _feed_in_tariff(self, price="0.08000"):
        return factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price=price)

    def _mp_fee_tariff(self, price="10.00"):
        return factories.TariffFactory(
            zev=self.zev,
            billing_mode=BillingMode.PER_METERING_POINT_MONTHLY_FEE,
            category=TariffCategory.METERING,
            energy_type=None,
            fixed_price_chf=Decimal(price),
        )

    def _grid_items(self, invoice):
        return list(invoice.items.filter(item_type=InvoiceItem.ItemType.GRID_ENERGY))

    def _feed_in_items(self, invoice):
        return list(invoice.items.filter(item_type=InvoiceItem.ItemType.FEED_IN))

    def _fee_items(self, invoice):
        return list(invoice.items.filter(tariff_category=TariffCategory.METERING))


class SharedConsumptionSplitTests(_SharedMeteringBase, TestCase):
    def test_shared_consumption_is_billed_to_every_member_by_weight(self):
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="3")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-1")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")

        self._grid_tariff(price="0.20000")
        levy = factories.flat_tariff(
            self.zev, category=TariffCategory.LEVIES, energy_type=EnergyType.GRID, price="0.05000")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        # Alice: 1/4 of 10 kWh = 2.5; Bob: 3/4 of 10 kWh = 7.5.
        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("2.5000"))
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("7.5000"))
        self.assertEqual(alice_invoice.total_local_kwh, Decimal("0.0000"))

        self.assertEqual(len(self._grid_items(alice_invoice)), 2)  # energy + levies, incl. levies
        energy_item = next(i for i in self._grid_items(alice_invoice) if i.tariff_category == TariffCategory.ENERGY)
        levy_item = next(i for i in self._grid_items(alice_invoice) if i.tariff_category == TariffCategory.LEVIES)
        self.assertEqual(energy_item.total_chf, Decimal("0.50"))   # 2.5 * 0.20
        self.assertEqual(levy_item.total_chf, Decimal("0.13"))     # 2.5 * 0.05 = 0.125 -> HALF_UP 0.13
        self.assertEqual(levy.category, TariffCategory.LEVIES)

        bob_energy = next(i for i in self._grid_items(bob_invoice) if i.tariff_category == TariffCategory.ENERGY)
        bob_levy = next(i for i in self._grid_items(bob_invoice) if i.tariff_category == TariffCategory.LEVIES)
        self.assertEqual(bob_energy.total_chf, Decimal("1.50"))   # 7.5 * 0.20
        self.assertEqual(bob_levy.total_chf, Decimal("0.38"))     # 7.5 * 0.05 = 0.375 -> HALF_UP 0.38

    def test_the_holder_pays_their_share_like_everyone_else(self):
        """The holder of record gets no special case: they pay only their weight
        share, exactly like every other eligible participant (§1.1)."""
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-2")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("5.0000"))
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("5.0000"))

    def test_sole_participant_carries_the_shared_meter_alone(self):
        alice = self._participant("Alice Muster", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-3")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)

        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("10.0000"))

    def test_shared_energy_conservation_within_rounding(self):
        """Uneven, non-terminating weight shares (1 and 2, thirds) must still
        conserve: the sum of both invoices reproduces the un-split amount
        within one rappen (§10)."""
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="2")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-4")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")
        self._grid_tariff(price="0.30000")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        full_amount = Decimal("10") * Decimal("0.30000")  # 3.00
        combined = alice_invoice.subtotal_chf + bob_invoice.subtotal_chf
        self.assertLessEqual(abs(combined - full_amount), Decimal("0.01"))

        combined_kwh = alice_invoice.total_grid_kwh + bob_invoice.total_grid_kwh
        self.assertLessEqual(abs(combined_kwh - Decimal("10")), Decimal("0.0001"))


class SharedProductionSplitTests(_SharedMeteringBase, TestCase):
    def test_shared_production_credits_every_member_symmetrically(self):
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="1")
        community_prod_mp = self._mp(MeteringPointType.PRODUCTION, "CH-SM-PROD-1")
        self._assign(community_prod_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._production(community_prod_mp, date(2026, 1, 5), "10")
        self._feed_in_tariff(price="0.08000")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        # No consumption anywhere: the entire community production is exported.
        self.assertEqual(alice_invoice.total_feed_in_kwh, Decimal("5.0000"))
        self.assertEqual(bob_invoice.total_feed_in_kwh, Decimal("5.0000"))

        alice_feed_in = self._feed_in_items(alice_invoice)[0]
        bob_feed_in = self._feed_in_items(bob_invoice)[0]
        self.assertEqual(alice_feed_in.total_chf, Decimal("-0.40"))  # -(5 * 0.08)
        self.assertEqual(bob_feed_in.total_chf, Decimal("-0.40"))

    def test_community_production_uses_same_eligibility_rule(self):
        """A mid-period joiner gets no credit for community production before
        their join date — the same date-granular eligibility rule as
        consumption."""
        alice = self._participant("Alice Muster", valid_from=JAN, weight="1")
        bob = self._participant("Bob Beispiel", valid_from=date(2026, 1, 16), weight="1")
        community_prod_mp = self._mp(MeteringPointType.PRODUCTION, "CH-SM-PROD-2")
        self._assign(community_prod_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._production(community_prod_mp, date(2026, 1, 5), "10")   # before Bob joins
        self._production(community_prod_mp, date(2026, 1, 20), "10")  # after Bob joins
        self._feed_in_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        # Jan 5: Alice alone -> all 10 exported to her. Jan 20: split 50/50.
        self.assertEqual(alice_invoice.total_feed_in_kwh, Decimal("15.0000"))
        self.assertEqual(bob_invoice.total_feed_in_kwh, Decimal("5.0000"))


class MixedWindowAndTimingTests(_SharedMeteringBase, TestCase):
    def test_shared_meter_part_of_period_only_shares_that_window(self):
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-5")
        # Community only Jan 1-15; unassigned afterwards.
        self._assign(community_mp, alice, JAN, date(2026, 1, 15), mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")   # inside the window
        self._consumption(community_mp, date(2026, 1, 20), "6")   # outside: a gap, billed to nobody
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        # Only the Jan 5 reading (10 kWh) is shared; the Jan 20 gap reading
        # (6 kWh) is excluded from both invoices entirely.
        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("5.0000"))
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("5.0000"))

    def test_mixed_window_meter_bills_personally_then_shares(self):
        """§7.3's load-bearing case: a meter personal in month 1 and community
        in month 2 bills the holder in full for month 1 and only a weighted
        share for month 2 — no lost readings, no double billing."""
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="1")
        mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-MIXED-1")
        self._assign(mp, alice, JAN, date(2026, 1, 15), mode=AllocationMode.PERSONAL)
        self._assign(mp, alice, date(2026, 1, 16), mode=AllocationMode.COMMUNITY)
        self._consumption(mp, date(2026, 1, 5), "10")   # personal window: Alice alone
        self._consumption(mp, date(2026, 1, 20), "8")    # community window: split 50/50
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("14.0000"))  # 10 + 4
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("4.0000"))     # 4 only

    def test_community_readings_are_not_counted_as_skipped(self):
        """A community reading must never appear in the "no assignment
        covered this reading" skip log — it belongs to everybody, not
        nobody (§7.3)."""
        alice = self._participant("Alice Muster", weight="1")
        self._participant("Bob Beispiel", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-6")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")
        self._grid_tariff()

        with self.assertNoLogs("invoices.engine", level="WARNING"):
            generate_invoice(alice, JAN, JAN_END)

    def test_joiner_does_not_pay_for_community_energy_before_join_date(self):
        alice = self._participant("Alice Muster", valid_from=JAN, weight="1")
        bob = self._participant("Bob Beispiel", valid_from=date(2026, 1, 16), weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-7")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")   # before Bob joins
        self._consumption(community_mp, date(2026, 1, 20), "10")  # after Bob joins
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        # Jan 5: Alice alone pays the full 10. Jan 20: split 50/50 (5 each).
        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("15.0000"))
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("5.0000"))

    def test_leaver_does_not_pay_for_community_energy_after_leave_date(self):
        alice = self._participant("Alice Muster", valid_from=JAN, valid_to=date(2026, 1, 15), weight="1")
        bob = self._participant("Bob Beispiel", valid_from=JAN, weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-COMM-8")
        self._assign(community_mp, bob, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")   # both eligible
        self._consumption(community_mp, date(2026, 1, 20), "10")  # only Bob eligible
        self._grid_tariff()

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("5.0000"))    # Jan 5 half only
        self.assertEqual(bob_invoice.total_grid_kwh, Decimal("15.0000"))     # Jan 5 half + Jan 20 full


class PerMeteringPointCommunityFeeTests(_SharedMeteringBase, TestCase):
    def test_per_metering_point_fee_splits_shared_meters_and_excludes_holder(self):
        alice = self._participant("Alice Muster", weight="1")
        bob = self._participant("Bob Beispiel", weight="1")
        personal_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-PMP-1")
        self._assign(personal_mp, alice, JAN, mode=AllocationMode.PERSONAL)
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-PMP-2")
        # Alice is also the holder of record for the community meter — this
        # must not count towards her *personal* per-metering-point total.
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._mp_fee_tariff(price="10.00")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)
        bob_invoice = generate_invoice(bob, JAN, JAN_END)

        alice_fees = self._fee_items(alice_invoice)
        # One personal line (her own meter, excluding the community one she
        # merely holds) and one shared line (her 1/2 weight share of the
        # community meter's fee).
        self.assertEqual(len(alice_fees), 2)
        personal_line = next(i for i in alice_fees if i.quantity_kwh == Decimal("1.0000") and i.total_chf == Decimal("10.00"))
        shared_line = next(i for i in alice_fees if i.total_chf == Decimal("5.00"))
        self.assertIsNotNone(personal_line)
        self.assertIsNotNone(shared_line)

        bob_fees = self._fee_items(bob_invoice)
        self.assertEqual(len(bob_fees), 1)  # no personal meters, only the shared line
        self.assertEqual(bob_fees[0].total_chf, Decimal("5.00"))

    def test_inactive_shared_meter_bills_nobody(self):
        alice = self._participant("Alice Muster", weight="1")
        self._participant("Bob Beispiel", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-PMP-3")
        community_mp.is_active = False
        community_mp.save()
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._mp_fee_tariff(price="10.00")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)

        self.assertEqual(self._fee_items(alice_invoice), [])

    def test_weighted_energy_and_fee_use_their_respective_time_granularity(self):
        """Energy shares are date-granular; per-metering-point fee shares are
        month-granular — a joiner's weight dilutes the whole month's fee
        denominator immediately, but only the energy readings from their
        join date onward (§7.1)."""
        alice = self._participant("Alice Muster", valid_from=JAN, weight="1")
        self._participant("Bob Beispiel", valid_from=date(2026, 1, 16), weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-PMP-4")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")  # before Bob joins
        self._grid_tariff()
        self._mp_fee_tariff(price="10.00")

        alice_invoice = generate_invoice(alice, JAN, JAN_END)

        # Energy: Bob is not eligible for the Jan 5 reading at all, so Alice
        # pays the full amount — no dilution.
        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("10.0000"))

        # Fee: Bob is a member for *some* part of January, so the month's
        # weight sum already includes him in full — Alice's fee share is
        # diluted for the whole month despite Bob joining on the 16th.
        shared_fee = next(i for i in self._fee_items(alice_invoice) if i.total_chf != Decimal("0.00"))
        self.assertEqual(shared_fee.total_chf, Decimal("5.00"))


class InvoiceTotalsAndDescriptionTests(_SharedMeteringBase, TestCase):
    def test_invoice_kwh_totals_include_shared_energy(self):
        alice = self._participant("Alice Muster", weight="1")
        self._participant("Bob Beispiel", weight="1")

        personal_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-TOT-1")
        self._assign(personal_mp, alice, JAN, mode=AllocationMode.PERSONAL)
        self._consumption(personal_mp, date(2026, 1, 5), "5")

        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-TOT-2")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "5")  # Alice's share: 2.5

        self._grid_tariff()

        invoice = generate_invoice(alice, JAN, JAN_END)

        self.assertEqual(invoice.total_grid_kwh, Decimal("7.5000"))

    def test_single_participant_regeneration_equals_full_run(self):
        """Regenerating one participant's invoice alone must yield the same
        shared share as it would in a full run: weights are read from ZEV
        membership, never from sibling invoices (§7.1)."""
        alice = self._participant("Alice Muster", weight="1")
        self._participant("Bob Beispiel", weight="1")
        community_mp = self._mp(MeteringPointType.CONSUMPTION, "CH-SM-TOT-3")
        self._assign(community_mp, alice, JAN, mode=AllocationMode.COMMUNITY)
        self._consumption(community_mp, date(2026, 1, 5), "10")
        self._grid_tariff()

        # Only Alice's invoice is generated — Bob's is never created.
        alice_invoice = generate_invoice(alice, JAN, JAN_END)

        self.assertEqual(alice_invoice.total_grid_kwh, Decimal("5.0000"))

    def test_shared_line_description_carries_the_community_marker(self):
        markers = {
            "de": "Gemeinschaftsanteil",
            "fr": "Part communautaire",
            "it": "Quota comunitaria",
            "en": "Community share",
        }
        for lang, marker in markers.items():
            with self.subTest(lang=lang):
                zev = Zev.objects.create(
                    name=f"Marker ZEV {lang}",
                    owner=self.owner,
                    zev_type="vzev",
                    start_date=JAN,
                    billing_interval="monthly",
                    invoice_prefix=f"MK{lang.upper()}",
                    invoice_language=lang,
                )
                zev.refresh_from_db()
                alice = factories.ParticipantFactory(zev=zev, first_name="Alice", last_name="Muster", valid_from=JAN)
                community_mp = MeteringPoint.objects.create(
                    zev=zev, meter_type=MeteringPointType.CONSUMPTION, meter_id=f"CH-SM-MARKER-{lang}")
                MeteringPointAssignment.objects.create(
                    metering_point=community_mp, participant=alice, valid_from=JAN,
                    allocation_mode=AllocationMode.COMMUNITY,
                )
                self._reading(community_mp, date(2026, 1, 5), "10", ReadingDirection.IN)
                factories.flat_tariff(zev, energy_type=EnergyType.GRID, price="0.20000")

                invoice = generate_invoice(alice, JAN, JAN_END)
                grid_item = self._grid_items(invoice)[0]
                self.assertIn(marker, grid_item.description)
