from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from shop.models import DeliveryZone, ProductVariant, Setting
from sales.models import CatalogVariantMapping
from sales.services import finished_sku_availability_map


TWOPLACES = Decimal("0.01")


class CartQuoteError(ValueError):
    def __init__(self, message, code="invalid_cart"):
        super().__init__(message)
        self.message = message
        self.code = code


def parse_decimal(value, default="0.00"):
    try:
        return Decimal(str(value)).quantize(TWOPLACES)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(TWOPLACES)


def parse_weight_to_variant(weight_label):
    raw = str(weight_label or "").strip().lower()
    if not raw:
        return None, None

    if raw.endswith("kg"):
        unit = ProductVariant.UNIT_KILOGRAMS
        amount = raw[:-2]
    elif raw.endswith("g"):
        unit = ProductVariant.UNIT_GRAMS
        amount = raw[:-1]
    else:
        return None, None

    try:
        return Decimal(amount), unit
    except (InvalidOperation, TypeError, ValueError):
        return None, None


def normalize_cart_lines(cart_payload):
    if not isinstance(cart_payload, list):
        raise CartQuoteError("Your cart could not be read. Please refresh and try again.")

    normalized = []
    for raw_item in cart_payload:
        if not isinstance(raw_item, dict):
            raise CartQuoteError("Your cart contains an invalid item.")

        try:
            qty = int(raw_item.get("qty", 0))
        except (TypeError, ValueError):
            raise CartQuoteError("Please use a valid quantity for each item.", "invalid_quantity")
        if qty <= 0:
            raise CartQuoteError("Please use a quantity of at least 1.", "invalid_quantity")

        variant_id = raw_item.get("variant_id") or raw_item.get("variantId")
        if variant_id:
            try:
                normalized.append({"variant_id": int(variant_id), "qty": qty})
                continue
            except (TypeError, ValueError):
                raise CartQuoteError("One of the selected items is no longer available.", "invalid_variant")

        product_id = raw_item.get("product_id") or raw_item.get("id")
        weight_label = raw_item.get("weight")
        if not product_id:
            raise CartQuoteError("One of the selected items is missing a variant.", "invalid_variant")
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise CartQuoteError("One of the selected items is invalid.", "invalid_variant")

        weight_value, weight_unit = parse_weight_to_variant(weight_label)
        normalized.append(
            {
                "product_id": product_id,
                "qty": qty,
                "weight_value": weight_value,
                "weight_unit": weight_unit,
            }
        )
    return normalized


@dataclass
class PricedCartLine:
    variant: ProductVariant
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


@dataclass
class CartQuote:
    lines: list
    subtotal: Decimal
    delivery_charge: Decimal
    total: Decimal


