from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from erp.export import rows_to_csv
from erp.permissions import has_erp_permission

from .models import DeliveryChallan, SalesInvoice, SalesOrder, SalesReturn
from .reports import sales_report


class SalesPermission(BasePermission):
    def has_permission(self, request, view):
        code = "sales.view" if request.method in ("GET", "HEAD", "OPTIONS") else "sales.manage"
        return has_erp_permission(request.user, code)


class SalesPagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class DynamicModelSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"


def serializer_for(model):
    return type(f"{model.__name__}Serializer", (DynamicModelSerializer,), {"Meta": type("Meta", (), {"model": model, "fields": "__all__"})})


class ReadOnlySalesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [SalesPermission]
    pagination_class = SalesPagePagination


class SalesOrderViewSet(ReadOnlySalesViewSet):
    queryset = SalesOrder.objects.select_related("customer", "shop_order").all()
    serializer_class = serializer_for(SalesOrder)


class SalesInvoiceViewSet(ReadOnlySalesViewSet):
    queryset = SalesInvoice.objects.select_related("customer", "order").all()
    serializer_class = serializer_for(SalesInvoice)


class DeliveryChallanViewSet(ReadOnlySalesViewSet):
    queryset = DeliveryChallan.objects.select_related("order").all()
    serializer_class = serializer_for(DeliveryChallan)


class SalesReturnViewSet(ReadOnlySalesViewSet):
    queryset = SalesReturn.objects.select_related("order").all()
    serializer_class = serializer_for(SalesReturn)


class SalesReportView(APIView):
    permission_classes = [SalesPermission]

    def get(self, request, report_name):
        try:
            limit = min(int(request.query_params.get("limit", 500)), 5000)
            rows = sales_report(report_name, limit=limit)
        except (ValueError, TypeError):
            return Response({"detail": "Unknown report or invalid limit."}, status=400)
        if request.query_params.get("export") == "csv":
            response = HttpResponse(rows_to_csv(rows), content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{report_name}.csv"'
            return response
        return Response({"report": report_name, "count": len(rows), "rows": rows})
