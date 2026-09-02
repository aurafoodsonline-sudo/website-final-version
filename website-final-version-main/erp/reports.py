from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    AdjustmentDocument,
    GRN,
    OpeningBalance,
    PackingOrder,
    Product,
    ProductionOrder,
    PurchaseOrder,
    QualityInspection,
    StockBatch,
    StockLedgerEntry,
    Supplier,
    SupplierInvoice,
    SupplierLedgerEntry,
    SupplierPayment,
    Warehouse,
)
from .services import fefo_allocation_plan, computed_supplier_balance


ZERO = Decimal("0")
ZERO_MONEY = Decimal("0.00")


def _date_filtered(queryset, date_field: str, *, date_from=None, date_to=None):
    if date_from:
        queryset = queryset.filter(**{f"{date_field}__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{date_field}__lte": date_to})
    return queryset


def supplier_ledger_report(supplier: Supplier, *, date_from=None, date_to=None) -> dict:
    running = Decimal("0.00")
    rows = []
    entries = _date_filtered(
        supplier.ledger_entries.select_related("created_by", "posted_by"),
        "transaction_date",
        date_from=date_from,
        date_to=date_to,
    )
    payable_total = ZERO_MONEY
    advance_total = ZERO_MONEY
    cash_bank_total = ZERO_MONEY
    for entry in entries.order_by("transaction_date", "id"):
        running += entry.payable_effect - entry.advance_effect
        payable_total += entry.payable_effect
        advance_total += entry.advance_effect
        cash_bank_total += entry.cash_bank_effect
        rows.append(
            {
                "supplier_code": supplier.code,
                "supplier_name": supplier.name,
                "date": entry.transaction_date,
                "document_type": entry.source_document_type,
                "document_number": entry.source_document_number,
                "description": entry.description,
                "debit": entry.debit_amount,
                "credit": entry.credit_amount,
                "advance_amount": entry.advance_effect,
                "payable_amount": entry.payable_effect,
                "running_balance": running,
                "reference_document": entry.source_document_number,
                "created_by": getattr(entry.created_by, "username", ""),
                "posted_by": getattr(entry.posted_by, "username", ""),
                "status": "posted",
            }
        )
    return {
        "rows": rows,
        "totals": {
            "payable_effect": payable_total,
            "advance_effect": advance_total,
            "cash_bank_effect": cash_bank_total,
            "net_effect": payable_total - advance_total,
        },
        "closing_running_balance": running,
        "computed_net_balance": supplier.payable_balance - supplier.advance_balance,
        "reconciled": running == payable_total - advance_total,
        "balance_reconciled": not date_from and not date_to and running == supplier.payable_balance - supplier.advance_balance,
        "reconciliation": {
            "source": "SupplierLedgerEntry rows for the selected supplier and optional date range.",
            "formula": "running_balance = sum(payable_effect) - sum(advance_effect)",
            "opening_balance": "Opening supplier payable/advance postings are included as dedicated opening ledger rows.",
            "reversals": "Reversal postings are included as compensating ledger rows.",
            "cancelled_documents": "Cancelled documents are excluded only when no ledger entry was posted.",
        },
    }


def supplier_payable_aging_report(*, supplier: Supplier | None = None, date_from=None, date_to=None) -> dict:
    today = timezone.localdate()
    rows = []
    total = Decimal("0.00")
    invoices = SupplierInvoice.objects.select_related("supplier").filter(
        status__in=["posted", "partially_paid", "overdue"]
    )
    if supplier:
        invoices = invoices.filter(supplier=supplier)
    invoices = _date_filtered(invoices, "invoice_date", date_from=date_from, date_to=date_to)
    for invoice in invoices.order_by("due_date", "number"):
        outstanding = invoice.outstanding_amount
        if outstanding <= 0:
            continue
        days_overdue = max((today - (invoice.due_date or invoice.invoice_date)).days, 0)
        if days_overdue <= 30:
            bucket = "0-30"
        elif days_overdue <= 60:
            bucket = "31-60"
        elif days_overdue <= 90:
            bucket = "61-90"
        else:
            bucket = "90+"
        total += outstanding
        rows.append(
            {
                "supplier_code": invoice.supplier.code,
                "supplier_name": invoice.supplier.name,
                "invoice_number": invoice.number,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "invoice_amount": invoice.amount,
                "paid_amount": invoice.paid_amount,
                "advance_adjusted_amount": invoice.advance_adjusted_amount,
                "debit_note_amount": invoice.debit_note_amount,
                "credit_note_amount": invoice.credit_note_amount,
                "outstanding_amount": outstanding,
                "days_overdue": days_overdue,
                "aging_bucket": bucket,
                "payment_status": "partial" if invoice.paid_amount or invoice.advance_adjusted_amount else "open",
            }
        )
    ledger_entries = SupplierLedgerEntry.objects.all()
    if supplier:
        ledger_entries = ledger_entries.filter(supplier=supplier)
    ledger_entries = _date_filtered(ledger_entries, "transaction_date", date_from=date_from, date_to=date_to)
    ledger_payable = ledger_entries.aggregate(total=Sum("payable_effect"))["total"] or Decimal("0.00")
    unallocated_payable_effect = ledger_payable - total
    return {
        "rows": rows,
        "total_outstanding": total,
        "ledger_payable": ledger_payable,
        "unallocated_payable_effect": unallocated_payable_effect,
        "reconciled": total + unallocated_payable_effect == ledger_payable,
        "reconciliation": {
            "source": "Posted SupplierInvoice rows after paid, advance, debit-note, and credit-note deductions.",
            "formula": "outstanding = amount - paid - advance_adjusted - debit_notes - credit_notes",
            "reversals": "Payment reversals restore invoice paid/advance fields through compensating service logic.",
            "unallocated_payable_effect": "Ledger payable effects not attached to invoice outstanding, such as standalone credit-note modes.",
        },
    }


def _movement_total(batch: StockBatch, *, direction: str, source_prefixes: tuple[str, ...] = ()) -> Decimal:
    entries = batch.stock_entries.filter(direction=direction)
    if source_prefixes:
        selected = ZERO
        for entry in entries:
            if entry.source_document_type in source_prefixes:
                selected += entry.quantity
        return selected
    return entries.aggregate(total=Sum("quantity"))["total"] or ZERO


