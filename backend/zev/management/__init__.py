"""
Django management command: python manage.py seed_demo

Creates a full demo ZEV environment with:
- Admin, ZEV owner, and participant user accounts
- A sample ZEV with 3 participants
- Metering points (consumption + production)
- Tariff definitions (local, grid, feed-in)
- Sample meter readings for Q1 2026
"""
from datetime import date, datetime, timedelta, timezone as tz
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User, UserRole
from zev.models import Zev, Participant, MeteringPoint, MeteringPointAssignment, MeteringPointType
from tariffs.models import Tariff, TariffPeriod, EnergyType, PeriodType
from metering.models import MeterReading, ReadingDirection


class Command(BaseCommand):
    help = "Seed the database with demo data for development and testing"

    @transaction.atomic
    def handle(self, *args, **options):
        verbosity = options.get("verbosity", 1)

        # ─── Create users ────────────────────────────────────────────────
        admin = User.objects.filter(username="admin").first()
        if not admin:
            admin = User.objects.create_superuser(
                username="admin",
                email="admin@openzev.local",
                password="admin1234",
                role=UserRole.ADMIN,
            )
            if verbosity >= 1:
                self.stdout.write(f"✓ Created admin: {admin.username}")

        owner = User.objects.filter(username="zev_owner").first()
        if not owner:
            owner = User.objects.create_user(
                username="zev_owner",
                email="owner@openzev.local",
                password="owner1234",
                role=UserRole.ZEV_OWNER,
                first_name="Jane",
                last_name="Owner",
            )
            if verbosity >= 1:
                self.stdout.write(f"✓ Created ZEV owner: {owner.username}")

        puser_alice = User.objects.filter(username="alice").first()
        if not puser_alice:
            puser_alice = User.objects.create_user(
                username="alice",
                email="alice@example.com",
                password="alice1234",
                role=UserRole.PARTICIPANT,
                first_name="Alice",
                last_name="Muster",
            )
            if verbosity >= 1:
                self.stdout.write(f"✓ Created participant: {puser_alice.username}")

        puser_bob = User.objects.filter(username="bob").first()
        if not puser_bob:
            puser_bob = User.objects.create_user(
                username="bob",
                email="bob@example.com",
                password="bob1234",
                role=UserRole.PARTICIPANT,
                first_name="Bob",
                last_name="Müller",
            )
            if verbosity >= 1:
                self.stdout.write(f"✓ Created participant: {puser_bob.username}")

        # ─── Create ZEV ──────────────────────────────────────────────────
        zev = Zev.objects.filter(name="Demo ZEV").first()
        if not zev:
            zev = Zev.objects.create(
                name="Demo ZEV",
                owner=owner,
                zev_type="vzev",
                grid_operator="Elektra Demo AG",
                city="Bern",
                postal_code="3011",
                invoice_prefix="DEMO",
                bank_iban="CH9300762011623852957",
                bank_name="Demo Bank",
                vat_number="CHE-123.456.789",
                billing_interval="monthly",
            )
            if verbosity >= 1:
                self.stdout.write(f"✓ Created ZEV: {zev.name}")

        # ─── Create participants ─────────────────────────────────────────
        participants = []
        for data in [
            ("Alice Muster", puser_alice, "MP-A-001"),
            ("Bob Müller", puser_bob, "MP-B-001"),
            ("Charlie Nächster", None, "MP-C-001"),
        ]:
            name, user, meter_base = data
            first, last = name.split(" ")
            p = Participant.objects.filter(zev=zev, first_name=first, last_name=last).first()
            if not p:
                p = Participant.objects.create(
                    zev=zev,
                    user=user,
                    title=Participant.Title.MR,
                    first_name=first,
                    last_name=last,
                    email=f"{first.lower()}@example.com",
                    postal_code="3011",
                    city="Bern",
                    valid_from=date(2026, 1, 1),
                )
                if verbosity >= 1:
                    self.stdout.write(f"✓ Created participant: {p.full_name}")
            participants.append((p, meter_base))

        # ─── Create metering points ──────────────────────────────────────
        metering_points = {}
        for p, meter_base in participants:
            for kind, mp_type in [("C", MeteringPointType.CONSUMPTION), ("P", MeteringPointType.PRODUCTION)]:
                mp = MeteringPoint.objects.filter(
                    zev=zev, meter_id=f"{meter_base}-{kind}"
                ).first()
                if not mp:
                    mp = MeteringPoint.objects.create(
                        zev=zev,
                        meter_id=f"{meter_base}-{kind}",
                        meter_type=mp_type,
                        is_active=True,
                    )
                    if verbosity >= 1:
                        self.stdout.write(f"  → Created metering point: {mp.meter_id}")
                MeteringPointAssignment.objects.get_or_create(
                    metering_point=mp,
                    participant=p,
                    valid_from=date(2026, 1, 1),
                    defaults={"valid_to": None},
                )
                metering_points[(p, kind)] = mp

        # ─── Create tariffs ──────────────────────────────────────────────
        tariffs = {}
        for energy_type, label in [
            (EnergyType.LOCAL, "Solar (Local)"),
            (EnergyType.GRID, "Grid Energy"),
            (EnergyType.FEED_IN, "Feed-in Credit"),
        ]:
            t = Tariff.objects.filter(zev=zev, energy_type=energy_type).first()
            if not t:
                t = Tariff.objects.create(
                    zev=zev,
                    name=label,
                    energy_type=energy_type,
                    valid_from=date(2026, 1, 1),
                )
                if verbosity >= 1:
                    self.stdout.write(f"✓ Created tariff: {t.name}")

                # Create tariff periods
                prices = {
                    EnergyType.LOCAL: Decimal("0.15"),
                    EnergyType.GRID: Decimal("0.28"),
                    EnergyType.FEED_IN: Decimal("0.09"),
                }
                TariffPeriod.objects.create(
                    tariff=t,
                    period_type=PeriodType.FLAT,
                    price_chf_per_kwh=prices[energy_type],
                )
            tariffs[energy_type] = t

        # ─── Create sample meter readings for Q1 2026 ────────────────────
        readings_created = 0
        base_date = datetime(2026, 1, 1, tzinfo=tz.utc)
        for day_offset in range(90):  # 90 days = Jan, Feb, Mar
            ts = base_date + timedelta(days=day_offset)

            for p, meter_base in participants:
                # Consumption: 15-30 kWh/day, variable pattern
                consumption = 15 + 10 * ((day_offset % 7) / 7)
                mp_c = metering_points[(p, "C")]
                try:
                    MeterReading.objects.create(
                        metering_point=mp_c,
                        timestamp=ts,
                        energy_kwh=Decimal(str(round(consumption, 2))),
                        direction=ReadingDirection.IN,
                        resolution="daily",
                        import_source="manual",
                    )
                    readings_created += 1
                except Exception:
                    pass  # Silently skip duplicates

                # Production: 12-25 kWh/day, variable + seasonal pattern
                day_season = (day_offset / 90)  # 0 = Jan, 1 = Mar
                production = (12 + 8 * day_season) * (0.8 + 0.4 * ((day_offset % 7) / 7))
                mp_p = metering_points[(p, "P")]
                try:
                    MeterReading.objects.create(
                        metering_point=mp_p,
                        timestamp=ts,
                        energy_kwh=Decimal(str(round(production, 2))),
                        direction=ReadingDirection.OUT,
                        resolution="daily",
                        import_source="manual",
                    )
                    readings_created += 1
                except Exception:
                    pass  # Silently skip duplicates

        if verbosity >= 1:
            self.stdout.write(f"✓ Created {readings_created} meter readings")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Demo data seeded successfully!\n\n"
                f"Admin account: admin / admin1234\n"
                f"Owner account: zev_owner / owner1234\n"
                f"Participant (Alice): alice / alice1234\n"
                f"Participant (Bob): bob / bob1234\n"
            )
        )
