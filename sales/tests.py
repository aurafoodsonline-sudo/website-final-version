from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from erp.models import Product as ERPProduct, StockBatch, StockLedgerEntry, UnitOfMeasure, Warehouse
from shop.models import Order, OrderItem, PaymentTransaction, Product, ProductVariant, RefundRequest, ReturnRequest
from shop.services.lifecycle import OrderLifecycleService

from .models import CatalogVariantMapping, CustomerLedgerEntry, Refund, SalesOrder, SalesStockReservation
from .services import (
    approve_return_stock_after_qa, create_return_from_shop, create_sales_order_from_shop,
    dispatch_stock_for_order, post_customer_credit_note, post_customer_debit_note,
    post_customer_payment, post_refund, reallocate_stock_reservation,
    reject_return_after_qa, release_stock_reservation,
)
from .reports import sales_report


class SalesIntegrationTests(TestCase):
    def setUp(self):
        unit = UnitOfMeasure.objects.create(code="EA", name="Each", unit_type="count")
        warehouse = Warehouse.objects.create(code="FG", name="Finished goods")
        self.erp_product = ERPProduct.objects.create(
            code="SKU-100", name="Chilli 100g", product_type=ERPProduct.ProductType.FINISHED,
            base_unit=unit, grammage=Decimal("100.000"), sale_price=Decimal("250.00"),
        )
        self.batch = StockBatch.objects.create(
            product=self.erp_product, batch_number="FG-001", batch_type=StockBatch.BatchType.FINISHED,
            source_document_type="PACK", source_document_number="PACK-1", warehouse=warehouse,
            quantity_on_hand=Decimal("10.000"), unit_cost=Decimal("100.0000"),
        )
        public_product = Product.objects.create(slug="chilli", name="Chilli")
        self.variant = ProductVariant.objects.create(
            product=public_product, sku="WEB-100", weight_value=100, price=Decimal("250.00"), stock_quantity=999,
        )
        CatalogVariantMapping.objects.create(variant=self.variant, erp_product=self.erp_product)
        self.order = Order.objects.create(
            customer_name="Retail Customer", email="retail@example.com", phone="03001234567",
            city="Karachi", address="Street 1, Karachi, Pakistan", reference="WEB-ORDER-1",
            subtotal=Decimal("500.00"), total=Decimal("500.00"),
        )
        OrderItem.objects.create(
            order=self.order, variant=self.variant, product_id=public_product.pk,
            product_name=public_product.name, quantity=2, weight_option="100g",
            price=Decimal("250.00"), subtotal=Decimal("500.00"),
        )

    def test_order_reserves_erp_batch_and_posts_receivable(self):
        sales_order = create_sales_order_from_shop(self.order)
        reservation = SalesStockReservation.objects.get(line__order=sales_order)
        self.assertEqual(reservation.batch, self.batch)
        self.assertEqual(reservation.quantity, Decimal("2"))
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("10.000"))
        self.assertEqual(CustomerLedgerEntry.objects.get().amount, Decimal("500.00"))

    def test_dispatch_posts_erp_stock_ledger_once(self):
        create_sales_order_from_shop(self.order)
        challan = dispatch_stock_for_order(self.order)
        self.batch.refresh_from_db()
        self.assertEqual(challan.status, "dispatched")
        self.assertEqual(self.batch.quantity_on_hand, Decimal("8.000"))
        self.assertEqual(StockLedgerEntry.objects.filter(source_document_type="SALES_DISPATCH").count(), 1)
        dispatch_stock_for_order(self.order)
        self.assertEqual(StockLedgerEntry.objects.filter(source_document_type="SALES_DISPATCH").count(), 1)

    def test_cancellation_releases_without_mutating_physical_stock(self):
        sales_order = create_sales_order_from_shop(self.order)
        self.assertEqual(release_stock_reservation(self.order), 1)
        self.assertEqual(SalesStockReservation.objects.get().status, "released")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("10.000"))
        sales_order.invoice.refresh_from_db()
        self.assertEqual(sales_order.invoice.status, "cancelled")
        self.assertEqual(sales_order.invoice.balance, Decimal("0.00"))
        self.assertEqual(
            CustomerLedgerEntry.objects.filter(invoice=sales_order.invoice).aggregate(total=Sum("amount"))["total"],
            Decimal("0.00"),
        )

    def test_dispatch_rejects_partial_reservation_before_stock_posting(self):
        create_sales_order_from_shop(self.order)
        reservation = SalesStockReservation.objects.get()
        reservation.quantity = Decimal("1.000")
        reservation.save(update_fields=["quantity"])
        with self.assertRaisesRegex(ValidationError, "fully cover"):
            dispatch_stock_for_order(self.order)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("10.000"))
        self.assertFalse(StockLedgerEntry.objects.filter(source_document_type="SALES_DISPATCH").exists())

    def test_expired_reservation_can_be_reallocated_then_dispatched(self):
        create_sales_order_from_shop(self.order)
        original = SalesStockReservation.objects.get()
        original.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        original.save(update_fields=["expires_at"])

        self.assertEqual(reallocate_stock_reservation(self.order), 1)
        original.refresh_from_db()
        current = SalesStockReservation.objects.get(status=SalesStockReservation.Status.ACTIVE)
        self.assertEqual(original.status, SalesStockReservation.Status.RELEASED)
        self.assertGreater(current.expires_at, timezone.now())
        dispatch_stock_for_order(self.order)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("8.000"))

    def test_unmapped_variant_is_not_sellable(self):
        CatalogVariantMapping.objects.all().delete()
        self.assertFalse(self.variant.is_sellable)
        with self.assertRaises(ValidationError):
            create_sales_order_from_shop(self.order)

    def test_verified_payment_posts_negative_ledger(self):
        sales_order = create_sales_order_from_shop(self.order)
        payment = PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="verified", amount=Decimal("500.00")
        )
        post_customer_payment(payment)
        self.assertEqual(sales_order.invoice.payment_allocations.get().amount, Decimal("500.00"))
        self.assertEqual(CustomerLedgerEntry.objects.aggregate(total=Sum("amount"))["total"], Decimal("0.00"))

    def test_unverified_and_overpayment_are_rejected(self):
        sales_order = create_sales_order_from_shop(self.order)
        pending = PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="pending", amount=Decimal("500.00")
        )
        with self.assertRaisesRegex(ValidationError, "verified"):
            post_customer_payment(pending)
        pending.status = "verified"
        pending.amount = Decimal("500.01")
        pending.save(update_fields=["status", "amount"])
        with self.assertRaisesRegex(ValidationError, "cannot exceed"):
            post_customer_payment(pending)
        self.assertEqual(sales_order.invoice.balance, Decimal("500.00"))

    def test_return_stays_quarantined_until_qa_then_posts_stock_in(self):
        sales_order = create_sales_order_from_shop(self.order)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        request = ReturnRequest.objects.create(order=self.order, reason="Sealed pack returned")
        sales_return = create_return_from_shop(request)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("8.000"))
        self.assertEqual(sales_return.status, "quarantined")
        approve_return_stock_after_qa(sales_return)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_on_hand, Decimal("10.000"))
        self.assertEqual(StockLedgerEntry.objects.filter(source_document_type="SALES_RETURN_QA").count(), 1)

    def test_qa_rejection_reverses_credit_without_restocking(self):
        sales_order = create_sales_order_from_shop(self.order)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        request = ReturnRequest.objects.create(order=self.order, reason="Opened product")
        sales_return = create_return_from_shop(request)

        reject_return_after_qa(sales_return, reason="Seal broken")

        sales_return.refresh_from_db()
        request.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(sales_return.status, "rejected")
        self.assertEqual(request.status, ReturnRequest.STATUS_REJECTED)
        self.assertEqual(sales_order.invoice.balance, Decimal("500.00"))
        self.assertEqual(self.batch.quantity_on_hand, Decimal("8.000"))
        self.assertFalse(StockLedgerEntry.objects.filter(source_document_type="SALES_RETURN_QA").exists())

    def test_paid_return_and_refund_reconcile_invoice_to_zero(self):
        sales_order = create_sales_order_from_shop(self.order)
        payment_tx = PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="verified", amount=Decimal("500.00")
        )
        post_customer_payment(payment_tx)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        return_request = ReturnRequest.objects.create(order=self.order, reason="Eligible sealed return")
        create_return_from_shop(return_request)
        refund_request = RefundRequest.objects.create(
            order=self.order, amount=Decimal("500.00"), reason="Return approved"
        )
        post_refund(refund_request)
        self.assertEqual(sales_order.invoice.balance, Decimal("0.00"))
        second_refund = RefundRequest.objects.create(
            order=self.order, amount=Decimal("0.01"), reason="Duplicate refund"
        )
        with self.assertRaisesRegex(ValidationError, "credit available"):
            post_refund(second_refund)

    def test_refund_lifecycle_updates_ledger_payment_and_order_atomically(self):
        operator = get_user_model().objects.create_superuser(
            "refund-operator", "refund-operator@example.com", "SafePassword123!"
        )
        sales_order = create_sales_order_from_shop(self.order)
        payment = PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="verified", amount=Decimal("500.00")
        )
        post_customer_payment(payment)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=["status"])
        return_request = OrderLifecycleService.request_return(self.order, "Eligible return")
        OrderLifecycleService.approve_return(return_request)
        refund_request = OrderLifecycleService.request_refund(self.order, Decimal("500.00"), "Approved", actor=None)

        OrderLifecycleService.approve_refund(refund_request, actor=operator)

        refund_request.refresh_from_db()
        payment.refresh_from_db()
        self.order.refresh_from_db()
        sales_order.invoice.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.STATUS_PROCESSED)
        self.assertEqual(payment.status, PaymentTransaction.STATUS_REFUNDED)
        self.assertEqual(self.order.payment_status, Order.PAYMENT_REFUNDED)
        self.assertEqual(sales_order.invoice.balance, Decimal("0.00"))

    def test_partial_refund_without_matching_verified_payment_is_rejected(self):
        PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="verified", amount=Decimal("500.00")
        )
        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=["status"])
        with self.assertRaisesRegex(ValidationError, "matching verified payment"):
            OrderLifecycleService.request_refund(self.order, Decimal("400.00"), "Partial")
        self.assertFalse(RefundRequest.objects.exists())

    def test_refund_permission_failure_rolls_back_ledger_posting(self):
        sales_order = create_sales_order_from_shop(self.order)
        payment = PaymentTransaction.objects.create(
            order=self.order, provider="manual", status="verified", amount=Decimal("500.00")
        )
        post_customer_payment(payment)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=["status"])
        return_request = OrderLifecycleService.request_return(self.order, "Eligible return")
        OrderLifecycleService.approve_return(return_request)
        refund_request = OrderLifecycleService.request_refund(self.order, Decimal("500.00"), "Approved")
        unauthorized = get_user_model().objects.create_user("refund-viewer", password="SafePassword123!")
        ledger_count = CustomerLedgerEntry.objects.count()

        with self.assertRaises(PermissionDenied):
            OrderLifecycleService.approve_refund(refund_request, actor=unauthorized)

        refund_request.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.STATUS_REQUESTED)
        self.assertEqual(payment.status, PaymentTransaction.STATUS_VERIFIED)
        self.assertEqual(CustomerLedgerEntry.objects.count(), ledger_count)
        self.assertFalse(Refund.objects.exists())

    def test_only_one_full_order_return_is_allowed(self):
        sales_order = create_sales_order_from_shop(self.order)
        dispatch_stock_for_order(self.order)
        sales_order.status = SalesOrder.Status.DELIVERED
        sales_order.save(update_fields=["status"])
        create_return_from_shop(ReturnRequest.objects.create(order=self.order, reason="First"))
        with self.assertRaisesRegex(ValidationError, "already been recorded"):
            create_return_from_shop(ReturnRequest.objects.create(order=self.order, reason="Second"))

    def test_credit_and_debit_note_signs_reconcile_on_invoice(self):
        sales_order = create_sales_order_from_shop(self.order)
        post_customer_credit_note(
            customer=sales_order.customer, amount=Decimal("25.00"), reason="Allowance", order=sales_order
        )
        post_customer_debit_note(
            customer=sales_order.customer, amount=Decimal("10.00"), reason="Extra charge", order=sales_order
        )
        self.assertEqual(sales_order.invoice.balance, Decimal("485.00"))

    def test_customer_aging_uses_ledger_balance_without_per_invoice_queries(self):
        sales_order = create_sales_order_from_shop(self.order)
        post_customer_debit_note(
            customer=sales_order.customer, amount=Decimal("10.00"), reason="Extra charge", order=sales_order
        )
        with self.assertNumQueries(1):
            rows = sales_report("customer-aging")
        self.assertEqual(rows[0]["balance"], Decimal("510.00"))

    def test_notes_require_an_invoice_order(self):
        sales_order = create_sales_order_from_shop(self.order)
        with self.assertRaisesRegex(ValidationError, "must reference"):
            post_customer_credit_note(customer=sales_order.customer, amount=Decimal("1.00"), reason="No invoice")

    def test_registered_and_guest_customer_codes_use_distinct_namespaces(self):
        user = get_user_model().objects.create_user(username="buyer", password="irrelevant")
        self.order.customer_user = user
        self.order.save(update_fields=["customer_user"])
        registered = create_sales_order_from_shop(self.order).customer
        guest_order = Order.objects.create(
            customer_name="Guest", email="guest@example.com", phone="03009999999",
            city="Karachi", address="Street 2", reference="WEB-ORDER-GUEST",
            subtotal=Decimal("250.00"), total=Decimal("250.00"),
        )
        OrderItem.objects.create(
            order=guest_order, variant=self.variant, product_id=self.variant.product_id,
            product_name=self.variant.product.name, quantity=1, weight_option="100g",
            price=Decimal("250.00"), subtotal=Decimal("250.00"),
        )
        guest = create_sales_order_from_shop(guest_order).customer
        self.assertTrue(registered.code.startswith("WEB-U-"))
        self.assertTrue(guest.code.startswith("WEB-G-"))
        self.assertNotEqual(registered.code, guest.code)


class CommercePermissionPresentationTests(TestCase):
    def grant(self, user, *codes):
        content_type = ContentType.objects.get_for_model(ERPProduct)
        for code in codes:
            permission, _ = Permission.objects.get_or_create(
                codename=code, content_type=content_type, defaults={"name": code}
            )
            user.user_permissions.add(permission)

    def test_read_only_sales_user_does_not_receive_mutation_controls(self):
        user = get_user_model().objects.create_user("sales-reader", password="SafePassword123!", is_staff=True)
        self.grant(user, "sales.view")
        self.client.force_login(user)

        response = self.client.get("/commerce-admin/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/transition/")
        self.assertNotContains(response, "/reallocate/")
        self.assertNotContains(response, "/verify/")
        self.assertNotContains(response, "/qa-accept/")
        self.assertNotContains(response, "/qa-reject/")
        self.assertNotContains(response, "/refunds/")
