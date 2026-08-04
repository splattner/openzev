"""Coverage for whole-ZEV export and import.

The interesting assertions are about what an archive is *not* allowed to do.
An import runs as the importing user and creates real billing data, so the
tests that earn their keep are the ones proving a hostile or broken archive
cannot link an account it does not own, cannot half-create a ZEV, and cannot be
read at all when its format version is one this instance does not understand.
"""

import io
import json
import zipfile
from datetime import date, datetime, time, timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoiceItem, InvoiceStatus
from metering.models import ImportLog, MeterReading, ReadingResolution
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth, make_user
from zev.models import (
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Zev,
)
from zev.transfer import ArchiveError, ImportFailed, build_archive, import_archive
from zev.transfer.schema import FORMAT_VERSION, MANIFEST_NAME, SECTIONS, missing_dependencies

ZEV_URL = "/api/v1/zev/zevs"


def build_populated_zev(owner, *, name="Transfer ZEV", meter_prefix="TR"):
    """A ZEV holding one of everything the archive can carry."""
    zev = Zev.objects.create(
        name=name,
        owner=owner,
        grid_operator="Testwerke AG",
        invoice_prefix="TRF",
        invoice_counter=3,
        bank_iban="CH9300762011623852957",
        notes="Community notes",
        local_tariff_notes="Local tariff conditions",
    )

    # Two participants sharing a surname: an assignment that survives this is
    # being remapped by id, not matched by name.
    alice = Participant.objects.create(
        zev=zev, first_name="Alice", last_name="Muster", email="alice@example.com",
        address_line1="Hauptstrasse 1", postal_code="8000", city="Zurich",
        valid_from=date(2026, 1, 1),
    )
    bob = Participant.objects.create(
        zev=zev, first_name="Bob", last_name="Muster", email="bob@example.com",
        valid_from=date(2026, 1, 1),
    )

    consumption = MeteringPoint.objects.create(
        zev=zev, meter_id=f"{meter_prefix}-CONS-1", meter_type=MeteringPointType.CONSUMPTION,
        location_description="Wohnung 1",
    )
    production = MeteringPoint.objects.create(
        zev=zev, meter_id=f"{meter_prefix}-PROD-1", meter_type=MeteringPointType.PRODUCTION,
    )
    MeteringPointAssignment.objects.create(
        metering_point=consumption, participant=bob, valid_from=date(2026, 1, 1),
    )
    MeteringPointAssignment.objects.create(
        metering_point=production, participant=alice, valid_from=date(2026, 1, 1),
    )

    tariff = Tariff.objects.create(
        zev=zev, name="Local solar", category=TariffCategory.ENERGY,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
        valid_from=date(2026, 1, 1),
    )
    TariffPeriod.objects.create(
        tariff=tariff, period_type=PeriodType.HIGH, price_chf_per_kwh=Decimal("0.18500"),
        time_from=time(7, 0), time_to=time(20, 0), weekdays="0,1,2,3,4",
    )

    MeterReading.objects.create(
        metering_point=consumption, timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("1.2500"), direction="in", resolution=ReadingResolution.HOURLY,
    )
    MeterReading.objects.create(
        metering_point=consumption, timestamp=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("2.5000"), direction="in", resolution=ReadingResolution.HOURLY,
    )
    MeterReading.objects.create(
        metering_point=production, timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("4.0000"), direction="out", resolution=ReadingResolution.HOURLY,
    )

    invoice = Invoice.objects.create(
        zev=zev, participant=alice, invoice_number="TRF-00002",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        status=InvoiceStatus.SENT, subtotal_chf=Decimal("42.00"), total_chf=Decimal("45.36"),
        vat_rate=Decimal("0.0800"), vat_chf=Decimal("3.36"),
    )
    InvoiceItem.objects.create(
        invoice=invoice, item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
        description="Solar energy", quantity_kwh=Decimal("100.0000"),
        unit_price_chf=Decimal("0.42000"), total_chf=Decimal("42.00"),
    )
    return zev


def export_to_bytes(zev, sections=None):
    buffer = io.BytesIO()
    build_archive(zev, sections, buffer)
    return buffer.getvalue()


