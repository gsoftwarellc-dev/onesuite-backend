"""
Notifications Models
Phase 7.2 Data Model Implementation with all corrections applied.
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

User = get_user_model()


# =============================================================================
# Enums
# =============================================================================

class NotificationChannel(models.TextChoices):
    EMAIL = 'EMAIL', 'Email'
    IN_APP = 'IN_APP', 'In-App'


class EmailStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Failed'
    BOUNCED = 'BOUNCED', 'Bounced'


class InboxStatus(models.TextChoices):
    UNREAD = 'UNREAD', 'Unread'
    READ = 'READ', 'Read'
    ARCHIVED = 'ARCHIVED', 'Archived'


class NotificationPriority(models.TextChoices):
    NORMAL = 'NORMAL', 'Normal'
    HIGH = 'HIGH', 'High'
    CRITICAL = 'CRITICAL', 'Critical'


class ScheduledStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSED = 'PROCESSED', 'Processed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    FAILED = 'FAILED', 'Failed'


class EventType(models.TextChoices):
    # Payment Events
    PAY_001 = 'PAY_001', 'Payment Completed'
    PAY_002 = 'PAY_002', 'Payment Failed'
    PAY_003 = 'PAY_003', 'Payment Retried'
    # Compliance Events
    COMP_001 = 'COMP_001', 'W-9 Missing'
    COMP_002 = 'COMP_002', 'W-9 Rejected'
    COMP_003 = 'COMP_003', '1099 Generated'
    COMP_004 = 'COMP_004', '1099 Ready for Filing'
    # Payout Events
    OUT_001 = 'OUT_001', 'Payout Released'
    OUT_002 = 'OUT_002', 'Payout Delayed'
    # Analytics Events
    ANLT_001 = 'ANLT_001', 'KPI Threshold Breach'
    ANLT_002 = 'ANLT_002', 'Reconciliation Discrepancy'
    # System Events
    SYS_001 = 'SYS_001', 'Aggregation Job Failed'
    SYS_002 = 'SYS_002', 'Export Ready'
    # Commission Events
    COMM_001 = 'COMM_001', 'Commission Submitted'
    COMM_002 = 'COMM_002', 'Commission Approved'
    COMM_003 = 'COMM_003', 'Commission Rejected'


# =============================================================================
# NotificationLog (Append-Only)
# =============================================================================

class NotificationLog(models.Model):
    """
    Immutable audit trail of all notification delivery attempts.
    Append-only with limited status field updates.
    """
    idempotency_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices)
    recipient = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='notification_logs'
    )
    status = models.CharField(
        max_length=10, choices=EmailStatus.choices, default=EmailStatus.PENDING
    )
    priority = models.CharField(
        max_length=10, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL
    )
    source_model = models.CharField(max_length=50, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['recipient', 'created_at'], name='idx_notif_recipient_created'),
            models.Index(fields=['event_type', 'created_at'], name='idx_notif_event_created'),
            models.Index(fields=['status', 'channel'], name='idx_notif_status_channel'),
            models.Index(fields=['status', 'next_retry_at'], name='idx_notif_retry_queue'),
            models.Index(fields=['source_model', 'source_id'], name='idx_notif_source'),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.event_type} → {self.recipient.username} ({self.status})"
    
    def save(self, *args, **kwargs):
        if self.pk is not None:
            # MUST use update_fields for any update
            if not kwargs.get('update_fields'):
                raise ValidationError("Must use update_fields for updates to NotificationLog.")
            allowed = {'status', 'retry_count', 'next_retry_at', 'error_message', 'sent_at'}
            if not set(kwargs['update_fields']).issubset(allowed):
                raise ValidationError("Only status-related fields can be updated.")
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        raise ValidationError("NotificationLog records cannot be deleted.")
    
    def mark_sent(self):
        """Mark notification as sent."""
        self.status = EmailStatus.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])
    
    def mark_failed(self, error: str):
        """Mark notification as failed with error."""
        self.status = EmailStatus.FAILED
        self.error_message = error
        self.save(update_fields=['status', 'error_message'])
    
    def schedule_retry(self, delay_minutes: int = 5):
        """Schedule a retry."""
        self.status = EmailStatus.PENDING
        self.retry_count += 1
        self.next_retry_at = timezone.now() + timezone.timedelta(minutes=delay_minutes)
        self.save(update_fields=['status', 'retry_count', 'next_retry_at'])


# =============================================================================
# NotificationInbox (In-App)
# =============================================================================

class NotificationInbox(models.Model):
    """
    In-app notifications for user inbox display.
    OneToOne with NotificationLog for IN_APP channel entries.
    """
    notification_log = models.OneToOneField(
        NotificationLog, on_delete=models.PROTECT, related_name='inbox_entry'
    )
    recipient = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='notification_inbox'
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(
        max_length=10, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL
    )
    status = models.CharField(
        max_length=10, choices=InboxStatus.choices, default=InboxStatus.UNREAD
    )
    action_url = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['recipient', 'status'], name='idx_inbox_recipient_status'),
            models.Index(fields=['recipient', 'created_at'], name='idx_inbox_recipient_created'),
        ]
        ordering = ['-created_at']
        verbose_name_plural = 'Notification Inbox Items'
    
    def __str__(self):
        return f"{self.title} ({self.status})"
    
    def save(self, *args, **kwargs):
        if self.pk is not None:
            allowed = {'status', 'read_at', 'archived_at'}
            if kwargs.get('update_fields') and not set(kwargs['update_fields']).issubset(allowed):
                raise ValidationError("Only status fields can be updated.")
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        raise ValidationError("Inbox items cannot be deleted.")
    
    def mark_read(self):
        """Mark as read (idempotent)."""
        if self.status != InboxStatus.READ:
            self.status = InboxStatus.READ
            self.read_at = timezone.now()
            self.save(update_fields=['status', 'read_at'])
    
    def mark_archived(self):
        """Mark as archived (idempotent)."""
        if self.status != InboxStatus.ARCHIVED:
            self.status = InboxStatus.ARCHIVED
            self.archived_at = timezone.now()
            self.save(update_fields=['status', 'archived_at'])


# =============================================================================
# ScheduledNotification
# =============================================================================

class ScheduledNotification(models.Model):
    """
    Pending notifications scheduled for future delivery.
    """
    idempotency_key = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    recipient = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='scheduled_notifications'
    )
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices)
    scheduled_for = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=ScheduledStatus.choices, default=ScheduledStatus.PENDING
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'scheduled_for'], name='idx_scheduled_queue'),
            models.Index(fields=['recipient', 'event_type'], name='idx_scheduled_recip_event'),
        ]
        ordering = ['scheduled_for']
    
    def __str__(self):
        return f"{self.event_type} → {self.recipient.username} @ {self.scheduled_for}"
    
    def cancel(self):
        """Cancel scheduled notification (idempotent)."""
        if self.status == ScheduledStatus.PROCESSED:
            raise ValidationError("Cannot cancel already processed notification.")
        if self.status != ScheduledStatus.CANCELLED:
            self.status = ScheduledStatus.CANCELLED
            self.save(update_fields=['status'])
    
    def mark_processed(self):
        """Mark as processed."""
        self.status = ScheduledStatus.PROCESSED
        self.processed_at = timezone.now()
        self.save(update_fields=['status', 'processed_at'])
    
    def mark_failed(self, error: str):
        """Mark as failed."""
        self.status = ScheduledStatus.FAILED
        self.error_message = error
        self.save(update_fields=['status', 'error_message'])
