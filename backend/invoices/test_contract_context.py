import io
import re
from datetime import date
from decimal import Decimal
from hashlib import sha256
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import TestCase

import pytest

from accounts.models import AppSettings, UserRole, VatRate
from audit.models import AuditEvent
from invoices.contract_pdf import (
    CONTRACT_TEMPLATE_NAME,
    _build_contract_context,
    _render_contract_html,
    generate_contract_pdf,
    issue_contract_pdf,
)
from invoices.contract_translations import CONTRACT_TRANSLATIONS
from invoices.models import ContractIssue
from invoices.test_helpers import make_participant, make_user, make_zev
from invoices.template_context import build_sample_contract_context
from tariffs.models import BillingMode, EnergyType, TariffPeriod
from testing.factories import TariffFactory, assignment_for, flat_tariff
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Zev


_STYLE_BLOCK_RE = re.compile(r"<style>.*?</style>", re.DOTALL)


def _render_contract_markup(participant) -> str:
    """Render the contract template to markup, stylesheets removed.

    Both the shared design base and the contract's own ``<style>`` block are
    stripped so structural assertions cannot pass on CSS selectors alone
    (mirrors ``test_pdf._render_invoice_markup``).
    """
    context = _build_contract_context(participant)
    html = render_to_string(CONTRACT_TEMPLATE_NAME, context)
    return _STYLE_BLOCK_RE.sub("", html)


class ContractPdfContextTests(TestCase):
    def setUp(self):
        self.owner = make_user("contract_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Contract ZEV")
        self.participant = make_participant(self.zev, first="Future", last="Participant")

    def test_future_metering_point_assignments_are_included_in_contract_context(self):
        current_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-CURRENT",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        future_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-FUTURE",
            meter_type=MeteringPointType.PRODUCTION,
        )
        past_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-PAST",
            meter_type=MeteringPointType.CONSUMPTION,
        )

        MeteringPointAssignment.objects.create(
            metering_point=current_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=future_mp,
            participant=self.participant,
            valid_from=date(2026, 6, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=past_mp,
            participant=self.participant,
            valid_from=date(2025, 1, 1),
            valid_to=date(2026, 2, 28),
        )

        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = date(2026, 4, 15)
            context = _build_contract_context(self.participant)

        self.assertEqual(
            [mp.meter_id for mp in context["consumption_mps"]],
            ["CH-CONTRACT-CURRENT"],
        )
        self.assertEqual(
            [mp.meter_id for mp in context["production_mps"]],
            ["CH-CONTRACT-FUTURE"],
        )

    def test_bidirectional_meter_appears_in_consumption_and_production_lists(self):
        """Bidirectional meters allocate as both consumption and production
        (see allocation.read_model), so the contract inventory must list them
        in both meter groups too."""
        bidirectional_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-CONTRACT-BIDIR",
            meter_type=MeteringPointType.BIDIRECTIONAL,
        )
        MeteringPointAssignment.objects.create(
            metering_point=bidirectional_mp,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

        context = _build_contract_context(self.participant)

        self.assertEqual(
            [mp.meter_id for mp in context["consumption_mps"]],
            ["CH-CONTRACT-BIDIR"],
        )
        self.assertEqual(
            [mp.meter_id for mp in context["production_mps"]],
            ["CH-CONTRACT-BIDIR"],
        )


class ContractPdfPaymentTermsTests(TestCase):
    """Regression: the contract PDF hardcoded 'payable within 30 days'
    independently of the invoice PDF's own copy of the same bug (#365 follow-up)."""

    def setUp(self):
        self.owner = make_user("contract_terms_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Contract Terms ZEV")
        self.participant = make_participant(self.zev, first="Terms", last="Participant")

    def test_payment_terms_unit_follows_the_zevs_configured_term(self):
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["zev"].payment_term_days, 45)
        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")

    def test_payment_terms_unit_uses_the_default_thirty_days(self):
        context = _build_contract_context(self.participant)

        self.assertEqual(context["zev"].payment_term_days, 30)
        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")

    def test_payment_terms_unit_is_grammatically_singular_for_one_day(self):
        self.zev.payment_term_days = 1
        self.zev.save(update_fields=["payment_term_days"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "Tag ab Rechnungsdatum")

    def test_payment_terms_unit_is_translated_per_zev_invoice_language(self):
        self.zev.payment_term_days = 45
        self.zev.invoice_language = "en"
        self.zev.save(update_fields=["payment_term_days", "invoice_language"])

        context = _build_contract_context(self.participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "days from invoice date")

    def test_building_one_contracts_context_does_not_leak_into_another(self):
        """CONTRACT_TRANSLATIONS is a module-level constant shared by every
        contract; resolving payment_terms_unit must copy it, not mutate it in
        place, or one ZEV's term would bleed into the next contract rendered
        in the same process."""
        self.zev.payment_term_days = 45
        self.zev.save(update_fields=["payment_term_days"])
        _build_contract_context(self.participant)

        other_owner = make_user("contract_terms_owner_other", UserRole.ZEV_OWNER)
        other_zev = make_zev(other_owner, "Other Contract Terms ZEV")
        other_participant = make_participant(other_zev, first="Other", last="Participant")

        context = _build_contract_context(other_participant)

        self.assertEqual(context["tr"]["payment_terms_unit"], "Tage ab Rechnungsdatum")


class ContractPdfContextFieldsTests(TestCase):
    """The redesigned contract renders dates like the invoice and reflects
    participation start, the active VAT rate and a short document id."""

    def setUp(self):
        self.owner = make_user("ctx_fields_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Context Fields ZEV")
        self.participant = make_participant(self.zev, first="Ctx", last="Participant")

    def _context(self, today=date(2026, 4, 15)):
        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = today
            return _build_contract_context(self.participant)

    def test_contract_date_follows_app_settings_date_format(self):
        settings = AppSettings.load()
        settings.date_format_short = AppSettings.SHORT_DATE_YYYY_MM_DD
        settings.save()
        self.assertEqual(self._context()["contract_date"], "2026-04-15")

    def test_contract_date_defaults_to_dd_mm_yyyy(self):
        self.assertEqual(self._context()["contract_date"], "15.04.2026")

    def test_participation_start_uses_earliest_assignment(self):
        mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-EARLIEST-1", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=self.participant, valid_from=date(2025, 6, 1)
        )
        self.assertEqual(self._context()["participation_start"], "01.06.2025")

    def test_participation_start_falls_back_to_participant_valid_from(self):
        self.assertEqual(self._context()["participation_start"], "01.01.2026")

    def test_vat_rate_display_shows_active_rate_when_liable(self):
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=date(2026, 1, 1))
        self.zev.vat_number = "CHE-123.456.789"
        self.zev.save(update_fields=["vat_number"])
        self.assertEqual(self._context()["vat_rate_display"], "8.10 %")

    def test_vat_rate_display_empty_when_not_liable(self):
        self.assertEqual(self._context()["vat_rate_display"], "")

    def test_vat_rate_display_empty_when_liable_without_active_rate(self):
        self.zev.vat_number = "CHE-123.456.789"
        self.zev.save(update_fields=["vat_number"])
        self.assertEqual(self._context()["vat_rate_display"], "")

    def test_document_id_is_short_and_stable(self):
        document_id = self._context()["document_id"]
        self.assertTrue(document_id.startswith("CTR-"))
        self.assertEqual(len(document_id), 12, "CTR- plus eight hex chars")


