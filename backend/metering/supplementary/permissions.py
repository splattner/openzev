"""Who may do what with a supplementary source (SPEC §3).

* The **owner** of a source is the participant who connected it. Only they (and an
  admin) hold or change the credential, test and sync it, and import files.
* A **manager** of the ZEV sees the status and may switch a source off, disconnect
  it, purge its readings or delete it. A manager never creates a source and never
  reads or sets a credential: the account belongs to the participant.
* A **viewer** only reads.

"Holds the metering point personally today" is judged on the Swiss civil date
(ADR 0026). Community-mode holders cannot connect a source: their readings are
split by weight, so no single household is described.
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import FeatureFlag
from allocation.validity import active_on
from zev import access
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, Participant

# Capabilities, ordered by how much they let a caller do to someone else's data.
OWNER_ONLY = frozenset({"partial_update_all", "test", "sync", "rotate_push_token", "import_csv"})
OWNER_OR_MANAGER = frozenset({"partial_update_enabled", "destroy", "disconnect", "purge"})

ACTION_CAPABILITY = {
    "test": "test",
    "sync": "sync",
    "rotate_push_token": "rotate_push_token",
    "import_csv": "import_csv",
    "destroy": "destroy",
    "disconnect": "disconnect",
    "purge": "purge",
}


def feature_enabled() -> bool:
    return FeatureFlag.is_enabled(FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED)


def require_feature() -> None:
    """The feature answers ``404`` while its flag is off, as if the endpoints did not exist."""
    if not feature_enabled():
        raise Http404


def holder_participant(user, metering_point: MeteringPoint, on=None) -> Participant | None:
    """The participant behind ``user`` who personally holds ``metering_point`` on ``on`` (today), if any."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    assignment = (
        active_on(
            MeteringPointAssignment.objects.filter(
                metering_point=metering_point,
                participant__user=user,
                allocation_mode=AllocationMode.PERSONAL,
            ),
            on or timezone.localdate(),
        )
        .select_related("participant")
        .first()
    )
    return assignment.participant if assignment else None


def is_owner(user, source) -> bool:
    return user.is_authenticated and source.participant.user_id == user.pk


def can_create_for(user, metering_point: MeteringPoint) -> Participant | None:
    """The participant a new source would belong to when ``user`` creates it, or ``None``.

    Admins act on behalf of a participant and name one themselves, so they are
    not resolved here.
    """
    return holder_participant(user, metering_point)


def role_for(user, source) -> str:
    """``admin``, ``owner``, ``manager``, ``viewer`` or ``none`` for ``user`` on ``source``."""
    if user.is_admin:
        return "admin"
    if is_owner(user, source):
        return "owner"
    zev = source.metering_point.zev
    if access.can_manage(user, zev):
        return "manager"
    if access.can_view(user, zev):
        return "viewer"
    return "none"


def allowed(role: str, capability: str) -> bool:
    if role == "admin":
        return True
    if capability in OWNER_ONLY:
        return role == "owner"
    if capability in OWNER_OR_MANAGER:
        return role in ("owner", "manager")
    return False


class SupplementarySourcePermission(BasePermission):
    """Authenticated callers only; the per-action rules are object-level."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        role = role_for(request.user, obj)
        action = getattr(view, "action", None)
        if action == "partial_update":
            # A manager may only switch a source on or off; the view narrows the fields.
            capability = "partial_update_all" if role != "manager" else "partial_update_enabled"
            if role == "manager":
                return True
            return allowed(role, capability)
        return allowed(role, ACTION_CAPABILITY.get(action, "partial_update_all"))
