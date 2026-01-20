"""
Notification Admin
Read-only admin views for notification models.
"""
from django.contrib import admin
from .models import NotificationLog, NotificationInbox, ScheduledNotification


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'event_type', 'channel', 'recipient', 'status',
        'priority', 'retry_count', 'created_at', 'sent_at'
    ]
    list_filter = ['event_type', 'channel', 'status', 'priority', 'created_at']
    search_fields = ['recipient__username', 'recipient__email', 'subject', 'idempotency_key']
    readonly_fields = [
        'idempotency_key', 'event_type', 'channel', 'recipient', 'status',
        'priority', 'source_model', 'source_id', 'subject', 'body',
        'metadata', 'retry_count', 'next_retry_at', 'error_message',
        'created_at', 'sent_at'
    ]
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationInbox)
class NotificationInboxAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'recipient', 'event_type', 'title', 'status',
        'priority', 'created_at', 'read_at'
    ]
    list_filter = ['event_type', 'status', 'priority', 'created_at']
    search_fields = ['recipient__username', 'recipient__email', 'title']
    readonly_fields = [
        'notification_log', 'recipient', 'event_type', 'title', 'message',
        'priority', 'status', 'action_url', 'created_at', 'read_at', 'archived_at'
    ]
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ScheduledNotification)
class ScheduledNotificationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'event_type', 'recipient', 'channel', 'scheduled_for',
        'status', 'retry_count', 'created_at'
    ]
    list_filter = ['event_type', 'channel', 'status', 'scheduled_for']
    search_fields = ['recipient__username', 'recipient__email', 'idempotency_key']
    readonly_fields = [
        'idempotency_key', 'event_type', 'recipient', 'channel',
        'scheduled_for', 'metadata', 'status', 'retry_count',
        'next_retry_at', 'error_message', 'processed_at', 'created_at'
    ]
    ordering = ['scheduled_for']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
