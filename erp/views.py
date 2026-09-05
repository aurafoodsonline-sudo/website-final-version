from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import HttpResponse
from django.templatetags.static import static
from django.utils.html import escape
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .export import rows_to_csv
from .models import (
    AdjustmentDocument,
    CashBankAccount,
    CustomerDistributor,
    CustomerShippingAddress,
    DailyProductionLog,
    GRN,
    PackingOrder,
    PackagingBOM,
    Product,
    ProductionOrder,
    PurchaseOrder,
    ScheduledTaskConfig,
    ScheduledTaskLog,
    StockBatch,
    Supplier,
    SupplierInvoice,
    SupplierPriceAgreement,
    SupplierPayment,
    UnitOfMeasure,
    Warehouse,
)
from .domain_reports import (
    customer_master_report,
    daily_production_log_report,
    production_packing_summary_report,
    production_issue_summary_report,
    production_wastage_summary_report,
    scheduled_task_log_report,
    supplier_active_rate_report,
    supplier_rate_variance_report,
)
from .reports import (
    adjustment_report,
    batch_traceability_report,
    costing_report,
    expiry_report,
    expired_stock_report,
    finished_goods_stock_report,
    fefo_dispatch_report,
    grn_report,
    low_stock_report,
    near_expiry_report,
    opening_balance_report,
    packaging_consumption_report,
    packaging_stock_report,
    packing_report,
    payment_reversal_report,
    powder_stock_report,
    purchase_report,
    quality_rejection_report,
    raw_material_stock_report,
    supplier_balance_summary_report,
    supplier_ledger_report,
    supplier_payable_aging_report,
    approval_pending_report,
    batch_cost_report,
    cost_variance_report,
    damaged_stock_report,
    finished_sku_production_report,
    grinding_report,
    repacking_report,
    supplier_advance_report,
    supplier_rejection_report,
    supplier_shortage_report,
    supplier_return_report,
    supplier_yield_report,
    user_activity_report,
    wastage_report,
    yield_report,
)
from .serializers import (
    AdjustmentDocumentSerializer,
    CashBankAccountSerializer,
    CustomerDistributorSerializer,
    CustomerShippingAddressSerializer,
    DailyProductionLogSerializer,
    GRNSerializer,
    PackagingBOMSerializer,
    PhysicalStockCountSerializer,
    ProductSerializer,
    PurchaseOrderSerializer,
    ScheduledTaskConfigSerializer,
    ScheduledTaskLogSerializer,
    StockBatchSerializer,
    SupplierInvoiceSerializer,
    SupplierPriceAgreementSerializer,
    SupplierPaymentSerializer,
    SupplierDirectorySerializer,
    SupplierSerializer,
    UnitOfMeasureSerializer,
    WarehouseSerializer,
)
from .domain_services import (
    activate_supplier_price_agreement,
    approve_daily_production_log,
    approve_supplier_price_agreement,
    cancel_supplier_price_agreement,
    create_customer_distributor,
    create_daily_production_log,
    create_supplier_price_agreement,
    set_customer_blocked,
    set_customer_status,
    submit_daily_production_log,
    submit_supplier_price_agreement,
)
from .permissions import (
    FinancialReadPermission,
    InventoryReadPermission,
    IsAuthenticatedAndCanPost,
    has_erp_permission,
    report_permission_for,
)
from .services import (
    PurchaseLineInput,
    adjust_supplier_advance,
    approve_grn,
    approve_purchase_order,
    cancel_grn,
    cancel_purchase_order,
    complete_packing_order,
    create_grn,
    submit_purchase_order,
    create_purchase_order,
    issue_raw_material_to_grinding,
    post_credit_note,
    post_debit_note,
    post_cash_bank_opening,
    post_physical_stock_count,
    post_relabeling,
    post_repacking,
    post_rework,
    post_stock_adjustment,
    post_quality_inspection,
    post_supplier_advance,
    post_supplier_payment,
    post_supplier_opening_advance,
    post_supplier_opening_payable,
    post_supplier_return,
    receive_powder_output,
    reverse_supplier_payment,
)


