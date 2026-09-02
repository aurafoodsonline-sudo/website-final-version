from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import (
    AdjustmentDocument,
    CashBankAccount,
    GRN,
    GRNLine,
    LandedCostAllocation,
    PackagingBOM,
    PackagingBOMLine,
    Product,
    ProductionOrder,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequirement,
    QualityInspection,
    Recipe,
    RecipeIngredient,
    StockBatch,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    UnitOfMeasure,
    Warehouse,
)


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ["id", "code", "name", "unit_type", "decimal_places", "is_active"]
        read_only_fields = ["id"]

    def validate_code(self, v):
        if not v.strip():
            raise serializers.ValidationError("UoM code is required.")
        return v.strip().upper()


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "code", "name", "location", "is_active"]
        read_only_fields = ["id"]


class ProductSerializer(serializers.ModelSerializer):
    base_unit_code = serializers.CharField(source="base_unit.code", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "code", "name", "product_type", "category", "base_unit", "base_unit_code",
            "grade", "origin", "storage_notes", "expected_grinding_yield_pct", "default_supplier",
            "linked_raw_spice", "moisture_loss_allowance_pct", "grinding_loss_allowance_pct",
            "grammage", "net_weight", "gross_weight", "pack_type", "carton_quantity",
            "mrp", "sale_price",
            "shelf_life_days", "minimum_stock", "maximum_stock", "reorder_level",
            "barcode", "label_version", "artwork_version", "design_version",
            "is_active", "claim_status",
        ]
        read_only_fields = ["id"]

    def validate(self, data):
        if data.get("product_type") == "finished" and not data.get("grammage"):
            raise serializers.ValidationError({"grammage": "Finished SKUs require grammage."})
        return data


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id", "code", "name", "business_name", "supplier_category",
            "contact_name", "phone", "email", "address", "city",
            "bank_account_title", "bank_name", "account_number", "iban",
            "payment_terms_days", "lead_time_days",
            "tax_identifier", "tax_category", "withholding_tax_rate",
            "payable_balance", "advance_balance", "is_active",
        ]
        read_only_fields = ["id", "payable_balance", "advance_balance"]

    def validate_withholding_tax_rate(self, v):
        if v < 0 or v > 100:
            raise serializers.ValidationError("Withholding tax rate must be between 0 and 100.")
        return v


class SupplierDirectorySerializer(serializers.ModelSerializer):
    """Non-financial supplier projection for authenticated operators."""

    class Meta:
        model = Supplier
        fields = [
            "id", "code", "name", "business_name", "supplier_category",
            "contact_name", "phone", "email", "city",
            "payment_terms_days", "lead_time_days", "is_active",
        ]
        read_only_fields = fields


class CashBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashBankAccount
        fields = ["id", "code", "name", "account_type", "bank_name", "account_number", "iban", "balance", "is_active"]
        read_only_fields = ["id", "balance"]


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id", "product", "quantity", "unit_cost", "rate_agreement",
            "agreed_rate_snapshot", "rate_variance_amount", "rate_variance_percentage",
            "rate_override_reason",
        ]
        read_only_fields = [
            "id", "rate_agreement", "agreed_rate_snapshot", "rate_variance_amount", "rate_variance_percentage",
        ]

    def validate_quantity(self, v):
        if v <= 0:
            raise serializers.ValidationError("Quantity must be positive.")
        return v

    def validate_unit_cost(self, v):
        if v <= 0:
            raise serializers.ValidationError("Unit cost must be positive.")
        return v


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ["id", "number", "supplier", "supplier_code", "order_date", "expected_date", "status", "lines"]
        read_only_fields = ["id", "number", "status"]


class GRNLineSerializer(serializers.ModelSerializer):
    accepted_value = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = GRNLine
        fields = [
            "id", "product", "ordered_quantity", "supplier_claimed_quantity",
            "received_quantity", "gross_weight", "tare_weight", "net_weight", "bag_count",
            "moisture_deduction", "quality_deduction",
            "accepted_quantity", "rejected_quantity", "shortage_quantity", "excess_quantity",
            "final_payable_quantity", "unit_cost", "accepted_value",
            "batch_number", "manufacturing_date", "expiry_date",
            "warehouse_location", "remarks",
        ]

    def validate(self, data):
        accepted = data.get("accepted_quantity", Decimal("0"))
        rejected = data.get("rejected_quantity", Decimal("0"))
        received = data.get("received_quantity", Decimal("0"))
        if accepted + rejected > received + Decimal("0.001"):
            raise serializers.ValidationError(
                "Accepted + rejected quantity cannot exceed received quantity."
            )
        if accepted < 0 or rejected < 0:
            raise serializers.ValidationError("Quantities must not be negative.")
        return data


