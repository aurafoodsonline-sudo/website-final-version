from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditStampedModel(TimeStampedModel):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_updated",
    )

    class Meta:
        abstract = True


class Company(AuditStampedModel):
    # Core identity
    name = models.CharField(max_length=160)
    legal_name = models.CharField(max_length=200, blank=True)
    tax_identifier = models.CharField(max_length=80, blank=True)
    # Address & contact
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="Pakistan")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    # Financial configuration
    default_currency = models.CharField(max_length=3, default="PKR")
    decimal_precision = models.PositiveSmallIntegerField(default=3)
    money_precision = models.PositiveSmallIntegerField(default=2)
    financial_year_start_month = models.PositiveSmallIntegerField(default=7)
    # Operational defaults
    default_warehouse = models.ForeignKey(
        "Warehouse", null=True, blank=True, on_delete=models.SET_NULL, related_name="default_for_company"
    )
    near_expiry_threshold_days = models.PositiveIntegerField(default=30)
    # Document numbering prefixes
    po_prefix = models.CharField(max_length=10, default="PO")
    grn_prefix = models.CharField(max_length=10, default="GRN")
    inv_prefix = models.CharField(max_length=10, default="INV")
    pay_prefix = models.CharField(max_length=10, default="PAY")
    adv_prefix = models.CharField(max_length=10, default="ADV")
    dn_prefix = models.CharField(max_length=10, default="DN")
    cn_prefix = models.CharField(max_length=10, default="CN")
    prod_prefix = models.CharField(max_length=10, default="PROD")
    pack_prefix = models.CharField(max_length=10, default="PACK")
    adj_prefix = models.CharField(max_length=10, default="ADJ")
    # Receipt print settings
    receipt_show_logo = models.BooleanField(default=True)
    receipt_footer_text = models.TextField(blank=True, default="Thank you for your business.")
    receipt_paper_size = models.CharField(max_length=10, default="A4")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Companies"

    def __str__(self) -> str:
        return self.name


class Warehouse(AuditStampedModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class UnitOfMeasure(AuditStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=80)
    unit_type = models.CharField(max_length=30, default="weight")
    decimal_places = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.code


class UnitConversion(AuditStampedModel):
    from_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="conversions_from")
    to_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="conversions_to")
    factor = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["from_unit", "to_unit"], name="uq_unit_conversion_pair"),
            models.CheckConstraint(check=models.Q(factor__gt=0), name="ck_unit_conversion_factor_positive"),
        ]


class Product(AuditStampedModel):
    class ProductType(models.TextChoices):
        RAW = "raw", "Raw Spice"
        POWDER = "powder", "Powder Product"
        FINISHED = "finished", "Finished SKU"
        PACKAGING = "packaging", "Packaging Material"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    product_type = models.CharField(max_length=20, choices=ProductType.choices)
    category = models.CharField(max_length=80, blank=True, help_text="Product category e.g. Red Chili, Turmeric")
    base_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    # Raw spice fields (product_type=raw)
    grade = models.CharField(max_length=40, blank=True)
    origin = models.CharField(max_length=80, blank=True)
    storage_notes = models.TextField(blank=True)
    expected_grinding_yield_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, help_text="Expected % yield after grinding")
    default_supplier = models.ForeignKey("Supplier", null=True, blank=True, on_delete=models.SET_NULL, related_name="default_products")
    # Powder fields (product_type=powder)
    linked_raw_spice = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="powder_products", limit_choices_to={"product_type": "raw"})
    moisture_loss_allowance_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    grinding_loss_allowance_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    # Finished SKU fields (product_type=finished)
    grammage = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    net_weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    gross_weight = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    pack_type = models.CharField(max_length=40, blank=True, help_text="e.g. pouch, jar, bottle, box")
    carton_quantity = models.PositiveIntegerField(null=True, blank=True, help_text="Packs per carton")
    mrp = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, help_text="Maximum retail price — D52 sales readiness")
    sale_price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, help_text="Standard sale price — D52 sales readiness")
    # Stock control
    shelf_life_days = models.PositiveIntegerField(null=True, blank=True)
    minimum_stock = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0"))
    maximum_stock = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    reorder_level = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    claim_status = models.CharField(max_length=20, default="draft")
    # Barcode and label readiness
    barcode = models.CharField(max_length=80, blank=True)
    batch_barcode_prefix = models.CharField(max_length=20, blank=True)
    carton_barcode = models.CharField(max_length=80, blank=True)
    qr_code_data = models.CharField(max_length=200, blank=True)
    label_version = models.CharField(max_length=40, blank=True)
    artwork_version = models.CharField(max_length=40, blank=True)
    design_version = models.CharField(max_length=40, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["product_type"], name="idx_product_type"),
            models.Index(fields=["barcode"], name="idx_product_barcode"),
        ]

    def clean(self) -> None:
        if self.product_type == self.ProductType.FINISHED and not self.grammage:
            raise ValidationError("Finished SKUs require grammage.")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Supplier(AuditStampedModel):
    code = models.CharField(max_length=40, unique=True)
    class SupplierCategory(models.TextChoices):
        RAW_MATERIAL = "raw_material", "Raw Material Supplier"
        PACKAGING = "packaging", "Packaging Supplier"
        GRINDING_SERVICE = "grinding_service", "Grinding Service"
        TRANSPORT = "transport", "Transport Supplier"
        GENERAL = "general", "General Service Supplier"

    name = models.CharField(max_length=160)
    business_name = models.CharField(max_length=200, blank=True)
    supplier_category = models.CharField(max_length=30, choices=SupplierCategory.choices, default=SupplierCategory.RAW_MATERIAL)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    payment_terms_days = models.PositiveIntegerField(default=0)
    lead_time_days = models.PositiveIntegerField(default=0)
    # Banking details
    bank_account_title = models.CharField(max_length=160, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=60, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    # Tax
    tax_identifier = models.CharField(max_length=80, blank=True)
    tax_category = models.CharField(max_length=80, blank=True)
    withholding_tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.000"))
    # Running balances (cached; source of truth = ledger)
    payable_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    advance_balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class CashBankAccount(AuditStampedModel):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=20, default="cash", help_text="cash or bank")
    # Spec 3.23: bank reconciliation readiness
    bank_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=60, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.code


