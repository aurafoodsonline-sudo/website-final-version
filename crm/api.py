from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from erp.permissions import has_erp_permission
from erp.export import rows_to_csv
from shop.models import ContactMessage, SupportTicket

from .models import Complaint, CRMInteraction, CustomerSegment, FollowUpTask, Lead, Opportunity
from .reports import crm_report
from .services import (
    convert_contact_message_to_lead, convert_lead_to_opportunity,
    convert_opportunity_to_customer, create_complaint_from_support,
)


class CRMPermission(BasePermission):
    def has_permission(self, request, view):
        code = "crm.view" if request.method in ("GET", "HEAD", "OPTIONS") else "crm.manage"
        return has_erp_permission(request.user, code)


class CRMPagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class CRMModelSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at", "created_by", "updated_by")


def serializer_for(model, extra_read_only=()):
    meta = type(
        "Meta", (), {
            "model": model,
            "fields": "__all__",
            "read_only_fields": ("created_at", "updated_at", "created_by", "updated_by", *extra_read_only),
        }
    )
    return type(f"{model.__name__}Serializer", (CRMModelSerializer,), {"Meta": meta})


class CRMViewSet(viewsets.ModelViewSet):
    permission_classes = [CRMPermission]
    pagination_class = CRMPagePagination

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class LeadViewSet(CRMViewSet):
    queryset = Lead.objects.select_related("assigned_to", "converted_customer").all()
    serializer_class = serializer_for(Lead, ("number", "contact_message", "converted_customer"))

    @action(detail=True, methods=["post"], url_path="convert-to-opportunity")
    def convert_to_opportunity(self, request, pk=None):
        lead = self.get_object()
        try:
            expected_value = Decimal(str(request.data.get("expected_value", "0")))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"detail": "expected_value must be numeric."}, status=400)
        opportunity = convert_lead_to_opportunity(
            lead, expected_value=expected_value,
            expected_close_date=request.data.get("expected_close_date") or None,
            user=request.user,
        )
        return Response({"id": opportunity.pk, "number": opportunity.number, "stage": opportunity.stage})


class OpportunityViewSet(CRMViewSet):
    queryset = Opportunity.objects.select_related("lead", "customer", "assigned_to").all()
    serializer_class = serializer_for(Opportunity, ("number", "customer"))

    @action(detail=True, methods=["post"], url_path="convert-to-customer")
    def convert_to_customer(self, request, pk=None):
        code = str(request.data.get("customer_code", "")).strip()
        if not code:
            return Response({"detail": "customer_code is required."}, status=400)
        customer = convert_opportunity_to_customer(self.get_object(), code=code, user=request.user)
        return Response({"id": customer.pk, "code": customer.code, "business_name": customer.business_name})


class InteractionViewSet(CRMViewSet):
    queryset = CRMInteraction.objects.select_related("lead", "customer", "opportunity", "created_by").all()
    serializer_class = serializer_for(CRMInteraction)


class FollowUpViewSet(CRMViewSet):
    queryset = FollowUpTask.objects.select_related("lead", "customer", "opportunity", "assigned_to").all()
    serializer_class = serializer_for(FollowUpTask)


class ComplaintViewSet(CRMViewSet):
    queryset = Complaint.objects.select_related("customer", "support_ticket", "assigned_to").all()
    serializer_class = serializer_for(Complaint, ("number", "support_ticket"))


class CustomerSegmentViewSet(CRMViewSet):
    queryset = CustomerSegment.objects.prefetch_related("customers").all()
    serializer_class = serializer_for(CustomerSegment)


class ContactMessageConversionView(APIView):
    permission_classes = [CRMPermission]

    def post(self, request, pk):
        message = get_object_or_404(ContactMessage, pk=pk)
        lead = convert_contact_message_to_lead(message, assigned_to=request.user, user=request.user)
        return Response({"id": lead.pk, "number": lead.number, "status": lead.status})


class SupportComplaintConversionView(APIView):
    permission_classes = [CRMPermission]

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket.objects.select_related("user"), pk=pk)
        complaint = create_complaint_from_support(ticket, assigned_to=request.user, user=request.user)
        return Response({"id": complaint.pk, "number": complaint.number, "status": complaint.status})


class CRMReportView(APIView):
    permission_classes = [CRMPermission]

    def get(self, request, report_name):
        try:
            rows = crm_report(report_name, limit=min(int(request.query_params.get("limit", 500)), 2000))
        except (ValueError, TypeError):
            return Response({"detail": "Unknown report or invalid limit."}, status=400)
        if request.query_params.get("export") == "csv":
            response = HttpResponse(rows_to_csv(rows), content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="crm-{report_name}.csv"'
            return response
        return Response({"report": report_name, "count": len(rows), "rows": rows})
