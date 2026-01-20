"""
Notification URL Configuration
12 endpoints under /api/notifications/
"""
from django.urls import path
from .views import (
    # Inbox (6)
    InboxListView,
    UnreadCountView,
    InboxDetailView,
    MarkReadView,
    MarkAllReadView,
    ArchiveView,
    # Admin (6)
    LogsListView,
    FailedLogsView,
    RetryLogView,
    StatsView,
    ScheduledListView,
    CancelScheduledView,
)

urlpatterns = [
    # Inbox endpoints
    path('inbox/', InboxListView.as_view(), name='inbox-list'),
    path('inbox/unread-count/', UnreadCountView.as_view(), name='inbox-unread-count'),
    path('inbox/mark-all-read/', MarkAllReadView.as_view(), name='inbox-mark-all-read'),
    path('inbox/<int:pk>/', InboxDetailView.as_view(), name='inbox-detail'),
    path('inbox/<int:pk>/read/', MarkReadView.as_view(), name='inbox-mark-read'),
    path('inbox/<int:pk>/archive/', ArchiveView.as_view(), name='inbox-archive'),
    
    # Admin endpoints
    path('logs/', LogsListView.as_view(), name='logs-list'),
    path('logs/failed/', FailedLogsView.as_view(), name='logs-failed'),
    path('logs/<int:pk>/retry/', RetryLogView.as_view(), name='logs-retry'),
    path('stats/', StatsView.as_view(), name='stats'),
    path('scheduled/', ScheduledListView.as_view(), name='scheduled-list'),
    path('scheduled/<int:pk>/cancel/', CancelScheduledView.as_view(), name='scheduled-cancel'),
]
