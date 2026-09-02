from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from erp.models import CustomerDistributor, Product, StockBatch
from erp.services import dispatch_finished_goods_stock, receive_approved_sales_return_stock

from .models import (
    CatalogVariantMapping, CustomerAccountProfile, CustomerLedgerEntry, CustomerPayment,
    CustomerCreditNote, CustomerDebitNote, CustomerPaymentAllocation, DeliveryChallan,
    DeliveryChallanLine, DeliveryStatusLog, DispatchAllocation, Refund, SalesInvoice,
    SalesInvoiceLine, SalesOrder, SalesOrderLine, SalesReturn, SalesReturnLine,
    SalesStockReservation,
)


def _number(prefix: str) -> str:
    return f"{prefix}-{timezone.now():%Y%m%d}-{uuid4().hex[:10].upper()}"


def _eligible_batches(product, *, lock=False):
    queryset = StockBatch.objects.filter(
        product=product,
        batch_type=StockBatch.BatchType.FINISHED,
        stock_state=StockBatch.StockState.ACCEPTED,
        is_blocked=False,
        quantity_on_hand__gt=0,
    ).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate()))
    if lock:
        queryset = queryset.select_for_update()
    return queryset.order_by(models_fefo_expiry(), "packing_date", "created_at", "pk")


def models_fefo_expiry():
    from django.db.models import F
    return F("expiry_date").asc(nulls_last=True)


def check_finished_sku_availability(product, quantity=None) -> Decimal | bool:
    available = finished_sku_availability_map([product.pk]).get(product.pk, Decimal("0.000"))
    if product.product_type != Product.ProductType.FINISHED or not product.is_active:
        available = Decimal("0.000")
    return available >= Decimal(str(quantity)) if quantity is not None else available


def finished_sku_availability_map(product_ids) -> dict[int, Decimal]:
    product_ids = set(product_ids)
    if not product_ids:
        return {}
    eligible = {
        "product_id__in": product_ids,
        "batch_type": StockBatch.BatchType.FINISHED,
        "stock_state": StockBatch.StockState.ACCEPTED,
        "is_blocked": False,
        "quantity_on_hand__gt": 0,
    }
    expiry_filter = Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate())
    physical = {
        row["product_id"]: row["total"]
        for row in StockBatch.objects.filter(**eligible).filter(expiry_filter)
        .values("product_id").annotate(total=Sum("quantity_on_hand"))
    }
    reserved = {
        row["batch__product_id"]: row["total"]
        for row in SalesStockReservation.objects.filter(
            batch__product_id__in=product_ids,
            batch__batch_type=StockBatch.BatchType.FINISHED,
            batch__stock_state=StockBatch.StockState.ACCEPTED,
            batch__is_blocked=False,
            batch__quantity_on_hand__gt=0,
            status=SalesStockReservation.Status.ACTIVE,
        ).filter(
            Q(batch__expiry_date__isnull=True) | Q(batch__expiry_date__gte=timezone.localdate())
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).values("batch__product_id").annotate(total=Sum("quantity"))
    }
    return {
        product_id: max(Decimal("0.000"), physical.get(product_id, Decimal("0.000")) - reserved.get(product_id, Decimal("0.000")))
        for product_id in product_ids
    }


def suggest_fefo_batches(product, quantity) -> list[tuple[StockBatch, Decimal]]:
    remaining = Decimal(str(quantity))
    suggestions = []
    for batch in _eligible_batches(product):
        reserved = batch.sales_reservations.filter(status=SalesStockReservation.Status.ACTIVE).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        available = max(Decimal("0.000"), batch.quantity_on_hand - reserved)
        take = min(remaining, available)
        if take > 0:
            suggestions.append((batch, take))
            remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise ValidationError(f"Insufficient sellable FEFO stock for {product.code}.")
    return suggestions


