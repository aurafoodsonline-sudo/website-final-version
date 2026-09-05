from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from shop.models import Order, OrderStatusLog, RefundRequest, ReturnRequest, Shipment


class OrderLifecycleService:
    VALID_TRANSITIONS = {
        Order.STATUS_PENDING: {Order.STATUS_CONFIRMED, Order.STATUS_CANCELLED},
        Order.STATUS_CONFIRMED: {Order.STATUS_PROCESSING, Order.STATUS_CANCELLED},
        Order.STATUS_PROCESSING: {Order.STATUS_SHIPPED, Order.STATUS_CANCELLED},
        Order.STATUS_SHIPPED: {Order.STATUS_DELIVERED},
        Order.STATUS_DELIVERED: set(),
        Order.STATUS_CANCELLED: set(),
    }

    @classmethod
    def transition_order(cls, order, new_status, actor=None, note=""):
        if new_status not in {choice[0] for choice in Order.STATUS_CHOICES}:
            raise ValidationError("Invalid order status.")
        if new_status == order.status:
            return order
        if new_status not in cls.VALID_TRANSITIONS.get(order.status, set()):
            raise ValidationError("This order status transition is not allowed.")

        with transaction.atomic():
            locked_order = Order.objects.select_for_update().get(id=order.id)
            old_status = locked_order.status
            if new_status not in cls.VALID_TRANSITIONS.get(old_status, set()):
                raise ValidationError("This order status transition is not allowed.")
            if new_status == Order.STATUS_SHIPPED:
                from sales.services import dispatch_stock_for_order
                shipment = getattr(locked_order, "shipment", None)
                dispatch_stock_for_order(
                    locked_order, user=actor,
                    carrier=getattr(shipment, "courier_name", ""),
                    tracking_number=getattr(shipment, "tracking_number", ""),
                )
            locked_order.status = new_status
            locked_order.save(update_fields=["status"])
            shipment = getattr(locked_order, "shipment", None)
            if shipment and new_status == Order.STATUS_SHIPPED:
                shipment.status = Shipment.STATUS_SHIPPED
                shipment.shipped_at = shipment.shipped_at or timezone.now()
                shipment.save(update_fields=["status", "shipped_at", "updated_at"])
            if new_status == Order.STATUS_DELIVERED:
                from shop.services.payments import PaymentService
                PaymentService.capture_cod_on_delivery(locked_order, actor=actor)
                if shipment:
                    shipment.status = Shipment.STATUS_DELIVERED
                    shipment.delivered_at = shipment.delivered_at or timezone.now()
                    shipment.save(update_fields=["status", "delivered_at", "updated_at"])
            elif new_status == Order.STATUS_CANCELLED and shipment:
                shipment.status = Shipment.STATUS_FAILED
                shipment.failed_reason = note or "Order cancelled before dispatch."
                shipment.save(update_fields=["status", "failed_reason", "updated_at"])
            OrderStatusLog.objects.create(
                order=locked_order,
                old_status=old_status,
                new_status=new_status,
                changed_by=actor if getattr(actor, "is_staff", False) else None,
                note=note,
            )
            from sales.services import sync_delivery_status
            sync_delivery_status(locked_order, new_status, user=actor, note=note)
            return locked_order

    @classmethod
    def cancel_order(cls, order, actor=None, note=""):
        if order.status == Order.STATUS_DELIVERED:
            raise ValidationError("Delivered orders must use the return workflow.")
        cancelled_order = cls.transition_order(order, Order.STATUS_CANCELLED, actor=actor, note=note)
        from sales.services import release_stock_reservation
        release_stock_reservation(cancelled_order, user=actor)
        return cancelled_order

    @staticmethod
    @transaction.atomic
    def request_return(order, reason, customer=None):
        if order.status != Order.STATUS_DELIVERED:
            raise ValidationError("Only delivered orders can enter the return workflow.")
        if customer is not None and order.customer_user_id != getattr(customer, "pk", None):
            raise ValidationError("This order does not belong to the requesting customer.")
        if order.return_requests.exists():
            raise ValidationError("A return request already exists for this order.")
        return ReturnRequest.objects.create(order=order, reason=(reason or "").strip())

    @staticmethod
    @transaction.atomic
    def approve_return(return_request, actor=None):
        return_request.status = ReturnRequest.STATUS_APPROVED
        return_request.resolved_at = timezone.now()
        return_request.save(update_fields=["status", "resolved_at"])
        from sales.services import create_return_from_shop
        create_return_from_shop(return_request, user=actor)
        return return_request

    @staticmethod
    @transaction.atomic
    def request_refund(order, amount, reason, actor=None):
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= 0 or amount > order.total:
            raise ValidationError("Refund amount cannot exceed the order total.")
        if order.status not in {Order.STATUS_DELIVERED, Order.STATUS_CANCELLED}:
            raise ValidationError("Refunds can be requested only for delivered or paid cancelled orders.")
        if actor is not None and getattr(actor, "is_authenticated", False) and not getattr(actor, "is_staff", False):
            if order.customer_user_id != actor.pk:
                raise ValidationError("This order does not belong to the requesting customer.")
        if order.refund_requests.filter(status__in=[RefundRequest.STATUS_REQUESTED, RefundRequest.STATUS_APPROVED]).exists():
            raise ValidationError("A refund request is already pending for this order.")
        payment = order.payment_transactions.filter(status="verified", amount=amount).order_by("pk").first()
        if not payment:
            raise ValidationError("A matching verified payment is required before requesting a refund.")
        return RefundRequest.objects.create(
            order=order, payment_transaction=payment, amount=amount, reason=(reason or "").strip()
        )

    @staticmethod
    @transaction.atomic
    def approve_refund(refund_request, actor=None):
        refund_request = RefundRequest.objects.select_for_update().select_related(
            "order", "payment_transaction"
        ).get(pk=refund_request.pk)
        if refund_request.status == RefundRequest.STATUS_PROCESSED:
            return refund_request
        if refund_request.status != RefundRequest.STATUS_REQUESTED:
            raise ValidationError("Only a requested refund can be processed.")
        if not refund_request.payment_transaction_id:
            raise ValidationError("A verified payment transaction is required for this refund.")
        from sales.services import post_refund
        refund = post_refund(refund_request, user=actor)
        from shop.services.payments import PaymentService
        PaymentService.refund(
            refund_request.payment_transaction, actor=actor,
            amount=refund.amount, note=refund_request.reason,
        )
        refund_request.status = RefundRequest.STATUS_PROCESSED
        refund_request.resolved_at = timezone.now()
        refund_request.save(update_fields=["status", "resolved_at"])
        return refund_request
