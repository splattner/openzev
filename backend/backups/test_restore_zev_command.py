"""``openzev_restore --mode zev``: the shell front end of a per-ZEV restore."""

import io
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from audit.models import AuditEvent
from backups.fixtures import PDF_BYTES, build_world
from backups.models import BackupDestination, BackupJob, RestoreJob
from backups.test_archive import build
from backups.test_restore_zev import zev_rows
from exports.models import ExportJob
from invoices.models import Invoice
from zev.models import Participant, Zev


class ZevCommandTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world()
        cls.alpha_id = cls.world.alpha.pk
        cls.raw, _ = build()
        cls.original = zev_rows(cls.alpha_id)
        cls.alpha_pdf = cls.world.alpha_invoice.pdf_file.name

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.safety_dir = self.tmp / "safety"
        self.backup_file = self.tmp / "backup.zip"
        self.backup_file.write_bytes(self.raw)
        self.addCleanup(self._put_pdf_back)

    def _put_pdf_back(self):
        default_storage.delete(self.alpha_pdf)
        default_storage.save(self.alpha_pdf, io.BytesIO(PDF_BYTES))

    def run_command(self, *args, source=None):
        out, err = StringIO(), StringIO()
        call_command(
            "openzev_restore", "--mode", "zev", "--from", str(source or self.backup_file), *args, stdout=out, stderr=err,
        )
        return out.getvalue(), err.getvalue()

    def damage(self):
        Zev.objects.filter(pk=self.alpha_id).update(name="Damaged")
        Participant.objects.filter(zev_id=self.alpha_id, first_name="Alice").delete()


