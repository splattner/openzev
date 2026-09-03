"""Importing tariffs from a grid operator's Art. 7b StromVV publication.

The stakes here are not "did the JSON parse" but "does the number that ends up
on every participant's invoice match the one the operator published". So the
tests lean on a *real* published document (InfraWerke Münsingen's 2027 tariffs,
fetched from the operator's own website and checked in unchanged) alongside
synthetic ones for the shapes that document happens not to contain, and the
mapping is asserted through to what the billing engine actually reads back.
"""
import json
import urllib.error
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from unittest import mock

import datetime as datetime_module

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from invoices.engine import _get_tariff_price
from tariffs.importers.planner import CandidateStatus, Selection, apply_import, plan_import
from tariffs.importers.remote import TariffFetchError, fetch_tariff_document
from tariffs.importers.vse_json import (
    FEE_BILLING_MODE_OPTIONS,
    TariffDocumentError,
    parse_document,
)
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory
from testing.helpers import authenticate, make_user
from zev.models import Zev


PREVIEW_URL = "/api/v1/tariffs/imports/vse/preview/"
APPLY_URL = "/api/v1/tariffs/imports/vse/apply/"

#: A document actually published by a Swiss grid operator, not a fixture written
#: to match this importer. Provenance is in the spec.
REAL_DOCUMENT_PATH = Path(__file__).resolve().parent / "testdata" / "vse_tariffs_iwm_2027.json"


def real_document() -> dict:
    with REAL_DOCUMENT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def document(*entries) -> dict:
    return {"dsoName": "Test Werke", "dsoNumber": 10355012345, "tariffs": list(entries)}


def entry(**overrides) -> dict:
    base = {
        "tariffName": "Netznutzung Basis",
        "tariffType": "grid",
        "tariffForm": "constant",
        "startDate": "2027-01-01",
        "endDate": "2027-12-31",
        "customerType": "Haushalte",
        "prices": {"energy": [{"from": "00:00", "to": "00:00", "price": 0.1, "priceUnit": "CHF/kWh"}]},
    }
    base.update(overrides)
    return base


def by_name(parsed, name):
    return next(candidate for candidate in parsed.candidates if candidate.name == name)


