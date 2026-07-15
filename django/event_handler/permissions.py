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
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
        )
