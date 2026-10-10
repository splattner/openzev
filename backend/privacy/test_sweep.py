"""The privacy retention sweep and its management command."""

import io
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import EmailVerificationToken, MagicLinkToken
from audit.models import AuditEvent, AuditEventSource
from invoices.models import EmailLog
from invoices.test_helpers import make_invoice, make_participant, make_zev
from privacy import sweep
from testing.helpers import make_user
from zev.models import ParticipantOnboardingToken

DAYS = {
    "PRIVACY_AUDIT_NETWORK_RETENTION_DAYS": 365,
    "PRIVACY_EMAIL_LOG_RETENTION_DAYS": 730,
    "PRIVACY_TOKEN_GRACE_DAYS": 30,
}


def ago(days):
    return timezone.now() - timedelta(days=days)


def backdate(obj, **fields):
    """Set auto_now_add fields, which ``save()`` would overwrite."""
    type(obj).objects.filter(pk=obj.pk).update(**fields)
    obj.refresh_from_db()
    return obj


def make_event(created_days_ago, **fields):
    event = AuditEvent.objects.create(
        action_category="system", action_type="test.event", target_type="test.Thing", summary="x",
        ip_address="203.0.113.7", user_agent="Mozilla/5.0", **fields,
    )
    return backdate(event, created_at=ago(created_days_ago))


@override_settings(**DAYS)
class AuditNetworkTests(TestCase):
    def test_old_event_loses_ip_and_user_agent_but_keeps_the_event(self):
        user = make_user("auditee")
        old = make_event(400, actor_user=user)

        report = sweep.sweep(dry_run=False)

        old.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertEqual(old.user_agent, "")
        self.assertEqual(old.actor_user, user)
        self.assertEqual(old.summary, "x")
        self.assertEqual(report["audit_network"], 1)

    def test_recent_event_is_untouched(self):
        recent = make_event(364)

        sweep.sweep()

        recent.refresh_from_db()
        self.assertEqual(recent.ip_address, "203.0.113.7")
        self.assertEqual(recent.user_agent, "Mozilla/5.0")

    def test_second_run_finds_nothing_to_do(self):
        make_event(400)
        sweep.sweep()

        self.assertEqual(sweep.sweep()["audit_network"], 0)

    @override_settings(PRIVACY_AUDIT_NETWORK_RETENTION_DAYS=0)
    def test_zero_switches_the_step_off(self):
        old = make_event(4000)

        report = sweep.sweep()

        old.refresh_from_db()
        self.assertEqual(old.ip_address, "203.0.113.7")
        self.assertEqual(report["audit_network"], 0)


@override_settings(**DAYS)
class EmailLogTests(TestCase):
    def setUp(self):
        owner = make_user("mail_owner")
        zev = make_zev(owner, "Mail ZEV")
        self.invoice = make_invoice(zev, make_participant(zev))

    def make_log(self, created_days_ago, **fields):
        log = EmailLog.objects.create(
            invoice=self.invoice, recipient="who@example.com", subject="Invoice", **fields,
        )
        return backdate(log, created_at=ago(created_days_ago))

    def test_old_log_loses_recipient_and_error_but_stays_for_readiness(self):
        old = self.make_log(800, status=EmailLog.Status.FAILED, error_message="550 who@example.com rejected")

        report = sweep.sweep()

        old.refresh_from_db()
        self.assertEqual(old.recipient, "")
        self.assertEqual(old.error_message, "")
        self.assertEqual(old.status, EmailLog.Status.FAILED)
        self.assertEqual(old.subject, "Invoice")
        self.assertEqual(report["email_log"], 1)

    def test_recent_log_is_untouched(self):
        recent = self.make_log(700)

        sweep.sweep()

        recent.refresh_from_db()
        self.assertEqual(recent.recipient, "who@example.com")


