"""Per-tool coverage (SPEC-2026-mcp-server §6, §10)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

import pytest

from invoices.models import InvoiceStatus
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection, ReadingResolution
from testing.factories import (
    InvoiceFactory,
    InvoiceItemFactory,
    MeteringPointAssignmentFactory,
    MeteringPointFactory,
    ParticipantFactory,
    ZevFactory,
)

from .conftest import call_tool

pytestmark = pytest.mark.django_db


def _tool_result(response):
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def _structured(response):
    return _tool_result(response)["structuredContent"]


def _is_error(response) -> bool:
    return _tool_result(response)["isError"]


class TestListZevs:
    def test_owner_sees_only_their_own_zevs(self, owner_mcp_client, owner_user):
        mine = ZevFactory(owner=owner_user)
        ZevFactory()  # somebody else's

        result = _structured(call_tool(owner_mcp_client, "list_zevs"))
        ids = {z["id"] for z in result["zevs"]}
        assert ids == {str(mine.id)}
        row = result["zevs"][0]
        assert set(row) == {"id", "name", "billing_interval", "start_date", "is_disabled"}

    def test_admin_sees_every_zev(self, admin_mcp_client):
        z1, z2 = ZevFactory(), ZevFactory()
        result = _structured(call_tool(admin_mcp_client, "list_zevs"))
        ids = {z["id"] for z in result["zevs"]}
        assert {str(z1.id), str(z2.id)} <= ids


class TestListParticipants:
    def test_lists_participants_with_assignments_and_no_contact_details(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        anna = ParticipantFactory(
            zev=zev, first_name="Anna", last_name="Muster",
            email="anna@example.com", phone="+41 79 000 00 00",
            valid_from=date(2025, 1, 1),
        )
        meter = MeteringPointFactory(zev=zev, meter_id="CH-MCP-0001")
        MeteringPointAssignmentFactory(metering_point=meter, participant=anna, valid_from=date(2025, 1, 1))

        result = _structured(call_tool(owner_mcp_client, "list_participants", {"zev_id": str(zev.id)}))

        assert len(result["participants"]) == 1
        row = result["participants"][0]
        assert row["id"] == str(anna.id)
        assert row["full_name"] == "Anna Muster"
        assert row["metering_points"] == [
            {"meter_id": "CH-MCP-0001", "meter_type": meter.meter_type, "valid_from": "2025-01-01", "valid_to": None}
        ]
        assert set(row) == {
            "id", "full_name", "valid_from", "valid_to", "has_account", "onboarding_status", "metering_points",
        }
        assert "anna@example.com" not in str(result)

    def test_query_filters_by_name(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        ParticipantFactory(zev=zev, first_name="Anna", last_name="Muster", valid_from=date(2025, 1, 1))
        ParticipantFactory(zev=zev, first_name="Ben", last_name="Baumann", valid_from=date(2025, 1, 1))

        result = _structured(
            call_tool(owner_mcp_client, "list_participants", {"zev_id": str(zev.id), "query": "baum"})
        )
        assert [p["full_name"] for p in result["participants"]] == ["Ben Baumann"]

    def test_active_on_hides_former_participants_unless_include_inactive(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        ParticipantFactory(zev=zev, first_name="Old", last_name="Tenant",
                           valid_from=date(2024, 1, 1), valid_to=date(2025, 10, 31))
        ParticipantFactory(zev=zev, first_name="New", last_name="Tenant", valid_from=date(2025, 11, 1))
        args = {"zev_id": str(zev.id), "active_on": "2025-12-01"}

        result = _structured(call_tool(owner_mcp_client, "list_participants", args))
        assert [p["full_name"] for p in result["participants"]] == ["New Tenant"]
        assert result["active_on"] == "2025-12-01"

        result = _structured(
            call_tool(owner_mcp_client, "list_participants", {**args, "include_inactive": True})
        )
        assert {p["full_name"] for p in result["participants"]} == {"Old Tenant", "New Tenant"}

    def test_limit_caps_and_reports_truncation(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        for i in range(3):
            ParticipantFactory(zev=zev, last_name=f"P{i}", valid_from=date(2025, 1, 1))

        result = _structured(
            call_tool(owner_mcp_client, "list_participants", {"zev_id": str(zev.id), "limit": 2})
        )
        assert len(result["participants"]) == 2
        assert result["truncated"] is True
        assert result["total"] == 3

    def test_owner_cannot_list_another_owners_participants(self, zev, owner_mcp_client):
        other_zev = ZevFactory()
        ParticipantFactory(zev=other_zev, first_name="Secret", last_name="Person", valid_from=date(2025, 1, 1))

        response = call_tool(owner_mcp_client, "list_participants", {"zev_id": str(other_zev.id)})
        assert _is_error(response)
        assert "Secret" not in str(response.json())


class TestPeriodReadiness:
    def test_invalid_arguments_missing_zev_id(self, zev, owner_mcp_client):
        response = call_tool(owner_mcp_client, "period_readiness", {})
        assert response.json()["error"]["code"] == -32602

    def test_owner_cannot_see_another_owners_zev(self, zev, owner_mcp_client):
        other_zev = ZevFactory()
        response = call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(other_zev.id)})
        result = _tool_result(response)
        assert result["isError"] is True
        assert "Permission denied" in result["content"][0]["text"]

    def test_zev_with_no_master_data_returns_setup_form(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user, start_date=date(2026, 1, 1))
        result = _structured(call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(zev.id)}))
        assert result["zev_id"] == str(zev.id)
        assert result["period"] is None
        assert "setup" in result
        assert all("link" not in str(k) for k in result["setup"])

    def test_admin_can_read_any_owners_zev(self, admin_mcp_client):
        zev = ZevFactory()
        result = _structured(call_tool(admin_mcp_client, "period_readiness", {"zev_id": str(zev.id)}))
        assert result["zev_id"] == str(zev.id)


class TestFindInvoices:
    def test_owner_finds_their_own_invoices(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev, first_name="Anna", last_name="Muster")
        InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            status=InvoiceStatus.DRAFT, total_chf=Decimal("42.00"),
        )

        result = _structured(call_tool(owner_mcp_client, "find_invoices", {"zev_id": str(zev.id)}))
        assert len(result["invoices"]) == 1
        row = result["invoices"][0]
        assert row["participant_name"] == "Anna Muster"
        assert row["total_chf"] == "42.00"

    def test_participant_query_filters_by_name(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        anna = ParticipantFactory(zev=zev, first_name="Anna", last_name="Muster")
        ben = ParticipantFactory(zev=zev, first_name="Ben", last_name="Baumann")
        InvoiceFactory(zev=zev, participant=anna, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
        InvoiceFactory(zev=zev, participant=ben, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))

        result = _structured(
            call_tool(owner_mcp_client, "find_invoices", {"zev_id": str(zev.id), "participant_query": "anna"})
        )
        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["participant_name"] == "Anna Muster"

    def test_participant_id_narrows_server_side(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        anna = ParticipantFactory(zev=zev, first_name="Anna", last_name="Muster")
        ben = ParticipantFactory(zev=zev, first_name="Ben", last_name="Baumann")
        InvoiceFactory(zev=zev, participant=anna, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
        InvoiceFactory(zev=zev, participant=ben, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))

        result = _structured(
            call_tool(owner_mcp_client, "find_invoices", {"zev_id": str(zev.id), "participant_id": str(ben.id)})
        )
        assert [r["participant_id"] for r in result["invoices"]] == [str(ben.id)]

    def test_limit_caps_and_reports_truncation(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        for i in range(5):
            InvoiceFactory(
                zev=zev, participant=participant, invoice_number=f"INV-{i:03d}",
                period_start=date(2026, i + 1, 1), period_end=date(2026, i + 1, 28),
            )

        result = _structured(
            call_tool(owner_mcp_client, "find_invoices", {"zev_id": str(zev.id), "limit": 2})
        )
        assert len(result["invoices"]) == 2
        assert result["truncated"] is True


class TestExplainInvoice:
    def test_breaks_down_lines_and_by_type(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        invoice = InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            total_local_kwh=Decimal("80.0000"), total_grid_kwh=Decimal("20.0000"),
            total_chf=Decimal("30.00"),
        )
        InvoiceItemFactory(
            invoice=invoice, item_type="local_energy", quantity_kwh=Decimal("80.0000"),
            unit_price_chf=Decimal("0.20000"), total_chf=Decimal("16.00"),
        )
        InvoiceItemFactory(
            invoice=invoice, item_type="grid_energy", quantity_kwh=Decimal("20.0000"),
            unit_price_chf=Decimal("0.70000"), total_chf=Decimal("14.00"),
        )

        result = _structured(call_tool(owner_mcp_client, "explain_invoice", {"invoice_id": str(invoice.id)}))
        assert len(result["lines"]) == 2
        assert result["by_type"]["local_energy"]["amount_chf"] == "16.00"
        assert result["energy"]["local_kwh"] == 80.0
        assert result["energy"]["grid_kwh"] == 20.0
        assert result["energy"]["local_share_pct"] == 80.0
        assert result["previous"] is None
        assert result["change"] is None

    def test_finds_previous_invoice_and_skips_cancelled(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        older_cancelled = InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2025, 11, 1), period_end=date(2025, 11, 30),
            status=InvoiceStatus.CANCELLED, total_chf=Decimal("999.00"),
        )
        actual_previous = InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2025, 12, 1), period_end=date(2025, 12, 31),
            status=InvoiceStatus.SENT, total_chf=Decimal("50.00"),
        )
        current = InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            status=InvoiceStatus.DRAFT, total_chf=Decimal("60.00"),
        )

        result = _structured(call_tool(owner_mcp_client, "explain_invoice", {"invoice_id": str(current.id)}))
        assert result["previous"] is not None
        assert result["previous"]["id"] == str(actual_previous.id)
        assert result["previous"]["id"] != str(older_cancelled.id)
        assert result["change"]["total_chf"] == "10.00"

    def test_compare_previous_false_skips_lookup(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2025, 12, 1), period_end=date(2025, 12, 31),
        )
        current = InvoiceFactory(
            zev=zev, participant=participant,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )
        result = _structured(
            call_tool(owner_mcp_client, "explain_invoice", {"invoice_id": str(current.id), "compare_previous": False})
        )
        assert result["previous"] is None

    def test_owner_cannot_read_another_owners_invoice(self, zev, owner_mcp_client):
        other_zev = ZevFactory()
        other_participant = ParticipantFactory(zev=other_zev)
        other_invoice = InvoiceFactory(zev=other_zev, participant=other_participant)

        response = call_tool(owner_mcp_client, "explain_invoice", {"invoice_id": str(other_invoice.id)})
        assert _is_error(response) is True


class TestImportTriage:
    def test_summarises_errors_and_extracts_meter_ids(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        ImportLog.objects.create(
            zev=zev, source=ImportSource.CSV, filename="demo.csv",
            rows_total=10, rows_imported=9, rows_skipped=1,
            errors=["Row 4: meter CH-DEMO-CONS-0009 not found in this ZEV (skipped)."],
            warnings=[],
        )
        ImportLog.objects.create(
            zev=zev, source=ImportSource.CSV, filename="clean.csv",
            rows_total=5, rows_imported=5, rows_skipped=0, errors=[], warnings=[],
        )

        result = _structured(call_tool(owner_mcp_client, "import_triage", {"zev_id": str(zev.id)}))
        assert len(result["imports"]) == 1  # only_problems defaults True
        row = result["imports"][0]
        assert row["error_count"] == 1
        assert "CH-DEMO-CONS-0009" in row["metering_points"]
        assert result["totals"]["imports"] == 1

    def test_only_problems_false_includes_clean_imports(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        ImportLog.objects.create(
            zev=zev, source=ImportSource.CSV, filename="clean.csv",
            rows_total=5, rows_imported=5, rows_skipped=0, errors=[], warnings=[],
        )
        result = _structured(
            call_tool(owner_mcp_client, "import_triage", {"zev_id": str(zev.id), "only_problems": False})
        )
        assert len(result["imports"]) == 1

    def test_limit_caps_and_reports_truncation(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        for i in range(3):
            ImportLog.objects.create(
                zev=zev, source=ImportSource.CSV, filename=f"f{i}.csv",
                rows_total=1, rows_imported=0, rows_skipped=1,
                errors=[f"boom {i}"], warnings=[],
            )
        result = _structured(
            call_tool(owner_mcp_client, "import_triage", {"zev_id": str(zev.id), "limit": 2})
        )
        assert len(result["imports"]) == 2
        assert result["truncated"] is True


class TestConsumptionSummary:
    def test_span_over_400_days_is_rejected(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        response = call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2025-01-01", "date_to": "2026-06-01",
        })
        assert _is_error(response) is True

    def test_happy_path_shape_with_no_readings(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-31", "bucket": "day",
        }))
        assert result["totals"]["consumed_kwh"] == 0.0
        assert result["totals"]["self_consumption_pct"] is None
        assert result["series"] == []

    @staticmethod
    def _consumer(zev, name, kwh, ts=datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc)):
        participant = ParticipantFactory(zev=zev, first_name=name, last_name="Test", valid_from=date(2026, 1, 1))
        meter = MeteringPointFactory(zev=zev, meter_type="consumption")
        MeteringPointAssignmentFactory(metering_point=meter, participant=participant, valid_from=date(2026, 1, 1))
        MeterReading.objects.create(
            metering_point=meter, timestamp=ts, energy_kwh=Decimal(kwh),
            direction=ReadingDirection.IN, resolution=ReadingResolution.FIFTEEN_MIN,
        )
        return participant

    def test_zev_wide_call_breaks_down_per_participant(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        small = self._consumer(zev, "Small", "2.0000")
        big = self._consumer(zev, "Big", "8.0000")

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-31",
        }))

        assert [p["participant_id"] for p in result["participants"]] == [str(big.id), str(small.id)]
        top = result["participants"][0]
        assert set(top) == {
            "participant_id", "participant_name", "consumed_kwh", "from_zev_kwh",
            "from_grid_kwh", "produced_kwh", "local_share_pct", "has_behind_meter_generation",
            "gross_self_sufficiency_pct", "gross_self_consumption_pct", "gross_coverage_pct",
        }
        assert top["gross_self_sufficiency_pct"] is None
        assert top["consumed_kwh"] == 8.0
        assert top["local_share_pct"] == 0.0
        assert top["has_behind_meter_generation"] is False
        assert result["totals"]["consumed_kwh"] == 10.0
        assert result["totals"]["has_behind_meter_generation"] is False

    def test_net_metered_participant_has_null_local_share(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        producer = ParticipantFactory(zev=zev, first_name="Producer", last_name="Test", valid_from=date(2026, 1, 1))
        meter = MeteringPointFactory(
            zev=zev, meter_type="bidirectional", has_behind_meter_generation=True,
        )
        MeteringPointAssignmentFactory(metering_point=meter, participant=producer, valid_from=date(2026, 1, 1))
        MeterReading.objects.create(
            metering_point=meter, timestamp=datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc),
            energy_kwh=Decimal("3.0000"), direction=ReadingDirection.IN,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-31",
        }))

        row = next(p for p in result["participants"] if p["participant_id"] == str(producer.id))
        assert row["has_behind_meter_generation"] is True
        assert row["local_share_pct"] is None
        assert result["totals"]["has_behind_meter_generation"] is True

    def test_participant_call_is_scoped_and_has_no_breakdown(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        self._consumer(zev, "Small", "2.0000")
        big = self._consumer(zev, "Big", "8.0000")

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-31",
            "participant_id": str(big.id),
        }))

        assert "participants" not in result
        assert result["participant_id"] == str(big.id)
        assert result["totals"]["consumed_kwh"] == 8.0

    def test_participant_without_readings_is_not_given_zev_totals(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        self._consumer(zev, "Big", "8.0000")
        idle = ParticipantFactory(zev=zev, valid_from=date(2026, 1, 1))

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-31",
            "participant_id": str(idle.id),
        }))

        assert result["totals"]["consumed_kwh"] == 0.0
        assert result["series"] == []
        assert "note" in result

    def test_hour_bucket_within_a_week(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        self._consumer(zev, "Big", "8.0000")

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-10", "date_to": "2026-01-16", "bucket": "hour",
        }))

        assert result["bucket"] == "hour"
        assert [e["bucket"][:13] for e in result["series"]] == ["2026-01-10T18"]

    def test_hour_bucket_over_a_week_is_rejected(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        response = call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-08", "bucket": "hour",
        })
        assert _is_error(response) is True


    @staticmethod
    def _net_metered_participant(zev, with_source=True):
        from datetime import timedelta

        from accounts.models import FeatureFlag
        from allocation.validity import period_start_dt
        from metering.models import SupplementaryReading, SupplementarySource

        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED, defaults={"enabled": True}
        )
        participant = ParticipantFactory(zev=zev, first_name="Net", last_name="Metered", valid_from=date(2026, 1, 1))
        meter = MeteringPointFactory(zev=zev, meter_type="bidirectional", has_behind_meter_generation=True)
        MeteringPointAssignmentFactory(metering_point=meter, participant=participant, valid_from=date(2026, 1, 1))
        start = period_start_dt(date(2026, 1, 10))
        end = period_start_dt(date(2026, 1, 11))
        stamps = [start + timedelta(minutes=15 * i) for i in range(96)]
        for stamp in stamps:
            MeterReading.objects.create(metering_point=meter, timestamp=stamp, energy_kwh=Decimal("0.1"),
                                        direction=ReadingDirection.IN, resolution=ReadingResolution.FIFTEEN_MIN)
        if with_source:
            source = SupplementarySource.objects.create(
                metering_point=meter, participant=participant, provider="push",
                covers_from=start, synced_through=end,
            )
            for stamp in stamps:
                SupplementaryReading.objects.create(
                    source=source, metering_point=meter, timestamp=stamp, consumption_kwh=Decimal("0.4"),
                    production_kwh=Decimal("1.2"), import_kwh=Decimal("0.1"), export_kwh=Decimal("0.9"),
                )
        return participant

    def test_gross_figures_come_from_the_participants_own_system(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = self._net_metered_participant(zev)

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-10", "date_to": "2026-01-10", "bucket": "day",
        }))

        entry = next(p for p in result["participants"] if p["participant_id"] == str(participant.id))
        assert entry["local_share_pct"] is None  # the meter-based figure stays withheld
        assert entry["gross_self_sufficiency_pct"] == 75.0
        assert entry["gross_self_consumption_pct"] == 25.0
        assert entry["gross_coverage_pct"] == 100.0

    def test_a_selected_participant_gets_the_gross_figures_in_the_totals(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = self._net_metered_participant(zev)

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-10", "date_to": "2026-01-10", "bucket": "day",
            "participant_id": str(participant.id),
        }))

        assert result["totals"]["self_sufficiency_pct"] is None
        assert result["totals"]["gross_self_sufficiency_pct"] == 75.0
        assert result["totals"]["gross_coverage_pct"] == 100.0

    def test_gross_figures_are_null_without_a_source(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = self._net_metered_participant(zev, with_source=False)

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-10", "date_to": "2026-01-10",
        }))

        entry = next(p for p in result["participants"] if p["participant_id"] == str(participant.id))
        assert entry["gross_self_sufficiency_pct"] is None
        assert entry["gross_coverage_pct"] is None

    def test_gross_figures_are_null_while_the_feature_is_off(self, owner_mcp_client, owner_user):
        from accounts.models import FeatureFlag

        zev = ZevFactory(owner=owner_user)
        participant = self._net_metered_participant(zev)
        FeatureFlag.objects.filter(name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED).update(enabled=False)

        result = _structured(call_tool(owner_mcp_client, "consumption_summary", {
            "zev_id": str(zev.id), "date_from": "2026-01-10", "date_to": "2026-01-10",
        }))

        entry = next(p for p in result["participants"] if p["participant_id"] == str(participant.id))
        assert entry["gross_self_sufficiency_pct"] is None


class TestConsumptionProfile:
    @staticmethod
    def _participant_with_reading(zev, kwh="10.0000"):
        participant = ParticipantFactory(zev=zev, valid_from=date(2026, 1, 1))
        meter = MeteringPointFactory(zev=zev, meter_type="consumption")
        MeteringPointAssignmentFactory(metering_point=meter, participant=participant, valid_from=date(2026, 1, 1))
        MeterReading.objects.create(
            metering_point=meter, timestamp=datetime(2026, 1, 10, 18, 0, tzinfo=ZoneInfo("Europe/Zurich")),
            energy_kwh=kwh, direction=ReadingDirection.IN, resolution=ReadingResolution.FIFTEEN_MIN,
        )
        return participant

    def _args(self, zev, participant, **extra):
        return {"zev_id": str(zev.id), "participant_id": str(participant.id),
                "date_from": "2026-01-01", "date_to": "2026-01-10", **extra}

    def test_profile_shape_peak_and_daily_average(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = self._participant_with_reading(zev)

        result = _structured(call_tool(owner_mcp_client, "consumption_profile", self._args(zev, participant)))

        assert len(result["profile"]) == 24
        assert set(result["profile"][0]) == {"hour", "from_zev_kwh", "from_grid_kwh", "total_kwh"}
        # One 10 kWh reading averaged over the 10-day range, all from the grid
        # (the ZEV has no production).
        assert result["peak_hour"] == 18
        assert result["profile"][18]["total_kwh"] == 1.0
        assert result["average_daily_kwh"] == 1.0
        assert result["local_share_pct"] == 0.0

    def test_net_metered_participant_has_null_local_share(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev, valid_from=date(2026, 1, 1))
        meter = MeteringPointFactory(
            zev=zev, meter_type="bidirectional", has_behind_meter_generation=True,
        )
        MeteringPointAssignmentFactory(metering_point=meter, participant=participant, valid_from=date(2026, 1, 1))
        MeterReading.objects.create(
            metering_point=meter, timestamp=datetime(2026, 1, 10, 18, 0, tzinfo=ZoneInfo("Europe/Zurich")),
            energy_kwh=Decimal("10.0000"), direction=ReadingDirection.IN, resolution=ReadingResolution.FIFTEEN_MIN,
        )

        result = _structured(call_tool(owner_mcp_client, "consumption_profile", self._args(zev, participant)))

        assert result["has_behind_meter_generation"] is True
        assert result["local_share_pct"] is None

    def test_no_readings_returns_null_profile_with_note(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev, valid_from=date(2026, 1, 1))

        result = _structured(call_tool(owner_mcp_client, "consumption_profile", self._args(zev, participant)))
        assert result["profile"] is None
        assert "note" in result

    def test_participant_is_required(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        response = call_tool(owner_mcp_client, "consumption_profile", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-10",
        })
        assert response.json()["error"]["code"] == -32602

    def test_participant_from_another_zev_is_an_error(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        other_participant = self._participant_with_reading(ZevFactory(owner=owner_user))

        response = call_tool(owner_mcp_client, "consumption_profile", self._args(zev, other_participant))
        assert _is_error(response) is True

    def test_owner_cannot_read_another_owners_zev(self, zev, owner_mcp_client):
        zev = ZevFactory()
        participant = self._participant_with_reading(zev)

        response = call_tool(owner_mcp_client, "consumption_profile", self._args(zev, participant))
        assert _is_error(response) is True
        assert "profile" not in str(response.json()["result"].get("structuredContent", {}))

    def test_span_over_400_days_is_rejected(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        response = call_tool(owner_mcp_client, "consumption_profile",
                             self._args(zev, participant, date_from="2025-01-01", date_to="2026-06-01"))
        assert _is_error(response) is True


class TestDataGaps:
    def test_metering_point_with_no_readings_is_fully_incomplete(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        participant = ParticipantFactory(zev=zev)
        mp = MeteringPointFactory(zev=zev, meter_id="CH-TEST-0001")
        MeteringPointAssignmentFactory(metering_point=mp, participant=participant)

        result = _structured(call_tool(owner_mcp_client, "data_gaps", {
            "zev_id": str(zev.id), "date_from": "2026-01-01", "date_to": "2026-01-05",
        }))
        assert len(result["metering_points"]) == 1
        point = result["metering_points"][0]
        assert point["meter_id"] == "CH-TEST-0001"
        assert point["completeness_pct"] == 0
        assert point["missing_days"] == 5

    def test_only_incomplete_false_still_lists_a_complete_point(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        MeteringPointFactory(zev=zev)
        result = _structured(call_tool(owner_mcp_client, "data_gaps", {
            "zev_id": str(zev.id), "only_incomplete": False,
        }))
        assert len(result["metering_points"]) == 1


class TestAuditQuery:
    def test_returns_events_within_scope(self, owner_mcp_client, owner_user):
        zev = ZevFactory(owner=owner_user)
        # Generate a real mcp.tool.call event to query for.
        call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(zev.id)})

        result = _structured(call_tool(owner_mcp_client, "audit_query", {"zev_id": str(zev.id)}))
        assert any(e["action_type"] == "mcp.tool.call" for e in result["events"])
        event = result["events"][0]
        assert "metadata" not in event
        assert "ip_address" not in event

    def test_limit_caps_results(self, owner_mcp_client, owner_user):
        # A zev_owner only sees audit events attached to a ZEV they own
        # (BaseAuditEventView._base_queryset) — a zev-less event (e.g. from
        # list_zevs, which takes no zev_id) would never show up here at all,
        # so this generates events that carry one.
        zev = ZevFactory(owner=owner_user)
        for _ in range(3):
            call_tool(owner_mcp_client, "period_readiness", {"zev_id": str(zev.id)})
        result = _structured(call_tool(owner_mcp_client, "audit_query", {"limit": 1}))
        assert len(result["events"]) == 1
