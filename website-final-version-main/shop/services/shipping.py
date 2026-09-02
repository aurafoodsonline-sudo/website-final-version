from decimal import Decimal

from django.utils import timezone

from shop.models import DeliveryZone, Shipment, Setting
from shop.services.pricing import parse_decimal


def fallback_delivery_charge():
    return parse_decimal(
        Setting.objects.filter(key="delivery_charge").values_list("value", flat=True).first()
        or "150"
    )


def fallback_free_delivery_min():
    return parse_decimal(
        Setting.objects.filter(key="free_delivery_min").values_list("value", flat=True).first()
        or "500"
    )


class ShippingService:
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

    @classmethod
    def delivery_charge_for(cls, subtotal, city=""):
        amount = Decimal(str(subtotal or "0.00"))
        zone = cls.zone_for_city(city)
        if zone:
            return zone.charge_for_subtotal(amount), zone
        if amount >= fallback_free_delivery_min():
            return Decimal("0.00"), None
        return fallback_delivery_charge(), None

    @classmethod
    def create_or_update_shipment(cls, order):
        zone = cls.zone_for_city(order.city)
        min_days = zone.estimated_days_min if zone else 2
        max_days = zone.estimated_days_max if zone else 5
        today = timezone.localdate()
        shipment, _ = Shipment.objects.update_or_create(
            order=order,
            defaults={
                "zone": zone,
                "courier_name": zone.courier_hint if zone else "",
                "estimated_delivery_min": today + timezone.timedelta(days=min_days),
                "estimated_delivery_max": today + timezone.timedelta(days=max_days),
                "public_note": "Your parcel will be prepared after order confirmation.",
            },
        )
        return shipment
