"""Reading-correction impact: flags without rewriting invoices.

A committed billing-input change records one open ``InvoiceReadingImpact``
per affected invoice (invoice-lifecycle spec §4.6). Imports never touch
snapshots, items, totals, status, PDFs or delivery evidence; drafts resolve
through explicit regeneration and issued invoices through the existing
cancel-and-regenerate workflow.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from collections import Counter
from allocation.validity import civil_date
from unittest.mock import patch
from unittest import skipUnless
import threading
import time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, OperationalError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone as dj_timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.engine import generate_invoice
from invoices.models import Invoice, InvoiceReadingImpact, InvoiceStatus, Payment
from invoices.readiness import compute_readiness
from invoices.reading_impact import flag_import_impacts
from invoices.workflow import cancel_invoice, mark_invoice_paid, mark_invoice_sent
from metering.models import ImportLog, ImportSource, MeterReading, QuarantinedReading, ReadingDirection
from testing.sdat import (
    CONS_ID,
    PROD_ID,
    build_block,
    build_e66,
    quarter_block,
    observation,
)
from testing.helpers import authenticate as auth, create_managed_zev, make_user
from zev.models import (
    AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant,
    ZevAccessGrant, ZevAccessRole,
)

INVOICES = "/api/v1/invoices/invoices/"
IMPORT_LOGS = "/api/v1/metering/import-logs/"
SDAT_IMPORT = "/api/v1/metering/import/sdatch/"

JUNE = (date(2025, 6, 1), date(2025, 6, 30))
MAY = (date(2025, 5, 1), date(2025, 5, 31))


def _invoice_number(prefix):
    # uuid, never a counter: parallel workers share no counter state with
    # each other or with the ZEV's own invoice sequence.
    return f"{prefix}-{uuid4().hex[:8]}"


def _change(metering_point, timestamp, direction="in", kind="value"):
    return {
        "metering_point": str(metering_point.pk),
        "meter_id": metering_point.meter_id,
        "timestamp": timestamp,
        "direction": direction,
        "kind": kind,
        "old_energy": "1.0000",
        "new_energy": "2.0000",
    }


def _scope(changes):
    scope = {}
    for change in changes:
        if change["kind"] in ("availability", "value"):
            key = (UUID(change["metering_point"]), civil_date(datetime.fromisoformat(change["timestamp"])), change["direction"])
            scope.setdefault(key, Counter())[change["kind"]] += 1
    return scope


def _delivery(**overrides):
    payload = {
        "delivery_id": "DELIVERY-1",
        "creation": "2025-06-05T15:40:05+00:00",
        "status": "5",
        "reason": "E88",
    }
    payload.update(overrides)
    return payload


class ImpactBase(TestCase):
    def setUp(self):
        self.owner = make_user("impact_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Impact ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="I"
        )
        self.alice = Participant.objects.create(
            zev=self.zev, first_name="Alice", last_name="Holder",
            email="alice@example.com", valid_from=date(2025, 1, 1),
        )
        self.bob = Participant.objects.create(
            zev=self.zev, first_name="Bob", last_name="Later",
            email="bob@example.com", valid_from=date(2025, 1, 1),
        )
        self.cons = MeteringPoint.objects.create(
            zev=self.zev, meter_id="IMPACT-CONS", meter_type=MeteringPointType.CONSUMPTION,
        )
        self.prod = MeteringPoint.objects.create(
            zev=self.zev, meter_id="IMPACT-PROD", meter_type=MeteringPointType.PRODUCTION,
        )

    def _assign(self, point, participant, valid_from, valid_to=None, mode=AllocationMode.PERSONAL):
        return MeteringPointAssignment.objects.create(
            metering_point=point, participant=participant,
            valid_from=valid_from, valid_to=valid_to, allocation_mode=mode,
        )

    def _invoice(self, participant, period, inv_status=InvoiceStatus.DRAFT):
        return Invoice.objects.create(
            invoice_number=_invoice_number("IMP"), zev=self.zev, participant=participant,
            period_start=period[0], period_end=period[1], status=inv_status,
            total_chf=Decimal("42.00"),
        )

    def _log(self, changes=(), **overrides):
        params = {
            "zev": self.zev, "imported_by": self.owner, "source": ImportSource.SDATCH,
            "filename": "correction.xml", "reading_changes": list(changes),
            "source_delivery": _delivery(),
        }
        params.update(overrides)
        return ImportLog.objects.create(**params)

    def _flag(self, changes, **kwargs):
        log = self._log(changes)
        flagged = flag_import_impacts(
            zev=self.zev, import_log=log, affected_slots=_scope(changes),
            changes_truncated=False, delivery=_delivery(), **kwargs,
        )
        return log, flagged


class AttributionTests(ImpactBase):
    def test_consumption_change_spreads_to_active_participants(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        self._assign(self.prod, self.bob, date(2025, 1, 1))
        alice_inv = self._invoice(self.alice, JUNE)
        bob_inv = self._invoice(self.bob, JUNE)

        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        self.assertEqual(flagged, 2)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=alice_inv, resolved_at__isnull=True).exists()
        )
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=bob_inv, resolved_at__isnull=True).exists()
        )

    def test_historical_assignee_flagged_not_current_holder(self):
        self.bob.valid_from = date(2025, 6, 16)
        self.bob.save()
        self._assign(self.cons, self.alice, date(2025, 1, 1), date(2025, 6, 15))
        self._assign(self.cons, self.bob, date(2025, 6, 16))
        alice_inv = self._invoice(self.alice, JUNE)
        bob_inv = self._invoice(self.bob, JUNE)

        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        self.assertEqual(flagged, 1)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=alice_inv, resolved_at__isnull=True).exists()
        )
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=bob_inv, resolved_at__isnull=True).exists()
        )

    def test_production_change_flags_whole_community(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        self._assign(self.prod, self.alice, date(2025, 1, 1))
        alice_inv = self._invoice(self.alice, JUNE)
        bob_inv = self._invoice(self.bob, JUNE)

        _, flagged = self._flag([_change(self.prod, "2025-06-10T00:00:00+00:00", direction="out")])

        self.assertEqual(flagged, 2)
        for invoice in (alice_inv, bob_inv):
            self.assertTrue(
                InvoiceReadingImpact.objects.filter(
                    invoice=invoice, resolved_at__isnull=True
                ).exists()
            )

    def test_community_mode_consumption_flags_everyone(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1), mode=AllocationMode.COMMUNITY)
        alice_inv = self._invoice(self.alice, JUNE)
        bob_inv = self._invoice(self.bob, JUNE)

        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        self.assertEqual(flagged, 2)
        for invoice in (alice_inv, bob_inv):
            self.assertTrue(
                InvoiceReadingImpact.objects.filter(
                    invoice=invoice, resolved_at__isnull=True
                ).exists()
            )

    def test_swiss_business_date_routes_the_period(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        may_inv = self._invoice(self.alice, MAY)
        june_inv = self._invoice(self.alice, JUNE)

        # May31 in UTC is already June1 in Zurich (CEST).
        _, flagged = self._flag([_change(self.cons, "2025-05-31T22:00:00+00:00")])

        self.assertEqual(flagged, 1)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=june_inv, resolved_at__isnull=True).exists()
        )
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=may_inv, resolved_at__isnull=True).exists()
        )

    def test_unrelated_period_and_zev_stay_unflagged(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        may_inv = self._invoice(self.alice, MAY)
        other_owner = make_user("impact_other", UserRole.USER)
        other_zev = create_managed_zev(
            name="Other ZEV", owner=other_owner, zev_type="vzev", invoice_prefix="O"
        )
        other = Participant.objects.create(
            zev=other_zev, first_name="Zed", last_name="Other",
            email="zed@example.com", valid_from=date(2025, 1, 1),
        )
        other_inv = Invoice.objects.create(
            invoice_number=_invoice_number("O"), zev=other_zev, participant=other,
            period_start=JUNE[0], period_end=JUNE[1], total_chf=Decimal("1.00"),
        )

        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        self.assertEqual(flagged, 0)
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=may_inv, resolved_at__isnull=True).exists()
        )
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=other_inv, resolved_at__isnull=True).exists()
        )

    def test_metadata_only_and_empty_changes_flag_nothing(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE)

        _, flagged_meta = self._flag(
            [_change(self.cons, "2025-06-10T00:00:00+00:00", kind="metadata")]
        )
        _, flagged_empty = self._flag([])

        self.assertEqual(flagged_meta, 0)
        self.assertEqual(flagged_empty, 0)
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=invoice).exists()
        )

    def test_cancelled_invoices_are_not_flagged(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        cancelled = self._invoice(self.alice, JUNE, inv_status=InvoiceStatus.CANCELLED)

        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        self.assertEqual(flagged, 0)
        self.assertFalse(InvoiceReadingImpact.objects.filter(invoice=cancelled).exists())

    def test_flagging_is_idempotent_per_import(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE)
        changes = [_change(self.cons, "2025-06-10T00:00:00+00:00")]
        log = self._log(changes)

        first = flag_import_impacts(
            zev=self.zev, import_log=log, affected_slots=_scope(changes),
            changes_truncated=False, delivery=_delivery(),
        )
        second = flag_import_impacts(
            zev=self.zev, import_log=log, affected_slots=_scope(changes),
            changes_truncated=False, delivery=_delivery(),
        )

        self.assertEqual((first, second), (1, 0))
        self.assertEqual(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).count(), 1
        )


class SdatImportBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("sdat_impact_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="SDAT Impact ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="S"
        )
        # After the grant: promoting the account retires tokens minted before it.
        auth(self.client, self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Sam", last_name="Meter",
            email="sam@example.com", valid_from=date(2025, 1, 1),
        )
        self.cons_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=CONS_ID, meter_type=MeteringPointType.CONSUMPTION,
        )
        self.prod_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=PROD_ID, meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.cons_mp, participant=self.participant,
            valid_from=date(2025, 1, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.prod_mp, participant=self.participant,
            valid_from=date(2025, 1, 1),
        )

    def _upload(self, content, name="delivery.xml"):
        upload = SimpleUploadedFile(name, content, content_type="application/xml")
        return self.client.post(
            SDAT_IMPORT, {"file": upload, "zev_id": str(self.zev.id)}, format="multipart"
        )

    def _original(self, **kwargs):
        return self._upload(
            build_e66(
                [quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, doc="ORIG-BLOCK")],
                creation="2025-06-05T10:00:00Z",
                delivery_id="ORIG-DELIVERY",
                **kwargs,
            )
        )

    def _correction(self, **kwargs):
        observations = "".join(
            observation(seq, str(500 + seq))
            for seq in range(1, 5)
        )
        return self._upload(
            build_e66(
                [
                    build_block(
                        CONS_ID, observations, doc="FIX-BLOCK",
                        start="2025-06-02T22:00:00Z", end="2025-06-02T23:00:00Z",
                    )
                ],
                status="5",
                creation="2025-06-06T10:00:00Z",
                delivery_id="FIX-DELIVERY",
                **kwargs,
            )
        )

    def _invoice(self, inv_status=InvoiceStatus.DRAFT):
        return Invoice.objects.create(
            invoice_number=_invoice_number("S"), zev=self.zev, participant=self.participant,
            period_start=JUNE[0], period_end=JUNE[1], status=inv_status,
            total_chf=Decimal("42.00"),
        )


class CorrectionImportTests(SdatImportBase):
    def test_failure_after_promotion_and_impact_creation_rolls_back_history(self):
        block = build_block(CONS_ID, observation(1, "1", "21") + "".join(observation(seq, str(seq)) for seq in range(2, 5)))
        self.assertEqual(self._upload(build_e66([block])).data["result_status"], "accepted")
        self.assertEqual(QuarantinedReading.objects.count(), 1)
        self._invoice(inv_status=InvoiceStatus.SENT)
        models = (MeterReading, QuarantinedReading, Invoice, InvoiceReadingImpact)
        before = [list(model.objects.order_by("pk").values()) for model in models]
        observed = {}

        def fail_after_impacts(**kwargs):
            flag_import_impacts(**kwargs)
            observed["held"] = QuarantinedReading.objects.count()
            observed["impacts"] = InvoiceReadingImpact.objects.filter(import_log=kwargs["import_log"]).count()
            raise RuntimeError("Failure after promotion and impact creation")

        with patch("invoices.reading_impact.flag_import_impacts", side_effect=fail_after_impacts) as recorder:
            response = self._correction()
        recorder.assert_called_once()
        self.assertEqual(observed, {"held": 0, "impacts": 1})
        self.assertEqual(response.data["result_status"], "rejected")
        for model, snapshot in zip(models, before):
            self.assertEqual(list(model.objects.order_by("pk").values()), snapshot)

    def test_truncated_delivery_still_flags_every_affected_period(self):
        june = self._invoice()
        july = Invoice.objects.create(
            invoice_number=_invoice_number("JUL"), zev=self.zev, participant=self.participant,
            period_start=date(2025, 7, 1), period_end=date(2025, 7, 31), total_chf=Decimal("42"),
        )
        content = build_e66([
            quarter_block(CONS_ID, "2025-06-10T00:00:00Z", 4, doc="JUNE"),
            quarter_block(CONS_ID, "2025-07-10T00:00:00Z", 4, doc="JULY"),
        ])
        with patch("metering.importers.sdatch_importer.READING_CHANGE_CAP", 4):
            response = self._upload(content)
        self.assertEqual(response.data["rows_imported"], 8)
        self.assertEqual(len(response.data["reading_changes"]), 4)
        impacts = InvoiceReadingImpact.objects.filter(invoice__in=[june, july])
        self.assertEqual(impacts.count(), 2)
        self.assertTrue(all(row.evidence["change_count"] == 8 for row in impacts))

    def test_value_change_after_metadata_prefix_is_not_lost(self):
        self._original()
        invoice = self._invoice()
        volumes = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))
        volumes[-1] = Decimal("999")
        observations = "".join(
            f"<rsm:Observation><rsm:Position><rsm:Sequence>{seq}</rsm:Sequence></rsm:Position>"
            f"<rsm:Volume>{volume:.3f}</rsm:Volume></rsm:Observation>"
            for seq, volume in enumerate(volumes, 1)
        )
        with patch("metering.importers.sdatch_importer.READING_CHANGE_CAP", 3):
            response = self._upload(build_e66(
                [build_block(CONS_ID, observations)], status="5", creation="2025-06-06T10:00:00Z",
            ))
        self.assertEqual(response.data["result_status"], "accepted")
        impact = InvoiceReadingImpact.objects.get(invoice=invoice)
        self.assertEqual(impact.evidence["change_count"], 1)
        self.assertEqual(impact.evidence["kinds"], ["value"])

    def test_correction_flags_the_overlapping_invoice(self):
        invoice = self._invoice()
        self.assertEqual(self._original().data["result_status"], "accepted")

        resp = self._correction()

        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertGreater(resp.data["rows_overwritten"], 0)
        impact = InvoiceReadingImpact.objects.get(
            invoice=invoice,
            import_log_id=resp.data["id"],
            resolved_at__isnull=True,
        )
        self.assertEqual(impact.evidence["delivery_id"], "FIX-DELIVERY")
        self.assertEqual(impact.evidence["source"], "sdat-import")
        self.assertIn("value", impact.evidence["kinds"])
        # The original delivery's new data flagged the invoice too.
        self.assertEqual(
            InvoiceReadingImpact.objects.filter(
                invoice=invoice, resolved_at__isnull=True
            ).count(),
            2,
        )

    def test_import_leaves_invoice_documents_untouched(self):
        invoice = self._invoice(inv_status=InvoiceStatus.SENT)
        invoice.sent_at = dj_timezone.now()
        invoice.save(update_fields=["sent_at"])
        from invoices.models import EmailLog, InvoiceItem

        InvoiceItem.objects.create(
            invoice=invoice, item_type="local_energy", description="Solar",
            quantity_kwh=Decimal("5"), total_chf=Decimal("1.00"),
        )
        email = EmailLog.objects.create(
            invoice=invoice, recipient="sam@example.com", subject="s", status="sent"
        )
        before = {
            "status": invoice.status,
            "totals": [invoice.total_chf, invoice.subtotal_chf],
            "items": list(
                invoice.items.order_by("id").values_list("description", "quantity_kwh", "total_chf")
            ),
            "pdf_status": invoice.pdf_status,
            "sent_at": invoice.sent_at,
            "emails": list(
                EmailLog.objects.filter(invoice=invoice).values_list("id", "status")
            ),
        }
        self.assertEqual(self._original().data["result_status"], "accepted")

        resp = self._correction()

        self.assertEqual(resp.data["result_status"], "accepted")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, before["status"])
        self.assertEqual([invoice.total_chf, invoice.subtotal_chf], before["totals"])
        self.assertEqual(
            list(invoice.items.order_by("id").values_list("description", "quantity_kwh", "total_chf")),
            before["items"],
        )
        self.assertEqual(invoice.pdf_status, before["pdf_status"])
        self.assertEqual(invoice.sent_at, before["sent_at"])
        self.assertEqual(
            list(EmailLog.objects.filter(invoice=invoice).values_list("id", "status")),
            before["emails"],
        )
        self.assertEqual(EmailLog.objects.get(pk=email.pk).status, "sent")
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists()
        )

    def test_held_duplicate_stale_and_rejected_files_flag_nothing(self):
        invoice = self._invoice()
        self.assertEqual(self._original().data["result_status"], "accepted")

        held = self._upload(
            build_e66(
                [quarter_block(CONS_ID, "2025-06-03T22:00:00Z", 4, doc="INFO-BLOCK")],
                reason_xml="<rsm:VSENationalCode>C38</rsm:VSENationalCode>",
                creation="2025-06-06T10:00:00Z",
                delivery_id="INFO-DELIVERY",
            )
        )
        self.assertEqual(held.data["result_status"], "held")

        duplicate = self._original()
        self.assertEqual(duplicate.data["result_status"], "unchanged")

        stale = self._upload(
            build_e66(
                [quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, doc="STALE-BLOCK")],
                status="5",
                creation="2025-06-04T10:00:00Z",
                delivery_id="STALE-DELIVERY",
            )
        )
        self.assertEqual(stale.data["result_status"], "unchanged")

        conflict = self._upload(
            build_e66(
                [
                    build_block(
                        CONS_ID,
                        "".join(
                            f"<rsm:Observation><rsm:Position><rsm:Sequence>{seq}</rsm:Sequence></rsm:Position>"
                            f"<rsm:Volume>{900 + seq}</rsm:Volume></rsm:Observation>"
                            for seq in range(1, 5)
                        ),
                        doc="CLASH-BLOCK",
                        start="2025-06-02T22:00:00Z",
                        end="2025-06-02T23:00:00Z",
                    )
                ],
                status="5",
                creation="2025-06-05T10:00:00Z",
                delivery_id="CLASH-DELIVERY",
            )
        )
        self.assertEqual(conflict.data["result_status"], "rejected")

        for resp in (held, duplicate, stale, conflict):
            self.assertEqual(resp.data["reading_changes"], [])
        # Only the original delivery's new data flagged the invoice; replays,
        # stale skips, held-only files and rejections add nothing.
        impacts = InvoiceReadingImpact.objects.filter(invoice=invoice)
        self.assertEqual(impacts.count(), 1)
        self.assertEqual(impacts.get().evidence["delivery_id"], "ORIG-DELIVERY")

    def test_rejected_cancellation_preserves_invoice_and_readiness(self):
        from invoices.models import InvoiceItem

        self.assertEqual(self._original().data["result_status"], "accepted")
        invoice = self._invoice(inv_status=InvoiceStatus.SENT)
        invoice.pdf_file = "invoices/pdf/issued.pdf"
        invoice.save(update_fields=["pdf_file"])
        InvoiceItem.objects.create(
            invoice=invoice, item_type="local_energy", description="Solar",
            quantity_kwh=Decimal("5"), total_chf=Decimal("1.00"),
        )
        invoices = list(Invoice.objects.values())
        items = list(invoice.items.values())
        readiness = compute_readiness(self.zev, *JUNE)
        cancellation = build_e66([], status="1", creation="2025-06-07T10:00:00Z")

        for _ in range(2):
            response = self._upload(cancellation)

            self.assertEqual(response.data["result_status"], "rejected")
            self.assertEqual(response.data["issues"][0]["code"], "cancellation_rejected")
            self.assertEqual(list(Invoice.objects.values()), invoices)
            self.assertEqual(list(invoice.items.values()), items)
            self.assertFalse(InvoiceReadingImpact.objects.exists())
            self.assertEqual(compute_readiness(self.zev, *JUNE), readiness)


class DraftRegenerationTests(ImpactBase):
    def setUp(self):
        super().setUp()
        from tariffs.models import (
            BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod,
        )

        for energy_type, price in [
            (EnergyType.LOCAL, Decimal("0.15")),
            (EnergyType.GRID, Decimal("0.25")),
            (EnergyType.FEED_IN, Decimal("0.08")),
        ]:
            tariff = Tariff.objects.create(
                zev=self.zev, name=f"{energy_type} tariff",
                category=TariffCategory.ENERGY, billing_mode=BillingMode.ENERGY,
                energy_type=energy_type, valid_from=date(2025, 1, 1),
            )
            TariffPeriod.objects.create(
                tariff=tariff, period_type=PeriodType.FLAT, price_chf_per_kwh=price,
            )
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        MeterReading.objects.create(
            metering_point=self.cons,
            timestamp=datetime(2025, 6, 10, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("10.0"), direction=ReadingDirection.IN,
        )

    def test_successful_regeneration_resolves_incorporated_impacts(self):
        draft = generate_invoice(self.alice, JUNE[0], JUNE[1])
        log, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])
        self.assertEqual(flagged, 1)

        regenerated = generate_invoice(self.alice, JUNE[0], JUNE[1])

        self.assertNotEqual(regenerated.pk, draft.pk)
        self.assertFalse(InvoiceReadingImpact.objects.filter(invoice_id=draft.pk).exists())
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=regenerated, resolved_at__isnull=True).exists()
        )

    def test_partial_period_replacement_preserves_draft_and_corrections(self):
        draft = generate_invoice(self.alice, *JUNE)
        self._flag([_change(self.cons, "2025-06-25T00:00:00+00:00")])
        for start, end in ((date(2025, 6, 1), date(2025, 6, 15)),
                           (date(2025, 6, 15), date(2025, 7, 15))):
            with self.subTest(start=start, end=end):
                with self.assertRaisesMessage(ValueError, "whole period"):
                    generate_invoice(self.alice, start, end)
                self.assertTrue(Invoice.objects.filter(pk=draft.pk).exists())
                self.assertTrue(InvoiceReadingImpact.objects.filter(invoice=draft).exists())

    def test_larger_period_incorporates_corrections_and_preserves_audit_evidence(self):
        from audit.models import AuditEvent
        draft = generate_invoice(self.alice, *JUNE)
        evidence = {"source": "import-deletion", "day_from": "2025-06-25"}
        InvoiceReadingImpact.objects.create(invoice=draft, evidence=evidence)
        new = generate_invoice(self.alice, date(2025, 6, 1), date(2025, 7, 15))
        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
        event = AuditEvent.objects.get(action_type="invoice.reading_impact_resolved", target_id=str(new.pk))
        self.assertEqual(event.metadata_json["previous_impacts"][0]["invoice_id"], str(draft.pk))
        self.assertEqual(event.metadata_json["previous_impacts"][0]["evidence"], evidence)

    def test_unfiltered_prefetch_does_not_report_resolved_impacts_as_open(self):
        from invoices.serializers import InvoiceSerializer
        invoice = self._invoice(self.alice, JUNE)
        InvoiceReadingImpact.objects.create(invoice=invoice, evidence={}, resolved_at=dj_timezone.now(), resolution="cancelled")
        invoice = Invoice.objects.prefetch_related("reading_impacts").get(pk=invoice.pk)
        serializer = InvoiceSerializer()
        self.assertFalse(serializer.get_needs_data_review(invoice))
        self.assertEqual(serializer.get_open_data_impact_count(invoice), 0)
        self.assertEqual(serializer.get_data_impacts(invoice), [])

    def test_failed_regeneration_keeps_the_flag(self):
        draft = generate_invoice(self.alice, JUNE[0], JUNE[1])
        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])
        self.assertEqual(flagged, 1)
        blocking = self._invoice(self.alice, (date(2025, 6, 15), date(2025, 7, 15)),
                                 inv_status=InvoiceStatus.APPROVED)

        with self.assertRaises(ValueError):
            generate_invoice(self.alice, JUNE[0], JUNE[1])

        blocking.delete()
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=draft, resolved_at__isnull=True).exists()
        )


class FinalInvoiceResolutionTests(ImpactBase):
    def test_resolution_actions_return_cleared_review_flags(self):
        client = APIClient()
        auth(client, self.owner)
        for action, invoice_status, payload, expected_status in (
            ("cancel", InvoiceStatus.SENT, {}, 200),
            ("correct", InvoiceStatus.PAID, {"kind": "reversal", "reason": "Corrected readings"}, 201),
        ):
            with self.subTest(action=action):
                invoice = self._invoice(self.alice, JUNE, inv_status=invoice_status)
                impact = InvoiceReadingImpact.objects.create(invoice=invoice, evidence={"source": "sdat-import"})
                if invoice_status == InvoiceStatus.PAID:
                    Payment.objects.create(invoice=invoice, amount_chf=invoice.total_chf, paid_on=JUNE[1])

                response = client.post(f"{INVOICES}{invoice.pk}/{action}/", payload, format="json")

                self.assertEqual(response.status_code, expected_status, response.data)
                impact.refresh_from_db()
                self.assertEqual(impact.resolution, "cancelled")
                data = response.data["invoice"] if action == "correct" else response.data
                self.assertEqual(data["status"], InvoiceStatus.CANCELLED)
                self.assertFalse(data["needs_data_review"])
                self.assertEqual(data["open_data_impact_count"], 0)
                self.assertEqual(data["data_impacts"], [])

    def test_cancel_resolves_and_paid_keeps_the_flag(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE, inv_status=InvoiceStatus.APPROVED)
        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])
        self.assertEqual(flagged, 1)

        mark_invoice_sent(invoice)
        mark_invoice_paid(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists()
        )

        with self.assertRaises(Exception):
            cancel_invoice(invoice)
        self.assertTrue(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists()
        )

    def test_cancelled_issued_invoice_resolves_its_impacts(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE, inv_status=InvoiceStatus.SENT)
        _, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])
        self.assertEqual(flagged, 1)

        cancel_invoice(invoice)

        impact = InvoiceReadingImpact.objects.get(invoice=invoice)
        self.assertEqual(impact.resolution, "cancelled")
        self.assertIsNotNone(impact.resolved_at)
        self.assertFalse(
            InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists()
        )


class VisibilityTests(ImpactBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        self.invoice = self._invoice(self.alice, JUNE, inv_status=InvoiceStatus.SENT)
        self.invoice.sent_at = dj_timezone.now()
        self.invoice.save(update_fields=["sent_at"])
        self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

    def test_manager_sees_flag_and_evidence(self):
        auth(self.client, self.owner)
        response = self.client.get(f"{INVOICES}{self.invoice.id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["needs_data_review"])
        self.assertEqual(response.data["open_data_impact_count"], 1)
        self.assertEqual(len(response.data["data_impacts"]), 1)
        self.assertEqual(
            response.data["data_impacts"][0]["evidence"]["delivery_id"], "DELIVERY-1"
        )

        listed = self.client.get(INVOICES)
        row = next(item for item in listed.data["results"] if item["id"] == str(self.invoice.id))
        self.assertTrue(row["needs_data_review"])
        self.assertEqual(row["open_data_impact_count"], 1)
        self.assertNotIn("data_impacts", row)

    def test_overview_limits_evidence_but_detail_preserves_full_history(self):
        InvoiceReadingImpact.objects.bulk_create([
            InvoiceReadingImpact(invoice=self.invoice, evidence={"source": "import-deletion", "deleted_readings": 1})
            for _ in range(24)
        ])
        auth(self.client, self.owner)
        response = self.client.get(f"{INVOICES}period-overview/", {
            "zev_id": str(self.zev.pk), "period_start": JUNE[0].isoformat(), "period_end": JUNE[1].isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.content)
        overview = next(row["invoice"] for row in response.data["rows"] if row["invoice"] and row["invoice"]["id"] == str(self.invoice.pk))
        self.assertEqual(overview["open_data_impact_count"], 25)
        self.assertTrue(overview["needs_data_review"])
        self.assertEqual(len(overview["data_impacts"]), 20)
        newest = InvoiceReadingImpact.objects.filter(invoice=self.invoice).order_by("-created_at", "id")[:20]
        self.assertEqual([row["id"] for row in overview["data_impacts"]], [str(row.pk) for row in newest])
        detail = self.client.get(f"{INVOICES}{self.invoice.pk}/")
        self.assertEqual(len(detail.data["data_impacts"]), 25)
        self.assertEqual(detail.data["open_data_impact_count"], 25)

    def test_participant_sees_the_count_in_the_inbox_without_import_evidence(self):
        from inbox.producers import deliver_invoice_document

        tenant = make_user("impact_tenant", UserRole.USER)
        self.alice.user = tenant
        self.alice.save(update_fields=["user"])
        auth(self.client, tenant)
        self.invoice.status = InvoiceStatus.SENT
        self.invoice.save(update_fields=["status"])
        deliver_invoice_document(self.invoice, b"%PDF-1.7\n")

        # The live invoice is not reachable for a participant any more (#862) ...
        self.assertEqual(self.client.get(f"{INVOICES}{self.invoice.id}/").status_code, 404)
        # ... the count a participant may see is on their inbox row, and nothing of the import.
        rows = self.client.get("/api/v1/inbox/documents/").data["results"]
        row = next(item for item in rows if str(item["invoice"]) == str(self.invoice.id))
        self.assertEqual(row["invoice_figures"]["open_data_impact_count"], 1)
        self.assertNotIn("data_impacts", row)
        self.assertNotIn("data_impacts", row["invoice_figures"])

    def test_viewer_and_admin_keep_import_evidence(self):
        viewer = make_user("impact_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER)
        admin = make_user("impact_admin", UserRole.ADMIN)
        for user in (viewer, admin):
            with self.subTest(user=user.email):
                auth(self.client, user)
                response = self.client.get(f"{INVOICES}{self.invoice.id}/")
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(len(response.data["data_impacts"]), 1)
                impact = response.data["data_impacts"][0]
                self.assertIsNotNone(impact["import_log"])
                self.assertEqual(impact["evidence"]["delivery_id"], "DELIVERY-1")

    def test_missing_request_hides_import_evidence_without_querying(self):
        from invoices.serializers import InvoiceSerializer

        with self.assertNumQueries(0):
            self.assertEqual(InvoiceSerializer().get_data_impacts(self.invoice), [])

    def test_other_zev_manager_sees_nothing(self):
        other_owner = make_user("impact_stranger", UserRole.USER)
        create_managed_zev(name="Stranger ZEV", owner=other_owner, zev_type="vzev")
        auth(self.client, other_owner)

        listed = self.client.get(INVOICES)
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn(str(self.invoice.id), {item["id"] for item in listed.data["results"]})
        detail = self.client.get(f"{INVOICES}{self.invoice.id}/")
        self.assertEqual(detail.status_code, 404)


class ReadinessImpactTests(ImpactBase):
    def test_data_corrections_step_warns_with_impacted_invoices(self):
        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE)
        self.assertEqual(
            next(
                step for step in compute_readiness(self.zev, JUNE[0], JUNE[1])["steps"]
                if step["key"] == "data_corrections"
            )["status"],
            "ok",
        )

        self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])

        step = next(
            step for step in compute_readiness(self.zev, JUNE[0], JUNE[1])["steps"]
            if step["key"] == "data_corrections"
        )
        self.assertEqual(step["status"], "warn")
        self.assertEqual(step["count"], 1)
        self.assertEqual(step["detail_data"]["corrections"][0]["invoice_id"], str(invoice.id))
        self.assertEqual(
            step["detail_data"]["corrections"][0]["participant_name"], "Alice Holder"
        )


class BackupRoundTripTests(ImpactBase):
    def test_impact_flags_survive_backup_restore(self):
        import io

        from backups import restore_zev
        from backups.test_archive import build

        self._assign(self.cons, self.alice, date(2025, 1, 1))
        invoice = self._invoice(self.alice, JUNE)
        log, flagged = self._flag([_change(self.cons, "2025-06-10T00:00:00+00:00")])
        self.assertEqual(flagged, 1)
        raw, _manifest = build(scope="zev", zev=self.zev)

        InvoiceReadingImpact.objects.all().delete()
        restore_zev.restore_zev(io.BytesIO(raw), str(self.zev.id))

        impact = InvoiceReadingImpact.objects.get(invoice=invoice, resolved_at__isnull=True)
        self.assertEqual(impact.import_log_id, log.id)
        self.assertEqual(impact.evidence["delivery_id"], "DELIVERY-1")


class DeletionImpactTests(TestCase):
    def test_truncated_deletion_still_flags_later_period(self):
        invoice = Invoice.objects.create(
            invoice_number=_invoice_number("LATE"), zev=self.zev, participant=self.participant,
            period_start=date(2025, 7, 1), period_end=date(2025, 7, 31), total_chf=Decimal("42"),
        )
        log = self._additive_log_with_reading()
        MeterReading.objects.create(metering_point=self.cons, timestamp=datetime(2025, 7, 10, tzinfo=timezone.utc),
                                    energy_kwh=Decimal("2"), import_batch=log.batch_id)
        with patch("metering.views.collect_deleted_slots", wraps=lambda batches, **kwargs: ([], True)):
            response = self.client.delete(f"{IMPORT_LOGS}{log.id}/")
        self.assertEqual(response.status_code, 200)
        impact = InvoiceReadingImpact.objects.get(invoice=invoice)
        self.assertEqual(impact.evidence["deleted_readings"], 2)
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("deletion_impact_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Deletion Impact ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="D"
        )
        # After the grant: promoting the account retires tokens minted before it.
        auth(self.client, self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Del", last_name="Case",
            email="del@example.com", valid_from=date(2025, 1, 1),
        )
        self.cons = MeteringPoint.objects.create(
            zev=self.zev, meter_id="DEL-CONS", meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.cons, participant=self.participant,
            valid_from=date(2025, 1, 1),
        )

    def _additive_log_with_reading(self):
        import uuid

        batch = uuid.uuid4()
        log = ImportLog.objects.create(
            zev=self.zev, imported_by=self.owner, source=ImportSource.CSV,
            filename="additive.csv", batch_id=batch,
        )
        MeterReading.objects.create(
            metering_point=self.cons,
            timestamp=datetime(2025, 6, 10, 0, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("7.0"), direction=ReadingDirection.IN,
            import_source=ImportSource.CSV, import_batch=batch,
        )
        return log

    def test_billable_deletion_flags_the_invoice(self):
        invoice = Invoice.objects.create(
            invoice_number=_invoice_number("D"), zev=self.zev, participant=self.participant,
            period_start=JUNE[0], period_end=JUNE[1], total_chf=Decimal("9.00"),
        )
        log = self._additive_log_with_reading()

        resp = self.client.delete(f"{IMPORT_LOGS}{log.id}/")

        self.assertEqual(resp.status_code, 200, resp.content)
        impact = InvoiceReadingImpact.objects.get(invoice=invoice, resolved_at__isnull=True)
        self.assertEqual(impact.evidence["source"], "import-deletion")
        self.assertIsNone(impact.import_log)

    def test_deletion_flag_survives_log_removal(self):
        invoice = Invoice.objects.create(
            invoice_number=_invoice_number("D"), zev=self.zev, participant=self.participant,
            period_start=JUNE[0], period_end=JUNE[1], total_chf=Decimal("9.00"),
        )
        log = self._additive_log_with_reading()
        self.client.delete(f"{IMPORT_LOGS}{log.id}/")

        impact = InvoiceReadingImpact.objects.get(invoice=invoice)
        self.assertEqual(impact.evidence["day_from"], "2025-06-10")
        self.assertEqual(impact.evidence["deleted_readings"], 1)


    def test_separate_deletions_keep_evidence_with_and_without_a_batch(self):
        admin = make_user("deletion_impact_admin", UserRole.ADMIN)
        auth(self.client, admin)
        invoice = Invoice.objects.create(
            invoice_number=_invoice_number("D"), zev=self.zev, participant=self.participant,
            period_start=JUNE[0], period_end=JUNE[1], total_chf=Decimal("9.00"),
        )
        batch = uuid4()
        endpoint = f"/api/v1/zev/metering-points/{self.cons.pk}/delete-readings/"
        for batch_id in (batch, None):
            with self.subTest(batch_id=batch_id):
                InvoiceReadingImpact.objects.filter(invoice=invoice).delete()
                for day in (10, 11):
                    MeterReading.objects.create(
                        metering_point=self.cons,
                        timestamp=datetime(2025, 6, day, tzinfo=timezone.utc),
                        energy_kwh=Decimal("7"), import_batch=batch_id,
                    )
                for day in (10, 11):
                    response = self.client.post(endpoint, {
                        "date_from": f"2025-06-{day}", "date_to": f"2025-06-{day}",
                    }, format="json")
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["deleted_count"], 1)
                impacts = InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True)
                self.assertEqual(impacts.count(), 2)
                self.assertEqual({row.evidence["day_from"] for row in impacts}, {"2025-06-10", "2025-06-11"})
                self.assertEqual(sum(row.evidence["deleted_readings"] for row in impacts), 2)

                # Retrying the last completed deletion has no remaining slots.
                retry = self.client.post(endpoint, {
                    "date_from": "2025-06-11", "date_to": "2025-06-11",
                }, format="json")
                self.assertEqual(retry.status_code, 200, retry.data)
                self.assertEqual(retry.data["deleted_count"], 0)
                self.assertEqual(impacts.count(), 2)


@skipUnless(connection.vendor == "postgresql", "requires cross-connection advisory locks")
class GenerationCorrectionRaceTests(TransactionTestCase):
    def setUp(self):
        from tariffs.models import Tariff, TariffPeriod
        self.owner = make_user("generation_race", UserRole.USER)
        self.zev = create_managed_zev(name="Generation race", owner=self.owner, invoice_prefix="RACE")
        self.participant = Participant.objects.create(zev=self.zev, first_name="Race", last_name="Holder", valid_from=date(2025, 1, 1))
        self.point = MeteringPoint.objects.create(zev=self.zev, meter_id=CONS_ID, meter_type=MeteringPointType.CONSUMPTION)
        MeteringPointAssignment.objects.create(metering_point=self.point, participant=self.participant, valid_from=date(2025, 1, 1))
        tariff = Tariff.objects.create(zev=self.zev, name="Grid", energy_type="grid", category="energy", valid_from=date(2025, 1, 1))
        TariffPeriod.objects.create(tariff=tariff, period_type="flat", price_chf_per_kwh=Decimal("0.30"))
        from metering.importers.sdatch_importer import import_sdatch
        import_sdatch(SimpleUploadedFile("original.xml", build_e66([quarter_block(CONS_ID, "2025-06-10T00:00:00Z", 4)])), self.zev, self.owner)
        generate_invoice(self.participant, *JUNE)

    def _assert_blocked(self, outcome):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [outcome["pid"]])
                if cursor.fetchone()[0]:
                    return
            if any(key in outcome for key in ("error", "log", "invoice")):
                break
        self.fail(f"Concurrent writer did not wait for generation: {outcome}")

    def _race(self, bulk):
        from invoices import engine
        from metering.importers.sdatch_importer import import_sdatch
        pid_ready = threading.Event()
        outcome = {}

        def correct():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    outcome["pid"] = cursor.fetchone()[0]
                pid_ready.set()
                content = build_e66([quarter_block(CONS_ID, "2025-06-10T00:00:00Z", 4)],
                                    status="5", creation="2025-06-06T10:00:00Z")
                content = content.replace(b"<rsm:Volume>101</rsm:Volume>", b"<rsm:Volume>999</rsm:Volume>")
                outcome["log"] = import_sdatch(SimpleUploadedFile("correction.xml", content), self.zev, self.owner)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                connection.close()

        worker = threading.Thread(target=correct)
        original = engine._gather_period_readings

        def price(*args, **kwargs):
            worker.start()
            self.assertTrue(pid_ready.wait(10))
            self._assert_blocked(outcome)
            return original(*args, **kwargs)

        try:
            with patch.object(engine, "_gather_period_readings", side_effect=price):
                if bulk:
                    result = engine.generate_invoices_for_zev(self.zev, *JUNE)
                    self.assertEqual(result.failures, [])
                    invoice = result.invoices[0]
                else:
                    invoice = generate_invoice(self.participant, *JUNE)
        finally:
            if worker.ident is not None:
                worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["log"].result_status, "accepted")
        self.assertTrue(InvoiceReadingImpact.objects.filter(invoice=invoice, import_log=outcome["log"]).exists())

    def test_single_generation_serializes_correction(self):
        self._race(False)

    def test_bulk_invoice_serializes_correction(self):
        self._race(True)

    def test_cancellation_serializes_with_flag_creation(self):
        invoice = Invoice.objects.get(zev=self.zev)
        errors = []

        def cancel():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '200ms'")
                cancel_invoice(invoice)
            except OperationalError as exc:
                errors.append(str(exc))
            finally:
                connection.close()

        with transaction.atomic():
            log = ImportLog.objects.create(zev=self.zev, source=ImportSource.SDATCH)
            flag_import_impacts(zev=self.zev, import_log=log,
                affected_slots=_scope([_change(self.point, "2025-06-10T00:00:00Z")]),
                changes_truncated=False, delivery=_delivery())
            worker = threading.Thread(target=cancel)
            worker.start()
            worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIn("lock timeout", errors[0])
        cancel_invoice(invoice)
        self.assertFalse(InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists())

    def test_correction_started_before_generation_is_incorporated(self):
        from metering.importers.sdatch_importer import import_sdatch
        ready = threading.Event()
        outcome = {}

        def generate():
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    outcome["pid"] = cursor.fetchone()[0]
                ready.set()
                outcome["invoice"] = generate_invoice(self.participant, *JUNE)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                connection.close()

        worker = threading.Thread(target=generate)
        try:
            with transaction.atomic():
                content = build_e66([quarter_block(CONS_ID, "2025-06-10T00:00:00Z", 4)],
                                    status="5", creation="2025-06-06T10:00:00Z")
                content = content.replace(b"<rsm:Volume>101</rsm:Volume>", b"<rsm:Volume>999</rsm:Volume>")
                log = import_sdatch(SimpleUploadedFile("earlier.xml", content), self.zev, self.owner)
                self.assertEqual(log.result_status, "accepted")
                worker.start()
                self.assertTrue(ready.wait(10))
                self._assert_blocked(outcome)
        finally:
            if worker.ident is not None:
                worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["invoice"].total_grid_kwh, Decimal("1308"))
        self.assertFalse(InvoiceReadingImpact.objects.filter(invoice=outcome["invoice"]).exists())

    def _reversal_import_race(self, invoice_status, reversal_first):
        from invoices import workflow
        from metering.locks import lock_billing_inputs

        invoice = Invoice.objects.get(zev=self.zev)
        invoice.status = invoice_status
        invoice.save(update_fields=["status"])
        Payment.objects.create(invoice=invoice, amount_chf=invoice.total_chf, paid_on=JUNE[1])
        import_locked = threading.Event()
        reversal_locked = threading.Event()
        flag_now = threading.Event()
        reverse_now = threading.Event()
        outcome = {}
        original_paid = workflow.paid_chf

        def received(pk):
            reversal_locked.set()
            if not reverse_now.wait(15):
                raise TimeoutError("Reversal was not released")
            return original_paid(pk)

        def reverse():
            try:
                outcome["reversal"] = workflow.correct_invoice(invoice, kind="reversal", reason="Reading correction")
            except Exception as exc:
                outcome["reversal_error"] = exc
            finally:
                connection.close()

        def flag():
            try:
                with transaction.atomic():
                    lock_billing_inputs(self.zev)
                    import_locked.set()
                    if not flag_now.wait(15):
                        raise TimeoutError("Import was not released")
                    log = ImportLog.objects.create(zev=self.zev, source=ImportSource.SDATCH)
                    outcome["flags"] = flag_import_impacts(
                        zev=self.zev, import_log=log, changes_truncated=False,
                        delivery=_delivery(), affected_slots=_scope([_change(self.point, "2025-06-10T00:00:00Z")]),
                    )
            except Exception as exc:
                outcome["import_error"] = exc
            finally:
                connection.close()

        importer = threading.Thread(target=flag)
        reversal = threading.Thread(target=reverse)
        try:
            with patch.object(workflow, "paid_chf", side_effect=received), patch("invoices.tasks.generate_credit_pdf_task.delay"):
                if reversal_first:
                    reversal.start()
                    self.assertTrue(reversal_locked.wait(10), outcome)
                    importer.start()
                    self.assertTrue(import_locked.wait(10), outcome)
                else:
                    importer.start()
                    self.assertTrue(import_locked.wait(10), outcome)
                    reversal.start()
                    self.assertTrue(reversal_locked.wait(10), outcome)
                flag_now.set()
                reverse_now.set()
                importer.join(15)
                reversal.join(15)
        finally:
            flag_now.set()
            reverse_now.set()
            for worker in (importer, reversal):
                if worker.ident is not None:
                    worker.join(15)
        self.assertFalse(importer.is_alive() or reversal.is_alive())
        self.assertNotIn("import_error", outcome)
        self.assertNotIn("reversal_error", outcome)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.CANCELLED)
        self.assertFalse(InvoiceReadingImpact.objects.filter(invoice=invoice, resolved_at__isnull=True).exists())

    def test_paid_reversal_during_import_completes(self):
        self._reversal_import_race(InvoiceStatus.PAID, False)

    def test_import_during_paid_reversal_completes(self):
        self._reversal_import_race(InvoiceStatus.PAID, True)

    def test_sent_with_payment_reversal_during_import_completes(self):
        self._reversal_import_race(InvoiceStatus.SENT, False)

    def test_import_during_sent_with_payment_reversal_completes(self):
        self._reversal_import_race(InvoiceStatus.SENT, True)