class DocumentSequence(models.Model):
    prefix = models.CharField(max_length=20, unique=True)
    next_number = models.PositiveIntegerField(default=1)


class DocumentState(models.TextChoices):
    DRAFT = "draft", "Draft"
    POSTED = "posted", "Posted"
    PENDING_APPROVAL = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    PARTIALLY_RECEIVED = "partially_received", "Partially Received"
    FULLY_RECEIVED = "fully_received", "Fully Received"
    QUALITY_PENDING = "quality_pending", "Quality Pending"
    PARTIALLY_PAID = "partially_paid", "Partially Paid"
    FULLY_PAID = "fully_paid", "Fully Paid"
    OVERDUE = "overdue", "Overdue"
    CANCELLED = "cancelled", "Cancelled"
    CLOSED = "closed", "Closed"
    REVERSED = "reversed", "Reversed"


class PurchaseOrder(AuditStampedModel):
    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    order_date = models.DateField(default=timezone.localdate)
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_po_number"),
            models.Index(fields=["supplier", "status"], name="idx_po_supplier_status"),
            models.Index(fields=["order_date"], name="idx_po_order_date"),
        ]


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    rate_agreement = models.ForeignKey(
        "SupplierPriceAgreement", null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_order_lines"
    )
    agreed_rate_snapshot = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    rate_variance_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    rate_variance_percentage = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal("0.0000"))
    rate_override_reason = models.TextField(blank=True)


class GRN(AuditStampedModel):
    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    purchase_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT)
    # Spec 3.14: GRN header fields
    grn_date = models.DateField(default=timezone.localdate)
    delivery_note_number = models.CharField(max_length=80, blank=True)
    vehicle_number = models.CharField(max_length=40, blank=True)
    received_by = models.CharField(max_length=120, blank=True)
    default_warehouse = models.ForeignKey(
        "Warehouse", null=True, blank=True, on_delete=models.PROTECT, related_name="grns_received"
    )
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="grns_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="grns_cancelled"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    shortage_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    quality_deduction_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payable_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_grn_number"),
            models.Index(fields=["supplier", "status"], name="idx_grn_supplier_status"),
            models.Index(fields=["grn_date"], name="idx_grn_date"),
        ]


class GRNLine(models.Model):
    grn = models.ForeignKey(GRN, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    # Quantity chain (spec 3.15 weighment & shortage control)
    ordered_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    supplier_claimed_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    received_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    # Weighment fields
    gross_weight = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    tare_weight = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    net_weight = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    bag_count = models.PositiveIntegerField(null=True, blank=True)
    # Quality deductions
    moisture_deduction = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    quality_deduction = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    # Accepted/rejected/shortage
    accepted_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    rejected_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    shortage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    excess_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    # Final payable quantity: accepted minus further deductions
    final_payable_quantity = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    rate_agreement = models.ForeignKey(
        "SupplierPriceAgreement", null=True, blank=True, on_delete=models.PROTECT, related_name="grn_lines"
    )
    agreed_rate_snapshot = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    rate_variance_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    rate_variance_percentage = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal("0.0000"))
    rate_override_reason = models.TextField(blank=True)
    batch_number = models.CharField(max_length=80)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    # Warehouse location for this line
    warehouse_location = models.CharField(max_length=80, blank=True)
    remarks = models.TextField(blank=True)

    @property
    def accepted_value(self) -> Decimal:
        qty = self.final_payable_quantity if self.final_payable_quantity is not None else self.accepted_quantity
        return qty * self.unit_cost

    def clean(self) -> None:
        from django.core.exceptions import ValidationError
        if self.accepted_quantity + self.rejected_quantity > self.received_quantity + Decimal("0.001"):
            raise ValidationError("accepted + rejected cannot exceed received quantity.")


class QualityInspection(AuditStampedModel):
    class Decision(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        ACCEPTED_WITH_DEDUCTION = "accepted_with_deduction", "Accepted with Deduction"
        PARTIALLY_ACCEPTED = "partially_accepted", "Partially Accepted"
        REJECTED = "rejected", "Rejected"
        HELD_FOR_REVIEW = "held_for_review", "Held for Review"
        RETURNED_TO_SUPPLIER = "returned_to_supplier", "Returned to Supplier"

    grn = models.OneToOneField(GRN, on_delete=models.PROTECT, related_name="quality_inspection")
    # Full inspection criteria (spec 3.16)
    color_ok = models.BooleanField(default=True)
    smell_ok = models.BooleanField(default=True)
    moisture_ok = models.BooleanField(default=True)
    dust_ok = models.BooleanField(default=True)
    foreign_particles_ok = models.BooleanField(default=True)
    stones_ok = models.BooleanField(default=True)
    insects_ok = models.BooleanField(default=True)
    adulteration_suspicion = models.BooleanField(default=False)
    cleanliness_ok = models.BooleanField(default=True)
    grade_match_ok = models.BooleanField(default=True)
    packaging_condition_ok = models.BooleanField(default=True)
    aroma_ok = models.BooleanField(default=True)
    contamination_ok = models.BooleanField(default=True)
    # Decision and deduction
    quality_decision = models.CharField(max_length=40, choices=Decision.choices, default=Decision.ACCEPTED)
    deduction_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    deduction_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    inspector_notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)