def _truthy(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _get_or_404(model, **kwargs):
    """Safe get-or-404 wrapper — prevents unhandled ObjectDoesNotExist 500s."""
    try:
        return model.objects.get(**kwargs)
    except ObjectDoesNotExist:
        from rest_framework.exceptions import NotFound
        raise NotFound(f"{model.__name__} not found.")


def _apply_row_window(request, data: dict, rows: list[dict]) -> list[dict]:
    offset = max(int(request.GET.get("offset", "0")), 0)
    limit = min(max(int(request.GET.get("limit", "250")), 1), 1000)
    data["pagination"] = {
        "offset": offset,
        "limit": limit,
        "total_rows": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
    }
    if request.GET.get("export") == "csv":
        return rows
    return rows[offset : offset + limit]


class DefaultModelViewSet(viewsets.ModelViewSet):
    """
    Master data viewset. Read access: any authenticated user (master data is not sensitive).
    Write/delete: requires admin.configure permission.
    """
    permission_classes = [IsAuthenticatedAndCanPost]
    required_action_permissions = {
        "create": "admin.configure",
        "update": "admin.configure",
        "partial_update": "admin.configure",
        "destroy": "admin.configure",
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class UnitOfMeasureViewSet(DefaultModelViewSet):
    queryset = UnitOfMeasure.objects.all()
    serializer_class = UnitOfMeasureSerializer


class WarehouseViewSet(DefaultModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer


class ProductViewSet(DefaultModelViewSet):
    queryset = Product.objects.select_related("base_unit").all()
    serializer_class = ProductSerializer


class SupplierViewSet(DefaultModelViewSet):
    """
    Supplier master: read open to authenticated users (non-sensitive master data).
    Financial actions (opening payable/advance) require explicit finance permissions.
    """
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    required_action_permissions = {
        **DefaultModelViewSet.required_action_permissions,
        "post_opening_payable": "supplier_invoice.post",
        "post_opening_advance": "supplier_advance.post",
    }

    def get_serializer_class(self):
        if has_erp_permission(self.request.user, "reports.view_financial") or has_erp_permission(
            self.request.user, "admin.configure"
        ):
            return SupplierSerializer
        return SupplierDirectorySerializer

    @action(detail=True, methods=["post"])
    def post_opening_payable(self, request, pk=None):
        supplier = _get_or_404(Supplier, pk=pk)
        opening = post_supplier_opening_payable(
            supplier=supplier,
            amount=Decimal(str(request.data["amount"])),
            user=request.user,
        )
        return Response({"opening_balance": opening.number}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def post_opening_advance(self, request, pk=None):
        supplier = _get_or_404(Supplier, pk=pk)
        opening = post_supplier_opening_advance(
            supplier=supplier,
            amount=Decimal(str(request.data["amount"])),
            user=request.user,
        )
        return Response({"opening_balance": opening.number}, status=status.HTTP_201_CREATED)


class CashBankAccountViewSet(DefaultModelViewSet):
    queryset = CashBankAccount.objects.all()
    serializer_class = CashBankAccountSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {
        **DefaultModelViewSet.required_action_permissions,
        "post_opening": "supplier_payment.post",
    }

    @action(detail=True, methods=["post"])
    def post_opening(self, request, pk=None):
        account = _get_or_404(CashBankAccount, pk=pk)
        amount = Decimal(str(request.data["amount"]))
        opening = post_cash_bank_opening(account=account, amount=amount, user=request.user)
        return Response({"opening_balance": opening.number, "account_balance": str(account.balance)})


class GRNViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    GRN: read requires financial permission (purchase documents are financial data).
    """
    queryset = GRN.objects.all().select_related("supplier")
    serializer_class = GRNSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {
        "direct_purchase": "grn.create",
        "inspect_quality": "quality.inspect",
        "approve": "grn.approve",
        "cancel": "admin.configure",
    }

    @action(detail=False, methods=["post"])
    def direct_purchase(self, request):
        supplier = _get_or_404(Supplier, pk=request.data["supplier"])
        warehouse = _get_or_404(Warehouse, pk=request.data["warehouse"])
        lines = []
        for item in request.data["lines"]:
            lines.append(
                PurchaseLineInput(
                    product=_get_or_404(Product, pk=item["product"]),
                    ordered_quantity=Decimal(str(item["ordered_quantity"])),
                    received_quantity=Decimal(str(item["received_quantity"])),
                    accepted_quantity=Decimal(str(item["accepted_quantity"])),
                    rejected_quantity=Decimal(str(item.get("rejected_quantity", "0"))),
                    unit_cost=Decimal(str(item["unit_cost"])),
                    batch_number=item["batch_number"],
                    expiry_date=item.get("expiry_date") or None,
                    rate_override_reason=item.get("rate_override_reason", ""),
                )
            )
        if any(line.rate_override_reason for line in lines) and not has_erp_permission(request.user, "supplier_rate.override"):
            return Response({"detail": "supplier_rate.override permission is required."}, status=403)
        grn = create_grn(supplier=supplier, warehouse=warehouse, lines=lines, user=request.user)
        return Response(GRNSerializer(grn).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def inspect_quality(self, request, pk=None):
        grn = _get_or_404(GRN, pk=pk)
        inspection = post_quality_inspection(
            grn=grn,
            deduction_amount=Decimal(str(request.data.get("deduction_amount", "0"))),
            user=request.user,
        )
        return Response({"inspection": inspection.pk, "grn": inspection.grn.number})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        grn = _get_or_404(GRN, pk=pk)
        warehouse = _get_or_404(Warehouse, pk=request.data["warehouse"])
        grn = approve_grn(
            grn=grn,
            warehouse=warehouse,
            create_invoice=_truthy(request.data.get("create_invoice"), default=True),
            user=request.user,
        )
        return Response(GRNSerializer(grn).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a draft/pending GRN. Spec 10.2."""
        grn = _get_or_404(GRN, pk=pk)
        reason = request.data.get("reason", "").strip()
        if not reason:
            return Response({"detail": "Cancellation reason is required."}, status=400)
        if not has_erp_permission(request.user, "admin.configure"):
            return Response({"detail": "GRN cancellation requires admin.configure permission."}, status=403)
        grn = cancel_grn(grn=grn, reason=reason, user=request.user)
        return Response(GRNSerializer(grn).data)


class PurchaseOrderViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Purchase orders: read requires financial permission."""
    queryset = PurchaseOrder.objects.all().select_related("supplier").prefetch_related("lines")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {
        "create_with_lines": "purchase.create",
        "submit": "purchase.create",
        "approve": "purchase.approve",
        "cancel": "admin.configure",
    }

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """Draft → Pending Approval. Spec 10.1."""
        order = _get_or_404(PurchaseOrder, pk=pk)
        if not has_erp_permission(request.user, "purchase.create"):
            return Response({"detail": "purchase.create required."}, status=403)
        return Response(PurchaseOrderSerializer(submit_purchase_order(order=order, user=request.user)).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Pending Approval → Approved. Spec 10.1."""
        order = _get_or_404(PurchaseOrder, pk=pk)
        if not has_erp_permission(request.user, "purchase.approve"):
            return Response({"detail": "purchase.approve required."}, status=403)
        return Response(PurchaseOrderSerializer(approve_purchase_order(order=order, user=request.user)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel PO. Spec 10.1."""
        order = _get_or_404(PurchaseOrder, pk=pk)
        if not has_erp_permission(request.user, "admin.configure"):
            return Response({"detail": "admin.configure required."}, status=403)
        return Response(PurchaseOrderSerializer(
            cancel_purchase_order(order=order, reason=request.data.get("reason",""), user=request.user)
        ).data)

    @action(detail=False, methods=["post"], url_path="create-with-lines")
    def create_with_lines(self, request):
        supplier = _get_or_404(Supplier, pk=request.data["supplier"])
        lines = []
        for item in request.data["lines"]:
            lines.append(
                PurchaseLineInput(
                    product=_get_or_404(Product, pk=item["product"]),
                    ordered_quantity=Decimal(str(item["quantity"])),
                    received_quantity=Decimal("0.000"),
                    accepted_quantity=Decimal("0.000"),
                    unit_cost=Decimal(str(item["unit_cost"])),
                    batch_number="",
                    rate_override_reason=item.get("rate_override_reason", ""),
                )
            )
        if any(line.rate_override_reason for line in lines) and not has_erp_permission(request.user, "supplier_rate.override"):
            return Response({"detail": "supplier_rate.override permission is required."}, status=403)
        order = create_purchase_order(supplier=supplier, lines=lines, user=request.user)
        return Response(PurchaseOrderSerializer(order).data, status=status.HTTP_201_CREATED)


class SupplierInvoiceViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Supplier invoices: FINANCIAL data — read requires reports.view_financial permission.
    Previously used broad IsAuthenticated — now fixed.
    """
    queryset = SupplierInvoice.objects.all().select_related("supplier")
    serializer_class = SupplierInvoiceSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]


class SupplierPaymentViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Supplier payments: FINANCIAL data — read requires reports.view_financial permission.
    Printable receipt also requires financial read permission.
    """
    queryset = SupplierPayment.objects.all().select_related("supplier")
    serializer_class = SupplierPaymentSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {
        "advance": "supplier_advance.post",
        "pay_invoice": "supplier_payment.post",
        "adjust_advance": "supplier_advance.adjust",
        "reverse": "supplier_payment.reverse",
    }

    @action(detail=False, methods=["post"])
    def advance(self, request):
        payment = post_supplier_advance(
            supplier=_get_or_404(Supplier, pk=request.data["supplier"]),
            cash_bank_account=_get_or_404(CashBankAccount, pk=request.data["cash_bank_account"]),
            amount=Decimal(str(request.data["amount"])),
            user=request.user,
        )
        return Response(SupplierPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def pay_invoice(self, request):
        payment = post_supplier_payment(
            supplier=_get_or_404(Supplier, pk=request.data["supplier"]),
            cash_bank_account=_get_or_404(CashBankAccount, pk=request.data["cash_bank_account"]),
            invoice=_get_or_404(SupplierInvoice, pk=request.data["invoice"]),
            amount=Decimal(str(request.data["amount"])),
            user=request.user,
        )
        return Response(SupplierPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def adjust_advance(self, request):
        payment = adjust_supplier_advance(
            supplier=_get_or_404(Supplier, pk=request.data["supplier"]),
            invoice=_get_or_404(SupplierInvoice, pk=request.data["invoice"]),
            amount=Decimal(str(request.data["amount"])),
            user=request.user,
        )
        return Response(SupplierPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = _get_or_404(SupplierPayment, pk=pk)
        reversal = reverse_supplier_payment(
            payment=payment,
            reason=request.data.get("reason", "Supplier payment reversal"),
            user=request.user,
        )
        return Response(SupplierPaymentSerializer(reversal).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="printable-receipt")
    def printable_receipt(self, request, pk=None):
        """Printable receipt — requires financial read permission (already enforced by FinancialReadPermission)."""
        payment = _get_or_404(SupplierPayment, pk=pk)
        # Spec 3.20: receipt must show all voucher fields including amount_in_words, approved_by, payment_method
        company_name = "AuraFoods"
        try:
            from .models import Company
            co = Company.objects.filter(is_active=True).first()
            if co:
                company_name = co.name
                footer = co.receipt_footer_text
            else:
                footer = "Thank you for your business."
        except Exception:
            footer = "Thank you for your business."

        approved_name = payment.approved_by.get_full_name() or payment.approved_by.username if payment.approved_by_id else "—"
        prepared_name = payment.prepared_by.get_full_name() or payment.prepared_by.username if payment.prepared_by_id else (payment.created_by.username if payment.created_by_id else "—")
        acct_name = payment.cash_bank_account.name if payment.cash_bank_account_id else "—"
        acct_method = payment.payment_method or "—"
        ref_no = payment.reference_number or payment.cheque_number or payment.bank_reference or payment.transaction_id or "—"

        def safe(value):
            return escape(str(value if value not in (None, "") else "—"))

        optional_rows = "".join(
            f"<tr><td>{safe(label)}</td><td>{safe(value)}</td></tr>"
            for label, value in (
                ("Cheque No.", payment.cheque_number),
                ("Bank Reference", payment.bank_reference),
                ("Transaction ID", payment.transaction_id),
                ("Remarks", payment.reason),
            )
            if value
        )
        receipt_script_url = safe(static("frontend/receipt.js"))

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Payment Voucher — {safe(payment.number)}</title>
<style>
  body {{font-family: "Segoe UI", Arial, sans-serif; max-width: 640px; margin: 40px auto; color: #1e293b; font-size: 14px;}}
  .header {{text-align: center; border-bottom: 2px solid #b45309; padding-bottom: 14px; margin-bottom: 20px;}}
  .header h1 {{margin: 0 0 4px; font-size: 18px; color: #b45309;}}
  .header p {{margin: 2px 0; font-size: 12px; color: #64748b;}}
  table {{width: 100%; border-collapse: collapse; margin-bottom: 18px;}}
  td {{padding: 7px 10px; border-bottom: 1px solid #e2e8f0; vertical-align: top;}}
  td:first-child {{font-weight: 600; width: 42%; color: #475569; white-space: nowrap;}}
  .amount-words {{background: #fef3c7; padding: 10px 12px; border-radius: 6px; font-style: italic; margin-bottom: 18px; border: 1px solid #fcd34d;}}
  .sig-row {{display: flex; justify-content: space-between; margin-top: 40px;}}
  .sig-box {{text-align: center; width: 28%;}}
  .sig-line {{border-top: 1px solid #94a3b8; padding-top: 6px; font-size: 12px; color: #64748b;}}
  .footer {{margin-top: 24px; font-size: 11px; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 10px;}}
  .print-btn {{display: block; margin: 24px auto; padding: 10px 28px; background: #b45309; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px;}}
  @media print {{.print-btn {{display: none;}} body {{margin: 0;}}}}
</style>
</head>
<body>
<div class="header">
  <h1>{safe(company_name)}</h1>
  <p><strong>Supplier Payment Voucher</strong></p>
  <p>This is a system-generated voucher. Verify before signing.</p>
</div>

<table>
  <tr><td>Voucher No.</td><td><strong>{safe(payment.number)}</strong></td></tr>
  <tr><td>Date</td><td>{safe(payment.payment_date)}</td></tr>
  <tr><td>Supplier</td><td>{safe(payment.supplier.code)} — {safe(payment.supplier.name)}</td></tr>
  <tr><td>Payment Type</td><td>{safe(payment.get_payment_type_display())}</td></tr>
  <tr><td>Payment Method</td><td>{safe(acct_method)}</td></tr>
  <tr><td>Cash / Bank Account</td><td>{safe(acct_name)}</td></tr>
  <tr><td>Reference No.</td><td>{safe(ref_no)}</td></tr>
  {optional_rows}
  <tr><td>Amount (PKR)</td><td><strong style="font-size:16px">{safe(payment.amount)}</strong></td></tr>
  <tr><td>Status</td><td>{safe(payment.status.upper())}</td></tr>
  <tr><td>Prepared By</td><td>{safe(prepared_name)}</td></tr>
  <tr><td>Approved By</td><td>{safe(approved_name)}</td></tr>
</table>

<div class="amount-words">
  <strong>Amount in Words:</strong> {safe(payment.amount_in_words)}
</div>

<div class="sig-row">
  <div class="sig-box"><div class="sig-line">Prepared By</div></div>
  <div class="sig-box"><div class="sig-line">Approved By</div></div>
  <div class="sig-box"><div class="sig-line">Supplier Signature</div></div>
</div>

<div class="footer">{safe(footer)}</div>

<button class="print-btn" id="print-voucher" type="button">Print Voucher</button>
<script src="{receipt_script_url}" defer></script>
</body>
</html>"""
        return HttpResponse(html, content_type="text/html")


class StockBatchViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Stock batches: INVENTORY data — read requires reports.view_inventory permission.
    Previously allowed any authenticated user to read — now fixed.
    """
    queryset = StockBatch.objects.all().select_related("product", "warehouse", "supplier", "parent_batch")
    serializer_class = StockBatchSerializer
    permission_classes = [IsAuthenticatedAndCanPost, InventoryReadPermission]
    required_action_permissions = {
        "issue_to_grinding": "stock.issue",
        "stock_adjustment": "stock.adjust",
        "physical_count": "stock.adjust",
        "supplier_return": "stock.adjust",
        "repack": "packing.post",
        "relabel": "packing.post",
        "rework": "packing.post",
    }

    @action(detail=True, methods=["post"])
    def issue_to_grinding(self, request, pk=None):
        raw_batch = _get_or_404(StockBatch, pk=pk)
        order = issue_raw_material_to_grinding(
            raw_batch=raw_batch,
            powder_product=_get_or_404(Product, pk=request.data["powder_product"]),
            issued_quantity=Decimal(str(request.data["issued_quantity"])),
            expected_output_quantity=Decimal(str(request.data["expected_output_quantity"])),
            user=request.user,
        )
        return Response({"production_order": order.number})

    @action(detail=True, methods=["post"])
    def stock_adjustment(self, request, pk=None):
        batch = _get_or_404(StockBatch, pk=pk)
        doc = post_stock_adjustment(
            batch=batch,
            counted_quantity=Decimal(str(request.data["counted_quantity"])),
            reason=request.data.get("reason", "Stock adjustment"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def physical_count(self, request, pk=None):
        batch = _get_or_404(StockBatch, pk=pk)
        doc = post_physical_stock_count(
            batch=batch,
            counted_quantity=Decimal(str(request.data["counted_quantity"])),
            reason=request.data.get("reason", "Physical stock count"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def supplier_return(self, request, pk=None):
        batch = _get_or_404(StockBatch, pk=pk)
        invoice = _get_or_404(SupplierInvoice, pk=request.data["invoice"]) if request.data.get("invoice") else None
        doc = post_supplier_return(
            batch=batch,
            quantity=Decimal(str(request.data["quantity"])),
            amount=Decimal(str(request.data.get("amount", "0"))),
            reason=request.data.get("reason", "Supplier return"),
            invoice=invoice,
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def repack(self, request, pk=None):
        source_batch = _get_or_404(StockBatch, pk=pk)
        doc = post_repacking(
            source_batch=source_batch,
            quantity=Decimal(str(request.data["quantity"])),
            finished_product=_get_or_404(Product, pk=request.data["finished_product"]),
            new_batch_number=request.data["new_batch_number"],
            loss_quantity=Decimal(str(request.data.get("loss_quantity", "0"))),
            reason=request.data.get("reason", "Repacking"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def relabel(self, request, pk=None):
        batch = _get_or_404(StockBatch, pk=pk)
        doc = post_relabeling(
            batch=batch,
            new_label_version=request.data["new_label_version"],
            reason=request.data.get("reason", "Relabeling"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def rework(self, request, pk=None):
        source_batch = _get_or_404(StockBatch, pk=pk)
        doc = post_rework(
            source_batch=source_batch,
            input_quantity=Decimal(str(request.data["input_quantity"])),
            output_product=_get_or_404(Product, pk=request.data["output_product"]),
            output_batch_number=request.data["output_batch_number"],
            output_quantity=Decimal(str(request.data["output_quantity"])),
            reason=request.data.get("reason", "Rework"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class PackagingBOMViewSet(DefaultModelViewSet):
    queryset = PackagingBOM.objects.all().select_related("finished_product", "powder_product").prefetch_related("lines")
    serializer_class = PackagingBOMSerializer
    required_action_permissions = {
        **DefaultModelViewSet.required_action_permissions,
        "complete_packing": "packing.post",
    }

    @action(detail=True, methods=["post"])
    def complete_packing(self, request, pk=None):
        bom = _get_or_404(PackagingBOM, pk=pk)
        packaging_batches = {
            int(item["product"]): _get_or_404(StockBatch, pk=item["batch"])
            for item in request.data.get("packaging_batches", [])
        }
        order = complete_packing_order(
            bom=bom,
            powder_batch=_get_or_404(StockBatch, pk=request.data["powder_batch"]),
            completed_units=Decimal(str(request.data["completed_units"])),
            wastage_units=Decimal(str(request.data.get("wastage_units", "0"))),
            finished_batch_number=request.data["finished_batch_number"],
            packaging_batches=packaging_batches,
            user=request.user,
        )
        return Response({"packing_order": order.number, "finished_batch": order.finished_batch.batch_number})


class AdjustmentDocumentViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Adjustment documents contain both financial and inventory data.
    Read access restricted by financial permission (covers debit/credit notes which are financial).
    """
    queryset = AdjustmentDocument.objects.all().select_related("supplier", "product", "batch")
    serializer_class = AdjustmentDocumentSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {
        "debit_note": "supplier_invoice.post",
        "credit_note": "supplier_invoice.post",
    }

    @action(detail=False, methods=["post"], url_path="debit-note")
    def debit_note(self, request):
        invoice = _get_or_404(SupplierInvoice, pk=request.data["invoice"]) if request.data.get("invoice") else None
        doc = post_debit_note(
            supplier=_get_or_404(Supplier, pk=request.data["supplier"]),
            invoice=invoice,
            amount=Decimal(str(request.data["amount"])),
            reason=request.data.get("reason", "Debit note"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="credit-note")
    def credit_note(self, request):
        invoice = _get_or_404(SupplierInvoice, pk=request.data["invoice"]) if request.data.get("invoice") else None
        doc = post_credit_note(
            supplier=_get_or_404(Supplier, pk=request.data["supplier"]),
            invoice=invoice,
            amount=Decimal(str(request.data["amount"])),
            balance_effect=request.data["balance_effect"],
            reason=request.data.get("reason", "Credit note"),
            user=request.user,
        )
        return Response(AdjustmentDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class SupplierPriceAgreementViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierPriceAgreementSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "supplier_rate.view"
    required_action_permissions = {
        "create": "supplier_rate.create",
        "update": "supplier_rate.create",
        "partial_update": "supplier_rate.create",
        "destroy": "admin.configure",
        "submit": "supplier_rate.create",
        "approve": "supplier_rate.approve",
        "activate": "supplier_rate.approve",
        "cancel": "supplier_rate.approve",
    }

    def get_queryset(self):
        queryset = SupplierPriceAgreement.objects.select_related("supplier", "product", "unit", "approved_by")
        for field in ("supplier", "product", "item_type", "status"):
            if self.request.GET.get(field):
                queryset = queryset.filter(**{field: self.request.GET[field]})
        if self.request.GET.get("active_only") == "1":
            queryset = queryset.filter(status=SupplierPriceAgreement.Status.ACTIVE)
        return queryset

    def perform_create(self, serializer):
        from .services import next_document_number
        serializer.instance = create_supplier_price_agreement(
            agreement_number=next_document_number("RATE"), user=self.request.user,
            **serializer.validated_data,
        )

    def perform_update(self, serializer):
        if serializer.instance.status != SupplierPriceAgreement.Status.DRAFT:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Only draft rate agreements can be edited.")
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        agreement = submit_supplier_price_agreement(agreement=self.get_object(), user=request.user)
        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        agreement = approve_supplier_price_agreement(agreement=self.get_object(), user=request.user)
        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        agreement = activate_supplier_price_agreement(agreement=self.get_object(), user=request.user)
        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        agreement = cancel_supplier_price_agreement(
            agreement=self.get_object(), reason=request.data.get("reason", ""), user=request.user
        )
        return Response(self.get_serializer(agreement).data)


class DailyProductionLogViewSet(viewsets.ModelViewSet):
    serializer_class = DailyProductionLogSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "production_log.view"
    required_action_permissions = {
        "create": "production_log.create",
        "update": "production_log.create",
        "partial_update": "production_log.create",
        "destroy": "admin.configure",
        "submit": "production_log.submit",
        "approve": "production_log.approve",
    }

    def get_queryset(self):
        queryset = DailyProductionLog.objects.select_related(
            "supervisor", "warehouse", "production_order", "packing_order",
            "raw_material_batch", "powder_batch", "finished_goods_batch", "approved_by",
        )
        for field in ("shift", "production_order", "packing_order", "status"):
            if self.request.GET.get(field):
                queryset = queryset.filter(**{field: self.request.GET[field]})
        if self.request.GET.get("date_from"):
            queryset = queryset.filter(log_date__gte=self.request.GET["date_from"])
        if self.request.GET.get("date_to"):
            queryset = queryset.filter(log_date__lte=self.request.GET["date_to"])
        if self.request.GET.get("operator"):
            queryset = queryset.filter(operator__icontains=self.request.GET["operator"])
        return queryset

    def perform_create(self, serializer):
        from .services import next_document_number
        serializer.instance = create_daily_production_log(
            log_number=next_document_number("PLOG"), user=self.request.user,
            **serializer.validated_data,
        )

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        item = submit_daily_production_log(production_log=self.get_object(), user=request.user)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        item = approve_daily_production_log(production_log=self.get_object(), user=request.user)
        return Response(self.get_serializer(item).data)


class CustomerDistributorViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerDistributorSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "customer.view"
    required_action_permissions = {
        "create": "customer.create",
        "update": "customer.edit",
        "partial_update": "customer.edit",
        "destroy": "admin.configure",
        "block": "customer.block",
        "unblock": "customer.block",
        "activate": "customer.edit",
        "deactivate": "customer.edit",
    }

    def get_queryset(self):
        queryset = CustomerDistributor.objects.prefetch_related("shipping_addresses")
        for field in ("customer_type", "sales_channel", "status", "country"):
            if self.request.GET.get(field):
                queryset = queryset.filter(**{field: self.request.GET[field]})
        if self.request.GET.get("city"):
            queryset = queryset.filter(city__iexact=self.request.GET["city"])
        if self.request.GET.get("search"):
            term = self.request.GET["search"]
            queryset = queryset.filter(
                Q(code__icontains=term) | Q(business_name__icontains=term)
                | Q(phone__icontains=term) | Q(city__icontains=term)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.instance = create_customer_distributor(user=self.request.user, **serializer.validated_data)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        customer = set_customer_blocked(customer=self.get_object(), blocked=True, user=request.user)
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["post"])
    def unblock(self, request, pk=None):
        customer = set_customer_blocked(customer=self.get_object(), blocked=False, user=request.user)
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        customer = set_customer_status(
            customer=self.get_object(), target_status=CustomerDistributor.Status.ACTIVE, user=request.user
        )
        return Response(self.get_serializer(customer).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        customer = set_customer_status(
            customer=self.get_object(), target_status=CustomerDistributor.Status.INACTIVE, user=request.user
        )
        return Response(self.get_serializer(customer).data)


class CustomerShippingAddressViewSet(viewsets.ModelViewSet):
    queryset = CustomerShippingAddress.objects.select_related("customer")
    serializer_class = CustomerShippingAddressSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "customer.view"
    required_action_permissions = {
        "create": "customer.create",
        "update": "customer.edit",
        "partial_update": "customer.edit",
        "destroy": "customer.edit",
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ScheduledTaskConfigViewSet(viewsets.ModelViewSet):
    queryset = ScheduledTaskConfig.objects.all()
    serializer_class = ScheduledTaskConfigSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "scheduled_task.view"
    required_action_permissions = {
        "create": "scheduled_task.configure",
        "update": "scheduled_task.configure",
        "partial_update": "scheduled_task.configure",
        "destroy": "scheduled_task.configure",
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ScheduledTaskLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ScheduledTaskLog.objects.all()
    serializer_class = ScheduledTaskLogSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_read_permission = "scheduled_task.view"
    required_action_permissions = {
        "run_expiry_refresh": "scheduled_task.run",
        "run_overdue_refresh": "scheduled_task.run",
        "run_maintenance": "scheduled_task.run",
    }

    @action(detail=False, methods=["post"], url_path="run-expiry-refresh")
    def run_expiry_refresh(self, request):
        from .scheduled_jobs import refresh_expiry_statuses

        log = refresh_expiry_statuses(triggered_by=ScheduledTaskLog.TriggeredBy.MANUAL)
        return Response(self.get_serializer(log).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="run-overdue-refresh")
    def run_overdue_refresh(self, request):
        from .scheduled_jobs import refresh_overdue_supplier_invoices

        log = refresh_overdue_supplier_invoices(triggered_by=ScheduledTaskLog.TriggeredBy.MANUAL)
        return Response(self.get_serializer(log).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="run-maintenance")
    def run_maintenance(self, request):
        from .scheduled_jobs import run_scheduled_erp_maintenance

        log = run_scheduled_erp_maintenance(triggered_by=ScheduledTaskLog.TriggeredBy.MANUAL)
        return Response(self.get_serializer(log).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def receive_powder(request):
    from .models import ProductionOrder
    if not has_erp_permission(request.user, "production.post"):
        return Response({"detail": "This workflow requires production.post permission."}, status=403)
    batch = receive_powder_output(
        production_order=_get_or_404(ProductionOrder, pk=request.data["production_order"]),
        actual_output_quantity=Decimal(str(request.data["actual_output_quantity"])),
        wastage_quantity=Decimal(str(request.data.get("wastage_quantity", "0"))),
        powder_batch_number=request.data["powder_batch_number"],
        expiry_date=request.data.get("expiry_date") or None,
        user=request.user,
    )
    return Response({"powder_batch": batch.batch_number})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_view(request, report_name: str):
    required_permission = report_permission_for(report_name)
    if not required_permission:
        return Response({"detail": "Unknown report."}, status=404)
    if not has_erp_permission(request.user, required_permission):
        return Response({"detail": "You do not have permission to view this report."}, status=403)

    date_from = request.GET.get("date_from") or None
    date_to = request.GET.get("date_to") or None
    include_blocked = request.GET.get("include_blocked") == "1"
    include_expired = request.GET.get("include_expired") == "1"

    warehouse = None
    if request.GET.get("warehouse"):
        try:
            warehouse = Warehouse.objects.get(pk=request.GET["warehouse"])
        except ObjectDoesNotExist:
            return Response({"detail": "Warehouse not found."}, status=404)

    try:
        if report_name == "supplier-ledger":
            supplier_pk = request.GET.get("supplier")
            if not supplier_pk:
                return Response({"detail": "supplier parameter is required."}, status=400)
            supplier = _get_or_404(Supplier, pk=supplier_pk)
            data = supplier_ledger_report(supplier, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "supplier-aging":
            supplier = None
            if request.GET.get("supplier"):
                supplier = _get_or_404(Supplier, pk=request.GET["supplier"])
            data = supplier_payable_aging_report(supplier=supplier, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "raw-stock":
            data = raw_material_stock_report(include_blocked=include_blocked, include_expired=include_expired, warehouse=warehouse)
            rows = data["rows"]
        elif report_name == "powder-stock":
            data = powder_stock_report(include_blocked=include_blocked, include_expired=include_expired, warehouse=warehouse)
            rows = data["rows"]
        elif report_name == "packaging-stock":
            data = packaging_stock_report(include_blocked=include_blocked, include_expired=include_expired, warehouse=warehouse)
            rows = data["rows"]
        elif report_name == "finished-stock":
            data = finished_goods_stock_report(include_blocked=include_blocked, include_expired=include_expired, warehouse=warehouse)
            rows = data["rows"]
        elif report_name == "fefo-dispatch":
            product = _get_or_404(Product, pk=request.GET["product"]) if request.GET.get("product") else None
            required_quantity = Decimal(str(request.GET["quantity"])) if request.GET.get("quantity") else None
            data = fefo_dispatch_report(product=product, warehouse=warehouse, required_quantity=required_quantity)
            rows = data["rows"]
        elif report_name == "yield":
            data = yield_report()
            rows = data["rows"]
        elif report_name == "costing":
            data = costing_report()
            rows = data["rows"]
        elif report_name == "expiry":
            data = expiry_report()
            rows = data["rows"]
        elif report_name == "batch-traceability":
            data = batch_traceability_report()
            rows = data["trace_back"] + data["trace_forward"]
        elif report_name == "purchase":
            supplier = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = purchase_report(supplier=supplier)
            rows = data["rows"]
        elif report_name == "grn":
            supplier = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = grn_report(supplier=supplier)
            rows = data["rows"]
        elif report_name == "quality-rejection":
            data = quality_rejection_report()
            rows = data["rows"]
        elif report_name == "wastage":
            data = wastage_report()
            rows = data["rows"]
        elif report_name == "packing":
            data = packing_report()
            rows = data["rows"]
        elif report_name == "packaging-consumption":
            data = packaging_consumption_report()
            rows = data["rows"]
        elif report_name == "near-expiry":
            data = near_expiry_report()
            rows = data["rows"]
        elif report_name == "expired-stock":
            data = expired_stock_report()
            rows = data["rows"]
        elif report_name == "stock-adjustment":
            data = adjustment_report("stock_adjustment")
            rows = data["rows"]
        elif report_name == "payment-reversal":
            data = payment_reversal_report()
            rows = data["rows"]
        elif report_name == "debit-note":
            data = adjustment_report("debit_note")
            rows = data["rows"]
        elif report_name == "credit-note":
            data = adjustment_report("credit_note")
            rows = data["rows"]
        elif report_name == "opening-balance":
            data = opening_balance_report()
            rows = data["rows"]
        elif report_name == "low-stock":
            data = low_stock_report()
            rows = data["rows"]
        elif report_name == "supplier-return":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_return_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "supplier-balance":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_balance_summary_report(supplier=s)
            rows = data["rows"]
        elif report_name == "damaged-stock":
            data = damaged_stock_report(warehouse=warehouse, include_expired=include_expired)
            rows = data["rows"]
        elif report_name == "supplier-advance-report":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_advance_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "supplier-rejection":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_rejection_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "supplier-shortage":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_shortage_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "supplier-yield":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = supplier_yield_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "repacking":
            data = repacking_report(date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "user-activity":
            data = user_activity_report(date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "approval-pending":
            data = approval_pending_report()
            rows = data["rows"]
        elif report_name == "grinding":
            s = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            data = grinding_report(supplier=s, date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "finished-sku-production":
            data = finished_sku_production_report(date_from=date_from, date_to=date_to)
            rows = data["rows"]
        elif report_name == "batch-cost":
            bt = request.GET.get("batch_type") or None
            data = batch_cost_report(batch_type=bt, warehouse=warehouse)
            rows = data["rows"]
        elif report_name == "cost-variance":
            data = cost_variance_report()
            rows = data["rows"]
        elif report_name == "supplier-active-rates":
            supplier = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            product = _get_or_404(Product, pk=request.GET["product"]) if request.GET.get("product") else None
            data = supplier_active_rate_report(
                supplier=supplier,
                product=product,
                item_type=request.GET.get("item_type") or None,
                status=request.GET.get("status") or SupplierPriceAgreement.Status.ACTIVE,
                date_from=date_from,
                date_to=date_to,
            )
            rows = data["rows"]
        elif report_name in {"supplier-rate-variance", "item-supplier-rate-comparison", "supplier-rate-comparison"}:
            supplier = _get_or_404(Supplier, pk=request.GET["supplier"]) if request.GET.get("supplier") else None
            product = _get_or_404(Product, pk=request.GET["product"]) if request.GET.get("product") else None
            threshold = Decimal(request.GET["variance_threshold"]) if request.GET.get("variance_threshold") else None
            data = supplier_rate_variance_report(
                supplier=supplier,
                product=product,
                item_type=request.GET.get("item_type") or None,
                source_type=request.GET.get("source_type") or None,
                date_from=date_from,
                date_to=date_to,
                variance_threshold=threshold,
            )
            rows = data["rows"]
        elif report_name in {
            "daily-production-log", "shift-production-log", "operator-production-log",
            "machine-production-log", "daily-wastage-summary", "daily-packing-summary",
        }:
            product = _get_or_404(Product, pk=request.GET["product"]) if request.GET.get("product") else None
            production_order = (
                _get_or_404(ProductionOrder, pk=request.GET["production_order"])
                if request.GET.get("production_order") else None
            )
            packing_order = (
                _get_or_404(PackingOrder, pk=request.GET["packing_order"])
                if request.GET.get("packing_order") else None
            )
            report_filters = dict(
                date_from=date_from,
                date_to=date_to,
                shift=request.GET.get("shift") or None,
                operator=request.GET.get("operator") or None,
                machine=request.GET.get("machine") or None,
                product=product,
                production_order=production_order,
                packing_order=packing_order,
            )
            if report_name == "daily-wastage-summary":
                data = production_wastage_summary_report(**report_filters)
            elif report_name == "daily-packing-summary":
                data = production_packing_summary_report(**report_filters)
            else:
                data = daily_production_log_report(**report_filters)
            rows = data["rows"]
        elif report_name == "production-issue-summary":
            data = production_issue_summary_report(
                date_from=date_from,
                date_to=date_to,
                shift=request.GET.get("shift") or None,
                operator=request.GET.get("operator") or None,
                machine=request.GET.get("machine") or None,
            )
            rows = data["rows"]
        elif report_name in {
            "customer-master", "customer-segmentation", "customer-by-channel",
            "customer-by-location", "blocked-customers", "distributor-readiness",
        }:
            data = customer_master_report(
                customer_type=(
                    "distributor" if report_name == "distributor-readiness"
                    else request.GET.get("customer_type") or None
                ),
                sales_channel=request.GET.get("sales_channel") or None,
                city=request.GET.get("city") or None,
                country=request.GET.get("country") or None,
                status="blocked" if report_name == "blocked-customers" else request.GET.get("status") or None,
            )
            rows = data["rows"]
        elif report_name in {"scheduled-task-log", "failed-scheduled-jobs"}:
            data = scheduled_task_log_report(
                status="failed" if report_name == "failed-scheduled-jobs" else request.GET.get("status") or None,
                job_type=request.GET.get("job_type") or None,
                date_from=date_from,
                date_to=date_to,
            )
            rows = data["rows"]
        else:
            return Response({"detail": "Unknown report."}, status=404)
    except ObjectDoesNotExist as exc:
        return Response({"detail": str(exc)}, status=404)

    rows = _apply_row_window(request, data, rows)
    if request.GET.get("export") == "csv":
        response = HttpResponse(rows_to_csv(rows), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{report_name}.csv"'
        return response
    data["rows"] = rows
    return Response(data)


# ── RECIPE VIEWSET ────────────────────────────────────────────────────────────
from .models import PurchaseRequirement, Recipe, RecipeIngredient, LandedCostAllocation
from .serializers import (
    PurchaseRequirementSerializer, RecipeSerializer, LandedCostAllocationSerializer
)


class RecipeViewSet(viewsets.ModelViewSet):
    """
    Recipe / formula management (spec 3.30 / P1).
    Confidentiality: full ingredient view requires admin.configure or reports.view_financial.
    """
    queryset = Recipe.objects.prefetch_related("ingredients").select_related("finished_product", "batch_unit")
    serializer_class = RecipeSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_action_permissions = {
        "create": "admin.configure",
        "update": "admin.configure",
        "partial_update": "admin.configure",
        "destroy": "admin.configure",
        "activate": "admin.configure",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        # Confidential recipes: only admin/financial users see ingredients
        if not has_erp_permission(self.request.user, "admin.configure") and \
           not has_erp_permission(self.request.user, "reports.view_financial"):
            qs = qs.filter(is_confidential=False)
        return qs

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        from .services import activate_recipe_version
        recipe = _get_or_404(Recipe, pk=pk)
        activated = activate_recipe_version(recipe_id=recipe.pk, user=request.user)
        return Response(RecipeSerializer(activated).data)


class PurchaseRequirementViewSet(viewsets.ModelViewSet):
    """Purchase requirements / demand notices (spec 3.11 / P1)."""
    queryset = PurchaseRequirement.objects.select_related("product", "purchase_order")
    serializer_class = PurchaseRequirementSerializer
    permission_classes = [IsAuthenticatedAndCanPost]
    required_action_permissions = {
        "create": "purchase.create",
        "update": "purchase.create",
        "partial_update": "purchase.create",
        "destroy": "admin.configure",
    }

    def perform_create(self, serializer):
        from .services import next_document_number
        number = next_document_number("PR")
        serializer.save(number=number, created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class LandedCostViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin,
                        mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Landed cost allocation per GRN (spec 3.46 / P1)."""
    queryset = LandedCostAllocation.objects.select_related("grn")
    serializer_class = LandedCostAllocationSerializer
    permission_classes = [IsAuthenticatedAndCanPost, FinancialReadPermission]
    required_action_permissions = {"create": "supplier_invoice.post"}

    def perform_create(self, serializer):
        from .services import next_document_number
        number = next_document_number("LC")
        serializer.save(number=number, created_by=self.request.user, updated_by=self.request.user)


class PhysicalStockCountViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin,
                               mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Physical stock count documents. Spec 3.45."""
    permission_classes = [IsAuthenticatedAndCanPost, InventoryReadPermission]
    serializer_class = PhysicalStockCountSerializer

    def get_queryset(self):
        from .models import PhysicalStockCount
        return PhysicalStockCount.objects.all().select_related("warehouse", "approved_by").prefetch_related("lines")

    def perform_create(self, serializer):
        from .services import next_document_number
        number = next_document_number("PSC")
        serializer.save(number=number, created_by=self.request.user, updated_by=self.request.user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def opening_stock_view(request):
    """
    Post opening stock for any product type (spec 3.54 / P0).
    Requires stock.adjust permission.
    """
    if not has_erp_permission(request.user, "stock.adjust"):
        return Response({"detail": "Requires stock.adjust permission."}, status=403)
    from .services import post_opening_stock
    product = _get_or_404(Product, pk=request.data["product"])
    warehouse = _get_or_404(Warehouse, pk=request.data["warehouse"])
    supplier = None
    if request.data.get("supplier"):
        supplier = _get_or_404(Supplier, pk=request.data["supplier"])
    batch = post_opening_stock(
        product=product,
        warehouse=warehouse,
        batch_number=request.data["batch_number"],
        quantity=Decimal(str(request.data["quantity"])),
        unit_cost=Decimal(str(request.data["unit_cost"])),
        expiry_date=request.data.get("expiry_date") or None,
        manufacturing_date=request.data.get("manufacturing_date") or None,
        supplier=supplier,
        remarks=request.data.get("remarks", "Opening stock balance"),
        user=request.user,
    )
    return Response({"batch_number": batch.batch_number, "quantity": str(batch.quantity_on_hand)}, status=201)
