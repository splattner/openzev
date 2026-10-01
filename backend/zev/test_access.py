"""The per-ZEV access grant model and the helpers that read it (#761, spec §4–§5).

Nothing reads grants for access yet (that is step 4 of the rollout); this pins
the model, the helpers and the transitional invariant that ``Zev.owner`` holds a
manager grant, so the read-path rewrite can rely on them.
"""

import io
from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import UserRole
from invoices.models import Invoice
from testing.helpers import make_user
from zev import access
from zev.models import Participant, Zev, ZevAccessGrant, ZevAccessRole

TODAY = date(2026, 6, 15)
MANAGER, VIEWER = ZevAccessRole.MANAGER, ZevAccessRole.VIEWER


def on_day(day):
    """Pin ``access``'s idea of today."""
    return mock.patch("zev.access._today", return_value=day)


class GrantTestCase(TestCase):
    def setUp(self):
        patcher = on_day(TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.owner = make_user("ga_owner", UserRole.ZEV_OWNER)
        self.other = make_user("ga_other", UserRole.PARTICIPANT)
        self.zev = Zev.objects.create(name="Grant ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="G")

    def grant(self, user, role=VIEWER, valid_from=date(2026, 1, 1), valid_to=None):
        return ZevAccessGrant.objects.create(
            zev=self.zev, user=user, role=role, valid_from=valid_from, valid_to=valid_to,
        )


class ZevAccessGrantModelTests(GrantTestCase):
    def test_one_open_grant_per_account_and_zev(self):
        self.grant(self.other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.grant(self.other, role=MANAGER)

    def test_a_closed_grant_and_an_open_one_may_coexist(self):
        self.grant(self.other, valid_to=date(2026, 3, 31))
        self.grant(self.other, valid_from=date(2026, 4, 1))
        self.assertEqual(ZevAccessGrant.objects.filter(zev=self.zev, user=self.other).count(), 2)

    def test_window_must_not_end_before_it_starts(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.grant(self.other, valid_from=date(2026, 5, 1), valid_to=date(2026, 4, 30))

    def test_revoke_ends_the_window_yesterday(self):
        grant = access.revoke(self.grant(self.other))
        self.assertEqual(grant.valid_to, TODAY - timedelta(days=1))
        self.assertFalse(access.can_view(self.other, self.zev))

    def test_revoking_a_grant_that_never_took_effect_deletes_it(self):
        pending = self.grant(self.other, valid_from=TODAY)
        self.assertIsNone(access.revoke(pending))
        self.assertFalse(ZevAccessGrant.objects.filter(pk=pending.pk).exists())

    def test_revoking_an_ended_grant_changes_nothing(self):
        ended = self.grant(self.other, valid_to=date(2026, 2, 28))
        access.revoke(ended)
        ended.refresh_from_db()
        self.assertEqual(ended.valid_to, date(2026, 2, 28))

    def test_change_role_ends_one_row_and_opens_another(self):
        old = self.grant(self.other)
        new = access.change_role(old, MANAGER, by=self.owner)
        old.refresh_from_db()
        self.assertEqual(old.valid_to, TODAY - timedelta(days=1))
        self.assertEqual((new.role, new.valid_from, new.valid_to, new.granted_by), (MANAGER, TODAY, None, self.owner))
        access.invalidate(self.other)
        self.assertTrue(access.can_manage(self.other, self.zev))


class AccessHelperTests(GrantTestCase):
    def test_manager_viewer_and_stranger(self):
        viewer = make_user("ga_viewer", UserRole.PARTICIPANT)
        self.grant(viewer)
        cases = {
            # user: (can_manage, can_view)
            self.owner: (True, True),
            viewer: (False, True),
            self.other: (False, False),
        }
        for user, (manage, view) in cases.items():
            with self.subTest(user=user.username):
                self.assertEqual(access.can_manage(user, self.zev), manage)
                self.assertEqual(access.can_view(user, self.zev.pk), view)

    def test_ids_may_be_given_as_strings_and_garbage_is_refused(self):
        self.assertTrue(access.can_manage(self.owner, str(self.zev.pk)))
        self.assertFalse(access.can_view(self.owner, "not-a-uuid"))
        self.assertFalse(access.can_view(self.owner, None))

    def test_admin_may_do_everything_without_a_grant(self):
        admin = make_user("ga_admin", UserRole.ADMIN)
        self.assertTrue(access.can_manage(admin, self.zev))
        self.assertTrue(access.can_view(admin, self.zev))
        self.assertEqual(access.managed_zev_ids(admin), frozenset())

    def test_anonymous_may_do_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        anonymous = AnonymousUser()
        self.assertFalse(access.can_view(anonymous, self.zev))
        self.assertEqual(access.viewable_zev_ids(anonymous), frozenset())

    def test_id_sets(self):
        self.assertEqual(access.managed_zev_ids(self.owner), {self.zev.pk})
        self.assertEqual(access.viewable_zev_ids(self.owner), {self.zev.pk})
        self.grant(self.other)
        self.assertEqual(access.managed_zev_ids(self.other), frozenset())
        self.assertEqual(access.viewable_zev_ids(self.other), {self.zev.pk})

    def test_window_bounds_are_inclusive_and_future_grants_inactive(self):
        cases = {
            "starts today": (TODAY, None, True),
            "ends today": (date(2026, 1, 1), TODAY, True),
            "ended yesterday": (date(2026, 1, 1), TODAY - timedelta(days=1), False),
            "starts tomorrow": (TODAY + timedelta(days=1), None, False),
        }
        for label, (valid_from, valid_to, active) in cases.items():
            with self.subTest(label):
                user = make_user(f"ga_{label.replace(' ', '_')}", UserRole.PARTICIPANT)
                self.grant(user, valid_from=valid_from, valid_to=valid_to)
                self.assertEqual(access.can_view(user, self.zev), active)

    def test_participant_zev_ids_skip_ended_rows_unless_asked(self):
        live = Participant.objects.create(
            zev=self.zev, user=self.other, first_name="L", last_name="Live", valid_from=date(2026, 1, 1),
        )
        other_zev = Zev.objects.create(name="Old ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="O")
        Participant.objects.create(
            zev=other_zev, user=self.other, first_name="E", last_name="Ended",
            valid_from=date(2025, 1, 1), valid_to=TODAY - timedelta(days=1),
        )
        self.assertEqual(access.participant_zev_ids(self.other), {live.zev_id})
        self.assertEqual(access.participant_zev_ids(self.other, include_ended=True), {self.zev.pk, other_zev.pk})

    def test_future_participant_rows_count_as_current(self):
        Participant.objects.create(
            zev=self.zev, user=self.other, first_name="F", last_name="Future", valid_from=TODAY + timedelta(days=30),
        )
        self.assertEqual(access.participant_zev_ids(self.other), {self.zev.pk})

    def test_lookups_are_memoised_per_request_user(self):
        user = self.owner
        access.invalidate(user)
        with CaptureQueriesContext(connection) as queries:
            for _ in range(3):
                access.can_manage(user, self.zev)
                access.can_view(user, self.zev)
                access.viewable_zev_ids(user)
        self.assertEqual(len(queries), 1)

    def test_is_last_manager(self):
        owner_grant = ZevAccessGrant.objects.get(zev=self.zev, user=self.owner)
        self.assertTrue(access.is_last_manager(owner_grant))
        self.grant(self.other, role=MANAGER)
        self.assertFalse(access.is_last_manager(owner_grant))
        self.assertFalse(access.is_last_manager(self.grant(make_user("ga_v2", UserRole.PARTICIPANT))))


class OwnerGrantInvariantTests(GrantTestCase):
    def test_creating_a_zev_makes_its_owner_manager(self):
        grant = ZevAccessGrant.objects.get(zev=self.zev)
        self.assertEqual((grant.user, grant.role, grant.valid_from, grant.valid_to), (self.owner, MANAGER, TODAY, None))

    def test_saving_without_an_owner_change_adds_nothing(self):
        self.zev.name = "Renamed"
        self.zev.save()
        Zev.objects.get(pk=self.zev.pk).save()
        self.assertEqual(ZevAccessGrant.objects.filter(zev=self.zev).count(), 1)

    def test_moving_ownership_moves_the_manager_grant(self):
        new_owner = make_user("ga_new_owner", UserRole.ZEV_OWNER)
        zev = Zev.objects.get(pk=self.zev.pk)
        zev.owner = new_owner
        zev.save()
        for user in (self.owner, new_owner):
            access.invalidate(user)
        self.assertFalse(access.can_view(self.owner, self.zev))
        self.assertTrue(access.can_manage(new_owner, self.zev))

    def test_a_new_owner_who_was_a_viewer_is_promoted(self):
        self.grant(self.other)
        zev = Zev.objects.get(pk=self.zev.pk)
        zev.owner = self.other
        zev.save()
        access.invalidate(self.other)
        self.assertTrue(access.can_manage(self.other, self.zev))
        self.assertEqual(
            ZevAccessGrant.objects.filter(zev=self.zev, user=self.other, valid_to__isnull=True).get().role, MANAGER,
        )

    def test_the_owner_grant_can_be_revoked_afterwards(self):
        # A legal owner may hand management to someone else; the invariant only
        # applies when a ZEV is created or changes owner.
        self.grant(self.other, role=MANAGER)
        access.revoke(ZevAccessGrant.objects.get(zev=self.zev, user=self.owner))
        Zev.objects.get(pk=self.zev.pk).save()
        access.invalidate(self.owner)
        self.assertFalse(access.can_manage(self.owner, self.zev))

    def test_ensure_a_manager_only_acts_when_nobody_manages(self):
        self.grant(self.other, role=MANAGER)
        access.revoke(ZevAccessGrant.objects.get(zev=self.zev, user=self.owner))
        access.ensure_a_manager(self.zev)
        access.invalidate(self.owner)
        self.assertFalse(access.can_manage(self.owner, self.zev))
        access.revoke(ZevAccessGrant.objects.get(zev=self.zev, user=self.other, valid_to__isnull=True))
        access.ensure_a_manager(self.zev)
        access.invalidate(self.owner)
        self.assertTrue(access.can_manage(self.owner, self.zev))

    def test_transfer_import_makes_the_importer_manager(self):
        from zev.test_transfer import build_populated_zev, export_to_bytes
        from zev.transfer.importer import import_archive

        source = build_populated_zev(self.owner, name="Exported", meter_prefix="GAEXP")
        raw = export_to_bytes(source)
        importer = make_user("ga_importer", UserRole.ZEV_OWNER)
        # Meter ids are unique across the instance, so the exported ZEV goes
        # first (its invoices protect it from deletion).
        Invoice.objects.filter(zev=source).delete()
        Zev.objects.filter(pk=source.pk).delete()

        result = import_archive(io.BytesIO(raw), owner=importer, sections=None, name_override="Imported")
        access.invalidate(importer)
        self.assertTrue(access.can_manage(importer, result["zev_id"]))


class GrantMigrationTests(TransactionTestCase):
    """0031 gives every existing ZEV's owner a manager grant, starting the day it was created."""

    def test_migration_grants_every_owner(self):
        call_command("migrate", "zev", "0030", verbosity=0, interactive=False)
        try:
            owner = make_user("mig_owner", UserRole.ZEV_OWNER)
            # bulk_create: Zev.save() would write a grant into a table 0030 lacks.
            zevs = Zev.objects.bulk_create([
                Zev(name=f"Mig {n}", owner=owner, zev_type="vzev", invoice_prefix="M", start_date=date(2030, 1, 1))
                for n in range(2)
            ])
            call_command("migrate", "zev", verbosity=0, interactive=False)
            grants = ZevAccessGrant.objects.filter(zev__in=zevs)
            self.assertEqual(grants.count(), 2)
            for grant in grants:
                self.assertEqual((grant.user_id, grant.role, grant.valid_to), (owner.pk, MANAGER, None))
                # The creation day, not a start_date in the future.
                self.assertLessEqual(grant.valid_from, date.today())
        finally:
            call_command("migrate", "zev", verbosity=0, interactive=False)
