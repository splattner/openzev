"""Format 7: a ZEV's supplementary energy data in the transfer archive (SPEC-2026-supplementary-energy-data §10).

The section is opt-in, carries no secret and no live state, and brings sources back disconnected.
"""

import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice
from metering.models import ImportLog, MeterReading, SupplementaryReading, SupplementarySource, SupplementaryStatus
from metering.supplementary.testing import INTEGRATION_KEY
from testing.helpers import authenticate as auth, make_user
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev
from zev.test_transfer import (
    ZEV_URL,
    build_populated_zev,
    export_and_clear,
    export_to_bytes,
    rewrite_archive,
)
from zev.transfer import ImportFailed, import_archive
from zev.transfer.export import _supplementary_csv_name
from zev.transfer.schema import (
    FORMAT_VERSION,
    OPT_IN_SECTIONS,
    SECTION_DEPENDENCIES,
    SECTION_SUPPLEMENTARY,
    SECTIONS,
    check_dependencies,
)

ALL = [name for name in SECTIONS]
SOURCES_FILE = "supplementary_sources.json"
START = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
SECRET_KEY = "refresh-token-very-secret"


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[INTEGRATION_KEY])
class SupplementaryArchiveTestCase(TestCase):
    def setUp(self):
        self.owner = make_user("sx_owner", UserRole.USER)
        self.importer = make_user("sx_importer", UserRole.ADMIN)
        self.zev = build_populated_zev(self.owner, meter_prefix="SX")
        self.alice = Participant.objects.get(zev=self.zev, party__first_name="Alice")
        self.bob = Participant.objects.get(zev=self.zev, party__first_name="Bob")
        self.solar_point = self.flagged_point("SX-NET-1", self.alice)
        self.push_point = self.flagged_point("SX-NET-2", self.bob)

        self.solar = SupplementarySource(
            metering_point=self.solar_point, participant=self.alice, provider="solar_manager",
            external_id="ABC123", label="Dach Süd", status=SupplementaryStatus.OK,
            covers_from=START, synced_through=START + timedelta(hours=1),
            last_sync_at=START, last_success_at=START, last_error="old problem",
            reconciliation={"state": "warn"},
        )
        self.solar.set_credential(SECRET_KEY)
        self.solar.save()
        self.push = SupplementarySource(
            metering_point=self.push_point, participant=self.bob, provider="push", label="Home Assistant",
            covers_from=START, synced_through=START + timedelta(minutes=30),
        )
        self.push_token = self.push.issue_push_token()
        self.push.save()
        for source in (self.solar, self.push):
            for i in range(4 if source is self.solar else 2):
                SupplementaryReading.objects.create(
                    source=source, metering_point=source.metering_point,
                    timestamp=START + timedelta(minutes=15 * i),
                    consumption_kwh=Decimal("0.4000") + i, production_kwh=Decimal("1.2000"),
                    import_kwh=Decimal("0.1000"), export_kwh=Decimal("0.9000"),
                )

    def flagged_point(self, meter_id, participant):
        point = MeteringPoint.objects.create(
            zev=self.zev, meter_id=meter_id, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        MeteringPointAssignment.objects.create(metering_point=point, participant=participant, valid_from=date(2026, 1, 1))
        return point

    def export(self, sections):
        return export_to_bytes(self.zev, sections)

    def full(self):
        return self.export(ALL)

    def import_(self, raw, **kwargs):
        return import_archive(io.BytesIO(raw), owner=self.importer, **kwargs)

    def members(self, raw):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def roundtrip(self, sections=ALL):
        raw = export_and_clear(self.zev, sections)
        return self.import_(raw), raw


class OptInTests(SupplementaryArchiveTestCase):
    def test_the_section_is_known_and_opt_in(self):
        self.assertIn(SECTION_SUPPLEMENTARY, SECTIONS)
        self.assertEqual(OPT_IN_SECTIONS, (SECTION_SUPPLEMENTARY,))

    def test_it_needs_metering_points_and_participants(self):
        self.assertEqual(set(SECTION_DEPENDENCIES[SECTION_SUPPLEMENTARY]), {"metering_points", "participants"})
        with self.assertRaisesRegex(ValueError, "supplementary_data requires"):
            check_dependencies(["zev", SECTION_SUPPLEMENTARY])
        with self.assertRaises(ValueError):
            self.export(["readings", SECTION_SUPPLEMENTARY])

    def test_a_default_export_leaves_it_out(self):
        members = self.members(self.export(None))

        self.assertNotIn(SOURCES_FILE, members)
        self.assertFalse([name for name in members if name.startswith("supplementary_readings/")])
        manifest = json.loads(members["manifest.json"])
        self.assertNotIn(SECTION_SUPPLEMENTARY, manifest["sections"])
        self.assertNotIn("supplementary_readings", manifest["counts"])

    def test_an_explicit_request_includes_it(self):
        members = self.members(self.full())

        self.assertIn(SOURCES_FILE, members)
        manifest = json.loads(members["manifest.json"])
        self.assertEqual(manifest["format_version"], FORMAT_VERSION)
        self.assertIn(SECTION_SUPPLEMENTARY, manifest["sections"])
        self.assertEqual(manifest["counts"][SECTION_SUPPLEMENTARY], 2)
        self.assertEqual(manifest["counts"]["supplementary_readings"], 6)

    def test_the_endpoint_follows_the_same_rule(self):
        client = APIClient()
        auth(client, self.owner)
        default = client.get(f"{ZEV_URL}/{self.zev.id}/export/")
        chosen = client.get(
            f"{ZEV_URL}/{self.zev.id}/export/",
            {"sections": "zev,participants,metering_points,supplementary_data"},
        )

        self.assertEqual(default.status_code, 200)
        self.assertNotIn(SOURCES_FILE, zipfile.ZipFile(io.BytesIO(b"".join(default.streaming_content))).namelist())
        self.assertEqual(chosen.status_code, 200)
        self.assertIn(SOURCES_FILE, zipfile.ZipFile(io.BytesIO(b"".join(chosen.streaming_content))).namelist())

    def test_the_section_list_endpoint_offers_it_with_its_prerequisites(self):
        client = APIClient()
        auth(client, self.owner)
        sections = {item["name"]: item["requires"] for item in client.get(f"{ZEV_URL}/transfer-sections/").json()["sections"]}

        self.assertEqual(set(sections[SECTION_SUPPLEMENTARY]), {"metering_points", "participants"})

    def test_exporting_does_not_depend_on_the_feature_flag(self):
        # The data is kept while the feature is off; an export of the community carries it when asked.
        self.assertIn(SOURCES_FILE, self.members(self.full()))


class SecretsNeverTravelTests(SupplementaryArchiveTestCase):
    def test_no_member_contains_a_credential_token_or_hash(self):
        needles = [
            SECRET_KEY.encode(),
            bytes(self.solar.credential_encrypted),
            self.push_token.encode(),
            self.push.push_token_prefix.encode(),
            self.push.push_token_hash.encode(),
            b"credential",
            b"push_token",
            b"last_error",
            b"old problem",
            b"reconciliation",
        ]
        for name, payload in self.members(self.full()).items():
            for needle in needles:
                self.assertNotIn(needle, payload, f"{needle!r} found in {name}")

    def test_a_source_entry_has_exactly_the_documented_keys(self):
        entries = json.loads(self.members(self.full())[SOURCES_FILE])

        self.assertEqual(len(entries), 2)
        for entry in entries:
            self.assertEqual(
                set(entry),
                {"id", "meter_id", "participant_id", "provider", "label", "external_id", "consented_at", "covers_from", "synced_through"},
            )

    def test_no_account_reference_travels(self):
        raw = self.full().decode("latin-1")
        self.assertNotIn("created_by", raw)


class RoundTripTests(SupplementaryArchiveTestCase):
    def imported(self):
        result, _ = self.roundtrip()
        return Zev.objects.get(pk=result["zev_id"]), result

    def test_sources_and_readings_come_back(self):
        zev, result = self.imported()

        self.assertEqual(result["counts"][SECTION_SUPPLEMENTARY], 2)
        self.assertEqual(result["counts"]["supplementary_readings"], 6)
        self.assertEqual(SupplementarySource.objects.filter(metering_point__zev=zev).count(), 2)
        self.assertEqual(SupplementaryReading.objects.filter(metering_point__zev=zev).count(), 6)

    def test_a_source_arrives_disconnected_and_without_any_secret(self):
        zev, _ = self.imported()
        solar = SupplementarySource.objects.get(metering_point__zev=zev, provider="solar_manager")
        push = SupplementarySource.objects.get(metering_point__zev=zev, provider="push")

        for source in (solar, push):
            self.assertFalse(source.enabled)
            self.assertEqual(source.status, SupplementaryStatus.DISABLED)
            self.assertFalse(source.has_credential)
            self.assertIsNone(source.push_token_prefix)
            self.assertEqual(source.push_token_hash, "")
            self.assertEqual(source.last_error, "")
            self.assertIsNone(source.last_sync_at)
            self.assertIsNone(source.last_success_at)
            self.assertEqual(source.reconciliation, {})
            self.assertIsNone(source.created_by)

    def test_what_describes_the_data_is_kept(self):
        zev, _ = self.imported()
        solar = SupplementarySource.objects.get(metering_point__zev=zev, provider="solar_manager")

        self.assertEqual((solar.external_id, solar.label), ("ABC123", "Dach Süd"))
        self.assertEqual(solar.covers_from, START)
        self.assertEqual(solar.synced_through, START + timedelta(hours=1))
        # The archive's JSON keeps milliseconds.
        self.assertLess(abs(solar.consented_at - self.solar.consented_at), timedelta(milliseconds=1))

    def test_the_import_says_the_sources_arrived_disconnected(self):
        _, result = self.imported()

        self.assertTrue(any("imported disconnected" in warning for warning in result["warnings"]))

    def test_sources_point_at_the_imported_participants_and_meters(self):
        zev, _ = self.imported()
        solar = SupplementarySource.objects.get(metering_point__zev=zev, provider="solar_manager")

        self.assertEqual(solar.metering_point.meter_id, "SX-NET-1")
        self.assertEqual(solar.participant.first_name, "Alice")
        self.assertEqual(solar.participant.zev_id, zev.id)
        self.assertEqual(solar.metering_point.zev_id, zev.id)

    def test_readings_are_identical(self):
        zev, _ = self.imported()
        solar = SupplementarySource.objects.get(metering_point__zev=zev, provider="solar_manager")

        rows = list(solar.readings.order_by("timestamp").values_list(
            "timestamp", "consumption_kwh", "production_kwh", "import_kwh", "export_kwh"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], (START, Decimal("0.4000"), Decimal("1.2000"), Decimal("0.1000"), Decimal("0.9000")))
        self.assertEqual(rows[3][1], Decimal("3.4000"))

    def test_the_official_meter_data_is_untouched_and_no_import_log_is_written_for_it(self):
        zev, _ = self.imported()

        # Only the two metering readings of the populated ZEV travelled (the readings section).
        self.assertEqual(MeterReading.objects.filter(metering_point__zev=zev).count(), 3)
        self.assertEqual(ImportLog.objects.filter(zev=zev).count(), 1)

    def test_the_source_can_be_reconnected_after_the_import(self):
        zev, _ = self.imported()
        push = SupplementarySource.objects.get(metering_point__zev=zev, provider="push")

        token = push.issue_push_token()
        push.enabled = True
        push.save()

        self.assertTrue(token.startswith("ozs_"))
        self.assertEqual(push.status, SupplementaryStatus.PENDING)

    def test_a_second_export_of_the_import_matches_the_first(self):
        zev, _ = self.imported()
        again = self.members(export_to_bytes(zev, ALL))

        first = json.loads(again[SOURCES_FILE])
        self.assertEqual({entry["meter_id"] for entry in first}, {"SX-NET-1", "SX-NET-2"})
        manifest = json.loads(again["manifest.json"])
        self.assertEqual(manifest["counts"]["supplementary_readings"], 6)

    def test_leaving_the_section_out_at_import_imports_none(self):
        raw = export_and_clear(self.zev, ALL)

        result = self.import_(raw, sections=[name for name in ALL if name != SECTION_SUPPLEMENTARY])

        self.assertNotIn(SECTION_SUPPLEMENTARY, result["counts"])
        self.assertEqual(SupplementarySource.objects.count(), 0)
        self.assertEqual(SupplementaryReading.objects.count(), 0)

    def test_importing_without_naming_sections_takes_what_the_archive_has(self):
        raw = export_and_clear(self.zev, ALL)

        result = self.import_(raw)

        self.assertIn(SECTION_SUPPLEMENTARY, result["sections"])

    def test_a_source_without_readings_travels_as_an_empty_file(self):
        SupplementaryReading.objects.filter(source=self.push).delete()
        members = self.members(self.full())

        self.assertEqual(members[_supplementary_csv_name("SX-NET-2")].decode().strip().count("\n"), 0)
        result, _ = self.roundtrip()
        self.assertEqual(result["counts"]["supplementary_readings"], 4)

    def test_the_invoices_of_the_import_are_the_same_with_and_without_the_section(self):
        without_section, _ = self.roundtrip([name for name in ALL if name != SECTION_SUPPLEMENTARY])
        count_without = Invoice.objects.filter(zev_id=without_section["zev_id"]).count()
        totals_without = sorted(Invoice.objects.filter(zev_id=without_section["zev_id"]).values_list("total_chf", flat=True))
        zev = Zev.objects.get(pk=without_section["zev_id"])
        raw = export_and_clear(zev, ALL)
        with_section = self.import_(raw)

        self.assertEqual(Invoice.objects.filter(zev_id=with_section["zev_id"]).count(), count_without)
        self.assertEqual(
            sorted(Invoice.objects.filter(zev_id=with_section["zev_id"]).values_list("total_chf", flat=True)), totals_without
        )


class RejectedSupplementaryArchiveTests(SupplementaryArchiveTestCase):
    def setUp(self):
        super().setUp()
        # Meter ids are unique instance-wide: the original has to go before any import can be tried.
        self.cleared_archive = export_and_clear(self.zev, ALL)

    def full(self):
        return self.cleared_archive

    def sources(self, raw):
        return json.loads(self.members(raw)[SOURCES_FILE])

    def assert_rejected(self, raw, fragment):
        zevs_before = Zev.objects.count()
        sources_before = SupplementarySource.objects.count()
        with self.assertRaises(ImportFailed) as caught:
            self.import_(raw)
        self.assertIn(fragment, json.dumps(caught.exception.errors))
        self.assertEqual(Zev.objects.count(), zevs_before)
        self.assertEqual(SupplementarySource.objects.count(), sources_before)

    def test_an_unknown_meter_is_rejected(self):
        raw = self.full()
        entries = self.sources(raw)
        entries[0]["meter_id"] = "NOPE-1"
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "No imported metering point")

    def test_an_unknown_participant_is_rejected(self):
        raw = self.full()
        entries = self.sources(raw)
        entries[0]["participant_id"] = "00000000-0000-0000-0000-000000000000"
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "Unknown participant")

    def test_an_unflagged_meter_cannot_have_a_source(self):
        raw = self.full()
        entries = self.sources(raw)
        entries[0]["meter_id"] = "SX-CONS-1"  # a consumption meter, not flagged
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "generation behind the meter")

    def test_an_unknown_provider_is_rejected(self):
        raw = self.full()
        entries = self.sources(raw)
        entries[0]["provider"] = "evil_cloud"
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "evil_cloud")

    def test_a_solar_manager_source_needs_a_valid_id(self):
        raw = self.full()
        entries = self.sources(raw)
        solar = next(entry for entry in entries if entry["provider"] == "solar_manager")
        solar["external_id"] = "../../etc"
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "external_id")

    def test_a_push_source_cannot_carry_an_external_id(self):
        raw = self.full()
        entries = self.sources(raw)
        push = next(entry for entry in entries if entry["provider"] == "push")
        push["external_id"] = "ABC123"
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries}), "external_id")

    def test_two_sources_for_one_meter_are_rejected(self):
        raw = self.full()
        entries = self.sources(raw)
        entries.append({**entries[0]})
        manifest = json.loads(self.members(raw)["manifest.json"])
        manifest["counts"][SECTION_SUPPLEMENTARY] = 3
        self.assert_rejected(rewrite_archive(raw, replace={SOURCES_FILE: entries, "manifest.json": manifest}), "metering_point")

    def csv_with(self, mutate):
        raw = self.full()
        name = _supplementary_csv_name("SX-NET-1")
        lines = self.members(raw)[name].decode().splitlines()
        return rewrite_archive(raw, replace={name: ("\n".join(mutate(lines)) + "\n").encode()})

    def test_a_negative_value_is_rejected(self):
        raw = self.csv_with(lambda lines: [lines[0], lines[1].replace("1.2000", "-1.2000"), *lines[2:]])
        self.assert_rejected(raw, "outside the allowed range")

    def test_an_unaligned_timestamp_is_rejected(self):
        raw = self.csv_with(lambda lines: [lines[0], lines[1].replace("08:00:00", "08:07:00"), *lines[2:]])
        self.assert_rejected(raw, "15-minute")

    def test_a_duplicate_row_is_rejected(self):
        raw = self.csv_with(lambda lines: [*lines, lines[1]])
        self.assert_rejected(raw, "Duplicate")

    def test_a_missing_column_is_rejected(self):
        raw = self.csv_with(lambda lines: [lines[0].replace(",export_kwh", ""), *[line.rsplit(",", 1)[0] for line in lines[1:]]])
        self.assert_rejected(raw, "Missing column")

    def test_a_reading_for_an_unknown_meter_is_rejected(self):
        raw = self.csv_with(lambda lines: [lines[0], lines[1].replace("SX-NET-1", "NOPE-1"), *lines[2:]])
        self.assert_rejected(raw, "No imported energy data source")

    def test_a_dropped_readings_file_is_caught_by_the_manifest_counts(self):
        raw = self.full()
        broken = rewrite_archive(raw, drop=(_supplementary_csv_name("SX-NET-1"),))
        self.assert_rejected(broken, "archive declares")

    def test_a_garbled_value_is_rejected(self):
        raw = self.csv_with(lambda lines: [lines[0], lines[1].replace("1.2000", "lots"), *lines[2:]])
        self.assert_rejected(raw, "Unreadable value")

    def test_the_whole_import_rolls_back_on_one_bad_row(self):
        raw = self.csv_with(lambda lines: [*lines[:-1], lines[-1].replace("0.9000", "-1")])
        zevs = Zev.objects.count()
        with self.assertRaises(ImportFailed):
            self.import_(raw)
        self.assertEqual(Zev.objects.count(), zevs)
        self.assertEqual(SupplementaryReading.objects.count(), 0)