def _stock_report(batch_type: str, *, include_blocked: bool = False, include_expired: bool = False, warehouse: Warehouse | None = None) -> dict:
    rows = []
    batches = StockBatch.objects.select_related("product", "supplier", "warehouse", "parent_batch").filter(batch_type=batch_type)
    if warehouse:
        batches = batches.filter(warehouse=warehouse)
    if not include_blocked:
        batches = batches.filter(is_blocked=False)
    if not include_expired:
        batches = batches.exclude(expiry_date__lt=timezone.localdate())
    total_available = ZERO
    total_ledger_balance = ZERO
    total_stock_value = ZERO_MONEY
    batches = batches.annotate(
        ledger_in=Sum("stock_entries__quantity", filter=Q(stock_entries__direction=StockLedgerEntry.Direction.IN)),
        ledger_out=Sum("stock_entries__quantity", filter=Q(stock_entries__direction=StockLedgerEntry.Direction.OUT)),
        opening_in=Sum(
            "stock_entries__quantity",
            filter=Q(
                stock_entries__direction=StockLedgerEntry.Direction.IN,
                stock_entries__source_document_type="OPENING_STOCK",
            ),
        ),
        adjustment_in=Sum(
            "stock_entries__quantity",
            filter=Q(
                stock_entries__direction=StockLedgerEntry.Direction.IN,
                stock_entries__source_document_type="STOCK_ADJUSTMENT",
            ),
        ),
        adjustment_out=Sum(
            "stock_entries__quantity",
            filter=Q(
                stock_entries__direction=StockLedgerEntry.Direction.OUT,
                stock_entries__source_document_type="STOCK_ADJUSTMENT",
            ),
        ),
        returned_out=Sum(
            "stock_entries__quantity",
            filter=Q(
                stock_entries__direction=StockLedgerEntry.Direction.OUT,
                stock_entries__source_document_type="SUPPLIER_RETURN",
            ),
        ),
    )
    for batch in batches:
        ins = batch.ledger_in or ZERO
        outs = batch.ledger_out or ZERO
        available = ins - outs
        total_available += batch.quantity_on_hand
        total_ledger_balance += available
        total_stock_value += available * batch.unit_cost
        # Spec 28.6.3 / 28.6.4: full column set required for raw + powder reports
        # issued_to_grinding: OUT movements via PRODUCTION_ISSUE
        issued_grind = ZERO
        for e in batch.stock_entries.filter(source_document_type="PRODUCTION_ISSUE"):
            issued_grind += e.quantity
        # source_production_order: for powder batches, the parent batch's production order
        source_prod_order = ""
        if batch.parent_batch_id:
            src = batch.stock_entries.filter(source_document_type="POWDER_RECEIVED").first()
            if src:
                source_prod_order = src.source_document_number
        # grn_number from source document if batch came from GRN
        grn_number = batch.source_document_number if batch.source_document_type in ("GRN", "GRN_LINE") else ""
        rows.append(
            {
                "product_code": batch.product.code,
                "product_name": batch.product.name,
                "batch_number": batch.batch_number,
                "supplier": batch.supplier.code if batch.supplier else "",
                "warehouse": batch.warehouse.code,
                "grn_number": grn_number,
                "source_production_order": source_prod_order,
                "received_or_produced_quantity": ins,
                "accepted_quantity": ins,  # alias for spec 28.6.3
                "opening_quantity": batch.opening_in or ZERO,
                "issued_to_grinding": issued_grind,  # spec 28.6.3
                "issued_or_consumed_quantity": outs,
                "adjusted_quantity": (batch.adjustment_in or ZERO) - (batch.adjustment_out or ZERO),
                "returned_quantity": batch.returned_out or ZERO,
                "available_quantity": available,
                "unit": batch.product.base_unit.code,
                "cost_per_unit": batch.unit_cost,
                "stock_value": available * batch.unit_cost,
                "stock_state": batch.stock_state,
                "expiry_date": batch.expiry_date,
                "status": "blocked" if batch.is_blocked else "available",
                "source_document": batch.source_document_number,
                "parent_batch": batch.parent_batch.batch_number if batch.parent_batch_id else "",
                "reconciled": available == batch.quantity_on_hand,
            }
        )
    return {
        "rows": rows,
        "totals": {
            "available_quantity": total_available,
            "ledger_balance": total_ledger_balance,
            "stock_value": total_stock_value,
        },
        "reconciled": total_available == total_ledger_balance and all(row["reconciled"] for row in rows),
        "reconciliation": {
            "source": f"StockBatch rows of type {batch_type} plus StockLedgerEntry in/out rows.",
            "formula": "available_quantity = ledger_in - ledger_out and must equal batch.quantity_on_hand.",
            "blocked": "Excluded by default from normal availability; pass include_blocked=True to include.",
            "expired": "Excluded by default from normal availability; pass include_expired=True to include.",
        },
    }


def raw_material_stock_report(**filters) -> dict:
    return _stock_report(StockBatch.BatchType.RAW, **filters)


def powder_stock_report(**filters) -> dict:
    return _stock_report(StockBatch.BatchType.POWDER, **filters)


def packaging_stock_report(**filters) -> dict:
    return _stock_report(StockBatch.BatchType.PACKAGING, **filters)


def finished_goods_stock_report(**filters) -> dict:
    return _stock_report(StockBatch.BatchType.FINISHED, **filters)


def yield_report() -> dict:
    rows = []
    total_issued = ZERO
    total_actual = ZERO
    total_wastage = ZERO
    for order in ProductionOrder.objects.select_related("raw_batch", "powder_product").all():
        total_issued += order.issued_quantity
        total_actual += order.actual_output_quantity
        total_wastage += order.wastage_quantity
        if order.issued_quantity:
            yield_percentage = (order.actual_output_quantity / order.issued_quantity) * Decimal("100")
        else:
            yield_percentage = Decimal("0")
        rows.append(
            {
                "production_order_number": order.number,
                "date": order.created_at.date(),
                "raw_material_code": order.raw_batch.product.code,
                "raw_material_name": order.raw_batch.product.name,
                "raw_batch_number": order.raw_batch.batch_number,
                "supplier": order.raw_batch.supplier.name if order.raw_batch.supplier else "",
                "quantity_issued": order.issued_quantity,
                "expected_powder_output": order.expected_output_quantity,
                "actual_powder_output": order.actual_output_quantity,
                "wastage_quantity": order.wastage_quantity,
                "wastage_percentage": (order.wastage_quantity / order.issued_quantity) * Decimal("100")
                if order.issued_quantity
                else Decimal("0"),
                "yield_percentage": yield_percentage,
                "expected_yield_percentage": (order.expected_output_quantity / order.issued_quantity) * Decimal("100")
                if order.issued_quantity
                else Decimal("0"),
                "yield_variance": order.actual_output_quantity - order.expected_output_quantity,
                "cost_before_grinding": order.issued_quantity * order.raw_batch.unit_cost,
                "cost_after_yield_adjustment": order.actual_output_quantity
                * (order.powder_batch.unit_cost if order.powder_batch else Decimal("0")),
                "operator": getattr(order.created_by, "username", ""),
                "machine": "",
                "status": order.status,
            }
        )
    return {
        "rows": rows,
        "totals": {
            "quantity_issued": total_issued,
            "actual_powder_output": total_actual,
            "wastage_quantity": total_wastage,
            "yield_percentage": (total_actual / total_issued) * Decimal("100") if total_issued else ZERO,
        },
        "reconciliation": {
            "formula": "yield_percentage = actual powder output / raw material issued * 100.",
            "costing": "Powder unit cost is calculated in receive_powder_output from issued raw cost divided by actual output.",
        },
    }


