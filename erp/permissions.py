from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS


ERP_PERMISSION_CODENAMES = (
    "purchase.create",
    "purchase.approve",
    "grn.create",
    "grn.approve",
    "quality.inspect",
    "supplier_invoice.post",
    "supplier_payment.post",
    "supplier_payment.reverse",
    "supplier_advance.post",
    "supplier_advance.adjust",
    "stock.issue",
    "stock.adjust",
    "production.post",
    "packing.post",
    "reports.view_financial",
    "reports.view_inventory",
    "supplier_rate.view",
    "supplier_rate.create",
    "supplier_rate.approve",
    "supplier_rate.override",
    "production_log.view",
    "production_log.create",
    "production_log.submit",
    "production_log.approve",
    "customer.view",
    "customer.create",
    "customer.edit",
    "customer.block",
    "scheduled_task.view",
    "scheduled_task.run",
    "scheduled_task.configure",
    "report.supplier_rate",
    "report.production_log",
    "report.customer_master",
    "report.scheduled_task",
    "sales.view",
    "sales.manage",
    "sales.invoice",
    "sales.payment",
    "sales.dispatch",
    "sales.return",
    "crm.view",
    "crm.manage",
    "release.view",
    "admin.configure",
)

DOMAIN_REPORT_PERMISSIONS = {
    "supplier-active-rates": "report.supplier_rate",
    "supplier-rate-variance": "report.supplier_rate",
    "item-supplier-rate-comparison": "report.supplier_rate",
    "supplier-rate-comparison": "report.supplier_rate",
    "daily-production-log": "report.production_log",
    "shift-production-log": "report.production_log",
    "operator-production-log": "report.production_log",
    "machine-production-log": "report.production_log",
    "daily-wastage-summary": "report.production_log",
    "daily-packing-summary": "report.production_log",
    "production-issue-summary": "report.production_log",
    "customer-master": "report.customer_master",
    "customer-segmentation": "report.customer_master",
    "customer-by-channel": "report.customer_master",
    "customer-by-location": "report.customer_master",
    "blocked-customers": "report.customer_master",
    "distributor-readiness": "report.customer_master",
    "scheduled-task-log": "report.scheduled_task",
    "failed-scheduled-jobs": "report.scheduled_task",
}

# Reports gated by financial permission
FINANCIAL_REPORTS = {
    "supplier-ledger",
    "supplier-aging",
    "supplier-balance",
    "payment-reversal",
    "debit-note",
    "credit-note",
    "opening-balance",
    "purchase",
    "grn",
    "supplier-advance-report",
    "user-activity",
    "approval-pending",
}

# Reports gated by inventory permission
INVENTORY_REPORTS = {
    "raw-stock",
    "powder-stock",
    "packaging-stock",
    "finished-stock",
    "yield",
    "costing",
    "expiry",
    "batch-traceability",
    "quality-rejection",
    "wastage",
    "packing",
    "packaging-consumption",
    "near-expiry",
    "expired-stock",
    "stock-adjustment",
    "fefo-dispatch",
    "low-stock",
    "supplier-return",
    "damaged-stock",
    "repacking",
    "supplier-rejection",
    "supplier-shortage",
    "supplier-yield",
    "grinding",
    "finished-sku-production",
    "batch-cost",
    "cost-variance",
}

# Read-permission mapping for viewsets  (safe-method reads)
FINANCIAL_READ_VIEWSETS = {
    "SupplierInvoiceViewSet",
    "SupplierPaymentViewSet",
    "AdjustmentDocumentViewSet",
}

INVENTORY_READ_VIEWSETS = {
    "StockBatchViewSet",
}


def has_erp_permission(user, codename: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.has_perm(f"erp.{codename}")


def report_permission_for(report_name: str) -> str | None:
    # Supplier returns affect stock and supplier balances. Apply the stronger
    # financial gate before inventory membership can match.
    if report_name == "supplier-return":
        return "reports.view_financial"
    if report_name in DOMAIN_REPORT_PERMISSIONS:
        return DOMAIN_REPORT_PERMISSIONS[report_name]
    if report_name in FINANCIAL_REPORTS:
        return "reports.view_financial"
    if report_name in INVENTORY_REPORTS:
        return "reports.view_inventory"
    # Supplier return is both inventory and financial — use financial
    if report_name in {"supplier-return", "supplier-balance"}:
        return "reports.view_financial"
    return None


class IsAuthenticatedAndCanPost(BasePermission):
    """
    Safe-method (GET/HEAD/OPTIONS) reads require IsAuthenticated by default.
    Write/action access requires the explicit permission declared on the view.
    
    IMPORTANT: For financial and inventory viewsets, safe-method reads are
    further restricted via FinancialReadPermission / InventoryReadPermission.
    """
    message = "This ERP workflow requires an explicit action permission."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            required = getattr(view, "required_read_permission", None)
            return not required or has_erp_permission(request.user, required)
        required = self._required_codename(view)
        return bool(required and has_erp_permission(request.user, required))

    def _required_codename(self, view) -> str | None:
        action = getattr(view, "action", None)
        action_permissions = getattr(view, "required_action_permissions", {})
        if action and action in action_permissions:
            return action_permissions[action]
        return getattr(view, "required_post_permission", None)


class FinancialReadPermission(BasePermission):
    """
    Restricts safe-method (read) access to financial endpoints.
    Requires reports.view_financial permission or superuser.
    Write/action permissions are handled separately by IsAuthenticatedAndCanPost.
    """
    message = "Financial data requires reports.view_financial permission."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method not in SAFE_METHODS:
            # Writes handled by IsAuthenticatedAndCanPost — allow through
            return True
        return has_erp_permission(request.user, "reports.view_financial")


class InventoryReadPermission(BasePermission):
    """
    Restricts safe-method (read) access to inventory endpoints.
    Requires reports.view_inventory permission or superuser.
    """
    message = "Inventory data requires reports.view_inventory permission."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method not in SAFE_METHODS:
            return True
        return has_erp_permission(request.user, "reports.view_inventory")
