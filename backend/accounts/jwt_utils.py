from rest_framework_simplejwt.tokens import RefreshToken


def make_jwt_for_user(user) -> dict:
    refresh = RefreshToken.for_user(user)
    add_custom_claims(refresh, user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def add_custom_claims(token, user) -> None:
    token["role"] = user.role
    token["email"] = user.email
    token["full_name"] = user.get_full_name()
    token["must_change_password"] = user.must_change_password
