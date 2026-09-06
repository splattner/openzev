"""Coverage for the tariff overview PDF (docs/specs/2026-09-tariff-overview-pdf.md).

Access and parameter handling are exercised through the real endpoint, like
``test_reports.py`` does for the other report views. Content is instead
checked against ``_build_template_context`` directly rather than by
extracting text from a rendered PDF for every assertion — precise numeric
comparisons (an amount string, a footnote flag) are more reliable read off
the context dict than off WeasyPrint's text layout, and a handful of
end-to-end renders (empty state, PDF/A) cover the template itself.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from tariffs.models import BillingMode, EnergyType, SplitKey, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth, make_user
from zev.models import VatMode

from .band_labels import band_description, translations_for
from .contract_pdf import _build_local_tariff_display
from .contract_translations import CONTRACT_TRANSLATIONS
from .test_helpers import make_participant, make_zev
from .test_pdfa import assert_is_pdfa
from .tariff_overview import _build_template_context, generate_tariff_overview_pdf
from .tariff_overview_translations import TARIFF_OVERVIEW_TRANSLATIONS

TARIFF_OVERVIEW_URL = "/api/v1/invoices/invoices/tariff-overview/"


def _flat_period(tariff, price="0.20000"):
    return TariffPeriod.objects.create(tariff=tariff, price_chf_per_kwh=Decimal(price))


class TariffOverviewTestCase(TestCase):
    """A ZEV plus a second, unrelated one, for cross-tenant checks."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("tov_admin", UserRole.ADMIN)

        self.owner = make_user("tov_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Overview ZEV")
        self.puser = make_user("tov_participant", UserRole.PARTICIPANT)
        self.participant = make_participant(self.zev, user=self.puser, first="Pia", last="Muster")

        self.other_owner = make_user("tov_other_owner", UserRole.ZEV_OWNER)
        self.other_zev = make_zev(self.other_owner, "Other Overview ZEV")

    def _get(self, user, **params):
        auth(self.client, user)
        return self.client.get(TARIFF_OVERVIEW_URL, params)

    def _energy_tariff(self, *, name, category=TariffCategory.ENERGY,
                        energy_type=EnergyType.LOCAL, zev=None, **kwargs):
        return Tariff.objects.create(
            zev=zev or self.zev,
            name=name,
            category=category,
            billing_mode=BillingMode.ENERGY,
            energy_type=energy_type,
            valid_from=kwargs.pop("valid_from", date(2026, 1, 1)),
            **kwargs,
        )


class TariffOverviewAccessTests(TariffOverviewTestCase):
    def test_owner_downloads_own_zev(self):
        self._energy_tariff(name="Solarstrom")
        _flat_period(Tariff.objects.get(name="Solarstrom"))

        resp = self._get(self.owner, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))

    def test_admin_downloads_any_zev(self):
        resp = self._get(self.admin, zev_id=str(self.zev.pk))
        self.assertEqual(resp.status_code, 200)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(self.owner, zev_id=str(self.other_zev.pk))
        self.assertEqual(resp.status_code, 403)

    def test_participant_is_refused(self):
        resp = self._get(self.puser, zev_id=str(self.zev.pk))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_rejected(self):
        resp = self.client.get(TARIFF_OVERVIEW_URL, {"zev_id": str(self.zev.pk)})
        self.assertEqual(resp.status_code, 401)

    def test_zev_id_is_required(self):
        resp = self._get(self.owner)
        self.assertEqual(resp.status_code, 400)

    def test_malformed_zev_id_is_404(self):
        resp = self._get(self.owner, zev_id="not-a-uuid")
        self.assertEqual(resp.status_code, 404)