class ContractPdfTariffRuleTests(TestCase):
    """The clause-5 tariff rule and the green-box line follow the tariff mode:
    a percentage-of-grid-tariff tariff prints the formula with the configured
    percentage, a fixed tariff falls back to the flat-rate clause, and the
    tariff table documents each tariff's validity period."""

    def setUp(self):
        self.owner = make_user("tariff_rule_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Tariff Rule ZEV")
        self.participant = make_participant(self.zev, first="Rule", last="Participant")

    def _percentage_tariff(self, *, valid_to=date(2026, 12, 31),
                           notes="EKZ Standardprodukt der Grundversorgung"):
        # Grid base of 22.50 Rp/kWh: 80% of it gives the 18.00 Rp/kWh headline.
        flat_tariff(self.zev, energy_type=EnergyType.GRID, price="0.22500")
        return TariffFactory(
            zev=self.zev,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,
            percentage=Decimal("80.00"),
            valid_from=date(2026, 1, 1),
            valid_to=valid_to,
            notes=notes,
        )

    def _context(self, today=date(2026, 4, 15)):
        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = today
            return _build_contract_context(self.participant)

    def _markup(self, today=date(2026, 4, 15)):
        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = today
            return _render_contract_markup(self.participant)

    def test_percentage_tariff_row_carries_pct_price_validity_and_notes(self):
        self._percentage_tariff()
        row = self._context()["local_tariff_rows"][0]

        self.assertEqual(row["pct"], "80.00")
        self.assertEqual(row["rate_rp"], "18.00")  # 80% of the 22.50 Rp/kWh grid base
        self.assertEqual(row["unit"], "Rp./kWh")
        self.assertEqual(row["validity"], "01.01.2026 – 31.12.2026")
        self.assertEqual(row["notes"], "EKZ Standardprodukt der Grundversorgung")

    def test_percentage_tariff_prints_formula_rule_reference_and_green_box_line(self):
        self._percentage_tariff()
        context = self._context()

        self.assertIn("80.00 %", context["tariff_rule"])
        self.assertIn("externen Standardprodukts", context["tariff_rule"])
        self.assertEqual(
            context["tariff_pct_line"],
            "= 80.00 % des Standardtarifs des Netzbetreibers",
        )
        self.assertEqual(
            context["tariff_reference_product"], "EKZ Standardprodukt der Grundversorgung"
        )

        markup = self._markup()
        self.assertIn("Tarifregel.", markup)
        self.assertIn("80.00 % des für den Teilnehmer massgebenden", markup)
        self.assertIn("= 80.00 % des Standardtarifs des Netzbetreibers", markup)
        self.assertIn("Referenzprodukt:", markup)
        self.assertIn("EKZ Standardprodukt der Grundversorgung", markup)
        self.assertIn("01.01.2026 – 31.12.2026", markup)  # validity column

    def test_flat_tariff_falls_back_to_fixed_rate_clause_without_pct_line(self):
        flat = flat_tariff(self.zev, price="0.18000")
        context = self._context()

        self.assertIsNone(context["local_tariff_rows"][0]["pct"])
        self.assertEqual(context["tariff_rule"], context["tr"]["clause_tariff_rule_flat"])
        self.assertIsNone(context["tariff_pct_line"])
        self.assertIsNone(context["tariff_reference_product"])

        markup = self._markup()
        self.assertIn("fester Tarif", markup)
        self.assertIn(flat.name, markup)  # the green box hints the tariff name
        self.assertNotIn("Referenzprodukt:", markup)

    def test_percentage_tariff_without_grid_base_shows_bare_percentage_without_unit(self):
        TariffFactory(
            zev=self.zev,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY,
            energy_type=EnergyType.LOCAL,
            percentage=Decimal("80.00"),
            valid_from=date(2026, 1, 1),
        )
        row = self._context()["local_tariff_rows"][0]

        self.assertEqual(row["rate_rp"], "80.00%")
        self.assertEqual(row["unit"], "")

        markup = self._markup()
        self.assertIn('<span class="amount">80.00%</span>', markup)

    def test_open_ended_percentage_tariff_renders_open_validity(self):
        self._percentage_tariff(valid_to=None)
        context = self._context()

        self.assertIsNone(context["local_tariff_rows"][0]["valid_to"])
        self.assertEqual(context["local_tariff_rows"][0]["validity"], "ab 01.01.2026")

    def test_no_local_tariff_prints_no_rule_and_placeholder_amount(self):
        context = self._context()

        self.assertEqual(context["local_tariff_rows"], [])
        self.assertIsNone(context["tariff_rule"])
        self.assertIsNone(context["tariff_pct_line"])

        markup = self._markup()
        self.assertIn("tariff-empty", markup)
        self.assertNotIn("Tarifregel.", markup)

    def test_empty_notes_render_blank_box_not_placeholder_prose(self):
        """Empty notes must never print the placeholder prose on a real
        contract — the German example text is not a contract term."""
        markup = self._markup()

        self.assertEqual(self._context()["local_tariff_notes"], "")
        self.assertIn("freetext-box", markup)
        self.assertNotIn("freetext-placeholder", markup)
        self.assertNotIn("Beispiel: Der Tarif", markup)


