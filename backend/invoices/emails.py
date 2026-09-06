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
    """
    from .models import EMAIL_TEMPLATE_DEFAULTS, EmailTemplate

    defaults = EMAIL_TEMPLATE_DEFAULTS["participant_magic_link"]
    override = EmailTemplate.objects.filter(template_key="participant_magic_link").first()
    subject_tpl = override.subject if override else defaults["subject"]
    body_tpl = override.body if override else defaults["body"]

    context = {
        "participant_name": participant.full_name,
        "zev_name": zev.name,
        "link_url": f"{settings.FRONTEND_URL.rstrip('/')}/signin/{link.token}",
        "valid_minutes": int(MAGIC_LINK_LIFETIME.total_seconds() // 60),
    }

    def _render(template: str) -> str:
        try:
            return template.format(**context)
        except (KeyError, IndexError):
            # An operator editing the template can remove or mistype a
            # placeholder. A sign-in link that fails to send is worse than one
            # whose wording is odd, so the raw template goes out instead.
            logger.warning("Magic-link template has an unknown placeholder; sending raw.")
            return template

    EmailMessage(
        subject=_render(subject_tpl),
        body=_render(body_tpl),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[participant.email],
    ).send(fail_silently=False)
