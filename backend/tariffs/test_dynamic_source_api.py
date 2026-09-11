"""``GET /tariffs/dynamic-sources/`` — the list a tariff form's picker reads.

Not ZEV-scoped, unlike everything else in ``tariffs/``: a source is global
(ADR 0018), carries nothing more sensitive than a public operator URL and
its fetched prices.
"""

from datetime import datetime, timezone

import pytest

from tariffs.dynamic.models import DynamicTariffSource

pytestmark = pytest.mark.django_db

UTC = timezone.utc


def make_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "Groupe E vario — grid",
        "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "adapter": "groupe_e",
        "tariff_type": "grid",
        "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


class TestAccess:
    def test_an_owner_can_list_sources(self, owner_client):
        make_source()

        response = owner_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_an_admin_can_list_sources(self, admin_client):
        make_source()

        response = admin_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 200

    def test_a_participant_is_refused(self, participant_client):
        response = participant_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 403

    def test_an_unauthenticated_request_is_refused(self, api_client):
        response = api_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 401


class TestListing:
    def test_sources_are_not_scoped_to_any_zev(self, owner_client, owner_user):
        # There is no ZEV in this request at all — the point of the test.
        make_source()

        response = owner_client.get("/api/v1/tariffs/dynamic-sources/")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_the_payload_carries_what_a_picker_needs(self, owner_client):
        make_source(
            last_fetch_status="ok",
            last_fetch_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            last_success_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            covers_from=datetime(2026, 9, 1, tzinfo=UTC),
            covers_to=datetime(2026, 9, 12, tzinfo=UTC),
        )

        row = owner_client.get("/api/v1/tariffs/dynamic-sources/").json()["results"][0]

        assert row["label"] == "Groupe E vario — grid"
        assert row["url"] == "https://api.tariffs.groupe-e.ch/v2/tariffs"
        assert row["adapter"] == "groupe_e"
        assert row["tariff_type"] == "grid"
        assert row["tariff_name"] == "vario"
        assert row["last_fetch_status"] == "ok"
        assert row["covers_from"] is not None
        assert row["covers_to"] is not None
        assert row["point_count"] == 0
        assert row["linked_tariff_count"] == 0
        assert row["linked_zev_count"] == 0
        assert row["supports_backfill"] is True
