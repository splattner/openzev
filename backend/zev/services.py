from __future__ import annotations

import secrets
import string

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from accounts.models import UserRole

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


def own_participant_for_user(user):
    """Self-service membership shared by ``/auth/me`` and report downloads."""
    from .models import Participant

    return Participant.objects.filter(user=user).select_related("zev").first()


def sync_participant_user_fields(participant, user) -> None:
    # Owners and admins can also have participant records. Updating their
    # profile or sending an invitation must not remove management access.
    if user.role not in (UserRole.ZEV_OWNER, UserRole.ADMIN):
        user.role = UserRole.PARTICIPANT
    user.email = participant.email
    user.first_name = participant.first_name
    user.last_name = participant.last_name


@transaction.atomic
def ensure_participant_account(participant):
    """The user account linked to ``participant``, creating one if needed.

    Never mints a usable password for a **participant-role** account. A
    freshly created account gets ``set_unusable_password()``: nothing is
    transmitted, so there is nothing to rotate, and ``must_change_password``
    would strand the participant in a form asking them to change a password
    they were never given. An already-linked participant account carrying a
    password from before this behaviour existed is neutralized the same way
    the moment it is touched here — the same safety net
    ``accounts.magic_links.account_for_participant`` relied on before this
    became the one place that logic lives.

    Signing in happens only through an onboarding or magic-sign-in link (see
    ``zev.onboarding``, ``accounts.magic_links``), or a password the
    participant chooses themselves through ``set_initial_password`` once they
    are in.

    **Deliberately does not touch the password of an owner or admin account**
    that also happens to be linked as a participant (``sync_participant_user_fields``
    already carves this case out for role, for the same reason). That is their
    real login, used for everything else they manage — nuking it because one
    of their own participant rows was saved or invited would lock them out of
    their own instance.
    """
    if participant.user_id:
        user = participant.user
        sync_participant_user_fields(participant, user)
        update_fields = ['role', 'email', 'first_name', 'last_name']
        if user.role == UserRole.PARTICIPANT:
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
        role=UserRole.PARTICIPANT,
        email=participant.email,
        first_name=participant.first_name,
        last_name=participant.last_name,
    )
    participant.user = user
    participant.save(update_fields=['user', 'updated_at'])
    return user


@transaction.atomic
def send_participant_onboarding_link(participant, invited_by) -> str:
    """Ensure an account and onboarding link exist, and email the link.

    Returns the URL, so the caller can also show or copy it — useful as a
    fallback if the mail never arrives. Raises ``ValueError`` when the
    participant has no address to send to, same guard the flow it replaced
    used.
    """
    from . import onboarding
    from .emails import send_onboarding_email

    if not participant.email:
        raise ValueError("Participant email is required to send an onboarding link.")

    ensure_participant_account(participant)
    token = onboarding.get_or_create_for_participant(participant)
    link_url = onboarding.public_url(token)

    inviter_name = invited_by.get_full_name() or invited_by.username
    send_onboarding_email(participant, inviter_name, link_url)
    return link_url


@transaction.atomic
def get_participant_onboarding_link(participant) -> str:
    """Ensure an account and onboarding link exist, without emailing it.

    Used by the "copy onboarding link" action: an operator handing the link
    over in person or by some channel other than email, and by the admin
    console's account-linking action, which historically did not require an
    email address either.
    """
    from . import onboarding

    ensure_participant_account(participant)
    token = onboarding.get_or_create_for_participant(participant)
    return onboarding.public_url(token)


@transaction.atomic
def create_zev_with_owner_setup(*, zev_data: dict, owner_data: dict, metering_points_data: list[dict]) -> dict:
    from .models import MeteringPoint, MeteringPointAssignment, Participant, Zev

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
        role=UserRole.ZEV_OWNER,
        email=email,
        first_name=first_name,
        last_name=last_name,
        must_change_password=True,
    )

    zev = Zev.objects.create(owner=owner_user, **zev_data)
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

    from .tasks import trigger_geocode_if_address_present
    trigger_geocode_if_address_present(owner_participant)

    created_metering_points: list[dict] = []
    for metering_point_data in metering_points_data:
        metering_point = MeteringPoint.objects.create(
            zev=zev,
            meter_id=metering_point_data['meter_id'],
            meter_type=metering_point_data['meter_type'],
            is_active=metering_point_data.get('is_active', True),
            location_description=metering_point_data.get('location_description', ''),
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
def create_zev_for_existing_owner(*, owner_user, zev_data: dict) -> dict:
    """Create a ZEV + owner Participant for an already-authenticated self-registered user."""
    from .models import Participant, Zev

    zev = Zev.objects.create(owner=owner_user, **zev_data)
    owner_participant = Participant.objects.create(
        zev=zev,
        user=owner_user,
        first_name=owner_user.first_name,
        last_name=owner_user.last_name,
        email=owner_user.email,
        valid_from=zev.start_date,
    )
    return {
        'zev': {'id': str(zev.id), 'name': zev.name},
        'owner_participant_id': str(owner_participant.id),
    }
