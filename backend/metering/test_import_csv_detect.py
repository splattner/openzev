"""Import-settings detection: what the wizard pre-fills from the file itself."""

import io
from datetime import datetime

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers.csv_importer import _read_table
from metering.testing import detect_csv, preview_csv
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointType, Zev


def _daily_rows(*, meter="M1", days=("01.02.2026", "02.02.2026"), slots=96, sep=";", decimal=",", prefix=()):
    value = f"0{decimal}25"
    return "\n".join(
        sep.join([meter, day, *prefix, *([value] * slots)]) for day in days
    )


class DetectCsvSettingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("detect_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)
        self.zev = Zev.objects.create(name="Detect ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="D")
        for meter_id in ("M1", "CH-DEMO-CONS-0001"):
            MeteringPoint.objects.create(zev=self.zev, meter_id=meter_id, meter_type=MeteringPointType.CONSUMPTION)

    def detect(self, content, name="data.csv"):
        resp = detect_csv(self.client, name, content.encode() if isinstance(content, str) else content)
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def assert_preview_is_clean(self, content, settings):
        """The detected settings must actually parse the file they came from."""
        columns = settings["column_map"]
        fields = {f"col_{key}": value for key, value in columns.items() if value}
        resp = preview_csv(
            self.client,
            "data.csv",
            content.encode(),
            zev_id=str(self.zev.id),
            has_header=str(settings["has_header"]).lower(),
            delimiter=settings["delimiter"],
            format_profile=settings["format_profile"],
            timestamp_format=settings["timestamp_format"],
            interval_minutes=settings["interval_minutes"],
            values_count=settings["values_count"],
            **fields,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["errors"], [])
        self.assertEqual(resp.data["summary"]["missing_metering_points"], 0)
        self.assertGreater(resp.data["summary"]["rows_previewed"], 0)

    def test_standard_headed_file_with_direction(self):
        content = (
            "meter_id,timestamp,energy_kwh,direction\n"
            "M1,01.02.2026,1.25,in\n"
            "M1,02.02.2026,0.875,out\n"
        )
        settings = self.detect(content)["settings"]
        self.assertEqual(settings["format_profile"], "standard")
        self.assertTrue(settings["has_header"])
        self.assertEqual(settings["delimiter"], ",")
        self.assertEqual(settings["timestamp_format"], "%d.%m.%Y")
        self.assertEqual(
            settings["column_map"],
            {"meter_id": "meter_id", "timestamp": "timestamp", "energy_kwh": "energy_kwh",
             "direction": "direction", "energy_start": None},
        )
        self.assert_preview_is_clean(content, settings)

    def test_headerless_semicolon_file_with_decimal_commas(self):
        content = "M1;01.02.2026 00:15;1,25\nM1;01.02.2026 00:30;0,5\n"
        result = self.detect(content)
        settings = result["settings"]
        self.assertTrue(result["detected"])
        self.assertFalse(settings["has_header"])
        self.assertEqual(settings["delimiter"], ";")
        self.assertEqual(settings["timestamp_format"], "%d.%m.%Y %H:%M")
        self.assertEqual(settings["column_map"]["meter_id"], "0")
        self.assertEqual(settings["column_map"]["timestamp"], "1")
        self.assertEqual(settings["column_map"]["energy_kwh"], "2")
        self.assert_preview_is_clean(content, settings)

    def test_obis_direction_column_and_iso_timestamps(self):
        content = (
            "mp;ts;obis;kwh\n"
            "M1;2026-01-01T00:00:00Z;1-1:1.29.0*255;1.2\n"
            "M1;2026-01-01T00:15:00Z;1-1:2.29.0*255;0.3\n"
        )
        settings = self.detect(content)["settings"]
        self.assertEqual(settings["timestamp_format"], "")
        self.assertEqual(settings["column_map"]["direction"], "obis")
        self.assertEqual(settings["column_map"]["energy_kwh"], "kwh")
        self.assert_preview_is_clean(content, settings)

    def test_daily_profile_is_recognised_from_time_headers(self):
        header = "meter_id,date," + ",".join(f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 1440, 15))
        content = header + "\n" + _daily_rows(sep=",", decimal=".")
        settings = self.detect(content)["settings"]
        self.assertEqual(settings["format_profile"], "daily_15min")
        self.assertEqual(settings["values_count"], 96)
        self.assertEqual(settings["interval_minutes"], 15)
        self.assertEqual(settings["column_map"]["energy_start"], "00:00")
        self.assertEqual(settings["column_map"]["timestamp"], "date")
        self.assert_preview_is_clean(content, settings)

    def test_headerless_daily_profile_is_recognised_from_the_row_width(self):
        content = _daily_rows(prefix=("in",))
        settings = self.detect(content)["settings"]
        self.assertEqual(settings["format_profile"], "daily_15min")
        self.assertFalse(settings["has_header"])
        self.assertEqual(settings["values_count"], 96)
        self.assertEqual(settings["interval_minutes"], 15)
        self.assertEqual(settings["column_map"]["direction"], "2")
        self.assertEqual(settings["column_map"]["energy_start"], "3")
        self.assert_preview_is_clean(content, settings)

    def test_hourly_profile_with_trailing_total_column(self):
        header = "Zählpunkt;Datum;" + ";".join(f"{h:02d}:00" for h in range(24)) + ";Summe"
        rows = "\n".join(f"M1;0{d}.02.2026;" + ";".join(["1"] * 24) + ";24" for d in (1, 2))
        content = f"{header}\n{rows}"
        settings = self.detect(content)["settings"]
        self.assertEqual(settings["format_profile"], "daily_15min")
        self.assertEqual(settings["values_count"], 24)
        self.assertEqual(settings["interval_minutes"], 60)
        self.assertEqual(settings["column_map"]["meter_id"], "Zählpunkt")
        self.assert_preview_is_clean(content, settings)

    def test_headerless_daily_profile_with_a_trailing_total_column(self):
        rows = "\n".join(f"M1;0{d}.02.2026;" + ";".join(["1"] * 96) + ";96" for d in (1, 2))
        settings = self.detect(rows)["settings"]
        self.assertEqual(settings["values_count"], 96)
        self.assertEqual(settings["interval_minutes"], 15)

    def test_numeric_meter_ids_are_still_the_meter_column(self):
        settings = self.detect("meter;date;kwh\n12345;01.02.2026;1.5\n12345;02.02.2026;2.5\n")["settings"]
        self.assertEqual(settings["column_map"]["meter_id"], "meter")
        self.assertEqual(settings["column_map"]["energy_kwh"], "kwh")

    def test_unrecognised_date_format_is_reported_and_left_to_auto_detect(self):
        result = self.detect("meter_id,timestamp,energy_kwh\nM1,2026.02.01,1.5\nM1,2026.02.02,2.5\n")
        self.assertIn("timestamp_format", result["undetected"])
        self.assertEqual(result["settings"]["timestamp_format"], "")

    def test_file_without_a_date_column_is_not_detected(self):
        result = self.detect("a,b,c\nx,y,z\nx,y,z\n")
        self.assertFalse(result["detected"])
        self.assertIn("timestamp", result["undetected"])

    def test_single_line_file_is_not_detected(self):
        result = self.detect("meter_id,timestamp,energy_kwh\n")
        self.assertFalse(result["detected"])
        self.assertEqual(result["undetected"], ["file"])

    def test_excel_file_uses_real_datetime_cells(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["meter_id", "timestamp", "energy_kwh"])
        sheet.append(["M1", datetime(2026, 2, 1, 0, 15), 1.5])
        sheet.append(["M1", datetime(2026, 2, 1, 0, 30), 2.5])
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = self.detect(buffer.getvalue(), name="data.xlsx")
        settings = result["settings"]
        self.assertTrue(result["detected"])
        self.assertEqual(settings["format_profile"], "standard")
        self.assertEqual(settings["timestamp_format"], "")
        self.assertEqual(settings["column_map"]["energy_kwh"], "energy_kwh")

    def test_only_a_bounded_sample_is_read(self):
        upload = SimpleUploadedFile("big.csv", ("a,b\n" + "1,2\n" * 500).encode())
        table = _read_table(upload, has_header=False, delimiter=",", limit=10)
        self.assertEqual(len(table.rows), 10)

    def test_requires_a_file(self):
        resp = self.client.post("/api/v1/metering/import/detect-csv/", {}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_legacy_excel_is_rejected(self):
        resp = detect_csv(self.client, "old.xls", b"x")
        self.assertEqual(resp.status_code, 400)

    def test_participants_cannot_use_detection(self):
        client = APIClient()
        auth(client, make_user("detect_participant", UserRole.PARTICIPANT))
        resp = detect_csv(client, "data.csv", b"a,b\n1,2\n")
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_requests_are_rejected(self):
        resp = detect_csv(APIClient(), "data.csv", b"a,b\n1,2\n")
        self.assertIn(resp.status_code, (401, 403))
