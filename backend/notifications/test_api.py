from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from notifications.test_helpers import Community
from testing.helpers import authenticate


def make(community, recipient, audience="manager", participant=None, **fields):
    return Notification.objects.create(
        recipient=recipient, zev=community.zev, participant=participant, audience=audience,
        type="import.finished", **fields,
    )


class NotificationApiTests(TestCase):
    URL = "/api/v1/notifications/"

    def setUp(self):
        self.c = Community("api")
        self.client = APIClient()
        authenticate(self.client, self.c.manager)

    def test_requires_authentication(self):
        for method, url in (("get", self.URL), ("get", self.URL + "unread-count/"), ("post", self.URL + "read-all/")):
            self.assertEqual(getattr(APIClient(), method)(url).status_code, 401, url)

    def test_list_is_paginated_newest_first_and_serialised(self):
        for index in range(25):
            make(self.c, self.c.manager, payload={"n": index})
        body = self.client.get(self.URL).json()
        self.assertEqual(body["count"], 25)
        self.assertEqual(len(body["results"]), 20)
        first = body["results"][0]
        self.assertEqual(first["payload"], {"n": 24})
        self.assertEqual(set(first), {"id", "type", "audience", "zev", "zev_name", "payload",
                                      "target_type", "target_id", "created_at", "read_at"})
        self.assertEqual(first["zev_name"], self.c.zev.name)

    def test_unread_and_zev_filters(self):
        make(self.c, self.c.manager)
        make(self.c, self.c.manager, read_at=timezone.now())
        self.assertEqual(self.client.get(self.URL, {"unread": "true"}).json()["count"], 1)
        self.assertEqual(self.client.get(self.URL, {"zev": str(self.c.zev.pk)}).json()["count"], 2)
        self.assertEqual(self.client.get(self.URL, {"zev": "2f0c5a0a-0000-4000-8000-000000000000"}).json()["count"], 0)
        self.assertEqual(self.client.get(self.URL, {"zev": "not-a-uuid"}).json()["count"], 0)

    def test_unread_count_follows_visibility(self):
        make(self.c, self.c.manager)
        make(self.c, self.c.manager, read_at=timezone.now())
        other = Community("other")
        make(other, other.manager)
        self.assertEqual(self.client.get(self.URL + "unread-count/").json(), {"count": 1})

    def test_mark_read_sets_read_at_once(self):
        note = make(self.c, self.c.manager)
        response = self.client.post(f"{self.URL}{note.pk}/read/")
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        stamp = note.read_at
        self.assertIsNotNone(stamp)
        self.client.post(f"{self.URL}{note.pk}/read/")
        note.refresh_from_db()
        self.assertEqual(note.read_at, stamp)

    def test_another_accounts_and_an_invisible_notification_are_404(self):
        theirs = make(self.c, self.c.login, "participant", self.c.participant)
        self.assertEqual(self.client.post(f"{self.URL}{theirs.pk}/read/").status_code, 404)
        hidden = make(self.c, self.c.manager)
        type(self.c.zev).objects.filter(pk=self.c.zev.pk).update(disabled_at=timezone.now())
        self.assertEqual(self.client.post(f"{self.URL}{hidden.pk}/read/").status_code, 404)

    def test_read_all_marks_only_visible_own_unread(self):
        mine = [make(self.c, self.c.manager) for _ in range(3)]
        theirs = make(self.c, self.c.login, "participant", self.c.participant)
        response = self.client.post(self.URL + "read-all/")
        self.assertEqual(response.json(), {"updated": 3})
        self.assertTrue(all(Notification.objects.get(pk=n.pk).read_at for n in mine))
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_read_all_can_be_limited_to_a_zev(self):
        other_zev = Community("api2")
        # Same account manages both communities.
        from zev.access import grant_manager

        grant_manager(other_zev.zev, self.c.manager)
        make(self.c, self.c.manager)
        elsewhere = make(other_zev, self.c.manager)
        response = self.client.post(f"{self.URL}read-all/?zev={self.c.zev.pk}")
        self.assertEqual(response.json(), {"updated": 1})
        elsewhere.refresh_from_db()
        self.assertIsNone(elsewhere.read_at)