class SupplierInvoice(AuditStampedModel):
    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    grn = models.ForeignKey(GRN, null=True, blank=True, on_delete=models.PROTECT)
    invoice_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    is_tax_inclusive = models.BooleanField(default=False)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    withholding_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    advance_adjusted_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    debit_note_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit_note_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.POSTED)

    @property
    def outstanding_amount(self) -> Decimal:
        return self.amount - self.paid_amount - self.advance_adjusted_amount - self.debit_note_amount - self.credit_note_amount

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_supplier_invoice_no"),
            models.Index(fields=["supplier", "status"], name="idx_invoice_supplier_status"),
            models.Index(fields=["invoice_date"], name="idx_invoice_date"),
            models.Index(fields=["due_date"], name="idx_invoice_due_date"),
        ]


class SupplierPayment(AuditStampedModel):
    class PaymentType(models.TextChoices):
        INVOICE = "invoice", "Invoice Payment"
        ADVANCE = "advance", "Advance Payment"
        IMMEDIATE = "immediate", "Immediate Payment"
        ADJUSTMENT = "adjustment", "Advance Adjustment"
        REVERSAL = "reversal", "Reversal"

    number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    cash_bank_account = models.ForeignKey(CashBankAccount, null=True, blank=True, on_delete=models.PROTECT)
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices)
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # Spec 3.19: payment voucher fields
    payment_method = models.CharField(max_length=40, blank=True, help_text="cash/bank_transfer/cheque/online/mobile_wallet/adjustment")
    reference_number = models.CharField(max_length=80, blank=True)
    cheque_number = models.CharField(max_length=40, blank=True)
    bank_reference = models.CharField(max_length=80, blank=True)
    transaction_id = models.CharField(max_length=80, blank=True)
    clearing_date = models.DateField(null=True, blank=True)
    bank_statement_matched = models.BooleanField(default=False)
    amount_in_words = models.CharField(max_length=300, blank=True)
    po_reference = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="payments_prepared"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="payments_approved"
    )
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="payments_reversed"
    )
    reversed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.POSTED)
    reversal_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_supplier_payment_no"),
            models.Index(fields=["supplier", "payment_type"], name="idx_payment_supplier_type"),
            models.Index(fields=["payment_date"], name="idx_payment_date"),
        ]


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(SupplierPayment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=18, decimal_places=2)


class StockBatch(AuditStampedModel):
    class BatchType(models.TextChoices):
        RAW = "raw", "Raw"
        POWDER = "powder", "Powder"
        FINISHED = "finished", "Finished"
        PACKAGING = "packaging", "Packaging"

    class StockState(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        HOLD = "hold", "On Hold"
        SUPPLIER_RETURNABLE = "supplier_returnable", "Supplier-Returnable"
        DAMAGED = "damaged", "Damaged"
        EXPIRED = "expired", "Expired"
        BLOCKED = "blocked", "Blocked"
        ISSUED = "issued", "Issued to Production"
        SAMPLE = "sample", "Sample"
        PROMOTIONAL = "promotional", "Promotional"
        REWORK = "rework", "In Rework"

    class ExpiryStatus(models.TextChoices):
        NOT_APPLICABLE = "not_applicable", "Not Applicable"
        CURRENT = "current", "Current"
        NEAR_EXPIRY = "near_expiry", "Near Expiry"
        EXPIRED = "expired", "Expired"

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    batch_number = models.CharField(max_length=80)
    batch_type = models.CharField(max_length=20, choices=BatchType.choices)
    stock_state = models.CharField(max_length=30, choices=StockState.choices, default=StockState.ACCEPTED)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    source_document_type = models.CharField(max_length=40)
    source_document_number = models.CharField(max_length=80)
    # Packing order reference for finished goods batches
    packing_order = models.ForeignKey(
        "PackingOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="finished_batches"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity_on_hand = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    manufacturing_date = models.DateField(null=True, blank=True)
    packing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    expiry_status = models.CharField(
        max_length=20, choices=ExpiryStatus.choices, default=ExpiryStatus.NOT_APPLICABLE
    )
    best_before_date = models.DateField(null=True, blank=True)
    # Label and design versioning for packaging/finished batches
    label_version = models.CharField(max_length=40, blank=True)
    design_version = models.CharField(max_length=40, blank=True)
    artwork_version = models.CharField(max_length=40, blank=True)
    batch_barcode = models.CharField(max_length=80, blank=True)
    is_blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=160, blank=True)
    parent_batch = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")

    class Meta:
        indexes = [
            models.Index(fields=["product", "batch_type"], name="idx_batch_product_type"),
            models.Index(fields=["batch_number"], name="idx_batch_number"),
            models.Index(fields=["warehouse", "batch_type"], name="idx_batch_wh_type"),
            models.Index(fields=["expiry_date"], name="idx_batch_expiry"),
            models.Index(fields=["source_document_type", "source_document_number"], name="idx_batch_source_doc"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["product", "batch_number", "batch_type"], name="uq_product_batch_type"),
            models.CheckConstraint(check=models.Q(quantity_on_hand__gte=0), name="ck_batch_qty_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.product.code}/{self.batch_number}"


class StockLedgerEntry(AuditStampedModel):
    class Direction(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"
        ADJUST = "adjust", "Adjust"

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="stock_entries")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    transaction_date = models.DateField(default=timezone.localdate)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    source_document_type = models.CharField(max_length=40)
    source_document_number = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["batch", "direction"], name="idx_stock_ledger_batch_dir"),
            models.Index(fields=["product", "transaction_date"], name="idx_stock_ledger_product_date"),
            models.Index(fields=["source_document_type", "source_document_number"], name="idx_stock_ledger_doc"),
        ]


class SupplierLedgerEntry(AuditStampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="ledger_entries")
    transaction_date = models.DateField(default=timezone.localdate)
    posting_date = models.DateField(default=timezone.localdate)
    source_document_type = models.CharField(max_length=40)
    source_document_number = models.CharField(max_length=80)
    balance_effect = models.CharField(max_length=40)
    payable_effect = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    advance_effect = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cash_bank_effect = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    debit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    running_payable_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    running_advance_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    description = models.CharField(max_length=240, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_ledgers_posted"
    )

    class Meta:
        indexes = [
            models.Index(fields=["supplier", "transaction_date"], name="idx_supplier_ledger_date"),
            models.Index(fields=["source_document_type", "source_document_number"], name="idx_supplier_ledger_doc"),
            models.Index(fields=["balance_effect"], name="idx_supplier_ledger_effect"),
        ]


class ProductionOrder(AuditStampedModel):
    number = models.CharField(max_length=40, unique=True)
    raw_batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="production_orders")
    powder_product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="powder_production_orders")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    issued_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    expected_output_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    actual_output_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    wastage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)
    powder_batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="source_production")

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_production_number"),
            models.Index(fields=["status"], name="idx_production_status"),
        ]