def _reserve_line_fefo(line, *, user=None):
    remaining = line.quantity
    for batch in _eligible_batches(line.erp_product, lock=True):
        reserved = SalesStockReservation.objects.filter(
            batch=batch, status=SalesStockReservation.Status.ACTIVE,
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0.000")
        take = min(remaining, max(Decimal("0.000"), batch.quantity_on_hand - reserved))
        if take > 0:
            SalesStockReservation.objects.create(
                line=line, batch=batch, quantity=take,
                expires_at=timezone.now() + timezone.timedelta(hours=24), created_by=user,
            )
            remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise ValidationError(f"Insufficient sellable FEFO stock for {line.erp_product.code}.")


def _sync_invoice_status(invoice, *, user=None):
    if invoice.status == SalesInvoice.Status.CANCELLED:
        return invoice
    balance = invoice.balance
    if balance <= 0:
        status = SalesInvoice.Status.PAID
    elif invoice.paid_amount > 0:
        status = SalesInvoice.Status.PART_PAID
    else:
        status = SalesInvoice.Status.POSTED
    if invoice.status != status or invoice.updated_by_id != getattr(user, "pk", None):
        invoice.status = status
        invoice.updated_by = user
        invoice.save(update_fields=["status", "updated_by", "updated_at"])
    return invoice


def _customer_for_shop_order(shop_order, user=None):
    if shop_order.customer_user_id:
        profile = CustomerAccountProfile.objects.filter(user_id=shop_order.customer_user_id).select_related("customer").first()
        if profile:
            return profile.customer
    code = f"WEB-U-{shop_order.customer_user_id}" if shop_order.customer_user_id else f"WEB-G-{shop_order.pk}"
    customer, _ = CustomerDistributor.objects.get_or_create(
        code=code,
        defaults={
            "business_name": shop_order.customer_name,
            "contact_person": shop_order.customer_name,
            "customer_type": CustomerDistributor.CustomerType.ECOMMERCE,
            "phone": shop_order.phone,
            "email": shop_order.email,
            "address": shop_order.address,
            "city": shop_order.city,
            "sales_channel": CustomerDistributor.SalesChannel.ECOMMERCE,
            "created_by": user,
        },
    )
    if shop_order.customer_user_id:
        CustomerAccountProfile.objects.get_or_create(
            user_id=shop_order.customer_user_id, defaults={"customer": customer, "created_by": user}
        )
    return customer


@transaction.atomic
def create_sales_order_from_shop(shop_order, *, user=None) -> SalesOrder:
    existing = SalesOrder.objects.filter(shop_order=shop_order).first()
    if existing:
        return existing
    customer = _customer_for_shop_order(shop_order, user=user)
    sales_order = SalesOrder.objects.create(
        shop_order=shop_order, customer=customer, number=_number("SO"),
        subtotal=shop_order.subtotal, delivery_charge=shop_order.delivery_charge,
        total=shop_order.total, created_by=user,
    )
    for item in shop_order.items.select_related("variant", "variant__product"):
        mapping = CatalogVariantMapping.objects.select_related("erp_product").filter(
            variant=item.variant, is_active=True, erp_product__is_active=True,
        ).first()
        if not mapping:
            raise ValidationError(f"Variant {item.variant.sku} is not mapped to an active ERP finished SKU.")
        quantity = Decimal(str(item.quantity))
        line = SalesOrderLine.objects.create(
            order=sales_order, shop_item=item, variant=item.variant, erp_product=mapping.erp_product,
            quantity=quantity, unit_price=item.price, line_total=item.subtotal,
        )
        _reserve_line_fefo(line, user=user)
    due_days = customer.credit_days or 0
    invoice = SalesInvoice.objects.create(
        number=_number("SI"), order=sales_order, customer=customer, amount=sales_order.total,
        due_date=timezone.localdate() + timezone.timedelta(days=due_days), created_by=user,
    )
    for line in sales_order.lines.select_related("erp_product"):
        SalesInvoiceLine.objects.create(
            invoice=invoice, order_line=line, description=line.erp_product.name,
            quantity=line.quantity, unit_price=line.unit_price, amount=line.line_total,
        )
    if sales_order.delivery_charge > 0:
        SalesInvoiceLine.objects.create(
            invoice=invoice, description="Delivery charge", quantity=Decimal("1.000"),
            unit_price=sales_order.delivery_charge, amount=sales_order.delivery_charge,
        )
    CustomerLedgerEntry.objects.create(
        customer=customer, invoice=invoice, entry_type=CustomerLedgerEntry.EntryType.INVOICE,
        amount=invoice.amount, reference_type="sales_invoice", reference_number=invoice.number,
        description=f"Invoice for {sales_order.number}", created_by=user,
    )
    DeliveryChallan.objects.create(number=_number("DC"), order=sales_order, created_by=user)
    return sales_order


@transaction.atomic
def release_stock_reservation(shop_order, *, user=None) -> int:
    sales_order = SalesOrder.objects.select_for_update().get(shop_order=shop_order)
    if sales_order.status in {SalesOrder.Status.DISPATCHED, SalesOrder.Status.DELIVERED}:
        raise ValidationError("Dispatched stock cannot be restored through cancellation; use sales return.")
    reservations = SalesStockReservation.objects.filter(line__order=sales_order, status=SalesStockReservation.Status.ACTIVE)
    count = reservations.update(status=SalesStockReservation.Status.RELEASED, released_at=timezone.now(), updated_by=user)
    sales_order.status = SalesOrder.Status.CANCELLED
    sales_order.updated_by = user
    sales_order.save(update_fields=["status", "updated_by", "updated_at"])
    invoice = SalesInvoice.objects.select_for_update().get(order=sales_order)
    if invoice.status != SalesInvoice.Status.CANCELLED:
        CustomerLedgerEntry.objects.create(
            customer=sales_order.customer,
            invoice=invoice,
            entry_type=CustomerLedgerEntry.EntryType.REVERSAL,
            amount=-invoice.amount,
            reference_type="sales_invoice_cancellation",
            reference_number=invoice.number,
            description=f"Cancellation reversal for {sales_order.number}",
            created_by=user,
        )
        invoice.status = SalesInvoice.Status.CANCELLED
        invoice.updated_by = user
        invoice.save(update_fields=["status", "updated_by", "updated_at"])
    return count


@transaction.atomic
def reallocate_stock_reservation(shop_order, *, user=None) -> int:
    sales_order = SalesOrder.objects.select_for_update().get(shop_order=shop_order)
    if sales_order.status not in {
        SalesOrder.Status.RESERVED, SalesOrder.Status.CONFIRMED, SalesOrder.Status.PROCESSING,
    }:
        raise ValidationError("Only an open, undispatched order can be reallocated.")
    active = SalesStockReservation.objects.select_for_update().filter(
        line__order=sales_order, status=SalesStockReservation.Status.ACTIVE,
    )
    released = active.update(
        status=SalesStockReservation.Status.RELEASED,
        released_at=timezone.now(),
        updated_by=user,
    )
    for line in sales_order.lines.select_related("erp_product").order_by("pk"):
        _reserve_line_fefo(line, user=user)
    return released


@transaction.atomic
def dispatch_stock_for_order(shop_order, *, user=None, carrier="", tracking_number="") -> DeliveryChallan:
    sales_order = SalesOrder.objects.select_for_update().select_related("delivery_challan").get(shop_order=shop_order)
    if sales_order.status == SalesOrder.Status.DISPATCHED:
        return sales_order.delivery_challan
    if sales_order.status not in {
        SalesOrder.Status.RESERVED, SalesOrder.Status.CONFIRMED, SalesOrder.Status.PROCESSING,
    }:
        raise ValidationError("Only an open, undispatched order can be dispatched.")
    challan = sales_order.delivery_challan
    active = list(SalesStockReservation.objects.select_for_update().select_related("line", "batch").filter(
        line__order=sales_order, status=SalesStockReservation.Status.ACTIVE,
    ))
    if not active or any(r.expires_at and r.expires_at <= timezone.now() for r in active):
        raise ValidationError("Order reservations are missing or expired; reallocation is required.")
    reserved_by_line = {}
    for reservation in active:
        reserved_by_line[reservation.line_id] = reserved_by_line.get(reservation.line_id, Decimal("0.000")) + reservation.quantity
    expected_by_line = dict(sales_order.lines.values_list("id", "quantity"))
    if set(reserved_by_line) != set(expected_by_line) or any(
        reserved_by_line[line_id] != quantity for line_id, quantity in expected_by_line.items()
    ):
        raise ValidationError("Active reservations do not fully cover every order line; reallocation is required.")
    challan.carrier = carrier
    challan.tracking_number = tracking_number
    challan.dispatch_date = timezone.localdate()
    challan.status = DeliveryChallan.Status.DISPATCHED
    challan.updated_by = user
    challan.save()
    challan_lines = {}
    for reservation in active:
        line = reservation.line
        challan_line = challan_lines.get(line.pk)
        if not challan_line:
            challan_line = DeliveryChallanLine.objects.create(challan=challan, order_line=line, quantity=line.quantity)
            challan_lines[line.pk] = challan_line
        ledger = dispatch_finished_goods_stock(
            batch=reservation.batch, quantity=reservation.quantity,
            source_number=f"{challan.number}-{reservation.pk}", user=user,
        )
        DispatchAllocation.objects.create(
            challan_line=challan_line, reservation=reservation, batch=reservation.batch,
            quantity=reservation.quantity, stock_ledger_entry=ledger, created_by=user,
        )
        reservation.status = SalesStockReservation.Status.DISPATCHED
        reservation.updated_by = user
        reservation.save(update_fields=["status", "updated_by", "updated_at"])
    old_status = sales_order.status
    sales_order.status = SalesOrder.Status.DISPATCHED
    sales_order.updated_by = user
    sales_order.save(update_fields=["status", "updated_by", "updated_at"])
    DeliveryStatusLog.objects.create(
        order=sales_order, old_status=old_status, new_status=SalesOrder.Status.DISPATCHED,
        note=f"Delivery challan {challan.number} dispatched", created_by=user,
    )
    return challan


@transaction.atomic
def post_customer_payment(shop_transaction, *, user=None) -> CustomerPayment:
    existing = CustomerPayment.objects.filter(shop_transaction=shop_transaction).first()
    if existing:
        return existing
    if shop_transaction.status != "verified":
        raise ValidationError("Only verified customer payments can be posted to the ledger.")
    invoice = SalesInvoice.objects.select_for_update().get(order__shop_order=shop_transaction.order)
    if invoice.status == SalesInvoice.Status.CANCELLED:
        raise ValidationError("Payments cannot be posted to a cancelled invoice.")
    if shop_transaction.amount <= 0 or shop_transaction.amount > invoice.balance:
        raise ValidationError("Payment amount must be positive and cannot exceed the invoice balance.")
    payment = CustomerPayment.objects.create(
        number=_number("CP"), customer=invoice.customer, shop_transaction=shop_transaction,
        amount=shop_transaction.amount, method=shop_transaction.provider,
        reference=shop_transaction.provider_reference, created_by=user,
    )
    allocation_amount = min(payment.amount, invoice.balance)
    if allocation_amount <= 0:
        raise ValidationError("Invoice has no receivable balance to allocate.")
    CustomerPaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=allocation_amount)
    CustomerLedgerEntry.objects.create(
        customer=invoice.customer, invoice=invoice, entry_type=CustomerLedgerEntry.EntryType.PAYMENT,
        amount=-payment.amount, reference_type="customer_payment", reference_number=payment.number,
        description=f"Payment allocated to {invoice.number}", created_by=user,
    )
    _sync_invoice_status(invoice, user=user)
    return payment


