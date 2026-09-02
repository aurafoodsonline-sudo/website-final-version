from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from erp.models import SupplierLedgerEntry
from erp.permissions import ERP_PERMISSION_CODENAMES


ROLE_NAMES = [
    "Owner",
    "Admin",
    "Purchase officer",
    "Warehouse officer",
    "Quality checker",
    "Production officer",
    "Packing officer",
    "Accounts officer",
    "Data entry operator",
    "Auditor viewer",
    "Sales officer",
]


ROLE_PERMISSION_MAP = {
    "Owner": set(ERP_PERMISSION_CODENAMES),
    "Admin": set(ERP_PERMISSION_CODENAMES),
    "Purchase officer": {
        "purchase.create", "purchase.approve", "grn.create", "reports.view_financial",
        "supplier_rate.view", "supplier_rate.create", "supplier_rate.override", "report.supplier_rate",
    },
    "Warehouse officer": {
        "grn.approve", "stock.issue", "stock.adjust", "reports.view_inventory",
        "sales.view", "sales.dispatch", "sales.return",
    },
    "Quality checker": {"quality.inspect", "reports.view_inventory"},
    "Production officer": {
        "stock.issue", "production.post", "reports.view_inventory",
        "production_log.view", "production_log.create", "production_log.submit", "report.production_log",
    },
    "Packing officer": {"packing.post", "stock.issue", "reports.view_inventory"},
    "Accounts officer": {
        "supplier_invoice.post",
        "supplier_payment.post",
        "supplier_payment.reverse",
        "supplier_advance.post",
        "supplier_advance.adjust",
        "reports.view_financial",
        "sales.view", "sales.invoice", "sales.payment",
    },
    "Data entry operator": {"customer.view", "customer.create", "customer.edit"},
    "Auditor viewer": {
        "reports.view_financial", "reports.view_inventory", "supplier_rate.view", "production_log.view",
        "customer.view", "scheduled_task.view", "report.supplier_rate", "report.production_log",
        "report.customer_master", "report.scheduled_task",
        "sales.view", "crm.view", "release.view",
    },
    "Sales officer": {
        "customer.view", "customer.create", "customer.edit", "customer.block", "report.customer_master",
        "sales.view", "sales.manage", "sales.invoice", "crm.view", "crm.manage",
    },
}


class Command(BaseCommand):
    help = "Create AuraFoods ERP role groups and endpoint-specific ERP permissions."

    def handle(self, *args, **options):
        content_type = ContentType.objects.get_for_model(SupplierLedgerEntry)
        permissions = {}
        for codename in ERP_PERMISSION_CODENAMES:
            permission, _ = Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": f"ERP {codename}"},
            )
            permissions[codename] = permission
        for role_name in ROLE_NAMES:
            group, _ = Group.objects.get_or_create(name=role_name)
            group.permissions.remove(*permissions.values())
            group.permissions.add(*(permissions[codename] for codename in ROLE_PERMISSION_MAP[role_name]))
        self.stdout.write(self.style.SUCCESS("AuraFoods ERP roles and endpoint permissions are ready."))
