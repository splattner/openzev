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
    user.phone = participant.phone
    user.address_line1 = participant.address_line1
    user.address_line2 = participant.address_line2
    user.postal_code = participant.postal_code
    user.city = participant.city


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
                'phone',
                'address_line1',
                'address_line2',
                'postal_code',
                'city',
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
        phone=participant.phone,
        address_line1=participant.address_line1,
        address_line2=participant.address_line2,
        postal_code=participant.postal_code,
        city=participant.city,
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

    subject = f'Invitation to OpenZEV for {participant.zev.name}'
    inviter_name = invited_by.get_full_name() or invited_by.username
    body = (
        f'Hello {participant.full_name},\n\n'
        f'{inviter_name} invited you to access your OpenZEV participant account for {participant.zev.name}.\n\n'
        f'Login username: {user.username}\n'
        f'Temporary password: {temporary_password}\n\n'
        f'Please sign in and change your password after your first login.\n\n'
        f'Best regards,\n'
        f'OpenZEV'
    )

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
        phone=owner_data.get('phone', ''),
        address_line1=owner_data.get('address_line1', ''),
        address_line2=owner_data.get('address_line2', ''),
        postal_code=owner_data.get('postal_code', ''),
        city=owner_data.get('city', ''),
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
            participant=owner_participant,
            meter_id=metering_point_data['meter_id'],
            meter_type=metering_point_data['meter_type'],
            is_active=metering_point_data.get('is_active', True),
            valid_from=metering_point_data.get('valid_from') or zev.start_date,
            valid_to=metering_point_data.get('valid_to'),
            location_description=metering_point_data.get('location_description', ''),
        )
        MeteringPointAssignment.objects.create(
            metering_point=metering_point,
            participant=owner_participant,
            valid_from=metering_point.valid_from,
            valid_to=metering_point.valid_to,
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
