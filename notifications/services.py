"""
Notification Services
Event routing, template rendering, and delivery logic.
"""
import logging
from datetime import timedelta
from typing import Optional, Dict, Any, List

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import (
    NotificationLog, NotificationInbox, ScheduledNotification,
    NotificationChannel, EmailStatus, InboxStatus, EventType,
    NotificationPriority, ScheduledStatus
)

logger = logging.getLogger(__name__)
User = get_user_model()

# Retry delays in minutes
RETRY_DELAYS = [5, 30, 120]  # 5min, 30min, 2hr
MAX_RETRIES = 3


# =============================================================================
# Email Templates Configuration
# =============================================================================

EMAIL_TEMPLATES = {
    EventType.PAY_001: {
        'subject': 'Payment Received - ${amount}',
        'template': 'notifications/payment_completed.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.PAY_002: {
        'subject': 'Payment Failed - Action Required',
        'template': 'notifications/payment_failed.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.PAY_003: {
        'subject': 'Payment Retry in Progress',
        'template': 'notifications/payment_retried.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.COMP_001: {
        'subject': 'Action Required: Submit Your W-9',
        'template': 'notifications/w9_missing.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.COMP_002: {
        'subject': 'W-9 Submission Rejected',
        'template': 'notifications/w9_rejected.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.COMP_003: {
        'subject': '1099 Tax Document Generated',
        'template': 'notifications/1099_generated.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.COMP_004: {
        'subject': '1099 Forms Ready for Filing',
        'template': 'notifications/1099_ready.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.OUT_001: {
        'subject': 'Payout Released - ${amount}',
        'template': 'notifications/payout_released.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.OUT_002: {
        'subject': 'Payout Delayed - Action May Be Required',
        'template': 'notifications/payout_delayed.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.ANLT_001: {
        'subject': '[ALERT] KPI Threshold Exceeded',
        'template': 'notifications/kpi_breach.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.ANLT_002: {
        'subject': '[ALERT] Reconciliation Discrepancy Detected',
        'template': 'notifications/reconciliation_discrepancy.html',
        'priority': NotificationPriority.HIGH,
    },
    EventType.SYS_001: {
        'subject': '[CRITICAL] Aggregation Job Failed',
        'template': 'notifications/aggregation_failed.html',
        'priority': NotificationPriority.CRITICAL,
    },
    EventType.SYS_002: {
        'subject': 'Your Export is Ready',
        'template': 'notifications/export_ready.html',
        'priority': NotificationPriority.NORMAL,
    },
    EventType.COMM_001: {
        'subject': 'New Commission Submitted: ${reference}',
        'template': None, # Fallback to text
        'priority': NotificationPriority.HIGH,
    },
    EventType.COMM_002: {
        'subject': 'Commission Approved: ${reference}',
        'template': None,
        'priority': NotificationPriority.NORMAL,
    },
    EventType.COMM_003: {
        'subject': 'Commission Rejected: ${reference}',
        'template': None,
        'priority': NotificationPriority.HIGH,
    },
}


# =============================================================================
# Idempotency Key Builder
# =============================================================================

def build_idempotency_key(
    event_type: str,
    source_id: int,
    recipient_id: int,
    channel: str
) -> str:
    """Build deterministic idempotency key."""
    return f"{event_type}:{source_id}:{recipient_id}:{channel}"


# =============================================================================
# Core Notification Service
# =============================================================================

