"""Manager-removal APIs serialize, refresh authority and preserve their invariants."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Event
from time import monotonic, sleep

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AppSettings, User, UserRole
from audit.models import AuditEvent
from testing.helpers import authenticate, create_managed_zev, make_user

from . import access, onboarding
from .models import Participant, Party, PartyRole, Zev, ZevAccessGrant, ZevAccessRole, ZevPartyRole
from .parties import assign_role
from .services import issue_invitation
from .views_access import DISABLED_MESSAGE, LAST_MANAGER_MESSAGE

pytestmark = pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires PostgreSQL row locks")
SUCCESS = {
    "grant_delete": 204, "grant_downgrade": 200, "grant_end": 200, "account_delete": 204,
    "participant_unlink": 200, "participant_delete": 204, "role_replace": 201, "role_end": 204,
}


@pytest.fixture
def manager_world(transactional_db):
    # Create settings before threads start so authentication cannot serialize the requests.
    AppSettings.load()
    return (
        create_managed_zev(name="Concurrent manager removals"),
        make_user("manager_admin", UserRole.ADMIN), make_user("manager_first"), make_user("manager_second"),
    )


def manager_grant(zev, user):
    return ZevAccessGrant.objects.create(
        zev=zev, user=user, role=ZevAccessRole.MANAGER, valid_from=timezone.localdate() - timedelta(days=1),
    )


def prepare_removal(zev, user, kind, role=PartyRole.ISSUER):
    if kind not in SUCCESS:
        raise ValueError(f"Unknown removal kind: {kind}")
    today = timezone.localdate()
    if kind.startswith("grant_") or kind == "account_delete":
        grant = manager_grant(zev, user)
        url = f"/api/v1/zev/zevs/{zev.pk}/access/{grant.pk}/"
        if kind == "grant_downgrade":
            return "patch", url, {"role": ZevAccessRole.VIEWER}
        if kind == "grant_end":
            return "patch", url, {"valid_to": (today + timedelta(days=30)).isoformat()}
        if kind == "account_delete":
            return "delete", f"/api/v1/auth/users/{user.pk}/", {}
        return "delete", url, {}
    if kind.startswith("participant_"):
        participant = Participant.objects.create(zev=zev, user=user, last_name=user.username, valid_from=today)
        party = participant.party
    else:
        party = Party.objects.create(zev=zev, user=user, last_name=user.username)
    row = assign_role(zev, party, role, today)
    if kind == "participant_unlink":
        return "post", f"/api/v1/zev/participants/{participant.pk}/unlink-account/", {}
    if kind == "participant_delete":
        return "delete", f"/api/v1/zev/participants/{participant.pk}/", {}
    if kind == "role_replace":
        nobody = Party.objects.create(zev=zev, last_name="Without an account")
        return "post", "/api/v1/zev/party-roles/", {
            "zev": str(zev.pk), "party": str(nobody.pk), "role": role, "valid_from": today.isoformat(),
        }
    return "post", f"/api/v1/zev/party-roles/{row.pk}/end/", {"last_day": (today - timedelta(days=1)).isoformat()}


def perform_request(user, action):
    client = APIClient()
    authenticate(client, user)
    method, url, data = action
    return getattr(client, method)(url, data, format="json")


def run_worker(operation):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SET statement_timeout = '20s'")
            cursor.execute("SELECT pg_backend_pid()")
            pid = cursor.fetchone()[0]
        return operation(pid)
    finally:
        connections.close_all()


@contextmanager
def held(operation):
    ready, release = Event(), Event()
    holder_pid = []

    def hold(pid):
        with transaction.atomic():
            result = operation()
            holder_pid.append(pid)
            ready.set()
            assert release.wait(15), "Holder transaction was not released"
            return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(run_worker, hold)
        try:
            deadline = monotonic() + 15
            while not ready.wait(0.05):
                if holder.done():
                    holder.result()
                assert monotonic() < deadline, "Holder operation did not complete"
            yield holder_pid[0], holder
        finally:
            release.set()
            holder.result(timeout=25)


def waits_for_lock(pid, holder_pid, future):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_blocking_pids(%s)", [pid])
            if holder_pid in cursor.fetchone()[0]:
                return True
        if future.done():
            return False
        sleep(0.01)
    return False


def contend(first, second, inspect_wait=None):
    """Hold the completed first request uncommitted while the contender waits."""
    connected = Event()
    contender_pid = []

    def attempt(pid):
        contender_pid.append(pid)
        connected.set()
        return second()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with held(first) as (holder_pid, holder):
            contender = pool.submit(run_worker, attempt)
            if not connected.wait(15):
                contender.result(timeout=25)
                pytest.fail("Contender did not connect")
            if not waits_for_lock(contender_pid[0], holder_pid, contender):
                if contender.done():
                    contender.result()
                pytest.fail("Did not wait for the holder")
            if inspect_wait is not None:
                inspect_wait()
        return holder.result(), contender.result(timeout=25)


@pytest.mark.parametrize("first,second", [
    ("grant_delete", "grant_delete"),
    ("grant_delete", "grant_downgrade"),
    ("grant_delete", "grant_end"),
    ("grant_delete", "role_end"),
    ("grant_delete", "role_replace"),
    ("role_end", "role_end"),
    ("account_delete", "grant_delete"),
    ("grant_delete", "account_delete"),
    ("grant_delete", "participant_unlink"),
    ("grant_delete", "participant_delete"),
])
def test_manager_removals_serialize(manager_world, first, second):
    zev, admin, first_user, second_user = manager_world
    first_action = prepare_removal(zev, first_user, first)
    second_action = prepare_removal(zev, second_user, second, PartyRole.REPRESENTATIVE)
    first_result, second_result = contend(
        lambda: perform_request(admin, first_action), lambda: perform_request(admin, second_action),
    )
    assert first_result.status_code == SUCCESS[first], first_result.data
    assert second_result.status_code == (403 if second == "account_delete" else 400), second_result.data
    if second.startswith("grant_"):
        assert second_result.data == {"detail": LAST_MANAGER_MESSAGE}
    elif second.startswith("role_"):
        assert second_result.data == {"party": [access.NO_MANAGER_LEFT]}
    else:
        assert second_result.data == {"detail": access.NO_MANAGER_LEFT}
    access.invalidate(first_user)
    access.invalidate(second_user)
    assert access.has_manager(zev)
    assert not access.can_manage(first_user, zev)
    assert access.can_manage(second_user, zev), "The rejected removal was not rolled back"
    assert AuditEvent.objects.filter(status="success").count() == 1, "The refused write left a success audit"


def test_account_deletion_keeps_a_manager_in_every_zev(manager_world):
    zev, admin, survivor, target = manager_world
    action = prepare_removal(zev, target, "account_delete")
    manager_grant(zev, survivor)
    other = create_managed_zev(name="Must retain its role manager")
    party = Party.objects.create(zev=other, user=target, last_name="Issuer")
    role = assign_role(other, party, PartyRole.ISSUER, timezone.localdate())
    grant = manager_grant(other, survivor)
    first, second = contend(
        lambda: perform_request(admin, ("delete", f"/api/v1/zev/zevs/{other.pk}/access/{grant.pk}/", {})),
        lambda: perform_request(admin, action),
    )
    assert first.status_code == 204
    assert second.status_code == 403
    assert second.data == {"detail": access.NO_MANAGER_LEFT}
    assert User.objects.filter(pk=target.pk).exists()
    assert target.zev_grants.get(zev=zev).valid_to is None
    party.refresh_from_db()
    assert party.user_id == target.pk
    assert party.roles.filter(pk=role.pk, valid_to=None).exists()
    assert access.has_manager(zev) and access.has_manager(other)


@pytest.mark.parametrize("method", ["delete", "patch"])
def test_waiting_grant_write_rereads_the_revoked_grant(manager_world, method):
    zev, admin, first_user, second_user = manager_world
    action = prepare_removal(zev, first_user, "grant_delete")
    manager_grant(zev, second_user)
    data = {"valid_to": (timezone.localdate() + timedelta(days=30)).isoformat()} if method == "patch" else {}
    first, second = contend(
        lambda: perform_request(admin, action), lambda: perform_request(admin, (method, action[1], data)),
    )
    assert first.status_code == 204
    assert second.status_code == 404
    assert first_user.zev_grants.get().valid_to < timezone.localdate()
    assert access.has_manager(zev)


def test_waiting_role_end_reports_a_removed_role(manager_world):
    zev, admin, first_user, second_user = manager_world
    action = prepare_removal(zev, first_user, "role_end")
    manager_grant(zev, second_user)
    first, second = contend(lambda: perform_request(admin, action), lambda: perform_request(admin, action))
    assert first.status_code == 204
    assert second.status_code == 400
    assert second.data == {"party": ["This role was removed in the meantime."]}
    assert access.has_manager(zev)


@pytest.mark.parametrize("change", ["revoke", "disable"])
@pytest.mark.parametrize("kind", ["grant_delete", "grant_downgrade", "role_end", "role_replace", "participant_delete"])
def test_waiting_write_refreshes_authority(manager_world, change, kind):
    zev, admin, actor, target = manager_world
    revoke_actor = prepare_removal(zev, actor, "grant_delete")
    action = prepare_removal(zev, target, kind)
    manager_grant(zev, make_user("remaining_manager"))

    def change_authority():
        if change == "revoke":
            assert perform_request(admin, revoke_actor).status_code == 204
        else:
            access.lock_zevs(zev)
            zev.disabled_at = timezone.now()
            zev.save(update_fields=["disabled_at"])

    _, response = contend(change_authority, lambda: perform_request(actor, action))
    expected = 403
    if kind == "role_replace" or (change == "disable" and kind.startswith("grant_")):
        expected = 400
    assert response.status_code == expected, response.data
    if kind.startswith("grant_"):
        detail = DISABLED_MESSAGE if change == "disable" else "Only a manager of this ZEV can change who has access."
        assert response.data == {"detail": detail}
    access.invalidate(target)
    assert access.can_manage(target, zev), "The unauthorized write changed the target's access"


@pytest.mark.parametrize("kind", ["account_delete", "participant_unlink"])
def test_waiting_admin_write_rechecks_platform_role(manager_world, kind):
    zev, admin, survivor, target = manager_world
    action = prepare_removal(zev, target, kind)
    manager_grant(zev, survivor)

    def demote_admin():
        access.lock_zevs(zev)
        User.objects.filter(pk=admin.pk).update(role=UserRole.USER)

    _, response = contend(demote_admin, lambda: perform_request(admin, action))
    assert response.status_code == 403, response.data
    access.invalidate(target)
    assert access.can_manage(target, zev)


def test_waiting_account_deletion_audits_deleted_caller(manager_world):
    _, admin, _, target = manager_world
    other_admin = make_user("deleting_admin", UserRole.ADMIN)
    admin_id = admin.pk
    action = "delete", f"/api/v1/auth/users/{target.pk}/", {}

    def delete_caller():
        response = perform_request(other_admin, ("delete", f"/api/v1/auth/users/{admin_id}/", {}))
        assert response.status_code == 204, response.data

    _, response = contend(
        lambda: User.objects.locked().get(pk=target.pk), lambda: perform_request(admin, action), delete_caller,
    )
    assert response.status_code == 403, response.data
    assert response.data == {"detail": "This account is no longer active."}
    assert not User.objects.filter(pk=admin_id).exists()
    assert User.objects.filter(pk=target.pk).exists()
    event = AuditEvent.objects.get(action_type="user.delete", target_id=str(target.pk))
    assert event.status == "denied"
    assert event.actor_user_id is None
    assert event.actor_display == admin.email
    assert event.actor_role_snapshot == UserRole.ADMIN


@pytest.mark.parametrize("relationship", ["grant", "party", "same_zev_party"])
def test_account_deletion_refuses_new_relationships(manager_world, monkeypatch, relationship):
    zev, admin, survivor, target = manager_world
    if relationship == "same_zev_party":
        prepare_removal(zev, target, "role_end")
        action = "delete", f"/api/v1/auth/users/{target.pk}/", {}
        other = zev
    else:
        action = prepare_removal(zev, target, "account_delete")
        other = create_managed_zev(owner=survivor, name="Newly managed community")
    manager_grant(zev, survivor)
    payload = {"email": target.email, "role": ZevAccessRole.MANAGER}
    if relationship != "grant":
        party = Party.objects.create(zev=other, last_name="New party", email=target.email)
        payload = {"party": str(party.pk), "role": ZevAccessRole.MANAGER}
    monkeypatch.setattr("zev.views_access.send_granted_notice", lambda *args: None)
    first, second = contend(
        lambda: perform_request(admin, ("post", f"/api/v1/zev/zevs/{other.pk}/access/", payload)),
        lambda: perform_request(admin, action),
    )
    assert first.status_code == 201, first.data
    assert second.status_code == 400, second.data
    assert second.data == {"detail": "This account's relationships changed. Retry deletion."}
    assert User.objects.filter(pk=target.pk).exists()
    assert target.zev_grants.filter(zev=other, valid_to=None).exists()
    if relationship != "grant":
        party.refresh_from_db()
        assert party.user_id == target.pk
    assert AuditEvent.objects.filter(action_type="user.delete", target_id=str(target.pk), status="denied").exists()


def test_account_deletion_locks_party_before_user(manager_world):
    zev, admin, survivor, target = manager_world
    prepare_removal(zev, target, "role_end")
    party = target.parties.get()
    manager_grant(zev, survivor)

    def hold_party():
        Party.objects.select_for_update().get(pk=party.pk)

    def user_is_available():
        with transaction.atomic():
            User.objects.select_for_update(no_key=True, nowait=True).get(pk=target.pk)

    _, response = contend(
        hold_party, lambda: perform_request(admin, ("delete", f"/api/v1/auth/users/{target.pk}/", {})),
        user_is_available,
    )
    assert response.status_code == 204
    party.refresh_from_db()
    assert party.user_id is None


def test_multiple_zevs_lock_in_id_order_even_with_reversed_arguments(manager_world):
    zev, _, _, _ = manager_world
    other = create_managed_zev(name="Lock ordering")
    lower, higher = sorted((zev, other), key=lambda row: row.pk)

    def hold_lower():
        Zev.objects.select_for_update(no_key=True).get(pk=lower.pk)

    def lock_reversed():
        with access.keeping_a_manager(higher, lower):
            pass

    def higher_is_available():
        with transaction.atomic():
            Zev.objects.select_for_update(no_key=True, nowait=True).get(pk=higher.pk)

    contend(hold_lower, lock_reversed, higher_is_available)


def test_manager_removal_allows_concurrent_foreign_key_insert(manager_world):
    zev, admin, first_user, second_user = manager_world
    action = prepare_removal(zev, first_user, "grant_delete")
    manager_grant(zev, second_user)
    viewer = make_user("new_viewer")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with held(lambda: perform_request(admin, action)) as (_, holder):
            created = pool.submit(run_worker, lambda _pid: ZevAccessGrant.objects.create(
                zev=zev, user=viewer, role=ZevAccessRole.VIEWER,
            ).pk).result(timeout=15)
    assert holder.result().status_code == 204
    assert ZevAccessGrant.objects.filter(pk=created).exists()


def linked_participant(zev, user):
    return Participant.objects.create(
        zev=zev, user=user, last_name=user.username, email=user.email, valid_from=timezone.localdate(),
    )


@pytest.mark.parametrize("first,second,expected", [
    ("delete", "delete", 404), ("delete", "unlink-account", 404), ("unlink-account", "unlink-account", 400),
])
def test_waiting_participant_removal_rereads_target(manager_world, first, second, expected):
    zev, admin, user, fallback = manager_world
    manager_grant(zev, fallback)
    participant = linked_participant(zev, user)
    url = f"/api/v1/zev/participants/{participant.pk}/"

    def removal(kind):
        return ("delete", url, {}) if kind == "delete" else ("post", f"{url}unlink-account/", {})

    done, waiting = contend(
        lambda: perform_request(admin, removal(first)), lambda: perform_request(admin, removal(second)),
    )
    assert done.status_code == (204 if first == "delete" else 200)
    assert waiting.status_code == expected, waiting.data
    assert AuditEvent.objects.filter(action_type="participant.unlink_account", target_id=str(participant.pk)).count() == (
        1 if first == "unlink-account" else 0
    )


def test_waiting_unlink_audits_the_current_account(manager_world):
    zev, admin, original, replacement = manager_world
    participant = linked_participant(zev, original)
    url = f"/api/v1/zev/participants/{participant.pk}/"
    linked, unlinked = contend(
        lambda: perform_request(admin, ("post", f"{url}link-account/", {"user_id": str(replacement.pk)})),
        lambda: perform_request(admin, ("post", f"{url}unlink-account/", {})),
    )
    assert linked.status_code == unlinked.status_code == 200
    link = AuditEvent.objects.get(action_type="participant.link_account", target_id=str(participant.pk))
    unlink = AuditEvent.objects.get(action_type="participant.unlink_account", target_id=str(participant.pk))
    assert link.changes_json["user"] == {"before": str(original.pk), "after": str(replacement.pk)}
    assert unlink.changes_json["user"] == {"before": str(replacement.pk), "after": None}
    participant.refresh_from_db()
    assert participant.user_id is None


@pytest.mark.parametrize("kind", [
    "grant_create", "grant_delete", "grant_downgrade", "participant_link", "participant_unlink", "participant_delete",
])
@pytest.mark.parametrize("change", ["demote", "deactivate"])
def test_waiting_write_rechecks_authority_after_user_lock(manager_world, monkeypatch, kind, change):
    zev, admin, target, fallback = manager_world
    manager_grant(zev, fallback)
    if kind == "grant_create":
        monkeypatch.setattr("zev.views_access.send_granted_notice", lambda *args: None)
        action = "post", f"/api/v1/zev/zevs/{zev.pk}/access/", {"email": target.email, "role": ZevAccessRole.VIEWER}
    elif kind == "participant_link":
        participant = linked_participant(zev, target)
        replacement = make_user("replacement")
        action = "post", f"/api/v1/zev/participants/{participant.pk}/link-account/", {"user_id": str(replacement.pk)}
    else:
        action = prepare_removal(zev, target, kind)

    def change_actor():
        changes = {"role": UserRole.USER} if change == "demote" else {"is_active": False}
        User.objects.filter(pk=admin.pk).update(**changes)

    _, response = contend(
        lambda: User.objects.locked().get(pk=target.pk), lambda: perform_request(admin, action), change_actor,
    )
    assert response.status_code == 403, response.data
    assert not AuditEvent.objects.filter(status="success", action_type__in=[
        "zev_access.grant", "zev_access.change", "zev_access.revoke", "participant.link_account",
        "participant.unlink_account", "participant.delete",
    ]).exists()
    if kind == "grant_create":
        assert not target.zev_grants.exists()
    else:
        access.invalidate(target)
        if kind == "participant_link":
            participant.refresh_from_db()
            assert participant.user_id == target.pk
        else:
            assert access.can_manage(target, zev)


def test_waiting_grant_creation_rechecks_revoked_manager(manager_world, monkeypatch):
    zev, admin, actor, recipient = manager_world
    actor_grant = manager_grant(zev, actor)
    manager_grant(zev, make_user("remaining_manager"))
    monkeypatch.setattr("zev.views_access.send_granted_notice", lambda *args: None)

    def revoke_actor():
        response = perform_request(admin, ("delete", f"/api/v1/zev/zevs/{zev.pk}/access/{actor_grant.pk}/", {}))
        assert response.status_code == 204

    _, response = contend(
        lambda: User.objects.locked().get(pk=recipient.pk),
        lambda: perform_request(actor, ("post", f"/api/v1/zev/zevs/{zev.pk}/access/", {
            "email": recipient.email, "role": ZevAccessRole.VIEWER,
        })), revoke_actor,
    )
    assert response.status_code == 403, response.data
    assert not recipient.zev_grants.exists()


@pytest.mark.parametrize("kind", ["role_replace", "role_end"])
@pytest.mark.parametrize("change", ["demote", "deactivate"])
def test_waiting_role_write_rechecks_authority_and_rolls_back(manager_world, kind, change):
    zev, admin, target, fallback = manager_world
    action = prepare_removal(zev, target, kind)
    manager_grant(zev, fallback)
    role = ZevPartyRole.objects.get(zev=zev, role=PartyRole.ISSUER)

    def change_actor():
        changes = {"role": UserRole.USER} if change == "demote" else {"is_active": False}
        User.objects.filter(pk=admin.pk).update(**changes)

    _, response = contend(
        lambda: ZevPartyRole.objects.select_for_update().get(pk=role.pk),
        lambda: perform_request(admin, action), change_actor,
    )
    assert response.status_code == (400 if kind == "role_replace" and change == "demote" else 403), response.data
    role.refresh_from_db()
    assert role.valid_to is None
    access.invalidate(target)
    assert access.can_manage(target, zev)
    assert not AuditEvent.objects.filter(action_type__in=["party_role.assign", "party_role.end"]).exists()


def test_waiting_onboarding_consumption_cannot_undo_unlink(manager_world):
    zev, admin, user, _ = manager_world
    participant = linked_participant(zev, user)
    token = onboarding.get_or_create_for_participant(participant)
    unlinked, consumed = contend(
        lambda: perform_request(admin, ("post", f"/api/v1/zev/participants/{participant.pk}/unlink-account/", {})),
        lambda: APIClient().post("/api/v1/public/onboarding/consume/", {
            "prefix": token.prefix, "s": token.secret,
        }, format="json"),
    )
    assert unlinked.status_code == 200
    assert consumed.status_code == 404, consumed.data
    participant.refresh_from_db()
    assert participant.user_id is None
    assert onboarding.resolve(token.prefix, token.secret) is None


@pytest.mark.parametrize("same_zev", [False, True])
def test_account_deletion_refuses_new_managing_participation(manager_world, same_zev):
    zev, admin, target, fallback = manager_world
    action = prepare_removal(zev, target, "account_delete")
    manager_grant(zev, fallback)
    other = zev if same_zev else create_managed_zev(name="New participation")
    party = Party.objects.create(zev=other, last_name="New issuer")
    assign_role(other, party, PartyRole.ISSUER, timezone.localdate())
    _, response = contend(
        lambda: Participant.objects.create(zev=other, party=party, user=target, valid_from=timezone.localdate()),
        lambda: perform_request(admin, action),
    )
    assert response.status_code == (403 if same_zev else 400), response.data
    assert User.objects.filter(pk=target.pk).exists()
    assert target.participations.filter(zev=other).exists()


@pytest.mark.parametrize("kind", ["recipient", "party"])
def test_waiting_grant_creation_reports_deleted_target(manager_world, kind):
    zev, admin, recipient, _ = manager_world
    if kind == "party":
        party = Party.objects.create(zev=zev, last_name="Contact", email=recipient.email)
        delete = "delete", f"/api/v1/zev/parties/{party.pk}/", {}
        payload = {"party": str(party.pk), "role": ZevAccessRole.VIEWER}
    else:
        delete = "delete", f"/api/v1/auth/users/{recipient.pk}/", {}
        payload = {"email": recipient.email, "role": ZevAccessRole.VIEWER}
    deleted, waiting = contend(
        lambda: perform_request(admin, delete),
        lambda: perform_request(admin, ("post", f"/api/v1/zev/zevs/{zev.pk}/access/", payload)),
    )
    assert deleted.status_code == 204
    assert waiting.status_code == 404, waiting.data
    assert not ZevAccessGrant.objects.filter(zev=zev).exists()


@pytest.mark.parametrize("delete_again", [False, True])
def test_waiting_landowner_end_reports_deleted_role(manager_world, delete_again):
    zev, admin, _, _ = manager_world
    today = timezone.localdate()
    party = Party.objects.create(zev=zev, last_name="Landowner")
    role = assign_role(zev, party, PartyRole.LANDOWNER, today)
    url = f"/api/v1/zev/party-roles/{role.pk}/end/"
    yesterday = (today - timedelta(days=1)).isoformat()
    first, waiting = contend(
        lambda: perform_request(admin, ("post", url, {"last_day": yesterday})),
        lambda: perform_request(admin, ("post", url, {"last_day": yesterday if delete_again else today.isoformat()})),
    )
    assert first.status_code == 204
    assert waiting.status_code == 400, waiting.data
    assert waiting.data == {"party": ["This role was removed in the meantime."]}
    assert AuditEvent.objects.filter(action_type="party_role.end", status="success").count() == 1


@pytest.mark.parametrize("change", ["demote", "deactivate", "revoke"])
def test_waiting_invitation_resend_rechecks_authority(manager_world, monkeypatch, change):
    zev, admin, actor, recipient = manager_world
    actor_grant = manager_grant(zev, actor)
    manager_grant(zev, make_user("remaining_manager"))
    recipient.is_active = False
    recipient.set_unusable_password()
    recipient.save(update_fields=["is_active", "password"])
    token = issue_invitation(recipient)
    grant = ZevAccessGrant.objects.create(zev=zev, user=recipient, role=ZevAccessRole.VIEWER)
    requester = actor if change == "revoke" else admin
    sent = []
    monkeypatch.setattr("zev.views_access.send_invitation", lambda *args: sent.append(True))

    def lose_authority():
        if change == "revoke":
            response = perform_request(admin, ("delete", f"/api/v1/zev/zevs/{zev.pk}/access/{actor_grant.pk}/", {}))
            assert response.status_code == 204
        else:
            changes = {"role": UserRole.USER} if change == "demote" else {"is_active": False}
            User.objects.filter(pk=admin.pk).update(**changes)

    _, waiting = contend(
        lambda: User.objects.locked().get(pk=recipient.pk),
        lambda: perform_request(requester, ("post", f"/api/v1/zev/zevs/{zev.pk}/access/{grant.pk}/resend-invitation/", {})),
        lose_authority,
    )
    assert waiting.status_code == 403, waiting.data
    token.refresh_from_db()
    assert token.consumed_at is None
    assert recipient.email_verification_tokens.count() == 1
    assert not sent
