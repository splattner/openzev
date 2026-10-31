"""``GET /live/enabled/`` (SPEC-2026-live-energy-data §5)."""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from metering.live.testing import LIVE, client_for, enable_live
from testing.helpers import make_user

ENABLED_URL = LIVE + "enabled/"


class LiveEnabledTests(TestCase):
    def setUp(self):
        self.user = make_user("live_enabled_user", UserRole.USER)

    def test_it_answers_true_while_the_live_flag_is_effective(self):
        enable_live()

        response = client_for(self.user).get(ENABLED_URL)

        self.assertEqual((response.status_code, response.json()), (200, {"enabled": True}))

    def test_it_answers_false_not_404_while_the_live_flag_is_off(self):
        enable_live(False)

        response = client_for(self.user).get(ENABLED_URL)

        self.assertEqual((response.status_code, response.json()), (200, {"enabled": False}))

    def test_the_live_flag_is_not_effective_without_the_energy_data_flag(self):
        enable_live()
        FeatureFlag.objects.filter(name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED).update(enabled=False)

        self.assertEqual(client_for(self.user).get(ENABLED_URL).json(), {"enabled": False})

    def test_an_anonymous_request_is_rejected(self):
        enable_live()

        self.assertEqual(APIClient().get(ENABLED_URL).status_code, 401)
