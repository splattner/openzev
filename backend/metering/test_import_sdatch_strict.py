"""Strict SDAT-CH profile, atomicity and revision tests.

Reference fixture provenance
----------------------------
``test_fixtures/sdatch/e66_1_4_4_customer.xml`` is an unmodified copy of the
official VSE example::

    Beispiel_Messdatenaustauschprozesse_1_4_4_Lastgänge_Einspeisegänge_an_Endverbraucher_Erzeugungseinheit_1p6.xml

Source archive: https://www.strom.ch/de/media/13704/download
(``sdat_examples.zip``, SDAT-CH 2025). SHA-256 of the copied file::

    02db4e971439d04ec9165162d2aa73202e0088ac8fb29da76fa8e91eb166558a

All other XML in this module is derived (synthesized by ``build_e66`` to
exercise one rule each) and labelled as such in the test names.
"""

import gzip
import os
import threading
import tracemalloc
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest import mock as unittest_mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase
from lxml import etree
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.importers import sdatch_importer
from metering.models import ImportLog, ImportSource, MeterReading, QuarantinedReading, ReadingDirection
from testing.helpers import authenticate as auth, make_user, create_managed_zev
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant, Zev

from testing.sdat import (
    CONS_ID, PROD_ID, TS0, ACTIVE_PRODUCT, REACTIVE_PRODUCT, LEG_PRODUCT,
    build_e66, build_block, quarter_block, observation,
)


class StrictBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("strict_owner", UserRole.USER)
        self.zev = create_managed_zev(name="Strict ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="T")
        # After the grant: promoting the account retires tokens minted before it.
        auth(self.client, self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Strict",
            last_name="Case",
            email="strict.case@example.com",
            valid_from=datetime(2026, 1, 1).date(),
        )
        self.cons_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=CONS_ID, meter_type=MeteringPointType.CONSUMPTION,
        )
        self.prod_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=PROD_ID, meter_type=MeteringPointType.PRODUCTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.cons_mp, participant=self.participant,
            valid_from=datetime(2026, 1, 1).date(),
        )

    def _upload(self, name, content, *, zev=None):
        upload = SimpleUploadedFile(name, content, content_type="application/xml")
        return self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str((zev or self.zev).id)},
            format="multipart",
        )

    def _import(self, content, **kwargs):
        return self._upload("derived.xml", content, **kwargs)

    def assertRejected(self, resp, code=None):
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "rejected")
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["rows_overwritten"], 0)
        self.assertTrue(resp.data["errors"], "rejected file must carry a failure log")
        if code is not None:
            self.assertTrue(
                any(issue["code"] == code for issue in resp.data["issues"]),
                f"expected issue code {code!r} in {resp.data['issues']}",
            )
FIXTURE_1_4_4 = os.path.join(
    os.path.dirname(__file__), "test_fixtures", "sdatch", "e66_1_4_4_customer.xml"
)


class StructuredDiagnosticTests(unittest.TestCase):
    """Semantic diagnostics retain useful values even when called without XSD validation."""

    def test_header_diagnostics_identify_missing_elements_and_invalid_values(self):
        for element in ("ValidatedMeteredData_HeaderInformation", "InstanceDocument"):
            with self.subTest(element=element):
                root = etree.fromstring(build_e66([]))
                node = root.find(f".//{sdatch_importer._qname(element)}")
                node.getparent().remove(node)
                with self.assertRaises(sdatch_importer._FileRejected) as caught:
                    sdatch_importer._validate_header(sdatch_importer._ImportRun(), root)
                self.assertEqual(caught.exception.issues[0]["element"], element)
                self.assertEqual(caught.exception.issues[0]["code"], "invalid_header")

        for arguments, code, params in (
            ({"doctype": "E31"}, "unsupported_document_type", {"document_type": "E31"}),
            ({"status": "7"}, "unsupported_status", {"status": "7"}),
            ({"creation": "invalid"}, "invalid_creation", {"creation": "invalid"}),
            ({"report_end": "2025-06-02T22:00:00Z"}, "invalid_report_period", {
                "interval_start": "2025-06-02T22:00:00Z", "interval_end": "2025-06-02T22:00:00Z",
            }),
        ):
            with self.subTest(code=code):
                with self.assertRaises(sdatch_importer._FileRejected) as caught:
                    sdatch_importer._validate_header(sdatch_importer._ImportRun(), etree.fromstring(build_e66([], **arguments)))
                issue = caught.exception.issues[0]
                self.assertEqual(issue["code"], code)
                self.assertEqual({key: issue[key] for key in params}, params)

    def test_block_diagnostics_preserve_semantic_failure_details(self):
        ordinary = "".join(observation(position, "10") for position in range(1, 5))
        for arguments, observations, code, params in (
            ({"start": "invalidZ"}, ordinary, "invalid_interval", {"detail_code": "invalid_timestamp", "interval_start": "invalidZ"}),
            ({"end": "2025-06-02T22:00:00Z"}, ordinary, "invalid_interval", {"detail_code": "empty_interval"}),
            ({"end": "2025-06-02T23:00:01Z"}, ordinary, "invalid_interval", {"detail_code": "non_minute_interval"}),
            ({"resolution": "60", "resolution_unit": "HUR"}, ordinary, "unsupported_resolution", {"resolution": "60", "resolution_unit": "HUR"}),
            ({}, observation(1, "NaN") + "".join(observation(position, "10") for position in range(2, 5)),
             "invalid_volume", {"detail_code": "invalid_number", "volume": "NaN"}),
            ({}, observation(1, "10", "99") + "".join(observation(position, "10") for position in range(2, 5)),
             "unknown_condition", {"condition": "99"}),
        ):
            with self.subTest(code=code, params=params):
                root = etree.fromstring(build_e66([build_block(CONS_ID, observations, **arguments)]))
                block = root.find(f".//{sdatch_importer._qname('MeteringData')}")
                with self.assertRaises(sdatch_importer._FileRejected) as caught:
                    sdatch_importer._parse_block(block, reason="E88", report_period=(
                        datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc),
                    ))
                issue = caught.exception.issues[0]
                self.assertEqual(issue["code"], code)
                self.assertEqual(issue["block_id"], "DERIVED-BLOCK")
                self.assertEqual({key: issue[key] for key in params}, params)

    def test_xml_error_params_keep_zero_locations_and_drop_empty_strings(self):
        error = unittest_mock.Mock(line=0, column=0, path="", type_name="ERR_XML")
        exc = unittest_mock.Mock(error_log=unittest_mock.Mock(last_error=error))

        self.assertEqual(sdatch_importer._xml_error_params(exc), {
            "xml_line": 0, "xml_column": 0, "xml_error_type": "ERR_XML",
        })


class BatchedPersistenceTests(StrictBase):
    def test_replacement_updates_in_bounded_batches(self):
        original = build_block(CONS_ID, observation(1, "1", "21") + "".join(observation(s, "1") for s in range(2, 5)))
        self._import(build_e66([original]))
        identity_before = dict(MeterReading.objects.values_list("pk", "created_at"))
        replacement = build_block(CONS_ID, "".join(observation(s, str(s + 1)) for s in range(1, 5)))
        with unittest_mock.patch.object(sdatch_importer, "PERSIST_BATCH_SIZE", 2), unittest_mock.patch.object(
            MeterReading.objects, "bulk_create", wraps=MeterReading.objects.bulk_create,
        ) as update:
            response = self._import(build_e66([replacement], status="5", creation="2025-06-06T15:40:05Z"))
        self.assertEqual(response.data["result_status"], "accepted")
        update_calls = [call for call in update.call_args_list if call.kwargs.get("update_conflicts")]
        create_calls = [call for call in update.call_args_list if not call.kwargs.get("update_conflicts")]
        self.assertEqual([len(call.args[0]) for call in update_calls], [2, 1])
        self.assertEqual(response.data["result_counts"]["promoted"], 1)
        self.assertEqual(
            list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True)),
            [Decimal(s + 1) for s in range(1, 5)],
        )
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(create_calls[0].kwargs["batch_size"], 2)
        self.assertFalse(QuarantinedReading.objects.exists())
        self.assertEqual(dict(MeterReading.objects.filter(pk__in=identity_before).values_list("pk", "created_at")), identity_before)

    def test_held_replacement_and_promotion_cross_batch_boundaries(self):
        original = build_block(CONS_ID, "".join(observation(s, str(s), "21") for s in range(1, 6)),
                               end="2025-06-02T23:15:00Z")
        initial = self._import(build_e66([original])).data
        self.assertEqual(initial["result_status"], "held")
        held_url = "/api/v1/metering/held-readings/"
        self.assertEqual(self.client.get(held_url, {"import_batch": initial["batch_id"]}).data["count"], 5)
        before = {
            row.timestamp: (row.pk, row.created_at)
            for row in QuarantinedReading.objects.all()
        }
        replacement = build_block(CONS_ID, "".join(observation(s, str(s + 10), "21") for s in range(1, 6)),
                                  end="2025-06-02T23:15:00Z")
        with unittest_mock.patch.object(sdatch_importer, "PERSIST_BATCH_SIZE", 2), unittest_mock.patch.object(
            QuarantinedReading.objects, "bulk_create", wraps=QuarantinedReading.objects.bulk_create,
        ) as update:
            response = self._import(build_e66(
                [replacement], status="5", creation="2025-06-06T15:40:05Z", delivery_id="HELD-REPLACEMENT",
            ))
        self.assertEqual(response.data["result_counts"]["quarantine_overwritten"], 5)
        self.assertEqual([len(call.args[0]) for call in update.call_args_list], [2, 2, 1])
        for slot, row in enumerate(QuarantinedReading.objects.order_by("timestamp"), 1):
            self.assertEqual((row.pk, row.created_at), before[row.timestamp])
            self.assertEqual(row.energy_kwh, Decimal(slot + 10))
            self.assertEqual(row.source_delivery_id, "HELD-REPLACEMENT")
            self.assertEqual(str(row.import_batch), response.data["batch_id"])
        replacement_batch = response.data["batch_id"]
        self.assertEqual(self.client.get(held_url, {"import_batch": initial["batch_id"]}).data["count"], 0)
        remaining = self.client.get(held_url, {"import_batch": replacement_batch}).data
        self.assertEqual(remaining["count"], 5)
        self.assertEqual(remaining["results"][0]["source_delivery_id"], "HELD-REPLACEMENT")

        promoted = build_block(CONS_ID, "".join(observation(s, str(s + 20)) for s in range(1, 6)),
                               end="2025-06-02T23:15:00Z")
        with unittest_mock.patch.object(sdatch_importer, "PERSIST_BATCH_SIZE", 2), unittest_mock.patch.object(
            QuarantinedReading.objects, "filter", wraps=QuarantinedReading.objects.filter,
        ) as selection:
            response = self._import(build_e66([promoted], status="5", creation="2025-06-07T15:40:05Z"))
        delete_batches = [call.kwargs["pk__in"] for call in selection.call_args_list if "pk__in" in call.kwargs]
        self.assertEqual([len(batch) for batch in delete_batches], [2, 2, 1])
        self.assertEqual({pk for batch in delete_batches for pk in batch}, {pk for pk, _ in before.values()})
        self.assertEqual(response.data["result_counts"]["promoted"], 5)
        self.assertFalse(QuarantinedReading.objects.exists())
        self.assertEqual(self.client.get(held_url, {"import_batch": replacement_batch}).data["count"], 0)
        historical = self.client.get(f"/api/v1/metering/import-logs/{initial['id']}/").data
        self.assertEqual(historical["result_counts"]["held"], 5)
        self.assertEqual(
            list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True)),
            [Decimal(s + 20) for s in range(1, 6)],
        )

    def test_later_batch_failure_rolls_back_creates_updates_and_provenance(self):
        original = build_block(CONS_ID, observation(1, "1", "21") + "".join(observation(s, "1") for s in range(2, 5)))
        self._import(build_e66([original]))
        before = list(MeterReading.objects.order_by("id").values())
        held_before = list(QuarantinedReading.objects.order_by("id").values())
        replacement = build_block(CONS_ID, "".join(observation(s, "2") for s in range(1, 5)))
        bulk_create = MeterReading.objects.bulk_create
        calls = 0

        def fail_later(rows, **kwargs):
            nonlocal calls
            if kwargs.get("update_conflicts"):
                calls += 1
                if calls == 2:
                    raise RuntimeError("Synthetic second-batch failure")
            return bulk_create(rows, **kwargs)

        with unittest_mock.patch.object(sdatch_importer, "PERSIST_BATCH_SIZE", 2), unittest_mock.patch.object(
            MeterReading.objects, "bulk_create", side_effect=fail_later,
        ):
            response = self._import(build_e66([replacement], status="5", creation="2025-06-06T15:40:05Z"))
        self.assertRejected(response, "internal_error")
        self.assertEqual(calls, 2)
        self.assertEqual(list(MeterReading.objects.order_by("id").values()), before)
        self.assertEqual(list(QuarantinedReading.objects.order_by("id").values()), held_before)
        self.assertEqual(response.data["reading_changes"], [])


