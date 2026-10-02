"""Access through grants and the union of an account's relationships (#761, spec §6, §13).

``zev/test_access_regression.py`` pins that an account with one relationship
sees exactly what it did before grants; this module covers what grants add:
viewers, several relationships per account, former participants, and the rule
that every write below ``manager`` is refused.
"""

import re
from datetime import date, timedelta
from unittest import mock

from django.db import transaction
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from accounts.models import FeatureFlag, UserRole
from invoices.models import EmailLog, Invoice, InvoiceStatus
from mcp_server.tests.conftest import call_tool, client_for
from metering.models import ImportLog, MeterReading
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import Tariff, TariffPeriod
from testing.helpers import make_user
from zev.models import (
    MeteringPoint, MeteringPointAssignment, Participant, Zev, ZevAccessGrant, ZevAccessRole,
)
from zev.test_access_regression import LISTS, AccessWorldMixin, _ids

YESTERDAY = timezone.localdate() - timedelta(days=1)


class GrantWorldMixin(AccessWorldMixin):
    """The regression world plus a viewer of Alpha and a viewer of Alpha who manages Beta."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.viewer = make_user("acc_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=cls.alpha, user=cls.viewer, role=ZevAccessRole.VIEWER)
        cls.viewer_manager = make_user("acc_viewer_manager", UserRole.USER)
        ZevAccessGrant.objects.create(zev=cls.alpha, user=cls.viewer_manager, role=ZevAccessRole.VIEWER)
        ZevAccessGrant.objects.create(zev=cls.beta, user=cls.viewer_manager, role=ZevAccessRole.MANAGER)

    def user_for(self, role):
        extra = {"viewer": self.viewer, "viewer_manager": self.viewer_manager}
        return extra[role] if role in extra else super().user_for(role)


class ViewerTests(GrantWorldMixin, TestCase):
    def test_a_viewer_reads_what_the_manager_reads(self):
        for name, (url, _, _) in LISTS.items():
            with self.subTest(list=name):
                manager = self.client_as("owner").get(url, {"zev_id": self.alpha.pk})
                viewer = self.client_as("viewer").get(url, {"zev_id": self.alpha.pk})
                self.assertEqual(viewer.status_code, 200, viewer.content[:200])
                self.assertEqual(_ids(viewer), _ids(manager))

    def test_a_viewer_reads_reports_of_its_zev_only(self):
        client = self.client_as("viewer")
        period = {"period_start": "2026-01-01", "period_end": "2026-01-31"}
        self.assertEqual(client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": self.alpha.pk}).status_code, 200)
        self.assertEqual(client.get("/api/v1/invoices/invoices/readiness/", {"zev_id": self.beta.pk}).status_code, 403)
        self.assertEqual(
            client.get("/api/v1/invoices/invoices/period-overview/", {"zev_id": self.alpha.pk, **period}).status_code, 200,
        )
        summary = client.get("/api/v1/metering/readings/dashboard-summary/")
        self.assertEqual((summary.status_code, summary.json()["summary_kind"]), (200, "zev"))

    def test_a_viewer_cannot_file_rows_under_its_zev(self):
        body = {"zev": str(self.alpha.pk), "meter_id": "ALPHA-VIEWER-1"}
        # A pure viewer is refused at the gate; one that manages elsewhere is
        # refused on the payload naming the ZEV it only views.
        self.assertEqual(self.client_as("viewer").post("/api/v1/zev/metering-points/", body, format="json").status_code, 403)
        self.assertEqual(
            self.client_as("viewer_manager").post("/api/v1/zev/metering-points/", body, format="json").status_code, 400,
        )
        self.assertFalse(MeteringPoint.objects.filter(meter_id="ALPHA-VIEWER-1").exists())

    def test_read_only_posts_are_open_to_a_viewer(self):
        from django.core.files.base import ContentFile

        self.tenant_sent.pdf_file.save("viewer-zip.pdf", ContentFile(b"%PDF-1.4 viewer"), save=True)
        self.addCleanup(self.tenant_sent.pdf_file.delete, save=False)
        client = self.client_as("viewer")
        zip_response = client.post(
            "/api/v1/invoices/invoices/download-pdfs/",
            {"zev_id": str(self.alpha.pk), "period_start": "2026-02-01", "period_end": "2026-02-28"},
            format="json",
        )
        self.assertEqual(zip_response.status_code, 200)
        with mock.patch("exports.views.run_export_job.delay"):
            export = client.post(
                "/api/v1/exports/jobs/",
                {"export_type": "annual_statements", "zev_id": str(self.alpha.pk), "params": {"year": 2026}},
                format="json",
            )
        self.assertEqual(export.status_code, 202)

    def test_a_viewer_may_use_the_mcp_server(self):
        FeatureFlag.objects.update_or_create(name=FeatureFlag.MCP_SERVER_ENABLED, defaults={"enabled": True})
        response = call_tool(client_for(self.viewer), "list_zevs")
        self.assertEqual(response.status_code, 200)
        zevs = response.json()["result"]["structuredContent"]["zevs"]
        self.assertEqual({row["id"] for row in zevs}, {str(self.alpha.pk)})

    def test_disabled_zev_stays_readable_and_not_writable(self):
        Zev.objects.filter(pk=self.alpha.pk).update(disabled_at=timezone.now())
        alice = Participant.objects.get(zev=self.alpha, first_name="Alice")
        url = f"/api/v1/zev/participants/{alice.pk}/"
        self.assertEqual(self.client_as("viewer").get(url).status_code, 200)
        self.assertEqual(self.client_as("viewer").patch(url, {"city": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client_as("owner").patch(url, {"city": "x"}, format="json").status_code, 403)
        # ...while it disappears for its participants.
        self.assertEqual(_ids(self.client_as("tenant").get("/api/v1/invoices/invoices/")), set())


class ViewerWriteRouterWalkTests(GrantWorldMixin, TestCase):
    """Every unsafe route a viewer can reach leaves the viewed ZEV untouched.

    Walks the URL configuration rather than a hand-kept list, so a new write
    action is covered the day it is added. Each attempt runs in a rolled-back
    savepoint. A pure viewer must never get a 2xx. An account that views Alpha
    and manages Beta may succeed on a list-level action (it acts on Beta), but
    Alpha's rows must be exactly as before.
    """

    READ_ONLY_POSTS = {
        "invoice-download-pdfs",  # a ZIP of the period's PDFs
        "export-job-create",  # an export is a read (annual statements)
        "feasibility-calculate",  # a calculator; writes nothing
        "mcp",  # every MCP tool is read-only (ADR 0025)
    }
    SKIPPED_PREFIXES = ("api/v1/auth/", "api/v1/public/", "api/v1/backups/")

    def _routes(self, patterns=None, prefix=""):
        for entry in patterns if patterns is not None else get_resolver().url_patterns:
            if isinstance(entry, URLResolver):
                yield from self._routes(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                yield prefix + str(entry.pattern), entry

    def _object_ids(self):
        tariff = Tariff.objects.filter(zev=self.alpha).first()
        # Shared price sources are written by admins only; any source will do.
        source = DynamicTariffSource.objects.create(
            label="Walk grid", url="https://prices.test/walk", api_version="v1_0_5",
            tariff_type="grid", tariff_name="vario",
        )
        log = EmailLog.objects.create(invoice=self.tenant_draft, recipient="x@example.com", subject="s", status="sent")
        return {
            Zev: self.alpha.pk,
            Participant: Participant.objects.get(zev=self.alpha, first_name="Alice").pk,
            MeteringPoint: self.tenant_meter.pk,
            MeteringPointAssignment: MeteringPointAssignment.objects.filter(metering_point__zev=self.alpha).first().pk,
            Tariff: tariff.pk,
            TariffPeriod: TariffPeriod.objects.filter(tariff__zev=self.alpha).first().pk,
            DynamicTariffSource: source.pk,
            Invoice: self.tenant_draft.pk,
            MeterReading: MeterReading.objects.filter(metering_point__zev=self.alpha).first().pk,
            ImportLog: ImportLog.objects.get(zev=self.alpha).pk,
            "email_log_id": log.pk,
        }

    def _alpha_state(self):
        rows = {
            Zev: Zev.objects.filter(pk=self.alpha.pk),
            Participant: Participant.objects.filter(zev=self.alpha),
            MeteringPoint: MeteringPoint.objects.filter(zev=self.alpha),
            MeteringPointAssignment: MeteringPointAssignment.objects.filter(metering_point__zev=self.alpha),
            Tariff: Tariff.objects.filter(zev=self.alpha),
            TariffPeriod: TariffPeriod.objects.filter(tariff__zev=self.alpha),
            Invoice: Invoice.objects.filter(zev=self.alpha),
            MeterReading: MeterReading.objects.filter(metering_point__zev=self.alpha),
            ImportLog: ImportLog.objects.filter(zev=self.alpha),
            ZevAccessGrant: ZevAccessGrant.objects.filter(zev=self.alpha),
        }
        return {model.__name__: sorted(map(str, qs.order_by("pk").values())) for model, qs in rows.items()}

    def _model_of(self, view_class):
        serializer = getattr(view_class, "serializer_class", None)
        return getattr(getattr(serializer, "Meta", None), "model", None)

    def _url(self, route, view_class, ids):
        if "(?P<format>" in route or "<drf_format_suffix" in route:
            return None
        url = "/" + route.replace("^", "").replace("$", "")
        if "(?P<pk>" in url:
            pk = ids.get(self._model_of(view_class))
            if pk is None:
                return None
            url = re.sub(r"\(\?P<pk>[^)]*\)", str(pk), url)
        url = re.sub(r"\(\?P<email_log_id>[^)]*\)", str(ids["email_log_id"]), url)
        url = re.sub(r"\(\?P<template_key>[^)]*\)", "invoice_email", url)
        return None if "(?P<" in url or "<" in url else url

    def test_no_unsafe_route_lets_a_viewer_write(self):
        ids = self._object_ids()
        before = self._alpha_state()
        attempted = 0
        for route, pattern in self._routes():
            if not route.startswith("api/v1/") or route.startswith(self.SKIPPED_PREFIXES):
                continue
            if pattern.name in self.READ_ONLY_POSTS:
                continue
            view_class = getattr(pattern.callback, "cls", None)
            actions = getattr(pattern.callback, "actions", None)
            if actions:
                methods = [m for m in actions if m in ("post", "put", "patch", "delete")]
            else:
                methods = [m for m in ("post", "put", "patch", "delete") if view_class and hasattr(view_class, m)]
            url = self._url(route, view_class, ids) if methods else None
            if url is None:
                continue
            for method in methods:
                for role in ("viewer", "viewer_manager"):
                    with self.subTest(route=pattern.name, method=method, role=role):
                        with transaction.atomic():
                            response = getattr(self.client_as(role), method)(url, {}, format="json")
                            after = self._alpha_state()
                            transaction.set_rollback(True)
                        attempted += 1
                        self.assertEqual(after, before, f"{method.upper()} {url} changed Alpha for a {role}")
                        if role == "viewer":
                            self.assertFalse(
                                200 <= response.status_code < 300,
                                f"{method.upper()} {url} answered {response.status_code} for a viewer",
                            )
        # The walk found the routes it is meant to cover.
        self.assertGreater(attempted, 100)


class MultiRelationshipScopingTests(GrantWorldMixin, TestCase):
    def test_a_tenant_in_two_communities_sees_both(self):
        beta_bob = Participant.objects.get(zev=self.beta, first_name="Bob")
        beta_bob.user = self.tenant
        beta_bob.save()
        Invoice.objects.filter(pk=self.beta_draft.pk).update(status=InvoiceStatus.SENT)
        client = self.client_as("tenant")
        self.assertEqual(_ids(client.get("/api/v1/invoices/invoices/")), {str(self.tenant_sent.pk), str(self.beta_draft.pk)})
        self.assertEqual(
            _ids(client.get("/api/v1/zev/metering-points/")),
            {str(self.tenant_meter.pk), str(MeteringPoint.objects.get(meter_id="BETA-CONS-1").pk)},
        )

    def test_an_owner_who_rents_elsewhere_sees_their_own_rows_there(self):
        beta_alice = Participant.objects.get(zev=self.beta, first_name="Alice")
        beta_alice.user = self.owner
        beta_alice.save()
        beta_invoice = Invoice.objects.get(zev=self.beta, participant=beta_alice)
        client = self.client_as("owner")

        invoices = _ids(client.get("/api/v1/invoices/invoices/"))
        self.assertTrue({str(pk) for pk in Invoice.objects.filter(zev=self.alpha).values_list("pk", flat=True)} <= invoices)
        self.assertIn(str(beta_invoice.pk), invoices)
        self.assertNotIn(str(self.beta_draft.pk), invoices)
        # Only Alpha's ZEV record: renting in Beta never reveals Beta's settings.
        self.assertEqual(_ids(client.get("/api/v1/zev/zevs/")), {str(self.alpha.pk)})
        # Beta's tariffs stay a manager-only resource.
        self.assertEqual(_ids(client.get("/api/v1/tariffs/tariffs/", {"zev_id": self.beta.pk})), set())
        # Writing to Beta is still refused.
        self.assertEqual(
            client.patch(f"/api/v1/zev/participants/{beta_alice.pk}/", {"city": "x"}, format="json").status_code, 404,
        )

        dashboard = client.get("/api/v1/metering/readings/dashboard-summary/", {"zev_id": self.beta.pk})
        self.assertEqual((dashboard.status_code, dashboard.json()["summary_kind"]), (200, "participant"))
        with mock.patch("invoices.views_reports.generate_annual_statement_pdf", return_value=b"%PDF") as generate:
            statement = client.get("/api/v1/invoices/invoices/annual-statement/", {"year": 2026, "zev_id": self.beta.pk})
        self.assertEqual(statement.status_code, 200)
        self.assertEqual(generate.call_args.args[0], beta_alice)
        self.assertIs(generate.call_args.kwargs["sent_only"], True)

    def test_a_manager_of_two_communities_sees_both(self):
        ZevAccessGrant.objects.create(zev=self.beta, user=self.owner, role=ZevAccessRole.MANAGER)
        client = self.client_as("owner")
        self.assertEqual(_ids(client.get("/api/v1/zev/zevs/")), {str(self.alpha.pk), str(self.beta.pk)})
        self.assertEqual(
            client.patch(f"/api/v1/zev/zevs/{self.beta.pk}/", {"notes": "x"}, format="json").status_code, 200,
        )
        self.assertEqual(client.get("/api/v1/metering/readings/dashboard-summary/").status_code, 400)

    def test_a_manager_who_is_also_a_participant_sees_unsent_invoices_through_the_grant(self):
        draft = Invoice.objects.create(
            zev=self.alpha, participant=self.owner_participant, invoice_number="ALPHA-OLIVIA-DRAFT",
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), status=InvoiceStatus.DRAFT,
        )
        self.assertIn(str(draft.pk), _ids(self.client_as("owner").get("/api/v1/invoices/invoices/")))


class FormerParticipantTests(GrantWorldMixin, TestCase):
    def setUp(self):
        Participant.objects.filter(pk=self.tenant_participant.pk).update(valid_to=YESTERDAY)

    def test_keeps_their_sent_invoices_only(self):
        client = self.client_as("tenant")
        self.assertEqual(_ids(client.get("/api/v1/invoices/invoices/")), {str(self.tenant_sent.pk)})
        self.assertEqual(client.get(f"/api/v1/invoices/invoices/{self.tenant_sent.pk}/").status_code, 200)

    def test_loses_everything_else(self):
        client = self.client_as("tenant")
        self.assertEqual(_ids(client.get("/api/v1/zev/metering-points/")), set())
        self.assertEqual(client.get("/api/v1/metering/readings/chart-data/").status_code in (200, 400), True)
        summary = client.get("/api/v1/metering/readings/dashboard-summary/").json()
        self.assertEqual(summary["zev_totals"]["produced_kwh"], 0)
        with mock.patch("invoices.views_reports.generate_annual_statement_pdf", return_value=b"%PDF"):
            self.assertEqual(client.get("/api/v1/invoices/invoices/annual-statement/", {"year": 2026}).status_code, 404)

    def test_a_current_row_elsewhere_keeps_that_community(self):
        beta_bob = Participant.objects.get(zev=self.beta, first_name="Bob")
        beta_bob.user = self.tenant
        beta_bob.save()
        self.assertEqual(
            _ids(self.client_as("tenant").get("/api/v1/zev/metering-points/")),
            {str(MeteringPoint.objects.get(meter_id="BETA-CONS-1").pk)},
        )
