from django.conf import settings
from django.db import models
from django.utils import timezone


class CRMAuditModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="%(class)s_crm_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="%(class)s_crm_updated")

    class Meta:
        abstract = True


class Lead(CRMAuditModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        CONVERTED = "converted", "Converted"
        LOST = "lost", "Lost"
        ON_HOLD = "on_hold", "On hold"

    number = models.CharField(max_length=40, unique=True)
    business_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="Pakistan")
    source = models.CharField(max_length=80, default="website")
    interest = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_crm_leads")
    next_follow_up_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    contact_message = models.OneToOneField("shop.ContactMessage", null=True, blank=True, on_delete=models.PROTECT, related_name="crm_lead")
    converted_customer = models.ForeignKey("erp.CustomerDistributor", null=True, blank=True, on_delete=models.PROTECT, related_name="originating_leads")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "assigned_to"]), models.Index(fields=["next_follow_up_date"])]

    def __str__(self):
        return f"{self.number} - {self.business_name}"


class Opportunity(CRMAuditModel):
    class Stage(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        SAMPLE_SENT = "sample_sent", "Sample sent"
        QUOTATION_SENT = "quotation_sent", "Quotation sent"
        NEGOTIATION = "negotiation", "Negotiation"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        ON_HOLD = "on_hold", "On hold"

    number = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.PROTECT, related_name="opportunities")
    customer = models.ForeignKey("erp.CustomerDistributor", null=True, blank=True, on_delete=models.PROTECT, related_name="opportunities")
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.NEW)
    expected_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    expected_close_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_opportunities")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["expected_close_date", "-expected_value"]
        indexes = [models.Index(fields=["stage", "assigned_to"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(lead__isnull=False) | models.Q(customer__isnull=False),
                name="crm_opportunity_has_party",
            )
        ]


class CRMInteraction(CRMAuditModel):
    class InteractionType(models.TextChoices):
        CALL = "call", "Call"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        MEETING = "meeting", "Meeting"
        SAMPLE_SENT = "sample_sent", "Sample sent"
        COMPLAINT = "complaint", "Complaint"
        SUPPORT = "support", "Support"
        OTHER = "other", "Other"

    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.CASCADE, related_name="interactions")
    customer = models.ForeignKey("erp.CustomerDistributor", null=True, blank=True, on_delete=models.CASCADE, related_name="crm_interactions")
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.CASCADE, related_name="interactions")
    interaction_type = models.CharField(max_length=20, choices=InteractionType.choices)
    interaction_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField()
    next_action = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-interaction_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(lead__isnull=False) | models.Q(customer__isnull=False) | models.Q(opportunity__isnull=False),
                name="crm_interaction_has_subject",
            )
        ]


class FollowUpTask(CRMAuditModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    title = models.CharField(max_length=200)
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    customer = models.ForeignKey("erp.CustomerDistributor", null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crm_follow_ups")
    due_date = models.DateField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["due_date", "-priority"]
        indexes = [models.Index(fields=["assigned_to", "status", "due_date"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(lead__isnull=False) | models.Q(customer__isnull=False) | models.Q(opportunity__isnull=False),
                name="crm_followup_has_subject",
            )
        ]


class Complaint(CRMAuditModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        INVESTIGATING = "investigating", "Investigating"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey("erp.CustomerDistributor", null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    support_ticket = models.OneToOneField("shop.SupportTicket", null=True, blank=True, on_delete=models.PROTECT, related_name="crm_complaint")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=20, choices=FollowUpTask.Priority.choices, default=FollowUpTask.Priority.NORMAL)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_complaints")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class CustomerSegment(CRMAuditModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    customers = models.ManyToManyField("erp.CustomerDistributor", blank=True, related_name="crm_segments")
    criteria = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