class RealDocumentTests(SimpleTestCase):
    """The published document has to come through without hand-holding."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parsed = parse_document(real_document())

    def test_every_published_entry_is_understood(self):
        self.assertEqual(self.parsed.errors, [])
        self.assertEqual(self.parsed.dso_name, "InfraWerkeMünsingen")
        self.assertTrue(all(candidate.is_importable for candidate in self.parsed.candidates))

    def test_only_the_operators_own_default_product_is_pre_selected(self):
        """23 published entries become 35 candidates; a ZEV needs a handful.

        Pre-ticking everything would be worse than pre-ticking nothing, so the
        recommendation follows the operator's own ``standardBasegroup`` flag.
        """
        recommended = sorted(c.name for c in self.parsed.candidates if c.recommended)

        self.assertEqual(recommended, [
            "Energie Basis Infra Blau (Arbeitspreis)",
            "Netznutzung Basis (Arbeitspreis)",
            "Netznutzung Basis (Grundpreis)",
        ])

    def test_a_base_and_energy_entry_becomes_two_tariffs(self):
        """One published tariff, two OpenZEV tariffs: ``Tariff`` carries a
        single ``billing_mode``, so a fee and a per-kWh price cannot share one."""
        fee = by_name(self.parsed, "Netznutzung Basis (Grundpreis)")
        energy = by_name(self.parsed, "Netznutzung Basis (Arbeitspreis)")

        self.assertEqual(fee.billing_mode, BillingMode.SHARED_MONTHLY_FEE)
        self.assertEqual(fee.fixed_price_chf, Decimal("7.00"))
        self.assertEqual(fee.category, TariffCategory.GRID_FEES)
        self.assertEqual(energy.billing_mode, BillingMode.ENERGY)
        self.assertEqual(energy.energy_type, EnergyType.GRID)
        self.assertEqual([p.price_chf_per_kwh for p in energy.periods], [Decimal("0.10600")])

    def test_a_three_window_two_price_tariff_maps_onto_HT_and_NT(self):
        """The document prices day, evening and night separately but with only
        two distinct prices, so it fits OpenZEV's HT/NT pair — the evening and
        night windows both become NT rows."""
        candidate = by_name(self.parsed, "Netznutzung Leistung (Arbeitspreis)")

        self.assertEqual(
            [(p.period_type, str(p.price_chf_per_kwh), p.time_from, p.time_to) for p in candidate.periods],
            [
                (PeriodType.HIGH, "0.07300", time(7, 0), time(21, 0)),
                (PeriodType.LOW, "0.06800", time(21, 0), time(23, 59)),
                (PeriodType.LOW, "0.06800", time(0, 0), time(7, 0)),
            ],
        )
        self.assertTrue(any("higher price" in warning for warning in candidate.warnings))

    def test_a_municipal_surcharge_becomes_its_own_levy(self):
        candidate = by_name(
            self.parsed,
            "Abgaben und Leistungen an das Gemeinwesen für alle Tarife – Münsingen (BFS 616) (Arbeitspreis)",
        )

        self.assertEqual(candidate.category, TariffCategory.LEVIES)
        self.assertEqual(candidate.periods[0].price_chf_per_kwh, Decimal("0.01500"))

    def test_power_and_reactive_charges_are_reported_not_dropped(self):
        candidate = by_name(self.parsed, "Netznutzung Leistung (Grundpreis)")

        self.assertTrue(any("power/demand charge" in warning for warning in candidate.warnings))
        self.assertTrue(any("reactive-power" in warning for warning in candidate.warnings))

    def test_components_priced_at_zero_are_offered_but_never_pre_selected(self):
        candidate = by_name(self.parsed, "Netznutzung OEB (Grundpreis)")

        self.assertEqual(candidate.fixed_price_chf, Decimal("0.00"))
        self.assertTrue(candidate.is_importable)
        self.assertFalse(candidate.recommended)


class DefensiveParsingTests(SimpleTestCase):
    """The OpenAPI definition is normative, but the NNMV-CH annex example has
    already drifted from it, so published documents follow either."""

    def test_swiss_dotted_dates_are_accepted(self):
        parsed = parse_document(document(entry(startDate="01.01.2027", endDate="31.12.2027")))

        self.assertEqual(parsed.candidates[0].valid_from, date(2027, 1, 1))
        self.assertEqual(parsed.candidates[0].valid_to, date(2027, 12, 31))

    def test_a_bare_number_is_accepted_as_a_base_price(self):
        """The annex prints ``"base": 5.52``; the OpenAPI models an object."""
        parsed = parse_document(document(entry(prices={"base": 5.52})))

        self.assertEqual(by_name(parsed, "Netznutzung Basis (Grundpreis)").fixed_price_chf, Decimal("5.52"))

    def test_weekday_and_month_codes_are_case_insensitive(self):
        parsed = parse_document(document(entry(prices={"energy": [
            {"months": ["JAN", "feb", "Mar", "apr", "may", "jun",
                        "jul", "aug", "sep", "oct", "nov", "dec"],
             "weekdays": ["mo", "TU", "We", "th", "fr", "sa", "su"],
             "from": "00:00", "to": "00:00", "price": 0.1, "priceUnit": "CHF/kWh"},
        ]})))

        self.assertTrue(parsed.candidates[0].is_importable)

    def test_a_window_that_wraps_past_midnight_is_split_in_two(self):
        """``TariffPeriod`` matches ``from <= t < to``; one row spanning
        midnight would match nothing at all."""
        parsed = parse_document(document(entry(tariffForm="multilevel", prices={"energy": [
            {"from": "06:00", "to": "22:00", "price": 0.2, "priceUnit": "CHF/kWh"},
            {"from": "22:00", "to": "06:00", "price": 0.1, "priceUnit": "CHF/kWh"},
        ]})))

        periods = parsed.candidates[0].periods

        self.assertEqual(
            [(p.period_type, p.time_from, p.time_to) for p in periods],
            [
                (PeriodType.HIGH, time(6, 0), time(22, 0)),
                (PeriodType.LOW, time(22, 0), time(23, 59)),
                (PeriodType.LOW, time(0, 0), time(6, 0)),
            ],
        )

    def test_one_bad_entry_does_not_block_the_rest(self):
        """A malformed entry for a customer group this ZEV does not use must
        not cost it the one it does."""
        parsed = parse_document(document(
            entry(tariffName="Broken", startDate="not-a-date"),
            entry(tariffName="Good"),
        ))

        self.assertEqual([error["tariff"] for error in parsed.errors], ["Broken"])
        self.assertEqual([c.name for c in parsed.candidates], ["Good (Arbeitspreis)"])

    def test_a_document_without_a_tariffs_array_is_rejected_outright(self):
        with self.assertRaises(TariffDocumentError):
            parse_document({"dsoName": "Test"})

    def test_a_json_array_is_rejected_outright(self):
        with self.assertRaises(TariffDocumentError):
            parse_document([{"tariffName": "x"}])

    def test_duplicate_tariff_names_are_reported_and_only_the_first_kept(self):
        parsed = parse_document(document(entry(), entry()))

        self.assertEqual(len(parsed.candidates), 1)
        self.assertIn("Duplicate tariff name", parsed.errors[0]["error"])


class UnsupportedConstructTests(SimpleTestCase):
    """Everything the model cannot express has to say so per entry. Silently
    dropping a construct is how a tariff ends up priced at the wrong number."""

    def test_more_than_two_distinct_prices_in_one_season_are_blocked(self):
        parsed = parse_document(document(entry(tariffForm="multilevel", prices={"energy": [
            {"from": "00:00", "to": "08:00", "price": 0.1, "priceUnit": "CHF/kWh"},
            {"from": "08:00", "to": "16:00", "price": 0.2, "priceUnit": "CHF/kWh"},
            {"from": "16:00", "to": "23:59", "price": 0.3, "priceUnit": "CHF/kWh"},
        ]})))

        self.assertIn("3 different energy prices", parsed.candidates[0].blocked_reason)

    def test_a_dynamic_tariff_is_blocked_and_names_its_url(self):
        parsed = parse_document(document(entry(
            tariffForm="dynamic",
            prices={"dynamic": {"url": "https://api.example.ch/v1/tariffs"}},
        )))

        self.assertIn("https://api.example.ch/v1/tariffs", parsed.candidates[0].blocked_reason)

    def test_an_energy_price_in_the_wrong_unit_is_blocked(self):
        parsed = parse_document(document(entry(prices={"energy": [
            {"from": "00:00", "to": "00:00", "price": 7, "priceUnit": "CHF/kW/M"},
        ]})))

        self.assertIn("CHF/kW/M", parsed.candidates[0].blocked_reason)

    def test_a_base_price_in_the_wrong_unit_is_blocked(self):
        parsed = parse_document(document(entry(prices={"base": {"price": 90, "priceUnit": "CHF/kW/Y"}})))

        self.assertIn("CHF/kW/Y", parsed.candidates[0].blocked_reason)

    def test_a_negative_price_is_blocked(self):
        parsed = parse_document(document(entry(prices={"base": {"price": -1, "priceUnit": "CHF/M"}})))

        self.assertIn("negative", parsed.candidates[0].blocked_reason)

    def test_excess_precision_is_rounded_and_said_so(self):
        parsed = parse_document(document(entry(prices={"energy": [
            {"from": "00:00", "to": "00:00", "price": 0.1234567, "priceUnit": "CHF/kWh"},
        ]})))

        candidate = parsed.candidates[0]

        self.assertEqual(candidate.periods[0].price_chf_per_kwh, Decimal("0.12346"))
        self.assertTrue(any("rounded" in warning for warning in candidate.warnings))


WINTER = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
SUMMER = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]


class SeasonalPriceTests(SimpleTestCase):
    """Winter/summer pricing is ordinary in Switzerland, and it combines with
    HT/NT — so the flat/HT/NT question has to be answered per season, not once
    for the whole entry."""

    def _parse(self, energy):
        return parse_document(document(entry(tariffForm="multilevel", prices={"energy": energy})))

    def test_a_two_season_flat_tariff_becomes_one_band_per_season(self):
        parsed = self._parse([
            {"months": WINTER, "from": "00:00", "to": "00:00", "price": 0.2, "priceUnit": "CHF/kWh"},
            {"months": SUMMER, "from": "00:00", "to": "00:00", "price": 0.1, "priceUnit": "CHF/kWh"},
        ])
        candidate = parsed.candidates[0]

        self.assertTrue(candidate.is_importable)
        self.assertEqual(
            [(p.period_type, str(p.price_chf_per_kwh), p.months) for p in candidate.periods],
            [
                (PeriodType.FLAT, "0.20000", "1,2,3,10,11,12"),
                (PeriodType.FLAT, "0.10000", "4,5,6,7,8,9"),
            ],
        )

    def test_four_distinct_prices_fit_when_they_are_two_per_season(self):
        """Globally there are four prices, which the old rule refused. But a
        winter band never competes with a summer one, so each season has its
        own HT and NT slot."""
        parsed = self._parse([
            {"months": WINTER, "from": "07:00", "to": "22:00", "price": 0.24, "priceUnit": "CHF/kWh"},
            {"months": WINTER, "from": "22:00", "to": "07:00", "price": 0.18, "priceUnit": "CHF/kWh"},
            {"months": SUMMER, "from": "07:00", "to": "22:00", "price": 0.14, "priceUnit": "CHF/kWh"},
            {"months": SUMMER, "from": "22:00", "to": "07:00", "price": 0.11, "priceUnit": "CHF/kWh"},
        ])
        candidate = parsed.candidates[0]

        self.assertTrue(candidate.is_importable, candidate.blocked_reason)
        self.assertEqual(
            [(p.period_type, str(p.price_chf_per_kwh), p.months) for p in candidate.periods],
            [
                (PeriodType.HIGH, "0.24000", "1,2,3,10,11,12"),
                (PeriodType.LOW, "0.18000", "1,2,3,10,11,12"),
                (PeriodType.LOW, "0.18000", "1,2,3,10,11,12"),
                (PeriodType.HIGH, "0.14000", "4,5,6,7,8,9"),
                (PeriodType.LOW, "0.11000", "4,5,6,7,8,9"),
                (PeriodType.LOW, "0.11000", "4,5,6,7,8,9"),
            ],
        )

    def test_a_year_round_band_stores_no_months_at_all(self):
        """Blank already means "every month" to the engine, so a non-seasonal
        import is byte-for-byte what it was before seasons existed."""
        parsed = self._parse([
            {"months": [], "from": "00:00", "to": "00:00", "price": 0.1, "priceUnit": "CHF/kWh"},
        ])

        self.assertEqual(parsed.candidates[0].periods[0].months, "")

    def test_seasons_that_overlap_are_refused_rather_than_guessed(self):
        """Grouping is by exact month set, so two groups sharing months would
        be mapped as if they never competed — and the engine would price those
        months from whichever sorted first."""
        parsed = self._parse([
            {"months": ["Jan", "Feb", "Mar"], "from": "00:00", "to": "00:00",
             "price": 0.2, "priceUnit": "CHF/kWh"},
            {"months": ["Mar", "Apr"], "from": "00:00", "to": "00:00",
             "price": 0.1, "priceUnit": "CHF/kWh"},
        ])

        self.assertIn("apply in the same months", parsed.candidates[0].blocked_reason)

    def test_a_year_only_partly_priced_is_imported_but_flagged(self):
        parsed = self._parse([
            {"months": WINTER, "from": "00:00", "to": "00:00", "price": 0.2, "priceUnit": "CHF/kWh"},
        ])
        candidate = parsed.candidates[0]

        self.assertTrue(candidate.is_importable)
        self.assertTrue(any("only 6 of 12 months" in w for w in candidate.warnings))

    def test_the_HT_NT_heuristic_is_reported_per_season(self):
        """The two seasons pick different prices, so one warning naming one
        pair would be telling the user about half of what happened."""
        parsed = self._parse([
            {"months": WINTER, "from": "07:00", "to": "22:00", "price": 0.24, "priceUnit": "CHF/kWh"},
            {"months": WINTER, "from": "22:00", "to": "07:00", "price": 0.18, "priceUnit": "CHF/kWh"},
            {"months": SUMMER, "from": "07:00", "to": "22:00", "price": 0.14, "priceUnit": "CHF/kWh"},
            {"months": SUMMER, "from": "22:00", "to": "07:00", "price": 0.11, "priceUnit": "CHF/kWh"},
        ])
        heuristic = [w for w in parsed.candidates[0].warnings if "higher price" in w]

        self.assertEqual(len(heuristic), 2)
        self.assertTrue(any("0.24" in w for w in heuristic))
        self.assertTrue(any("0.14" in w for w in heuristic))


class PlanningTests(TestCase):
    """What an import would do to *this* ZEV, which is where a careless import
    doubles somebody's bill."""

    def setUp(self):
        self.owner = make_user("vse_plan_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Plan ZEV", owner=self.owner, zev_type="zev")

    def _apply(self, doc, selections=None, url="https://example.ch/tariffs.json"):
        parsed = parse_document(doc)
        if selections is None:
            selections = [Selection(c.key) for c in parsed.candidates if c.is_importable]
        return apply_import(
            zev=self.zev, document=parsed, selections=selections,
            source_url=url, imported_on=date(2026, 9, 2),
        )

    def test_a_name_the_zev_has_never_seen_is_new(self):
        planned = plan_import(self.zev.id, parse_document(document(entry())))

        self.assertEqual(planned[0].status, CandidateStatus.NEW)

    def test_importing_the_same_document_twice_changes_nothing(self):
        """Idempotency is not a nicety: the second run must not trip the
        same-name overlap guard, and must not create a second copy that would
        bill twice."""
        doc = document(entry())
        self._apply(doc)

        planned = plan_import(self.zev.id, parse_document(doc))
        report, created = self._apply(doc)

        self.assertEqual(planned[0].status, CandidateStatus.DUPLICATE)
        self.assertEqual(created, [])
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(Tariff.objects.filter(zev=self.zev).count(), 1)

    def test_next_years_document_appends_a_version_and_closes_the_previous_one(self):
        self._apply(document(entry(prices={"energy": [
            {"from": "00:00", "to": "00:00", "price": 0.10, "priceUnit": "CHF/kWh"},
        ]})))
        next_year = document(entry(startDate="2028-01-01", endDate="2028-12-31", prices={"energy": [
            {"from": "00:00", "to": "00:00", "price": 0.12, "priceUnit": "CHF/kWh"},
        ]}))

        planned = plan_import(self.zev.id, parse_document(next_year))
        self._apply(next_year)

        self.assertEqual(planned[0].status, CandidateStatus.NEW_VERSION)
        versions = list(Tariff.objects.filter(zev=self.zev).order_by("valid_from"))
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].valid_to, date(2027, 12, 31))
        self.assertEqual(versions[1].valid_from, date(2028, 1, 1))
        self.assertEqual(versions[1].periods.first().price_chf_per_kwh, Decimal("0.12000"))

    def test_an_open_ended_predecessor_is_closed_rather_than_colliding(self):
        """A hand-entered tariff usually has no end date, so the first import
        under that name has to truncate it or the overlap guard rejects it."""
        Tariff.objects.create(
            zev=self.zev, name="Netznutzung Basis (Arbeitspreis)",
            category=TariffCategory.GRID_FEES, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2025, 1, 1),
        )

        report, _ = self._apply(document(entry()))

        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.created), 1)
        predecessor = Tariff.objects.get(zev=self.zev, valid_from=date(2025, 1, 1))
        self.assertEqual(predecessor.valid_to, date(2026, 12, 31))

    def test_a_name_that_already_means_something_else_is_a_conflict(self):
        """Versions of one tariff must agree on what the tariff is; importing
        a grid fee over a local-energy tariff of the same name would make the
        series incoherent."""
        Tariff.objects.create(
            zev=self.zev, name="Netznutzung Basis (Arbeitspreis)",
            category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.LOCAL, valid_from=date(2025, 1, 1),
        )

        planned = plan_import(self.zev.id, parse_document(document(entry())))
        report, created = self._apply(document(entry()))

        self.assertEqual(planned[0].status, CandidateStatus.CONFLICT)
        self.assertEqual(created, [])
        self.assertIn("already exists in this ZEV", report.skipped[0]["reason"])

    def test_only_the_selected_candidates_are_created(self):
        parsed = parse_document(real_document())
        wanted = [c for c in parsed.candidates if c.recommended]

        report, _ = apply_import(
            zev=self.zev, document=parsed, selections=[Selection(c.key) for c in wanted],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 2),
        )

        self.assertEqual(len(report.created), 3)
        self.assertEqual(Tariff.objects.filter(zev=self.zev).count(), 3)

    def test_a_blocked_candidate_is_never_written_even_if_asked_for(self):
        parsed = parse_document(document(entry(
            tariffForm="dynamic", prices={"dynamic": {"url": "https://x.ch"}},
        )))

        report, created = apply_import(
            zev=self.zev, document=parsed, selections=[Selection(parsed.candidates[0].key)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 2),
        )

        self.assertEqual(created, [])
        self.assertIn("Dynamic tariffs", report.skipped[0]["reason"])

    def test_two_versions_inside_one_document_are_chained_not_collided(self):
        """A document that publishes this year and next year under one name has
        to leave a closed timeline, which means each write plans against the
        one before it rather than against a list read once up front."""
        doc = document(
            entry(startDate="2027-01-01", endDate="2027-12-31"),
            entry(startDate="2028-01-01", endDate="2028-12-31", prices={"energy": [
                {"from": "00:00", "to": "00:00", "price": 0.12, "priceUnit": "CHF/kWh"},
            ]}),
        )

        report, _ = self._apply(doc)

        self.assertEqual(report.errors, [])
        versions = list(Tariff.objects.filter(zev=self.zev).order_by("valid_from"))
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].valid_to, date(2027, 12, 31))
        self.assertEqual(versions[1].valid_from, date(2028, 1, 1))

    def test_a_key_that_is_no_longer_in_the_document_is_an_error(self):
        report, _ = apply_import(
            zev=self.zev, document=parse_document(document(entry())),
            selections=[Selection("Something Else@2027-01-01")],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 2),
        )

        self.assertIn("Run the preview again", report.errors[0]["error"])

    def test_the_source_url_is_recorded_on_every_imported_tariff(self):
        """A year later, whoever looks at the tariff has to be able to tell
        where the number came from without asking anyone."""
        self._apply(document(entry()), url="https://werke.example.ch/tarife.json")

        notes = Tariff.objects.get(zev=self.zev).notes

        self.assertIn("https://werke.example.ch/tarife.json", notes)
        self.assertIn("Test Werke", notes)
        self.assertIn("Haushalte", notes)


