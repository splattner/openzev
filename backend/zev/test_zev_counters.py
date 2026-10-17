"""Settings writes must preserve document numbers allocated after loading a ZEV."""

from datetime import timedelta

import pytest
from django.utils import timezone

from zev.models import Zev
from zev.serializers import ZevSerializer

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("partial,data", [
    (True, {"name": "Settings changed"}),
    (True, {}),
    (False, {"name": "Settings changed"}),
])
def test_stale_settings_save_preserves_allocations(zev, partial, data):
    stale = Zev.objects.get(pk=zev.pk)
    serializer = ZevSerializer(stale, data=data, partial=partial)
    serializer.is_valid(raise_exception=True)

    zev.next_invoice_number()
    zev.next_contract_number()
    Zev.objects.filter(pk=zev.pk).update(
        bank_name="Concurrently changed bank", vat_mode="registered", vat_number="CHE-123.456.789",
    )
    serializer.save()

    zev.refresh_from_db()
    assert zev.invoice_counter == zev.contract_counter == 2
    assert zev.name == data.get("name", stale.name)
    assert zev.bank_name == "Concurrently changed bank"
    assert zev.vat_mode == "registered"
    assert zev.vat_number == "CHE-123.456.789"
    assert serializer.data["invoice_counter"] == serializer.data["contract_counter"] == 2
    assert serializer.data["bank_name"] == "Concurrently changed bank"


@pytest.mark.parametrize("method", ["patch", "put"])
def test_settings_request_preserves_allocations_after_loading(owner_client, zev, monkeypatch, method):
    original_update = ZevSerializer.update

    def allocate_before_save(serializer, instance, validated_data):
        concurrent = Zev.objects.get(pk=instance.pk)
        concurrent.next_invoice_number()
        concurrent.next_contract_number()
        return original_update(serializer, instance, validated_data)

    monkeypatch.setattr(ZevSerializer, "update", allocate_before_save)
    response = getattr(owner_client, method)(
        f"/api/v1/zev/zevs/{zev.pk}/", {"name": "Renamed"}, format="json",
    )

    assert response.status_code == 200, response.data
    zev.refresh_from_db()
    assert zev.name == "Renamed"
    assert zev.invoice_counter == zev.contract_counter == 2
    assert response.data["invoice_counter"] == response.data["contract_counter"] == 2


@pytest.mark.parametrize("method,data", [
    ("patch", {"name": "Renamed"}),
    ("put", {"name": "Renamed"}),
    ("patch", {}),
])
def test_api_counter_edits_are_ignored(owner_client, zev, method, data):
    old_name = zev.name
    old_timestamp = timezone.now() - timedelta(days=1)
    Zev.objects.filter(pk=zev.pk).update(invoice_counter=7, contract_counter=8, updated_at=old_timestamp)
    response = getattr(owner_client, method)(
        f"/api/v1/zev/zevs/{zev.pk}/",
        {**data, "invoice_counter": 1, "contract_counter": 99},
        format="json",
    )

    assert response.status_code == 200, response.data
    zev.refresh_from_db()
    assert zev.name == data.get("name", old_name)
    assert zev.invoice_counter == response.data["invoice_counter"] == 7
    assert zev.contract_counter == response.data["contract_counter"] == 8
    assert zev.updated_at > old_timestamp


def test_admin_create_ignores_counters(admin_client):
    response = admin_client.post(
        "/api/v1/zev/zevs/",
        {"name": "New ZEV", "invoice_counter": 99, "contract_counter": 99},
        format="json",
    )

    assert response.status_code == 201, response.data
    zev = Zev.objects.get(pk=response.data["id"])
    assert zev.invoice_counter == response.data["invoice_counter"] == 1
    assert zev.contract_counter == response.data["contract_counter"] == 1


@pytest.mark.parametrize("initial,data,concurrent_data", [
    (
        {"vat_mode": "registered", "vat_number": "CHE-123.456.789"},
        {"vat_number": "CHE-987.654.321"},
        {"vat_mode": "not_registered", "vat_number": ""},
    ),
    (
        {"vat_mode": "not_registered", "vat_number": ""},
        {"vat_mode": "inclusive"},
        {"vat_mode": "registered", "vat_number": "CHE-987.654.321"},
    ),
])
def test_stale_vat_update_preserves_validated_pair(zev, initial, data, concurrent_data):
    Zev.objects.filter(pk=zev.pk).update(**initial)
    stale = Zev.objects.get(pk=zev.pk)
    serializer = ZevSerializer(stale, data=data, partial=True)
    serializer.is_valid(raise_exception=True)

    concurrent = ZevSerializer(Zev.objects.get(pk=zev.pk), data=concurrent_data, partial=True)
    concurrent.is_valid(raise_exception=True)
    concurrent.save()
    serializer.save()

    zev.refresh_from_db()
    assert zev.vat_mode == data.get("vat_mode", initial["vat_mode"])
    assert zev.vat_number == data.get("vat_number", initial["vat_number"])
    zev.full_clean()
