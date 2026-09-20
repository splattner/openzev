"""The admin accounts list: memberships and second-factor methods.

Spec: docs/specs/2026-03-community-and-access.md (admin accounts page). The
list is what makes an account that belongs to several communities legible, so
what is pinned here is the *shape* per relationship, plus that adding accounts
does not add queries.
"""

import secrets
from datetime import date

import pyotp
from django.test import TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from testing.helpers import authenticate, make_user
from zev.models import Participant, Zev

from .models import AppSettings, TotpDevice, UserRole, WebAuthnCredential

URL = "/api/v1/auth/users/"


def _participant(zev, user, first="Pat", last="Tenant"):
    return Participant.objects.create(
        zev=zev, user=user, first_name=first, last_name=last,
        email=f"{first.lower()}@example.com", valid_from=date(2026, 1, 1),
    )


class AdminUserListTests(TestCase):
    def setUp(self):
        self.admin = make_user("ual_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        # Pre-create the settings singleton: mfa_compliance (added later in this
        # module) calls AppSettings.load(), whose first-ever call does an extra
        # INSERT — leaving that for the query-count test's first GET would make
        # its two captures see a different number of queries for a reason that
        # has nothing to do with the number of accounts.
        AppSettings.load()

    def _rows(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["username"]: row for row in response.json()["results"]}

    def test_account_without_any_community_has_no_memberships(self):
        make_user("ual_loner", UserRole.GUEST)
        self.assertEqual(self._rows()["ual_loner"]["memberships"], [])

    def test_participant_membership_names_the_community_and_the_participant(self):
        owner = make_user("ual_owner", UserRole.ZEV_OWNER)
        zev = Zev.objects.create(name="Sonnenberg", owner=owner, zev_type="vzev", invoice_prefix="S")
        tenant = make_user("ual_tenant", UserRole.PARTICIPANT)
        participant = _participant(zev, tenant)

        self.assertEqual(
            self._rows()["ual_tenant"]["memberships"],
            [{"zev": str(zev.pk), "zev_name": "Sonnenberg", "is_owner": False, "participant": str(participant.pk)}],
        )

    def test_owner_who_is_also_their_own_participant_is_one_membership(self):
        # Two relations, one community: reading it as two roles is the
        # confusion the list exists to remove.
        owner = make_user("ual_owner2", UserRole.ZEV_OWNER)
        zev = Zev.objects.create(name="Alpenblick", owner=owner, zev_type="vzev", invoice_prefix="A")
        participant = _participant(zev, owner, "Olga", "Owner")

        self.assertEqual(
            self._rows()["ual_owner2"]["memberships"],
            [{"zev": str(zev.pk), "zev_name": "Alpenblick", "is_owner": True, "participant": str(participant.pk)}],
        )

    def test_owner_of_several_communities_lists_each_sorted_by_name(self):
        owner = make_user("ual_multi", UserRole.ZEV_OWNER)
        for name in ("Zermatt", "alpha", "Bern"):
            Zev.objects.create(name=name, owner=owner, zev_type="vzev", invoice_prefix=name[:1].upper())

        memberships = self._rows()["ual_multi"]["memberships"]
        self.assertEqual([m["zev_name"] for m in memberships], ["alpha", "Bern", "Zermatt"])
        self.assertTrue(all(m["is_owner"] and m["participant"] is None for m in memberships))

    def test_mfa_methods_report_only_confirmed_totp_and_passkeys(self):
        both = make_user("ual_both", UserRole.PARTICIPANT)
        pending = make_user("ual_pending", UserRole.PARTICIPANT)
        make_user("ual_none", UserRole.PARTICIPANT)
        with override_settings(MFA_ENCRYPTION_KEYS=[_fernet_key()]):
            for user, confirmed in ((both, True), (pending, False)):
                device = TotpDevice(user=user, confirmed_at=timezone.now() if confirmed else None)
                device.set_secret(pyotp.random_base32())
                device.save()
        WebAuthnCredential.objects.create(
            user=both, credential_id=secrets.token_bytes(32), public_key=b"pk", sign_count=0, name="Laptop",
        )

        rows = self._rows()
        self.assertEqual(rows["ual_both"]["mfa_methods"], ["totp", "passkey"])
        self.assertEqual(rows["ual_pending"]["mfa_methods"], [])
        self.assertEqual(rows["ual_none"]["mfa_methods"], [])

    def test_query_count_does_not_grow_with_the_number_of_accounts(self):
        def build(prefix, n):
            owner = make_user(f"{prefix}_owner", UserRole.ZEV_OWNER)
            zev = Zev.objects.create(name=f"Z {prefix}", owner=owner, zev_type="vzev", invoice_prefix=prefix[:2].upper())
            for i in range(n):
                tenant = make_user(f"{prefix}_t{i}", UserRole.PARTICIPANT)
                _participant(zev, tenant, f"T{i}", prefix)
                WebAuthnCredential.objects.create(
                    user=tenant, credential_id=secrets.token_bytes(32), public_key=b"pk", sign_count=0, name="k",
                )

        build("few", 2)
        with CaptureQueriesContext(connection) as small:
            self.client.get(URL)
        build("many", 12)
        with CaptureQueriesContext(connection) as large:
            self.client.get(URL)
        self.assertEqual(len(small), len(large))

    def test_me_endpoint_does_not_carry_the_admin_only_fields(self):
        body = self.client.get("/api/v1/auth/me/").json()
        for field in ("memberships", "mfa_methods"):
            self.assertNotIn(field, body)


def _fernet_key():
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


class MfaComplianceFieldTests(TestCase):
    """`mfa_compliance` on the admin accounts list — spec §6.1a."""

    def setUp(self):
        self.admin = make_user("mc_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        AppSettings.load()

    def _rows(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["username"]: row for row in response.json()["results"]}

    def _set_policy(self, **payload):
        from datetime import timedelta

        from django.utils import timezone

        from .models import AppSettings

        with override_settings(MFA_ENCRYPTION_KEYS=[_fernet_key()]):
            response = self.client.patch("/api/v1/auth/app-settings/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        if "changed_days_ago" in payload:
            AppSettings.objects.update(
                mfa_policy_changed_at=timezone.now() - timedelta(days=payload["changed_days_ago"])
            )

    def test_none_when_the_policy_does_not_name_the_role(self):
        make_user("mc_free", UserRole.PARTICIPANT)
        self.assertIsNone(self._rows()["mc_free"]["mfa_compliance"])

    def test_grace_before_the_deadline(self):
        self._set_policy(mfa_required_roles=["participant"], mfa_grace_period_days=30)
        make_user("mc_grace", UserRole.PARTICIPANT)
        entry = self._rows()["mc_grace"]["mfa_compliance"]
        self.assertEqual(entry["status"], "grace")
        self.assertIsNotNone(entry["deadline"])

    def test_overdue_once_the_grace_period_has_passed(self):
        self._set_policy(mfa_required_roles=["participant"], mfa_grace_period_days=1, changed_days_ago=400)
        stale = make_user("mc_overdue", UserRole.PARTICIPANT)
        from datetime import timedelta

        from django.utils import timezone

        type(stale).objects.filter(pk=stale.pk).update(date_joined=timezone.now() - timedelta(days=400))
        self.assertEqual(self._rows()["mc_overdue"]["mfa_compliance"]["status"], "overdue")

    def test_compliant_once_enrolled_regardless_of_the_deadline(self):
        self._set_policy(mfa_required_roles=["participant"], mfa_grace_period_days=1, changed_days_ago=400)
        enrolled = make_user("mc_compliant", UserRole.PARTICIPANT)
        from datetime import timedelta

        from django.utils import timezone

        type(enrolled).objects.filter(pk=enrolled.pk).update(date_joined=timezone.now() - timedelta(days=400))
        with override_settings(MFA_ENCRYPTION_KEYS=[_fernet_key()]):
            device = TotpDevice(user=enrolled, confirmed_at=timezone.now())
            device.set_secret(pyotp.random_base32())
            device.save()
        self.assertEqual(self._rows()["mc_compliant"]["mfa_compliance"]["status"], "compliant")

    def test_field_does_not_add_a_query_per_account(self):
        self._set_policy(mfa_required_roles=["participant"], mfa_grace_period_days=30)
        for i in range(3):
            make_user(f"mc_q_{i}", UserRole.PARTICIPANT)
        with CaptureQueriesContext(connection) as small:
            self.client.get(URL)
        for i in range(10):
            make_user(f"mc_q_more_{i}", UserRole.PARTICIPANT)
        with CaptureQueriesContext(connection) as large:
            self.client.get(URL)
        self.assertEqual(len(small), len(large))
