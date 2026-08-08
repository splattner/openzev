"""Behavioural tests for the CSV/Excel metering import.

Written as characterization tests to make the pandas removal safe, and kept
afterwards as the regression suite for the parser. They cover the paths the rest
of the suite misses: the frontend defaults to ``format_profile=daily_15min`` with
``timestamp_format='%d.%m.%Y'`` (see ``frontend/src/pages/ImportsPage.tsx``), so
real traffic goes through ``datetime.strptime`` — and Excel, which is offered in
the file picker, had no coverage at all.

Several tests pin behaviour that is non-obvious but load-bearing (trailing vs
mid-file blank rows, row numbering across blank lines, the missing-vs-empty cell
distinction). Those assertions are deliberate, not incidental.
"""

import io
from datetime import datetime, timezone
from decimal import Decimal

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from metering.models import MeterReading
from metering.testing import preview_csv, upload_csv
from testing.helpers import authenticate as auth
from zev.models import MeteringPoint, MeteringPointType, Zev

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class CsvImportCharacterizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="charact_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        auth(self.client, self.owner)
        self.zev = Zev.objects.create(
            name="Characterization ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="X"
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-IMPORT-1", meter_type=MeteringPointType.CONSUMPTION
        )
        # A purely numeric meter id, to pin pandas' dtype inference.
        self.numeric_metering_point = MeteringPoint.objects.create(
            zev=self.zev, meter_id="1234", meter_type=MeteringPointType.CONSUMPTION
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _xlsx_bytes(rows, *, extra_sheet_rows=None, active_index=0):
        """Build a workbook in memory. Data goes on the FIRST sheet."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "First"
        for row in rows:
            ws.append(row)
        if extra_sheet_rows is not None:
            second = wb.create_sheet("Second")
            for row in extra_sheet_rows:
                second.append(row)
        wb.active = active_index
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _upload_xlsx(self, name, rows, *, extra_sheet_rows=None, active_index=0, **fields):
        upload = SimpleUploadedFile(
            name,
            self._xlsx_bytes(rows, extra_sheet_rows=extra_sheet_rows, active_index=active_index),
            content_type=XLSX_CONTENT_TYPE,
        )
        return self.client.post(
            "/api/v1/metering/import/csv/", {"file": upload, **fields}, format="multipart"
        )

    def _preview_xlsx(self, name, rows, **fields):
        upload = SimpleUploadedFile(name, self._xlsx_bytes(rows), content_type=XLSX_CONTENT_TYPE)
        return self.client.post(
            "/api/v1/metering/import/preview-csv/", {"file": upload, **fields}, format="multipart"
        )

    def _timestamps(self, metering_point=None):
        qs = MeterReading.objects.filter(metering_point=metering_point or self.metering_point)
        return list(qs.order_by("timestamp").values_list("timestamp", flat=True))

    # ── A. Excel (no coverage before this file) ──────────────────────────────

    def test_xlsx_reads_first_sheet_not_the_active_sheet(self):
        """pandas uses sheet_name=0. openpyxl's wb.active is whatever tab was
        selected on save, so a reimplementation must use worksheets[0]."""
        resp = self._upload_xlsx(
            "sheets.xlsx",
            [
                ["meter_id", "timestamp", "energy_kwh"],
                ["CH-IMPORT-1", "2026-02-01T00:00:00Z", "1.5"],
            ],
            extra_sheet_rows=[["meter_id", "timestamp", "energy_kwh"], ["CH-IMPORT-1", "bogus", "9"]],
            active_index=1,
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)]
        )

    def test_xlsx_native_datetime_cell_is_assumed_utc(self):
        resp = self._upload_xlsx(
            "dt.xlsx",
            [
                ["meter_id", "timestamp", "energy_kwh"],
                ["CH-IMPORT-1", datetime(2026, 2, 2, 5, 30), "2.5"],
            ],
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 2, 2, 5, 30, tzinfo=timezone.utc)]
        )

    def test_xlsx_trailing_empty_rows_are_excluded_from_rows_total(self):
        resp = self._preview_xlsx(
            "trailing.xlsx",
            [
                ["meter_id", "timestamp", "energy_kwh"],
                ["CH-IMPORT-1", "2026-02-03T00:00:00Z", "1.0"],
                [None, None, None],
                [None, None, None],
            ],
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 1)

    def test_xlsx_mid_file_empty_row_is_counted_and_skipped(self):
        """pandas trims trailing blank rows but keeps mid-file ones."""
        resp = self._upload_xlsx(
            "midblank.xlsx",
            [
                ["meter_id", "timestamp", "energy_kwh"],
                ["CH-IMPORT-1", "2026-02-04T00:00:00Z", "1.0"],
                [None, None, None],
                ["CH-IMPORT-1", "2026-02-05T00:00:00Z", "2.0"],
            ],
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 2)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Missing meter_id" in err["error"] for err in resp.data["errors"]))

    def test_xlsx_blank_interval_cell_is_skipped_not_zero(self):
        resp = self._upload_xlsx(
            "daily.xlsx",
            [
                ["meter_id", "date", "v1", "v2"],
                ["CH-IMPORT-1", "2026-02-06", 1.0, None],
            ],
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="2",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 2, 6, 0, 0, tzinfo=timezone.utc)]
        )

    def test_xlsx_text_date_cell_with_timestamp_format(self):
        resp = self._upload_xlsx(
            "textdate.xlsx",
            [
                ["meter_id", "date", "v1"],
                ["CH-IMPORT-1", "07.02.2026", 1.0],
            ],
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
            timestamp_format="%d.%m.%Y",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 2, 7, 0, 0, tzinfo=timezone.utc)]
        )

    # ── B. timestamp_format: the actual production path ──────────────────────

    def test_daily_profile_with_frontend_default_settings(self):
        """The highest-value test here: this is what the UI actually sends.

        Defaults from ImportsPage.tsx — headerless, semicolon-delimited,
        daily_15min, '%d.%m.%Y', meter_id at 0, date at 3, values from 4.
        """
        csv_bytes = b"CH-IMPORT-1;meta;meta;07.03.2026;1,0;2,0;3,0;4,0\n"

        resp = upload_csv(self.client,
            "production.csv",
            csv_bytes,
            has_header="false",
            delimiter=";",
            format_profile="daily_15min",
            timestamp_format="%d.%m.%Y",
            col_meter_id="0",
            col_timestamp="3",
            col_energy_start="4",
            values_count="4",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 4)
        self.assertEqual(
            self._timestamps(),
            [
                datetime(2026, 3, 7, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 7, 0, 15, tzinfo=timezone.utc),
                datetime(2026, 3, 7, 0, 30, tzinfo=timezone.utc),
                datetime(2026, 3, 7, 0, 45, tzinfo=timezone.utc),
            ],
        )
        energies = list(
            MeterReading.objects.filter(metering_point=self.metering_point)
            .order_by("timestamp")
            .values_list("energy_kwh", flat=True)
        )
        self.assertEqual(
            energies,
            [Decimal("1.0000"), Decimal("2.0000"), Decimal("3.0000"), Decimal("4.0000")],
        )

    def test_standard_profile_with_timestamp_format_forces_utc(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,08.03.2026 13:45,1.5000\n"
        )

        resp = upload_csv(self.client,
            "fmt.csv", csv_bytes, timestamp_format="%d.%m.%Y %H:%M"
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 3, 8, 13, 45, tzinfo=timezone.utc)]
        )

    def test_timestamp_format_mismatch_is_skipped_not_a_server_error(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-03-09T00:00:00Z,1.5000\n"
        )

        resp = upload_csv(self.client, "mismatch.csv", csv_bytes, timestamp_format="%d.%m.%Y")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertEqual(MeterReading.objects.count(), 0)

    # ── C. Date parsing without an explicit format ───────────────────────────

    def _daily_date_upload(self, name, raw_date):
        return upload_csv(self.client,
            name,
            b"meter_id,date,v1\nCH-IMPORT-1," + raw_date + b",1.0000\n",
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="1",
        )

    def test_daily_profile_parses_dotted_date_day_first(self):
        resp = self._daily_date_upload("dotted.csv", b"07.04.2026")

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 4, 7, 0, 0, tzinfo=timezone.utc)]
        )

    def test_daily_profile_parses_slashed_date_day_first(self):
        resp = self._daily_date_upload("slashed.csv", b"07/04/2026")

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 4, 7, 0, 0, tzinfo=timezone.utc)]
        )

    def test_preview_daily_profile_falls_back_to_raw_string_for_unparsable_date(self):
        resp = preview_csv(self.client,
            "unparsable.csv",
            b"meter_id,date,v1\nCH-IMPORT-1,not-a-date,1.0000\n",
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preview_rows"][0]["timestamp"], "not-a-date")

    # ── D. Standard timestamps ───────────────────────────────────────────────

    def test_naive_timestamp_is_assumed_utc(self):
        resp = upload_csv(self.client,
            "naive.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-05-01 05:00:00,1.0000\n",
        )

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 5, 1, 5, 0, tzinfo=timezone.utc)]
        )

    def test_date_only_timestamp_becomes_midnight_utc(self):
        resp = upload_csv(self.client,
            "dateonly.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-05-02,1.0000\n",
        )

        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            self._timestamps(), [datetime(2026, 5, 2, 0, 0, tzinfo=timezone.utc)]
        )

    def test_unparsable_timestamp_is_skipped_and_reported(self):
        resp = upload_csv(self.client,
            "badts.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,definitely-not-a-date,1.0000\n",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertEqual(MeterReading.objects.count(), 0)

    # ── E. Table shape ──────────────────────────────────────────────────────

    def test_blank_line_is_skipped_and_row_numbers_compact_over_it(self):
        """pandas' skip_blank_lines also compacts the index, so the row *after*
        a blank line is numbered as if the blank had never existed. A rewrite
        must not "fix" this numbering or the reported rows drift."""
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-06-01T00:00:00Z,1.0000\n"
            b"\n"
            b"CH-UNKNOWN,2026-06-02T00:00:00Z,2.0000\n"
        )

        resp = upload_csv(self.client, "blankline.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 2)
        self.assertEqual(resp.data["rows_imported"], 1)
        not_found = [err for err in resp.data["errors"] if "not found" in err["error"]]
        self.assertEqual(len(not_found), 1)
        self.assertEqual(not_found[0]["row"], 3)

    def test_short_row_is_padded_to_header_width(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-06-03T00:00:00Z\n"
        )

        resp = upload_csv(self.client, "short.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any("Missing numeric value" in err["error"] for err in resp.data["errors"]))

    def test_bom_prefixed_header_still_resolves_by_name(self):
        csv_bytes = (
            b"\xef\xbb\xbfmeter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-06-04T00:00:00Z,1.0000\n"
        )

        resp = upload_csv(self.client, "bom.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)

    def test_quoted_field_containing_the_delimiter_is_not_split(self):
        csv_bytes = (
            b'meter_id,timestamp,energy_kwh,note\n'
            b'CH-IMPORT-1,2026-06-05T00:00:00Z,1.0000,"a,b"\n'
        )

        resp = upload_csv(self.client, "quoted.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)

    def test_column_index_out_of_range_reports_the_range(self):
        resp = upload_csv(self.client,
            "oor.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-06-06T00:00:00Z,1.0000\n",
            col_meter_id="99",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            any(
                "Column index 99 is out of range (0..2)." in err["error"]
                for err in resp.data["errors"]
            ),
            resp.data["errors"],
        )

    def test_unknown_column_name_is_reported_by_name(self):
        resp = upload_csv(self.client,
            "unknown.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-06-07T00:00:00Z,1.0000\n",
            col_meter_id="nope",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            any("Column 'nope' not found." in err["error"] for err in resp.data["errors"]),
            resp.data["errors"],
        )

    def test_daily_profile_reports_an_error_per_missing_interval_column(self):
        csv_bytes = b"meter_id,date,v1,v2\nCH-IMPORT-1,2026-06-08,1.0000,2.0000\n"

        resp = upload_csv(self.client,
            "shortslots.csv",
            csv_bytes,
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
            values_count="4",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 2)
        missing_slots = [
            err for err in resp.data["errors"] if "Missing interval column" in err["error"]
        ]
        self.assertEqual(len(missing_slots), 2)

    # ── F. Value coercion — where the latent bugs live ───────────────────────

    def test_numeric_meter_id_column_matches_the_metering_point(self):
        """An all-numeric column infers int64, whose str() is '1234'."""
        csv_bytes = b"meter_id,timestamp,energy_kwh\n1234,2026-07-01T00:00:00Z,1.0000\n"

        resp = upload_csv(self.client, "numeric.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            MeterReading.objects.filter(metering_point=self.numeric_metering_point).count(), 1
        )

    def test_numeric_meter_id_column_with_a_blank_row_still_matches(self):
        """Regression test for a bug pandas caused.

        Under pandas a single empty cell forced the column to float64, so the
        valid meter id 1234 stringified to '1234.0' and lookup failed with a
        misleading "not found" — silently dropping a good row. Reading cells as
        text keeps the id intact.
        """
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"1234,2026-07-02T00:00:00Z,1.0000\n"
            b",2026-07-02T00:15:00Z,2.0000\n"
        )

        resp = upload_csv(self.client, "numeric-blank.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(
            MeterReading.objects.filter(metering_point=self.numeric_metering_point).count(), 1
        )

    def test_literal_nan_energy_value_is_rejected(self):
        """Asserts the outcome, not the message: pandas coerces the text 'nan'
        to a real NaN today, but Decimal('nan') is a *valid* Decimal, so a
        pandas-free implementation must reject non-finite values explicitly or
        NaN reaches the database."""
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-07-03T00:00:00Z,nan\n"

        resp = upload_csv(self.client, "nan.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_literal_infinite_energy_value_is_rejected(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-07-04T00:00:00Z,inf\n"

        resp = upload_csv(self.client, "inf.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_four_decimal_energy_is_preserved_exactly(self):
        csv_bytes = b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-07-05T00:00:00Z,1.2345\n"

        resp = upload_csv(self.client, "decimals.csv", csv_bytes)

        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.energy_kwh, Decimal("1.2345"))

    def test_comma_decimal_energy_is_accepted_on_the_headered_path(self):
        csv_bytes = (
            b"meter_id;timestamp;energy_kwh\n"
            b"CH-IMPORT-1;2026-07-06T00:00:00Z;6,2500\n"
        )

        resp = upload_csv(self.client, "commadec.csv", csv_bytes, delimiter=";")

        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.energy_kwh, Decimal("6.2500"))

    def test_whitespace_only_meter_id_reports_empty_rather_than_missing(self):
        """Empty and whitespace-only cells take *different* branches: pandas
        NaNs an empty field but keeps '   ' as a string. Both messages must
        survive a rewrite, which is why the missing-value check must not strip.
        """
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b'"   ",2026-07-07T00:00:00Z,1.0000\n'
        )

        resp = upload_csv(self.client, "wsmeter.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            any("Empty meter_id value." in err["error"] for err in resp.data["errors"]),
            resp.data["errors"],
        )

    def test_blank_meter_id_reports_missing(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b",2026-07-08T00:00:00Z,1.0000\n"
        )

        resp = upload_csv(self.client, "blankmeter.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            any("Missing meter_id value." in err["error"] for err in resp.data["errors"]),
            resp.data["errors"],
        )

    def test_direction_mapped_to_an_unknown_column_is_silently_ignored(self):
        """Unlike the required columns, an unresolvable direction mapping is
        swallowed and treated as 'no explicit direction'."""
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-07-09T00:00:00Z,1.0000\n"
        )

        resp = upload_csv(self.client, "nodirection.csv", csv_bytes, col_direction="does_not_exist")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)

    # ── G. Preview ──────────────────────────────────────────────────────────

    def test_preview_caps_rows_at_max_rows_but_reports_the_full_total(self):
        rows = b"".join(
            b"CH-IMPORT-1,2026-08-01T%02d:00:00Z,1.0000\n" % hour for hour in range(24)
        ) + b"".join(
            b"CH-IMPORT-1,2026-08-02T%02d:00:00Z,1.0000\n" % hour for hour in range(11)
        )
        csv_bytes = b"meter_id,timestamp,energy_kwh\n" + rows

        resp = preview_csv(self.client, "many.csv", csv_bytes)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 35)
        self.assertEqual(resp.data["summary"]["rows_previewed"], 30)
        self.assertEqual(resp.data["preview_rows"][0]["row"], 2)
        self.assertEqual(resp.data["preview_rows"][-1]["row"], 31)

    def test_preview_daily_profile_flags_rows_that_already_have_data(self):
        MeterReading.objects.create(
            metering_point=self.metering_point,
            timestamp=datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("1.0000"),
            direction="in",
            resolution="hourly",
            import_source="manual",
        )

        resp = preview_csv(self.client,
            "existing.csv",
            b"meter_id,date,v1\nCH-IMPORT-1,2026-08-03,1.0000\n",
            format_profile="daily_15min",
            col_timestamp="date",
            col_energy_start="2",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["preview_rows"][0]["existing_data"])
        self.assertEqual(resp.data["preview_rows"][0]["timestamp"], "2026-08-03")

    def test_preview_column_error_returns_total_with_no_preview_rows(self):
        resp = preview_csv(self.client,
            "colerr.csv",
            b"meter_id,timestamp,energy_kwh\nCH-IMPORT-1,2026-08-04T00:00:00Z,1.0000\n",
            col_timestamp="missing_column",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["rows_total"], 1)
        self.assertEqual(resp.data["preview_rows"], [])
        self.assertEqual(resp.data["summary"]["rows_previewed"], 0)
        self.assertEqual(len(resp.data["errors"]), 1)
        self.assertIsNone(resp.data["errors"][0]["row"])

    # ── H. Unreadable files are rejected with 400, not a 500 ─────────────────

    def test_legacy_xls_is_rejected_with_a_helpful_message(self):
        """`.xls` was advertised by the file picker but never worked (xlrd is not
        installed), so it surfaced as an opaque 500."""
        upload = SimpleUploadedFile(
            "legacy.xls", b"\xd0\xcf\x11\xe0\x00\x00\x00\x00", content_type="application/vnd.ms-excel"
        )

        resp = self.client.post(
            "/api/v1/metering/import/csv/", {"file": upload}, format="multipart"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn(".xlsx", resp.data["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_multi_character_delimiter_is_rejected_with_a_helpful_message(self):
        resp = upload_csv(self.client,
            "multidelim.csv",
            b"meter_id;;timestamp;;energy_kwh\nCH-IMPORT-1;;2026-09-01T00:00:00Z;;1.0000\n",
            delimiter=";;",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("single character", resp.data["error"])

    def test_tab_delimiter_can_be_requested_as_a_backslash_escape(self):
        resp = upload_csv(self.client,
            "tabs.csv",
            b"meter_id\ttimestamp\tenergy_kwh\nCH-IMPORT-1\t2026-09-02T00:00:00Z\t1.0000\n",
            delimiter="\\t",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)

    def test_non_utf8_file_is_rejected_with_a_helpful_message(self):
        resp = upload_csv(self.client,
            "latin1.csv",
            "meter_id,timestamp,energy_kwh,note\nCH-IMPORT-1,2026-09-03T00:00:00Z,1.0,Zürich\n".encode(
                "latin-1"
            ),
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("UTF-8", resp.data["error"])

    def test_preview_of_an_unreadable_file_is_rejected_with_400(self):
        upload = SimpleUploadedFile(
            "legacy.xls", b"\xd0\xcf\x11\xe0\x00\x00\x00\x00", content_type="application/vnd.ms-excel"
        )

        resp = self.client.post(
            "/api/v1/metering/import/preview-csv/", {"file": upload}, format="multipart"
        )

        self.assertEqual(resp.status_code, 400)

    # ── I. Ragged rows (previously a 500, or silent column misalignment) ──────

    def test_row_with_extra_trailing_field_is_imported_without_misalignment(self):
        """A trailing-comma export used to make pandas promote meter_id to the
        index and shift every column left, then crash on the row numbering."""
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-09-04T00:00:00Z,1.5000,EXTRA\n"
        )

        resp = upload_csv(self.client, "extrafield.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.energy_kwh, Decimal("1.5000"))
        self.assertEqual(reading.timestamp, datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc))

    def test_rows_of_differing_widths_are_handled_row_by_row(self):
        csv_bytes = (
            b"meter_id,timestamp,energy_kwh\n"
            b"CH-IMPORT-1,2026-09-05T00:00:00Z,1.0000\n"
            b"CH-IMPORT-1,2026-09-06T00:00:00Z,2.0000,EXTRA\n"
            b"CH-IMPORT-1,2026-09-07T00:00:00Z\n"
        )

        resp = upload_csv(self.client, "ragged.csv", csv_bytes)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 2)
        self.assertEqual(resp.data["rows_skipped"], 1)
        self.assertTrue(any("Missing numeric value" in err["error"] for err in resp.data["errors"]))
