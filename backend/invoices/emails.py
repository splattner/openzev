"""Outbound mail for the public invoice-access flow.

Kept out of ``zev.services`` because that module's mail is about *managing*
participants — an owner inviting someone. This is a participant asking for
their own way in, and the two should not share a template or a reason to
change.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage

from accounts.models import MAGIC_LINK_LIFETIME

logger = logging.getLogger(__name__)


def send_magic_link_email(participant, zev, link) -> None:
    """Send the sign-in link to the address on file.

    The recipient is always ``participant.email`` and never anything the
    requester supplied — that is the whole trust anchor of tier 2.

    Sent in the ZEV's ``invoice_language`` unless an operator has saved a
    custom template, which then applies to every language: ``EmailTemplate``
    holds one row per key, and this does not change that contract. So a
    customised sign-in mail opts out of translation, deliberately and visibly
    (the admin console tab says so).
    """
    from .models import (
        MAGIC_LINK_EMAIL_DEFAULTS_BY_LANGUAGE,
        EmailTemplate,
    )

    defaults = MAGIC_LINK_EMAIL_DEFAULTS_BY_LANGUAGE.get(
        zev.invoice_language or "de",
        MAGIC_LINK_EMAIL_DEFAULTS_BY_LANGUAGE["en"],
    )
    override = EmailTemplate.objects.filter(template_key="participant_magic_link").first()
    subject_tpl = override.subject if override else defaults["subject"]
    body_tpl = override.body if override else defaults["body"]

    context = {
        "participant_name": participant.full_name,
        "zev_name": zev.name,
        "link_url": f"{settings.FRONTEND_URL.rstrip('/')}/signin/{link.token}",
        "valid_minutes": int(MAGIC_LINK_LIFETIME.total_seconds() // 60),
    }

    def _render(template: str, fallback: str) -> str:
        """Fill ``template``, falling back to the shipped default on a bad edit.

        An operator editing the template can mistype or invent a placeholder.
        Sending the *raw* template would then deliver a mail whose body reads
        ``{link_url}`` — a sign-in email with no way to sign in, which is worse
        than one whose wording is not the operator's own. ``fallback`` is the
        shipped default, whose placeholders are exactly this context, so it
        always renders and always carries a working link.

        Same policy as the invitation mail (``zev.services``); ``ValueError``
        and ``IndexError`` cover malformed braces and positional fields, which
        ``str.format`` raises instead of ``KeyError``.
        """
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            logger.warning(
                "Magic-link template has an unusable placeholder; "
                "sending the default template instead."
            )
            return fallback.format(**context)

    EmailMessage(
        subject=_render(subject_tpl, defaults["subject"]),
        body=_render(body_tpl, defaults["body"]),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[participant.email],
    ).send(fail_silently=False)
