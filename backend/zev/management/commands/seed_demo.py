"""
Django management command: python manage.py seed_demo

Creates or refreshes an idempotent demo environment with:
- 1 admin account
- 1 ZEV owner account
- 2 participant accounts
- 1 demo ZEV
- 3 metering points (1 production, 2 consumption)
- sample tariffs
- 15-minute metering data for Q1 and Q2 2026
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from math import exp, pi, sin

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from invoices.engine import generate_invoices_for_zev
from invoices.models import Invoice, InvoiceStatus
from metering.models import ImportSource, MeterReading, ReadingDirection, ReadingResolution
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from zev.models import (
    BillingInterval,
    InvoiceLanguage,
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Zev,
    ZevType,
)


UTC = dt_timezone.utc

DEMO_ZEV_NAME = "OpenZEV Demo Community"


def quarter_start(day: date) -> date:
    """First day of the calendar quarter containing ``day``.

    Mirrors ``startOfBillingPeriod`` in the frontend for the quarterly interval
    the demo ZEV uses, so seeded data lines up with the period the UI opens on.
    """
    return date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)


def previous_quarter(day: date) -> tuple[date, date]:
    """Inclusive ``(start, end)`` of the complete quarter before ``day``'s quarter."""
    current_start = quarter_start(day)
    previous_end = current_start - timedelta(days=1)
    return quarter_start(previous_end), previous_end


def years_before(day: date, years: int) -> date:
    """``day`` shifted back whole years, clamping 29 February to the 28th.

    Tariff history is anchored to the seed window's start, which is a quarter
    boundary by default — so the clamp only comes into play for a hand-passed
    ``--start-date`` of 29 February, where ``replace`` would otherwise raise.
    """
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


