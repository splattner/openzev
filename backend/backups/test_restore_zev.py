"""Restoring one community into a running instance.

The promises worth testing are the negative ones: nothing outside the target
community changes — not another community, not an account row, not one audit
event — and a refusal or a failure leaves the community exactly as it was.
"""

import io
import json
from unittest import mock

from django.apps import apps
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import User, UserRole
from audit.models import AuditEvent
from backups import restore, restore_zev
from backups.fixtures import PDF_BYTES, build_world
from backups.models import BackupJobStatus, RestoreJob
from backups.registry import ZEV_SECTIONS
from backups.test_archive import build
from backups.test_restore_instance import lines, put_lines, snapshot, tamper
from exports.models import ExportJob
from invoices.models import ContractIssue, Invoice, InvoiceStatus
from metering.models import MeterReading
from testing.helpers import make_user
from zev.models import MeteringPoint, Participant, Zev


def zev_rows(zev_id) -> dict[str, list[dict]]:
    """The community's restorable rows, field for field (the audit trail is not restored)."""
    result = {}
    for name, parts in ZEV_SECTIONS:
        if name == "audit_events":
            continue
        for part in parts:
            model = apps.get_model(part.label)
            fields = [f.name for f in model._meta.concrete_fields if f.serialize]
            rows = [
                {"pk": obj.pk, **{n: getattr(obj, model._meta.get_field(n).attname) for n in fields}}
                for obj in model._base_manager.filter(**{part.lookup: zev_id}).order_by("pk")
            ]
            result[part.label] = rows
    return result


def rows_outside(zev_id) -> dict[str, list[dict]]:
    """Every backed-up row that does not belong to ``zev_id``: must be identical after a restore."""
    everything = snapshot()
    mine = zev_rows(zev_id)
    outside = {}
    for label, rows in everything.items():
        own = {row["pk"] for row in mine.get(label, [])}
        outside[label] = [row for row in rows if row["pk"] not in own]
    return outside


def restore_from(raw: bytes, zev_id, **options):
    return restore_zev.restore_zev(io.BytesIO(raw), str(zev_id), **options)


class ZevRestoreTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.alpha_id = cls.world.alpha.pk
        cls.beta_id = cls.world.beta.pk
        cls.raw, cls.manifest = build()
        cls.original_alpha = zev_rows(cls.alpha_id)
        cls.alpha_pdf = cls.world.alpha_invoice.pdf_file.name

    def setUp(self):
        self.addCleanup(self._put_pdf_back)

    def _put_pdf_back(self):
        default_storage.delete(self.alpha_pdf)
        default_storage.save(self.alpha_pdf, io.BytesIO(PDF_BYTES))

    def damage_alpha(self):
        """Change alpha the way a bad week might: rename it, lose people and readings, add an invoice."""
        Zev.objects.filter(pk=self.alpha_id).update(name="Damaged")
        Participant.objects.filter(zev_id=self.alpha_id, first_name="Alice").delete()
        MeterReading.objects.filter(metering_point__zev_id=self.alpha_id).delete()