class OrderPricingService:
    @staticmethod
    def zone_for_city(city):
        fallback = None
        for zone in DeliveryZone.objects.filter(active=True):
            if not zone.city_pattern.strip():
                fallback = fallback or zone
                continue
            if zone.matches_city(city):
                return zone
        return fallback

    @staticmethod
    def get_delivery_settings():
        free_delivery_min = parse_decimal(
            Setting.objects.filter(key="free_delivery_min")
            .values_list("value", flat=True)
            .first()
            or "500"
        )
        delivery_charge = parse_decimal(
            Setting.objects.filter(key="delivery_charge")
            .values_list("value", flat=True)
            .first()
            or "150"
        )
        return free_delivery_min, delivery_charge

    @classmethod
    def _resolve_variant(cls, normalized_line):
        if normalized_line.get("variant_id"):
            variant = ProductVariant.objects.select_related("product", "erp_mapping__erp_product").filter(
                id=normalized_line["variant_id"],
            ).first()
            if not variant or not variant.product.active or not variant.active:
                raise CartQuoteError(
                    "One of the selected items is no longer available.",
                    "unavailable_variant",
                )
            return variant

        queryset = ProductVariant.objects.select_related("product", "erp_mapping__erp_product").filter(
            product_id=normalized_line["product_id"],
            active=True,
            product__active=True,
        )
        weight_value = normalized_line.get("weight_value")
        weight_unit = normalized_line.get("weight_unit")
        if weight_value is not None and weight_unit:
            queryset = queryset.filter(weight_value=weight_value, weight_unit=weight_unit)
        return queryset.order_by("sort_order", "id").first()

    @classmethod
    def _resolve_variants(cls, normalized_lines):
        variant_ids = {line["variant_id"] for line in normalized_lines if line.get("variant_id")}
        product_ids = {line["product_id"] for line in normalized_lines if line.get("product_id")}
        base = ProductVariant.objects.select_related("product", "erp_mapping__erp_product").filter(
            active=True, product__active=True,
        )
        by_id = {variant.pk: variant for variant in base.filter(pk__in=variant_ids)}
        by_product = {}
        for variant in base.filter(product_id__in=product_ids).order_by("sort_order", "id"):
            by_product.setdefault(variant.product_id, []).append(variant)

        resolved = []
        for line in normalized_lines:
            variant = by_id.get(line.get("variant_id"))
            if not line.get("variant_id"):
                candidates = by_product.get(line["product_id"], [])
                weight_value = line.get("weight_value")
                weight_unit = line.get("weight_unit")
                variant = next(
                    (
                        candidate for candidate in candidates
                        if weight_value is None
                        or (candidate.weight_value == weight_value and candidate.weight_unit == weight_unit)
                    ),
                    None,
                )
            resolved.append(variant)
        return resolved

    @classmethod
    def quote(cls, cart_payload, city=""):
        normalized_lines = normalize_cart_lines(cart_payload)
        if not normalized_lines:
            raise CartQuoteError("Your cart is empty.", "empty_cart")

        resolved = {}
        ordered_variant_ids = []
        for normalized_line, variant in zip(normalized_lines, cls._resolve_variants(normalized_lines)):
            if not variant:
                raise CartQuoteError(
                    "One of the selected items is no longer available.",
                    "unavailable_variant",
                )
            try:
                mapping = variant.erp_mapping
            except CatalogVariantMapping.DoesNotExist:
                raise CartQuoteError(
                    f"{variant.product.name} ({variant.display_weight}) is out of stock.",
                    "out_of_stock",
                )
            if not mapping.is_active or not mapping.erp_product.is_active:
                raise CartQuoteError(
                    f"{variant.product.name} ({variant.display_weight}) is unavailable.",
                    "unavailable_variant",
                )
            if variant.pk not in resolved:
                resolved[variant.pk] = {"variant": variant, "mapping": mapping, "quantity": 0}
                ordered_variant_ids.append(variant.pk)
            resolved[variant.pk]["quantity"] += normalized_line["qty"]

        availability = finished_sku_availability_map(
            [resolved[variant_id]["mapping"].erp_product_id for variant_id in ordered_variant_ids]
        )
        priced_lines = []
        subtotal = Decimal("0.00")
        for variant_id in ordered_variant_ids:
            item = resolved[variant_id]
            variant = item["variant"]
            mapping = item["mapping"]
            quantity = item["quantity"]
            available_quantity = availability.get(mapping.erp_product_id, Decimal("0.000"))
            if available_quantity < 1:
                raise CartQuoteError(
                    f"{variant.product.name} ({variant.display_weight}) is out of stock.",
                    "out_of_stock",
                )
            if Decimal(quantity) > available_quantity:
                raise CartQuoteError(
                    f"Only {available_quantity} units are available for "
                    f"{variant.product.name} ({variant.display_weight}).",
                    "insufficient_stock",
                )

            unit_price = mapping.display_price if mapping.display_price is not None else variant.price
            line_subtotal = (unit_price * quantity).quantize(TWOPLACES)
            subtotal += line_subtotal
            priced_lines.append(
                PricedCartLine(
                    variant=variant,
                    quantity=quantity,
                    unit_price=unit_price,
                    subtotal=line_subtotal,
                )
            )

        zone = cls.zone_for_city(city)
        if zone:
            delivery_charge = zone.charge_for_subtotal(subtotal).quantize(TWOPLACES)
        else:
            free_delivery_min, delivery_charge_value = cls.get_delivery_settings()
            delivery_charge = (
                Decimal("0.00") if subtotal >= free_delivery_min else delivery_charge_value
            ).quantize(TWOPLACES)
        total = (subtotal + delivery_charge).quantize(TWOPLACES)
        return CartQuote(
            lines=priced_lines,
            subtotal=subtotal.quantize(TWOPLACES),
            delivery_charge=delivery_charge,
            total=total,
        )
