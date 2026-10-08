"""The one definition of gross-energy figures (SPEC §4.3, §4.4)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase, override_settings

from metering.models import SupplementaryReading, SupplementarySource
from metering.supplementary import stats
from testing import factories
from zev.models import AllocationMode, MeteringPointType

D = Decimal
START = datetime(2026, 7, 1, tzinfo=timezone.utc)
SLOT = timedelta(minutes=15)


class SelfConsumptionTests(TestCase):
    def test_formula(self):
        # Production minus export, never negative, never above production or consumption.
        self.assertEqual(stats.self_consumption(D("5"), D("2"), D("10")), D("3"))
        self.assertEqual(stats.self_consumption(D("5"), D("2"), D("1")), D("1"))
        self.assertEqual(stats.self_consumption(D("2"), D("3"), D("10")), D("0"))
        self.assertEqual(stats.self_consumption(D("0"), D("0"), D("10")), D("0"))


class GrossEnergyTests(TestCase):
    def setUp(self):
        self.zev = factories.ZevFactory()
        self.participant = factories.ParticipantFactory(zev=self.zev, valid_from=date(2026, 1, 1))
        self.point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        self.assignment = factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.participant, valid_from=date(2026, 1, 1)
        )
        self.source = SupplementarySource.objects.create(
            metering_point=self.point, participant=self.participant, provider="push"
        )

    def add(self, offset, consumption, production, imported, exported, *, source=None):
        SupplementaryReading.objects.create(
            source=source or self.source,
            metering_point=self.point,
            timestamp=START + offset * SLOT,
            consumption_kwh=consumption,
            production_kwh=production,
            import_kwh=imported,
            export_kwh=exported,
        )

    def covered(self, slots, *, source=None):
        source = source or self.source
        source.covers_from = START
        source.synced_through = START + slots * SLOT
        source.save()

    def figures(self, slots=None, **kwargs):
        slots = slots or 96
        return stats.gross_energy([self.participant.pk], START, START + slots * SLOT, **kwargs)

    # ---- rates ----

    def test_rates_from_hand_computed_intervals(self):
        # (consumption, production, import, export)
        rows = [("2", "0", "2", "0"), ("3", "6", "0", "4"), ("4", "4", "1", "1"), ("1", "0", "1", "0")]
        for i, (c, p, im, ex) in enumerate(rows):
            self.add(i, D(c), D(p), D(im), D(ex))
        self.covered(4)

        result = self.figures(4)

        self.assertEqual(result["consumption_kwh"], 10.0)
        self.assertEqual(result["production_kwh"], 10.0)
        self.assertEqual(result["import_kwh"], 4.0)
        self.assertEqual(result["export_kwh"], 5.0)
        # self-consumption per interval: 0, min(2, 6, 3)=2, min(3, 4, 4)=3, 0
        self.assertEqual(result["self_consumption_kwh"], 5.0)
        self.assertEqual(result["self_sufficiency_rate"], 60.0)  # 1 - 4/10
        self.assertEqual(result["self_consumption_rate"], 50.0)  # 5/10
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertIsNone(result["rates_withheld_reason"])
        self.assertEqual(result["source_provider"], "push")

    def test_rates_are_none_when_the_denominator_is_zero(self):
        self.add(0, D("0"), D("0"), D("0"), D("0"))
        self.covered(1)
        result = self.figures(1)
        self.assertIsNone(result["self_sufficiency_rate"])
        self.assertIsNone(result["self_consumption_rate"])
        self.assertIsNone(result["rates_withheld_reason"])

    def test_self_sufficiency_is_clamped(self):
        # Import above consumption (clock skew between meters) must not go negative.
        self.add(0, D("1"), D("0"), D("2"), D("0"))
        self.covered(1)
        self.assertEqual(self.figures(1)["self_sufficiency_rate"], 0.0)

    # ---- coverage ----

    def test_no_source_means_none(self):
        other = factories.ParticipantFactory(zev=self.zev)
        self.assertIsNone(stats.gross_energy([other.pk], START, START + 96 * SLOT))

    def test_a_source_that_never_ingested_expects_nothing(self):
        self.assertIsNone(self.figures())

    def test_missing_intervals_lower_coverage(self):
        for i in range(0, 19):  # 19 of 20 expected = 95 %
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.covered(20)
        result = self.figures(20)
        self.assertEqual(result["coverage_pct"], 95.0)
        self.assertIsNone(result["rates_withheld_reason"])
        self.assertEqual(result["self_sufficiency_rate"], 100.0)

    def test_rates_withheld_below_minimum_coverage(self):
        for i in range(0, 18):  # 18 of 20 = 90 %
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.covered(20)
        result = self.figures(20)
        self.assertEqual(result["coverage_pct"], 90.0)
        self.assertEqual(result["rates_withheld_reason"], "low_coverage")
        self.assertIsNone(result["self_sufficiency_rate"])
        self.assertIsNone(result["self_consumption_rate"])
        # The sums are still reported.
        self.assertEqual(result["consumption_kwh"], 18.0)

    @override_settings(SUPPLEMENTARY_MIN_COVERAGE=0.5)
    def test_minimum_coverage_is_a_setting(self):
        for i in range(0, 18):
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.covered(20)
        self.assertIsNone(self.figures(20)["rates_withheld_reason"])

    def test_no_rows_at_all_is_no_data(self):
        self.covered(8)
        result = self.figures(8)
        self.assertEqual(result["rates_withheld_reason"], "no_data")
        self.assertEqual(result["coverage_pct"], 0.0)

    def test_only_the_synced_range_is_expected(self):
        # Connected late: the window is 96 slots, the source covers only the last 48.
        for i in range(48, 96):
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.source.covers_from = START + 48 * SLOT
        self.source.synced_through = START + 96 * SLOT
        self.source.save()
        result = self.figures(96)
        self.assertEqual(result["coverage_pct"], 100.0)
        self.assertEqual(result["covered_from"], START + 48 * SLOT)
        self.assertEqual(result["covered_to"], START + 96 * SLOT)

    # ---- who held the meter ----

    def test_window_clipped_to_the_personal_assignment(self):
        # Assignment starts at Swiss midnight of 2 July (22:00 UTC on 1 July).
        self.assignment.valid_from = date(2026, 7, 2)
        self.assignment.save()
        for i in range(0, 48):  # all of 1 July UTC, before the assignment
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.covered(96)

        # 1 July 00:00-22:00 UTC is before the holder had the meter; only 22:00-24:00 UTC counts.
        result = self.figures(96)
        self.assertEqual(result["covered_from"], datetime(2026, 7, 1, 22, tzinfo=timezone.utc))
        self.assertEqual(result["coverage_pct"], 0.0)
        self.assertEqual(result["consumption_kwh"], 0.0)  # earlier rows are not counted
        self.assertEqual(result["rates_withheld_reason"], "no_data")

    def test_a_later_holder_does_not_count_the_earlier_holders_data(self):
        self.assignment.valid_to = date(2026, 7, 1)
        self.assignment.save()
        newcomer = factories.ParticipantFactory(zev=self.zev, valid_from=date(2026, 1, 1))
        factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=newcomer, valid_from=date(2026, 7, 2)
        )
        for i in range(0, 96):
            self.add(i, D("1"), D("1"), D("0"), D("0"))
        self.covered(96)
        self.assertIsNone(stats.gross_energy([newcomer.pk], START, START + 96 * SLOT))

    def test_community_assignment_is_excluded(self):
        self.assignment.allocation_mode = AllocationMode.COMMUNITY
        self.assignment.save()
        self.add(0, D("1"), D("1"), D("0"), D("0"))
        self.covered(4)
        self.assertIsNone(self.figures(4))

    def test_back_to_back_assignments_merge_into_one_window(self):
        self.assignment.valid_to = date(2026, 3, 31)
        self.assignment.save()
        factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.participant, valid_from=date(2026, 4, 1)
        )
        self.assertEqual(len(stats.personal_windows(self.source)), 1)

    def test_a_gap_between_assignments_stays_a_gap(self):
        self.assignment.valid_to = date(2026, 3, 31)
        self.assignment.save()
        factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.participant, valid_from=date(2026, 4, 5)
        )
        self.assertEqual(len(stats.personal_windows(self.source)), 2)

    # ---- sources ----

    def test_a_disconnected_source_still_counts(self):
        self.add(0, D("2"), D("0"), D("2"), D("0"))
        self.covered(1)
        self.source.disconnect()
        self.source.save()
        self.assertEqual(self.figures(1)["consumption_kwh"], 2.0)

    def test_several_flagged_meters_are_summed(self):
        point2 = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        factories.MeteringPointAssignmentFactory(
            metering_point=point2, participant=self.participant, valid_from=date(2026, 1, 1)
        )
        source2 = SupplementarySource.objects.create(
            metering_point=point2, participant=self.participant, provider="push"
        )
        self.add(0, D("2"), D("0"), D("2"), D("0"))
        SupplementaryReading.objects.create(
            source=source2, metering_point=point2, timestamp=START,
            consumption_kwh=D("3"), production_kwh=D("0"), import_kwh=D("3"), export_kwh=D("0"),
        )
        self.covered(1)
        self.covered(1, source=source2)
        result = self.figures(1)
        self.assertEqual(result["consumption_kwh"], 5.0)
        self.assertEqual(result["coverage_pct"], 100.0)

    # ---- timeline ----

    def test_timeline_buckets_by_the_given_key(self):
        for i in range(0, 8):
            self.add(i, D("1"), D("2"), D("0"), D("1"))
        self.covered(8)
        result = self.figures(8, bucket_key=lambda ts: ts.replace(minute=0, second=0, microsecond=0))
        self.assertEqual([point["bucket"] for point in result["timeline"]], [START, START + timedelta(hours=1)])
        first = result["timeline"][0]
        self.assertEqual(
            (first["consumption_kwh"], first["production_kwh"], first["export_kwh"], first["self_consumption_kwh"]),
            (4.0, 8.0, 4.0, 4.0),
        )

    def test_no_timeline_unless_asked(self):
        self.add(0, D("1"), D("1"), D("0"), D("0"))
        self.covered(1)
        self.assertNotIn("timeline", self.figures(1))
