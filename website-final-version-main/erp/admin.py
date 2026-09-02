from django.contrib import admin

from . import models


class NoDeleteAdminMixin:
    def has_delete_permission(self, request, obj=None):
        return False


class PostedDocumentAdminMixin(NoDeleteAdminMixin):
    def get_readonly_fields(self, request, obj=None):
        if obj and getattr(obj, "status", None) != models.DocumentState.DRAFT:
            return [field.name for field in obj._meta.fields]
        return super().get_readonly_fields(request, obj)


class ImmutableAdminMixin(NoDeleteAdminMixin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "legal_name", "default_currency", "is_active")


@admin.register(models.Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "location", "is_active")


@admin.register(models.UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit_type", "decimal_places", "is_active")


@admin.register(models.UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin):
    list_display = ("from_unit", "to_unit", "factor")


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "product_type", "base_unit", "grammage", "shelf_life_days", "is_active")
    list_filter = ("product_type", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "payment_terms_days", "payable_balance", "advance_balance", "is_active")
    search_fields = ("code", "name")


@admin.register(models.CashBankAccount)
class CashBankAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "balance", "is_active")


class PurchaseOrderLineInline(admin.TabularInline):
    model = models.PurchaseOrderLine
    extra = 0


@admin.register(models.PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "supplier", "order_date", "expected_date", "status")
    inlines = [PurchaseOrderLineInline]


class GRNLineInline(admin.TabularInline):
    model = models.GRNLine
    extra = 0

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != models.DocumentState.DRAFT:
            return [field.name for field in self.model._meta.fields]
        return super().get_readonly_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        if obj and obj.status != models.DocumentState.DRAFT:
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status != models.DocumentState.DRAFT:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(models.GRN)
class GRNAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "supplier", "grn_date", "status", "payable_amount", "shortage_amount", "cancelled_by", "cancelled_at")
    list_filter = ("status",)
    search_fields = ("number", "supplier__code", "delivery_note_number")
    readonly_fields = ("approved_by", "approved_at", "cancelled_by", "cancelled_at")
    fieldsets = (
        ("GRN Header", {"fields": (
            "number", "supplier", "purchase_order", "grn_date",
            "delivery_note_number", "vehicle_number", "received_by",
            "default_warehouse", "remarks", "status",
        )}),
        ("Approval", {"fields": ("approved_by", "approved_at")}),
        ("Cancellation", {"fields": ("cancelled_by", "cancelled_at", "cancellation_reason")}),
        ("Totals", {"fields": ("payable_amount", "shortage_amount", "quality_deduction_amount")}),
    )
    inlines = [GRNLineInline]


@admin.register(models.QualityInspection)
class QualityInspectionAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("grn", "status", "deduction_amount", "moisture_ok", "aroma_ok", "contamination_ok")


@admin.register(models.SupplierInvoice)
class SupplierInvoiceAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "supplier", "invoice_date", "due_date", "amount", "paid_amount", "advance_adjusted_amount", "status")
    list_filter = ("status",)


@admin.register(models.SupplierPayment)
class SupplierPaymentAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "supplier", "payment_type", "payment_date", "amount", "status")
    list_filter = ("payment_type", "status")


@admin.register(models.StockBatch)
class StockBatchAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("product", "batch_number", "batch_type", "warehouse", "quantity_on_hand", "unit_cost", "expiry_date", "is_blocked")
    list_filter = ("batch_type", "is_blocked")
    search_fields = ("batch_number", "product__code", "product__name")


@admin.register(models.StockLedgerEntry)
class StockLedgerEntryAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("transaction_date", "product", "batch", "direction", "quantity", "source_document_type", "source_document_number")
    list_filter = ("direction", "source_document_type")


@admin.register(models.SupplierLedgerEntry)
class SupplierLedgerEntryAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "supplier",
        "source_document_type",
        "source_document_number",
        "balance_effect",
        "payable_effect",
        "advance_effect",
        "running_payable_balance",
        "running_advance_balance",
    )
    list_filter = ("balance_effect", "source_document_type")


@admin.register(models.ProductionOrder)
class ProductionOrderAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "raw_batch", "powder_product", "issued_quantity", "actual_output_quantity", "wastage_quantity", "status")


class PackagingBOMLineInline(admin.TabularInline):
    model = models.PackagingBOMLine
    extra = 0


@admin.register(models.PackagingBOM)
class PackagingBOMAdmin(admin.ModelAdmin):
    list_display = ("finished_product", "powder_product", "powder_quantity_per_unit", "version", "is_active")
    inlines = [PackagingBOMLineInline]