class BillingModeChoiceTests(TestCase):
    """A published base price is an amount per month; *who* pays it is the one
    thing the document cannot say. The preview asks rather than guessing, so
    the offered set and what the write path accepts must be the same set."""

    def setUp(self):
        self.owner = make_user("vse_mode_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Mode ZEV", owner=self.owner, zev_type="zev")

    def _fee_and_energy(self):
        parsed = parse_document(document(entry(prices={
            "base": {"price": 7, "priceUnit": "CHF/M"},
            "energy": [{"from": "00:00", "to": "00:00", "price": 0.1, "priceUnit": "CHF/kWh"}],
        })))
        return (
            parsed,
            by_name(parsed, "Netznutzung Basis (Grundpreis)"),
            by_name(parsed, "Netznutzung Basis (Arbeitspreis)"),
        )

    def test_a_fee_offers_the_three_monthly_modes_and_defaults_to_the_shared_one(self):
        """Shared leads because the operator bills the community once for its
        connection; billing it per participant would collect it N times over."""
        _, fee, _ = self._fee_and_energy()

        self.assertEqual(fee.billing_mode, BillingMode.SHARED_MONTHLY_FEE)
        self.assertEqual(fee.billing_mode_options, FEE_BILLING_MODE_OPTIONS)

    def test_no_yearly_mode_is_ever_offered(self):
        """The yearly modes read ``fixed_price_chf`` as a per-year amount, so
        offering one for a CHF/M price would bill a twelfth of it."""
        self.assertEqual(
            [mode for mode in FEE_BILLING_MODE_OPTIONS if "yearly" in mode], []
        )

    def test_an_energy_candidate_offers_no_choice(self):
        _, _, energy = self._fee_and_energy()

        self.assertEqual(energy.billing_mode_options, ())

    def test_the_chosen_mode_is_what_gets_created(self):
        """A vZEV whose participants each hold their own contract picks the
        plain monthly fee."""
        parsed, fee, _ = self._fee_and_energy()

        report, _ = apply_import(
            zev=self.zev, document=parsed,
            selections=[Selection(fee.key, billing_mode=BillingMode.MONTHLY_FEE)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 3),
        )

        self.assertEqual(report.created[0]["billing_mode"], BillingMode.MONTHLY_FEE)
        self.assertEqual(Tariff.objects.get(zev=self.zev).billing_mode, BillingMode.MONTHLY_FEE)

    def test_a_per_meter_charge_can_be_billed_per_metering_point(self):
        """The Messtarif is charged per meter, which is exactly the case the
        shared default gets wrong."""
        parsed, fee, _ = self._fee_and_energy()

        apply_import(
            zev=self.zev, document=parsed,
            selections=[Selection(fee.key, billing_mode=BillingMode.PER_METERING_POINT_MONTHLY_FEE)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 3),
        )

        self.assertEqual(
            Tariff.objects.get(zev=self.zev).billing_mode,
            BillingMode.PER_METERING_POINT_MONTHLY_FEE,
        )

    def test_a_mode_that_was_never_offered_is_refused(self):
        """The candidate's own option list is the allowlist, so a client cannot
        reach a mode the preview did not render."""
        parsed, fee, _ = self._fee_and_energy()

        report, created = apply_import(
            zev=self.zev, document=parsed,
            selections=[Selection(fee.key, billing_mode=BillingMode.SHARED_YEARLY_FEE)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 3),
        )

        self.assertEqual(created, [])
        self.assertIn("not a billing mode this tariff can be imported as", report.errors[0]["error"])

    def test_an_override_on_an_energy_tariff_is_refused_not_ignored(self):
        """Silently billing per kWh what somebody asked to be billed monthly is
        exactly what this feature must not do."""
        parsed, _, energy = self._fee_and_energy()

        report, created = apply_import(
            zev=self.zev, document=parsed,
            selections=[Selection(energy.key, billing_mode=BillingMode.MONTHLY_FEE)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 3),
        )

        self.assertEqual(created, [])
        self.assertEqual(len(report.errors), 1)


