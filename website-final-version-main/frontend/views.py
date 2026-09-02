from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.shortcuts import render
from django.utils import timezone

from erp.models import (
    AdjustmentDocument,
    CashBankAccount,
    Company,
    CustomerDistributor,
    DailyProductionLog,
    GRN,
    PackagingBOM,
    PackingOrder,
    Product,
    ProductionOrder,
    PurchaseRequirement,
    Recipe,
    ScheduledTaskLog,
    StockBatch,
    Supplier,
    SupplierInvoice,
    SupplierPriceAgreement,
    SupplierLedgerEntry,
    SupplierPayment,
    UnitOfMeasure,
    Warehouse,
)
from erp.permissions import has_erp_permission


@login_required
def operations_console(request):
    user = request.user
    today = timezone.localdate()
    can_view_financial = has_erp_permission(user, "reports.view_financial")
    can_view_inventory = has_erp_permission(user, "reports.view_inventory")
    can_purchase_view = has_erp_permission(user, "purchase.create")
    can_grn_view = can_view_financial or any(
        has_erp_permission(user, permission)
        for permission in ("grn.create", "grn.approve", "quality.inspect")
    )
    can_recipe_view = can_view_financial or any(
        has_erp_permission(user, permission)
        for permission in ("admin.configure", "production.post", "packing.post")
    )
    can_use_payment_workflows = any(
        has_erp_permission(user, permission)
        for permission in (
            "supplier_payment.post", "supplier_payment.reverse",
            "supplier_advance.post", "supplier_advance.adjust",
        )
    )
    # Get near-expiry threshold from Company settings
    near_expiry_threshold_days = 30
    try:
        co = Company.objects.filter(is_active=True).first()
        if co and co.near_expiry_threshold_days:
            near_expiry_threshold_days = co.near_expiry_threshold_days
    except Exception:
        pass
    near_expiry_threshold = today + timezone.timedelta(days=near_expiry_threshold_days)

    # ── Suppliers ────────────────────────────────────────────────────────────
    suppliers = list(
        Supplier.objects.filter(is_active=True)
        .order_by("code")
        .values("id", "code", "name", "payable_balance", "advance_balance")
    )

    # ── Products by type ─────────────────────────────────────────────────────
    all_products = list(
        Product.objects.filter(is_active=True)
        .select_related("base_unit")
        .order_by("code")
        .values("id", "code", "name", "product_type", "grammage", "base_unit__code")
    )
    raw_products = [p for p in all_products if p["product_type"] == "raw"]
    powder_products = [p for p in all_products if p["product_type"] == "powder"]
    finished_products = [p for p in all_products if p["product_type"] == "finished"]
    packaging_products = [p for p in all_products if p["product_type"] == "packaging"]

    # ── Warehouses ───────────────────────────────────────────────────────────
    warehouses = list(Warehouse.objects.filter(is_active=True).order_by("code").values("id", "code", "name"))

    # ── Units ────────────────────────────────────────────────────────────────
    units = list(UnitOfMeasure.objects.filter(is_active=True).order_by("code").values("id", "code", "name"))

    # ── Cash/bank accounts ───────────────────────────────────────────────────
    cash_bank_accounts = list(
        CashBankAccount.objects.filter(is_active=True)
        .order_by("code")
        .values("id", "code", "name", "account_type", "balance")
    ) if can_view_financial or can_use_payment_workflows else []

    # ── Stock batches by type ─────────────────────────────────────────────────
    raw_batches = list(
        StockBatch.objects.filter(batch_type="raw", quantity_on_hand__gt=0, is_blocked=False)
        .select_related("product", "supplier", "warehouse")
        .order_by("expiry_date", "created_at")
        .values("id", "batch_number", "product__code", "product__name",
                "supplier__code", "warehouse__code", "quantity_on_hand", "unit_cost", "expiry_date")
    )
    powder_batches = list(
        StockBatch.objects.filter(batch_type="powder", quantity_on_hand__gt=0, is_blocked=False)
        .select_related("product", "warehouse")
        .order_by("expiry_date", "created_at")
        .values("id", "batch_number", "product__code", "product__name",
                "warehouse__code", "quantity_on_hand", "unit_cost", "expiry_date")
    )
    packaging_batches = list(
        StockBatch.objects.filter(batch_type="packaging", quantity_on_hand__gt=0, is_blocked=False)
        .select_related("product", "warehouse")
        .order_by("product__code", "created_at")
        .values("id", "batch_number", "product__code", "product__name",
                "warehouse__code", "quantity_on_hand", "unit_cost")
    )

    # ── GRNs (pending quality / approval) ────────────────────────────────────
    pending_grns = list(
        GRN.objects.exclude(status="approved")
        .select_related("supplier")
        .order_by("-grn_date")[:20]
        .values("id", "number", "status", "grn_date", "supplier__code", "supplier__name", "payable_amount")
    ) if can_grn_view else []

    # ── Supplier invoices (open) ──────────────────────────────────────────────
    open_invoices = list(
        SupplierInvoice.objects.exclude(status__in=["cancelled", "reversed"])
        .select_related("supplier")
        .order_by("-invoice_date")[:20]
        .values("id", "number", "invoice_date", "due_date", "amount",
                "paid_amount", "advance_adjusted_amount", "supplier__code", "supplier__name", "status")
    ) if can_view_financial or can_use_payment_workflows else []

    # ── Production orders (open) ──────────────────────────────────────────────
    open_production_orders = list(
        ProductionOrder.objects.exclude(status="approved")
        .select_related("raw_batch__product", "powder_product")
        .order_by("-created_at")[:20]
        .values("id", "number", "status", "issued_quantity",
                "expected_output_quantity", "actual_output_quantity",
                "raw_batch__batch_number", "powder_product__code", "powder_product__name")
    )

    # ── Packaging BOMs ────────────────────────────────────────────────────────
    boms = list(
        PackagingBOM.objects.filter(is_active=True)
        .select_related("finished_product", "powder_product")
        .order_by("finished_product__code")
        .values("id", "finished_product__code", "finished_product__name",
                "powder_product__code", "powder_product__name",
                "powder_quantity_per_unit", "version")
    )

    # ── Purchase requirements (open) ──────────────────────────────────────────
    open_requirements = list(
        PurchaseRequirement.objects.exclude(status__in=["cancelled", "posted"])
        .select_related("product")
        .order_by("required_by_date")[:20]
        .values("id", "number", "status", "source", "purpose",
                "required_quantity", "required_by_date",
                "product__code", "product__name")
    ) if can_purchase_view else []

    # ── Recipes (active) ──────────────────────────────────────────────────────
    active_recipes = list(
        Recipe.objects.filter(status="posted")
        .select_related("finished_product", "batch_unit")
        .order_by("code", "-version")
        .values("id", "code", "name", "version", "finished_product__code",
                "effective_date", "is_confidential", "status")
    ) if can_recipe_view else []

    supplier_rate_queryset = SupplierPriceAgreement.objects.select_related("supplier", "product", "unit")
    for field in ("supplier", "product", "item_type", "status"):
        if request.GET.get(f"rate_{field}"):
            supplier_rate_queryset = supplier_rate_queryset.filter(**{field: request.GET[f"rate_{field}"]})
    supplier_rate_agreements = list(supplier_rate_queryset.order_by("-effective_date", "supplier__code")[:100])

    production_log_queryset = DailyProductionLog.objects.select_related("supervisor", "production_order", "packing_order")
    for field in ("shift", "status", "production_order", "packing_order"):
        if request.GET.get(f"production_{field}"):
            production_log_queryset = production_log_queryset.filter(**{field: request.GET[f"production_{field}"]})
    if request.GET.get("production_operator"):
        production_log_queryset = production_log_queryset.filter(operator__icontains=request.GET["production_operator"])
    if request.GET.get("production_date_from"):
        production_log_queryset = production_log_queryset.filter(log_date__gte=request.GET["production_date_from"])
    if request.GET.get("production_date_to"):
        production_log_queryset = production_log_queryset.filter(log_date__lte=request.GET["production_date_to"])
    production_logs = list(production_log_queryset.order_by("-log_date", "shift")[:100])
    recent_packing_orders = list(
        PackingOrder.objects.select_related("bom__finished_product").order_by("-created_at")[:30]
    )
    customer_queryset = CustomerDistributor.objects.all()
    for field in ("customer_type", "sales_channel", "status", "country"):
        if request.GET.get(field):
            customer_queryset = customer_queryset.filter(**{field: request.GET[field]})
    if request.GET.get("city"):
        customer_queryset = customer_queryset.filter(city__iexact=request.GET["city"])
    if request.GET.get("customer_search"):
        term = request.GET["customer_search"]
        customer_queryset = customer_queryset.filter(
            Q(code__icontains=term) | Q(business_name__icontains=term)
            | Q(contact_person__icontains=term) | Q(phone__icontains=term)
        )
    customers = list(customer_queryset.order_by("code")[:100])

    scheduled_log_queryset = ScheduledTaskLog.objects.all()
    if request.GET.get("job_status"):
        scheduled_log_queryset = scheduled_log_queryset.filter(status=request.GET["job_status"])
    if request.GET.get("job_type"):
        scheduled_log_queryset = scheduled_log_queryset.filter(job_type=request.GET["job_type"])
    scheduled_task_logs = list(scheduled_log_queryset.order_by("-started_at")[:100])
    today_production = DailyProductionLog.objects.filter(log_date=today).aggregate(
        raw=Sum("raw_quantity_issued"),
        powder=Sum("powder_quantity_received"),
        packed=Sum("finished_quantity_packed"),
        downtime=Sum("downtime_minutes"),
    )

    # ── Dashboard metrics ─────────────────────────────────────────────────────
    total_payable = Supplier.objects.aggregate(t=Sum("payable_balance"))["t"] or 0 if can_view_financial else 0
    total_advance = Supplier.objects.aggregate(t=Sum("advance_balance"))["t"] or 0 if can_view_financial else 0
    # compute real stock value from aggregation
    stock_value_calc = sum(
        float(b["quantity_on_hand"]) * float(b["unit_cost"])
        for b in StockBatch.objects.filter(is_blocked=False).values("quantity_on_hand", "unit_cost")
    ) if can_view_inventory else 0
    low_stock_count = Product.objects.filter(
        is_active=True, minimum_stock__gt=0
    ).count() if can_view_inventory else 0  # simplified — full low stock needs batch aggregation
    near_expiry_count = StockBatch.objects.filter(
        expiry_date__lte=near_expiry_threshold, expiry_date__gte=today, is_blocked=False, quantity_on_hand__gt=0
    ).count() if can_view_inventory else 0
    expired_count = StockBatch.objects.filter(
        expiry_date__lt=today, quantity_on_hand__gt=0
    ).count() if can_view_inventory else 0

    metrics = {
        "suppliers": len(suppliers),
        "products": len(all_products),
        "open_grns": GRN.objects.exclude(status="approved").count() if can_grn_view else 0,
        "payable": float(total_payable),
        "advance": float(total_advance),
        "stock_value": round(stock_value_calc, 2),
        "adjustments": AdjustmentDocument.objects.count() if can_view_financial else 0,
        "ledger_rows": SupplierLedgerEntry.objects.count() if can_view_financial else 0,
        "near_expiry_count": near_expiry_count,
        "expired_count": expired_count,
        "low_stock_count": low_stock_count,
        "open_requirements": len(open_requirements),
        "active_recipes": len(active_recipes),
        "today_powder_output": float(today_production["powder"] or 0),
        "today_finished_units": float(today_production["packed"] or 0),
        "today_downtime_minutes": int(today_production["downtime"] or 0),
        "near_expiry_threshold_days": near_expiry_threshold_days,
    }

    # ── Recent activity ───────────────────────────────────────────────────────
    recent_invoices = list(
        SupplierInvoice.objects.select_related("supplier").order_by("-created_at")[:8]
    ) if can_view_financial else []
    recent_batches = list(
        StockBatch.objects.select_related("product", "warehouse", "supplier").order_by("-created_at")[:10]
    ) if can_view_inventory else []

    # ── Permission map ────────────────────────────────────────────────────────
    can = {
        "admin_configure": has_erp_permission(user, "admin.configure"),
        "purchase_create": has_erp_permission(user, "purchase.create"),
        "grn_create": has_erp_permission(user, "grn.create"),
        "grn_approve": has_erp_permission(user, "grn.approve"),
        "quality_inspect": has_erp_permission(user, "quality.inspect"),
        "supplier_invoice_post": has_erp_permission(user, "supplier_invoice.post"),
        "supplier_payment_post": has_erp_permission(user, "supplier_payment.post"),
        "supplier_payment_reverse": has_erp_permission(user, "supplier_payment.reverse"),
        "supplier_advance_post": has_erp_permission(user, "supplier_advance.post"),
        "supplier_advance_adjust": has_erp_permission(user, "supplier_advance.adjust"),
        "stock_adjust": has_erp_permission(user, "stock.adjust"),
        "stock_issue": has_erp_permission(user, "stock.issue"),
        "production_post": has_erp_permission(user, "production.post"),
        "packing_post": has_erp_permission(user, "packing.post"),
        "financial_reports": has_erp_permission(user, "reports.view_financial"),
        "inventory_reports": has_erp_permission(user, "reports.view_inventory"),
        "grn_view": can_grn_view,
        "recipe_view": can_recipe_view,
        "view_financial_data": has_erp_permission(user, "reports.view_financial"),
        "view_inventory_data": has_erp_permission(user, "reports.view_inventory"),
        "supplier_rate_view": has_erp_permission(user, "supplier_rate.view"),
        "supplier_rate_create": has_erp_permission(user, "supplier_rate.create"),
        "supplier_rate_approve": has_erp_permission(user, "supplier_rate.approve"),
        "supplier_rate_override": has_erp_permission(user, "supplier_rate.override"),
        "production_log_view": has_erp_permission(user, "production_log.view"),
        "production_log_create": has_erp_permission(user, "production_log.create"),
        "production_log_submit": has_erp_permission(user, "production_log.submit"),
        "production_log_approve": has_erp_permission(user, "production_log.approve"),
        "customer_view": has_erp_permission(user, "customer.view"),
        "customer_create": has_erp_permission(user, "customer.create"),
        "customer_edit": has_erp_permission(user, "customer.edit"),
        "customer_block": has_erp_permission(user, "customer.block"),
        "scheduled_task_view": has_erp_permission(user, "scheduled_task.view"),
        "scheduled_task_run": has_erp_permission(user, "scheduled_task.run"),
        "scheduled_task_configure": has_erp_permission(user, "scheduled_task.configure"),
        "supplier_rate_reports": has_erp_permission(user, "report.supplier_rate"),
        "production_log_reports": has_erp_permission(user, "report.production_log"),
        "customer_reports": has_erp_permission(user, "report.customer_master"),
        "scheduled_task_reports": has_erp_permission(user, "report.scheduled_task"),
    }

    context = {
        "metrics": metrics,
        "recent_invoices": recent_invoices,
        "recent_batches": recent_batches,
        "suppliers": suppliers,
        "all_products": all_products,
        "raw_products": raw_products,
        "powder_products": powder_products,
        "finished_products": finished_products,
        "packaging_products": packaging_products,
        "warehouses": warehouses,
        "units": units,
        "cash_bank_accounts": cash_bank_accounts,
        "raw_batches": raw_batches,
        "powder_batches": powder_batches,
        "packaging_batches": packaging_batches,
        "pending_grns": pending_grns,
        "open_invoices": open_invoices,
        "open_production_orders": open_production_orders,
        "boms": boms,
        "open_requirements": open_requirements,
        "active_recipes": active_recipes,
        "supplier_rate_agreements": supplier_rate_agreements,
        "production_logs": production_logs,
        "recent_packing_orders": recent_packing_orders,
        "customers": customers,
        "scheduled_task_logs": scheduled_task_logs,
        "can": can,
    }
    return render(request, "frontend/app.html", context)