class PackagingBOM(AuditStampedModel):
    finished_product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="packaging_boms")
    powder_product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="powder_boms")
    powder_quantity_per_unit = models.DecimalField(max_digits=18, decimal_places=6)
    packing_wastage_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    effective_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    approved_by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.PROTECT, related_name="boms_approved")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["finished_product", "version"], name="uq_packaging_bom_version"),
        ]


class PackagingBOMLine(models.Model):
    bom = models.ForeignKey(PackagingBOM, on_delete=models.CASCADE, related_name="lines")
    packaging_product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity_per_unit = models.DecimalField(max_digits=18, decimal_places=6)
    wastage_allowance_pct = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    sequence = models.PositiveSmallIntegerField(default=0)
    remarks = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["sequence"]


class PackingOrder(AuditStampedModel):
    class PackingStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"
        REVERSED = "reversed", "Reversed"

    number = models.CharField(max_length=40, unique=True)
    bom = models.ForeignKey(PackagingBOM, on_delete=models.PROTECT)
    powder_batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="packing_orders")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    planned_units = models.DecimalField(max_digits=18, decimal_places=3)
    completed_units = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    rejected_units = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    wastage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    operator = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=PackingStatus.choices, default=PackingStatus.DRAFT)
    finished_batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="source_packing")

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_packing_number"),
            models.Index(fields=["status"], name="idx_packing_status"),
        ]


class OpeningBalance(AuditStampedModel):
    number = models.CharField(max_length=40, unique=True)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    cash_bank_account = models.ForeignKey(CashBankAccount, null=True, blank=True, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)


class AdjustmentDocument(AuditStampedModel):
    class AdjustmentType(models.TextChoices):
        DEBIT_NOTE = "debit_note", "Debit Note"
        CREDIT_NOTE = "credit_note", "Credit Note"
        STOCK_ADJUSTMENT = "stock_adjustment", "Stock Adjustment"
        SUPPLIER_RETURN = "supplier_return", "Supplier Return"
        REPACKING = "repacking", "Repacking"
        RELABELING = "relabeling", "Relabeling"
        REWORK = "rework", "Rework"
        PHYSICAL_COUNT = "physical_count", "Physical Count"

    number = models.CharField(max_length=40, unique=True)
    adjustment_type = models.CharField(max_length=30, choices=AdjustmentType.choices)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    balance_effect = models.CharField(max_length=40, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)

    class Meta:
        indexes = [
            models.Index(fields=["number"], name="idx_adjustment_number"),
            models.Index(fields=["adjustment_type", "status"], name="idx_adjustment_type_status"),
        ]


class AuditEvent(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=80)
    source_document_type = models.CharField(max_length=40)
    source_document_number = models.CharField(max_length=80)
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)


# ── PURCHASE REQUIREMENT ──────────────────────────────────────────────────────

class PurchaseRequirement(AuditStampedModel):
    """
    Purchase requirement / demand notice before a formal purchase order is raised.
    P0 business readiness domain.
    """
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual Demand"
        LOW_STOCK = "low_stock", "Low Stock Alert"
        PRODUCTION = "production", "Production Planning"
        SEASONAL = "seasonal", "Seasonal Bulk Purchase"
        PACKAGING = "packaging", "Packaging Shortage"
        OWNER = "owner", "Owner/Director Instruction"

    number = models.CharField(max_length=40, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    required_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    required_by_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=30, choices=Source.choices, default=Source.MANUAL)
    purpose = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)
    purchase_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="requirements"
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="idx_pr_status"),
            models.Index(fields=["required_by_date"], name="idx_pr_required_date"),
        ]

    def __str__(self) -> str:
        return self.number


