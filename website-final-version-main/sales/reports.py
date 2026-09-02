from decimal import Decimal

from django.db.models import Count, DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    CustomerLedgerEntry, CustomerPaymentAllocation, DeliveryChallan, DispatchAllocation, Refund, SalesInvoice,
    SalesOrder, SalesReturn, SalesStockReservation,
)


MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)


def invoices_with_balance():
    ledger_total = (
        CustomerLedgerEntry.objects.filter(invoice=OuterRef("pk"))
        .values("invoice").annotate(total=Sum("amount")).values("total")
    )
    payment_total = (
        CustomerPaymentAllocation.objects.filter(invoice=OuterRef("pk"))
        .values("invoice").annotate(total=Sum("amount")).values("total")
    )
    fallback = F("amount") - Coalesce(Subquery(payment_total, output_field=MONEY_FIELD), Value(Decimal("0.00")), output_field=MONEY_FIELD)
    return SalesInvoice.objects.annotate(
        calculated_balance=Coalesce(Subquery(ledger_total, output_field=MONEY_FIELD), fallback, output_field=MONEY_FIELD)
    )


def sales_report(report_name, limit=500):
    limit = max(1, min(int(limit), 5000))
    if report_name == "sales-orders":
        return list(SalesOrder.objects.values("number", "order_date", "customer__code", "status", "channel", "total")[:limit])
    if report_name == "sales-invoices":
        return [
            {"number": invoice.number, "invoice_date": invoice.invoice_date, "due_date": invoice.due_date,
             "customer__code": invoice.customer.code, "status": invoice.status, "amount": invoice.amount,
            "balance": invoice.calculated_balance}
            for invoice in invoices_with_balance().select_related("customer").order_by("-invoice_date", "-id")[:limit]
        ]
    if report_name == "customer-ledger":
        return list(CustomerLedgerEntry.objects.values("customer__code", "invoice__number", "transaction_date", "entry_type", "reference_number", "amount")[:limit])
    if report_name == "customer-aging":
        today = timezone.localdate()
        rows = []
        invoices = invoices_with_balance().exclude(status=SalesInvoice.Status.CANCELLED).filter(calculated_balance__gt=0)
        for invoice in invoices.select_related("customer")[:limit]:
            balance = invoice.calculated_balance
            age = max(0, (today - invoice.due_date).days)
            bucket = "current" if age == 0 else "1-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
            rows.append({"customer": invoice.customer.code, "invoice": invoice.number, "due_date": invoice.due_date, "days_overdue": age, "bucket": bucket, "balance": balance})
        return rows
    if report_name == "delivery-challans":
        return list(DeliveryChallan.objects.values("number", "order__number", "dispatch_date", "status", "carrier", "tracking_number")[:limit])
    if report_name == "dispatch":
        return list(DispatchAllocation.objects.values("challan_line__challan__number", "batch__batch_number", "batch__product__code", "quantity")[:limit])
    if report_name == "sales-returns":
        return list(SalesReturn.objects.annotate(quantity=Sum("lines__quantity")).values("number", "order__number", "status", "received_at", "quantity")[:limit])
    if report_name == "refunds":
        return list(Refund.objects.values("number", "order__number", "amount", "processed_at")[:limit])
    if report_name == "product-sales":
        return list(SalesInvoice.objects.filter(lines__order_line__isnull=False).values("lines__order_line__erp_product__code", "lines__description").annotate(quantity=Sum("lines__quantity"), amount=Sum("lines__amount"))[:limit])
    if report_name == "customer-sales":
        return list(SalesInvoice.objects.values("customer__code", "customer__business_name").annotate(invoice_count=Count("id"), amount=Sum("amount"))[:limit])
    if report_name == "channel-sales":
        return list(SalesOrder.objects.values("channel").annotate(order_count=Count("id"), amount=Sum("total"))[:limit])
    if report_name == "stock-allocation":
        return list(SalesStockReservation.objects.values("line__order__number", "batch__product__code", "batch__batch_number", "status").annotate(quantity=Sum("quantity"))[:limit])
    raise ValueError("Unknown sales report.")


def ledger_control_total():
    return CustomerLedgerEntry.objects.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