class OfficialCustomerAcceptanceTests(StrictBase):
    """Full official customer example 1_4_4: 190 billable / 2 held / 192 skipped."""

    def test_full_customer_file_yields_expected_accounting(self):
        with open(FIXTURE_1_4_4, "rb") as fh:
            resp = self._upload("1_4_4.xml", fh.read())

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_total"], 384)
        self.assertEqual(resp.data["rows_imported"], 190)
        self.assertEqual(resp.data["rows_overwritten"], 0)
        self.assertEqual(resp.data["rows_skipped"], 192)
        counts = resp.data["result_counts"]
        self.assertEqual(
            counts,
            {
                "created": 190,
                "overwritten": 0,
                "held": 2,
                "promoted": 0,
                "duplicate": 0, "original_existing": 0,
                "stale": 0,
                "excluded": 192,
                "rejected": 0,
                "quarantine_overwritten": 0,
                "reading_changes_truncated": False,
            },
        )
        self.assertEqual(MeterReading.objects.count(), 190)
        self.assertEqual(QuarantinedReading.objects.count(), 2)

    def test_full_customer_file_sums_directions_quality_and_timestamps(self):
        from django.db.models import Sum

        with open(FIXTURE_1_4_4, "rb") as fh:
            resp = self._upload("1_4_4.xml", fh.read())
        self.assertEqual(resp.data["result_status"], "accepted")

        cons_sum = MeterReading.objects.filter(
            metering_point=self.cons_mp, direction=ReadingDirection.IN
        ).aggregate(total=Sum("energy_kwh"))["total"]
        prod_sum = MeterReading.objects.filter(
            metering_point=self.prod_mp, direction=ReadingDirection.OUT
        ).aggregate(total=Sum("energy_kwh"))["total"]
        # Independent of the importer: active totals minus the temporary seq1.
        self.assertEqual(cons_sum, Decimal("14060.102"))
        self.assertEqual(prod_sum, Decimal("33060.302"))

        stamps = list(MeterReading.objects.order_by("timestamp").values_list("timestamp", flat=True))
        # seq1 (22:00) is temporary and held back, so billing starts at 22:15.
        self.assertEqual(stamps[0], datetime(2025, 6, 2, 22, 15, tzinfo=timezone.utc))
        self.assertEqual(stamps[-1], datetime(2025, 6, 3, 21, 45, tzinfo=timezone.utc))
        self.assertEqual(len(set(stamps)), 95)  # seq1 held back per active block
        # Canonical interval-start range over every observation, held included.
        held_stamps = list(QuarantinedReading.objects.values_list("timestamp", flat=True))
        self.assertEqual(min(stamps[0], *held_stamps), datetime(2025, 6, 2, 22, 0, tzinfo=timezone.utc))

        estimated = MeterReading.objects.filter(condition="56")
        self.assertEqual(estimated.count(), 2)  # E88/56 stays billable with quality kept
        measured = MeterReading.objects.filter(condition="")
        self.assertEqual(measured.count(), 188)

        held = list(QuarantinedReading.objects.order_by("metering_point__meter_id"))
        self.assertEqual([(q.energy_kwh, q.condition) for q in held],
                         [(Decimal("100.0000"), "21"), (Decimal("300.0000"), "21")])
        self.assertTrue(all(q.timestamp == TS0 for q in held))
        # Temporary 400 kWh never enter billing.
        self.assertEqual(sum(q.energy_kwh for q in held), Decimal("400.0000"))

    def test_full_customer_file_provenance_and_change_signal(self):
        with open(FIXTURE_1_4_4, "rb") as fh:
            resp = self._upload("1_4_4.xml", fh.read())

        sample = MeterReading.objects.filter(metering_point=self.cons_mp).first()
        self.assertEqual(sample.source_creation, datetime(2025, 6, 5, 15, 40, 5, tzinfo=timezone.utc))
        self.assertTrue(sample.source_document_id.startswith("Beispiel_Messdatenaustausch_1_4_4"))
        self.assertEqual(sample.source_delivery_id, "Beispiel_Messdatenaustausch_1_4_4")
        self.assertEqual(sample.business_reason, "E88")
        self.assertEqual(sample.source_product, ACTIVE_PRODUCT)
        self.assertEqual(sample.source_unit, "KWH")
        self.assertEqual(sample.source_meter_id, CONS_ID)
        self.assertEqual(sample.import_source, ImportSource.SDATCH)
        self.assertIsNotNone(sample.import_batch)

        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.source_delivery["delivery_id"], "Beispiel_Messdatenaustausch_1_4_4")
        self.assertEqual(log.source_delivery["reason"], "E88")
        self.assertEqual(log.source_delivery["status"], "9")
        self.assertEqual(log.source_delivery["sender_role"], "MDR")

        changes = resp.data["reading_changes"]
        self.assertEqual(len(changes), 190)
        self.assertTrue(all(c["kind"] == "availability" for c in changes))
        self.assertTrue(all(c["old_energy"] is None for c in changes))

        codes = [issue["code"] for issue in resp.data["issues"]]
        self.assertIn("reactive_excluded", codes)
        self.assertTrue(all({"code", "severity", "message"} <= set(issue) for issue in resp.data["issues"]))


class StrictUnitTests(StrictBase):
    def test_out_of_range_volumes_are_rejected_before_rounding(self):
        for volume in ("123456789012345678901234567890", "100000000"):
            with self.subTest(volume=volume):
                block = build_block(CONS_ID, observation(1, volume) + "".join(observation(s, "10") for s in range(2, 5)))
                resp = self._import(build_e66([block]))
                self.assertRejected(resp, "invalid_volume")
                issue = resp.data["issues"][0]
                self.assertEqual(issue["detail_code"], "volume_out_of_range")
                self.assertEqual(issue["volume"], volume)
                self.assertEqual(issue["volume_limit"], str(sdatch_importer.MAX_ENERGY_KWH))
                self.assertEqual(MeterReading.objects.count(), 0)

    def test_derived_kwt_unit_rejects_whole_file(self):
        # Regression: schema-valid KWT must never be stored as kWh.
        block = build_block(CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), unit="KWT")

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "unsupported_unit")
        self.assertIn("KWT", resp.data["errors"][0]["error"])

    def test_derived_kwh_unit_is_billed(self):
        block = build_block(CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), unit="KWH")

        resp = self._import(build_e66([block]))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_imported"], 4)

    def test_derived_other_supported_product_rejects_file(self):
        # 8716867000016 passes the XSD enumeration but has no billing meaning here.
        block = build_block(
            CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), product="8716867000016"
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "unknown_product")

    def test_derived_garbage_product_is_schema_rejected(self):
        block = build_block(
            CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), product="9999999999999"
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "schema_invalid")
        self.assertIn("Schema validation failed", resp.data["errors"][0]["error"])

    def test_derived_leg_product_is_excluded_with_named_issue(self):
        block = build_block(
            CONS_ID,
            "".join(observation(s, "10") for s in range(1, 5)),
            product=LEG_PRODUCT,
            product_scheme="VSENationalCode",
            product_agency="260",
        )

        resp = self._import(build_e66([block]))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "unchanged")
        self.assertEqual(resp.data["result_counts"]["excluded"], 4)
        self.assertTrue(any(issue["code"] == "leg_excluded" for issue in resp.data["issues"]))
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_derived_nan_volume_is_schema_rejected(self):
        # The XSD decimal type already refuses NaN; the importer additionally
        # guards finiteness before any write. Either way: rejected, no writes.
        block = build_block(CONS_ID, observation(1, "NaN") + "".join(observation(s, "10") for s in range(2, 5)))

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "schema_invalid")

    def test_derived_negative_volume_rejects_file(self):
        block = build_block(CONS_ID, observation(1, "-5") + "".join(observation(s, "10") for s in range(2, 5)))

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "invalid_volume")
        self.assertEqual(resp.data["issues"][0]["detail_code"], "negative_volume")
        self.assertEqual(resp.data["issues"][0]["volume"], "-5")

    def test_derived_bad_condition_is_schema_rejected(self):
        block = build_block(
            CONS_ID, observation(1, "10", "99") + "".join(observation(s, "10") for s in range(2, 5))
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "schema_invalid")


