"""Security notification emails: what is sent, to whom, and that sending can
never break the action it reports.

Spec: docs/specs/2026-03-community-and-access.md §5.6c.
"""

from unittest import mock

import pyotp
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from testing.helpers import authenticate as auth, make_user

from . import notifications
from .models import TotpDevice, UserRole
from .tasks import send_security_notification
from .test_mfa import RECOVERY_CODES_URL, TOTP_CONFIRM_URL, TOTP_DEVICE_URL
from .test_passkeys import (
    ORIGIN,
    PASSKEYS_URL,
    RP_ID,
    TEST_KEY,
    SoftAuthenticator,
    register_passkey,
)

CHANGE_PASSWORD = "/api/v1/auth/me/change-password/"


def _subjects() -> list[str]:
    return [message.subject for message in mail.outbox]


class ComposeTests(TestCase):
    def setUp(self):
        self.user = make_user("nt_compose", UserRole.PARTICIPANT)
        self.user.first_name = "Ada"

    def test_every_event_composes(self):
        for event in notifications.EVENTS:
            subject, body = notifications.compose(self.user, event, detail="Laptop")
            self.assertTrue(subject, event)
            self.assertIn("When:", body, event)
            self.assertNotIn("{detail}", body, event)

    def test_names_the_passkey_and_the_person(self):
        subject, body = notifications.compose(self.user, "passkey_added", detail="MacBook Touch ID")
        self.assertIn("passkey", subject.lower())
        self.assertIn('"MacBook Touch ID"', body)
        self.assertTrue(body.startswith("Hello Ada,"))

    def test_greets_without_a_name_and_says_when_and_from_where(self):
        self.user.first_name = ""
        _, body = notifications.compose(
            self.user, "password_changed", when="2026-09-20T15:31:00+00:00", ip="203.0.113.7"
        )
        self.assertTrue(body.startswith("Hello,\n"))
        self.assertIn("When: 2026-09-20 15:31 UTC", body)
        self.assertIn("From: 203.0.113.7", body)

    def test_omits_the_origin_line_when_unknown(self):
        _, body = notifications.compose(self.user, "password_changed")
        self.assertNotIn("From:", body)

    def test_an_unparseable_time_falls_back_to_now_instead_of_failing(self):
        _, body = notifications.compose(self.user, "password_changed", when="not a date")
        self.assertIn("UTC", body)

    def test_advice_differs_when_an_administrator_did_it(self):
        _, own = notifications.compose(self.user, "passkey_added", detail="x")
        _, admin = notifications.compose(self.user, "mfa_reset_by_admin")
        self.assertIn("change your password", own)
        self.assertNotIn("change your password", admin)
        self.assertIn("contact your administrator", admin)

    def test_says_it_cannot_be_turned_off(self):
        _, body = notifications.compose(self.user, "totp_enabled")
        self.assertIn("cannot be turned off", body)

    def test_an_unknown_event_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            notifications.notify(self.user, "made_up")


