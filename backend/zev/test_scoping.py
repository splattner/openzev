"""Direct unit tests for the shared ZEV queryset scoping mixin."""

import pytest

from zev.models import Zev
from zev.scoping import ZevScopedQuerySetMixin
from testing.factories import AdminFactory, OwnerFactory, ParticipantFactory, ParticipantUserFactory, ZevFactory

pytestmark = pytest.mark.django_db


class _FakeRequest:
    """Stands in for a DRF ``Request``: the mixin reads both of these."""

    def __init__(self, user, query_params=None):
        self.user = user
        self.query_params = query_params or {}


class _ZevScope(ZevScopedQuerySetMixin):
    zev_owner_filter = "owner"
    participant_filter = "participants__user"
    participant_distinct = True

    def __init__(self, user, query_params=None):
        self.request = _FakeRequest(user, query_params)


class _OwnerOnlyScope(ZevScopedQuerySetMixin):
    zev_owner_filter = "owner"
    participant_filter = None

    def __init__(self, user, query_params=None):
        self.request = _FakeRequest(user, query_params)


class TestZevScopedQuerySetMixin:
    def test_admin_sees_everything(self):
        admin = AdminFactory()
        ZevFactory()
        ZevFactory()

        qs = _ZevScope(admin).scope_queryset(Zev.objects.all())

        assert qs.count() == 2

    def test_zev_owner_sees_only_own_zevs(self):
        owner = OwnerFactory()
        own_zev = ZevFactory(owner=owner)
        ZevFactory()

        qs = _ZevScope(owner).scope_queryset(Zev.objects.all())

        assert list(qs) == [own_zev]

    def test_participant_sees_only_linked_zevs(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        ZevFactory()
        user = ParticipantUserFactory()
        ParticipantFactory(zev=zev, user=user)

        qs = _ZevScope(user).scope_queryset(Zev.objects.all())

        assert list(qs) == [zev]

    def test_participant_gets_nothing_for_owner_only_resources(self):
        owner = OwnerFactory()
        zev = ZevFactory(owner=owner)
        user = ParticipantUserFactory()
        ParticipantFactory(zev=zev, user=user)

        qs = _OwnerOnlyScope(user).scope_queryset(Zev.objects.all())

        assert qs.count() == 0
