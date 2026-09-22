"""``geocode_participants`` and the ``participants/geocoding-enabled/`` endpoint
— gated by ``FeatureFlag.PARTICIPANT_GEOCODING_ENABLED`` (#796)."""

import io
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from testing import factories
from testing.helpers import make_user

pytestmark = pytest.mark.django_db

GEOCODING_ENABLED_URL = "/api/v1/zev/participants/geocoding-enabled/"


def run(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


class TestGeocodeParticipantsCommand:
    def test_refuses_to_run_while_the_flag_is_off(self):
        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.PARTICIPANT_GEOCODING_ENABLED, defaults={"enabled": False}
        )
        with pytest.raises(CommandError, match="disabled"):
            run("geocode_participants")

    def test_warms_the_cache_for_every_addressed_participant_when_enabled(self):
        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.PARTICIPANT_GEOCODING_ENABLED, defaults={"enabled": True}
        )
        factories.ParticipantFactory(address_line1="Main Street 1", postal_code="8000", city="Zurich")
        factories.ParticipantFactory(address_line1="", postal_code="", city="")

        with mock.patch("zev.management.commands.geocode_participants.warm_geocode_cache") as warm:
            out, _err = run("geocode_participants")

        warm.assert_called_once_with("Main Street 1", "8000", "Zurich")
        assert "Warmed geocoding cache for 1 participant address(es)." in out


class TestParticipantGeocodingEnabledEndpoint:
    def test_reports_off_by_default(self):
        client = APIClient()
        client.force_authenticate(make_user("geocoding_flag_reader", UserRole.ZEV_OWNER))

        response = client.get(GEOCODING_ENABLED_URL)

        assert response.status_code == 200
        assert response.data == {"enabled": False}

    def test_reflects_the_flag_once_enabled(self):
        FeatureFlag.objects.update_or_create(
            name=FeatureFlag.PARTICIPANT_GEOCODING_ENABLED, defaults={"enabled": True}
        )
        client = APIClient()
        client.force_authenticate(make_user("geocoding_flag_reader_on", UserRole.PARTICIPANT))

        response = client.get(GEOCODING_ENABLED_URL)

        assert response.status_code == 200
        assert response.data == {"enabled": True}

    def test_requires_authentication(self):
        client = APIClient()

        response = client.get(GEOCODING_ENABLED_URL)

        assert response.status_code == 401
