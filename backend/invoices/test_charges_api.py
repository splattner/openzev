"""The charges API (#924): scoping, validation, the lock after issue, audit."""

from datetime import date

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent, AuditEventStatus
from testing import factories
from testing.helpers import authenticate
from zev.models import ZevAccessGrant, ZevAccessRole

from .engine import generate_invoice
from .models import Charge, InvoiceStatus

pytestmark = pytest.mark.django_db

URL = "/api/v1/invoices/charges/"
JAN = date(2026, 1, 1)
JAN_END = date(2026, 1, 31)


def payload(zev, **overrides):
    return {
        "zev": str(zev.pk), "description": "Porto", "amount_chf": "30.00",
        "charge_date": "2026-01-15", **overrides,
    }


def client_for(user):
    client = APIClient()
    authenticate(client, user)
    return client


def issue(invoice):
    invoice.status = InvoiceStatus.APPROVED
    invoice.approved_at = timezone.now()
    invoice.save()


def test_a_manager_creates_lists_updates_and_deletes_a_charge(owner_client, zev):
    created = owner_client.post(URL, payload(zev), format="json")
    assert created.status_code == 201, created.content
    charge_id = created.data["id"]
    assert created.data["is_locked"] is False

    listed = owner_client.get(URL, {"zev_id": str(zev.pk)})
    assert [row["id"] for row in listed.data["results"]] == [charge_id]

    patched = owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "45.00"}, format="json")
    assert patched.status_code == 200 and patched.data["amount_chf"] == "45.00"

    assert owner_client.delete(f"{URL}{charge_id}/").status_code == 204
    assert not Charge.objects.exists()


def test_the_period_filter_keeps_charges_dated_within_it(owner_client, zev):
    owner_client.post(URL, payload(zev, charge_date="2026-01-15"), format="json")
    owner_client.post(URL, payload(zev, charge_date="2026-02-15"), format="json")

    listed = owner_client.get(URL, {"period_start": "2026-02-01", "period_end": "2026-02-28"})

    assert [row["charge_date"] for row in listed.data["results"]] == ["2026-02-15"]


def test_the_participant_filter_includes_charges_for_everyone_and_for_that_participant(owner_client, zev):
    mine, other = factories.ParticipantFactory(zev=zev), factories.ParticipantFactory(zev=zev)
    owner_client.post(URL, payload(zev, description="Alle"), format="json")
    owner_client.post(URL, payload(
        zev, description="Meins", allocation="selected_participants", participants=[str(mine.pk)],
    ), format="json")
    owner_client.post(URL, payload(
        zev, description="Seins", allocation="selected_participants", participants=[str(other.pk)],
    ), format="json")

    listed = owner_client.get(URL, {"participant": str(mine.pk)})

    assert {row["description"] for row in listed.data["results"]} == {"Alle", "Meins"}


@pytest.mark.parametrize("overrides, field", [
    ({"amount_chf": "0.00"}, "amount_chf"),
    ({"amount_chf": "-5.00"}, "amount_chf"),
    ({"description": "   "}, "description"),
    ({"allocation": "selected_participants"}, "participants"),
])
def test_invalid_charges_are_refused(owner_client, zev, overrides, field):
    response = owner_client.post(URL, payload(zev, **overrides), format="json")

    assert response.status_code == 400 and field in response.data


def test_participants_are_only_allowed_when_selecting_and_must_belong_to_the_zev(owner_client, zev):
    member = factories.ParticipantFactory(zev=zev)
    stranger = factories.ParticipantFactory()

    for body in (
        payload(zev, participants=[str(member.pk)]),
        payload(zev, allocation="selected_participants", participants=[str(stranger.pk)]),
    ):
        response = owner_client.post(URL, body, format="json")
        assert response.status_code == 400 and "participants" in response.data


def test_another_communitys_zev_cannot_be_written_to(owner_client, zev):
    foreign = factories.ZevFactory()

    response = owner_client.post(URL, payload(foreign), format="json")

    assert response.status_code == 400 and "zev" in response.data
    assert not Charge.objects.exists()


def test_other_accounts_cannot_manage_charges(zev, owner_client, participant_user):
    factories.ParticipantFactory(zev=zev, user=participant_user)
    viewer = factories.UserFactory()
    ZevAccessGrant.objects.create(zev=zev, user=viewer, role=ZevAccessRole.VIEWER)
    charge_id = owner_client.post(URL, payload(zev), format="json").data["id"]

    assert client_for(viewer).get(URL).data["count"] == 1
    assert client_for(viewer).post(URL, payload(zev), format="json").status_code == 403
    assert client_for(viewer).delete(f"{URL}{charge_id}/").status_code == 403
    assert client_for(participant_user).get(URL).status_code == 403
    assert APIClient().get(URL).status_code == 401


def test_a_manager_of_another_zev_sees_nothing(owner_client, zev):
    owner_client.post(URL, payload(zev), format="json")
    stranger = factories.OwnerFactory()
    factories.ZevFactory(owner=stranger)

    assert client_for(stranger).get(URL).data["count"] == 0