class NotificationService:
    """
    Main service for sending notifications.
    Handles idempotency, routing, and delivery.
    """
    
    @staticmethod
    def send(
        event_type: str,
        recipient: User,
        source_model: str,
        source_id: int,
        metadata: Dict[str, Any] = None,
        channels: List[str] = None
    ) -> List[NotificationLog]:
        """
        Send a notification via specified channels.
        
        Args:
            event_type: Event type code (e.g., PAY_001)
            recipient: Target user
            source_model: Source model name (e.g., "PaymentTransaction")
            source_id: Source object ID
            metadata: Template variables (amount, date, etc.)
            channels: Channels to use (default: both EMAIL and IN_APP)
        
        Returns:
            List of created NotificationLog entries
        """
        metadata = metadata or {}
        channels = channels or [NotificationChannel.EMAIL, NotificationChannel.IN_APP]
        
        template_config = EMAIL_TEMPLATES.get(event_type, {})
        priority = template_config.get('priority', NotificationPriority.NORMAL)
        
        logs = []
        for channel in channels:
            log = NotificationService._send_single(
                event_type=event_type,
                recipient=recipient,
                channel=channel,
                source_model=source_model,
                source_id=source_id,
                metadata=metadata,
                priority=priority
            )
            if log:
                logs.append(log)
        
        return logs
    
    @staticmethod
    def _send_single(
        event_type: str,
        recipient: User,
        channel: str,
        source_model: str,
        source_id: int,
        metadata: Dict,
        priority: str
    ) -> Optional[NotificationLog]:
        """Send a single notification (one channel)."""
        idempotency_key = build_idempotency_key(
            event_type, source_id, recipient.id, channel
        )
        
        # Check idempotency
        if NotificationLog.objects.filter(idempotency_key=idempotency_key).exists():
            logger.debug(f"Notification already exists: {idempotency_key}")
            return None
        
        # Build content
        template_config = EMAIL_TEMPLATES.get(event_type, {})
        subject = NotificationService._render_subject(
            template_config.get('subject', event_type),
            metadata
        )
        body = NotificationService._render_body(
            template_config.get('template'),
            event_type,
            recipient,
            metadata
        )
        
        # Create log entry
        log = NotificationLog.objects.create(
            idempotency_key=idempotency_key,
            event_type=event_type,
            channel=channel,
            recipient=recipient,
            status=EmailStatus.PENDING,
            priority=priority,
            source_model=source_model,
            source_id=source_id,
            subject=subject,
            body=body,
            metadata=metadata
        )
        
        # Deliver based on channel
        if channel == NotificationChannel.EMAIL:
            NotificationService._deliver_email(log)
        elif channel == NotificationChannel.IN_APP:
            NotificationService._deliver_in_app(log)
        
        return log
    
    @staticmethod
    def _render_subject(template: str, metadata: Dict) -> str:
        """Render subject with metadata substitution."""
        result = template
        for key, value in metadata.items():
            result = result.replace(f"${{{key}}}", str(value))
        return result
    
    @staticmethod
    def _render_body(template_name: str, event_type: str, recipient: User, metadata: Dict) -> str:
        """Render email body from template."""
        context = {
            'recipient': recipient,
            'event_type': event_type,
            **metadata
        }
        try:
            if template_name:
                return render_to_string(template_name, context)
        except Exception as e:
            logger.warning(f"Template render failed: {e}")
        
        # Fallback: simple text body
        return f"Notification: {event_type}\n\n{metadata}"
    
    @staticmethod
    def _deliver_email(log: NotificationLog):
        """Deliver email notification."""
        try:
            send_mail(
                subject=log.subject,
                message=log.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[log.recipient.email],
                fail_silently=False
            )
            log.mark_sent()
            logger.info(f"Email sent: {log.idempotency_key}")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Email failed: {log.idempotency_key} - {error_msg}")
            
            if log.retry_count < MAX_RETRIES:
                delay = RETRY_DELAYS[min(log.retry_count, len(RETRY_DELAYS) - 1)]
                log.schedule_retry(delay_minutes=delay)
            else:
                log.mark_failed(error_msg)
    
    @staticmethod
    def _deliver_in_app(log: NotificationLog):
        """Create in-app inbox entry."""
        try:
            NotificationInbox.objects.create(
                notification_log=log,
                recipient=log.recipient,
                event_type=log.event_type,
                title=log.subject,
                message=log.metadata.get('summary', log.subject),
                priority=log.priority,
                action_url=log.metadata.get('action_url')
            )
            log.mark_sent()
            logger.info(f"In-app notification created: {log.idempotency_key}")
        except Exception as e:
            log.mark_failed(str(e))
            logger.error(f"In-app notification failed: {e}")
    
    @staticmethod
    def retry_failed(log: NotificationLog) -> bool:
        """
        Retry a failed notification.
        
        Returns:
            True if retry was scheduled, False otherwise
        """
        if log.status not in [EmailStatus.FAILED, EmailStatus.BOUNCED]:
            return False
        
        if log.channel == NotificationChannel.IN_APP:
            # IN_APP cannot be retried
            return False
        
        log.schedule_retry(delay_minutes=0)  # Immediate retry
        return True


# =============================================================================
# Inbox Service
# =============================================================================

class InboxService:
    """Service for managing user inbox."""
    
    @staticmethod
    def get_inbox(
        user: User,
        status: str = None,
        priority: str = None,
        limit: int = 20,
        offset: int = 0,
        ordering: str = '-created_at'
    ) -> tuple:
        """Get user's inbox with filtering and pagination."""
        queryset = NotificationInbox.objects.filter(recipient=user)
        
        if status:
            queryset = queryset.filter(status=status)
        if priority:
            queryset = queryset.filter(priority=priority)
        
        # Handle ordering
        if ordering.startswith('-'):
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by(ordering)
        
        total = queryset.count()
        items = list(queryset[offset:offset + limit])
        
        return items, total
    
    @staticmethod
    def get_unread_count(user: User) -> Dict[str, int]:
        """Get unread notification counts."""
        base = NotificationInbox.objects.filter(
            recipient=user,
            status=InboxStatus.UNREAD
        )
        return {
            'unread_count': base.count(),
            'high_priority_count': base.filter(
                priority__in=[NotificationPriority.HIGH, NotificationPriority.CRITICAL]
            ).count()
        }
    
    @staticmethod
    def mark_read(inbox_item: NotificationInbox) -> NotificationInbox:
        """Mark item as read (idempotent)."""
        inbox_item.mark_read()
        return inbox_item
    
    @staticmethod
    def mark_all_read(user: User) -> int:
        """Mark all unread items as read. Returns count."""
        items = NotificationInbox.objects.filter(
            recipient=user,
            status=InboxStatus.UNREAD
        )
        count = 0
        for item in items:
            item.mark_read()
            count += 1
        return count
    
    @staticmethod
    def archive(inbox_item: NotificationInbox) -> NotificationInbox:
        """Archive item (idempotent)."""
        inbox_item.mark_archived()
        return inbox_item


