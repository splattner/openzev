"""Gross energy on the statistics surfaces (SPEC §5.1): dashboards, annual report, annual statement, MCP."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from allocation.validity import period_start_dt
from metering.models import MeterReading, SupplementaryReading, SupplementarySource
from metering.supplementary import surfaces
from metering.supplementary.stats import civil_window
from metering.supplementary.testing import SupplementaryApiTestCase, client_for, enable_feature
from testing import factories
from zev.models import MeteringPointType

DASHBOARD = "/api/v1/metering/readings/dashboard-summary/"
ANNUAL_REPORT = "/api/v1/invoices/invoices/annual-report/"
QUARTER = timedelta(minutes=15)
DAYS = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]

# Per interval: self-consumption = min(max(1.2 - 0.9, 0), 1.2, 0.4) = 0.3.
# Per day (96 intervals): consumption 38.4, production 115.2, import 9.6, export 86.4, self 28.8,
# so self-sufficiency 75.0 % and self-consumption rate 25.0 %.
ROW = dict(consumption_kwh=Decimal("0.4"), production_kwh=Decimal("1.2"), import_kwh=Decimal("0.1"), export_kwh=Decimal("0.9"))


class SurfaceTestCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="solar_manager", external_id="ABC123"
        )

    def seed_day(self, day, *, readings=True, supplementary=True, share=1.0, row=None):
        start = period_start_dt(day)
        slots = int((period_start_dt(day + timedelta(days=1)) - start) / QUARTER)
        for i in range(int(slots * share)):
            stamp = start + QUARTER * i
            if readings:
                MeterReading.objects.create(metering_point=self.point, timestamp=stamp, energy_kwh=Decimal("0.1"), direction="in")
                MeterReading.objects.create(metering_point=self.point, timestamp=stamp, energy_kwh=Decimal("0.9"), direction="out")
            if supplementary:
                SupplementaryReading.objects.create(source=self.source, metering_point=self.point, timestamp=stamp, **(row or ROW))
        if supplementary:
            lo, hi = period_start_dt(day), period_start_dt(day + timedelta(days=1))
            self.source.covers_from = min(filter(None, [self.source.covers_from, lo]))
            self.source.synced_through = max(filter(None, [self.source.synced_through, hi]))
            self.source.save()

    def seed(self, days=DAYS, **kwargs):
        for day in days:
            self.seed_day(day, **kwargs)

    def dashboard(self, user, **params):
        params = {"zev_id": str(self.zev.pk), "date_from": "2026-07-01", "date_to": "2026-07-03", "bucket": "day", **params}
        response = client_for(user).get(DASHBOARD, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class WindowAndBucketTests(SurfaceTestCase):
    def test_a_window_is_the_civil_dates_inclusive(self):
        start, end = surfaces.window_for(date(2026, 7, 1), date(2026, 7, 3))
        self.assertEqual((start, end), civil_window(date(2026, 7, 1), date(2026, 7, 3)))

    def test_an_open_window_is_unbounded(self):
        start, end = surfaces.window_for(None, None)
        self.assertLess(start, period_start_dt(date(2001, 1, 1)))
        self.assertGreater(end, period_start_dt(date(2100, 1, 1)))

    def test_bucket_labels_equal_the_ones_the_dashboard_uses(self):
        for day in (date(2026, 3, 29), date(2026, 10, 25), date(2026, 7, 1)):  # both DST changes and a plain day
            self.seed_day(day, supplementary=False)
        for bucket in ("day", "month", "hour"):
            label = surfaces.bucket_key_for(bucket)
            data = self.dashboard(self.manager, date_from="2026-03-29", date_to="2026-10-25", bucket=bucket)
            stamps = MeterReading.objects.filter(direction="in").values_list("timestamp", flat=True)
            self.assertEqual({label(ts) for ts in stamps}, {item["bucket"] for item in data["timeline"]}, bucket)


class ParticipantDashboardTests(SurfaceTestCase):
    def test_the_participant_sees_their_own_figures_with_a_timeline(self):
        self.seed()
        gross = self.dashboard(self.holder_user)["gross_energy"]
        self.assertEqual(gross["source_provider"], "solar_manager")
        self.assertAlmostEqual(gross["consumption_kwh"], 38.4 * 3, places=3)
        self.assertAlmostEqual(gross["production_kwh"], 115.2 * 3, places=3)
        self.assertAlmostEqual(gross["import_kwh"], 9.6 * 3, places=3)
        self.assertAlmostEqual(gross["export_kwh"], 86.4 * 3, places=3)
        self.assertAlmostEqual(gross["self_consumption_kwh"], 28.8 * 3, places=3)
        self.assertEqual(gross["self_sufficiency_rate"], 75.0)
        self.assertEqual(gross["self_consumption_rate"], 25.0)
        self.assertEqual(gross["coverage_pct"], 100.0)
        self.assertIsNone(gross["rates_withheld_reason"])
        self.assertEqual(len(gross["timeline"]), 3)
        self.assertTrue(all(item["bucket"].startswith("2026-07-0") for item in gross["timeline"]))
        self.assertAlmostEqual(gross["timeline"][0]["self_consumption_kwh"], 28.8, places=3)

    def test_the_dashboards_own_numbers_are_unchanged(self):
        self.seed()
        with_source = self.dashboard(self.holder_user)
        enable_feature(False)
        without = self.dashboard(self.holder_user)
        self.assertIsNone(without["gross_energy"])
        for key in ("totals", "timeline", "zev_totals", "zev_participant_stats", "has_behind_meter_generation"):
            self.assertEqual(with_source[key], without[key], key)

    def test_the_date_range_bounds_the_figures(self):
        self.seed()
        gross = self.dashboard(self.holder_user, date_from="2026-07-02", date_to="2026-07-02")["gross_energy"]
        self.assertAlmostEqual(gross["consumption_kwh"], 38.4, places=3)
        self.assertEqual(len(gross["timeline"]), 1)

    def test_a_range_before_the_data_has_no_block(self):
        self.seed()
        self.assertIsNone(self.dashboard(self.holder_user, date_from="2026-06-01", date_to="2026-06-30")["gross_energy"])

    def test_low_coverage_withholds_the_rates_and_says_why(self):
        self.seed(days=DAYS[:2])
        self.seed_day(DAYS[2], share=0.5)
        gross = self.dashboard(self.holder_user)["gross_energy"]
        self.assertLess(gross["coverage_pct"], 95)
        self.assertIsNone(gross["self_sufficiency_rate"])
        self.assertIsNone(gross["self_consumption_rate"])
        self.assertEqual(gross["rates_withheld_reason"], "low_coverage")
        self.assertGreater(gross["consumption_kwh"], 0)  # the energy is still reported

    def test_a_participant_without_a_source_gets_null(self):
        self.seed()
        self.assertIsNone(self.dashboard(self.other_user)["gross_energy"])

    def test_nobody_else_sees_the_holders_figures_in_the_participant_view(self):
        self.seed()
        data = self.dashboard(self.other_user)
        self.assertNotIn("gross_energy", str(data["zev_participant_stats"]))

    def test_a_disconnected_source_keeps_its_history(self):
        self.seed()
        self.source.disconnect()
        self.source.save()
        self.assertIsNotNone(self.dashboard(self.holder_user)["gross_energy"])

    def test_nothing_while_the_flag_is_off(self):
        self.seed()
        enable_feature(False)
        self.assertIsNone(self.dashboard(self.holder_user)["gross_energy"])

    def test_a_tenancy_that_ended_does_not_leak_into_the_next_holders_view(self):
        self.seed()
        self.assignment.valid_to = date(2026, 7, 1)
        self.assignment.save()
        factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.other, valid_from=date(2026, 7, 2)
        )
        self.assertIsNone(self.dashboard(self.other_user)["gross_energy"])
        gross = self.dashboard(self.holder_user)["gross_energy"]
        self.assertAlmostEqual(gross["consumption_kwh"], 38.4, places=3)  # only 1 July, while they held it


class OwnerDashboardTests(SurfaceTestCase):
    def stat(self, data, participant):
        return next(item for item in data["participant_stats"] if item["participant_id"] == str(participant.pk))

    def test_each_participant_stat_carries_gross_energy_without_a_timeline(self):
        self.seed()
        data = self.dashboard(self.manager)
        gross = self.stat(data, self.holder)["gross_energy"]
        self.assertEqual(gross["self_sufficiency_rate"], 75.0)
        self.assertNotIn("timeline", gross)
        self.assertIsNone(data["selected_gross_energy"])

    def test_a_selected_participant_adds_the_timeline(self):
        self.seed()
        data = self.dashboard(self.manager, participant_id=str(self.holder.pk))
        self.assertEqual(len(data["selected_gross_energy"]["timeline"]), 3)

    def test_a_selected_participant_without_a_source_is_null(self):
        self.seed()
        self.assertIsNone(self.dashboard(self.manager, participant_id=str(self.other.pk))["selected_gross_energy"])

    def test_participants_without_a_source_are_null(self):
        self.seed()
        consumer_point = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        factories.MeteringPointAssignmentFactory(metering_point=consumer_point, participant=self.other, valid_from=date(2025, 1, 1))
        MeterReading.objects.create(metering_point=consumer_point, timestamp=period_start_dt(DAYS[0]), energy_kwh=Decimal("1"), direction="in")
        data = self.dashboard(self.manager)
        self.assertIsNone(self.stat(data, self.other)["gross_energy"])

    def test_viewers_and_admins_see_what_the_dashboard_shows(self):
        self.seed()
        for user in (self.viewer, self.admin):
            self.assertIsNotNone(self.stat(self.dashboard(user), self.holder)["gross_energy"], user.username)

    def test_nothing_while_the_flag_is_off(self):
        self.seed()
        enable_feature(False)
        data = self.dashboard(self.manager, participant_id=str(self.holder.pk))
        self.assertIsNone(self.stat(data, self.holder)["gross_energy"])
        self.assertIsNone(data["selected_gross_energy"])

    def test_the_billing_shaped_numbers_are_identical_with_and_without_the_source(self):
        self.seed()
        with_source = self.dashboard(self.manager)
        enable_feature(False)
        without = self.dashboard(self.manager)
        strip = lambda data: [{k: v for k, v in item.items() if k != "gross_energy"} for item in data["participant_stats"]]  # noqa: E731
        self.assertEqual(strip(with_source), strip(without))
        self.assertEqual(with_source["totals"], without["totals"])
        self.assertEqual(with_source["timeline"], without["timeline"])


class AnnualReportTests(SurfaceTestCase):
    def report(self, user=None):
        response = client_for(user or self.manager).get(ANNUAL_REPORT, {"zev_id": str(self.zev.pk), "year": 2026})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def row(self, report, participant):
        return next(item for item in report["participants"] if item["participant_id"] == str(participant.pk))

    def test_the_participant_row_gains_gross_energy_and_keeps_the_meter_rate_null(self):
        self.seed()
        row = self.row(self.report(), self.holder)
        self.assertAlmostEqual(row["gross_energy"]["consumption_kwh"], 38.4 * 3, places=3)
        self.assertNotIn("timeline", row["gross_energy"])
        self.assertIsNone(row["self_sufficiency_rate"])  # the meter-based figure stays withheld
        self.assertTrue(row["has_behind_meter_generation"])

    def test_coverage_is_judged_on_the_synced_range_not_the_whole_year(self):
        self.seed()
        gross = self.row(self.report(), self.holder)["gross_energy"]
        self.assertEqual(gross["coverage_pct"], 100.0)
        self.assertEqual(gross["self_sufficiency_rate"], 75.0)

    def test_everything_else_in_the_report_is_unchanged(self):
        self.seed()
        with_source = self.report()
        enable_feature(False)
        without = self.report()
        for key in ("totals", "previous_totals", "months", "savings_total_chf", "has_data"):
            self.assertEqual(with_source[key], without[key], key)
        self.assertIsNone(self.row(without, self.holder)["gross_energy"])

    def test_participants_without_a_source_are_null(self):
        self.seed()
        row = self.row(self.report(), self.holder)
        self.assertIsNotNone(row["gross_energy"])
        others = [item for item in self.report()["participants"] if item["participant_id"] != str(self.holder.pk)]
        self.assertTrue(all(item["gross_energy"] is None for item in others))


class AnnualStatementTests(SurfaceTestCase):
    def setUp(self):
        super().setUp()
        from invoices.annual_statement import ANNUAL_TRANSLATIONS

        self.translations = ANNUAL_TRANSLATIONS

    def render(self, lang="de"):
        from invoices import annual_statement

        self.zev.invoice_language = lang
        self.zev.save()
        captured = {}

        def fake_pdf(html):
            captured["html"] = html
            return b"%PDF-fake"

        real = annual_statement._render_template

        def spy(template, context):
            captured["context"] = context
            return real(template, context)

        with mock.patch.object(annual_statement, "render_pdf", fake_pdf), \
                mock.patch.object(annual_statement, "_render_template", spy):
            annual_statement.generate_annual_statement_pdf(self.holder, self.zev, 2026)
        return captured["context"], captured["html"]

    def seed_full_months(self):
        # July and August fully covered, September missing a lot.
        self.seed(days=[date(2026, 7, 1) + timedelta(days=n) for n in range(62)])
        for n in range(30):
            self.seed_day(date(2026, 9, 1) + timedelta(days=n), share=0.4 if n % 2 else 0.0, readings=False)

    def test_covered_months_show_the_gross_rate_and_others_stay_dashes(self):
        self.seed_full_months()
        context, _ = self.render()
        rates = [row["self_sufficiency_pct"] for row in context["monthly_data"]]
        self.assertEqual(rates[6], 75)
        self.assertEqual(rates[7], 75)
        self.assertIsNone(rates[8])  # September: too little data
        self.assertTrue(all(rate is None for rate in rates[:6] + rates[9:]))
        self.assertEqual(context["gross_energy_source"], "solar_manager")

    def test_the_year_total_follows_the_years_own_coverage(self):
        self.seed_full_months()
        context, _ = self.render()
        # July and August are complete, September is not; the year as a whole is judged on its own coverage.
        self.assertIsNone(context["totals"]["self_sufficiency_pct"])

    def test_a_fully_covered_year_so_far_shows_a_total(self):
        self.seed(days=[date(2026, 7, 1) + timedelta(days=n) for n in range(31)])
        context, _ = self.render()
        self.assertEqual(context["totals"]["self_sufficiency_pct"], 75)

    def test_the_note_explains_where_the_figures_come_from_in_every_language(self):
        self.seed_full_months()
        for lang in ("de", "fr", "it", "en"):
            context, html = self.render(lang)
            note = self.translations[lang]["behind_meter_supplementary_note"]
            plain = html.replace("&#x27;", "'").replace("&#39;", "'")
            self.assertIn(note, plain, lang)
            self.assertNotIn(self.translations[lang]["behind_meter_note"], plain, lang)

    def test_without_enough_data_the_plain_note_stays(self):
        self.seed_day(date(2026, 7, 1), share=0.3)
        context, html = self.render()
        self.assertIsNone(context["gross_energy_source"])
        self.assertIn("Deshalb wird keine Autarkie ausgewiesen", html)
        self.assertTrue(all(row["self_sufficiency_pct"] is None for row in context["monthly_data"]))

    def test_a_participant_without_a_source_is_unchanged(self):
        self.seed_day(date(2026, 7, 1), supplementary=False)
        self.source.delete()
        context, html = self.render()
        self.assertTrue(context["has_behind_meter_generation"])
        self.assertIsNone(context["gross_energy_source"])
        self.assertIsNone(context["totals"]["self_sufficiency_pct"])

    def test_nothing_while_the_flag_is_off(self):
        self.seed_full_months()
        enable_feature(False)
        context, _ = self.render()
        self.assertIsNone(context["gross_energy_source"])
        self.assertTrue(all(row["self_sufficiency_pct"] is None for row in context["monthly_data"]))

    def test_a_participant_who_is_not_net_metered_keeps_their_meter_based_rate(self):
        self.point.has_behind_meter_generation = False
        self.point.save()
        self.seed_full_months()
        context, _ = self.render()
        self.assertFalse(context["has_behind_meter_generation"])
        self.assertIsNone(context["gross_energy_source"])

    def test_every_language_has_the_new_note_and_the_catalog_lists_it(self):
        from invoices.field_catalog_data import _ANNUAL_STATEMENT_TRANSLATION_KEYS

        for lang in ("de", "fr", "it", "en"):
            self.assertTrue(self.translations[lang]["behind_meter_supplementary_note"], lang)
        self.assertIn("behind_meter_supplementary_note", _ANNUAL_STATEMENT_TRANSLATION_KEYS)


class MeteringPointStatusTests(SurfaceTestCase):
    def status_for(self, user):
        response = client_for(user).get("/api/v1/zev/metering-points/")
        self.assertEqual(response.status_code, 200, response.content)
        results = response.json().get("results", response.json())
        match = [item for item in results if item["id"] == str(self.point.pk)]
        return match[0]["supplementary_source_status"] if match else "invisible"

    def test_owner_manager_viewer_and_admin_see_the_status(self):
        self.source.mark_ok()
        self.source.save()
        for user in (self.holder_user, self.manager, self.viewer, self.admin):
            self.assertEqual(self.status_for(user), "ok", user.username)

    def test_another_participant_does_not_learn_that_a_source_exists(self):
        self.assertIn(self.status_for(self.other_user), (None, "invisible"))

    def test_a_meter_without_a_source_is_null(self):
        self.source.delete()
        self.assertIsNone(self.status_for(self.manager))

    def test_null_while_the_flag_is_off(self):
        enable_feature(False)
        self.assertIsNone(self.status_for(self.manager))
