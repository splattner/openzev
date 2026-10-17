from __future__ import annotations

import secrets
import string
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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
    """Self-service membership for report downloads.

    The account's current participant row — in ``zev_id`` when given, else the
    first by ordering. Ended rows and disabled ZEVs give no self-service
    access; an unusable ``zev_id`` finds nothing rather than raising.
    """
    from django.core.exceptions import ValidationError

    from .access import live_participant_q
    from .models import Participant

    rows = Participant.objects.filter(
        live_participant_q(), user=user, zev__disabled_at__isnull=True,
    ).select_related("zev")
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
    if not _same_address(user.email, participant.email):
        user.email = participant.email
    if not _shares_account(participant, user):
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


def account_for_email(email, *, lock=False):
    """The account whose address is ``email`` (case-insensitive); ``None`` for a blank or unused one."""
    email = (email or "").strip()
    if not email:
        return None
    accounts = User.objects.locked() if lock else User.objects.all()
    return accounts.filter(email__iexact=email).order_by("pk").first()


@transaction.atomic
def ensure_participant_account(participant):
    """The user account linked to ``participant``, creating one if needed.

    The participant's email identifies the account (``User.email`` is unique):
    an account that already holds the address is linked as it is, with its
    password, email and name untouched, instead of a second one being created.
    Several participant rows with one address therefore share one account.

    New participant-only accounts are passwordless. Synchronizing an existing
    account preserves its password and pending password-change requirement.
    Accounts with their own login keep their password, email and name.
    """
    user = User.objects.locked().get(pk=participant.user_id) if participant.user_id else None
    if user is not None:
        participant.user = user
        if requires_independent_login(user):
            return user

    holder = account_for_email(participant.email, lock=True)
    if holder is not None and (user is None or holder.pk != user.pk):
        return _link_participant(participant, holder)

    if (
        user is not None
        and (participant.email or "").strip()
        and not _same_address(participant.email, user.email)
        and _shares_account(participant, user)
    ):
        # The address moved on, but other rows still use this account: they keep
        # it, and this row gets an account of its own for the new address.
        user = None

    if user is not None:
        sync_participant_user_fields(participant, user)
        user.save(update_fields=['email', 'first_name', 'last_name'])
        return user

    username = build_unique_participant_username(
        first_name=participant.first_name,
        last_name=participant.last_name,
        email=participant.email,
    )
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                role=UserRole.USER,
                email=participant.email,
                first_name=participant.first_name,
                last_name=participant.last_name,
            )
    except IntegrityError:
        # A concurrent request created the account for this address first.
        holder = account_for_email(participant.email, lock=True)
        if holder is None:
            raise
        return _link_participant(participant, holder)
    return _link_participant(participant, user)


def _link_participant(participant, user):
    participant.user = user
    participant.save(update_fields=['user', 'updated_at'])
    return user


def _same_address(first, second) -> bool:
    return (first or "").strip().lower() == (second or "").strip().lower()


def _shares_account(participant, user) -> bool:
    return user.participations.exclude(pk=participant.pk).exists()


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
    if not user.is_active or requires_independent_login(user):
        raise LinkRefused()
    return user


def has_independent_login_credentials(user):
    """Return whether the account has an independent login credential."""
    return (
        (user.has_usable_password() and not user.password_from_participant_link)
        or user.social_accounts.filter(provider__enabled=True, from_participant_link=False).exists()
        or user.webauthn_credentials.filter(from_participant_link=False).exists()
    )


def is_pending_invitation(user) -> bool:
    return not user.is_active and user.email_verification_tokens.filter(
        purpose=EmailVerificationToken.Purpose.INVITATION, consumed_at__isnull=True,
    ).exists()


def validate_account_login(user, *, field="user") -> None:
    if not has_independent_login_credentials(user) and not is_pending_invitation(user):
        raise ValidationError({
            field: "Send an access invitation before assigning independent access.",
        })


def protect_account_login(user, *, credential_field="user"):
    """Require ownership, then retire participant credentials before promotion.

    Already-protected accounts are unchanged, including between invitation
    acceptance and password enrollment. Call inside a transaction.
    Bulk writes bypass the model guards that call this, so
    maintenance code must call it before adding access.
    """
    from accounts.models import ApiKey, MagicLinkToken, TotpDevice
    from accounts.session_revocation import revoke_sessions
    from .onboarding import revoke_active_for_user

    locked = User.objects.locked().get(pk=user.pk)
    if locked.independent_login_required:
        return locked
    validate_account_login(locked, field=credential_field)
    if locked.password_from_participant_link:
        locked.set_unusable_password()
        locked.password_from_participant_link = False
        locked.must_change_password = False
        locked.save(update_fields=["password", "password_from_participant_link", "must_change_password"])
    locked.webauthn_credentials.filter(from_participant_link=True).delete()
    locked.social_accounts.filter(from_participant_link=True).delete()
    locked.mfa_recovery_codes.filter(from_participant_link=True).delete()
    TotpDevice.objects.filter(user=locked, from_participant_link=True).delete()
    revoke_sessions(locked)
    ApiKey.objects.filter(user=locked, revoked_at__isnull=True).update(revoked_at=timezone.now())
    revoke_active_for_user(locked)
    MagicLinkToken.objects.filter(user=locked, consumed_at__isnull=True).update(consumed_at=timezone.now())
    if not is_pending_invitation(locked):
        locked.independent_login_required = True
        locked.save(update_fields=["independent_login_required"])
    return locked


def existing_owner_problem(user) -> str | None:
    """Why ``user`` cannot be made a ZEV's owner, or ``None`` when it can.

    An admin already sees every ZEV and cannot be linked to a participant. A
    deactivated account cannot sign in, and one without a login (or a pending
    invitation) would be promoted to a manager nobody can sign in as.
    """
    if user.is_admin:
        return "An admin account cannot be a ZEV owner. Choose another account."
    if not user.is_active and not is_pending_invitation(user):
        return "This account is deactivated."
    if not has_independent_login_credentials(user) and not is_pending_invitation(user):
        return "Send this account an access invitation before making it a ZEV owner."
    return None


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
    """Create a ZEV, its owner and metering points.

    ``owner_data['account']`` names an existing account to make the owner: it is
    linked as it is, so its password, email and name stay untouched and no
    temporary password is returned. Otherwise a new account is created.
    """
    from .models import MeteringPoint, MeteringPointAssignment, Participant, Zev
    from .access import grant_manager_until_role
    from .buildings import ensure_initial_building
    from .parties import ensure_initial_roles

    existing_account = owner_data.get('account')
    temporary_password = None
    if existing_account is not None:
        owner_user = User.objects.locked().get(pk=existing_account.pk)
        problem = existing_owner_problem(owner_user)
        if problem:
            raise ValidationError({'owner': problem})
        first_name = owner_data.get('first_name') or owner_user.first_name
        last_name = owner_data.get('last_name') or owner_user.last_name
        email = owner_user.email
    else:
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
            # None for an existing account: nothing was created or changed.
            'temporary_password': temporary_password,
            'existing_account': existing_account is not None,
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
