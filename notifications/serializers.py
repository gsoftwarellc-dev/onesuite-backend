"""
Notification Serializers
Query parameter validation and response shaping.
"""
from rest_framework import serializers
from .models import NotificationInbox, NotificationLog, ScheduledNotification


# =============================================================================
# Query Parameter Serializers
# =============================================================================

class InboxListSerializer(serializers.Serializer):
    """Query params for inbox listing."""
    status = serializers.ChoiceField(choices=['UNREAD', 'READ', 'ARCHIVED'], required=False)
    priority = serializers.ChoiceField(choices=['NORMAL', 'HIGH', 'CRITICAL'], required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20, required=False)
    offset = serializers.IntegerField(min_value=0, default=0, required=False)
    ordering = serializers.ChoiceField(
        choices=['-created_at', 'created_at', '-priority', 'priority'],
        default='-created_at',
        required=False
    )


class LogsListSerializer(serializers.Serializer):
    """Query params for admin logs listing."""
    event_type = serializers.CharField(required=False)
    channel = serializers.ChoiceField(choices=['EMAIL', 'IN_APP'], required=False)
    status = serializers.ChoiceField(choices=['PENDING', 'SENT', 'FAILED', 'BOUNCED'], required=False)
    recipient_id = serializers.IntegerField(required=False)
    source_model = serializers.CharField(required=False)
    source_id = serializers.IntegerField(required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=50, required=False)
    offset = serializers.IntegerField(min_value=0, default=0, required=False)


class FailedLogsSerializer(serializers.Serializer):
    """Query params for failed logs."""
    days = serializers.IntegerField(min_value=1, max_value=90, default=7, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=50, required=False)


class StatsSerializer(serializers.Serializer):
    """Query params for stats."""
    days = serializers.IntegerField(min_value=1, max_value=90, default=7, required=False)


class ScheduledListSerializer(serializers.Serializer):
    """Query params for scheduled notifications."""
    status = serializers.ChoiceField(
        choices=['PENDING', 'PROCESSED', 'CANCELLED', 'FAILED'],
        default='PENDING',
        required=False
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50, required=False)


# =============================================================================
# Response Serializers
# =============================================================================

class InboxItemSerializer(serializers.ModelSerializer):
    """Response serializer for inbox items."""
    
    class Meta:
        model = NotificationInbox
        fields = [
            'id', 'event_type', 'title', 'message', 'priority',
            'status', 'action_url', 'created_at', 'read_at', 'archived_at'
        ]


class UnreadCountSerializer(serializers.Serializer):
    """Response serializer for unread count."""
    unread_count = serializers.IntegerField()
    high_priority_count = serializers.IntegerField()


class LogItemSerializer(serializers.ModelSerializer):
    """Response serializer for log items (admin)."""
    recipient_email = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationLog
        fields = [
            'id', 'idempotency_key', 'event_type', 'channel',
            'recipient_id', 'recipient_email', 'status', 'priority',
            'subject', 'source_model', 'source_id',
            'retry_count', 'error_message',
            'created_at', 'sent_at'
        ]
    
    def get_recipient_email(self, obj):
        return obj.recipient.email if obj.recipient else None


class ScheduledItemSerializer(serializers.ModelSerializer):
    """Response serializer for scheduled notifications."""
    
    class Meta:
        model = ScheduledNotification
        fields = [
            'id', 'idempotency_key', 'event_type', 'recipient_id',
            'channel', 'scheduled_for', 'status',
            'retry_count', 'error_message', 'created_at'
        ]


class StatsResponseSerializer(serializers.Serializer):
    """Response serializer for stats."""
    period_days = serializers.IntegerField()
    total_sent = serializers.IntegerField()
    total_failed = serializers.IntegerField()
    by_channel = serializers.DictField()
    by_event_type = serializers.DictField()
    failure_rate = serializers.CharField()
