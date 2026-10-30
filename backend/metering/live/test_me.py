"""``GET /live/me/`` (SPEC-2026-live-energy-data §5.5)."""

from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.test_api_keys import create_api_key
from metering.live.permissions import LiveReadThrottle
from metering.live.testing import ME_URL, LiveTestCase, client_for, enable_live
from testing import factories
from zev.models import MeteringPointType, ZevType


class LiveMeTests(LiveTestCase):
    def test_a_participant_gets_a_flat_entry_for_their_zev(self):
        self.wire(pv=-8000, flat2=1200, connection=-3000)

        response = client_for(self.user2).get(ME_URL)

        self.assertEqual(response.status_code, 200, response.content)
        (entry,) = response.json()["zevs"]
        self.assertEqual(
            {key: entry[key] for key in ("zev_id", "zev_name", "tier", "production_w", "surplus_w", "local_share_pct",
                                         "own_consumption_w", "own_local_w", "forecast_next_peak")},
            {"zev_id": str(self.zev.pk), "zev_name": self.zev.name, "tier": "exact", "production_w": 8000.0,
             "surplus_w": 3000.0, "local_share_pct": 100.0, "own_consumption_w": 1200.0, "own_local_w": 1200.0,
             "forecast_next_peak": None},
        )
        self.assertIsNotNone(entry["as_of"])

    def test_the_production_tier_carries_no_surplus(self):
        self.wire(pv=-8000, flat2=1200)

        (entry,) = client_for(self.user2).get(ME_URL).json()["zevs"]

        self.assertEqual((entry["tier"], entry["production_w"], entry["surplus_w"], entry["local_share_pct"]),
                         ("production", 8000.0, None, None))
        self.assertEqual((entry["own_consumption_w"], entry["own_local_w"]), (1200.0, None))

    def test_a_participant_without_a_live_source_gets_null_own_values(self):
        self.wire(pv=-8000)

        (entry,) = client_for(self.quiet_user).get(ME_URL).json()["zevs"]

        self.assertEqual((entry["own_consumption_w"], entry["own_local_w"]), (None, None))

    def test_a_read_only_personal_api_key_is_enough(self):
        self.wire(pv=-8000)
        _, secret = create_api_key(self.user1, read_only=True)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {secret}")

        response = client.get(ME_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["zevs"][0]["production_w"], 8000.0)

    def test_every_zev_the_caller_participates_in_is_listed(self):
        other = factories.ZevFactory(zev_type=ZevType.VZEV)
        factories.ParticipantFactory(zev=other, user=self.user1, valid_from=self.p1.valid_from)
        panel = factories.MeteringPointFactory(zev=other, meter_type=MeteringPointType.PRODUCTION)
        self.sample(self.live_source(panel), -500)
        self.wire(pv=-8000)

        zevs = client_for(self.user1).get(ME_URL).json()["zevs"]

        self.assertEqual({entry["zev_id"] for entry in zevs}, {str(self.zev.pk), str(other.pk)})
        by_id = {entry["zev_id"]: entry for entry in zevs}
        self.assertEqual(by_id[str(other.pk)]["production_w"], 500.0)

    def test_a_manager_who_is_no_participant_gets_no_zevs(self):
        self.assertEqual(client_for(self.manager).get(ME_URL).json(), {"zevs": []})

    def test_a_disabled_zev_is_left_out(self):
        from django.utils import timezone
        from zev.models import Zev

        Zev.objects.filter(pk=self.zev.pk).update(disabled_at=timezone.now())

        self.assertEqual(client_for(self.user1).get(ME_URL).json(), {"zevs": []})

    def test_the_anonymous_caller_is_refused(self):
        self.assertEqual(client_for(None).get(ME_URL).status_code, 401)

    def test_the_flag_off_answers_404(self):
        enable_live(False)

        self.assertEqual(client_for(self.user1).get(ME_URL).status_code, 404)

    def test_a_key_and_a_browser_session_have_separate_budgets(self):
        cache.clear()
        _, secret = create_api_key(self.user1, read_only=True)
        keyed = APIClient()
        keyed.credentials(HTTP_AUTHORIZATION=f"Api-Key {secret}")
        rates = dict(LiveReadThrottle.THROTTLE_RATES)
        LiveReadThrottle.THROTTLE_RATES = {**rates, "live_read": "2/hour"}
        try:
            key_statuses = [keyed.get(ME_URL).status_code for _ in range(3)]
            session = client_for(self.user1).get(ME_URL).status_code
        finally:
            LiveReadThrottle.THROTTLE_RATES = rates

        self.assertEqual((key_statuses, session), ([200, 200, 429], 200))
