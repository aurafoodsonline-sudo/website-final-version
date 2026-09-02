from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from .models import (
    CustomerDistributor,
    DailyProductionLog,
    GRNLine,
    PurchaseOrderLine,
    ScheduledTaskLog,
    SupplierInvoiceLine,
    SupplierPriceAgreement,
)


def supplier_active_rate_report(
    *, supplier=None, product=None, item_type=None, status=None, date_from=None, date_to=None
) -> dict:
    queryset = SupplierPriceAgreement.objects.select_related("supplier", "product", "unit")
    if supplier:
        queryset = queryset.filter(supplier=supplier)
    if product:
        queryset = queryset.filter(product=product)
    if item_type:
        queryset = queryset.filter(item_type=item_type)
    if status:
        queryset = queryset.filter(status=status)
    if date_from:
        queryset = queryset.filter(expiry_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(effective_date__lte=date_to)
    rows = [{
        "supplier_code": item.supplier.code,
        "supplier_name": item.supplier.name,
        "item_code": item.product.code,
        "item_name": item.product.name,
        "item_type": item.item_type,
        "agreement_number": item.agreement_number,
        "agreed_rate": item.agreed_rate,
        "currency": item.currency,
        "unit": item.unit.code,
        "effective_date": item.effective_date,
        "expiry_date": item.expiry_date,
        "status": item.status,
        "rate_type": item.rate_type,
        "tolerance_percentage": item.tolerance_percentage,
    } for item in queryset]
    return {"rows": rows, "totals": {"agreements": len(rows)}}


def supplier_rate_variance_report(
    *, supplier=None, product=None, item_type=None, source_type=None,
    date_from=None, date_to=None, variance_threshold=None
) -> dict:
    sources = (
        ("PO", PurchaseOrderLine.objects.select_related("purchase_order__supplier", "product__base_unit", "rate_agreement"), "purchase_order", "order_date"),
        ("GRN", GRNLine.objects.select_related("grn__supplier", "product__base_unit", "rate_agreement"), "grn", "grn_date"),
        ("INVOICE", SupplierInvoiceLine.objects.select_related("invoice__supplier", "product__base_unit", "rate_agreement"), "invoice", "invoice_date"),
    )
    rows = []
    for source_name, queryset, document_field, date_field in sources:
        if source_type and source_name.lower() != source_type.lower():
            continue
        if supplier:
            queryset = queryset.filter(**{f"{document_field}__supplier": supplier})
        if product:
            queryset = queryset.filter(product=product)
        if item_type:
            queryset = queryset.filter(rate_agreement__item_type=item_type)
        if date_from:
            queryset = queryset.filter(**{f"{document_field}__{date_field}__gte": date_from})
        if date_to:
            queryset = queryset.filter(**{f"{document_field}__{date_field}__lte": date_to})
        queryset = queryset.filter(agreed_rate_snapshot__isnull=False)
        if variance_threshold is not None:
            queryset = queryset.filter(rate_variance_percentage__gte=variance_threshold)
        for line in queryset:
            document = getattr(line, document_field)
            agreement = line.rate_agreement
            variance = line.rate_variance_amount
            rows.append({
                "supplier_code": document.supplier.code,
                "supplier_name": document.supplier.name,
                "item_code": line.product.code,
                "item_name": line.product.name,
                "item_type": agreement.item_type if agreement else line.product.product_type,
                "agreement_number": agreement.agreement_number if agreement else "",
                "agreed_rate": line.agreed_rate_snapshot,
                "actual_rate": line.unit_cost,
                "variance_amount": variance,
                "variance_percentage": line.rate_variance_percentage,
                "unit": line.product.base_unit.code,
                "effective_date": agreement.effective_date if agreement else None,
                "expiry_date": agreement.expiry_date if agreement else None,
                "status": agreement.status if agreement else "",
                "purchase_reference": document.number,
                "transaction_date": getattr(document, date_field),
                "source_type": source_name,
                "override_reason": line.rate_override_reason,
                "variance_flag": "unfavorable" if variance > 0 else "favorable" if variance < 0 else "neutral",
            })
    return {
        "rows": rows,
        "totals": {
            "comparisons": len(rows),
            "variance_amount": sum((row["variance_amount"] for row in rows), Decimal("0")),
            "unfavorable_count": sum(1 for row in rows if row["variance_flag"] == "unfavorable"),
        },
    }


def _production_log_totals(rows: list[dict]) -> dict:
    return {
        "logs": len(rows),
        "raw_quantity_issued": sum((row["raw_quantity_issued"] for row in rows), Decimal("0")),
        "powder_quantity_received": sum((row["powder_quantity_received"] for row in rows), Decimal("0")),
        "finished_quantity_packed": sum((row["finished_quantity_packed"] for row in rows), Decimal("0")),
        "grinding_wastage": sum((row["grinding_wastage"] for row in rows), Decimal("0")),
        "packing_wastage": sum((row["packing_wastage"] for row in rows), Decimal("0")),
        "downtime_minutes": sum(row["downtime_minutes"] for row in rows),
    }


def daily_production_log_report(
    *, date_from=None, date_to=None, shift=None, operator=None, machine=None,
    product=None, production_order=None, packing_order=None
) -> dict:
    queryset = DailyProductionLog.objects.select_related(
        "supervisor", "production_order", "packing_order", "raw_material_batch__product",
        "powder_batch__product", "finished_goods_batch__product",
    )
    if date_from:
        queryset = queryset.filter(log_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(log_date__lte=date_to)
    if shift:
        queryset = queryset.filter(shift=shift)
    if operator:
        queryset = queryset.filter(operator__icontains=operator)
    if machine:
        queryset = queryset.filter(machine__icontains=machine)
    if product:
        queryset = queryset.filter(
            Q(raw_material_batch__product=product)
            | Q(powder_batch__product=product)
            | Q(finished_goods_batch__product=product)
        )
    if production_order:
        queryset = queryset.filter(production_order=production_order)
    if packing_order:
        queryset = queryset.filter(packing_order=packing_order)
    rows = [{
        "date": item.log_date,
        "shift": item.shift,
        "production_log_number": item.log_number,
        "supervisor": item.supervisor.get_full_name() or item.supervisor.username,
        "operator": item.operator,
        "machine": item.machine,
        "production_order": item.production_order.number if item.production_order else "",
        "packing_order": item.packing_order.number if item.packing_order else "",
        "raw_material": item.raw_material_batch.product.code if item.raw_material_batch else "",
        "raw_batch": item.raw_material_batch.batch_number if item.raw_material_batch else "",
        "raw_quantity_issued": item.raw_quantity_issued,
        "powder_product": item.powder_batch.product.code if item.powder_batch else "",
        "powder_quantity_received": item.powder_quantity_received,
        "finished_sku": item.finished_goods_batch.product.code if item.finished_goods_batch else "",
        "finished_quantity_packed": item.finished_quantity_packed,
        "planned_output": (
            item.production_order.expected_output_quantity if item.production_order
            else item.packing_order.planned_units if item.packing_order else Decimal("0")
        ),
        "actual_output": (
            item.powder_quantity_received if item.production_order
            else item.finished_quantity_packed if item.packing_order else Decimal("0")
        ),
        "output_variance": (
            item.powder_quantity_received - item.production_order.expected_output_quantity
            if item.production_order
            else item.finished_quantity_packed - item.packing_order.planned_units
            if item.packing_order else Decimal("0")
        ),
        "grinding_wastage": item.grinding_wastage_quantity,
        "packing_wastage": item.packing_wastage_quantity,
        "yield_percentage": item.yield_percentage,
        "wastage_percentage": item.wastage_percentage,
        "downtime_minutes": item.downtime_minutes,
        "issue_category": item.issue_category,
        "remarks": item.remarks,
        "status": item.status,
    } for item in queryset]
    return {"rows": rows, "totals": _production_log_totals(rows)}


def production_wastage_summary_report(**filters) -> dict:
    data = daily_production_log_report(**filters)
    rows = [row for row in data["rows"] if row["grinding_wastage"] or row["packing_wastage"]]
    return {"rows": rows, "totals": _production_log_totals(rows)}


def production_packing_summary_report(**filters) -> dict:
    data = daily_production_log_report(**filters)
    rows = [row for row in data["rows"] if row["finished_quantity_packed"]]
    return {"rows": rows, "totals": _production_log_totals(rows)}


def production_issue_summary_report(**filters) -> dict:
    data = daily_production_log_report(**filters)
    rows = [row for row in data["rows"] if row["issue_category"] != DailyProductionLog.IssueCategory.NONE]
    return {"rows": rows, "totals": {"issues": len(rows), "downtime_minutes": sum(row["downtime_minutes"] for row in rows)}}


def customer_master_report(*, customer_type=None, sales_channel=None, city=None, country=None, status=None) -> dict:
    queryset = CustomerDistributor.objects.all()
    for field, value in {
        "customer_type": customer_type,
        "sales_channel": sales_channel,
        "city__iexact": city,
        "country__iexact": country,
        "status": status,
    }.items():
        if value:
            queryset = queryset.filter(**{field: value})
    rows = [{
        "customer_code": item.code,
        "business_name": item.business_name,
        "contact_person": item.contact_person,
        "customer_type": item.customer_type,
        "sales_channel": item.sales_channel,
        "city": item.city,
        "country": item.country,
        "phone": item.phone,
        "credit_limit": item.credit_limit,
        "credit_days": item.credit_days,
        "status": item.status,
        "created_date": item.created_at.date(),
    } for item in queryset]
    return {"rows": rows, "totals": {"customers": len(rows), "blocked": sum(1 for row in rows if row["status"] == "blocked")}}


def scheduled_task_log_report(*, status=None, job_type=None, date_from=None, date_to=None) -> dict:
    queryset = ScheduledTaskLog.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    if job_type:
        queryset = queryset.filter(job_type=job_type)
    if date_from:
        queryset = queryset.filter(started_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(started_at__date__lte=date_to)
    rows = [{
        "job_name": item.job_name,
        "job_type": item.job_type,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "status": item.status,
        "duration_seconds": item.duration.total_seconds() if item.duration else None,
        "message": item.message,
        "error_summary": item.error_details[:240],
        "triggered_by": item.triggered_by,
    } for item in queryset]
    return {"rows": rows, "totals": {"runs": len(rows), "failed": sum(1 for row in rows if row["status"] == "failed")}}