@transaction.atomic
def create_return_from_shop(return_request, *, user=None) -> SalesReturn:
    existing = SalesReturn.objects.filter(shop_request=return_request).first()
    if existing:
        return existing
    sales_order = SalesOrder.objects.select_for_update().get(shop_order=return_request.order)
    if sales_order.status != SalesOrder.Status.DELIVERED:
        raise ValidationError("Only delivered sales orders can be returned.")
    if SalesReturn.objects.filter(order=sales_order).exists():
        raise ValidationError("This full-order return has already been recorded.")
    sales_return = SalesReturn.objects.create(
        number=_number("SR"), order=sales_order, shop_request=return_request,
        reason=return_request.reason, status=SalesReturn.Status.QUARANTINED,
        received_at=timezone.now(), created_by=user,
    )
    for line in sales_order.lines.all():
        SalesReturnLine.objects.create(sales_return=sales_return, order_line=line, quantity=line.quantity)
    CustomerLedgerEntry.objects.create(
        customer=sales_order.customer, invoice=sales_order.invoice,
        entry_type=CustomerLedgerEntry.EntryType.RETURN,
        amount=-sales_order.total, reference_type="sales_return", reference_number=sales_return.number,
        description="Returned goods placed in quarantine; no stock restored pending QA.", created_by=user,
    )
    _sync_invoice_status(sales_order.invoice, user=user)
    return sales_return


