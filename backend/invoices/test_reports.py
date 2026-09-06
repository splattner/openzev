"""Coverage for the annual statement and financial summary report endpoints.

``annual-statement`` and ``annual-statements-zip`` had no backend tests at all
before this module; ``financial-summary`` had four, in ``tests.py``, all of them
happy-path. Since all three resolve a ZEV and a participant from query
parameters and decide access from that, the untested half was mostly the
boundary: cross-tenant reads, self-service, and malformed input.
"""

import io
import os
import subprocess
import sys
import zipfile
from contextlib import ExitStack
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import UserRole
from allocation.read_model import (
    community_totals_by_timestamp,
    eligible_participant_shares,
)
from testing.helpers import authenticate as auth, make_user
from zev.models import Participant

from .test_helpers import make_participant, make_zev

ANNUAL_STATEMENT = "/api/v1/invoices/invoices/annual-statement/"
STATEMENTS_ZIP = "/api/v1/invoices/invoices/annual-statements-zip/"
FINANCIAL_SUMMARY = "/api/v1/invoices/invoices/financial-summary/"


class ReportTestCase(TestCase):
    """Two ZEVs under different owners, so cross-tenant reads are testable."""

    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("rpt_admin", UserRole.ADMIN)

        self.owner = make_user("rpt_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Report ZEV")
        self.puser = make_user("rpt_participant", UserRole.PARTICIPANT)
        self.participant = make_participant(self.zev, user=self.puser, first="Pia", last="Muster")

        self.other_owner = make_user("rpt_other_owner", UserRole.ZEV_OWNER)
        self.other_zev = make_zev(self.other_owner, "Other ZEV")
        self.other_participant = make_participant(self.other_zev, first="Otto", last="Fremd")

    def _get(self, url, user, **params):
        auth(self.client, user)
        return self.client.get(url, params)


