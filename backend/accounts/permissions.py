from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import UserRole


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin


def may_hold_management_access(user) -> bool:
    """Transitional (#761, until ``User.role`` collapses): an account still
    carrying the old ``zev_owner`` role passes the coarse "manages something"
    gates even before it holds a grant, as it did before grants existed — a
    self-registered owner who has not finished setup sees empty lists rather
    than 403s. It widens nothing: rows are still scoped by grants."""
    return getattr(user, "role", None) == UserRole.ZEV_OWNER


class HasZevAccess(BasePermission):
    """The account may view (safe methods) or manage (unsafe ones) some ZEV.

    A coarse gate only: which ZEV is decided by the scoped queryset or an
    explicit ``zev.access.can_manage`` / ``can_view`` check in the view. A view
    may list read-only POST actions in ``viewer_allowed_actions``.
    """

    def has_permission(self, request, view):
        from zev import access

        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_admin or may_hold_management_access(user):
            return True
        reads = self.only_reads(request, view)
        return bool(access.viewable_zev_ids(user) if reads else access.managed_zev_ids(user))

    def only_reads(self, request, view) -> bool:
        return request.method in SAFE_METHODS or getattr(view, "action", None) in getattr(
            view, "viewer_allowed_actions", ()
        )


class HasZevReadAccess(HasZevAccess):
    """``HasZevAccess`` for an endpoint whose every request only reads, whatever
    its method — the MCP endpoint, which is POST-only but read-only (ADR 0025)."""

    def only_reads(self, request, view) -> bool:
        return True