class ContractPdfSeasonalTariffTests(TestCase):
    """A seasonal tariff has two or more bands sharing a period_type. The table
    used to pick the first of them, which printed one price on a contract with
    nothing to say it only applies for half the year."""

    def setUp(self):
        self.owner = make_user("seasonal_contract_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Seasonal Contract ZEV")
        self.participant = make_participant(self.zev, first="Season", last="Participant")
        self.tariff = TariffFactory(
            zev=self.zev,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )

    def _rows(self):
        with patch("invoices.contract_pdf.timezone.localdate") as mocked:
            mocked.return_value = date(2026, 4, 15)
            return _build_contract_context(self.participant)["local_tariff_rows"]

    def test_each_season_gets_its_own_row_naming_its_months(self):
        TariffPeriod.objects.create(
            tariff=self.tariff, period_type="flat",
            price_chf_per_kwh=Decimal("0.25"), months="1,2,3,10,11,12",
        )
        TariffPeriod.objects.create(
            tariff=self.tariff, period_type="flat",
            price_chf_per_kwh=Decimal("0.15"), months="4,5,6,7,8,9",
        )

        rows = self._rows()

        self.assertEqual(
            sorted((row["rate_rp"], row["rate_description"]) for row in rows),
            [
                ("15.00", "Einheitstarif (Apr.\u2013Sept.)"),
                ("25.00", "Einheitstarif (Okt.\u2013März)"),
            ],
        )

    def test_a_year_round_tariff_reads_exactly_as_it_did_before(self):
        """No season, no qualifier — the overwhelming majority of contracts."""
        TariffPeriod.objects.create(
            tariff=self.tariff, period_type="flat", price_chf_per_kwh=Decimal("0.20"),
        )

        rows = self._rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rate_description"], "Einheitstarif")

    def test_a_three_band_tariff_prints_every_band(self):
        """The table used to pick HIGH and LOW by name, so a third band was
        dropped from the contract entirely — a participant would have been
        billed at a price their contract never mentioned."""
        for price, start, end, label in (
            ("0.09", "00:00", "07:00", ""),
            ("0.24", "07:00", "17:00", "Spitzenlast"),
            ("0.15", "17:00", "23:59", ""),
        ):
            TariffPeriod.objects.create(
                tariff=self.tariff, period_type="band", price_chf_per_kwh=Decimal(price),
                time_from=start, time_to=end, label=label,
            )

        rows = self._rows()

        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [(row["rate_rp"], row["rate_description"]) for row in rows],
            [
                ("9.00", "00:00\u201307:00"),
                ("24.00", "Spitzenlast"),
                ("15.00", "17:00\u201323:59"),
            ],
        )

    def test_both_bands_of_a_season_are_printed(self):
        """Four rows from four bands: winter HT, winter NT, summer HT, summer NT."""
        for months, ht, nt in (("1,2,3,10,11,12", "0.28", "0.22"), ("4,5,6,7,8,9", "0.18", "0.14")):
            TariffPeriod.objects.create(
                tariff=self.tariff, period_type="high", price_chf_per_kwh=Decimal(ht),
                time_from="07:00", time_to="22:00", months=months,
            )
            TariffPeriod.objects.create(
                tariff=self.tariff, period_type="low", price_chf_per_kwh=Decimal(nt),
                time_from="22:00", time_to="23:59", months=months,
            )

        rows = self._rows()

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["rate_description"] for row in rows},
            {
                "HT (Hochtarif) (Okt.\u2013März)", "NT (Niedertarif) (Okt.\u2013März)",
                "HT (Hochtarif) (Apr.\u2013Sept.)", "NT (Niedertarif) (Apr.\u2013Sept.)",
            },
        )


