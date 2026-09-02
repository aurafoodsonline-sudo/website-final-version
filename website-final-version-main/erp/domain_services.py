from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AuditEvent,
    CustomerDistributor,
    DailyProductionLog,
    Product,
    Supplier,
    SupplierPriceAgreement,
    UnitOfMeasure,
)


ZERO = Decimal("0")


def _record(event_type: str, source_type: str, source_number: str, message: str, user=None) -> None:
    AuditEvent.objects.create(
        actor=user,
        event_type=event_type,
        source_document_type=source_type,
        source_document_number=source_number,
        message=message,
    )


def supplier_agreement_item_type(product: Product) -> str:
    mapping = {
        Product.ProductType.RAW: SupplierPriceAgreement.ItemType.RAW_SPICE,
        Product.ProductType.PACKAGING: SupplierPriceAgreement.ItemType.PACKAGING_MATERIAL,
        Product.ProductType.POWDER: SupplierPriceAgreement.ItemType.POWDER_PRODUCT,
    }
    if product.product_type not in mapping:
        raise ValidationError("This product type is not supported by supplier price agreements.")
    return mapping[product.product_type]


@transaction.atomic
def create_supplier_price_agreement(*, agreement_number: str, user=None, **values) -> SupplierPriceAgreement:
    values["item_type"] = supplier_agreement_item_type(values["product"])
    agreement = SupplierPriceAgreement(
        agreement_number=agreement_number,
        created_by=user,
        updated_by=user,
        **values,
    )
    agreement.full_clean()
    agreement.save()
    _record("supplier_rate_created", "SUPPLIER_RATE", agreement.agreement_number, "Draft rate agreement created", user)
    return agreement


@transaction.atomic
def submit_supplier_price_agreement(*, agreement: SupplierPriceAgreement, user=None) -> SupplierPriceAgreement:
    agreement = SupplierPriceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != SupplierPriceAgreement.Status.DRAFT:
        raise ValidationError("Only draft rate agreements can be submitted.")
    agreement.full_clean()
    agreement.status = SupplierPriceAgreement.Status.PENDING_APPROVAL
    agreement.updated_by = user
    agreement.save(update_fields=["status", "updated_by", "updated_at"])
    _record("supplier_rate_submitted", "SUPPLIER_RATE", agreement.agreement_number, "Submitted for approval", user)
    return agreement


@transaction.atomic
def approve_supplier_price_agreement(*, agreement: SupplierPriceAgreement, user=None) -> SupplierPriceAgreement:
    agreement = SupplierPriceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != SupplierPriceAgreement.Status.PENDING_APPROVAL:
        raise ValidationError("Only pending rate agreements can be approved.")
    agreement.full_clean()
    agreement.status = SupplierPriceAgreement.Status.APPROVED
    agreement.approved_by = user
    agreement.approved_at = timezone.now()
    agreement.updated_by = user
    agreement.save(update_fields=["status", "approved_by", "approved_at", "updated_by", "updated_at"])
    _record("supplier_rate_approved", "SUPPLIER_RATE", agreement.agreement_number, "Rate agreement approved", user)
    return agreement


@transaction.atomic
def activate_supplier_price_agreement(*, agreement: SupplierPriceAgreement, user=None) -> SupplierPriceAgreement:
    agreement = SupplierPriceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != SupplierPriceAgreement.Status.APPROVED:
        raise ValidationError("Only approved rate agreements can be activated.")
    overlapping = SupplierPriceAgreement.objects.select_for_update().filter(
        supplier=agreement.supplier,
        product=agreement.product,
        unit=agreement.unit,
        status=SupplierPriceAgreement.Status.ACTIVE,
        effective_date__lte=agreement.expiry_date,
        expiry_date__gte=agreement.effective_date,
    ).exclude(pk=agreement.pk)
    overlapping.update(status=SupplierPriceAgreement.Status.SUPERSEDED, updated_by=user, updated_at=timezone.now())
    agreement.status = SupplierPriceAgreement.Status.ACTIVE
    agreement.updated_by = user
    agreement.save(update_fields=["status", "updated_by", "updated_at"])
    _record("supplier_rate_activated", "SUPPLIER_RATE", agreement.agreement_number, "Rate agreement activated", user)
    return agreement