class AnnualStatementTests(ReportTestCase):
    def test_admin_can_read_any_zev(self):
        resp = self._get(ANNUAL_STATEMENT, self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("annual-statement-2026-Muster.pdf", resp["Content-Disposition"])
        self.assertTrue(resp["Content-Disposition"].startswith("inline"))

    def test_owner_can_read_own_zev(self):
        resp = self._get(ANNUAL_STATEMENT, self.owner, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 200)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(ANNUAL_STATEMENT, self.owner, year=2026, zev_id=str(self.other_zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 403)

    def test_participant_gets_their_own_without_naming_ids(self):
        """A participant never passes zev_id/participant_id; the ids they *do*
        pass are ignored, so they cannot request someone else's statement."""
        resp = self._get(ANNUAL_STATEMENT, self.puser, year=2026,
                         zev_id=str(self.other_zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertIn("annual-statement-2026-Muster.pdf", resp["Content-Disposition"])

    def test_participant_without_a_record_is_404(self):
        resp = self._get(ANNUAL_STATEMENT, make_user("rpt_orphan", UserRole.PARTICIPANT), year=2026)

        self.assertEqual(resp.status_code, 404)

    def test_year_is_required_and_must_be_numeric(self):
        missing = self._get(ANNUAL_STATEMENT, self.admin, zev_id=str(self.zev.pk), participant_id=str(self.participant.pk))
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.data["error"], "year is required.")

        bad = self._get(ANNUAL_STATEMENT, self.admin, year="not-a-year", zev_id=str(self.zev.pk),
                        participant_id=str(self.participant.pk))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.data["error"], "year must be a number.")

    def test_owner_must_name_both_ids(self):
        resp = self._get(ANNUAL_STATEMENT, self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "participant_id and zev_id are required.")

    def test_unknown_zev_is_404(self):
        resp = self._get(ANNUAL_STATEMENT, self.admin, year=2026, zev_id="00000000-0000-0000-0000-000000000000",
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participant_from_another_zev_is_404(self):
        """The participant lookup is scoped to the resolved ZEV, so naming a
        valid participant of a different ZEV must not leak their statement."""
        resp = self._get(ANNUAL_STATEMENT, self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_anonymous_is_rejected(self):
        self.client.credentials()

        self.assertEqual(self.client.get(ANNUAL_STATEMENT, {"year": 2026}).status_code, 401)


class AnnualStatementsZipTests(ReportTestCase):
    def test_owner_downloads_a_zip_of_every_participant(self):
        bea = make_participant(self.zev, first="Bea", last="Zweit")

        resp = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertIn("annual-statements-2026.zip", resp["Content-Disposition"])
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        self.assertEqual(
            sorted(names),
            [
                f"annual-statement-2026-Muster_Pia-{self.participant.pk}.pdf",
                f"annual-statement-2026-Zweit_Bea-{bea.pk}.pdf",
            ],
        )

    def test_zip_builds_participant_shares_once_for_every_statement(self):
        make_participant(self.zev, first="Bea", last="Zweit")

        with (
            mock.patch(
                "invoices.views_reports.eligible_participant_shares",
                wraps=eligible_participant_shares,
            ) as build_shares,
            mock.patch(
                "invoices.views_reports.community_totals_by_timestamp",
                wraps=community_totals_by_timestamp,
            ) as build_totals,
            mock.patch(
                "invoices.views_reports.generate_annual_statement_pdf",
                return_value=b"PDF",
            ) as generate_statement,
        ):
            resp = self._get(
                STATEMENTS_ZIP,
                self.owner,
                year=2026,
                zev_id=str(self.zev.pk),
            )

        self.assertEqual(resp.status_code, 200)
        build_shares.assert_called_once()
        build_totals.assert_called_once()
        self.assertEqual(generate_statement.call_count, 2)
        shares_by_date = generate_statement.call_args_list[0].kwargs["shares_by_date"]
        self.assertTrue(
            all(
                call.kwargs["shares_by_date"] is shares_by_date
                for call in generate_statement.call_args_list
            )
        )
        zev_totals_by_ts = generate_statement.call_args_list[0].kwargs["zev_totals_by_ts"]
        self.assertTrue(
            all(
                call.kwargs["zev_totals_by_ts"] is zev_totals_by_ts
                for call in generate_statement.call_args_list
            )
        )

    def test_zip_returns_500_when_shared_participant_calculation_fails(self):
        with (
            mock.patch(
                "invoices.views_reports.eligible_participant_shares",
                side_effect=ValueError("invalid shared data"),
            ) as build_shares,
            mock.patch(
                "invoices.views_reports.generate_annual_statement_pdf",
            ) as generate_statement,
        ):
            resp = self._get(
                STATEMENTS_ZIP,
                self.owner,
                year=2026,
                zev_id=str(self.zev.pk),
            )

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {"error": "Could not generate annual statements."})
        build_shares.assert_called_once()
        generate_statement.assert_not_called()

    def test_zip_omits_only_failed_statement(self):
        """Both render paths omit exactly the failed statement and name it in
        ``omitted.txt`` (ID plus human-readable name)."""
        for index in range(3):
            make_participant(self.zev, first="Extra", last=f"Zed{index}")
        participants = list(self.zev.participants.order_by("last_name", "first_name"))
        failed_pk = participants[1].pk
        expected_names = [
            f"annual-statement-2026-Muster_Pia-{participants[0].pk}.pdf",
            f"annual-statement-2026-Zed1_Extra-{participants[2].pk}.pdf",
            f"annual-statement-2026-Zed2_Extra-{participants[3].pk}.pdf",
            "omitted.txt",
        ]

        def _generate(participant, zev, year, **kwargs):
            if participant.pk == failed_pk:
                raise ValueError("render failed")
            return str(participants.index(participant)).encode()

        results = [
            (participant.pk, None, "render failed") if participant.pk == failed_pk
            else (participant.pk, str(index).encode(), None)
            for index, participant in enumerate(participants)
        ]
        for path in ("serial", "parallel"):
            with self.subTest(path=path):
                with ExitStack() as stack:
                    if path == "serial":
                        # One worker forces the serial path through the real gate.
                        stack.enter_context(override_settings(PDF_POOL_MAX_WORKERS=1))
                        stack.enter_context(
                            mock.patch(
                                "invoices.views_reports.generate_annual_statement_pdf",
                                side_effect=_generate,
                            )
                        )
                        serial = None
                    else:
                        stack.enter_context(
                            mock.patch(
                                "invoices.pdf_pool.render_statements_parallel",
                                return_value=results,
                            )
                        )
                        serial = stack.enter_context(
                            mock.patch("invoices.views_reports.generate_annual_statement_pdf")
                        )
                    response = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))
                if path == "parallel":
                    serial.assert_not_called()
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    self.assertEqual(archive.namelist(), expected_names)
                    self.assertEqual(
                        [archive.read(name) for name in archive.namelist()[:3]], [b"0", b"2", b"3"],
                    )
                    # The manifest must name exactly the omitted participant, with a
                    # human-readable name alongside the machine-readable ID.
                    manifest = archive.read("omitted.txt").decode()
                    self.assertIn(str(participants[1].pk), manifest)
                    self.assertIn(f"{participants[1].last_name}, {participants[1].first_name}", manifest)
                    self.assertNotIn(str(participants[0].pk), manifest)

    def test_parallel_zip_returns_500_when_every_statement_fails(self):
        """A fully failed export must be distinguishable from a successful
        (even partial) one, so it cannot return an empty ZIP with status 200."""
        make_participant(self.zev, first="Bea", last="Zweit")
        participants = list(self.zev.participants.order_by("last_name", "first_name"))
        results = [
            (participant.pk, None, "render failed")
            for participant in participants
        ]
        with (
            mock.patch("invoices.pdf_pool.render_statements_parallel", return_value=results),
            mock.patch("invoices.views_reports.generate_annual_statement_pdf") as serial,
        ):
            response = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "Could not generate annual statements."})
        serial.assert_not_called()

    def test_serial_zip_returns_500_when_every_statement_fails(self):
        """The serial path shares the complete-failure rule."""
        make_participant(self.zev, first="Bea", last="Zweit")
        with (
            mock.patch("invoices.pdf_pool.render_statements_parallel", return_value=None),
            mock.patch(
                "invoices.views_reports.generate_annual_statement_pdf",
                side_effect=ValueError("template rejected"),
            ),
        ):
            response = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "Could not generate annual statements."})

    def test_parallel_crash_returns_500_without_serial_generation(self):
        """A crashed worker (or a deterministic calculation error) fails fast
        instead of rerunning the batch inside the API process: retrying a
        document that crashed a child could take down this process, and a
        late failure leaves no budget for a second full batch."""
        from invoices import pdf_pool

        for i in range(5):
            make_participant(self.zev, first=f"Extra{i}", last=f"Viel{i}")

        for exc in (
            RuntimeError("PDF worker exited with status 3"),
            OSError("PDF worker spawn failed"),
            RuntimeError("deterministic calculation error"),
        ):
            with (
                self.subTest(exc=exc),
                mock.patch.object(
                    pdf_pool,
                    "render_statements_parallel",
                    side_effect=exc,
                ),
                mock.patch(
                    "invoices.views_reports.generate_annual_statement_pdf",
                ) as generate_statement,
            ):
                resp = self._get(
                    STATEMENTS_ZIP,
                    self.owner,
                    year=2026,
                    zev_id=str(self.zev.pk),
                )

            self.assertEqual(resp.status_code, 500)
            self.assertEqual(resp.json(), {"error": "Could not generate annual statements."})
            generate_statement.assert_not_called()

    def test_parallel_timeout_returns_500_without_serial_generation(self):
        from invoices import pdf_pool

        for i in range(5):
            make_participant(self.zev, first=f"Extra{i}", last=f"Viel{i}")

        with mock.patch.object(
            pdf_pool,
            "render_statements_parallel",
            side_effect=TimeoutError("statement batch deadline exceeded"),
        ), mock.patch(
            "invoices.views_reports.generate_annual_statement_pdf",
        ) as generate_statement:
            resp = self._get(
                STATEMENTS_ZIP,
                self.owner,
                year=2026,
                zev_id=str(self.zev.pk),
            )

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {"error": "Could not generate annual statements."})
        generate_statement.assert_not_called()

    def test_participant_is_refused(self):
        resp = self._get(STATEMENTS_ZIP, self.puser, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.other_zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_year_and_zev_id_are_both_required(self):
        for params in ({"year": 2026}, {"zev_id": "x"}):
            with self.subTest(params=params):
                resp = self._get(STATEMENTS_ZIP, self.owner, **params)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.data["error"], "year and zev_id are required.")

    def test_zev_without_participants_for_that_year_is_404(self):
        """Participants are filtered by validity window, so a year before the
        ZEV had anyone yields 404 rather than an empty archive."""
        resp = self._get(STATEMENTS_ZIP, self.owner, year=2020, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participants_who_left_before_the_year_are_excluded(self):
        Participant.objects.filter(pk=self.participant.pk).update(valid_to=date(2024, 6, 30))

        resp = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 404)

    def test_zip_names_fit_filesystem_limits_for_maximum_length_names(self):
        """Two 100-char names plus the UUID previously produced a 264-byte
        entry that failed to extract; only the readable portion is truncated
        and the pk is always kept."""
        from .views_reports import _ZIP_ENTRY_BYTE_BUDGET, _annual_statement_zip_name

        long_last = "L" * 100
        long_first = "F" * 100
        participant = make_participant(self.zev, first=long_first, last=long_last)

        name = _annual_statement_zip_name(participant, 2026)

        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)
        self.assertIn(str(participant.pk), name)
        self.assertTrue(name.startswith("annual-statement-2026-"))
        self.assertTrue(name.endswith(f"-{participant.pk}.pdf"))

    def test_zip_names_replace_windows_invalid_and_control_characters(self):
        from .views_reports import _ZIP_ENTRY_BYTE_BUDGET, _annual_statement_zip_name

        participant = make_participant(self.zev, first='A"B', last="C<>D\x01E|F?G*H")

        name = _annual_statement_zip_name(participant, 2026)

        for character in '<>:"/\\|?*\x01':
            self.assertNotIn(character, name)
        self.assertIn(str(participant.pk), name)
        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)

    def test_zip_names_truncate_multibyte_names_on_character_boundaries(self):
        from .views_reports import _ZIP_ENTRY_BYTE_BUDGET, _annual_statement_zip_name

        participant = make_participant(self.zev, first="ü" * 100, last="ö" * 100)

        name = _annual_statement_zip_name(participant, 2026)

        self.assertLessEqual(len(name.encode("utf-8")), _ZIP_ENTRY_BYTE_BUDGET)
        self.assertIn(str(participant.pk), name)
        # Re-encoding must round-trip: no split multibyte sequence.
        name.encode("utf-8").decode("utf-8")

    def test_zip_with_maximum_length_names_extracts(self):
        participant = make_participant(self.zev, first="F" * 100, last="L" * 100)

        with mock.patch(
            "invoices.views_reports.generate_annual_statement_pdf",
            return_value=b"PDF",
        ):
            resp = self._get(STATEMENTS_ZIP, self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            for entry in names:
                self.assertLessEqual(len(entry.encode("utf-8")), 255)
                archive.read(entry)
            self.assertTrue(any(str(participant.pk) in entry for entry in names))

    @pytest.mark.slow
    @pytest.mark.integration
    def test_zip_renders_end_to_end_in_worker_subprocesses(self):
        """No render mocks and a file-backed database, so the four-participant
        batch exercises the real statement pipeline through the parallel path:
        with two CPUs and two pinned workers, two PDF workers must spawn. A
        serial fallback fails instead of passing silently. Subprocesses cannot
        share the TestCase database, hence the self-contained child run."""
        import json as jsonlib
        import tempfile
        import textwrap

        script = textwrap.dedent("""
            import io, json, subprocess, zipfile
            import django
            django.setup()
            from django.core.management import call_command
            call_command("migrate", verbosity=0, interactive=False)
            from rest_framework.test import APIClient
            from accounts.models import UserRole
            from testing.helpers import make_user
            from invoices.test_helpers import make_participant, make_zev

            owner = make_user("zip_e2e_owner", UserRole.ZEV_OWNER)
            zev = make_zev(owner, "ZIP E2E ZEV")
            for index in range(4):
                make_participant(zev, first="Extra", last=f"Zed{index}")
            client = APIClient()
            from testing.helpers import authenticate as auth
            auth(client, owner)

            spawned = []
            real_popen = subprocess.Popen

            def observed_popen(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                command = args[0] if args else kwargs.get("args")
                if (isinstance(command, (list, tuple))
                        and "invoices.pdf_worker" in command):
                    spawned.append(process.pid)
                return process

            subprocess.Popen = observed_popen
            try:
                resp = client.get(
                    "/api/v1/invoices/invoices/annual-statements-zip/",
                    {"year": 2026, "zev_id": str(zev.pk)},
                )
                assert resp.status_code == 200, resp.content[:500]
                with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
                    names = archive.namelist()
                    assert len(names) == 4, names
                    assert "omitted.txt" not in names
                    assert all(archive.read(n).startswith(b"%PDF-") for n in names)
            finally:
                subprocess.Popen = real_popen
            print(json.dumps({"documents": len(names), "workers_spawned": len(spawned)}))
        """)
        with tempfile.TemporaryDirectory(prefix="zip-e2e-") as tmp:
            environment = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings_test",
                "DATABASE_URL": f"sqlite:///{tmp}/e2e.sqlite3",
                "MEDIA_ROOT": f"{tmp}/media",
                "SECRET_KEY": "isolated-zip-e2e-test-key",
                "ALLOWED_HOSTS": "testserver,localhost",
                # Pin the child to two CPUs and two workers so the assertion
                # holds on any host, from one CPU upward.
                "PYTHON_CPU_COUNT": "2",
                "PDF_POOL_MAX_WORKERS": "2",
            }
            child = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=environment, capture_output=True, text=True, timeout=300,
            )
        assert child.returncode == 0, child.stderr[-2000:]
        payload = jsonlib.loads(child.stdout.strip().splitlines()[-1])
        assert payload == {"documents": 4, "workers_spawned": 2}


