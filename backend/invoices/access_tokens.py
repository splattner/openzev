"""Minting and resolving the bearer token printed on an invoice.

The security argument for serving an invoice without a login is in
``docs/specs/2026-09-participant-invoice-access.md`` §9, and it rests entirely
on the token resolving to **one invoice**. Everything here is written to keep
that true: there is no lookup that returns a participant, a ZEV, or a set.

The secret is stored in clear rather than hashed. The reasoning is on
``InvoiceAccessToken.secret``; the short version is that hashing would defend
nothing (the token and the invoice it protects live in the same database) and
would cost the property the whole feature depends on — that a regenerated PDF
carries the same QR as the copy already in the post.
"""
import hmac
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import InvoiceAccessToken

PREFIX_BYTES = 8
SECRET_BYTES = 32

# A reader refreshing the page should not write a row per refresh, and the
# audit log should not fill with one person reading their bill.
USE_RECORD_INTERVAL = timedelta(hours=1)


def generate() -> tuple[str, str]:
    """Return ``(prefix, secret)``."""
    return secrets.token_hex(PREFIX_BYTES), secrets.token_urlsafe(SECRET_BYTES)


def get_or_create_for_invoice(invoice) -> InvoiceAccessToken:
    """The active token for ``invoice``, minting one if there is none.

    Get-or-create rather than create, because the printed QR must survive a
    re-render: an invoice regenerated after a template change has to carry the
    link that is already in someone's folder. Minting per render would kill
    every link ever printed, silently and in bulk.

    Revoking is therefore the only way a printed link stops working, which is
    the intended design and not a limitation.
    """
    existing = invoice.access_tokens.filter(revoked_at__isnull=True).first()
    if existing is not None:
        return existing

    prefix, secret = generate()
    return InvoiceAccessToken.objects.create(
        invoice=invoice, prefix=prefix, secret=secret,
    )


def public_url(token: InvoiceAccessToken) -> str:
    """The URL printed as a QR on the invoice.

    Built from ``FRONTEND_URL`` because it is a page a person opens, not an
    endpoint a script calls — the SPA route resolves the token through the API
    itself.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/i/{token.prefix}?s={quote(token.secret, safe='')}"


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
    # Constant time: the comparison is against a stored secret either way, and
    # a timing signal would leak it a byte at a time.
    if not hmac.compare_digest(token.secret, secret):
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


def qr_svg(token: InvoiceAccessToken) -> str:
    """An inline SVG QR for :func:`public_url`, sized for the insights page.

    Inline rather than a data: URI so it scales crisply in print and carries no
    raster weight, matching how the QR-Rechnung reaches the same document.
    """
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(
        public_url(token),
        image_factory=qrcode.image.svg.SvgPathImage,
        # M tolerates ~15% damage, which is what a folded and posted invoice
        # actually suffers. H would cost density for a link that is reprinted
        # rather than irreplaceable.
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")