# =============================================================================
# Admin Log Service
# =============================================================================

class NotificationLogService:
    """Service for admin notification log queries."""
    
    @staticmethod
    def get_logs(
        event_type: str = None,
        channel: str = None,
        status: str = None,
        recipient_id: int = None,
        source_model: str = None,
        source_id: int = None,
        start_date=None,
        end_date=None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple:
        """Get notification logs with filtering."""
        queryset = NotificationLog.objects.all()
        
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if channel:
            queryset = queryset.filter(channel=channel)
        if status:
            queryset = queryset.filter(status=status)
        if recipient_id:
            queryset = queryset.filter(recipient_id=recipient_id)
        if source_model:
            queryset = queryset.filter(source_model=source_model)
        if source_id:
            queryset = queryset.filter(source_id=source_id)
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        
        total = queryset.count()
        items = list(queryset.select_related('recipient')[offset:offset + limit])
        
        return items, total
    
    @staticmethod
    def get_failed(days: int = 7, limit: int = 50) -> List[NotificationLog]:
        """Get failed notifications from last N days."""
        cutoff = timezone.now() - timedelta(days=days)
        return list(NotificationLog.objects.filter(
            status__in=[EmailStatus.FAILED, EmailStatus.BOUNCED],
            created_at__gte=cutoff
        ).select_related('recipient')[:limit])
    
    @staticmethod
    def get_stats(days: int = 7) -> Dict[str, Any]:
        """Get notification statistics."""
        cutoff = timezone.now() - timedelta(days=days)
        logs = NotificationLog.objects.filter(created_at__gte=cutoff)
        
        total = logs.count()
        sent = logs.filter(status=EmailStatus.SENT).count()
        failed = logs.filter(status__in=[EmailStatus.FAILED, EmailStatus.BOUNCED]).count()
        
        # By channel
        by_channel = {}
        for channel in NotificationChannel.values:
            channel_logs = logs.filter(channel=channel)
            by_channel[channel] = {
                'sent': channel_logs.filter(status=EmailStatus.SENT).count(),
                'failed': channel_logs.filter(status__in=[EmailStatus.FAILED, EmailStatus.BOUNCED]).count()
            }
        
        # By event type
        by_event = {}
        for event in EventType.values:
            event_logs = logs.filter(event_type=event)
            if event_logs.exists():
                by_event[event] = {
                    'sent': event_logs.filter(status=EmailStatus.SENT).count(),
                    'failed': event_logs.filter(status__in=[EmailStatus.FAILED, EmailStatus.BOUNCED]).count()
                }
        
        return {
            'period_days': days,
            'total_sent': sent,
            'total_failed': failed,
            'by_channel': by_channel,
            'by_event_type': by_event,
            'failure_rate': f"{(failed / total * 100):.1f}%" if total > 0 else "0%"
        }


# =============================================================================
# Scheduled Notification Service
# =============================================================================

class ScheduledNotificationService:
    """Service for managing scheduled notifications."""
    
    @staticmethod
    def schedule(
        event_type: str,
        recipient: User,
        channel: str,
        scheduled_for,
        metadata: Dict = None
    ) -> Optional[ScheduledNotification]:
        """Schedule a notification for future delivery."""
        idempotency_key = build_idempotency_key(
            event_type, 0, recipient.id, channel
        ) + f":{scheduled_for.isoformat()}"
        
        # Check idempotency
        if ScheduledNotification.objects.filter(idempotency_key=idempotency_key).exists():
            return None
        
        return ScheduledNotification.objects.create(
            idempotency_key=idempotency_key,
            event_type=event_type,
            recipient=recipient,
            channel=channel,
            scheduled_for=scheduled_for,
            metadata=metadata or {}
        )
    
    @staticmethod
    def get_pending(limit: int = 50) -> List[ScheduledNotification]:
        """Get pending scheduled notifications."""
        return list(ScheduledNotification.objects.filter(
            status=ScheduledStatus.PENDING
        ).select_related('recipient')[:limit])
    
    @staticmethod
    def get_due() -> List[ScheduledNotification]:
        """Get scheduled notifications that are due for processing."""
        return list(ScheduledNotification.objects.filter(
            status=ScheduledStatus.PENDING,
            scheduled_for__lte=timezone.now()
        ).select_related('recipient'))
    
    @staticmethod
    def cancel(scheduled: ScheduledNotification):
        """Cancel a scheduled notification (idempotent)."""
        scheduled.cancel()
    
    @staticmethod
    def process(scheduled: ScheduledNotification):
        """Process a scheduled notification by sending it."""
        try:
            NotificationService.send(
                event_type=scheduled.event_type,
                recipient=scheduled.recipient,
                source_model='ScheduledNotification',
                source_id=scheduled.id,
                metadata=scheduled.metadata,
                channels=[scheduled.channel]
            )
            scheduled.mark_processed()
        except Exception as e:
            scheduled.mark_failed(str(e))
