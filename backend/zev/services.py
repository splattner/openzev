from __future__ import annotations

import secrets
import string

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
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


def sync_participant_user_fields(participant, user) -> None:
    user.role = UserRole.PARTICIPANT
    user.email = participant.email
    user.first_name = participant.first_name
    user.last_name = participant.last_name


@transaction.atomic
def ensure_participant_account(participant):
    if participant.user_id:
        user = participant.user
        sync_participant_user_fields(participant, user)
        user.save(
            update_fields=[
                'role',
                'email',
                'first_name',
                'last_name',
            ]
        )
        return user, None

    password = generate_temporary_password()
    username = build_unique_participant_username(
        first_name=participant.first_name,
        last_name=participant.last_name,
        email=participant.email,
    )
    user = User.objects.create_user(
        username=username,
        password=password,
        role=UserRole.PARTICIPANT,
        email=participant.email,
        first_name=participant.first_name,
        last_name=participant.last_name,
        must_change_password=True,
    )
    participant.user = user
    participant.save(update_fields=['user', 'updated_at'])
    return user, password


@transaction.atomic
def send_participant_invitation(participant, invited_by) -> tuple[str, str]:
    user, _ = ensure_participant_account(participant)
    recipient = participant.email or user.email
    if not recipient:
        raise ValueError("Participant email is required to send an invitation.")

    temporary_password = generate_temporary_password()
    user.set_password(temporary_password)
    user.must_change_password = True
    user.save(update_fields=['password', 'must_change_password'])

    from invoices.models import EmailTemplate, EMAIL_TEMPLATE_DEFAULTS

    defaults = EMAIL_TEMPLATE_DEFAULTS["participant_invitation"]
    override = EmailTemplate.objects.filter(template_key="participant_invitation").first()
    subject_tpl = override.subject if override else defaults["subject"]
    body_tpl = override.body if override else defaults["body"]

    inviter_name = invited_by.get_full_name() or invited_by.username
    template_ctx = {
        "participant_name": participant.full_name,
        "inviter_name": inviter_name,
        "zev_name": participant.zev.name,
        "username": user.username,
        "temporary_password": temporary_password,
    }

    try:
        subject = subject_tpl.format_map(template_ctx)
        body = body_tpl.format_map(template_ctx)
    except (KeyError, ValueError):
        subject = defaults["subject"].format_map(template_ctx)
        body = defaults["body"].format_map(template_ctx)

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    email.send(fail_silently=False)
    return user.username, temporary_password


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