@transaction.atomic
def approve_return_stock_after_qa(sales_return, *, user=None) -> SalesReturn:
    sales_return = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if sales_return.status != SalesReturn.Status.QUARANTINED:
        raise ValidationError("Only quarantined returns can be released by QA.")
    for return_line in sales_return.lines.select_for_update().select_related("order_line"):
        remaining = return_line.quantity
        allocations = DispatchAllocation.objects.filter(
            challan_line__order_line=return_line.order_line,
        ).select_related("batch").order_by("pk")
        for allocation in allocations:
            take = min(remaining, allocation.quantity)
            if take > 0:
                receive_approved_sales_return_stock(
                    batch=allocation.batch, quantity=take,
                    source_number=f"{sales_return.number}-{return_line.pk}-{allocation.pk}", user=user,
                )
                remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            raise ValidationError("Return quantity exceeds the traceable dispatched quantity.")
        return_line.disposition = SalesReturnLine.Disposition.RESTOCKED
        return_line.save(update_fields=["disposition"])
    sales_return.status = SalesReturn.Status.CLOSED
    sales_return.updated_by = user
    sales_return.save(update_fields=["status", "updated_by", "updated_at"])
    return sales_return


@transaction.atomic
def reject_return_after_qa(sales_return, *, user=None, reason="") -> SalesReturn:
    sales_return = SalesReturn.objects.select_for_update().select_related(
        "order__invoice", "shop_request"
    ).get(pk=sales_return.pk)
    if sales_return.status != SalesReturn.Status.QUARANTINED:
        raise ValidationError("Only quarantined returns can be rejected by QA.")
    invoice = sales_return.order.invoice
    CustomerLedgerEntry.objects.create(
        customer=sales_return.order.customer,
        invoice=invoice,
        entry_type=CustomerLedgerEntry.EntryType.REVERSAL,
        amount=sales_return.order.total,
        reference_type="sales_return_rejection",
        reference_number=sales_return.number,
        description=(reason or "QA rejected the returned goods; return credit reversed.")[:240],
        created_by=user,
    )
    sales_return.lines.update(disposition=SalesReturnLine.Disposition.REJECTED)
    sales_return.status = SalesReturn.Status.REJECTED
    sales_return.updated_by = user
    sales_return.save(update_fields=["status", "updated_by", "updated_at"])
    if sales_return.shop_request_id:
        sales_return.shop_request.status = sales_return.shop_request.STATUS_REJECTED
        sales_return.shop_request.resolved_at = timezone.now()
        sales_return.shop_request.admin_note = reason
        sales_return.shop_request.save(update_fields=["status", "resolved_at", "admin_note"])
    _sync_invoice_status(invoice, user=user)
    return sales_return


