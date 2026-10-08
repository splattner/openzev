"""Supplementary data never reaches billing (ADR 0030)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from invoices.engine import generate_invoice
from metering.models import MeterReading, ReadingDirection, SupplementaryReading, SupplementarySource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing import factories
from zev.models import MeteringPointType

BACKEND = Path(__file__).resolve().parent.parent

# The invoice engine and everything that renders an invoice, plus allocation and tariffs.
BILLING_FILES = [
    BACKEND / "invoices" / name
    for name in (
        "engine.py",
        "financial_summary.py",
        "tariff_pricing.py",
        "template_context.py",
    )
] + sorted((BACKEND / "invoices").glob("pdf*.py"))
BILLING_PACKAGES = [BACKEND / "allocation", BACKEND / "tariffs"]


def _billing_sources():
    files = list(BILLING_FILES)
    for package in BILLING_PACKAGES:
        files.extend(
            path for path in package.rglob("*.py")
            if "migrations" not in path.parts and not path.name.startswith("test")
        )
    return files


class SupplementaryIsolationTests(SimpleTestCase):
    def test_billing_modules_do_not_mention_supplementary_data(self):
        files = _billing_sources()
        self.assertGreater(len(files), 20, "the billing source list looks empty")
        offenders = [
            str(path.relative_to(BACKEND))
            for path in files
            if "supplementary" in path.read_text(encoding="utf-8").lower()
        ]
        self.assertEqual(
            offenders, [],
            "Billing code must not read supplementary energy data (ADR 0030). "
            "Statistics read it through metering.supplementary.stats only.",
        )

    def test_the_billing_source_list_covers_the_known_modules(self):
        names = {path.name for path in _billing_sources()}
        self.assertTrue({"engine.py", "split.py", "pdf.py", "tariff_pricing.py"} <= names)


class InvoiceInvariantTests(TestCase):
    """Invoices come out identical with and without supplementary data."""

    def setUp(self):
        self.zev = factories.ZevFactory()
        self.participant = factories.ParticipantFactory(zev=self.zev, valid_from=date(2026, 1, 1))
        self.point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.participant, valid_from=date(2026, 1, 1)
        )
        for energy_type, price in ((EnergyType.LOCAL, "0.15"), (EnergyType.GRID, "0.25"), (EnergyType.FEED_IN, "0.08")):
            tariff = Tariff.objects.create(
                zev=self.zev, name=f"{energy_type} tariff", category=TariffCategory.ENERGY,
                billing_mode=BillingMode.ENERGY, energy_type=energy_type, valid_from=date(2026, 1, 1),
            )
            TariffPeriod.objects.create(tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal(price))
        for i in range(8):
            ts = datetime(2026, 1, 15, 10, tzinfo=timezone.utc) + timedelta(minutes=15 * i)
            MeterReading.objects.create(
                metering_point=self.point, timestamp=ts, energy_kwh=Decimal("0.5"), direction=ReadingDirection.IN
            )
            MeterReading.objects.create(
                metering_point=self.point, timestamp=ts, energy_kwh=Decimal("1.5"), direction=ReadingDirection.OUT
            )

    def snapshot(self):
        invoice = generate_invoice(self.participant, date(2026, 1, 1), date(2026, 1, 31))
        items = sorted(
            (item.description, item.quantity_kwh, item.unit_price_chf, item.total_chf)
            for item in invoice.items.all()
        )
        return (
            invoice.total_local_kwh, invoice.total_grid_kwh, invoice.total_feed_in_kwh,
            invoice.subtotal_chf, invoice.vat_chf, invoice.total_chf, items,
        )

    def test_invoice_amounts_identical_with_and_without_supplementary_data(self):
        before = self.snapshot()

        source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.participant, provider="push",
            covers_from=datetime(2026, 1, 15, tzinfo=timezone.utc),
            synced_through=datetime(2026, 1, 16, tzinfo=timezone.utc),
        )
        for i in range(96):
            SupplementaryReading.objects.create(
                source=source, metering_point=self.point,
                timestamp=datetime(2026, 1, 15, tzinfo=timezone.utc) + timedelta(minutes=15 * i),
                consumption_kwh=Decimal("9.9"), production_kwh=Decimal("99.9"),
                import_kwh=Decimal("0.1"), export_kwh=Decimal("9.9"),
            )

        self.assertEqual(self.snapshot(), before)

    def test_ingest_never_touches_meter_readings(self):
        count = MeterReading.objects.count()
        source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.participant, provider="push"
        )
        SupplementaryReading.objects.create(
            source=source, metering_point=self.point,
            timestamp=datetime(2026, 1, 15, 10, tzinfo=timezone.utc),
            consumption_kwh=1, production_kwh=1, import_kwh=0, export_kwh=0,
        )
        self.assertEqual(MeterReading.objects.count(), count)