# ── SUPPLIER TERMS & PERFORMANCE ─────────────────────────────────────────────

class SupplierTerm(AuditStampedModel):
    """Commercial terms for a supplier (payment mode, advance, credit days, etc.)."""
    supplier = models.OneToOneField(Supplier, on_delete=models.CASCADE, related_name="terms")
    payment_mode = models.CharField(max_length=40, blank=True)
    advance_required = models.BooleanField(default=False)
    credit_days = models.PositiveIntegerField(default=0)
    discount_terms = models.TextField(blank=True)
    delivery_responsibility = models.CharField(max_length=80, blank=True)
    quality_deduction_rules = models.TextField(blank=True)
    shortage_tolerance_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    replacement_policy = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"Terms: {self.supplier.code}"


class SupplierPerformance(AuditStampedModel):
    """Aggregated supplier performance record (report-ready, updated by service layer)."""
    supplier = models.OneToOneField(Supplier, on_delete=models.CASCADE, related_name="performance")
    total_purchases = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_grn_count = models.PositiveIntegerField(default=0)
    total_rejected_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    total_shortage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    average_yield_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    quality_complaints = models.PositiveIntegerField(default=0)
    payment_disputes = models.PositiveIntegerField(default=0)
    rating = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Performance: {self.supplier.code}"


# ── RECIPE / FORMULA MANAGEMENT ──────────────────────────────────────────────