def export_and_clear(zev, sections=None):
    """Export ``zev``, then delete it so its meter ids are free again.

    Meter ids are unique instance-wide, so importing an archive back into the
    instance it came from collides on every meter — correct behaviour, and
    exactly what a round-trip test must get out of the way to test anything
    else. ``Invoice.zev`` is PROTECT, so invoices go first.
    """
    raw = export_to_bytes(zev, sections)
    Invoice.objects.filter(zev=zev).delete()
    zev.delete()
    return raw


def rewrite_archive(raw, *, replace=None, drop=()):
    """Return a copy of ``raw`` with members replaced or removed."""
    replace = replace or {}
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            if name in drop:
                continue
            payload = replace.get(name, source.read(name))
            if not isinstance(payload, bytes):
                payload = json.dumps(payload).encode("utf-8")
            target.writestr(name, payload)
        for name, payload in replace.items():
            if name not in source.namelist():
                target.writestr(name, payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    return out.getvalue()


class SectionDependencyTests(TestCase):
    def test_readings_require_metering_points(self):
        self.assertEqual(missing_dependencies(["readings"]), {"readings": ["metering_points"]})

    def test_assignments_require_participants(self):
        self.assertEqual(
            missing_dependencies(["metering_points"]), {"metering_points": ["participants"]}
        )

    def test_a_complete_selection_has_no_gaps(self):
        self.assertEqual(missing_dependencies(SECTIONS), {})

    def test_export_refuses_an_incomplete_selection(self):
        owner = make_user("dep_owner", UserRole.ZEV_OWNER)
        zev = Zev.objects.create(name="Deps", owner=owner)
        with self.assertRaises(ValueError) as ctx:
            export_to_bytes(zev, ["readings"])
        self.assertIn("metering_points", str(ctx.exception))


class ArchiveShapeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("shape_owner", UserRole.ZEV_OWNER)
        cls.zev = build_populated_zev(cls.owner, meter_prefix="SHAPE")

    def test_archive_contains_a_manifest_and_one_csv_per_meter(self):
        with zipfile.ZipFile(io.BytesIO(export_to_bytes(self.zev))) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read(MANIFEST_NAME))
        self.assertIn("zev.json", names)
        self.assertIn("readings/SHAPE-CONS-1.csv", names)
        self.assertIn("readings/SHAPE-PROD-1.csv", names)
        self.assertEqual(manifest["format_version"], FORMAT_VERSION)
        self.assertEqual(manifest["counts"]["readings"], 3)

    def test_manifest_keeps_the_source_ids_so_a_restore_stays_possible(self):
        with zipfile.ZipFile(io.BytesIO(export_to_bytes(self.zev))) as archive:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        self.assertEqual(manifest["source_zev"]["id"], str(self.zev.id))

    def test_the_archive_never_carries_an_account_reference(self):
        """An export must not be able to grant anybody access to anything."""
        self.zev.participants.update(user=self.owner)
        raw = export_to_bytes(self.zev)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            participants = json.loads(archive.read("participants.json"))
            zev_payload = json.loads(archive.read("zev.json"))
        for entry in participants:
            self.assertNotIn("user", entry)
        self.assertNotIn("owner", zev_payload)
        self.assertNotIn(self.owner.username.encode(), raw)

    def test_selecting_one_section_leaves_the_others_out(self):
        with zipfile.ZipFile(io.BytesIO(export_to_bytes(self.zev, ["tariffs"]))) as archive:
            names = set(archive.namelist())
        self.assertEqual(names, {MANIFEST_NAME, "tariffs.json"})

    def test_a_meter_id_with_a_path_separator_cannot_escape_the_readings_folder(self):
        MeteringPoint.objects.create(
            zev=self.zev, meter_id="../../etc/passwd", meter_type=MeteringPointType.CONSUMPTION
        )
        with zipfile.ZipFile(io.BytesIO(export_to_bytes(self.zev))) as archive:
            names = archive.namelist()
        self.assertTrue(all(name.startswith(("readings/", "manifest", "zev.", "participants", "metering", "tariffs", "invoices")) for name in names))
        self.assertNotIn("../../etc/passwd.csv", names)
        self.assertIn("readings/.._.._etc_passwd.csv", names)

    def test_meter_ids_that_sanitize_to_the_same_name_keep_their_readings(self):
        """``"A/B"`` and ``"A_B"`` must not share a ZIP member: a duplicate
        member can only be read back as the first one, losing the second
        meter's readings without an error."""
        for meter_id, energy in (("SHAPE A/B", Decimal("9.0")), ("SHAPE A_B", Decimal("8.0"))):
            point = MeteringPoint.objects.create(
                zev=self.zev, meter_id=meter_id, meter_type=MeteringPointType.CONSUMPTION,
            )
            MeterReading.objects.create(
                metering_point=point,
                timestamp=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
                energy_kwh=energy,
                direction="in",
                resolution=ReadingResolution.HOURLY,
            )
        with zipfile.ZipFile(io.BytesIO(export_to_bytes(self.zev))) as archive:
            reading_members = [name for name in archive.namelist() if name.startswith("readings/")]
            payload = b"".join(archive.read(name) for name in set(reading_members))
        self.assertIn(b"9.0", payload)
        self.assertIn(b"8.0", payload)


class RoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("rt_owner", UserRole.ZEV_OWNER)
        cls.importer = make_user("rt_importer", UserRole.ADMIN)
        cls.source = build_populated_zev(cls.owner, meter_prefix="RT")

    def _import(self, raw=None, **kwargs):
        raw = raw if raw is not None else export_and_clear(self.source)
        return import_archive(io.BytesIO(raw), owner=self.importer, **kwargs)

    def test_every_section_arrives(self):
        result = self._import()
        imported = Zev.objects.get(pk=result["zev_id"])

        self.assertNotEqual(imported.pk, self.source.pk)
        self.assertEqual(imported.owner, self.importer)
        self.assertEqual(imported.name, self.source.name)
        self.assertEqual(imported.grid_operator, "Testwerke AG")
        self.assertEqual(imported.local_tariff_notes, "Local tariff conditions")
        self.assertEqual(imported.participants.count(), 2)
        self.assertEqual(imported.metering_points.count(), 2)
        self.assertEqual(imported.tariffs.count(), 1)
        self.assertEqual(imported.invoices.count(), 1)
        self.assertEqual(
            MeterReading.objects.filter(metering_point__zev=imported).count(), 3
        )

    def test_assignments_follow_the_right_participant_not_the_matching_surname(self):
        result = self._import()
        imported = Zev.objects.get(pk=result["zev_id"])
        holders = {
            assignment.metering_point.meter_id: assignment.participant.first_name
            for assignment in MeteringPointAssignment.objects.filter(
                metering_point__zev=imported
            )
        }
        self.assertEqual(holders, {"RT-CONS-1": "Bob", "RT-PROD-1": "Alice"})

    def test_participants_arrive_unlinked_even_when_an_account_shares_the_email(self):
        """Re-linking by email would let an edited archive hand over an account."""
        existing = make_user("alice_account", UserRole.PARTICIPANT)
        self.source.participants.filter(first_name="Alice").update(email=existing.email)
        result = self._import()
        imported = Zev.objects.get(pk=result["zev_id"])
        self.assertEqual(imported.participants.filter(user__isnull=False).count(), 0)

    def test_readings_keep_their_resolution_and_values(self):
        result = self._import()
        readings = MeterReading.objects.filter(
            metering_point__zev_id=result["zev_id"], metering_point__meter_id="RT-CONS-1"
        ).order_by("timestamp")
        self.assertEqual([r.energy_kwh for r in readings], [Decimal("1.2500"), Decimal("2.5000")])
        self.assertEqual({r.resolution for r in readings}, {ReadingResolution.HOURLY})

    def test_tariff_periods_round_trip_with_their_time_bands(self):
        result = self._import()
        period = TariffPeriod.objects.get(tariff__zev_id=result["zev_id"])
        self.assertEqual(period.price_chf_per_kwh, Decimal("0.18500"))
        self.assertEqual(period.time_from, time(7, 0))
        self.assertEqual(period.weekdays, "0,1,2,3,4")

    def test_invoice_items_travel_but_pdfs_do_not(self):
        result = self._import()
        invoice = Invoice.objects.get(zev_id=result["zev_id"])
        self.assertEqual(invoice.invoice_number, "TRF-00002")
        self.assertEqual(invoice.total_chf, Decimal("45.36"))
        self.assertEqual(invoice.items.count(), 1)
        self.assertFalse(invoice.pdf_file)

    def test_the_counter_is_pushed_past_the_imported_numbering(self):
        """Otherwise the first billing run mints a number the ZEV already has."""
        result = self._import()
        imported = Zev.objects.get(pk=result["zev_id"])
        self.assertEqual(imported.next_invoice_number(), "TRF-00003")

    def test_readings_are_recorded_as_an_import_log(self):
        result = self._import()
        log = ImportLog.objects.get(zev_id=result["zev_id"])
        self.assertEqual(log.rows_imported, 3)

    def test_importing_the_same_archive_twice_collides_on_the_meter_ids(self):
        """Import is not idempotent, and instance-wide meter ids make that visible."""
        raw = export_and_clear(self.source)
        first = self._import(raw)
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        self.assertIn("RT-CONS-1", json.dumps(ctx.exception.errors))
        self.assertEqual(Zev.objects.filter(pk=first["zev_id"]).count(), 1)

    def test_a_structure_only_archive_can_be_imported_twice(self):
        """Nothing in it is unique instance-wide, so two copies is the outcome."""
        raw = export_and_clear(self.source, ["zev", "tariffs"])
        first = self._import(raw)
        second = self._import(raw)
        self.assertNotEqual(first["zev_id"], second["zev_id"])
        self.assertEqual(Zev.objects.filter(name=self.source.name).count(), 2)

    def test_a_subset_can_be_imported_from_a_full_archive(self):
        result = self._import(sections=["zev", "tariffs"])
        imported = Zev.objects.get(pk=result["zev_id"])
        self.assertEqual(imported.tariffs.count(), 1)
        self.assertEqual(imported.participants.count(), 0)
        self.assertEqual(imported.metering_points.count(), 0)

    def test_a_name_override_renames_the_imported_zev(self):
        result = self._import(name_override="Copy of RT")
        self.assertEqual(Zev.objects.get(pk=result["zev_id"]).name, "Copy of RT")

    def test_a_structure_only_archive_still_names_the_zev(self):
        """The name falls back to the manifest when the settings section is absent."""
        name = self.source.name
        result = self._import(export_and_clear(self.source, ["tariffs"]))
        self.assertEqual(Zev.objects.get(pk=result["zev_id"]).name, name)


class RejectedArchiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("rej_owner", UserRole.ZEV_OWNER)
        cls.importer = make_user("rej_importer", UserRole.ADMIN)
        cls.source = build_populated_zev(cls.owner, meter_prefix="REJ")

    def _import(self, raw, **kwargs):
        return import_archive(io.BytesIO(raw), owner=self.importer, **kwargs)

    def _archive(self, sections=None, **rewrite):
        """An archive of the source ZEV, with the source then removed."""
        raw = export_and_clear(self.source, sections)
        return rewrite_archive(raw, **rewrite) if rewrite else raw

    def test_a_file_that_is_not_a_zip_is_refused(self):
        with self.assertRaises(ArchiveError):
            self._import(b"this is not a zip file")

    def test_a_zip_without_a_manifest_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("zev.json", b"{}")
        with self.assertRaises(ArchiveError) as ctx:
            self._import(buffer.getvalue())
        self.assertIn("not an OpenZEV export", str(ctx.exception))

    def test_an_unknown_format_version_fails_loudly(self):
        """Better than importing something half-understood."""
        raw = self._archive(replace={MANIFEST_NAME: {"format_version": 99, "sections": ["zev"]}})
        with self.assertRaises(ArchiveError) as ctx:
            self._import(raw)
        self.assertIn("99", str(ctx.exception))
        self.assertFalse(Zev.objects.filter(owner=self.importer).exists())

    def test_a_manifest_promising_a_missing_file_is_refused(self):
        raw = self._archive(["tariffs"], drop=("tariffs.json",))
        with self.assertRaises(ArchiveError) as ctx:
            self._import(raw)
        self.assertIn("tariffs.json", str(ctx.exception))

    def test_a_section_absent_from_the_archive_cannot_be_selected(self):
        with self.assertRaises(ValueError) as ctx:
            self._import(self._archive(["tariffs"]), sections=["tariffs", "participants"])
        self.assertIn("participants", str(ctx.exception))

    def test_a_colliding_meter_id_is_reported_by_name(self):
        raw = export_and_clear(self.source)
        MeteringPoint.objects.create(
            zev=Zev.objects.create(name="Other", owner=self.owner),
            meter_id="REJ-CONS-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        errors = ctx.exception.errors
        self.assertEqual([entry["label"] for entry in errors], ["REJ-CONS-1"])
        self.assertIn("unique instance-wide", errors[0]["errors"]["meter_id"][0])

    def test_nothing_is_created_when_any_entry_fails(self):
        """The whole import is one transaction: no half-populated ZEV survives."""
        raw = self._archive(
            replace={
                "participants.json": [
                    {"first_name": "Broken", "last_name": "Entry", "valid_from": "not-a-date"}
                ]
            }
        )
        before = set(Zev.objects.values_list("pk", flat=True))
        with self.assertRaises(ImportFailed):
            self._import(raw)
        self.assertEqual(set(Zev.objects.values_list("pk", flat=True)), before)
        # The metering-point section runs after participants, so these rows had
        # already been written when the rollback took them away again.
        self.assertFalse(MeteringPoint.objects.filter(meter_id="REJ-CONS-1").exists())
        self.assertFalse(MeterReading.objects.exists())

    def test_every_bad_entry_is_reported_in_one_response(self):
        raw = self._archive(
            ["zev", "participants"],
            replace={
                "participants.json": [
                    {"first_name": "A", "last_name": "One", "valid_from": "nope"},
                    {"first_name": "B", "last_name": "Two", "valid_from": "also-nope"},
                    {"first_name": "C", "last_name": "Three", "valid_from": "still-nope"},
                ]
            },
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        self.assertEqual(ctx.exception.total_errors, 3)
        self.assertEqual(
            [entry["label"] for entry in ctx.exception.errors], ["A One", "B Two", "C Three"]
        )

    def test_an_assignment_pointing_at_nothing_is_reported_rather_than_dropped(self):
        raw = self._archive(replace={"participants.json": []})
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        orphaned = [
            entry for entry in ctx.exception.errors if "participant_id" in entry["errors"]
        ]
        # Both assignments and the invoice: every reference is reported, so one
        # response says what the archive is actually missing.
        self.assertEqual(
            sorted(entry["section"] for entry in orphaned),
            ["invoices", "metering_points", "metering_points"],
        )

    def test_a_bad_reading_row_names_its_line(self):
        raw = self._archive(
            replace={
                "readings/REJ-CONS-1.csv": (
                    b"meter_id,timestamp,energy_kwh,direction,resolution,import_source\n"
                    b"REJ-CONS-1,2026-01-01T00:00:00+00:00,notanumber,in,hourly,csv\n"
                )
            }
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        entry = next(e for e in ctx.exception.errors if e["section"] == "readings")
        self.assertEqual(entry["position"], 2)
        self.assertIn("energy_kwh", entry["errors"])

    def test_a_duplicated_reading_is_named_rather_than_crashing_the_batch(self):
        row = b"REJ-CONS-1,2026-01-01T00:00:00+00:00,1.0,in,hourly,csv\n"
        raw = self._archive(
            replace={
                "readings/REJ-CONS-1.csv": (
                    b"meter_id,timestamp,energy_kwh,direction,resolution,import_source\n" + row + row
                )
            }
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        entry = next(e for e in ctx.exception.errors if e["section"] == "readings")
        self.assertIn("Duplicate", json.dumps(entry["errors"]))

    def test_a_readings_file_missing_a_column_is_reported_once_not_per_row(self):
        raw = self._archive(
            replace={"readings/REJ-CONS-1.csv": b"meter_id,timestamp\nREJ-CONS-1,2026-01-01T00:00:00+00:00\n"}
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        entries = [e for e in ctx.exception.errors if e["section"] == "readings"]
        self.assertEqual(len(entries), 1)
        self.assertIn("energy_kwh", json.dumps(entries[0]["errors"]))

    def test_the_error_list_is_capped_but_the_total_is_not(self):
        raw = self._archive(
            ["zev", "participants"],
            replace={
                "participants.json": [
                    {"first_name": f"P{index}", "last_name": "Bad", "valid_from": "nope"}
                    for index in range(120)
                ]
            },
        )
        with self.assertRaises(ImportFailed) as ctx:
            self._import(raw)
        self.assertEqual(ctx.exception.total_errors, 120)
        self.assertEqual(len(ctx.exception.errors), 50)
        self.assertIn("showing the first 50", ctx.exception.summary)


class TransferEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("tx_admin", UserRole.ADMIN)
        cls.owner = make_user("tx_owner", UserRole.ZEV_OWNER)
        cls.other_owner = make_user("tx_other", UserRole.ZEV_OWNER)
        cls.zev = build_populated_zev(cls.owner, meter_prefix="TX")

    def setUp(self):
        self.client = APIClient()

    def test_an_owner_can_export_their_own_zev(self):
        auth(self.client, self.owner)
        response = self.client.get(f"{ZEV_URL}/{self.zev.id}/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("openzev-export-transfer-zev-", response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertIn(MANIFEST_NAME, archive.namelist())

    def test_an_owner_cannot_export_somebody_elses_zev(self):
        auth(self.client, self.other_owner)
        response = self.client.get(f"{ZEV_URL}/{self.zev.id}/export/")
        self.assertEqual(response.status_code, 404)

    def test_export_accepts_a_section_selection(self):
        auth(self.client, self.admin)
        response = self.client.get(f"{ZEV_URL}/{self.zev.id}/export/?sections=tariffs")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertEqual(set(archive.namelist()), {MANIFEST_NAME, "tariffs.json"})

    def test_export_rejects_an_incomplete_selection_with_a_reason(self):
        auth(self.client, self.admin)
        response = self.client.get(f"{ZEV_URL}/{self.zev.id}/export/?sections=readings")
        self.assertEqual(response.status_code, 400)
        self.assertIn("metering_points", response.json()["detail"])

    def test_export_rejects_an_unknown_section(self):
        auth(self.client, self.admin)
        response = self.client.get(f"{ZEV_URL}/{self.zev.id}/export/?sections=secrets")
        self.assertEqual(response.status_code, 400)
        self.assertIn("secrets", response.json()["detail"])

    def test_the_dependency_graph_is_served_rather_than_hard_coded_client_side(self):
        auth(self.client, self.owner)
        response = self.client.get(f"{ZEV_URL}/transfer-sections/")
        self.assertEqual(response.status_code, 200)
        graph = {entry["name"]: entry["requires"] for entry in response.json()["sections"]}
        self.assertEqual(graph["readings"], ["metering_points"])
        self.assertEqual(list(graph), list(SECTIONS))

    def _upload(self, raw, name="archive.zip"):
        upload = io.BytesIO(raw)
        upload.name = name
        return upload

    def test_an_admin_can_import_an_archive(self):
        raw = export_and_clear(self.zev)
        auth(self.client, self.admin)
        response = self.client.post(
            f"{ZEV_URL}/import-archive/",
            {"file": self._upload(raw), "name": "Imported TX"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["zev_name"], "Imported TX")
        self.assertEqual(body["counts"]["participants"], 2)
        self.assertEqual(Zev.objects.get(pk=body["zev_id"]).owner, self.admin)

    def test_a_zev_owner_cannot_import(self):
        """Import creates a ZEV, and only admins create ZEVs on this instance."""
        auth(self.client, self.owner)
        response = self.client.post(
            f"{ZEV_URL}/import-archive/",
            {"file": self._upload(export_to_bytes(self.zev))},
            format="multipart",
        )
        self.assertEqual(response.status_code, 403)

    def test_import_reports_every_failure_in_the_response_body(self):
        raw = rewrite_archive(
            export_and_clear(self.zev, ["zev", "participants"]),
            replace={"participants.json": [{"first_name": "X", "last_name": "Y", "valid_from": "nope"}]},
        )
        auth(self.client, self.admin)
        response = self.client.post(
            f"{ZEV_URL}/import-archive/", {"file": self._upload(raw)}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["total_errors"], 1)
        self.assertEqual(body["errors"][0]["section"], "participants")
        self.assertEqual(body["errors"][0]["label"], "X Y")

    def test_import_without_a_file_says_so(self):
        auth(self.client, self.admin)
        response = self.client.post(f"{ZEV_URL}/import-archive/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_inspect_returns_the_manifest_without_creating_anything(self):
        before = Zev.objects.count()
        auth(self.client, self.admin)
        response = self.client.post(
            f"{ZEV_URL}/inspect-archive/",
            {"file": self._upload(export_to_bytes(self.zev))},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sections"], list(SECTIONS))
        self.assertEqual(Zev.objects.count(), before)

    def test_inspect_refuses_a_file_that_is_not_an_archive(self):
        auth(self.client, self.admin)
        response = self.client.post(
            f"{ZEV_URL}/inspect-archive/", {"file": self._upload(b"nope")}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
