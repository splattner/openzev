"""SDAT-CH metering import tests (spec-compliant E66 ValidatedMeteredData)."""

import gzip
import os
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone as django_timezone
from lxml import etree
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers import csv_importer, sdatch_importer
from metering.models import ImportLog, ImportSource, MeterReading, QuarantinedReading, ReadingDirection
from testing.helpers import authenticate as auth, make_user, create_managed_zev
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant

FIXTURES = os.path.join(os.path.dirname(__file__), "test_fixtures", "sdatch")

CONS_ID = "CH9999901234500000000000000000001"
PROD_ID = "CH9999901234500000000000000000002"
ALT_ID = "CH9999901234500000000000000000009"

TS0 = datetime(2025, 6, 2, 22, 0, tzinfo=timezone.utc)
TS1 = datetime(2025, 6, 2, 22, 15, tzinfo=timezone.utc)
TS2 = datetime(2025, 6, 2, 22, 30, tzinfo=timezone.utc)
TS3 = datetime(2025, 6, 2, 22, 45, tzinfo=timezone.utc)


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


class SdatchImportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdatch_owner", UserRole.USER)
        self.other_owner = make_user("sdatch_other_owner", UserRole.USER)
        self.admin = make_user("sdatch_admin", UserRole.ADMIN)

        self.zev = create_managed_zev(name="SDAT ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S")
        auth(self.client, self.owner)
        self.other_zev = create_managed_zev(name="Other SDAT ZEV", owner=self.other_owner, zev_type="vzev", invoice_prefix="O")
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="SDAT",
            last_name="Participant",
            email="sdatch.participant@example.com",
            valid_from=datetime(2026, 1, 1).date(),
        )
        self.cons_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id=CONS_ID,
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.prod_mp = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id=PROD_ID,
            meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.cons_mp,
            participant=self.participant,
            valid_from=datetime(2026, 1, 1).date(),
        )

    def _upload(self, name, content, *, zev=None):
        upload = SimpleUploadedFile(name, content, content_type="application/xml")
        return self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str((zev or self.zev).id)},
            format="multipart",
        )

    def test_sdatch_without_zev_id_is_rejected(self):
        upload = SimpleUploadedFile("no-zev.xml", fixture("e66_basic.xml"), content_type="application/xml")

        resp = self.client.post("/api/v1/metering/import/sdatch/", {"file": upload}, format="multipart")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("zev_id", resp.data["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_sdatch_with_invalid_zev_id_is_rejected(self):
        upload = SimpleUploadedFile("bad-zev.xml", fixture("e66_basic.xml"), content_type="application/xml")

        resp = self.client.post(
            "/api/v1/metering/import/sdatch/", {"file": upload, "zev_id": "not-a-uuid"}, format="multipart"
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("valid UUID", resp.data["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_sdatch_with_unknown_zev_id_returns_404(self):
        upload = SimpleUploadedFile("unknown-zev.xml", fixture("e66_basic.xml"), content_type="application/xml")

        resp = self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": "00000000-0000-0000-0000-000000000000"},
            format="multipart",
        )

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_malformed_sdatch_payload_is_reported_without_crash(self):
        resp = self._upload("broken.xml", b"<MeteringData><broken></MeteringData")

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(resp.data["errors"])
        self.assertIn("Malformed SDAT-CH XML", resp.data["errors"][0]["error"])
        issue = resp.data["issues"][0]
        self.assertEqual(issue["xml_line"], 1)
        self.assertGreater(issue["xml_column"], 0)
        self.assertTrue(issue["xml_error_type"].startswith("ERR_"))
        self.assertEqual(ImportLog.objects.get(pk=resp.data["id"]).issues, resp.data["issues"])

    def test_e66_basic_imports_billable_and_quarantines_temporary(self):
        resp = self._upload("basic.xml", fixture("e66_basic.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 8)
        self.assertEqual(resp.data["rows_imported"], 6)
        self.assertEqual(resp.data["rows_skipped"], 0)

        readings = list(MeterReading.objects.order_by("metering_point__meter_id", "timestamp"))
        self.assertEqual(len(readings), 6)
        # seq1 (Condition 21, temporary) is quarantined, not billed.
        self.assertEqual(
            [r.timestamp for r in readings if r.metering_point == self.cons_mp], [TS1, TS2, TS3]
        )
        self.assertEqual(
            [r.energy_kwh for r in readings if r.metering_point == self.cons_mp],
            [Decimal("101.0000"), Decimal("102.1020"), Decimal("103.0000")],
        )
        self.assertTrue(all(r.direction == ReadingDirection.IN for r in readings if r.metering_point == self.cons_mp))
        self.assertTrue(all(r.direction == ReadingDirection.OUT for r in readings if r.metering_point == self.prod_mp))
        self.assertTrue(all(r.import_source == ImportSource.SDATCH for r in readings))
        self.assertTrue(all(r.source_creation is not None for r in readings))

        quarantined = list(QuarantinedReading.objects.order_by("timestamp"))
        self.assertEqual(len(quarantined), 2)
        self.assertTrue(all(q.timestamp == TS0 for q in quarantined))
        self.assertTrue(all(q.condition == "21" for q in quarantined))

        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.zev, self.zev)
        self.assertEqual(log.imported_by, self.owner)
        self.assertEqual(log.timestamp_timezone, "Europe/Zurich")
        self.assertTrue(any("Quarantined 2" in w["warning"] for w in log.warnings))

    def test_e66_repeat_import_skips_duplicates(self):
        first = self._upload("first.xml", fixture("e66_basic.xml"))
        self.assertEqual(first.data["rows_imported"], 6)

        second = self._upload("second.xml", fixture("e66_basic.xml"))

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data["rows_total"], 8)
        self.assertEqual(second.data["rows_imported"], 0)
        self.assertEqual(second.data["rows_skipped"], 8)
        self.assertEqual(MeterReading.objects.count(), 6)
        self.assertEqual(QuarantinedReading.objects.count(), 2)

    def test_e66_replace_overwrites_and_promotes_quarantine(self):
        self._upload("basic.xml", fixture("e66_basic.xml"))

        resp = self._upload("replace.xml", fixture("e66_replace.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 2)  # seq1 slots are new billable rows
        self.assertEqual(resp.data["rows_overwritten"], 6)
        self.assertEqual(
            [r.energy_kwh for r in MeterReading.objects.filter(metering_point=self.cons_mp).order_by("timestamp")],
            [Decimal("110.0000"), Decimal("111.0000"), Decimal("112.1120"), Decimal("113.0000")],
        )
        # The quarantined seq1 observations were promoted into billing.
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        self.assertTrue(any("promoted 2" in w["warning"] for w in ImportLog.objects.get(id=resp.data["id"]).warnings))

    def test_e66_stale_replace_is_skipped(self):
        self._upload("basic.xml", fixture("e66_basic.xml"))

        resp = self._upload("stale.xml", fixture("e66_stale_replace.xml"))

        self.assertEqual(resp.status_code, 201)
        # Newer held data must not block validated billing. The stale Status=5
        # delivery is older than every stored row: its three measured slots
        # are stale skips — but seq1 has no billable row yet (basic delivered
        # it as temporary), so the stale validated value still lands in
        # billing while the newer held row stays visible.
        self.assertEqual(resp.data["rows_imported"], 1)
        self.assertEqual(resp.data["rows_overwritten"], 0)
        self.assertEqual(resp.data["rows_skipped"], 3)
        self.assertEqual(resp.data["result_counts"]["stale"], 3)
        self.assertEqual(
            MeterReading.objects.get(metering_point=self.cons_mp, timestamp=TS0).energy_kwh,
            Decimal("110.0000"),
        )
        # The slot basic delivered as Status=9 measured keeps its value.
        self.assertEqual(
            MeterReading.objects.get(metering_point=self.cons_mp, timestamp=TS1).energy_kwh,
            Decimal("101.0000"),
        )
        self.assertEqual(QuarantinedReading.objects.count(), 2)

    def test_e66_replace_rejects_whole_file_on_csv_overlap(self):
        MeterReading.objects.create(
            metering_point=self.cons_mp,
            timestamp=TS1,
            direction=ReadingDirection.IN,
            energy_kwh=Decimal("9.0000"),
            import_source=ImportSource.CSV,
        )

        resp = self._upload("basic.xml", fixture("e66_basic.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "rejected")
        self.assertEqual(resp.data["rows_total"], 8)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_overwritten"], 0)
        self.assertTrue(
            any("CSV/manual" in error["error"] for error in resp.data["errors"]),
            resp.data["errors"],
        )
        self.assertEqual(
            [issue["code"] for issue in resp.data["issues"]].count("source_conflict"), 1
        )
        row = MeterReading.objects.get(metering_point=self.cons_mp, timestamp=TS1)
        self.assertEqual(row.energy_kwh, Decimal("9.0000"))
        self.assertEqual(row.import_source, ImportSource.CSV)
        self.assertEqual(MeterReading.objects.count(), 1)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertTrue(log.errors)

    def test_c38_info_file_is_fully_quarantined(self):
        resp = self._upload("info.xml", fixture("e66_c38_info.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 4)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 4)
        self.assertTrue(all(q.business_reason == "C38" for q in QuarantinedReading.objects.all()))

    def test_aggregated_metered_data_is_rejected_loudly(self):
        resp = self._upload("agg.xml", fixture("e31_aggregated.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 0)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertIn("AggregatedMeteredData", resp.data["errors"][0]["error"])
        self.assertEqual(resp.data["issues"][0]["detail_code"], "aggregated_data")
        self.assertTrue(resp.data["issues"][0]["root_element"].startswith("AggregatedMeteredData_"))
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_reactive_and_leg_products_are_skipped_with_notes(self):
        resp = self._upload("products.xml", fixture("e66_products.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_total"], 4)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_skipped"], 4)
        self.assertEqual(MeterReading.objects.count(), 0)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertTrue(any("reactive" in w["warning"] for w in log.warnings))
        self.assertTrue(any("LEG" in w["warning"] for w in log.warnings))

    def test_block_without_resolution_is_rejected(self):
        resp = self._upload("nores.xml", fixture("e66_no_resolution.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertIn("Resolution", resp.data["errors"][0]["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_schema_invalid_file_is_rejected(self):
        resp = self._upload("badcond.xml", fixture("e66_bad_condition.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertIn("Schema validation failed", resp.data["errors"][0]["error"])
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_exchange_metering_point_is_skipped(self):
        resp = self._upload("exchange.xml", fixture("e66_exchange.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertTrue(any("Exchange" in w["warning"] for w in log.warnings))

    def test_cancellation_is_rejected(self):
        seed = self._upload("basic.xml", fixture("e66_basic.xml"))
        self.assertEqual(seed.status_code, 201)
        self.assertEqual(seed.data["result_status"], "accepted")
        readings = list(MeterReading.objects.order_by("id").values())
        held = list(QuarantinedReading.objects.order_by("id").values())
        self.assertEqual(len(readings), 6)
        self.assertEqual(len(held), 2)

        # Cancellation rejection takes precedence over freshness and delivery scope.
        for creation in ("2025-06-04T15:40:05Z", "2025-06-05T15:40:05Z", "2025-06-06T15:40:05Z"):
            for has_metering_data in (True, False):
                with self.subTest(creation=creation, has_metering_data=has_metering_data):
                    root = etree.fromstring(fixture("e66_cancellation.xml"))
                    root.find(".//{http://www.strom.ch}Creation").text = creation
                    if not has_metering_data:
                        for block in root.findall("{http://www.strom.ch}MeteringData"):
                            root.remove(block)
                    resp = self._upload("cancel.xml", etree.tostring(root))

                    self.assertEqual(resp.status_code, 201)
                    log = ImportLog.objects.get(id=resp.data["id"])
                    self.assertEqual(log.result_status, "rejected")
                    self.assertEqual([issue["code"] for issue in log.issues], ["cancellation_rejected"])
                    self.assertEqual(log.rows_imported, 0)
                    self.assertEqual(log.rows_overwritten, 0)
                    self.assertEqual(log.reading_changes, [])
                    self.assertIn("cancellation", log.errors[0]["error"].lower())
                    self.assertEqual(list(MeterReading.objects.order_by("id").values()), readings)
                    self.assertEqual(list(QuarantinedReading.objects.order_by("id").values()), held)

        # This replacement predates the newest rejected cancellation, but follows the seed.
        replacement = self._upload("replace.xml", fixture("e66_replace.xml"))
        self.assertEqual(replacement.data["result_status"], "accepted")
        self.assertEqual(replacement.data["rows_imported"], 2)
        self.assertEqual(replacement.data["rows_overwritten"], 6)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        self.assertEqual(
            MeterReading.objects.get(metering_point=self.cons_mp, timestamp=TS1).energy_kwh,
            Decimal("111.0000"),
        )

    def test_secondary_meter_id_matches_alias(self):
        self.cons_mp.secondary_meter_id = ALT_ID
        self.cons_mp.save(update_fields=["secondary_meter_id"])

        resp = self._upload("alias.xml", fixture("e66_alias.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 3)
        readings = list(
            MeterReading.objects.filter(metering_point=self.cons_mp).order_by("timestamp")
        )
        self.assertEqual(
            [(r.timestamp, r.energy_kwh) for r in readings],
            [(TS1, Decimal("101.0000")), (TS2, Decimal("102.0000")), (TS3, Decimal("103.0000"))],
        )
        held = QuarantinedReading.objects.get(metering_point=self.cons_mp, timestamp=TS0)
        self.assertEqual(held.energy_kwh, Decimal("100.0000"))

    def test_unknown_meter_id_rejects_whole_file(self):
        resp = self._upload("alias.xml", fixture("e66_alias.xml"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "rejected")
        self.assertEqual(resp.data["rows_total"], 4)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertTrue(any(error.get("meter_id") == ALT_ID for error in resp.data["errors"]))
        self.assertTrue(any(issue["code"] == "unknown_meter" for issue in resp.data["issues"]))
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_gzipped_upload_is_decompressed(self):
        resp = self._upload("basic.xml.gz", gzip.compress(fixture("e66_basic.xml")))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 6)
        self.assertEqual(MeterReading.objects.count(), 6)

    def test_owner_cannot_import_sdatch_for_other_owners_zev(self):
        resp = self._upload("forbidden.xml", fixture("e66_basic.xml"), zev=self.other_zev)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_admin_import_resolves_meters_in_target_zev(self):
        other_cons = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH9999901234500000000000000000010",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        other_prod = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH9999901234500000000000000000020",
            meter_type=MeteringPointType.PRODUCTION,
        )
        auth(self.client, self.admin)
        content = fixture("e66_basic.xml").replace(
            CONS_ID.encode(), b"CH9999901234500000000000000000010"
        ).replace(
            PROD_ID.encode(), b"CH9999901234500000000000000000020"
        )

        resp = self._upload("admin.xml", content, zev=self.other_zev)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_imported"], 6)
        self.assertTrue(MeterReading.objects.filter(metering_point=other_cons).exists())
        self.assertTrue(MeterReading.objects.filter(metering_point=other_prod).exists())
        self.assertFalse(MeterReading.objects.filter(metering_point=self.cons_mp).exists())

    def test_admin_import_rejects_file_with_foreign_meter(self):
        auth(self.client, self.admin)
        resp = self._upload("admin.xml", fixture("e66_basic.xml"), zev=self.other_zev)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "rejected")
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_owner_cannot_import_sdatch_into_disabled_zev(self):
        self.zev.disabled_at = django_timezone.now()
        self.zev.save(update_fields=["disabled_at"])

        resp = self._upload("disabled-zev.xml", fixture("e66_basic.xml"))

        self.assertEqual(resp.status_code, 400)
        self.assertIn("This ZEV is disabled", resp.data["error"])
        self.assertFalse(MeterReading.objects.exists())
        self.assertFalse(ImportLog.objects.exists())

    def test_admin_can_import_sdatch_into_disabled_zev(self):
        other_cons = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH9999901234500000000000000000011",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        other_prod = MeteringPoint.objects.create(
            zev=self.other_zev,
            meter_id="CH9999901234500000000000000000021",
            meter_type=MeteringPointType.PRODUCTION,
        )
        self.other_zev.disabled_at = django_timezone.now()
        self.other_zev.save(update_fields=["disabled_at"])
        auth(self.client, self.admin)
        content = fixture("e66_basic.xml").replace(
            CONS_ID.encode(), b"CH9999901234500000000000000000011"
        ).replace(
            PROD_ID.encode(), b"CH9999901234500000000000000000021"
        )

        resp = self._upload("admin-disabled-zev.xml", content, zev=self.other_zev)

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(MeterReading.objects.filter(metering_point=other_cons).exists())
        self.assertTrue(MeterReading.objects.filter(metering_point=other_prod).exists())


class SdatchLimitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdatch_limit_owner", UserRole.USER)
        self.zev = create_managed_zev(name="SDAT Limit ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="Y")
        auth(self.client, self.owner)

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
        self.assertEqual(resp.data["issues"][0]["size_bytes"], len(xml))
        self.assertEqual(resp.data["issues"][0]["limit_bytes"], 10)
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_row_error_list_is_capped_with_a_truncation_note(self):
        root = etree.fromstring(fixture("e66_basic.xml"))
        ns = "http://www.strom.ch"
        block = root.find(f"{{{ns}}}MeteringData")
        for md in list(root.iter(f"{{{ns}}}MeteringData")):
            root.remove(md)
        for i in range(60):
            clone = deepcopy(block)
            clone.find(f"{{{ns}}}DocumentID").text = f"FIX-CAP-{i:03d}"
            point = clone.find(f"{{{ns}}}ConsumptionMeteringPoint")
            point.find(f"{{{ns}}}VSENationalID").text = f"CH99999012345{i:020d}"
            root.append(clone)
        xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

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
