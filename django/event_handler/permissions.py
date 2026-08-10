"""DRF permissions shared by staff-only API routes."""
from rest_framework.permissions import BasePermission


def active_staff_user(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_staff
    )


class IsActiveStaff(BasePermission):
    """Require the active staff account used for security-sensitive setup."""

    def has_permission(self, request, view):
        return active_staff_user(request.user)