class FinancialSummaryTests(ReportTestCase):
    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(FINANCIAL_SUMMARY, self.owner, year=2026, zev_id=str(self.other_zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_zev_id_is_required_for_an_owner(self):
        resp = self._get(FINANCIAL_SUMMARY, self.owner, year=2026)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "zev_id is required.")

    def test_without_participant_id_it_falls_back_to_the_zev_owner(self):
        """An admin naming only the ZEV gets the owner's record, since the
        admin has none of their own in it."""
        owner_participant = make_participant(self.zev, user=self.owner, first="Olga", last="Wirt")

        resp = self._get(FINANCIAL_SUMMARY, self.admin, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"financial-summary-2026-{owner_participant.last_name}.pdf",
                      resp["Content-Disposition"])

    def test_without_any_default_participant_it_is_400(self):
        resp = self._get(FINANCIAL_SUMMARY, self.admin, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "participant_id is required (no default participant found).")

    def test_participant_from_another_zev_is_404(self):
        resp = self._get(FINANCIAL_SUMMARY, self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participant_ignores_supplied_ids_and_gets_their_own(self):
        resp = self._get(FINANCIAL_SUMMARY, self.puser, year=2026, zev_id=str(self.other_zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertIn("financial-summary-2026-Muster.pdf", resp["Content-Disposition"])


class MalformedInputTests(ReportTestCase):
    """Malformed ids and out-of-range years used to raise uncaught exceptions.

    All of these are reachable by any authenticated user through a query
    parameter, so they were crashes on untrusted input rather than exotic edge
    cases: a malformed UUID raised ValidationError past the DoesNotExist
    handler, and an out-of-range year raised ValueError from date(year, 1, 1)
    deep inside PDF generation.
    """

    def test_malformed_zev_id_is_404(self):
        for url in (ANNUAL_STATEMENT, STATEMENTS_ZIP, FINANCIAL_SUMMARY):
            with self.subTest(url=url):
                resp = self._get(url, self.admin, year=2026, zev_id="not-a-uuid",
                                 participant_id=str(self.participant.pk))
                self.assertEqual(resp.status_code, 404)

    def test_malformed_participant_id_is_404(self):
        for url in (ANNUAL_STATEMENT, FINANCIAL_SUMMARY):
            with self.subTest(url=url):
                resp = self._get(url, self.admin, year=2026, zev_id=str(self.zev.pk),
                                 participant_id="not-a-uuid")
                self.assertEqual(resp.status_code, 404)

    def test_year_is_validated_before_the_zev_is_authorised(self):
        """Ordering change from the crash fix: the range check lives with the
        year parse, which runs before the ZEV is fetched. A caller who is not
        entitled to the ZEV *and* passes a bad year now gets 400 rather than
        403 — which also stops the response confirming the ZEV exists."""
        auth(self.client, self.other_owner)

        resp = self.client.get(ANNUAL_STATEMENT, {
            "year": "999999", "zev_id": str(self.zev.pk), "participant_id": str(self.participant.pk),
        })

        self.assertEqual(resp.status_code, 400)

    def test_a_valid_year_still_yields_403_for_an_unauthorised_zev(self):
        auth(self.client, self.other_owner)

        resp = self.client.get(ANNUAL_STATEMENT, {
            "year": "2026", "zev_id": str(self.zev.pk), "participant_id": str(self.participant.pk),
        })

        self.assertEqual(resp.status_code, 403)

    def test_out_of_range_year_is_400(self):
        for year in ("999999", "-5", "0"):
            with self.subTest(year=year):
                resp = self._get(ANNUAL_STATEMENT, self.admin, year=year,
                                 zev_id=str(self.zev.pk), participant_id=str(self.participant.pk))
                self.assertEqual(resp.status_code, 400)


class AnnualStatementMonthlyDataTests(TestCase):
    """``_compute_monthly_data`` attributes readings per timestamp (ADR 0013):
    a mid-year assignment transfer must not leak readings across holders."""

    def setUp(self):
        self.owner = make_user("as_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Annual ZEV")
        self.participant = make_participant(self.zev, first="Pia", last="Muster")
        from invoices.annual_statement import ANNUAL_TRANSLATIONS
        self.tr = ANNUAL_TRANSLATIONS["de"]

    def test_readings_before_the_assignment_start_are_excluded(self):
        from invoices.annual_statement import _compute_monthly_data
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

        # Assignment only from Feb 1 — the January readings belong to nobody
        # for this participant.
        mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH00000000000000000000000000REP01",
            meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=self.participant,
            valid_from=date(2026, 2, 1), valid_to=None)
        for day in (date(2026, 1, 15), date(2026, 2, 15)):
            MeterReading.objects.create(
                metering_point=mp,
                timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc),
                energy_kwh=Decimal("4"), direction=ReadingDirection.IN,
                resolution=ReadingResolution.DAILY,
            )
        # Community production so January's excluded reading would be local if
        # it leaked through.
        prod_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH00000000000000000000000000REP02",
            meter_type=MeteringPointType.PRODUCTION)
        MeteringPointAssignment.objects.create(
            metering_point=prod_mp, participant=self.participant,
            valid_from=date(2026, 2, 1), valid_to=None)
        for day in (date(2026, 1, 15), date(2026, 2, 15)):
            MeterReading.objects.create(
                metering_point=prod_mp,
                timestamp=datetime(day.year, day.month, day.day, 12, 0, tzinfo=dt_timezone.utc),
                energy_kwh=Decimal("10"), direction=ReadingDirection.OUT,
                resolution=ReadingResolution.DAILY,
            )

        monthly, _totals = _compute_monthly_data(
            self.participant, self.zev, 2026, self.tr)

        jan = monthly[0]
        feb = monthly[1]
        # January must be empty for this participant despite the readings.
        self.assertEqual(jan["consumed_kwh"], "0.00")
        self.assertEqual(jan["from_zev_kwh"], "0.00")
        # February shows the post-assignment reading, fully local.
        self.assertEqual(feb["consumed_kwh"], "4.00")
        self.assertEqual(feb["from_zev_kwh"], "4.00")

    def test_community_meter_contributes_only_the_participants_weighted_share(self):
        """A community meter this participant does not literally hold must
        still reach their statement, at their weighted share — not zero
        (they're not the holder) and not the full reading (they'd be
        double-counted against the holder's own share).

        Shared metering points, docs/specs/2026-08-shared-metering-points.md
        §7.7: broadens the fetch beyond this participant's own assignments,
        and replaces the literal is_held_by gate with a mode-aware one.
        """
        from invoices.annual_statement import _compute_monthly_data
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType

        holder = make_participant(self.zev, first="Hans", last="Halter")
        self.participant.allocation_weight = Decimal("1")
        self.participant.save(update_fields=["allocation_weight"])
        holder.allocation_weight = Decimal("3")
        holder.save(update_fields=["allocation_weight"])

        community_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH00000000000000000000000000REP03",
            meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=community_mp, participant=holder,
            valid_from=date(2026, 1, 1), allocation_mode=AllocationMode.COMMUNITY,
        )
        MeterReading.objects.create(
            metering_point=community_mp,
            timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal("8"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.DAILY,
        )

        monthly, _totals = _compute_monthly_data(self.participant, self.zev, 2026, self.tr)

        # Weight 1 of 4 total (1 + 3): this participant's share is 8 * 1/4 = 2.
        self.assertEqual(monthly[0]["consumed_kwh"], "2.00")

    def test_community_holder_is_not_double_billed_alongside_their_share(self):
        """The literal holder of a community meter must be billed only their
        own weighted share, not the full reading on top of it — the
        double-counting bug the original spec draft had (§7.3's fix, applied
        here via the mode-aware gate)."""
        from invoices.annual_statement import _compute_monthly_data
        from metering.models import MeterReading, ReadingDirection, ReadingResolution
        from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType

        other = make_participant(self.zev, first="Otto", last="Other")
        self.participant.allocation_weight = Decimal("3")
        self.participant.save(update_fields=["allocation_weight"])
        other.allocation_weight = Decimal("1")
        other.save(update_fields=["allocation_weight"])

        community_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH00000000000000000000000000REP04",
            meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(
            metering_point=community_mp, participant=self.participant,
            valid_from=date(2026, 1, 1), allocation_mode=AllocationMode.COMMUNITY,
        )
        MeterReading.objects.create(
            metering_point=community_mp,
            timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc),
            energy_kwh=Decimal("8"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.DAILY,
        )

        monthly, _totals = _compute_monthly_data(self.participant, self.zev, 2026, self.tr)

        # Weight 3 of 4 total: the holder's own share is 8 * 3/4 = 6, not 8.
        self.assertEqual(monthly[0]["consumed_kwh"], "6.00")
