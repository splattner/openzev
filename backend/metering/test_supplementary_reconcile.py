"""Reconciliation against the official meter (SPEC §6.5)."""

from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone

from allocation.validity import period_start_dt
from metering.models import MeterReading, SupplementaryReading, SupplementarySource
from metering.supplementary import reconcile
from metering.supplementary.testing import SupplementaryApiTestCase

QUARTER = timedelta(minutes=15)


def profile(i: int) -> Decimal:
    """A lumpy, non-periodic export profile, so a shifted copy of it is recognisably shifted."""
    return Decimal(((i * 7 + i * i) % 13) + 1) / 10


def import_profile(i: int) -> Decimal:
    return Decimal(((i * 5 + 3 * i * i) % 11)) / 20


class ReconcileTestCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        self.source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.holder, provider="solar_manager", external_id="ABC123"
        )
        self.today = timezone.localdate()

    def day_start(self, days_ago: int):
        return period_start_dt(self.today - timedelta(days=days_ago))

    def add_day(self, days_ago, *, source_shift=0, source_factor=Decimal(1), meter=True, source=True, share=1.0):
        """Fill a civil day in the meter and/or the source; ``source_shift`` offsets the source's timestamps."""
        start = self.day_start(days_ago)
        slots = int((period_start_dt(self.today - timedelta(days=days_ago - 1)) - start) / QUARTER)
        for i in range(int(slots * share)):
            stamp = start + QUARTER * i
            export, imported = profile(i), import_profile(i)
            if meter:
                MeterReading.objects.create(metering_point=self.point, timestamp=stamp, energy_kwh=export, direction="out")
                MeterReading.objects.create(metering_point=self.point, timestamp=stamp, energy_kwh=imported, direction="in")
            if source:
                SupplementaryReading.objects.update_or_create(
                    metering_point=self.point, timestamp=stamp + QUARTER * source_shift,
                    defaults=dict(
                        source=self.source, consumption_kwh=2, production_kwh=3,
                        export_kwh=export * source_factor, import_kwh=imported * source_factor,
                    ),
                )

    def run_it(self, **kwargs):
        return reconcile.reconcile(self.source, **kwargs)


