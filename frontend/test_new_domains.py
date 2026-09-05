from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from erp.models import CustomerDistributor, Supplier


class NewDomainConsoleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ui-user", password="test-pass")
        self.client.force_login(self.user)

    def grant(self, *codenames):
        content_type = ContentType.objects.get_for_model(Supplier)
        for codename in codenames:
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type, codename=codename, defaults={"name": codename}
            )
            self.user.user_permissions.add(permission)

    def test_new_domains_hidden_without_read_permissions(self):
        response = self.client.get("/erp/")
        self.assertNotContains(response, "Supplier Rate Agreements")
        self.assertNotContains(response, "Scheduled Maintenance")
        self.assertNotContains(response, "Total Payable")
        self.assertNotContains(response, "Advance Balance")
        self.assertNotContains(response, "Stock Value")
        self.assertNotContains(response, "Recent Invoices")
        self.assertNotContains(response, "Recent Stock Batches")
        self.assertNotContains(response, "Open GRNs")
        self.assertNotContains(response, "Near Expiry")
        self.assertNotContains(response, "Expired Stock")
        self.assertNotContains(response, "Ledger Entries")
        self.assertNotContains(response, "Open Requirements")
        self.assertNotContains(response, "Active Recipes")

    def test_new_domain_screens_visible_with_permissions(self):
        self.grant("supplier_rate.view", "production_log.view", "customer.view", "scheduled_task.view")
        response = self.client.get("/erp/")
        self.assertContains(response, "Supplier Rate Agreements")
        self.assertContains(response, "Daily / Shift Production Logs")
        self.assertContains(response, "Customer / Distributor Master")
        self.assertContains(response, "Scheduled Maintenance")

    def test_customer_filter_details_and_edit_workflow_are_frontend_accessible(self):
        CustomerDistributor.objects.create(
            code="CUS-LHE", business_name="Lahore Retail", customer_type="retailer",
            sales_channel="retail", city="Lahore",
        )
        CustomerDistributor.objects.create(
            code="CUS-KHI", business_name="Karachi Wholesale", customer_type="wholesaler",
            sales_channel="wholesale", city="Karachi",
        )
        self.grant("customer.view", "customer.edit")
        response = self.client.get("/erp/?city=Lahore")
        self.assertContains(response, "CUS-LHE")
        self.assertNotContains(response, "CUS-KHI")
        self.assertContains(response, "View details")
        self.assertContains(response, 'data-method="PATCH"')

    def test_financial_inventory_dashboard_requires_read_permissions_and_csp_has_no_inline_script(self):
        response = self.client.get("/erp/")
        self.assertNotContains(response, "<script>", html=False)
        self.grant("reports.view_financial", "reports.view_inventory")
        response = self.client.get("/erp/")
        self.assertContains(response, "Total Payable")
        self.assertContains(response, "Stock Value")

    def test_frontend_action_urls_match_drf_router_contract(self):
        script = (settings.BASE_DIR / "frontend" / "static" / "frontend" / "app.js").read_text(encoding="utf-8")
        expected_paths = (
            "/api/grns/direct_purchase/", "/inspect_quality/", "/pay_invoice/", "/adjust_advance/",
            "/issue_to_grinding/", "/complete_packing/", "/stock_adjustment/",
            "/post_opening_payable/", "/post_opening_advance/", "/post_opening/",
            "/physical_count/", "/supplier_return/",
        )
        for path in expected_paths:
            self.assertIn(path, script)
        for stale_path in (
            "/direct-purchase/", "/inspect-quality/", "/pay-invoice/", "/adjust-advance/",
            "/issue-to-grinding/", "/complete-packing/", "/stock-adjustment/",
            "/physical-count/", "/supplier-return/",
        ):
            self.assertNotIn(stale_path, script)