FIXTURE_OUT_OF_ORDER = os.path.join(
    os.path.dirname(__file__), "test_fixtures", "sdatch", "e66_out_of_order_positions.xml"
)


class OutOfOrderPositionTests(StrictBase):
    """Issue #956: XML order must not move a value to a neighbouring interval.

    The fixture is self-authored for this regression: a two-slot block starting
    at an explicit ``2026-03-01T00:00:00Z``, with Position 2 listed before
    Position 1 and a distinct value and condition on each.
    """

    def test_derived_out_of_order_positions_keep_their_interval(self):
        with open(FIXTURE_OUT_OF_ORDER, "rb") as fh:
            resp = self._upload("out-of-order.xml", fh.read())

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_imported"], 2)

        readings = {
            reading.timestamp: reading
            for reading in MeterReading.objects.filter(metering_point=self.cons_mp)
        }
        first = readings[datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)]
        second = readings[datetime(2026, 3, 1, 0, 15, tzinfo=timezone.utc)]
        # Position 1 sits at 00:00 and Position 2 at 00:15, whatever order the
        # observations appear in.
        self.assertEqual(first.energy_kwh, Decimal("1.25"))
        self.assertEqual(first.condition, "56")
        self.assertEqual(second.energy_kwh, Decimal("2.5"))
        self.assertEqual(second.condition, "")
        self.assertFalse(QuarantinedReading.objects.exists())


class StrictPositionTests(StrictBase):
    def test_long_interval_with_missing_positions_has_bounded_diagnostics(self):
        block = build_block(CONS_ID, observation(1, "10"), end="2099-06-02T23:00:00Z")
        tracemalloc.start()
        try:
            resp = self._import(build_e66([block]))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertRejected(resp, "missing_position")
        self.assertLess(peak, 10 * 1024 * 1024)
        issue = next(issue for issue in resp.data["issues"] if issue["code"] == "missing_position")
        self.assertEqual(len(issue["missing"]), 50)
        expected = int((datetime(2099, 6, 2, 23, tzinfo=timezone.utc) - TS0).total_seconds() // 900)
        self.assertEqual(issue["expected_positions"], expected)
        self.assertEqual(issue["missing_count"], expected - 1)

    def _four_slot(self, observations, **kwargs):
        return self._import(build_e66([build_block(CONS_ID, observations, **kwargs)]))

    def test_derived_out_of_range_position_rejects_file(self):
        # Regression: seq 999 in a 4-slot block must not write outside it.
        obs = "".join(observation(s, "10") for s in range(1, 4)) + observation(999, "10")

        resp = self._four_slot(obs)

        self.assertRejected(resp, "invalid_position")
        self.assertEqual(resp.data["issues"][0]["position"], "999")
        self.assertEqual(resp.data["issues"][0]["expected_positions"], 4)

    def test_derived_gap_rejects_file_without_inventing_readings(self):
        obs = observation(1, "10") + observation(2, "10") + observation(3, "10") + observation(5, "10")

        resp = self._four_slot(obs)

        self.assertRejected(resp)
        codes = [issue["code"] for issue in resp.data["issues"]]
        self.assertIn("invalid_position", codes)

    def test_derived_missing_position_rejects_file(self):
        obs = "".join(observation(s, "10") for s in range(1, 4))  # seq4 absent

        resp = self._four_slot(obs)

        self.assertRejected(resp, "missing_position")
        self.assertIn("4", resp.data["errors"][0]["error"])
        self.assertEqual(resp.data["issues"][0]["missing_count"], 1)
        self.assertEqual(resp.data["issues"][0]["expected_positions"], 4)

    def test_derived_duplicate_position_rejects_file(self):
        obs = "".join(observation(s, "10") for s in range(1, 5)) + observation(2, "10")

        resp = self._four_slot(obs)

        self.assertRejected(resp, "duplicate_position")

    def test_derived_conflicting_overlap_rejects_file(self):
        first = build_block(CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), doc="BLOCK-A")
        second = build_block(CONS_ID, "".join(observation(s, "99") for s in range(1, 5)), doc="BLOCK-B")

        resp = self._import(build_e66([first, second]))

        self.assertRejected(resp, "conflicting_position")
        self.assertEqual(resp.data["issues"][0]["block_id"], "BLOCK-B")
        self.assertEqual(resp.data["issues"][0]["other_block_id"], "BLOCK-A")

    def test_derived_zero_position_is_schema_rejected(self):
        obs = observation(0, "10") + "".join(observation(s, "10") for s in range(2, 5))

        resp = self._four_slot(obs)

        self.assertRejected(resp, "schema_invalid")

    def test_derived_unaligned_interval_rejects_file(self):
        block = build_block(
            CONS_ID,
            "".join(observation(s, "10") for s in range(1, 5)),
            start="2025-06-02T22:07:00Z",
            end="2025-06-02T23:07:00Z",
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "unaligned_interval")
        self.assertEqual(resp.data["issues"][0]["interval_start"], "2025-06-02T22:07:00Z")
        self.assertEqual(resp.data["issues"][0]["interval_end"], "2025-06-02T23:07:00Z")

    def test_derived_indivisible_interval_rejects_file(self):
        block = build_block(
            CONS_ID,
            "".join(observation(s, "10") for s in range(1, 5)),
            start="2025-06-02T22:00:00Z",
            end="2025-06-02T22:50:00Z",
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "unaligned_interval")

    def test_valid_early_plus_invalid_late_block_rolls_back_everything(self):
        good = quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, doc="GOOD")
        bad = build_block(
            PROD_ID,
            "".join(observation(s, "10") for s in range(1, 4)),
            doc="BAD",
            point="ProductionMeteringPoint",
        )

        resp = self._import(build_e66([good, bad]))

        self.assertRejected(resp, "missing_position")
        self.assertTrue(resp.data["errors"], "failure log must be preserved")
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        self.assertEqual(resp.data["result_counts"]["rejected"], 7)
        self.assertEqual(resp.data["rows_total"], 7)
        self.assertEqual(resp.data["reading_changes"], [])
        log = ImportLog.objects.get(id=resp.data["id"])
        self.assertEqual(log.result_status, "rejected")
        self.assertTrue(log.errors)


class StrictHeaderTests(StrictBase):
    C38 = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'
    C40 = '<rsm:VSENationalCode>C40</rsm:VSENationalCode>'
    C23 = '<rsm:VSENationalCode>C23</rsm:VSENationalCode>'

    def _four_slot(self, **kwargs):
        return build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)], **kwargs)

    def test_derived_hourly_resolution_is_rejected(self):
        block = build_block(
            CONS_ID,
            "".join(observation(s, "10") for s in range(1, 5)),
            start="2025-06-02T22:00:00Z",
            end="2025-06-03T02:00:00Z",
            resolution="60",
        )

        resp = self._import(build_e66([block]))

        # The 1.6 XSD fixes Resolution at 15/MIN: hourly is not normative 1.6
        # and must never slip through a structural fallback.
        self.assertRejected(resp)
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_derived_offset_less_interval_is_rejected(self):
        block = build_block(
            CONS_ID,
            "".join(observation(s, "10") for s in range(1, 5)),
            start="2025-06-02T22:00:00",
            end="2025-06-02T23:00:00",
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp)

    def test_derived_wrong_namespace_is_rejected(self):
        resp = self._import(self._four_slot(namespace="http://example.com"))

        self.assertRejected(resp, "unsupported_root")
        self.assertEqual(resp.data["issues"][0]["detail_code"], "wrong_namespace")
        self.assertEqual(resp.data["issues"][0]["namespace"], "http://example.com")
        self.assertEqual(resp.data["issues"][0]["root_element"], "ValidatedMeteredData_16")

    def test_derived_older_schema_version_is_rejected(self):
        resp = self._import(self._four_slot(root="ValidatedMeteredData_15"))

        self.assertRejected(resp, "unsupported_schema_version")
        self.assertEqual(resp.data["issues"][0]["root_element"], "ValidatedMeteredData_15")

    def test_derived_unknown_status_is_schema_rejected(self):
        resp = self._import(self._four_slot(status="7"))

        self.assertRejected(resp, "schema_invalid")
        issue = resp.data["issues"][0]
        self.assertGreater(issue["xml_line"], 0)
        self.assertIn("Status", issue["xml_path"])
        self.assertTrue(issue["xml_error_type"].startswith("SCHEMAV_"))

    def test_derived_cancellation_names_cancellation(self):
        resp = self._import(self._four_slot(status="1"))

        self.assertRejected(resp, "cancellation_rejected")
        self.assertIn("cancellation", resp.data["errors"][0]["error"].lower())

    def test_derived_e66_schema_permits_original_and_replace_but_not_cancellation(self):
        schema = sdatch_importer._load_schema_16()
        for status in ("9", "5"):
            with self.subTest(status=status):
                schema.assertValid(etree.fromstring(self._four_slot(status=status)))
        with self.assertRaisesRegex(etree.DocumentInvalid, "Status"):
            schema.assertValid(etree.fromstring(self._four_slot(status="1")))

    def test_derived_missing_creation_is_rejected(self):
        xml = self._four_slot().replace(b"<rsm:Creation>2025-06-05T15:40:05Z</rsm:Creation>", b"")

        resp = self._import(xml)

        self.assertRejected(resp)

    def test_derived_missing_reason_is_rejected(self):
        import re

        xml = self._four_slot()
        xml = re.sub(rb"<rsm:BusinessReasonType.*?</rsm:BusinessReasonType>", b"", xml, flags=re.S)

        resp = self._import(xml)

        self.assertRejected(resp)

    def test_derived_missing_interval_is_rejected(self):
        block = build_block(
            CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), omit_interval=True
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "missing_interval")
        self.assertEqual(resp.data["issues"][0]["block_id"], "DERIVED-BLOCK")

    def test_derived_missing_point_is_rejected(self):
        block = build_block(
            CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), omit_point=True
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "missing_meter_point")


