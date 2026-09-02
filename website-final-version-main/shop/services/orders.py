from django.core.validators import validate_email
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from shop.models import Order, OrderItem
from shop.services.payments import PaymentService
from shop.services.pricing import OrderPricingService
from shop.services.shipping import ShippingService


class OrderPlacementService:
    @staticmethod
    def validate_customer_data(customer_data):
        name = (customer_data.get("customer_name") or "").strip()
        phone = (customer_data.get("phone") or "").strip()
        city = (customer_data.get("city") or "").strip()
        address = (customer_data.get("address") or "").strip()
        payment_method = (customer_data.get("payment_method") or "cod").strip().lower()
        notes = (customer_data.get("notes") or "").strip()
        email = (customer_data.get("email") or "").strip()

        if len(name) < 2:
            raise ValueError("Please enter a valid full name.")
        if len(phone) < 10 or not any(ch.isdigit() for ch in phone):
            raise ValueError("Please enter a valid phone number.")
        if len(city) < 2:
            raise ValueError("Please enter a valid city.")
        if len(address) < 10:
            raise ValueError("Please enter a complete delivery address.")
        if payment_method not in {"cod", "jazzcash", "easypaisa"}:
            raise ValueError("Please choose a valid payment method.")
        if email:
            validate_email(email)

        return {
            "customer_name": name,
            "email": email,
            "phone": phone,
            "city": city,
            "address": address,
            "payment_method": payment_method,
            "notes": notes,
        }

    @classmethod
    def place_order(cls, customer_data, cart_payload):
        idempotency_key = (customer_data.get("idempotency_key") or "").strip() or None
        if idempotency_key:
            existing_order = Order.objects.filter(idempotency_key=idempotency_key).first()
            if existing_order:
                return existing_order

        validated_data = cls.validate_customer_data(customer_data)
        customer_user = customer_data.get("customer_user")
        if not getattr(customer_user, "is_authenticated", False) or getattr(customer_user, "is_staff", False):
            customer_user = None
        quote = OrderPricingService.quote(cart_payload, city=validated_data["city"])
        suspicious_order = False
        risk_note = ""
        if validated_data["payment_method"] == "cod":
            recent_cutoff = timezone.now() - timezone.timedelta(minutes=30)
            duplicate_exists = Order.objects.filter(
                payment_method="cod",
                phone=validated_data["phone"],
                address__iexact=validated_data["address"],
                created_at__gte=recent_cutoff,
            ).exists()
            if duplicate_exists:
                suspicious_order = True
                risk_note = "Duplicate COD order from same phone/address within 30 minutes."

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    customer_user=customer_user,
                    idempotency_key=idempotency_key,
                    subtotal=quote.subtotal,
                    delivery_charge=quote.delivery_charge,
                    total=quote.total,
                    suspicious_order=suspicious_order,
                    fraud_review_required=suspicious_order,
                    risk_note=risk_note,
                    **validated_data,
                )
                order_items = []
                for line in quote.lines:
                    order_items.append(
                        OrderItem(
                            order=order,
                            variant=line.variant,
                            product_id=line.variant.product_id,
                            product_name=line.variant.product.name,
                            quantity=line.quantity,
                            weight_option=line.variant.display_weight,
                            price=line.unit_price,
                            subtotal=line.subtotal,
                        )
                    )
                OrderItem.objects.bulk_create(order_items)
                from sales.services import create_sales_order_from_shop
                create_sales_order_from_shop(order)
                PaymentService.create_for_order(order, order.payment_method)
                ShippingService.create_or_update_shipment(order)
            return order
        except IntegrityError:
            if idempotency_key:
                existing_order = Order.objects.filter(idempotency_key=idempotency_key).first()
                if existing_order:
                    return existing_order
            raise