@admin.register(models.PackingOrder)
class PackingOrderAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "bom", "powder_batch", "planned_units", "completed_units", "finished_batch", "status")


@admin.register(models.OpeningBalance)
class OpeningBalanceAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "product", "supplier", "cash_bank_account", "quantity", "amount", "status")


@admin.register(models.AdjustmentDocument)
class AdjustmentDocumentAdmin(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("number", "adjustment_type", "supplier", "product", "batch", "amount", "quantity", "balance_effect", "status")
    list_filter = ("adjustment_type", "status")


@admin.register(models.AuditEvent)
class AuditEventAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "event_type", "source_document_type", "source_document_number", "actor")
    list_filter = ("event_type", "source_document_type")


# ── NEW MODELS (V6 gap fill) ─────────────────────────────────────────────────

@admin.register(models.PurchaseRequirement)
class PurchaseRequirementAdmin(admin.ModelAdmin):
    list_display = ("number", "product", "required_quantity", "required_by_date", "source", "status", "purchase_order")
    list_filter = ("status", "source")
    search_fields = ("number", "product__code", "product__name")
    readonly_fields = ("number",)


@admin.register(models.SupplierTerm)
class SupplierTermAdmin(admin.ModelAdmin):
    list_display = ("supplier", "payment_mode", "credit_days", "advance_required", "shortage_tolerance_pct")
    search_fields = ("supplier__code", "supplier__name")


@admin.register(models.SupplierPerformance)
class SupplierPerformanceAdmin(admin.ModelAdmin):
    list_display = ("supplier", "total_grn_count", "total_rejected_quantity", "average_yield_pct", "rating", "last_updated")
    search_fields = ("supplier__code",)


class RecipeIngredientInline(admin.TabularInline):
    model = models.RecipeIngredient
    extra = 1
    fields = ("ingredient", "quantity", "percentage", "tolerance_pct", "sequence", "remarks")


@admin.register(models.Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "finished_product", "version", "effective_date", "is_confidential", "status", "approved_by")
    list_filter = ("status", "is_confidential")
    search_fields = ("code", "name", "finished_product__code")
    readonly_fields = ("approved_by", "approved_at")
    inlines = [RecipeIngredientInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == "posted":
            return [field.name for field in obj._meta.fields]
        return self.readonly_fields


@admin.register(models.LandedCostAllocation)
class LandedCostAllocationAdmin(admin.ModelAdmin):
    list_display = ("number", "grn", "cost_category", "amount", "allocation_base", "status")
    list_filter = ("cost_category", "status")
    readonly_fields = ("number",)


@admin.register(models.ChartOfAccountEntry)
class ChartOfAccountEntryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "is_active")
    list_filter = ("account_type", "is_active")
    search_fields = ("code", "name")


# Update existing QualityInspection admin to show new fields
admin.site.unregister(models.QualityInspection)


@admin.register(models.QualityInspection)
class QualityInspectionAdminV2(PostedDocumentAdminMixin, admin.ModelAdmin):
    list_display = (
        "grn", "quality_decision", "status", "deduction_amount",
        "color_ok", "smell_ok", "moisture_ok", "foreign_particles_ok",
        "adulteration_suspicion",
    )
    list_filter = ("quality_decision", "status")
    fieldsets = (
        ("GRN Reference", {"fields": ("grn",)}),
        ("Inspection Criteria", {"fields": (
            "color_ok", "smell_ok", "moisture_ok", "dust_ok",
            "foreign_particles_ok", "stones_ok", "insects_ok",
            "adulteration_suspicion", "cleanliness_ok", "grade_match_ok",
            "packaging_condition_ok", "aroma_ok", "contamination_ok",
        )}),
        ("Decision & Deductions", {"fields": (
            "quality_decision", "deduction_amount", "deduction_quantity", "inspector_notes",
        )}),
        ("Status", {"fields": ("status",)}),
    )


# Update Product admin to show new fields
admin.site.unregister(models.Product)


