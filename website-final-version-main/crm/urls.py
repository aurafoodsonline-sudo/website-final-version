from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    ComplaintViewSet, ContactMessageConversionView, CRMReportView, CustomerSegmentViewSet,
    FollowUpViewSet, InteractionViewSet, LeadViewSet, OpportunityViewSet,
    SupportComplaintConversionView,
)

router = DefaultRouter()
router.register("leads", LeadViewSet)
router.register("opportunities", OpportunityViewSet)
router.register("interactions", InteractionViewSet)
router.register("follow-ups", FollowUpViewSet)
router.register("complaints", ComplaintViewSet)
router.register("segments", CustomerSegmentViewSet)
urlpatterns = router.urls + [
    path("sources/contact/<int:pk>/convert/", ContactMessageConversionView.as_view(), name="crm-contact-convert"),
    path("sources/support/<int:pk>/complaint/", SupportComplaintConversionView.as_view(), name="crm-support-convert"),
    path("reports/<slug:report_name>/", CRMReportView.as_view(), name="crm-report"),
]
