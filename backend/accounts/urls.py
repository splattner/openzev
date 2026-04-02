from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomTokenObtainPairView, UserListCreateView,
    UserDetailView, me, change_password, impersonate_participant, app_settings,
    VatRateListCreateView, VatRateDetailView,
    feature_flags_list, feature_flag_update,
    register, verify_email, set_initial_password,
    # OAuth
    OAuthProviderListCreateView, OAuthProviderDetailView,
    oauth_providers_public,
    oauth_login_initiate, oauth_link_initiate,
    oauth_callback, oauth_token_exchange,
    social_accounts_list, social_account_delete,
)

urlpatterns = [
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("register/", register, name="register"),
    path("verify-email/", verify_email, name="verify-email"),
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:user_id>/impersonate/", impersonate_participant, name="impersonate-participant"),
    path("me/", me, name="me"),
    path("me/change-password/", change_password, name="change-password"),
    path("me/set-initial-password/", set_initial_password, name="set-initial-password"),
    path("me/social-accounts/", social_accounts_list, name="social-accounts-list"),
    path("me/social-accounts/<int:pk>/", social_account_delete, name="social-account-delete"),
    path("app-settings/", app_settings, name="app-settings"),
    path("vat-rates/", VatRateListCreateView.as_view(), name="vat-rate-list-create"),
    path("vat-rates/<int:pk>/", VatRateDetailView.as_view(), name="vat-rate-detail"),
    path("feature-flags/", feature_flags_list, name="feature-flags-list"),
    path("feature-flags/<int:pk>/", feature_flag_update, name="feature-flag-update"),
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
