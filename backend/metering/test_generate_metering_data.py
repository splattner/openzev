"""Regression tests for the generate_metering_data management command."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import UserRole
from metering.models import MeterReading, ReadingResolution
from testing.helpers import make_user, create_managed_zev
from zev.models import MeteringPoint, MeteringPointType


class GenerateMeteringDataResolutionTests(TestCase):
    """The command must write valid ReadingResolution choices.

    Regression guard: it previously wrote "QH" for 15-minute intervals,
    which is not a valid ReadingResolution value, so admin filtering and
    any resolution-based queries silently excluded those readings.
    """

    def setUp(self):
        self.owner = make_user("gen_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Gen ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="G"
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-GEN-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )

    def _run(self, interval):
        out = StringIO()
        call_command(
            "generate_metering_data",
            self.metering_point.meter_id,
            "consumption",
            "--start",
            "2026-01-01",
            days=1,
            interval=interval,
            stdout=out,
        )
        return out.getvalue()

    def test_15min_interval_writes_valid_resolution(self):
        self._run("15min")
        resolutions = set(
            MeterReading.objects.filter(metering_point=self.metering_point).values_list(
                "resolution", flat=True
            )
        )
        self.assertEqual(resolutions, {ReadingResolution.FIFTEEN_MIN})

    def test_hourly_interval_writes_valid_resolution(self):
        self._run("hourly")
        resolutions = set(
            MeterReading.objects.filter(metering_point=self.metering_point).values_list(
                "resolution", flat=True
            )
        )
        self.assertEqual(resolutions, {ReadingResolution.HOURLY})

    def test_all_written_resolutions_are_model_choices(self):
        """Every reading the command creates must match the model's choice set."""
        self._run("15min")
        valid = {value for value, _label in ReadingResolution.choices}
        readings = MeterReading.objects.filter(metering_point=self.metering_point)
        self.assertGreater(readings.count(), 0)
        for resolution in readings.values_list("resolution", flat=True):
            self.assertIn(resolution, valid)
