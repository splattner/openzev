"""Shared context builders keep editable email fields aligned with send paths."""

from __future__ import annotations


def build_invoice_email_context(
    *,
    invoice_number: object,
    zev_name: object,
    participant_name: object,
    period_start: object,
    period_end: object,
    due_date: object,
    total_chf: object,
) -> dict[str, object]:
    """Return the variables available to the invoice-email subject and body."""
    return {
        "invoice_number": invoice_number,
        "zev_name": zev_name,
        "participant_name": participant_name,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
        "total_chf": total_chf,
    }


def build_onboarding_email_context(
    *,
    participant_name: object,
    inviter_name: object,
    zev_name: object,
    link_url: object,
    expiry_date: object,
) -> dict[str, object]:
    """Return the variables available to the onboarding email."""
    return {
        "participant_name": participant_name,
        "inviter_name": inviter_name,
        "zev_name": zev_name,
        "link_url": link_url,
        "expiry_date": expiry_date,
    }


def build_verification_email_context(*, verify_url: object) -> dict[str, object]:
    """Return the variables available to the account-verification email."""
    return {"verify_url": verify_url}


def build_magic_link_email_context(
    *,
    participant_name: object,
    zev_name: object,
    link_url: object,
    valid_minutes: object,
) -> dict[str, object]:
    """Return the variables available to the participant magic-link email."""
    return {
        "participant_name": participant_name,
        "zev_name": zev_name,
        "link_url": link_url,
        "valid_minutes": valid_minutes,
    }
