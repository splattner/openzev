"""Who may read the live view, and the throttles of the live endpoints (SPEC-2026-live-energy-data §3)."""

from __future__ import annotations

import uuid

from django.http import Http404
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import ApiKey
from zev import access
from zev.models import Zev

from ..models import SupplementarySource
from ..supplementary.permissions import live_feature_enabled


def require_live_feature() -> None:
    """The live view answers ``404`` while its flag is not effective, as if it did not exist."""
    if not live_feature_enabled():
        raise Http404


class LiveFeatureMixin:
    """Checked before authentication, so a switched-off instance reveals nothing."""

    def initial(self, request, *args, **kwargs):
        require_live_feature()
        super().initial(request, *args, **kwargs)


def readable_zev(user, zev_id) -> Zev:
    """The ZEV, if ``user`` may see its live view; ``Http404`` otherwise (existence is not revealed).

    Managers, viewers and admins always may. Anybody else must be a *current* participant: a former
    participant has no claim on today's figures. A disabled ZEV is invisible to everyone but admins.
    """
    try:
        zev = Zev.objects.filter(pk=uuid.UUID(str(zev_id))).first()
    except ValueError:
        zev = None
    if zev is None or (zev.disabled_at is not None and not user.is_admin):
        raise Http404
    if access.can_view(user, zev) or zev.pk in access.participant_zev_ids(user):
        return zev
    raise Http404


class LiveEnergyPermission(BasePermission):
    """Authenticated, and allowed to see the ZEV named in the URL. The view narrows the payload by role."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        view.zev = readable_zev(request.user, view.kwargs["zev_id"])
        return True


class LivePushThrottle(SimpleRateThrottle):
    """Per push token, on top of the 5-second floor, so one noisy device cannot spend another's budget."""

    scope = "live_push"

    def get_cache_key(self, request, view):
        source = request.auth
        if not isinstance(source, SupplementarySource):
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(source.pk)}


class LiveReadThrottle(SimpleRateThrottle):
    """Per personal API key, or per user for a browser session, so a sensor and the UI do not share a budget."""

    scope = "live_read"

    def get_cache_key(self, request, view):
        key = request.auth
        ident = f"key:{key.pk}" if isinstance(key, ApiKey) else f"user:{request.user.pk}"
        return self.cache_format % {"scope": self.scope, "ident": ident}