class TariffOverviewParameterTests(TariffOverviewTestCase):
    def test_as_of_defaults_to_today(self):
        resp = self._get(self.owner, zev_id=str(self.zev.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"tariff-overview-{date.today().isoformat()}.pdf", resp["Content-Disposition"])

    def test_as_of_selects_the_version_in_force(self):
        old = self._energy_tariff(name="Series", valid_from=date(2025, 1, 1), valid_to=date(2025, 12, 31))
        _flat_period(old, "0.10000")
        new = Tariff.objects.create(
            zev=self.zev, name="Series", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )
        _flat_period(new, "0.20000")

        ctx_2025 = _build_template_context(self.zev, date(2025, 6, 1), "valid")
        ctx_2026 = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        amount_2025 = ctx_2025["groups"][0]["tariffs"][0]["price_rows"][0]["amount"]
        amount_2026 = ctx_2026["groups"][0]["tariffs"][0]["price_rows"][0]["amount"]
        self.assertEqual(amount_2025, "10.00")
        self.assertEqual(amount_2026, "20.00")

    def test_unparseable_as_of_is_400(self):
        resp = self._get(self.owner, zev_id=str(self.zev.pk), as_of="not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("YYYY-MM-DD", resp.json()["error"])

    def test_scope_all_includes_superseded_versions(self):
        old = self._energy_tariff(name="Series", valid_from=date(2025, 1, 1), valid_to=date(2025, 12, 31))
        _flat_period(old)
        new = Tariff.objects.create(
            zev=self.zev, name="Series", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )
        _flat_period(new)

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "all")
        self.assertEqual(len(ctx["groups"][0]["tariffs"]), 2)
        current_flags = {row["is_current"] for row in ctx["groups"][0]["tariffs"]}
        self.assertEqual(current_flags, {True, False})

    def test_unknown_scope_is_400(self):
        resp = self._get(self.owner, zev_id=str(self.zev.pk), scope="everything")
        self.assertEqual(resp.status_code, 400)


class TariffOverviewContentTests(TariffOverviewTestCase):
    def test_categories_appear_in_invoice_order(self):
        self._energy_tariff(name="Energy T", category=TariffCategory.ENERGY)
        _flat_period(Tariff.objects.get(name="Energy T"))
        self._energy_tariff(name="Levy T", category=TariffCategory.LEVIES, energy_type=EnergyType.GRID)
        _flat_period(Tariff.objects.get(name="Levy T"))
        self._energy_tariff(name="Metering T", category=TariffCategory.METERING, energy_type=EnergyType.GRID)
        _flat_period(Tariff.objects.get(name="Metering T"))

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        self.assertEqual(
            [g["key"] for g in ctx["groups"]],
            [TariffCategory.ENERGY, TariffCategory.LEVIES, TariffCategory.METERING],
        )

    def test_empty_category_is_omitted(self):
        self._energy_tariff(name="Only energy")
        _flat_period(Tariff.objects.get(name="Only energy"))

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        self.assertEqual([g["key"] for g in ctx["groups"]], [TariffCategory.ENERGY])

    def test_every_band_of_a_multi_band_tariff_is_listed(self):
        from datetime import time

        tariff = self._energy_tariff(name="Multi-band", energy_type=EnergyType.GRID)
        TariffPeriod.objects.create(
            tariff=tariff, period_type="high", price_chf_per_kwh=Decimal("0.30000"),
            time_from=time(6, 0), time_to=time(22, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type="low", price_chf_per_kwh=Decimal("0.10000"),
            time_from=time(22, 0), time_to=time(23, 59, 59),
        )

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        price_rows = ctx["groups"][0]["tariffs"][0]["price_rows"]

        self.assertEqual(len(price_rows), 2)
        amounts = {row["amount"] for row in price_rows}
        self.assertEqual(amounts, {"30.00", "10.00"})

    def test_band_labels_match_the_contract(self):
        from datetime import time

        tariff = self._energy_tariff(name="Local bands", energy_type=EnergyType.LOCAL)
        TariffPeriod.objects.create(
            tariff=tariff, period_type="high", price_chf_per_kwh=Decimal("0.25000"),
            time_from=time(7, 0), time_to=time(20, 0),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type="low", price_chf_per_kwh=Decimal("0.15000"),
            time_from=time(20, 0), time_to=time(23, 59, 59),
        )

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        overview_labels = {row["label"] for row in ctx["groups"][0]["tariffs"][0]["price_rows"]}

        contract_rows = _build_local_tariff_display(
            self.zev, CONTRACT_TRANSLATIONS["de"], "dd.MM.yyyy", date(2026, 6, 1)
        )
        contract_labels = {row["rate_description"] for row in contract_rows}

        self.assertEqual(overview_labels, contract_labels)

    def test_seasonal_band_carries_its_season(self):
        tariff = self._energy_tariff(name="Seasonal", energy_type=EnergyType.GRID)
        period = TariffPeriod.objects.create(
            tariff=tariff, period_type="high", price_chf_per_kwh=Decimal("0.28000"),
            months="10,11,12,1,2,3",
        )

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        label = ctx["groups"][0]["tariffs"][0]["price_rows"][0]["label"]

        self.assertEqual(label, band_description(period, translations_for("de")))
        self.assertIn("Okt", label)

    def test_prices_are_printed_in_rappen(self):
        self._energy_tariff(name="Rappen T")
        _flat_period(Tariff.objects.get(name="Rappen T"), "0.22500")

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        row = ctx["groups"][0]["tariffs"][0]["price_rows"][0]

        self.assertEqual(row["amount"], "22.50")
        self.assertEqual(row["unit"], "Rp./kWh")

    def test_shared_fee_names_its_split(self):
        Tariff.objects.create(
            zev=self.zev, name="Shared fee", category=TariffCategory.METERING,
            billing_mode=BillingMode.SHARED_MONTHLY_FEE, split_key=SplitKey.WEIGHT,
            fixed_price_chf=Decimal("500.00"), valid_from=date(2026, 1, 1),
        )

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        row = ctx["groups"][0]["tariffs"][0]["price_rows"][0]

        tr = TARIFF_OVERVIEW_TRANSLATIONS["de"]
        self.assertEqual(row["label"], tr["fee_shared_weight"])
        self.assertEqual(row["amount"], "500.00")
        self.assertEqual(row["unit"], "CHF/Mt.")

    def _grid_sheet(self):
        """A grid tariff as an operator actually files one: the Arbeitspreis in
        ENERGY, network usage in GRID_FEES, levies in LEVIES. Only the first is
        category ENERGY, which is what makes this the case that catches a base
        selected by category. Sums to 0.28890 CHF/kWh.
        """
        for name, category, price in (
            ("Arbeitspreis", TariffCategory.ENERGY, "0.13600"),
            ("Netznutzung", TariffCategory.GRID_FEES, "0.10400"),
            ("KEV", TariffCategory.LEVIES, "0.02380"),
            ("SDL", TariffCategory.LEVIES, "0.00290"),
            ("Gemeinwesen", TariffCategory.LEVIES, "0.01620"),
            ("WiRes", TariffCategory.LEVIES, "0.00440"),
            ("SGF", TariffCategory.LEVIES, "0.00110"),
            ("Solidarisierte Kosten", TariffCategory.LEVIES, "0.00050"),
        ):
            _flat_period(
                self._energy_tariff(name=name, category=category, energy_type=EnergyType.GRID),
                price,
            )

    def _local_pct(self, percentage="65.00"):
        return Tariff.objects.create(
            zev=self.zev, name="Local pct", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
            percentage=Decimal(percentage), valid_from=date(2026, 1, 1),
        )

    def _pct_row(self, as_of=date(2026, 6, 1)):
        ctx = _build_template_context(self.zev, as_of, "valid")
        return next(
            row for group in ctx["groups"] for tariff in group["tariffs"]
            for row in tariff["price_rows"] if tariff["name"] == "Local pct"
        )

    def test_percentage_row_matches_the_contract_figure(self):
        grid = self._energy_tariff(name="Grid", energy_type=EnergyType.GRID)
        _flat_period(grid, "0.29500")
        self._local_pct("18.00")

        overview_row = self._pct_row()

        contract_rows = _build_local_tariff_display(
            self.zev, CONTRACT_TRANSLATIONS["de"], "dd.MM.yyyy", date(2026, 6, 1)
        )
        contract_row = next(r for r in contract_rows if r["name"] == "Local pct")

        self.assertEqual(overview_row["amount"], contract_row["rate_rp"])
        self.assertIsNone(overview_row["footnote"])

    def test_percentage_base_spans_every_grid_category(self):
        """The base is the whole grid price, not just its ENERGY component.

        Selecting by category kept only the 13.60 Arbeitspreis and printed
        8.84 instead of 18.78 — less than half the rate actually billed.
        """
        self._grid_sheet()
        self._local_pct("65.00")

        row = self._pct_row()

        self.assertEqual(row["amount"], "18.78")
        self.assertIn("28.89", row["label"])

    def test_percentage_row_matches_the_contract_across_grid_categories(self):
        """The parity the spec asks for, on a grid sheet that spans categories.

        The single-tariff case above agrees whichever way the base is selected,
        so it cannot see a divergence between the two documents.
        """
        self._grid_sheet()
        self._local_pct("65.00")

        contract_rows = _build_local_tariff_display(
            self.zev, CONTRACT_TRANSLATIONS["de"], "dd.MM.yyyy", date(2026, 6, 1)
        )
        contract_row = next(r for r in contract_rows if r["name"] == "Local pct")

        self.assertEqual(self._pct_row()["amount"], contract_row["rate_rp"])

    def test_multiband_grid_base_adds_the_footnote(self):
        from datetime import time

        grid = self._energy_tariff(name="Grid multi", energy_type=EnergyType.GRID)
        TariffPeriod.objects.create(
            tariff=grid, period_type="high", price_chf_per_kwh=Decimal("0.30000"),
            time_from=time(6, 0), time_to=time(22, 0),
        )
        TariffPeriod.objects.create(
            tariff=grid, period_type="low", price_chf_per_kwh=Decimal("0.10000"),
            time_from=time(22, 0), time_to=time(23, 59, 59),
        )
        Tariff.objects.create(
            zev=self.zev, name="Local pct", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.PERCENTAGE_OF_ENERGY, energy_type=EnergyType.LOCAL,
            percentage=Decimal("18.00"), valid_from=date(2026, 1, 1),
        )

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        overview_row = next(
            row for group in ctx["groups"] for tariff in group["tariffs"]
            for row in tariff["price_rows"] if tariff["name"] == "Local pct"
        )

        self.assertEqual(overview_row["footnote"], "multiband_base")
        self.assertEqual(len(ctx["footnotes"]), 1)
        self.assertEqual(ctx["footnotes"][0][1], TARIFF_OVERVIEW_TRANSLATIONS["de"]["footnote_multiband_base"])


class TariffOverviewVatTests(TariffOverviewTestCase):
    def test_inclusive_states_prices_are_net(self):
        self.zev.vat_mode = VatMode.INCLUSIVE
        self.zev.save()

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        tr = TARIFF_OVERVIEW_TRANSLATIONS["de"]
        self.assertEqual(ctx["vat_display"], tr["vat_inclusive"])
        self.assertEqual(ctx["vat_note"], tr["vat_note_inclusive"])

    def test_registered_states_prices_exclude_vat(self):
        self.zev.vat_mode = VatMode.REGISTERED
        self.zev.vat_number = "CHE-123.456.789 MWST"
        self.zev.save()

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        tr = TARIFF_OVERVIEW_TRANSLATIONS["de"]
        self.assertEqual(ctx["vat_note"], tr["vat_note_registered"])
        self.assertIn("CHE-123.456.789 MWST", ctx["vat_display"])

    def test_not_registered_has_no_vat_footnote(self):
        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        tr = TARIFF_OVERVIEW_TRANSLATIONS["de"]
        self.assertEqual(ctx["vat_display"], tr["vat_not_registered"])
        self.assertIsNone(ctx["vat_note"])


class TariffOverviewEdgeTests(TariffOverviewTestCase):
    def test_zev_without_tariffs_renders_an_empty_state(self):
        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")
        self.assertEqual(ctx["groups"], [])

        pdf_bytes = generate_tariff_overview_pdf(self.zev, date(2026, 6, 1))
        from pypdf import PdfReader
        import io
        text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text() or ""
        self.assertIn("keine Tarife", text)

    def test_energy_tariff_without_periods_is_skipped(self):
        self._energy_tariff(name="No bands")

        ctx = _build_template_context(self.zev, date(2026, 6, 1), "valid")

        self.assertEqual(ctx["groups"], [])

    def test_output_is_pdfa(self):
        self._energy_tariff(name="PDFA check")
        _flat_period(Tariff.objects.get(name="PDFA check"))

        pdf_bytes = generate_tariff_overview_pdf(self.zev, date(2026, 6, 1))
        assert_is_pdfa(self, pdf_bytes)


class TariffOverviewTranslationParityTests(TestCase):
    def test_all_locales_have_identical_keys_and_structure(self):
        reference = TARIFF_OVERVIEW_TRANSLATIONS["de"]
        for locale_name, tr in TARIFF_OVERVIEW_TRANSLATIONS.items():
            self.assertEqual(set(tr), set(reference), f"{locale_name} translation keys differ")
            for key in tr:
                if isinstance(reference[key], dict):
                    self.assertIsInstance(tr[key], dict, f"{locale_name}.{key} must be a dict")
                    self.assertEqual(
                        set(tr[key]), set(reference[key]), f"{locale_name}.{key} subkeys differ"
                    )
                    for sub_val in tr[key].values():
                        self.assertIsInstance(sub_val, str, f"{locale_name}.{key} values must be strings")
                else:
                    self.assertIsInstance(tr[key], str, f"{locale_name}.{key} must be a string")
