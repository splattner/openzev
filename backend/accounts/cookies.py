"""Auth cookie names and helpers shared across the accounts views.

The project delivers JWTs in httpOnly cookies (``CookieJWTAuthentication`` also
accepts an ``Authorization: Bearer`` header as a fallback). Login, refresh,
logout, registration, email verification, OAuth and impersonation all set or
clear these cookies, so the names and the set/clear helpers live here rather
than being module-private to any one of them.

``ADMIN_*`` are the backup pair: while an admin is impersonating another user,
their own tokens are parked under these names so ``stop-impersonation`` can put
them back.
"""

from datetime import timedelta

from django.conf import settings

ACCESS_COOKIE = "openzev_access"
REFRESH_COOKIE = "openzev_refresh"
ADMIN_ACCESS_COOKIE = "openzev_admin_access"
ADMIN_REFRESH_COOKIE = "openzev_admin_refresh"


def cookie_kwargs() -> dict:
    """Shared kwargs for all auth cookies: httpOnly, Secure in prod, SameSite=Lax."""
    return {
        "httponly": True,
        "samesite": "Lax",
        "secure": not settings.DEBUG,
        "path": "/",
    }


def set_auth_cookies(
    response,
    *,
    access: str,
    refresh: str,
    access_cookie: str = ACCESS_COOKIE,
    refresh_cookie: str = REFRESH_COOKIE,
) -> None:
    jwt_settings = settings.SIMPLE_JWT
    access_max_age = int(jwt_settings.get("ACCESS_TOKEN_LIFETIME", timedelta(minutes=60)).total_seconds())
    refresh_max_age = int(jwt_settings.get("REFRESH_TOKEN_LIFETIME", timedelta(days=7)).total_seconds())
    kw = cookie_kwargs()
    response.set_cookie(access_cookie, access, max_age=access_max_age, **kw)
    response.set_cookie(refresh_cookie, refresh, max_age=refresh_max_age, **kw)


def clear_auth_cookies(
    response,
    access_cookie: str = ACCESS_COOKIE,
    refresh_cookie: str = REFRESH_COOKIE,
) -> None:
    response.delete_cookie(access_cookie, path="/")
    response.delete_cookie(refresh_cookie, path="/")