class ReplaceInPlaceTests(ZevRestoreTestCase):
    def test_a_damaged_community_comes_back_exactly(self):
        self.damage_alpha()
        result = restore_from(self.raw, self.alpha_id)
        self.assertEqual(zev_rows(self.alpha_id), self.original_alpha)
        self.assertFalse(result.plan["blocked"])
        self.assertGreater(result.plan["restored"]["metering.MeterReading"], 0)

    def test_nothing_outside_the_community_changes(self):
        before = rows_outside(self.alpha_id)
        self.damage_alpha()
        damaged_outside = rows_outside(self.alpha_id)
        restore_from(self.raw, self.alpha_id)
        self.assertEqual(rows_outside(self.alpha_id), damaged_outside)
        # ...and the damage really was confined to alpha, so the comparison means something.
        self.assertEqual(damaged_outside["zev.Zev"], before["zev.Zev"])

    def test_no_account_row_is_created_modified_or_deleted(self):
        accounts = snapshot()["accounts.User"]
        self.damage_alpha()
        restore_from(self.raw, self.alpha_id)
        self.assertEqual(snapshot()["accounts.User"], accounts)

    def test_the_community_row_is_updated_in_place_so_links_to_it_survive(self):
        """Deleting it would null the audit events' community and the owner's preferred one."""
        events = list(AuditEvent.objects.filter(zev_id=self.alpha_id).values_list("pk", flat=True))
        self.assertTrue(events)
        self.damage_alpha()
        restore_from(self.raw, self.alpha_id)
        self.assertEqual(
            set(AuditEvent.objects.filter(zev_id=self.alpha_id).values_list("pk", flat=True)), set(events)
        )
        self.world.owner.refresh_from_db()
        self.assertEqual(self.world.owner.preferred_zev_id, self.alpha_id)

    def test_the_audit_trail_is_untouched_and_the_restore_writes_none_of_its_own(self):
        trail = snapshot()["audit.AuditEvent"]
        self.damage_alpha()
        restore_from(self.raw, self.alpha_id)
        self.assertEqual(snapshot()["audit.AuditEvent"], trail)

    def test_a_deleted_community_is_recreated_and_its_old_audit_events_stay_as_they_were(self):
        Invoice.objects.filter(zev_id=self.alpha_id).delete()
        Zev.objects.filter(pk=self.alpha_id).delete()
        orphaned = snapshot()["audit.AuditEvent"]
        self.assertFalse(Zev.objects.filter(pk=self.alpha_id).exists())

        result = restore_from(self.raw, self.alpha_id)

        self.assertFalse(result.plan["zev"]["exists_now"])
        self.assertEqual(zev_rows(self.alpha_id), self.original_alpha)
        self.assertEqual(snapshot()["audit.AuditEvent"], orphaned)

    def test_other_communities_can_be_restored_from_the_same_instance_backup(self):
        Zev.objects.filter(pk=self.beta_id).update(name="Damaged beta")
        restore_from(self.raw, self.beta_id)
        self.assertEqual(Zev.objects.get(pk=self.beta_id).name, "Beta")
        self.assertEqual(Zev.objects.get(pk=self.alpha_id).name, "Alpha")

    def test_a_single_community_backup_restores_that_community(self):
        raw, _ = build("zev", self.world.alpha)
        self.damage_alpha()
        restore_from(raw, self.alpha_id)
        self.assertEqual(zev_rows(self.alpha_id), self.original_alpha)

    def test_a_community_the_backup_does_not_hold_is_refused(self):
        raw, _ = build("zev", self.world.alpha)
        with self.assertRaisesMessage(restore.RestoreError, "does not contain that community"):
            restore_from(raw, self.beta_id)

    def test_invoice_pdfs_are_written_back_under_their_names(self):
        default_storage.delete(self.alpha_pdf)
        restore_from(self.raw, self.alpha_id)
        with default_storage.open(self.alpha_pdf, "rb") as stored:
            self.assertEqual(stored.read(), PDF_BYTES)

    def test_a_sequence_only_advances_for_integer_keys(self):
        with mock.patch.object(restore.connection.ops, "sequence_reset_sql", return_value=[]) as reset:
            restore_from(self.raw, self.alpha_id)
        models = reset.call_args.args[1]
        self.assertEqual({m._meta.label for m in models}, {"invoices.InvoiceDynamicSourceEvidence"})