class StrictProfileTests(StrictBase):
    C38 = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'
    C40 = '<rsm:VSENationalCode>C40</rsm:VSENationalCode>'
    C23 = '<rsm:VSENationalCode>C23</rsm:VSENationalCode>'
    E44 = '<rsm:ebIXCode>E44</rsm:ebIXCode>'

    def _four(self, **kwargs):
        return quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, **kwargs)

    def test_derived_temporary_only_file_is_held(self):
        obs = "".join(observation(s, "10", "21") for s in range(1, 5))

        resp = self._import(build_e66([build_block(CONS_ID, obs)]))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "held")
        self.assertEqual(resp.data["rows_imported"], 0)
        self.assertEqual(resp.data["result_counts"]["held"], 4)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 4)

    def test_derived_c38_file_is_held_not_billed(self):
        resp = self._import(build_e66([self._four()], reason_xml=self.C38))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "held")
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 4)
        self.assertTrue(all(q.business_reason == "C38" for q in QuarantinedReading.objects.all()))

    def test_derived_c40_community_profile_is_named_unsupported(self):
        resp = self._import(build_e66([self._four()], reason_xml=self.C40))

        self.assertRejected(resp, "unsupported_reason")
        self.assertIn("C40", resp.data["errors"][0]["error"])
        self.assertIn("C40", resp.data["errors"][0]["error"])

    def test_derived_query_profile_is_named_unsupported(self):
        resp = self._import(build_e66([self._four()], reason_xml=self.C23))

        self.assertRejected(resp, "unsupported_reason")
        self.assertIn("C23", resp.data["errors"][0]["error"])

    def test_derived_e66_root_alone_does_not_imply_support(self):
        # Valid E66 root, valid blocks, unsupported market role: no writes.
        resp = self._import(build_e66([self._four()], reason_xml=self.E44))

        self.assertRejected(resp, "unsupported_reason")
        self.assertEqual(resp.data["rows_total"], 0)

    def test_derived_exchange_only_file_is_unchanged_with_named_issue(self):
        block = build_block(
            "CH9999901234500000000000000000033",
            "".join(observation(s, "10") for s in range(1, 5)),
            point="ExchangeMeteringPoint",
            start="2025-06-05T22:00:00Z",
            end="2025-06-05T23:00:00Z",
        )

        resp = self._import(build_e66([block]))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "unchanged")
        self.assertEqual(resp.data["result_counts"]["excluded"], 4)
        self.assertTrue(any(issue["code"] == "exchange_excluded" for issue in resp.data["issues"]))
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_derived_hkn_style_totals_are_rejected_without_inventing_slots(self):
        # Irregular multi-month single-observation delivery without usable
        # resolution: must never become quarter-hour slots.
        block = build_block(
            CONS_ID,
            observation(1, "12345"),
            start="2025-01-01T00:00:00Z",
            end="2025-04-01T00:00:00Z",
            omit_resolution=True,
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "missing_resolution")
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_derived_sparse_delivery_with_resolution_is_rejected(self):
        block = build_block(
            CONS_ID,
            observation(1, "10"),
            start="2025-01-01T00:00:00Z",
            end="2025-01-02T00:00:00Z",
        )

        resp = self._import(build_e66([block]))

        self.assertRejected(resp, "missing_position")


class RevisionTests(StrictBase):
    def test_resolution_change_is_a_billing_input_change(self):
        self._import(build_e66([self._four()]))
        MeterReading.objects.filter(timestamp=TS0).update(resolution="hourly")
        resp = self._import(self._replace_four(["101", "102", "103", "104"], creation="2025-06-06T10:00:00Z"))
        changed = next(change for change in resp.data["reading_changes"] if change["timestamp"] == TS0.isoformat())
        self.assertEqual(changed["kind"], "value")
        self.assertEqual(changed["old_energy"], changed["new_energy"])

    def _four(self, **kwargs):
        return quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, **kwargs)

    def _replace_four(self, values, *, creation, status="5", delivery_id="DERIVED-REPL"):
        obs = "".join(observation(s, v) for s, v in zip(range(1, 5), values))
        return build_e66(
            [build_block(CONS_ID, obs, doc="DERIVED-REPL-C")],
            status=status,
            creation=creation,
            delivery_id=delivery_id,
        )

    def test_newer_and_stale_replacements_in_both_orders(self):
        for first_creation, second_creation, expected in (
            ("2025-06-04T10:00:00Z", "2025-06-06T10:00:00Z",
             [Decimal("210"), Decimal("211"), Decimal("212"), Decimal("213")]),
            ("2025-06-06T10:00:00Z", "2025-06-04T10:00:00Z",
             [Decimal("200"), Decimal("201"), Decimal("202"), Decimal("203")]),
        ):
            with self.subTest(first=first_creation, second=second_creation):
                MeterReading.objects.all().delete()
                QuarantinedReading.objects.all().delete()
                self._import(build_e66([self._four()]))
                self._import(self._replace_four(["200", "201", "202", "203"], creation=first_creation))
                resp = self._import(
                    self._replace_four(["210", "211", "212", "213"], creation=second_creation)
                )
                # Arrival order never wins: only Creation decides.
                got = [
                    r.energy_kwh
                    for r in MeterReading.objects.filter(metering_point=self.cons_mp).order_by("timestamp")
                ]
                self.assertEqual(got, expected)
                self.assertEqual(resp.status_code, 201)

    def test_equal_creation_identical_replay_is_idempotent(self):
        self._import(build_e66([self._four()]))
        before = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))

        resp = self._import(build_e66([self._four()], delivery_id="DERIVED-REPLAY"))

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["result_status"], "unchanged")
        self.assertEqual(resp.data["result_counts"]["duplicate"], 4)
        self.assertEqual(resp.data["reading_changes"], [])
        after = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))
        self.assertEqual(before, after)

    def test_equal_creation_conflict_rejects_file_and_exposes_both_documents(self):
        self._import(build_e66([self._four()], delivery_id="DERIVED-ORIG"))
        before = {
            (r.timestamp, r.energy_kwh)
            for r in MeterReading.objects.filter(metering_point=self.cons_mp)
        }

        resp = self._import(
            self._replace_four(
                ["200", "201", "202", "203"],
                creation="2025-06-05T15:40:05Z",  # same Creation as the original
                delivery_id="DERIVED-CONFLICT",
            )
        )

        self.assertRejected(resp, "equal_creation_conflict")
        conflict = next(i for i in resp.data["issues"] if i["code"] == "equal_creation_conflict")
        self.assertEqual(conflict["incoming_document_id"], "DERIVED-REPL-C")
        self.assertEqual(conflict["incoming_delivery_id"], "DERIVED-CONFLICT")
        self.assertIn("DERIVED", conflict["stored_document_id"])
        self.assertEqual(conflict["stored_delivery_id"], "DERIVED-ORIG")
        self.assertEqual(conflict["creation"], "2025-06-05T15:40:05+00:00")
        self.assertEqual(resp.data["reading_changes"], [])
        after = {
            (r.timestamp, r.energy_kwh)
            for r in MeterReading.objects.filter(metering_point=self.cons_mp)
        }
        self.assertEqual(before, after)

    def test_original_with_newer_creation_does_not_overwrite(self):
        self._import(build_e66([self._four()]))
        before = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))

        # Status=9 originals never overwrite, even with a newer Creation:
        # corrections arrive as Status=5.
        resp = self._import(
            self._replace_four(
                ["200", "201", "202", "203"], creation="2025-06-09T10:00:00Z", status="9"
            )
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["rows_overwritten"], 0)
        self.assertEqual(resp.data["result_counts"]["original_existing"], 4)
        after = list(MeterReading.objects.order_by("timestamp").values_list("energy_kwh", flat=True))
        self.assertEqual(before, after)

    def test_legacy_null_provenance_is_replaced_by_dated_delivery(self):
        MeterReading.objects.create(
            metering_point=self.cons_mp,
            timestamp=datetime(2025, 6, 2, 22, 15, tzinfo=timezone.utc),
            direction=ReadingDirection.IN,
            energy_kwh=Decimal("9.0000"),
            import_source=ImportSource.SDATCH,
            source_creation=None,
            source_document_id="LEGACY",
        )
        block = build_block(
            CONS_ID,
            observation(1, "50") + "".join(observation(s, str(100 + s)) for s in range(2, 5)),
        )

        resp = self._import(build_e66([block], status="5", creation="2025-06-06T10:00:00Z"))

        # NULL provenance counts as older than any dated delivery.
        self.assertEqual(resp.status_code, 201)
        row = MeterReading.objects.get(
            metering_point=self.cons_mp,
            timestamp=datetime(2025, 6, 2, 22, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(row.energy_kwh, Decimal("102.0000"))
        self.assertIsNotNone(row.source_creation)

    def test_value_availability_and_metadata_changes_are_distinguished(self):
        self._import(build_e66([self._four()], delivery_id="DERIVED-ORIG"))
        # Value change on two slots, identical value (metadata-only) on two.
        resp = self._import(
            self._replace_four(
                ["101", "102", "999", "998"], creation="2025-06-06T10:00:00Z"
            )
        )

        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_overwritten"], 4)
        by_ts = {c["timestamp"]: c for c in resp.data["reading_changes"]}
        self.assertEqual(len(by_ts), 4)
        kinds = sorted(c["kind"] for c in by_ts.values())
        self.assertEqual(kinds, ["metadata", "metadata", "value", "value"])
        for change in by_ts.values():
            if change["kind"] == "metadata":
                self.assertEqual(change["old_energy"], change["new_energy"])
            else:
                self.assertNotEqual(change["old_energy"], change["new_energy"])

    def test_promotion_is_an_availability_change_without_double_count(self):
        self._import(
            build_e66([self._four()], reason_xml='<rsm:VSENationalCode>C38</rsm:VSENationalCode>')
        )
        self.assertEqual(QuarantinedReading.objects.count(), 4)

        resp = self._import(build_e66([self._four()], delivery_id="DERIVED-PROMOTE"))

        counts = resp.data["result_counts"]
        self.assertEqual(counts["created"], 4)
        self.assertEqual(counts["promoted"], 4)
        self.assertEqual(resp.data["rows_imported"], 4)  # no double count on top
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        changes = resp.data["reading_changes"]
        self.assertEqual(len(changes), 4)
        self.assertTrue(all(c["kind"] == "availability" and c["promoted"] for c in changes))


class FreshnessSeparationTests(StrictBase):
    C38 = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'

    def _four(self, **kwargs):
        return quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, **kwargs)

    def test_newer_held_does_not_block_validated_billing(self):
        self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-06T10:00:00Z")
        )
        self.assertEqual(QuarantinedReading.objects.count(), 4)

        # Older validated delivery still lands in billing; the newer held
        # discrepancy stays visible instead of being silently deleted.
        resp = self._import(build_e66([self._four()], creation="2025-06-04T10:00:00Z"))

        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_imported"], 4)
        self.assertEqual(resp.data["result_counts"]["promoted"], 0)
        self.assertEqual(MeterReading.objects.count(), 4)
        self.assertEqual(QuarantinedReading.objects.count(), 4)

    def test_billable_promotes_only_predecessors(self):
        self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-04T10:00:00Z")
        )

        resp = self._import(build_e66([self._four()], creation="2025-06-06T10:00:00Z"))

        self.assertEqual(resp.data["result_counts"]["promoted"], 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_equal_creation_billable_wins_over_quarantine(self):
        self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-05T15:40:05Z")
        )

        resp = self._import(build_e66([self._four()], creation="2025-06-05T15:40:05Z"))

        self.assertEqual(resp.data["rows_imported"], 4)
        self.assertEqual(resp.data["result_counts"]["promoted"], 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)

    def test_stale_info_does_not_shadow_validated_billing(self):
        self._import(build_e66([self._four()], creation="2025-06-06T10:00:00Z"))
        self.assertEqual(MeterReading.objects.count(), 4)

        resp = self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-04T10:00:00Z")
        )

        self.assertEqual(resp.data["result_status"], "unchanged")
        self.assertEqual(resp.data["result_counts"]["stale"], 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        self.assertEqual(MeterReading.objects.count(), 4)

    def test_newer_info_stays_visible_next_to_billing(self):
        self._import(build_e66([self._four()], creation="2025-06-04T10:00:00Z"))

        resp = self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-06T10:00:00Z")
        )

        self.assertEqual(resp.data["result_status"], "held")
        self.assertEqual(resp.data["result_counts"]["held"], 4)
        self.assertEqual(MeterReading.objects.count(), 4)
        self.assertEqual(QuarantinedReading.objects.count(), 4)


