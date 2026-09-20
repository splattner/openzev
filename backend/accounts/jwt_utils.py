from rest_framework_simplejwt.tokens import RefreshToken

#: Claim carrying ``User.session_version`` at the moment the token was issued.
#: A token whose value no longer matches the account's is a signed-out session
#: (see ``accounts.session_revocation`` and ADR 0022).
SESSION_CLAIM = "sv"

IMPERSONATOR_CLAIM = "impersonated_by"


def make_jwt_for_user(user, *, impersonated_by=None) -> dict:
    refresh = RefreshToken.for_user(user)
    add_custom_claims(refresh, user)
    if impersonated_by:
        refresh[IMPERSONATOR_CLAIM] = impersonated_by
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def add_custom_claims(token, user) -> None:
    token["role"] = user.role
    token["email"] = user.email
    token["full_name"] = user.get_full_name()
    token["must_change_password"] = user.must_change_password
    token[SESSION_CLAIM] = user.session_version


def impersonator_of(token) -> int | None:
    """The admin behind an impersonation session, or ``None``.

    ``request.auth`` is a validated JWT for browser sessions but an ``ApiKey``
    for scripts, which carry no such claim — hence the ``hasattr`` guard.
    """
    if token is None or not hasattr(token, "get"):
        return None
    return token.get(IMPERSONATOR_CLAIM) or None