class LockTests(ZevRestoreTestCase):
    def test_the_community_row_is_locked_for_the_duration_of_the_replace(self):
        """SQLite ignores row locks, so what can be checked everywhere is that one is taken, on that row."""
        from django.db.models.query import QuerySet

        locked = []
        original = QuerySet.select_for_update

        def spy(queryset, *args, **kwargs):
            locked.append(queryset.model)
            return original(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", spy):
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(locked, [Zev])

    def test_a_dry_run_takes_no_lock(self):
        from django.db.models.query import QuerySet

        with mock.patch.object(QuerySet, "select_for_update", side_effect=AssertionError("locked")):
            restore_from(self.raw, self.alpha_id, dry_run=True)


class AccountRelinkTests(ZevRestoreTestCase):
    def test_a_participants_account_is_found_again_by_email_even_under_a_new_id(self):
        member = self.world.member
        email = member.email
        member.delete()
        replacement = make_user("member-again", UserRole.PARTICIPANT)
        User.objects.filter(pk=replacement.pk).update(email=email)

        result = restore_from(self.raw, self.alpha_id)

        alice = Participant.objects.get(zev_id=self.alpha_id, first_name="Alice")
        self.assertEqual(alice.user_id, replacement.pk)
        self.assertEqual(result.plan["accounts"]["missing"], [])
        replacement.refresh_from_db()
        self.assertEqual(replacement.email, email)  # untouched

    def test_a_missing_account_is_reported_and_left_unlinked(self):
        email = self.world.member.email
        self.world.member.delete()
        result = restore_from(self.raw, self.alpha_id)
        self.assertIn(email, result.plan["accounts"]["missing"])
        self.assertIsNone(Participant.objects.get(zev_id=self.alpha_id, first_name="Alice").user_id)
        self.assertFalse(User.objects.filter(email=email).exists(), "a restore never creates an account")

    def test_the_owner_follows_the_email_when_the_owner_account_was_recreated(self):
        Invoice.objects.all().delete()
        Zev.objects.all().delete()
        email = self.world.owner.email
        self.world.owner.delete()
        new_owner = make_user("owner-again", UserRole.ZEV_OWNER)
        User.objects.filter(pk=new_owner.pk).update(email=email)
        restore_from(self.raw, self.alpha_id)
        self.assertEqual(Zev.objects.get(pk=self.alpha_id).owner_id, new_owner.pk)

    def test_a_community_that_exists_keeps_its_owner_when_the_backups_owner_is_gone(self):
        current_owner = make_user("later-owner", UserRole.ZEV_OWNER)
        Zev.objects.filter(pk=self.alpha_id).update(owner=current_owner)
        Zev.objects.filter(pk=self.beta_id).update(owner=current_owner)
        self.world.owner.delete()  # the backup's owner no longer exists
        result = restore_from(self.raw, self.alpha_id)
        self.assertEqual(Zev.objects.get(pk=self.alpha_id).owner_id, current_owner.pk)
        self.assertFalse(result.plan["blocked"])

    def test_a_community_that_must_be_recreated_without_a_findable_owner_is_refused(self):
        Invoice.objects.all().delete()
        Zev.objects.all().delete()
        self.world.owner.delete()
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id, force=True)
        self.assertEqual([c["kind"] for c in caught.exception.plan["conflicts"]], ["owner_not_found"])


class ConflictTests(ZevRestoreTestCase):
    def kinds(self, plan):
        return [c["kind"] for c in plan["conflicts"]]

    def test_a_clean_restore_has_no_conflicts(self):
        self.assertEqual(restore_from(self.raw, self.alpha_id, dry_run=True).plan["conflicts"], [])

    def test_a_sent_invoice_the_restore_would_delete_needs_force(self):
        extra = Invoice.objects.get(pk=self.world.alpha_invoice.pk)
        extra.pk = None
        extra.invoice_number = "TRF-EXTRA"
        extra.status = InvoiceStatus.PAID
        extra.save()
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(self.kinds(caught.exception.plan), ["sent_invoice_deleted"])
        self.assertIn("TRF-EXTRA", caught.exception.plan["conflicts"][0]["detail"])
        self.assertTrue(Invoice.objects.filter(invoice_number="TRF-EXTRA").exists())

        restore_from(self.raw, self.alpha_id, force=True)
        self.assertFalse(Invoice.objects.filter(invoice_number="TRF-EXTRA").exists())

    def test_an_invoice_that_was_only_draft_in_the_backup_is_rolled_back_only_with_force(self):
        Invoice.objects.filter(pk=self.world.alpha_invoice.pk).update(status=InvoiceStatus.DRAFT)
        raw, _ = build()
        Invoice.objects.filter(pk=self.world.alpha_invoice.pk).update(status=InvoiceStatus.PAID)
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(raw, self.alpha_id)
        self.assertEqual(self.kinds(caught.exception.plan), ["sent_invoice_reverted"])
        self.assertIn("paid → draft", caught.exception.plan["conflicts"][0]["detail"])
        restore_from(raw, self.alpha_id, force=True)
        self.assertEqual(Invoice.objects.get(pk=self.world.alpha_invoice.pk).status, InvoiceStatus.DRAFT)

    def test_an_issued_contract_the_restore_would_delete_needs_force(self):
        alice = Participant.objects.get(zev_id=self.alpha_id, first_name="Alice")
        ContractIssue.objects.create(
            zev_id=self.alpha_id, participant=alice, version=2, document_number="C-NEW", language="de",
            context_hash="c" * 64, pdf=b"%PDF-new", issued_by=self.world.owner,
        )
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(self.kinds(caught.exception.plan), ["contract_issue_deleted"])
        self.assertTrue(ContractIssue.objects.filter(document_number="C-NEW").exists())
        restore_from(self.raw, self.alpha_id, force=True)
        self.assertFalse(ContractIssue.objects.filter(document_number="C-NEW").exists())

    def test_a_meter_id_now_owned_by_another_community_cannot_be_forced(self):
        point = MeteringPoint.objects.get(zev_id=self.alpha_id, meter_id="ALPHA-CONS-1")
        MeteringPoint.objects.filter(pk=point.pk).update(zev_id=self.beta_id, meter_id="ALPHA-CONS-1")
        # Alpha's own copy of that point is gone from alpha; the backup still lists it there.
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id, force=True)
        conflict = caught.exception.plan["conflicts"][0]
        self.assertEqual(conflict["kind"], "meter_id_owned_by_other_zev")
        self.assertIn("Beta", conflict["detail"])
        self.assertFalse(conflict["overridable"])
        self.assertEqual(MeteringPoint.objects.get(pk=point.pk).zev_id, self.beta_id)

    def test_a_referenced_price_source_that_no_longer_exists_cannot_be_forced(self):
        def edit(members, manifest):
            name = f"zevs/{self.alpha_id}/tariffs.jsonl"
            records = lines(members, name)
            tariff = next(r for r in records if r["model"] == "tariffs.tariff")
            tariff["fields"]["dynamic_source"] = "9d2b5f0e-0000-4000-8000-000000000001"
            put_lines(members, name, records)

        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(tamper(self.raw, edit), self.alpha_id, force=True)
        self.assertEqual(self.kinds(caught.exception.plan), ["referenced_row_missing"])

    def test_a_running_export_blocks_it_even_with_force(self):
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id, force=True)
        self.assertEqual(self.kinds(caught.exception.plan), ["export_in_progress"])

    def test_another_restore_of_the_same_community_blocks_it(self):
        other = RestoreJob.objects.create(target_zev_id=self.alpha_id, status=BackupJobStatus.RUNNING)
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(self.kinds(caught.exception.plan), ["restore_in_progress"])
        # ...but a job does not block itself.
        restore_from(self.raw, self.alpha_id, exclude_job=other.pk)

    def test_a_refusal_changes_nothing(self):
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="queued")
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)
        with self.assertRaises(restore_zev.RestoreRefused):
            restore_from(self.raw, self.alpha_id, force=True)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_the_conflict_list_is_capped_and_says_how_many_more(self):
        template = Invoice.objects.get(pk=self.world.alpha_invoice.pk)
        for n in range(restore_zev._MAX_LISTED + 5):
            template.pk = None
            template.invoice_number = f"TRF-X-{n:03d}"
            template.status = InvoiceStatus.SENT
            template.save()
        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id)
        details = [c["detail"] for c in caught.exception.plan["conflicts"]]
        self.assertEqual(len(details), restore_zev._MAX_LISTED + 1)
        self.assertEqual(details[-1], "and 5 more")


