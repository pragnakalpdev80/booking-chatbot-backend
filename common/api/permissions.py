from rest_framework.permissions import BasePermission


class IsProviderUser(BasePermission):
    """
    Allows access only to authenticated users who have the 'is_provider'
    flag set to True on their UserProfile.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_provider", False)
        )
