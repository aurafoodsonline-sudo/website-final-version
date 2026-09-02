from django.contrib import admin

from .models import Complaint, CRMInteraction, CustomerSegment, FollowUpTask, Lead, Opportunity


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("number", "business_name", "source", "status", "assigned_to", "next_follow_up_date")
    list_filter = ("status", "source", "assigned_to")
    search_fields = ("number", "business_name", "contact_person", "phone", "email")


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "stage", "expected_value", "expected_close_date", "assigned_to")
    list_filter = ("stage", "assigned_to")


for model in (CRMInteraction, FollowUpTask, Complaint, CustomerSegment):
    admin.site.register(model)
