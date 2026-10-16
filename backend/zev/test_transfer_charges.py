"""Format 8: a ZEV's one-off charges in the transfer archive (SPEC-2026-10-variable-charges §6)."""

import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import UserRole
from invoices.models import Charge, ChargeAllocation, ChargeVatTreatment
from tariffs.models import SplitKey
from testing.helpers import make_user
from zev.models import Participant, Zev
from zev.test_transfer import build_populated_zev, export_and_clear, export_to_bytes, rewrite_archive
from zev.transfer import ImportFailed, import_archive
from zev.transfer.schema import SECTION_CHARGES, SECTION_DEPENDENCIES, SECTIONS, check_dependencies

ALL = list(SECTIONS)


class ChargeArchiveTests(TestCase):
    def setUp(self):
        self.owner = make_user("ch_owner", UserRole.USER)
        self.importer = make_user("ch_importer", UserRole.ADMIN)
        self.zev = build_populated_zev(self.owner, meter_prefix="CH")
        self.alice = Participant.objects.get(zev=self.zev, party__first_name="Alice")
        self.bob = Participant.objects.get(zev=self.zev, party__first_name="Bob")
        everyone = Charge.objects.create(
            zev=self.zev, description="Porto", amount_chf=Decimal("12.50"), charge_date=date(2026, 1, 15),
        )
        chosen = Charge.objects.create(
            zev=self.zev, description="Reparatur", amount_chf=Decimal("80.00"), charge_date=date(2026, 2, 3),
            allocation=ChargeAllocation.SELECTED_PARTICIPANTS, split_key=SplitKey.WEIGHT,
            vat_treatment=ChargeVatTreatment.PASS_THROUGH,
        )
        chosen.participants.set([self.alice])
        self.everyone, self.chosen = everyone, chosen

    def import_(self, raw):
        return import_archive(io.BytesIO(raw), owner=self.importer)

    def test_the_section_depends_on_participants(self):
        self.assertEqual(SECTION_DEPENDENCIES[SECTION_CHARGES], ("participants",))
        with self.assertRaisesRegex(ValueError, "charges requires"):
            check_dependencies(["zev", SECTION_CHARGES])

    def test_charges_survive_a_round_trip_with_their_participants(self):
        raw = export_and_clear(self.zev, ALL)

        result = self.import_(raw)

        zev = Zev.objects.get(pk=result["zev_id"])
        self.assertEqual(result["counts"][SECTION_CHARGES], 2)
        charges = {c.description: c for c in Charge.objects.filter(zev=zev)}
        self.assertEqual(set(charges), {"Porto", "Reparatur"})
        porto, repair = charges["Porto"], charges["Reparatur"]
        self.assertEqual((porto.amount_chf, porto.allocation, porto.vat_treatment),
                         (Decimal("12.50"), "all_participants", "taxable"))
        self.assertEqual(
            (repair.amount_chf, repair.charge_date, repair.allocation, repair.split_key, repair.vat_treatment),
            (Decimal("80.00"), date(2026, 2, 3), "selected_participants", "weight", "pass_through"),
        )
        self.assertEqual([p.party.first_name for p in repair.participants.all()], ["Alice"])
        self.assertEqual(list(porto.participants.all()), [])

    def test_a_default_export_carries_charges_and_counts_them(self):
        raw = export_to_bytes(self.zev)

        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            rows = json.loads(archive.read("charges.json"))
        self.assertEqual(manifest["counts"][SECTION_CHARGES], 2)
        self.assertEqual({row["description"] for row in rows}, {"Porto", "Reparatur"})

    def test_an_older_archive_without_the_section_still_imports(self):
        raw = export_and_clear(self.zev, ["zev", "participants"])

        self.import_(raw)

        self.assertFalse(Charge.objects.exists())

    def test_a_selected_charge_whose_participants_are_missing_rejects_the_import(self):
        raw = export_to_bytes(self.zev, ["zev", "participants", SECTION_CHARGES])
        rows = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("charges.json"))
        for row in rows:
            row["participant_ids"] = ["unknown-id"] if row["participant_ids"] else []
        tampered = rewrite_archive(raw, replace={"charges.json": rows})
        export_and_clear(self.zev, ["zev"])

        with self.assertRaises(ImportFailed) as caught:
            self.import_(tampered)

        self.assertIn("Reparatur", str(caught.exception.errors))
        self.assertFalse(Charge.objects.exists())