class EnginePricingTests(TestCase):
    """The point of the import is that the engine reads back what the operator
    published — asserting on the stored rows alone would not show that."""

    def setUp(self):
        self.owner = make_user("vse_price_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Pricing ZEV", owner=self.owner, zev_type="zev")
        parsed = parse_document(real_document())
        wanted = by_name(parsed, "Netznutzung Leistung (Arbeitspreis)")
        apply_import(
            zev=self.zev, document=parsed, selections=[Selection(wanted.key)],
            source_url="https://example.ch/t.json", imported_on=date(2026, 9, 2),
        )
        self.tariff = Tariff.objects.get(zev=self.zev)

    def _price_at(self, hour, minute=0):
        stamp = datetime_module.datetime(2027, 3, 15, hour, minute)
        return _get_tariff_price(self.tariff, stamp)

    def test_daytime_consumption_is_priced_at_the_high_band(self):
        self.assertEqual(self._price_at(12), Decimal("0.07300"))

    def test_night_and_evening_consumption_are_priced_at_the_low_band(self):
        self.assertEqual(self._price_at(3), Decimal("0.06800"))
        self.assertEqual(self._price_at(22), Decimal("0.06800"))

    def test_the_band_boundaries_fall_the_way_the_document_wrote_them(self):
        self.assertEqual(self._price_at(6, 59), Decimal("0.06800"))
        self.assertEqual(self._price_at(7, 0), Decimal("0.07300"))
        self.assertEqual(self._price_at(20, 59), Decimal("0.07300"))
        self.assertEqual(self._price_at(21, 0), Decimal("0.06800"))


