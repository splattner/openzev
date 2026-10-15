"""Custom tariff writes must obey the same disabled-ZEV rule as CRUD."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tariffs.models import Tariff, TariffPeriod
from testing.factories import TariffFactory, TariffPeriodFactory, UserFactory
from testing.helpers import authenticate
from zev.models import ZevAccessGrant, ZevAccessRole


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("role", ["manager", "viewer", "admin"])
@pytest.mark.parametrize("action, payload, ok_status", [
    ("new-version", {"valid_from": "2027-01-01"}, 201),
    ("duplicate", {"name": "Copy"}, 201),
    ("rename-series", {"name": "Renamed"}, 200),
])
def test_custom_write_access(zev, owner_user, admin_user, disabled, role, action, payload, ok_status):
    tariff = TariffFactory(zev=zev)
    TariffPeriodFactory(tariff=tariff)
    if disabled:
        zev.disabled_at = timezone.now()
        zev.save()
    user = admin_user if role == "admin" else owner_user
    if role == "viewer":
        user = UserFactory()
        ZevAccessGrant.objects.create(zev=zev, user=user, role=ZevAccessRole.VIEWER)
    client = APIClient()
    authenticate(client, user)
    url = f"/api/v1/tariffs/tariffs/{tariff.pk}/"
    assert client.get(url).status_code == 200
    tariffs = Tariff.objects.filter(zev=zev).order_by("pk")
    periods = TariffPeriod.objects.filter(tariff__zev=zev).order_by("pk")
    before_tariffs = list(tariffs.values())
    before_periods = list(periods.values())

    response = client.post(f"{url}{action}/", payload, format="json")

    expected = ok_status
    if role == "viewer":
        expected = 403
    elif disabled and role == "manager":
        expected = 400
    assert response.status_code == expected, response.content
    if expected != ok_status:
        assert list(tariffs.values()) == before_tariffs
        assert list(periods.values()) == before_periods
