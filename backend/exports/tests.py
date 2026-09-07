"""Coverage for the async export job flow (ADR 0017).

The whole-ZEV annual-statement ZIP moved here from ``invoices/test_reports.py``
when generation became a Celery job: this module covers the job endpoints
(create/list/status/download), the executor's claim and failure semantics,
expiry and the periodic sweep, and the ZIP builder's naming rules that used to
live in the reports view tests. Single-document report tests stay in
``invoices/test_reports.py``.

The executor resolves renderers through each type's ``ExportDefinition`` in
``EXPORT_DEFINITIONS``, so tests stub the definition's ``renderer`` callable
(patching the registry mapping itself would not affect the lookup).
"""

import io
import uuid
import zipfile
from contextlib import ExitStack
from datetime import timedelta
from unittest import mock

import pytest

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventSource, AuditEventStatus
from testing.helpers import authenticate as auth, make_user

from . import exporters
from . import tasks as tasks_module
from .exporters import ExportNotPossibleError, ExportResult
from .models import ExportJob, ExportJobStatus
from .tasks import execute_export_job, run_export_job, sweep_export_jobs_impl
from invoices.test_helpers import make_participant, make_zev

EXPORTS = "/api/v1/exports/"


def _stub_renderer(return_value=None, side_effect=None):
    """A mock renderer wired into the annual-statements definition for the
    test's duration."""
    render = mock.Mock(return_value=return_value, side_effect=side_effect)
    return render, mock.patch.object(
        exporters.EXPORT_DEFINITIONS["annual_statements"], "renderer", render,
    )


def _default_result():
    return ExportResult(payload=b"ZIP", generated_count=2, omitted_ids=[])


