"""Upload hardening limits for the CSV/Excel import path.

Each cap is enforced before any expensive work: size via the upload's
``size`` attribute, rows/columns during streaming, ZIP members/ratio before
openpyxl inflates anything. The tests patch the module constants down to
small values rather than building multi-megabyte fixtures.
"""

import io
from datetime import date
from unittest import mock

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers import csv_importer
from metering.models import MeterReading
from metering.testing import preview_csv, upload_csv
from testing.helpers import authenticate as auth, make_user
from testing.zips import ZIP_BOMB_BYTES, zip_upload
from zev.models import MeteringPoint, MeteringPointType, Participant, Zev


class CsvLimitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("csv_limit_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)
        self.zev = Zev.objects.create(name="CSV Limit ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="X")

    def test_file_over_size_cap_is_rejected(self):
        with mock.patch.object(csv_importer, "MAX_CSV_BYTES", 10):
            resp = upload_csv(self.client, "big.csv", b"meter_id,timestamp,energy_kwh\n" + b"x" * 100)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too large", resp.data["error"])

    def test_file_over_row_cap_is_rejected(self):
        rows = b"".join(b"CH-X,2026-01-01T00:00:00Z,1.0\n" for _ in range(4))
        with mock.patch.object(csv_importer, "MAX_CSV_ROWS", 3):
            resp = upload_csv(self.client, "rows.csv", b"meter_id,timestamp,energy_kwh\n" + rows)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too many rows", resp.data["error"])

    def test_row_cap_counts_data_rows_not_the_header(self):
        # Header + exactly MAX_CSV_ROWS data rows must fit — the header is not
        # a data row and must not consume the cap.
        rows = b"".join(b"CH-X,2026-01-01T00:00:00Z,1.0\n" for _ in range(3))
        with mock.patch.object(csv_importer, "MAX_CSV_ROWS", 3):
            resp = upload_csv(self.client, "rows.csv", b"meter_id,timestamp,energy_kwh\n" + rows)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 3)

    def test_row_cap_headerless_file_gets_the_full_budget(self):
        # Without a header the file may carry exactly MAX_CSV_ROWS rows — the
        # +1 headroom applies only when a header row exists.
        rows = b"".join(b"CH-X,2026-01-01T00:00:00Z,1.0\n" for _ in range(3))
        with mock.patch.object(csv_importer, "MAX_CSV_ROWS", 3):
            resp = upload_csv(
                self.client, "rows.csv", rows,
                has_header="false", col_meter_id="0", col_timestamp="1", col_energy_kwh="2",
            )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 3)

    def test_row_cap_headerless_file_over_the_cap_is_rejected(self):
        rows = b"".join(b"CH-X,2026-01-01T00:00:00Z,1.0\n" for _ in range(4))
        with mock.patch.object(csv_importer, "MAX_CSV_ROWS", 3):
            resp = upload_csv(
                self.client, "rows.csv", rows,
                has_header="false", col_meter_id="0", col_timestamp="1", col_energy_kwh="2",
            )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too many rows", resp.data["error"])

    def test_file_over_column_cap_is_rejected(self):
        with mock.patch.object(csv_importer, "MAX_CSV_COLUMNS", 3):
            resp = upload_csv(self.client, "cols.csv", b"a,b,c,d\n1,2,3,4\n")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too many columns", resp.data["error"])

    def test_values_count_above_maximum_is_rejected(self):
        resp = upload_csv(
            self.client, "vc.csv", b"meter_id,date,1,2\nCH-X,2026-01-01,1,2\n",
            format_profile="daily_15min", values_count="2000",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("values_count must be between 1 and 1440", resp.data["error"])

    def test_values_count_below_one_is_rejected_on_import_and_preview(self):
        csv_bytes = b"meter_id,date,1,2\nCH-X,2026-01-01,1,2\n"
        resp = upload_csv(
            self.client, "vc0.csv", csv_bytes, format_profile="daily_15min", values_count="0"
        )
        self.assertEqual(resp.status_code, 400)
        resp = preview_csv(
            self.client, "vc0.csv", csv_bytes, format_profile="daily_15min", values_count="0"
        )
        self.assertEqual(resp.status_code, 400)

    def test_values_count_at_maximum_is_accepted(self):
        self.mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-LIMIT-1", meter_type=MeteringPointType.CONSUMPTION
        )
        Participant.objects.create(
            zev=self.zev, first_name="L", last_name="P", email="limit@example.com",
            valid_from=date(2026, 1, 1),
        )

        resp = upload_csv(
            self.client, "vc.csv", b"meter_id,timestamp,energy_kwh\nCH-LIMIT-1,2026-01-01T00:00:00Z,1.0\n",
            values_count="1440",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(MeterReading.objects.count(), 1)

    def test_non_integer_interval_or_values_count_is_rejected(self):
        resp = upload_csv(
            self.client, "vc.csv", b"meter_id,timestamp,energy_kwh\nCH-X,2026-01-01T00:00:00Z,1.0\n",
            values_count="abc",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("values_count must be an integer", resp.data["error"])

    def test_row_error_list_is_capped_with_a_truncation_note(self):
        rows = b"".join(
            f"NOPE-{i},2026-01-01T00:00:00Z,1.0\n".encode() for i in range(60)
        )

        resp = upload_csv(self.client, "errs.csv", b"meter_id,timestamp,energy_kwh\n" + rows)

        self.assertEqual(resp.status_code, 201)
        errors = resp.data["errors"]
        self.assertEqual(len(errors), csv_importer.MAX_REPORTED_ERRORS + 1)
        self.assertIn("Too many errors", errors[-1]["error"])

    def test_overwrite_note_cannot_push_the_error_list_past_its_cap(self):
        MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-LIMIT-1", meter_type=MeteringPointType.CONSUMPTION
        )
        header = b"meter_id,timestamp,energy_kwh\n"
        rows = b"CH-LIMIT-1,2026-01-01T00:00:00Z,1.0\n" + b"".join(
            f"NOPE-{i},2026-01-01T00:00:00Z,1.0\n".encode() for i in range(60)
        )
        upload_csv(self.client, "ov.csv", header + rows)
        resp = upload_csv(self.client, "ov.csv", header + rows, overwrite_existing="true")

        self.assertEqual(resp.status_code, 201)
        errors = resp.data["errors"]
        self.assertEqual(len(errors), csv_importer.MAX_REPORTED_ERRORS + 1)
        self.assertEqual(errors[0]["error"], "Overwrote 1 existing readings.")
        self.assertIn("Too many errors", errors[-1]["error"])

    def test_interval_minutes_below_one_is_rejected(self):
        csv_bytes = b"meter_id,date,1,2\nCH-X,2026-01-01,1,2\n"
        resp = upload_csv(
            self.client, "iv.csv", csv_bytes, format_profile="daily_15min", interval_minutes="0"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("interval_minutes must be at least 1", resp.data["error"])
        resp = preview_csv(
            self.client, "iv.csv", csv_bytes, format_profile="daily_15min", interval_minutes="0"
        )
        self.assertEqual(resp.status_code, 400)


class XlsxZipLimitTests(TestCase):
    """The XLSX pre-inflation ZIP checks: member count and compression ratio."""

    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("xlsx_limit_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)

    def _upload(self, upload):
        return self.client.post(
            "/api/v1/metering/import/csv/", {"file": upload}, format="multipart"
        )

    def test_zip_with_too_many_members_is_rejected(self):
        members = {f"part{i}.xml": b"<x/>" for i in range(6)}
        with mock.patch.object(csv_importer, "MAX_XLSX_MEMBERS", 5):
            resp = self._upload(zip_upload("bomb.xlsx", members))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too many members", resp.data["error"])

    def test_zip_with_a_high_ratio_member_is_rejected(self):
        resp = self._upload(zip_upload("bomb.xlsx", {"xl/sharedStrings.xml": ZIP_BOMB_BYTES}))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("suspicious compression ratio", resp.data["error"])

    def test_non_zip_xlsx_is_rejected(self):
        resp = self._upload(SimpleUploadedFile("fake.xlsx", b"not a zip", content_type="text/csv"))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Could not read the Excel file", resp.data["error"])

    def test_wide_row_past_the_first_is_rejected(self):
        # The column cap must hold for every row: a sheet whose width only
        # shows up after row 1 (openpyxl may or may not pad row 1 to the
        # sheet's declared width) still has to be refused.
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["a"])
        sheet.append(["b", "c", "d", "e"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile(
            "wide.xlsx", buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        with mock.patch.object(csv_importer, "MAX_CSV_COLUMNS", 3):
            resp = self._upload(upload)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("too many columns", resp.data["error"])