class NotifyGuardTests(TestCase):
    def test_no_mail_without_an_address(self):
        user = make_user("nt_noaddr", UserRole.PARTICIPANT)
        user.email = ""
        notifications.notify(user, "password_changed")
        self.assertEqual(mail.outbox, [])

    def test_no_mail_to_an_inactive_account(self):
        user = make_user("nt_inactive", UserRole.PARTICIPANT)
        user.is_active = False
        notifications.notify(user, "password_changed")
        self.assertEqual(mail.outbox, [])

    def test_an_account_gone_by_send_time_gets_nothing(self):
        user = make_user("nt_gone", UserRole.PARTICIPANT)
        user_id = user.pk
        user.delete()
        send_security_notification(user_id, "password_changed", {})
        self.assertEqual(mail.outbox, [])

    def test_an_account_deactivated_before_send_time_gets_nothing(self):
        user = make_user("nt_late", UserRole.PARTICIPANT)
        type(user).objects.filter(pk=user.pk).update(is_active=False)
        send_security_notification(user.pk, "password_changed", {})
        self.assertEqual(mail.outbox, [])


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY], WEBAUTHN_RP_ID=RP_ID, WEBAUTHN_ORIGIN=ORIGIN)
class NotificationHookTests(TestCase):
    def setUp(self):
        self.user = make_user("nt_user", UserRole.ZEV_OWNER)
        self.client = APIClient()
        auth(self.client, self.user)

    def _enrol_totp(self):
        secret = self.client.post(TOTP_DEVICE_URL).data["secret"]
        return self.client.post(TOTP_CONFIRM_URL, {"code": pyotp.TOTP(secret).now()})

    def test_enabling_an_authenticator_sends_a_notice_to_the_account(self):
        self.assertEqual(self._enrol_totp().status_code, 200)
        self.assertEqual(_subjects(), ["An authenticator app was added to your OpenZEV account"])
        self.assertEqual(mail.outbox[0].to, ["nt_user@example.com"])
        self.assertIn("From: 127.0.0.1", mail.outbox[0].body)

    def test_beginning_enrolment_without_confirming_sends_nothing(self):
        self.client.post(TOTP_DEVICE_URL)
        self.assertEqual(mail.outbox, [])

    def test_removing_an_active_authenticator_sends_a_notice(self):
        self._enrol_totp()
        mail.outbox.clear()
        self.assertEqual(self.client.delete(TOTP_DEVICE_URL).status_code, 204)
        self.assertEqual(_subjects(), ["The authenticator app was removed from your OpenZEV account"])

    def test_discarding_an_unconfirmed_enrolment_sends_nothing(self):
        self.client.post(TOTP_DEVICE_URL)
        self.assertEqual(self.client.delete(TOTP_DEVICE_URL).status_code, 204)
        self.assertEqual(mail.outbox, [])

    def test_regenerating_recovery_codes_sends_a_notice(self):
        self._enrol_totp()
        mail.outbox.clear()
        self.assertEqual(self.client.post(RECOVERY_CODES_URL).status_code, 200)
        self.assertEqual(_subjects(), ["New recovery codes were generated for your OpenZEV account"])

    def test_adding_and_removing_a_passkey_name_it_in_the_notice(self):
        response = register_passkey(self.client, SoftAuthenticator(), name="Work laptop")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(_subjects(), ["A passkey was added to your OpenZEV account"])
        self.assertIn('"Work laptop"', mail.outbox[0].body)

        mail.outbox.clear()
        passkey_id = response.data["passkey"]["id"]
        self.assertEqual(self.client.delete(f"{PASSKEYS_URL}{passkey_id}/").status_code, 204)
        self.assertEqual(_subjects(), ["A passkey was removed from your OpenZEV account"])
        self.assertIn('"Work laptop"', mail.outbox[0].body)

    def test_changing_the_password_sends_a_notice(self):
        response = self.client.post(
            CHANGE_PASSWORD, {"old_password": "pass1234", "new_password": "Uniquely-Long-9164!"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_subjects(), ["Your OpenZEV password was changed"])

    def test_a_failed_password_change_sends_nothing(self):
        self.client.post(CHANGE_PASSWORD, {"old_password": "wrong", "new_password": "Uniquely-Long-9164!"}, format="json")
        self.assertEqual(mail.outbox, [])


@override_settings(MFA_ENCRYPTION_KEYS=[TEST_KEY])
class AdminActionNotificationTests(TestCase):
    def setUp(self):
        self.admin = make_user("nt_admin", UserRole.ADMIN)
        self.target = make_user("nt_target", UserRole.PARTICIPANT)
        self.client = APIClient()
        auth(self.client, self.admin)

    def _give_target_a_totp(self):
        device = TotpDevice(user=self.target)
        device.set_secret(pyotp.random_base32())
        device.confirmed_at = self.target.date_joined
        device.save()

    def test_an_mfa_reset_tells_the_account_not_the_admin(self):
        self._give_target_a_totp()
        self.assertEqual(self.client.delete(f"/api/v1/auth/users/{self.target.pk}/mfa/").status_code, 200)
        self.assertEqual(_subjects(), ["Two-factor authentication was reset on your OpenZEV account"])
        self.assertEqual(mail.outbox[0].to, ["nt_target@example.com"])
        self.assertIn("contact your administrator", mail.outbox[0].body)

    def test_resetting_an_account_that_had_nothing_to_reset_sends_nothing(self):
        self.assertEqual(self.client.delete(f"/api/v1/auth/users/{self.target.pk}/mfa/").status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_an_admin_signing_an_account_out_tells_it(self):
        self.assertEqual(self.client.post(f"/api/v1/auth/users/{self.target.pk}/revoke-sessions/").status_code, 200)
        self.assertEqual(_subjects(), ["You were signed out of OpenZEV everywhere"])
        self.assertEqual(mail.outbox[0].to, ["nt_target@example.com"])

    def test_signing_yourself_out_of_other_devices_sends_nothing(self):
        # You did it; you do not need an email about it.
        self.assertEqual(self.client.post("/api/v1/auth/me/sessions/revoke/").status_code, 200)
        self.assertEqual(mail.outbox, [])


class SendingCanNeverBreakTheAction(TestCase):
    def setUp(self):
        self.user = make_user("nt_resilient", UserRole.ZEV_OWNER)
        self.client = APIClient()
        auth(self.client, self.user)
        self.body = {"old_password": "pass1234", "new_password": "Uniquely-Long-9164!"}

    def test_a_broker_outage_does_not_fail_the_password_change(self):
        with mock.patch.object(send_security_notification, "delay", side_effect=ConnectionError("broker down")):
            with self.assertLogs("accounts.notifications", level="ERROR"):
                response = self.client.post(CHANGE_PASSWORD, self.body, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Uniquely-Long-9164!"))

    def test_a_mail_failure_does_not_fail_the_password_change(self):
        with mock.patch("accounts.notifications.EmailMessage.send", side_effect=OSError("smtp down")):
            response = self.client.post(CHANGE_PASSWORD, self.body, format="json")
        self.assertEqual(response.status_code, 200)
