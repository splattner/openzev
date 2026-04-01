from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomTokenObtainPairView, UserListCreateView,
    UserDetailView, me, change_password, impersonate_participant, app_settings,
    VatRateListCreateView, VatRateDetailView,
    feature_flags_list, feature_flag_update,
    register, verify_email, set_initial_password,
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
    path("app-settings/", app_settings, name="app-settings"),
    path("vat-rates/", VatRateListCreateView.as_view(), name="vat-rate-list-create"),
    path("vat-rates/<int:pk>/", VatRateDetailView.as_view(), name="vat-rate-detail"),
    path("feature-flags/", feature_flags_list, name="feature-flags-list"),
    path("feature-flags/<int:pk>/", feature_flag_update, name="feature-flag-update"),
]
