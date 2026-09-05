from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from erp.models import CustomerDistributor

from .models import CRMInteraction, Complaint, FollowUpTask, Lead, Opportunity


def _number(prefix):
    return f"{prefix}-{timezone.now():%Y%m%d}-{uuid4().hex[:10].upper()}"


@transaction.atomic
def convert_contact_message_to_lead(message, *, assigned_to=None, user=None):
    lead, _ = Lead.objects.get_or_create(
        contact_message=message,
        defaults={
            "number": _number("LEAD"), "business_name": message.name,
            "contact_person": message.name, "phone": message.phone,
            "email": message.email, "source": "website_contact",
            "interest": message.message[:200], "remarks": message.message,
            "assigned_to": assigned_to, "created_by": user,
        },
    )
    return lead


@transaction.atomic
def convert_lead_to_opportunity(lead, *, expected_value=0, expected_close_date=None, user=None):
    existing = lead.opportunities.exclude(stage=Opportunity.Stage.LOST).order_by("created_at").first()
    if existing:
        return existing
    opportunity = Opportunity.objects.create(
        number=_number("OPP"), name=f"{lead.business_name} opportunity", lead=lead,
        expected_value=expected_value, expected_close_date=expected_close_date,
        assigned_to=lead.assigned_to, created_by=user,
    )
    lead.status = Lead.Status.QUALIFIED
    lead.updated_by = user
    lead.save(update_fields=["status", "updated_by", "updated_at"])
    return opportunity


def record_interaction(*, lead=None, customer=None, opportunity=None, interaction_type, notes, next_action="", user=None):
    if not any((lead, customer, opportunity)):
        raise ValueError("An interaction must be linked to a lead, customer, or opportunity.")
    return CRMInteraction.objects.create(
        lead=lead, customer=customer, opportunity=opportunity,
        interaction_type=interaction_type, notes=notes, next_action=next_action, created_by=user,
    )


@transaction.atomic
def create_complaint_from_support(ticket, *, customer=None, assigned_to=None, user=None):
    if customer is None and ticket.user_id:
        profile = getattr(ticket.user, "sales_profile", None)
        customer = profile.customer if profile else None
    complaint, _ = Complaint.objects.get_or_create(
        support_ticket=ticket,
        defaults={
            "number": _number("CMP"), "customer": customer, "subject": ticket.subject,
            "description": ticket.message, "assigned_to": assigned_to, "created_by": user,
        },
    )
    return complaint


def create_follow_up(*, title, assigned_to, due_date, lead=None, customer=None, opportunity=None, remarks="", user=None):
    return FollowUpTask.objects.create(
        title=title, assigned_to=assigned_to, due_date=due_date, lead=lead,
        customer=customer, opportunity=opportunity, remarks=remarks, created_by=user,
    )


@transaction.atomic
def convert_opportunity_to_customer(opportunity, *, code, customer_type=CustomerDistributor.CustomerType.OTHER, user=None):
    opportunity = Opportunity.objects.select_for_update().select_related("lead").get(pk=opportunity.pk)
    lead = opportunity.lead
    if opportunity.customer_id:
        return opportunity.customer
    customer = CustomerDistributor.objects.create(
        code=code, business_name=lead.business_name if lead else opportunity.name,
        contact_person=lead.contact_person if lead else "", phone=lead.phone if lead else "",
        email=lead.email if lead else "", city=lead.city if lead else "",
        country=lead.country if lead else "Pakistan", customer_type=customer_type,
        sales_channel=CustomerDistributor.SalesChannel.WHOLESALE, created_by=user,
    )
    opportunity.customer = customer
    opportunity.stage = Opportunity.Stage.WON
    opportunity.updated_by = user
    opportunity.save(update_fields=["customer", "stage", "updated_by", "updated_at"])
    if lead:
        lead.status = Lead.Status.CONVERTED
        lead.converted_customer = customer
        lead.updated_by = user
        lead.save(update_fields=["status", "converted_customer", "updated_by", "updated_at"])
    return customer
