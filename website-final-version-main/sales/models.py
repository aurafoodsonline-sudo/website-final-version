from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class SalesAuditModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="%(class)s_sales_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="%(class)s_sales_updated",
    )

    class Meta:
        abstract = True


class CatalogVariantMapping(SalesAuditModel):
    variant = models.OneToOneField("shop.ProductVariant", on_delete=models.CASCADE, related_name="erp_mapping")
    erp_product = models.ForeignKey("erp.Product", on_delete=models.PROTECT, related_name="catalog_mappings")
    display_price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    mrp = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    public_stock_visibility = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["variant__product__name", "variant__sort_order"]
        permissions = [("manage_catalog_mapping", "Can manage ERP catalog mappings")]

    def clean(self):
        if self.erp_product_id and self.erp_product.product_type != "finished":
            raise ValidationError({"erp_product": "Web variants can map only to finished ERP SKUs."})

    def __str__(self):
        return f"{self.variant.sku} -> {self.erp_product.code}"


class CustomerAccountProfile(SalesAuditModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sales_profile")
    customer = models.OneToOneField("erp.CustomerDistributor", on_delete=models.PROTECT, related_name="web_profile")

    def __str__(self):
        return f"{self.user} / {self.customer.code}"


class SalesOrder(SalesAuditModel):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        DISPATCHED = "dispatched", "Dispatched"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    shop_order = models.OneToOneField("shop.Order", on_delete=models.PROTECT, related_name="sales_record")
    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT, related_name="sales_orders")
    number = models.CharField(max_length=40, unique=True)
    channel = models.CharField(max_length=30, default="ecommerce")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RESERVED)
    order_date = models.DateField(default=timezone.localdate)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2)
    delivery_charge = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "order_date"]), models.Index(fields=["status", "channel"])]

    def __str__(self):
        return self.number


class SalesOrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    shop_item = models.OneToOneField("shop.OrderItem", null=True, blank=True, on_delete=models.PROTECT)
    variant = models.ForeignKey("shop.ProductVariant", on_delete=models.PROTECT)
    erp_product = models.ForeignKey("erp.Product", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    line_total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [models.CheckConstraint(check=models.Q(quantity__gt=0), name="sales_line_qty_positive")]


class SalesStockReservation(SalesAuditModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        DISPATCHED = "dispatched", "Dispatched"

    line = models.ForeignKey(SalesOrderLine, on_delete=models.CASCADE, related_name="reservations")
    batch = models.ForeignKey("erp.StockBatch", on_delete=models.PROTECT, related_name="sales_reservations")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["batch", "status"]), models.Index(fields=["expires_at", "status"])]
        constraints = [models.CheckConstraint(check=models.Q(quantity__gt=0), name="sales_reservation_qty_positive")]


class SalesInvoice(SalesAuditModel):
    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        PART_PAID = "part_paid", "Part paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=40, unique=True)
    order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT, related_name="invoice")
    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT, related_name="sales_invoices")
    invoice_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)

    class Meta:
        indexes = [models.Index(fields=["customer", "due_date", "status"])]

    @property
    def paid_amount(self):
        return self.payment_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def balance(self):
        ledger_total = self.ledger_entries.aggregate(total=Sum("amount"))["total"]
        return ledger_total if ledger_total is not None else self.amount - self.paid_amount

    def __str__(self):
        return self.number


class SalesInvoiceLine(models.Model):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="lines")
    order_line = models.OneToOneField(SalesOrderLine, null=True, blank=True, on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.DecimalField(max_digits=18, decimal_places=2)


class CustomerPayment(SalesAuditModel):
    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT, related_name="customer_payments")
    shop_transaction = models.OneToOneField(
        "shop.PaymentTransaction", null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_payment"
    )
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    method = models.CharField(max_length=30)
    reference = models.CharField(max_length=120, blank=True)
    is_reversed = models.BooleanField(default=False)


class CustomerPaymentAllocation(models.Model):
    payment = models.ForeignKey(CustomerPayment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT, related_name="payment_allocations")
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["payment", "invoice"], name="sales_payment_invoice_unique"),
            models.CheckConstraint(check=models.Q(amount__gt=0), name="sales_payment_alloc_positive"),
        ]


class CustomerLedgerEntry(SalesAuditModel):
    class EntryType(models.TextChoices):
        OPENING = "opening", "Opening receivable"
        INVOICE = "invoice", "Sales invoice"
        PAYMENT = "payment", "Customer payment"
        REFUND = "refund", "Refund"
        CREDIT_NOTE = "credit_note", "Credit note"
        DEBIT_NOTE = "debit_note", "Debit note"
        RETURN = "return", "Sales return"
        ADJUSTMENT = "adjustment", "Adjustment"
        REVERSAL = "reversal", "Reversal"

    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT, related_name="sales_ledger")
    invoice = models.ForeignKey(
        SalesInvoice, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    transaction_date = models.DateField(default=timezone.localdate)
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2, help_text="Positive means customer owes Aura Foods.")
    reference_type = models.CharField(max_length=40)
    reference_number = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["transaction_date", "id"]
        indexes = [models.Index(fields=["customer", "transaction_date"]), models.Index(fields=["reference_type", "reference_number"])]


class DeliveryChallan(SalesAuditModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        DISPATCHED = "dispatched", "Dispatched"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=40, unique=True)
    order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT, related_name="delivery_challan")
    dispatch_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    carrier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)


class DeliveryChallanLine(models.Model):
    challan = models.ForeignKey(DeliveryChallan, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)


class DispatchAllocation(SalesAuditModel):
    challan_line = models.ForeignKey(DeliveryChallanLine, on_delete=models.PROTECT, related_name="allocations")
    reservation = models.OneToOneField(SalesStockReservation, on_delete=models.PROTECT, related_name="dispatch")
    batch = models.ForeignKey("erp.StockBatch", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    stock_ledger_entry = models.OneToOneField("erp.StockLedgerEntry", on_delete=models.PROTECT)


class SalesReturn(SalesAuditModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        QUARANTINED = "quarantined", "Quarantined"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CLOSED = "closed", "Closed"

    number = models.CharField(max_length=40, unique=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="returns")
    shop_request = models.OneToOneField("shop.ReturnRequest", null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    reason = models.TextField()
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order"], name="sales_one_full_return_per_order")]


class SalesReturnLine(models.Model):
    class Disposition(models.TextChoices):
        QUARANTINE = "quarantine", "Quarantine"
        RESTOCKED = "restocked", "Restocked after QA"
        REJECTED = "rejected", "Rejected"

    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    disposition = models.CharField(max_length=20, choices=Disposition.choices, default=Disposition.QUARANTINE)


class Refund(SalesAuditModel):
    number = models.CharField(max_length=40, unique=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="refunds")
    shop_request = models.OneToOneField("shop.RefundRequest", null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.TextField(blank=True)
    processed_at = models.DateTimeField(default=timezone.now)


class DeliveryStatusLog(SalesAuditModel):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="delivery_logs")
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    note = models.CharField(max_length=240, blank=True)


class CustomerCreditNote(SalesAuditModel):
    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT)
    order = models.ForeignKey(SalesOrder, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.TextField()


class CustomerDebitNote(SalesAuditModel):
    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey("erp.CustomerDistributor", on_delete=models.PROTECT)
    order = models.ForeignKey(SalesOrder, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.TextField()
