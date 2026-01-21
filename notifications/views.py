"""
Notification Views
12 API endpoints as specified in Phase 7.3 API Design.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import (
    NotificationInbox, NotificationLog, ScheduledNotification,
    EmailStatus, ScheduledStatus, NotificationChannel
)
from .serializers import (
    InboxListSerializer, LogsListSerializer, FailedLogsSerializer,
    StatsSerializer, ScheduledListSerializer,
    InboxItemSerializer, LogItemSerializer, ScheduledItemSerializer,
    UnreadCountSerializer
)
from .services import (
    InboxService, NotificationLogService, ScheduledNotificationService,
    NotificationService
)
from .exceptions import (
    NotificationError, NotFoundError, ForbiddenError,
    AlreadyProcessedError, ValidationError
)
from .throttling import (
    NotificationsInboxThrottle, NotificationsAdminThrottle, NotificationsRetryThrottle
)


def is_finance_or_admin(user) -> bool:
    """Check if user has finance or admin role."""
    role = getattr(user, 'role', '')
    role_value = role.lower() if isinstance(role, str) else role
    return user.is_staff or user.is_superuser or role_value in ['finance', 'admin']


class NotificationAPIView(APIView):
    """Base view with error handling."""
    permission_classes = [IsAuthenticated]
    
    def handle_exception(self, exc):
        from rest_framework.exceptions import Throttled
        
        if isinstance(exc, Throttled):
            return Response(
                {
                    'error': 'rate_limited',
                    'message': 'Too many requests',
                    'details': {'retry_after': exc.wait}
                },
                status=429
            )
        
        if isinstance(exc, NotificationError):
            return Response(exc.to_dict(), status=exc.status_code)
        
        return super().handle_exception(exc)


# =============================================================================
# Inbox Endpoints (6)
# =============================================================================

class InboxListView(NotificationAPIView):
    """GET /api/notifications/inbox/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def get(self, request):
        serializer = InboxListSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        items, total = InboxService.get_inbox(
            user=request.user,
            status=params.get('status'),
            priority=params.get('priority'),
            limit=params.get('limit', 20),
            offset=params.get('offset', 0),
            ordering=params.get('ordering', '-created_at')
        )
        
        return Response({
            'count': total,
            'results': InboxItemSerializer(items, many=True).data
        })


class UnreadCountView(NotificationAPIView):
    """GET /api/notifications/inbox/unread-count/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def get(self, request):
        counts = InboxService.get_unread_count(request.user)
        return Response(counts)


class InboxDetailView(NotificationAPIView):
    """GET /api/notifications/inbox/{id}/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def get(self, request, pk):
        try:
            item = NotificationInbox.objects.get(pk=pk)
        except NotificationInbox.DoesNotExist:
            raise NotFoundError("Notification not found")
        
        if item.recipient != request.user:
            raise ForbiddenError("You can only view your own notifications")
        
        return Response(InboxItemSerializer(item).data)


class MarkReadView(NotificationAPIView):
    """POST /api/notifications/inbox/{id}/read/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def post(self, request, pk):
        try:
            item = NotificationInbox.objects.get(pk=pk)
        except NotificationInbox.DoesNotExist:
            raise NotFoundError("Notification not found")
        
        if item.recipient != request.user:
            raise ForbiddenError("You can only mark your own notifications as read")
        
        # Idempotent - returns 200 even if already read
        InboxService.mark_read(item)
        return Response(InboxItemSerializer(item).data)


class MarkAllReadView(NotificationAPIView):
    """POST /api/notifications/inbox/mark-all-read/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def post(self, request):
        count = InboxService.mark_all_read(request.user)
        return Response({'updated_count': count})


class ArchiveView(NotificationAPIView):
    """POST /api/notifications/inbox/{id}/archive/"""
    throttle_classes = [NotificationsInboxThrottle]
    
    def post(self, request, pk):
        try:
            item = NotificationInbox.objects.get(pk=pk)
        except NotificationInbox.DoesNotExist:
            raise NotFoundError("Notification not found")
        
        if item.recipient != request.user:
            raise ForbiddenError("You can only archive your own notifications")
        
        # Idempotent - returns 200 even if already archived
        InboxService.archive(item)
        return Response(InboxItemSerializer(item).data)


