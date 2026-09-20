from django.urls import path
from .views import (
    AdminApiKeyDetailView, AdminApiKeyListView,
    ApiKeyDetailView, ApiKeyListCreateView,
    CustomTokenObtainPairView, CookieTokenRefreshView, TokenMfaView, logout_view,
    MfaStatusView, MfaRecoveryCodesView, TotpDeviceView, TotpEnrolConfirmView,
    AdminMfaResetView,
    UserListCreateView,
    UserDetailView, me, change_password, app_settings,
    VatRateListCreateView, VatRateDetailView,
    feature_flags_list, feature_flag_update, registration_enabled,
    register, verify_email, set_initial_password,
)
from .views_oauth import (
    OAuthProviderDetailView,
    OAuthProviderListCreateView,
    oauth_callback,
    oauth_link_initiate,
    oauth_login_initiate,
    oauth_providers_public,
    oauth_token_exchange,
    social_account_delete,
    social_accounts_list,
)
from .views_passkeys import (
    PasskeyAuthenticateBeginView,
    PasskeyAuthenticateCompleteView,
    PasskeyDetailView,
    PasskeyListView,
    PasskeyRegisterBeginView,
    PasskeyRegisterCompleteView,
)
from .views_impersonation import ImpersonateParticipantView, StopImpersonationView
from .views_system import SystemHealthView

urlpatterns = [
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("token/mfa/", TokenMfaView.as_view(), name="token-mfa"),
    path("logout/", logout_view, name="logout"),
    path("register/", register, name="register"),
    path("verify-email/", verify_email, name="verify-email"),
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:user_id>/impersonate/", ImpersonateParticipantView.as_view(), name="impersonate-participant"),
    path("users/stop-impersonation/", StopImpersonationView.as_view(), name="stop-impersonation"),
    path("me/", me, name="me"),
    path("me/change-password/", change_password, name="change-password"),
    path("me/set-initial-password/", set_initial_password, name="set-initial-password"),
    # Deliberately absent from ACCOUNTS_API_KEY_ALLOWLIST (default-deny): a key
    # must not be able to manage or bypass its own owner's second factor.
    path("me/mfa/", MfaStatusView.as_view(), name="mfa-status"),
    path("me/mfa/totp/", TotpDeviceView.as_view(), name="mfa-totp-device"),
    path("me/mfa/totp/confirm/", TotpEnrolConfirmView.as_view(), name="mfa-totp-confirm"),
    path("me/mfa/recovery-codes/", MfaRecoveryCodesView.as_view(), name="mfa-recovery-codes"),
    path("me/passkeys/", PasskeyListView.as_view(), name="passkey-list"),
    path("me/passkeys/register/begin/", PasskeyRegisterBeginView.as_view(), name="passkey-register-begin"),
    path("me/passkeys/register/complete/", PasskeyRegisterCompleteView.as_view(), name="passkey-register-complete"),
    path("me/passkeys/<uuid:pk>/", PasskeyDetailView.as_view(), name="passkey-detail"),
    path("passkeys/authenticate/begin/", PasskeyAuthenticateBeginView.as_view(), name="passkey-authenticate-begin"),
    path("passkeys/authenticate/complete/", PasskeyAuthenticateCompleteView.as_view(), name="passkey-authenticate-complete"),
    path("users/<int:pk>/mfa/", AdminMfaResetView.as_view(), name="admin-mfa-reset"),
    # Deliberately absent from ACCOUNTS_API_KEY_ALLOWLIST: a key that can issue
    # or revoke keys makes revoking a leaked one pointless.
    path("me/api-keys/", ApiKeyListCreateView.as_view(), name="api-key-list-create"),
    path("me/api-keys/<uuid:pk>/", ApiKeyDetailView.as_view(), name="api-key-detail"),
    # Admin console: read + revoke any user's key. Also absent from
    # ACCOUNTS_API_KEY_ALLOWLIST — an admin's own key must not be able to
    # revoke everyone else's.
    path("api-keys/", AdminApiKeyListView.as_view(), name="admin-api-key-list"),
    path("api-keys/<uuid:pk>/", AdminApiKeyDetailView.as_view(), name="admin-api-key-detail"),
    path("me/social-accounts/", social_accounts_list, name="social-accounts-list"),
    path("me/social-accounts/<int:pk>/", social_account_delete, name="social-account-delete"),
    path("app-settings/", app_settings, name="app-settings"),
    path("system-health/", SystemHealthView.as_view(), name="system-health"),
    path("vat-rates/", VatRateListCreateView.as_view(), name="vat-rate-list-create"),
    path("vat-rates/<int:pk>/", VatRateDetailView.as_view(), name="vat-rate-detail"),
    path("feature-flags/", feature_flags_list, name="feature-flags-list"),
    path("feature-flags/<int:pk>/", feature_flag_update, name="feature-flag-update"),
    path("registration-enabled/", registration_enabled, name="registration-enabled"),
    # OAuth provider config (admin)
    path("oauth/providers/config/", OAuthProviderListCreateView.as_view(), name="oauth-provider-list-create"),
    path("oauth/providers/config/<int:pk>/", OAuthProviderDetailView.as_view(), name="oauth-provider-detail"),
    # OAuth flow (public)
    path("oauth/providers/", oauth_providers_public, name="oauth-providers-public"),
    path("oauth/login/<str:provider_slug>/", oauth_login_initiate, name="oauth-login-initiate"),
    path("oauth/link/<str:provider_slug>/", oauth_link_initiate, name="oauth-link-initiate"),
    path("oauth/callback/<str:provider_slug>/", oauth_callback, name="oauth-callback"),
    path("oauth/token-exchange/", oauth_token_exchange, name="oauth-token-exchange"),
]
