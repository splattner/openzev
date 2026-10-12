"""VAT on invoices that carry a producer credit (#957).

See tariffs spec §4.8. At CHF 0.20/kWh a producer's 200 kWh sold locally earn
CHF 40.00; the ZEV charges a monthly fee of CHF 100.00. VAT is 8.1 %.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase

from accounts.models import UserRole, VatRate
from invoices.engine import generate_invoice
from invoices.test_helpers import make_user
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from testing import factories
from testing.helpers import clear_vat_rates, create_managed_zev
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType, VatMode

JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)


class _ProducerCreditVatBase:
    vat_mode = VatMode.REGISTERED

    def setUp(self):
        clear_vat_rates()
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=JAN)
        self.owner = make_user(f"pcv_owner_{id(self)}", UserRole.USER)
        self.zev = create_managed_zev(
            name="Producer Credit VAT ZEV", owner=self.owner, zev_type="vzev",
            start_date=JAN, billing_interval="monthly", invoice_prefix=f"PV{id(self) % 10000}",
        )
        self.zev.vat_mode = self.vat_mode
        self.zev.save(update_fields=["vat_mode"])
        factories.flat_tariff(self.zev, energy_type=EnergyType.LOCAL, price="0.20000")
        self.fee = Tariff.objects.create(
            zev=self.zev, name="Basic fee", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE, fixed_price_chf=Decimal("100.00"),
            valid_from=JAN,
        )

    def _participant(self, first, last):
        return factories.ParticipantFactory(
            zev=self.zev, first_name=first, last_name=last,
            email=f"{first}.{last}@example.com".lower(), valid_from=JAN,
        )

    def _meter(self, participant, meter_type, meter_id, kwh, direction, mode=AllocationMode.PERSONAL):
        mp = MeteringPoint.objects.create(zev=self.zev, meter_type=meter_type, meter_id=meter_id)
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=participant, valid_from=JAN, allocation_mode=mode,
        )
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 5, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal(kwh), direction=direction,
        )
        return mp

    def _producer_and_consumer(self):
        """A producer selling 200 kWh locally to a consumer who takes all of it."""
        producer = self._participant("Paula", "Producer")
        consumer = self._participant("Carl", "Consumer")
        self._meter(producer, MeteringPointType.PRODUCTION, "CH-PCV-P", "200", ReadingDirection.OUT)
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-PCV-C", "200", ReadingDirection.IN)
        return producer, consumer

    def _generate(self, participant):
        return generate_invoice(participant, JAN, JAN_END)


class ProducerCreditVatRegisteredTests(_ProducerCreditVatBase, TestCase):
    def test_vat_is_charged_on_the_zevs_supplies_not_on_the_net_of_the_credit(self):
        producer, _ = self._producer_and_consumer()

        invoice = self._generate(producer)

        self.assertEqual(invoice.subtotal_chf, Decimal("60.00"))  # 100.00 fee - 40.00 credit
        self.assertEqual(invoice.vat_base_chf, Decimal("100.00"))
        self.assertEqual(invoice.vat_chf, Decimal("8.10"))
        self.assertEqual(invoice.total_chf, Decimal("68.10"))

    def test_a_consumer_without_a_credit_is_unchanged(self):
        _, consumer = self._producer_and_consumer()

        invoice = self._generate(consumer)

        # fee 100.00 + 200 kWh local energy 40.00
        self.assertEqual(invoice.subtotal_chf, Decimal("140.00"))
        self.assertEqual(invoice.vat_base_chf, Decimal("140.00"))
        self.assertEqual(invoice.vat_chf, Decimal("11.34"))
        self.assertEqual(invoice.total_chf, Decimal("151.34"))

    def test_participant_with_only_local_producer_credits_owes_no_vat(self):
        producer, _ = self._producer_and_consumer()
        self.fee.delete()

        invoice = self._generate(producer)

        self.assertEqual(invoice.subtotal_chf, Decimal("-40.00"))
        self.assertEqual(invoice.vat_base_chf, Decimal("0.00"))
        self.assertEqual(invoice.vat_chf, Decimal("0.00"))
        self.assertEqual(invoice.total_chf, Decimal("-40.00"))

    def test_feed_in_credit_still_reduces_the_vat_base(self):
        # Open question #969: the feed-in credit is not a producer-credit bucket.
        producer = self._participant("Paula", "Producer")
        consumer = self._participant("Carl", "Consumer")
        self._meter(producer, MeteringPointType.PRODUCTION, "CH-PCV-FP", "200", ReadingDirection.OUT)
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-PCV-FC", "100", ReadingDirection.IN)
        factories.flat_tariff(self.zev, energy_type=EnergyType.FEED_IN, price="0.10000")
        self.fee.delete()

        invoice = self._generate(producer)

        # 100 kWh sold locally (-20.00) and 100 kWh exported (-10.00).
        self.assertEqual(invoice.subtotal_chf, Decimal("-30.00"))
        self.assertEqual(invoice.vat_base_chf, Decimal("-10.00"))
        self.assertEqual(invoice.vat_chf, Decimal("-0.81"))

    def test_shared_producer_credit_does_not_reduce_vat_either(self):
        alice = self._participant("Alice", "Member")
        bob = self._participant("Bob", "Member")
        carol = self._participant("Carol", "Consumer")
        # A community-owned plant, shared by weight between all three members.
        self._meter(
            alice, MeteringPointType.PRODUCTION, "CH-PCV-SP", "200", ReadingDirection.OUT,
            mode=AllocationMode.COMMUNITY,
        )
        self._meter(carol, MeteringPointType.CONSUMPTION, "CH-PCV-SC", "200", ReadingDirection.IN)

        invoice = self._generate(alice)

        # 200 kWh sold locally, a third to each member: credit 13.33 against the fee.
        self.assertEqual(invoice.subtotal_chf, Decimal("86.67"))
        self.assertEqual(invoice.vat_base_chf, Decimal("100.00"))
        self.assertEqual(invoice.vat_chf, Decimal("8.10"))
        self.assertEqual(invoice.total_chf, Decimal("94.77"))
        self.assertEqual(self._generate(bob).total_chf, Decimal("94.77"))

    def test_a_genuine_credit_line_still_reduces_the_vat_base(self):
        producer, _ = self._producer_and_consumer()
        Tariff.objects.create(
            zev=self.zev, name="Goodwill", category=TariffCategory.LEVIES,
            billing_mode=BillingMode.YEARLY_FEE, fixed_price_chf=Decimal("-120.00"),
            valid_from=JAN,
        )

        invoice = self._generate(producer)

        # The goodwill line is a price reduction on the ZEV's own supply: -10.00 for the month.
        self.assertEqual(invoice.subtotal_chf, Decimal("50.00"))
        self.assertEqual(invoice.vat_base_chf, Decimal("90.00"))
        self.assertEqual(invoice.vat_chf, Decimal("7.29"))
        self.assertEqual(invoice.total_chf, Decimal("57.29"))


class _NoVatModeChecks:
    """``not_registered`` and ``inclusive`` charge no VAT and record no base."""

    subtotal = Decimal("60.00")

    def test_no_vat_base_is_recorded_and_the_credit_nets_off_verbatim(self):
        producer, _ = self._producer_and_consumer()

        invoice = self._generate(producer)

        self.assertIsNone(invoice.vat_base_chf)
        self.assertEqual(invoice.vat_chf, Decimal("0.00"))
        self.assertEqual(invoice.subtotal_chf, self.subtotal)
        self.assertEqual(invoice.total_chf, self.subtotal)


class ProducerCreditVatNotRegisteredTests(_NoVatModeChecks, _ProducerCreditVatBase, TestCase):
    vat_mode = VatMode.NOT_REGISTERED


class ProducerCreditVatInclusiveTests(_NoVatModeChecks, _ProducerCreditVatBase, TestCase):
    vat_mode = VatMode.INCLUSIVE
    # The fee bears input VAT and is grossed (100.00 × 1.081); the credit is not.
    subtotal = Decimal("68.10")
