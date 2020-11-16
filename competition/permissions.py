from rest_framework import permissions


class ProblemPermission(permissions.BasePermission):
    """
    Prístup k objektom má iba staff
    """

    def has_permission(self, request, view):
        if view.action in ['list', 'create', 'update', 'partial_update', 'destroy']:
            return request.user.is_authenticated and request.user.is_staff
        elif view.action in ['retrieve']:
            return True

    def has_object_permission(self, request, view, obj):
        if view.action == 'retrieve':
            return obj.is_visible or (request.user.is_authenticated and request.user.is_staff)
        elif view.action in ['update', 'partial_update', 'destroy']:
            return request.user.is_staff
        else:
            return False
