"""Second-factor challenge issuing/resolution, shared across every login door.

Kept separate from ``models.py`` and ``views.py`` for the same reason
``mfa_crypto.py`` and ``api_keys.py`` are: one place for a security-sensitive
mechanism used by several call sites, rather than duplicated per view.

See ``docs/specs/2026-09-two-factor-authentication.md`` §5.1 and §5.4.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.utils import timezone

from .api_keys import hash_secret, verify_secret
from .models import AppSettings, MfaRecoveryCode, TotpDevice, User

MFA_CHALLENGE_SALT = "accounts.mfa.challenge"

# How long a password-verified-but-not-yet-challenged login has to complete
# the second step. Not configurable via settings, like MAGIC_LINK_LIFETIME —
# no deployment has asked to tune this, and a fixed value is one less thing
# to get wrong.
MFA_CHALLENGE_TTL = timedelta(minutes=5)

# RFC 8176 "Authentication Method Reference Values" entries that indicate a
# second factor was actually used. "pwd" (password alone) deliberately does
# NOT satisfy door 4's require_mfa_claim check — an IdP naming only "pwd" in
# amr is telling us exactly what local password-only login already provides.
OAUTH_MFA_AMR_VALUES = {"mfa", "otp", "hwk", "swk", "sms", "face", "fpt", "iris", "vbm", "wia"}


class MfaChallengeError(Exception):
    """The challenge token is malformed, expired, or names a user that no
    longer exists. Callers respond with a generic 400 either way — see
    CustomTokenObtainPairView's own philosophy of not distinguishing failure
    reasons to the caller, only internally (in the audit reason)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def issue_challenge(user: User) -> str:
    """Sign a token naming ``user``, valid for MFA_CHALLENGE_TTL.

    Deliberately a signed value, not a JWT: no authentication class in this
    project parses ``TimestampSigner`` output, so this token is structurally
    incapable of authenticating a request even if a bug tried to use it as
    one — see ``test_challenge_token_cannot_authenticate_a_request``.
    """
    signer = signing.TimestampSigner(salt=MFA_CHALLENGE_SALT)
    return signer.sign(str(user.pk))


def resolve_challenge(token: str) -> User:
    """Resolve a challenge token to its user.

    Raises ``MfaChallengeError`` (reason "expired_challenge" or
    "invalid_challenge") rather than leaking which case applies to the
    caller — only the audit log's reason field distinguishes them.
    """
    signer = signing.TimestampSigner(salt=MFA_CHALLENGE_SALT)
    try:
        user_pk = signer.unsign(token or "", max_age=MFA_CHALLENGE_TTL)
    except signing.SignatureExpired:
        raise MfaChallengeError("expired_challenge") from None
    except signing.BadSignature:
        raise MfaChallengeError("invalid_challenge") from None

    try:
        return User.objects.get(pk=user_pk)
    except (User.DoesNotExist, ValueError):
        # ValueError: user_pk isn't a valid pk shape (shouldn't happen for a
        # token this process issued, but a foreign/forged token could claim
        # anything the signature happens to still validate against — it
        # can't, since the signing key differs, but defence in depth is free).
        raise MfaChallengeError("invalid_challenge") from None


def has_active_factor(user: User) -> bool:
    """Whether ``user`` has a second factor that *gates a password login* —
    i.e. one that can answer a challenge. That is TOTP only.

    A passkey is deliberately not counted: it authenticates on its own and
    replaces the password (ADR 0020), so it cannot be a second step after
    one. See ``has_any_factor`` for "is this account protected at all".
    """
    # A query, not ``user.totp_device``: that reverse accessor caches on the
    # instance, so right after a device is deleted it would still report one.
    return TotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def has_any_factor(user: User) -> bool:
    """Whether ``user`` has any registered factor — an active TOTP device or
    at least one passkey. What the enrolment policy is satisfied by."""
    return has_active_factor(user) or user.webauthn_credentials.exists()


def policy_applies(user: User) -> bool:
    """Whether ``AppSettings.mfa_required_roles`` names this user's role."""
    return user.role in AppSettings.load().mfa_required_roles


def grace_deadline(user: User):
    """When enrolment stops being optional for ``user``, or ``None`` if no
    policy applies to them.

    Runs from the later of the account's creation and the last policy change,
    so switching the requirement on never locks out an account that already
    existed — the failure mode this deadline exists to prevent.
    """
    app_settings = AppSettings.load()
    if user.role not in app_settings.mfa_required_roles:
        return None
    since = max(t for t in (user.date_joined, app_settings.mfa_policy_changed_at) if t is not None)
    return since + timedelta(days=app_settings.mfa_grace_period_days)