class Command(BaseCommand):
    help = "Seed the database with a reusable OpenZEV demo environment"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Metering data start date (YYYY-MM-DD). Default: start of the previous quarter.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Metering data end date (YYYY-MM-DD). Default: today.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # Seed relative to today so the period the UI opens on always has data.
        # A fixed window silently goes stale: once today moves past it, the
        # dashboard, charts and invoice pages all render empty.
        today = date.today()
        default_start, _ = previous_quarter(today)

        start_date = date.fromisoformat(options["start_date"]) if options["start_date"] else default_start
        end_date = date.fromisoformat(options["end_date"]) if options["end_date"] else today
        if end_date < start_date:
            raise ValueError("end-date must be on or after start-date.")

        User = get_user_model()

        self._upsert_user(
            User,
            username="admin",
            email="admin@openzev.local",
            password="admin1234",
            role="admin",
            first_name="System",
            last_name="Admin",
            is_superuser=True,
        )
        owner = self._upsert_user(
            User,
            username="demo_owner",
            email="owner@openzev.local",
            password="owner1234",
            role="zev_owner",
            first_name="Paula",
            last_name="Producer",
        )
        participant_one_user = self._upsert_user(
            User,
            username="participant1",
            email="anna.consumer@openzev.local",
            password="participant1234",
            role="participant",
            first_name="Anna",
            last_name="Consumer",
        )
        participant_two_user = self._upsert_user(
            User,
            username="participant2",
            email="ben.consumer@openzev.local",
            password="participant1234",
            role="participant",
            first_name="Ben",
            last_name="Consumer",
        )

        zev, _ = Zev.objects.get_or_create(
            name=DEMO_ZEV_NAME,
            defaults={
                "owner": owner,
                "start_date": start_date,
                "zev_type": ZevType.VZEV,
                "grid_operator": "Stadtwerk Demo AG",
                "grid_connection_point": "CH-DEMO-GRID-0001",
                "billing_interval": BillingInterval.QUARTERLY,
                "invoice_prefix": "OZV",
                "invoice_language": InvoiceLanguage.EN,
                "bank_iban": "CH9300762011623852957",
                "bank_name": "Demo Energy Bank",
                "vat_number": "CHE-123.456.789",
            },
        )
        zev.owner = owner
        zev.start_date = start_date
        zev.zev_type = ZevType.VZEV
        zev.grid_operator = "Stadtwerk Demo AG"
        zev.grid_connection_point = "CH-DEMO-GRID-0001"
        zev.billing_interval = BillingInterval.QUARTERLY
        zev.invoice_prefix = "OZV"
        zev.invoice_language = InvoiceLanguage.EN
        zev.bank_iban = "CH9300762011623852957"
        zev.bank_name = "Demo Energy Bank"
        zev.vat_number = "CHE-123.456.789"
        zev.save()

        owner_participant = self._upsert_participant(
            zev=zev,
            user=owner,
            title=Participant.Title.MS,
            first_name="Paula",
            last_name="Producer",
            email=owner.email,
            phone="+41 31 555 10 10",
            address_line1="Solarweg 1",
            postal_code="3000",
            city="Bern",
            valid_from=start_date,
        )
        participant_one = self._upsert_participant(
            zev=zev,
            user=participant_one_user,
            title=Participant.Title.MS,
            first_name="Anna",
            last_name="Consumer",
            email=participant_one_user.email,
            phone="+41 31 555 20 20",
            address_line1="Aarestrasse 12",
            postal_code="3000",
            city="Bern",
            valid_from=start_date,
        )
        participant_two = self._upsert_participant(
            zev=zev,
            user=participant_two_user,
            title=Participant.Title.MR,
            first_name="Ben",
            last_name="Consumer",
            email=participant_two_user.email,
            phone="+41 31 555 30 30",
            address_line1="Aarestrasse 14",
            postal_code="3000",
            city="Bern",
            valid_from=start_date,
        )

        owner_prod = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-PROD-0001",
            meter_type=MeteringPointType.PRODUCTION,
            location_description="Rooftop PV production meter",
        )
        participant_one_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 1 consumption meter",
        )
        participant_two_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0002",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 2 consumption meter",
        )

        self._ensure_assignment(owner_prod, owner_participant, start_date)
        self._ensure_assignment(participant_one_cons, participant_one, start_date)
        self._ensure_assignment(participant_two_cons, participant_two, start_date)

        self._seed_tariffs(zev, start_date)

        deleted_readings = self._seed_meter_readings(
            start_date=start_date,
            end_date=end_date,
            production_meter=owner_prod,
            consumer_one_meter=participant_one_cons,
            consumer_two_meter=participant_two_cons,
        )

        invoice_period_start, invoice_period_end = previous_quarter(end_date)
        seeded_invoices = self._seed_invoices(zev, invoice_period_start, invoice_period_end)

        production_total = MeterReading.objects.filter(metering_point=owner_prod).aggregate(total=Sum("energy_kwh"))["total"]
        consumption_total = MeterReading.objects.filter(
            metering_point__in=[participant_one_cons, participant_two_cons]
        ).aggregate(total=Sum("energy_kwh"))["total"]

        self.stdout.write(
            self.style.SUCCESS(
                "\n".join(
                    [
                        "",
                        "Demo environment ready.",
                        "",
                        "Frontend: http://localhost:8080",
                        "Backend API: http://localhost:8001/api/v1",
                        "",
                        "Accounts:",
                        "  Admin:         admin@openzev.local / admin1234",
                        "  ZEV owner:     owner@openzev.local / owner1234",
                        "  Participant 1: anna.consumer@openzev.local / participant1234",
                        "  Participant 2: ben.consumer@openzev.local / participant1234",
                        "",
                        f"ZEV: {zev.name}",
                        f"Metering period: {start_date} -> {end_date}",
                        f"Invoice period: {invoice_period_start} -> {invoice_period_end}",
                        f"Tariffs: {zev.tariffs.count()} versions across "
                        f"{zev.tariffs.values('name').distinct().count()} tariffs",
                        f"Invoices created: {len(seeded_invoices)}",
                        f"Deleted existing demo readings: {deleted_readings}",
                        f"Production total: {production_total} kWh",
                        f"Consumption total: {consumption_total} kWh",
                        f"Net export total: {(production_total - consumption_total).quantize(Decimal('0.0001'))} kWh",
                    ]
                )
            )
        )

    def _upsert_user(
        self,
        User,
        *,
        username: str,
        email: str,
        password: str,
        role: str,
        first_name: str,
        last_name: str,
        is_superuser: bool = False,
    ):
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "role": role,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": is_superuser,
                "is_superuser": is_superuser,
                "is_active": True,
            },
        )
        user.email = email
        user.role = role
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.is_staff = is_superuser or user.is_staff
        user.is_superuser = is_superuser or user.is_superuser
        user.must_change_password = False
        user.set_password(password)
        user.save()
        return user

    def _upsert_participant(
        self,
        *,
        zev: Zev,
        user,
        title: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        address_line1: str,
        postal_code: str,
        city: str,
        valid_from: date,
    ) -> Participant:
        participant, _ = Participant.objects.get_or_create(
            zev=zev,
            first_name=first_name,
            last_name=last_name,
            defaults={
                "user": user,
                "title": title,
                "email": email,
                "phone": phone,
                "address_line1": address_line1,
                "postal_code": postal_code,
                "city": city,
                "valid_from": valid_from,
            },
        )
        participant.user = user
        participant.title = title
        participant.email = email
        participant.phone = phone
        participant.address_line1 = address_line1
        participant.postal_code = postal_code
        participant.city = city
        participant.valid_from = valid_from
        participant.valid_to = None
        participant.save()
        return participant

    def _upsert_metering_point(
        self,
        *,
        zev: Zev,
        meter_id: str,
        meter_type: str,
        location_description: str,
    ) -> MeteringPoint:
        meter, _ = MeteringPoint.objects.get_or_create(
            meter_id=meter_id,
            defaults={
                "zev": zev,
                "meter_type": meter_type,
                "is_active": True,
                "location_description": location_description,
            },
        )
        meter.zev = zev
        meter.meter_type = meter_type
        meter.is_active = True
        meter.location_description = location_description
        meter.save()
        return meter

    def _ensure_assignment(self, meter: MeteringPoint, participant: Participant, valid_from: date) -> None:
        # The seed window moves every quarter. Drop the prior open-ended window
        # first so the new one cannot trip the model's non-overlap guard on save.
        with transaction.atomic():
            MeteringPointAssignment.objects.filter(metering_point=meter).delete()
            MeteringPointAssignment.objects.create(
                metering_point=meter,
                participant=participant,
                valid_from=valid_from,
                valid_to=None,
            )

    def _seed_tariffs(self, zev: Zev, valid_from: date) -> None:
        tariff_specs = [
            {
                "name": "Local Solar Energy",
                "category": TariffCategory.ENERGY,
                "billing_mode": BillingMode.ENERGY,
                "energy_type": EnergyType.LOCAL,
                "fixed_price_chf": None,
                "percentage": None,
                "notes": "Base local energy tariff for participant consumption within the ZEV.",
                "periods": [
                    {
                        "period_type": PeriodType.FLAT,
                        "price_chf_per_kwh": Decimal("0.18000"),
                        "time_from": None,
                        "time_to": None,
                        "weekdays": "",
                    }
                ],
                "price_history": [
                    {"prices": [Decimal("0.15000")]},
                    {"prices": [Decimal("0.16500")]},
                ],
            },
            {
                "name": "Grid Energy HT/NT",
                "category": TariffCategory.ENERGY,
                "billing_mode": BillingMode.ENERGY,
                "energy_type": EnergyType.GRID,
                "fixed_price_chf": None,
                "percentage": None,
                "notes": "Sample high and low tariff for imported grid energy.",
                "periods": [
                    {
                        "period_type": PeriodType.HIGH,
                        "price_chf_per_kwh": Decimal("0.29500"),
                        "time_from": time(7, 0),
                        "time_to": time(21, 0),
                        "weekdays": "0,1,2,3,4",
                    },
                    {
                        "period_type": PeriodType.LOW,
                        "price_chf_per_kwh": Decimal("0.22500"),
                        "time_from": None,
                        "time_to": None,
                        "weekdays": "",
                    },
                ],
                # HT and NT both rise, but HT faster, so the chart shows the
                # spread widening (0.050 -> 0.060 -> 0.070) rather than two
                # parallel lines that could just as well be one.
                "price_history": [
                    {"prices": [Decimal("0.24500"), Decimal("0.19500")]},
                    {"prices": [Decimal("0.27000"), Decimal("0.21000")]},
                ],
            },
            {
                "name": "Feed-in Credit",
                "category": TariffCategory.ENERGY,
                "billing_mode": BillingMode.ENERGY,
                "energy_type": EnergyType.FEED_IN,
                "fixed_price_chf": None,
                "percentage": None,
                "notes": "Credit for exported surplus energy.",
                "periods": [
                    {
                        "period_type": PeriodType.FLAT,
                        "price_chf_per_kwh": Decimal("0.08500"),
                        "time_from": None,
                        "time_to": None,
                        "weekdays": "",
                    }
                ],
            },
            {
                "name": "Levies on Grid Energy",
                "category": TariffCategory.LEVIES,
                "billing_mode": BillingMode.PERCENTAGE_OF_ENERGY,
                "energy_type": EnergyType.GRID,
                "fixed_price_chf": None,
                "percentage": Decimal("18.00"),
                "notes": "Sample levy priced as a percentage of the grid base tariff.",
                "periods": [],
                # A percentage version carries no price of its own, so its chart
                # is the *derived* effective price — it moves both when the
                # percentage changes and when the grid tariffs it references do.
                "price_history": [
                    {"percentage": Decimal("15.00")},
                    {"percentage": Decimal("16.50")},
                ],
            },
            {
                "name": "Metering Service Fee",
                "category": TariffCategory.METERING,
                "billing_mode": BillingMode.MONTHLY_FEE,
                "energy_type": None,
                "fixed_price_chf": Decimal("8.50"),
                "percentage": None,
                "notes": "Sample monthly fixed fee per participant invoice.",
                "periods": [],
            },
        ]

        # Rebuild the seeded series rather than upserting into it. A tariff with
        # history is a *timeline*, and the timeline is anchored to a seed window
        # that moves every quarter: an upsert keyed on name alone cannot tell
        # which of several versions it should be updating, and one keyed on
        # (name, valid_from) would leave last quarter's versions behind to
        # collide with this quarter's under the overlap guard. Deleting is safe
        # because nothing references a Tariff — invoice items copy the price and
        # description they were billed at — and filtering on the seeded names
        # leaves any tariff added by hand alone.
        Tariff.objects.filter(zev=zev, name__in=[spec["name"] for spec in tariff_specs]).delete()

        for spec in tariff_specs:
            history = spec.get("price_history", [])

            # Oldest first, one year per historical version, each closed on the
            # day before the next begins so the timeline has no gap. The final
            # version starts at valid_from, stays open-ended, and keeps the
            # spec's own prices — so the seeded invoices bill exactly what they
            # billed before any of this history existed.
            for index, prices in enumerate(history):
                remaining = len(history) - index
                self._create_tariff_version(
                    zev,
                    spec,
                    prices,
                    valid_from=years_before(valid_from, remaining),
                    valid_to=years_before(valid_from, remaining - 1) - timedelta(days=1),
                )

            self._create_tariff_version(zev, spec, {}, valid_from=valid_from, valid_to=None)

    def _create_tariff_version(
        self,
        zev: Zev,
        spec: dict,
        prices: dict,
        valid_from: date,
        valid_to: date | None,
    ) -> Tariff:
        """One version of a seeded tariff.

        ``prices`` overrides just the price-carrying fields; empty means "use the
        spec's own", which is how the current version is built. Historical
        versions reuse the spec's band *structure* — the HT window and weekdays
        rarely change when a price does — and override only the rates.
        """
        tariff = Tariff.objects.create(
            zev=zev,
            name=spec["name"],
            category=spec["category"],
            billing_mode=spec["billing_mode"],
            energy_type=spec["energy_type"],
            fixed_price_chf=prices.get("fixed_price_chf", spec["fixed_price_chf"]),
            percentage=prices.get("percentage", spec["percentage"]),
            notes=spec["notes"],
            valid_from=valid_from,
            valid_to=valid_to,
        )

        band_prices = prices.get("prices")
        for band, period in enumerate(spec["periods"]):
            TariffPeriod.objects.create(
                tariff=tariff,
                period_type=period["period_type"],
                price_chf_per_kwh=band_prices[band] if band_prices else period["price_chf_per_kwh"],
                time_from=period["time_from"],
                time_to=period["time_to"],
                weekdays=period["weekdays"],
            )
        return tariff

    def _seed_invoices(self, zev: Zev, period_start: date, period_end: date) -> list[Invoice]:
        """Generate invoices for the last complete billing period.

        Existing demo invoices are removed first: ``generate_invoice`` refuses to
        overwrite anything past draft, so leaving approved/sent invoices behind
        would make a second ``seed_demo`` run fail.

        Statuses are varied so the invoice list exercises each badge.
        """
        Invoice.objects.filter(zev=zev).delete()

        invoices = generate_invoices_for_zev(zev, period_start, period_end)
        invoices.sort(key=lambda invoice: invoice.invoice_number)

        # First stays DRAFT; the rest advance so the list shows a realistic mix.
        if len(invoices) > 1:
            invoices[1].status = InvoiceStatus.APPROVED
            invoices[1].save(update_fields=["status"])
        if len(invoices) > 2:
            invoices[2].status = InvoiceStatus.SENT
            invoices[2].sent_at = datetime.combine(period_end, time.min, tzinfo=UTC)
            invoices[2].save(update_fields=["status", "sent_at"])

        return invoices

    def _seed_meter_readings(
        self,
        *,
        start_date: date,
        end_date: date,
        production_meter: MeteringPoint,
        consumer_one_meter: MeteringPoint,
        consumer_two_meter: MeteringPoint,
    ) -> int:
        start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
        stop_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)

        deleted, _ = MeterReading.objects.filter(
            metering_point__in=[production_meter, consumer_one_meter, consumer_two_meter],
            timestamp__gte=start_dt,
            timestamp__lt=stop_dt,
        ).delete()

        readings: list[MeterReading] = []
        for timestamp in self._iter_quarters(start_date, end_date):
            day_index = (timestamp.date() - start_date).days
            readings.append(
                MeterReading(
                    metering_point=consumer_one_meter,
                    timestamp=timestamp,
                    energy_kwh=self._consumer_one_kwh(timestamp, day_index),
                    direction=ReadingDirection.IN,
                    resolution=ReadingResolution.FIFTEEN_MIN,
                    import_source=ImportSource.MANUAL,
                )
            )
            readings.append(
                MeterReading(
                    metering_point=consumer_two_meter,
                    timestamp=timestamp,
                    energy_kwh=self._consumer_two_kwh(timestamp, day_index),
                    direction=ReadingDirection.IN,
                    resolution=ReadingResolution.FIFTEEN_MIN,
                    import_source=ImportSource.MANUAL,
                )
            )
            readings.append(
                MeterReading(
                    metering_point=production_meter,
                    timestamp=timestamp,
                    energy_kwh=self._producer_kwh(timestamp, day_index),
                    direction=ReadingDirection.OUT,
                    resolution=ReadingResolution.FIFTEEN_MIN,
                    import_source=ImportSource.MANUAL,
                )
            )

        MeterReading.objects.bulk_create(readings, batch_size=5000)
        return deleted

    def _iter_quarters(self, start_date: date, end_date: date):
        current = datetime.combine(start_date, time.min, tzinfo=UTC)
        stop = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        while current < stop:
            yield current
            current += timedelta(minutes=15)

    def _gaussian(self, value: float, mean: float, sigma: float) -> float:
        return exp(-((value - mean) ** 2) / (2 * sigma**2))

    def _weekend_factor(self, weekday: int) -> float:
        return 1.08 if weekday >= 5 else 1.0

    def _seasonal_solar_factor(self, day_of_year: int) -> float:
        return 0.52 + 0.42 * max(0.0, sin(pi * (day_of_year - 80) / 365.0))

    def _cloud_factor(self, day_index: int) -> float:
        return 0.78 + ((day_index * 17) % 23) / 100.0

    def _consumer_one_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        hour = timestamp.hour + timestamp.minute / 60.0
        weekday = timestamp.weekday()
        base = 0.030
        morning = 0.135 * self._gaussian(hour, 7.2, 1.2)
        midday = (0.020 if weekday < 5 else 0.060) * self._gaussian(hour, 13.0, 2.4)
        evening = 0.190 * self._gaussian(hour, 19.1, 2.1)
        variation = ((day_index % 9) - 4) * 0.0025
        value = (base + morning + midday + evening + variation) * self._weekend_factor(weekday)
        return Decimal(str(round(max(value, 0.006), 4)))

    def _consumer_two_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        hour = timestamp.hour + timestamp.minute / 60.0
        weekday = timestamp.weekday()
        base = 0.025
        morning = 0.105 * self._gaussian(hour, 6.8, 1.0)
        midday = (0.015 if weekday < 5 else 0.045) * self._gaussian(hour, 12.6, 2.0)
        evening = 0.150 * self._gaussian(hour, 18.6, 2.0)
        variation = ((day_index % 11) - 5) * 0.0020
        value = (base + morning + midday + evening + variation) * (1.04 if weekday >= 5 else 0.99)
        return Decimal(str(round(max(value, 0.005), 4)))

    def _producer_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        hour = timestamp.hour + timestamp.minute / 60.0
        daylight_curve = self._gaussian(hour, 13.0, 2.7)
        season = self._seasonal_solar_factor(timestamp.timetuple().tm_yday)
        cloud = self._cloud_factor(day_index)
        shoulder = 0.92 + ((day_index % 7) * 0.018)
        weekend = 1.03 if timestamp.weekday() >= 5 else 1.0
        value = 1.25 * daylight_curve * season * cloud * shoulder * weekend
        return Decimal(str(round(max(value, 0.0), 4)))