class RestoreCommandTests(ZevCommandTestCase):
    def test_a_real_restore_by_id_takes_a_safety_backup_and_restores(self):
        self.damage()
        out, _ = self.run_command("--zev", str(self.alpha_id), "--path", str(self.safety_dir))
        self.assertIn("Restore complete.", out)
        self.assertEqual(zev_rows(self.alpha_id), self.original)
        self.assertEqual(len(list(self.safety_dir.glob("*.zip"))), 1)
        self.assertIn(str(self.safety_dir), out)

    def test_the_run_is_recorded_as_a_restore_job_and_audited_as_a_management_command(self):
        self.damage()
        self.run_command("--zev", str(self.alpha_id), "--path", str(self.safety_dir))
        job = RestoreJob.objects.get()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.source_description, str(self.backup_file))
        self.assertIsNone(job.requester)
        self.assertFalse(job.dry_run)
        self.assertEqual(AuditEvent.objects.get(action_type="zev.restored").source, "management_command")

    def test_a_community_can_be_named_by_its_current_name(self):
        self.damage()  # now called "Damaged"
        self.run_command("--zev", "Damaged", "--path", str(self.safety_dir))
        self.assertEqual(zev_rows(self.alpha_id), self.original)

    def test_a_saved_destination_can_take_the_safety_backup(self):
        BackupDestination.objects.create(name="nightly", kind="local", path=str(self.safety_dir))
        self.damage()
        self.run_command("--zev", str(self.alpha_id), "--destination", "nightly")
        self.assertEqual(BackupJob.objects.get(trigger="pre_restore").destination.name, "nightly")

    def test_a_real_restore_without_a_place_for_the_safety_backup_is_refused_up_front(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        with self.assertRaisesMessage(CommandError, "safety backup"):
            self.run_command("--zev", str(self.alpha_id))
        self.assertEqual(zev_rows(self.alpha_id), damaged)
        self.assertFalse(RestoreJob.objects.exists())

    def test_a_deleted_community_is_named_by_id_and_needs_no_safety_backup(self):
        Invoice.objects.filter(zev_id=self.alpha_id).delete()
        Zev.objects.filter(pk=self.alpha_id).delete()
        out, _ = self.run_command("--zev", str(self.alpha_id))
        self.assertIn("Restore complete.", out)
        self.assertEqual(zev_rows(self.alpha_id), self.original)
        self.assertFalse(BackupJob.objects.filter(trigger="pre_restore").exists())

    def test_a_name_that_matches_nothing_says_how_to_name_a_deleted_community(self):
        with self.assertRaisesMessage(CommandError, "named by its id"):
            self.run_command("--zev", "Nonexistent", "--dry-run")

    def test_an_ambiguous_name_lists_the_ids(self):
        twin = Zev.objects.create(name="Alpha", owner=self.world.owner)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--zev", "Alpha", "--dry-run")
        self.assertIn(str(twin.pk), str(caught.exception))

    def test_the_safety_path_may_not_be_inside_the_media_root(self):
        with self.assertRaisesMessage(CommandError, "MEDIA_ROOT"):
            self.run_command("--zev", str(self.alpha_id), "--path", str(Path(settings.MEDIA_ROOT) / "safety"))

    def test_a_restore_from_s3_downloads_first(self):
        self.damage()

        def fake_fetch(url, target, *, endpoint_url="", region=""):
            self.assertEqual(url, "s3://bkt/backups/b.zip")
            target.write_bytes(self.raw)

        with mock.patch("backups.management.commands.openzev_restore.fetch_archive", side_effect=fake_fetch):
            out, _ = self.run_command(
                "--zev", str(self.alpha_id), "--path", str(self.safety_dir), source="s3://bkt/backups/b.zip"
            )
        self.assertIn("Restore complete.", out)
        self.assertEqual(zev_rows(self.alpha_id), self.original)


class PreviewAndRefusalTests(ZevCommandTestCase):
    def test_a_dry_run_prints_the_plan_and_changes_nothing(self):
        self.damage()
        damaged = zev_rows(self.alpha_id)
        out, _ = self.run_command("--zev", str(self.alpha_id), "--dry-run")
        self.assertIn("Dry run: nothing was changed.", out)
        self.assertIn("readings", out)
        self.assertIn("kept, never restored", out)
        self.assertEqual(zev_rows(self.alpha_id), damaged)
        self.assertFalse(BackupJob.objects.filter(trigger="pre_restore").exists())

    def test_a_dry_run_needs_no_safety_destination(self):
        self.run_command("--zev", str(self.alpha_id), "--dry-run")

    def test_a_dry_run_that_would_be_refused_exits_non_zero_and_says_why(self):
        ExportJob.objects.create(zev_id=self.alpha_id, requester=self.world.owner, status="running")
        with self.assertRaisesMessage(CommandError, "would be refused"):
            self.run_command("--zev", str(self.alpha_id), "--dry-run")

    def test_a_refusal_lists_each_problem_and_whether_force_helps(self):
        Invoice.objects.filter(pk=self.world.alpha_invoice.pk).update(status="paid")
        err = StringIO()
        with self.assertRaisesMessage(CommandError, "refused"):
            call_command(
                "openzev_restore", "--mode", "zev", "--from", str(self.backup_file), "--zev", str(self.alpha_id),
                "--path", str(self.safety_dir), stdout=StringIO(), stderr=err,
            )
        self.assertIn("PROBLEM: sent_invoice_reverted", err.getvalue())
        self.assertIn("needs --force", err.getvalue())
        self.assertFalse(list(self.safety_dir.glob("*.zip")), "no safety backup for a refused restore")

        out, err = self.run_command("--zev", str(self.alpha_id), "--path", str(self.safety_dir), "--force")
        self.assertIn("Restore complete.", out)
        self.assertIn("overridden with --force", err)

    def test_a_missing_account_is_a_warning_naming_it(self):
        email = self.world.member.email
        self.world.member.delete()
        _, err = self.run_command("--zev", str(self.alpha_id), "--dry-run")
        self.assertIn(email, err)
        self.assertIn("No account is ever created", err)


class ArgumentTests(ZevCommandTestCase):
    def test_zev_mode_needs_a_community(self):
        with self.assertRaisesMessage(CommandError, "--mode zev needs --zev"):
            self.run_command("--dry-run")

    def test_instance_mode_rejects_the_community_options(self):
        for flag, value in (("--zev", "x"), ("--path", "/tmp/x"), ("--destination", "d")):
            with self.subTest(flag), self.assertRaisesMessage(CommandError, "applies to --mode zev only"):
                call_command(
                    "openzev_restore", "--mode", "instance", "--from", str(self.backup_file), flag, value,
                    stdout=StringIO(), stderr=StringIO(),
                )

    def test_a_community_the_backup_does_not_hold_is_refused(self):
        raw, _ = build("zev", self.world.alpha)
        single = self.tmp / "alpha.zip"
        single.write_bytes(raw)
        with self.assertRaisesMessage(CommandError, "does not contain that community"):
            self.run_command("--zev", str(self.world.beta.pk), "--dry-run", source=single)

    def test_a_missing_file_is_a_command_error(self):
        with self.assertRaisesMessage(CommandError, "Cannot read"):
            self.run_command("--zev", str(self.alpha_id), "--dry-run", source="/nonexistent/backup.zip")
        self.assertFalse(RestoreJob.objects.exists())