class FakeResponse:
    def __init__(self, body: bytes, content_length=None):
        self.body = body
        self.headers = {"Content-Length": content_length} if content_length else {}

    def read(self, size=None):
        return self.body[:size] if size is not None else self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout=None):
        return self.response


def fake_public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def fake_private_dns(*args, **kwargs):
    """An internal name resolving into RFC1918 space — what the guard is for."""
    return [(2, 1, 6, "", ("10.0.0.5", 80))]


class RemoteFetchTests(SimpleTestCase):
    """The URL comes from the user — there is no registry of these documents —
    so this is a server-side request to an address a user chose."""

    def test_a_url_resolving_into_private_space_is_refused(self):
        """Otherwise an authenticated user could aim the import at an internal
        service and read the answer back through the preview."""
        with self.assertRaises(TariffFetchError) as caught:
            fetch_tariff_document("http://127.0.0.1:8000/tariffs.json")

        self.assertIn("does not resolve to a public address", str(caught.exception))

    def test_localhost_is_refused_by_name_too(self):
        """Asserting on the message, not just the exception: without the
        address check this URL still fails, but with a connection error, which
        would make the test pass while the guard was gone."""
        with self.assertRaises(TariffFetchError) as caught:
            fetch_tariff_document("http://localhost/tariffs.json")

        self.assertIn("does not resolve to a public address", str(caught.exception))

    def test_the_refusal_does_not_report_what_the_name_resolved_to(self):
        """Blocking the request but naming the address turns a failed import
        into a way of mapping internal DNS: aim it at an internal hostname and
        read the answer off the error. The address is logged, not returned.

        The resolver is faked rather than pointed at ``localhost``: which of
        ``127.0.0.1`` and ``::1`` that yields depends on the host, so asserting
        on a literal made the test pass here and fail on CI.
        """
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_private_dns):
            with self.assertRaises(TariffFetchError) as caught:
                fetch_tariff_document("http://internal-db.corp/tariffs.json")

        self.assertNotIn("10.0.0.5", str(caught.exception))
        self.assertIn("internal-db.corp", str(caught.exception))
        self.assertIn("10.0.0.5", caught.exception.log_detail)

    def test_socket_errors_are_logged_rather_than_returned(self):
        """A raw URLError carries TLS and library detail about the deployment,
        none of which helps the user fix their URL."""
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_public_dns), \
             mock.patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer "
                "certificate (_ssl.c:1006) /etc/ssl/internal-ca.pem"
            )
            with self.assertRaises(TariffFetchError) as caught:
                fetch_tariff_document("https://werke.example.ch/tarife.json")

        self.assertNotIn("_ssl.c", str(caught.exception))
        self.assertNotIn("internal-ca.pem", str(caught.exception))
        self.assertIn("internal-ca.pem", caught.exception.log_detail)

    def test_only_http_and_https_are_fetched(self):
        with self.assertRaises(TariffFetchError) as caught:
            fetch_tariff_document("file:///etc/passwd")

        self.assertIn("Only http and https", str(caught.exception))

    def test_a_redirect_into_private_space_is_refused_too(self):
        """A public URL that 302s to the metadata service would otherwise walk
        straight past the check on the original URL."""
        from tariffs.importers.remote import _ValidatingRedirectHandler

        handler = _ValidatingRedirectHandler()

        with self.assertRaises(TariffFetchError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/latest/")

    def test_an_oversized_document_is_refused_even_without_a_content_length(self):
        oversized = b"x" * (6 * 1024 * 1024)
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_public_dns), \
             mock.patch("urllib.request.build_opener", return_value=FakeOpener(FakeResponse(oversized))):
            with self.assertRaises(TariffFetchError) as caught:
                fetch_tariff_document("https://werke.example.ch/tarife.json")

        self.assertIn("larger than", str(caught.exception))

    def test_the_operators_own_error_text_is_not_echoed_back(self):
        """The status code is what the user needs; the reason phrase comes from
        a server we were merely pointed at."""
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_public_dns), \
             mock.patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://werke.example.ch/tarife.json", 403, "Forbidden by WAF rule 42",
                {}, None,
            )
            with self.assertRaises(TariffFetchError) as caught:
                fetch_tariff_document("https://werke.example.ch/tarife.json")

        self.assertIn("403", str(caught.exception))
        self.assertNotIn("WAF rule 42", str(caught.exception))

    def test_a_web_page_instead_of_json_gives_an_actionable_message(self):
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_public_dns), \
             mock.patch("urllib.request.build_opener",
                        return_value=FakeOpener(FakeResponse(b"<!doctype html><html>"))):
            with self.assertRaises(TariffFetchError) as caught:
                fetch_tariff_document("https://werke.example.ch/tarife.json")

        self.assertIn("not valid JSON", str(caught.exception))

    def test_the_digest_covers_the_bytes_that_were_downloaded(self):
        body = json.dumps(document(entry())).encode()
        with mock.patch("tariffs.importers.remote.socket.getaddrinfo", fake_public_dns), \
             mock.patch("urllib.request.build_opener", return_value=FakeOpener(FakeResponse(body))):
            payload, digest = fetch_tariff_document("https://werke.example.ch/tarife.json")

        from hashlib import sha256
        self.assertEqual(digest, sha256(body).hexdigest())
        self.assertEqual(payload["dsoName"], "Test Werke")