class QuarantineLifecycleTests(StrictBase):
    C38 = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'

    def _four(self, **kwargs):
        return quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, **kwargs)

    def test_quarantine_replacement_is_counted_as_protection_evidence(self):
        self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-04T10:00:00Z")
        )
        obs = "".join(observation(s, str(200 + s)) for s in range(1, 5))
        block = build_block(CONS_ID, obs)

        resp = self._import(
            build_e66([block], status="5", reason_xml=self.C38, creation="2025-06-06T10:00:00Z")
        )

        counts = resp.data["result_counts"]
        self.assertEqual(resp.data["result_status"], "held")
        self.assertEqual(counts["held"], 4)
        self.assertEqual(counts["quarantine_overwritten"], 4)
        self.assertEqual(
            QuarantinedReading.objects.get(
                metering_point=self.cons_mp,
                timestamp=datetime(2025, 6, 2, 22, 0, tzinfo=timezone.utc),
            ).energy_kwh,
            Decimal("201.0000"),
        )

    def test_quarantine_rows_carry_full_provenance(self):
        self._import(
            build_e66([self._four()], reason_xml=self.C38, delivery_id="DERIVED-INFO")
        )

        row = QuarantinedReading.objects.first()
        self.assertEqual(row.business_reason, "C38")
        self.assertEqual(row.source_delivery_id, "DERIVED-INFO")
        self.assertIsNotNone(row.source_creation)
        self.assertEqual(row.source_product, ACTIVE_PRODUCT)
        self.assertEqual(row.source_unit, "KWH")
        self.assertEqual(row.source_meter_id, CONS_ID)
        self.assertIsNotNone(row.import_batch)

    def test_quarantine_never_leaks_into_billing_totals(self):
        from django.db.models import Sum

        self._import(
            build_e66([self._four()], reason_xml=self.C38, creation="2025-06-04T10:00:00Z")
        )
        total = MeterReading.objects.filter(metering_point=self.cons_mp).aggregate(
            total=Sum("energy_kwh")
        )["total"]
        self.assertIsNone(total)


class ResultContractTests(StrictBase):
    def test_failure_after_writes_clears_committed_counters(self):
        finalize = sdatch_importer._finalize_log

        def failed_finalize(*args, **kwargs):
            finalize(*args, **kwargs)
            raise RuntimeError("Simulated failure before transaction commit")

        for reason in ("<rsm:ebIXCode>E88</rsm:ebIXCode>", "<rsm:VSENationalCode>C38</rsm:VSENationalCode>"):
            with self.subTest(reason=reason), unittest_mock.patch.object(sdatch_importer, "_finalize_log", failed_finalize):
                resp = self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)], reason_xml=reason))
            self.assertRejected(resp, "internal_error")
            self.assertEqual(MeterReading.objects.count(), 0)
            self.assertEqual(QuarantinedReading.objects.count(), 0)
            self.assertEqual(resp.data["reading_changes"], [])
            self.assertEqual(resp.data["warnings"], [])
            self.assertEqual(resp.data["result_counts"]["created"], 0)
            self.assertEqual(resp.data["result_counts"]["held"], 0)
            self.assertEqual(resp.data["result_counts"]["rejected"], 4)

    def test_response_carries_structured_contract_fields(self):
        resp = self._import(
            build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)])
        )

        for key in (
            "result_status",
            "result_counts",
            "issues",
            "reading_changes",
            "source_delivery",
        ):
            self.assertIn(key, resp.data, f"ImportLog response must carry {key}")
        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(
            set(resp.data["result_counts"]),
            {
                "created", "overwritten", "held", "promoted", "duplicate",
                "original_existing",
                "stale", "excluded", "rejected", "quarantine_overwritten",
                "reading_changes_truncated",
            },
        )

    def test_rejection_counts_unparsed_later_blocks(self):
        bad = build_block(CONS_ID, "".join(observation(position, "10") for position in range(1, 4)))
        later = quarter_block(PROD_ID, "2025-06-02T22:00:00Z", 4, point="ProductionMeteringPoint")
        resp = self._import(build_e66([bad, later]))
        self.assertRejected(resp, "missing_position")
        self.assertEqual(resp.data["rows_total"], 7)
        self.assertEqual(resp.data["result_counts"]["rejected"], 7)

    def test_counter_identity_for_accepted_and_rejected_files(self):
        good = self._import(
            build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)])
        )
        counts = good.data["result_counts"]
        accounted = (
            counts["created"] + counts["overwritten"] + counts["held"]
            + counts["duplicate"] + counts["stale"] + counts["excluded"]
        )
        self.assertEqual(accounted, good.data["rows_total"])
        self.assertEqual(counts["rejected"], 0)

        bad_block = build_block(CONS_ID, "".join(observation(s, "10") for s in range(1, 4)))
        bad = self._import(build_e66([bad_block]))
        bad_counts = bad.data["result_counts"]
        self.assertEqual(
            bad_counts["excluded"] + bad_counts["rejected"], bad.data["rows_total"]
        )

    def test_multi_file_uploads_stay_independent(self):
        good_resp = self._import(
            build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)])
        )
        self.assertEqual(good_resp.data["result_status"], "accepted")

        bad_block = build_block(
            PROD_ID,
            "".join(observation(s, "10") for s in range(1, 4)),
            point="ProductionMeteringPoint",
        )
        bad_resp = self._import(build_e66([bad_block]))

        self.assertEqual(bad_resp.data["result_status"], "rejected")
        # The earlier file's readings are untouched by the later rejection.
        self.assertEqual(MeterReading.objects.count(), 4)
        self.assertEqual(ImportLog.objects.count(), 2)

    def test_csv_overlap_rejects_quarantine_planned_slots_too(self):
        MeterReading.objects.create(
            metering_point=self.cons_mp,
            timestamp=datetime(2025, 6, 2, 22, 0, tzinfo=timezone.utc),
            direction=ReadingDirection.IN,
            energy_kwh=Decimal("9.0000"),
            import_source=ImportSource.MANUAL,
        )
        obs = "".join(observation(s, "10", "21") for s in range(1, 5))

        resp = self._import(
            build_e66(
                [build_block(CONS_ID, obs)],
                reason_xml='<rsm:VSENationalCode>C38</rsm:VSENationalCode>',
            )
        )

        self.assertRejected(resp, "source_conflict")
        row = MeterReading.objects.get(
            metering_point=self.cons_mp,
            timestamp=datetime(2025, 6, 2, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(row.energy_kwh, Decimal("9.0000"))


class AmbiguityTests(StrictBase):
    def test_legacy_cross_column_collision_rejects_file(self):
        other = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH9999901234500000000000000000099",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        # Legacy / direct-DB state current validation forbids: bypass it.
        MeteringPoint.objects.filter(pk=other.pk).update(secondary_meter_id=CONS_ID)

        resp = self._import(
            build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4)])
        )

        self.assertRejected(resp, "ambiguous_meter")
        self.assertIn(CONS_ID, resp.data["errors"][0]["error"])

    def test_primary_plus_alias_of_same_point_is_a_within_file_duplicate(self):
        self.cons_mp.secondary_meter_id = "CH9999901234500000000000000000098"
        self.cons_mp.save(update_fields=["secondary_meter_id"])
        first = build_block(
            CONS_ID, "".join(observation(s, "10") for s in range(1, 5)), doc="BLOCK-PRIMARY"
        )
        second = build_block(
            "CH9999901234500000000000000000098",
            "".join(observation(s, "10") for s in range(1, 5)),
            doc="BLOCK-ALIAS",
        )

        resp = self._import(build_e66([first, second]))

        # Both identities resolve to the same point: the slot is delivered
        # twice, which is a duplicate even though the values agree.
        self.assertRejected(resp, "duplicate_position")
        self.assertEqual(resp.data["issues"][0]["block_id"], "BLOCK-ALIAS")
        self.assertEqual(resp.data["issues"][0]["other_block_id"], "BLOCK-PRIMARY")