# =============================================================================
# Admin Endpoints (6)
# =============================================================================

class LogsListView(NotificationAPIView):
    """GET /api/notifications/logs/"""
    throttle_classes = [NotificationsAdminThrottle]
    
    def get(self, request):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        serializer = LogsListSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        items, total = NotificationLogService.get_logs(
            event_type=params.get('event_type'),
            channel=params.get('channel'),
            status=params.get('status'),
            recipient_id=params.get('recipient_id'),
            source_model=params.get('source_model'),
            source_id=params.get('source_id'),
            start_date=params.get('start_date'),
            end_date=params.get('end_date'),
            limit=params.get('limit', 50),
            offset=params.get('offset', 0)
        )
        
        return Response({
            'count': total,
            'results': LogItemSerializer(items, many=True).data
        })


class FailedLogsView(NotificationAPIView):
    """GET /api/notifications/logs/failed/"""
    throttle_classes = [NotificationsAdminThrottle]
    
    def get(self, request):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        serializer = FailedLogsSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        items = NotificationLogService.get_failed(
            days=params.get('days', 7),
            limit=params.get('limit', 50)
        )
        
        return Response({
            'count': len(items),
            'results': LogItemSerializer(items, many=True).data
        })


class RetryLogView(NotificationAPIView):
    """POST /api/notifications/logs/{id}/retry/"""
    throttle_classes = [NotificationsRetryThrottle]
    
    def post(self, request, pk):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        try:
            log = NotificationLog.objects.get(pk=pk)
        except NotificationLog.DoesNotExist:
            raise NotFoundError("Notification log not found")
        
        # Check if already sent
        if log.status == EmailStatus.SENT:
            raise AlreadyProcessedError("Notification already sent successfully")
        
        # Check if IN_APP - cannot retry
        if log.channel == NotificationChannel.IN_APP:
            raise ValidationError("IN_APP delivery cannot be retried; inbox is already stored.")
        
        # Only retry FAILED or BOUNCED
        if log.status not in [EmailStatus.FAILED, EmailStatus.BOUNCED]:
            raise ValidationError(f"Cannot retry notification with status {log.status}")
        
        success = NotificationService.retry_failed(log)
        if success:
            log.refresh_from_db()
            return Response({
                'id': log.id,
                'status': log.status,
                'retry_count': log.retry_count,
                'next_retry_at': log.next_retry_at.isoformat() if log.next_retry_at else None,
                'message': 'Notification queued for retry'
            })
        
        raise ValidationError("Retry failed")


class StatsView(NotificationAPIView):
    """GET /api/notifications/stats/"""
    throttle_classes = [NotificationsAdminThrottle]
    
    def get(self, request):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        serializer = StatsSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        stats = NotificationLogService.get_stats(days=params.get('days', 7))
        return Response(stats)


class ScheduledListView(NotificationAPIView):
    """GET /api/notifications/scheduled/"""
    throttle_classes = [NotificationsAdminThrottle]
    
    def get(self, request):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        serializer = ScheduledListSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        
        items = ScheduledNotificationService.get_pending(limit=params.get('limit', 50))
        
        return Response({
            'count': len(items),
            'results': ScheduledItemSerializer(items, many=True).data
        })


class CancelScheduledView(NotificationAPIView):
    """POST /api/notifications/scheduled/{id}/cancel/"""
    throttle_classes = [NotificationsRetryThrottle]
    
    def post(self, request, pk):
        if not is_finance_or_admin(request.user):
            raise ForbiddenError("Admin access required")
        
        try:
            scheduled = ScheduledNotification.objects.get(pk=pk)
        except ScheduledNotification.DoesNotExist:
            raise NotFoundError("Scheduled notification not found")
        
        # Check if already processed
        if scheduled.status == ScheduledStatus.PROCESSED:
            raise AlreadyProcessedError("Cannot cancel already processed notification")
        
        # Idempotent cancel
        if scheduled.status == ScheduledStatus.CANCELLED:
            return Response({
                'id': scheduled.id,
                'status': scheduled.status,
                'message': 'Scheduled notification already cancelled'
            })
        
        ScheduledNotificationService.cancel(scheduled)
        return Response({
            'id': scheduled.id,
            'status': scheduled.status,
            'message': 'Scheduled notification cancelled'
        })
