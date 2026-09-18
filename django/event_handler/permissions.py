"""
permissions.py — the "bouncer" for coach-only actions.

Some actions (creating athletes, assigning racks, ending sessions) should only
work for a logged-in coach. This file is that check: is the person making the
request a logged-in coach? Yes -> let them through. No -> block it. Endpoints
that are open to any screen simply don't use this bouncer.
"""
from rest_framework.permissions import BasePermission


class IsCoach(BasePermission):
    """Allow the request only if it carries a valid coach login (a JWT token,
    which the login endpoint hands out)."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsActiveStaff(BasePermission):
    """Require the active staff account used for security-sensitive setup."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
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
        )