class SecurityLimitTests(StrictBase):
    def test_compressed_upload_without_size_hint_is_read_with_a_limit(self):
        from io import BytesIO

        content = gzip.compress(build_e66([self._four()]))
        upload = BytesIO(content)
        upload.name = "bounded.xml.gz"
        with unittest_mock.patch.object(sdatch_importer, "MAX_SDAT_BYTES", 10):
            with unittest_mock.patch.object(upload, "read", wraps=upload.read) as read:
                log = sdatch_importer.import_sdatch(upload, self.zev, self.owner)
        self.assertEqual(log.result_status, "rejected")
        self.assertEqual(log.issues[0]["code"], "file_too_large")
        self.assertNotIn("size_bytes", log.issues[0])
        self.assertEqual(log.issues[0]["limit_bytes"], 10)
        read.assert_called_once_with(11)

    def _four(self, **kwargs):
        return quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 4, **kwargs)

    def test_truncated_gzip_is_rejected(self):
        payload = gzip.compress(build_e66([self._four()]))[:-10]

        resp = self._upload("truncated.xml.gz", payload)

        self.assertRejected(resp, "gzip_error")
        self.assertIn("decompress", resp.data["errors"][0]["error"].lower())

    def test_decompressed_bomb_is_rejected(self):
        big = build_e66([self._four()]) * 40
        payload = gzip.compress(big)

        with unittest_mock.patch.object(sdatch_importer, "MAX_SDAT_DECOMPRESSED_BYTES", 100):
            resp = self._upload("bomb.xml.gz", payload)

        self.assertRejected(resp, "decompressed_too_large")
        self.assertNotIn("size_bytes", resp.data["issues"][0])
        self.assertEqual(resp.data["issues"][0]["limit_bytes"], 100)

    def test_actual_size_is_enforced_without_size_hint(self):
        upload = SimpleUploadedFile("big.xml", build_e66([self._four()]), content_type="application/xml")
        upload.size = None  # missing hint: the real byte count still applies.

        with unittest_mock.patch.object(sdatch_importer, "MAX_SDAT_BYTES", 10):
            resp = self.client.post(
                "/api/v1/metering/import/sdatch/",
                {"file": upload, "zev_id": str(self.zev.id)},
                format="multipart",
            )

        self.assertRejected(resp, "file_too_large")

    def test_external_entity_payload_is_rejected_safely(self):
        payload = (
            b"<?xml version='1.0' encoding='UTF-8'?>\n"
            b'<!DOCTYPE rsm:ValidatedMeteredData_16 [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
            + build_e66([self._four()])
        )

        resp = self._import(payload)

        self.assertRejected(resp)
        self.assertNotIn("root:", "".join(e["error"] for e in resp.data["errors"]))

    def test_entity_expansion_payload_does_not_hang_or_write(self):
        laughs = (
            b"<?xml version='1.0'?><!DOCTYPE l ["
            b'<!ENTITY a "1234567890">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
            b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">'
            b"]><l>&c;</l>"
        )

        resp = self._import(laughs)

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(MeterReading.objects.count(), 0)
        self.assertEqual(QuarantinedReading.objects.count(), 0)


