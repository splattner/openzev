"""WebAuthn ceremony helpers for passkey registration and authentication.

Kept apart from ``views_passkeys.py`` for the same reason ``mfa.py`` is apart
from ``views.py``: the security-relevant steps (challenge lifetime, what is
demanded of the authenticator) live in one readable place, and the views only
translate HTTP.

A user-verified passkey authenticates on its own and replaces the password
(ADR 0020). That is why **every** ceremony here demands
``userVerification: "required"`` — a credential usable by whoever holds an
unlocked device would be a single possession factor, and would not justify
dropping the password.

See ``docs/specs/2026-09-two-factor-authentication.md`` §5.1, §5.2 and §6.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorTransport,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import User, WebAuthnCredential

# Ceremony challenges are single-use by construction and must not outlive the
# ceremony — five minutes is generous for a biometric prompt.
CHALLENGE_TTL = timedelta(minutes=5)

_KEY_PREFIX = "mfa:webauthn"


class PasskeyCeremonyError(Exception):
    """A ceremony step failed. ``reason`` is what the audit log records; the
    HTTP response is deliberately the same generic 400 whatever it is, as with
    every other failure on the login path."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _cache_set(key: str, value: str) -> None:
    cache.set(key, value, timeout=int(CHALLENGE_TTL.total_seconds()))


def _cache_take(key: str) -> str | None:
    """Return and remove ``key``'s value; ``None`` if absent or already taken.

    ``cache.delete`` reports whether the key existed, which is what makes this
    atomic enough: of two concurrent completions of the same ceremony, only
    the one whose delete succeeds may proceed. Matters for authenticators that
    always report a zero signature counter, where the single-use challenge is
    the only replay guard.
    """
    value = cache.get(key)
    if value is None or not cache.delete(key):
        return None
    return value


def user_handle(user: User) -> bytes:
    """The opaque, stable ``user.id`` handed to the authenticator. Not secret
    and not PII, unlike the email — WebAuthn asks for exactly that."""
    return str(user.pk).encode()


def _descriptor(credential: WebAuthnCredential) -> PublicKeyCredentialDescriptor:
    known = {t.value for t in AuthenticatorTransport}
    transports = [AuthenticatorTransport(t) for t in credential.transports if t in known]
    return PublicKeyCredentialDescriptor(id=bytes(credential.credential_id), transports=transports or None)


def _json(options) -> dict:
    return json.loads(options_to_json(options))


def begin_registration(user: User) -> dict:
    """Options for ``navigator.credentials.create()``.

    Existing credentials are excluded so the same authenticator cannot be
    enrolled twice under one account.
    """
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=user_handle(user),
        user_name=user.email or user.username,
        user_display_name=user.get_full_name() or user.email or user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[_descriptor(c) for c in user.webauthn_credentials.all()],
    )
    _cache_set(f"{_KEY_PREFIX}:reg:{user.pk}", bytes_to_base64url(options.challenge))
    return _json(options)


def complete_registration(user: User, credential: dict):
    """Verify an attestation and return the library's ``VerifiedRegistration``.

    Raises ``PasskeyCeremonyError`` when the challenge is missing or spent, or
    the attestation does not verify (including an authenticator that did not
    verify the user).
    """
    from webauthn.helpers.exceptions import WebAuthnException

    challenge = _cache_take(f"{_KEY_PREFIX}:reg:{user.pk}")
    if challenge is None:
        raise PasskeyCeremonyError("expired_challenge")
    try:
        return verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise PasskeyCeremonyError("invalid_attestation") from None


def begin_authentication(email: str = "") -> dict:
    """Options for ``navigator.credentials.get()``.

    ``email`` only narrows ``allowCredentials`` as a hint; it is never
    required (a discoverable credential names its own user). An unknown
    address, or one with no passkeys, yields the same shape as no address at
    all — so this endpoint cannot be used to learn which accounts exist.
    """
    allow = []
    email = (email or "").strip()
    if email:
        matches = list(User.objects.filter(email__iexact=email, is_active=True)[:2])
        if len(matches) == 1:
            allow = [_descriptor(c) for c in matches[0].webauthn_credentials.all()]

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow or None,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _cache_set(f"{_KEY_PREFIX}:auth:{bytes_to_base64url(options.challenge)}", "1")
    return _json(options)


def _challenge_of(credential: dict) -> str:
    """The challenge the authenticator signed, read back out of its own
    ``clientDataJSON``. Authentication is unauthenticated — there is no
    session to key the cached challenge on — so the challenge itself is the
    key, and is still verified against what the browser signed."""
    try:
        client_data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        challenge = client_data["challenge"]
    except (KeyError, TypeError, ValueError):
        raise PasskeyCeremonyError("invalid_assertion") from None
    # Untrusted input that becomes part of a cache key: bound it.
    if not isinstance(challenge, str) or not challenge or len(challenge) > 128:
        raise PasskeyCeremonyError("invalid_assertion")
    return challenge


def complete_authentication(credential: dict):
    """Verify an assertion. Returns ``(stored_credential, verified)``.

    Does **not** update the stored counter or ``last_used_at`` — the view
    does, after checking for a counter regression, inside its own transaction.

    Raises ``PasskeyCeremonyError`` with ``expired_challenge``,
    ``unknown_credential`` or ``invalid_assertion``.
    """
    from webauthn.helpers.exceptions import WebAuthnException

    challenge = _challenge_of(credential)
    if _cache_take(f"{_KEY_PREFIX}:auth:{challenge}") is None:
        raise PasskeyCeremonyError("expired_challenge")

    try:
        raw_id = base64url_to_bytes(credential["rawId"])
    except (KeyError, TypeError, ValueError):
        raise PasskeyCeremonyError("invalid_assertion") from None
    stored = WebAuthnCredential.objects.select_related("user").filter(credential_id=raw_id).first()
    if stored is None:
        raise PasskeyCeremonyError("unknown_credential")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=bytes(stored.public_key),
            # The library's own regression check is neutralised (0 never
            # rejects a positive count) so the view can audit a regression
            # as auth.passkey.sign_count_regression instead of a bare failure.
            credential_current_sign_count=0,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        raise PasskeyCeremonyError("invalid_assertion") from None
    return stored, verified


def is_sign_count_regression(stored_count: int, new_count: int) -> bool:
    """A counter that did not advance, on an authenticator that has counted
    before. Authenticators that always report 0 (permitted by the spec) are
    exempt because their stored value is 0."""
    return stored_count != 0 and new_count <= stored_count