def costing_report() -> dict:
    rows = []
    for order in PackingOrder.objects.select_related("bom", "powder_batch", "finished_batch", "bom__finished_product").all():
        finished_batch = order.finished_batch
        powder_entries = StockLedgerEntry.objects.filter(
            source_document_number=order.number,
            source_document_type="PACKING_CONSUME_POWDER",
            direction=StockLedgerEntry.Direction.OUT,
        )
        packaging_entries = StockLedgerEntry.objects.filter(
            source_document_number=order.number,
            source_document_type="PACKING_CONSUME_PACKAGING",
            direction=StockLedgerEntry.Direction.OUT,
        )
        powder_cost_total = sum(entry.quantity * entry.unit_cost for entry in powder_entries)
        packaging_cost_total = sum(entry.quantity * entry.unit_cost for entry in packaging_entries)
        finished_value = (finished_batch.quantity_on_hand * finished_batch.unit_cost) if finished_batch else ZERO_MONEY
        produced_units = order.completed_units or ZERO
        packaging_material_cost = packaging_cost_total / produced_units if produced_units else ZERO_MONEY
        powder_cost_per_unit = powder_cost_total / produced_units if produced_units else ZERO_MONEY
        finished_unit_cost = finished_batch.unit_cost if finished_batch else ZERO_MONEY
        planned_powder_cost = order.bom.powder_quantity_per_unit * order.completed_units * order.powder_batch.unit_cost
        packing_wastage_cost_impact = powder_cost_total - planned_powder_cost
        production_order = order.powder_batch.source_production.first()
        raw_unit_cost = order.powder_batch.parent_batch.unit_cost if order.powder_batch.parent_batch else ZERO_MONEY
        grinding_wastage_cost_impact = order.powder_batch.unit_cost - raw_unit_cost
        source_total_cost = powder_cost_total + packaging_cost_total
        finished_total_cost = produced_units * finished_unit_cost
        cost_variance = finished_total_cost - source_total_cost
        rows.append(
            {
                "costing_document_reference": order.number,
                "raw_material_batch": order.powder_batch.parent_batch.batch_number if order.powder_batch.parent_batch else "",
                "powder_batch": order.powder_batch.batch_number,
                "finished_goods_batch": finished_batch.batch_number if finished_batch else "",
                "sku": order.bom.finished_product.code,
                "purchase_cost": raw_unit_cost,
                "accepted_quantity_cost": raw_unit_cost,
                "landed_cost": raw_unit_cost,
                "grinding_cost": Decimal("0.00"),
                "grinding_wastage_cost_impact": grinding_wastage_cost_impact,
                "yield_adjusted_powder_cost_per_kg": order.powder_batch.unit_cost,
                "packaging_material_cost": packaging_material_cost,
                "powder_cost_per_finished_unit": powder_cost_per_unit,
                "packing_wastage_quantity": order.wastage_quantity,
                "packing_wastage_cost_impact": packing_wastage_cost_impact,
                "finished_sku_cost": finished_unit_cost,
                "source_total_cost": source_total_cost,
                "finished_total_cost": finished_total_cost,
                "cost_variance": cost_variance,
                "inventory_value": finished_value,
                "costing_method": "batch_actual_cost",
                "production_order": production_order.number if production_order else "",
                "reconciled": abs(cost_variance) <= Decimal("0.01"),
            }
        )
    return {
        "rows": rows,
        "reconciled": all(row["reconciled"] for row in rows),
        "reconciliation": {
            "source": "PackingOrder and StockLedgerEntry rows generated by complete_packing_order.",
            "formula": "finished_total_cost = consumed powder cost + consumed packaging cost.",
            "grinding_wastage": "Absorbed into powder unit cost during powder receipt.",
            "packing_wastage": "Packing wastage is captured on PackingOrder and absorbed into finished SKU cost.",
        },
    }


def expiry_report() -> dict:
    today = timezone.localdate()
    rows = []
    for batch in StockBatch.objects.select_related("product", "warehouse").exclude(expiry_date__isnull=True):
        days = (batch.expiry_date - today).days if batch.expiry_date else None
        status = "expired" if days is not None and days < 0 else "near_expiry" if days is not None and days <= 30 else "valid"
        rows.append(
            {
                "product_type": batch.batch_type,
                "product_code": batch.product.code,
                "product_name": batch.product.name,
                "batch_number": batch.batch_number,
                "sku": batch.product.code if batch.batch_type == StockBatch.BatchType.FINISHED else "",
                "warehouse": batch.warehouse.code,
                "available_quantity": batch.quantity_on_hand,
                "manufacturing_date": batch.manufacturing_date,
                "packing_date": batch.packing_date,
                "expiry_date": batch.expiry_date,
                "best_before_date": batch.expiry_date,
                "near_expiry_threshold_date": batch.expiry_date,
                "days_to_expiry": days,
                "expiry_status": status,
                "fefo_priority": days,
                "blocked": batch.is_blocked,
                "action_recommended": "block" if status == "expired" else "use_first" if status == "near_expiry" else "none",
            }
        )
    return {
        "rows": rows,
        "totals": {
            "expired": sum(1 for row in rows if row["expiry_status"] == "expired"),
            "near_expiry": sum(1 for row in rows if row["expiry_status"] == "near_expiry"),
            "valid": sum(1 for row in rows if row["expiry_status"] == "valid"),
        },
        "reconciliation": {
            "source": "StockBatch expiry_date and current quantity_on_hand.",
            "formula": "days_to_expiry = expiry_date - current local date.",
        },
    }


def purchase_report(*, supplier: Supplier | None = None) -> dict:
    orders = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines")
    if supplier:
        orders = orders.filter(supplier=supplier)
    rows = []
    total_ordered_value = ZERO_MONEY
    for order in orders.order_by("order_date", "number"):
        amount = sum(line.quantity * line.unit_cost for line in order.lines.all())
        total_ordered_value += amount
        rows.append(
            {
                "purchase_order_number": order.number,
                "supplier_code": order.supplier.code,
                "supplier_name": order.supplier.name,
                "order_date": order.order_date,
                "expected_date": order.expected_date,
                "status": order.status,
                "line_count": order.lines.count(),
                "ordered_value": amount,
            }
        )
    return {"rows": rows, "totals": {"ordered_value": total_ordered_value, "orders": len(rows)}}


def grn_report(*, supplier: Supplier | None = None) -> dict:
    grns = GRN.objects.select_related("supplier", "purchase_order").prefetch_related("lines")
    if supplier:
        grns = grns.filter(supplier=supplier)
    rows = []
    total_payable = ZERO_MONEY
    total_shortage = ZERO_MONEY
    total_rejected = ZERO
    for grn in grns.order_by("grn_date", "number"):
        rejected = sum(line.rejected_quantity for line in grn.lines.all())
        total_rejected += rejected
        total_payable += grn.payable_amount
        total_shortage += grn.shortage_amount
        rows.append(
            {
                "grn_number": grn.number,
                "supplier_code": grn.supplier.code,
                "supplier_name": grn.supplier.name,
                "purchase_order": grn.purchase_order.number if grn.purchase_order else "",
                "grn_date": grn.grn_date,
                "status": grn.status,
                "payable_amount": grn.payable_amount,
                "shortage_amount": grn.shortage_amount,
                "quality_deduction_amount": grn.quality_deduction_amount,
                "rejected_quantity": rejected,
            }
        )
    return {"rows": rows, "totals": {"payable_amount": total_payable, "shortage_amount": total_shortage, "rejected_quantity": total_rejected}}


def quality_rejection_report() -> dict:
    rows = []
    total_deduction = ZERO_MONEY
    for inspection in QualityInspection.objects.select_related("grn", "grn__supplier").order_by("created_at"):
        total_deduction += inspection.deduction_amount
        rejected = sum(line.rejected_quantity for line in inspection.grn.lines.all())
        rows.append(
            {
                "grn_number": inspection.grn.number,
                "supplier_code": inspection.grn.supplier.code,
                "supplier_name": inspection.grn.supplier.name,
                "deduction_amount": inspection.deduction_amount,
                "rejected_quantity": rejected,
                "moisture_ok": inspection.moisture_ok,
                "aroma_ok": inspection.aroma_ok,
                "contamination_ok": inspection.contamination_ok,
                "status": inspection.status,
            }
        )
    return {"rows": rows, "totals": {"deduction_amount": total_deduction, "inspections": len(rows)}}


def wastage_report() -> dict:
    rows = []
    total_wastage = ZERO
    for order in ProductionOrder.objects.select_related("raw_batch", "powder_product").order_by("created_at"):
        total_wastage += order.wastage_quantity
        rows.append(
            {
                "production_order_number": order.number,
                "raw_batch": order.raw_batch.batch_number,
                "powder_product": order.powder_product.code,
                "issued_quantity": order.issued_quantity,
                "actual_output_quantity": order.actual_output_quantity,
                "wastage_quantity": order.wastage_quantity,
                "wastage_percentage": (order.wastage_quantity / order.issued_quantity) * Decimal("100") if order.issued_quantity else ZERO,
                "status": order.status,
            }
        )
    packing_wastage = ZERO
    for order in PackingOrder.objects.select_related("bom", "bom__finished_product").order_by("created_at"):
        packing_wastage += order.wastage_quantity
        rows.append(
            {
                "production_order_number": "",
                "packing_order_number": order.number,
                "raw_batch": "",
                "powder_product": order.bom.finished_product.code,
                "issued_quantity": order.completed_units + order.wastage_quantity,
                "actual_output_quantity": order.completed_units,
                "wastage_quantity": order.wastage_quantity,
                "wastage_percentage": (order.wastage_quantity / (order.completed_units + order.wastage_quantity)) * Decimal("100")
                if order.completed_units + order.wastage_quantity
                else ZERO,
                "status": order.status,
            }
        )
    return {"rows": rows, "totals": {"wastage_quantity": total_wastage + packing_wastage, "packing_wastage_quantity": packing_wastage}}


