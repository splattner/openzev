"""SDAT-CH metering import tests."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers import csv_importer, sdatch_importer
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev


class SdatchImportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdatch_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("sdatch_other_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("sdatch_admin", UserRole.ADMIN)
        auth(self.client, self.owner)

        self.zev = Zev.objects.create(name="SDAT ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
        self.other_zev = Zev.objects.create(name="Other SDAT ZEV", owner=self.other_owner, zev_type="vzev", invoice_prefix="O")
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="SDAT",
            last_name="Participant",
            email="sdatch.participant@example.com",
            valid_from=date(2026, 1, 1),
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-SDAT-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.metering_point,
            participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

    def _upload(self, name, content, *, zev=None):
        upload = SimpleUploadedFile(name, content, content_type="application/xml")
        return self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str((zev or self.zev).id)},
            format="multipart",
        )

    def _xml(self, body):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<MeteringData>
  {body}
</MeteringData>
""".encode()

    def _meter_xml(self, meter_id, intervals):
        return f"""
<MeteringPoint>
  <MeteringPointID>{meter_id}</MeteringPointID>
  {intervals}
</MeteringPoint>
"""

    def _interval_xml(self, *, start="2026-01-01T00:00:00Z", resolution="PT15M", observations=""):
        return f"""
<Interval>
  <Start>{start}</Start>
  <Resolution>{resolution}</Resolution>
  {observations}
</Interval>
"""

    def _observation_xml(self, quantity="1.0000", direction=None, *, tag="Volume"):
        direction_xml = f"<Direction>{direction}</Direction>" if direction is not None else ""
        return f"""
<Observation>
  <{tag}>{quantity}</{tag}>
  {direction_xml}
</Observation>
"""

    def test_malformed_sdatch_payload_is_reported_without_crash(self):
        resp = self._upload("broken.xml", b"<MeteringData><broken></MeteringData")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(resp.data["errors"])
        self.assertIn("Malformed SDAT-CH XML", resp.data["errors"][0]["error"])

    def test_valid_sdatch_import_creates_readings_and_log(self):
        observations = self._observation_xml("1.2500") + self._observation_xml("2.5000")
        xml = self._xml(self._meter_xml("CH-SDAT-1", self._interval_xml(observations=observations)))

        resp = self._upload("valid.xml", xml)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 2)
        self.assertEqual(resp.data["rows_imported"], 2)
        self.assertEqual(resp.data["rows_skipped"], 0)
        readings = list(MeterReading.objects.filter(metering_point=self.metering_point).order_by("timestamp"))
        self.assertEqual([reading.timestamp for reading in readings], [
            datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc),
        ])
        self.assertEqual([reading.energy_kwh for reading in readings], [Decimal("1.2500"), Decimal("2.5000")])
        self.assertEqual([reading.import_source for reading in readings], [ImportSource.SDATCH, ImportSource.SDATCH])

        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.zev)
        self.assertEqual(log.imported_by, self.owner)

    def test_unknown_meter_id_is_reported_and_skipped(self):
        observations = self._observation_xml("1.0000")
        xml = self._xml(self._meter_xml("CH-UNKNOWN", self._interval_xml(observations=observations)))

        resp = self._upload("unknown.xml", xml)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 0)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any(error.get("meter_id") == "CH-UNKNOWN" for error in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_repeated_import_skips_duplicate_observations(self):
        observations = self._observation_xml("3.0000")
        xml = self._xml(self._meter_xml("CH-SDAT-1", self._interval_xml(observations=observations)))

        first_resp = self._upload("first.xml", xml)
        self.assertEqual(first_resp.status_code, 201)
        self.assertEqual(first_resp.data["rows_imported"], 1)

        second_resp = self._upload("second.xml", xml)

        self.assertEqual(second_resp.status_code, 201)
        self.assertEqual(second_resp.data["rows_total"], 1)
        self.assertEqual(second_resp.data["rows_imported"], 0)
        self.assertEqual(second_resp.data["rows_skipped"], 1)
        self.assertEqual(MeterReading.objects.filter(metering_point=self.metering_point).count(), 1)

    def test_invalid_timestamp_is_reported_without_creating_readings(self):
        observations = self._observation_xml("1.0000")
        xml = self._xml(self._meter_xml("CH-SDAT-1", self._interval_xml(start="not-a-date", observations=observations)))

        resp = self._upload("invalid-ts.xml", xml)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any("Invalid timestamp" in error["error"] for error in resp.data["errors"]))
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_out_direction_and_quantity_alias_are_imported(self):
        observations = self._observation_xml("4.2500", "OUT", tag="Quantity")
        xml = self._xml(self._meter_xml("CH-SDAT-1", self._interval_xml(observations=observations)))

        resp = self._upload("out.xml", xml)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        reading = MeterReading.objects.get(metering_point=self.metering_point)
        self.assertEqual(reading.direction, ReadingDirection.OUT)
        self.assertEqual(reading.energy_kwh, Decimal("4.2500"))

    def test_30_and_60_minute_resolutions_offset_observations(self):
        observations_30 = self._observation_xml("1.0000") + self._observation_xml("2.0000")
        observations_60 = self._observation_xml("3.0000") + self._observation_xml("4.0000")
        intervals = (
            self._interval_xml(start="2026-01-02T00:00:00Z", resolution="PT30M", observations=observations_30)
            + self._interval_xml(start="2026-01-03T00:00:00Z", resolution="PT1H", observations=observations_60)
        )
        xml = self._xml(self._meter_xml("CH-SDAT-1", intervals))

        resp = self._upload("resolutions.xml", xml)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 4)
        readings = list(MeterReading.objects.filter(metering_point=self.metering_point).order_by("timestamp"))
        self.assertEqual([reading.timestamp for reading in readings], [
            datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 3, 1, 0, tzinfo=timezone.utc),
        ])

    def test_owner_cannot_import_sdatch_for_other_owners_zev(self):
        xml = self._xml(self._meter_xml("CH-SDAT-1", self._interval_xml(observations=self._observation_xml("1.0000"))))

        resp = self._upload("forbidden.xml", xml, zev=self.other_zev)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_admin_can_import_sdatch_for_any_zev(self):
        admin_meter = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH-ADMIN-SDAT",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        auth(self.client, self.admin)
        xml = self._xml(self._meter_xml("CH-ADMIN-SDAT", self._interval_xml(observations=self._observation_xml("1.0000"))))

        resp = self._upload("admin.xml", xml, zev=self.other_zev)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertTrue(MeterReading.objects.filter(metering_point=admin_meter).exists())


class SdatchLimitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdatch_limit_owner", UserRole.ZEV_OWNER)
        auth(self.client, self.owner)
        self.zev = Zev.objects.create(name="SDAT Limit ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="Y")

    def test_file_over_size_cap_is_reported_without_parsing(self):
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?><MeteringData>'
            b'<MeteringPoint><ID>CH-SDAT-1</ID></MeteringPoint></MeteringData>'
        )

        with mock.patch.object(sdatch_importer, "MAX_SDAT_BYTES", 10):
            upload = SimpleUploadedFile("big.xml", xml, content_type="application/xml")
            resp = self.client.post(
                "/api/v1/metering/import/sdatch/",
                {"file": upload, "zev_id": str(self.zev.id)},
                format="multipart",
            )

        self.assertEqual(resp.status_code, 201)
        self.assertIn("too large", resp.data["errors"][0]["error"].lower())
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_row_error_list_is_capped_with_a_truncation_note(self):
        meters = "".join(
            f"<MeteringPoint><ID>NOPE-{i}</ID></MeteringPoint>" for i in range(60)
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><MeteringData>{meters}</MeteringData>'.encode()

        upload = SimpleUploadedFile("errs.xml", xml, content_type="application/xml")
        resp = self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str(self.zev.id)},
            format="multipart",
        )

        self.assertEqual(resp.status_code, 201)
        errors = resp.data["errors"]
        self.assertEqual(len(errors), csv_importer.MAX_REPORTED_ERRORS + 1)
        self.assertIn("Too many errors", errors[-1]["error"])