@admin.register(models.Product)
class ProductAdminV2(admin.ModelAdmin):
    list_display = ("code", "name", "product_type", "category", "grade", "base_unit", "grammage", "minimum_stock", "reorder_level", "is_active")
    list_filter = ("product_type", "is_active")
    search_fields = ("code", "name", "barcode")
    fieldsets = (
        ("Core", {"fields": ("code", "name", "product_type", "category", "base_unit", "is_active")}),
        ("Raw Material", {"fields": ("grade", "origin", "storage_notes", "expected_grinding_yield_pct", "default_supplier"), "classes": ("collapse",)}),
        ("Powder", {"fields": ("linked_raw_spice", "moisture_loss_allowance_pct", "grinding_loss_allowance_pct"), "classes": ("collapse",)}),
        ("Finished SKU", {"fields": ("grammage", "net_weight", "gross_weight", "pack_type", "carton_quantity", "shelf_life_days", "mrp", "sale_price"), "classes": ("collapse",)}),
        ("Stock Control", {"fields": ("minimum_stock", "maximum_stock", "reorder_level")}),
        ("Barcodes & Labels", {"fields": ("barcode", "batch_barcode_prefix", "carton_barcode", "qr_code_data", "label_version", "artwork_version", "design_version"), "classes": ("collapse",)}),
    )


# Update Supplier admin with new fields
admin.site.unregister(models.Supplier)


@admin.register(models.Supplier)
class SupplierAdminV2(admin.ModelAdmin):
    list_display = ("code", "name", "supplier_category", "city", "payment_terms_days", "payable_balance", "advance_balance", "is_active")
    list_filter = ("supplier_category", "is_active")
    search_fields = ("code", "name", "tax_identifier")
    fieldsets = (
        ("Identity", {"fields": ("code", "name", "business_name", "supplier_category", "is_active")}),
        ("Contact", {"fields": ("contact_name", "phone", "email", "address", "city")}),
        ("Banking", {"fields": ("bank_account_title", "bank_name", "account_number", "iban"), "classes": ("collapse",)}),
        ("Terms", {"fields": ("payment_terms_days", "lead_time_days", "tax_identifier", "tax_category", "withholding_tax_rate")}),
        ("Balances (read-only)", {"fields": ("payable_balance", "advance_balance")}),
    )
    readonly_fields = ("payable_balance", "advance_balance")


# Update PackagingBOM admin
admin.site.unregister(models.PackagingBOM)


class PackagingBOMLineInlineV2(admin.TabularInline):
    model = models.PackagingBOMLine
    extra = 0
    fields = ("packaging_product", "quantity_per_unit", "wastage_allowance_pct", "sequence", "remarks")


@admin.register(models.PackagingBOM)
class PackagingBOMAdminV2(admin.ModelAdmin):
    list_display = ("finished_product", "powder_product", "powder_quantity_per_unit", "packing_wastage_pct", "version", "effective_date", "is_active")
    inlines = [PackagingBOMLineInlineV2]
    readonly_fields = ("approved_by",)


# Update Company admin
admin.site.unregister(models.Company)


@admin.register(models.Company)
class CompanyAdminV2(admin.ModelAdmin):
    list_display = ("name", "legal_name", "default_currency", "financial_year_start_month", "near_expiry_threshold_days", "is_active")
    fieldsets = (
        ("Identity", {"fields": ("name", "legal_name", "tax_identifier", "is_active")}),
        ("Contact & Address", {"fields": ("address", "city", "country", "phone", "email")}),
        ("Financial", {"fields": ("default_currency", "decimal_precision", "money_precision", "financial_year_start_month")}),
        ("Operational Defaults", {"fields": ("default_warehouse", "near_expiry_threshold_days")}),
        ("Document Numbering", {"fields": ("po_prefix", "grn_prefix", "inv_prefix", "pay_prefix", "adv_prefix", "dn_prefix", "cn_prefix", "prod_prefix", "pack_prefix", "adj_prefix"), "classes": ("collapse",)}),
        ("Receipt Print", {"fields": ("receipt_show_logo", "receipt_footer_text", "receipt_paper_size"), "classes": ("collapse",)}),
    )


@admin.register(models.SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "value_type", "description", "is_editable", "updated_at")
    list_filter = ("value_type", "is_editable")
    search_fields = ("key", "description")
    readonly_fields = ("updated_at", "updated_by")

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(models.DocumentNumberSeries)
class DocumentNumberSeriesAdmin(admin.ModelAdmin):
    list_display = ("prefix", "description", "current_number", "padding_digits", "separator", "is_active")
    list_filter = ("is_active",)
    search_fields = ("prefix", "description")


# ── STRUCTURAL MODELS (V7) ───────────────────────────────────────────────────

class SupplierInvoiceLineInline(admin.TabularInline):
    model = models.SupplierInvoiceLine
    extra = 0
    fields = ("product", "accepted_quantity", "unit_cost", "discount_amount", "tax_amount", "line_total")
    readonly_fields = ("line_total",)


