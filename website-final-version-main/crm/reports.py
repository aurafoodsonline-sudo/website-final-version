from django.db.models import Count, Sum
from django.utils import timezone

from .models import CRMInteraction, Complaint, FollowUpTask, Lead, Opportunity


def crm_report(report_name, limit=500):
    limit = max(1, min(int(limit), 2000))
    if report_name == "leads":
        return list(Lead.objects.values("number", "business_name", "source", "status", "assigned_to__username", "next_follow_up_date")[:limit])
    if report_name == "opportunity-pipeline":
        return list(Opportunity.objects.values("stage").annotate(count=Count("id"), expected_value=Sum("expected_value"))[:limit])
    if report_name == "follow-up-due":
        return list(FollowUpTask.objects.filter(due_date__lte=timezone.localdate()).exclude(status__in=["done", "cancelled"]).values("title", "assigned_to__username", "due_date", "priority", "status")[:limit])
    if report_name == "interactions":
        return list(CRMInteraction.objects.values("interaction_at", "interaction_type", "lead__number", "customer__code", "opportunity__number", "created_by__username")[:limit])
    if report_name == "complaints":
        return list(Complaint.objects.values("number", "subject", "status", "priority", "assigned_to__username", "created_at")[:limit])
    if report_name == "conversion":
        return list(Lead.objects.values("source").annotate(total=Count("id"), converted=Count("id", filter=models_q_converted()))[:limit])
    if report_name == "salesperson-activity":
        return list(CRMInteraction.objects.values("created_by__username").annotate(interactions=Count("id"))[:limit])
    raise ValueError("Unknown CRM report.")


def models_q_converted():
    from django.db.models import Q
    return Q(status=Lead.Status.CONVERTED)
