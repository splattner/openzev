from rest_framework_simplejwt.tokens import RefreshToken


def make_jwt_for_user(user) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["email"] = user.email
    refresh["full_name"] = user.get_full_name()
    refresh["must_change_password"] = user.must_change_password
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def add_custom_claims(token, user) -> None:
    token["role"] = user.role
    token["email"] = user.email
    token["full_name"] = user.get_full_name()
    token["must_change_password"] = user.must_change_password