class Recipe(AuditStampedModel):
    """
    Recipe/formula for mixed spices and masala products.
    P1 structural — implemented as first-class model.
    Confidentiality: admin.configure or owner only sees full formula.
    """
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    finished_product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="recipes",
        limit_choices_to={"product_type": "finished"},
    )
    standard_batch_size = models.DecimalField(max_digits=18, decimal_places=3)
    batch_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    version = models.PositiveIntegerField(default=1)
    effective_date = models.DateField()
    is_confidential = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)
    approved_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.PROTECT, related_name="recipes_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    change_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code", "version"], name="uq_recipe_code_version"),
        ]
        indexes = [
            models.Index(fields=["status"], name="idx_recipe_status"),
        ]

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class RecipeIngredient(models.Model):
    """Ingredient line within a recipe formula."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey(
        Product, on_delete=models.PROTECT,
        limit_choices_to={"product_type__in": ["raw", "powder"]},
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    percentage = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    tolerance_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    sequence = models.PositiveSmallIntegerField(default=0)
    remarks = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["sequence"]


# ── SYSTEM SETTINGS ─────────────────────────────────────────────────────────

class SystemSetting(models.Model):
    """
    Key-value system configuration store.
    Allows business-level settings without code changes (spec 3.1).
    Keys are namespaced: category.key_name
    """
    key = models.CharField(max_length=120, unique=True)
    value = models.TextField(blank=True)
    value_type = models.CharField(
        max_length=20, default="string",
        choices=[("string","String"),("integer","Integer"),("decimal","Decimal"),
                 ("boolean","Boolean"),("json","JSON")]
    )
    description = models.CharField(max_length=300, blank=True)
    is_editable = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["key"]
        verbose_name = "System Setting"

    def __str__(self) -> str:
        return f"{self.key} = {self.value[:60]}"

    @classmethod
    def get(cls, key: str, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default


# ── DOCUMENT NUMBER SERIES ────────────────────────────────────────────────────

class DocumentNumberSeries(models.Model):
    """
    Configurable document numbering series (spec 12 / IMPLEMENTATION: Section 12).
    Prefix, zero-padding, starting number — all configurable without code changes.
    next_document_number() in services uses DocumentSequence; this model extends it
    with per-prefix configuration.
    """
    prefix = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=160, blank=True)
    current_number = models.PositiveIntegerField(default=0)
    padding_digits = models.PositiveSmallIntegerField(default=6)
    separator = models.CharField(max_length=5, default="-")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Document Number Series"
        verbose_name_plural = "Document Number Series"

    def __str__(self) -> str:
        return f"{self.prefix}{self.separator}{str(self.current_number+1).zfill(self.padding_digits)}"

    def next(self) -> str:
        """Generate next number (call inside select_for_update transaction)."""
        self.current_number += 1
        self.save(update_fields=["current_number"])
        return f"{self.prefix}{self.separator}{str(self.current_number).zfill(self.padding_digits)}"


# ── LANDED COST ALLOCATION (Application-side placeholder) ────────────────────

class LandedCostAllocation(AuditStampedModel):
    """
    Application-side landed cost allocation placeholder.
    
    IMPLEMENTATION STATUS NOTE:
    Full landed-cost allocation by freight/loading/other charges is an
    application-side placeholder. This model stores the cost amounts and
    their allocation to GRN/batch, but does NOT constitute a complete
    costing subledger. Full landed-cost subledger with multi-batch
    allocation and per-unit cost adjustment is P1 future scope.
    """
    class CostCategory(models.TextChoices):
        FREIGHT = "freight", "Freight/Transport"
        LOADING = "loading", "Loading/Unloading"
        CUSTOMS = "customs", "Customs/Duty"
        INSPECTION = "inspection", "Inspection Fee"
        OTHER = "other", "Other Direct Cost"

    number = models.CharField(max_length=40, unique=True)
    grn = models.ForeignKey(GRN, on_delete=models.PROTECT, related_name="landed_costs")
    cost_category = models.CharField(max_length=30, choices=CostCategory.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    allocation_base = models.CharField(max_length=40, default="quantity", help_text="quantity or value")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)

    class Meta:
        indexes = [
            models.Index(fields=["grn"], name="idx_landed_cost_grn"),
        ]

    def __str__(self) -> str:
        return f"{self.number} / {self.cost_category}"


# ── CHART OF ACCOUNTS READINESS (Structural placeholder) ─────────────────────

class ChartOfAccountEntry(models.Model):
    """
    Chart of accounts / general ledger readiness stub.
    
    IMPLEMENTATION STATUS NOTE:
    Full chart of accounts / general ledger is FUTURE SCOPE.
    This model provides account type mapping for ERP document types
    to support future double-entry accounting integration without
    redesigning supplier, payment, inventory, or costing records.
    """
    class AccountType(models.TextChoices):
        PAYABLE = "payable", "Supplier Payable"
        ADVANCE = "advance", "Supplier Advance"
        RAW_INVENTORY = "raw_inventory", "Raw Material Inventory"
        PACKAGING_INVENTORY = "packaging_inventory", "Packaging Inventory"
        FINISHED_INVENTORY = "finished_inventory", "Finished Goods Inventory"
        CASH = "cash", "Cash"
        BANK = "bank", "Bank"
        PURCHASE = "purchase", "Purchase Expense"
        GRINDING = "grinding", "Grinding Expense"
        PACKAGING_EXP = "packaging_exp", "Packaging Expense"
        WASTAGE = "wastage", "Wastage/Loss"
        DISCOUNT = "discount", "Discount Received"
        ADJUSTMENT = "adjustment", "Stock Adjustment Gain/Loss"
        CUSTOMER_RECEIVABLE = "customer_receivable", "Customer Receivable"  # D52 sales readiness
        SALES_REVENUE = "sales_revenue", "Sales Revenue"  # D52 sales readiness

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    account_type = models.CharField(max_length=40, choices=AccountType.choices)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

# ── SUPPLIER INVOICE LINE ─────────────────────────────────────────────────────

class SupplierInvoiceLine(models.Model):
    """
    Line-level detail for supplier invoices (spec 3.17 / SupplierInvoiceLine entity).
    Links to GRNLine for quantity/rate reconciliation.
    """
    invoice = models.ForeignKey("SupplierInvoice", on_delete=models.CASCADE, related_name="lines")
    grn_line = models.ForeignKey(GRNLine, null=True, blank=True, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    description = models.CharField(max_length=200, blank=True)
    accepted_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    rate_agreement = models.ForeignKey(
        "SupplierPriceAgreement", null=True, blank=True, on_delete=models.PROTECT, related_name="invoice_lines"
    )
    agreed_rate_snapshot = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    rate_variance_amount = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    rate_variance_percentage = models.DecimalField(max_digits=9, decimal_places=4, default=Decimal("0.0000"))
    rate_override_reason = models.TextField(blank=True)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    def save(self, *args, **kwargs):
        self.line_total = (self.accepted_quantity * self.unit_cost) - self.discount_amount + self.tax_amount
        super().save(*args, **kwargs)


# ── PHYSICAL STOCK COUNT LINES ────────────────────────────────────────────────

class PhysicalStockCount(AuditStampedModel):
    """
    Physical stock count header (spec 3.45).
    """
    class CountType(models.TextChoices):
        FULL = "full", "Full Count"
        CYCLE = "cycle", "Cycle Count"
        ITEM = "item", "Item-Wise Count"
        BATCH = "batch", "Batch-Wise Count"
        WAREHOUSE = "warehouse", "Warehouse-Wise Count"

    number = models.CharField(max_length=40, unique=True)
    count_date = models.DateField()
    count_type = models.CharField(max_length=20, choices=CountType.choices, default=CountType.FULL)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.PROTECT)
    freeze_stock = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=DocumentState.choices, default=DocumentState.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="psc_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.number


class PhysicalStockCountLine(models.Model):
    """
    Line per batch in a physical stock count (spec 3.45 / PhysicalStockCountLine entity)."""
    count = models.ForeignKey(PhysicalStockCount, on_delete=models.CASCADE, related_name="lines")
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT)
    system_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    physical_quantity = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    variance = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    variance_value = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    reason = models.TextField(blank=True)
    adjustment_number = models.CharField(max_length=40, blank=True)

    def compute_variance(self):
        if self.physical_quantity is not None:
            self.variance = self.physical_quantity - self.system_quantity
            self.variance_value = self.variance * self.batch.unit_cost


# ── OPENING BALANCE LINE ──────────────────────────────────────────────────────

class OpeningBalanceLine(models.Model):
    """
    Line item within an OpeningBalance document (spec 3.54 / OpeningBalanceLine entity).
    Each line represents one batch/account opening entry.
    """
    opening_balance = models.ForeignKey("OpeningBalance", on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.PROTECT)
    batch_number = models.CharField(max_length=80, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    expiry_date = models.DateField(null=True, blank=True)
    remarks = models.CharField(max_length=200, blank=True)
    batch_created = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT)

    def save(self, *args, **kwargs):
        if not self.amount and self.quantity and self.unit_cost:
            self.amount = self.quantity * self.unit_cost
        super().save(*args, **kwargs)


# ── SUPPLIER PAYMENT ALLOCATION ───────────────────────────────────────────────

class SupplierPaymentAllocation(models.Model):
    """
    Allocation of a supplier payment or advance against specific invoices.
    Spec 3.19 / SupplierPaymentAllocation entity.
    """
    payment = models.ForeignKey(SupplierPayment, on_delete=models.CASCADE, related_name="payment_allocations")
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT)
    allocated_amount = models.DecimalField(max_digits=18, decimal_places=2)
    allocation_type = models.CharField(
        max_length=20,
        choices=[("payment","Payment"),("advance_adjustment","Advance Adjustment"),("debit_note","Debit Note")],
        default="payment"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("payment", "invoice")]

    def __str__(self) -> str:
        return f"{self.payment.number} → {self.invoice.number}: {self.allocated_amount}"


class SupplierPriceAgreement(AuditStampedModel):
    class ItemType(models.TextChoices):
        RAW_SPICE = "raw_spice", "Raw Spice"
        PACKAGING_MATERIAL = "packaging_material", "Packaging Material"
        POWDER_PRODUCT = "powder_product", "Powder Product"
        SERVICE = "service", "Service"

    class RateType(models.TextChoices):
        FIXED = "fixed", "Fixed"
        SEASONAL = "seasonal", "Seasonal"
        NEGOTIATED = "negotiated", "Negotiated"
        SPOT = "spot", "Spot"
        CONTRACT = "contract", "Contract"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        APPROVED = "approved", "Approved"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded"
        CANCELLED = "cancelled", "Cancelled"

    agreement_number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="price_agreements")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="supplier_price_agreements")
    item_type = models.CharField(max_length=30, choices=ItemType.choices)
    agreed_rate = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=3, default="PKR")
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    minimum_quantity = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    maximum_quantity = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    effective_date = models.DateField()
    expiry_date = models.DateField()
    rate_type = models.CharField(max_length=20, choices=RateType.choices, default=RateType.FIXED)
    payment_terms_reference = models.CharField(max_length=160, blank=True)
    delivery_terms_reference = models.CharField(max_length=160, blank=True)
    quality_grade_reference = models.CharField(max_length=120, blank=True)
    tolerance_percentage = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.000"))
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="price_agreements_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-effective_date", "supplier__code", "product__code"]
        indexes = [
            models.Index(fields=["supplier", "product", "unit", "status"], name="idx_rate_lookup"),
            models.Index(fields=["effective_date", "expiry_date"], name="idx_rate_validity"),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(agreed_rate__gt=0), name="ck_rate_agreed_positive"),
            models.CheckConstraint(check=models.Q(expiry_date__gte=models.F("effective_date")), name="ck_rate_valid_dates"),
            models.CheckConstraint(check=models.Q(tolerance_percentage__gte=0), name="ck_rate_tolerance_nonneg"),
        ]

    def clean(self):
        if self.maximum_quantity is not None and self.minimum_quantity is not None:
            if self.maximum_quantity < self.minimum_quantity:
                raise ValidationError("Maximum quantity cannot be less than minimum quantity.")

    def __str__(self) -> str:
        return f"{self.agreement_number} / {self.supplier.code} / {self.product.code}"


class DailyProductionLog(AuditStampedModel):
    class Shift(models.TextChoices):
        MORNING = "morning", "Morning"
        EVENING = "evening", "Evening"
        NIGHT = "night", "Night"
        GENERAL = "general", "General"
        CUSTOM = "custom", "Custom"

    class IssueCategory(models.TextChoices):
        NONE = "none", "None"
        MACHINE = "machine_issue", "Machine Issue"
        LABOR = "labor_issue", "Labor Issue"
        MATERIAL_QUALITY = "material_quality_issue", "Material Quality Issue"
        PACKAGING = "packaging_issue", "Packaging Issue"
        POWER = "power_issue", "Power Issue"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        LOCKED = "locked", "Locked"

    log_number = models.CharField(max_length=40, unique=True)
    log_date = models.DateField(default=timezone.localdate)
    shift = models.CharField(max_length=20, choices=Shift.choices, default=Shift.GENERAL)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="production_logs_supervised"
    )
    operator = models.CharField(max_length=120, blank=True)
    machine = models.CharField(max_length=120, blank=True)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.PROTECT)
    production_order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="shift_logs"
    )
    packing_order = models.ForeignKey(
        PackingOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="shift_logs"
    )
    raw_material_batch = models.ForeignKey(
        StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="raw_shift_logs"
    )
    powder_batch = models.ForeignKey(
        StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="powder_shift_logs"
    )
    finished_goods_batch = models.ForeignKey(
        StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="finished_shift_logs"
    )
    raw_quantity_issued = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    powder_quantity_received = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    finished_quantity_packed = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    grinding_wastage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    packing_wastage_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    downtime_minutes = models.PositiveIntegerField(default=0)
    issue_category = models.CharField(max_length=30, choices=IssueCategory.choices, default=IssueCategory.NONE)
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="production_logs_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-log_date", "shift", "log_number"]
        indexes = [
            models.Index(fields=["log_date", "shift"], name="idx_prodlog_date_shift"),
            models.Index(fields=["status"], name="idx_prodlog_status"),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(raw_quantity_issued__gte=0), name="ck_prodlog_raw_nonneg"),
            models.CheckConstraint(check=models.Q(powder_quantity_received__gte=0), name="ck_prodlog_powder_nonneg"),
            models.CheckConstraint(check=models.Q(finished_quantity_packed__gte=0), name="ck_prodlog_finished_nonneg"),
        ]

    @property
    def yield_percentage(self) -> Decimal:
        if not self.raw_quantity_issued:
            return Decimal("0.00")
        return (self.powder_quantity_received / self.raw_quantity_issued * Decimal("100")).quantize(Decimal("0.01"))

    @property
    def wastage_percentage(self) -> Decimal:
        if not self.raw_quantity_issued:
            return Decimal("0.00")
        total = self.grinding_wastage_quantity + self.packing_wastage_quantity
        return (total / self.raw_quantity_issued * Decimal("100")).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return self.log_number


class CustomerDistributor(AuditStampedModel):
    class CustomerType(models.TextChoices):
        RETAILER = "retailer", "Retailer"
        DISTRIBUTOR = "distributor", "Distributor"
        WHOLESALER = "wholesaler", "Wholesaler"
        RESTAURANT = "restaurant", "Restaurant"
        CATERER = "caterer", "Caterer"
        INSTITUTION = "institution", "Institution"
        ECOMMERCE = "ecommerce", "Ecommerce"
        EXPORT_BUYER = "export_buyer", "Export Buyer"
        WALK_IN = "walk_in", "Walk In"
        OTHER = "other", "Other"

    class SalesChannel(models.TextChoices):
        RETAIL = "retail", "Retail"
        WHOLESALE = "wholesale", "Wholesale"
        DISTRIBUTOR = "distributor", "Distributor"
        HORECA = "horeca", "HORECA"
        ECOMMERCE = "ecommerce", "Ecommerce"
        EXPORT = "export", "Export"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        BLOCKED = "blocked", "Blocked"

    code = models.CharField(max_length=40, unique=True)
    business_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=120, blank=True)
    customer_type = models.CharField(max_length=30, choices=CustomerType.choices)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    province_state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="Pakistan")
    tax_registration_number = models.CharField(max_length=80, blank=True)
    local_tax_number = models.CharField(max_length=80, blank=True, help_text="NTN/STRN or local equivalent")
    credit_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    credit_days = models.PositiveIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=160, blank=True)
    preferred_price_list = models.CharField(max_length=120, blank=True)
    sales_channel = models.CharField(max_length=20, choices=SalesChannel.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["customer_type", "sales_channel", "status"], name="idx_customer_segment"),
            models.Index(fields=["city", "country"], name="idx_customer_location"),
            models.Index(fields=["phone"], name="idx_customer_phone"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(credit_limit__isnull=True) | models.Q(credit_limit__gte=0),
                name="ck_customer_credit_nonneg",
            ),
            models.UniqueConstraint(Lower("code"), name="uq_customer_code_ci"),
        ]

    def clean(self):
        self.code = self.code.strip().upper()
        if not self.code:
            raise ValidationError({"code": "Customer code is required."})

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} - {self.business_name}"


class CustomerShippingAddress(AuditStampedModel):
    customer = models.ForeignKey(CustomerDistributor, on_delete=models.CASCADE, related_name="shipping_addresses")
    address_label = models.CharField(max_length=80)
    recipient_contact = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=80)
    province_state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="Pakistan")
    is_default = models.BooleanField(default=False)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["customer__code", "-is_default", "address_label"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "address_label"], name="uq_customer_address_label")
        ]


class ScheduledTaskConfig(AuditStampedModel):
    job_name = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=True)
    frequency_description = models.CharField(max_length=160)
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)
    command_name = models.CharField(max_length=100)
    remarks = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.job_name


class ScheduledTaskLock(TimeStampedModel):
    class Status(models.TextChoices):
        ACQUIRED = "acquired", "Acquired"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"
        STALE = "stale", "Stale"

    job_name = models.CharField(max_length=100, unique=True)
    lock_key = models.CharField(max_length=180, unique=True)
    locked_by = models.CharField(max_length=180)
    locked_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACQUIRED)

    class Meta:
        indexes = [models.Index(fields=["status", "expires_at"], name="idx_tasklock_status_exp")]

    def __str__(self):
        return f"{self.job_name}: {self.status}"


class ScheduledTaskLog(models.Model):
    class JobType(models.TextChoices):
        EXPIRY_REFRESH = "expiry_refresh", "Expiry Refresh"
        OVERDUE_REFRESH = "overdue_refresh", "Overdue Refresh"
        BACKUP = "backup", "Backup"
        HEALTH_CHECK = "health_check", "Health Check"
        REPORT_SNAPSHOT = "report_snapshot", "Report Snapshot"
        CLEANUP = "cleanup", "Cleanup"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class TriggeredBy(models.TextChoices):
        SYSTEM = "system", "System"
        MANUAL = "manual", "Manual"
        CRON = "cron", "Cron"
        MANAGEMENT_COMMAND = "management_command", "Management Command"

    job_name = models.CharField(max_length=100)
    job_type = models.CharField(max_length=30, choices=JobType.choices)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)
    duration = models.DurationField(null=True, blank=True)
    message = models.TextField(blank=True)
    error_details = models.TextField(blank=True)
    triggered_by = models.CharField(max_length=30, choices=TriggeredBy.choices, default=TriggeredBy.SYSTEM)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["job_type", "status", "started_at"], name="idx_joblog_type_status"),
        ]