def test_a_disabled_zev_refuses_writes_unless_admin(owner_client, admin_client, zev):
    charge_id = owner_client.post(URL, payload(zev), format="json").data["id"]
    zev.disabled_at = timezone.now()
    zev.save()

    assert owner_client.post(URL, payload(zev), format="json").status_code == 400
    assert owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "1.00"}, format="json").status_code == 400
    assert owner_client.delete(f"{URL}{charge_id}/").status_code == 400
    assert admin_client.patch(f"{URL}{charge_id}/", {"amount_chf": "1.00"}, format="json").status_code == 200


# ── the lock once an invoice is issued ───────────────────────────────────────

def issued_charge(owner_client, zev):
    member = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    charge_id = owner_client.post(URL, payload(zev), format="json").data["id"]
    invoice = generate_invoice(member, JAN, JAN_END)
    return charge_id, invoice


def test_a_charge_on_a_draft_invoice_stays_editable(owner_client, zev):
    charge_id, _invoice = issued_charge(owner_client, zev)

    assert owner_client.get(f"{URL}{charge_id}/").data["is_locked"] is False
    assert owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "5.00"}, format="json").status_code == 200


def test_an_issued_invoice_locks_the_charge(owner_client, zev):
    charge_id, invoice = issued_charge(owner_client, zev)
    issue(invoice)

    assert owner_client.get(f"{URL}{charge_id}/").data["is_locked"] is True
    assert owner_client.get(URL).data["results"][0]["is_locked"] is True
    for response in (
        owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "5.00"}, format="json"),
        owner_client.delete(f"{URL}{charge_id}/"),
    ):
        assert response.status_code == 409
        assert response.data["code"] == "charge_locked"
        assert response.data["invoice_number"] == invoice.invoice_number
    assert Charge.objects.get(pk=charge_id).amount_chf == 30
    assert AuditEvent.objects.filter(
        action_type__in=["charge.update_denied", "charge.delete_denied"], status=AuditEventStatus.DENIED,
    ).count() == 2


def test_any_issued_invoice_of_the_period_locks_the_charge_not_only_a_bearers(owner_client, zev):
    # The charge is borne by one member; another member's invoice is the one issued.
    bearer = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    other = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    created = owner_client.post(
        URL, payload(zev, allocation="selected_participants", participants=[str(bearer.pk)]), format="json",
    )
    assert created.status_code == 201
    issue(generate_invoice(other, JAN, JAN_END))

    assert owner_client.get(f"{URL}{created.data['id']}/").data["is_locked"] is True
    assert owner_client.patch(f"{URL}{created.data['id']}/", {"amount_chf": "5.00"}, format="json").status_code == 409
    assert owner_client.post(URL, payload(zev, charge_date="2026-01-25"), format="json").status_code == 400


def test_a_cancelled_unissued_invoice_does_not_lock(owner_client, zev):
    charge_id, invoice = issued_charge(owner_client, zev)
    invoice.status = InvoiceStatus.CANCELLED
    invoice.save()

    assert owner_client.get(f"{URL}{charge_id}/").data["is_locked"] is False


def test_a_new_charge_cannot_land_on_a_date_an_issued_invoice_covers(owner_client, zev):
    _charge_id, invoice = issued_charge(owner_client, zev)
    issue(invoice)

    response = owner_client.post(URL, payload(zev, charge_date="2026-01-20"), format="json")

    assert response.status_code == 400
    assert invoice.invoice_number in str(response.data["charge_date"])
    assert owner_client.post(URL, payload(zev, charge_date="2026-02-02"), format="json").status_code == 201


def test_moving_a_charge_into_an_issued_period_is_refused(owner_client, zev):
    member = factories.ParticipantFactory(zev=zev, valid_from=JAN)
    issue(generate_invoice(member, JAN, JAN_END))
    charge_id = owner_client.post(URL, payload(zev, charge_date="2026-02-10"), format="json").data["id"]

    response = owner_client.patch(f"{URL}{charge_id}/", {"charge_date": "2026-01-10"}, format="json")

    assert response.status_code == 400 and "charge_date" in response.data


def test_editing_a_charge_after_issue_never_reaches_the_invoice(owner_client, zev):
    charge_id, invoice = issued_charge(owner_client, zev)
    issue(invoice)
    owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "99.00"}, format="json")

    assert invoice.items.get(tariff_category="other").total_chf == 30


# ── audit and preview ────────────────────────────────────────────────────────

def test_create_update_and_delete_are_audited(owner_client, zev):
    charge_id = owner_client.post(URL, payload(zev), format="json").data["id"]
    owner_client.patch(f"{URL}{charge_id}/", {"amount_chf": "31.00"}, format="json")
    owner_client.delete(f"{URL}{charge_id}/")

    recorded = set(AuditEvent.objects.filter(target_id=charge_id).values_list("action_type", flat=True))
    assert recorded == {"charge.create", "charge.update", "charge.delete"}


def test_preview_answers_with_the_split_the_engine_bills(owner_client, zev):
    members = [factories.ParticipantFactory(zev=zev, valid_from=JAN) for _ in range(3)]

    response = owner_client.post(f"{URL}preview/", payload(zev, amount_chf="10.00"), format="json")

    assert response.status_code == 200
    assert {row["share_chf"] for row in response.data["bearers"]} == {"3.33"}
    assert {row["participant"] for row in response.data["bearers"]} == {str(m.pk) for m in members}
    assert (response.data["total_billed_chf"], response.data["unrecovered_chf"]) == ("9.99", "0.01")
    assert not Charge.objects.exists()
