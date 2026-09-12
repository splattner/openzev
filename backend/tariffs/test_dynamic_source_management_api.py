"""Creation, history, and admin operations for shared dynamic sources."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

from audit.models import AuditEvent
from tariffs.dynamic.discovery import EndpointDiscovery, SourceCapabilities
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.dynamic.protocol import DiscoveredComponent
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.models import EnergyType
from testing import factories

pytestmark = pytest.mark.django_db
UTC = timezone.utc


def make_source(**overrides):
    defaults = {
        "label": "Example dynamic grid",
        "url": "https://prices.example.test/tariffs",
        "api_version": "v1_0_5",
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
    def test_owner_can_discover_version_and_components(self, owner_client):
        discovery = EndpointDiscovery(
            api_version="v2_0_0",
            components=[DiscoveredComponent("grid", "standard")],
        )
        with mock.patch("tariffs.views.discover_endpoint", return_value=discovery):
            response = owner_client.post(
                "/api/v1/tariffs/dynamic-sources/discover/",
                {"url": "https://prices.example.test/tariffs"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "api_version": "v2_0_0",
            "version_detected": True,
            "components_discovered": True,
            "components": [{
                "tariff_type": "grid",
                "tariff_name": "standard",
                "aggregated_tariff_types": [],
            }],
        }

    def test_source_payload_serves_the_versioned_component_expansion(self, owner_client):
        make_source(api_version="v2_0_0", tariff_type="dso", tariff_name="")
        response = owner_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert row["aggregated_tariff_types"] == ["grid", "metering", "national_fees"]

    def test_owner_can_probe_and_create_a_source(self, owner_client):
        point = PricePoint(
            valid_from=datetime(2026, 9, 11, tzinfo=UTC),
            valid_to=datetime(2026, 9, 11, 0, 15, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.12345"),
        )
        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            return_value=SourceCapabilities(
                api_version="v1_0_5", request_mode="standard",
                query_tariff_type="grid", supports_range=True,
                points=[point], warnings=[],
            ),
        ):
            response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
                "label": "Manual VSE grid",
                "url": "https://tariffs.example.test/dynamic",
                "api_version": "v1_0_5",
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

    def test_creation_reports_units_the_source_publishes_but_cannot_bill(self, owner_client):
        # A dropped demand or fixed-fee unit must reach the caller, not just
        # the audit trail — the point in time it is most useful is right when
        # the source is being configured.
        point = PricePoint(
            valid_from=datetime(2026, 9, 11, tzinfo=UTC),
            valid_to=datetime(2026, 9, 11, 0, 15, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.12345"),
        )
        warning = "The grid series also publishes a fixed charge (CHF/m) which is not billed here."
        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            return_value=SourceCapabilities(
                api_version="v2_0_0", request_mode="standard",
                query_tariff_type="grid", supports_range=True,
                points=[point], warnings=[warning],
            ),
        ):
            response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
                "label": "Manual VSE grid",
                "url": "https://tariffs.example.test/dynamic",
                "api_version": "v2_0_0",
                "tariff_type": "grid",
                "tariff_name": "home",
            })

        assert response.status_code == 201
        assert response.json()["warnings"] == [warning]
        source = DynamicTariffSource.objects.get()
        event = AuditEvent.objects.get(
            action_type="tariff.dynamic_source_create", target_id=str(source.pk)
        )
        assert event.metadata_json["warnings"] == [warning]

    def test_reusing_an_existing_source_reports_no_warnings(self, owner_client):
        # Nothing was probed, so there is nothing new to warn about.
        source = make_source()

        response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
            "label": "Different label",
            "url": source.url,
            "api_version": source.api_version,
            "tariff_type": source.tariff_type,
            "tariff_name": source.tariff_name,
        })

        assert response.status_code == 200
        assert response.json()["warnings"] == []

    def test_creation_reuses_the_natural_key_without_refetching(self, owner_client):
        source = make_source()
        with mock.patch("tariffs.dynamic.services.probe_source_configuration") as probe:
            response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
                "label": "Different label",
                "url": source.url,
                "api_version": source.api_version,
                "tariff_type": source.tariff_type,
                "tariff_name": source.tariff_name,
            })

        assert response.status_code == 200
        assert response.json()["id"] == str(source.pk)
        probe.assert_not_called()

    def test_provider_adapter_names_are_not_accepted_as_versions(self, owner_client):
        response = owner_client.post("/api/v1/tariffs/dynamic-sources/", {
            "label": "Example", "url": "https://prices.example.test/tariffs",
            "api_version": "provider_name", "tariff_type": "grid",
        })

        assert response.status_code == 400
        assert "api_version" in response.json()

    def test_only_admin_can_edit_a_source(self, owner_client, admin_client):
        source = make_source()
        url = f"/api/v1/tariffs/dynamic-sources/{source.pk}/"

        assert owner_client.patch(url, {"label": "Owner edit"}).status_code == 403
        response = admin_client.patch(url, {"label": "Admin edit"})

        assert response.status_code == 200
        source.refresh_from_db()
        assert source.label == "Admin edit"

    def test_admin_can_disable_scheduled_fetches(self, admin_client):
        source = make_source()

        response = admin_client.patch(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"enabled": False},
        )

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        source.refresh_from_db()
        assert source.enabled is False
        event = AuditEvent.objects.get(
            action_type="tariff.dynamic_source_update", target_id=str(source.pk)
        )
        assert event.changes_json["enabled"] == {"before": True, "after": False}


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
        # The queried day is the local (Europe/Zurich) civil day, which in
        # September starts two hours before UTC midnight. The one point sits
        # at UTC midnight, so it leaves a gap on both sides of it.
        assert payload["stats"]["gap_count"] == 2
        assert payload["points"][0]["price_chf_per_kwh"] == "-0.01000"

    def test_owner_cannot_read_an_unlinked_source(self, owner_client):
        source = make_source()

        response = owner_client.get(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/"
        )

        assert response.status_code == 403

    def test_the_search_window_is_the_local_civil_day_not_the_utc_day(
        self, admin_client
    ):
        """Europe/Zurich is UTC+2 in September, so local 2026-09-10 runs
        from 2026-09-09T22:00Z to 2026-09-10T22:00Z. Anchoring the window on
        UTC midnight instead reported the day's last two hours as a gap even
        though this point covers them."""
        source = make_source()
        DynamicPricePoint.objects.create(
            source=source,
            valid_from=datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
            valid_to=datetime(2026, 9, 10, 22, 0, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.10000"),
        )

        response = admin_client.get(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"date_from": "2026-09-10", "date_to": "2026-09-10"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["stats"]["point_count"] == 1
        assert payload["stats"]["gap_count"] == 0

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

    def test_clearing_needs_only_the_label_typed_back(self, admin_client):
        # The label has to be read off the row being cleared; a reason box on
        # top of that invites a keystroke rather than a thought.
        source = make_source()
        add_point(source)

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label},
        )

        assert response.status_code == 200
        assert source.points.count() == 0

    def test_clearing_still_refuses_a_mistyped_label(self, admin_client):
        source = make_source()
        add_point(source)

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": "Example dynamic"},
        )

        assert response.status_code == 400
        assert source.points.count() == 1

    def test_clear_is_blocked_by_an_overlapping_invoice(self, admin_client, zev):
        source = make_source()
        link_source(source, zev)
        factories.InvoiceFactory(
            zev=zev,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status="approved",
        )

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label, "reason": "cleanup"},
        )

        assert response.status_code == 409

    def test_a_draft_invoice_freezes_the_source(self, admin_client, zev):
        source = make_source()
        link_source(source, zev)
        add_point(source)
        factories.InvoiceFactory(
            zev=zev,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status="draft",
        )

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/prices/",
            {"confirmation": source.label},
        )

        assert response.status_code == 409


class TestRecheckingCapabilities:
    """A wrongly-negative ``supports_range`` had no way back before this:
    identity fields (url/api_version/tariff_type/tariff_name) are immutable
    after creation, and the initial probe can under-detect range support on
    a transient blip or an endpoint with nothing published yet."""

    def test_admin_can_correct_a_wrongly_detected_capability(self, admin_client):
        source = make_source(supports_range=False, request_mode="exact_url")
        point = PricePoint(
            valid_from=datetime(2026, 9, 11, tzinfo=UTC),
            valid_to=datetime(2026, 9, 11, 0, 15, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.12345"),
        )
        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            return_value=SourceCapabilities(
                api_version="v1_0_5", request_mode="standard",
                query_tariff_type="grid", supports_range=True,
                points=[point], warnings=[],
            ),
        ):
            response = admin_client.post(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/recheck/"
            )

        assert response.status_code == 200
        assert response.json()["supports_backfill"] is True
        source.refresh_from_db()
        assert source.supports_range is True
        assert source.request_mode == "standard"
        # Identity fields are untouched by a recheck.
        assert source.url == "https://prices.example.test/tariffs"
        assert source.api_version == "v1_0_5"
        event = AuditEvent.objects.get(action_type="tariff.dynamic_source_recheck")
        assert event.metadata_json["supports_range"] is True

    def test_recheck_reports_units_it_cannot_bill(self, admin_client):
        source = make_source()
        warning = "The grid series also publishes a demand charge which is not billed."
        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            return_value=SourceCapabilities(
                api_version="v1_0_5", request_mode="standard",
                query_tariff_type="grid", supports_range=True,
                points=[], warnings=[warning],
            ),
        ):
            response = admin_client.post(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/recheck/"
            )

        assert response.status_code == 200
        assert response.json()["warnings"] == [warning]

    def test_owner_cannot_recheck(self, owner_client):
        source = make_source()

        response = owner_client.post(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/recheck/"
        )

        assert response.status_code == 403

    def test_recheck_is_refused_while_a_fetch_holds_the_lock(self, admin_client):
        source = make_source()

        with mock.patch("tariffs.views.dynamic_source_lock") as lock:
            lock.return_value.__enter__ = mock.Mock(return_value=False)
            lock.return_value.__exit__ = mock.Mock(return_value=False)
            response = admin_client.post(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/recheck/"
            )

        assert response.status_code == 409

    def test_a_fetch_failure_during_recheck_is_reported_clearly(self, admin_client):
        from tariffs.importers.remote import TariffFetchError

        source = make_source()
        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            side_effect=TariffFetchError("The endpoint could not be reached."),
        ):
            response = admin_client.post(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/recheck/"
            )

        assert response.status_code == 400
        source.refresh_from_db()
        # An identity field is untouched by a failed probe.
        assert source.supports_range is True


class TestDeletingASource:
    """A source nobody points at any more is ordinary clutter, not evidence.

    Removing it is only allowed once no tariff links to it — which also means
    no invoice can have been derived from it, since
    ``source_has_billing_evidence`` reasons entirely over linked tariffs.
    """

    def test_admin_can_delete_an_unused_source_and_its_points(self, admin_client):
        source = make_source()
        add_point(source)

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"confirmation": source.label},
        )

        assert response.status_code == 204
        assert not DynamicTariffSource.objects.filter(pk=source.pk).exists()
        assert DynamicPricePoint.objects.count() == 0

    def test_deleting_is_audited_with_what_it_removed(self, admin_client):
        source = make_source()
        add_point(source)
        DynamicPricePoint.objects.create(
            source=source,
            valid_from=datetime(2026, 9, 10, 0, 15, tzinfo=UTC),
            valid_to=datetime(2026, 9, 10, 0, 30, tzinfo=UTC),
            price_chf_per_kwh=Decimal("0.20000"),
        )

        admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"confirmation": source.label},
        )

        # The row is gone, so the audit event is the only record left of how
        # much was destroyed with it.
        event = AuditEvent.objects.get(action_type="tariff.dynamic_source_delete")
        assert event.target_display == "Example dynamic grid"
        assert event.metadata_json["deleted_points"] == 2
        assert "Example dynamic grid" in event.summary

    def test_a_source_still_used_by_a_tariff_is_refused(self, admin_client, zev):
        # PROTECT would refuse the write anyway; a 409 naming what still uses
        # it is what tells the admin where to look.
        source = make_source()
        link_source(source, zev)

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"confirmation": source.label},
        )

        assert response.status_code == 409
        assert "1 tariff" in response.json()["detail"]
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()

    def test_deleting_refuses_a_mistyped_label(self, admin_client):
        source = make_source()

        response = admin_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"confirmation": "example dynamic grid"},  # wrong case
        )

        assert response.status_code == 400
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()

    def test_deleting_requires_a_confirmation_at_all(self, admin_client):
        source = make_source()

        response = admin_client.delete(f"/api/v1/tariffs/dynamic-sources/{source.pk}/", {})

        assert response.status_code == 400
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()

    def test_an_owner_cannot_delete_a_source(self, owner_client):
        source = make_source()

        response = owner_client.delete(
            f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
            {"confirmation": source.label},
        )

        assert response.status_code == 403
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()

    def test_deleting_is_refused_while_a_fetch_holds_the_lock(self, admin_client):
        source = make_source()

        with mock.patch("tariffs.views.dynamic_source_lock") as lock:
            lock.return_value.__enter__ = mock.Mock(return_value=False)
            lock.return_value.__exit__ = mock.Mock(return_value=False)
            response = admin_client.delete(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
                {"confirmation": source.label},
            )

        assert response.status_code == 409
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()

    def test_a_tariff_linked_during_the_delete_still_refuses(self, admin_client, zev):
        # The count check above is for the message; PROTECT is what decides.
        # Without catching it, this race surfaces as a 500 rather than a 409.
        source = make_source()

        real_delete = DynamicTariffSource.delete

        def link_then_delete(self, *args, **kwargs):
            link_source(self, zev)
            return real_delete(self, *args, **kwargs)

        with mock.patch.object(DynamicTariffSource, "delete", link_then_delete):
            response = admin_client.delete(
                f"/api/v1/tariffs/dynamic-sources/{source.pk}/",
                {"confirmation": source.label},
            )

        assert response.status_code == 409
        assert DynamicTariffSource.objects.filter(pk=source.pk).exists()
