"""``notify()``: validation, writing after commit, dedupe and coalescing."""

from unittest import mock

from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification
from notifications.recipients import manager_accounts
from notifications.services import notify
from notifications.test_helpers import Community
from testing.helpers import make_user
from zev.access import grant_manager


class NotifyTests(TestCase):
    def setUp(self):
        self.c = Community("s")

    def fire(self, type_key="invoice.paid", **overrides):
        args = {
            "zev": self.c.zev,
            "recipients": [(self.c.login, self.c.participant)],
            "payload": {"invoice_number": "S-1"},
            "target_id": "t1",
        }
        args.update(overrides)
        with self.captureOnCommitCallbacks(execute=True):
            notify(type_key, **args)

    def test_unknown_type_and_payload_key_raise(self):
        with self.assertRaises(ValueError):
            notify("nope", zev=self.c.zev, recipients=[], payload={})
        with self.assertRaises(ValueError):
            notify("invoice.paid", zev=self.c.zev, recipients=[(self.c.login, self.c.participant)],
                   payload={"invoice_number": "1", "amount_chf": "42.00"})

    def test_participant_notification_needs_a_participation(self):
        with self.assertRaises(ValueError):
            notify("invoice.paid", zev=self.c.zev, recipients=[self.c.login], payload={"invoice_number": "1"})

    def test_writes_row_with_type_payload_and_target(self):
        self.fire()
        row = Notification.objects.get()
        self.assertEqual((row.recipient, row.type, row.audience, row.target_type, row.target_id),
                         (self.c.login, "invoice.paid", "participant", "invoice", "t1"))
        self.assertEqual(row.payload, {"invoice_number": "S-1"})
        self.assertIsNone(row.read_at)

    def test_nothing_is_written_when_the_transaction_rolls_back(self):
        from django.db import transaction

        try:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    notify("invoice.paid", zev=self.c.zev, recipients=[(self.c.login, self.c.participant)],
                           payload={"invoice_number": "1"})
                    raise RuntimeError("rollback")
        except RuntimeError:
            pass
        self.assertEqual(Notification.objects.count(), 0)

    def test_a_failing_write_does_not_raise_into_the_caller(self):
        with mock.patch("notifications.services.Notification.objects.create", side_effect=RuntimeError("db")):
            self.fire()
        self.assertEqual(Notification.objects.count(), 0)

    def test_once_dedupe_creates_nothing_the_second_time_even_when_read(self):
        self.fire(dedupe_key="k")
        Notification.objects.update(read_at=timezone.now())
        self.fire(dedupe_key="k")
        self.assertEqual(Notification.objects.count(), 1)

    def test_coalescing_updates_the_unread_row_and_starts_a_new_one_after_it_was_read(self):
        def data(first, last):
            self.fire(
                "metering.data",
                payload={"meter_id": "M", "first_day": first, "last_day": last},
                dedupe_key="d",
            )

        data("2026-03-02", "2026-03-03")
        data("2026-03-01", "2026-03-02")
        row = Notification.objects.get()
        self.assertEqual((row.payload["first_day"], row.payload["last_day"]), ("2026-03-01", "2026-03-03"))
        Notification.objects.update(read_at=timezone.now())
        data("2026-03-04", "2026-03-04")
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 1)

    def test_exclude_removes_an_account(self):
        extra = make_user("mgr_extra")
        grant_manager(self.c.zev, extra)
        self.fire(
            "import.finished",
            recipients=manager_accounts(self.c.zev),
            payload={"import_log_id": "x", "source": "csv", "rows_imported": 1, "rows_skipped": 0, "issues": 0},
            exclude=[self.c.manager],
        )
        self.assertEqual(list(Notification.objects.values_list("recipient", flat=True)), [extra.pk])

    def test_disabled_zev_notifies_nobody(self):
        type(self.c.zev).objects.filter(pk=self.c.zev.pk).update(disabled_at=timezone.now())
        self.c.zev.refresh_from_db()
        self.fire()
        self.assertEqual(Notification.objects.count(), 0)

    def test_manager_accounts_lists_each_grant_holder_once(self):
        grant_manager(self.c.zev, make_user("mgr_two"))
        names = sorted(account.username for account in manager_accounts(self.c.zev))
        self.assertEqual(names, ["mgr_s", "mgr_two"])
