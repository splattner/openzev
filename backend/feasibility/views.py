from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import FeatureFlag
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev

from .calculator import FeasibilityInput, ParticipantInput, compute_feasibility
from .prefill import build_prefill
from .serializers import (
    FeasibilityInputSerializer,
    FeasibilityPrefillSerializer,
    FeasibilityResultSerializer,
)


def _feasibility_disabled_response() -> Response:
    """The 403 both gated views return when the flag is off.

    A shared helper so the message can't drift between the two call sites —
    ``FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED`` gates both, and a client
    hiding the nav link is not a substitute for the API enforcing it.
    """
    return Response(
        {"detail": "The feasibility calculator is currently disabled."},
        status=status.HTTP_403_FORBIDDEN,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def feasibility_calculator_enabled(request):
    """Whether the feasibility calculator is on, for any authenticated user.

    Mirrors ``accounts.views.registration_enabled``: a minimal boolean rather
    than the admin-only flag list, since every authenticated role (not just
    admins) needs to know this to decide whether to show the nav link and
    the page. Read-only — no ``sync_defaults()`` call — for the same reason
    that endpoint skips it: ``FeatureFlag.is_enabled`` already falls back to
    the code default without a database row, so nothing here needs a row to
    exist, and every authenticated user hitting this on every page load
    should not be a write.
    """
    return Response({"enabled": FeatureFlag.is_enabled(FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED)})


class FeasibilityCalculateView(APIView):
    """Stateless vZEV feasibility calculation.

    Not scoped to a specific ZEV — any authenticated user can run planning
    scenarios (e.g. a prospect evaluating whether to form a vZEV at all).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not FeatureFlag.is_enabled(FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED):
            return _feasibility_disabled_response()

        input_serializer = FeasibilityInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        validated = dict(input_serializer.validated_data)
        validated["participants"] = tuple(
            ParticipantInput(**participant) for participant in validated["participants"]
        )

        inputs = FeasibilityInput(**validated)
        result = compute_feasibility(inputs)

        return Response(FeasibilityResultSerializer(result).data)


class FeasibilityPrefillView(APIView):
    """Best-effort prefill of calculator inputs from a real ZEV's
    participants and tariffs — see ``prefill.build_prefill`` for exactly
    what it can and can't determine. Scoped to the ZEV's owner (or an admin),
    unlike the calculate endpoint, since it exposes real participant names
    and tariff figures.
    """

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get(self, request, zev_id, *args, **kwargs):
        if not FeatureFlag.is_enabled(FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED):
            return _feasibility_disabled_response()

        zev = self._get_accessible_zev(zev_id)
        if zev is None:
            return Response({"detail": "ZEV not found or not accessible."}, status=status.HTTP_404_NOT_FOUND)

        prefill = build_prefill(zev)
        return Response(FeasibilityPrefillSerializer(prefill).data)

    def _get_accessible_zev(self, zev_id):
        user = self.request.user
        if user.is_admin:
            return Zev.objects.filter(id=zev_id).first()
        return Zev.objects.filter(id=zev_id, owner=user).first()