@transaction.atomic
def sync_delivery_status(shop_order, new_status, *, user=None, note=""):
    sales_order = SalesOrder.objects.select_for_update().get(shop_order=shop_order)
    mapping = {
        "confirmed": SalesOrder.Status.CONFIRMED,
        "processing": SalesOrder.Status.PROCESSING,
        "shipped": SalesOrder.Status.DISPATCHED,
        "delivered": SalesOrder.Status.DELIVERED,
        "cancelled": SalesOrder.Status.CANCELLED,
    }
    target = mapping.get(new_status)
    if not target or sales_order.status == target:
        return sales_order
    old = sales_order.status
    sales_order.status = target
    sales_order.updated_by = user
    sales_order.save(update_fields=["status", "updated_by", "updated_at"])
    if target == SalesOrder.Status.DELIVERED:
        challan = sales_order.delivery_challan
        challan.status = DeliveryChallan.Status.DELIVERED
        challan.updated_by = user
        challan.save(update_fields=["status", "updated_by", "updated_at"])
    DeliveryStatusLog.objects.create(order=sales_order, old_status=old, new_status=target, note=note, created_by=user)
    return sales_order


@transaction.atomic
def post_refund(shop_request, *, user=None) -> Refund:
    existing = Refund.objects.filter(shop_request=shop_request).first()
    if existing:
        return existing
    sales_order = SalesOrder.objects.select_for_update().select_related("invoice").get(shop_order=shop_request.order)
    amount = Decimal(str(shop_request.amount)).quantize(Decimal("0.01"))
    credit_available = max(Decimal("0.00"), -sales_order.invoice.balance)
    if amount <= 0 or amount > credit_available:
        raise ValidationError("Refund amount exceeds the customer credit available on this invoice.")
    refund = Refund.objects.create(
        number=_number("RF"), order=sales_order, shop_request=shop_request,
        amount=amount, reason=shop_request.reason, created_by=user,
    )
    CustomerLedgerEntry.objects.create(
        customer=sales_order.customer, invoice=sales_order.invoice,
        entry_type=CustomerLedgerEntry.EntryType.REFUND,
        amount=refund.amount, reference_type="refund", reference_number=refund.number,
        description="Cash refund after customer return/credit.", created_by=user,
    )
    _sync_invoice_status(sales_order.invoice, user=user)
    return refund


