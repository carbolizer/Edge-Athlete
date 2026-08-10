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


def active_organization_for_user(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None

    from .models import OrganizationMembership

    memberships = list(
        OrganizationMembership.objects
        .filter(user=user, is_active=True)
        .select_related("organization")
        .order_by("id")[:2]
    )
    return memberships[0].organization if len(memberships) == 1 else None


class HasActiveOrganization(BasePermission):
    message = "active organization membership required"
    code = "active_organization_membership_required"

    def has_permission(self, request, view):
        request.organization = active_organization_for_user(request.user)
        return request.organization is not None
