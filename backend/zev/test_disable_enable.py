"""Disable/enable: the first half of the ZEV lifecycle (disable is reversible,
not deletion).

An owner may disable their own ZEV; only an admin may reverse that. A
disabled ZEV is inert — nothing under it is touched — but this module only
covers what actually changed so far: the state itself, who may flip it, and
that a disabled ZEV stops being visible to participants and stops being
writable to anyone but an admin. Cutting off participant/owner access to the
data *underneath* a disabled ZEV (participants, metering points, invoices,
public links, Celery tasks) is tracked on the ZEV lifecycle issue and not yet
done — see the comment above ``ZevViewSet.disable``.
"""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from testing.helpers import authenticate as auth, make_user
from zev.models import Participant, Zev

ZEVS = "/api/v1/zev/zevs/"
SELF_SETUP = f"{ZEVS}self-setup/"


class _OneOwnerOneZev(TestCase):
    def setUp(self):
        self.owner = make_user("de_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("de_other_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("de_admin", UserRole.ADMIN)
        self.zev = Zev.objects.create(name="Lifecycle ZEV", owner=self.owner)
        self.participant_user = make_user("de_participant", UserRole.PARTICIPANT)
        self.participant = Participant.objects.create(
            zev=self.zev, user=self.participant_user,
            first_name="Paula", last_name="Participant",
            email="paula@example.com", valid_from=date(2026, 1, 1),
        )

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.other_owner_client = APIClient()
        auth(self.other_owner_client, self.other_owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)
        self.participant_client = APIClient()
        auth(self.participant_client, self.participant_user)

    def _disable(self, client, reason=""):
        return client.post(f"{ZEVS}{self.zev.id}/disable/", {"reason": reason}, format="json")

    def _enable(self, client):
        return client.post(f"{ZEVS}{self.zev.id}/enable/")


class DisableTests(_OneOwnerOneZev):
    def test_owner_can_disable_their_own_zev(self):
        response = self._disable(self.owner_client, reason="Community dissolved")
        self.assertEqual(response.status_code, 200, response.content)
        self.zev.refresh_from_db()
        self.assertIsNotNone(self.zev.disabled_at)
        self.assertEqual(self.zev.disabled_by, self.owner)
        self.assertEqual(self.zev.disabled_reason, "Community dissolved")

    def test_admin_can_disable_any_zev(self):
        response = self._disable(self.admin_client)
        self.assertEqual(response.status_code, 200, response.content)
        self.zev.refresh_from_db()
        self.assertIsNotNone(self.zev.disabled_at)
        self.assertEqual(self.zev.disabled_by, self.admin)

    def test_owner_cannot_disable_another_owners_zev(self):
        # 404, not 403: the object is outside the other owner's scoped
        # queryset entirely (ZevScopedQuerySetMixin), so get_object() never
        # finds it to run the object-permission check — the same convention
        # as e.g. exporting somebody else's ZEV (test_transfer.py).
        response = self._disable(self.other_owner_client)
        self.assertEqual(response.status_code, 404, response.content)
        self.zev.refresh_from_db()
        self.assertIsNone(self.zev.disabled_at)

    def test_participant_cannot_disable(self):
        response = self._disable(self.participant_client)
        self.assertEqual(response.status_code, 403, response.content)
        self.zev.refresh_from_db()
        self.assertIsNone(self.zev.disabled_at)

    def test_disabling_twice_is_rejected(self):
        self._disable(self.owner_client)
        response = self._disable(self.owner_client)
        self.assertEqual(response.status_code, 400, response.content)

    def test_disable_is_audited(self):
        self._disable(self.owner_client, reason="Testing")
        event = AuditEvent.objects.filter(action_type="zev.disable").latest("created_at")
        self.assertEqual(event.target_display, "Lifecycle ZEV")
        self.assertEqual(event.metadata_json.get("reason"), "Testing")

    def test_disabling_does_not_touch_participants(self):
        self._disable(self.owner_client)
        self.assertTrue(Participant.objects.filter(pk=self.participant.pk).exists())


class EnableTests(_OneOwnerOneZev):
    def setUp(self):
        super().setUp()
        self._disable(self.admin_client)
        self.zev.refresh_from_db()

    def test_admin_can_enable(self):
        response = self._enable(self.admin_client)
        self.assertEqual(response.status_code, 200, response.content)
        self.zev.refresh_from_db()
        self.assertIsNone(self.zev.disabled_at)
        self.assertIsNone(self.zev.disabled_by)
        self.assertEqual(self.zev.disabled_reason, "")

    def test_owner_cannot_enable_their_own_zev(self):
        response = self._enable(self.owner_client)
        self.assertEqual(response.status_code, 403, response.content)
        self.zev.refresh_from_db()
        self.assertIsNotNone(self.zev.disabled_at)

    def test_enabling_an_active_zev_is_rejected(self):
        self._enable(self.admin_client)
        response = self._enable(self.admin_client)
        self.assertEqual(response.status_code, 400, response.content)

    def test_enable_is_audited(self):
        self._enable(self.admin_client)
        event = AuditEvent.objects.filter(action_type="zev.enable").latest("created_at")
        self.assertEqual(event.target_display, "Lifecycle ZEV")


class WriteProtectionTests(_OneOwnerOneZev):
    """A disabled ZEV is read-only to everyone but an admin.

    Participant visibility is deliberately not covered here: a participant
    already gets 403 from ZevManagementPermission on every method of this
    viewset regardless of a ZEV's state (they read their community elsewhere
    — see accounts.views._serialize_me), so there is nothing this change
    alters for them on this endpoint specifically.
    """

    def setUp(self):
        super().setUp()
        self._disable(self.owner_client)
        self.zev.refresh_from_db()

    def test_owner_still_sees_their_disabled_zev(self):
        response = self.owner_client.get(f"{ZEVS}{self.zev.id}/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_owner_cannot_patch_a_disabled_zev(self):
        response = self.owner_client.patch(f"{ZEVS}{self.zev.id}/", {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.zev.refresh_from_db()
        self.assertEqual(self.zev.name, "Lifecycle ZEV")

    def test_admin_can_still_patch_a_disabled_zev(self):
        response = self.admin_client.patch(f"{ZEVS}{self.zev.id}/", {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.zev.refresh_from_db()
        self.assertEqual(self.zev.name, "Renamed")

    def test_disabled_at_cannot_be_cleared_through_a_patch(self):
        """Guards the read-only rule directly, independent of the admin-only
        ``enable`` action — a PATCH must never be able to re-enable a ZEV."""
        response = self.admin_client.patch(
            f"{ZEVS}{self.zev.id}/", {"disabled_at": None}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.zev.refresh_from_db()
        self.assertIsNotNone(self.zev.disabled_at)


class SelfSetupGuardTests(_OneOwnerOneZev):
    """Disabling an owner's only ZEV must not lock them out of self-setup."""

    def _self_setup_payload(self, name):
        return {
            "name": name, "start_date": "2026-06-01", "zev_type": "vzev",
            "billing_interval": "monthly",
            "owner_address_line1": "Teststrasse 1", "owner_postal_code": "8000",
            "owner_city": "Zurich",
        }

    def test_owner_with_an_active_zev_is_still_blocked(self):
        response = self.owner_client.post(SELF_SETUP, self._self_setup_payload("Second ZEV"), format="json")
        self.assertEqual(response.status_code, 400, response.content)

    def test_owner_with_only_a_disabled_zev_can_self_setup_again(self):
        self._disable(self.owner_client)
        response = self.owner_client.post(SELF_SETUP, self._self_setup_payload("Replacement ZEV"), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(Zev.objects.filter(owner=self.owner, name="Replacement ZEV").exists())
