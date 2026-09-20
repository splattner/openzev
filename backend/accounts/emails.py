"""Fixed system emails about an account's own security.

Deliberately *not* entries in ``EMAIL_TEMPLATE_DEFAULTS``: those are meant to be
customised per installation, and a security notice an admin can reword is one
that can be made to stop saying what happened.
"""

from django.conf import settings
from django.core.mail import EmailMessage


def mask_address(email: str) -> str:
    """``jane@example.com`` → ``j***@example.com``: enough to recognise, not
    enough to hand the new address to whoever reads the old mailbox."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def send_email_change_confirmation(new_email: str, confirm_url: str) -> None:
    EmailMessage(
        subject="Confirm your new OpenZEV email address",
        body=(
            "Hello,\n\n"
            "Someone asked to use this address for an OpenZEV account.\n"
            "To confirm the change, open the link below:\n\n"
            f"{confirm_url}\n\n"
            "This link is valid for 24 hours. Once you confirm, you will be signed "
            "out everywhere and can sign in again with this address.\n\n"
            "If you did not ask for this, ignore this email — nothing will change.\n\n"
            "Best regards,\nOpenZEV"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[new_email],
    ).send(fail_silently=False)


def send_email_change_notice(old_email: str, new_email: str) -> None:
    """Tell the *previous* address, which is what makes a hijack visible."""
    EmailMessage(
        subject="Your OpenZEV email address was changed",
        body=(
            "Hello,\n\n"
            f"The email address of your OpenZEV account was changed to {mask_address(new_email)}. "
            "You have been signed out everywhere.\n\n"
            "If this was you, no action is needed. If it was not, contact your "
            "administrator right away.\n\n"
            "Best regards,\nOpenZEV"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[old_email],
    ).send(fail_silently=True)