def packing_report() -> dict:
    rows = []
    total_units = ZERO
    for order in PackingOrder.objects.select_related("bom", "bom__finished_product", "powder_batch", "finished_batch").order_by("created_at"):
        total_units += order.completed_units
        rows.append(
            {
                "packing_order_number": order.number,
                "finished_sku": order.bom.finished_product.code,
                "powder_batch": order.powder_batch.batch_number,
                "finished_batch": order.finished_batch.batch_number if order.finished_batch else "",
                "planned_units": order.planned_units,
                "completed_units": order.completed_units,
                "wastage_units": order.wastage_quantity,
                "planned_powder_consumption": order.bom.powder_quantity_per_unit * order.completed_units,
                "actual_powder_consumption": order.bom.powder_quantity_per_unit * (order.completed_units + order.wastage_quantity),
                "status": order.status,
            }
        )
    return {
        "rows": rows,
        "totals": {
            "completed_units": total_units,
            "wastage_units": sum(row["wastage_units"] for row in rows),
            "orders": len(rows),
        },
    }


def fefo_dispatch_report(*, product: Product | None = None, warehouse: Warehouse | None = None, required_quantity: Decimal | None = None) -> dict:
    if not product:
        return {
            "rows": [],
            "totals": {"allocated_quantity": ZERO, "shortage_quantity": required_quantity or ZERO},
            "reconciliation": {
                "source": "Select a finished SKU product to generate a FEFO dispatch allocation plan.",
                "strategy": "Earliest non-expired batch first; blocked and expired batches are excluded.",
            },
        }
    plan = fefo_allocation_plan(product=product, warehouse=warehouse, required_quantity=required_quantity)
    return {
        "rows": plan["rows"],
        "totals": {
            "required_quantity": required_quantity or ZERO,
            "allocated_quantity": plan["allocated_quantity"],
            "shortage_quantity": plan["shortage_quantity"],
            "allocation_value": sum(row["allocation_value"] for row in plan["rows"]),
        },
        "reconciled": plan["reconciled"],
        "reconciliation": {
            "source": "StockBatch finished-goods rows with positive quantity, non-blocked status, and non-expired expiry dates.",
            "strategy": plan["strategy"],
            "mutation": "Read-only dispatch suggestion; final sales/dispatch posting remains a future module.",
        },
    }


def packaging_consumption_report() -> dict:
    rows = []
    total_quantity = ZERO
    total_value = ZERO_MONEY
    entries = StockLedgerEntry.objects.select_related("product", "batch", "warehouse").filter(
        source_document_type="PACKING_CONSUME_PACKAGING",
        direction=StockLedgerEntry.Direction.OUT,
    )
    for entry in entries.order_by("transaction_date", "source_document_number"):
        value = entry.quantity * entry.unit_cost
        total_quantity += entry.quantity
        total_value += value
        rows.append(
            {
                "packing_order_number": entry.source_document_number,
                "packaging_item_code": entry.product.code,
                "packaging_item_name": entry.product.name,
                "batch_number": entry.batch.batch_number,
                "warehouse": entry.warehouse.code,
                "quantity": entry.quantity,
                "unit_cost": entry.unit_cost,
                "value": value,
            }
        )
    return {"rows": rows, "totals": {"quantity": total_quantity, "value": total_value}}


def near_expiry_report() -> dict:
    """
    Near-expiry batches within the configured threshold.
    Spec 28.6.9: includes near_expiry_threshold_date, days_to_expiry, action_recommended.
    Source: expiry_report filtered to near_expiry status.
    """
    from .models import Company
    threshold_days = 30
    try:
        co = Company.objects.filter(is_active=True).first()
        if co:
            threshold_days = co.near_expiry_threshold_days
    except Exception:
        pass
    today = timezone.localdate()
    data = expiry_report()
    rows = []
    for row in data["rows"]:
        if row["expiry_status"] == "near_expiry":
            expiry = row.get("expiry_date")
            days = (expiry - today).days if expiry else None
            row["near_expiry_threshold_days"] = threshold_days
            row["near_expiry_threshold_date"] = today + timezone.timedelta(days=threshold_days)
            row["days_to_expiry"] = days
            row["action_recommended"] = "dispatch_first_fefo"
            rows.append(row)
    return {
        "rows": rows,
        "totals": {"near_expiry": len(rows), "threshold_days": threshold_days},
        "reconciliation": {
            "formula": "expiry_status=near_expiry when 0 <= days_to_expiry <= threshold_days.",
            "source": "expiry_report filtered on near_expiry status.",
        },
    }


def expired_stock_report() -> dict:
    data = expiry_report()
    rows = [row for row in data["rows"] if row["expiry_status"] == "expired"]
    return {"rows": rows, "totals": {"expired": len(rows)}}


def adjustment_report(adjustment_type: str | None = None) -> dict:
    docs = AdjustmentDocument.objects.select_related("supplier", "product", "batch")
    if adjustment_type:
        docs = docs.filter(adjustment_type=adjustment_type)
    rows = []
    total_amount = ZERO_MONEY
    total_quantity = ZERO
    for doc in docs.order_by("created_at", "number"):
        total_amount += doc.amount
        total_quantity += doc.quantity
        rows.append(
            {
                "number": doc.number,
                "adjustment_type": doc.adjustment_type,
                "supplier": doc.supplier.code if doc.supplier else "",
                "product": doc.product.code if doc.product else "",
                "batch": doc.batch.batch_number if doc.batch else "",
                "amount": doc.amount,
                "quantity": doc.quantity,
                "balance_effect": doc.balance_effect,
                "reason": doc.reason,
                "status": doc.status,
            }
        )
    return {"rows": rows, "totals": {"amount": total_amount, "quantity": total_quantity, "documents": len(rows)}}


def payment_reversal_report() -> dict:
    rows = []
    total = ZERO_MONEY
    payments = SupplierPayment.objects.select_related("supplier", "reversal_of").filter(payment_type=SupplierPayment.PaymentType.REVERSAL)
    for payment in payments.order_by("payment_date", "number"):
        total += payment.amount
        rows.append(
            {
                "reversal_number": payment.number,
                "reversal_of": payment.reversal_of.number if payment.reversal_of else "",
                "supplier_code": payment.supplier.code,
                "supplier_name": payment.supplier.name,
                "amount": payment.amount,
                "payment_date": payment.payment_date,
                "reason": payment.reason,
                "status": payment.status,
            }
        )
    return {"rows": rows, "totals": {"amount": total, "reversals": len(rows)}}


def opening_balance_report() -> dict:
    rows = []
    total_amount = ZERO_MONEY
    total_quantity = ZERO
    for opening in OpeningBalance.objects.select_related("product", "supplier", "cash_bank_account", "warehouse").order_by("created_at"):
        total_amount += opening.amount
        total_quantity += opening.quantity
        rows.append(
            {
                "opening_number": opening.number,
                "product": opening.product.code if opening.product else "",
                "supplier": opening.supplier.code if opening.supplier else "",
                "cash_bank_account": opening.cash_bank_account.code if opening.cash_bank_account else "",
                "warehouse": opening.warehouse.code if opening.warehouse else "",
                "quantity": opening.quantity,
                "amount": opening.amount,
                "status": opening.status,
            }
        )
    return {"rows": rows, "totals": {"amount": total_amount, "quantity": total_quantity, "openings": len(rows)}}


