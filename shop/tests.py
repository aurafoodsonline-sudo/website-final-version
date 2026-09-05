import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from io import BytesIO, StringIO
from decimal import Decimal

from django.core import mail
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from PIL import Image
from erp.models import Product as ERPProduct, StockBatch as ERPStockBatch, StockLedgerEntry as ERPStockLedgerEntry, UnitOfMeasure, Warehouse
from sales.models import CatalogVariantMapping, CustomerLedgerEntry, SalesStockReservation

from shop.models import (
    AdminActivityLog,
    BlogPost,
    Bundle,
    Category,
    ContactMessage,
    CustomerAddress,
    CustomerEmailVerification,
    CustomerPasswordReset,
    DeliveryZone,
    FAQItem,
    Order,
    OrderStatusLog,
    PaymentTransaction,
    PolicyPage,
    Product,
    ProductBatch,
    ProductVariant,
    RefundRequest,
    ReturnRequest,
    Setting,
    Shipment,
    SiteRating,
    SpiceProductProfile,
    StaffMFADevice,
    StockLedger,
    SupportTicket,
)
from shop.services.lifecycle import OrderLifecycleService
from shop.services.mfa import generate_totp_secret, totp_code
from shop.services.mfa_crypto import decrypt_totp_secret, is_encrypted_secret
from shop.services.payments import PaymentService
from shop.services.uploads import safe_uploaded_image_name, validate_uploaded_image


class ShopSecurityAndCheckoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category = Category.objects.create(name="Chili")
        self.product = Product.objects.create(
            slug="kunri-red-chili",
            name="Kunri Red Chili",
            tagline="Hot and fresh",
            price=Decimal("250.00"),
            old_price=Decimal("300.00"),
            weight="200g",
            category=self.category,
            description="Pure chili powder",
            ingredients="Red chili",
            usage="Use in curries",
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            sku="AURA-1-default",
            weight_value=Decimal("200"),
            weight_unit="g",
            price=Decimal("250.00"),
            old_price=Decimal("300.00"),
            stock_quantity=5,
        )
        unit = UnitOfMeasure.objects.create(code="EA", name="Each", unit_type="count")
        warehouse = Warehouse.objects.create(code="FG", name="Finished goods")
        self.erp_product = ERPProduct.objects.create(
            code=self.variant.sku, name=self.product.name, product_type=ERPProduct.ProductType.FINISHED,
            base_unit=unit, grammage=Decimal("200.000"), sale_price=Decimal("250.00"),
        )
        self.erp_batch = ERPStockBatch.objects.create(
            product=self.erp_product, batch_number="ERP-FG-001", batch_type=ERPStockBatch.BatchType.FINISHED,
            warehouse=warehouse, quantity_on_hand=Decimal("5.000"), unit_cost=Decimal("100.0000"),
            source_document_type="PACK", source_document_number="PACK-TEST",
            expiry_date=timezone.localdate() + timedelta(days=180),
        )
        CatalogVariantMapping.objects.create(variant=self.variant, erp_product=self.erp_product)
        Setting.objects.create(key="free_delivery_min", value="500")
        Setting.objects.create(key="delivery_charge", value="150")
        self.staff_user = User.objects.create_user(
            username="staff",
            password="SafePassword123!",
            is_staff=True,
        )
        permission_content_type = ContentType.objects.get_for_model(ERPProduct)
        for codename in ("admin.configure", "sales.payment", "sales.view"):
            permission, _ = Permission.objects.get_or_create(
                codename=codename,
                content_type=permission_content_type,
                defaults={"name": f"ERP {codename}"},
            )
            self.staff_user.user_permissions.add(permission)

    def test_anonymous_product_api_writes_are_blocked(self):
        create_response = self.client.post(
            "/store/api/products/",
            data={"name": "Hacked Product"},
            content_type="application/json",
        )
        update_response = self.client.patch(
            f"/store/api/products/{self.product.id}/",
            data=json.dumps({"name": "Tampered"}),
            content_type="application/json",
        )
        delete_response = self.client.delete(f"/store/api/products/{self.product.id}/")

        self.assertIn(create_response.status_code, {401, 403})
        self.assertIn(update_response.status_code, {401, 403})
        self.assertIn(delete_response.status_code, {401, 403})

    def test_variant_display_weight_preserves_significant_zeros(self):
        self.assertEqual(self.variant.display_weight, "200g")

    @override_settings(ADMIN_LOGIN_FAILURE_LIMIT=2, ADMIN_LOGIN_LOCKOUT_SECONDS=60)
    def test_admin_login_failures_are_logged_and_locked(self):
        cache.clear()
        first = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "wrong"},
            REMOTE_ADDR="10.10.10.10",
        )
        second = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "wrong"},
            REMOTE_ADDR="10.10.10.10",
        )
        locked = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "SafePassword123!"},
            REMOTE_ADDR="10.10.10.10",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(
            AdminActivityLog.objects.filter(action="admin_login_failure").count(),
            2,
        )
        self.assertTrue(AdminActivityLog.objects.filter(action="admin_login_locked").exists())
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="admin_login_failure",
                severity=AdminActivityLog.SEVERITY_WARNING,
            ).exists()
        )
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="admin_login_locked",
                severity=AdminActivityLog.SEVERITY_CRITICAL,
            ).exists()
        )

    def test_successful_admin_login_creates_security_log(self):
        response = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "SafePassword123!"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AdminActivityLog.objects.filter(action="admin_login_success").exists())

    @override_settings(STAFF_MFA_REQUIRED=True)
    def test_staff_login_requires_and_accepts_totp(self):
        cache.clear()
        secret = generate_totp_secret()
        device = StaffMFADevice.objects.create(user=self.staff_user, secret=secret, confirmed=True)
        device.refresh_from_db()

        missing = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "SafePassword123!"},
        )
        valid = self.client.post(
            "/admin/login/",
            {
                "username": "staff",
                "password": "SafePassword123!",
                "mfa_token": totp_code(secret),
            },
        )

        self.assertEqual(missing.status_code, 401)
        self.assertContains(missing, "Authenticator Code", status_code=401)
        self.assertEqual(valid.status_code, 302)
        self.assertNotEqual(device.secret, secret)
        self.assertTrue(is_encrypted_secret(device.secret))
        self.assertEqual(decrypt_totp_secret(device.secret), secret)
        self.assertTrue(AdminActivityLog.objects.filter(action="mfa_login_failure").exists())
        self.assertTrue(AdminActivityLog.objects.filter(action="mfa_login_success").exists())

    @override_settings(STAFF_MFA_REQUIRED=True)
    def test_staff_login_without_enrolled_mfa_device_is_blocked(self):
        response = self.client.post(
            "/admin/login/",
            {"username": "staff", "password": "SafePassword123!"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="mfa_missing_device",
                severity=AdminActivityLog.SEVERITY_CRITICAL,
            ).exists()
        )

    def test_policy_pages_are_routed_and_linked(self):
        PolicyPage.objects.create(
            title="Privacy Policy",
            slug="privacy-policy",
            page_type=PolicyPage.TYPE_PRIVACY,
            content="Configured privacy text.",
            requires_checkout_visibility=True,
        )

        policy_response = self.client.get("/policies/privacy-policy/")
        footer_response = self.client.get("/")
        checkout_response = self.client.get("/checkout/")
        fallback_response = self.client.get("/policies/allergen-disclosure/")

        self.assertEqual(policy_response.status_code, 200)
        self.assertContains(policy_response, "Configured privacy text.")
        self.assertContains(footer_response, "/policies/privacy-policy/")
        self.assertContains(checkout_response, "/policies/privacy-policy/")
        self.assertContains(checkout_response, "/policies/terms-and-conditions/")
        self.assertEqual(fallback_response.status_code, 200)
        self.assertContains(fallback_response, "Allergen")

    def test_rating_requires_post_csrf_and_throttles_duplicates(self):
        csrf_client = Client(enforce_csrf_checks=True)
        get_response = csrf_client.get("/site-rating/?rating=5")
        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(SiteRating.objects.count(), 0)

        csrf_client.get("/")
        csrf_token = csrf_client.cookies["csrftoken"].value
        created = csrf_client.post(
            "/site-rating/",
            {"rating": "5"},
            HTTP_X_CSRFTOKEN=csrf_token,
            REMOTE_ADDR="10.20.30.40",
        )
        duplicate = csrf_client.post(
            "/site-rating/",
            {"rating": "4"},
            HTTP_X_CSRFTOKEN=csrf_token,
            REMOTE_ADDR="10.20.30.40",
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(duplicate.status_code, 429)
        self.assertEqual(SiteRating.objects.count(), 1)

    def test_contact_validation_honeypot_and_throttle(self):
        spam = self.client.post(
            "/contact/",
            {
                "name": "Spam Bot",
                "email": "spam@example.com",
                "message": "This should be silently moderated.",
                "website": "https://spam.example",
            },
        )
        invalid = self.client.post(
            "/contact/",
            {"name": "A", "email": "bad-email", "message": "short"},
        )

        self.assertEqual(spam.status_code, 200)
        self.assertEqual(invalid.status_code, 400)
        self.assertTrue(ContactMessage.objects.filter(spam_status=ContactMessage.STATUS_SPAM).exists())

    def test_duplicate_cod_order_is_flagged_for_review(self):
        payload = {
            "fullName": "Ayesha Khan",
            "phone": "03351234567",
            "city": "Karachi",
            "address": "House 12, Street 5, Block A, Karachi",
            "payment": "cod",
            "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
        }

        first = self.client.post("/checkout/", payload)
        second = self.client.post("/checkout/", payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        first_order, second_order = Order.objects.order_by("created_at")
        self.assertFalse(first_order.suspicious_order)
        self.assertTrue(second_order.suspicious_order)
        self.assertTrue(second_order.fraud_review_required)

    def test_public_product_api_uses_minimized_serializer(self):
        response = self.client.get("/store/api/products/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()[0]
        variant = payload["variants"][0]
        self.assertIn("display_price", payload)
        self.assertNotIn("grammage_options", payload)
        self.assertNotIn("active", payload)
        self.assertNotIn("stock_quantity", variant)
        self.assertNotIn("sellable", variant)

    def test_admin_product_api_can_use_admin_fields(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/store/api/products/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()[0]
        self.assertIn("grammage_options", payload)
        self.assertIn("active", payload)

    def test_product_detail_api_keeps_public_payload_minimized(self):
        response = self.client.get(f"/store/api/product/{self.product.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("display_price", payload)
        self.assertNotIn("price", payload)
        self.assertNotIn("old_price", payload)
        self.assertNotIn("grammage_options", payload)
        self.assertNotIn("active", payload)

    def test_staff_product_detail_api_supports_admin_edit_modal_fields(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(f"/store/api/product/{self.product.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["price"], "250.00")
        self.assertEqual(payload["old_price"], "300.00")
        self.assertEqual(payload["weight"], "200g")
        self.assertIn("grammage_options", payload)
        self.assertIn("active", payload)

    def test_admin_helper_product_lists_require_staff(self):
        response = self.client.get(f"/store/api/category/{self.category.id}/products/")

        self.assertIn(response.status_code, {401, 403})

    @override_settings(CSP_REPORT_ONLY=True)
    def test_csp_report_only_header_is_present(self):
        response = self.client.get("/")

        self.assertIn("Content-Security-Policy-Report-Only", response)
        self.assertIn("default-src 'self'", response["Content-Security-Policy-Report-Only"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy-Report-Only"])
        self.assertNotIn("script-src 'self' 'unsafe-inline'", response["Content-Security-Policy-Report-Only"])

    def test_staff_product_api_write_is_allowed(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            "/store/api/products/",
            data=json.dumps(
                {
                    "slug": "staff-created-product",
                    "name": "Staff Created Product",
                    "tagline": "Created safely",
                    "price": "100.00",
                    "old_price": "120.00",
                    "weight": "100g",
                    "category": self.category.id,
                    "description": "Test product",
                    "ingredients": "Spice",
                    "usage": "Cooking",
                    "active": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Product.objects.filter(slug="staff-created-product").exists())

    def test_admin_mutation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff_user)

        missing_csrf = client.post("/admin/category/add/", {"name": "Secure Category"})
        self.assertEqual(missing_csrf.status_code, 403)

        client.get("/admin/dashboard/")
        csrf_token = client.cookies["csrftoken"].value
        valid_response = client.post(
            "/admin/category/add/",
            {"name": "Secure Category"},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(valid_response.status_code, 302)
        self.assertTrue(Category.objects.filter(name="Secure Category").exists())

    def test_admin_dashboard_dynamic_product_ui_uses_static_js_without_inline_handlers(self):
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "admin",
            "dashboard.html",
        )
        with open(template_path, encoding="utf-8-sig") as template_file:
            template_source = template_file.read()
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "static",
            "js",
            "admin.js",
        )
        with open(js_path, encoding="utf-8-sig") as js_file:
            js_source = js_file.read()

        self.assertNotIn("innerHTML", template_source)
        self.assertNotIn("onclick=", template_source)
        self.assertNotIn("onchange=", template_source)
        self.assertNotIn("onsubmit=", template_source)
        self.assertIn('src="/static/js/admin.js" defer', template_source)
        self.assertIn("appendManagedProductOption", js_source)
        self.assertIn('strong.textContent = product.name || ""', js_source)
        self.assertNotIn("innerHTML", js_source)

    def test_public_templates_do_not_use_inline_handlers_or_dynamic_html_rendering(self):
        templates_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        public_templates = [
            "base.html",
            "index.html",
            "shop.html",
            "product.html",
            "cart.html",
            "checkout.html",
            "order_confirmation.html",
            "account_login.html",
            "account_register.html",
            "account_profile.html",
            "account_password_reset.html",
            "account_password_reset_confirm.html",
            "account_verify_email.html",
            "account_order_support.html",
            "faq.html",
            "support.html",
            "track_order.html",
        ]
        for template_name in public_templates:
            with self.subTest(template=template_name):
                with open(os.path.join(templates_root, template_name), encoding="utf-8-sig") as template_file:
                    template_source = template_file.read()
                self.assertNotIn("onclick=", template_source)
                self.assertNotIn("onchange=", template_source)
                self.assertNotIn("onsubmit=", template_source)
                self.assertNotIn("innerHTML", template_source)
                if template_name != "base.html":
                    self.assertNotIn("<script", template_source)

    def test_analytics_is_consent_gated_and_config_driven(self):
        Setting.objects.create(key="analytics_measurement_id", value="G-TEST123")
        response = self.client.get("/")
        product_response = self.client.get(f"/product/{self.product.slug}/")
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )
        order.items.create(
            variant=self.variant,
            product_id=self.product.id,
            product_name=self.product.name,
            quantity=1,
            weight_option="200g",
            price=Decimal("250.00"),
            subtotal=Decimal("250.00"),
        )
        session = self.client.session
        session["recent_order_reference"] = order.reference
        session.save()
        confirmation_response = self.client.get(f"/order-confirmation/ref/{order.reference}/")
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "static",
            "js",
            "main.js",
        )
        with open(js_path, encoding="utf-8-sig") as js_file:
            js_source = js_file.read()

        self.assertContains(response, 'data-analytics-id="G-TEST123"')
        self.assertNotContains(response, "googletagmanager.com")
        self.assertIn("auraAnalyticsConsent", js_source)
        self.assertIn("Allow analytics", js_source)
        self.assertIn('analyticsEvent("view_item"', js_source)
        self.assertIn('analyticsEvent("add_to_cart"', js_source)
        self.assertIn('analyticsEvent("begin_checkout"', js_source)
        self.assertIn('analyticsEvent("purchase"', js_source)
        self.assertContains(product_response, 'data-analytics-product-view="1"')
        self.assertContains(confirmation_response, 'data-analytics-purchase="1"')
        self.assertNotContains(confirmation_response, "data-order-reference")
        self.assertNotIn("order_reference", js_source)
        self.assertNotIn("customer_email", js_source)
        self.assertNotIn("customer_phone", js_source)
        self.assertNotIn("customer_address", js_source)

    def test_release_smoke_check_command_covers_public_and_admin_entry_routes(self):
        output = StringIO()

        call_command("release_smoke_check", "--strict", stdout=output)
        report = output.getvalue()

        self.assertIn("home: / status=200", report)
        self.assertIn("product detail:", report)
        self.assertIn("category detail:", report)
        self.assertIn("admin login: /admin/login/ status=200", report)
        self.assertIn("Release smoke checks passed.", report)

    def test_enroll_staff_mfa_command_creates_confirmed_device_and_audit_log(self):
        output = StringIO()

        call_command("enroll_staff_mfa", self.staff_user.username, stdout=output)

        device = StaffMFADevice.objects.get(user=self.staff_user)
        self.assertTrue(device.confirmed)
        self.assertTrue(is_encrypted_secret(device.secret))
        self.assertIn("Secret: [redacted]", output.getvalue())
        self.assertIn("Provisioning URI: [redacted]", output.getvalue())
        self.assertNotIn("otpauth://totp/", output.getvalue())
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="mfa_device_enrolled",
                object_id=str(device.id),
                severity=AdminActivityLog.SEVERITY_WARNING,
            ).exists()
        )

    def test_enroll_staff_mfa_command_rotation_replaces_existing_device(self):
        old_device = StaffMFADevice.objects.create(
            user=self.staff_user,
            name="Old phone",
            secret=generate_totp_secret(),
            confirmed=True,
        )
        output = StringIO()

        call_command("enroll_staff_mfa", self.staff_user.username, "--rotate", stdout=output)

        self.assertFalse(StaffMFADevice.objects.filter(id=old_device.id).exists())
        device = StaffMFADevice.objects.get(user=self.staff_user)
        self.assertTrue(device.confirmed)
        self.assertIn("rotated", output.getvalue().lower())
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="mfa_device_enrolled",
                object_id=str(device.id),
                severity=AdminActivityLog.SEVERITY_CRITICAL,
            ).exists()
        )

    def test_enroll_staff_mfa_show_secret_requires_explicit_flag(self):
        output = StringIO()

        call_command("enroll_staff_mfa", self.staff_user.username, "--show-secret", stdout=output)

        self.assertIn("Sensitive one-time enrollment material follows", output.getvalue())
        self.assertIn("Provisioning URI: otpauth://totp/", output.getvalue())

    def test_custom_admin_product_category_settings_and_password_changes_are_logged(self):
        self.client.force_login(self.staff_user)

        self.client.post(
            "/admin/product/add/",
            {
                "name": "Logged Product",
                "tagline": "Audit",
                "price": "111.00",
                "old_price": "125.00",
                "weight": "100g",
                "category_id": self.category.id,
                "description": "Audit product",
                "ingredients": "Spice",
                "usage": "Cooking",
            },
            REMOTE_ADDR="10.10.10.10",
            HTTP_USER_AGENT="AuditTest/1.0",
        )
        product = Product.objects.get(name="Logged Product")
        self.client.post(f"/admin/product/delete/{product.id}/")
        self.client.post("/admin/category/add/", {"name": "Logged Category"})
        self.client.post("/admin/settings/save/", {"setting_site_name": "Aura Audit"})
        self.client.post(
            "/admin/change-password/",
            {"current": "SafePassword123!", "newpass": "NewSafePassword123!"},
        )

        product_log = AdminActivityLog.objects.get(action="product_add", object_id=str(product.id))
        self.assertEqual(product_log.ip_address, "10.10.10.10")
        self.assertEqual(product_log.user_agent, "AuditTest/1.0")
        self.assertEqual(product_log.severity, AdminActivityLog.SEVERITY_CRITICAL)
        self.assertTrue(AdminActivityLog.objects.filter(action="product_delete").exists())
        self.assertTrue(AdminActivityLog.objects.filter(action="category_add").exists())
        self.assertTrue(AdminActivityLog.objects.filter(action="settings_update", severity=AdminActivityLog.SEVERITY_CRITICAL).exists())
        self.assertTrue(AdminActivityLog.objects.filter(action="password_change", severity=AdminActivityLog.SEVERITY_CRITICAL).exists())

    @override_settings(MEDIA_UPLOADS_ENABLED=True)
    def test_custom_admin_image_uploads_are_logged_without_secret_material(self):
        self.client.force_login(self.staff_user)
        bundle = Bundle.objects.create(name="Audit Bundle", items=self.product.name, price="100.00", old_price="120.00")
        post = BlogPost.objects.create(
            slug="audit-post",
            title="Audit Post",
            category="Audit",
            read_time="2 min",
            excerpt="Audit excerpt",
            content="Audit content",
        )

        def upload(name):
            buffer = BytesIO()
            Image.new("RGB", (8, 8), color=(180, 30, 30)).save(buffer, format="PNG")
            return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

        self.client.post(f"/admin/product/image/{self.product.id}/", {"file": upload("product.png")})
        self.client.post(f"/admin/bundle/image/{bundle.id}/", {"file": upload("bundle.png")})
        self.client.post(f"/admin/blog/image/{post.id}/", {"file": upload("blog.png")})

        for action in ("product_image_upload", "bundle_image_upload", "blog_image_upload"):
            log = AdminActivityLog.objects.get(action=action)
            self.assertEqual(log.severity, AdminActivityLog.SEVERITY_WARNING)
            self.assertNotIn("secret", json.dumps(log.new_value or {}).lower())

    def test_checkout_recalculates_prices_from_variant(self):
        idempotency_key = "checkout-123"
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "idempotency_key": idempotency_key,
                "cart_data": json.dumps(
                    [
                        {
                            "variant_id": self.variant.id,
                            "qty": 2,
                            "price": "1.00",
                            "name": "Fake Name",
                            "total": "2.00",
                        }
                    ]
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        item = order.items.get()
        self.assertIn(f"/order-confirmation/ref/{order.reference}/", response.url)
        self.assertEqual(order.subtotal, Decimal("500.00"))
        self.assertEqual(order.delivery_charge, Decimal("0.00"))
        self.assertEqual(order.total, Decimal("500.00"))
        self.assertEqual(item.price, Decimal("250.00"))
        self.assertEqual(item.product_name, self.product.name)
        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))
        self.assertEqual(order.payment_status, Order.PAYMENT_UNPAID)
        transaction = order.payment_transactions.get()
        self.assertEqual(transaction.provider, PaymentTransaction.PROVIDER_COD)
        self.assertEqual(transaction.status, PaymentTransaction.STATUS_PENDING)
        self.assertEqual(transaction.amount, order.total)
        self.assertTrue(SalesStockReservation.objects.filter(batch=self.erp_batch, quantity=2, status="active").exists())

    def test_customer_account_registration_login_and_order_history(self):
        mail.outbox = []
        register = self.client.post(
            "/account/register/",
            {
                "username": "customer1",
                "email": "customer1@example.com",
                "password": "CustomerSafe123!",
                "confirm_password": "CustomerSafe123!",
            },
        )
        profile = self.client.get("/account/")

        self.assertEqual(register.status_code, 302)
        self.assertEqual(profile.status_code, 200)
        self.assertTrue(User.objects.filter(username="customer1", is_staff=False).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/account/verify-email/", mail.outbox[0].body)

    def test_logged_in_customer_checkout_links_order_and_saved_address(self):
        customer = User.objects.create_user(
            username="customer2",
            email="customer2@example.com",
            password="CustomerSafe123!",
        )
        self.client.force_login(customer)

        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Customer Two",
                "email": "customer2@example.com",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "save_address": "1",
                "idempotency_key": "customer-checkout-1",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )

        order = Order.objects.get(idempotency_key="customer-checkout-1")
        profile = self.client.get("/account/")
        other = User.objects.create_user(username="other-customer", password="CustomerSafe123!")
        self.client.force_login(other)
        other_profile = self.client.get("/account/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.customer_user, customer)
        self.assertEqual(order.email, "customer2@example.com")
        self.assertTrue(CustomerAddress.objects.filter(user=customer, is_default=True).exists())
        self.assertContains(profile, order.reference)
        self.assertNotContains(other_profile, order.reference)

    def test_customer_email_verification_and_password_reset_tokens_are_hashed(self):
        customer = User.objects.create_user(
            username="customer-reset",
            email="reset@example.com",
            password="CustomerSafe123!",
        )
        verification, verify_token = CustomerEmailVerification.create_for_user(customer)
        reset, reset_token = CustomerPasswordReset.create_for_user(customer)

        self.assertNotIn(verify_token, verification.token_hash)
        self.assertNotIn(reset_token, reset.token_hash)

        verify_response = self.client.get(f"/account/verify-email/{verify_token}/")
        reset_get = self.client.get(f"/account/password-reset/{reset_token}/")
        reset_post = self.client.post(
            f"/account/password-reset/{reset_token}/",
            {
                "password": "NewCustomerSafe123!",
                "confirm_password": "NewCustomerSafe123!",
            },
        )
        customer.refresh_from_db()
        reset.refresh_from_db()

        self.assertEqual(verify_response.status_code, 200)
        self.assertEqual(reset_get.status_code, 200)
        self.assertEqual(reset_post.status_code, 302)
        self.assertTrue(customer.check_password("NewCustomerSafe123!"))
        self.assertIsNotNone(reset.used_at)

    def test_password_reset_request_is_generic_and_creates_token_for_customer_email(self):
        mail.outbox = []
        User.objects.create_user(
            username="request-reset",
            email="request-reset@example.com",
            password="CustomerSafe123!",
        )
        response = self.client.post(
            "/account/password-reset/",
            {"email": "request-reset@example.com"},
        )
        missing = self.client.post(
            "/account/password-reset/",
            {"email": "not-registered@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(CustomerPasswordReset.objects.count(), 1)
        self.assertContains(response, "If that email is registered")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/account/password-reset/", mail.outbox[0].body)

    def test_zone_based_checkout_creates_shipment_and_tracking_view(self):
        DeliveryZone.objects.create(
            name="Karachi Metro",
            city_pattern="karachi",
            base_charge=Decimal("99.00"),
            free_delivery_min=Decimal("1000.00"),
            estimated_days_min=1,
            estimated_days_max=2,
            courier_hint="Aura Rider",
        )
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Shipping Customer",
                "email": "ship@example.com",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "idempotency_key": "shipping-checkout-1",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )
        order = Order.objects.get(idempotency_key="shipping-checkout-1")
        shipment = order.shipment
        tracking = self.client.post(
            "/track-order/",
            {"reference": order.reference, "phone": "0335 1234567"},
        )
        partial_phone = self.client.post(
            "/track-order/", {"reference": order.reference, "phone": "4567"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.delivery_charge, Decimal("99.00"))
        self.assertEqual(shipment.zone.name, "Karachi Metro")
        self.assertEqual(shipment.courier_name, "Aura Rider")
        self.assertContains(tracking, order.reference)
        self.assertContains(tracking, "Pending")
        self.assertEqual(partial_phone.status_code, 404)

    def test_duplicate_cart_lines_cannot_overcommit_erp_stock(self):
        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [
                {"variant_id": self.variant.id, "qty": 3},
                {"variant_id": self.variant.id, "qty": 3},
            ]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "insufficient_stock")

    def test_cod_delivery_updates_shipment_and_reconciles_customer_ledger(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "COD Customer", "email": "cod@example.com", "phone": "03351234567",
                "city": "Karachi", "address": "House 12, Street 5, Karachi", "payment": "cod",
                "idempotency_key": "cod-delivery-1",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(idempotency_key="cod-delivery-1")
        for status in (Order.STATUS_CONFIRMED, Order.STATUS_PROCESSING, Order.STATUS_SHIPPED, Order.STATUS_DELIVERED):
            order = OrderLifecycleService.transition_order(order, status, actor=self.staff_user)

        order.refresh_from_db()
        order.shipment.refresh_from_db()
        transaction = order.payment_transactions.get(provider=PaymentTransaction.PROVIDER_COD)
        invoice = order.sales_record.invoice
        self.assertEqual(order.status, Order.STATUS_DELIVERED)
        self.assertEqual(order.shipment.status, Shipment.STATUS_DELIVERED)
        self.assertIsNotNone(order.shipment.shipped_at)
        self.assertIsNotNone(order.shipment.delivered_at)
        self.assertEqual(transaction.status, PaymentTransaction.STATUS_VERIFIED)
        self.assertEqual(invoice.balance, Decimal("0.00"))
        self.assertEqual(CustomerLedgerEntry.objects.filter(invoice=invoice).count(), 2)

    def test_default_delivery_zone_applies_to_unmatched_city(self):
        DeliveryZone.objects.create(
            name="Rest of Pakistan",
            city_pattern="",
            base_charge=Decimal("300.00"),
            free_delivery_min=Decimal("3000.00"),
            estimated_days_min=3,
            estimated_days_max=6,
            courier_hint="National courier",
            sort_order=99,
        )
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Remote Customer",
                "email": "remote@example.com",
                "phone": "03351234567",
                "city": "Sukkur",
                "address": "House 12, Street 5, Sukkur",
                "payment": "cod",
                "idempotency_key": "fallback-zone-checkout-1",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )
        order = Order.objects.get(idempotency_key="fallback-zone-checkout-1")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.delivery_charge, Decimal("300.00"))
        self.assertEqual(order.shipment.zone.name, "Rest of Pakistan")

    def test_customer_order_support_creates_ticket_return_and_refund_requests(self):
        customer = User.objects.create_user(
            username="support-customer",
            email="support-customer@example.com",
            password="CustomerSafe123!",
        )
        order = Order.objects.create(
            customer_user=customer,
            customer_name="Support Customer",
            email="support-customer@example.com",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
            status=Order.STATUS_DELIVERED,
        )
        PaymentTransaction.objects.create(
            order=order, provider="manual", status=PaymentTransaction.STATUS_VERIFIED, amount=order.total
        )
        self.client.force_login(customer)
        return_response = self.client.post(
            f"/account/orders/{order.reference}/support/",
            {"category": "return", "message": "The parcel arrived damaged and unopened."},
        )
        refund_response = self.client.post(
            f"/account/orders/{order.reference}/support/",
            {"category": "refund", "message": "Please review refund eligibility."},
        )
        other = User.objects.create_user(username="other-support", password="CustomerSafe123!")
        self.client.force_login(other)
        blocked = self.client.post(
            f"/account/orders/{order.reference}/support/",
            {"category": "return", "message": "I should not access this order."},
        )

        self.assertEqual(return_response.status_code, 302)
        self.assertEqual(refund_response.status_code, 302)
        self.assertEqual(blocked.status_code, 404)
        self.assertTrue(SupportTicket.objects.filter(order=order, user=customer).exists())
        self.assertTrue(ReturnRequest.objects.filter(order=order).exists())
        self.assertTrue(RefundRequest.objects.filter(order=order, amount=order.total).exists())

    def test_support_and_faq_pages_create_public_support_ticket(self):
        FAQItem.objects.create(
            question="How long does delivery take?",
            answer="Delivery estimates are shown with order tracking.",
            active=True,
        )
        faq = self.client.get("/faq/")
        support = self.client.post(
            "/support/",
            {
                "name": "Public Customer",
                "email": "public@example.com",
                "phone": "03351234567",
                "category": "complaint",
                "subject": "Packaging issue",
                "message": "The packaging needs review for my area.",
            },
        )

        self.assertContains(faq, "How long does delivery take?")
        self.assertEqual(support.status_code, 200)
        self.assertTrue(SupportTicket.objects.filter(email="public@example.com", category=SupportTicket.CATEGORY_COMPLAINT).exists())

    def test_public_order_reference_hides_private_details_without_session_match(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )
        order.items.create(
            variant=self.variant,
            product_id=self.product.id,
            product_name=self.product.name,
            quantity=1,
            weight_option="200g",
            price=Decimal("250.00"),
            subtotal=Decimal("250.00"),
        )

        response = Client().get(f"/order-confirmation/ref/{order.reference}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.reference)
        self.assertContains(response, "For privacy")
        self.assertNotContains(response, "Ayesha Khan")
        self.assertNotContains(response, "03351234567")
        self.assertNotContains(response, "House 12")
        self.assertNotContains(response, self.product.name)
        self.assertNotContains(response, "Payment")
        self.assertNotContains(response, "Rs.400")

    def test_order_reference_shows_private_details_for_matching_session_or_staff(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )
        order.items.create(
            variant=self.variant,
            product_id=self.product.id,
            product_name=self.product.name,
            quantity=1,
            weight_option="200g",
            price=Decimal("250.00"),
            subtotal=Decimal("250.00"),
        )
        session = self.client.session
        session["recent_order_reference"] = order.reference
        session.save()

        session_response = self.client.get(f"/order-confirmation/ref/{order.reference}/")
        staff_client = Client()
        staff_client.force_login(self.staff_user)
        staff_response = staff_client.get(f"/order-confirmation/ref/{order.reference}/")

        self.assertContains(session_response, "Ayesha Khan")
        self.assertContains(session_response, self.product.name)
        self.assertContains(staff_response, "03351234567")

    def test_cart_quote_uses_server_prices(self):
        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps(
                {
                    "items": [
                        {
                            "variant_id": self.variant.id,
                            "qty": 2,
                            "price": "1.00",
                            "name": "Fake Name",
                            "total": "2.00",
                        }
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subtotal"], "500.00")
        self.assertEqual(payload["grand_total"], "500.00")
        self.assertEqual(payload["lines"][0]["unit_price"], "250.00")
        self.assertEqual(payload["lines"][0]["product_name"], self.product.name)

    def test_cart_quote_post_requires_csrf_when_enforced(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_cart_quote_rejects_invalid_variant_id(self):
        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": 999999, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_checkout_invalid_variant_id_does_not_crash(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": 999999, "qty": 1}]),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no longer available")
        self.assertEqual(Order.objects.count(), 0)

    def test_inactive_variant_cannot_be_quoted_or_checked_out(self):
        self.variant.active = False
        self.variant.save(update_fields=["active"])

        quote_response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 1}]}),
            content_type="application/json",
        )
        checkout_response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )

        self.assertEqual(quote_response.status_code, 400)
        self.assertFalse(quote_response.json()["ok"])
        self.assertEqual(checkout_response.status_code, 200)
        self.assertContains(checkout_response, "no longer available")
        self.assertEqual(Order.objects.count(), 0)

    def test_deleted_variant_is_handled_safely(self):
        variant_id = self.variant.id
        self.variant.delete()

        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": variant_id, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_zero_and_negative_quantities_are_rejected(self):
        for qty in (0, -1):
            response = self.client.post(
                "/api/cart/quote/",
                data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": qty}]}),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["errors"][0]["code"], "invalid_quantity")

    def test_zero_quantity_checkout_is_rejected(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 0}]),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "quantity of at least 1")
        self.assertEqual(Order.objects.count(), 0)

    def test_quantity_above_stock_is_rejected_by_quote_endpoint(self):
        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 99}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "insufficient_stock")

    def test_out_of_stock_variant_cannot_be_checked_out(self):
        self.erp_batch.quantity_on_hand = 0
        self.erp_batch.save(update_fields=["quantity_on_hand"])

        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "out of stock", status_code=200)
        self.assertEqual(Order.objects.count(), 0)

    def test_duplicate_checkout_submission_returns_same_order(self):
        payload = {
            "fullName": "Ayesha Khan",
            "phone": "03351234567",
            "city": "Karachi",
            "address": "House 12, Street 5, Block A, Karachi",
            "payment": "cod",
            "idempotency_key": "duplicate-submit-1",
            "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
        }

        first = self.client.post("/checkout/", payload)
        second = self.client.post("/checkout/", payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))
        self.assertEqual(SalesStockReservation.objects.filter(status="active").count(), 1)

    def test_public_sequential_confirmation_url_returns_404(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )

        response = self.client.get(f"/order-confirmation/{order.id}/")

        self.assertEqual(response.status_code, 404)

    def test_manual_payment_is_awaiting_verification_not_paid(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "jazzcash",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        transaction = order.payment_transactions.get()
        self.assertEqual(order.payment_status, Order.PAYMENT_AWAITING_VERIFICATION)
        self.assertEqual(transaction.status, PaymentTransaction.STATUS_AWAITING_VERIFICATION)

    def test_non_staff_cannot_verify_manual_payment(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="jazzcash",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )
        transaction = PaymentService.create_for_order(order, "jazzcash")
        user = User.objects.create_user(username="customer", password="SafePassword123!")

        with self.assertRaises(PermissionDenied):
            PaymentService.verify_manual_payment(transaction, user)

    def test_staff_can_verify_manual_payment_for_matching_amount(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="easypaisa",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )
        transaction = PaymentService.create_for_order(order, "easypaisa")

        PaymentService.verify_manual_payment(transaction, self.staff_user, amount="400.00")

        transaction.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(transaction.status, PaymentTransaction.STATUS_VERIFIED)
        self.assertEqual(order.payment_status, Order.PAYMENT_PAID)
        self.assertTrue(
            AdminActivityLog.objects.filter(
                action="payment_verified",
                severity=AdminActivityLog.SEVERITY_WARNING,
            ).exists()
        )

        with self.assertRaises(ValidationError):
            PaymentService.verify_manual_payment(transaction, self.staff_user, amount="400.00")

    def test_staff_without_sales_payment_permission_cannot_verify(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan", phone="03351234567", city="Karachi",
            address="Street 1", payment_method="easypaisa",
            subtotal=Decimal("250.00"), delivery_charge=Decimal("150.00"), total=Decimal("400.00"),
        )
        transaction = PaymentService.create_for_order(order, "easypaisa")
        unprivileged_staff = User.objects.create_user(username="limited-staff", is_staff=True)
        with self.assertRaises(PermissionDenied):
            PaymentService.verify_manual_payment(transaction, unprivileged_staff, amount="400.00")

    def test_invalid_payment_provider_is_rejected(self):
        with self.assertRaises(ValidationError):
            PaymentService.create_for_order(
                Order(
                    customer_name="Ayesha Khan",
                    phone="03351234567",
                    city="Karachi",
                    address="House 12, Street 5, Block A, Karachi",
                    subtotal=Decimal("250.00"),
                    delivery_charge=Decimal("150.00"),
                    total=Decimal("400.00"),
                ),
                "fakepay",
            )

    def test_expired_batch_cannot_be_sold(self):
        self.erp_batch.expiry_date = timezone.localdate() - timedelta(days=1)
        self.erp_batch.save(update_fields=["expiry_date"])

        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "out_of_stock")

    def test_blocked_batch_cannot_be_sold(self):
        self.erp_batch.is_blocked = True
        self.erp_batch.stock_state = ERPStockBatch.StockState.BLOCKED
        self.erp_batch.save(update_fields=["is_blocked", "stock_state"])

        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_active_batch_deducts_and_creates_ledger(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 2}]),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))
        self.assertTrue(SalesStockReservation.objects.filter(batch=self.erp_batch, quantity=2).exists())
        self.assertFalse(ERPStockLedgerEntry.objects.filter(source_document_type="SALES_DISPATCH").exists())

    def test_cart_quote_reports_batch_available_quantity(self):
        self.erp_batch.quantity_on_hand = Decimal("2.000")
        self.erp_batch.save(update_fields=["quantity_on_hand"])

        response = self.client.post(
            "/api/cart/quote/",
            data=json.dumps({"items": [{"variant_id": self.variant.id, "qty": 1}]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.json()["lines"][0]["available_quantity"]), Decimal("2.000"))

    def test_inventory_report_command_lists_operational_stock_sections(self):
        self.erp_batch.expiry_date = timezone.localdate() + timedelta(days=7)
        self.erp_batch.save(update_fields=["expiry_date"])
        expired = ERPStockBatch.objects.create(
            product=self.erp_product, batch_number="EXPIRED-001",
            batch_type=ERPStockBatch.BatchType.FINISHED,
            warehouse=self.erp_batch.warehouse, quantity_on_hand=Decimal("1.000"),
            unit_cost=Decimal("100.0000"), source_document_type="PACK",
            source_document_number="PACK-EXPIRED", expiry_date=timezone.localdate() - timedelta(days=1),
        )
        ERPStockLedgerEntry.objects.create(
            product=self.erp_product, batch=self.erp_batch, warehouse=self.erp_batch.warehouse,
            direction=ERPStockLedgerEntry.Direction.IN, quantity=Decimal("2.000"),
            source_document_type="inventory_test", source_document_number="1",
        )
        output = StringIO()

        call_command("inventory_report", "--expiry-days=14", "--movement-limit=5", stdout=output)
        report = output.getvalue()

        self.assertIn("Aura Foods ERP Finished-Goods Inventory Report", report)
        self.assertIn("LOW STOCK FINISHED SKUS", report)
        self.assertIn("EXPIRING ERP BATCHES (1)", report)
        self.assertIn(self.erp_batch.batch_number, report)
        self.assertIn("EXPIRED ERP BATCHES (1)", report)
        self.assertIn(expired.batch_number, report)
        self.assertIn("RECENT ERP STOCK MOVEMENTS (1)", report)
        self.assertIn("inventory_test:1", report)

    def test_cancellation_restores_batch_quantity_once(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 2}]),
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))

        OrderLifecycleService.cancel_order(order, actor=self.staff_user, note="Customer requested")
        OrderLifecycleService.cancel_order(Order.objects.get(id=order.id), actor=self.staff_user, note="Retry")

        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))
        self.assertEqual(SalesStockReservation.objects.get().status, "released")
        self.assertFalse(ERPStockLedgerEntry.objects.filter(source_document_type="SALES_DISPATCH").exists())

    def test_cancellation_restores_stock_once_and_logs_status(self):
        response = self.client.post(
            "/checkout/",
            {
                "fullName": "Ayesha Khan",
                "phone": "03351234567",
                "city": "Karachi",
                "address": "House 12, Street 5, Block A, Karachi",
                "payment": "cod",
                "cart_data": json.dumps([{"variant_id": self.variant.id, "qty": 1}]),
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()

        OrderLifecycleService.cancel_order(order, actor=self.staff_user, note="Customer requested")
        OrderLifecycleService.cancel_order(Order.objects.get(id=order.id), actor=self.staff_user, note="Retry")

        self.erp_batch.refresh_from_db()
        self.assertEqual(self.erp_batch.quantity_on_hand, Decimal("5.000"))
        self.assertEqual(SalesStockReservation.objects.get().status, "released")
        self.assertTrue(OrderStatusLog.objects.filter(order=order, new_status=Order.STATUS_CANCELLED).exists())

    def test_delivered_order_cannot_be_cancelled_directly(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
            status=Order.STATUS_DELIVERED,
        )

        with self.assertRaises(ValidationError):
            OrderLifecycleService.cancel_order(order, actor=self.staff_user)

    def test_refund_cannot_exceed_order_total(self):
        order = Order.objects.create(
            customer_name="Ayesha Khan",
            phone="03351234567",
            city="Karachi",
            address="House 12, Street 5, Block A, Karachi",
            payment_method="cod",
            subtotal=Decimal("250.00"),
            delivery_charge=Decimal("150.00"),
            total=Decimal("400.00"),
        )

        with self.assertRaises(ValidationError):
            OrderLifecycleService.request_refund(order, Decimal("401.00"), "Too much")

    def test_product_slug_url_and_legacy_redirect(self):
        slug_response = self.client.get(f"/product/{self.product.slug}/")
        legacy_response = self.client.get(f"/product/{self.product.id}/")

        self.assertEqual(slug_response.status_code, 200)
        self.assertEqual(legacy_response.status_code, 301)
        self.assertEqual(legacy_response["Location"], f"/product/{self.product.slug}/")

    def test_product_page_does_not_show_hard_coded_reviews_without_ratings(self):
        response = self.client.get(f"/product/{self.product.slug}/")

        self.assertNotContains(response, "124 reviews")
        self.assertNotContains(response, "aggregateRating")
        self.assertNotContains(response, "reviewCount")

    def test_admin_edit_does_not_override_canonical_variant_price(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            f"/admin/product/edit/{self.product.id}/",
            {
                "name": self.product.name,
                "tagline": self.product.tagline,
                "price": "1.00",
                "old_price": "2.00",
                "weight": "200g",
                "category_id": self.category.id,
                "description": self.product.description,
                "ingredients": self.product.ingredients,
                "usage": self.product.usage,
                "gram_200": "1.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.price, Decimal("250.00"))

    def test_category_slug_url_and_sitemap_use_canonical_urls(self):
        category_response = self.client.get(f"/category/{self.category.name.lower()}/")
        sitemap_response = self.client.get("/sitemap.xml/")

        self.assertEqual(category_response.status_code, 200)
        self.assertContains(sitemap_response, f"/product/{self.product.slug}/")
        self.assertNotContains(sitemap_response, f"/product/{self.product.id}")

    def test_spice_profile_renders_and_claim_requires_approval(self):
        SpiceProductProfile.objects.create(
            product=self.product,
            spice_form=SpiceProductProfile.FORM_GROUND,
            organic_claim=True,
            premium_claim=True,
            heat_level=SpiceProductProfile.HEAT_HOT,
            allergen_statement="Packed in a facility that handles sesame.",
            storage_instructions="Store in an airtight jar.",
            usage_instructions="Use in curries.",
        )

        response = self.client.get(f"/product/{self.product.slug}/")

        self.assertContains(response, "Allergen disclosure")
        self.assertContains(response, "Store in an airtight jar.")
        self.assertNotContains(response, "Organic claim verified")


class UploadValidationTests(TestCase):
    def make_image(self, fmt="JPEG", name="spice.jpg", content_type="image/jpeg"):
        buffer = BytesIO()
        Image.new("RGB", (8, 8), color=(180, 30, 30)).save(buffer, format=fmt)
        return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)

    @override_settings(MEDIA_UPLOADS_ENABLED=True, AURAFOODS_MAX_UPLOAD_BYTES=1024 * 1024)
    def test_valid_jpeg_png_and_webp_are_accepted(self):
        for fmt, name, content_type in (
            ("JPEG", "spice.jpg", "image/jpeg"),
            ("PNG", "spice.png", "image/png"),
            ("WEBP", "spice.webp", "image/webp"),
        ):
            self.assertTrue(validate_uploaded_image(self.make_image(fmt, name, content_type)))

    @override_settings(MEDIA_UPLOADS_ENABLED=True, AURAFOODS_MAX_UPLOAD_BYTES=1024 * 1024)
    def test_fake_image_svg_and_oversized_file_are_rejected(self):
        fake = SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg")
        svg = SimpleUploadedFile("bad.svg", b"<svg></svg>", content_type="image/svg+xml")
        big = SimpleUploadedFile("big.jpg", b"x" * 2048, content_type="image/jpeg")

        with self.assertRaises(ValidationError):
            validate_uploaded_image(fake)
        with self.assertRaises(ValidationError):
            validate_uploaded_image(svg)
        with override_settings(AURAFOODS_MAX_UPLOAD_BYTES=100):
            with self.assertRaises(ValidationError):
                validate_uploaded_image(big)

    def test_path_traversal_filename_is_neutralized(self):
        name = safe_uploaded_image_name("../../secret.jpg", "../products")

        self.assertNotIn("..", name)
        self.assertTrue(name.startswith("products/"))


class SettingsHardeningTests(TestCase):
    def test_public_settings_api_and_home_exclude_unapproved_keys(self):
        Setting.objects.create(key="site_name", value="Aura Public")
        Setting.objects.create(key="private_signing_secret", value="do-not-disclose")

        api_response = self.client.get("/api/settings/")
        home_response = self.client.get("/")

        self.assertEqual(api_response.status_code, 200)
        self.assertContains(api_response, "Aura Public")
        self.assertNotContains(api_response, "private_signing_secret")
        self.assertNotContains(api_response, "do-not-disclose")
        self.assertNotContains(home_response, "do-not-disclose")

    def test_anonymous_user_cannot_read_erp_or_sales_data(self):
        for url in ("/api/stock-batches/", "/api/sales/invoices/", "/api/reports/raw-stock/"):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, {401, 403})

    def test_production_without_allowed_hosts_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                "DATABASE_URL": "postgres://aura:aura@localhost:5432/aurafoods",
                "MFA_SECRET_ENCRYPTION_KEY": "s0f0H-WTod2GGbBDl220EItWk-_1YiivkcEk9503ZTg=",
            }
        )
        env.pop("DJANGO_ALLOWED_HOSTS", None)
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS must be set", result.stderr + result.stdout)

    def test_production_without_database_url_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                "DJANGO_ALLOWED_HOSTS": "aurafoods.pk",
            }
        )
        env.pop("DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL must be set", result.stderr + result.stdout)

    def test_production_sqlite_database_url_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                "DJANGO_ALLOWED_HOSTS": "aurafoods.pk",
                "DATABASE_URL": "sqlite:///not-production.sqlite3",
                "MFA_SECRET_ENCRYPTION_KEY": "s0f0H-WTod2GGbBDl220EItWk-_1YiivkcEk9503ZTg=",
            }
        )
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Production DATABASE_URL must not use SQLite", result.stderr + result.stdout)

    def test_production_s3_media_storage_missing_credentials_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                "DJANGO_ALLOWED_HOSTS": "aurafoods.pk",
                "DATABASE_URL": "postgres://aura:aura@localhost:5432/aurafoods",
                "MEDIA_STORAGE_BACKEND": "s3",
            }
        )
        for key in ("AWS_STORAGE_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Production S3-compatible media storage is missing", result.stderr + result.stdout)

    def test_production_staff_mfa_missing_encryption_key_fails_closed(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                "DJANGO_ALLOWED_HOSTS": "aurafoods.pk",
                "DATABASE_URL": "postgres://aura:aura@localhost:5432/aurafoods",
                "MEDIA_STORAGE_BACKEND": "s3",
                "AWS_STORAGE_BUCKET_NAME": "aura-test",
                "AWS_ACCESS_KEY_ID": "not-secret-in-test",
                "AWS_SECRET_ACCESS_KEY": "not-secret-in-test",
                "STAFF_MFA_REQUIRED": "True",
            }
        )
        env.pop("MFA_SECRET_ENCRYPTION_KEY", None)
        result = subprocess.run(
            [sys.executable, "manage.py", "check"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MFA_SECRET_ENCRYPTION_KEY must be set", result.stderr + result.stdout)

    def test_production_s3_settings_do_not_create_local_data_or_media_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = os.path.join(temp_dir, "data-root")
            media_root = os.path.join(temp_dir, "media-root")
            env = os.environ.copy()
            env.update(
                {
                    "DJANGO_DEBUG": "False",
                    "DJANGO_SECRET_KEY": "production-like-secret-key-for-tests-123456789",
                    "DJANGO_ALLOWED_HOSTS": "aurafoods.pk",
                    "DATABASE_URL": "postgres://aura:aura@localhost:5432/aurafoods",
                    "MEDIA_STORAGE_BACKEND": "s3",
                    "AWS_STORAGE_BUCKET_NAME": "aura-test",
                    "AWS_ACCESS_KEY_ID": "not-secret-in-test",
                    "AWS_SECRET_ACCESS_KEY": "not-secret-in-test",
                    "MFA_SECRET_ENCRYPTION_KEY": "s0f0H-WTod2GGbBDl220EItWk-_1YiivkcEk9503ZTg=",
                    "AURAFOODS_DATA_ROOT": data_root,
                    "AURAFOODS_MEDIA_ROOT": media_root,
                }
            )
            result = subprocess.run(
                [sys.executable, "manage.py", "check"],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(os.path.exists(data_root))
            self.assertFalse(os.path.exists(media_root))

    @override_settings(MEDIA_STORAGE_BACKEND="local")
    def test_check_media_storage_reports_local_backend_without_secrets(self):
        output = StringIO()

        call_command("check_media_storage", stdout=output)

        self.assertIn("Media storage backend: local", output.getvalue())
        self.assertIn("Write test skipped", output.getvalue())
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", output.getvalue())

    @override_settings(MEDIA_STORAGE_BACKEND="s3", STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}})
    def test_check_media_storage_missing_s3_env_fails_without_printing_secrets(self):
        output = StringIO()

        with self.assertRaises(CommandError) as context:
            call_command("check_media_storage", stdout=output)

        self.assertIn("Missing production media storage settings", str(context.exception))
        self.assertNotIn("not-secret", output.getvalue())

    def test_release_performance_check_command_passes_local_budgets(self):
        output = StringIO()

        call_command("release_performance_check", stdout=output, max_bytes=500000)

        self.assertIn("Release performance budgets passed", output.getvalue())
        self.assertIn("/shop/", output.getvalue())

    def test_release_package_script_excludes_sensitive_artifacts_and_uses_posix_paths(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        output = os.path.join(project_root, "dist", "test-release.zip")
        result = subprocess.run(
            [sys.executable, "scripts/build_release_package.py", "--output", output],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        import zipfile

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
        self.assertTrue(all("\\" not in name for name in names))
        self.assertIn("manage.py", names)
        self.assertIn("outputs/sbom.cdx.json", names)
        forbidden = ("media/", "staticfiles/", "__pycache__", ".git/", ".venv/")
        self.assertFalse(any(any(part in name for part in forbidden) for name in names))
