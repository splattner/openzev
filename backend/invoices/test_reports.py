"""Coverage for the annual statement and financial summary report endpoints.

``annual-statement`` and ``annual-statements-zip`` had no backend tests at all
before this module; ``financial-summary`` had four, in ``tests.py``, all of them
happy-path. Since all three resolve a ZEV and a participant from query
parameters and decide access from that, the untested half was mostly the
boundary: cross-tenant reads, self-service, and malformed input.
"""

import io
import zipfile
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
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


class AnnualStatementTests(ReportTestCase):
    def _get(self, user, **params):
        auth(self.client, user)
        return self.client.get(ANNUAL_STATEMENT, params)

    def test_admin_can_read_any_zev(self):
        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("annual-statement-2026-Muster.pdf", resp["Content-Disposition"])
        self.assertTrue(resp["Content-Disposition"].startswith("inline"))

    def test_owner_can_read_own_zev(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 200)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.other_zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 403)

    def test_participant_gets_their_own_without_naming_ids(self):
        """A participant never passes zev_id/participant_id; the ids they *do*
        pass are ignored, so they cannot request someone else's statement."""
        resp = self._get(self.puser, year=2026,
                         zev_id=str(self.other_zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertIn("annual-statement-2026-Muster.pdf", resp["Content-Disposition"])

    def test_participant_without_a_record_is_404(self):
        resp = self._get(make_user("rpt_orphan", UserRole.PARTICIPANT), year=2026)

        self.assertEqual(resp.status_code, 404)

    def test_year_is_required_and_must_be_numeric(self):
        missing = self._get(self.admin, zev_id=str(self.zev.pk), participant_id=str(self.participant.pk))
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.data["error"], "year is required.")

        bad = self._get(self.admin, year="not-a-year", zev_id=str(self.zev.pk),
                        participant_id=str(self.participant.pk))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.data["error"], "year must be a number.")

    def test_owner_must_name_both_ids(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "participant_id and zev_id are required.")

    def test_unknown_zev_is_404(self):
        resp = self._get(self.admin, year=2026, zev_id="00000000-0000-0000-0000-000000000000",
                         participant_id=str(self.participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participant_from_another_zev_is_404(self):
        """The participant lookup is scoped to the resolved ZEV, so naming a
        valid participant of a different ZEV must not leak their statement."""
        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_anonymous_is_rejected(self):
        self.client.credentials()

        self.assertEqual(self.client.get(ANNUAL_STATEMENT, {"year": 2026}).status_code, 401)


class AnnualStatementsZipTests(ReportTestCase):
    def _get(self, user, **params):
        auth(self.client, user)
        return self.client.get(STATEMENTS_ZIP, params)

    def test_owner_downloads_a_zip_of_every_participant(self):
        make_participant(self.zev, first="Bea", last="Zweit")

        resp = self._get(self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertIn("annual-statements-2026.zip", resp["Content-Disposition"])
        names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
        self.assertEqual(
            sorted(names),
            ["annual-statement-2026-Muster_Pia.pdf", "annual-statement-2026-Zweit_Bea.pdf"],
        )

    def test_participant_is_refused(self):
        resp = self._get(self.puser, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.other_zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_year_and_zev_id_are_both_required(self):
        for params in ({"year": 2026}, {"zev_id": "x"}):
            with self.subTest(params=params):
                resp = self._get(self.owner, **params)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.data["error"], "year and zev_id are required.")

    def test_zev_without_participants_for_that_year_is_404(self):
        """Participants are filtered by validity window, so a year before the
        ZEV had anyone yields 404 rather than an empty archive."""
        resp = self._get(self.owner, year=2020, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participants_who_left_before_the_year_are_excluded(self):
        Participant.objects.filter(pk=self.participant.pk).update(valid_to=date(2024, 6, 30))

        resp = self._get(self.owner, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 404)


class FinancialSummaryTests(ReportTestCase):
    def _get(self, user, **params):
        auth(self.client, user)
        return self.client.get(FINANCIAL_SUMMARY, params)

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.other_zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_zev_id_is_required_for_an_owner(self):
        resp = self._get(self.owner, year=2026)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "zev_id is required.")

    def test_without_participant_id_it_falls_back_to_the_zev_owner(self):
        """An admin naming only the ZEV gets the owner's record, since the
        admin has none of their own in it."""
        owner_participant = make_participant(self.zev, user=self.owner, first="Olga", last="Wirt")

        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"financial-summary-2026-{owner_participant.last_name}.pdf",
                      resp["Content-Disposition"])

    def test_without_any_default_participant_it_is_400(self):
        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "participant_id is required (no default participant found).")

    def test_participant_from_another_zev_is_404(self):
        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk),
                         participant_id=str(self.other_participant.pk))

        self.assertEqual(resp.status_code, 404)

    def test_participant_ignores_supplied_ids_and_gets_their_own(self):
        resp = self._get(self.puser, year=2026, zev_id=str(self.other_zev.pk),
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

    def _get(self, url, user, **params):
        auth(self.client, user)
        return self.client.get(url, params)

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
