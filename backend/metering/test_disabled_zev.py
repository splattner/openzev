"""Disabled-ZEV access for import-log actions and participant data quality."""

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from metering.models import ImportLog, MeterReading
from testing.factories import MeteringPointFactory, UserFactory, ZevFactory, assignment_for
from testing.helpers import authenticate
from zev.models import ZevAccessGrant, ZevAccessRole


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("role", ["manager", "viewer", "admin"])
def test_disabled_import_log_deletion(zev, owner_user, admin_user, bulk, role):
    zev.disabled_at = timezone.now()
    zev.save()
    user = admin_user if role == "admin" else owner_user
    if role == "viewer":
        user = UserFactory()
        ZevAccessGrant.objects.create(zev=zev, user=user, role=ZevAccessRole.VIEWER)
    log = ImportLog.objects.create(zev=zev, imported_by=owner_user, batch_id=uuid.uuid4(), source="csv")
    reading = MeterReading.objects.create(
        metering_point=MeteringPointFactory(zev=zev), timestamp=timezone.now(),
        energy_kwh="1.0", import_batch=log.batch_id,
    )
    client = APIClient()
    authenticate(client, user)
    url = "/api/v1/metering/import-logs/"

    if bulk:
        response = client.post(f"{url}bulk-delete/", {"zev_id": str(zev.pk)}, format="json")
    else:
        response = client.delete(f"{url}{log.pk}/")

    assert response.status_code == {"manager": 400, "viewer": 403, "admin": 200}[role], response.content
    assert ImportLog.objects.filter(pk=log.pk).exists() == (role != "admin")
    assert MeterReading.objects.filter(pk=reading.pk).exists() == (role != "admin")


def test_bulk_delete_with_a_disabled_zev_preserves_the_entire_selection(zev, owner_user, owner_client):
    disabled = ZevFactory(owner=owner_user, disabled_at=timezone.now())
    logs = [ImportLog.objects.create(zev=community, imported_by=owner_user, batch_id=uuid.uuid4(), source="csv")
            for community in (zev, disabled)]
    readings = [MeterReading.objects.create(
        metering_point=MeteringPointFactory(zev=log.zev), timestamp=timezone.now(),
        energy_kwh="1.0", import_batch=log.batch_id,
    ) for log in logs]

    response = owner_client.post("/api/v1/metering/import-logs/bulk-delete/", {"mode": "all"}, format="json")

    assert response.status_code == 400, response.content
    assert ImportLog.objects.filter(pk__in=[log.pk for log in logs]).count() == 2
    assert MeterReading.objects.filter(pk__in=[reading.pk for reading in readings]).count() == 2


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("role", ["participant", "manager", "viewer", "admin"])
def test_data_quality_visibility(zev, participant, participant_user, admin_user, disabled, role):
    participant.user = participant_user
    participant.save()
    assignment = assignment_for(participant)
    zev.disabled_at = timezone.now() if disabled else None
    zev.save()
    if role in ("manager", "viewer"):
        ZevAccessGrant.objects.create(zev=zev, user=participant_user, role=role)
    client = APIClient()
    authenticate(client, admin_user if role == "admin" else participant_user)

    response = client.get("/api/v1/metering/readings/data-quality-status/", {
        "zev_id": str(zev.pk), "date_from": "2026-01-01", "date_to": "2026-01-02",
    })

    assert response.status_code == 200, response.content
    meters = response.json()["metering_points"]
    assert [meter["id"] for meter in meters] == (
        [] if disabled and role == "participant" else [str(assignment.metering_point_id)]
    )
