from __future__ import annotations

import secrets
import string
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import EmailVerificationToken, UserRole

if TYPE_CHECKING:
    from .models import ParticipantOnboardingToken

User = get_user_model()

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_temporary_password(length: int = 12) -> str:
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def build_unique_participant_username(*, first_name: str, last_name: str, email: str | None = None) -> str:
    return build_unique_username(first_name=first_name, last_name=last_name, email=email, fallback='participant')


def build_unique_username(*, first_name: str, last_name: str, email: str | None = None, fallback: str = 'user') -> str:
    candidates: list[str] = []

    if email and '@' in email:
        email_local = slugify(email.split('@', 1)[0]).replace('-', '.')
        if email_local:
            candidates.append(email_local)

    full_name = slugify(f'{first_name}.{last_name}').replace('-', '.')
    if full_name:
        candidates.append(full_name)

    first_only = slugify(first_name).replace('-', '.')
    if first_only:
        candidates.append(first_only)

    base = next((candidate for candidate in candidates if candidate), fallback)
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f'{base}{suffix}'
    return username


def own_participant_for_user(user, zev_id=None):
    """Self-service membership shared by ``/auth/me`` and report downloads.

    The account's current participant row — in ``zev_id`` when given, else the
    first by ordering. An ended row is not a membership any more (#761); an
    unusable ``zev_id`` finds nothing rather than raising.
    """
    from django.core.exceptions import ValidationError

    from .access import live_participant_q
    from .models import Participant

    rows = Participant.objects.filter(live_participant_q(), user=user).select_related("zev")
    if zev_id:
        try:
            rows = rows.filter(zev_id=zev_id)
            return rows.first()
        except (ValidationError, ValueError):
            return None
    return rows.first()


def sync_participant_user_fields(participant, user) -> None:
    # The role is left alone: what an account may do comes from its grants and
    # participant rows, not from the role (#761).
    user.email = participant.email
    user.first_name = participant.first_name
    user.last_name = participant.last_name


def requires_independent_login(user) -> bool:
    """Whether participant links must never authenticate this account."""
    from .access import holds_managing_role_ever
    from .models import ZevAccessGrant

    return (
        user.independent_login_required
        or user.is_admin
        or user.may_create_zev
        or ZevAccessGrant.objects.filter(user=user).exists()
        or holds_managing_role_ever(user)
    )


@transaction.atomic
def ensure_participant_account(participant):
    """The user account linked to ``participant``, creating one if needed.

    Participant-only accounts get unusable passwords and no password-change
    requirement: nothing was transmitted, so ``must_change_password`` would
    strand them on a form asking to change a password they were never given.
    Existing passwords are cleared here; participants can set their own
    password after signing in through a link.
    Accounts with their own login keep their password, email and name.
    """
    if participant.user_id:
        user = User.objects.locked().get(pk=participant.user_id)
        participant.user = user
        if requires_independent_login(user):
            return user
        sync_participant_user_fields(participant, user)
        update_fields = ['email', 'first_name', 'last_name']
        if user.has_usable_password():
            user.set_unusable_password()
            update_fields.append('password')
        if user.must_change_password:
            user.must_change_password = False
            update_fields.append('must_change_password')
        user.save(update_fields=update_fields)
        return user

    username = build_unique_participant_username(
        first_name=participant.first_name,
        last_name=participant.last_name,
        email=participant.email,
    )
    user = User.objects.create_user(
        username=username,
        role=UserRole.USER,
        email=participant.email,
        first_name=participant.first_name,
        last_name=participant.last_name,
    )
    participant.user = user
    participant.save(update_fields=['user', 'updated_at'])
    return user


class LinkRefused(Exception):
    def __init__(self, message="This account must use its existing login.", *, code="own_login_required"):
        self.code = code
        super().__init__(message)


