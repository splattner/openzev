"""Unauthenticated onboarding, reached from the link emailed to a participant.

Companion to ``invoices.views_public``, which serves the equivalent flow for a
participant who already has an invoice. See ``zev.onboarding`` for why this
token is a reusable bearer link rather than a one-shot magic link.
"""
import logging

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.cookies import set_auth_cookies
from accounts.jwt_utils import make_jwt_for_user
from accounts.throttling import OnboardingLinkThrottle
from audit.models import AuditActionCategory, AuditEventSource, AuditEventStatus
from audit.services import record_audit_event

from . import onboarding
from .services import ensure_participant_account

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([OnboardingLinkThrottle])
def onboarding_consume(request):
    """Sign in as the participant this link was sent to.

    One step rather than invoice access's two: the credential is the token
    itself, emailed to the address already on file, so there is nothing left
    to prove by first asking for a second link the way tier 2 does. Reusable
    and not consumed — see ``ParticipantOnboardingToken`` for why.
    """
    prefix = (request.data or {}).get("prefix", "")
    secret = (request.data or {}).get("s", "")
    token = onboarding.resolve(prefix, secret)
    if token is None:
        return Response({"detail": "This link is not valid."}, status=status.HTTP_404_NOT_FOUND)

    participant = token.participant
    user = ensure_participant_account(participant)

    request.audit_source = AuditEventSource.ONBOARDING_LINK
    underlying = getattr(request, "_request", None)
    if underlying is not None:
        underlying.audit_source = AuditEventSource.ONBOARDING_LINK

    if onboarding.note_use(token):
        record_audit_event(
            action_type="participant_onboarding.consumed",
            action_category=AuditActionCategory.AUTH,
            status=AuditEventStatus.SUCCESS,
            source=AuditEventSource.ONBOARDING_LINK,
            request=request,
            zev=participant.zev,
            user=user,
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.username,
            summary=f"Signed in with an onboarding link: {user.username}.",
            metadata={"token_prefix": token.prefix},
        )

    tokens = make_jwt_for_user(user)
    response = Response({
        "detail": "Signed in.",
        "zev_name": participant.zev.name,
        "participant_name": participant.full_name,
    })
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
    return response
