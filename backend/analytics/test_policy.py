"""The participant-visibility threshold for ZEV-wide totals: platform default, admin setting, floor."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import AppSettings
from analytics.policy import AGGREGATE_FLOOR, min_participants_for_zev_aggregate, platform_default
from analytics.testing import DAY, Community
from audit.models import AuditEvent
from testing.factories import AdminFactory
from testing.helpers import authenticate

SETTINGS_URL = "/api/v1/auth/app-settings/"
SERIES = "/api/v1/analytics/series/"
FIELD = "analytics_min_participants_for_aggregate"


@pytest.fixture
def community(db):
    return Community()


def client_for(user):
    client = APIClient()
    authenticate(client, user)
    return client


def set_threshold(value):
    settings_row = AppSettings.load()
    settings_row.analytics_min_participants_for_aggregate = value
    settings_row.save()


def zev_totals(user, community):
    return client_for(user).get(
        SERIES, {"zev": str(community.zev.pk), "from": DAY.isoformat(), "to": DAY.isoformat(), "group_by": "zev"},
    )


class TestResolution:
    def test_unset_follows_the_platform_default(self, db):
        assert min_participants_for_zev_aggregate() == 5
        with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=8):
            assert min_participants_for_zev_aggregate() == 8

    def test_an_admin_value_wins_over_the_environment(self, db):
        set_threshold(4)
        with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=9):
            assert min_participants_for_zev_aggregate() == 4

    def test_the_floor_holds_whatever_is_configured(self, db):
        with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=1):
            assert platform_default() == AGGREGATE_FLOOR
            assert min_participants_for_zev_aggregate() == AGGREGATE_FLOOR
        # A row written around the validators (a migration, the shell) is clamped too.
        AppSettings.objects.update_or_create(pk=1, defaults={FIELD: 1})
        assert min_participants_for_zev_aggregate() == AGGREGATE_FLOOR


class TestSeriesFollowsTheSetting:
    """The test community has four participants."""

    def test_default_suppresses_a_participants_totals(self, community):
        assert zev_totals(community.alice_user, community).status_code == 403

    def test_a_lower_value_shows_them(self, community):
        set_threshold(3)

        assert zev_totals(community.alice_user, community).status_code == 200

    def test_the_threshold_is_inclusive(self, community):
        set_threshold(4)
        assert zev_totals(community.alice_user, community).status_code == 200

        set_threshold(5)
        response = zev_totals(community.alice_user, community)
        assert response.status_code == 403
        assert "at least 5" in response.json()["detail"]

    def test_managers_are_never_held_back(self, community):
        set_threshold(100)

        assert zev_totals(community.manager, community).status_code == 200


class TestAdminSetting:
    def test_admin_reads_the_value_the_default_and_the_floor(self, db):
        response = client_for(AdminFactory()).get(SETTINGS_URL)

        assert response.status_code == 200
        assert response.json()[FIELD] is None
        assert response.json()["analytics_min_participants_default"] == 5
        assert response.json()["analytics_min_participants_floor"] == AGGREGATE_FLOOR

    def test_the_default_shown_is_the_effective_one_not_the_raw_env(self, db):
        with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=1):
            response = client_for(AdminFactory()).get(SETTINGS_URL)

        assert response.json()["analytics_min_participants_default"] == AGGREGATE_FLOOR

    def test_admin_sets_and_clears_it(self, db):
        admin = client_for(AdminFactory())

        response = admin.patch(SETTINGS_URL, {FIELD: 3}, format="json")
        assert response.status_code == 200
        assert response.json()[FIELD] == 3
        assert AppSettings.load().analytics_min_participants_for_aggregate == 3

        response = admin.patch(SETTINGS_URL, {FIELD: None}, format="json")
        assert response.status_code == 200
        assert AppSettings.load().analytics_min_participants_for_aggregate is None

    @pytest.mark.parametrize("value", [0, 1, AGGREGATE_FLOOR - 1, 101, -1, "many"])
    def test_values_below_the_floor_or_out_of_range_are_refused(self, db, value):
        response = client_for(AdminFactory()).patch(SETTINGS_URL, {FIELD: value}, format="json")

        assert response.status_code == 400
        assert FIELD in response.json()
        assert AppSettings.load().analytics_min_participants_for_aggregate is None

    def test_other_settings_are_untouched_by_a_partial_update(self, db):
        set_threshold(6)

        client_for(AdminFactory()).patch(SETTINGS_URL, {"mfa_grace_period_days": 7}, format="json")

        assert AppSettings.load().analytics_min_participants_for_aggregate == 6

    def test_a_participant_cannot_change_it(self, community):
        response = client_for(community.alice_user).patch(SETTINGS_URL, {FIELD: 3}, format="json")

        assert response.status_code == 403
        assert AppSettings.load().analytics_min_participants_for_aggregate is None

    def test_ordinary_accounts_do_not_see_it(self, community):
        response = client_for(community.alice_user).get(SETTINGS_URL)

        assert response.status_code == 200
        assert not [key for key in response.json() if key.startswith("analytics_")]

    def test_a_change_is_audited_with_before_and_after(self, db):
        set_threshold(5)

        client_for(AdminFactory()).patch(SETTINGS_URL, {FIELD: 3}, format="json")

        event = AuditEvent.objects.get(action_type="app_settings.update")
        assert event.changes_json[FIELD] == {"before": 5, "after": 3}
