"""drf-spectacular extensions.

Without these, the schema generator sees a bare ``BaseAuthentication`` subclass
and emits nothing — so ``/api/docs/`` would document every endpoint while
telling a reader nothing about how to authenticate against it.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "A personal API key, created under Account → API Keys.\n\n"
                "Send it as `Authorization: Api-Key ozv_<prefix>_<secret>`.\n\n"
                "A key acts with its owner's permissions. Read-only keys are "
                "refused on any method other than GET, HEAD and OPTIONS. "
                "Endpoints under `/auth/` that mint a session, change how the "
                "owner signs in, or manage keys are closed to key "
                "authentication entirely."
            ),
        }


class CookieJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.CookieJWTAuthentication"
    name = "CookieJwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "The browser session. The access token normally travels in the "
                "`openzev_access` httpOnly cookie; the `Authorization: Bearer "
                "<token>` header is accepted as well."
            ),
        }