def batch_traceability_report() -> dict:
    trace_back = []
    trace_forward = []
    for finished in StockBatch.objects.filter(batch_type=StockBatch.BatchType.FINISHED).select_related("parent_batch", "product"):
        powder = finished.parent_batch
        raw = powder.parent_batch if powder else None
        trace_back.append(
            {
                "finished_sku": finished.product.code,
                "finished_goods_batch": finished.batch_number,
                "packing_order": finished.source_document_number,
                "powder_batch": powder.batch_number if powder else "",
                "production_order": powder.source_document_number if powder else "",
                "raw_material_batch": raw.batch_number if raw else "",
                "grn_number": raw.source_document_number if raw else "",
                "supplier": raw.supplier.name if raw and raw.supplier else "",
                "quality_inspection_reference": raw.source_document_number if raw else "",
                "manufacturing_date": finished.manufacturing_date,
                "expiry_date": finished.expiry_date,
                "quantity_produced": finished.stock_entries.filter(direction=StockLedgerEntry.Direction.IN).aggregate(total=Sum("quantity"))[
                    "total"
                ]
                or ZERO,
                "quantity_remaining": finished.quantity_on_hand,
            }
        )
    for raw in StockBatch.objects.filter(batch_type=StockBatch.BatchType.RAW).select_related("supplier", "product"):
        for powder in raw.children.filter(batch_type=StockBatch.BatchType.POWDER):
            for finished in powder.children.filter(batch_type=StockBatch.BatchType.FINISHED):
                trace_forward.append(
                    {
                        "raw_material_batch": raw.batch_number,
                        "grn_number": raw.source_document_number,
                        "supplier": raw.supplier.name if raw.supplier else "",
                        "accepted_quantity": raw.stock_entries.filter(direction=StockLedgerEntry.Direction.IN).aggregate(total=Sum("quantity"))[
                            "total"
                        ]
                        or ZERO,
                        "production_order": powder.source_document_number,
                        "powder_batch": powder.batch_number,
                        "powder_quantity_produced": powder.stock_entries.filter(direction=StockLedgerEntry.Direction.IN).aggregate(
                            total=Sum("quantity")
                        )["total"]
                        or ZERO,
                        "packing_order": finished.source_document_number,
                        "finished_sku": finished.product.code,
                        "finished_goods_batch": finished.batch_number,
                        "finished_quantity_produced": finished.stock_entries.filter(direction=StockLedgerEntry.Direction.IN).aggregate(
                            total=Sum("quantity")
                        )["total"]
                        or ZERO,
                        "finished_quantity_remaining": finished.quantity_on_hand,
                        "expiry_date": finished.expiry_date,
                        "current_status": "blocked" if finished.is_blocked else "available",
                    }
                )
    return {
        "trace_back": trace_back,
        "trace_forward": trace_forward,
        "reconciled": bool(trace_back) == bool(trace_forward) or not trace_back,
        "reconciliation": {
            "trace_back": "Finished batch -> powder parent batch -> raw parent batch -> GRN/supplier source.",
            "trace_forward": "Raw batch children -> powder children -> finished goods batches.",
        },
    }


# ── LOW STOCK REPORT ─────────────────────────────────────────────────────────

def low_stock_report() -> dict:
    """
    Items whose current available stock is at or below reorder_level or minimum_stock.
    Spec 3.50 / 28: Low stock report.
    Source: StockBatch aggregated by product vs Product.minimum_stock / reorder_level.
    """
    from django.db.models import Sum
    rows = []
    products = Product.objects.filter(is_active=True).select_related("base_unit")
    for product in products:
        available = (
            StockBatch.objects.filter(
                product=product, is_blocked=False, quantity_on_hand__gt=0
            )
            .exclude(stock_state__in=["rejected", "damaged", "expired", "issued"])
            .aggregate(total=Sum("quantity_on_hand"))["total"] or Decimal("0")
        )
        min_stock = product.minimum_stock or Decimal("0")
        reorder = product.reorder_level or min_stock
        if reorder > 0 and available <= reorder:
            rows.append({
                "product_code": product.code,
                "product_name": product.name,
                "product_type": product.product_type,
                "unit": product.base_unit.code,
                "available_quantity": available,
                "minimum_stock": min_stock,
                "reorder_level": reorder,
                "maximum_stock": product.maximum_stock,
                "shortage": max(reorder - available, Decimal("0")),
                "status": "critical" if available <= min_stock else "low",
                "default_supplier": product.default_supplier.code if product.default_supplier_id else "",
            })
    rows.sort(key=lambda r: (r["status"] == "low", r["shortage"]), reverse=True)
    return {
        "rows": rows,
        "totals": {"critical": sum(1 for r in rows if r["status"] == "critical"),
                   "low": sum(1 for r in rows if r["status"] == "low"),
                   "total_items": len(rows)},
        "reconciliation": {
            "formula": "available_quantity = sum(StockBatch.quantity_on_hand) where not blocked/rejected/damaged/expired/issued.",
            "source": "StockBatch aggregated per product vs Product.reorder_level.",
        },
    }


# ── SUPPLIER RETURN REPORT ────────────────────────────────────────────────────