class DstBoundaryTests(StrictBase):
    """Interval-start storage across Swiss calendar boundaries.

    Source timestamps describe interval ends; the backend stores interval
    starts (``start + (seq-1) * 15min``). These tests pin the mapping at
    92/96/100-slot days and civil boundaries.
    """

    def _day(self, start, count, **kwargs):
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end = (start_dt + timedelta(minutes=15 * count)).strftime("%Y-%m-%dT%H:%M:%SZ")
        obs = "".join(observation(seq, str(100 + seq)) for seq in range(1, count + 1))
        return build_e66(
            [build_block(CONS_ID, obs, start=start, end=end, doc="DERIVED-DAY")], **kwargs
        )

    def test_short_dst_day_has_92_slots(self):
        # Spring forward: 2025-03-30 is a 23-hour Swiss day.
        resp = self._import(self._day("2025-03-29T23:00:00Z", 92))

        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_imported"], 92)
        stamps = list(
            MeterReading.objects.order_by("timestamp").values_list("timestamp", flat=True)
        )
        self.assertEqual(stamps[0], datetime(2025, 3, 29, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(stamps[-1], datetime(2025, 3, 30, 21, 45, tzinfo=timezone.utc))
        self.assertEqual(len(stamps), 92)

    def test_long_dst_day_has_100_slots(self):
        # Fall back: 2025-10-26 is a 25-hour Swiss day.
        resp = self._import(self._day("2025-10-25T22:00:00Z", 100))

        self.assertEqual(resp.data["result_status"], "accepted")
        self.assertEqual(resp.data["rows_imported"], 100)
        stamps = list(
            MeterReading.objects.order_by("timestamp").values_list("timestamp", flat=True)
        )
        self.assertEqual(stamps[0], datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(stamps[-1], datetime(2025, 10, 26, 22, 45, tzinfo=timezone.utc))

    def test_leap_day_month_and_year_boundaries(self):
        cases = [
            ("2024-02-29T00:00:00Z", 4),  # leap day
            ("2025-01-31T23:00:00Z", 8),  # month boundary
            ("2024-12-31T23:00:00Z", 8),  # year boundary
        ]
        for start, count in cases:
            with self.subTest(start=start):
                MeterReading.objects.all().delete()
                resp = self._import(self._day(start, count))
                self.assertEqual(resp.data["result_status"], "accepted", resp.data.get("errors"))
                first = MeterReading.objects.order_by("timestamp").first()
                # Interval-start convention: seq1 lands exactly on block start.
                self.assertEqual(
                    first.timestamp,
                    datetime.fromisoformat(start.replace("Z", "+00:00")),
                )
                self.assertEqual(MeterReading.objects.count(), count)

    def test_midnight_tariff_boundary_keeps_slot_identity(self):
        resp = self._import(self._day("2025-06-02T23:00:00Z", 8))
        self.assertEqual(resp.data["result_status"], "accepted")

        stamps = sorted(
            MeterReading.objects.values_list("timestamp", flat=True)
        )
        self.assertEqual(stamps[4], datetime(2025, 6, 3, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(
            MeterReading.objects.get(timestamp=stamps[4]).energy_kwh, Decimal("105.0000")
        )


class InvoiceBillingRegressionTests(TestCase):
    """End-to-end billing safety: quarantine never billed, estimated billed
    with quality kept, promotion completes the billing input. Uses the
    invoice engine read-only; invoice impact workflows remain D's scope."""

    def setUp(self):
        from datetime import date

        from invoices.test_helpers import make_participant as _make_participant
        from invoices.test_helpers import make_zev as _make_zev
        from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
        from testing.helpers import clear_vat_rates

        clear_vat_rates()
        self.client = APIClient()
        self.owner = make_user("bill_owner", UserRole.USER)
        self.zev = _make_zev(self.owner, "Billing ZEV")
        # After the grant: promoting the account retires tokens minted before it.
        auth(self.client, self.owner)
        self.participant = _make_participant(self.zev, first="Bill", last="Case")
        self.participant.valid_from = date(2025, 6, 1)
        self.participant.save(update_fields=["valid_from"])
        self.cons_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=CONS_ID, meter_type=MeteringPointType.CONSUMPTION,
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.cons_mp, participant=self.participant,
            valid_from=date(2025, 6, 1),
        )
        self.tariff = Tariff.objects.create(
            zev=self.zev,
            name="Billing Grid",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID,
            valid_from=date(2025, 6, 1),
        )
        TariffPeriod.objects.create(
            tariff=self.tariff, period_type="flat", price_chf_per_kwh=Decimal("0.20000"),
        )

    def _upload(self, content):
        upload = SimpleUploadedFile("billing.xml", content, content_type="application/xml")
        return self.client.post(
            "/api/v1/metering/import/sdatch/",
            {"file": upload, "zev_id": str(self.zev.id)},
            format="multipart",
        )

    def test_estimated_billed_temporary_excluded_then_promotion_completes_input(self):
        from datetime import date

        from invoices.engine import generate_invoice

        obs = observation(1, "100", "21") + observation(2, "50", "56") + observation(3, "10") + observation(4, "10")
        resp = self._upload(build_e66([build_block(CONS_ID, obs)]))
        self.assertEqual(resp.data["result_status"], "accepted")

        invoice = generate_invoice(self.participant, date(2025, 6, 1), date(2025, 6, 30))
        item = invoice.items.get(description=self.tariff.name)
        # Estimated (56) is billable with quality kept; temporary (21) is not.
        self.assertEqual(item.quantity_kwh, Decimal("70.0000"))
        self.assertEqual(
            MeterReading.objects.get(
                metering_point=self.cons_mp,
                timestamp=datetime(2025, 6, 2, 22, 15, tzinfo=timezone.utc),
            ).condition,
            "56",
        )

        # A later billable delivery promotes the temporary slot into billing.
        promote = observation(1, "100") + observation(2, "50", "56") + observation(3, "10") + observation(4, "10")
        resp2 = self._upload(build_e66([build_block(CONS_ID, promote, doc="PROMOTE")]))
        self.assertEqual(resp2.data["result_counts"]["promoted"], 1)
        self.assertEqual(
            MeterReading.objects.filter(metering_point=self.cons_mp).count(), 4
        )


@unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL-only locking evidence")
class SdatConcurrencyTests(TransactionTestCase):
    """Concurrent revision selection on PostgreSQL.

    SQLite serializes writers at the database level, so it cannot prove the
    locking strategy; these tests are skipped anywhere but PostgreSQL and the
    completion report must state which backend ran them.
    """

    def setUp(self):
        self.owner = make_user("conc_owner", UserRole.USER)
        self.zev = create_managed_zev(
            name="Concurrency ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="K"
        )
        self.cons_mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id=CONS_ID, meter_type=MeteringPointType.CONSUMPTION,
        )
        self.zev_id = self.zev.pk
        self.owner_id = self.owner.pk

    def _file(self, values, *, creation, status="9", delivery_id="DERIVED"):
        obs = "".join(observation(s, v) for s, v in zip(range(1, 5), values))
        return build_e66(
            [build_block(CONS_ID, obs, doc=f"{delivery_id}-C")],
            status=status,
            creation=creation,
            delivery_id=delivery_id,
        )

    def _run_pair(self, payload_a, payload_b):
        """Import two files on two threads with a shared start barrier."""
        barrier = threading.Barrier(3)
        outcomes = {}

        def worker(name, payload):
            from django.db import connections

            connections.close_all()
            try:
                zev = Zev.objects.get(pk=self.zev_id)
                user = get_user_model().objects.get(pk=self.owner_id)
                barrier.wait(timeout=30)
                try:
                    log = sdatch_importer.import_sdatch(
                        SimpleUploadedFile(f"{name}.xml", payload, content_type="application/xml"),
                        zev,
                        user,
                    )
                    outcomes[name] = log
                except Exception as exc:  # noqa: BLE001 — surfaced below, never swallowed.
                    outcomes[name] = exc
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=("a", payload_a)),
            threading.Thread(target=worker, args=("b", payload_b)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=30)
        for thread in threads:
            thread.join(timeout=120)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "import thread did not finish")
        for name, outcome in outcomes.items():
            self.assertFalse(
                isinstance(outcome, Exception), f"thread {name} raised {outcome!r}"
            )
        return outcomes["a"], outcomes["b"]

    def test_concurrent_duplicate_originals_stay_idempotent(self):
        payload = self._file(["101", "102", "103", "104"], creation="2025-06-05T15:40:05Z")

        log_a, log_b = self._run_pair(payload, payload)

        statuses = sorted([log_a.result_status, log_b.result_status])
        self.assertEqual(statuses, ["accepted", "unchanged"])
        self.assertEqual(MeterReading.objects.count(), 4)
        self.assertEqual(
            ImportLog.objects.filter(result_status="accepted").count(), 1
        )

    def test_concurrent_older_and_newer_replacement_converges_on_newer(self):
        newer = self._file(
            ["210", "211", "212", "213"], creation="2025-06-06T10:00:00Z", status="5"
        )
        older = self._file(
            ["200", "201", "202", "203"], creation="2025-06-04T10:00:00Z", status="5"
        )

        self._run_pair(newer, older)

        got = [
            r.energy_kwh
            for r in MeterReading.objects.filter(metering_point=self.cons_mp).order_by("timestamp")
        ]
        self.assertEqual(got, [Decimal("210"), Decimal("211"), Decimal("212"), Decimal("213")])
        self.assertEqual(MeterReading.objects.count(), 4)

    def test_concurrent_equal_creation_conflict_accepts_exactly_one(self):
        first = self._file(
            ["210", "211", "212", "213"],
            creation="2025-06-06T10:00:00Z",
            status="5",
            delivery_id="DERIVED-RACE-A",
        )
        second = self._file(
            ["310", "311", "312", "313"],
            creation="2025-06-06T10:00:00Z",
            status="5",
            delivery_id="DERIVED-RACE-B",
        )

        log_a, log_b = self._run_pair(first, second)

        statuses = sorted([log_a.result_status, log_b.result_status])
        self.assertEqual(statuses, ["accepted", "rejected"])
        winner = log_a if log_a.result_status == "accepted" else log_b
        loser = log_b if winner is log_a else log_a
        self.assertTrue(
            any(i["code"] == "equal_creation_conflict" for i in loser.issues)
        )
        winning_values = (
            ["210", "211", "212", "213"]
            if winner.source_delivery.get("delivery_id") == "DERIVED-RACE-A"
            else ["310", "311", "312", "313"]
        )
        got_dec = [
            r.energy_kwh
            for r in MeterReading.objects.filter(metering_point=self.cons_mp).order_by("timestamp")
        ]
        self.assertEqual(got_dec, [Decimal(v) for v in winning_values])
        self.assertEqual(MeterReading.objects.count(), 4)

    def test_concurrent_promotion_runs_once(self):
        held_obs = "".join(observation(s, "10", "21") for s in range(1, 5))
        sdatch_importer.import_sdatch(
            SimpleUploadedFile("held.xml", build_e66([build_block(CONS_ID, held_obs)]),
                               content_type="application/xml"),
            Zev.objects.get(pk=self.zev_id),
            get_user_model().objects.get(pk=self.owner_id),
        )
        self.assertEqual(QuarantinedReading.objects.count(), 4)
        billable = self._file(["101", "102", "103", "104"], creation="2025-06-06T10:00:00Z")

        log_a, log_b = self._run_pair(billable, billable)

        statuses = sorted([log_a.result_status, log_b.result_status])
        self.assertEqual(statuses, ["accepted", "unchanged"])
        self.assertEqual(MeterReading.objects.count(), 4)
        self.assertEqual(QuarantinedReading.objects.count(), 0)
        promotions = sum(
            log.result_counts.get("promoted", 0) for log in (log_a, log_b)
        )
        self.assertEqual(promotions, 4)


class DeliveryBoundaryTests(StrictBase):
    def test_incompatible_direction_rejects_the_entire_delivery(self):
        for meter, point in ((CONS_ID, "ProductionMeteringPoint"), (PROD_ID, "ConsumptionMeteringPoint")):
            with self.subTest(meter=meter):
                good = quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1, doc="GOOD")
                bad = quarter_block(meter, "2025-06-02T22:15:00Z", 1, point=point, doc="BAD")
                response = self._import(build_e66([good, bad]))
                self.assertRejected(response, "meter_direction_mismatch")
                expected_type = MeteringPointType.CONSUMPTION if meter == CONS_ID else MeteringPointType.PRODUCTION
                self.assertEqual(response.data["issues"][0]["meter_type"], expected_type)
                self.assertFalse(MeterReading.objects.exists())

    def test_bidirectional_readings_reach_both_billing_pools(self):
        from allocation.read_model import community_totals_by_timestamp

        self.cons_mp.meter_type = MeteringPointType.BIDIRECTIONAL
        self.cons_mp.save(update_fields=["meter_type"])
        blocks = [
            quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1, doc="IN"),
            quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1, doc="OUT", point="ProductionMeteringPoint"),
        ]
        response = self._import(build_e66(blocks))
        self.assertEqual(response.data["result_status"], "accepted", response.data)
        consumption, production = community_totals_by_timestamp(self.zev, TS0, TS0 + timedelta(minutes=15))
        self.assertEqual(consumption, {TS0: Decimal("101")})
        self.assertEqual(production, {TS0: Decimal("101")})

    def test_report_period_rejects_lower_upper_and_straddling_blocks(self):
        for start, count in (("2025-06-02T21:45:00Z", 1), ("2025-06-03T22:00:00Z", 1),
                             ("2025-06-02T21:45:00Z", 2), ("2025-06-03T21:45:00Z", 2)):
            with self.subTest(start=start, count=count):
                response = self._import(build_e66(
                    [quarter_block(CONS_ID, start, count)],
                    report_start="2025-06-02T22:00:00Z", report_end="2025-06-03T22:00:00Z",
                ))
                self.assertRejected(response, "outside_report_period")
                self.assertFalse(MeterReading.objects.exists())

    def test_excluded_blocks_do_not_require_billing_interval_fields(self):
        kinds = (
            {"point": "ExchangeMeteringPoint"},
            {"product": REACTIVE_PRODUCT},
            {"product": LEG_PRODUCT, "product_scheme": "VSENationalCode", "product_agency": "260"},
        )
        for i, options in enumerate(kinds):
            for j, omission in enumerate(("omit_interval", "omit_resolution")):
                with self.subTest(options=options, omission=omission):
                    stamp = (TS0 + timedelta(minutes=15 * (i * 2 + j))).strftime("%Y-%m-%dT%H:%M:%SZ")
                    good = quarter_block(CONS_ID, stamp, 1, doc="GOOD")
                    excluded = build_block(CONS_ID, observation(1, "1"), doc="EXCLUDED", **options, **{omission: True})
                    response = self._import(build_e66([good, excluded]))
                    self.assertEqual(response.data["result_status"], "accepted", response.data)
                    self.assertEqual(response.data["result_counts"]["excluded"], 1)
        self.assertEqual(MeterReading.objects.count(), 6)

    def test_identity_is_resolved_after_acquiring_the_commit_lock(self):
        original_lock = sdatch_importer._lock_zev_imports

        def change_identity(zev):
            original_lock(zev)
            self.cons_mp.meter_id = "CH9999901234500000000000000000099"
            self.cons_mp.save(update_fields=["meter_id"])

        with unittest_mock.patch.object(sdatch_importer, "_lock_zev_imports", side_effect=change_identity):
            response = self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1)]))
        self.assertRejected(response, "unknown_meter")
        self.assertFalse(MeterReading.objects.exists())

    def test_sparse_corrections_do_not_fetch_intervening_history(self):
        unrelated = MeterReading.objects.create(
            metering_point=self.cons_mp, timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc), energy_kwh=1,
        )
        original_fetch = sdatch_importer._fetch_existing
        loaded = []

        def capture(blocks):
            streams = original_fetch(blocks)
            loaded.extend(row.pk for stream in streams for row in stream.values())
            return streams

        payload = build_e66([
            quarter_block(CONS_ID, "2010-01-01T00:00:00Z", 1, doc="EARLY"),
            quarter_block(CONS_ID, "2030-01-01T00:00:00Z", 1, doc="LATE"),
        ])
        with unittest_mock.patch.object(sdatch_importer, "_fetch_existing", side_effect=capture):
            response = self._import(payload)
        self.assertEqual(response.data["result_status"], "accepted", response.data)
        self.assertNotIn(unrelated.pk, loaded)

    def test_informational_issue_truncation_is_not_an_error(self):
        blocks = [build_block(CONS_ID, observation(1, "1"), doc=f"EXCLUDED-{i}", product=REACTIVE_PRODUCT) for i in range(3)]
        with unittest_mock.patch.object(sdatch_importer, "MAX_ISSUES", 1):
            response = self._import(build_e66(blocks))
        self.assertEqual(response.data["result_status"], "unchanged", response.data)
        self.assertEqual(response.data["errors"], [])
        self.assertEqual(response.data["issues"][-1]["code"], "too_many_issues")
        self.assertEqual(response.data["issues"][-1]["severity"], "info")