class DryRunTests(ZevRestoreTestCase):
    def test_a_dry_run_returns_the_plan_and_writes_nothing(self):
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)
        result = restore_from(self.raw, self.alpha_id, dry_run=True)
        self.assertEqual(zev_rows(self.alpha_id), damaged)
        sections = result.plan["sections"]
        self.assertGreater(sections["readings"]["backup"], sections["readings"]["current"])
        self.assertEqual(sections["readings"]["current"], 0)
        self.assertTrue(sections["audit_events"]["kept"])
        self.assertEqual(result.plan["zev"]["current_name"], "Damaged")
        self.assertEqual(result.plan["zev"]["name"], "Alpha")
        self.assertIsNone(result.plan["restored"])

    def test_a_dry_run_reports_refusals_instead_of_raising(self):
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
        result = restore_from(self.raw, self.alpha_id, dry_run=True)
        self.assertTrue(result.plan["blocked"])
        self.assertEqual(result.plan["conflicts"][0]["kind"], "export_in_progress")

    def test_a_dry_run_shows_accounts_that_would_not_be_found(self):
        email = self.world.member.email
        self.world.member.delete()
        result = restore_from(self.raw, self.alpha_id, dry_run=True)
        self.assertEqual(result.plan["accounts"]["missing"], [email])
        self.assertEqual(result.plan["accounts"]["relink"], 1)

    def test_a_dry_run_never_takes_a_safety_backup(self):
        safety = mock.Mock()
        restore_from(self.raw, self.alpha_id, dry_run=True, safety_backup=safety)
        safety.assert_not_called()

    def test_a_dry_run_finds_records_the_schema_cannot_hold(self):
        def edit(members, manifest):
            name = f"zevs/{self.alpha_id}/participants.jsonl"
            records = lines(members, name)
            records[0]["fields"]["no_such_column"] = "Secret Name"
            put_lines(members, name, records)

        with self.assertRaises(restore.RestoreError) as caught:
            restore_from(tamper(self.raw, edit), self.alpha_id, dry_run=True)
        self.assertNotIn("Secret Name", str(caught.exception))


