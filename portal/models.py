import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from .fields import EncryptedTextField

def private_path(instance, filename):
    return f'{timezone.now():%Y/%m}/{uuid.uuid4().hex}.bin'

class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    erp_id = models.UUIDField(unique=True, null=True, blank=True)
    account_number = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    identity_version = models.CharField(max_length=64, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Company administrator'
        REQUESTER = 'requester', 'Sales / requester'
        ACCOUNTANT = 'accountant', 'Company accountant'
        CEO = 'ceo', 'Sama CEO'
        SALES = 'sales', 'Sama sales'
        FINANCE = 'finance', 'Sama accounting'
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT, related_name='users')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.REQUESTER)
    is_primary = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    phone = models.CharField(max_length=30, blank=True)
    passport_number = EncryptedTextField(blank=True, max_length=50)
    passport_expiry = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    email_notifications = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(Lower('username'), name='unique_login_case_insensitive'),
            models.UniqueConstraint(fields=['company'], condition=models.Q(is_primary=True), name='one_primary_per_company')]

    @property
    def label(self):
        return self.get_full_name().strip() or self.username

    @property
    def is_sama(self):
        return self.role in (self.Role.CEO, self.Role.SALES, self.Role.FINANCE) and self.company_id is None

    @property
    def profile_complete(self):
        if self.is_sama:
            return bool(self.first_name and self.last_name and self.email)
        from django.conf import settings
        completed = all([self.first_name, self.last_name, self.email, self.phone, self.passport_number, self.passport_expiry, self.nationality])
        completed = completed and self.passport_expiry > timezone.localdate()
        if settings.REQUIRE_PASSPORT_COPY:
            completed = completed and self.passport_files.exists()
        return bool(completed)

class Draft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    messages = models.JSONField(default=list)
    summary = models.JSONField(default=dict)
    ai_busy_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class TravelRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROGRESS = 'in_progress', 'In progress'
        CLIENT = 'awaiting_client', 'Awaiting client'
        QUOTED = 'quote_sent', 'Quote sent'
        APPROVAL = 'awaiting_approval', 'Awaiting approval'
        APPROVED = 'approved', 'Approved'
        BOOKING = 'booking', 'Booking in progress'
        CONFIRMED = 'confirmed', 'Confirmed'
        CLOSED = 'closed', 'Closed'
        REJECTED = 'rejected', 'Quote rejected'
        CANCELLED = 'cancelled', 'Cancelled'
        EXPIRED = 'expired', 'Quote expired'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=24, unique=True)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name='requests')
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='assigned_requests')
    source_draft = models.OneToOneField(Draft, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=160)
    origin = models.CharField(max_length=120)
    destination = models.CharField(max_length=120)
    departure = models.DateField()
    return_date = models.DateField(null=True, blank=True)
    travellers = models.PositiveSmallIntegerField(default=1)
    budget = models.CharField(max_length=120, blank=True)
    requirements = models.TextField(blank=True)
    traveller_details = EncryptedTextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    booking_reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['company', 'status']), models.Index(fields=['assignee', 'status'])]

class Message(models.Model):
    request = models.ForeignKey(TravelRequest, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[('human','Message'),('system','Update'),('ai','Assistant')], default='human')
    body = models.TextField()
    internal = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at', 'id']

class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(TravelRequest, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name='attachments')
    passport_owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='passport_files')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    file = models.FileField(upload_to=private_path)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=80)
    size = models.PositiveIntegerField()
    internal = models.BooleanField(default=False)
    sensitive = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Quote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(TravelRequest, on_delete=models.CASCADE, related_name='quotes')
    version = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    details = models.TextField()
    inclusions = models.TextField(blank=True)
    exclusions = models.TextField(blank=True)
    payment_terms = models.TextField()
    valid_until = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval_required_count = models.PositiveIntegerField(default=0)
    superseded = models.BooleanField(default=False)
    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['request','version'], name='unique_quote_version')]
    @property
    def reference(self):
        return f'{self.request.reference}-Q{self.version}'
    @property
    def expired(self):
        return self.valid_until <= timezone.now()
    @property
    def all_approved(self):
        decisions = self.approvals.all()
        return self.approval_required_count > 0 and decisions.count() == self.approval_required_count and not decisions.exclude(decision='approved').exists()

class Approval(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='approvals')
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name_snapshot = models.CharField(max_length=200)
    decision = models.CharField(max_length=12, choices=[('pending','Pending'),('approved','Approved'),('rejected','Rejected')], default='pending')
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['quote', 'user'], name='one_decision_per_quote_user')]

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    request = models.ForeignKey(TravelRequest, null=True, blank=True, on_delete=models.CASCADE)
    text = models.CharField(max_length=240)
    url = models.CharField(max_length=255)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']

class Delivery(models.Model):
    notification = models.ForeignKey(Notification, null=True, blank=True, on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=[('email','Email'),('push','Push'),('sms','SMS')])
    recipient = models.CharField(max_length=255)
    payload = models.JSONField(default=dict)
    dedupe_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=12, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=120, blank=True)
    provider_message_id = models.CharField(max_length=80, blank=True)
    provider_status = models.CharField(max_length=24, blank=True)
    provider_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    endpoint = models.URLField(max_length=2048, unique=True)
    subscription = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class AIBudget(models.Model):
    month = models.CharField(max_length=7, primary_key=True)
    reserved = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0'))
    spent = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0'))

class AICall(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    budget = models.ForeignKey(AIBudget, on_delete=models.PROTECT)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    reservation = models.DecimalField(max_digits=8, decimal_places=6)
    charged = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=12, default='reserved')
    created_at = models.DateTimeField(auto_now_add=True)

class Audit(models.Model):
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MailReview(models.Model):
    uid = models.CharField(max_length=100, unique=True)
    sender = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    body = EncryptedTextField(blank=True)
    reason = models.CharField(max_length=200)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class WorkerState(models.Model):
    name = models.CharField(max_length=80, primary_key=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

class RateLimit(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    expires = models.DateTimeField()