def lock_participant_account(participant, *, for_save=False, update_fields=None):
    """Lock old/new parties, old/new users, then the participant; return its previous links.

    Lookups reload both related objects. Saves reload links outside update_fields
    and preserve unchanged cached objects. Uses the shared party/user/participant order.
    """
    from .models import Participant, Party

    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("lock_participant_account requires an outer transaction")
    rows = Participant.objects.order_by().filter(pk=participant.pk).values("user_id", "party_id")
    previous = rows.first()
    if previous is None and (not for_save or not participant._state.adding):
        raise Participant.DoesNotExist("This participant no longer exists.")
    party_id, user_id = participant.party_id, participant.user_id
    if previous is not None and (not for_save or update_fields is not None):
        fields = set(update_fields or ())
        if not for_save or not {"party", "party_id"}.intersection(fields):
            party_id = previous["party_id"]
        if not for_save or not {"user", "user_id"}.intersection(fields):
            user_id = previous["user_id"]
    party_id, user_id = Party._meta.pk.to_python(party_id), User._meta.pk.to_python(user_id)
    parties = {p.pk: p for p in Party.objects.select_for_update().filter(
        pk__in={party_id, (previous or {}).get("party_id")} - {None},
    ).order_by("pk")}
    users = {u.pk: u for u in User.objects.locked().filter(
        pk__in={user_id, (previous or {}).get("user_id")} - {None},
    ).order_by("pk")}
    locked = rows.select_for_update().first()
    if locked is None and previous is not None:
        raise Participant.DoesNotExist("This participant no longer exists.")
    if locked != previous:
        raise ValidationError("This participant changed during locking. Please try again.", code="participant_changed")
    if party_id is not None and party_id not in parties:
        raise ValidationError({"party": "This party no longer exists."})
    if user_id is not None and user_id not in users:
        raise ValidationError({"user": "This account no longer exists."})
    if not for_save or participant.party_id != party_id:
        participant.party = parties.get(party_id)
    if not for_save or participant.user_id != user_id:
        participant.user = users.get(user_id)
    return previous


@transaction.atomic
def link_account_for(participant):
    """Return the participant account only when a link may authenticate it."""
    from .models import MANAGING_ROLES

    lock_participant_account(participant)
    if not participant.user_id and participant.party.roles.filter(role__in=MANAGING_ROLES).exists():
        raise LinkRefused(
            "Give this party an access invitation before creating a participant login.",
            code="login_setup_required",
        )
    user = ensure_participant_account(participant)
    if requires_independent_login(user):
        raise LinkRefused()
    return user


def has_login_credentials(user):
    return (
        user.has_usable_password()
        or user.social_accounts.filter(provider__enabled=True).exists()
        or user.webauthn_credentials.exists()
    )


def is_pending_invitation(user) -> bool:
    return not user.is_active and user.email_verification_tokens.filter(
        purpose=EmailVerificationToken.Purpose.INVITATION, consumed_at__isnull=True,
    ).exists()


def validate_account_login(user, *, field="user") -> None:
    if not has_login_credentials(user) and not is_pending_invitation(user):
        raise ValidationError({
            field: "Send an access invitation before assigning independent access.",
        })


def protect_account_login(user, *, credential_field="user"):
    """Require a login, then retire sessions, API keys and participant tokens before promotion.

    An already protected account was promoted before and passes unchanged, even
    between accepting its invitation and choosing a password. Call inside a
    transaction. Bulk writes bypass the model guards that call this, so
    maintenance code must call it before adding access.
    """
    from accounts.models import ApiKey, MagicLinkToken
    from accounts.session_revocation import revoke_sessions
    from .onboarding import revoke_active_for_user

    locked = User.objects.locked().get(pk=user.pk)
    if locked.independent_login_required:
        return locked
    validate_account_login(locked, field=credential_field)
    revoke_sessions(locked)
    ApiKey.objects.filter(user=locked, revoked_at__isnull=True).update(revoked_at=timezone.now())
    revoke_active_for_user(locked)
    MagicLinkToken.objects.filter(user=locked, consumed_at__isnull=True).update(consumed_at=timezone.now())
    if not is_pending_invitation(locked):
        locked.independent_login_required = True
        locked.save(update_fields=["independent_login_required"])
    return locked


def send_participant_onboarding_link(participant, invited_by) -> tuple[str, ParticipantOnboardingToken]:
    """Email an onboarding link; raises ValueError without email or LinkRefused for protected accounts."""
    from . import onboarding
    from .emails import send_onboarding_email

    if not participant.email:
        raise ValueError("Participant email is required to send an onboarding link.")

    with transaction.atomic():
        link_account_for(participant)
        token = onboarding.get_or_create_for_participant(participant)
        link_url = onboarding.public_url(token)

    inviter_name = invited_by.get_full_name() or invited_by.username
    send_onboarding_email(participant, inviter_name, link_url, token.expires_at)
    return link_url, token


@transaction.atomic
def get_participant_onboarding_link(participant) -> tuple[str, ParticipantOnboardingToken]:
    """Return a link and its token without emailing; raise LinkRefused for ineligible accounts.

    Needs no email address: the operator hands the link over in person or by
    another channel, as does the admin console's account-linking action.
    """
    from . import onboarding

    link_account_for(participant)
    token = onboarding.get_or_create_for_participant(participant)
    return onboarding.public_url(token), token


