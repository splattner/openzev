"""What a producer's local sales would have earned as feed-in, stored per invoice.

The annual report's producer uplift is ``local_sale_chf`` minus
``local_sale_feed_in_chf``, so the second figure has to be priced the way the
real feed-in credit is: interval by interval, through the same resolver. A
producer who sells 200 kWh locally at CHF 0.20 earns 40.00; at a feed-in tariff
of CHF 0.08 the same energy would have earned 16.00.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase

from invoices.engine import generate_invoice
from metering.models import MeterReading, ReadingDirection
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from testing import factories
from testing.helpers import create_managed_zev
from invoices.test_helpers import make_user
from accounts.models import UserRole
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType

JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)
UTC = dt_timezone.utc


def _at(day, hour, minute=0):
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


class _Base:
    def setUp(self):
        owner = make_user(f"lsf_owner_{id(self)}", UserRole.USER)
        self.zev = create_managed_zev(
            name="Local Sale ZEV", owner=owner, zev_type="vzev", start_date=JAN,
            billing_interval="monthly", invoice_prefix=f"LS{id(self) % 10000}",
        )
        factories.flat_tariff(self.zev, energy_type=EnergyType.LOCAL, price="0.20000")

    def _participant(self, first, last):
        return factories.ParticipantFactory(
            zev=self.zev, first_name=first, last_name=last,
            email=f"{first}.{last}@example.com".lower(), valid_from=JAN,
        )

    def _meter(self, participant, meter_type, meter_id, readings, direction, mode=AllocationMode.PERSONAL):
        mp = MeteringPoint.objects.create(zev=self.zev, meter_type=meter_type, meter_id=meter_id)
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=JAN, allocation_mode=mode,
        )
        for ts, kwh in readings:
            MeterReading.objects.create(
                metering_point=mp, timestamp=ts, energy_kwh=Decimal(kwh), direction=direction,
            )
        return mp

    def _producer_and_consumer(self, produced, consumed):
        """``produced``/``consumed`` are lists of ``(timestamp, kwh)``."""
        producer = self._participant("Paula", "Producer")
        consumer = self._participant("Carl", "Consumer")
        self._meter(producer, MeteringPointType.PRODUCTION, "CH-LS-P", produced, ReadingDirection.OUT)
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-LS-C", consumed, ReadingDirection.IN)
        return producer, consumer

    def _generate(self, participant):
        return generate_invoice(participant, JAN, JAN_END)


class StaticFeedInTests(_Base, TestCase):
    def test_local_sales_are_priced_at_the_feed_in_tariff(self):
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.08000")
        producer, _ = self._producer_and_consumer([(_at(5, 12), "200")], [(_at(5, 12), "200")])

        invoice = self._generate(producer)

        self.assertEqual(invoice.total_local_sold_kwh, Decimal("200.0000"))
        self.assertEqual(invoice.local_sale_chf, Decimal("40.00"))
        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("16.00"))

    def test_only_the_locally_sold_part_of_the_production_counts(self):
        # 300 kWh produced, 200 consumed in the ZEV: 200 sold locally, 100 exported.
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.08000")
        producer, _ = self._producer_and_consumer([(_at(5, 12), "300")], [(_at(5, 12), "200")])

        invoice = self._generate(producer)

        self.assertEqual(invoice.total_local_sold_kwh, Decimal("200.0000"))
        self.assertEqual(invoice.total_feed_in_kwh, Decimal("100.0000"))
        self.assertEqual(invoice.local_sale_chf, Decimal("40.00"))
        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("16.00"))

    def test_a_feed_in_tariff_in_force_on_the_day_applies_not_a_later_one(self):
        # 100 kWh sold on the 5th at the early rate, 100 on the 20th at the later one.
        factories.flat_tariff(
            self.zev, energy_type=EnergyType.FEED_IN, price="0.05000", valid_to=date(2026, 1, 14),
        )
        factories.flat_tariff(
            self.zev, energy_type=EnergyType.FEED_IN, price="0.10000", valid_from=date(2026, 1, 15),
        )
        producer, _ = self._producer_and_consumer(
            [(_at(5, 12), "100"), (_at(20, 12), "100")],
            [(_at(5, 12), "100"), (_at(20, 12), "100")],
        )

        invoice = self._generate(producer)

        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("15.00"))  # 100*0.05 + 100*0.10

    def test_a_participant_without_local_sales_has_a_zero_not_a_null(self):
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.08000")
        _, consumer = self._producer_and_consumer([(_at(5, 12), "200")], [(_at(5, 12), "200")])

        invoice = self._generate(consumer)

        self.assertEqual(invoice.total_local_sold_kwh, Decimal("0.0000"))
        self.assertEqual(invoice.local_sale_chf, Decimal("0.00"))
        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("0.00"))

    def test_without_a_feed_in_tariff_the_comparison_is_unknown_and_the_invoice_still_bills(self):
        producer, _ = self._producer_and_consumer([(_at(5, 12), "200")], [(_at(5, 12), "200")])

        invoice = self._generate(producer)

        self.assertEqual(invoice.local_sale_chf, Decimal("40.00"))
        self.assertIsNone(invoice.local_sale_feed_in_chf)
        self.assertEqual(invoice.subtotal_chf, Decimal("-40.00"))

    def test_a_feed_in_tariff_missing_on_one_sale_day_makes_the_whole_figure_unknown(self):
        # Covering only half the sales would understate the benchmark and
        # inflate the uplift, so one unpriced interval makes the figure null.
        factories.flat_tariff(
            self.zev, energy_type=EnergyType.FEED_IN, price="0.08000", valid_to=date(2026, 1, 14),
        )
        producer, _ = self._producer_and_consumer(
            [(_at(5, 12), "100"), (_at(20, 12), "100")],
            [(_at(5, 12), "100"), (_at(20, 12), "100")],
        )

        invoice = self._generate(producer)

        self.assertIsNone(invoice.local_sale_feed_in_chf)
        self.assertEqual(invoice.local_sale_chf, Decimal("40.00"))


class DynamicFeedInTests(_Base, TestCase):
    def _feed_in_source(self, prices, *, minimum=None):
        source = DynamicTariffSource.objects.create(
            label="Example feed-in", url="https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn",
            api_version="v1_0_5", request_mode="exact_url", supports_range=False,
            tariff_type="feed_in", tariff_name="",
        )
        for ts, price in prices:
            DynamicPricePoint.objects.create(
                source=source, valid_from=ts, valid_to=ts + timedelta(minutes=15),
                price_chf_per_kwh=Decimal(price),
            )
        Tariff.objects.create(
            zev=self.zev, name="Feed-in (dynamic)", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.FEED_IN,
            valid_from=JAN, dynamic_source=source, minimum_price_chf_per_kwh=minimum,
        )

    def test_each_interval_is_priced_at_its_own_fetched_price(self):
        self._feed_in_source([(_at(5, 12), "0.04000"), (_at(5, 13), "0.12000")])
        producer, _ = self._producer_and_consumer(
            [(_at(5, 12), "100"), (_at(5, 13), "100")],
            [(_at(5, 12), "100"), (_at(5, 13), "100")],
        )

        invoice = self._generate(producer)

        # 100*0.04 + 100*0.12 — an average over the exported kWh could not give this.
        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("16.00"))

    def test_the_contractual_minimum_applies_to_the_comparison_too(self):
        self._feed_in_source([(_at(5, 12), "0.05000")], minimum=Decimal("0.08000"))
        producer, _ = self._producer_and_consumer([(_at(5, 12), "100")], [(_at(5, 12), "100")])

        invoice = self._generate(producer)

        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("8.00"))

    def test_a_gap_in_the_fetched_series_leaves_the_comparison_unknown_without_failing_billing(self):
        # Only the first interval is published; the second sale falls in a gap.
        self._feed_in_source([(_at(5, 12), "0.08000")])
        producer, _ = self._producer_and_consumer(
            [(_at(5, 12), "100"), (_at(5, 13), "100")],
            [(_at(5, 12), "100"), (_at(5, 13), "100")],
        )

        invoice = self._generate(producer)

        self.assertEqual(invoice.local_sale_chf, Decimal("40.00"))
        self.assertIsNone(invoice.local_sale_feed_in_chf)


class CommunityProductionTests(_Base, TestCase):
    def test_a_participants_share_of_community_production_is_compared_at_feed_in(self):
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.08000")
        member_a = self._participant("Anna", "Member")
        member_b = self._participant("Bert", "Member")
        self._meter(
            member_a, MeteringPointType.PRODUCTION, "CH-LS-CP", [(_at(5, 12), "200")],
            ReadingDirection.OUT, mode=AllocationMode.COMMUNITY,
        )
        self._meter(
            member_b, MeteringPointType.CONSUMPTION, "CH-LS-CC", [(_at(5, 12), "200")],
            ReadingDirection.IN, mode=AllocationMode.PERSONAL,
        )

        invoice = self._generate(member_a)

        # Two equally weighted members split the community sale: 100 kWh each.
        self.assertEqual(invoice.total_local_sold_kwh, Decimal("100.0000"))
        self.assertEqual(invoice.local_sale_chf, Decimal("20.00"))
        self.assertEqual(invoice.local_sale_feed_in_chf, Decimal("8.00"))
