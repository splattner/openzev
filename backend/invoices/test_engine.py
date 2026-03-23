from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from accounts.models import User, UserRole
from metering.models import MeterReading, ReadingDirection
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev
from .engine import generate_invoice


class InvoiceEngineTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            password="secret",
            role=UserRole.ZEV_OWNER,
        )
        self.zev = Zev.objects.create(
            name="OpenZEV Demo",
            owner=self.owner,
            zev_type="vzev",
            invoice_prefix="INV",
        )
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Alice",
            last_name="Muster",
            email="alice@example.com",
            valid_from=date(2026, 1, 1),
        )
        self.consumption_mp = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.participant,
            meter_id="MP-C-1",
            meter_type=MeteringPointType.CONSUMPTION,
            valid_from=date(2026, 1, 1),
        )
        self.production_mp = MeteringPoint.objects.create(
            zev=self.zev,
            participant=self.participant,
            meter_id="MP-P-1",
            meter_type=MeteringPointType.PRODUCTION,
            valid_from=date(2026, 1, 1),
        )

        for energy_type, price in [
            (EnergyType.LOCAL, Decimal("0.15")),
            (EnergyType.GRID, Decimal("0.25")),
            (EnergyType.FEED_IN, Decimal("0.08")),
        ]:
            tariff = Tariff.objects.create(
                zev=self.zev,
                name=f"{energy_type} tariff",
                category=TariffCategory.ENERGY,
                billing_mode=BillingMode.ENERGY,
                energy_type=energy_type,
                valid_from=date(2026, 1, 1),
            )
            TariffPeriod.objects.create(
                tariff=tariff,
                period_type=PeriodType.FLAT,
                price_chf_per_kwh=price,
            )

    def test_generate_invoice_prices_local_and_grid_energy(self):
        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"),
            direction=ReadingDirection.IN,
        )
        MeterReading.objects.create(
            metering_point=self.production_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("6.0"),
            direction=ReadingDirection.OUT,
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))

        self.assertEqual(invoice.total_local_kwh, Decimal("6.0000"))
        self.assertEqual(invoice.total_grid_kwh, Decimal("4.0000"))
        self.assertEqual(invoice.subtotal_chf, Decimal("1.42"))
        self.assertEqual(invoice.total_chf, Decimal("1.42"))
        self.assertEqual(invoice.items.count(), 3)

    def test_generate_invoice_separates_categories_and_fixed_fees(self):
        grid_tariff = Tariff.objects.create(
            zev=self.zev,
            name="Grid usage fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=grid_tariff,
            period_type=PeriodType.FLAT,
            price_chf_per_kwh=Decimal("0.05"),
        )
        levy_tariff = Tariff.objects.create(
            zev=self.zev,
            name="Federal levy",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=levy_tariff,
            period_type=PeriodType.FLAT,
            price_chf_per_kwh=Decimal("0.02"),
        )
        Tariff.objects.create(
            zev=self.zev,
            name="Metering basic fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE,
            fixed_price_chf=Decimal("12.00"),
            valid_from=date(2026, 1, 1),
        )
        Tariff.objects.create(
            zev=self.zev,
            name="Annual admin fee",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.YEARLY_FEE,
            fixed_price_chf=Decimal("120.00"),
            valid_from=date(2026, 1, 1),
        )

        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"),
            direction=ReadingDirection.IN,
        )
        MeterReading.objects.create(
            metering_point=self.production_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("6.0"),
            direction=ReadingDirection.OUT,
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 15), date(2026, 1, 31))

        self.assertEqual(invoice.subtotal_chf, Decimal("23.70"))
        categories = {item.description: item.tariff_category for item in invoice.items.all()}
        self.assertEqual(categories["Grid usage fee"], TariffCategory.GRID_FEES)
        self.assertEqual(categories["Federal levy"], TariffCategory.LEVIES)

        fixed_items = {item.description: item for item in invoice.items.filter(unit="month")}
        self.assertEqual(fixed_items["Metering basic fee (1 Monat)"].total_chf, Decimal("12.00"))
        self.assertEqual(fixed_items["Annual admin fee (1 monatliche Rate der Jahresgeb\u00fchr)"].total_chf, Decimal("10.00"))

    def test_fixed_fees_bill_each_touched_month_without_proration(self):
        Tariff.objects.create(
            zev=self.zev,
            name="Monthly service fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.MONTHLY_FEE,
            fixed_price_chf=Decimal("12.00"),
            valid_from=date(2026, 1, 1),
        )
        Tariff.objects.create(
            zev=self.zev,
            name="Annual platform fee",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.YEARLY_FEE,
            fixed_price_chf=Decimal("120.00"),
            valid_from=date(2026, 1, 1),
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 15), date(2026, 2, 14))

        fixed_items = {item.description: item for item in invoice.items.filter(unit="month")}
        self.assertEqual(fixed_items["Monthly service fee (2 Monate)"].total_chf, Decimal("24.00"))
        self.assertEqual(fixed_items["Annual platform fee (2 monatliche Raten der Jahresgeb\u00fchr)"].total_chf, Decimal("20.00"))

    def test_per_metering_point_fees_bill_per_metering_point_month(self):
        Tariff.objects.create(
            zev=self.zev,
            name="Metering operation fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.PER_METERING_POINT_MONTHLY_FEE,
            fixed_price_chf=Decimal("3.00"),
            valid_from=date(2026, 1, 1),
        )
        Tariff.objects.create(
            zev=self.zev,
            name="Metering annual levy",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.PER_METERING_POINT_YEARLY_FEE,
            fixed_price_chf=Decimal("120.00"),
            valid_from=date(2026, 1, 1),
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 15), date(2026, 2, 14))

        fixed_items = {item.description: item for item in invoice.items.filter(unit="month")}
        self.assertEqual(fixed_items["Metering operation fee (4 Messpunkt-Monate)"].total_chf, Decimal("12.00"))
        self.assertEqual(fixed_items["Metering annual levy (4 monatliche Raten pro Messpunkt)"].total_chf, Decimal("40.00"))

    def test_percentage_of_energy_billing_mode(self):
        """
        Percentage-of-energy tariff: effective price per kWh = sum of all GRID
        ENERGY-mode tariffs × (percentage / 100), applied to the tariff's own
        energy_type (here: LOCAL — the primary use-case).

        Setup:
          GRID energy tariffs (3 categories, all BillingMode.ENERGY):
            energy category:   0.25 CHF/kWh  (from setUp)
            grid_fees:          0.05 CHF/kWh
            levies:             0.02 CHF/kWh
          → grid base sum = 0.32 CHF/kWh

          Percentage tariff: 50% of GRID base → effective = 0.16 CHF/kWh
          Applied to: LOCAL energy (energy_type=LOCAL)

          Readings: 10 kWh consumed, 6 kWh produced (same timestamp, sole participant)
            → local = 6 kWh, grid = 4 kWh
          → Percentage item total = 6 × 0.16 = 0.96 CHF
        """
        grid_fee = Tariff.objects.create(
            zev=self.zev,
            name="Grid fee",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(tariff=grid_fee, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal("0.05"))

        levy = Tariff.objects.create(
            zev=self.zev,
            name="Federal levy",
            category=TariffCategory.LEVIES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(tariff=levy, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal("0.02"))

        pct_tariff = Tariff.objects.create(
            zev=self.zev,
            name="Surcharge 50%",
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,  # applies to local kWh, priced as % of GRID base
            percentage=Decimal("50.00"),
            valid_from=date(2026, 1, 1),
        )

        MeterReading.objects.create(
            metering_point=self.consumption_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"),
            direction=ReadingDirection.IN,
        )
        MeterReading.objects.create(
            metering_point=self.production_mp,
            timestamp=datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("6.0"),
            direction=ReadingDirection.OUT,
        )

        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))

        # Find the percentage-of-energy line item
        pct_item = invoice.items.get(description__startswith="Surcharge 50%")
        self.assertEqual(pct_item.description, "Surcharge 50% (50% von CHF 0.32/kWh)")
        self.assertEqual(pct_item.quantity_kwh, Decimal("6.0000"))  # local kWh
        # grid base_sum = 0.25 + 0.05 + 0.02 = 0.32; effective = 0.32 × 0.50 = 0.16
        # total = 6 × 0.16 = 0.96
        self.assertEqual(pct_item.total_chf, Decimal("0.96"))
        self.assertEqual(pct_item.unit, "kWh")