def removal_blocked(user: User, *, leaving: int) -> bool:
    """Whether dropping a factor must be refused: the policy requires one
    from this user and ``leaving`` factors would remain (zero means none).

    Refused regardless of the grace period — the grace period is for people
    who have not enrolled yet, not a way back out once they have.
    """
    return leaving == 0 and policy_applies(user)


def factor_count(user: User) -> int:
    """How many factors the user has: one for an active TOTP device plus one
    per passkey. Only used to reason about what a removal would leave."""
    return int(has_active_factor(user)) + user.webauthn_credentials.count()


def drop_recovery_codes_if_unprotected(user: User) -> None:
    """Recovery codes recover into a factor; with none left they are dead
    weight (and re-enrolling issues a fresh set anyway)."""
    if not has_any_factor(user):
        MfaRecoveryCode.objects.filter(user=user).delete()


def consume_recovery_code(user: User, code: str) -> bool:
    """Mark one of ``user``'s unused recovery codes used, if ``code``
    matches any of them. Locks the candidate rows so two concurrent
    submissions of the same code cannot both succeed."""
    with transaction.atomic():
        candidates = MfaRecoveryCode.objects.select_for_update().filter(user=user, used_at__isnull=True)
        for candidate in candidates:
            if verify_secret(code, candidate.code_hash):
                candidate.used_at = timezone.now()
                candidate.save(update_fields=["used_at"])
                return True
    return False


def verify_mfa_code(user: User, raw_code: str) -> tuple[bool, str | None, str | None]:
    """Check a code submitted to complete a challenge.

    Returns ``(success, method, failure_reason)``: on success ``method`` is
    ``"totp"`` or ``"recovery_code"`` and ``failure_reason`` is ``None``; on
    failure ``method`` is ``None`` and ``failure_reason`` is
    ``"invalid_code"`` or ``"replayed_code"``.

    Dispatches on shape rather than trying both blindly: a TOTP code is
    exactly 6 digits, a recovery code is 10 hex characters (optionally
    grouped with a dash, as displayed — stripped here before matching).
    """
    code = (raw_code or "").strip().replace("-", "").replace(" ", "")

    if code.isdigit() and len(code) == 6:
        device = getattr(user, "totp_device", None)
        if device is None or not device.is_active:
            return False, None, "invalid_code"
        ok, reason = device.check_code(code)
        if ok:
            return True, "totp", None
        return False, None, reason

    if consume_recovery_code(user, code):
        return True, "recovery_code", None
    return False, None, "invalid_code"


# Ten codes per issue (spec §4.3) — few enough to print on one line each, many
# enough that losing an authenticator does not mean losing the account after
# a handful of logins.
RECOVERY_CODE_COUNT = 10


def issue_recovery_codes(user: User) -> list[str]:
    """Replace ``user``'s recovery codes with a fresh set of
    ``RECOVERY_CODE_COUNT``, returned in plaintext — the only time they ever
    are. Used both at first confirmation and at explicit regeneration; either
    way, an old printout must stop working."""
    MfaRecoveryCode.objects.filter(user=user).delete()
    plaintext_codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5)
        MfaRecoveryCode.objects.create(user=user, code_hash=hash_secret(raw))
        plaintext_codes.append(f"{raw[:5]}-{raw[5:]}")
    return plaintext_codes


def totp_qr_svg(provisioning_uri: str) -> str:
    """An inline SVG QR encoding an otpauth:// URI, matching how
    invoices.access_tokens.qr_svg renders the QR-Rechnung: no raster weight,
    scales crisply, and never touches a third-party QR-rendering service —
    which matters here more than for a printed invoice, since this SVG
    briefly represents the shared secret itself."""
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(
        provisioning_uri,
        image_factory=qrcode.image.svg.SvgPathImage,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def amr_satisfies_mfa(amr_claim) -> bool:
    """Whether an OIDC ``amr`` claim names a second-factor method.

    ``amr`` is conventionally a list of strings, but tolerate a single
    string (some providers send a space-separated string instead of a JSON
    array) rather than rejecting a provider that satisfies the OIDC spirit
    but not this project's assumed shape.
    """
    if isinstance(amr_claim, str):
        values = amr_claim.split()
    elif isinstance(amr_claim, (list, tuple)):
        values = [str(v) for v in amr_claim]
    else:
        values = []
    return bool(OAUTH_MFA_AMR_VALUES.intersection(values))