@override_settings(**DAYS)
class TokenTests(TestCase):
    def setUp(self):
        self.user = make_user("token_user")
        owner = make_user("token_owner")
        self.participant = make_participant(make_zev(owner, "Token ZEV"))

    def verification(self, created_days_ago, purpose="signup", consumed_days_ago=None):
        token = EmailVerificationToken.objects.create(
            user=self.user, token=f"v{EmailVerificationToken.objects.count()}", purpose=purpose,
        )
        return backdate(
            token, created_at=ago(created_days_ago),
            consumed_at=ago(consumed_days_ago) if consumed_days_ago is not None else None,
        )

    def magic(self, created_days_ago, consumed_days_ago=None):
        token = MagicLinkToken.objects.create(user=self.user, token=f"m{MagicLinkToken.objects.count()}")
        return backdate(
            token, created_at=ago(created_days_ago),
            consumed_at=ago(consumed_days_ago) if consumed_days_ago is not None else None,
        )

    def onboarding(self, *, expires_days_ago=None, revoked_days_ago=None, expires_in_days=30):
        n = ParticipantOnboardingToken.objects.count()
        return ParticipantOnboardingToken.objects.create(
            participant=self.participant, prefix=f"p{n}", secret="s" * 32,
            expires_at=ago(expires_days_ago) if expires_days_ago is not None else timezone.now() + timedelta(days=expires_in_days),
            revoked_at=ago(revoked_days_ago) if revoked_days_ago is not None else None,
        )

    def test_verification_tokens_expired_or_consumed_past_grace_are_deleted(self):
        self.verification(40)  # signup, expired 39 days ago
        self.verification(45, purpose="invitation")  # expired 38 days ago
        self.verification(1, consumed_days_ago=31)
        keep = [
            self.verification(0),  # live
            self.verification(10, purpose="invitation"),  # live: 7-day lifetime, not past it
            self.verification(20),  # expired 19 days ago, inside grace
            self.verification(1, consumed_days_ago=29),
            self.verification(34, purpose="invitation"),  # expired 27 days ago, inside grace
        ]

        report = sweep.sweep()

        self.assertEqual(report["tokens"]["email_verification"], 3)
        self.assertCountEqual(
            EmailVerificationToken.objects.values_list("pk", flat=True), [t.pk for t in keep],
        )

    def test_magic_link_tokens(self):
        self.magic(31)
        self.magic(1, consumed_days_ago=31)
        live = self.magic(0)
        recent = self.magic(5)

        report = sweep.sweep()

        self.assertEqual(report["tokens"]["magic_link"], 2)
        self.assertCountEqual(MagicLinkToken.objects.values_list("pk", flat=True), [live.pk, recent.pk])

    def test_onboarding_tokens_never_delete_a_live_one(self):
        # one unrevoked token per participant is a DB constraint, so revoke the spent ones
        self.onboarding(expires_days_ago=31, revoked_days_ago=40)
        self.onboarding(revoked_days_ago=31)
        self.onboarding(revoked_days_ago=5)  # revoked inside grace
        live = self.onboarding()

        report = sweep.sweep()

        self.assertEqual(report["tokens"]["onboarding"], 2)
        self.assertEqual(ParticipantOnboardingToken.objects.count(), 2)
        self.assertTrue(ParticipantOnboardingToken.objects.filter(pk=live.pk).exists())

    @override_settings(PRIVACY_TOKEN_GRACE_DAYS=0)
    def test_zero_switches_the_step_off(self):
        self.magic(400)

        report = sweep.sweep()

        self.assertEqual(MagicLinkToken.objects.count(), 1)
        self.assertEqual(report["tokens"], {})


@override_settings(**DAYS)
class ReportingTests(TestCase):
    def test_dry_run_counts_but_changes_nothing_and_leaves_no_audit_event(self):
        old = make_event(400)
        before = AuditEvent.objects.count()

        report = sweep.sweep(dry_run=True)

        old.refresh_from_db()
        self.assertEqual(old.ip_address, "203.0.113.7")
        self.assertEqual(report["audit_network"], 1)
        self.assertEqual(report["total"], 1)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_a_sweep_that_did_something_records_one_audit_event(self):
        make_event(400)

        sweep.sweep(source=AuditEventSource.CELERY)

        event = AuditEvent.objects.get(action_type=sweep.ACTION_SWEPT)
        self.assertEqual(event.source, AuditEventSource.CELERY)
        self.assertEqual(event.metadata_json["audit_network"], 1)
        self.assertIsNone(event.ip_address)

    def test_an_idle_sweep_leaves_no_audit_event(self):
        report = sweep.sweep()

        self.assertEqual(report["total"], 0)
        self.assertFalse(AuditEvent.objects.filter(action_type=sweep.ACTION_SWEPT).exists())

    def test_the_audit_event_of_a_sweep_survives_the_next_one(self):
        make_event(400)
        sweep.sweep()

        sweep.sweep()

        self.assertEqual(AuditEvent.objects.filter(action_type=sweep.ACTION_SWEPT).count(), 1)


@override_settings(**DAYS)
class CommandTests(TestCase):
    def run_command(self, *args):
        out = io.StringIO()
        call_command("openzev_privacy_sweep", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_counts_without_changing_anything(self):
        old = make_event(400)

        out = self.run_command("--dry-run")

        old.refresh_from_db()
        self.assertEqual(old.ip_address, "203.0.113.7")
        self.assertIn("Dry run: 1 record(s).", out)
        self.assertIn("Would affect: 1 audit events", out)

    def test_run_applies_the_sweep_as_a_management_command(self):
        old = make_event(400)

        out = self.run_command()

        old.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertIn("1 record(s).", out)
        self.assertEqual(
            AuditEvent.objects.get(action_type=sweep.ACTION_SWEPT).source, AuditEventSource.MANAGEMENT_COMMAND,
        )


class TaskTests(TestCase):
    @override_settings(**DAYS)
    def test_the_celery_task_runs_the_sweep(self):
        from privacy.tasks import sweep_personal_data

        old = make_event(400)

        report = sweep_personal_data()

        old.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertEqual(report["audit_network"], 1)

    def test_it_is_on_the_beat_schedule(self):
        from django.conf import settings

        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["sweep-personal-data"]["task"], "privacy.tasks.sweep_personal_data",
        )
