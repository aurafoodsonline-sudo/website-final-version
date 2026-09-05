import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from erp.models import Product
from shop.models import ContactMessage, SupportTicket

from .models import CRMInteraction, FollowUpTask, Lead
from .services import (
    convert_contact_message_to_lead, convert_lead_to_opportunity,
    convert_opportunity_to_customer, create_follow_up, record_interaction,
)


class CRMWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sales", password="not-a-real-secret")
        self.message = ContactMessage.objects.create(
            name="A Buyer", email="buyer@example.com", phone="03001234567",
            message="Please contact us about wholesale packs.",
        )

    def grant(self, user, *codenames):
        content_type = ContentType.objects.get_for_model(Product)
        for codename in codenames:
            permission, _ = Permission.objects.get_or_create(
                codename=codename, content_type=content_type,
                defaults={"name": f"ERP {codename}"},
            )
            user.user_permissions.add(permission)

    def test_contact_converts_once_and_enters_pipeline(self):
        lead = convert_contact_message_to_lead(self.message, assigned_to=self.user, user=self.user)
        self.assertEqual(convert_contact_message_to_lead(self.message).pk, lead.pk)
        opportunity = convert_lead_to_opportunity(lead, expected_value=100000, user=self.user)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.QUALIFIED)
        self.assertEqual(opportunity.assigned_to, self.user)

    def test_interaction_and_followup_require_operational_records(self):
        lead = convert_contact_message_to_lead(self.message, assigned_to=self.user)
        interaction = record_interaction(
            lead=lead, interaction_type=CRMInteraction.InteractionType.CALL,
            notes="Qualified pack sizes", next_action="Send quotation", user=self.user,
        )
        task = create_follow_up(
            title="Send quotation", assigned_to=self.user,
            due_date=timezone.localdate(), lead=lead, user=self.user,
        )
        self.assertEqual(interaction.lead, lead)
        self.assertEqual(task.status, FollowUpTask.Status.OPEN)

    def test_won_opportunity_creates_customer_master_link(self):
        lead = convert_contact_message_to_lead(self.message, assigned_to=self.user)
        opportunity = convert_lead_to_opportunity(lead, expected_value=100000)
        customer = convert_opportunity_to_customer(opportunity, code="CRM-001", user=self.user)
        lead.refresh_from_db()
        opportunity.refresh_from_db()
        self.assertEqual(lead.converted_customer, customer)
        self.assertEqual(opportunity.stage, "won")

    def test_inquiry_to_customer_pipeline_includes_follow_up(self):
        lead = convert_contact_message_to_lead(self.message, assigned_to=self.user, user=self.user)
        opportunity = convert_lead_to_opportunity(lead, expected_value=Decimal("150000.00"), user=self.user)
        follow_up = create_follow_up(
            title="Confirm wholesale terms", assigned_to=self.user,
            due_date=timezone.localdate(), opportunity=opportunity, user=self.user,
        )
        customer = convert_opportunity_to_customer(opportunity, code="CRM-E2E-001", user=self.user)

        lead.refresh_from_db()
        opportunity.refresh_from_db()
        self.assertEqual(follow_up.opportunity, opportunity)
        self.assertEqual(lead.converted_customer, customer)
        self.assertEqual(opportunity.stage, opportunity.Stage.WON)

    def test_crm_api_denies_anonymous_and_read_only_staff_cannot_mutate(self):
        self.assertIn(self.client.get("/api/crm/leads/").status_code, (401, 403))
        viewer = get_user_model().objects.create_user(username="crm-viewer", is_staff=True)
        self.grant(viewer, "crm.view")
        self.client.force_login(viewer)
        self.assertEqual(self.client.get("/api/crm/leads/").status_code, 200)
        denied = self.client.post(
            "/api/crm/leads/",
            data=json.dumps({"business_name": "Unauthorized lead"}),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_contact_and_support_sources_convert_through_permissioned_api(self):
        manager = get_user_model().objects.create_user(username="crm-manager", is_staff=True)
        self.grant(manager, "crm.view", "crm.manage")
        self.client.force_login(manager)
        lead_response = self.client.post(f"/api/crm/sources/contact/{self.message.pk}/convert/")
        self.assertEqual(lead_response.status_code, 200)
        lead = Lead.objects.get(pk=lead_response.json()["id"])
        opportunity_response = self.client.post(
            f"/api/crm/leads/{lead.pk}/convert-to-opportunity/",
            data=json.dumps({"expected_value": "125000.00"}),
            content_type="application/json",
        )
        self.assertEqual(opportunity_response.status_code, 200)
        ticket = SupportTicket.objects.create(
            name="Buyer", email="buyer@example.com", phone="03001234567",
            subject="Damaged delivery", message="The sealed delivery arrived damaged.",
        )
        complaint_response = self.client.post(f"/api/crm/sources/support/{ticket.pk}/complaint/")
        self.assertEqual(complaint_response.status_code, 200)
        self.assertEqual(ticket.crm_complaint.pk, complaint_response.json()["id"])

    def test_database_constraints_reject_orphan_operational_records(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CRMInteraction.objects.create(
                interaction_type=CRMInteraction.InteractionType.CALL,
                notes="No subject must be rejected",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            FollowUpTask.objects.create(
                title="Orphan task", assigned_to=self.user, due_date=timezone.localdate()
            )
