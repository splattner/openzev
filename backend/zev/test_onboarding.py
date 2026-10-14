"""Tests for the participant-onboarding-link flow.

Covers what zev/tests.py's participant CRUD tests do not: the token service
itself, the unauthenticated consume endpoint, and revocation. See
docs/specs and issue #712 for the design this implements.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from audit.models import AuditEvent, AuditEventSource, AuditEventStatus
from testing.helpers import authenticate as auth, make_user, create_managed_zev

from . import onboarding
from invoices.models import EmailTemplate

from .emails import format_expiry_date
from .models import Participant, ParticipantOnboardingToken, Party
from .services import get_participant_onboarding_link, send_participant_onboarding_link


class OnboardingTokenServiceTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_svc", UserRole.USER)
        self.zev = create_managed_zev(
            name="Onboarding ZEV", owner=owner, zev_type="vzev", invoice_prefix="O",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Ada", last_name="Onboardee",
            email="ada@example.com", valid_from=date(2026, 1, 1),
        )

    def test_get_or_create_returns_the_same_token_on_repeat_calls(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ParticipantOnboardingToken.objects.count(), 1)

    def test_resolve_rejects_wrong_secret(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        self.assertIsNone(onboarding.resolve(token.prefix, "wrong-secret"))
        self.assertIsNotNone(onboarding.resolve(token.prefix, token.secret))

    def test_resolve_rejects_a_revoked_token(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        onboarding.revoke(token)

        self.assertIsNone(onboarding.resolve(token.prefix, token.secret))

    def test_resolve_rejects_a_disabled_zev(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self.zev.disabled_at = timezone.now()
        self.zev.save()

        self.assertIsNone(onboarding.resolve(token.prefix, token.secret))

    def test_revoked_token_is_not_reused_by_get_or_create(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        onboarding.revoke(first)

        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertNotEqual(first.pk, second.pk)
        self.assertTrue(second.is_active)

    def test_public_url_carries_prefix_and_secret(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        url = onboarding.public_url(token)

        self.assertIn(f"/join/{token.prefix}", url)
        self.assertIn(token.secret, url)


class SendOnboardingLinkServiceTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_send", UserRole.USER)
        self.zev = create_managed_zev(
            name="Send ZEV", owner=owner, zev_type="vzev", invoice_prefix="S",
        )
        self.owner = owner

    def test_raises_without_an_email_on_file(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="No", last_name="Email",
            valid_from=date(2026, 1, 1),
        )

        with self.assertRaises(ValueError):
            send_participant_onboarding_link(participant, self.owner)

    def test_sends_a_working_link_and_records_no_password(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Bea", last_name="Recipient",
            email="bea@example.com", valid_from=date(2026, 1, 1),
        )

        url, token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["bea@example.com"])
        self.assertIn(url, mail.outbox[0].body)
        self.assertIn(format_expiry_date(token.expires_at), mail.outbox[0].body)
        participant.refresh_from_db()
        self.assertFalse(participant.user.has_usable_password())

    def test_custom_template_uses_every_send_time_field(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="All", last_name="Fields",
            email="all.fields@example.com", valid_from=date(2026, 1, 1),
        )
        EmailTemplate.objects.create(
            template_key="participant_onboarding",
            subject="{participant_name}|{inviter_name}|{zev_name}|{link_url}|{expiry_date}",
            body="{participant_name}|{inviter_name}|{zev_name}|{link_url}|{expiry_date}",
        )

        url, token = send_participant_onboarding_link(participant, self.owner)

        expected = "|".join(
            [
                participant.full_name,
                self.owner.username,
                self.zev.name,
                url,
                format_expiry_date(token.expires_at),
            ]
        )
        self.assertEqual(mail.outbox[-1].subject, expected)
        self.assertEqual(mail.outbox[-1].body, expected)

    def test_resending_reuses_the_same_link(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Cai", last_name="Repeat",
            email="cai@example.com", valid_from=date(2026, 1, 1),
        )

        first_url, _first = send_participant_onboarding_link(participant, self.owner)
        second_url, second_token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_resend_states_the_actual_expiry_not_30_days(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Dag", last_name="Aged",
            email="dag@example.com", valid_from=date(2026, 1, 1),
        )
        first_url, first_token = send_participant_onboarding_link(participant, self.owner)
        ParticipantOnboardingToken.objects.filter(pk=first_token.pk).update(
            expires_at=timezone.now() + timedelta(days=1)
        )
        mail.outbox = []

        second_url, second_token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(format_expiry_date(second_token.expires_at), mail.outbox[0].body)

    def test_get_link_never_sends_mail(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Dee", last_name="Silent",
            valid_from=date(2026, 1, 1),
        )

        url, _token = get_participant_onboarding_link(participant)

        self.assertTrue(url)
        self.assertEqual(len(mail.outbox), 0)


class OnboardingConsumeViewTests(TestCase):
    CONSUME_URL = "/api/v1/public/onboarding/consume/"

    def setUp(self):
        owner = make_user("owner_onboarding_consume", UserRole.USER)
        self.zev = create_managed_zev(
            name="Consume ZEV", owner=owner, zev_type="vzev", invoice_prefix="C",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Eve", last_name="Consumer",
            email="eve@example.com", valid_from=date(2026, 1, 1),
        )
        self.token = onboarding.get_or_create_for_participant(self.participant)
        self.client = APIClient()

    def test_valid_link_signs_in_and_creates_the_account_lazily(self):
        self.assertIsNone(self.participant.user_id)

        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["zev_name"], self.zev.name)
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user)
        self.assertFalse(self.participant.user.has_usable_password())
        self.assertIn("openzev_access", resp.cookies)

    def test_link_is_reusable_unlike_a_magic_link(self):
        first = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )
        second = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_wrong_secret_is_a_404(self):
        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": "not-it"}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_revoked_link_is_a_404(self):
        onboarding.revoke(self.token)

        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_disabled_zev_link_is_a_404(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save()

        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_records_an_audit_event_with_the_onboarding_link_source(self):
        self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        event = AuditEvent.objects.filter(action_type="participant_onboarding.consumed").latest("created_at")
        self.assertEqual(event.source, AuditEventSource.ONBOARDING_LINK)

    def test_stamps_last_login(self):
        self.client.post(self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json")

        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user.last_login)


class OwnLoginLinkTests(TestCase):
    """Participant links cannot sign in accounts with independent access."""

    CONSUME_URL = "/api/v1/public/onboarding/consume/"

    def setUp(self):
        self.manager = make_user("own_login_manager", UserRole.USER)
        self.zev = create_managed_zev(
            name="Tenant ZEV", owner=self.manager, zev_type="vzev", invoice_prefix="T",
        )
        # Manages a ZEV of its own and is a participant in this one.
        self.landlord = make_user("own_login_landlord", UserRole.USER)
        create_managed_zev(
            name="Landlord ZEV", owner=self.landlord, zev_type="vzev", invoice_prefix="L",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, user=self.landlord, first_name="Lena", last_name="Landlord",
            email=self.landlord.email, valid_from=date(2026, 1, 1),
        )
        self.client = APIClient()
        auth(self.client, self.manager)

    def test_copying_a_link_is_refused(self):
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/onboarding-link/")

        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data["code"], "own_login_required")
        self.assertFalse(self.participant.onboarding_tokens.exists())

    def test_sending_a_link_is_refused(self):
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/send-onboarding-link/")

        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.participant.onboarding_tokens.exists())

    def test_a_refusal_is_audited_as_denied(self):
        self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/onboarding-link/")

        event = AuditEvent.objects.get(action_type="participant.onboarding_link_created")
        self.assertEqual(event.status, AuditEventStatus.DENIED)

    def test_a_link_from_before_the_account_had_its_own_login_stops_signing_in(self):
        tenant = Participant.objects.create(
            zev=self.zev, first_name="Tim", last_name="Tenant",
            email="tim@example.com", valid_from=date(2026, 1, 1),
        )
        _url, token = get_participant_onboarding_link(tenant)
        tenant.refresh_from_db()
        tenant.user.set_password("IndependentPassword42!")
        tenant.user.save(update_fields=["password"])
        create_managed_zev(name="Tim's ZEV", owner=tenant.user, zev_type="vzev", invoice_prefix="M")

        resp = APIClient().post(
            self.CONSUME_URL, {"prefix": token.prefix, "s": token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("openzev_access", resp.cookies)

    def test_a_participant_only_account_still_signs_in(self):
        tenant = Participant.objects.create(
            zev=self.zev, first_name="Tim", last_name="Tenant",
            email="tim@example.com", valid_from=date(2026, 1, 1),
        )

        resp = self.client.post(f"/api/v1/zev/participants/{tenant.pk}/onboarding-link/")

        self.assertEqual(resp.status_code, 200, resp.content)
        token = tenant.onboarding_tokens.get()
        signed_in = APIClient().post(
            self.CONSUME_URL, {"prefix": token.prefix, "s": token.secret}, format="json",
        )
        self.assertEqual(signed_in.status_code, 200)
        self.assertIn("openzev_access", signed_in.cookies)

    def test_access_gained_during_account_setup_refuses_sign_in(self):
        from .services import ensure_participant_account

        tenant = Participant.objects.create(
            zev=self.zev, first_name="Tim", last_name="Tenant", email="tim.race@example.com",
            valid_from=date(2026, 1, 1),
        )
        _url, token = get_participant_onboarding_link(tenant)

        def promoted_account(participant):
            account = ensure_participant_account(participant)
            account.set_password("IndependentPassword42!")
            account.save(update_fields=["password"])
            create_managed_zev(name="New Access", owner=account, zev_type="vzev", invoice_prefix="R")
            return account

        with patch("zev.services.ensure_participant_account", side_effect=promoted_account):
            response = APIClient().post(
                self.CONSUME_URL, {"prefix": token.prefix, "s": token.secret}, format="json",
            )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("openzev_access", response.cookies)


class LinkPromotionLockTests(TransactionTestCase):
    def setUp(self):
        self._bound_lock_waits()
        if connections["default"].vendor == "postgresql":
            self.addCleanup(self._reset_lock_waits)

    def _bound_lock_waits(self):
        if connections["default"].vendor == "postgresql":
            with connections["default"].cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '15s'")

    def _reset_lock_waits(self):
        with connections["default"].cursor() as cursor:
            cursor.execute("RESET lock_timeout")
            cursor.execute("RESET statement_timeout")

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_user_save_during_party_move_is_refused(self):
        self._move_during_link(lambda row: row.save(update_fields=["user_id"]))

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_lookup_during_party_move_is_refused(self):
        from .services import link_account_for

        self._move_during_link(link_account_for)

    def _move_during_link(self, operation):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from django.core.exceptions import ValidationError

        from . import access
        from .models import PartyRole
        from .parties import assign_role

        zev = create_managed_zev(name="Concurrent party move")
        managing = Party.objects.create(zev=zev, last_name="Representative")
        assign_role(zev, managing, PartyRole.REPRESENTATIVE, timezone.localdate())
        participant = Participant.objects.create(
            zev=zev, last_name="Moving", email="moving@example.com", valid_from=timezone.localdate(),
        )
        account = User.objects.create_user(username="moving")
        linking, release = Event(), Event()
        original_lock = Party.objects.select_for_update

        def paused_lock(*args, **kwargs):
            # Commit the move after the snapshot, before the first party lock.
            if not linking.is_set():
                linking.set()
                if not release.wait(5):
                    raise TimeoutError("Paused link was not released")
            return original_lock(*args, **kwargs)

        def link():
            try:
                self._bound_lock_waits()
                row = Participant.objects.get(pk=participant.pk)
                row.user = account
                return operation(row)
            finally:
                connections.close_all()

        with patch("zev.models.Party.objects.select_for_update", side_effect=paused_lock), ThreadPoolExecutor(1) as pool:
            linked = pool.submit(link)
            try:
                self.assertTrue(linking.wait(5))
                participant.party = managing
                participant.save(update_fields=["party_id"])
            finally:
                release.set()
            with self.assertRaises(ValidationError):
                linked.result(timeout=10)
        participant.refresh_from_db()
        self.assertEqual(participant.party_id, managing.pk)
        self.assertIsNone(participant.user_id)
        self.assertFalse(access.can_manage(account, zev))

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_lookup_during_account_relink_is_refused(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from django.core.exceptions import ValidationError

        zev = create_managed_zev(name="Concurrent account relink")
        participant = Participant.objects.create(
            zev=zev, last_name="Relinking", email="relinking@example.com", valid_from=timezone.localdate(),
        )
        replacement = make_user("replacement_relink")
        password = replacement.password
        linking, release = Event(), Event()
        original_lock = Party.objects.select_for_update

        def paused_lock(*args, **kwargs):
            if not linking.is_set():
                linking.set()
                if not release.wait(5):
                    raise TimeoutError("Paused lookup was not released")
            return original_lock(*args, **kwargs)

        def lookup():
            try:
                self._bound_lock_waits()
                return get_participant_onboarding_link(Participant.objects.get(pk=participant.pk))
            finally:
                connections.close_all()

        with patch("zev.models.Party.objects.select_for_update", side_effect=paused_lock), ThreadPoolExecutor(1) as pool:
            linked = pool.submit(lookup)
            try:
                self.assertTrue(linking.wait(5))
                participant.user = replacement
                participant.save(update_fields=["user"])
            finally:
                release.set()
            with self.assertRaises(ValidationError):
                linked.result(timeout=10)
        participant.refresh_from_db()
        replacement.refresh_from_db()
        self.assertEqual(participant.user_id, replacement.pk)
        self.assertEqual(replacement.password, password)
        self.assertFalse(participant.onboarding_tokens.exists())

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_resolved_token_cannot_sign_in_after_unlink(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        zev = create_managed_zev(name="Concurrent unlink")
        participant = Participant.objects.create(
            zev=zev, last_name="Unlinking", email="unlinking@example.com", valid_from=timezone.localdate(),
        )
        _url, token = get_participant_onboarding_link(participant)
        account_count = User.objects.count()
        admin = make_user("unlink_lock_admin", UserRole.ADMIN)
        client = APIClient()
        auth(client, admin)
        resolved, release = Event(), Event()
        original_resolve = onboarding.resolve

        def paused_resolve(*args):
            result = original_resolve(*args)
            resolved.set()
            if not release.wait(5):
                raise TimeoutError("Resolved token was not released")
            return result

        def consume():
            try:
                self._bound_lock_waits()
                return APIClient().post(
                    "/api/v1/public/onboarding/consume/",
                    {"prefix": token.prefix, "s": token.secret}, format="json",
                )
            finally:
                connections.close_all()

        with patch("zev.onboarding.resolve", side_effect=paused_resolve), ThreadPoolExecutor(1) as pool:
            signed_in = pool.submit(consume)
            try:
                self.assertTrue(resolved.wait(5))
                response = client.post(f"/api/v1/zev/participants/{participant.pk}/unlink-account/")
                self.assertEqual(response.status_code, 200, response.content)
            finally:
                release.set()
            response = signed_in.result(timeout=10)
        self.assertEqual(response.status_code, 404, response.content)
        self.assertEqual(response.data, {"detail": "This link is not valid."})
        self.assertNotIn("openzev_access", response.cookies)
        participant.refresh_from_db()
        token.refresh_from_db()
        self.assertIsNone(participant.user_id)
        self.assertIsNotNone(token.revoked_at)
        self.assertEqual(User.objects.count(), account_count + 1)

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_edit_and_copy_of_the_same_participant_complete_without_deadlock(self):
        from concurrent.futures import ThreadPoolExecutor
        from decimal import Decimal
        from threading import Event

        from .serializers import ParticipantSerializer
        from .services import ensure_participant_account

        zev = create_managed_zev(name="Concurrent edit")
        participant = Participant.objects.create(
            zev=zev, last_name="Concurrent", email="concurrent@example.com", valid_from=timezone.localdate(),
        )
        ensure_participant_account(participant)
        copying, editing, release = Event(), Event(), Event()
        original_get = onboarding.get_or_create_for_participant

        def paused_get(row):
            copying.set()
            if not release.wait(5):
                raise TimeoutError("Copy was not released")
            return original_get(row)

        def copy():
            try:
                self._bound_lock_waits()
                return get_participant_onboarding_link(Participant.objects.get(pk=participant.pk))
            finally:
                connections.close_all()

        def edit():
            try:
                self._bound_lock_waits()
                row = Participant.objects.get(pk=participant.pk)
                editing.set()
                return ParticipantSerializer().update(row, {"allocation_weight": Decimal("2")})
            finally:
                connections.close_all()

        with (
            patch("zev.onboarding.get_or_create_for_participant", side_effect=paused_get),
            ThreadPoolExecutor(2) as pool,
        ):
            copied = pool.submit(copy)
            try:
                self.assertTrue(copying.wait(5))
                # Taking the party first prevents an edit from holding it while waiting for this user.
                with self.assertRaises(DatabaseError), transaction.atomic():
                    Party.objects.select_for_update(nowait=True).get(pk=participant.party_id)
                with self.assertRaises(DatabaseError), transaction.atomic():
                    Participant.objects.order_by().values("user_id").select_for_update(nowait=True).get(pk=participant.pk)
                edited = pool.submit(edit)
                self.assertTrue(editing.wait(5))
            finally:
                release.set()
            self.assertEqual(copied.result(timeout=10)[1].participant_id, participant.pk)
            self.assertEqual(edited.result(timeout=10).pk, participant.pk)
        participant.refresh_from_db()
        self.assertEqual(participant.allocation_weight, Decimal("2"))

    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_sign_in_holds_the_user_lock_and_promotion_retires_its_session(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from accounts.jwt_utils import make_jwt_for_user

        zev = create_managed_zev(name="Lock ZEV", zev_type="vzev", invoice_prefix="K")
        participant = Participant.objects.create(
            zev=zev, first_name="Tim", last_name="Lock", email="tim.lock@example.com",
            valid_from=date(2026, 1, 1),
        )
        _url, token = get_participant_onboarding_link(participant)
        minting, release = Event(), Event()

        def paused_mint(user, **kwargs):
            minting.set()
            if not release.wait(5):
                raise TimeoutError("Session mint was not released")
            return make_jwt_for_user(user, **kwargs)

        def consume():
            try:
                self._bound_lock_waits()
                return APIClient().post(
                    "/api/v1/public/onboarding/consume/",
                    {"prefix": token.prefix, "s": token.secret}, format="json",
                )
            finally:
                connections.close_all()

        with patch("zev.views_public.make_jwt_for_user", side_effect=paused_mint), ThreadPoolExecutor(1) as pool:
            signed_in = pool.submit(consume)
            try:
                self.assertTrue(minting.wait(5))
                with self.assertRaises(DatabaseError), transaction.atomic():
                    User.objects.select_for_update(nowait=True).get(pk=participant.user_id)
                with self.assertRaises(DatabaseError), transaction.atomic():
                    ParticipantOnboardingToken.objects.select_for_update(nowait=True).get(pk=token.pk)
            finally:
                release.set()
            response = signed_in.result(timeout=5)

        self.assertEqual(response.status_code, 200)
        client = APIClient()
        client.cookies = response.cookies
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)
        participant.user.set_password("IndependentPassword42!")
        participant.user.save(update_fields=["password"])
        create_managed_zev(name="Independent Access", owner=participant.user, zev_type="vzev", invoice_prefix="X")
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)


class RevokeAndUnlinkTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin_revoke", UserRole.ADMIN)
        owner = make_user("owner_revoke", UserRole.USER)
        self.zev = create_managed_zev(
            name="Revoke ZEV", owner=owner, zev_type="vzev", invoice_prefix="R",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Fay", last_name="Revoked",
            email="fay@example.com", valid_from=date(2026, 1, 1),
        )
        self.client = APIClient()
        auth(self.client, self.admin)

    def test_unlink_conflict_leaves_account_and_token_unchanged(self):
        from django.core.exceptions import ValidationError

        _url, token = get_participant_onboarding_link(self.participant)
        account_id = self.participant.user_id
        with patch("zev.services.lock_participant_account", side_effect=ValidationError("Changed")):
            response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/unlink-account/")
        self.assertEqual(response.status_code, 400, response.content)
        self.participant.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(self.participant.user_id, account_id)
        self.assertIsNone(token.revoked_at)
        self.assertFalse(AuditEvent.objects.filter(action_type="participant.unlink_account").exists())

    def test_revocation_failure_rolls_back_unlink(self):
        _url, token = get_participant_onboarding_link(self.participant)
        account_id = self.participant.user_id
        with patch("zev.onboarding.revoke_active_for_participant", side_effect=RuntimeError("Revocation failed")):
            with self.assertRaisesRegex(RuntimeError, "Revocation failed"):
                self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/unlink-account/")
        self.participant.refresh_from_db()
        token.refresh_from_db()
        self.assertEqual(self.participant.user_id, account_id)
        self.assertIsNone(token.revoked_at)
        self.assertFalse(AuditEvent.objects.filter(action_type="participant.unlink_account").exists())

    def test_revoke_action_kills_the_link_but_keeps_the_account(self):
        get_participant_onboarding_link(self.participant)
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user_id)

        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/revoke-onboarding-link/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["onboarding_status"], "revoked")
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user_id)

    def test_unlink_account_also_revokes_the_active_link(self):
        self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.participant.refresh_from_db()
        self.assertTrue(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/unlink-account/")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

    def test_onboarding_status_transitions(self):
        list_url = f"/api/v1/zev/participants/{self.participant.id}/"

        self.assertEqual(self.client.get(list_url).data["onboarding_status"], "not_sent")

        link_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.assertEqual(link_resp.data["participant"]["onboarding_status"], "sent")

        token = self.participant.onboarding_tokens.get()
        onboarding.note_use(token)
        self.assertEqual(self.client.get(list_url).data["onboarding_status"], "active")

        revoke_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/revoke-onboarding-link/")
        self.assertEqual(revoke_resp.data["onboarding_status"], "revoked")


class OnboardingExpiryTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_expiry", UserRole.USER)
        self.zev = create_managed_zev(
            name="Expiry ZEV", owner=owner, zev_type="vzev", invoice_prefix="E",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Exp", last_name="Ired",
            email="exp@example.com", valid_from=date(2026, 1, 1),
        )
        self.client = APIClient()

    def _expire(self, token):
        ParticipantOnboardingToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        token.refresh_from_db()
        return token

    def _mint_link(self, username):
        admin = make_user(username, UserRole.ADMIN)
        auth(self.client, admin)
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_new_token_carries_a_30_day_expiry(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        delta = token.expires_at - timezone.now()
        self.assertTrue(timedelta(days=29) < delta <= timedelta(days=30))
        self.assertTrue(token.is_active)

    def test_creating_a_token_without_expiry_fails(self):
        with self.assertRaises(IntegrityError):
            ParticipantOnboardingToken.objects.create(
                participant=self.participant, prefix="no-expiry", secret="s" * 32,
            )

    def test_resolve_rejects_an_expired_token(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self._expire(token)

        self.assertIsNone(onboarding.resolve(token.prefix, token.secret))
        self.assertFalse(
            ParticipantOnboardingToken.objects.get(pk=token.pk).is_active
        )

    def test_expired_link_is_a_404(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self._expire(token)

        resp = self.client.post(
            "/api/v1/public/onboarding/consume/",
            {"prefix": token.prefix, "s": token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_expired_active_token_is_revoked_and_replaced(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)

        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertTrue(second.is_active)
        self.assertNotEqual(first.prefix, second.prefix)

    def test_expired_link_reads_as_expired_with_its_date(self):
        self._mint_link("admin_expiry_status")
        token = self.participant.onboarding_tokens.get()
        self._expire(token)

        data = self.client.get(f"/api/v1/zev/participants/{self.participant.id}/").data

        self.assertEqual(data["onboarding_status"], "expired")
        self.assertEqual(data["onboarding_link_expires_at"], token.expires_at)

    def test_copy_rotates_an_expired_link(self):
        self._mint_link("admin_expiry_copy")
        first_token = self.participant.onboarding_tokens.order_by("-created_at").first()
        first_prefix = first_token.prefix
        self._expire(first_token)

        second_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")

        self.assertEqual(second_resp.status_code, 200)
        self.assertIsNotNone(second_resp.data["onboarding_expires_at"])
        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertTrue(live.is_active)
        self.assertNotEqual(live.prefix, first_prefix)

    def test_copy_response_url_and_expiry_belong_to_the_same_token(self):
        resp = self._mint_link("admin_expiry_match_copy")

        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertIn(f"/join/{live.prefix}", resp.data["onboarding_url"])
        self.assertEqual(resp.data["onboarding_expires_at"], resp.data["participant"]["onboarding_link_expires_at"])
        self.assertEqual(resp.data["onboarding_expires_at"], live.expires_at)

    def test_send_response_url_and_expiry_belong_to_the_same_token(self):
        admin = make_user("admin_expiry_match_send", UserRole.ADMIN)
        auth(self.client, admin)
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/send-onboarding-link/")

        self.assertEqual(resp.status_code, 200)
        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertIn(f"/join/{live.prefix}", resp.data["onboarding_url"])
        self.assertEqual(resp.data["onboarding_expires_at"], live.expires_at)

    def test_setting_a_password_revokes_the_link(self):
        from .services import ensure_participant_account

        user = ensure_participant_account(self.participant)
        onboarding.get_or_create_for_participant(self.participant)
        self.assertTrue(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )
        auth(self.client, user)

        resp = self.client.post(
            "/api/v1/auth/me/set-initial-password/",
            {"new_password": "A-very-long-initial-1!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )
        event = AuditEvent.objects.get(action_type="password.set_initial")
        self.assertEqual(event.metadata_json["onboarding_links_revoked"], 1)

    def test_changing_a_password_revokes_the_link(self):
        user = make_user("pw_change_participant", UserRole.USER)
        participant = Participant.objects.create(
            zev=self.zev, user=user, first_name="Pam", last_name="Word",
            email="pam@example.com", valid_from=date(2026, 1, 1),
        )
        onboarding.get_or_create_for_participant(participant)
        auth(self.client, user)

        resp = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"old_password": "pass1234", "new_password": "A-very-long-changed-2!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

    def test_only_one_unrevoked_link_per_participant(self):
        from django.db import transaction

        onboarding.get_or_create_for_participant(self.participant)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ParticipantOnboardingToken.objects.create(
                    participant=self.participant, prefix="second-live",
                    secret="s" * 32,
                    expires_at=timezone.now() + timedelta(days=30),
                )


    def test_racing_mint_returns_the_winners_link(self):
        from contextlib import nullcontext
        from unittest import mock

        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)
        real_create = ParticipantOnboardingToken.objects.create

        def racy_create(**kwargs):
            # A concurrent copy/send mints and commits first, so our insert
            # hits the one-unrevoked-link constraint.
            real_create(
                participant=self.participant, prefix="racer-winner",
                secret="r" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )
            raise IntegrityError("one_unrevoked_onboarding_token_per_participant")

        # No savepoint: on a real second connection the winner's commit
        # survives our rollback; in this single test connection it must stay
        # visible for the fallback fetch.
        with (
            mock.patch.object(
                ParticipantOnboardingToken.objects, "create", racy_create
            ),
            mock.patch("zev.onboarding.transaction.atomic", nullcontext),
        ):
            result = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(result.prefix, "racer-winner")
        self.assertTrue(result.is_active)
        self.assertEqual(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).count(),
            1,
        )

    def test_failed_mint_is_retried_not_stranded(self):
        from unittest import mock

        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)
        real_create = ParticipantOnboardingToken.objects.create
        calls = {"n": 0}

        def flaky_create(**kwargs):
            # First mint attempt fails with nobody else holding a live link.
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("one_unrevoked_onboarding_token_per_participant")
            return real_create(**kwargs)

        # Real savepoint (not mocked): the failed mint must roll the revoke back.
        with mock.patch.object(
            ParticipantOnboardingToken.objects, "create", flaky_create
        ):
            result = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(calls["n"], 2)
        self.assertTrue(result.is_active)
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertEqual(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).count(),
            1,
        )


class OnboardingConstraintUpgradeTests(TransactionTestCase):
    """Migration 0029 cleans up before constraining.

    Rows minted by the old race-prone implementation can hold several
    unrevoked links per participant; the migration revokes all but the
    newest before adding the partial unique constraint.
    """

    def test_upgrade_revokes_older_duplicates_then_constrains(self):
        from django.core.management import call_command
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        def migrate(target):
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            # Latest first: a plan mixing directions across apps is refused.
            executor.migrate(executor.loader.graph.leaf_nodes())
            executor.loader.build_graph()
            executor.migrate([target])
            return executor.loader.project_state([target]).apps

        # The rows are written with the models as they were at 0028, not
        # today's (a participant had its own name columns then).
        owner = make_user("owner_mig_0029", UserRole.USER)
        old_apps = migrate(("zev", "0028_onboarding_token_expires_at"))
        try:
            OldZev = old_apps.get_model("zev", "Zev")
            OldParticipant = old_apps.get_model("zev", "Participant")
            OldToken = old_apps.get_model("zev", "ParticipantOnboardingToken")
            zev = OldZev.objects.create(name="Mig ZEV", owner_id=owner.pk, zev_type="vzev", invoice_prefix="M")
            participant = OldParticipant.objects.create(
                zev=zev, first_name="Mig", last_name="Rate",
                email="mig@example.com", valid_from=date(2026, 1, 1),
            )
            old = OldToken.objects.create(
                participant=participant, prefix="mig-old", secret="o" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )
            OldToken.objects.filter(pk=old.pk).update(
                created_at=timezone.now() - timedelta(days=1)
            )
            new = OldToken.objects.create(
                participant=participant, prefix="mig-new", secret="n" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )

            call_command("migrate", "zev", verbosity=0, interactive=False)

            live = list(
                ParticipantOnboardingToken.objects.filter(participant_id=participant.pk, revoked_at__isnull=True)
            )
            self.assertEqual([t.pk for t in live], [new.pk])
            self.assertIsNotNone(ParticipantOnboardingToken.objects.get(pk=old.pk).revoked_at)
            # The upgrade carried the participant's name onto its party.
            self.assertEqual(Participant.objects.get(pk=participant.pk).full_name, "Mig Rate")
        finally:
            call_command("migrate", verbosity=0, interactive=False)

        # Following tests need the live invoice schema, too.
        from testing.factories import InvoiceFactory
        InvoiceFactory()