class ExportJobApiTestCase(TestCase):
    """Two ZEVs under different owners, plus a plain participant."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("exp_admin", UserRole.ADMIN)
        self.owner = make_user("exp_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Export ZEV")
        for index in range(2):
            make_participant(self.zev, first=f"Pia{index}", last="Muster")
        self.other_owner = make_user("exp_other_owner", UserRole.ZEV_OWNER)
        self.other_zev = make_zev(self.other_owner, "Other ZEV")
        make_participant(self.other_zev, first="Otto", last="Fremd")
        self.participant_user = make_user("exp_participant", UserRole.PARTICIPANT)

    def _post(self, user, payload=None):
        auth(self.client, user)
        return self.client.post(EXPORTS + "jobs/", payload or {}, format="json")

    def _create_job(self, user=None, zev=None, year=2026):
        user = user or self.owner
        zev = zev or self.zev
        return self._post(user, {
            "export_type": "annual_statements",
            "zev_id": str(zev.pk),
            "params": {"year": year},
        })


class ExportJobCreateTests(ExportJobApiTestCase):
    def test_owner_creates_a_queued_job_with_202(self):
        resp = self._create_job()

        self.assertEqual(resp.status_code, 202)
        job = ExportJob.objects.get(pk=resp.data["job"]["id"])
        self.assertEqual(job.status, ExportJobStatus.QUEUED)
        self.assertEqual(job.requester, self.owner)
        self.assertEqual(job.zev, self.zev)
        self.assertEqual(job.params, {"year": 2026})

    def test_admin_can_create_for_any_zev(self):
        resp = self._create_job(user=self.admin)

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(ExportJob.objects.get(pk=resp.data["job"]["id"]).requester, self.admin)

    def test_enqueue_is_registered_after_commit_with_the_job_id(self):
        with mock.patch("exports.views.transaction.on_commit") as on_commit, \
                mock.patch("exports.tasks.run_export_job.delay") as delay:
            resp = self._create_job()
            callback = on_commit.call_args.args[0]
            callback()

        self.assertEqual(resp.status_code, 202)
        job = ExportJob.objects.get(pk=resp.data["job"]["id"])
        delay.assert_called_once_with(str(job.pk))

    def test_repeat_request_returns_the_inflight_job_instead_of_duplicating(self):
        first = self._create_job()
        second = self._create_job()

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.data["job"]["id"], first.data["job"]["id"])
        self.assertEqual(
            ExportJob.objects.filter(requester=self.owner, zev=self.zev).count(), 1,
        )

    def test_repeat_request_matches_any_inflight_job_not_only_the_newest(self):
        """A repeat of an older year is deduplicated against that year's own
        inflight job even when a newer year is queued behind it: comparing only
        the newest active job would schedule a second render of 2026."""
        first = self._create_job(year=2026)
        newer = self._create_job(year=2027)

        self.assertNotEqual(newer.data["job"]["id"], first.data["job"]["id"])
        again = self._create_job(year=2026)

        self.assertEqual(again.data["job"]["id"], first.data["job"]["id"])
        self.assertEqual(
            ExportJob.objects.filter(requester=self.owner, zev=self.zev).count(), 2,
        )

    def test_a_completed_job_does_not_block_a_new_export(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            execute_export_job(str(job.pk))

        again = self._create_job()
        self.assertEqual(again.status_code, 202)
        self.assertNotEqual(again.data["job"]["id"], str(job.pk))

    def test_enqueue_failure_marks_the_job_failed_and_returns_503(self):
        """TestCase runs inside a transaction, so on_commit is deferred; run
        the callback inline to exercise the broker-failure path."""
        with mock.patch(
            "exports.views.transaction.on_commit", side_effect=lambda fn: fn(),
        ), mock.patch.object(run_export_job, "delay", side_effect=RuntimeError("broker down")):
            resp = self._create_job()

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["error"], "The export could not be queued. Please try again.")
        job = ExportJob.objects.get(requester=self.owner, zev=self.zev)
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertTrue(job.error_message)
        failed = AuditEvent.objects.get(
            action_type="annual_statement_export.failed", target_id=str(job.pk),
        )
        self.assertEqual(failed.status, AuditEventStatus.FAILED)
        self.assertEqual(failed.metadata_json.get("error"), "enqueue failed")

    def test_creation_records_a_queued_audit_event(self):
        resp = self._create_job()
        job = ExportJob.objects.get(pk=resp.data["job"]["id"])

        event = AuditEvent.objects.get(action_type="annual_statement_export.created", target_id=str(job.pk))
        self.assertEqual(event.status, AuditEventStatus.QUEUED)
        self.assertEqual(event.actor_user, self.owner)
        self.assertEqual(event.zev, self.zev)
        self.assertEqual(event.metadata_json.get("year"), 2026)

    def test_creation_audit_uses_the_export_types_own_display_and_summary(self):
        """The generic create path must not assume annual statements or a
        year: a type with year-less params is audited with its own wording."""
        from .exporters import EXPORT_DEFINITIONS, ExportDefinition

        stub = ExportDefinition(
            validator=lambda zev, params: {"flavour": params.get("flavour", "plain")},
            renderer=mock.Mock(),
            audit_prefix="stub_export",
            audit_category="invoice",
            filename=lambda params: "stub.zip",
            display_for=lambda zev, params: f"{zev.name} [{params['flavour']}]",
            created_summary_for=lambda zev, params: f"Queued stub ({params['flavour']}).",
            enqueue_failed_summary_for=lambda zev, params: "Stub could not be queued.",
            completed_summary_for=lambda zev, params, result: "Stub done.",
            audit_metadata_for=lambda params: {"flavour": params["flavour"]},
        )
        EXPORT_DEFINITIONS["stub"] = stub
        try:
            resp = self._post(self.owner, {
                "export_type": "stub",
                "zev_id": str(self.zev.pk),
                "params": {"flavour": "smoke"},
            })
        finally:
            del EXPORT_DEFINITIONS["stub"]

        self.assertEqual(resp.status_code, 202)
        job = ExportJob.objects.get(pk=resp.data["job"]["id"])
        self.assertEqual(job.params, {"flavour": "smoke"})
        event = AuditEvent.objects.get(
            action_type="stub_export.created", target_id=str(job.pk),
        )
        self.assertEqual(event.summary, "Queued stub (smoke).")
        self.assertEqual(event.target_display, f"{self.zev.name} [smoke]")
        self.assertEqual(event.metadata_json.get("flavour"), "smoke")

    def test_participant_is_refused(self):
        resp = self._create_job(user=self.participant_user)
        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_create_for_another_owners_zev(self):
        resp = self._create_job(zev=self.other_zev)
        self.assertEqual(resp.status_code, 403)

    def test_unknown_zev_is_404(self):
        resp = self._post(self.owner, {
            "export_type": "annual_statements",
            "zev_id": "00000000-0000-0000-0000-000000000000",
            "params": {"year": 2026},
        })
        self.assertEqual(resp.status_code, 404)

    def test_malformed_zev_id_is_404(self):
        """A malformed UUID in the body must answer 404, not surface Django's
        ValidationError as a 500."""
        resp = self._post(self.owner, {
            "export_type": "annual_statements",
            "zev_id": "not-a-uuid",
            "params": {"year": 2026},
        })
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["error"], "ZEV not found.")

    def test_anonymous_is_rejected(self):
        self.client.credentials()
        self.assertEqual(self.client.post(EXPORTS + "jobs/", {}, format="json").status_code, 401)

    def test_missing_and_unknown_fields_are_400(self):
        cases = [
            ({"zev_id": str(self.zev.pk), "params": {"year": 2026}}, "export_type is required."),
            ({"export_type": "annual_statements", "params": {"year": 2026}}, "zev_id is required."),
            ({"export_type": "annual_statements", "zev_id": str(self.zev.pk)}, "params is required."),
            ({"export_type": "bogus", "zev_id": str(self.zev.pk), "params": {"year": 2026}}, "Unknown export type."),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                resp = self._post(self.owner, payload)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.data["error"], message)

    def test_year_validation_matches_the_single_statement_contract(self):
        for year in (None, "not-a-year", 999999, -5, 0):
            params = {"year": year} if year is not None else {}
            resp = self._post(self.owner, {
                "export_type": "annual_statements", "zev_id": str(self.zev.pk), "params": params,
            })
            self.assertEqual(resp.status_code, 400, f"year={year}")
            self.assertIn("year", resp.data["error"])

    def test_zev_without_participants_for_that_year_is_400(self):
        resp = self._create_job(year=2020)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "No participants found for this ZEV and year.")


class ExportJobListTests(ExportJobApiTestCase):
    def test_owner_sees_only_their_own_jobs_newest_first(self):
        # Two jobs for the same ZEV need the first to finish: an in-flight job
        # is returned by a repeat request rather than duplicated.
        first = self._create_job().data["job"]
        first_job = ExportJob.objects.get(pk=first["id"])
        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            execute_export_job(str(first_job.pk))
        second = self._create_job().data["job"]
        self._create_job(user=self.other_owner, zev=self.other_zev)

        auth(self.client, self.owner)
        resp = self.client.get(EXPORTS + "jobs/")

        ids = [job["id"] for job in resp.data]
        self.assertEqual(ids, [second["id"], first["id"]])

    def test_requester_who_lost_ownership_no_longer_sees_the_jobs(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        self.zev.__class__.objects.filter(pk=self.zev.pk).update(owner=self.other_owner)

        auth(self.client, self.owner)
        resp = self.client.get(EXPORTS + "jobs/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

        # The job is the requester's, but the ZEV is no longer readable: the
        # status endpoint answers 403, matching the download endpoint.
        status_resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/")
        self.assertEqual(status_resp.status_code, 403)
        download_resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")
        self.assertEqual(download_resp.status_code, 403)

    def test_list_can_be_filtered_by_zev_and_export_type(self):
        job = self._create_job().data["job"]
        auth(self.client, self.owner)

        resp = self.client.get(EXPORTS + "jobs/", {"zev_id": str(self.zev.pk)})
        self.assertEqual([j["id"] for j in resp.data], [job["id"]])

        resp = self.client.get(EXPORTS + "jobs/", {"export_type": "bogus"})
        self.assertEqual(resp.data, [])

    def test_other_owners_and_participants_see_nothing(self):
        self._create_job()
        for user in (self.other_owner, self.participant_user):
            auth(self.client, user)
            resp = self.client.get(EXPORTS + "jobs/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.data, [])


class ExportJobRunnerTests(ExportJobApiTestCase):
    def test_running_job_claims_queued_rows_and_records_counts(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            outcome = execute_export_job(str(job.pk))

        self.assertEqual(outcome, {"generated_count": 2, "omitted_count": 0})
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)
        self.assertEqual(job.generated_count, 2)
        self.assertEqual(job.omitted_count, 0)
        self.assertIsNotNone(job.completed_at)
        self.assertIsNotNone(job.file_expires_at)
        self.assertTrue(job.result_file)
        self.assertTrue(job.result_file.storage.exists(job.result_file.name))
        event = AuditEvent.objects.get(action_type="annual_statement_export.completed", target_id=str(job.pk))
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.source, AuditEventSource.CELERY)
        self.assertEqual(event.actor_user, self.owner)

    def test_duplicate_delivery_never_renders_twice(self):
        """A task delivered twice must not render the same job twice: the
        second execution finds nothing queued and returns without calling the
        renderer."""
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            self.assertEqual(execute_export_job(str(job.pk))["generated_count"], 2)
            self.assertIsNone(execute_export_job(str(job.pk)))

        self.assertEqual(render.call_count, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)

    def test_partial_failure_publishes_a_zip_with_omitted_manifest(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(return_value=ExportResult(
            payload=b"ZIP-with-omissions", generated_count=1, omitted_ids=["omit-1"],
        ))
        with patcher:
            execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)
        self.assertEqual(job.generated_count, 1)
        self.assertEqual(job.omitted_count, 1)
        self.assertEqual(job.omitted_participant_ids, ["omit-1"])
        event = AuditEvent.objects.get(action_type="annual_statement_export.completed", target_id=str(job.pk))
        self.assertTrue(event.metadata_json["partial"])

    def test_soft_time_limit_never_publishes_a_completed_zip(self):
        """A soft time limit mid-batch must abort the whole run, not degrade
        it to a partial success: no ZIP is published even when earlier
        statements already rendered (the limit is recorded as a clean failure
        and re-raised for the worker)."""
        from billiard.exceptions import SoftTimeLimitExceeded

        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        calls = {"count": 0}

        def _generate(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] > 1:
                raise SoftTimeLimitExceeded()
            return b"PDF"

        with mock.patch(
            "invoices.annual_statement.generate_annual_statement_pdf", _generate,
        ):
            with self.assertRaises(SoftTimeLimitExceeded):
                execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertEqual(job.error_message, tasks_module._STALE_RUNNING_MESSAGE)
        self.assertFalse(job.result_file)
        self.assertFalse(
            AuditEvent.objects.filter(
                action_type="annual_statement_export.completed", target_id=str(job.pk),
            ).exists()
        )

    def test_all_statements_failing_marks_the_job_failed_without_a_download(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(
            side_effect=ExportNotPossibleError("Could not generate annual statements."),
        )
        with patcher:
            with self.assertRaises(ExportNotPossibleError):
                execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertEqual(job.error_message, "Could not generate annual statements.")
        self.assertFalse(job.result_file)
        event = AuditEvent.objects.get(action_type="annual_statement_export.failed", target_id=str(job.pk))
        self.assertEqual(event.status, AuditEventStatus.FAILED)

    def test_unexpected_render_failure_leaves_a_generic_message(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(side_effect=RuntimeError("boom"))
        with patcher:
            with self.assertRaises(RuntimeError):
                execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertEqual(job.error_message, "Could not generate the export.")

    def test_a_job_that_was_not_queued_is_left_alone(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        ExportJob.objects.filter(pk=job.pk).update(status=ExportJobStatus.FAILED)

        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            self.assertIsNone(execute_export_job(str(job.pk)))
        render.assert_not_called()

    def test_file_is_only_published_after_a_successful_save(self):
        """A storage failure while saving the ZIP leaves no file behind and
        marks the job failed."""
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(return_value=_default_result())
        from django.core.files.storage import default_storage

        with patcher, mock.patch.object(default_storage, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertFalse(job.result_file)
        self.assertEqual(job.error_message, "Could not generate the export.")

    def test_retention_window_starts_at_completion_not_claim(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            execute_export_job(str(job.pk))

        job.refresh_from_db()
        retention = timedelta(hours=int(getattr(settings, "EXPORT_RETENTION_HOURS", 24)))
        self.assertEqual(job.file_expires_at - job.completed_at, retention)

    def test_late_completion_never_resurrects_a_swept_failed_job(self):
        """A render that finishes after the sweep failed the job is discarded:
        the job stays failed, no file is published, no completion is recorded."""
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])

        def fail_while_rendering(job):
            # Simulate the sweep failing the job while its render runs on.
            ExportJob.objects.filter(pk=job.pk).update(
                status=ExportJobStatus.FAILED,
                error_message="The export did not finish. Prepare a new export to try again.",
            )
            return _default_result()

        render = mock.Mock(side_effect=fail_while_rendering)
        with mock.patch.object(
            exporters.EXPORT_DEFINITIONS["annual_statements"], "renderer", render,
        ):
            outcome = execute_export_job(str(job.pk))

        self.assertIsNone(outcome)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertTrue(job.error_message)
        self.assertFalse(job.result_file)
        self.assertFalse(
            AuditEvent.objects.filter(
                action_type="annual_statement_export.completed", target_id=str(job.pk),
            ).exists()
        )

    def test_run_export_job_task_carries_the_configured_time_limits(self):
        """The task must enforce the runner budget itself, not leave it to the
        sweep alone (ADR 0017)."""
        self.assertEqual(run_export_job.soft_time_limit, tasks_module._RUNNER_SOFT_LIMIT_S)
        self.assertEqual(run_export_job.time_limit, tasks_module._RUNNER_HARD_LIMIT_S)


class ExportJobDownloadTests(ExportJobApiTestCase):
    def _completed_job(self, payload=b"ZIP"):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        render, patcher = _stub_renderer(return_value=ExportResult(
            payload=payload, generated_count=2, omitted_ids=[],
        ))
        with patcher:
            execute_export_job(str(job.pk))
        return ExportJob.objects.get(pk=job.pk)

    def test_requester_downloads_the_completed_zip(self):
        job = self._completed_job()

        auth(self.client, self.owner)
        resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertIn('filename="annual-statements-2026.zip"', resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), b"ZIP")

    def test_not_ready_job_has_no_download(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        auth(self.client, self.owner)

        resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["error"], "Export is not ready.")

    def test_only_the_requester_can_download(self):
        job = self._completed_job()
        for user in (self.other_owner, self.participant_user):
            auth(self.client, user)
            resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")
            self.assertEqual(resp.status_code, 404)

    def test_status_shows_counts_and_expiry(self):
        job = self._completed_job()

        auth(self.client, self.owner)
        resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/")

        self.assertEqual(resp.data["status"], ExportJobStatus.COMPLETED)
        self.assertEqual(resp.data["generated_count"], 2)
        self.assertEqual(resp.data["omitted_count"], 0)
        self.assertFalse(resp.data["expired"])

    def test_expired_job_is_410_and_flagged_in_status(self):
        job = self._completed_job()
        ExportJob.objects.filter(pk=job.pk).update(
            file_expires_at=timezone.now() - timedelta(minutes=1),
        )

        auth(self.client, self.owner)
        status_resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/")
        self.assertTrue(status_resp.data["expired"])

        download_resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")
        self.assertEqual(download_resp.status_code, 410)

    def test_unknown_job_is_404(self):
        auth(self.client, self.owner)
        resp = self.client.get(f"{EXPORTS}jobs/{uuid.uuid4()}/download/")
        self.assertEqual(resp.status_code, 404)


class ExportJobSweepTests(ExportJobApiTestCase):
    def test_sweep_deletes_expired_files_but_keeps_metadata(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        render, patcher = _stub_renderer(return_value=_default_result())
        with patcher:
            execute_export_job(str(job.pk))
        job.refresh_from_db()
        stored_name = job.result_file.name
        self.assertTrue(job.result_file.storage.exists(stored_name))

        ExportJob.objects.filter(pk=job.pk).update(
            file_expires_at=timezone.now() - timedelta(minutes=1),
        )
        result = sweep_export_jobs_impl()

        job.refresh_from_db()
        self.assertEqual(result["files_deleted"], 1)
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)
        self.assertFalse(job.result_file)
        self.assertFalse(job.result_file.storage.exists(stored_name))

    def test_sweep_recovers_stale_running_and_lost_queued_jobs(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        running_cutoff = timedelta(
            seconds=tasks_module._RUNNER_HARD_LIMIT_S
            + tasks_module._SWEEP_RUNNING_GRACE_S
            + 1
        )
        ExportJob.objects.filter(pk=job.pk).update(
            status=ExportJobStatus.RUNNING,
            started_at=timezone.now() - running_cutoff,
        )
        # A different requester's ZEV so the in-flight dedupe does not return
        # the running job above.
        queued_job = ExportJob.objects.get(
            pk=self._create_job(user=self.other_owner, zev=self.other_zev).data["job"]["id"]
        )
        queued_cutoff = timedelta(
            seconds=tasks_module._SWEEP_QUEUED_CUTOFF_S + 1
        )
        ExportJob.objects.filter(pk=queued_job.pk).update(
            created_at=timezone.now() - queued_cutoff,
        )

        result = sweep_export_jobs_impl()

        self.assertEqual(result["stale_failed"], 2)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.FAILED)
        self.assertTrue(job.error_message)
        queued_job.refresh_from_db()
        self.assertEqual(queued_job.status, ExportJobStatus.FAILED)
        stale_events = [
            event for event in AuditEvent.objects.filter(
                action_type="annual_statement_export.failed",
            )
            if event.metadata_json.get("stale")
        ]
        self.assertEqual(len(stale_events), 2)

    def test_sweep_does_not_fail_a_stale_queued_job_claimed_during_the_sweep(self):
        """A worker that claims a stale queued job between the sweep's SELECT
        and its failure UPDATE wins: the job is a fresh ``running`` run and
        must not be marked failed by the sweep (which would audit a failure it
        did not actually cause)."""
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        queued_cutoff = timedelta(seconds=tasks_module._SWEEP_QUEUED_CUTOFF_S + 1)
        ExportJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - queued_cutoff,
        )

        real_mark_failed = tasks_module._mark_failed

        def claim_before_failing(job_row, message, **kwargs):
            # Simulate the worker claiming the job after the sweep selected it
            # as stale but before the failure write reaches the database.
            ExportJob.objects.filter(pk=job_row.pk).update(
                status=ExportJobStatus.RUNNING,
                started_at=timezone.now(),
            )
            return real_mark_failed(job_row, message, **kwargs)

        with mock.patch.object(tasks_module, "_mark_failed", side_effect=claim_before_failing):
            result = sweep_export_jobs_impl()

        job.refresh_from_db()
        self.assertEqual(result, {"files_deleted": 0, "stale_failed": 0})
        self.assertEqual(job.status, ExportJobStatus.RUNNING)
        self.assertFalse(job.error_message)
        self.assertFalse(
            AuditEvent.objects.filter(action_type="annual_statement_export.failed").exists()
        )

    def test_sweep_leaves_recently_queued_backlog_alone(self):
        """A queued job waiting behind a backlog must not be failed at the
        running-job cutoff: only the far longer queued window applies."""
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        # An hour old: past any running-job cutoff, well inside the queued
        # window.
        ExportJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(seconds=3600),
        )

        result = sweep_export_jobs_impl()

        self.assertEqual(result["stale_failed"], 0)
        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.QUEUED)

    def test_fresh_jobs_are_untouched(self):
        job = ExportJob.objects.get(pk=self._create_job().data["job"]["id"])
        result = sweep_export_jobs_impl()
        job.refresh_from_db()
        self.assertEqual(result, {"files_deleted": 0, "stale_failed": 0})
        self.assertEqual(job.status, ExportJobStatus.QUEUED)


class AnnualStatementExportBuilderTests(ExportJobApiTestCase):
    """ZIP entry naming rules (sanitization, pk suffix, UTF-8 byte budget)."""

    def _build(self, zev=None, year=2026, generate=None):
        from invoices.annual_statement_export import build_annual_statements_zip

        if generate is not None:
            patcher = mock.patch(
                "invoices.annual_statement.generate_annual_statement_pdf", generate
            )
        else:
            patcher = mock.patch(
                "invoices.annual_statement.generate_annual_statement_pdf",
                return_value=b"PDF",
            )
        with patcher:
            return build_annual_statements_zip(zev or self.zev, year)

    def test_zip_contains_one_entry_per_participant(self):
        make_participant(self.zev, first="Bea", last="Zweit")
        bytes_, generated, omitted = self._build()

        pia0 = self.zev.participants.get(first_name="Pia0")
        pia1 = self.zev.participants.get(first_name="Pia1")
        self.assertEqual(generated, [str(pia0.pk), str(pia1.pk),
                                     str(self.zev.participants.get(first_name="Bea").pk)])
        self.assertEqual(omitted, [])
        with zipfile.ZipFile(io.BytesIO(bytes_)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 3)
            self.assertTrue(all(name.startswith("annual-statement-2026-") for name in names))

    def test_zip_builds_shared_data_once(self):
        from allocation.read_model import (
            community_totals_by_timestamp,
            eligible_participant_shares,
        )
        from invoices.annual_statement_export import build_annual_statements_zip

        with ExitStack() as stack:
            stack.enter_context(mock.patch(
                "invoices.annual_statement.generate_annual_statement_pdf",
                return_value=b"PDF",
            ))
            build_shares = stack.enter_context(mock.patch(
                "invoices.annual_statement_export.eligible_participant_shares",
                wraps=eligible_participant_shares,
            ))
            build_totals = stack.enter_context(mock.patch(
                "invoices.annual_statement_export.community_totals_by_timestamp",
                wraps=community_totals_by_timestamp,
            ))
            build_annual_statements_zip(self.zev, 2026)

        build_shares.assert_called_once()
        build_totals.assert_called_once()

    def test_zip_omits_only_failed_statements_and_names_them(self):
        for index in range(3):
            make_participant(self.zev, first=f"Extra{index}", last=f"Zed{index}")
        participants = list(self.zev.participants.order_by("last_name", "first_name"))
        failed_pk = participants[1].pk

        def _generate(participant, *args, **kwargs):
            if participant.pk == failed_pk:
                raise ValueError("render failed")
            return str(participants.index(participant)).encode()

        bytes_, generated, omitted = self._build(generate=_generate)

        self.assertNotIn(str(failed_pk), generated)
        self.assertEqual(omitted, [str(failed_pk)])
        with zipfile.ZipFile(io.BytesIO(bytes_)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), len(participants))  # 3 PDFs + omitted.txt
            manifest = archive.read("omitted.txt").decode()
            self.assertIn(str(failed_pk), manifest)
            self.assertIn(f"{participants[1].last_name}, {participants[1].first_name}", manifest)

    def test_soft_time_limit_aborts_the_batch_instead_of_omitting_participants(self):
        """A soft time limit inside one participant's render must abort the
        whole export, not be recorded as that participant's failure and keep
        rendering toward a published ZIP."""
        from billiard.exceptions import SoftTimeLimitExceeded
        from invoices.annual_statement_export import build_annual_statements_zip

        def _generate(participant, *args, **kwargs):
            raise SoftTimeLimitExceeded()

        with mock.patch("invoices.annual_statement.generate_annual_statement_pdf", _generate):
            with self.assertRaises(SoftTimeLimitExceeded):
                build_annual_statements_zip(self.zev, 2026)

    def test_soft_time_limit_during_shared_data_calculation_propagates(self):
        """The shared yearly-data phase must propagate a soft time limit too,
        instead of repackaging it as an all-failed export error."""
        from billiard.exceptions import SoftTimeLimitExceeded
        from invoices.annual_statement_export import build_annual_statements_zip

        with mock.patch(
            "invoices.annual_statement_export.eligible_participant_shares",
            side_effect=SoftTimeLimitExceeded,
        ):
            with self.assertRaises(SoftTimeLimitExceeded):
                build_annual_statements_zip(self.zev, 2026)

    def test_all_failed_statements_never_publish_a_zip(self):
        from invoices.annual_statement_export import (
            AnnualStatementExportError,
            build_annual_statements_zip,
        )

        def _generate(participant, *args, **kwargs):
            raise ValueError("render failed")

        with mock.patch("invoices.annual_statement.generate_annual_statement_pdf", _generate):
            with self.assertRaises(AnnualStatementExportError):
                build_annual_statements_zip(self.zev, 2026)

    def test_zev_without_participants_for_the_year_raises(self):
        from invoices.annual_statement_export import (
            AnnualStatementExportError,
            build_annual_statements_zip,
        )
        with mock.patch("invoices.annual_statement.generate_annual_statement_pdf") as render:
            with self.assertRaises(AnnualStatementExportError):
                build_annual_statements_zip(self.zev, 2020)
        render.assert_not_called()

    def test_zip_names_fit_filesystem_limits_for_maximum_length_names(self):
        from invoices.annual_statement_export import (
            _ZIP_ENTRY_BYTE_BUDGET,
            _annual_statement_zip_name,
        )

        participant = make_participant(self.zev, first="F" * 100, last="L" * 100)
        name = _annual_statement_zip_name(participant, 2026)

        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)
        self.assertNotIn(str(participant.pk), name)
        self.assertTrue(name.startswith("annual-statement-2026-"))
        self.assertTrue(name.endswith(".pdf"))

    def test_zip_names_replace_windows_invalid_and_control_characters(self):
        from invoices.annual_statement_export import (
            _ZIP_ENTRY_BYTE_BUDGET,
            _annual_statement_zip_name,
        )

        participant = make_participant(self.zev, first='A"B', last="C<>D\x01E|F?G*H")
        name = _annual_statement_zip_name(participant, 2026)

        for character in '<>:"/\\|?*\x01':
            self.assertNotIn(character, name)
        self.assertNotIn(str(participant.pk), name)
        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)

    def test_zip_names_truncate_multibyte_names_on_character_boundaries(self):
        from invoices.annual_statement_export import (
            _ZIP_ENTRY_BYTE_BUDGET,
            _annual_statement_zip_name,
        )

        participant = make_participant(self.zev, first="ü" * 100, last="ö" * 100)
        name = _annual_statement_zip_name(participant, 2026)

        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)
        self.assertNotIn(str(participant.pk), name)

    def test_zip_names_disambiguate_only_duplicate_names_with_pk(self):
        from invoices.annual_statement_export import (
            _ZIP_ENTRY_BYTE_BUDGET,
            _annual_statement_zip_names,
        )

        twin_a = make_participant(self.zev, first="Hans", last="Muster")
        twin_b = make_participant(self.zev, first="Hans", last="Muster")
        solo = make_participant(self.zev, first="Bea", last="Zweit")
        names = _annual_statement_zip_names([twin_a, twin_b, solo], 2026)

        self.assertNotEqual(names[twin_a.pk], names[twin_b.pk])
        self.assertIn(str(twin_a.pk), names[twin_a.pk])
        self.assertIn(str(twin_b.pk), names[twin_b.pk])
        self.assertNotIn(str(solo.pk), names[solo.pk])
        self.assertEqual(len(set(names.values())), 3)
        for name in names.values():
            self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)

    def test_zip_names_guard_against_secondary_collisions_with_suffixed_names(self):
        """A readable name that mimics another entry's pk-suffixed name must
        not share it: the final uniqueness guard appends the mimic's own pk."""
        from invoices.annual_statement_export import _ZIP_ENTRY_BYTE_BUDGET

        twin_a = make_participant(self.zev, first="Hans", last="Muster")
        make_participant(self.zev, first="Hans", last="Muster")
        mimic = make_participant(self.zev, first=f"Hans-{twin_a.pk}", last="Muster")

        bytes_, generated, omitted = self._build()

        self.assertEqual(omitted, [])
        with zipfile.ZipFile(io.BytesIO(bytes_)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), len(set(names)))
            mimic_names = [name for name in names if str(mimic.pk) in name]
            self.assertEqual(len(mimic_names), 1)
            self.assertIn(str(twin_a.pk), mimic_names[0])
            for name in names:
                self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)

    def test_end_to_end_job_download_roundtrip(self):
        """One render path through the executor with the real builder and a
        stubbed PDF boundary: the stored artifact downloads back intact."""
        job_id = self._create_job().data["job"]["id"]
        with mock.patch("invoices.annual_statement.generate_annual_statement_pdf",
                        return_value=b"%PDF-1.7\nstmt\n%%EOF\n"):
            execute_export_job(job_id)

        job = ExportJob.objects.get(pk=job_id)
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)
        auth(self.client, self.owner)
        resp = self.client.get(f"{EXPORTS}jobs/{job.pk}/download/")
        self.assertEqual(resp.status_code, 200)
        content = b"".join(resp.streaming_content)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            self.assertTrue(all(archive.read(name).startswith(b"%PDF-") for name in names))