def supplier_return_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    All supplier return transactions.
    Spec 3.50: Supplier return report.
    Source: AdjustmentDocument where adjustment_type=supplier_return.
    """
    qs = AdjustmentDocument.objects.filter(
        adjustment_type="supplier_return"
    ).select_related("supplier", "product", "batch")
    if supplier:
        qs = qs.filter(supplier=supplier)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for doc in qs.order_by("-created_at"):
        rows.append({
            "document_number": doc.number,
            "date": doc.created_at.date(),
            "supplier": doc.supplier.code if doc.supplier_id else "",
            "supplier_name": doc.supplier.name if doc.supplier_id else "",
            "product": doc.product.code if doc.product_id else "",
            "product_name": doc.product.name if doc.product_id else "",
            "batch": doc.batch.batch_number if doc.batch_id else "",
            "quantity_returned": doc.quantity,
            "amount": doc.amount,
            "reason": doc.reason,
            "status": doc.status,
        })
    total_qty = sum(r["quantity_returned"] for r in rows if r["quantity_returned"])
    total_amt = sum(r["amount"] for r in rows if r["amount"])
    return {
        "rows": rows,
        "totals": {"total_returns": len(rows), "total_quantity": total_qty, "total_amount": total_amt},
        "reconciliation": {
            "source": "AdjustmentDocument(adjustment_type=supplier_return).",
            "formula": "All posted supplier return documents in date range.",
        },
    }


# ── SUPPLIER BALANCE SUMMARY REPORT ──────────────────────────────────────────

def supplier_balance_summary_report(supplier=None) -> dict:
    """
    Supplier balance summary: payable, advance, net per supplier.
    Spec 3.50 / 29.1: Supplier balance must be separately auditable.
    Source: Supplier.payable_balance, Supplier.advance_balance (cached) +
            computed from SupplierLedgerEntry for verification.
    """
    qs = Supplier.objects.filter(is_active=True).order_by("code")
    if supplier:
        qs = qs.filter(pk=supplier.pk)
    rows = []
    for sup in qs:
        computed = computed_supplier_balance(sup)
        rows.append({
            "supplier_code": sup.code,
            "supplier_name": sup.name,
            "cached_payable": sup.payable_balance,
            "cached_advance": sup.advance_balance,
            "computed_payable": computed["payable"],
            "computed_advance": computed["advance"],
            "net_balance": computed["payable"] - computed["advance"],
            "is_reconciled": (
                abs(sup.payable_balance - computed["payable"]) < Decimal("0.01") and
                abs(sup.advance_balance - computed["advance"]) < Decimal("0.01")
            ),
        })
    return {
        "rows": rows,
        "totals": {
            "total_payable": sum(r["computed_payable"] for r in rows),
            "total_advance": sum(r["computed_advance"] for r in rows),
            "total_net": sum(r["net_balance"] for r in rows),
            "unreconciled": sum(1 for r in rows if not r["is_reconciled"]),
        },
        "reconciliation": {
            "formula": "computed_payable = sum(SupplierLedgerEntry.payable_effect); cached vs computed are both shown.",
            "source": "Supplier.payable_balance (cached) vs computed_supplier_balance() from SupplierLedgerEntry.",
        },
    }


# ── DAMAGED STOCK REPORT ─────────────────────────────────────────────────────

def damaged_stock_report(warehouse=None, include_expired=False) -> dict:
    """
    All batches in damaged/expired/blocked state with remaining quantity.
    Spec 3.50 / 28: Damaged stock report.
    Source: StockBatch where stock_state in damaged/expired/blocked/rejected.
    """
    from django.utils import timezone
    states = ["damaged", "blocked", "rejected"]
    if include_expired:
        states.append("expired")
    qs = StockBatch.objects.filter(
        stock_state__in=states, quantity_on_hand__gt=0
    ).select_related("product", "warehouse", "supplier")
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    rows = []
    for b in qs.order_by("product__code", "expiry_date"):
        rows.append({
            "batch_number": b.batch_number,
            "product_code": b.product.code,
            "product_name": b.product.name,
            "product_type": b.product.product_type,
            "stock_state": b.stock_state,
            "warehouse": b.warehouse.code,
            "quantity_on_hand": b.quantity_on_hand,
            "unit_cost": b.unit_cost,
            "stock_value": b.quantity_on_hand * b.unit_cost,
            "expiry_date": b.expiry_date,
            "supplier": b.supplier.code if b.supplier_id else "",
            "source_document": b.source_document_number,
            "block_reason": b.block_reason,
            "action_recommended": "write_off" if b.stock_state in ("damaged","expired") else "investigate",
        })
    total_value = sum(r["stock_value"] for r in rows)
    return {
        "rows": rows,
        "totals": {"total_batches": len(rows), "total_value": total_value},
        "reconciliation": {
            "source": "StockBatch where stock_state in (damaged, blocked, rejected[, expired]).",
            "formula": "quantity_on_hand × unit_cost per batch.",
        },
    }


# ── SUPPLIER ADVANCE REPORT ───────────────────────────────────────────────────

def supplier_advance_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    All supplier advance transactions with utilisation status.
    Spec 3.50 / 29.1: Supplier advance must be separately auditable.
    Source: SupplierPayment where payment_type=advance.
    """
    qs = SupplierPayment.objects.filter(
        payment_type="advance"
    ).select_related("supplier", "cash_bank_account")
    if supplier:
        qs = qs.filter(supplier=supplier)
    if date_from:
        qs = qs.filter(payment_date__gte=date_from)
    if date_to:
        qs = qs.filter(payment_date__lte=date_to)
    rows = []
    for p in qs.order_by("-payment_date"):
        rows.append({
            "voucher_number": p.number,
            "payment_date": p.payment_date,
            "supplier_code": p.supplier.code,
            "supplier_name": p.supplier.name,
            "advance_amount": p.amount,
            "payment_method": p.payment_method,
            "account": p.cash_bank_account.name if p.cash_bank_account_id else "",
            "reference": p.reference_number,
            "status": p.status,
            "reversal_of": p.reversal_of_id,
            "amount_in_words": p.amount_in_words,
        })
    total = sum(r["advance_amount"] for r in rows if r["status"] != "reversed")
    return {
        "rows": rows,
        "totals": {"total_advances": len(rows), "total_active_amount": total},
        "reconciliation": {
            "source": "SupplierPayment(payment_type=advance) excluding reversed.",
            "formula": "Sum of advance amounts in period; net advance per supplier from SupplierLedgerEntry.",
        },
    }


# ── SUPPLIER REJECTION REPORT ─────────────────────────────────────────────────

def supplier_rejection_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    GRN-level rejection summary per supplier.
    Spec 3.50: Supplier-wise rejection report.
    Source: GRNLine where rejected_quantity > 0.
    """
    from .models import GRNLine
    qs = GRNLine.objects.filter(
        rejected_quantity__gt=0
    ).select_related("grn__supplier", "product", "grn")
    if supplier:
        qs = qs.filter(grn__supplier=supplier)
    if date_from:
        qs = qs.filter(grn__grn_date__gte=date_from)
    if date_to:
        qs = qs.filter(grn__grn_date__lte=date_to)
    rows = []
    for line in qs.order_by("-grn__grn_date"):
        rows.append({
            "grn_number": line.grn.number,
            "grn_date": line.grn.grn_date,
            "supplier_code": line.grn.supplier.code,
            "supplier_name": line.grn.supplier.name,
            "product_code": line.product.code,
            "product_name": line.product.name,
            "batch_number": line.batch_number,
            "received_quantity": line.received_quantity,
            "accepted_quantity": line.accepted_quantity,
            "rejected_quantity": line.rejected_quantity,
            "rejection_rate_pct": (
                (line.rejected_quantity / line.received_quantity * 100)
                if line.received_quantity else Decimal("0")
            ),
            "unit_cost": line.unit_cost,
            "rejection_value": line.rejected_quantity * line.unit_cost,
        })
    total_rejected = sum(r["rejected_quantity"] for r in rows)
    total_rejection_value = sum(r["rejection_value"] for r in rows)
    return {
        "rows": rows,
        "totals": {"total_rejection_lines": len(rows),
                   "total_rejected_quantity": total_rejected,
                   "total_rejection_value": total_rejection_value},
        "reconciliation": {
            "source": "GRNLine where rejected_quantity > 0.",
            "formula": "rejection_rate_pct = rejected_quantity / received_quantity × 100.",
        },
    }


# ── SUPPLIER SHORTAGE REPORT ──────────────────────────────────────────────────

def supplier_shortage_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    GRN-level shortage summary per supplier.
    Spec 3.50: Supplier-wise shortage report.
    Source: GRNLine where shortage_quantity > 0.
    """
    from .models import GRNLine
    qs = GRNLine.objects.filter(
        shortage_quantity__gt=0
    ).select_related("grn__supplier", "product", "grn")
    if supplier:
        qs = qs.filter(grn__supplier=supplier)
    if date_from:
        qs = qs.filter(grn__grn_date__gte=date_from)
    if date_to:
        qs = qs.filter(grn__grn_date__lte=date_to)
    rows = []
    for line in qs.order_by("-grn__grn_date"):
        rows.append({
            "grn_number": line.grn.number,
            "grn_date": line.grn.grn_date,
            "supplier_code": line.grn.supplier.code,
            "supplier_name": line.grn.supplier.name,
            "product_code": line.product.code,
            "product_name": line.product.name,
            "batch_number": line.batch_number,
            "ordered_quantity": line.ordered_quantity,
            "received_quantity": line.received_quantity,
            "shortage_quantity": line.shortage_quantity,
            "shortage_rate_pct": (
                (line.shortage_quantity / line.ordered_quantity * 100)
                if line.ordered_quantity else Decimal("0")
            ),
            "shortage_value": line.shortage_quantity * line.unit_cost,
        })
    total_shortage = sum(r["shortage_quantity"] for r in rows)
    return {
        "rows": rows,
        "totals": {"total_shortage_lines": len(rows), "total_shortage_quantity": total_shortage},
        "reconciliation": {
            "source": "GRNLine where shortage_quantity > 0.",
            "formula": "shortage_quantity = ordered_quantity - received_quantity.",
        },
    }


# ── SUPPLIER YIELD REPORT ─────────────────────────────────────────────────────