class ContractIssuanceTests(TestCase):
    """Issued contracts are frozen, versioned snapshots: unchanged re-downloads
    reuse the stored PDF, data changes mint a new numbered version, and the
    document number is a per-ZEV sequence."""

    def setUp(self):
        self.owner = make_user("issue_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Issuance ZEV")
        self.participant = make_participant(self.zev, first="Issue", last="Participant")
        flat_tariff(self.zev, price="0.18000")

    def _issue(self, today=date(2026, 4, 15)):
        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = today
            return issue_contract_pdf(self.participant)

    @pytest.mark.slow
    def test_first_download_issues_version_one_with_sequence_number(self):
        issue, created = self._issue()

        self.assertTrue(created)
        self.assertEqual(issue.version, 1)
        self.assertEqual(issue.document_number, "CTR-2026-0001")
        self.assertTrue(issue.pdf.startswith(b"%PDF"))
        self.assertEqual(len(issue.context_hash), 64)
        self.zev.refresh_from_db()
        self.assertEqual(self.zev.contract_counter, 2)

    @pytest.mark.slow
    def test_unchanged_redownload_reuses_the_frozen_snapshot(self):
        first, _ = self._issue()
        second, created = self._issue()

        self.assertFalse(created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.pdf, first.pdf)
        self.assertEqual(ContractIssue.objects.count(), 1)

    @pytest.mark.slow
    def test_redownload_on_a_later_calendar_day_reuses_the_frozen_snapshot(self):
        """The issue date is frozen into the snapshot (``rendered_on``): a
        re-download reproduces the issued document at that date, so the passing
        of a calendar day alone must never mint a new version."""
        first, created = self._issue(today=date(2026, 4, 15))
        self.assertTrue(created)

        second, created = self._issue(today=date(2026, 8, 11))

        self.assertFalse(created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.pdf, first.pdf)
        self.assertEqual(ContractIssue.objects.count(), 1)

    def test_concurrent_identical_issuances_mint_a_single_version(self):
        """A competing issuance of identical content that commits while this
        request waits is reused, not re-minted — the row becomes visible under
        the Zev lock and the post-lock comparison reproduces it."""
        def _competing_issuer(year=None):
            # Simulate the other request's identical first issuance having
            # landed while this one was inside the locked section.
            if not ContractIssue.objects.filter(participant=self.participant).exists():
                html = _render_contract_html(
                    self.participant,
                    document_id="CTR-2026-0001",
                    as_of=date(2026, 4, 15),
                )
                ContractIssue.objects.create(
                    zev=self.zev,
                    participant=self.participant,
                    version=1,
                    document_number="CTR-2026-0001",
                    language="de",
                    rendered_on=date(2026, 4, 15),
                    context_hash=sha256(html.encode("utf-8")).hexdigest(),
                    pdf=b"%PDF-competing",
                )
            return f"CTR-{year}-0002"

        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = date(2026, 4, 15)
            with patch.object(Zev, "next_contract_number", side_effect=_competing_issuer):
                issue, created = issue_contract_pdf(self.participant)

        self.assertFalse(created)
        self.assertEqual(issue.version, 1)
        self.assertEqual(issue.document_number, "CTR-2026-0001")
        self.assertEqual(ContractIssue.objects.count(), 1)

        # The number minted before the competitor's identical snapshot became
        # visible is never reused — but the gap is written to the audit
        # stream so the sequence stays explainable.
        gap = AuditEvent.objects.get(action_type="contract.number_gap")
        self.assertEqual(gap.metadata_json["skipped_document_number"], "CTR-2026-0002")
        self.assertEqual(gap.metadata_json["reused_document_number"], "CTR-2026-0001")
        self.assertEqual(gap.source, "system")

    @pytest.mark.slow
    def test_contract_issues_survive_participant_and_zev_deletion(self):
        """Issued contracts are an immutable archive: deleting the participant
        or the ZEV retains the snapshot (SET_NULL), so a signed document is
        never destroyed by account cleanup."""
        issue, _ = self._issue()
        issue_id = issue.pk

        self.participant.delete()
        self.zev.delete()

        archived = ContractIssue.objects.get(pk=issue_id)
        self.assertIsNone(archived.participant_id)
        self.assertIsNone(archived.zev_id)
        self.assertEqual(archived.version, 1)
        self.assertEqual(archived.document_number, "CTR-2026-0001")
        self.assertTrue(archived.pdf.startswith(b"%PDF"))

    @pytest.mark.slow
    def test_data_change_bumps_version_and_number(self):
        first, _ = self._issue()
        flat_tariff(self.zev, price="0.19000")  # a second local tariff changes the render
        second, created = self._issue()

        self.assertTrue(created)
        self.assertEqual(second.version, 2)
        self.assertEqual(second.document_number, "CTR-2026-0002")
        self.assertNotEqual(second.pdf, first.pdf)

    @pytest.mark.slow
    def test_document_number_sequence_is_per_zev(self):
        other_owner = make_user("issue_owner_other", UserRole.ZEV_OWNER)
        other_zev = make_zev(other_owner, "Other Issuance ZEV")
        other_participant = make_participant(other_zev, first="Other", last="Participant")
        flat_tariff(other_zev, price="0.20000")
        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = date(2026, 4, 15)
            other_issue, _ = issue_contract_pdf(other_participant)

        self.assertEqual(other_issue.document_number, "CTR-2026-0001")
        self.assertEqual(self._issue()[0].document_number, "CTR-2026-0001")

    @pytest.mark.slow
    def test_new_issue_renders_the_stable_document_number_in_the_pdf(self):
        issue, _ = self._issue()

        context = _build_contract_context(self.participant, document_id=issue.document_number)
        html = render_to_string(CONTRACT_TEMPLATE_NAME, context)
        self.assertIn("CTR-2026-0001", html)

    @pytest.mark.slow
    def test_concurrent_first_issuances_get_distinct_versions(self):
        """A request that read ``latest`` before a competing first issuance
        committed must derive the version from the row visible under the Zev
        row lock — not crash on the (participant, version) constraint."""
        def _competing_issuer(year=None):
            # Simulate the other request's commit having landed while this one
            # waited on the row lock: the re-read inside the lock must see it.
            if not ContractIssue.objects.filter(participant=self.participant).exists():
                ContractIssue.objects.create(
                    zev=self.zev,
                    participant=self.participant,
                    version=1,
                    document_number="CTR-2026-0001",
                    language="de",
                    context_hash="0" * 64,
                    pdf=b"%PDF-competing",
                )
            return f"CTR-{year}-0002"

        with patch("invoices.contract_pdf.timezone.localdate") as mocked_localdate:
            mocked_localdate.return_value = date(2026, 4, 15)
            with patch.object(Zev, "next_contract_number", side_effect=_competing_issuer):
                issue, created = issue_contract_pdf(self.participant)

        self.assertTrue(created)
        self.assertEqual(issue.version, 2)
        self.assertEqual(issue.document_number, "CTR-2026-0002")

    def test_issue_zev_is_derived_from_the_participant(self):
        """``ContractIssue.zev`` is a denormalized copy of ``participant.zev``;
        save() derives it so the two can never disagree."""
        other_owner = make_user("issue_owner_zev_derive", UserRole.ZEV_OWNER)
        other_zev = make_zev(other_owner, "Derivation ZEV")

        issue = ContractIssue.objects.create(
            zev=other_zev,  # deliberately wrong — save() must override it
            participant=self.participant,
            version=99,
            document_number="CTR-X-0099",
            language="de",
            context_hash="0" * 64,
            pdf=b"%PDF",
        )

        self.assertEqual(issue.zev, self.zev)

    @pytest.mark.slow
    def test_contract_pdf_endpoint_streams_the_issued_snapshot(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/v1/zev/participants/{self.participant.pk}/contract-pdf/"

        resp = client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("_v1.pdf", resp["Content-Disposition"])
        issue = ContractIssue.objects.get()
        self.assertEqual(issue.issued_by, self.owner)
        self.assertTrue(AuditEvent.objects.filter(action_type="contract.issue").exists())

        # Unchanged re-download reuses the snapshot — no new version, no new
        # issuance, but the download itself is audited.
        resp = client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ContractIssue.objects.count(), 1)
        download = AuditEvent.objects.get(action_type="contract.download")
        self.assertEqual(download.metadata_json["version"], 1)
        self.assertTrue(download.metadata_json["reused_snapshot"])

    @pytest.mark.slow
    def test_get_streams_the_existing_snapshot_without_issuing(self):
        """GET is a pure read: it serves what was already issued and never
        mints a version of its own."""
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/v1/zev/participants/{self.participant.pk}/contract-pdf/"
        self.assertEqual(client.post(url).status_code, 200)
        AuditEvent.objects.all().delete()

        resp = client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("_v1.pdf", resp["Content-Disposition"])
        self.assertEqual(ContractIssue.objects.count(), 1)
        self.assertFalse(AuditEvent.objects.filter(action_type="contract.issue").exists())
        download = AuditEvent.objects.get(action_type="contract.download")
        self.assertEqual(download.metadata_json["version"], 1)

    def test_get_404s_before_the_contract_has_been_issued(self):
        """Nothing has been issued yet, so there is nothing to read — and a
        read must not become the issuance."""
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.owner)

        resp = client.get(f"/api/v1/zev/participants/{self.participant.pk}/contract-pdf/")

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(ContractIssue.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action_type="contract.issue").exists())

    @pytest.mark.slow
    def test_get_serves_the_latest_version_after_a_reissue(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.owner)
        url = f"/api/v1/zev/participants/{self.participant.pk}/contract-pdf/"
        self.assertEqual(client.post(url).status_code, 200)

        # A data change makes the next issuance mint v2.
        self.zev.additional_contract_notes = "Renegotiated terms."
        self.zev.save()
        self.assertEqual(client.post(url).status_code, 200)
        self.assertEqual(ContractIssue.objects.count(), 2)

        resp = client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("_v2.pdf", resp["Content-Disposition"])


