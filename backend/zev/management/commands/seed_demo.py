"""python manage.py seed_demo — idempotent demo environment.

Two communities owned by one demo owner (flagship STWEG + company ZEV),
accounts (including a viewer and a property manager with per-ZEV access), meters, readings, tariffs, invoices in every status, and
operational history (import/email logs, contracts, audit events), plus personas
for the per-ZEV access and party model (#761). See the README for the full list
and the demo login credentials.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from math import exp, pi, sin
from typing import Callable, NamedTuple

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum

from accounts.models import FeatureFlag, VatRate
from allocation.validity import active_during, business_tz, civil_date, period_start_dt, period_window, wall_clock
from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
from audit.services import record_audit_event
from invoices.contract_pdf import issue_contract_pdf
from invoices.engine import generate_invoices_for_zev
from invoices.models import (
    DEFAULT_INVOICE_EMAIL_SUBJECT,
    ContractIssue,
    EmailLog,
    Invoice,
    InvoiceStatus,
)
from invoices.pdf import save_invoice_pdf
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection, ReadingResolution
from tariffs.dynamic.models import DynamicApiVersion, DynamicTariffSource, DynamicTariffType, FetchStatus
from tariffs.dynamic.storage import store_points
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from zev.models import (
    AllocationMode,
    BillingInterval,
    InvoiceLanguage,
    Building,
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Party,
    PartyKind,
    PartyRole,
    VatMode,
    Zev,
    ZevAccessGrant,
    ZevAccessRole,
    ZevPartyRole,
    ZevType,
)
from zev.buildings import ensure_initial_building
from zev.parties import assign_role, ensure_initial_roles
from zev.services import issue_invitation



# The tail of the seed window keeps 15-minute rows (see ``_seed_meter_readings``);
# everything older is hourly so the dataset stays small enough to re-seed fast.
FINE_READING_DAYS = 14

DEMO_ZEV_NAME = "ZEV STWEG Sonnenhof"
# The flagship demo community: a classic Swiss condominium (STWEG) on one
# building with rooftop PV, apartments and a shared common-area meter. German
# invoices, VAT folded into prices (a STWEG is not VAT-registered), ``zev``
# type. Superseded names this community may still carry in older databases.
DEMO_ZEV_LEGACY_NAME = "OpenZEV Demo Community"

SECOND_DEMO_ZEV_NAME = "ZEV Sonnenfirma AG"
# The second, smaller community: a property-company (AG) site that invoices in
# English, is VAT-registered (UID shown) and runs as a ``vzev`` — the
# counterpart that makes the community switcher show two different setups.

DEMO_DYNAMIC_TARIFF_NAME = "Netznutzung dynamisch"
DEMO_DYNAMIC_SOURCE_LABEL = "Demo – dynamische Netznutzung (synthetisch)"
DEMO_DYNAMIC_SOURCE_URL = "https://dynamic-tariffs.openzev.invalid/v2/tariffs"

# One hourly ``(timestamp, day_index) -> energy_kwh`` curve per meter kind;
# the second community reuses these shapes at different amplitudes.
Profile = Callable[[datetime, int], Decimal]


class SecondCommunitySeed(NamedTuple):
    """What ``_seed_second_community`` produced: the open month and the closed one before it."""

    open_invoices: list[Invoice]
    open_start: date
    open_end: date
    closed_invoices: list[Invoice]
    closed_start: date
    closed_end: date

# ZEV-level email overrides so the ZEV settings page shows real ones: the
# STWEG invoices in German, the company in English.
DEMO_EMAIL_SUBJECT = "Rechnung {invoice_number} – {zev_name}"
DEMO_EMAIL_BODY = (
    "Guten Tag {participant_name},\n\n"
    "Im Anhang finden Sie Ihre Energierechnung für den Zeitraum "
    "{period_start} bis {period_end}.\n\n"
    "Total: CHF {total_chf}\n\n"
    "Freundliche Grüsse,\n{zev_name}"
)
SECOND_DEMO_EMAIL_SUBJECT = "Invoice {invoice_number} – {zev_name}"
SECOND_DEMO_EMAIL_BODY = (
    "Dear {participant_name},\n\n"
    "Please find attached your energy invoice for the period "
    "{period_start} to {period_end}.\n\n"
    "Total: CHF {total_chf}\n\n"
    "Kind regards,\n{zev_name}"
)

# Contract-PDF filler: German for the STWEG, English for the company, so the
# notes sections never render blank.
DEMO_LOCAL_TARIFF_NOTES = (
    "Der lokale Solarstrom wird zu der jeweils gültigen Tariftabelle der "
    "Gemeinschaft abgerechnet. Die Tabelle wird von der Verwaltung jährlich "
    "festgelegt und den Mitgliedern vor Beginn des Abrechnungsjahres "
    "mitgeteilt; Netzbezug wird zum Selbstkostenpreis weitergegeben."
)
DEMO_ADDITIONAL_CONTRACT_NOTES = (
    "Die Mitgliedschaft besteht auf unbestimmte Zeit. Die Kündigung erfolgt "
    "schriftlich mit dreimonatiger Frist auf Ende eines Kalenderquartals. "
    "Aufnahmegebühren und Anschlusskosten richten sich nach dem Reglement "
    "der Gemeinschaft."
)
SECOND_DEMO_LOCAL_TARIFF_NOTES = (
    "Local solar energy is billed at the current community tariff table. The "
    "table is reviewed annually and published to all tenants before the "
    "start of the billing year; grid purchases are passed through at cost."
)
SECOND_DEMO_ADDITIONAL_CONTRACT_NOTES = (
    "Supply agreements run for an indefinite term. Termination requires "
    "three months' written notice to the end of a calendar quarter."
)

# The second community's tariff set: energy and feed-in tariffs, a percentage
# levy, a shared connection fee the engine splits across active participants,
# and a fee per metering point. ``itemize_tariff_bands`` is enabled on that
# ZEV, so the HT/NT grid tariff prints as two invoice lines. Only the fields
# that differ from the model defaults are written out; ``_create_tariff_version``
# supplies the rest.
SECOND_DEMO_TARIFF_SPECS = [
    {
        "name": "Local Solar Energy",
        "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY,
        "energy_type": EnergyType.LOCAL,
        "notes": "Local energy tariff for the second demo community.",
        "periods": [
            {
                "period_type": PeriodType.FLAT,
                "price_chf_per_kwh": Decimal("0.16000"),
            }
        ],
    },
    {
        "name": "Grid Energy HT/NT",
        "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY,
        "energy_type": EnergyType.GRID,
        "notes": "High and low tariff for imported grid energy.",
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
            },
        ],
    },
    {
        "name": "Feed-in Credit",
        "category": TariffCategory.ENERGY,
        "billing_mode": BillingMode.ENERGY,
        "energy_type": EnergyType.FEED_IN,
        "notes": "Credit for exported surplus energy.",
        "periods": [
            {
                "period_type": PeriodType.FLAT,
                "price_chf_per_kwh": Decimal("0.08000"),
            }
        ],
    },
    {
        "name": "Levies on Grid Energy",
        "category": TariffCategory.LEVIES,
        "billing_mode": BillingMode.PERCENTAGE_OF_ENERGY,
        "energy_type": EnergyType.GRID,
        "notes": "Levy priced as a percentage of the grid base tariff.",
        "periods": [
            {
                "period_type": PeriodType.FLAT,
                "percentage": Decimal("18.00"),
            }
        ],
    },
    {
        "name": "Grid Connection Fee",
        "category": TariffCategory.METERING,
        "billing_mode": BillingMode.SHARED_MONTHLY_FEE,
        "fixed_price_chf": Decimal("54.00"),
        "notes": "Connection fee billed to the community as one amount and split "
        "equally across the participants active in the month.",
        "periods": [],
    },
    {
        "name": "Metering per Point",
        "category": TariffCategory.METERING,
        "billing_mode": BillingMode.PER_METERING_POINT_MONTHLY_FEE,
        "fixed_price_chf": Decimal("4.80"),
        "notes": "Monthly metering fee per assigned metering point.",
        "periods": [],
    },
]


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


def previous_month(day: date) -> tuple[date, date]:
    """Inclusive ``(start, end)`` of the complete calendar month before ``day``'s month.

    The second community bills monthly, so its seeded invoices line up with
    the month the UI opens on for a monthly-interval ZEV.
    """
    month_start = day.replace(day=1)
    previous_end = month_start - timedelta(days=1)
    return previous_end.replace(day=1), previous_end


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
            help="Metering data start date (YYYY-MM-DD). Default: start of the quarter before the end date.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Metering data end date (YYYY-MM-DD). Default: today.",
        )

    def _parse_option_date(self, value, label: str) -> date | None:
        """Parse a ``--start-date`` / ``--end-date`` value or ``None``."""
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            raise CommandError(f"--{label} expects YYYY-MM-DD, got {value!r}.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo creates demo users with known passwords and is only available when DEBUG=True.")
        # Seed relative to today so the period the UI opens on always has data.
        # A fixed window silently goes stale: once today moves past it, the
        # dashboard, charts and invoice pages all render empty.
        today = date.today()
        # Resolve the end date first: the default start is the start of the
        # quarter before it, so seeding with ``--end-date`` alone lands on the
        # billing period that precedes that end instead of one derived from
        # today (which can fall *after* the requested end and error out).
        end_date = self._parse_option_date(options["end_date"], "end-date") or today
        default_start, _ = previous_quarter(end_date)
        start_date = self._parse_option_date(options["start_date"], "start-date") or default_start
        if end_date < start_date:
            raise CommandError("end-date must be on or after start-date.")

        # The main community is treated as if it existed for the whole previous
        # calendar year: participants, meters and assignments are valid from
        # then on, and hourly readings cover the year up to the seed window, so
        # the reports pages (annual statements, financial summary) have a
        # complete year to render instead of one quarter.
        history_start = date(end_date.year - 1, 1, 1)
        main_valid_from = min(history_start, start_date)

        User = get_user_model()

        admin = self._upsert_user(
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
            role="user",
            first_name="Paula",
            last_name="Producer",
        )
        participant_one_user = self._upsert_user(
            User,
            username="participant1",
            email="anna@openzev.local",
            password="anna1234",
            role="user",
            first_name="Anna",
            last_name="Consumer",
        )
        participant_two_user = self._upsert_user(
            User,
            username="participant2",
            email="ben@openzev.local",
            password="ben1234",
            role="user",
            first_name="Ben",
            last_name="Consumer",
        )
        # A member of the *second* community logs in with her own account, so
        # the participant-side view (no switcher, everything scoped to her
        # ZEV) can be demoed on both communities.
        second_participant_user = self._upsert_user(
            User,
            username="participant3",
            email="clara@openzev.local",
            password="clara1234",
            role="user",
            first_name="Clara",
            last_name="Müller",
        )

        # Databases seeded under the superseded flagship name (the name the
        # base branch shipped) are renamed first, so ``_upsert_zev`` below
        # refreshes that row instead of creating a second ZEV under the
        # current name. Only the demo owner's rows are touched: a tenant who
        # happens to carry the same display name must not lose their ZEV.
        self._migrate_legacy_demo_zev_names(owner=owner)

        # The flagship community is the STWEG: a single-building ``zev`` that
        # invoices quarterly in German and folds VAT into its prices (it is
        # not VAT-registered). It is treated as if it existed from the start of
        # its history — the participants, meters and readings all begin there,
        # and so does the community itself. The second community is the
        # property company — a ``vzev`` that invoices monthly in English and
        # is VAT-registered, so its invoices show the UID and a separate VAT
        # line.
        zev = self._upsert_zev(
            owner=owner,
            name=DEMO_ZEV_NAME,
            zev_type=ZevType.ZEV,
            start_date=main_valid_from,
            grid_operator="Stadtwerk Demo AG",
            grid_connection_point="CH-DEMO-GRID-0001",
            billing_interval=BillingInterval.QUARTERLY,
            invoice_prefix="OZV",
            invoice_language=InvoiceLanguage.DE,
            bank_iban="CH9300762011623852957",
            bank_name="Demo Energy Bank",
            vat_mode=VatMode.INCLUSIVE,
            vat_number="",
            email_subject_template=DEMO_EMAIL_SUBJECT,
            email_body_template=DEMO_EMAIL_BODY,
            tariff_source_url=f"https://www.stadtwerk-demo.ch/stromtarife/{end_date.year}.xml",
            local_tariff_notes=DEMO_LOCAL_TARIFF_NOTES,
            additional_contract_notes=DEMO_ADDITIONAL_CONTRACT_NOTES,
        )

        second_zev = self._upsert_zev(
            owner=owner,
            name=SECOND_DEMO_ZEV_NAME,
            zev_type=ZevType.VZEV,
            start_date=start_date,
            grid_operator="Stadtwerk Demo AG",
            grid_connection_point="CH-DEMO-GRID-0002",
            billing_interval=BillingInterval.MONTHLY,
            invoice_prefix="OZ2",
            invoice_language=InvoiceLanguage.EN,
            bank_iban="CH4431999123000889012",
            bank_name="Demo Energy Bank",
            vat_mode=VatMode.REGISTERED,
            vat_number="CHE-987.654.321",
            itemize_tariff_bands=True,
            email_subject_template=SECOND_DEMO_EMAIL_SUBJECT,
            email_body_template=SECOND_DEMO_EMAIL_BODY,
            local_tariff_notes=SECOND_DEMO_LOCAL_TARIFF_NOTES,
            additional_contract_notes=SECOND_DEMO_ADDITIONAL_CONTRACT_NOTES,
        )

        # Per-ZEV access (#761): a viewer of the flagship community, and a
        # property manager (Verwaltung) who manages both communities — the
        # switcher lists both with their relation. Neither is a participant,
        # so billing data is unaffected. The Verwaltung manages the flagship
        # through its representative role (below), the second one by grant.
        viewer = self._upsert_user(
            User,
            username="demo_viewer",
            email="viewer@openzev.local",
            password="viewer1234",
            role="user",
            first_name="Vera",
            last_name="Viewer",
        )
        property_manager = self._upsert_user(
            User,
            username="demo_manager",
            email="manager@openzev.local",
            password="manager1234",
            role="user",
            first_name="Marco",
            last_name="Verwaltung",
        )
        self._upsert_grant(zev=zev, user=viewer, role=ZevAccessRole.VIEWER, granted_by=owner)
        ZevAccessGrant.objects.filter(zev=zev, user=property_manager).delete()
        self._upsert_grant(zev=second_zev, user=property_manager, role=ZevAccessRole.MANAGER, granted_by=owner)

        # Access and party personas (#761); the README lists what each shows.
        former_user = self._upsert_user(
            User,
            username="demo_former",
            email="former@openzev.local",
            password="former1234",
            role="user",
            first_name="Maria Alexandra Elisabeth",
            last_name="von Sonnenberg-Musterlingen",
        )
        household_user = self._upsert_user(
            User,
            username="demo_household",
            email="household@openzev.local",
            password="household1234",
            role="user",
            first_name="Robin",
            last_name="Muster",
        )
        organisation_user = self._upsert_user(
            User,
            username="demo_organisation",
            email="organisation@openzev.local",
            password="organisation1234",
            role="user",
            first_name="Mira",
            last_name="Keller",
        )
        mixed_user = self._upsert_user(
            User,
            username="demo_mixed",
            email="mixed@openzev.local",
            password="mixed1234",
            role="user",
            first_name="Sam",
            last_name="Wechsel",
        )
        self._upsert_grant(zev=zev, user=mixed_user, role=ZevAccessRole.MANAGER, granted_by=owner)
        auditor = self._upsert_user(
            User,
            username="demo_auditor",
            email="treuhand@openzev.local",
            password="treuhand1234",
            role="user",
            first_name="Tina",
            last_name="Treuhand",
        )
        # Access is checked against the real date, so this end date follows
        # today rather than --end-date: the login must still work.
        self._upsert_grant(
            zev=zev, user=auditor, role=ZevAccessRole.VIEWER, granted_by=owner,
            valid_to=date(today.year + 1, 3, 31),
        )
        newcomer = self._upsert_user(
            User,
            username="demo_newcomer",
            email="newcomer@openzev.local",
            password="newcomer1234",
            role="user",
            first_name="Nora",
            last_name="Neu",
        )
        if not newcomer.may_create_zev:
            newcomer.may_create_zev = True
            newcomer.save(update_fields=["may_create_zev"])
        # Like an access-API invitation: inactive, no password, an unused
        # link. Never emailed; a re-seed issues a fresh link.
        invitee, _ = User.objects.update_or_create(
            username="demo_invitee",
            defaults={
                "email": "invitee@openzev.local",
                "role": "user",
                "first_name": "Alex",
                "last_name": "Eingeladen",
                "is_active": False,
            },
        )
        if invitee.has_usable_password():
            invitee.set_unusable_password()
            invitee.save(update_fields=["password"])
        self._upsert_grant(zev=second_zev, user=invitee, role=ZevAccessRole.VIEWER, granted_by=owner)
        issue_invitation(invitee)

        # Participants and their meter assignments are valid from the start of
        # the previous calendar year — not just from the seed window — so
        # annual statements and reports cover a full year. ``start_date``
        # above stays the metering/tariff anchor for the current window.
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
            valid_from=main_valid_from,
        )
        # Dated issuer handover: the previous owner (no login) issued H1 of
        # the settled year, Paula from mid-year. Rows are rebuilt every run.
        ZevPartyRole.objects.filter(
            zev=zev, role__in=[PartyRole.ISSUER, PartyRole.LANDOWNER]
        ).delete()
        handover_day = date(end_date.year - 1, 7, 1)
        previous_issuer = self._upsert_party(
            zev=zev,
            kind=PartyKind.PERSON,
            first_name="Otto",
            last_name="Vorbesitzer",
            email="",
            phone="+41 31 555 05 05",
            address_line1="Solarweg 1",
            postal_code="3000",
            city="Bern",
        )
        assign_role(
            zev, previous_issuer, PartyRole.ISSUER,
            main_valid_from, valid_to=handover_day - timedelta(days=1),
        )
        assign_role(zev, owner_participant.party, PartyRole.ISSUER, handover_day)
        assign_role(zev, owner_participant.party, PartyRole.LANDOWNER, main_valid_from)
        # One property: its single building takes the issuer's address.
        main_building = ensure_initial_building(zev)
        self._drop_grant_covered_by_role(zev, owner)
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
            valid_from=main_valid_from,
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
            valid_from=main_valid_from,
        )
        # Flat 3 changes tenants at the start of Q2 last year ("last year" is
        # the year before --end-date). Maria keeps this address until her
        # invoices are seeded, then moves away (below).
        tenant_change = date(end_date.year - 1, 4, 1)
        former_participant = self._upsert_participant(
            zev=zev,
            user=former_user,
            title=Participant.Title.MS,
            first_name="Maria Alexandra Elisabeth",
            last_name="von Sonnenberg-Musterlingen",
            email=former_user.email,
            phone="+41 31 555 60 60",
            address_line1="Aarestrasse 16",
            postal_code="3000",
            city="Bern",
            valid_from=main_valid_from,
            valid_to=tenant_change - timedelta(days=1),
        )
        household_participant = self._upsert_participant(
            zev=zev,
            user=household_user,
            title=Participant.Title.MR,
            first_name="Robin",
            last_name="Muster",
            name_addition="und Dominique Muster-Keller",
            email=household_user.email,
            phone="+41 31 555 61 61",
            address_line1="Aarestrasse 16",
            postal_code="3000",
            city="Bern",
            valid_from=tenant_change,
        )
        organisation_participant = self._upsert_participant(
            zev=zev,
            user=organisation_user,
            title=Participant.Title.MS,
            kind=PartyKind.ORGANISATION,
            organisation_name="Atelier für nachhaltige Architektur und Gebäudetechnik Muster AG",
            first_name="Mira",
            last_name="Keller",
            email=organisation_user.email,
            phone="+41 31 555 62 62",
            address_line1="Aarestrasse 10",
            address_line2="Atelier im Erdgeschoss",
            postal_code="3000",
            city="Bern",
            valid_from=main_valid_from,
        )
        # Ben's parking space is a second participation of his party, told
        # apart from his flat by its note.
        garage_note = "Einstellhalle, Platz 4 mit Ladestation"
        garage_participant = Participant.objects.filter(
            zev=zev, party=participant_two.party, notes=garage_note,
        ).first() or Participant(zev=zev, party=participant_two.party, notes=garage_note)
        garage_participant.user = participant_two_user
        garage_participant.valid_from = main_valid_from
        garage_participant.valid_to = None
        garage_participant.save()

        # Parties that are not participants (#761): the Verwaltung represents
        # the community toward the grid operator, and its login manages the
        # ZEV through that role; the caretaker is a contact without a role or
        # access. A re-seed restores both and the representative role.
        verwaltung = self._upsert_party(
            zev=zev,
            kind=PartyKind.ORGANISATION,
            organisation_name="Verwaltung Muster AG",
            first_name="Marco",
            last_name="Verwaltung",
            email=property_manager.email,
            phone="+41 31 555 40 40",
            address_line1="Bundesgasse 8",
            postal_code="3011",
            city="Bern",
            user=property_manager,
        )
        ZevPartyRole.objects.filter(zev=zev, role=PartyRole.REPRESENTATIVE).delete()
        assign_role(zev, verwaltung, PartyRole.REPRESENTATIVE, main_valid_from)
        self._upsert_party(
            zev=zev,
            kind=PartyKind.PERSON,
            first_name="Hans",
            last_name="Hauswart",
            email="hauswart@openzev.local",
            phone="+41 79 555 50 50",
            notes="Hauswart, hat den Schlüssel zum Zählerraum.",
        )

        owner_prod = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-PROD-0001",
            meter_type=MeteringPointType.PRODUCTION,
            location_description="Rooftop PV production meter",
            building=main_building,
        )
        participant_one_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 1 consumption meter",
            building=main_building,
        )
        participant_two_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0002",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 2 consumption meter",
            building=main_building,
        )
        # Intentionally unassigned: exercises the "no assignment yet" UI state
        # (Ohne Zuweisung filter, Teilnehmer zuweisen action) in demos and lets
        # the screenshot suite capture the assign flow without creating its own
        # fixtures. A presenter may assign it through the demo UI during a
        # session; a re-seed is the demo's reset button, so that assignment is
        # cleared again here.
        spare_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0003",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Spare consumption meter (unassigned)",
            building=main_building,
        )
        MeteringPointAssignment.objects.filter(metering_point=spare_cons).delete()
        # Allgemeinstrom: the shared draw nobody uses alone. Held by the owner
        # (who acts as the Verwaltung here) but allocated across the community
        # by weight, which is what makes the demo show off shared metering.
        common_area_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-COMMON-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Common area: stairwell, lift, laundry",
            building=main_building,
        )
        flat_three_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0004",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 3 consumption meter",
            building=main_building,
        )
        studio_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-CONS-0005",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Ground-floor studio consumption meter",
            building=main_building,
        )
        charger_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO-EV-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Garage space 4: EV charger",
            building=main_building,
        )

        self._ensure_assignment(owner_prod, owner_participant, main_valid_from)
        self._ensure_assignment(participant_one_cons, participant_one, main_valid_from)
        self._ensure_assignment(participant_two_cons, participant_two, main_valid_from)
        self._ensure_assignment(
            common_area_cons, owner_participant, main_valid_from,
            allocation_mode=AllocationMode.COMMUNITY,
        )
        self._ensure_assignment(studio_cons, organisation_participant, main_valid_from)
        self._ensure_assignment(charger_cons, garage_participant, main_valid_from)
        self._ensure_assignments(flat_three_cons, [
            (former_participant, main_valid_from, former_participant.valid_to),
            (household_participant, tenant_change, None),
        ])

        # Unequal so the demo shows a real weighted split rather than an equal
        # one that looks the same either way; the parking space carries a
        # small share.
        for participant, weight in (
            (owner_participant, Decimal("1")),
            (participant_one, Decimal("1")),
            (participant_two, Decimal("2")),
            (former_participant, Decimal("2")),
            (household_participant, Decimal("2")),
            (organisation_participant, Decimal("2")),
            (garage_participant, Decimal("0.25")),
        ):
            if participant.allocation_weight != weight:
                participant.allocation_weight = weight
                participant.save(update_fields=["allocation_weight"])

        self._seed_tariffs(zev, start_date, history_start=main_valid_from)
        dynamic_tariff = self._seed_dynamic_tariff(zev, end_date=end_date)
        self._upsert_vat_rates()

        # Rerun hygiene: drop every earlier reading on the main meters (both
        # last run's quarter window and its hourly history) so the shifting
        # seed windows below can never leave overlapping or stale rows behind.
        # The roof is sized for the whole house, so the year's production
        # still slightly exceeds its consumption.
        main_meters = [
            (owner_prod, ReadingDirection.OUT, self._scaled_kwh(self._producer_kwh, 2.0)),
            (participant_one_cons, ReadingDirection.IN, self._consumer_one_kwh),
            (participant_two_cons, ReadingDirection.IN, self._consumer_two_kwh),
            (common_area_cons, ReadingDirection.IN, self._common_area_kwh),
            (flat_three_cons, ReadingDirection.IN, self._scaled_kwh(self._consumer_two_kwh, 1.15)),
            (studio_cons, ReadingDirection.IN, self._studio_kwh),
            (charger_cons, ReadingDirection.IN, self._ev_charger_kwh),
        ]
        consumption_meters = [meter for meter, direction, _ in main_meters if direction == ReadingDirection.IN]
        deleted_readings = MeterReading.objects.filter(
            metering_point__in=[meter for meter, _, _ in main_meters],
        ).delete()[0]

        # Reading volume dominates re-seed time, so 15-minute rows are kept
        # only for the tail of the window — what the recent-day views show —
        # and everything older is hourly, each row summing the four
        # quarter-hour samples it replaces. The boundary is derived from
        # ``end_date`` once and shared by every meter. The full previous
        # calendar year stays hourly so the reports pages can render a
        # complete year at a fraction of the row count.
        self._seed_history_readings(
            history_start=history_start,
            stop_date=start_date,
            meters=main_meters,
        )
        fine_from = self._seed_meter_readings(
            start_date=start_date,
            end_date=end_date,
            meters=main_meters,
        )

        # The flagship's invoices are rebuilt from scratch every run: a
        # settled previous calendar year (paid, so the financial summary's
        # tax overview has a full reports year to render) plus the open last
        # complete quarter in draft/approved/sent.
        invoice_period_start, invoice_period_end = previous_quarter(end_date)
        self._delete_invoices(Invoice.objects.filter(zev=zev))
        year_paid_invoices = self._seed_paid_year_invoices(
            zev,
            year=end_date.year - 1,
            skip_period=(invoice_period_start, invoice_period_end),
        )
        seeded_invoices = self._seed_invoices(zev, invoice_period_start, invoice_period_end)
        # Maria has moved away; her issued invoices keep their address copy.
        former_participant.address_line1 = "Alte Sonnenbergstrasse 123, Haus C, Appartement 42"
        former_participant.address_line2 = "Eingang Nord, 3. Obergeschoss, Klingel Musterlingen"
        former_participant.postal_code = "8001"
        former_participant.city = "Zürich"
        former_participant.save()

        # Second community: same shapes as the main one but smaller. Its
        # monthly cadence lets us seed a *closed* previous month (paid and
        # cancelled invoices) alongside the open last complete month, so the
        # invoice list shows settled periods too.
        second = self._seed_second_community(
            owner=owner,
            clara_user=second_participant_user,
            mixed_user=mixed_user,
            zev=second_zev,
            start_date=start_date,
            end_date=end_date,
        )

        # The demo is deliberately not pristine: a recent ~12-day reading gap
        # on one meter gives the data-quality page something real to show, and
        # the operational-history seeding fills the import/email/audit/contract
        # pages that would otherwise sit empty. Both run after the invoices so
        # neither can disturb the seeded billing periods.
        gap_start, gap_end = self._punch_quality_gap(
            meter=participant_two_cons,
            after=invoice_period_end,
            end_date=end_date,
        )

        # Printed totals are computed after the gap deleted its rows, so they
        # describe the database the seed leaves behind.
        production_total = (
            MeterReading.objects.filter(metering_point=owner_prod).aggregate(
                total=Sum("energy_kwh")
            )["total"]
            or Decimal("0")
        )
        consumption_total = (
            MeterReading.objects.filter(
                metering_point__in=consumption_meters
            ).aggregate(total=Sum("energy_kwh"))["total"]
            or Decimal("0")
        )
        common_area_total = (
            MeterReading.objects.filter(metering_point=common_area_cons).aggregate(
                total=Sum("energy_kwh")
            )["total"]
            or Decimal("0")
        )

        op_stats = self._seed_operational_history(
            owner=owner,
            admin=admin,
            anna_user=participant_one_user,
            zev=zev,
            second_zev=second_zev,
            invoice_period_start=invoice_period_start,
            invoice_period_end=invoice_period_end,
            end_date=end_date,
            second_closed_start=second.closed_start,
        )

        summary = [
            "",
            "Demo environment ready.",
            "",
            "Frontend: http://localhost:8080",
            "Backend API: http://localhost:8080/api/v1",
            "",
            "Accounts:",
            "  Admin:         admin@openzev.local / admin1234",
            "  Issuer:        owner@openzev.local / owner1234                (ZEV 1 + ZEV 2)",
            "  Participant 1: anna@openzev.local / anna1234                  (ZEV 1)",
            "  Participant 2: ben@openzev.local / ben1234                    (ZEV 1, flat 2 + parking space with charger)",
            "  Participant 3: clara@openzev.local / clara1234                (ZEV 2)",
            "  Viewer:        viewer@openzev.local / viewer1234              (ZEV 1, read-only)",
            "  Manager:       manager@openzev.local / manager1234            (ZEV 1 as representative + ZEV 2)",
            "  Former:        former@openzev.local / former1234              (ZEV 1, moved out)",
            "  Household:     household@openzev.local / household1234        (ZEV 1, joint household)",
            "  Organisation:  organisation@openzev.local / organisation1234  (ZEV 1, organisation)",
            "  Mixed:         mixed@openzev.local / mixed1234                (ZEV 1 manager by grant + ZEV 2 participant)",
            "  Treuhand:      treuhand@openzev.local / treuhand1234          (ZEV 1 viewer until 31 March next year)",
            "  Newcomer:      newcomer@openzev.local / newcomer1234          (no ZEV yet, may set one up)",
            "  Invited:       invitee@openzev.local, no password             (ZEV 2 viewer, invitation pending)",
            "  No login:      Otto Vorbesitzer (ZEV 1 issuer until mid last year), Hans Hauswart (ZEV 1 contact),",
            "                 Lukas (ZEV 2 participant and landowner)",
            "",
            f"ZEV 1: {zev.name} (full dataset, {zev.billing_interval} "
            f"{zev.invoice_language.upper()} invoices, VAT folded into prices)",
            f"  Metering: {history_start} -> {end_date} "
            f"(15-min {fine_from} -> {end_date}; hourly before that)",
            f"  Invoice period: {invoice_period_start} -> {invoice_period_end} "
            f"({len(seeded_invoices)} invoices)",
            f"  Settled {end_date.year - 1}: {len(year_paid_invoices)} paid invoices "
            f"(feeds the producer's tax overview)",
            f"  Tariffs: {zev.tariffs.count()} versions across "
            f"{zev.tariffs.values('name').distinct().count()} tariffs",
            f"  Dynamic demo: {dynamic_tariff.name} from {dynamic_tariff.valid_from} "
            "(synthetic, fetching disabled)",
            f"  Deleted existing demo readings: {deleted_readings}",
            f"  Production total ({history_start} -> {end_date}): {production_total} kWh",
            f"  Consumption total ({history_start} -> {end_date}): {consumption_total} kWh",
            f"    of which common area (split by weight): {common_area_total} kWh",
            f"  Production minus consumption: {(production_total - consumption_total).quantize(Decimal('0.0001'))} kWh",
        ]
        if gap_start is not None:
            summary.append(
                f"  Data-quality demo gap: {participant_two_cons.meter_id} has no readings "
                f"{gap_start} -> {gap_end} (current quarter; seeded invoices untouched)"
            )
        summary.extend([
            "",
            f"ZEV 2: {second_zev.name} (smaller dataset, "
            f"{second_zev.billing_interval} {second_zev.invoice_language.upper()} "
            f"invoices, VAT-registered, itemized tariff bands)",
            f"  Open invoices: {len(second.open_invoices)} "
            f"(period {second.open_start} -> {second.open_end})",
            f"  Closed invoices (paid/cancelled): {len(second.closed_invoices)} "
            f"(period {second.closed_start} -> {second.closed_end})",
            "",
            "Operational demo history:",
            f"  Import logs: {op_stats['import_logs']} (CSV + SDAT-CH) "
            f"· Email logs: {op_stats['email_logs']} · Audit events: "
            f"{op_stats['audit_events']} (one denied) · Contracts issued: "
            f"{op_stats['contracts']}",
            "  Switch between both communities from the sidebar dropdown ",
            "  (use the demo owner login).",
        ])

        # A custom window can begin after the periods the seed advertises; the
        # lists are then empty by design, so say so explicitly instead of
        # silently shipping an empty invoice section.
        if not seeded_invoices:
            summary.append(
                f"  NOTE: no flagship invoices for {invoice_period_start} -> "
                f"{invoice_period_end}: the window starts on {start_date}, after "
                "that quarter ended — pass an earlier --start-date to bill it."
            )
        if not second.open_invoices:
            summary.append(
                f"  NOTE: no ZEV 2 open invoices for {second.open_start} -> "
                f"{second.open_end}: participants begin on {start_date}, after "
                "that month ended."
            )
        if not second.closed_invoices:
            summary.append(
                f"  NOTE: no ZEV 2 closed invoices for {second.closed_start} -> "
                f"{second.closed_end}: participants begin on {start_date}, after "
                "that month ended."
            )

        self._enable_demo_feature_flags()
        summary.append("Feature flags: feasibility calculator enabled for this demo.")

        self.stdout.write(self.style.SUCCESS("\n".join(summary)))

    def _upsert_zev(
        self,
        *,
        owner,
        name: str,
        zev_type: str,
        start_date: date,
        grid_operator: str,
        grid_connection_point: str,
        billing_interval: str,
        invoice_prefix: str,
        invoice_language: str,
        bank_iban: str,
        bank_name: str,
        vat_mode: str,
        vat_number: str,
        itemize_tariff_bands: bool = False,
        tariff_source_url: str = "",
        local_tariff_notes: str = "",
        additional_contract_notes: str = "",
        email_subject_template: str = "",
        email_body_template: str = "",
    ) -> Zev:
        """Create a demo ZEV, or refresh it to the canonical config (re-applied every run).

        The demo owner manages it — first by grant, then through the issuer
        role (``_drop_grant_covered_by_role``); either is how a re-run finds it
        again.
        """
        zev = self._owned_zevs(owner).filter(name=name).order_by("created_at").first() or Zev(name=name)
        config = {
            "start_date": start_date,
            "zev_type": zev_type,
            "grid_operator": grid_operator,
            "grid_connection_point": grid_connection_point,
            "billing_interval": billing_interval,
            "invoice_prefix": invoice_prefix,
            "invoice_language": invoice_language,
            "bank_iban": bank_iban,
            "bank_name": bank_name,
            "vat_mode": vat_mode,
            "vat_number": vat_number,
            "itemize_tariff_bands": itemize_tariff_bands,
            "tariff_source_url": tariff_source_url,
            "local_tariff_notes": local_tariff_notes,
            "additional_contract_notes": additional_contract_notes,
            "email_subject_template": email_subject_template,
            "email_body_template": email_body_template,
            # The invoice counter is part of the canonical config too: the
            # seed deletes the demo invoices before regenerating them, so
            # without the reset the numbers would keep climbing across
            # re-seeds. The
            # contract counter is deliberately left alone — issued
            # contract snapshots are not deleted, so resetting it could
            # mint duplicate CTR-YYYY-NNNN document numbers.
            "invoice_counter": 1,
        }
        for field, value in config.items():
            setattr(zev, field, value)
        zev.save()
        self._upsert_grant(zev=zev, user=owner, role=ZevAccessRole.MANAGER, granted_by=None)
        return zev

    @staticmethod
    def _owned_zevs(owner):
        """The ZEVs the demo owner manages, by grant or as their issuer."""
        return Zev.objects.filter(
            Q(access_grants__user=owner, access_grants__role=ZevAccessRole.MANAGER)
            | Q(party_roles__role=PartyRole.ISSUER, party_roles__party__participations__user=owner),
        ).distinct()

    @staticmethod
    def _drop_grant_covered_by_role(zev: Zev, user) -> None:
        """Remove ``user``'s grant on ``zev`` once a role makes it manager today:
        the issuer manages through its role (#761), and a grant on top would
        list the same person twice under People & access."""
        from zev import access

        if any(account == user for account, _row in access.role_managers(zev)):
            ZevAccessGrant.objects.filter(zev=zev, user=user).delete()

    def _migrate_legacy_demo_zev_names(self, *, owner) -> None:
        """Rename the demo owner's row still carrying the superseded flagship name.

        Runs before ``_upsert_zev`` so that row is refreshed under the current
        name instead of a second, duplicated ZEV being created. ``Zev.name``
        carries no unique constraint, so multiple legacy rows that would end
        up on the same name are deduplicated first — otherwise the later
        update-or-create lookup would raise ``MultipleObjectsReturned`` and
        roll the whole seed back. Everything here is scoped to the demo
        owner: a tenant who happens to carry the same display name on another
        community is never selected, renamed or deleted.
        """
        legacy_rows = self._owned_zevs(owner).filter(name=DEMO_ZEV_LEGACY_NAME).order_by("created_at")
        if not legacy_rows.exists():
            return
        if self._owned_zevs(owner).filter(name=DEMO_ZEV_NAME).exists():
            # The current name is already taken by the owner; any legacy rows
            # left over are superseded duplicates of it.
            self._delete_demo_zev_rows(legacy_rows)
            return
        # Keep the newest legacy row, drop older duplicates of it, then
        # rename the survivor.
        survivor = legacy_rows.last()
        self._delete_demo_zev_rows(legacy_rows.exclude(pk=survivor.pk))
        survivor.name = DEMO_ZEV_NAME
        survivor.save(update_fields=["name"])

    def _delete_demo_zev_rows(self, rows) -> None:
        """Delete superseded demo ZEV rows that may carry invoices.

        ``Invoice.zev`` is PROTECT, so the ZEV cannot go first when an older
        seed run left invoices behind — clear those (cascading to items and
        email logs) before deleting the row itself.
        """
        for zev in rows:
            self._delete_invoices(zev.invoices.all())
            zev.delete()

    def _delete_invoices(self, invoices) -> None:
        """Delete invoice rows; remove unreferenced PDFs after commit."""
        stale = {name for name in invoices.values_list("pdf_file", flat=True) if name}
        invoices.delete()
        if stale:
            transaction.on_commit(lambda: self._delete_stale_pdfs(stale), robust=True)

    def _delete_stale_pdfs(self, names: set[str]) -> None:
        # A storage that overwrites could have handed a name to a new PDF.
        names = names - set(Invoice.objects.filter(pdf_file__in=names).values_list("pdf_file", flat=True))
        storage = Invoice._meta.get_field("pdf_file").storage
        for name in sorted(names):
            try:
                storage.delete(name)
            except OSError as exc:
                self.stdout.write(self.style.WARNING(f"seed_demo: stale PDF {name} not removed ({exc})"))

    def _seed_invoice_pdfs(self, invoice_ids) -> None:
        created = 0
        for invoice in Invoice.objects.filter(pk__in=invoice_ids).order_by("period_start"):
            try:
                # Isolate a failed database write so the remaining PDFs can be saved.
                with transaction.atomic():
                    save_invoice_pdf(invoice)
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"seed_demo: PDF for invoice {invoice.invoice_number} skipped "
                        f"({exc.__class__.__name__}: {exc})"
                    )
                )
            else:
                created += 1
        self.stdout.write(f"  Invoice PDFs: {created}")

    def _scaled_kwh(self, profile: Profile, factor: float) -> Profile:
        """A main-community profile at another amplitude (one shape per meter kind)."""

        def scaled(timestamp: datetime, day_index: int) -> Decimal:
            return Decimal(str(round(float(profile(timestamp, day_index)) * factor, 4)))

        return scaled

    def _seed_second_community(
        self,
        *,
        owner,
        clara_user,
        mixed_user=None,
        zev: Zev,
        start_date: date,
        end_date: date,
    ) -> SecondCommunitySeed:
        """Seed the smaller second demo community.

        A scaled-down mirror of the main ZEV's structure — owner-held PV and
        common-area meter plus two households — with the same idempotent-
        refresh semantics: assignments re-applied, tariffs rebuilt, and
        readings and invoices replaced on every run. Clara has a login so the
        participant side can be demoed on this ZEV too; Lukas is billed by
        mail without an account. Sam has just moved in, without a meter yet.

        Two months of invoices are seeded: the last complete month in the
        normal draft/approved/sent progression, and the month before it as a
        closed (paid/cancelled) period.
        """
        # Rerun hygiene, mirroring the flagship wipe in ``handle``: drop every
        # earlier reading and invoice on this ZEV so a shifted ``--start-date``
        # / ``--end-date`` can never leave stale rows outside the new window
        # or stale billing periods behind. ``_seed_invoices`` never deletes;
        # its callers own wiping.
        # Filter the foreign key directly: a joined DELETE adds a readings
        # self-join that PostgreSQL can plan poorly with stale statistics.
        MeterReading.objects.filter(
            metering_point__in=MeteringPoint.objects.filter(zev=zev),
        ).delete()
        self._delete_invoices(Invoice.objects.filter(zev=zev))

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
        ensure_initial_roles(zev, owner_participant.party, start_date)
        self._drop_grant_covered_by_role(zev, owner)
        # A vZEV of three houses, one building each (#890); the landowner
        # roles are assigned below, once all three participants exist.
        owner_house = self._upsert_building(
            zev=zev, address_line1="Solarweg 1", name="Solarweg 1", postal_code="3000", city="Bern",
        )
        clara_house = self._upsert_building(
            zev=zev, address_line1="Kirchenfeldstrasse 42", name="Kirchenfeldstrasse 42",
            postal_code="3005", city="Bern",
        )
        lukas_house = self._upsert_building(
            zev=zev, address_line1="Monbijoustrasse 88", name="Monbijoustrasse 88",
            postal_code="3007", city="Bern",
        )
        participant_one = self._upsert_participant(
            zev=zev,
            user=clara_user,
            title=Participant.Title.MS,
            first_name="Clara",
            last_name="Müller",
            email=clara_user.email,
            phone="+41 31 555 40 40",
            address_line1="Kirchenfeldstrasse 42",
            postal_code="3005",
            city="Bern",
            valid_from=start_date,
        )
        participant_two = self._upsert_participant(
            zev=zev,
            user=None,
            title=Participant.Title.MR,
            first_name="Lukas",
            last_name="Schneider",
            email="lukas.schneider@openzev.local",
            phone="+41 31 555 50 50",
            address_line1="Monbijoustrasse 88",
            postal_code="3007",
            city="Bern",
            valid_from=start_date,
        )
        # Sam has just moved in: his meter is not assigned yet, so he has no
        # seeded invoices.
        if mixed_user is not None:
            self._upsert_participant(
                zev=zev,
                user=mixed_user,
                title=Participant.Title.MR,
                first_name="Sam",
                last_name="Wechsel",
                email=mixed_user.email,
                phone="+41 31 555 63 63",
                address_line1="Monbijoustrasse 90",
                postal_code="3007",
                city="Bern",
                valid_from=end_date,
            )

        # One landowner per house, rebuilt every run; Lukas has no login.
        ZevPartyRole.objects.filter(zev=zev, role=PartyRole.LANDOWNER).delete()
        assign_role(
            zev, owner_participant.party, PartyRole.LANDOWNER,
            start_date, building=owner_house,
        )
        assign_role(
            zev, participant_one.party, PartyRole.LANDOWNER,
            start_date, building=clara_house,
        )
        assign_role(
            zev, participant_two.party, PartyRole.LANDOWNER,
            start_date, building=lukas_house,
        )

        owner_prod = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO2-PROD-0001",
            meter_type=MeteringPointType.PRODUCTION,
            location_description="Rooftop PV production meter",
            building=owner_house,
        )
        participant_one_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO2-CONS-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 1 consumption meter",
            building=clara_house,
        )
        participant_two_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO2-CONS-0002",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Apartment 2 consumption meter",
            building=lukas_house,
        )
        common_area_cons = self._upsert_metering_point(
            zev=zev,
            meter_id="CH-DEMO2-COMMON-0001",
            meter_type=MeteringPointType.CONSUMPTION,
            location_description="Common area: stairwell, lift, laundry",
            building=owner_house,
        )

        self._ensure_assignment(owner_prod, owner_participant, start_date)
        self._ensure_assignment(participant_one_cons, participant_one, start_date)
        self._ensure_assignment(participant_two_cons, participant_two, start_date)
        self._ensure_assignment(
            common_area_cons, owner_participant, start_date,
            allocation_mode=AllocationMode.COMMUNITY,
        )

        # Equal weights here — each participant pays one third of the common
        # area — which reads differently from the main ZEV's unequal weights.
        for participant in (owner_participant, participant_one, participant_two):
            if participant.allocation_weight != Decimal("1"):
                participant.allocation_weight = Decimal("1")
                participant.save(update_fields=["allocation_weight"])

        self._seed_tariffs(zev, start_date, specs=SECOND_DEMO_TARIFF_SPECS)

        self._seed_meter_readings(
            start_date=start_date,
            end_date=end_date,
            meters=[
                (owner_prod, ReadingDirection.OUT, self._scaled_kwh(self._producer_kwh, 0.72)),
                (participant_one_cons, ReadingDirection.IN, self._scaled_kwh(self._consumer_one_kwh, 0.94)),
                (participant_two_cons, ReadingDirection.IN, self._scaled_kwh(self._consumer_two_kwh, 1.12)),
                (common_area_cons, ReadingDirection.IN, self._scaled_kwh(self._common_area_kwh, 0.90)),
            ],
        )

        # Monthly interval, so the seeded invoice run covers the last complete
        # month — the period the UI opens on for a monthly-billed ZEV. The
        # ZEV's invoices were wiped above; ``_seed_invoices`` never deletes,
        # so the two periods seed independently of each other's call order.
        invoice_period_start, invoice_period_end = previous_month(end_date)

        # One month earlier, everything is settled: invoices are paid, the
        # last one cancelled as if issued in error, so the list shows the
        # closed-period badges and period totals.
        closed_end = invoice_period_start - timedelta(days=1)
        closed_start = closed_end.replace(day=1)
        closed_invoices = self._seed_invoices(
            zev, closed_start, closed_end, closed=True,
        )
        invoices = self._seed_invoices(
            zev, invoice_period_start, invoice_period_end,
        )
        return SecondCommunitySeed(
            open_invoices=invoices,
            open_start=invoice_period_start,
            open_end=invoice_period_end,
            closed_invoices=closed_invoices,
            closed_start=closed_start,
            closed_end=closed_end,
        )

    def _reset_demo_audit_trail(
        self,
        *,
        owner,
        admin,
        anna_user,
        zev: Zev,
        second_zev: Zev,
    ) -> None:
        """Delete the demo's audit trail so a re-seed starts clean.

        Removes every event on the two demo ZEVs (whoever the actor — including
        the other demo logins, Ben and Clara) plus owner, admin and Anna events
        that carry no ZEV at all (e.g. ``vat_rate.create``). Events the demo actors
        left on *other* communities in a shared dev database survive the reset.
        """
        AuditEvent.objects.filter(zev__in=[zev, second_zev]).delete()
        AuditEvent.objects.filter(
            actor_user__in=[owner, admin, anna_user],
            zev__isnull=True,
        ).delete()

    def _punch_quality_gap(
        self,
        *,
        meter: MeteringPoint,
        after: date,
        end_date: date,
        days: int = 12,
    ) -> tuple[date | None, date | None]:
        """Delete ``days`` of readings after the last billed day; no-op if that window does not fit."""
        gap_end = end_date - timedelta(days=1)
        gap_start = gap_end - timedelta(days=days - 1)
        if gap_start <= after:
            return None, None
        window_start, window_end = period_window(gap_start, gap_end)
        MeterReading.objects.filter(
            metering_point=meter, timestamp__gte=window_start, timestamp__lt=window_end,
        ).delete()
        return gap_start, gap_end

    def _seed_operational_history(
        self,
        *,
        owner,
        admin,
        anna_user,
        zev: Zev,
        second_zev: Zev,
        invoice_period_start: date,
        invoice_period_end: date,
        end_date: date,
        second_closed_start: date,
    ) -> dict[str, int]:
        """Fill the import/email/contract/audit pages with plausible demo history.

        Re-created on every run instead of appended to, so re-seeding stays
        stable: import logs (CSV provenance on a real meter month of the main
        ZEV), one email log per sent invoice, participation contracts via the
        real issuance path (unchanged re-seeds reuse the stored snapshot), the
        PDFs of Anna's sent/paid invoices after commit, and audit events across categories
        including one denied. Audit timestamps are anchored to the seeded
        periods rather than to "today minus fixed offsets", so a custom
        ``--end-date`` in the past still tells a consistent story.
        """
        stats = {"import_logs": 0, "email_logs": 0, "audit_events": 0, "contracts": 0}

        ImportLog.objects.filter(zev__in=[zev, second_zev]).delete()

        # CSV provenance: a real meter month of the main ZEV was "imported"
        # from a CSV file, so the ImportLog row and the tagged readings agree.
        csv_meter = MeteringPoint.objects.get(zev=zev, meter_id="CH-DEMO-CONS-0001")
        csv_start = date(invoice_period_end.year, invoice_period_end.month, 1)
        if invoice_period_end.month == 12:
            next_first = date(invoice_period_end.year + 1, 1, 1)
        else:
            next_first = date(invoice_period_end.year, invoice_period_end.month + 1, 1)

        import_log = ImportLog.objects.create(
            zev=zev,
            imported_by=owner,
            source=ImportSource.CSV,
            filename=f"openzev-demo-{csv_start:%Y-%m}.csv",
            timestamp_timezone=str(business_tz()),
            rows_total=0,
            rows_imported=0,
            rows_skipped=0,
            errors=[],
        )
        imported_rows = MeterReading.objects.filter(
            metering_point=csv_meter,
            timestamp__gte=period_start_dt(csv_start),
            timestamp__lt=period_start_dt(next_first),
        ).update(import_source=ImportSource.CSV, import_batch=import_log.batch_id)
        import_log.rows_total = imported_rows
        import_log.rows_imported = imported_rows
        import_log.save(update_fields=["rows_total", "rows_imported"])

        # A second log on the second community with skipped rows + errors, so
        # the import list shows those badges without needing a real bad import.
        ImportLog.objects.create(
            zev=second_zev,
            imported_by=owner,
            source=ImportSource.SDATCH,
            filename=f"zev-sonnenfirma-sdat-{second_closed_start:%Y-%m}.xml",
            timestamp_timezone=str(business_tz()),
            rows_total=992,
            rows_imported=980,
            rows_skipped=12,
            errors=[
                "Row 41: meter CH-DEMO2-UNKNOWN-9 not found in this ZEV (skipped).",
                "Row 212: duplicate timestamp for CH-DEMO2-CONS-0001 (skipped).",
            ],
        )
        stats["import_logs"] = ImportLog.objects.filter(zev__in=[zev, second_zev]).count()

        # One row per invoice that carries a sent_at (the settled year, the
        # open period's sent invoices and the closed month), so the invoice
        # detail's email section is filled.
        EmailLog.objects.filter(invoice__zev__in=[zev, second_zev]).delete()
        for invoice in Invoice.objects.filter(
            zev__in=[zev, second_zev], sent_at__isnull=False
        ).select_related("participant__party", "zev"):
            subject_template = invoice.zev.email_subject_template or DEFAULT_INVOICE_EMAIL_SUBJECT
            # A presenter may have added other {placeholders} to the template in
            # the settings UI; fall back to the default subject rather than
            # crashing the re-seed, mirroring invoices/tasks.py.
            try:
                subject = subject_template.format(
                    invoice_number=invoice.invoice_number,
                    zev_name=invoice.zev.name,
                )
            except (KeyError, ValueError):
                subject = DEFAULT_INVOICE_EMAIL_SUBJECT.format(
                    invoice_number=invoice.invoice_number,
                    zev_name=invoice.zev.name,
                )
            EmailLog.objects.create(
                invoice=invoice,
                recipient=invoice.participant.email or "",
                subject=subject,
                status=EmailLog.Status.SENT,
                sent_at=invoice.sent_at,
            )
        stats["email_logs"] = EmailLog.objects.filter(
            invoice__zev__in=[zev, second_zev]
        ).count()

        # Two representative contracts — Anna on the flagship (German) and
        # Clara on the second community (English) — issued through the real
        # issuance path; unchanged re-seeds reuse the stored snapshot.
        # Issuing one for every participation would multiply the PDF-render
        # cost for no new demo value. One failing participant must not roll back the whole seed
        # (``handle`` is atomic), so it is warned and skipped.
        for participant in Participant.objects.filter(
            zev__in=[zev, second_zev],
            party__first_name__in=["Anna", "Clara"],
        ):
            try:
                issue_contract_pdf(participant, issued_by=owner)
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"seed_demo: contract snapshot for {participant} skipped "
                        f"({exc.__class__.__name__}: {exc})"
                    )
                )
        stats["contracts"] = ContractIssue.objects.filter(
            zev__in=[zev, second_zev]
        ).count()

        # A failed seed must not leave newly written PDFs without invoice rows.
        invoice_ids = list(Invoice.objects.filter(
            zev=zev,
            participant__user=anna_user,
            status__in=[InvoiceStatus.SENT, InvoiceStatus.PAID],
        ).values_list("pk", flat=True))
        transaction.on_commit(lambda: self._seed_invoice_pdfs(invoice_ids), robust=True)

        # Reset the demo trail first (including anything a presenter clicked
        # during a previous session): this command is the demo's reset button.
        self._reset_demo_audit_trail(
            owner=owner,
            admin=admin,
            anna_user=anna_user,
            zev=zev,
            second_zev=second_zev,
        )

        anna_participant = Participant.objects.get(zev=zev, party__first_name="Anna")
        clara_participant = Participant.objects.get(zev=second_zev, party__first_name="Clara")
        sent_invoice = Invoice.objects.filter(zev=zev, status=InvoiceStatus.SENT).first()
        draft_invoice = Invoice.objects.filter(zev=zev, status=InvoiceStatus.DRAFT).first()
        grid_tariff = (
            Tariff.objects.filter(zev=zev, name="Grid Energy HT/NT")
            .order_by("-valid_from")
            .first()
        )
        anna_contract = ContractIssue.objects.filter(participant=anna_participant).first()

        audit_count = 0
        # Synthetic events are dated from the seeded period (capped at the end
        # of the window and at today), not from "today minus fixed offsets",
        # so a custom historical ``--end-date`` yields a consistent timeline.
        cap = min(end_date, date.today())
        csv_import_at = datetime.combine(
            min(csv_start + timedelta(days=6), cap), time(12, 0), tzinfo=business_tz()
        )

        def at_noon(day: date) -> datetime:
            return datetime.combine(day, time(12, 0), tzinfo=business_tz())

        def anchored(offset_days: int) -> datetime:
            """A date relative to the flagship's billed period end, capped at today."""
            return at_noon(min(invoice_period_end + timedelta(days=offset_days), cap))

        def audit(*, at: datetime, **kwargs):
            nonlocal audit_count
            event = record_audit_event(**kwargs)
            audit_count += 1
            AuditEvent.objects.filter(pk=event.pk).update(created_at=at)
            return event

        audit(
            at=anchored(-310),
            user=admin,
            action_category=AuditActionCategory.SYSTEM,
            action_type="vat_rate.create",
            target_type="accounts.VatRate",
            target_id="",
            target_display="8.10 % (from 2024-01-01)",
            summary="Created VAT rate 0.0810 (8.10 %).",
        )
        audit(
            at=anchored(-150),
            user=owner,
            zev=zev,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="zev.update",
            target_type="zev.Zev",
            target_id=str(zev.pk),
            target_display=zev.name,
            summary=f"Updated community settings for {zev.name}.",
            changes={"billing_interval": {"before": "monthly", "after": "quarterly"}},
        )
        # Anna's row is valid from her membership start, so her creation event
        # is dated shortly after that, keeping the timeline consistent with the
        # data it describes.
        audit(
            at=at_noon(min(anna_participant.valid_from + timedelta(days=10), cap)),
            user=owner,
            zev=zev,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.create",
            target_type="zev.Participant",
            target_id=str(anna_participant.pk),
            target_display=anna_participant.full_name,
            summary=f"Added participant {anna_participant.full_name}.",
        )
        audit(
            at=anchored(-130),
            user=owner,
            zev=zev,
            action_category=AuditActionCategory.TARIFF,
            action_type="tariff.update",
            target_type="tariffs.Tariff",
            target_id=str(grid_tariff.pk) if grid_tariff else "",
            target_display=grid_tariff.name if grid_tariff else "Grid Energy HT/NT",
            summary="Updated tariff Grid Energy HT/NT.",
            changes={
                "price_chf_per_kwh": {"before": "0.27000", "after": "0.29500"}
            },
        )
        audit(
            at=csv_import_at,
            user=owner,
            zev=zev,
            action_category=AuditActionCategory.IMPORT,
            action_type="metering.import",
            target_type="zev.MeteringPoint",
            target_id=str(csv_meter.pk),
            target_display=csv_meter.meter_id,
            summary=f"Imported {imported_rows} readings from {import_log.filename}.",
            metadata={"rows": imported_rows, "source": "csv"},
        )
        audit(
            at=anchored(2),
            user=owner,
            zev=zev,
            action_category=AuditActionCategory.INVOICE,
            action_type="invoice.generate_batch",
            target_type="invoices.Invoice",
            summary=(
                f"Generated {Invoice.objects.filter(zev=zev, period_start=invoice_period_start).count()} "
                f"invoices for {invoice_period_start} to {invoice_period_end}."
            ),
            metadata={
                "period_start": invoice_period_start.isoformat(),
                "period_end": invoice_period_end.isoformat(),
            },
        )
        if sent_invoice:
            audit(
                at=anchored(6),
                user=owner,
                zev=zev,
                action_category=AuditActionCategory.INVOICE,
                action_type="invoice.send",
                target_type="invoices.Invoice",
                target_id=str(sent_invoice.pk),
                target_display=f"{sent_invoice.invoice_number} – {sent_invoice.participant.full_name}",
                summary=f"Sent invoice {sent_invoice.invoice_number} to {sent_invoice.participant.email}.",
            )
        if draft_invoice:
            audit(
                at=anchored(4),
                user=anna_user,
                zev=zev,
                action_category=AuditActionCategory.INVOICE,
                action_type="invoice.approve",
                target_type="invoices.Invoice",
                target_id=str(draft_invoice.pk),
                target_display=f"{draft_invoice.invoice_number} – {draft_invoice.participant.full_name}",
                summary="Participant tried to approve an invoice.",
                status=AuditEventStatus.DENIED,
                reason="Participants cannot approve invoices. Only the community owner or an admin may.",
            )
        audit(
            at=at_noon(min(clara_participant.valid_from + timedelta(days=10), cap)),
            user=owner,
            zev=second_zev,
            action_category=AuditActionCategory.PARTICIPANT,
            action_type="participant.create",
            target_type="zev.Participant",
            target_id=str(clara_participant.pk),
            target_display=clara_participant.full_name,
            summary=f"Added participant {clara_participant.full_name} to {second_zev.name}.",
        )
        if anna_contract:
            audit(
                at=datetime.now(dt_timezone.utc),  # the snapshot was just issued by this run
                user=owner,
                zev=zev,
                action_category=AuditActionCategory.PARTICIPANT,
                action_type="contract.issue",
                target_type="zev.Participant",
                target_id=str(anna_participant.pk),
                target_display=anna_participant.full_name,
                summary=f"Issued participation contract {anna_contract.document_number} for {anna_participant.full_name}.",
                metadata={"document_number": anna_contract.document_number},
            )
        stats["audit_events"] = audit_count
        return stats

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

    def _upsert_grant(
        self, *, zev: Zev, user, role: str, granted_by, valid_to: date | None = None,
    ) -> ZevAccessGrant:
        """A grant of ``role`` for ``user`` on ``zev``, valid since the
        community started (or today, for a community that starts later).
        Open-ended unless ``valid_to`` is given; a dated grant replaces the
        user's earlier grants on the ZEV."""
        valid_from = min(zev.start_date, date.today())
        if valid_to is not None:
            ZevAccessGrant.objects.filter(zev=zev, user=user).delete()
            return ZevAccessGrant.objects.create(
                zev=zev, user=user, role=role, valid_from=valid_from, valid_to=valid_to,
                granted_by=granted_by,
            )
        grant = ZevAccessGrant.objects.filter(zev=zev, user=user, valid_to__isnull=True).first()
        if grant is None:
            grant = ZevAccessGrant.objects.create(
                zev=zev,
                user=user,
                role=role,
                valid_from=valid_from,
                granted_by=granted_by,
            )
        elif grant.role != role:
            grant.role = role
            grant.save(update_fields=["role", "updated_at"])
        return grant

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
        valid_to: date | None = None,
        kind: str = PartyKind.PERSON,
        organisation_name: str = "",
        name_addition: str = "",
        address_line2: str = "",
    ) -> Participant:
        # Oldest first: Ben's party also holds his parking space.
        participant = Participant.objects.filter(
            zev=zev, party__first_name=first_name, party__last_name=last_name,
        ).order_by("created_at").first() or Participant(zev=zev)
        participant.kind = kind
        participant.organisation_name = organisation_name
        participant.first_name = first_name
        participant.last_name = last_name
        participant.name_addition = name_addition
        participant.user = user
        participant.title = title
        participant.email = email
        participant.phone = phone
        participant.address_line1 = address_line1
        participant.address_line2 = address_line2
        participant.postal_code = postal_code
        participant.city = city
        participant.valid_from = valid_from
        # A re-seed resets the window.
        participant.valid_to = valid_to
        participant.save()
        return participant

    def _upsert_party(self, *, zev: Zev, kind: str, user=None, **fields) -> Party:
        """A party that is not a participant, found by its name."""
        lookup = (
            {"organisation_name": fields["organisation_name"]}
            if kind == PartyKind.ORGANISATION
            else {"first_name": fields["first_name"], "last_name": fields["last_name"]}
        )
        party = Party.objects.filter(zev=zev, kind=kind, **lookup).first() or Party(zev=zev, kind=kind)
        for name, value in fields.items():
            setattr(party, name, value)
        party.user = user
        party.save()
        return party

    def _upsert_building(self, *, zev: Zev, address_line1: str, **fields) -> Building:
        """A demo building, found by its street line within the ZEV."""
        building = Building.objects.filter(zev=zev, address_line1=address_line1).first() or Building(
            zev=zev, address_line1=address_line1
        )
        for name, value in fields.items():
            setattr(building, name, value)
        building.save()
        return building

    def _upsert_metering_point(
        self,
        *,
        zev: Zev,
        meter_id: str,
        meter_type: str,
        location_description: str,
        building: Building | None = None,
    ) -> MeteringPoint:
        defaults = {
            "zev": zev,
            "meter_type": meter_type,
            "is_active": True,
            "location_description": location_description,
        }
        if building is not None:
            defaults["building"] = building
        meter, _ = MeteringPoint.objects.update_or_create(meter_id=meter_id, defaults=defaults)
        return meter

    def _ensure_assignment(
        self,
        meter: MeteringPoint,
        participant: Participant,
        valid_from: date,
        allocation_mode: str = AllocationMode.PERSONAL,
    ) -> None:
        self._ensure_assignments(meter, [(participant, valid_from, None)], allocation_mode=allocation_mode)

    def _ensure_assignments(
        self,
        meter: MeteringPoint,
        windows: list[tuple[Participant, date, date | None]],
        allocation_mode: str = AllocationMode.PERSONAL,
    ) -> None:
        """Replace ``meter``'s assignments with ``windows``, in order."""
        # The seed window moves every quarter. Drop the prior windows first so
        # the new ones cannot trip the model's non-overlap guard on save.
        with transaction.atomic():
            MeteringPointAssignment.objects.filter(metering_point=meter).delete()
            for participant, valid_from, valid_to in windows:
                MeteringPointAssignment.objects.create(
                    metering_point=meter,
                    participant=participant,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    allocation_mode=allocation_mode,
                )

    def _seed_tariffs(
        self, zev: Zev, valid_from: date, specs: list | None = None,
        *, history_start: date | None = None,
    ) -> None:
        """Rebuild a ZEV's seeded tariffs, optionally from caller-supplied specs.

        The main community uses the default list below; the second community
        passes its own so the two demo cost structures stay different.
        """
        # Only fields that differ from the model defaults are written out;
        # ``_create_tariff_version`` supplies the rest (None prices, empty
        # notes, unrestricted band windows).
        tariff_specs = specs if specs is not None else [
            {
                "name": "Local Solar Energy",
                "category": TariffCategory.ENERGY,
                "billing_mode": BillingMode.ENERGY,
                "energy_type": EnergyType.LOCAL,
                "notes": "Base local energy tariff for participant consumption within the ZEV.",
                "periods": [
                    {
                        "period_type": PeriodType.FLAT,
                        "price_chf_per_kwh": Decimal("0.18000"),
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
                "notes": "Credit for exported surplus energy.",
                "periods": [
                    {
                        "period_type": PeriodType.FLAT,
                        "price_chf_per_kwh": Decimal("0.08500"),
                    }
                ],
            },
            {
                "name": "Levies on Grid Energy",
                "category": TariffCategory.LEVIES,
                "billing_mode": BillingMode.PERCENTAGE_OF_ENERGY,
                "energy_type": EnergyType.GRID,
                "notes": "Sample levy priced as a percentage of the grid base tariff.",
                "periods": [
                    {
                        "period_type": PeriodType.FLAT,
                        "percentage": Decimal("18.00"),
                    }
                ],
                # A percentage version carries no price of its own, so its chart
                # is the *derived* effective price — it moves both when the
                # percentage changes and when the grid tariffs it references do.
                "price_history": [
                    {"prices": [Decimal("15.00")]},
                    {"prices": [Decimal("16.50")]},
                ],
            },
            {
                "name": "Metering Service Fee",
                "category": TariffCategory.METERING,
                "billing_mode": BillingMode.MONTHLY_FEE,
                "fixed_price_chf": Decimal("8.50"),
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

            # Unchanged tariffs must cover the paid historical invoices too.
            first_day = min(valid_from, history_start) if history_start and not history else valid_from
            self._create_tariff_version(zev, spec, {}, valid_from=first_day, valid_to=None)

    def _seed_dynamic_tariff(self, zev: Zev, *, end_date: date) -> Tariff:
        """A local price series for the tariff drawer and platform console.

        The tariff starts in the quarter after every seeded invoice period, so
        it must be reset before invoices are rebuilt. Prices depend only on the
        civil date and time, so overlapping re-seeds store identical points.
        """
        valid_from = quarter_start(end_date)
        source, _ = DynamicTariffSource.objects.update_or_create(
            url=DEMO_DYNAMIC_SOURCE_URL,
            api_version=DynamicApiVersion.V2_0_0,
            tariff_type=DynamicTariffType.GRID,
            tariff_name="demo-grid",
            defaults={
                "label": DEMO_DYNAMIC_SOURCE_LABEL,
                "enabled": False,
                "supports_range": False,
                "query_tariff_type": "grid",
            },
        )
        points = []
        # Include tomorrow, as a day-ahead source would. UTC iteration preserves
        # all 92/100 quarter-hours on Swiss daylight-saving transition days.
        for timestamp in self._iter_quarters(valid_from, end_date + timedelta(days=1)):
            local = wall_clock(timestamp)
            hour = local.hour + local.minute / 60.0
            variation = ((local.date().toordinal() % 7) - 3) * 0.002
            price = (
                0.045 + variation
                + 0.060 * self._gaussian(hour, 7.5, 1.6)
                + 0.095 * self._gaussian(hour, 19.0, 2.0)
                - 0.075 * self._gaussian(hour, 13.0, 2.2)
            )
            points.append(PricePoint(
                valid_from=timestamp,
                valid_to=timestamp + timedelta(minutes=15),
                price_chf_per_kwh=Decimal(str(price)).quantize(Decimal("0.00001")),
            ))
        store_points(source, points)
        seeded_at = datetime.now(dt_timezone.utc)
        source.last_fetch_status = FetchStatus.OK
        source.last_fetch_at = seeded_at
        source.last_success_at = seeded_at
        source.last_fetch_error = ""
        source.recovery_from = None
        source.save(update_fields=[
            "last_fetch_status", "last_fetch_at", "last_success_at",
            "last_fetch_error", "recovery_from", "updated_at",
        ])
        # Rebuild rather than upsert, for the reasons given in _seed_tariffs: a
        # demo session may have added versions or switched it back to bands.
        Tariff.objects.filter(zev=zev, name=DEMO_DYNAMIC_TARIFF_NAME).delete()
        return Tariff.objects.create(
            zev=zev,
            name=DEMO_DYNAMIC_TARIFF_NAME,
            category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            dynamic_source=source,
            valid_from=valid_from,
            notes="Synthetic prices generated by seed_demo; no API calls.",
        )

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
            energy_type=spec.get("energy_type"),
            fixed_price_chf=prices.get("fixed_price_chf", spec.get("fixed_price_chf")),
            notes=spec.get("notes", ""),
            valid_from=valid_from,
            valid_to=valid_to,
        )

        # A percentage-of-energy tariff's bands carry a percentage, not a
        # price; every other billing mode's bands carry a price. ``prices``
        # overrides the band's own value by position, same as before bands
        # existed for percentage tariffs too.
        is_percentage = spec["billing_mode"] == BillingMode.PERCENTAGE_OF_ENERGY
        band_prices = prices.get("prices")
        for band, period in enumerate(spec["periods"]):
            if band_prices:
                value = band_prices[band]
            elif is_percentage:
                value = period["percentage"]
            else:
                value = period["price_chf_per_kwh"]
            TariffPeriod.objects.create(
                tariff=tariff,
                period_type=period["period_type"],
                price_chf_per_kwh=None if is_percentage else value,
                percentage=value if is_percentage else None,
                time_from=period.get("time_from"),
                time_to=period.get("time_to"),
                weekdays=period.get("weekdays", ""),
            )
        return tariff

    def _seed_invoices(
        self,
        zev: Zev,
        period_start: date,
        period_end: date,
        *,
        closed: bool = False,
    ) -> list[Invoice]:
        """Generate invoices for a billing period and vary their statuses.

        The caller owns deleting the ZEV's earlier invoices first (``handle``
        and ``_seed_second_community`` both wipe before seeding):
        ``generate_invoice`` refuses to overwrite anything past draft, so
        leaving earlier invoices behind would make a second ``seed_demo`` run
        fail.

        By default the run advances through draft/approved/sent so the invoice
        list exercises those badges. ``closed=True`` instead settles the whole
        period: every invoice is paid except the last, which is cancelled as if
        issued in error — the counterpart for the UI's paid/cancelled badges,
        filters and period totals.
        """
        invoices, failures = generate_invoices_for_zev(zev, period_start, period_end)
        if failures:
            raise CommandError(
                f"invoice seeding failed for {len(failures)} participant(s): {failures}"
            )
        invoices.sort(key=lambda invoice: invoice.invoice_number)

        if closed:
            for invoice in invoices:
                invoice.status = InvoiceStatus.PAID
                invoice.sent_at = period_start_dt(period_end)
                invoice.save(update_fields=["status", "sent_at"])
            if len(invoices) > 1:
                invoices[-1].status = InvoiceStatus.CANCELLED
                invoices[-1].save(update_fields=["status"])
            return invoices

        # First stays DRAFT; the rest advance so the list shows a realistic mix.
        if len(invoices) > 1:
            invoices[1].status = InvoiceStatus.APPROVED
            invoices[1].save(update_fields=["status"])
        if len(invoices) > 2:
            invoices[2].status = InvoiceStatus.SENT
            invoices[2].sent_at = period_start_dt(period_end)
            invoices[2].save(update_fields=["status", "sent_at"])

        return invoices

    def _seed_paid_year_invoices(
        self,
        zev: Zev,
        *,
        year: int,
        skip_period: tuple[date, date] | None = None,
    ) -> list[Invoice]:
        """Settle a whole billing year so the producer's tax overview has data.

        One run per quarter of ``year`` (the flagship bills quarterly), every
        invoice paid as if long collected — the reports page defaults to the
        previous calendar year, and its financial summary reads paid invoices
        only, so draft/sent rows would leave it empty. A quarter overlapping
        ``skip_period`` (the flagship's open period, seeded separately in
        draft/approved/sent) is left alone, and quarters without readings are
        skipped rather than billed against nothing.
        """
        seeded: list[Invoice] = []
        for month in (1, 4, 7, 10):
            period_start = date(year, month, 1)
            if month == 10:
                period_end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                period_end = date(year, month + 3, 1) - timedelta(days=1)
            if skip_period is not None and not (
                period_end < skip_period[0] or period_start > skip_period[1]
            ):
                continue
            window_start, window_end = period_window(period_start, period_end)
            if not MeterReading.objects.filter(
                metering_point__zev=zev, timestamp__gte=window_start, timestamp__lt=window_end,
            ).exists():
                continue
            invoices, failures = generate_invoices_for_zev(zev, period_start, period_end)
            if failures:
                raise CommandError(
                    f"settled-year invoice seeding failed for {len(failures)} "
                    f"participant(s): {failures}"
                )
            for invoice in invoices:
                invoice.status = InvoiceStatus.PAID
                invoice.sent_at = period_start_dt(period_end)
                invoice.save(update_fields=["status", "sent_at"])
            seeded.extend(invoices)
        return seeded

    def _upsert_vat_rates(self) -> None:
        """Install the standard Swiss VAT history if it is missing.

        Invoices are priced with the rate active at their period end. A demo
        database with no VatRate rows bills 0 % VAT everywhere, so the VAT line
        on the VAT-registered company ZEV (Sonnenfirma AG) — and the embedded
        VAT on the VAT-inclusive STWEG — would never show up.

        The contract is deliberately "install missing defaults": VAT rates an
        admin added or edited in a shared development database are left alone.
        Deleting and recreating the canonical rows on every run could not only
        undo that work but *collide* with it — a preserved custom open-ended
        rate overlapping the recreated 2024 row would trip the model's
        overlap guard and fail the whole seed.
        """
        for rate, valid_from, valid_to in (
            (Decimal("0.0770"), date(2018, 1, 1), date(2023, 12, 31)),
            (Decimal("0.0810"), date(2024, 1, 1), None),
        ):
            if not active_during(VatRate.objects.all(), valid_from, valid_to or date.max).exists():
                VatRate.objects.create(rate=rate, valid_from=valid_from, valid_to=valid_to)

    def _enable_demo_feature_flags(self) -> None:
        """Turn on features that ship off by default, so a fresh demo is
        immediately playable rather than looking half-finished.

        Off by default in production because the feature is new or
        experimental, not because the demo shouldn't showcase it — the
        opposite of a real deployment's stance, so this is flipped
        explicitly rather than inherited from ``FeatureFlag.DEFAULTS``.
        Unconditional, unlike ``_upsert_vat_rates``: an admin manually
        disabling it during a previous demo session should not survive a
        re-seed, since the whole point of ``seed_demo`` is a known-good,
        immediately-playable state.
        """
        FeatureFlag.sync_defaults()
        FeatureFlag.objects.filter(name=FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED).update(enabled=True)

    def _seed_history_readings(
        self,
        *,
        history_start: date,
        stop_date: date,
        meters: list[tuple[MeteringPoint, str, Profile]],
    ) -> None:
        """Fill hourly readings from ``history_start`` up to ``stop_date``.

        One row per hour per meter; each hour sums the four 15-minute profile
        samples so volumes stay consistent with the finer-resolution rows
        seeded later. The buffer is flushed as it fills, so the list never
        grows to the whole year in memory.
        """
        if stop_date <= history_start:
            return

        readings: list[MeterReading] = []

        def flush() -> None:
            if readings:
                MeterReading.objects.bulk_create(readings, batch_size=5000)
                readings.clear()

        # Real UTC hours across Swiss civil days (23/24/25 of them); the
        # profiles read the Swiss wall clock (ADR 0026).
        hour_start = period_start_dt(history_start)
        stop = period_start_dt(stop_date)
        while hour_start < stop:
            day_index = (civil_date(hour_start) - history_start).days
            quarters = [wall_clock(hour_start + timedelta(minutes=15 * quarter)) for quarter in range(4)]
            for meter, direction, profile in meters:
                total = sum(float(profile(local, day_index)) for local in quarters)
                readings.append(
                    MeterReading(
                        metering_point=meter,
                        timestamp=hour_start,
                        energy_kwh=Decimal(str(round(total, 4))),
                        direction=direction,
                        resolution=ReadingResolution.HOURLY,
                        import_source=ImportSource.MANUAL,
                    )
                )
            if len(readings) >= 5000:
                flush()
            hour_start += timedelta(hours=1)
        flush()

    def _seed_meter_readings(
        self,
        *,
        start_date: date,
        end_date: date,
        meters: list[tuple[MeteringPoint, str, Profile]],
    ) -> date:
        """Fill ``meters`` between ``start_date`` and ``end_date`` (inclusive).

        The last ``FINE_READING_DAYS`` days keep the 15-minute rows the live
        views show; everything older inside the window is hourly, each hour
        summing the four quarter-hour samples it replaces — so per-day volumes
        are identical across the boundary. The boundary is derived from
        ``end_date`` once and shared by every meter, and the hourly rows use
        the same day anchor as the quarter-hour ones, so the profile does not
        jump where the resolution changes.

        Callers own deleting earlier readings (see the flagship wipe in
        ``handle`` and the equivalent in ``_seed_second_community``); this
        method only inserts, flushing its buffer as it fills so a long window
        never builds the whole list in memory.

        Returns the date the 15-minute tail starts on.
        """
        fine_from = end_date - timedelta(days=FINE_READING_DAYS - 1)
        if fine_from <= start_date:
            # A window shorter than the fine tail stays entirely 15-minute.
            fine_from = start_date

        self._seed_history_readings(
            history_start=start_date, stop_date=fine_from, meters=meters,
        )
        readings: list[MeterReading] = []

        def flush() -> None:
            if readings:
                MeterReading.objects.bulk_create(readings, batch_size=5000)
                readings.clear()

        for timestamp in self._iter_quarters(fine_from, end_date):
            day_index = (civil_date(timestamp) - start_date).days
            local = wall_clock(timestamp)
            for meter, direction, profile in meters:
                readings.append(
                    MeterReading(
                        metering_point=meter,
                        timestamp=timestamp,
                        energy_kwh=profile(local, day_index),
                        direction=direction,
                        resolution=ReadingResolution.FIFTEEN_MIN,
                        import_source=ImportSource.MANUAL,
                    )
                )
            if len(readings) >= 5000:
                flush()
        flush()
        return fine_from

    def _iter_quarters(self, start_date: date, end_date: date):
        """Real UTC quarter-hours covering the Swiss civil days, DST included."""
        current, stop = period_window(start_date, end_date)
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

    def _common_area_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        """Allgemeinstrom: a small round-the-clock base plus stairwell lighting.

        Deliberately flat and modest next to the apartment profiles — a common
        area draws continuously (lift standby, cellar, ventilation) and peaks
        when people come and go after dark, rather than tracking a household's
        cooking and laundry. Weekends are slightly quieter, not busier.
        """
        hour = timestamp.hour + timestamp.minute / 60.0
        weekday = timestamp.weekday()
        base = 0.022
        # Stairwell and entrance lighting: morning before daylight, evening after.
        morning = 0.028 * self._gaussian(hour, 6.8, 1.1)
        evening = 0.046 * self._gaussian(hour, 19.8, 2.6)
        # Laundry room, mostly used on weekdays and Saturday mornings.
        laundry = (0.034 if weekday < 6 else 0.0) * self._gaussian(hour, 10.5, 1.8)
        variation = ((day_index % 7) - 3) * 0.0012
        quieter_at_weekends = 0.94 if weekday >= 5 else 1.0
        value = (base + morning + evening + laundry + variation) * quieter_at_weekends
        return Decimal(str(round(max(value, 0.004), 4)))

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

    def _studio_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        """An office: busy on weekday working hours, a standby base otherwise."""
        hour = timestamp.hour + timestamp.minute / 60.0
        base = 0.018
        office = (0.210 if timestamp.weekday() < 5 else 0.0) * self._gaussian(hour, 12.5, 3.0)
        variation = ((day_index % 5) - 2) * 0.0020
        return Decimal(str(round(max(base + office + variation, 0.005), 4)))

    def _ev_charger_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        """A car charged on some evenings; the charger idles in between."""
        hour = timestamp.hour + timestamp.minute / 60.0
        if day_index % 3 != 0:
            return Decimal("0.002")
        charging = 1.6 * self._gaussian(hour, 20.5, 1.4)
        return Decimal(str(round(max(charging, 0.002), 4)))

    def _producer_kwh(self, timestamp: datetime, day_index: int) -> Decimal:
        hour = timestamp.hour + timestamp.minute / 60.0
        daylight_curve = self._gaussian(hour, 13.0, 2.7)
        season = self._seasonal_solar_factor(timestamp.timetuple().tm_yday)
        cloud = self._cloud_factor(day_index)
        shoulder = 0.92 + ((day_index % 7) * 0.018)
        weekend = 1.03 if timestamp.weekday() >= 5 else 1.0
        value = 1.25 * daylight_curve * season * cloud * shoulder * weekend
        return Decimal(str(round(max(value, 0.0), 4)))