@transaction.atomic
def cancel_supplier_price_agreement(
    *, agreement: SupplierPriceAgreement, reason: str, user=None
) -> SupplierPriceAgreement:
    reason = reason.strip()
    if not reason:
        raise ValidationError("Cancellation reason is required.")
    agreement = SupplierPriceAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status in {
        SupplierPriceAgreement.Status.EXPIRED,
        SupplierPriceAgreement.Status.SUPERSEDED,
        SupplierPriceAgreement.Status.CANCELLED,
    }:
        raise ValidationError("Expired, superseded, or cancelled agreements cannot be cancelled again.")
    agreement.status = SupplierPriceAgreement.Status.CANCELLED
    agreement.remarks = f"{agreement.remarks}\nCancellation: {reason}".strip()
    agreement.updated_by = user
    agreement.save(update_fields=["status", "remarks", "updated_by", "updated_at"])
    _record("supplier_rate_cancelled", "SUPPLIER_RATE", agreement.agreement_number, reason, user)
    return agreement


def expire_supplier_price_agreements(*, as_of=None) -> int:
    as_of = as_of or timezone.localdate()
    return SupplierPriceAgreement.objects.filter(
        status=SupplierPriceAgreement.Status.ACTIVE,
        expiry_date__lt=as_of,
    ).update(status=SupplierPriceAgreement.Status.EXPIRED, updated_at=timezone.now())


def find_applicable_supplier_price_agreement(
    *, supplier: Supplier, product: Product, unit: UnitOfMeasure, transaction_date=None, quantity=None
) -> SupplierPriceAgreement | None:
    transaction_date = transaction_date or timezone.localdate()
    query = SupplierPriceAgreement.objects.filter(
        supplier=supplier,
        product=product,
        unit=unit,
        status=SupplierPriceAgreement.Status.ACTIVE,
        effective_date__lte=transaction_date,
        expiry_date__gte=transaction_date,
    )
    if quantity is not None:
        query = query.filter(
            Q(minimum_quantity__isnull=True) | Q(minimum_quantity__lte=quantity),
            Q(maximum_quantity__isnull=True) | Q(maximum_quantity__gte=quantity),
        )
    return query.order_by("-effective_date", "-approved_at", "-pk").first()


def calculate_rate_variance(*, agreed_rate: Decimal, actual_rate: Decimal) -> dict:
    variance = actual_rate - agreed_rate
    percentage = ZERO if not agreed_rate else (variance / agreed_rate * Decimal("100")).quantize(Decimal("0.0001"))
    return {
        "variance_amount": variance.quantize(Decimal("0.0001")),
        "variance_percentage": percentage,
        "variance_flag": "unfavorable" if variance > 0 else "favorable" if variance < 0 else "neutral",
    }


def evaluate_supplier_rate(
    *, supplier: Supplier, product: Product, actual_rate: Decimal, transaction_date=None,
    quantity=None, unit=None, override_reason: str = ""
) -> dict:
    unit = unit or product.base_unit
    agreement = find_applicable_supplier_price_agreement(
        supplier=supplier,
        product=product,
        unit=unit,
        transaction_date=transaction_date,
        quantity=quantity,
    )
    if not agreement:
        return {
            "agreement": None,
            "agreed_rate": None,
            "variance_amount": ZERO,
            "variance_percentage": ZERO,
            "variance_flag": "no_agreement",
            "override_reason": override_reason.strip(),
        }
    result = calculate_rate_variance(agreed_rate=agreement.agreed_rate, actual_rate=actual_rate)
    if result["variance_percentage"] > agreement.tolerance_percentage and not override_reason.strip():
        raise ValidationError(
            f"Actual rate exceeds agreement {agreement.agreement_number} by "
            f"{result['variance_percentage']}%; an approved override reason is required."
        )
    return {
        "agreement": agreement,
        "agreed_rate": agreement.agreed_rate,
        **result,
        "override_reason": override_reason.strip(),
    }


