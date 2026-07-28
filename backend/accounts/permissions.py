from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_admin


class IsZevOwnerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_zev_owner or request.user.is_admin
        )


class IsParticipantOrAbove(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated
