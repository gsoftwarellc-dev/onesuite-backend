"""
Phase 7.5 Notifications Verification Tests
Comprehensive test suite for Notifications & Alerts module.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError

from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from .models import (
    NotificationLog, NotificationInbox, ScheduledNotification,
    NotificationChannel, EmailStatus, InboxStatus, EventType,
    NotificationPriority, ScheduledStatus
)
from .services import (
    NotificationService, InboxService, NotificationLogService,
    ScheduledNotificationService, build_idempotency_key
)

User = get_user_model()


# =============================================================================
# 1. Event → Notification Creation Tests
# =============================================================================

class NotificationCreationTests(TestCase):
    """Test notification creation from events."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
    
    @patch('notifications.services.send_mail')
    def test_notification_creates_log(self, mock_send):
        """Sending notification creates NotificationLog."""
        mock_send.return_value = 1  # Success
        
        logs = NotificationService.send(
            event_type=EventType.PAY_001,
            recipient=self.user,
            source_model='PaymentTransaction',
            source_id=123,
            metadata={'amount': '100.00'}
        )
        
        self.assertEqual(len(logs), 2)  # EMAIL + IN_APP
        self.assertTrue(NotificationLog.objects.filter(
            event_type=EventType.PAY_001,
            recipient=self.user
        ).exists())
    
    @patch('notifications.services.send_mail')
    def test_notification_creates_inbox(self, mock_send):
        """IN_APP notification creates inbox entry."""
        mock_send.return_value = 1
        
        NotificationService.send(
            event_type=EventType.PAY_001,
            recipient=self.user,
            source_model='PaymentTransaction',
            source_id=123,
            channels=[NotificationChannel.IN_APP]
        )
        
        self.assertTrue(NotificationInbox.objects.filter(
            recipient=self.user,
            event_type=EventType.PAY_001
        ).exists())


# =============================================================================
# 2. Idempotency Tests
# =============================================================================

class IdempotencyTests(TestCase):
    """Test idempotency enforcement."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
    
    def test_idempotency_key_format(self):
        """Idempotency key has correct format."""
        key = build_idempotency_key('PAY_001', 123, 456, 'EMAIL')
        self.assertEqual(key, 'PAY_001:123:456:EMAIL')
    
    @patch('notifications.services.send_mail')
    def test_duplicate_notification_blocked(self, mock_send):
        """Duplicate notifications are prevented."""
        mock_send.return_value = 1
        
        # First send
        logs1 = NotificationService.send(
            event_type=EventType.PAY_001,
            recipient=self.user,
            source_model='PaymentTransaction',
            source_id=123,
            channels=[NotificationChannel.EMAIL]
        )
        
        # Second send (same params)
        logs2 = NotificationService.send(
            event_type=EventType.PAY_001,
            recipient=self.user,
            source_model='PaymentTransaction',
            source_id=123,
            channels=[NotificationChannel.EMAIL]
        )
        
        self.assertEqual(len(logs1), 1)
        self.assertEqual(len(logs2), 0)  # Blocked by idempotency
        self.assertEqual(NotificationLog.objects.count(), 1)
    
    def test_unique_constraint_enforced(self):
        """Unique constraint on idempotency_key."""
        NotificationLog.objects.create(
            idempotency_key='TEST:1:1:EMAIL',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.EMAIL,
            recipient=self.user,
            subject='Test',
            body='Test'
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            NotificationLog.objects.create(
                idempotency_key='TEST:1:1:EMAIL',
                event_type=EventType.PAY_001,
                channel=NotificationChannel.EMAIL,
                recipient=self.user,
                subject='Test2',
                body='Test2'
            )


# =============================================================================
# 3. Append-Only Tests
# =============================================================================

class AppendOnlyTests(TestCase):
    """Test append-only enforcement."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
    
    def test_log_no_arbitrary_update(self):
        """NotificationLog blocks arbitrary updates."""
        log = NotificationLog.objects.create(
            idempotency_key='TEST:1:1:EMAIL',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.EMAIL,
            recipient=self.user,
            subject='Test',
            body='Test'
        )
        
        log.subject = 'Modified'
        with self.assertRaises(ValidationError):
            log.save()
    
    def test_log_status_update_allowed(self):
        """Status updates are allowed."""
        log = NotificationLog.objects.create(
            idempotency_key='TEST:2:1:EMAIL',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.EMAIL,
            recipient=self.user,
            subject='Test',
            body='Test'
        )
        
        log.status = EmailStatus.SENT
        log.save(update_fields=['status'])  # Should not raise
        
        log.refresh_from_db()
        self.assertEqual(log.status, EmailStatus.SENT)
    
    def test_log_no_delete(self):
        """NotificationLog cannot be deleted."""
        log = NotificationLog.objects.create(
            idempotency_key='TEST:3:1:EMAIL',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.EMAIL,
            recipient=self.user,
            subject='Test',
            body='Test'
        )
        
        with self.assertRaises(ValidationError):
            log.delete()


# =============================================================================
# 4. Inbox Isolation Tests
# =============================================================================

class InboxIsolationTests(APITestCase):
    """Test inbox access control."""
    
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='user1', email='user1@test.com', password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='user2', email='user2@test.com', password='testpass123'
        )
        self.client = APIClient()
        
        # Create inbox items
        log1 = NotificationLog.objects.create(
            idempotency_key='TEST:1:1:IN_APP',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.IN_APP,
            recipient=self.user1,
            subject='User1 Notification',
            body='Test'
        )
        NotificationInbox.objects.create(
            notification_log=log1,
            recipient=self.user1,
            event_type=EventType.PAY_001,
            title='User1 Notification',
            message='Test'
        )
        
        log2 = NotificationLog.objects.create(
            idempotency_key='TEST:2:2:IN_APP',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.IN_APP,
            recipient=self.user2,
            subject='User2 Notification',
            body='Test'
        )
        NotificationInbox.objects.create(
            notification_log=log2,
            recipient=self.user2,
            event_type=EventType.PAY_001,
            title='User2 Notification',
            message='Test'
        )
    
    def test_user_sees_own_inbox_only(self):
        """User only sees their own notifications."""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get('/api/notifications/inbox/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], 'User1 Notification')
    
    def test_cannot_access_other_user_notification(self):
        """Cannot access another user's notification."""
        inbox = NotificationInbox.objects.get(recipient=self.user2)
        
        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f'/api/notifications/inbox/{inbox.id}/')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# =============================================================================
# 5. Retry Logic Tests
# =============================================================================

class RetryLogicTests(TestCase):
    """Test retry logic for failed notifications."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
    
    @patch('notifications.services.send_mail')
    def test_failed_email_schedules_retry(self, mock_send):
        """Failed email schedules retry."""
        mock_send.side_effect = Exception('SMTP Error')
        
        NotificationService.send(
            event_type=EventType.PAY_001,
            recipient=self.user,
            source_model='PaymentTransaction',
            source_id=1,
            channels=[NotificationChannel.EMAIL]
        )
        
        log = NotificationLog.objects.get(channel=NotificationChannel.EMAIL)
        self.assertEqual(log.status, EmailStatus.PENDING)
        self.assertEqual(log.retry_count, 1)
        self.assertIsNotNone(log.next_retry_at)
    
    def test_retry_service_updates_status(self):
        """Retry service updates log status."""
        log = NotificationLog.objects.create(
            idempotency_key='TEST:1:1:EMAIL',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.EMAIL,
            recipient=self.user,
            status=EmailStatus.FAILED,
            subject='Test',
            body='Test',
            retry_count=1
        )
        
        success = NotificationService.retry_failed(log)
        
        self.assertTrue(success)
        log.refresh_from_db()
        self.assertEqual(log.status, EmailStatus.PENDING)
        self.assertEqual(log.retry_count, 2)
    
    def test_in_app_cannot_retry(self):
        """IN_APP notifications cannot be retried."""
        log = NotificationLog.objects.create(
            idempotency_key='TEST:2:1:IN_APP',
            event_type=EventType.PAY_001,
            channel=NotificationChannel.IN_APP,
            recipient=self.user,
            status=EmailStatus.FAILED,
            subject='Test',
            body='Test'
        )
        
        success = NotificationService.retry_failed(log)
        self.assertFalse(success)


# =============================================================================
# 6. Scheduled Notification Tests
# =============================================================================

class ScheduledNotificationTests(TestCase):
    """Test scheduled notifications."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password='testpass123'
        )
    
    def test_schedule_creates_entry(self):
        """Scheduling creates ScheduledNotification."""
        scheduled = ScheduledNotificationService.schedule(
            event_type=EventType.COMP_001,
            recipient=self.user,
            channel=NotificationChannel.EMAIL,
            scheduled_for=timezone.now() + timedelta(days=7),
            metadata={'days_overdue': 7}
        )
        
        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.status, ScheduledStatus.PENDING)
    
    def test_cancel_idempotent(self):
        """Cancel is idempotent."""
        scheduled = ScheduledNotification.objects.create(
            idempotency_key='TEST:1:1:EMAIL:2026-01-27',
            event_type=EventType.COMP_001,
            recipient=self.user,
            channel=NotificationChannel.EMAIL,
            scheduled_for=timezone.now() + timedelta(days=7)
        )
        
        scheduled.cancel()
        self.assertEqual(scheduled.status, ScheduledStatus.CANCELLED)
        
        # Second cancel should not raise
        scheduled.cancel()
        self.assertEqual(scheduled.status, ScheduledStatus.CANCELLED)
    
    def test_cannot_cancel_processed(self):
        """Cannot cancel already processed notification."""
        scheduled = ScheduledNotification.objects.create(
            idempotency_key='TEST:2:1:EMAIL:2026-01-27',
            event_type=EventType.COMP_001,
            recipient=self.user,
            channel=NotificationChannel.EMAIL,
            scheduled_for=timezone.now() + timedelta(days=7),
            status=ScheduledStatus.PROCESSED
        )
        
        with self.assertRaises(ValidationError):
            scheduled.cancel()


# =============================================================================
# 7. Admin Endpoint Tests
# =============================================================================

class AdminEndpointTests(APITestCase):
    """Test admin-only endpoints."""
    
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='testpass123'
        )
        self.user = User.objects.create_user(
            username='user1', email='user@test.com', password='testpass123'
        )
        self.client = APIClient()
    
    def test_logs_requires_admin(self):
        """Logs endpoint requires admin."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/notifications/logs/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_logs_accessible_to_admin(self):
        """Logs endpoint accessible to admin."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/notifications/logs/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_stats_requires_admin(self):
        """Stats endpoint requires admin."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/notifications/stats/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# =============================================================================
# 8. Throttle Class Tests
# =============================================================================

class ThrottleTests(TestCase):
    """Test throttle classes are assigned."""
    
    def test_inbox_throttle_assigned(self):
        """Inbox views have throttle."""
        from notifications.views import InboxListView
        from notifications.throttling import NotificationsInboxThrottle
        self.assertIn(NotificationsInboxThrottle, InboxListView.throttle_classes)
    
    def test_admin_throttle_assigned(self):
        """Admin views have throttle."""
        from notifications.views import LogsListView
        from notifications.throttling import NotificationsAdminThrottle
        self.assertIn(NotificationsAdminThrottle, LogsListView.throttle_classes)
    
    def test_retry_throttle_assigned(self):
        """Retry view has stricter throttle."""
        from notifications.views import RetryLogView
        from notifications.throttling import NotificationsRetryThrottle
        self.assertIn(NotificationsRetryThrottle, RetryLogView.throttle_classes)


# =============================================================================
# 9. Regression Tests
# =============================================================================

class RegressionTests(TestCase):
    """Test no regressions to Phase 4-6."""
    
    def test_payment_model_unchanged(self):
        """Payment models from Phase 5 unaffected."""
        from payments.models import PaymentMethod, PaymentTransaction
        self.assertTrue(hasattr(PaymentTransaction, 'amount'))
        self.assertTrue(hasattr(PaymentTransaction, 'status'))
    
    def test_payout_model_unchanged(self):
        """Payout models from Phase 4 unaffected."""
        from payouts.models import Payout, PayoutBatch
        self.assertTrue(hasattr(PayoutBatch, 'status'))
        self.assertTrue(hasattr(Payout, 'total_commission'))
    
    def test_analytics_model_unchanged(self):
        """Analytics models from Phase 6 unaffected."""
        from analytics.models import CommissionMetric, ExportLog
        self.assertTrue(hasattr(CommissionMetric, 'total_amount'))
        self.assertTrue(hasattr(ExportLog, 'report_type'))