class ImportEndpointTests(TestCase):
    URL = "https://werke.example.ch/tarife.json"

    def setUp(self):
        self.owner = make_user("vse_api_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="API ZEV", owner=self.owner, zev_type="zev")
        self.client = APIClient()
        authenticate(self.client, self.owner)
        self.document = document(entry())
        self.digest = "a" * 64

    def _patched(self):
        return mock.patch(
            "tariffs.views_import.fetch_tariff_document",
            return_value=(self.document, self.digest),
        )

    def _preview(self, **overrides):
        payload = {"zev": str(self.zev.id), "url": self.URL}
        payload.update(overrides)
        with self._patched():
            return self.client.post(PREVIEW_URL, payload, format="json")

    def _apply(self, keys, modes=None, **overrides):
        modes = modes or {}
        payload = {
            "zev": str(self.zev.id), "url": self.URL,
            "selections": [
                {"key": key, **({"billing_mode": modes[key]} if key in modes else {})}
                for key in keys
            ],
            "document_digest": self.digest,
        }
        payload.update(overrides)
        with self._patched():
            return self.client.post(APPLY_URL, payload, format="json")

    def test_preview_requires_authentication(self):
        self.assertEqual(APIClient().post(PREVIEW_URL, {}, format="json").status_code, 401)

    def test_participants_cannot_import_tariffs(self):
        client = APIClient()
        authenticate(client, make_user("vse_api_participant", UserRole.PARTICIPANT))

        response = client.post(PREVIEW_URL, {"zev": str(self.zev.id)}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_an_owner_cannot_import_into_somebody_elses_zev(self):
        """The role check alone would let any ZEV owner write tariffs into any
        other ZEV."""
        other = make_user("vse_api_other_owner", UserRole.ZEV_OWNER)
        other_zev = Zev.objects.create(name="Other ZEV", owner=other, zev_type="zev")

        response = self.client.post(PREVIEW_URL, {"zev": str(other_zev.id)}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_preview_reports_the_candidates_without_writing_anything(self):
        response = self._preview()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["dso_name"], "Test Werke")
        self.assertEqual(body["document_digest"], self.digest)
        self.assertEqual(body["candidates"][0]["status"], CandidateStatus.NEW)
        self.assertEqual(Tariff.objects.count(), 0)

    def test_preview_falls_back_to_the_url_stored_on_the_zev(self):
        self.zev.tariff_source_url = self.URL
        self.zev.save()

        with self._patched() as fetch:
            response = self.client.post(PREVIEW_URL, {"zev": str(self.zev.id)}, format="json")

        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(self.URL)

    def test_a_zev_with_no_url_is_told_what_is_missing(self):
        response = self.client.post(PREVIEW_URL, {"zev": str(self.zev.id)}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("No tariff URL is set", response.json()["detail"])

    def test_a_fetch_failure_is_reported_as_a_message_not_a_500(self):
        with mock.patch("tariffs.views_import.fetch_tariff_document",
                        side_effect=TariffFetchError("The operator's server answered 404 Not Found.")):
            response = self.client.post(PREVIEW_URL, {"zev": str(self.zev.id), "url": self.URL},
                                        format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("404", response.json()["detail"])

    def test_apply_creates_only_what_was_ticked_and_remembers_the_url(self):
        key = self._preview().json()["candidates"][0]["key"]

        response = self._apply([key])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["created"]), 1)
        self.zev.refresh_from_db()
        self.assertEqual(self.zev.tariff_source_url, self.URL)
        self.assertEqual(Tariff.objects.filter(zev=self.zev).count(), 1)

    def test_apply_is_audited_with_its_source(self):
        key = self._preview().json()["candidates"][0]["key"]

        self._apply([key])

        event = AuditEvent.objects.get(action_type="tariff.import_vse")
        self.assertEqual(event.zev_id, self.zev.id)
        self.assertEqual(event.metadata_json["source_url"], self.URL)
        self.assertEqual(
            event.metadata_json["created"],
            [{"name": "Netznutzung Basis (Arbeitspreis)", "billing_mode": "energy"}],
        )

    def test_a_document_that_changed_since_the_preview_is_refused(self):
        """Apply re-fetches rather than trusting tariff data from the browser,
        so the digest is what ties the confirmation to what was reviewed."""
        key = self._preview().json()["candidates"][0]["key"]

        response = self._apply([key], document_digest="b" * 64)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Tariff.objects.count(), 0)

    def test_the_preview_tells_the_client_which_billing_modes_it_may_offer(self):
        """The frontend renders exactly this list, so a mode can never appear in
        the picker that the apply step would then refuse."""
        self.document = document(entry(prices={"base": {"price": 7, "priceUnit": "CHF/M"}}))

        candidate = self._preview().json()["candidates"][0]

        self.assertEqual(candidate["billing_mode"], "shared_monthly_fee")
        self.assertEqual(
            candidate["billing_mode_options"],
            ["shared_monthly_fee", "monthly_fee", "per_metering_point_monthly_fee"],
        )

    def test_a_billing_mode_picked_in_the_preview_reaches_the_created_tariff(self):
        self.document = document(entry(prices={"base": {"price": 7, "priceUnit": "CHF/M"}}))
        key = self._preview().json()["candidates"][0]["key"]

        response = self._apply([key], modes={key: "monthly_fee"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["created"][0]["billing_mode"], "monthly_fee")
        self.assertEqual(Tariff.objects.get(zev=self.zev).billing_mode, "monthly_fee")

    def test_the_url_is_not_stored_when_the_user_declines(self):
        key = self._preview().json()["candidates"][0]["key"]

        self._apply([key], remember_url=False)

        self.zev.refresh_from_db()
        self.assertEqual(self.zev.tariff_source_url, "")
