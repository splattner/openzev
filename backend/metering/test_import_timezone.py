"""Which zone offset-less import timestamps are read in, and the DST rules (ADR 0026).

Spec: docs/specs/2026-09-swiss-civil-time.md §6.1–6.2.
"""

import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers.sdatch_importer import _parse_ts
from metering.models import ImportLog, MeterReading
from metering.testing import preview_csv, upload_csv
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointType, Zev

ZURICH = ZoneInfo("Europe/Zurich")
UTC = timezone.utc


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


def _daily_row(day, values):
    return f"CH-TZ-1,{day},{','.join(values)}\n"


class ImportTimezoneTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        owner = make_user("tz_import_owner", UserRole.USER)
        auth(self.client, owner)
        self.zev = Zev.objects.create(name="TZ ZEV", owner=owner, zev_type="vzev", invoice_prefix="Z")
        self.meter = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-TZ-1", meter_type=MeteringPointType.CONSUMPTION,
        )

    def _upload(self, csv_text, **fields):
        return upload_csv(self.client, "tz.csv", csv_text.encode(), zev_id=str(self.zev.id), **fields)

    def _timestamps(self):
        return list(MeterReading.objects.order_by("timestamp").values_list("timestamp", flat=True))

    def _daily(self, rows, values_count, **fields):
        header = "meter_id,date," + ",".join(f"v{i}" for i in range(values_count)) + "\n"
        return self._upload(
            header + "".join(rows),
            format_profile="daily_15min", col_timestamp="date", col_energy_start="2",
            values_count=str(values_count), **fields,
        )

    # ── Standard profile ────────────────────────────────────────────────────

    def test_csv_offsetless_default_is_zurich(self):
        resp = self._upload("meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-01-15 14:00:00,1.0\n")

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(self._timestamps(), [_utc(2026, 1, 15, 13)])
        self.assertEqual(ImportLog.objects.get().timestamp_timezone, "Europe/Zurich")

    def test_csv_utc_option_keeps_legacy_behaviour(self):
        resp = self._upload(
            "meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-01-15 14:00:00,1.0\n", timestamp_timezone="UTC",
        )

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(self._timestamps(), [_utc(2026, 1, 15, 14)])
        self.assertEqual(ImportLog.objects.get().timestamp_timezone, "UTC")

    def test_csv_offset_ignores_timezone_setting(self):
        for zone in ("Europe/Zurich", "UTC"):
            MeterReading.objects.all().delete()
            self._upload(
                "meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-01-15T14:00:00+01:00,1.0\n", timestamp_timezone=zone,
            )
            self.assertEqual(self._timestamps(), [_utc(2026, 1, 15, 13)], zone)

    def test_csv_autumn_hour_imports_both_occurrences(self):
        rows = "".join(
            f"CH-TZ-1,2026-10-25 {hhmm},1.0\n"
            for hhmm in ("01:45", "02:00", "02:15", "02:00", "02:15", "03:00")
        )
        resp = self._upload("meter_id,timestamp,energy_kwh\n" + rows)

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 6)
        self.assertEqual(self._timestamps(), [
            _utc(2026, 10, 24, 23, 45),
            _utc(2026, 10, 25, 0, 0),  # 02:00 CEST
            _utc(2026, 10, 25, 0, 15),
            _utc(2026, 10, 25, 1, 0),  # 02:00 CET
            _utc(2026, 10, 25, 1, 15),
            _utc(2026, 10, 25, 2, 0),  # 03:00 CET
        ])

    def test_csv_autumn_hour_is_per_direction(self):
        """An in and an out row at the same wall-clock time are one occurrence each."""
        self.meter.meter_type = MeteringPointType.BIDIRECTIONAL
        self.meter.save(update_fields=["meter_type"])
        rows = "".join(
            f"CH-TZ-1,2026-10-25 02:00,1.0,{direction}\n" for direction in ("in", "out", "in", "out")
        )
        resp = self._upload("meter_id,timestamp,energy_kwh,direction\n" + rows)

        self.assertEqual(resp.data["errors"], [])
        readings = MeterReading.objects.order_by("timestamp", "direction").values_list("timestamp", "direction")
        self.assertEqual(list(readings), [
            (_utc(2026, 10, 25, 0), "in"), (_utc(2026, 10, 25, 0), "out"),
            (_utc(2026, 10, 25, 1), "in"), (_utc(2026, 10, 25, 1), "out"),
        ])

    def test_csv_spring_hour_zero_rows_skipped_with_warning(self):
        resp = self._upload(
            "meter_id,timestamp,energy_kwh\n"
            "CH-TZ-1,2026-03-29 02:00,0\n"
            "CH-TZ-1,2026-03-29 02:15,0\n"
            "CH-TZ-1,2026-03-29 03:00,1.0\n"
        )

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_skipped"], 2)
        self.assertEqual(self._timestamps(), [_utc(2026, 3, 29, 1)])
        self.assertIn(
            "Skipped 2 rows at 2026-03-29 02:00–02:59: that hour does not exist in Swiss time (DST start).",
            [warning["warning"] for warning in resp.data["warnings"]],
        )

    def test_csv_spring_hour_nonzero_row_errors(self):
        resp = self._upload("meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-03-29 02:30,1.5\n")

        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(
            resp.data["errors"][0]["error"],
            "Timestamp 2026-03-29 02:30 does not exist in Swiss time (DST start).",
        )

    def test_preview_counts_spring_gap_rows_instead_of_reporting_errors(self):
        resp = preview_csv(
            self.client, "tz.csv",
            b"meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-03-29 02:00,0\nCH-TZ-1,2026-03-29 03:00,1\n",
            zev_id=str(self.zev.id),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_skipped_dst_gap"], 1)
        self.assertEqual(resp.data["timestamp_timezone"], "Europe/Zurich")

    def test_invalid_timestamp_timezone_rejected(self):
        resp = self._upload(
            "meter_id,timestamp,energy_kwh\nCH-TZ-1,2026-01-15 14:00:00,1.0\n", timestamp_timezone="Mars/Olympus",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "timestamp_timezone must be one of Europe/Zurich, UTC.")

    # ── Daily profile ───────────────────────────────────────────────────────

    def test_daily_profile_starts_at_swiss_midnight(self):
        self._daily([_daily_row("2026-07-01", ["1", "2"])], 2)

        self.assertEqual(self._timestamps(), [_utc(2026, 6, 30, 22), _utc(2026, 6, 30, 22, 15)])

    def test_daily_profile_utc_option_starts_at_utc_midnight(self):
        self._daily([_daily_row("2026-07-01", ["1", "2"])], 2, timestamp_timezone="UTC")

        self.assertEqual(self._timestamps(), [_utc(2026, 7, 1), _utc(2026, 7, 1, 0, 15)])

    def test_daily_profile_dst_start_accepts_92_of_96_with_empty_missing_hour(self):
        values = ["1"] * 96
        values[8:12] = ["", "", "", ""]  # 02:00–02:45, which does not exist that day
        resp = self._daily([_daily_row("2026-03-29", values)], 96)

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 92)
        stamps = self._timestamps()
        self.assertEqual(stamps[0], _utc(2026, 3, 28, 23))
        self.assertEqual(stamps[8], _utc(2026, 3, 29, 1))  # 03:00 CEST follows 01:45 CET
        self.assertEqual(stamps[-1], _utc(2026, 3, 29, 21, 45))

    def test_daily_profile_dst_start_accepts_trailing_empty_columns(self):
        resp = self._daily([_daily_row("2026-03-29", ["1"] * 92 + [""] * 4)], 96)

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 92)

    def test_daily_profile_dst_start_rejects_96_filled_values(self):
        resp = self._daily([_daily_row("2026-03-29", ["1"] * 96)], 96)

        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(
            resp.data["errors"][0]["error"],
            "2026-03-29 has 92 intervals in Swiss time (DST start), but the row has 96 values.",
        )

    def test_daily_profile_dst_end_requires_100(self):
        resp = self._daily([_daily_row("2026-10-25", ["1"] * 96)], 96)

        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(
            resp.data["errors"][0]["error"],
            "2026-10-25 has 100 intervals in Swiss time (DST end), but the row has 96 values.",
        )

    def test_daily_profile_dst_end_imports_100_values(self):
        resp = self._daily([_daily_row("2026-10-25", ["1"] * 100)], 100)

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 100)
        self.assertEqual(self._timestamps()[-1], _utc(2026, 10, 25, 22, 45))

    def test_daily_profile_100_columns_on_an_ordinary_day_drops_trailing_empties(self):
        resp = self._daily([_daily_row("2026-06-01", ["1"] * 96 + [""] * 4)], 100)

        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["rows_imported"], 96)

    def test_daily_profile_existing_check_uses_the_civil_day(self):
        MeterReading.objects.create(
            metering_point=self.meter, timestamp=_utc(2026, 6, 30, 22), energy_kwh=Decimal("1"), direction="in",
        )
        resp = preview_csv(
            self.client, "tz.csv", b"meter_id,date,v0\nCH-TZ-1,2026-07-01,1\n",
            zev_id=str(self.zev.id), format_profile="daily_15min", col_timestamp="date",
            col_energy_start="2", values_count="1",
        )

        self.assertEqual(resp.data["summary"]["readings_existing"], 1)
        self.assertEqual(resp.data["preview_rows"][0]["timestamp"], "2026-07-01")


class SdatTimestampTests(SimpleTestCase):
    def test_sdat_offsetless_timestamp_is_zurich_whatever_the_process_tz(self):
        previous = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            self.assertEqual(_parse_ts("2026-01-15T14:00:00"), _utc(2026, 1, 15, 13))
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    def test_sdat_offsets_are_kept(self):
        self.assertEqual(_parse_ts("2026-07-01T00:00:00+02:00"), _utc(2026, 6, 30, 22))
        self.assertEqual(_parse_ts("2026-07-01T00:00:00Z"), _utc(2026, 7, 1))
        self.assertEqual(date(2026, 7, 1), _parse_ts("2026-07-01T00:00:00+02:00").astimezone(ZURICH).date())
