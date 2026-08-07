from rest_framework.permissions import BasePermission


class IsHost(BasePermission):
    """Allows access only to authenticated users with the 'host' role."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.roles == 'host'
        )