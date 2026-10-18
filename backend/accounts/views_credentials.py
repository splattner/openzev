from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import CookieJWTAuthentication
from .credentials import KINDS, STATUSES, can_create, list_credentials
from .permissions import IsAdmin


class MyCredentialsView(APIView):
    """The signed-in account's API keys, analytics tokens and energy data push tokens, as one list.

    Session only: a credential cannot enumerate credentials (the view is in
    ``accounts``, which API keys cannot reach, and it lists no token
    authentication). Never carries a secret.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Your tokens and keys", responses={200: dict})
    def get(self, request):
        return Response({"credentials": list_credentials(request.user), "can_create": can_create(request.user)})


class AdminCredentialsView(APIView):
    """Every account's credentials, for the admin console (read-only; revoking uses each kind's endpoint)."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdmin]

    @extend_schema(
        summary="All tokens and keys",
        parameters=[
            OpenApiParameter("user", int, description="Only this account's credentials."),
            OpenApiParameter("kind", str, enum=list(KINDS)),
            OpenApiParameter("status", str, enum=list(STATUSES)),
        ],
        responses={200: dict},
    )
    def get(self, request):
        params = request.query_params
        owner_id = params.get("user")
        if owner_id:
            if not (owner_id.isascii() and owner_id.isdigit()):
                raise ValidationError({"user": ["Not a valid user id."]})
            owner_id = int(owner_id)
        kind, status = params.get("kind") or None, params.get("status") or None
        if kind is not None and kind not in KINDS:
            raise ValidationError({"kind": [f"Expected one of: {', '.join(KINDS)}."]})
        if status is not None and status not in STATUSES:
            raise ValidationError({"status": [f"Expected one of: {', '.join(STATUSES)}."]})
        return Response({"credentials": list_credentials(None, kind=kind, status=status, owner_id=owner_id or None)})