class ReconcileTests(ReconcileTestCase):
    def test_matching_series_are_ok_with_no_deviation_and_no_shift(self):
        for days_ago in (2, 3, 4):
            self.add_day(days_ago)
        result = self.run_it()
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["days_compared"], 3)
        self.assertEqual(result["export_deviation_pct"], 0.0)
        self.assertEqual(result["import_deviation_pct"], 0.0)
        self.assertEqual(result["best_shift_intervals"], 0)

    def test_a_deviation_above_the_tolerance_warns(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, source_factor=Decimal("1.3"))
        result = self.run_it()
        self.assertEqual(result["state"], "warn")
        self.assertAlmostEqual(result["export_deviation_pct"], 30.0, delta=0.2)

    def test_a_deviation_below_the_tolerance_is_fine(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, source_factor=Decimal("1.05"))
        self.assertEqual(self.run_it()["state"], "ok")

    @override_settings(SUPPLEMENTARY_RECONCILE_TOLERANCE=0.02)
    def test_the_tolerance_is_a_setting(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, source_factor=Decimal("1.05"))
        self.assertEqual(self.run_it()["state"], "warn")

    def test_timestamps_one_interval_late_are_detected_as_a_shift(self):
        for days_ago in (2, 3, 4):
            self.add_day(days_ago, source_shift=1)
        result = self.run_it()
        self.assertEqual(result["best_shift_intervals"], 1)
        self.assertEqual(result["state"], "warn")

    def test_timestamps_early_by_two_intervals_are_detected_too(self):
        for days_ago in (2, 3, 4):
            self.add_day(days_ago, source_shift=-2)
        result = self.run_it()
        self.assertEqual(result["best_shift_intervals"], -2)
        self.assertEqual(result["state"], "warn")

    def test_fewer_than_two_comparable_days_is_insufficient(self):
        self.add_day(2)
        result = self.run_it()
        self.assertEqual(result["state"], "insufficient")
        self.assertEqual(result["days_compared"], 1)
        self.assertIsNone(result["export_deviation_pct"])

    def test_without_official_data_it_is_insufficient(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, meter=False)
        self.assertEqual(self.run_it()["state"], "insufficient")

    def test_without_supplementary_data_it_is_insufficient(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, source=False)
        self.assertEqual(self.run_it()["state"], "insufficient")

    def test_a_mostly_empty_day_is_not_compared(self):
        self.add_day(2)
        self.add_day(3)
        self.add_day(4, share=0.5)
        self.assertEqual(self.run_it()["days_compared"], 2)

    def test_the_newest_days_win(self):
        for days_ago in range(2, 12):
            self.add_day(days_ago)
        self.assertEqual(self.run_it(days=7)["days_compared"], 7)
        result = self.run_it(days=3, include_days=True)
        self.assertEqual([d["date"] for d in result["days"]],
                         sorted((self.today - timedelta(days=n)).isoformat() for n in (2, 3, 4)))

    def test_days_older_than_the_lookback_are_not_looked_at(self):
        for days_ago in (reconcile.LOOKBACK_DAYS + 5, reconcile.LOOKBACK_DAYS + 6):
            self.add_day(days_ago)
        self.assertEqual(self.run_it()["state"], "insufficient")

    def test_the_per_day_view_carries_both_totals(self):
        for days_ago in (2, 3):
            self.add_day(days_ago)
        days = self.run_it(include_days=True)["days"]
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["export_source_kwh"], days[0]["export_meter_kwh"])
        self.assertNotIn("days", self.run_it())

    def test_the_comparison_changes_nothing(self):
        for days_ago in (2, 3):
            self.add_day(days_ago, source_factor=Decimal("1.5"))
        meter = list(MeterReading.objects.order_by("timestamp", "direction").values_list("energy_kwh", flat=True))
        supplementary = list(SupplementaryReading.objects.order_by("timestamp").values_list("export_kwh", flat=True))
        self.run_it()
        self.assertEqual(list(MeterReading.objects.order_by("timestamp", "direction").values_list("energy_kwh", flat=True)), meter)
        self.assertEqual(list(SupplementaryReading.objects.order_by("timestamp").values_list("export_kwh", flat=True)), supplementary)

    def test_a_tiny_meter_total_does_not_divide_by_zero(self):
        for days_ago in (2, 3):
            start = self.day_start(days_ago)
            for i in range(96):
                stamp = start + QUARTER * i
                for direction in ("out", "in"):
                    MeterReading.objects.create(metering_point=self.point, timestamp=stamp, energy_kwh=0, direction=direction)
                SupplementaryReading.objects.create(
                    source=self.source, metering_point=self.point, timestamp=stamp,
                    consumption_kwh=0, production_kwh=0, export_kwh=0, import_kwh=0,
                )
        result = self.run_it()
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["export_deviation_pct"], 0.0)


class StoreTests(ReconcileTestCase):
    def test_the_seven_day_result_is_stored_on_the_source(self):
        for days_ago in (2, 3):
            self.add_day(days_ago)
        result = reconcile.reconcile_and_store(self.source)
        stored = SupplementarySource.objects.get(pk=self.source.pk).reconciliation
        self.assertEqual(stored, result)
        self.assertNotIn("days", stored)
        self.assertEqual(stored["state"], "ok")

    def test_the_stored_result_is_exposed_on_the_source_payload(self):
        from metering.supplementary.testing import SOURCES_URL, client_for

        for days_ago in (2, 3):
            self.add_day(days_ago)
        reconcile.reconcile_and_store(self.source)
        body = client_for(self.holder_user).get(f"{SOURCES_URL}{self.source.pk}/").json()
        self.assertEqual(body["reconciliation"]["state"], "ok")
