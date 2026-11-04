"""What an account may see of its notifications, decided when it reads them.

A notification never reveals more than the account may see now
(SPEC-2026-11-notification-center §3): a manager notice needs a current
managing role on the ZEV, a participant notice a current participation of the
recipient, and neither is shown for a disabled ZEV. Rows are kept, so a
restored access shows them again.
"""

from django.db.models import Q

from zev import access

from .models import Notification, NotificationAudience


def visible_to(user):
    """The notifications ``user`` may see now, newest first."""
    if user is None or not getattr(user, "is_authenticated", False):
        return Notification.objects.none()
    as_manager = Q(audience=NotificationAudience.MANAGER, zev_id__in=access.managed_zev_ids(user))
    as_participant = Q(
        audience=NotificationAudience.PARTICIPANT, participant__user=user
    ) & access.live_participant_q("participant__")
    return Notification.objects.filter(recipient=user, zev__disabled_at__isnull=True).filter(
        as_manager | as_participant
    )
