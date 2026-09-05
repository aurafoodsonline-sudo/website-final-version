from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from .models import UnitConversion, UnitOfMeasure


def convert_quantity(quantity: Decimal, *, from_unit: UnitOfMeasure, to_unit: UnitOfMeasure) -> Decimal:
    if from_unit.pk == to_unit.pk:
        return quantity
    direct = UnitConversion.objects.filter(from_unit=from_unit, to_unit=to_unit).first()
    if direct:
        return quantity * direct.factor
    inverse = UnitConversion.objects.filter(from_unit=to_unit, to_unit=from_unit).first()
    if inverse:
        return quantity / inverse.factor
    raise ValidationError(f"No unit conversion is configured from {from_unit.code} to {to_unit.code}.")
