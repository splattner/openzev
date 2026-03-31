"""
Django management command: python manage.py generate_metering_data

Generates realistic sample metering data for a given metering point.

Examples:
  # 30 days of consumption at 15-min intervals
  python manage.py generate_metering_data MP_UUID consumption \
      --start 2026-01-01 --days 30 --interval 15min

  # 90 days of production (solar) at hourly intervals
  python manage.py generate_metering_data MP_UUID production \
      --start 2026-01-01 --days 90 --interval hourly

  # 60 days of bidirectional data at 15-min intervals (net metering auto-enabled)
  python manage.py generate_metering_data MP_UUID bidirectional \
      --start 2026-01-01 --days 60 --interval 15min

  # Consumption meter behind a solar system (grid connection meter)
  python manage.py generate_metering_data MP_UUID consumption \
      --start 2026-01-01 --days 30 --net-metering
"""
import math
import random
import uuid
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from metering.models import MeterReading, ReadingDirection
from zev.models import MeteringPoint


INTERVAL_MINUTES = {
    "15min": 15,
    "hourly": 60,
}


def _solar_factor(hour: float, day_of_year: int) -> float:
    """Realistic solar production curve: bell-shaped around noon, seasonal."""
    if hour < 6 or hour > 20:
        return 0.0
    # Bell curve peaking at 13:00 (solar noon offset)
    peak_hour = 13.0
    spread = 3.5
    bell = math.exp(-((hour - peak_hour) ** 2) / (2 * spread**2))
    # Seasonal factor: higher in summer (day ~172), lower in winter (day ~355/0)
    seasonal = 0.4 + 0.6 * max(0, math.sin(math.pi * (day_of_year - 80) / 365))
    # Random cloud variance
    cloud = random.uniform(0.6, 1.0)
    return bell * seasonal * cloud


def _consumption_factor(hour: float, weekday: int) -> float:
    """
    Realistic household consumption curve.
    Morning and evening peaks, lower overnight and midday.
    Weekend has a slightly different pattern (more midday usage).
    """
    # Base overnight (low)
    base = 0.15
    if weekday >= 5:  # weekend
        if 8 <= hour < 12:
            base = 0.5 + 0.3 * math.sin(math.pi * (hour - 8) / 4)
        elif 12 <= hour < 14:
            base = 0.6
        elif 17 <= hour < 21:
            base = 0.7 + 0.2 * math.sin(math.pi * (hour - 17) / 4)
        elif 6 <= hour < 8:
            base = 0.3
    else:  # weekday
        if 6 <= hour < 9:
            base = 0.5 + 0.3 * math.sin(math.pi * (hour - 6) / 3)
        elif 9 <= hour < 17:
            base = 0.2
        elif 17 <= hour < 22:
            base = 0.6 + 0.3 * math.sin(math.pi * (hour - 17) / 5)

    # Random household variance
    return base * random.uniform(0.7, 1.3)


