from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from crm.models import Complaint, FollowUpTask, Lead, Opportunity
from crm.services import convert_contact_message_to_lead, create_complaint_from_support
from erp.permissions import has_erp_permission
from shop.models import ContactMessage, PaymentTransaction, RefundRequest, ReturnRequest, SupportTicket
from shop.services.lifecycle import OrderLifecycleService
from shop.services.payments import PaymentService

from .models import CustomerLedgerEntry, SalesInvoice, SalesOrder, SalesStockReservation
from .models import SalesReturn
from .reports import invoices_with_balance
from .services import (
    approve_return_stock_after_qa, reallocate_stock_reservation, reject_return_after_qa,
)


def _require(request, *permissions):
    if not request.user.is_authenticated or not all(has_erp_permission(request.user, code) for code in permissions):
        raise PermissionDenied("This commerce action requires: " + ", ".join(permissions))


def commerce_console(request):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    can_sales = has_erp_permission(request.user, "sales.view")
    can_crm = has_erp_permission(request.user, "crm.view")
    if not (can_sales or can_crm):
        raise PermissionDenied("Commerce operations access is required.")
    today = timezone.localdate()
    context = {"can_sales": can_sales, "can_crm": can_crm}
    if can_sales:
        context.update({
            "orders": SalesOrder.objects.select_related("customer", "shop_order").order_by("-created_at")[:20],
            "invoices": invoices_with_balance().select_related("customer").order_by("-created_at")[:20],
            "order_count": SalesOrder.objects.exclude(status=SalesOrder.Status.CANCELLED).count(),
            "receivable": CustomerLedgerEntry.objects.aggregate(total=Sum("amount"))["total"] or 0,
            "overdue_count": SalesInvoice.objects.filter(due_date__lt=today).exclude(status__in=[SalesInvoice.Status.PAID, SalesInvoice.Status.CANCELLED]).count(),
            "reserved_count": SalesStockReservation.objects.filter(status=SalesStockReservation.Status.ACTIVE).count(),
            "pending_payments": PaymentTransaction.objects.filter(
                status=PaymentTransaction.STATUS_AWAITING_VERIFICATION,
                order__sales_record__isnull=False,
            ).select_related("order")[:20],
            "return_requests": ReturnRequest.objects.filter(status=ReturnRequest.STATUS_REQUESTED).select_related("order")[:20],
            "quarantined_returns": SalesReturn.objects.filter(
                status=SalesReturn.Status.QUARANTINED
            ).select_related("order", "shop_request")[:20],
            "refund_requests": RefundRequest.objects.filter(status=RefundRequest.STATUS_REQUESTED).select_related("order")[:20],
            "can_sales_manage": has_erp_permission(request.user, "sales.manage"),
            "can_sales_dispatch": has_erp_permission(request.user, "sales.dispatch"),
            "can_sales_payment": has_erp_permission(request.user, "sales.payment"),
            "can_sales_return": has_erp_permission(request.user, "sales.return"),
            "can_quality_inspect": has_erp_permission(request.user, "quality.inspect"),
        })
    if can_crm:
        context.update({
            "leads": Lead.objects.select_related("assigned_to").order_by("-created_at")[:12],
            "pipeline": Opportunity.objects.exclude(stage__in=[Opportunity.Stage.WON, Opportunity.Stage.LOST]).aggregate(count=Count("id"), value=Sum("expected_value")),
            "due_followups": FollowUpTask.objects.filter(due_date__lte=today).exclude(status__in=[FollowUpTask.Status.DONE, FollowUpTask.Status.CANCELLED]).select_related("assigned_to")[:12],
            "open_complaints": Complaint.objects.exclude(status=Complaint.Status.CLOSED).count(),
            "contact_sources": ContactMessage.objects.filter(crm_lead__isnull=True).order_by("-created_at")[:10],
            "support_sources": SupportTicket.objects.filter(crm_complaint__isnull=True).order_by("-created_at")[:10],
            "can_crm_manage": has_erp_permission(request.user, "crm.manage"),
        })
    return render(request, "sales/commerce_console.html", context)


@require_POST
def commerce_order_transition(request, pk):
    sales_order = get_object_or_404(SalesOrder.objects.select_related("shop_order"), pk=pk)
    new_status = request.POST.get("status", "")
    permission = "sales.dispatch" if new_status in {"shipped", "delivered"} else "sales.manage"
    _require(request, permission)
    try:
        if new_status == "cancelled":
            OrderLifecycleService.cancel_order(sales_order.shop_order, actor=request.user, note="Commerce console")
        else:
            OrderLifecycleService.transition_order(sales_order.shop_order, new_status, actor=request.user, note="Commerce console")
        messages.success(request, f"Order {sales_order.number} moved to {new_status}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_order_reallocate(request, pk):
    _require(request, "sales.dispatch")
    sales_order = get_object_or_404(SalesOrder.objects.select_related("shop_order"), pk=pk)
    try:
        reallocate_stock_reservation(sales_order.shop_order, user=request.user)
        messages.success(request, f"FEFO stock reallocated for {sales_order.number}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_verify_payment(request, pk):
    _require(request, "sales.payment")
    payment = get_object_or_404(PaymentTransaction.objects.select_related("order"), pk=pk)
    try:
        PaymentService.verify_manual_payment(
            payment, request.user, amount=request.POST.get("amount") or payment.amount,
            provider_reference=request.POST.get("provider_reference", "").strip(),
        )
        messages.success(request, f"Payment for {payment.order.reference} verified and posted.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_return_action(request, pk):
    _require(request, "sales.return")
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    try:
        OrderLifecycleService.approve_return(return_request, actor=request.user)
        messages.success(request, f"Return for {return_request.order.reference} quarantined for QA.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_return_qa_accept(request, pk):
    _require(request, "sales.return", "quality.inspect")
    sales_return = get_object_or_404(SalesReturn, pk=pk)
    try:
        approve_return_stock_after_qa(sales_return, user=request.user)
        messages.success(request, f"Return {sales_return.number} passed QA and stock was posted.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_return_qa_reject(request, pk):
    _require(request, "sales.return", "quality.inspect")
    sales_return = get_object_or_404(SalesReturn, pk=pk)
    try:
        reject_return_after_qa(
            sales_return, user=request.user,
            reason=request.POST.get("reason", "").strip() or "Rejected during QA inspection.",
        )
        messages.success(request, f"Return {sales_return.number} rejected and customer credit reversed.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_refund_action(request, pk):
    _require(request, "sales.return", "sales.payment")
    refund_request = get_object_or_404(RefundRequest, pk=pk)
    try:
        OrderLifecycleService.approve_refund(refund_request, actor=request.user)
        messages.success(request, f"Refund for {refund_request.order.reference} posted.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("/commerce-admin/")


@require_POST
def commerce_contact_convert(request, pk):
    _require(request, "crm.manage")
    source = get_object_or_404(ContactMessage, pk=pk)
    lead = convert_contact_message_to_lead(source, assigned_to=request.user, user=request.user)
    messages.success(request, f"Lead {lead.number} created from website inquiry.")
    return redirect("/commerce-admin/")


@require_POST
def commerce_support_convert(request, pk):
    _require(request, "crm.manage")
    source = get_object_or_404(SupportTicket.objects.select_related("user"), pk=pk)
    complaint = create_complaint_from_support(source, assigned_to=request.user, user=request.user)
    messages.success(request, f"Complaint {complaint.number} created from support ticket.")
    return redirect("/commerce-admin/")