def production_log_defaults(*, production_order=None, packing_order=None) -> dict:
    defaults = {}
    if production_order:
        defaults.update({
            "warehouse": production_order.warehouse,
            "raw_material_batch": production_order.raw_batch,
            "powder_batch": production_order.powder_batch,
            "raw_quantity_issued": production_order.issued_quantity,
            "powder_quantity_received": production_order.actual_output_quantity,
            "grinding_wastage_quantity": production_order.wastage_quantity,
        })
    if packing_order:
        defaults.update({
            "warehouse": packing_order.warehouse,
            "powder_batch": packing_order.powder_batch,
            "finished_goods_batch": packing_order.finished_batch,
            "finished_quantity_packed": packing_order.completed_units,
            "packing_wastage_quantity": packing_order.wastage_quantity,
        })
    return defaults


@transaction.atomic
def create_daily_production_log(*, log_number: str, user=None, **values) -> DailyProductionLog:
    defaults = production_log_defaults(
        production_order=values.get("production_order"),
        packing_order=values.get("packing_order"),
    )
    for key, value in defaults.items():
        values.setdefault(key, value)
    production_log = DailyProductionLog(
        log_number=log_number,
        created_by=user,
        updated_by=user,
        **values,
    )
    production_log.full_clean()
    production_log.save()
    _record("production_log_created", "PRODUCTION_LOG", production_log.log_number, "Shift log created", user)
    return production_log


@transaction.atomic
def submit_daily_production_log(*, production_log: DailyProductionLog, user=None) -> DailyProductionLog:
    production_log = DailyProductionLog.objects.select_for_update().get(pk=production_log.pk)
    if production_log.status != DailyProductionLog.Status.DRAFT:
        raise ValidationError("Only draft production logs can be submitted.")
    production_log.status = DailyProductionLog.Status.SUBMITTED
    production_log.updated_by = user
    production_log.save(update_fields=["status", "updated_by", "updated_at"])
    _record("production_log_submitted", "PRODUCTION_LOG", production_log.log_number, "Shift log submitted", user)
    return production_log


@transaction.atomic
def approve_daily_production_log(*, production_log: DailyProductionLog, user=None) -> DailyProductionLog:
    production_log = DailyProductionLog.objects.select_for_update().get(pk=production_log.pk)
    if production_log.status != DailyProductionLog.Status.SUBMITTED:
        raise ValidationError("Only submitted production logs can be approved and locked.")
    production_log.status = DailyProductionLog.Status.LOCKED
    production_log.approved_by = user
    production_log.approved_at = timezone.now()
    production_log.updated_by = user
    production_log.save(update_fields=["status", "approved_by", "approved_at", "updated_by", "updated_at"])
    _record("production_log_locked", "PRODUCTION_LOG", production_log.log_number, "Shift log approved and locked", user)
    return production_log


@transaction.atomic
def set_customer_status(*, customer: CustomerDistributor, target_status: str, user=None) -> CustomerDistributor:
    if target_status not in CustomerDistributor.Status.values:
        raise ValidationError("Invalid customer status.")
    customer = CustomerDistributor.objects.select_for_update().get(pk=customer.pk)
    if customer.status == target_status:
        return customer
    previous_status = customer.status
    customer.status = target_status
    customer.updated_by = user
    customer.save(update_fields=["status", "updated_by", "updated_at"])
    _record(
        f"customer_{target_status}",
        "CUSTOMER",
        customer.code,
        f"Customer status changed from {previous_status} to {target_status}",
        user,
    )
    return customer


def set_customer_blocked(*, customer: CustomerDistributor, blocked: bool, user=None) -> CustomerDistributor:
    return set_customer_status(
        customer=customer,
        target_status=CustomerDistributor.Status.BLOCKED if blocked else CustomerDistributor.Status.ACTIVE,
        user=user,
    )


@transaction.atomic
def create_customer_distributor(*, user=None, **values) -> CustomerDistributor:
    customer = CustomerDistributor(created_by=user, updated_by=user, **values)
    customer.full_clean()
    customer.save()
    _record("customer_created", "CUSTOMER", customer.code, "Customer/distributor created", user)
    return customer
