"""Room membership is required for coach data; staff adds installation administration."""
from rest_framework.permissions import BasePermission
from .room_access import has_room_access


class IsCoach(BasePermission):
    """Require an active account assigned to this installation’s room."""

    def has_permission(self, request, view):
        return has_room_access(request.user)


class IsActiveStaff(BasePermission):
    """Require the active staff account used for security-sensitive setup."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
            and has_room_access(request.user)
        )


class IsInstallationAdmin(BasePermission):
    """The head coach: an active staff account that may manage other coaches.

    Staff status is the sole difference between an administrator and an ordinary
    coach, so this is the check that keeps account creation, password resets, and
    deactivation out of a regular coach's hands.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
            and has_room_access(request.user)
        )
