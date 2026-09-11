"""Creation, history, and admin operations for shared dynamic sources."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

from audit.models import AuditEvent
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import EnergyType
from testing import factories

pytestmark = pytest.mark.django_db
UTC = timezone.utc


def make_source(**overrides):
    defaults = {
        "label": "Groupe E vario — grid",
        "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "adapter": "groupe_e",
        "tariff_type": "grid",
        "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


def link_source(source, zev):
    return factories.TariffFactory(
        zev=zev, energy_type=EnergyType.GRID, dynamic_source=source
    )


def add_point(source, price="0.10000"):
    return DynamicPricePoint.objects.create(
        source=source,
        valid_from=datetime(2026, 9, 10, tzinfo=UTC),
        valid_to=datetime(2026, 9, 10, 0, 15, tzinfo=UTC),
        price_chf_per_kwh=Decimal(price),
    )


class TestCreationAndEditing:
    def test_owner_can_probe_and_create_a_source(self, owner_client):
        point = PricePoint(
            valid_from=datetime(2026, 9, 11, tzinfo=UTC),
            valid_to=datetime(2026, 9, 11, 0, 15, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.12345"),
        )
        with mock.patch(
            "tariffs.dynamic.services.fetch_window", return_value=([point], [])
        ):
            response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
                "label": "Manual VSE grid",
                "url": "https://tariffs.example.test/dynamic",
                "adapter": "vse_v1",
                "tariff_type": "grid",
                "tariff_name": "home",
            })

        assert response.status_code == 201
        source = DynamicTariffSource.objects.get()
        assert source.points.count() == 1
        assert source.last_fetch_status == "ok"
        assert AuditEvent.objects.filter(
            action_type="tariff.dynamic_source_create", target_id=str(source.pk)
        ).exists()

    def test_creation_reuses_the_natural_key_without_refetching(self, owner_client):
        source = make_source()
        with mock.patch("tariffs.dynamic.services.fetch_window") as fetch:
            response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
                "label": "Different label",
                "url": source.url,
                "adapter": source.adapter,
                "tariff_type": source.tariff_type,
                "tariff_name": source.tariff_name,
            })

        assert response.status_code == 200
        assert response.json()["id"] == str(source.pk)
        fetch.assert_not_called()

    def test_bkw_configuration_is_constrained(self, owner_client):
        response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
            "label": "BKW grid",
            "url": "https://api.example.test/bkw",
            "adapter": "bkw",
            "tariff_type": "grid",
        })

        assert response.status_code == 400
        assert "tariff_type" in response.json()

    def test_only_admin_can_edit_a_source(self, owner_client, admin_client):
        source = make_source()
        url = f"/api/v1/tariffs/dynamic-sources/{source.pk}/"

        assert owner_client.patch(url, {"label": "Owner edit"}).status_code == 403
        response = admin_client.patch(url, {"label": "Admin edit"})

        assert response.status_code == 200
        source.refresh_from_db()
        assert source.label == "Admin edit"


class TestPriceHistory:
    def test_owner_can_read_history_for_a_source_linked_to_their_zev(
        self, owner_client, zev
    ):
        source = make_source()
        link_source(source, zev)
        add_point(source, "-0.01000")

        response = owner_client.get(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"date_from": "2026-09-10", "date_to": "2026-09-10"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["stats"]["point_count"] == 1
        assert payload["stats"]["negative_count"] == 1
        assert payload["stats"]["gap_count"] == 1
        assert payload["points"][0]["price_chf_per_kwh"] == "-0.01000"

    def test_owner_cannot_read_an_unlinked_source(self, owner_client):
        source = make_source()

        response = owner_client.get(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/"
        )

        assert response.status_code == 403

    def test_history_is_limited_to_31_days(self, admin_client):
        source = make_source()

        response = admin_client.get(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"date_from": "2026-08-01", "date_to": "2026-09-01"},
        )

        assert response.status_code == 400


class TestOperations:
    def test_admin_can_queue_a_manual_fetch(self, admin_client):
        source = make_source()
        task = mock.Mock(id="task-123")
        with mock.patch("tariffs.views.fetch_dynamic_prices.delay", return_value=task) as delay:
            response = admin_client.post(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/fetch/",
                {"backfill": True},
            )

        assert response.status_code == 202
        delay.assert_called_once()
        event = AuditEvent.objects.get(action_type="tariff.dynamic_fetch")
        assert event.status == "queued"
        assert event.correlation_id == response.json()["correlation_id"]

    def test_owner_cannot_queue_or_clear(self, owner_client):
        source = make_source()

        fetch_response = owner_client.post(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/fetch/", {}
        )
        clear_response = owner_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label, "reason": "test"},
        )

        assert fetch_response.status_code == 403
        assert clear_response.status_code == 403

    def test_admin_can_clear_unbilled_points(self, admin_client):
        source = make_source()
        add_point(source)

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label, "reason": "Wrong endpoint configured"},
        )

        assert response.status_code == 200
        assert response.json()["deleted_points"] == 1
        assert source.points.count() == 0
        source.refresh_from_db()
        assert source.last_fetch_status == "pending"
        assert source.last_fetch_at is None
        assert source.last_success_at is None
        assert AuditEvent.objects.get(action_type="tariff.dynamic_source_clear").reason

    def test_clear_is_blocked_by_an_overlapping_invoice(self, admin_client, zev):
        source = make_source()
        link_source(source, zev)
        factories.InvoiceFactory(
            zev=zev,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label, "reason": "cleanup"},
        )

        assert response.status_code == 409