class GRNSerializer(serializers.ModelSerializer):
    lines = GRNLineSerializer(many=True, read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)

    class Meta:
        model = GRN
        fields = [
            "id", "number", "supplier", "supplier_code", "supplier_name",
            "purchase_order", "grn_date", "delivery_note_number", "vehicle_number",
            "received_by", "default_warehouse", "remarks",
            "status", "approved_by", "approved_at",
            "payable_amount", "shortage_amount", "quality_deduction_amount",
            "lines",
        ]
        read_only_fields = ["id", "number", "status", "approved_by", "approved_at"]


class QualityInspectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QualityInspection
        fields = [
            "id", "grn", "quality_decision",
            "color_ok", "smell_ok", "moisture_ok", "dust_ok",
            "foreign_particles_ok", "stones_ok", "insects_ok",
            "adulteration_suspicion", "cleanliness_ok", "grade_match_ok",
            "packaging_condition_ok", "aroma_ok", "contamination_ok",
            "deduction_amount", "deduction_quantity", "inspector_notes", "status",
        ]
        read_only_fields = ["id", "status"]


class SupplierInvoiceSerializer(serializers.ModelSerializer):
    outstanding_amount = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)

    class Meta:
        model = SupplierInvoice
        fields = [
            "id", "number", "supplier", "supplier_code", "grn",
            "invoice_date", "due_date", "amount",
            "is_tax_inclusive", "tax_amount", "withholding_amount",
            "paid_amount", "advance_adjusted_amount", "debit_note_amount", "credit_note_amount",
            "outstanding_amount", "status",
        ]
        read_only_fields = ["id", "number", "status", "paid_amount", "advance_adjusted_amount",
                            "debit_note_amount", "credit_note_amount", "outstanding_amount"]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = [
            "id", "number", "supplier", "supplier_code",
            "cash_bank_account", "payment_type", "payment_date", "amount",
            "payment_method", "reference_number", "cheque_number",
            "bank_reference", "transaction_id", "clearing_date", "bank_statement_matched",
            "amount_in_words", "po_reference",
            "prepared_by", "approved_by", "reversed_by", "reversed_at",
            "status", "reversal_of", "reason",
        ]
        read_only_fields = ["id", "number", "status", "amount_in_words",
                            "reversed_by", "reversed_at", "reversal_of"]

    def validate_amount(self, v):
        if v <= 0:
            raise serializers.ValidationError("Payment amount must be positive.")
        return v


class StockBatchSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True, allow_null=True)

    class Meta:
        model = StockBatch
        fields = [
            "id", "product", "product_code", "product_name",
            "batch_number", "batch_type", "stock_state",
            "supplier", "supplier_code",
            "source_document_type", "source_document_number",
            "warehouse", "warehouse_code",
            "quantity_on_hand", "unit_cost",
            "manufacturing_date", "packing_date", "expiry_date", "best_before_date",
            "expiry_status",
            "label_version", "design_version", "artwork_version", "batch_barcode",
            "is_blocked", "block_reason",
            "parent_batch",
        ]
        read_only_fields = ["id", "quantity_on_hand", "source_document_type", "source_document_number"]


class PackagingBOMLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackagingBOMLine
        fields = ["id", "packaging_product", "quantity_per_unit", "wastage_allowance_pct", "sequence", "remarks"]


class PackagingBOMSerializer(serializers.ModelSerializer):
    lines = PackagingBOMLineSerializer(many=True, read_only=True)

    class Meta:
        model = PackagingBOM
        fields = [
            "id", "finished_product", "powder_product",
            "powder_quantity_per_unit", "packing_wastage_pct",
            "effective_date", "version", "is_active", "approved_by", "lines",
        ]
        read_only_fields = ["id", "approved_by"]

    def validate_powder_quantity_per_unit(self, v):
        if v <= 0:
            raise serializers.ValidationError("Powder quantity per unit must be positive.")
        return v


class AdjustmentDocumentSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(source="supplier.code", read_only=True, allow_null=True)
    product_code = serializers.CharField(source="product.code", read_only=True, allow_null=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, allow_null=True)

    class Meta:
        model = AdjustmentDocument
        fields = [
            "id", "number", "adjustment_type",
            "supplier", "supplier_code",
            "product", "product_code",
            "batch", "batch_number",
            "amount", "quantity", "balance_effect",
            "reason", "status",
        ]
        read_only_fields = ["id", "number", "status"]

    def validate_amount(self, v):
        if v < 0:
            raise serializers.ValidationError("Adjustment amount must not be negative.")
        return v


class PurchaseRequirementSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = PurchaseRequirement
        fields = [
            "id", "number", "product", "product_code",
            "required_quantity", "required_by_date",
            "source", "purpose", "status", "purchase_order",
        ]
        read_only_fields = ["id", "number"]

    def validate_required_quantity(self, v):
        if v <= 0:
            raise serializers.ValidationError("Required quantity must be positive.")
        return v


class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_code = serializers.CharField(source="ingredient.code", read_only=True)

    class Meta:
        model = RecipeIngredient
        fields = ["id", "ingredient", "ingredient_code", "quantity", "percentage", "tolerance_pct", "sequence", "remarks"]


class RecipeSerializer(serializers.ModelSerializer):
    ingredients = RecipeIngredientSerializer(many=True, read_only=True)
    finished_product_code = serializers.CharField(source="finished_product.code", read_only=True)

    class Meta:
        model = Recipe
        fields = [
            "id", "code", "name", "finished_product", "finished_product_code",
            "standard_batch_size", "batch_unit", "version", "effective_date",
            "is_confidential", "status", "approved_by", "approved_at",
            "change_reason", "ingredients",
        ]
        read_only_fields = ["id", "approved_by", "approved_at"]


class LandedCostAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandedCostAllocation
        fields = ["id", "number", "grn", "cost_category", "amount", "allocation_base", "notes", "status"]
        read_only_fields = ["id", "number"]

    def validate_amount(self, v):
        if v <= 0:
            raise serializers.ValidationError("Landed cost amount must be positive.")
        return v


from .models import PhysicalStockCount, PhysicalStockCountLine, SupplierInvoiceLine


class PhysicalStockCountLineSerializer(serializers.ModelSerializer):
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    product_code = serializers.CharField(source="batch.product.code", read_only=True)

    class Meta:
        model = PhysicalStockCountLine
        fields = [
            "id", "batch", "batch_number", "product_code",
            "system_quantity", "physical_quantity",
            "variance", "variance_value", "reason", "adjustment_number",
        ]
        read_only_fields = ["id", "system_quantity", "variance", "variance_value"]


class PhysicalStockCountSerializer(serializers.ModelSerializer):
    lines = PhysicalStockCountLineSerializer(many=True, read_only=True)

    class Meta:
        model = PhysicalStockCount
        fields = [
            "id", "number", "count_date", "count_type", "warehouse",
            "freeze_stock", "status", "approved_by", "approved_at", "remarks", "lines",
        ]
        read_only_fields = ["id", "number", "approved_by", "approved_at"]


class SupplierInvoiceLineSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = SupplierInvoiceLine
        fields = [
            "id", "invoice", "grn_line", "product", "product_code",
            "description", "accepted_quantity", "unit_cost",
            "discount_amount", "tax_amount", "line_total",
            "rate_agreement", "agreed_rate_snapshot", "rate_variance_amount",
            "rate_variance_percentage", "rate_override_reason",
        ]
        read_only_fields = [
            "id", "line_total", "rate_agreement", "agreed_rate_snapshot",
            "rate_variance_amount", "rate_variance_percentage",
        ]

    def validate_accepted_quantity(self, v):
        if v <= 0:
            raise serializers.ValidationError("Accepted quantity must be positive.")
        return v


from .models import (
    CustomerDistributor,
    CustomerShippingAddress,
    DailyProductionLog,
    ScheduledTaskConfig,
    ScheduledTaskLog,
    SupplierPriceAgreement,
)


class SupplierPriceAgreementSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)

    class Meta:
        model = SupplierPriceAgreement
        fields = [
            "id", "agreement_number", "supplier", "supplier_code", "supplier_name",
            "product", "product_code", "product_name", "item_type", "agreed_rate",
            "currency", "unit", "unit_code", "minimum_quantity", "maximum_quantity",
            "effective_date", "expiry_date", "rate_type", "payment_terms_reference",
            "delivery_terms_reference", "quality_grade_reference", "tolerance_percentage",
            "status", "approved_by", "approved_at", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "agreement_number", "item_type", "status", "approved_by", "approved_at", "created_at", "updated_at",
        ]

    def validate(self, data):
        if data.get("expiry_date") and data.get("effective_date") and data["expiry_date"] < data["effective_date"]:
            raise serializers.ValidationError({"expiry_date": "Expiry date must be on or after effective date."})
        minimum = data.get("minimum_quantity")
        maximum = data.get("maximum_quantity")
        if minimum is not None and maximum is not None and maximum < minimum:
            raise serializers.ValidationError({"maximum_quantity": "Maximum quantity cannot be below minimum quantity."})
        product = data.get("product")
        if product and data.get("unit") and data["unit"] != product.base_unit:
            raise serializers.ValidationError({"unit": "Agreement unit must match the product base unit."})
        return data


class DailyProductionLogSerializer(serializers.ModelSerializer):
    supervisor_name = serializers.CharField(source="supervisor.get_full_name", read_only=True)
    production_order_number = serializers.CharField(source="production_order.number", read_only=True)
    packing_order_number = serializers.CharField(source="packing_order.number", read_only=True)
    yield_percentage = serializers.DecimalField(max_digits=9, decimal_places=2, read_only=True)
    wastage_percentage = serializers.DecimalField(max_digits=9, decimal_places=2, read_only=True)

    class Meta:
        model = DailyProductionLog
        fields = [
            "id", "log_number", "log_date", "shift", "supervisor", "supervisor_name",
            "operator", "machine", "warehouse", "production_order", "production_order_number",
            "packing_order", "packing_order_number", "raw_material_batch", "powder_batch",
            "finished_goods_batch", "raw_quantity_issued", "powder_quantity_received",
            "finished_quantity_packed", "grinding_wastage_quantity", "packing_wastage_quantity",
            "yield_percentage", "wastage_percentage", "downtime_minutes", "issue_category",
            "remarks", "status", "approved_by", "approved_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "log_number", "status", "approved_by", "approved_at", "created_at", "updated_at"]

    def validate(self, data):
        instance = self.instance
        if instance and instance.status in {DailyProductionLog.Status.APPROVED, DailyProductionLog.Status.LOCKED}:
            raise serializers.ValidationError("Approved or locked production logs cannot be edited.")
        if not data.get("production_order") and not data.get("packing_order"):
            has_manual_qty = any(data.get(field, 0) for field in (
                "raw_quantity_issued", "powder_quantity_received", "finished_quantity_packed"
            ))
            if not has_manual_qty:
                raise serializers.ValidationError("Link an order or provide at least one production quantity.")
        return data


class CustomerShippingAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerShippingAddress
        fields = [
            "id", "customer", "address_label", "recipient_contact", "phone", "address",
            "city", "province_state", "country", "is_default", "remarks",
        ]
        read_only_fields = ["id"]


class CustomerDistributorSerializer(serializers.ModelSerializer):
    shipping_addresses = CustomerShippingAddressSerializer(many=True, read_only=True)

    class Meta:
        model = CustomerDistributor
        fields = [
            "id", "code", "business_name", "contact_person", "customer_type", "phone", "email",
            "address", "city", "province_state", "country", "tax_registration_number",
            "local_tax_number", "credit_limit", "credit_days", "payment_terms",
            "preferred_price_list", "sales_channel", "status", "shipping_addresses",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

    def validate_code(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError("Customer code is required.")
        return value

    def validate_credit_limit(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Credit limit cannot be negative.")
        return value


class ScheduledTaskConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledTaskConfig
        fields = [
            "id", "job_name", "enabled", "frequency_description", "last_run", "next_run",
            "command_name", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "last_run", "created_at", "updated_at"]


class ScheduledTaskLogSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledTaskLog
        fields = [
            "id", "job_name", "job_type", "started_at", "finished_at", "status",
            "duration", "duration_seconds", "message", "error_details", "triggered_by", "created_at",
        ]
        read_only_fields = fields

    def get_duration_seconds(self, obj):
        return obj.duration.total_seconds() if obj.duration else None