class Command(BaseCommand):
    help = "Generate realistic sample metering data for a metering point"

    def add_arguments(self, parser):
        parser.add_argument(
            "meter_id",
            type=str,
            help="Meter ID (e.g. CH1234567890120000000006666665030) or UUID of the metering point",
        )
        parser.add_argument(
            "type",
            type=str,
            choices=["consumption", "production", "bidirectional"],
            help="Type of data to generate",
        )
        parser.add_argument(
            "--start",
            type=str,
            required=True,
            help="Start date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--days",
            type=int,
            required=True,
            help="Number of days to generate",
        )
        parser.add_argument(
            "--interval",
            type=str,
            choices=list(INTERVAL_MINUTES.keys()),
            default="15min",
            help="Measurement interval (default: 15min)",
        )
        parser.add_argument(
            "--peak-kwh",
            type=float,
            default=None,
            help="Peak kWh per interval (default: auto-scaled based on type and interval)",
        )
        parser.add_argument(
            "--net-metering",
            action="store_true",
            help="Simulate grid connection meter: local production offsets consumption. "
                 "Automatically enabled for bidirectional type.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print statistics without writing to DB",
        )

    def handle(self, *args, **options):
        meter_id = options["meter_id"]
        data_type = options["type"]
        interval = options["interval"]
        days = options["days"]
        dry_run = options["dry_run"]
        net_metering = options["net_metering"] or data_type == "bidirectional"

        try:
            mp = MeteringPoint.objects.get(meter_id=meter_id)
        except MeteringPoint.DoesNotExist:
            try:
                mp = MeteringPoint.objects.get(id=meter_id)
            except (MeteringPoint.DoesNotExist, ValueError):
                raise CommandError(f"Metering point '{meter_id}' not found.")

        try:
            start_dt = datetime.strptime(options["start"], "%Y-%m-%d").replace(tzinfo=tz.utc)
        except ValueError:
            raise CommandError("Invalid date format. Use YYYY-MM-DD.")

        interval_min = INTERVAL_MINUTES[interval]
        resolution = "QH" if interval_min == 15 else "hourly"
        end_dt = start_dt + timedelta(days=days)
        delta = timedelta(minutes=interval_min)

        # Auto-scale peak kWh based on interval duration
        # For a typical household: ~4000 kWh/year consumption, ~8 kWp solar
        interval_hours = interval_min / 60
        if options["peak_kwh"] is not None:
            peak_cons = options["peak_kwh"]
            peak_prod = options["peak_kwh"]
        else:
            # ~0.8 kWh peak per hour for consumption, ~6 kWh peak per hour for production (8kWp system)
            peak_cons = 0.8 * interval_hours
            peak_prod = 6.0 * interval_hours

        import_batch = uuid.uuid4()
        readings = []
        directions = []

        if data_type == "consumption":
            directions = [ReadingDirection.IN]
        elif data_type == "production":
            directions = [ReadingDirection.OUT]
        else:  # bidirectional
            directions = [ReadingDirection.IN, ReadingDirection.OUT]

        current = start_dt
        total_in = Decimal("0")
        total_out = Decimal("0")
        count = 0

        while current < end_dt:
            hour = current.hour + current.minute / 60.0
            weekday = current.weekday()
            day_of_year = current.timetuple().tm_yday

            if net_metering:
                # Simulate grid connection meter: compute net = consumption - production
                gross_cons = peak_cons * _consumption_factor(hour, weekday)
                gross_prod = peak_prod * _solar_factor(hour, day_of_year)
                net = gross_cons - gross_prod

                for direction in directions:
                    if direction == ReadingDirection.IN:
                        kwh = Decimal(str(round(max(0, net), 4)))
                    else:
                        kwh = Decimal(str(round(max(0, -net), 4)))

                    readings.append(MeterReading(
                        metering_point=mp,
                        timestamp=current,
                        energy_kwh=kwh,
                        direction=direction,
                        resolution=resolution,
                        import_source="manual",
                        import_batch=import_batch,
                    ))

                    if direction == ReadingDirection.IN:
                        total_in += kwh
                    else:
                        total_out += kwh
                    count += 1
            else:
                for direction in directions:
                    if direction == ReadingDirection.IN:
                        factor = _consumption_factor(hour, weekday)
                        kwh = Decimal(str(round(peak_cons * factor, 4)))
                    else:
                        factor = _solar_factor(hour, day_of_year)
                        kwh = Decimal(str(round(peak_prod * factor, 4)))

                    if kwh <= 0:
                        kwh = Decimal("0.0000")

                    readings.append(MeterReading(
                        metering_point=mp,
                        timestamp=current,
                        energy_kwh=kwh,
                        direction=direction,
                        resolution=resolution,
                        import_source="manual",
                        import_batch=import_batch,
                    ))

                    if direction == ReadingDirection.IN:
                        total_in += kwh
                    else:
                        total_out += kwh
                    count += 1

            current += delta

        self.stdout.write(f"\nMetering point: {mp.meter_id} ({mp.id})")
        self.stdout.write(f"Type: {data_type}" + (" (net metering)" if net_metering else ""))
        self.stdout.write(f"Period: {start_dt.date()} → {end_dt.date()} ({days} days)")
        self.stdout.write(f"Interval: {interval} ({interval_min} min)")
        self.stdout.write(f"Readings to create: {count}")
        if total_in > 0:
            self.stdout.write(f"Total consumption: {total_in:.2f} kWh ({float(total_in) / days:.1f} kWh/day avg)")
        if total_out > 0:
            self.stdout.write(f"Total production:  {total_out:.2f} kWh ({float(total_out) / days:.1f} kWh/day avg)")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run: no data written."))
            return

        with transaction.atomic():
            MeterReading.objects.bulk_create(readings, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(f"\n✓ Created {count} readings (batch {import_batch})"))
