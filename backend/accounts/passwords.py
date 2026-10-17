"""Set an independent password and revoke sessions and sign-in links."""

from django.db import transaction

from zev.onboarding import revoke_active_for_user

from .magic_links import revoke_for_user
from .models import User
from .session_revocation import revoke_sessions


@transaction.atomic
def recover_password(user: User, password: str | None) -> User:
    user = User.objects.locked().get(pk=user.pk)
    user.set_password(password)
    user.password_from_participant_link = False
    user.must_change_password = False
    user.save(update_fields=["password", "password_from_participant_link", "must_change_password"])
    revoke_sessions(user)
    revoke_active_for_user(user)
    revoke_for_user(user)
    return user