class AnnualStatementExportRealRenderTests(TestCase):
    """Slow end-to-end run with the real WeasyPrint pipeline.

    Replaces the subprocess-worker e2e test: with export jobs the render runs
    in the Celery worker's process, so an in-process run exercises the real
    path. Marked slow — excluded by the default ``-m "not slow"`` run.
    """

    def setUp(self):
        self.owner = make_user("exp_e2e_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "E2E ZEV")
        for index in range(3):
            make_participant(self.zev, first=f"Extra{index}", last=f"Zed{index}")

    @pytest.mark.slow
    def test_real_render_completes_the_job(self):
        job = ExportJob.objects.create(
            export_type="annual_statements",
            zev=self.zev,
            requester=self.owner,
            params={"year": 2026},
        )
        outcome = execute_export_job(str(job.pk))

        job.refresh_from_db()
        self.assertEqual(job.status, ExportJobStatus.COMPLETED)
        self.assertEqual(outcome, {"generated_count": 3, "omitted_count": 0})
        self.assertTrue(job.result_file)
        with job.result_file.open("rb") as handle:
            with zipfile.ZipFile(handle) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), 3)
                self.assertTrue(all(archive.read(name).startswith(b"%PDF-") for name in names))
        self.assertTrue(
            AuditEvent.objects.filter(action_type="annual_statement_export.completed").exists()
        )
