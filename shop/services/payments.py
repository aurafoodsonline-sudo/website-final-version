from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from shop.models import AdminActivityLog, Order, PaymentTransaction
from erp.permissions import has_erp_permission


class PaymentService:
    MANUAL_PROVIDERS = {
        PaymentTransaction.PROVIDER_JAZZCASH,
        PaymentTransaction.PROVIDER_EASYPAISA,
        PaymentTransaction.PROVIDER_BANK_TRANSFER,
        PaymentTransaction.PROVIDER_MANUAL,
    }
    ALLOWED_PROVIDERS = MANUAL_PROVIDERS | {PaymentTransaction.PROVIDER_COD}

    @classmethod
    def create_for_order(cls, order, provider):
        provider = (provider or PaymentTransaction.PROVIDER_COD).strip().lower()
        if provider not in cls.ALLOWED_PROVIDERS:
            raise ValidationError("Invalid payment provider.")

        status = (
            PaymentTransaction.STATUS_PENDING
            if provider == PaymentTransaction.PROVIDER_COD
            else PaymentTransaction.STATUS_AWAITING_VERIFICATION
        )
        order_payment_status = (
            Order.PAYMENT_UNPAID
            if provider == PaymentTransaction.PROVIDER_COD
            else Order.PAYMENT_AWAITING_VERIFICATION
        )
        transaction = PaymentTransaction.objects.create(
            order=order,
            provider=provider,
            status=status,
            amount=order.total,
        )
        if order.payment_status != order_payment_status:
            order.payment_status = order_payment_status
            order.save(update_fields=["payment_status"])
        return transaction

    @classmethod
    def verify_manual_payment(cls, transaction_obj, actor, amount=None, provider_reference=""):
        if not has_erp_permission(actor, "sales.payment"):
            raise PermissionDenied("Customer payment verification requires sales.payment permission.")
        if transaction_obj.provider not in cls.MANUAL_PROVIDERS:
            raise ValidationError("Only manual payment providers can be verified here.")
        if transaction_obj.status != PaymentTransaction.STATUS_AWAITING_VERIFICATION:
            raise ValidationError("Only awaiting-verification transactions can be verified.")
        if amount is not None:
            try:
                amount = Decimal(str(amount)).quantize(Decimal("0.01"))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError("Payment amount is invalid.") from exc
            if amount != transaction_obj.amount:
                raise ValidationError("Payment amount does not match the order total.")

        with transaction.atomic():
            transaction_obj.status = PaymentTransaction.STATUS_VERIFIED
            transaction_obj.verified_by = actor
            transaction_obj.verified_at = timezone.now()
            if provider_reference:
                transaction_obj.provider_reference = provider_reference
            transaction_obj.save(
                update_fields=["status", "verified_by", "verified_at", "provider_reference", "updated_at"]
            )
            order = transaction_obj.order
            order.payment_status = Order.PAYMENT_PAID
            order.save(update_fields=["payment_status"])
            # Pre-merge orders may not have an integrated sales record. All new
            # checkout orders do, and must post through the customer ledger.
            if hasattr(order, "sales_record"):
                from sales.services import post_customer_payment
                post_customer_payment(transaction_obj, user=actor)
            AdminActivityLog.objects.create(
                actor=actor,
                action="payment_verified",
                model_name="PaymentTransaction",
                object_id=str(transaction_obj.id),
                object_repr=f"{transaction_obj.provider} {transaction_obj.amount}",
                severity=AdminActivityLog.SEVERITY_WARNING,
            )
        return transaction_obj

    @classmethod
    @transaction.atomic
    def capture_cod_on_delivery(cls, order, actor=None):
        transaction_obj = order.payment_transactions.select_for_update().filter(
            provider=PaymentTransaction.PROVIDER_COD,
            status=PaymentTransaction.STATUS_PENDING,
        ).first()
        if not transaction_obj:
            return None
        transaction_obj.status = PaymentTransaction.STATUS_VERIFIED
        transaction_obj.verified_by = actor if getattr(actor, "is_authenticated", False) else None
        transaction_obj.verified_at = timezone.now()
        transaction_obj.provider_reference = transaction_obj.provider_reference or f"COD-{order.reference}"
        transaction_obj.save(update_fields=["status", "verified_by", "verified_at", "provider_reference", "updated_at"])
        order.payment_status = Order.PAYMENT_PAID
        order.save(update_fields=["payment_status"])
        if hasattr(order, "sales_record"):
            from sales.services import post_customer_payment
            post_customer_payment(transaction_obj, user=actor)
        AdminActivityLog.objects.create(
            actor=actor if getattr(actor, "is_staff", False) else None,
            action="cod_collected_on_delivery",
            model_name="PaymentTransaction",
            object_id=str(transaction_obj.id),
            object_repr=f"COD {transaction_obj.amount}",
            severity=AdminActivityLog.SEVERITY_WARNING,
        )
        return transaction_obj

    @staticmethod
    def mark_failed(transaction_obj, actor=None, note=""):
        if not has_erp_permission(actor, "sales.payment"):
            raise PermissionDenied("Marking a payment failed requires sales.payment permission.")
        transaction_obj.status = PaymentTransaction.STATUS_FAILED
        transaction_obj.save(update_fields=["status", "updated_at"])
        order = transaction_obj.order
        order.payment_status = Order.PAYMENT_FAILED
        order.save(update_fields=["payment_status"])
        AdminActivityLog.objects.create(
            actor=actor if getattr(actor, "is_staff", False) else None,
            action="payment_failed",
            model_name="PaymentTransaction",
            object_id=str(transaction_obj.id),
            object_repr=note,
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
        return transaction_obj

    @staticmethod
    @transaction.atomic
    def refund(transaction_obj, actor=None, amount=None, note=""):
        if not has_erp_permission(actor, "sales.payment"):
            raise PermissionDenied("Payment refund requires sales.payment permission.")
        transaction_obj = PaymentTransaction.objects.select_for_update().get(pk=transaction_obj.pk)
        if transaction_obj.status == PaymentTransaction.STATUS_REFUNDED:
            return transaction_obj
        if transaction_obj.status != PaymentTransaction.STATUS_VERIFIED:
            raise ValidationError("Only a verified payment can be refunded.")
        amount = Decimal(str(amount if amount is not None else transaction_obj.amount)).quantize(Decimal("0.01"))
        if amount != transaction_obj.amount:
            raise ValidationError("Partial payment-transaction refunds are not supported by this workflow.")
        transaction_obj.status = PaymentTransaction.STATUS_REFUNDED
        transaction_obj.save(update_fields=["status", "updated_at"])
        order = transaction_obj.order
        order.payment_status = Order.PAYMENT_REFUNDED
        order.save(update_fields=["payment_status"])
        AdminActivityLog.objects.create(
            actor=actor if getattr(actor, "is_staff", False) else None,
            action="payment_refunded",
            model_name="PaymentTransaction",
            object_id=str(transaction_obj.id),
            object_repr=note,
            severity=AdminActivityLog.SEVERITY_CRITICAL,
        )
        return transaction_obj
