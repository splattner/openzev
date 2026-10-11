"""A feature flag whose default follows the instance's configuration (ADR 0032).

The energy data flag is on once ``INTEGRATION_ENCRYPTION_KEYS`` is set, unless an admin has
switched it off. "Not chosen yet" and "chosen off" must stay distinguishable.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from cryptography.fernet import Fernet
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from testing.helpers import authenticate, make_user

pytestmark = pytest.mark.django_db

NAME = FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED
KEY = Fernet.generate_key().decode()
ENV = f"FEATURE_{NAME.upper()}"


@pytest.fixture(autouse=True)
def no_env_override():
    with mock.patch.dict(os.environ):
        os.environ.pop(ENV, None)
        yield


@pytest.fixture
def client():
    return APIClient()


def _flag() -> FeatureFlag:
    FeatureFlag.sync_defaults()
    return FeatureFlag.objects.get(name=NAME)


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
def test_off_without_a_key():
    assert FeatureFlag.is_enabled(NAME) is False
    _flag()
    assert FeatureFlag.is_enabled(NAME) is False


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_on_once_a_key_is_configured_before_and_after_the_row_exists():
    assert FeatureFlag.is_enabled(NAME) is True
    assert _flag().follows_default is True
    assert FeatureFlag.is_enabled(NAME) is True


def test_the_default_tracks_the_key_without_touching_the_row():
    _flag()
    with override_settings(INTEGRATION_ENCRYPTION_KEYS=[]):
        assert FeatureFlag.is_enabled(NAME) is False
    with override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY]):
        assert FeatureFlag.is_enabled(NAME) is True


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_an_explicit_off_beats_the_default():
    FeatureFlag.objects.filter(pk=_flag().pk).update(enabled=False, follows_default=False)
    assert FeatureFlag.is_enabled(NAME) is False


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[])
def test_an_explicit_on_works_without_a_key():
    # Push and file sources need no key, so an admin may want the feature with Solar Manager unusable.
    FeatureFlag.objects.filter(pk=_flag().pk).update(enabled=True, follows_default=False)
    assert FeatureFlag.is_enabled(NAME) is True


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_the_environment_override_still_wins():
    _flag()
    with mock.patch.dict(os.environ, {ENV: "false"}):
        assert FeatureFlag.is_enabled(NAME) is False


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_other_flags_keep_their_fixed_default():
    FeatureFlag.sync_defaults()
    assert FeatureFlag.objects.get(name=FeatureFlag.MCP_SERVER_ENABLED).follows_default is False
    assert FeatureFlag.is_enabled(FeatureFlag.MCP_SERVER_ENABLED) is False
    assert FeatureFlag.is_enabled(FeatureFlag.ZEV_SELF_REGISTRATION_ENABLED) is True


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_admin_list_shows_the_effective_value_and_that_it_is_a_default(client):
    admin = make_user("flag_admin", UserRole.ADMIN)
    authenticate(client, admin)
    rows = {row["name"]: row for row in client.get("/api/v1/auth/feature-flags/").json()}
    assert rows[NAME]["enabled"] is True
    assert rows[NAME]["follows_default"] is True


@override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY])
def test_switching_it_off_in_the_admin_is_remembered(client):
    admin = make_user("flag_admin", UserRole.ADMIN)
    authenticate(client, admin)
    flag = _flag()

    response = client.patch(f"/api/v1/auth/feature-flags/{flag.pk}/", {"enabled": False}, format="json")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["follows_default"] is False
    assert FeatureFlag.is_enabled(NAME) is False


def test_the_audit_diff_compares_effective_values(client):
    from audit.models import AuditEvent

    admin = make_user("flag_admin", UserRole.ADMIN)
    authenticate(client, admin)
    with override_settings(INTEGRATION_ENCRYPTION_KEYS=[KEY]):
        flag = _flag()
        client.patch(f"/api/v1/auth/feature-flags/{flag.pk}/", {"enabled": False}, format="json")

    event = AuditEvent.objects.filter(action_type="feature_flag.update").latest("created_at")
    assert event.changes_json == {"enabled": {"before": True, "after": False}}


def test_an_unrelated_edit_keeps_following_the_default(client):
    admin = make_user("flag_admin", UserRole.ADMIN)
    authenticate(client, admin)
    flag = _flag()

    client.patch(f"/api/v1/auth/feature-flags/{flag.pk}/", {}, format="json")

    flag.refresh_from_db()
    assert flag.follows_default is True


def test_the_migration_treats_a_stored_off_as_unchosen_and_a_stored_on_as_chosen():
    from importlib import import_module

    from django.apps import apps

    migrate = import_module("accounts.migrations.0023_featureflag_follows_default")
    off = FeatureFlag.objects.create(name=NAME, enabled=False)
    other = FeatureFlag.objects.create(name="other_flag", enabled=False)

    migrate.untouched_supplementary_follows_default(apps, None)
    off.refresh_from_db()
    other.refresh_from_db()
    assert off.follows_default is True
    assert other.follows_default is False

    off.enabled, off.follows_default = True, False
    off.save()
    migrate.untouched_supplementary_follows_default(apps, None)
    off.refresh_from_db()
    assert off.follows_default is False
