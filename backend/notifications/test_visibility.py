"""Read-time visibility: a notification never shows more than the account may see now."""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification
from notifications.test_helpers import Community
from notifications.visibility import visible_to
from zev import access
from zev.models import ZevAccessGrant, ZevAccessRole
from testing.helpers import make_user


def raise_notification(community, recipient, audience, participant=None, **fields):
    return Notification.objects.create(
        recipient=recipient, zev=community.zev, participant=participant, audience=audience,
        type="import.finished" if audience == "manager" else "invoice.paid", **fields,
    )


class VisibilityTests(TestCase):
    def setUp(self):
        self.c = Community("v")
        self.manager_note = raise_notification(self.c, self.c.manager, "manager")
        self.participant_note = raise_notification(self.c, self.c.login, "participant", self.c.participant)

    def visible(self, user):
        access.invalidate(user)
        return set(visible_to(user).values_list("pk", flat=True))

    def test_manager_and_participant_see_their_own(self):
        self.assertEqual(self.visible(self.c.manager), {self.manager_note.pk})
        self.assertEqual(self.visible(self.c.login), {self.participant_note.pk})

    def test_anonymous_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(visible_to(AnonymousUser()).count(), 0)

    def test_notification_of_another_account_is_never_visible(self):
        other = make_user("someone_else")
        self.assertEqual(self.visible(other), set())

    def test_revoked_grant_hides_manager_notices_and_a_new_grant_restores_them(self):
        grant = ZevAccessGrant.objects.get(zev=self.c.zev, user=self.c.manager)
        ZevAccessGrant.objects.filter(pk=grant.pk).update(
            valid_from=date(2026, 1, 1), valid_to=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(self.visible(self.c.manager), set())
        access.grant_manager(self.c.zev, self.c.manager)
        self.assertEqual(self.visible(self.c.manager), {self.manager_note.pk})

    def test_viewer_does_not_see_manager_notices(self):
        viewer = make_user("viewer_v")
        ZevAccessGrant.objects.create(zev=self.c.zev, user=viewer, role=ZevAccessRole.VIEWER)
        raise_notification(self.c, viewer, "manager")
        self.assertEqual(self.visible(viewer), set())

    def test_ended_participant_link_hides_notices_and_a_reopened_one_shows_them(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        type(self.c.participant).objects.filter(pk=self.c.participant.pk).update(valid_to=yesterday)
        self.assertEqual(self.visible(self.c.login), set())
        type(self.c.participant).objects.filter(pk=self.c.participant.pk).update(valid_to=None)
        self.assertEqual(self.visible(self.c.login), {self.participant_note.pk})

    def test_account_reached_through_another_participant_does_not_see_this_ones_notices(self):
        # The notice is about ``participant``; being linked to a colleague's row grants nothing.
        note = raise_notification(self.c, self.c.manager, "participant", self.c.participant)
        self.assertNotIn(note.pk, self.visible(self.c.manager))

    def test_disabled_zev_hides_everything(self):
        type(self.c.zev).objects.filter(pk=self.c.zev.pk).update(disabled_at=timezone.now())
        self.assertEqual(self.visible(self.c.manager), set())
        self.assertEqual(self.visible(self.c.login), set())

    def test_account_that_is_manager_and_participant_sees_each_audience_through_its_own_access(self):
        both = self.c.login
        access.grant_manager(self.c.zev, both)
        own_manager_note = raise_notification(self.c, both, "manager")
        self.assertEqual(self.visible(both), {self.participant_note.pk, own_manager_note.pk})