# Update SupplierInvoice admin to include lines
try:
    admin.site.unregister(models.SupplierInvoice)
except Exception:
    pass


@admin.register(models.SupplierInvoice)
class SupplierInvoiceAdminV2(admin.ModelAdmin):
    list_display = ("number", "supplier", "invoice_date", "due_date", "amount", "paid_amount", "outstanding_amount", "status")
    list_filter = ("status",)
    search_fields = ("number", "supplier__code")
    readonly_fields = ("paid_amount", "advance_adjusted_amount", "debit_note_amount", "credit_note_amount")
    inlines = [SupplierInvoiceLineInline]


class PhysicalStockCountLineInline(admin.TabularInline):
    model = models.PhysicalStockCountLine
    extra = 0
    fields = ("batch", "system_quantity", "physical_quantity", "variance", "variance_value", "reason", "adjustment_number")
    readonly_fields = ("system_quantity", "variance", "variance_value")


@admin.register(models.PhysicalStockCount)
class PhysicalStockCountAdmin(admin.ModelAdmin):
    list_display = ("number", "count_date", "count_type", "warehouse", "status", "approved_by")
    list_filter = ("count_type", "status")
    readonly_fields = ("approved_by", "approved_at")
    inlines = [PhysicalStockCountLineInline]


class OpeningBalanceLineInline(admin.TabularInline):
    model = models.OpeningBalanceLine
    extra = 0
    fields = ("product", "warehouse", "batch_number", "quantity", "unit_cost", "amount", "expiry_date", "remarks")
    readonly_fields = ("amount",)


try:
    admin.site.unregister(models.OpeningBalance)
except Exception:
    pass


@admin.register(models.OpeningBalance)
class OpeningBalanceAdminV2(admin.ModelAdmin):
    list_display = ("number", "amount", "status", "created_by", "created_at")
    list_filter = ("status",)
    readonly_fields = ("number",)
    inlines = [OpeningBalanceLineInline]


@admin.register(models.SupplierPaymentAllocation)
class SupplierPaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ("payment", "invoice", "allocated_amount", "allocation_type", "created_at")
    list_filter = ("allocation_type",)
    search_fields = ("payment__number", "invoice__number")


@admin.register(models.SupplierPriceAgreement)
class SupplierPriceAgreementAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "agreement_number", "supplier", "product", "agreed_rate", "unit",
        "effective_date", "expiry_date", "status",
    )
    list_filter = ("status", "item_type", "rate_type")
    search_fields = ("agreement_number", "supplier__code", "supplier__name", "product__code", "product__name")
    readonly_fields = ("approved_by", "approved_at")


@admin.register(models.DailyProductionLog)
class DailyProductionLogAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "log_number", "log_date", "shift", "supervisor", "operator", "machine",
        "raw_quantity_issued", "powder_quantity_received", "finished_quantity_packed", "status",
    )
    list_filter = ("shift", "issue_category", "status", "log_date")
    search_fields = ("log_number", "operator", "machine", "remarks")
    readonly_fields = ("approved_by", "approved_at")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status in {models.DailyProductionLog.Status.APPROVED, models.DailyProductionLog.Status.LOCKED}:
            return [field.name for field in obj._meta.fields]
        return self.readonly_fields


class CustomerShippingAddressInline(admin.TabularInline):
    model = models.CustomerShippingAddress
    extra = 0


@admin.register(models.CustomerDistributor)
class CustomerDistributorAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code", "business_name", "customer_type", "sales_channel", "contact_person",
        "phone", "city", "country", "credit_days", "credit_limit", "status",
    )
    list_filter = ("customer_type", "sales_channel", "status", "country")
    search_fields = ("code", "business_name", "contact_person", "phone", "city")
    inlines = [CustomerShippingAddressInline]


@admin.register(models.ScheduledTaskConfig)
class ScheduledTaskConfigAdmin(admin.ModelAdmin):
    list_display = ("job_name", "enabled", "frequency_description", "command_name", "last_run", "next_run")
    list_filter = ("enabled",)
    search_fields = ("job_name", "command_name")


@admin.register(models.ScheduledTaskLog)
class ScheduledTaskLogAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("job_name", "job_type", "started_at", "finished_at", "status", "duration", "triggered_by")
    list_filter = ("job_type", "status", "triggered_by")
    search_fields = ("job_name", "message", "error_details")