class RevisionBoundaryTests(StrictBase):
    def test_tariff_band_observations_reject_whole_delivery(self):
        for feature in ("E10", "E11", "E12"):
            with self.subTest(feature=feature):
                obs = observation(1, "5").replace("</rsm:Observation>",
                    f'<rsm:Feature listAgencyID="260">{feature}</rsm:Feature></rsm:Observation>')
                blocks = [quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1, doc="GOOD"),
                          build_block(CONS_ID, obs, doc="BAND", start="2025-06-02T22:15:00Z", end="2025-06-02T22:30:00Z")]
                self.assertRejected(self._import(build_e66(blocks)), "unsupported_feature")
                self.assertFalse(MeterReading.objects.exists())

    def test_all_schema_supported_reactive_products_are_excluded_in_mixed_files(self):
        for index, product in enumerate(("8716867000047", "8716867000139", "8716867000146")):
            with self.subTest(product=product):
                stamp = (TS0 + timedelta(minutes=15 * index)).strftime("%Y-%m-%dT%H:%M:%SZ")
                response = self._import(build_e66([
                    quarter_block(CONS_ID, stamp, 1, doc="ACTIVE"),
                    build_block(CONS_ID, observation(1, "5"), doc="REACTIVE", product=product, omit_resolution=True),
                ]))
                self.assertEqual(response.data["result_status"], "accepted", response.data)
                self.assertEqual(response.data["result_counts"]["excluded"], 1)
                self.assertEqual(response.data["issues"][0]["code"], "reactive_excluded")

    def test_resolution_failures_respect_cap_without_losing_rejection(self):
        for kind in ("unknown", "direction", "ambiguous"):
            with self.subTest(kind=kind):
                blocks = [quarter_block(CONS_ID if kind != "unknown" else f"CH99999012345000000000000000000{i:02}",
                    "2025-06-02T22:00:00Z", 1, doc=f"BAD-{i}",
                    point="ProductionMeteringPoint" if kind == "direction" else "ConsumptionMeteringPoint") for i in range(11, 15)]
                with unittest_mock.patch.object(sdatch_importer, "MAX_ISSUES", 2):
                    if kind == "ambiguous":
                        from zev.models import AmbiguousMeterIdentity
                        with unittest_mock.patch.object(sdatch_importer, "resolve_metering_point", side_effect=AmbiguousMeterIdentity(CONS_ID, [])):
                            response = self._import(build_e66(blocks))
                    else:
                        response = self._import(build_e66(blocks))
                self.assertRejected(response)
                self.assertEqual(len(response.data["issues"]), 3)
                self.assertEqual(response.data["issues"][-1]["code"], "too_many_issues")
                self.assertEqual(response.data["result_counts"]["rejected"], 4)
                self.assertFalse(MeterReading.objects.exists())
                self.assertFalse(QuarantinedReading.objects.exists())

    def test_original_preserves_existing_quarantine(self):
        reason = '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'
        block = quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1)
        self._import(build_e66([block], reason_xml=reason))
        before = list(QuarantinedReading.objects.values())
        newer = block.replace("<rsm:Volume>101</rsm:Volume>", "<rsm:Volume>999</rsm:Volume>")
        response = self._import(build_e66([newer], reason_xml=reason, creation="2025-06-06T15:40:05Z"))
        self.assertEqual(response.data["result_status"], "unchanged")
        self.assertEqual(response.data["result_counts"]["original_existing"], 1)
        self.assertEqual(list(QuarantinedReading.objects.values()), before)

    def test_equal_creation_quality_changes_are_conflicts_for_both_streams(self):
        for reason in ('<rsm:ebIXCode>E88</rsm:ebIXCode>', '<rsm:VSENationalCode>C38</rsm:VSENationalCode>'):
            with self.subTest(reason=reason):
                self.cons_mp.readings.all().delete()
                self.cons_mp.quarantined_readings.all().delete()
                block = build_block(CONS_ID, observation(1, "5"), end="2025-06-02T22:15:00Z")
                self._import(build_e66([block], reason_xml=reason))
                changed = build_block(CONS_ID, observation(1, "5", "56"), end="2025-06-02T22:15:00Z")
                self.assertRejected(self._import(build_e66([changed], reason_xml=reason, status="5")), "equal_creation_conflict")

    def test_original_existing_guidance_survives_mixed_accepted_outcome(self):
        self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1)]))
        response = self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 2)], creation="2025-06-06T15:40:05Z"))
        self.assertEqual(response.data["result_status"], "accepted")
        self.assertIn("original_exists", [issue["code"] for issue in response.data["issues"]])

    def test_internal_failures_rollback_and_hide_server_details(self):
        for target, code in (("_apply_plan", "internal_error"), ("_load_schema_16", "validation_unavailable")):
            with self.subTest(target=target), unittest_mock.patch.object(sdatch_importer, target, side_effect=RuntimeError("/private/server/path")):
                with self.assertLogs(sdatch_importer.logger, level="ERROR"):
                    response = self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1)]))
                self.assertRejected(response, code)
                self.assertNotIn("/private/server/path", str(response.data))
                self.assertEqual(response.data["issues"][0]["import_log_id"], str(response.data["id"]))
                self.assertFalse(MeterReading.objects.exists())

    def test_integrity_failure_is_not_retried_and_rolls_back_saved_log_and_rows(self):
        from django.db import IntegrityError
        finalize = sdatch_importer._finalize_log

        def fail_after_save(*args, **kwargs):
            finalize(*args, **kwargs)
            raise IntegrityError("private constraint")

        with unittest_mock.patch.object(sdatch_importer, "_finalize_log", side_effect=fail_after_save) as save:
            with self.assertLogs(sdatch_importer.logger, level="ERROR"):
                response = self._import(build_e66([quarter_block(CONS_ID, "2025-06-02T22:00:00Z", 1)]))
        self.assertEqual(save.call_count, 1)
        self.assertRejected(response, "internal_error")
        self.assertEqual(ImportLog.objects.count(), 1)
        self.assertFalse(MeterReading.objects.exists())

    def test_upload_stream_errors_hide_server_details(self):
        upload = unittest_mock.Mock(spec=["name", "size", "read"])
        upload.name = "stream.xml"
        upload.size = 5
        upload.read.side_effect = OSError("/private/upload/path")
        with self.assertLogs(sdatch_importer.logger, level="ERROR"):
            log = sdatch_importer.import_sdatch(upload, self.zev, self.owner)
        self.assertEqual(log.result_status, "rejected")
        self.assertEqual(log.issues[0]["code"], "internal_error")
        self.assertNotIn("/private/upload/path", str(log.issues))
        self.assertEqual(log.issues[0]["import_log_id"], str(log.pk))
        self.assertFalse(MeterReading.objects.exists())

    def test_resolution_failure_rejects_even_when_info_already_filled_issue_cap(self):
        blocks = [build_block(CONS_ID, observation(1, "1"), doc=f"INFO-{i}", product=REACTIVE_PRODUCT) for i in range(3)]
        blocks.append(quarter_block("CH9999901234500000000000000000099", "2025-06-02T22:00:00Z", 1, doc="UNKNOWN"))
        with unittest_mock.patch.object(sdatch_importer, "MAX_ISSUES", 2):
            response = self._import(build_e66(blocks))
        self.assertRejected(response)
        self.assertEqual(response.data["result_counts"]["excluded"], 3)
        self.assertEqual(response.data["result_counts"]["rejected"], 1)
        self.assertEqual(len(response.data["issues"]), 3)
        self.assertEqual(response.data["issues"][-1]["code"], "too_many_issues")
        self.assertFalse(MeterReading.objects.exists())
