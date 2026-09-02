from rest_framework.permissions import SAFE_METHODS, BasePermission

from erp.permissions import has_erp_permission


class ReadOnlyOrStaffPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return has_erp_permission(request.user, "admin.configure")


class CRMSourcePermission(BasePermission):
    def has_permission(self, request, view):
        codename = "crm.view" if request.method in SAFE_METHODS else "crm.manage"
        return has_erp_permission(request.user, codename)
