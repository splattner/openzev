"""Auth cookie names and helpers. ``set_auth_cookies`` also issues the CSRF cookie."""

from datetime import timedelta

from django.conf import settings
from django.middleware.csrf import get_token

ACCESS_COOKIE = "openzev_access"
REFRESH_COOKIE = "openzev_refresh"
ADMIN_ACCESS_COOKIE = "openzev_admin_access"
ADMIN_REFRESH_COOKIE = "openzev_admin_refresh"


def _cookie_kwargs() -> dict:
    """Shared kwargs for all auth cookies: httpOnly, Secure in prod, SameSite=Lax."""
    return {
        "httponly": True,
        "samesite": "Lax",
        "secure": not settings.DEBUG,
        "path": "/",
    }


def set_auth_cookies(
    request,
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
    kw = _cookie_kwargs()
    response.set_cookie(access_cookie, access, max_age=access_max_age, **kw)
    response.set_cookie(refresh_cookie, refresh, max_age=refresh_max_age, **kw)
    get_token(request)  # CsrfViewMiddleware sets the cookie


def clear_auth_cookies(
    response,
    access_cookie: str = ACCESS_COOKIE,
    refresh_cookie: str = REFRESH_COOKIE,
) -> None:
    response.delete_cookie(access_cookie, path="/")
    response.delete_cookie(refresh_cookie, path="/")
