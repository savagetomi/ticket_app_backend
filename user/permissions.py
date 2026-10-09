from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsActiveAuthenticated(BasePermission):
    """Require an authenticated account that has not been deactivated."""

    message = 'This account has been deactivated.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, 'is_active', False)
        )


class IsActiveAuthenticatedOrReadOnly(BasePermission):
    """Allow public reads but require an active account for writes."""

    message = 'This account has been deactivated.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return IsActiveAuthenticated().has_permission(request, view)


class IsHost(BasePermission):
    """Allow only active accounts that hold the host role."""

    message = 'An active host account is required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, 'is_active', False)
            and getattr(user, 'roles', None) == 'host'
        )


class IsAccountAdministrator(BasePermission):
    """Permit only active Django/app administrators to recover accounts.

    A superuser is always an administrator. Other accounts must have both
    Django staff access and the explicit application ``admin`` role; a client
    cannot obtain either privilege through the public registration endpoint.
    """

    message = 'Administrator permissions are required.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not (
            user
            and user.is_authenticated
            and getattr(user, 'is_active', False)
        ):
            return False

        return bool(
            getattr(user, 'is_superuser', False)
            or (
                getattr(user, 'is_staff', False)
                and getattr(user, 'roles', None) == 'admin'
            )
        )
