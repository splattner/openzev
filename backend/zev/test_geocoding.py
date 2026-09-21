"""Tests for the Nominatim-backed building geocoding + cache layer."""
import json
import urllib.error
from unittest import mock

import pytest
from django.core.cache import cache
from django.db import transaction

from zev import geocoding
from zev.tasks import trigger_geocode_if_address_present, warm_participant_geocode_cache_task
from testing import factories

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


_A_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[8.54, 47.36], [8.541, 47.36], [8.5405, 47.3605], [8.54, 47.36]]],
}


def _nominatim_response(*, boundingbox, addresstype="building", geojson=_A_POLYGON):
    return [
        {
            "boundingbox": boundingbox,
            "addresstype": addresstype,
            "geojson": geojson,
        }
    ]


class FakeHttpResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestGeocodeBuildingFootprint:
    def test_returns_none_when_address_line1_or_city_is_blank(self):
        assert geocoding.geocode_building_footprint("", "8000", "Zurich") is None
        assert geocoding.geocode_building_footprint("Main Street 1", "8000", "") is None

    def test_parses_a_building_scale_match_into_its_real_polygon(self):
        payload = _nominatim_response(boundingbox=["47.36", "47.37", "8.54", "8.55"])
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
            footprint = geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich")

        # The actual angled polygon, not a derived axis-aligned rectangle.
        assert footprint == _A_POLYGON

    def test_rejects_a_coarse_match_by_address_type_and_size(self):
        # A whole postal-code-area fallback match: not tagged as a building,
        # and its bounding box spans far more than a single building.
        payload = _nominatim_response(
            boundingbox=["47.30", "47.45", "8.40", "8.60"],
            addresstype="postcode",
        )
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
            assert geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich") is None

    def test_accepts_a_small_bbox_even_without_a_building_addresstype(self):
        # Small enough to plausibly be a single building regardless of tagging.
        payload = _nominatim_response(boundingbox=["47.3700", "47.3705", "8.5400", "8.5405"], addresstype="residential")
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
            assert geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich") is not None

    def test_rejects_a_match_with_no_mapped_polygon(self):
        # Nominatim resolved an address point but there's no drawn building
        # footprint in OSM for it (e.g. a bare housenumber node) — geojson is
        # a Point, not a Polygon/MultiPolygon.
        payload = _nominatim_response(
            boundingbox=["47.3700", "47.3705", "8.5400", "8.5405"],
            geojson={"type": "Point", "coordinates": [8.54, 47.37]},
        )
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse(payload)):
            assert geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich") is None

    def test_returns_none_when_no_results(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse([])):
            assert geocoding.geocode_building_footprint("Nowhere Street", "0000", "Nowhere") is None

    def test_returns_none_on_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            assert geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich") is None

    def test_returns_none_on_malformed_response(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeHttpResponse([{"boundingbox": "not-a-list", "geojson": _A_POLYGON}])):
            assert geocoding.geocode_building_footprint("Main Street 1", "8000", "Zurich") is None


class TestWarmGeocodeCache:
    def test_positive_result_is_cached_and_readable(self):
        with mock.patch("zev.geocoding.geocode_building_footprint", return_value=_A_POLYGON) as geocode:
            geocoding.warm_geocode_cache("Main Street 1", "8000", "Zurich")

        geocode.assert_called_once_with("Main Street 1", "8000", "Zurich")
        assert geocoding.get_cached_building_footprint("Main Street 1", "8000", "Zurich") == _A_POLYGON

    def test_negative_result_is_cached_as_not_found(self):
        with mock.patch("zev.geocoding.geocode_building_footprint", return_value=None):
            geocoding.warm_geocode_cache("Nowhere Street", "0000", "Nowhere")

        assert geocoding.get_cached_building_footprint("Nowhere Street", "0000", "Nowhere") is None

    def test_a_cached_address_is_never_looked_up_twice(self):
        # Same building, two different participants — Nominatim should only
        # ever be called once for the shared address.
        with mock.patch("zev.geocoding.geocode_building_footprint", return_value=_A_POLYGON) as geocode:
            geocoding.warm_geocode_cache("Main Street 1", "8000", "Zurich")
            geocoding.warm_geocode_cache("Main Street 1", "8000", "Zurich")

        geocode.assert_called_once()

    def test_a_cached_negative_result_is_not_retried_immediately(self):
        with mock.patch("zev.geocoding.geocode_building_footprint", return_value=None) as geocode:
            geocoding.warm_geocode_cache("Nowhere Street", "0000", "Nowhere")
            geocoding.warm_geocode_cache("Nowhere Street", "0000", "Nowhere")

        geocode.assert_called_once()

    def test_get_cached_building_footprint_is_none_when_never_warmed(self):
        assert geocoding.get_cached_building_footprint("Untouched Street 1", "8000", "Zurich") is None

    def test_get_cached_building_footprint_is_none_for_blank_address(self):
        assert geocoding.get_cached_building_footprint("", "8000", "Zurich") is None


class TestWarmParticipantGeocodeCacheTask:
    def test_missing_participant_returns_without_error(self):
        warm_participant_geocode_cache_task.run("00000000-0000-0000-0000-000000000000")

    def test_participant_without_address_is_skipped(self):
        participant = factories.ParticipantFactory()
        with mock.patch("zev.geocoding.warm_geocode_cache") as warm:
            warm_participant_geocode_cache_task.run(str(participant.pk))
        warm.assert_not_called()

    def test_participant_with_address_triggers_cache_warm(self):
        participant = factories.ParticipantFactory(
            address_line1="Main Street 1", postal_code="8000", city="Zurich",
        )
        with mock.patch("zev.geocoding.warm_geocode_cache") as warm:
            warm_participant_geocode_cache_task.run(str(participant.pk))
        warm.assert_called_once_with("Main Street 1", "8000", "Zurich")


class TestTriggerGeocodeIfAddressPresent:
    def test_enqueues_when_address_present(self, django_capture_on_commit_callbacks):
        participant = factories.ParticipantFactory(
            address_line1="Main Street 1", postal_code="8000", city="Zurich",
        )
        with (
            mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            trigger_geocode_if_address_present(participant)
        delay.assert_called_once_with(str(participant.pk))

    def test_enqueues_only_after_transaction_commits(self, django_capture_on_commit_callbacks):
        participant = factories.ParticipantFactory(
            address_line1="Main Street 1", postal_code="8000", city="Zurich",
        )
        with (
            mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            with transaction.atomic():
                trigger_geocode_if_address_present(participant)
                delay.assert_not_called()
            delay.assert_not_called()
        delay.assert_called_once_with(str(participant.pk))

    def test_does_not_enqueue_without_an_address(self, django_capture_on_commit_callbacks):
        participant = factories.ParticipantFactory()
        with (
            mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay") as delay,
            django_capture_on_commit_callbacks(execute=True),
        ):
            trigger_geocode_if_address_present(participant)
        delay.assert_not_called()