def supplier_yield_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    Supplier-wise grinding yield summary.
    Spec 3.50: Supplier-wise yield report.
    Source: ProductionOrder grouped by supplier (via raw_batch.supplier).
    """
    from django.db.models import Avg, Sum
    qs = ProductionOrder.objects.filter(
        status__in=["powder_received", "closed"]
    ).select_related("raw_batch__supplier", "raw_batch__product", "powder_product")
    if supplier:
        qs = qs.filter(raw_batch__supplier=supplier)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for o in qs.order_by("raw_batch__supplier__code", "-created_at"):
        raw_supplier = o.raw_batch.supplier if o.raw_batch_id and o.raw_batch.supplier_id else None
        actual_out = o.actual_output_quantity or Decimal("0")
        issued = o.issued_quantity or Decimal("0")
        yield_pct = (actual_out / issued * 100) if issued else Decimal("0")
        rows.append({
            "production_order": o.number,
            "date": o.created_at.date(),
            "supplier_code": raw_supplier.code if raw_supplier else "",
            "supplier_name": raw_supplier.name if raw_supplier else "",
            "raw_product": o.raw_batch.product.code if o.raw_batch_id else "",
            "raw_batch": o.raw_batch.batch_number if o.raw_batch_id else "",
            "powder_product": o.powder_product.code if o.powder_product_id else "",
            "issued_quantity": issued,
            "actual_output": actual_out,
            "wastage_quantity": o.wastage_quantity or Decimal("0"),
            "yield_pct": yield_pct.quantize(Decimal("0.001")),
            "expected_yield_pct": (
                o.raw_batch.product.expected_grinding_yield_pct
                if o.raw_batch_id and o.raw_batch.product.expected_grinding_yield_pct
                else None
            ),
        })
    # Supplier-level summary
    by_supplier = {}
    for r in rows:
        k = r["supplier_code"]
        if k not in by_supplier:
            by_supplier[k] = {"issued": Decimal("0"), "output": Decimal("0"), "orders": 0}
        by_supplier[k]["issued"] += r["issued_quantity"]
        by_supplier[k]["output"] += r["actual_output"]
        by_supplier[k]["orders"] += 1
    supplier_summary = [
        {"supplier_code": k, "total_issued": v["issued"], "total_output": v["output"],
         "avg_yield_pct": (v["output"] / v["issued"] * 100).quantize(Decimal("0.001")) if v["issued"] else Decimal("0"),
         "total_orders": v["orders"]}
        for k, v in by_supplier.items()
    ]
    return {
        "rows": rows,
        "supplier_summary": supplier_summary,
        "totals": {"total_orders": len(rows),
                   "total_issued": sum(r["issued_quantity"] for r in rows),
                   "total_output": sum(r["actual_output"] for r in rows)},
        "reconciliation": {
            "source": "ProductionOrder where status in (powder_received, closed).",
            "formula": "yield_pct = actual_output / issued_quantity × 100.",
        },
    }


# ── REPACKING REPORT ──────────────────────────────────────────────────────────

def repacking_report(date_from=None, date_to=None) -> dict:
    """
    All repacking adjustment documents.
    Spec 3.50: Repacking report.
    Source: AdjustmentDocument where adjustment_type=repacking.
    """
    qs = AdjustmentDocument.objects.filter(
        adjustment_type="repacking"
    ).select_related("supplier", "product", "batch")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for doc in qs.order_by("-created_at"):
        rows.append({
            "document_number": doc.number,
            "date": doc.created_at.date(),
            "product_code": doc.product.code if doc.product_id else "",
            "product_name": doc.product.name if doc.product_id else "",
            "source_batch": doc.batch.batch_number if doc.batch_id else "",
            "quantity": doc.quantity,
            "amount": doc.amount,
            "reason": doc.reason,
            "status": doc.status,
        })
    return {
        "rows": rows,
        "totals": {"total_repacking_orders": len(rows),
                   "total_quantity": sum(r["quantity"] for r in rows if r["quantity"])},
        "reconciliation": {
            "source": "AdjustmentDocument(adjustment_type=repacking).",
        },
    }


# ── USER ACTIVITY REPORT ──────────────────────────────────────────────────────

def user_activity_report(user=None, date_from=None, date_to=None) -> dict:
    """
    Activity summary from AuditEvent per user.
    Spec 3.50 / Control: User activity report.
    Source: AuditEvent model.
    """
    from .models import AuditEvent
    qs = AuditEvent.objects.select_related("user")
    if user:
        qs = qs.filter(user=user)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for event in qs.order_by("-created_at")[:1000]:
        rows.append({
            "timestamp": event.created_at,
            "user": event.user.username if event.user_id else "system",
            "event_type": event.event_type,
            "source_type": event.source_type,
            "document_number": event.source_number,
            "message": event.message[:120],
            "ip_address": event.ip_address,
        })
    return {
        "rows": rows,
        "totals": {"total_events": len(rows)},
        "reconciliation": {
            "source": "AuditEvent (latest 1000). Increase limit for full history.",
        },
    }


# ── APPROVAL PENDING REPORT ───────────────────────────────────────────────────

def approval_pending_report() -> dict:
    """
    All documents in draft/pending status requiring approval action.
    Spec 3.50 / Control: Approval pending report.
    Source: Multiple models queried for draft/pending status.
    """
    from .models import PurchaseOrder, GRN, SupplierInvoice, AdjustmentDocument, PurchaseRequirement
    rows = []

    for po in PurchaseOrder.objects.filter(status="draft").select_related("supplier"):
        rows.append({"document_type": "Purchase Order", "number": po.number,
                     "date": po.created_at.date(), "supplier": po.supplier.code,
                     "status": po.status, "created_by": po.created_by.username if po.created_by_id else ""})

    for grn in GRN.objects.exclude(status__in=["approved", "cancelled", "reversed"]).select_related("supplier"):
        rows.append({"document_type": "GRN", "number": grn.number,
                     "date": grn.grn_date, "supplier": grn.supplier.code,
                     "status": grn.status, "created_by": grn.created_by.username if grn.created_by_id else ""})

    for inv in SupplierInvoice.objects.filter(status="draft").select_related("supplier"):
        rows.append({"document_type": "Supplier Invoice", "number": inv.number,
                     "date": inv.invoice_date, "supplier": inv.supplier.code,
                     "status": inv.status, "created_by": inv.created_by.username if inv.created_by_id else ""})

    for adj in AdjustmentDocument.objects.filter(status="draft").select_related("supplier"):
        rows.append({"document_type": adj.adjustment_type.replace("_", " ").title(),
                     "number": adj.number, "date": adj.created_at.date(),
                     "supplier": adj.supplier.code if adj.supplier_id else "",
                     "status": adj.status, "created_by": adj.created_by.username if adj.created_by_id else ""})

    for pr in PurchaseRequirement.objects.filter(status="draft").select_related("product"):
        rows.append({"document_type": "Purchase Requirement", "number": pr.number,
                     "date": pr.created_at.date() if pr.created_at else "",
                     "supplier": pr.product.code,
                     "status": pr.status, "created_by": pr.created_by.username if pr.created_by_id else ""})

    return {
        "rows": rows,
        "totals": {"total_pending": len(rows)},
        "reconciliation": {
            "source": "PurchaseOrder(draft), GRN(not approved/cancelled), SupplierInvoice(draft), AdjustmentDocument(draft), PurchaseRequirement(draft).",
        },
    }


# ── GRINDING / PRODUCTION OUTPUT REPORT ──────────────────────────────────────

def grinding_report(supplier=None, date_from=None, date_to=None) -> dict:
    """
    All grinding/production orders with input, output, wastage and yield.
    Spec 3.50 / 3.29 Yield and Wastage Tracking.
    Source: ProductionOrder (all statuses).
    """
    qs = ProductionOrder.objects.select_related(
        "raw_batch__product", "raw_batch__supplier", "powder_product"
    )
    if supplier:
        qs = qs.filter(raw_batch__supplier=supplier)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for o in qs.order_by("-created_at"):
        issued = o.issued_quantity or Decimal("0")
        actual = o.actual_output_quantity or Decimal("0")
        wastage = o.wastage_quantity or Decimal("0")
        expected = o.expected_output_quantity or Decimal("0")
        yld = (actual / issued * 100).quantize(Decimal("0.001")) if issued else Decimal("0")
        rows.append({
            "order_number": o.number,
            "date": o.created_at.date(),
            "status": o.status,
            "raw_product": o.raw_batch.product.code if o.raw_batch_id else "",
            "raw_batch": o.raw_batch.batch_number if o.raw_batch_id else "",
            "supplier": o.raw_batch.supplier.code if o.raw_batch_id and o.raw_batch.supplier_id else "",
            "powder_product": o.powder_product.code if o.powder_product_id else "",
            "issued_quantity": issued,
            "expected_output": expected,
            "actual_output": actual,
            "wastage_quantity": wastage,
            "yield_pct": yld,
            "raw_material_cost": issued * (o.raw_batch.unit_cost if o.raw_batch_id else Decimal("0")),
        })
    return {
        "rows": rows,
        "totals": {
            "total_orders": len(rows),
            "total_issued": sum(r["issued_quantity"] for r in rows),
            "total_output": sum(r["actual_output"] for r in rows),
            "total_wastage": sum(r["wastage_quantity"] for r in rows),
        },
        "reconciliation": {
            "source": "ProductionOrder — all statuses.",
            "formula": "yield_pct = actual_output / issued_quantity × 100.",
        },
    }


# ── FINISHED SKU PRODUCTION REPORT ───────────────────────────────────────────

def finished_sku_production_report(date_from=None, date_to=None) -> dict:
    """
    Packing orders producing finished SKUs — units completed, wastage, and cost.
    Spec 3.50 / 3.33 Packing Order.
    Source: PackingOrder.
    """
    from .models import PackingOrder
    qs = PackingOrder.objects.select_related(
        "bom__finished_product", "bom__powder_product", "powder_batch", "warehouse", "finished_batch"
    )
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    rows = []
    for o in qs.order_by("-created_at"):
        fin_cost = o.finished_batch.unit_cost if o.finished_batch_id else Decimal("0")
        rows.append({
            "order_number": o.number,
            "date": o.created_at.date(),
            "status": o.status,
            "finished_sku": o.bom.finished_product.code if o.bom_id else "",
            "finished_sku_name": o.bom.finished_product.name if o.bom_id else "",
            "powder_product": o.bom.powder_product.code if o.bom_id else "",
            "powder_batch": o.powder_batch.batch_number if o.powder_batch_id else "",
            "warehouse": o.warehouse.code if o.warehouse_id else "",
            "planned_units": o.planned_units,
            "completed_units": o.completed_units,
            "wastage_units": o.wastage_quantity,
            "rejected_units": o.rejected_units,
            "finished_batch": o.finished_batch.batch_number if o.finished_batch_id else "",
            "unit_cost": fin_cost,
            "total_value": o.completed_units * fin_cost,
        })
    return {
        "rows": rows,
        "totals": {
            "total_orders": len(rows),
            "total_completed_units": sum(r["completed_units"] for r in rows),
            "total_wastage_units": sum(r["wastage_units"] for r in rows),
            "total_value": sum(r["total_value"] for r in rows),
        },
        "reconciliation": {
            "source": "PackingOrder all statuses.",
            "formula": "total_value = completed_units × finished_batch.unit_cost.",
        },
    }


# ── BATCH COST REPORT ─────────────────────────────────────────────────────────

def batch_cost_report(batch_type=None, warehouse=None) -> dict:
    """
    Per-batch cost breakdown across all stock types.
    Spec 3.46 Costing and Valuation / 3.50 Reports.
    Source: StockBatch with quantity_on_hand > 0.
    """
    qs = StockBatch.objects.filter(quantity_on_hand__gt=0).select_related(
        "product", "warehouse", "supplier", "parent_batch"
    )
    if batch_type:
        qs = qs.filter(batch_type=batch_type)
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    rows = []
    for b in qs.order_by("product__code", "batch_type"):
        rows.append({
            "batch_number": b.batch_number,
            "batch_type": b.batch_type,
            "product_code": b.product.code,
            "product_name": b.product.name,
            "warehouse": b.warehouse.code,
            "stock_state": b.stock_state,
            "quantity_on_hand": b.quantity_on_hand,
            "unit_cost": b.unit_cost,
            "inventory_value": (b.quantity_on_hand * b.unit_cost).quantize(Decimal("0.01")),
            "supplier": b.supplier.code if b.supplier_id else "",
            "source_document": b.source_document_number,
            "expiry_date": b.expiry_date,
            "parent_batch": b.parent_batch.batch_number if b.parent_batch_id else "",
            "is_blocked": b.is_blocked,
        })
    total_value = sum(r["inventory_value"] for r in rows)
    return {
        "rows": rows,
        "totals": {"total_batches": len(rows), "total_inventory_value": total_value},
        "reconciliation": {
            "source": "StockBatch where quantity_on_hand > 0.",
            "formula": "inventory_value = quantity_on_hand × unit_cost per batch.",
        },
    }


# ── COST VARIANCE REPORT ──────────────────────────────────────────────────────

def cost_variance_report() -> dict:
    """
    Variance between expected yield cost and actual batch cost.
    Spec 3.46 / 3.29: Variance between expected and actual grinding yield impact on cost.
    Source: ProductionOrder where actual_output_quantity is set.
    """
    rows = []
    orders = ProductionOrder.objects.filter(
        status__in=["powder_received", "closed"],
        actual_output_quantity__gt=0
    ).select_related("raw_batch__product", "raw_batch__supplier", "powder_product")

    for o in orders.order_by("-created_at"):
        issued = o.issued_quantity or Decimal("0")
        actual = o.actual_output_quantity or Decimal("0")
        expected = o.expected_output_quantity or Decimal("0")
        raw_cost = issued * (o.raw_batch.unit_cost if o.raw_batch_id else Decimal("0"))
        expected_yield_pct = (
            o.raw_batch.product.expected_grinding_yield_pct
            if o.raw_batch_id and o.raw_batch.product.expected_grinding_yield_pct
            else None
        )
        expected_output_from_pct = (
            (issued * expected_yield_pct / 100).quantize(Decimal("0.001"))
            if expected_yield_pct else expected
        )
        actual_unit_cost = (raw_cost / actual).quantize(Decimal("0.0001")) if actual else Decimal("0")
        expected_unit_cost = (
            (raw_cost / expected_output_from_pct).quantize(Decimal("0.0001"))
            if expected_output_from_pct else Decimal("0")
        )
        cost_variance = actual_unit_cost - expected_unit_cost
        rows.append({
            "order_number": o.number,
            "date": o.created_at.date(),
            "raw_product": o.raw_batch.product.code if o.raw_batch_id else "",
            "supplier": o.raw_batch.supplier.code if o.raw_batch_id and o.raw_batch.supplier_id else "",
            "issued_quantity": issued,
            "actual_output": actual,
            "expected_output": expected_output_from_pct,
            "output_variance": actual - expected_output_from_pct,
            "expected_yield_pct": expected_yield_pct,
            "actual_yield_pct": (actual / issued * 100).quantize(Decimal("0.001")) if issued else Decimal("0"),
            "expected_unit_cost": expected_unit_cost,
            "actual_unit_cost": actual_unit_cost,
            "cost_variance_per_kg": cost_variance,
            "total_cost_variance": (cost_variance * actual).quantize(Decimal("0.01")),
            "variance_direction": "favourable" if cost_variance < 0 else ("adverse" if cost_variance > 0 else "nil"),
        })
    total_variance = sum(r["total_cost_variance"] for r in rows)
    return {
        "rows": rows,
        "totals": {
            "total_orders": len(rows),
            "total_cost_variance": total_variance,
            "adverse_orders": sum(1 for r in rows if r["variance_direction"] == "adverse"),
            "favourable_orders": sum(1 for r in rows if r["variance_direction"] == "favourable"),
        },
        "reconciliation": {
            "source": "ProductionOrder where status in (powder_received, closed).",
            "formula": "cost_variance_per_kg = actual_unit_cost - expected_unit_cost. "
                       "Positive = adverse (actual > expected), negative = favourable.",
        },
    }
