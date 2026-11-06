"""Where a participant finds their documents (SPEC-2026-11-participant-document-inbox §5.4)."""

from django.conf import settings

INBOX_PATH = "/me/documents"


def inbox_url(participant) -> str:
    """The *My documents* page, for a participant with a login; empty for one without.

    The list rather than one entry: an invoice email is rendered before the
    invoice is delivered, so there is no row to point at yet.
    """
    if participant is None or participant.user_id is None:
        return ""
    return f"{settings.FRONTEND_URL.rstrip('/')}{INBOX_PATH}"