class ContractPdfCsrfTests(TestCase):
    """Issuance writes (document number, ContractIssue, audit event), so it
    must not be reachable by a cross-site link click.

    ``SameSite=Lax`` still sends the auth cookies on a cross-site top-level
    navigation with a safe method, and CSRF enforcement deliberately exempts
    safe methods — so a state-changing GET here was forgeable. See #448.
    """

    def setUp(self):
        self.owner = make_user("csrf_contract_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "CSRF Contract ZEV")
        self.participant = make_participant(self.zev, first="Csrf", last="Participant")
        flat_tariff(self.zev, price="0.18000")
        self.url = f"/api/v1/zev/participants/{self.participant.pk}/contract-pdf/"

    def _cookie_client(self, csrf_token=None):
        # enforce_csrf_checks=True is load-bearing: without it APIClient sets
        # _dont_enforce_csrf_checks and the negative test passes spuriously.
        from django.conf import settings
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        from accounts.cookies import ACCESS_COOKIE, REFRESH_COOKIE

        client = APIClient(enforce_csrf_checks=True)
        refresh = RefreshToken.for_user(self.owner)
        client.cookies[ACCESS_COOKIE] = str(refresh.access_token)
        client.cookies[REFRESH_COOKIE] = str(refresh)
        if csrf_token is not None:
            client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
            client.credentials(HTTP_X_CSRFTOKEN=csrf_token)
        return client

    def test_cookie_get_never_issues_a_contract(self):
        """The forged request from the report: auth cookies, no CSRF token.
        It must not mint anything."""
        resp = self._cookie_client().get(self.url)

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(ContractIssue.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action_type="contract.issue").exists())

    def test_cookie_post_without_csrf_is_forbidden(self):
        resp = self._cookie_client().post(self.url)

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ContractIssue.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action_type="contract.issue").exists())

    @pytest.mark.slow
    def test_cookie_post_with_csrf_issues(self):
        token = "a" * 32

        resp = self._cookie_client(csrf_token=token).post(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        issue = ContractIssue.objects.get()
        self.assertEqual(issue.issued_by, self.owner)


class ContractPdfTranslationParityTests(TestCase):
    def test_all_locales_have_identical_keys_and_structure(self):
        reference = CONTRACT_TRANSLATIONS["de"]
        for locale_name, tr in CONTRACT_TRANSLATIONS.items():
            self.assertEqual(
                set(tr), set(reference), f"{locale_name} translation keys differ"
            )
            for key in tr:
                if isinstance(reference[key], dict):
                    self.assertIsInstance(
                        tr[key], dict, f"{locale_name}.{key} must be a dict"
                    )
                    self.assertEqual(
                        set(tr[key]),
                        set(reference[key]),
                        f"{locale_name}.{key} subkeys differ",
                    )
                    for sub_val in tr[key].values():
                        self.assertIsInstance(sub_val, str, f"{locale_name}.{key} values must be strings")
                elif isinstance(reference[key], list):
                    self.assertIsInstance(tr[key], list, f"{locale_name}.{key} must be a list")
                    self.assertEqual(len(tr[key]), len(reference[key]), f"{locale_name}.{key} length differs")
                    for item in tr[key]:
                        self.assertIsInstance(item, str, f"{locale_name}.{key} items must be strings")
                else:
                    self.assertIsInstance(tr[key], str, f"{locale_name}.{key} must be a string")

    def test_translation_values_carry_no_html_markup(self):
        """Legal prose stays plain text; markup (the bold clause lead-ins)
        lives in the template, so nothing is rendered ``|safe`` and the
        translations remain a lawyer-reviewable data file without 4×
        duplicated markup."""
        for locale_name, tr in CONTRACT_TRANSLATIONS.items():
            for key, value in tr.items():
                if isinstance(value, list):
                    strings = value
                elif isinstance(value, dict):
                    strings = list(value.values())
                else:
                    strings = [value]
                for text in strings:
                    self.assertIsNone(
                        re.search(r"<\s*/?[a-zA-Z]", text),
                        f"{locale_name}.{key} contains HTML markup",
                    )

    def test_all_locales_use_identical_placeholder_sets(self):
        """A placeholder typo in one language only blows up at render time for
        that language (e.g. {pct} vs {pctt}). Assert the {placeholder} set of
        every key matches across all four locales."""

        def _strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from _strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from _strings(v)

        def _placeholders(value):
            found = set()
            for text in _strings(value):
                found.update(re.findall(r"\{(\w+)\}", text))
            return found

        reference = CONTRACT_TRANSLATIONS["de"]
        for key, value in reference.items():
            expected = _placeholders(value)
            for locale_name, tr in CONTRACT_TRANSLATIONS.items():
                with self.subTest(key=key, locale=locale_name):
                    self.assertEqual(
                        _placeholders(tr[key]),
                        expected,
                        f"{locale_name}.{key} placeholder set differs",
                    )


class ContractPdfRenderingTests(TestCase):
    """End-to-end smoke test: the contract renders to a real PDF in every
    supported language and carries the invoice-style page furniture."""

    def setUp(self):
        self.owner = make_user("render_contract_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Render Contract ZEV")
        self.zev.vat_number = "CHE-123.456.789"
        self.zev.invoice_language = "de"
        self.zev.payment_term_days = 30
        self.zev.save(update_fields=["vat_number", "invoice_language", "payment_term_days"])
        VatRate.objects.create(rate=Decimal("0.0810"), valid_from=date(2026, 1, 1))

        self.owner_participant = make_participant(self.zev, user=self.owner, first="Maria", last="Muster")
        self.owner_participant.address_line1 = "Solarweg 1"
        self.owner_participant.postal_code = "8000"
        self.owner_participant.city = "Zürich"
        self.owner_participant.save(update_fields=["address_line1", "postal_code", "city"])

        self.participant = make_participant(self.zev, user=None, first="Alice", last="Muster")
        self.participant.address_line1 = "Musterweg 3"
        self.participant.postal_code = "3000"
        self.participant.city = "Bern"
        self.participant.phone = "+41 31 123 45 67"
        self.participant.save(update_fields=["address_line1", "postal_code", "city", "phone"])
        assignment_for(self.participant)
        assignment_for(self.participant, meter_type=MeteringPointType.PRODUCTION)
        flat_tariff(self.zev, price="0.18000")

    def _page_count(self, pdf_bytes: bytes) -> int:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)

    def _raw_html(self) -> str:
        return render_to_string(CONTRACT_TEMPLATE_NAME, _build_contract_context(self.participant))

    @pytest.mark.slow
    def test_renders_pdf_in_all_four_languages_with_running_page_machinery(self):
        expected_titles = {
            "de": "Teilnahmevertrag vZEV",
            "fr": "Contrat de participation vZEV",
            "it": "Contratto di partecipazione ZEV virtuale",
            "en": "vZEV Participation Agreement",
        }
        for lang, title in expected_titles.items():
            with self.subTest(lang=lang):
                self.zev.invoice_language = lang
                self.zev.save(update_fields=["invoice_language"])

                pdf = generate_contract_pdf(self.participant)
                self.assertTrue(pdf.startswith(b"%PDF-1.7"), f"{lang}: must render a PDF")
                self.assertGreaterEqual(
                    self._page_count(pdf), 3, f"{lang}: contract must span at least three pages"
                )
                self.assertLessEqual(
                    self._page_count(pdf), 7, f"{lang}: contract must not balloon past seven pages"
                )

                markup = _render_contract_markup(self.participant)
                self.assertIn(title, markup, f"{lang}: contract title missing from markup")

                html = self._raw_html()
                self.assertIn("running(footer-meta)", html)
                # The contract prints a footer on every page but deliberately
                # no running header — page 1 carries the document header.
                self.assertNotIn("running(header-meta)", html)
                self.assertIn("page-meta--footer", html)
                self.assertIn("counter(page)", html)
                self.assertIn("counter(pages)", html)

    def test_page_1_uses_the_invoice_document_header_anatomy(self):
        markup = _render_contract_markup(self.participant)
        self.assertIn("document-header", markup)
        self.assertIn("document-label", markup)
        self.assertIn("document-number", markup)
        self.assertIn("document-status", markup)
        self.assertIn("Ausstellungsdatum", markup)
        self.assertIn("parties-grid", markup)

    def test_known_values_are_prefilled_and_vat_rate_is_rendered(self):
        markup = _render_contract_markup(self.participant)
        self.assertIn("Alice Muster", markup)
        self.assertIn("Maria Muster", markup)
        meter_ids = [
            assignment.metering_point.meter_id
            for assignment in self.participant.metering_point_assignments.all()
        ]
        for meter_id in meter_ids:
            self.assertIn(meter_id, markup)  # metering points render
        self.assertIn("8.10 %", markup)
        self.assertIn("CHE-123.456.789", markup)
        self.assertIn("01.01.2026", markup)  # participation start

    def test_sample_contract_context_renders(self):
        html = render_to_string(CONTRACT_TEMPLATE_NAME, build_sample_contract_context())
        self.assertIn("CTR-3B7A9C21", html)

    def test_appendix_b_renders_the_structured_privacy_notice(self):
        markup = _render_contract_markup(self.participant)

        self.assertIn("Verantwortlicher", markup)
        self.assertIn("Maria Muster", markup)  # controller identity from owner_participant
        # Regression: `.clause-text` uses white-space: pre-line, so any source
        # newline in the address tag pairs renders as a line break — the block
        # is one source line and the comma never starts its own line.
        self.assertIn("Solarweg 1, 8000 Zürich", markup)
        self.assertIn("Bearbeitete Daten und Zwecke", markup)
        self.assertIn("Aufbewahrungsdauer", markup)
        self.assertIn("10 Jahre (gesetzliche Aufbewahrungspflicht)", markup)
        self.assertIn("Rechte der Teilnehmer", markup)
        self.assertIn("EDÖB", markup)

    def test_summary_sheet_is_not_part_of_the_signed_document(self):
        """The ten-point plain-language summary was removed from the signed
        contract; Appendix A now opens with a precedence statement instead."""
        markup = _render_contract_markup(self.participant)

        self.assertNotIn("summary-sheet", markup)
        self.assertNotIn("Auf einen Blick", markup)
        self.assertNotIn("Günstiger Lokalstrom", markup)
        self.assertNotIn("Tarifstabilität", markup)
        self.assertIn("Allgemeine Informationen", markup)
        # The closing disclaimer box was dropped: heading parenthetical and
        # precedence_note state the non-binding character once.
        self.assertNotIn("info-note", markup)
        self.assertIn("Allgemeine Informationen (unverbindlich; der Vertrag geht vor)", markup)
        self.assertIn("Dieser Anhang enthält allgemeine, unverbindliche Informationen", markup)
        self.assertIn(
            "Bei Widersprüchen gehen die nummerierten Vertragsbestimmungen den Angaben in diesem Anhang vor",
            markup,
        )
        self.assertIn("Anhang B ist für die Bearbeitung personenbezogener Daten verbindlich", markup)

    def test_corrected_contract_clauses_render_without_unsafe_shortcuts(self):
        """The signed document must describe the legal/operational guardrails
        without promising unrestricted vZEV geography, blanket withdrawal, or
        immediate individual external-grid billing."""
        expected_markers = {
            "de": (
                "gesetzlichen Voraussetzungen für den Zusammenschluss",
                "validierte Messdaten",
                "Mehrwertsteuer",
                "Für Mieter und Pächter richten sich Teilnahme",
                "nach Mahnung und unter Einhaltung des zwingenden Rechts",
            ),
            "fr": (
                "conditions légales du regroupement",
                "données validées",
                "TVA",
                "Pour les locataires et fermiers",
                "résilier la participation conformément au ch. 10",
            ),
            "it": (
                "requisiti legali per il raggruppamento",
                "dati di misura validati",
                "IVA",
                "Per locatari e affittuari",
                "disdire la partecipazione conformemente alla cifra 10",
            ),
            "en": (
                "statutory requirements for common self-consumption",
                "validated meter data",
                "VAT",
                "For tenants and leaseholders",
                "terminate participation in accordance with section 10",
            ),
        }
        for language, markers in expected_markers.items():
            with self.subTest(language=language):
                self.zev.invoice_language = language
                self.zev.save(update_fields=["invoice_language"])
                markup = _render_contract_markup(self.participant)

                for marker in markers:
                    self.assertIn(marker, markup)
                self.assertIn("80", markup)
                self.assertIn(markers[2], markup)
                self.assertNotIn("entire service area of the same grid operator", markup)
                self.assertNotIn("suspend participation in the internal tariff", markup)
                self.assertNotIn("bill the affected party as an external grid customer", markup)
                self.assertNotIn("consommateur externe", markup)
                self.assertNotIn("un consumatore esterno", markup)
                self.assertNotIn("externe Netzbezügerin", markup)

        self.zev.invoice_language = "en"
        self.zev.save(update_fields=["invoice_language"])
        markup = _render_contract_markup(self.participant)
        self.assertIn("technical assessment", markup)
        self.assertIn("mandatory Swiss tenancy law", markup)
        self.assertIn("resulting change in supply or metering arrangements", markup)
        self.assertIn("credited or charged on the next invoice", markup)

    @pytest.mark.slow
    def test_no_page_is_left_nearly_empty(self):
        """Regression guard for the previous layout where the signatures
        landed alone on a page with only ~180 extracted characters."""
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(generate_contract_pdf(self.participant)))
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            self.assertGreaterEqual(
                len(text),
                100,
                f"page {index} carries almost no content ({len(text)} chars)",
            )

    @pytest.mark.slow
    def test_signature_block_is_never_split_across_pages(self):
        """The signature intro and the signing grids must travel as one unit."""
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(generate_contract_pdf(self.participant)))
        for page in reader.pages:
            text = page.extract_text() or ""
            if "Unterschriften" in text:
                self.assertIn("Ort, Datum", text, "intro and signing grids split across pages")
                self.assertIn("Unterschrift", text)

    def test_free_text_notes_keep_line_breaks_and_escape_markup(self):
        self.zev.local_tariff_notes = "Erste Zeile\n\nZweite Zeile\n<script>alert(1)</script>"
        self.zev.additional_contract_notes = "Absatz eins\n\nAbsatz zwei"
        self.zev.save(update_fields=["local_tariff_notes", "additional_contract_notes"])

        markup = _render_contract_markup(self.participant)
        self.assertIn("Erste Zeile\n\nZweite Zeile", markup)
        self.assertIn("Absatz eins\n\nAbsatz zwei", markup)
        self.assertIn("&lt;script&gt;", markup, "note content must be HTML-escaped")
        self.assertNotIn("<script>alert", markup)

        # The .freetext-box rule must preserve line breaks and wrap long tokens.
        raw_html = self._raw_html()
        freetext_rule = raw_html.split(".freetext-box {", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: pre-line", freetext_rule)
        self.assertIn("overflow-wrap: anywhere", freetext_rule)

    @pytest.mark.slow
    def test_very_long_notes_do_not_balloon_the_document(self):
        """A long free-text note may push the signatures and appendices, but
        the rendered document must stay bounded and complete."""
        from pypdf import PdfReader

        prose = (
            "Der Teilnehmer bestätigt, dass er die Regelungen dieses Vertrags zur Kenntnis genommen hat "
            "und mit der internen Zuordnung und Abrechnung der lokalen Energie einverstanden ist. "
        )
        self.zev.local_tariff_notes = prose * 25  # ~3,800 characters
        self.zev.save(update_fields=["local_tariff_notes"])

        reader = PdfReader(io.BytesIO(generate_contract_pdf(self.participant)))
        page_count = len(reader.pages)
        self.assertLessEqual(page_count, 12, f"long note pushed the contract to {page_count} pages")
        last_text = reader.pages[-1].extract_text() or ""
        self.assertIn("Datenschutzerklärung", last_text, "Appendix B must still render last")

    def test_unassigned_meter_placeholder_is_neutral(self):
        """Without a consumption meter the template must show one neutral
        statement, not fake 'CH' meter-number chips."""
        no_meter_participant = make_participant(self.zev, first="No", last="Meter")

        markup = _render_contract_markup(no_meter_participant)
        self.assertEqual(markup.count("Noch kein Messpunkt zugeordnet"), 2)  # consumption + production
        self.assertNotIn('meter-chip--empty">CH', markup)
        self.assertNotIn("CH</span><br>\n<span class=\"meter-chip meter-chip--empty\">CH", markup)
