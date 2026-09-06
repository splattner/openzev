"""Minting and resolving the bearer token printed on an invoice.

The security argument for serving an invoice without a login is in
``docs/specs/2026-09-participant-invoice-access.md`` §9, and it rests entirely
on the token resolving to **one invoice**. Everything here is written to keep
that true: there is no lookup that returns a participant, a ZEV, or a set.

Hashing reuses ``accounts.api_keys`` rather than repeating the reasoning for a
single SHA-256 pass over a high-entropy secret — that module's docstring is the
argument, and having two copies of it invites one of them to be "improved".
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.api_keys import hash_secret, verify_secret

from .models import InvoiceAccessToken

PREFIX_BYTES = 8
SECRET_BYTES = 32

# A reader refreshing the page should not write a row per refresh, and the
# audit log should not fill with one person reading their bill.
USE_RECORD_INTERVAL = timedelta(hours=1)


def generate() -> tuple[str, str, str]:
    """Return ``(prefix, secret, hashed_secret)``.

    ``secret`` is the only time it exists in plain text: it goes into the
    printed URL and is never stored.
    """
    secret = secrets.token_urlsafe(SECRET_BYTES)
    return secrets.token_hex(PREFIX_BYTES), secret, hash_secret(secret)


def get_or_create_for_invoice(invoice) -> tuple[InvoiceAccessToken, str | None]:
    """Return ``(token, secret)`` for ``invoice``, minting one if needed.

    ``secret`` is ``None`` when an existing token is returned — it was shown
    once at creation and is not recoverable, exactly like an API key.

    **The token is stable across PDF regeneration**, which is the whole reason
    this is get-or-create rather than create. A regenerated invoice must carry
    the same QR as the copy already in the post; minting a fresh token on every
    render would silently kill every link ever printed.

    Consequently the secret cannot be recovered for an existing token, so the
    URL must be built at mint time and stored in the rendered PDF. Revoking is
    the only way to force a new one.
    """
    existing = invoice.access_tokens.filter(revoked_at__isnull=True).first()
    if existing is not None:
        return existing, None

    prefix, secret, hashed = generate()
    token = InvoiceAccessToken.objects.create(
        invoice=invoice, prefix=prefix, hashed_secret=hashed,
    )
    return token, secret


def resolve(prefix: str, secret: str) -> InvoiceAccessToken | None:
    """The active token for ``prefix`` whose secret matches, else ``None``.

    Returns ``None`` for every failure — unknown prefix, revoked token, wrong
    secret, and a ZEV that has not opted in. The caller turns all of them into
    the same 404: distinguishing "no such invoice" from "wrong secret" tells a
    scanner which prefixes exist.
    """
    if not prefix or not secret:
        return None

    token = (
        InvoiceAccessToken.objects
        .select_related("invoice__zev", "invoice__participant")
        .filter(prefix=prefix, revoked_at__isnull=True)
        .first()
    )
    if token is None:
        return None
    if not verify_secret(secret, token.hashed_secret):
        return None
    if not token.invoice.zev.participant_invoice_access:
        return None
    return token


def note_use(token: InvoiceAccessToken) -> bool:
    """Stamp ``last_used_at``, at most once per :data:`USE_RECORD_INTERVAL`.

    Returns whether the stamp was written, which is also the caller's signal to
    record an audit event — so the log gets one entry per reading session
    rather than one per refresh, without a second rule that could drift from
    this one.
    """
    now = timezone.now()
    if token.last_used_at is not None and now - token.last_used_at < USE_RECORD_INTERVAL:
        return False

    with transaction.atomic():
        updated = (
            InvoiceAccessToken.objects
            .filter(pk=token.pk)
            .filter(last_used_at=token.last_used_at)
            .update(last_used_at=now)
        )
    if updated:
        token.last_used_at = now
    # A concurrent request winning the race means the use was recorded by that
    # request; this one must not record it a second time.
    return bool(updated)


def revoke(token: InvoiceAccessToken) -> None:
    """Kill a printed link. The next render mints a fresh one."""
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
