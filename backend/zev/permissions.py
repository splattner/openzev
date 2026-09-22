from rest_framework.permissions import BasePermission, SAFE_METHODS


class BaseZevScopedPermission(BasePermission):
    allow_participant_safe_methods = False

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_admin or user.is_zev_owner:
            return True
        return self.allow_participant_safe_methods and request.method in SAFE_METHODS

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_admin:
            return True
        zev = self._get_zev(obj)
        if zev is None:
            return False
        if user.is_zev_owner and zev.owner == user:
            return True
        if self.allow_participant_safe_methods and request.method in SAFE_METHODS:
            return zev.participants.filter(user=user).exists()
        return False

    def _get_zev(self, obj):
        from .models import Zev, Participant, MeteringPoint, MeteringPointAssignment
        if isinstance(obj, Zev):
            return obj
        if isinstance(obj, Participant):
            return obj.zev
        if isinstance(obj, MeteringPoint):
            return obj.zev
        if isinstance(obj, MeteringPointAssignment):
            return obj.metering_point.zev
        return None


class ZevManagementPermission(BaseZevScopedPermission):
    # POST creates a ZEV (or imports an archive, which creates one) —
    # admin-only, same as ``ZevViewSet.create``. DELETE is the same
    # irreversibility class: ``ZevViewSet`` has no ``destroy`` override, so
    # without this a ZEV owner's object-level match in
    # ``has_object_permission`` would let them hard-delete their own
    # community straight through DRF's default ``DestroyModelMixin``.
    ADMIN_ONLY_METHODS = frozenset({"POST", "DELETE"})

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in self.ADMIN_ONLY_METHODS:
            return request.user.is_admin
        return True


class MeteringPointPermission(BaseZevScopedPermission):
    allow_participant_safe_methods = True


class MeteringPointAssignmentPermission(BaseZevScopedPermission):
    pass
