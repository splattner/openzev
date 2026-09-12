"""Outbound mail for onboarding a participant.

Kept out of ``invoices.emails``, which is where the magic-link mail lives: that
one is a participant asking for their own way in from an invoice they already
hold, and this is an operator adding someone who has nothing yet. Different
trigger, different reason to change.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def send_onboarding_email(participant, inviter_name: str, link_url: str) -> None:
    """Email the onboarding link to the address on the participant's record.

    Not localized by the ZEV's ``invoice_language`` — this mail predates any
    invoice, so there is no document whose language it needs to match. An
    operator who wants it in a specific language edits the template, same as
    the invitation mail it replaces did.
    """
    from invoices.models import EMAIL_TEMPLATE_DEFAULTS, EmailTemplate

    defaults = EMAIL_TEMPLATE_DEFAULTS["participant_onboarding"]
    override = EmailTemplate.objects.filter(template_key="participant_onboarding").first()
    subject_tpl = override.subject if override else defaults["subject"]
    body_tpl = override.body if override else defaults["body"]

    context = {
        "participant_name": participant.full_name,
        "inviter_name": inviter_name,
        "zev_name": participant.zev.name,
        "link_url": link_url,
    }

    def _render(template: str, fallback: str) -> str:
        """Fill ``template``, falling back to the shipped default on a bad edit.

        Same policy as ``invoices.emails.send_magic_link_email``: a mistyped
        placeholder must not produce a mail whose body reads ``{link_url}`` —
        an onboarding email with no way to onboard is worse than one whose
        wording is not the operator's own.
        """
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            logger.warning(
                "Onboarding template has an unusable placeholder; "
                "sending the default template instead."
            )
            return fallback.format(**context)

    EmailMessage(
        subject=_render(subject_tpl, defaults["subject"]),
        body=_render(body_tpl, defaults["body"]),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[participant.email],
    ).send(fail_silently=False)
