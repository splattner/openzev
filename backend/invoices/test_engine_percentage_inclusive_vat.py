"""Percentage-of-energy tariffs on a ZEV in inclusive VAT mode (#1173).

Grid energy 0.10 plus grid fee 0.10 is 0.20 CHF/kWh without VAT. In inclusive
mode the participant is billed 0.20 x 1.081 = 0.2162 for it, so "65 % of the
grid price" is 0.14053 CHF/kWh, not 0.13.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase

from accounts.models import UserRole, VatRate
from invoices.engine import generate_invoice
from invoices.test_helpers import make_user
from metering.models import MeterReading, ReadingDirection
from tariffs.models import EnergyType, TariffCategory
from testing import factories
from testing.helpers import clear_vat_rates, create_managed_zev
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, VatMode

JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)


class PercentageBaseInclusiveVatTests(TestCase):
    vat_mode = VatMode.INCLUSIVE

    def setUp(self):
        clear_vat_rates()
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=JAN)
        self.owner = make_user(f"pbi_owner_{id(self)}", UserRole.USER)
        self.zev = create_managed_zev(
            name="Percentage Base ZEV", owner=self.owner, zev_type="vzev",
            start_date=JAN, billing_interval="monthly", invoice_prefix=f"PB{id(self) % 10000}",
        )
        self.zev.vat_mode = self.vat_mode
        self.zev.save(update_fields=["vat_mode"])
        factories.flat_tariff(self.zev, energy_type=EnergyType.GRID, price="0.10000")
        factories.flat_tariff(
            self.zev, category=TariffCategory.GRID_FEES, energy_type=EnergyType.GRID, price="0.10000",
        )
        self.local_pct = factories.percentage_tariff(
            self.zev, category=TariffCategory.ENERGY, energy_type=EnergyType.LOCAL, percentage="65.00",
        )

    def _participant(self, first):
        return factories.ParticipantFactory(
            zev=self.zev, first_name=first, last_name="Member",
            email=f"{first}@example.com".lower(), valid_from=JAN,
        )

    def _meter(self, participant, meter_type, meter_id, kwh, direction):
        mp = MeteringPoint.objects.create(zev=self.zev, meter_type=meter_type, meter_id=meter_id)
        MeteringPointAssignment.objects.create(metering_point=mp, participant=participant, valid_from=JAN)
        MeterReading.objects.create(
            metering_point=mp, timestamp=datetime(2026, 1, 5, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal(kwh), direction=direction,
        )

    def _local_trade(self):
        producer, consumer = self._participant("Paula"), self._participant("Carl")
        self._meter(producer, MeteringPointType.PRODUCTION, "CH-PBI-P", "200", ReadingDirection.OUT)
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-PBI-C", "200", ReadingDirection.IN)
        return producer, consumer

    def _item(self, invoice, tariff):
        # Items keep no tariff link, only the description the tariff's name opens.
        return invoice.items.get(description__startswith=f"{tariff.name} (")

    def _local_item(self, invoice):
        return self._item(invoice, self.local_pct)

    def test_percentage_is_taken_of_the_grid_price_with_vat(self):
        _, consumer = self._local_trade()

        item = self._local_item(generate_invoice(consumer, JAN, JAN_END))

        self.assertEqual(item.total_chf, Decimal("28.11"))  # 200 x 0.2162 x 65 %
        self.assertEqual(item.unit_price_chf, Decimal("0.14053"))
        self.assertIn("65% von CHF 0.2162/kWh", item.description)

    def test_local_line_itself_gets_no_vat_added(self):
        _, consumer = self._local_trade()

        invoice = generate_invoice(consumer, JAN, JAN_END)

        self.assertEqual(invoice.subtotal_chf, Decimal("28.11"))
        self.assertEqual(invoice.vat_chf, Decimal("0.00"))
        self.assertEqual(invoice.embedded_vat_chf, Decimal("0.00"))

    def test_producer_credit_uses_the_same_base_as_the_consumer_charge(self):
        producer, consumer = self._local_trade()

        charge = generate_invoice(consumer, JAN, JAN_END).subtotal_chf
        credit = generate_invoice(producer, JAN, JAN_END).subtotal_chf

        self.assertEqual(charge + credit, Decimal("0.00"))

    def test_a_grossed_percentage_line_is_not_grossed_twice(self):
        # A 10 % levy on the grid price is itself VAT-bearing, so the engine
        # grosses it afterwards: 100 kWh x 0.20 x 10 % = 2.00, x 1.081 = 2.16.
        levy = factories.percentage_tariff(
            self.zev, category=TariffCategory.LEVIES, energy_type=EnergyType.GRID, percentage="10.00",
        )
        consumer = self._participant("Carl")
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-PBI-G", "100", ReadingDirection.IN)

        invoice = generate_invoice(consumer, JAN, JAN_END)

        self.assertEqual(self._item(invoice, levy).total_chf, Decimal("2.16"))
        self.assertEqual(invoice.subtotal_chf, Decimal("23.78"))  # 10.81 + 10.81 + 2.16


class PercentageBaseOtherVatModesTests(PercentageBaseInclusiveVatTests):
    """Not-registered and registered ZEVs keep the base without VAT."""

    vat_mode = VatMode.NOT_REGISTERED

    def test_percentage_is_taken_of_the_grid_price_with_vat(self):
        _, consumer = self._local_trade()

        item = self._local_item(generate_invoice(consumer, JAN, JAN_END))

        self.assertEqual(item.total_chf, Decimal("26.00"))  # 200 x 0.20 x 65 %
        self.assertIn("65% von CHF 0.2/kWh", item.description)

    def test_local_line_itself_gets_no_vat_added(self):
        _, consumer = self._local_trade()
        self.assertEqual(generate_invoice(consumer, JAN, JAN_END).subtotal_chf, Decimal("26.00"))

    def test_a_grossed_percentage_line_is_not_grossed_twice(self):
        levy = factories.percentage_tariff(
            self.zev, category=TariffCategory.LEVIES, energy_type=EnergyType.GRID, percentage="10.00",
        )
        consumer = self._participant("Carl")
        self._meter(consumer, MeteringPointType.CONSUMPTION, "CH-PBI-G", "100", ReadingDirection.IN)

        invoice = generate_invoice(consumer, JAN, JAN_END)

        self.assertEqual(self._item(invoice, levy).total_chf, Decimal("2.00"))
