from rest_framework.permissions import BasePermission, SAFE_METHODS

from accounts.permissions import may_hold_management_access

from . import access


class BaseZevScopedPermission(BasePermission):
    """Per-ZEV access for the ZEV, participant and metering-point viewsets.

    Viewing a ZEV's rows takes a manager or viewer grant (or a participant link,
    where ``allow_participant_safe_methods``); changing them takes a manager
    grant. ADR 0027, SPEC-2026-10-zev-access-grants §6.2.
    """

    allow_participant_safe_methods = False

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_admin or may_hold_management_access(user):
            return True
        if request.method in SAFE_METHODS:
            return self.allow_participant_safe_methods or bool(access.viewable_zev_ids(user))
        return bool(access.managed_zev_ids(user))

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_admin:
            return True
        zev = self._get_zev(obj)
        if zev is None:
            return False
        # A disabled ZEV is inert: its managers and viewers keep read-only
        # access to whatever is under it (to check status, or pull the transfer
        # archive) but writing to it again takes an admin — through
        # ZevViewSet.enable or, later, a purge. This is the create-time
        # counterpart of ZevScopedQuerySetMixin.assert_within_scope, which
        # covers the same rule on POST (DRF never calls has_object_permission
        # there). Not yet covered here: Tariff/TariffPeriod/Invoice/
        # MeterReading use HasZevAccess, not this class; for those the
        # scoping mixin's assert_target_not_disabled gives the same rule.
        if zev.disabled_at is not None and request.method not in SAFE_METHODS:
            return user.is_admin
        if request.method not in SAFE_METHODS:
            return access.can_manage(user, zev)
        if access.can_view(user, zev):
            return True
        if self.allow_participant_safe_methods:
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
    # admin-only, same as ``ZevViewSet.create``. DELETE is not a supported
    # method on ``ZevViewSet`` at all (see its ``http_method_names``) — the
    # only way to permanently remove a ZEV is disable, then purge.
    ADMIN_ONLY_METHODS = frozenset({"POST"})

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in self.ADMIN_ONLY_METHODS:
            return request.user.is_admin
        return True

    # has_object_permission's disabled-ZEV write block is inherited from
    # BaseZevScopedPermission unchanged — a Zev object resolves to itself via
    # _get_zev, so the same rule that protects a Participant/MeteringPoint
    # row under a disabled ZEV also protects the Zev row itself.


class ZevDisablePermission(BaseZevScopedPermission):
    """Management only — deliberately without the inherited disabled-ZEV write
    block.

    ``disable``'s whole job is to act on a ZEV regardless of its current
    state: calling it on an already-disabled ZEV is a 400 ("already
    disabled") from the view, not a 403 from here. An owner is not being
    denied permission to touch their own ZEV; the request is just redundant,
    and the object-permission layer should not pre-empt that distinction.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_admin:
            return True
        zev = self._get_zev(obj)
        return zev is not None and access.can_manage(user, zev)


class MeteringPointPermission(BaseZevScopedPermission):
    allow_participant_safe_methods = True


class MeteringPointAssignmentPermission(BaseZevScopedPermission):
    pass
