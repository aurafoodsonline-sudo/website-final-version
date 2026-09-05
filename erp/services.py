from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    AuditEvent,
    AdjustmentDocument,
    CashBankAccount,
    DocumentSequence,
    DocumentState,
    GRN,
    GRNLine,
    OpeningBalance,
    OpeningBalanceLine,
    PackagingBOM,
    PackingOrder,
    Product,
    ProductionOrder,
    PurchaseOrder,
    PurchaseOrderLine,
    QualityInspection,
    StockBatch,
    StockLedgerEntry,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierLedgerEntry,
    SupplierPayment,
    Warehouse,
)


ZERO_QTY = Decimal("0.000")
ZERO_MONEY = Decimal("0.00")


def _amount_in_words(amount: Decimal) -> str:
    """
    Convert a Decimal amount to words for payment vouchers (spec 3.19/3.20).
    Uses basic units only — PKR context. Extend with a library for full coverage.
    """
    try:
        units = [
            "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
            "Sixteen", "Seventeen", "Eighteen", "Nineteen",
        ]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

        def _below_thousand(n: int) -> str:
            if n == 0:
                return ""
            elif n < 20:
                return units[n]
            elif n < 100:
                return tens[n // 10] + (" " + units[n % 10] if n % 10 else "")
            else:
                return units[n // 100] + " Hundred" + (" " + _below_thousand(n % 100) if n % 100 else "")

        rupees = int(amount)
        paisas = round((amount - rupees) * 100)

        if rupees == 0:
            words = "Zero"
        elif rupees < 1000:
            words = _below_thousand(rupees)
        elif rupees < 100000:
            words = _below_thousand(rupees // 1000) + " Thousand" + (" " + _below_thousand(rupees % 1000) if rupees % 1000 else "")
        elif rupees < 10000000:
            words = _below_thousand(rupees // 100000) + " Lakh" + (" " + _below_thousand((rupees % 100000) // 1000) + " Thousand" if (rupees % 100000) // 1000 else "") + (" " + _below_thousand(rupees % 1000) if rupees % 1000 else "")
        else:
            words = _below_thousand(rupees // 10000000) + " Crore" + (" " + _below_thousand((rupees % 10000000) // 100000) + " Lakh" if (rupees % 10000000) // 100000 else "") + (" " + _below_thousand(rupees % 1000) if rupees % 1000 else "")

        result = words + " Rupees"
        if paisas:
            result += f" and {_below_thousand(paisas)} Paisas"
        return result + " Only"
    except Exception:
        return str(amount)


@dataclass(frozen=True)
class PurchaseLineInput:
    product: Product
    ordered_quantity: Decimal
    received_quantity: Decimal
    accepted_quantity: Decimal
    unit_cost: Decimal
    batch_number: str
    manufacturing_date: object | None = None
    expiry_date: object | None = None
    rejected_quantity: Decimal = ZERO_QTY
    rate_override_reason: str = ""


def _audit(event_type: str, source_type: str, source_number: str, message: str, user=None, **metadata) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=user,
        event_type=event_type,
        source_document_type=source_type,
        source_document_number=source_number,
        message=message,
        metadata=metadata,
    )


def next_document_number(prefix: str) -> str:
    sequence, _ = DocumentSequence.objects.select_for_update().get_or_create(prefix=prefix, defaults={"next_number": 1})
    value = sequence.next_number
    sequence.next_number += 1
    sequence.save(update_fields=["next_number"])
    return f"{prefix}-{value:06d}"


def _ensure_decimal_positive(value: Decimal, label: str) -> None:
    if value <= 0:
        raise ValidationError(f"{label} must be greater than zero.")


def _post_supplier_ledger(
    *,
    supplier: Supplier,
    source_type: str,
    source_number: str,
    balance_effect: str,
    payable_effect: Decimal = ZERO_MONEY,
    advance_effect: Decimal = ZERO_MONEY,
    cash_bank_effect: Decimal = ZERO_MONEY,
    debit_amount: Decimal = ZERO_MONEY,
    credit_amount: Decimal = ZERO_MONEY,
    description: str = "",
    user=None,
) -> SupplierLedgerEntry:
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    supplier.payable_balance += payable_effect
    supplier.advance_balance += advance_effect
    if supplier.payable_balance < 0:
        raise ValidationError("Supplier payable balance cannot become negative through this posting.")
    if supplier.advance_balance < 0:
        raise ValidationError("Supplier advance balance cannot become negative.")
    supplier.save(update_fields=["payable_balance", "advance_balance", "updated_at"])
    entry = SupplierLedgerEntry.objects.create(
        supplier=supplier,
        source_document_type=source_type,
        source_document_number=source_number,
        balance_effect=balance_effect,
        payable_effect=payable_effect,
        advance_effect=advance_effect,
        cash_bank_effect=cash_bank_effect,
        debit_amount=debit_amount,
        credit_amount=credit_amount,
        net_amount=payable_effect - advance_effect,
        running_payable_balance=supplier.payable_balance,
        running_advance_balance=supplier.advance_balance,
        description=description,
        created_by=user,
        posted_by=user,
    )
    _audit("supplier_ledger_posted", source_type, source_number, description or balance_effect, user)
    return entry


def _stock_batch_type(product: Product) -> str:
    if product.product_type == Product.ProductType.RAW:
        return StockBatch.BatchType.RAW
    if product.product_type == Product.ProductType.POWDER:
        return StockBatch.BatchType.POWDER
    if product.product_type == Product.ProductType.FINISHED:
        return StockBatch.BatchType.FINISHED
    if product.product_type == Product.ProductType.PACKAGING:
        return StockBatch.BatchType.PACKAGING
    raise ValidationError("Unsupported product type.")


def _stock_in(
    *,
    product: Product,
    batch_number: str,
    warehouse: Warehouse,
    quantity: Decimal,
    unit_cost: Decimal,
    source_type: str,
    source_number: str,
    supplier: Supplier | None = None,
    manufacturing_date=None,
    packing_date=None,
    expiry_date=None,
    parent_batch: StockBatch | None = None,
    user=None,
) -> StockBatch:
    _ensure_decimal_positive(quantity, "Stock quantity")
    batch, _ = StockBatch.objects.select_for_update().get_or_create(
        product=product,
        batch_number=batch_number,
        batch_type=_stock_batch_type(product),
        defaults={
            "supplier": supplier,
            "source_document_type": source_type,
            "source_document_number": source_number,
            "warehouse": warehouse,
            "unit_cost": unit_cost,
            "manufacturing_date": manufacturing_date,
            "packing_date": packing_date,
            "expiry_date": expiry_date,
            "parent_batch": parent_batch,
            "created_by": user,
        },
    )
    batch.quantity_on_hand += quantity
    batch.unit_cost = unit_cost
    if expiry_date:
        batch.expiry_date = expiry_date
    batch.save(update_fields=["quantity_on_hand", "unit_cost", "expiry_date", "updated_at"])
    StockLedgerEntry.objects.create(
        product=product,
        batch=batch,
        warehouse=warehouse,
        direction=StockLedgerEntry.Direction.IN,
        quantity=quantity,
        unit_cost=unit_cost,
        source_document_type=source_type,
        source_document_number=source_number,
        created_by=user,
        description=f"Stock in from {source_type}",
    )
    return batch


def _stock_out(
    *,
    batch: StockBatch,
    quantity: Decimal,
    source_type: str,
    source_number: str,
    user=None,
    allow_blocked: bool = False,
) -> None:
    _ensure_decimal_positive(quantity, "Stock issue quantity")
    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    today = timezone.localdate()
    if batch.is_blocked and not allow_blocked:
        raise ValidationError("Blocked stock cannot be issued through normal posting.")
    if batch.expiry_date and batch.expiry_date < today and not allow_blocked:
        raise ValidationError("Expired stock cannot be issued through normal posting.")
    if batch.quantity_on_hand < quantity:
        raise ValidationError("Insufficient available stock.")
    batch.quantity_on_hand -= quantity
    batch.save(update_fields=["quantity_on_hand", "updated_at"])
    StockLedgerEntry.objects.create(
        product=batch.product,
        batch=batch,
        warehouse=batch.warehouse,
        direction=StockLedgerEntry.Direction.OUT,
        quantity=quantity,
        unit_cost=batch.unit_cost,
        source_document_type=source_type,
        source_document_number=source_number,
        created_by=user,
        description=f"Stock out to {source_type}",
    )


@transaction.atomic
def dispatch_finished_goods_stock(*, batch: StockBatch, quantity: Decimal, source_number: str, user=None):
    """Public sales boundary: post a finished-goods issue and return its immutable ledger row."""
    if batch.batch_type != StockBatch.BatchType.FINISHED or batch.product.product_type != Product.ProductType.FINISHED:
        raise ValidationError("Sales dispatch accepts finished-goods batches only.")
    _stock_out(
        batch=batch,
        quantity=quantity,
        source_type="SALES_DISPATCH",
        source_number=source_number,
        user=user,
    )
    return StockLedgerEntry.objects.get(
        batch=batch,
        source_document_type="SALES_DISPATCH",
        source_document_number=source_number,
    )


@transaction.atomic
def receive_approved_sales_return_stock(*, batch: StockBatch, quantity: Decimal, source_number: str, user=None):
    """Return QA-approved goods to their original finished batch and post an ERP stock-in ledger row."""
    batch = StockBatch.objects.select_for_update().select_related("product", "warehouse").get(pk=batch.pk)
    if batch.batch_type != StockBatch.BatchType.FINISHED or batch.product.product_type != Product.ProductType.FINISHED:
        raise ValidationError("Sales returns can be restored only to finished-goods batches.")
    if batch.is_blocked or batch.stock_state != StockBatch.StockState.ACCEPTED:
        raise ValidationError("Returned goods cannot be restored to a blocked or non-accepted batch.")
    if batch.expiry_date and batch.expiry_date < timezone.localdate():
        raise ValidationError("Expired returned goods cannot be restored to sellable stock.")
    _stock_in(
        product=batch.product, batch_number=batch.batch_number, warehouse=batch.warehouse,
        quantity=quantity, unit_cost=batch.unit_cost, source_type="SALES_RETURN_QA",
        source_number=source_number, manufacturing_date=batch.manufacturing_date,
        packing_date=batch.packing_date, expiry_date=batch.expiry_date, user=user,
    )
    return StockLedgerEntry.objects.get(
        batch=batch, source_document_type="SALES_RETURN_QA", source_document_number=source_number,
    )


@transaction.atomic
def create_purchase_order(*, supplier: Supplier, lines: list[PurchaseLineInput], user=None) -> PurchaseOrder:
    from .domain_services import evaluate_supplier_rate

    number = next_document_number("PO")
    po = PurchaseOrder.objects.create(number=number, supplier=supplier, created_by=user)
    for line in lines:
        rate = evaluate_supplier_rate(
            supplier=supplier,
            product=line.product,
            actual_rate=line.unit_cost,
            transaction_date=po.order_date,
            quantity=line.ordered_quantity,
            override_reason=line.rate_override_reason,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=po,
            product=line.product,
            quantity=line.ordered_quantity,
            unit_cost=line.unit_cost,
            rate_agreement=rate["agreement"],
            agreed_rate_snapshot=rate["agreed_rate"],
            rate_variance_amount=rate["variance_amount"],
            rate_variance_percentage=rate["variance_percentage"],
            rate_override_reason=rate["override_reason"],
        )
    _audit("purchase_order_created", "PO", number, "Purchase order created", user)
    return po


@transaction.atomic
def submit_purchase_order(*, order, user=None):
    """Draft → Pending Approval. Spec 10.1."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status != "draft":
        raise ValidationError(f"Only draft POs can be submitted. Current: {order.status}")
    order.status = "pending_approval"
    order.updated_by = user
    order.save(update_fields=["status", "updated_by", "updated_at"])
    _audit("po_submitted", "PO", order.number, "PO submitted for approval", user)
    return order


@transaction.atomic
def approve_purchase_order(*, order, user=None):
    """Pending Approval → Approved. Spec 10.1."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status not in ("draft", "pending_approval"):
        raise ValidationError(f"Cannot approve PO from status '{order.status}'.")
    order.status = "approved"
    order.updated_by = user
    order.save(update_fields=["status", "updated_by", "updated_at"])
    _audit("po_approved", "PO", order.number, "PO approved", user)
    return order


@transaction.atomic
def cancel_purchase_order(*, order, reason: str, user=None):
    """Cancel PO. Spec 10.1: approved only if no active GRN."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status in ("fully_received", "closed", "cancelled"):
        raise ValidationError(f"Cannot cancel PO from status '{order.status}'.")
    if order.status == "approved":
        active_grns = GRN.objects.filter(purchase_order=order).exclude(status="cancelled").count()
        if active_grns:
            raise ValidationError(f"PO has {active_grns} active GRN(s). Cannot cancel.")
    if not reason or not reason.strip():
        raise ValidationError("Cancellation reason is required.")
    order.status = "cancelled"
    order.updated_by = user
    order.save(update_fields=["status", "updated_by", "updated_at"])
    _audit("po_cancelled", "PO", order.number, reason, user)
    return order


@transaction.atomic
def create_grn(
    *,
    supplier: Supplier,
    warehouse: Warehouse,
    lines: list[PurchaseLineInput],
    purchase_order: PurchaseOrder | None = None,
    user=None,
) -> GRN:
    from .domain_services import evaluate_supplier_rate

    number = next_document_number("GRN")
    grn = GRN.objects.create(number=number, supplier=supplier, purchase_order=purchase_order, created_by=user)
    payable = ZERO_MONEY
    shortage = ZERO_MONEY
    for line in lines:
        if line.product.product_type not in {Product.ProductType.RAW, Product.ProductType.PACKAGING}:
            raise ValidationError("GRN accepts raw spices or packaging material only.")
        if line.accepted_quantity + line.rejected_quantity > line.received_quantity:
            raise ValidationError("Accepted plus rejected quantity cannot exceed received quantity.")
        shortage_qty = max(line.ordered_quantity - line.received_quantity, ZERO_QTY)
        rate = evaluate_supplier_rate(
            supplier=supplier,
            product=line.product,
            actual_rate=line.unit_cost,
            transaction_date=grn.grn_date,
            quantity=line.accepted_quantity,
            override_reason=line.rate_override_reason,
        )
        payable += line.accepted_quantity * line.unit_cost
        shortage += shortage_qty * line.unit_cost
        GRNLine.objects.create(
            grn=grn,
            product=line.product,
            ordered_quantity=line.ordered_quantity,
            received_quantity=line.received_quantity,
            accepted_quantity=line.accepted_quantity,
            rejected_quantity=line.rejected_quantity,
            shortage_quantity=shortage_qty,
            unit_cost=line.unit_cost,
            rate_agreement=rate["agreement"],
            agreed_rate_snapshot=rate["agreed_rate"],
            rate_variance_amount=rate["variance_amount"],
            rate_variance_percentage=rate["variance_percentage"],
            rate_override_reason=rate["override_reason"],
            batch_number=line.batch_number,
            manufacturing_date=line.manufacturing_date,
            expiry_date=line.expiry_date,
        )
    grn.shortage_amount = shortage
    grn.payable_amount = payable
    grn.status = DocumentState.QUALITY_PENDING  # Spec 10.2: Draft→Received→Quality Pending
    grn.save(update_fields=["shortage_amount", "payable_amount", "status", "updated_at"])
    _audit("grn_created", "GRN", number, "GRN created — quality inspection pending", user, warehouse_id=warehouse.pk)
    return grn


@transaction.atomic
def post_quality_inspection(*, grn: GRN, deduction_amount: Decimal = ZERO_MONEY, user=None,
                              quality_decision: str = "accepted", **criteria) -> QualityInspection:
    grn = GRN.objects.select_for_update().get(pk=grn.pk)
    if grn.status not in (DocumentState.DRAFT, DocumentState.QUALITY_PENDING):
        raise ValidationError(
            f"Quality inspection can only be posted for GRNs in draft/quality_pending state. "
            f"Current: {grn.status}"
        )
    inspection = QualityInspection.objects.create(
        grn=grn,
        deduction_amount=deduction_amount,
        quality_decision=quality_decision,
        status=DocumentState.POSTED,
        created_by=user,
        **criteria,
    )
    grn.quality_deduction_amount = deduction_amount
    grn.payable_amount -= deduction_amount
    if grn.payable_amount < 0:
        raise ValidationError("Quality deduction cannot exceed payable amount.")
    grn.save(update_fields=["quality_deduction_amount", "payable_amount", "updated_at"])
    _audit("quality_inspection_posted", "GRN", grn.number, "Quality inspection posted", user)
    return inspection


@transaction.atomic
def approve_grn(*, grn: GRN, warehouse: Warehouse, create_invoice: bool = True, user=None) -> GRN:
    grn = GRN.objects.select_for_update().get(pk=grn.pk)
    if grn.status not in (DocumentState.DRAFT, DocumentState.QUALITY_PENDING):
        raise ValidationError(
            f"GRN cannot be approved from status '{grn.status}'. "
            "Only draft/quality_pending GRNs can be approved."
        )
    for line in grn.lines.select_related("product"):
        if line.accepted_quantity > 0:
            _stock_in(
                product=line.product,
                batch_number=line.batch_number,
                warehouse=warehouse,
                quantity=line.accepted_quantity,
                unit_cost=line.unit_cost,
                source_type="GRN",
                source_number=grn.number,
                supplier=grn.supplier,
                manufacturing_date=line.manufacturing_date,
                expiry_date=line.expiry_date,
                user=user,
            )
    grn.status = DocumentState.APPROVED
    grn.approved_by = user
    grn.approved_at = timezone.now()
    grn.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    if create_invoice and grn.payable_amount > 0:
        post_supplier_invoice(supplier=grn.supplier, grn=grn, amount=grn.payable_amount, user=user)
    _audit("grn_approved", "GRN", grn.number, "GRN approved and stock posted", user)
    return grn


@transaction.atomic
def post_supplier_invoice(*, supplier: Supplier, amount: Decimal, grn: GRN | None = None, user=None) -> SupplierInvoice:
    _ensure_decimal_positive(amount, "Supplier invoice amount")
    number = next_document_number("SIN")
    due_date = timezone.localdate() + timedelta(days=supplier.payment_terms_days)
    invoice = SupplierInvoice.objects.create(
        number=number,
        supplier=supplier,
        grn=grn,
        amount=amount,
        due_date=due_date,
        created_by=user,
    )
    if grn:
        for grn_line in grn.lines.select_related("product", "rate_agreement"):
            quantity = grn_line.final_payable_quantity or grn_line.accepted_quantity
            SupplierInvoiceLine.objects.create(
                invoice=invoice,
                grn_line=grn_line,
                product=grn_line.product,
                accepted_quantity=quantity,
                unit_cost=grn_line.unit_cost,
                rate_agreement=grn_line.rate_agreement,
                agreed_rate_snapshot=grn_line.agreed_rate_snapshot,
                rate_variance_amount=grn_line.rate_variance_amount,
                rate_variance_percentage=grn_line.rate_variance_percentage,
                rate_override_reason=grn_line.rate_override_reason,
            )
    _post_supplier_ledger(
        supplier=supplier,
        source_type="SUPPLIER_INVOICE",
        source_number=number,
        balance_effect="increase_payable",
        payable_effect=amount,
        credit_amount=amount,
        description="Supplier invoice posted",
        user=user,
    )
    return invoice


@transaction.atomic
def post_supplier_advance(*, supplier: Supplier, cash_bank_account: CashBankAccount, amount: Decimal, user=None) -> SupplierPayment:
    _ensure_decimal_positive(amount, "Advance amount")
    number = next_document_number("SPAY")
    account = CashBankAccount.objects.select_for_update().get(pk=cash_bank_account.pk)
    if account.balance < amount:
        raise ValidationError("Cash/bank account has insufficient funds for advance.")
    account.balance -= amount
    account.save(update_fields=["balance", "updated_at"])
    payment = SupplierPayment.objects.create(
        number=number,
        supplier=supplier,
        cash_bank_account=account,
        payment_type=SupplierPayment.PaymentType.ADVANCE,
        amount=amount,
        amount_in_words=_amount_in_words(amount),
        prepared_by=user,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _post_supplier_ledger(
        supplier=supplier,
        source_type="SUPPLIER_ADVANCE",
        source_number=number,
        balance_effect="increase_advance",
        advance_effect=amount,
        debit_amount=amount,
        cash_bank_effect=-amount,
        description="Supplier advance posted",
        user=user,
    )
    return payment


@transaction.atomic
def post_supplier_payment(
    *,
    supplier: Supplier,
    cash_bank_account: CashBankAccount,
    invoice: SupplierInvoice,
    amount: Decimal,
    user=None,
) -> SupplierPayment:
    _ensure_decimal_positive(amount, "Payment amount")
    invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != DocumentState.POSTED:
        raise ValidationError("Only posted invoices may be paid.")
    if invoice.outstanding_amount < amount:
        raise ValidationError("Payment amount exceeds invoice outstanding amount.")
    account = CashBankAccount.objects.select_for_update().get(pk=cash_bank_account.pk)
    if account.balance < amount:
        raise ValidationError("Cash/bank account has insufficient funds.")
    account.balance -= amount
    account.save(update_fields=["balance", "updated_at"])
    number = next_document_number("SPAY")
    payment = SupplierPayment.objects.create(
        number=number,
        supplier=supplier,
        cash_bank_account=account,
        payment_type=SupplierPayment.PaymentType.INVOICE,
        amount=amount,
        created_by=user,
    )
    payment.allocations.create(invoice=invoice, amount=amount)
    invoice.paid_amount += amount
    # Update invoice status based on payment position
    if invoice.outstanding_amount <= Decimal("0.01"):
        invoice.status = "fully_paid"
    elif invoice.paid_amount > 0:
        invoice.status = "partially_paid"
    invoice.save(update_fields=["paid_amount", "status", "updated_at"])
    _post_supplier_ledger(
        supplier=supplier,
        source_type="SUPPLIER_PAYMENT",
        source_number=number,
        balance_effect="decrease_payable",
        payable_effect=-amount,
        debit_amount=amount,
        cash_bank_effect=-amount,
        description=f"Payment allocated to {invoice.number}",
        user=user,
    )
    return payment


@transaction.atomic
def adjust_supplier_advance(*, supplier: Supplier, invoice: SupplierInvoice, amount: Decimal, user=None) -> SupplierPayment:
    _ensure_decimal_positive(amount, "Advance adjustment amount")
    invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
    supplier_locked = Supplier.objects.select_for_update().get(pk=supplier.pk)
    if supplier_locked.advance_balance < amount:
        raise ValidationError("Supplier advance balance is insufficient.")
    if invoice.outstanding_amount < amount:
        raise ValidationError("Advance adjustment exceeds invoice outstanding amount.")
    number = next_document_number("SADJ")
    payment = SupplierPayment.objects.create(
        number=number,
        supplier=supplier_locked,
        payment_type=SupplierPayment.PaymentType.ADJUSTMENT,
        amount=amount,
        created_by=user,
        reason=f"Advance adjusted against {invoice.number}",
    )
    payment.allocations.create(invoice=invoice, amount=amount)
    invoice.advance_adjusted_amount += amount
    invoice.save(update_fields=["advance_adjusted_amount", "updated_at"])
    _post_supplier_ledger(
        supplier=supplier_locked,
        source_type="SUPPLIER_ADVANCE_ADJUSTMENT",
        source_number=number,
        balance_effect="decrease_advance_and_payable",
        payable_effect=-amount,
        advance_effect=-amount,
        debit_amount=amount,
        description=f"Advance adjusted to {invoice.number}",
        user=user,
    )
    return payment


@transaction.atomic
def reverse_supplier_payment(*, payment: SupplierPayment, reason: str, user=None) -> SupplierPayment:
    payment = SupplierPayment.objects.select_for_update().select_related("supplier", "cash_bank_account").get(pk=payment.pk)
    if payment.status == DocumentState.REVERSED:
        raise ValidationError("Supplier payment cannot be reversed twice.")
    number = next_document_number("SREV")
    reversal = SupplierPayment.objects.create(
        number=number,
        supplier=payment.supplier,
        cash_bank_account=payment.cash_bank_account,
        payment_type=SupplierPayment.PaymentType.REVERSAL,
        amount=payment.amount,
        reversal_of=payment,
        reason=reason,
        created_by=user,
    )
    if payment.cash_bank_account_id:
        account = CashBankAccount.objects.select_for_update().get(pk=payment.cash_bank_account_id)
        account.balance += payment.amount
        account.save(update_fields=["balance", "updated_at"])
    if payment.payment_type == SupplierPayment.PaymentType.INVOICE:
        for allocation in payment.allocations.select_related("invoice"):
            invoice = SupplierInvoice.objects.select_for_update().get(pk=allocation.invoice_id)
            invoice.paid_amount -= allocation.amount
            if invoice.paid_amount < 0:
                raise ValidationError("Payment reversal would make paid amount negative.")
            invoice.save(update_fields=["paid_amount", "updated_at"])
        _post_supplier_ledger(
            supplier=payment.supplier,
            source_type="SUPPLIER_PAYMENT_REVERSAL",
            source_number=number,
            balance_effect="restore_payable",
            payable_effect=payment.amount,
            credit_amount=payment.amount,
            cash_bank_effect=payment.amount,
            description=reason,
            user=user,
        )
    elif payment.payment_type == SupplierPayment.PaymentType.ADVANCE:
        _post_supplier_ledger(
            supplier=payment.supplier,
            source_type="SUPPLIER_ADVANCE_REVERSAL",
            source_number=number,
            balance_effect="decrease_advance",
            advance_effect=-payment.amount,
            credit_amount=payment.amount,
            cash_bank_effect=payment.amount,
            description=reason,
            user=user,
        )
    elif payment.payment_type == SupplierPayment.PaymentType.ADJUSTMENT:
        for allocation in payment.allocations.select_related("invoice"):
            invoice = SupplierInvoice.objects.select_for_update().get(pk=allocation.invoice_id)
            invoice.advance_adjusted_amount -= allocation.amount
            if invoice.advance_adjusted_amount < 0:
                raise ValidationError("Advance reversal would make adjusted amount negative.")
            invoice.save(update_fields=["advance_adjusted_amount", "updated_at"])
        _post_supplier_ledger(
            supplier=payment.supplier,
            source_type="SUPPLIER_ADVANCE_ADJUSTMENT_REVERSAL",
            source_number=number,
            balance_effect="restore_advance_and_payable",
            payable_effect=payment.amount,
            advance_effect=payment.amount,
            credit_amount=payment.amount,
            description=reason,
            user=user,
        )
    else:
        raise ValidationError("Unsupported payment type for reversal.")
    payment.status = DocumentState.REVERSED
    payment.reversed_by = user
    payment.reversed_at = timezone.now()
    payment.save(update_fields=["status", "reversed_by", "reversed_at", "updated_at"])
    _audit("supplier_payment_reversed", "SUPPLIER_PAYMENT", payment.number, reason, user, reversal_number=number)
    return reversal


@transaction.atomic
def post_debit_note(
    *,
    supplier: Supplier,
    amount: Decimal,
    reason: str,
    invoice: SupplierInvoice | None = None,
    user=None,
) -> AdjustmentDocument:
    _ensure_decimal_positive(amount, "Debit note amount")
    number = next_document_number("DN")
    if invoice:
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.outstanding_amount < amount:
            raise ValidationError("Debit note exceeds invoice outstanding amount.")
        invoice.debit_note_amount += amount
        invoice.save(update_fields=["debit_note_amount", "updated_at"])
    doc = AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.DEBIT_NOTE,
        supplier=supplier,
        amount=amount,
        balance_effect="decrease_payable",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _post_supplier_ledger(
        supplier=supplier,
        source_type="DEBIT_NOTE",
        source_number=number,
        balance_effect="decrease_payable",
        payable_effect=-amount,
        debit_amount=amount,
        description=reason,
        user=user,
    )
    return doc


@transaction.atomic
def post_credit_note(
    *,
    supplier: Supplier,
    amount: Decimal,
    balance_effect: str,
    reason: str,
    invoice: SupplierInvoice | None = None,
    user=None,
) -> AdjustmentDocument:
    _ensure_decimal_positive(amount, "Credit note amount")
    allowed = {
        "increase_payable",
        "decrease_payable",
        "increase_advance",
        "decrease_advance",
        "supplier_refund_due",
        "supplier_replacement_due",
        "informational_only",
    }
    if balance_effect not in allowed:
        raise ValidationError("Unsupported credit note balance effect.")
    payable_effect = ZERO_MONEY
    advance_effect = ZERO_MONEY
    if balance_effect == "increase_payable":
        payable_effect = amount
    elif balance_effect == "decrease_payable":
        payable_effect = -amount
        if invoice:
            invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
            if invoice.outstanding_amount < amount:
                raise ValidationError("Credit note exceeds invoice outstanding amount.")
            invoice.credit_note_amount += amount
            invoice.save(update_fields=["credit_note_amount", "updated_at"])
    elif balance_effect == "increase_advance":
        advance_effect = amount
    elif balance_effect == "decrease_advance":
        advance_effect = -amount
    number = next_document_number("CN")
    doc = AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.CREDIT_NOTE,
        supplier=supplier,
        amount=amount,
        balance_effect=balance_effect,
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )
    if balance_effect != "informational_only":
        _post_supplier_ledger(
            supplier=supplier,
            source_type="CREDIT_NOTE",
            source_number=number,
            balance_effect=balance_effect,
            payable_effect=payable_effect,
            advance_effect=advance_effect,
            debit_amount=amount if payable_effect < 0 or advance_effect > 0 else ZERO_MONEY,
            credit_amount=amount if payable_effect > 0 or advance_effect < 0 else ZERO_MONEY,
            description=reason,
            user=user,
        )
    else:
        _audit("credit_note_informational", "CREDIT_NOTE", number, reason, user)
    return doc


@transaction.atomic
def post_supplier_return(
    *,
    batch: StockBatch,
    quantity: Decimal,
    amount: Decimal,
    reason: str,
    invoice: SupplierInvoice | None = None,
    user=None,
) -> AdjustmentDocument:
    if not batch.supplier_id:
        raise ValidationError("Supplier return requires a supplier-linked batch.")
    number = next_document_number("SRET")
    _stock_out(batch=batch, quantity=quantity, source_type="SUPPLIER_RETURN", source_number=number, user=user, allow_blocked=True)
    if invoice and amount > 0:
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.outstanding_amount < amount:
            raise ValidationError("Supplier return amount exceeds invoice outstanding amount.")
        invoice.debit_note_amount += amount
        invoice.save(update_fields=["debit_note_amount", "updated_at"])
    doc = AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.SUPPLIER_RETURN,
        supplier=batch.supplier,
        product=batch.product,
        batch=batch,
        amount=amount,
        quantity=quantity,
        balance_effect="decrease_payable",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )
    if amount > 0:
        _post_supplier_ledger(
            supplier=batch.supplier,
            source_type="SUPPLIER_RETURN",
            source_number=number,
            balance_effect="decrease_payable",
            payable_effect=-amount,
            debit_amount=amount,
            description=reason,
            user=user,
        )
    return doc


@transaction.atomic
def post_stock_adjustment(
    *,
    batch: StockBatch,
    counted_quantity: Decimal,
    reason: str,
    adjustment_type: str = AdjustmentDocument.AdjustmentType.STOCK_ADJUSTMENT,
    user=None,
) -> AdjustmentDocument:
    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    variance = counted_quantity - batch.quantity_on_hand
    number = next_document_number("ADJ")
    doc = AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=adjustment_type,
        product=batch.product,
        batch=batch,
        quantity=variance,
        amount=abs(variance) * batch.unit_cost,
        balance_effect="stock_variance",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )
    if variance > 0:
        _stock_in(
            product=batch.product,
            batch_number=batch.batch_number,
            warehouse=batch.warehouse,
            quantity=variance,
            unit_cost=batch.unit_cost,
            source_type="STOCK_ADJUSTMENT",
            source_number=number,
            supplier=batch.supplier,
            parent_batch=batch.parent_batch,
            user=user,
        )
    elif variance < 0:
        _stock_out(batch=batch, quantity=abs(variance), source_type="STOCK_ADJUSTMENT", source_number=number, user=user, allow_blocked=True)
    else:
        _audit("stock_count_no_variance", "STOCK_ADJUSTMENT", number, reason, user)
    return doc


@transaction.atomic
def post_physical_stock_count(*, batch: StockBatch, counted_quantity: Decimal, reason: str, user=None) -> AdjustmentDocument:
    return post_stock_adjustment(
        batch=batch,
        counted_quantity=counted_quantity,
        reason=reason,
        adjustment_type=AdjustmentDocument.AdjustmentType.PHYSICAL_COUNT,
        user=user,
    )


@transaction.atomic
def post_repacking(
    *,
    source_batch: StockBatch,
    quantity: Decimal,
    finished_product: Product,
    new_batch_number: str,
    loss_quantity: Decimal = ZERO_QTY,
    reason: str,
    user=None,
) -> AdjustmentDocument:
    if source_batch.batch_type != StockBatch.BatchType.FINISHED:
        raise ValidationError("Repacking requires finished goods source stock.")
    output_quantity = quantity - loss_quantity
    _ensure_decimal_positive(output_quantity, "Repacked output quantity")
    number = next_document_number("RPK")
    _stock_out(batch=source_batch, quantity=quantity, source_type="REPACKING", source_number=number, user=user)
    unit_cost = (quantity * source_batch.unit_cost) / output_quantity
    _stock_in(
        product=finished_product,
        batch_number=new_batch_number,
        warehouse=source_batch.warehouse,
        quantity=output_quantity,
        unit_cost=unit_cost,
        source_type="REPACKING",
        source_number=number,
        parent_batch=source_batch,
        packing_date=timezone.localdate(),
        expiry_date=source_batch.expiry_date,
        user=user,
    )
    return AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.REPACKING,
        product=finished_product,
        batch=source_batch,
        quantity=output_quantity,
        amount=loss_quantity * source_batch.unit_cost,
        balance_effect="repack_finished_goods",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )


@transaction.atomic
def post_relabeling(*, batch: StockBatch, new_label_version: str, reason: str, user=None) -> AdjustmentDocument:
    batch = StockBatch.objects.select_for_update().select_related("product").get(pk=batch.pk)
    old_label = batch.product.label_version
    batch.product.label_version = new_label_version
    batch.product.save(update_fields=["label_version", "updated_at"])
    number = next_document_number("RLB")
    _audit("relabeling_posted", "RELABELING", number, reason, user, old_label=old_label, new_label=new_label_version)
    return AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.RELABELING,
        product=batch.product,
        batch=batch,
        quantity=ZERO_QTY,
        amount=ZERO_MONEY,
        balance_effect="label_version_change",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )


@transaction.atomic
def post_rework(
    *,
    source_batch: StockBatch,
    input_quantity: Decimal,
    output_product: Product,
    output_batch_number: str,
    output_quantity: Decimal,
    reason: str,
    user=None,
) -> AdjustmentDocument:
    _ensure_decimal_positive(input_quantity, "Rework input quantity")
    _ensure_decimal_positive(output_quantity, "Rework output quantity")
    number = next_document_number("RWK")
    _stock_out(batch=source_batch, quantity=input_quantity, source_type="REWORK", source_number=number, user=user, allow_blocked=True)
    unit_cost = (input_quantity * source_batch.unit_cost) / output_quantity
    _stock_in(
        product=output_product,
        batch_number=output_batch_number,
        warehouse=source_batch.warehouse,
        quantity=output_quantity,
        unit_cost=unit_cost,
        source_type="REWORK",
        source_number=number,
        parent_batch=source_batch,
        expiry_date=source_batch.expiry_date,
        user=user,
    )
    return AdjustmentDocument.objects.create(
        number=number,
        adjustment_type=AdjustmentDocument.AdjustmentType.REWORK,
        product=output_product,
        batch=source_batch,
        quantity=output_quantity,
        amount=(input_quantity - output_quantity) * source_batch.unit_cost,
        balance_effect="rework_stock",
        reason=reason,
        status=DocumentState.POSTED,
        created_by=user,
    )


@transaction.atomic
def issue_raw_material_to_grinding(
    *,
    raw_batch: StockBatch,
    powder_product: Product,
    issued_quantity: Decimal,
    expected_output_quantity: Decimal,
    user=None,
) -> ProductionOrder:
    if raw_batch.batch_type != StockBatch.BatchType.RAW:
        raise ValidationError("Only raw batches can be issued to grinding.")
    if powder_product.product_type != Product.ProductType.POWDER:
        raise ValidationError("Grinding output must be a powder product.")
    # Spec 6.1 + 10.7: rejected/damaged/blocked/expired/hold stock must not be issued
    non_issuable = {"rejected", "damaged", "blocked", "expired", "hold", "supplier_returnable"}
    if raw_batch.stock_state in non_issuable:
        raise ValidationError(
            f"Batch {raw_batch.batch_number} has stock_state '{raw_batch.stock_state}' and cannot be issued. "
            "Only accepted/available stock may be issued to grinding."
        )
    if raw_batch.is_blocked:
        raise ValidationError(f"Batch {raw_batch.batch_number} is blocked: {raw_batch.block_reason}")
    today = timezone.localdate()
    if raw_batch.expiry_date and raw_batch.expiry_date < today:
        raise ValidationError(
            f"Batch {raw_batch.batch_number} expired on {raw_batch.expiry_date}. Expired stock cannot be issued."
        )
    if raw_batch.quantity_on_hand < issued_quantity:
        raise ValidationError(
            f"Insufficient raw stock in batch {raw_batch.batch_number}: "
            f"available {raw_batch.quantity_on_hand}, requested {issued_quantity}."
        )
    number = next_document_number("PROD")
    order = ProductionOrder.objects.create(
        number=number,
        raw_batch=raw_batch,
        powder_product=powder_product,
        warehouse=raw_batch.warehouse,
        issued_quantity=issued_quantity,
        expected_output_quantity=expected_output_quantity,
        status="issued",  # Spec 10.7: raw material issued → production order becomes "issued"
        created_by=user,
    )
    _stock_out(batch=raw_batch, quantity=issued_quantity, source_type="PRODUCTION_ISSUE", source_number=number, user=user)
    _audit("raw_issued_to_grinding", "PRODUCTION_ORDER", number, "Raw material issued to grinding", user)
    return order


@transaction.atomic
def receive_powder_output(
    *,
    production_order: ProductionOrder,
    actual_output_quantity: Decimal,
    wastage_quantity: Decimal,
    powder_batch_number: str,
    expiry_date=None,
    user=None,
) -> StockBatch:
    order = ProductionOrder.objects.select_for_update().select_related("raw_batch", "powder_product").get(pk=production_order.pk)
    if order.powder_batch_id:
        raise ValidationError("Powder output has already been received for this production order.")
    _ensure_decimal_positive(actual_output_quantity, "Actual powder output")
    raw_cost = order.issued_quantity * order.raw_batch.unit_cost
    powder_unit_cost = raw_cost / actual_output_quantity
    powder_batch = _stock_in(
        product=order.powder_product,
        batch_number=powder_batch_number,
        warehouse=order.warehouse,
        quantity=actual_output_quantity,
        unit_cost=powder_unit_cost,
        source_type="POWDER_RECEIPT",
        source_number=order.number,
        parent_batch=order.raw_batch,
        expiry_date=expiry_date,
        user=user,
    )
    order.actual_output_quantity = actual_output_quantity
    order.wastage_quantity = wastage_quantity
    order.powder_batch = powder_batch
    order.status = DocumentState.APPROVED
    order.save(update_fields=["actual_output_quantity", "wastage_quantity", "powder_batch", "status", "updated_at"])
    _audit("powder_received", "PRODUCTION_ORDER", order.number, "Powder output received", user)
    return powder_batch


@transaction.atomic
def complete_packing_order(
    *,
    bom: PackagingBOM,
    powder_batch: StockBatch,
    completed_units: Decimal,
    wastage_units: Decimal = ZERO_QTY,
    finished_batch_number: str,
    packaging_batches: dict[int, StockBatch],
    user=None,
) -> PackingOrder:
    if powder_batch.batch_type != StockBatch.BatchType.POWDER:
        raise ValidationError("Packing requires powder batch input.")
    _ensure_decimal_positive(completed_units, "Completed packing units")
    if wastage_units < 0:
        raise ValidationError("Packing wastage cannot be negative.")
    number = next_document_number("PACK")
    powder_consumption_units = completed_units + wastage_units
    powder_required = bom.powder_quantity_per_unit * powder_consumption_units
    order = PackingOrder.objects.create(
        number=number,
        bom=bom,
        powder_batch=powder_batch,
        warehouse=powder_batch.warehouse,
        planned_units=completed_units,
        completed_units=completed_units,
        wastage_quantity=wastage_units,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _stock_out(batch=powder_batch, quantity=powder_required, source_type="PACKING_CONSUME_POWDER", source_number=number, user=user)
    packaging_cost = ZERO_MONEY
    for line in bom.lines.select_related("packaging_product"):
        batch = packaging_batches.get(line.packaging_product_id)
        if not batch:
            raise ValidationError(f"Packaging batch missing for {line.packaging_product.code}.")
        qty = line.quantity_per_unit * completed_units
        # Spec 6.1: packaging material must be available before consumption
        if batch.quantity_on_hand < qty:
            raise ValidationError(
                f"Insufficient packaging material '{line.packaging_product.code}' "
                f"in batch {batch.batch_number}: available {batch.quantity_on_hand}, required {qty}."
            )
        _stock_out(batch=batch, quantity=qty, source_type="PACKING_CONSUME_PACKAGING", source_number=number, user=user)
        packaging_cost += qty * batch.unit_cost
    powder_cost = powder_required * powder_batch.unit_cost
    finished_unit_cost = (powder_cost + packaging_cost) / completed_units
    shelf_life = bom.finished_product.shelf_life_days or 0
    expiry_date = timezone.localdate() + timedelta(days=shelf_life) if shelf_life else None
    finished_batch = _stock_in(
        product=bom.finished_product,
        batch_number=finished_batch_number,
        warehouse=powder_batch.warehouse,
        quantity=completed_units,
        unit_cost=finished_unit_cost,
        source_type="PACKING_COMPLETE",
        source_number=number,
        parent_batch=powder_batch,
        packing_date=timezone.localdate(),
        expiry_date=expiry_date,
        user=user,
    )
    order.finished_batch = finished_batch
    order.status = DocumentState.APPROVED
    order.save(update_fields=["finished_batch", "status", "updated_at"])
    _audit("packing_completed", "PACKING_ORDER", number, "Finished goods batch created", user)
    return order


def fefo_allocation_plan(
    *,
    product: Product,
    required_quantity: Decimal | None = None,
    warehouse: Warehouse | None = None,
) -> dict:
    if product.product_type != Product.ProductType.FINISHED:
        raise ValidationError("FEFO dispatch allocation currently supports finished goods SKUs.")
    if required_quantity is not None and required_quantity <= 0:
        raise ValidationError("Required dispatch quantity must be greater than zero.")
    today = timezone.localdate()
    remaining = required_quantity
    rows = []
    batches = StockBatch.objects.select_related("product", "warehouse").filter(
        product=product,
        batch_type=StockBatch.BatchType.FINISHED,
        is_blocked=False,
        quantity_on_hand__gt=0,
    )
    if warehouse:
        batches = batches.filter(warehouse=warehouse)
    batches = batches.filter(models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today)).order_by(
        "expiry_date",
        "created_at",
        "batch_number",
    )
    for batch in batches:
        if remaining is None:
            allocate = batch.quantity_on_hand
        elif remaining <= 0:
            allocate = ZERO_QTY
        else:
            allocate = min(batch.quantity_on_hand, remaining)
            remaining -= allocate
        rows.append(
            {
                "product_code": batch.product.code,
                "batch_number": batch.batch_number,
                "warehouse": batch.warehouse.code,
                "expiry_date": batch.expiry_date,
                "available_quantity": batch.quantity_on_hand,
                "allocated_quantity": allocate,
                "unit_cost": batch.unit_cost,
                "allocation_value": allocate * batch.unit_cost,
                "fefo_rank": len(rows) + 1,
            }
        )
    shortage = remaining if remaining is not None and remaining > 0 else ZERO_QTY
    return {
        "rows": rows,
        "required_quantity": required_quantity,
        "allocated_quantity": sum(row["allocated_quantity"] for row in rows),
        "shortage_quantity": shortage,
        "reconciled": shortage == ZERO_QTY if required_quantity is not None else True,
        "strategy": "FEFO by earliest non-expired expiry_date, then receipt time, then batch number.",
    }


@transaction.atomic
def post_cash_bank_opening(*, account: CashBankAccount, amount: Decimal, user=None) -> OpeningBalance:
    number = next_document_number("OPEN")
    account = CashBankAccount.objects.select_for_update().get(pk=account.pk)
    account.balance += amount
    account.save(update_fields=["balance", "updated_at"])
    opening = OpeningBalance.objects.create(
        number=number,
        cash_bank_account=account,
        amount=amount,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _audit("cash_bank_opening_posted", "OPENING_BALANCE", number, "Cash/bank opening balance posted", user)
    return opening


@transaction.atomic
def post_supplier_opening_payable(*, supplier: Supplier, amount: Decimal, user=None) -> OpeningBalance:
    _ensure_decimal_positive(amount, "Supplier opening payable")
    number = next_document_number("OPEN")
    opening = OpeningBalance.objects.create(
        number=number,
        supplier=supplier,
        amount=amount,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _post_supplier_ledger(
        supplier=supplier,
        source_type="OPENING_SUPPLIER_PAYABLE",
        source_number=number,
        balance_effect="opening_payable",
        payable_effect=amount,
        credit_amount=amount,
        description="Supplier opening payable posted",
        user=user,
    )
    return opening


@transaction.atomic
def post_supplier_opening_advance(*, supplier: Supplier, amount: Decimal, user=None) -> OpeningBalance:
    _ensure_decimal_positive(amount, "Supplier opening advance")
    number = next_document_number("OPEN")
    opening = OpeningBalance.objects.create(
        number=number,
        supplier=supplier,
        amount=amount,
        status=DocumentState.POSTED,
        created_by=user,
    )
    _post_supplier_ledger(
        supplier=supplier,
        source_type="OPENING_SUPPLIER_ADVANCE",
        source_number=number,
        balance_effect="opening_advance",
        advance_effect=amount,
        debit_amount=amount,
        description="Supplier opening advance posted",
        user=user,
    )
    return opening


def computed_supplier_balance(supplier: Supplier) -> dict[str, Decimal]:
    rows = SupplierLedgerEntry.objects.filter(supplier=supplier).aggregate(
        payable=Sum("payable_effect"), advance=Sum("advance_effect")
    )
    return {
        "payable": rows["payable"] or ZERO_MONEY,
        "advance": rows["advance"] or ZERO_MONEY,
        "net": (rows["payable"] or ZERO_MONEY) - (rows["advance"] or ZERO_MONEY),
    }


def stock_ledger_balance(batch: StockBatch) -> Decimal:
    rows = StockLedgerEntry.objects.filter(batch=batch).aggregate(
        ins=Sum("quantity", filter=models.Q(direction=StockLedgerEntry.Direction.IN)),
        outs=Sum("quantity", filter=models.Q(direction=StockLedgerEntry.Direction.OUT)),
    )
    return (rows["ins"] or ZERO_QTY) - (rows["outs"] or ZERO_QTY)


# ── RECIPE VERSION ACTIVATION ────────────────────────────────────────────────
@transaction.atomic
def activate_recipe_version(*, recipe_id: int, user=None):
    """
    Activate a recipe version, deactivating all other versions of the same recipe code.
    Spec 3.30 / 1.7: recipe version activation must be service-layer controlled.
    """
    from .models import Recipe
    recipe = Recipe.objects.select_for_update().get(pk=recipe_id)
    if recipe.status == DocumentState.POSTED:
        raise ValidationError("Recipe is already active.")
    if recipe.status == DocumentState.CANCELLED:
        raise ValidationError("A cancelled recipe cannot be activated.")
    # Deactivate all other active versions of same code
    Recipe.objects.filter(code=recipe.code, status=DocumentState.POSTED).exclude(pk=recipe.pk).update(
        status=DocumentState.CANCELLED, updated_at=timezone.now()
    )
    recipe.status = DocumentState.POSTED
    recipe.approved_by = user
    recipe.approved_at = timezone.now()
    recipe.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    _audit(
        "recipe_version_activated",
        "RECIPE",
        recipe.code,
        f"Recipe v{recipe.version} activated. Prior versions deactivated.",
        user,
    )
    return recipe


# ── OPENING STOCK ────────────────────────────────────────────────────────────
@transaction.atomic
def post_opening_stock(
    *,
    product,
    warehouse,
    batch_number: str,
    quantity: Decimal,
    unit_cost: Decimal,
    expiry_date=None,
    manufacturing_date=None,
    supplier=None,
    remarks: str = "Opening stock balance",
    user=None,
) -> StockBatch:
    """
    Post opening stock for raw, powder, packaging, or finished goods.
    Creates a StockBatch with source_type=OPENING and a stock ledger entry.
    Spec 3.54: opening balances must create auditable opening ledger entries.
    """
    if quantity <= 0:
        raise ValidationError("Opening stock quantity must be positive.")
    if unit_cost < 0:
        raise ValidationError("Opening stock unit cost cannot be negative.")
    number = next_document_number("OPEN")
    # Duplicate prevention: same product+batch+warehouse cannot have two open openings
    if StockBatch.objects.filter(
        product=product, batch_number=batch_number, warehouse=warehouse, source_document_type="OPENING"
    ).exists():
        raise ValidationError(
            f"Opening stock for batch {batch_number} of {product.code} in {warehouse.code} already posted."
        )
    batch = _stock_in(
        product=product,
        batch_number=batch_number,
        warehouse=warehouse,
        quantity=quantity,
        unit_cost=unit_cost,
        source_type="OPENING",
        source_number=number,
        supplier=supplier,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        user=user,
    )
    opening = OpeningBalance.objects.create(
        number=number,
        product=product,
        supplier=supplier,
        warehouse=warehouse,
        quantity=quantity,
        amount=quantity * unit_cost,
        status=DocumentState.POSTED,
        created_by=user,
    )
    OpeningBalanceLine.objects.create(
        opening_balance=opening,
        product=product,
        warehouse=warehouse,
        batch_number=batch_number,
        quantity=quantity,
        unit_cost=unit_cost,
        amount=quantity * unit_cost,
        expiry_date=expiry_date,
        remarks=remarks,
        batch_created=batch,
    )
    _audit("opening_stock_posted", "OPENING_BALANCE", number, f"Opening stock posted: {product.code} batch {batch_number} qty {quantity}", user)
    return batch


# ── INVOICE OVERDUE STATUS ────────────────────────────────────────────────────
def refresh_invoice_overdue_status():
    """
    Mark supplier invoices as overdue based on due_date.
    Call periodically from a scheduled job or before aging report generation.
    Spec 3.17: SupplierInvoice has overdue status.
    """
    today = timezone.localdate()
    updated = SupplierInvoice.objects.filter(
        status=DocumentState.POSTED,
        due_date__lt=today,
    ).exclude(outstanding_amount__lte=0).update(
        status="overdue", updated_at=timezone.now()
    )
    return updated


# ── GRN CANCELLATION ─────────────────────────────────────────────────────────
@transaction.atomic
def cancel_grn(*, grn: GRN, reason: str, user=None) -> GRN:
    """
    Cancel a GRN that has not yet been approved/posted.
    Spec 10.2: GRN cancellation is terminal unless explicitly reopened.
    Only draft/quality_pending GRNs may be cancelled here.
    Approved GRNs must be reversed through reversal workflow.
    """
    grn = GRN.objects.select_for_update().get(pk=grn.pk)
    if grn.status in (DocumentState.APPROVED, DocumentState.REVERSED, DocumentState.CANCELLED):
        raise ValidationError(
            f"GRN {grn.number} cannot be cancelled from status '{grn.status}'. "
            "Use reversal for approved GRNs."
        )
    # quality_pending and draft are both cancellable
    if not reason or not reason.strip():
        raise ValidationError("Cancellation reason is required.")
    grn.status = DocumentState.CANCELLED
    grn.cancelled_by = user
    grn.cancelled_at = timezone.now()
    grn.cancellation_reason = reason
    grn.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancellation_reason", "updated_at"])
    _audit("grn_cancelled", "GRN", grn.number, reason, user)
    return grn


# ── PARTIAL PAYMENT WORKFLOW ──────────────────────────────────────────────────
def post_partial_payment(
    *, supplier: Supplier, cash_bank_account, invoice: SupplierInvoice,
    amount: Decimal, user=None
) -> SupplierPayment:
    """
    Post a partial payment against an invoice.
    Spec 5.2: partial payment must reduce payable by amount paid only.
    If amount >= outstanding, it is treated as full payment.
    """
    invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.outstanding_amount <= 0:
        raise ValidationError(f"Invoice {invoice.number} is already fully paid.")
    if amount <= 0:
        raise ValidationError("Partial payment amount must be positive.")
    if amount > invoice.outstanding_amount:
        raise ValidationError(
            f"Amount {amount} exceeds outstanding {invoice.outstanding_amount} on invoice {invoice.number}. "
            "Use advance posting for excess amounts."
        )
    # Delegate to post_supplier_payment which handles the ledger correctly
    return post_supplier_payment(
        supplier=supplier,
        cash_bank_account=cash_bank_account,
        invoice=invoice,
        amount=amount,
        user=user,
    )


# ── ALIAS for spec compliance ─────────────────────────────────────────────────
# Spec 1.7 names this post_opening_balance; post_opening_stock is the implementation.
post_opening_balance = post_opening_stock


# ── SUPPLIER PAYMENT ALLOCATION SERVICE ──────────────────────────────────────
@transaction.atomic
def allocate_supplier_payment(
    *, payment: SupplierPayment, invoice: SupplierInvoice,
    allocated_amount: Decimal, user=None
):
    """
    Allocate a supplier payment or advance to a specific invoice line.
    Spec 1.7 / 3.19 / SupplierPaymentAllocation entity.
    """
    from .models import SupplierPaymentAllocation
    payment = SupplierPayment.objects.select_for_update().get(pk=payment.pk)
    invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
    if allocated_amount <= 0:
        raise ValidationError("Allocation amount must be positive.")
    if invoice.outstanding_amount < allocated_amount - Decimal("0.01"):
        raise ValidationError(
            f"Allocation amount {allocated_amount} exceeds outstanding "
            f"{invoice.outstanding_amount} on invoice {invoice.number}."
        )
    alloc, created = SupplierPaymentAllocation.objects.get_or_create(
        payment=payment,
        invoice=invoice,
        defaults={"allocated_amount": allocated_amount, "allocation_type": "payment"},
    )
    if not created:
        alloc.allocated_amount = allocated_amount
        alloc.save(update_fields=["allocated_amount"])
    _audit(
        "payment_allocated", "SUPPLIER_PAYMENT", payment.number,
        f"Allocated {allocated_amount} to invoice {invoice.number}", user
    )
    return alloc