class SafetyBackupTests(ZevRestoreTestCase):
    def test_it_runs_after_the_plan_passes_and_before_the_first_write(self):
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)
        seen = {}

        def safety():
            seen["rows_at_that_moment"] = zev_rows(self.alpha_id)
            return "safety-job-id"

        result = restore_from(self.raw, self.alpha_id, safety_backup=safety)
        self.assertEqual(seen["rows_at_that_moment"], damaged)
        self.assertEqual(result.plan["safety_backup_id"], "safety-job-id")
        self.assertEqual(result.safety_backup_id, "safety-job-id")

    def test_a_failing_safety_backup_stops_everything(self):
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)

        def safety():
            raise restore.RestoreError("The safety backup failed, so nothing was restored.")

        with self.assertRaises(restore.RestoreError):
            restore_from(self.raw, self.alpha_id, safety_backup=safety)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_conflicts_are_checked_again_under_the_lock_after_the_safety_backup(self):
        """Minutes can pass between the plan and the first write; the world can change in them."""
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)

        def safety():
            ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
            return "safety-job-id"

        with self.assertRaises(restore_zev.RestoreRefused) as caught:
            restore_from(self.raw, self.alpha_id, safety_backup=safety)
        self.assertEqual([c["kind"] for c in caught.exception.plan["conflicts"]], ["export_in_progress"])
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_it_is_not_taken_for_a_refused_restore(self):
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
        safety = mock.Mock()
        with self.assertRaises(restore_zev.RestoreRefused):
            restore_from(self.raw, self.alpha_id, safety_backup=safety)
        safety.assert_not_called()

    def test_it_is_not_taken_for_a_community_that_does_not_exist_yet(self):
        Invoice.objects.filter(zev_id=self.alpha_id).delete()
        Zev.objects.filter(pk=self.alpha_id).delete()
        safety = mock.Mock()
        restore_from(self.raw, self.alpha_id, safety_backup=safety)
        safety.assert_not_called()


class RollbackTests(ZevRestoreTestCase):
    def test_a_failure_late_in_the_restore_leaves_the_community_as_it_was(self):
        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)
        with (
            mock.patch.object(restore_zev, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_a_pdf_that_was_overwritten_is_put_back_when_the_restore_fails(self):
        default_storage.delete(self.alpha_pdf)
        default_storage.save(self.alpha_pdf, io.BytesIO(b"the current pdf, newer than the backup"))
        with (
            mock.patch.object(restore_zev, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw, self.alpha_id)
        with default_storage.open(self.alpha_pdf, "rb") as stored:
            self.assertEqual(stored.read(), b"the current pdf, newer than the backup")

    def test_dangling_references_roll_everything_back(self):
        def edit(members, manifest):
            name = f"zevs/{self.alpha_id}/invoices.jsonl"
            records = lines(members, name)
            invoice = next(r for r in records if r["model"] == "invoices.invoice")
            invoice["fields"]["participant"] = "9d2b5f0e-0000-4000-8000-000000000002"
            put_lines(members, name, records)

        self.damage_alpha()
        damaged = zev_rows(self.alpha_id)
        with self.assertRaises(restore.RestoreError):
            restore_from(tamper(self.raw, edit), self.alpha_id)
        self.assertEqual(zev_rows(self.alpha_id), damaged)

    def test_the_trail_and_other_communities_survive_a_failed_restore(self):
        outside = rows_outside(self.alpha_id)
        with (
            mock.patch.object(restore_zev, "_reconcile_sequences", side_effect=IntegrityError("boom")),
            self.assertRaises(restore.RestoreError),
        ):
            restore_from(self.raw, self.alpha_id)
        self.assertEqual(rows_outside(self.alpha_id), outside)


class MetadataTests(ZevRestoreTestCase):
    def test_the_plan_describes_the_backup_it_came_from(self):
        plan = restore_from(self.raw, self.alpha_id, dry_run=True).plan
        self.assertEqual(plan["backup"]["scope"], "instance")
        self.assertEqual(plan["backup"]["created_at"], self.manifest["created_at"])
        self.assertEqual(plan["media"]["files"], 1)
        self.assertTrue(json.dumps(plan))  # the plan is stored as JSON