@transaction.atomic
def post_customer_credit_note(*, customer, amount, reason, order=None, user=None) -> CustomerCreditNote:
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValidationError("Credit note amount must be positive.")
    if order is None or order.customer_id != customer.pk:
        raise ValidationError("Customer credit notes must reference an invoice order for the same customer.")
    note = CustomerCreditNote.objects.create(
        number=_number("SCN"), customer=customer, order=order, amount=amount,
        reason=reason, created_by=user,
    )
    invoice = order.invoice if order else None
    CustomerLedgerEntry.objects.create(
        customer=customer, invoice=invoice, entry_type=CustomerLedgerEntry.EntryType.CREDIT_NOTE,
        amount=-amount, reference_type="customer_credit_note", reference_number=note.number,
        description=reason[:240], created_by=user,
    )
    _sync_invoice_status(invoice, user=user)
    return note


@transaction.atomic
def post_customer_debit_note(*, customer, amount, reason, order=None, user=None) -> CustomerDebitNote:
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValidationError("Debit note amount must be positive.")
    if order is None or order.customer_id != customer.pk:
        raise ValidationError("Customer debit notes must reference an invoice order for the same customer.")
    note = CustomerDebitNote.objects.create(
        number=_number("SDN"), customer=customer, order=order, amount=amount,
        reason=reason, created_by=user,
    )
    invoice = order.invoice if order else None
    CustomerLedgerEntry.objects.create(
        customer=customer, invoice=invoice, entry_type=CustomerLedgerEntry.EntryType.DEBIT_NOTE,
        amount=amount, reference_type="customer_debit_note", reference_number=note.number,
        description=reason[:240], created_by=user,
    )
    _sync_invoice_status(invoice, user=user)
    return note