@transaction.atomic
def create_zev_with_owner_setup(*, zev_data: dict, owner_data: dict, metering_points_data: list[dict]) -> dict:
    from .models import MeteringPoint, MeteringPointAssignment, Participant, Zev
    from .access import grant_manager_until_role
    from .buildings import ensure_initial_building
    from .parties import ensure_initial_roles

    first_name = owner_data['first_name']
    last_name = owner_data['last_name']
    email = owner_data['email']
    username = (owner_data.get('username') or '').strip()
    if not username:
        username = build_unique_username(first_name=first_name, last_name=last_name, email=email, fallback='owner')

    temporary_password = generate_temporary_password()
    owner_user = User.objects.create_user(
        username=username,
        password=temporary_password,
        role=UserRole.USER,
        email=email,
        first_name=first_name,
        last_name=last_name,
        must_change_password=True,
    )

    zev = Zev.objects.create(**zev_data)
    owner_participant = Participant.objects.create(
        zev=zev,
        user=owner_user,
        title=owner_data.get('title', ''),
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=owner_data.get('phone', ''),
        address_line1=owner_data.get('address_line1', ''),
        address_line2=owner_data.get('address_line2', ''),
        postal_code=owner_data.get('postal_code', ''),
        city=owner_data.get('city', ''),
        valid_from=zev.start_date,
    )
    ensure_initial_roles(zev, owner_participant.party, zev.start_date)
    building = ensure_initial_building(zev)
    # The issuer role is the creator's access; a grant only bridges a later start.
    grant_manager_until_role(zev, owner_user, zev.start_date)

    created_metering_points: list[dict] = []
    for metering_point_data in metering_points_data:
        metering_point = MeteringPoint.objects.create(
            zev=zev,
            meter_id=metering_point_data['meter_id'],
            meter_type=metering_point_data['meter_type'],
            is_active=metering_point_data.get('is_active', True),
            location_description=metering_point_data.get('location_description', ''),
            building=building,
        )
        MeteringPointAssignment.objects.create(
            metering_point=metering_point,
            participant=owner_participant,
            valid_from=zev.start_date,
        )
        created_metering_points.append(
            {
                'id': str(metering_point.id),
                'meter_id': metering_point.meter_id,
            }
        )

    return {
        'zev': {
            'id': str(zev.id),
            'name': zev.name,
        },
        'owner': {
            'id': owner_user.id,
            'username': owner_user.username,
            'temporary_password': temporary_password,
        },
        'owner_participant_id': str(owner_participant.id),
        'metering_points': created_metering_points,
    }


@transaction.atomic
def create_zev_for_existing_owner(*, owner_user, zev_data: dict, participant_data: dict | None = None) -> dict:
    """Create a ZEV and its owner participant for a self-registered user.

    The caller's party is its issuer and a landowner from its start date, and
    manages it through that role — no grant, unless the ZEV starts later.
    """
    from .models import Participant, Zev
    from .access import grant_manager_until_role
    from .buildings import ensure_initial_building
    from .parties import ensure_initial_roles

    zev = Zev.objects.create(**zev_data)
    owner_participant = Participant.objects.create(
        zev=zev,
        user=owner_user,
        first_name=owner_user.first_name,
        last_name=owner_user.last_name,
        email=owner_user.email,
        **(participant_data or {}),
        valid_from=zev.start_date,
    )
    ensure_initial_roles(zev, owner_participant.party, zev.start_date)
    ensure_initial_building(zev)
    # The issuer role is the creator's access; a grant only bridges a later start.
    grant_manager_until_role(zev, owner_user, zev.start_date)
    return {
        'zev': {'id': str(zev.id), 'name': zev.name},
        'owner_participant_id': str(owner_participant.id),
    }


@transaction.atomic
def issue_invitation(user) -> EmailVerificationToken:
    """A fresh invitation link; earlier unused ones stop working."""
    user = User.objects.locked().get(pk=user.pk)
    if user.is_active:
        raise ValidationError({"user": "This account has already accepted its invitation."})
    user.email_verification_tokens.filter(
        purpose=EmailVerificationToken.Purpose.INVITATION, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    return EmailVerificationToken.objects.create(
        user=user, token=secrets.token_urlsafe(48), purpose=EmailVerificationToken.Purpose.INVITATION
    )
