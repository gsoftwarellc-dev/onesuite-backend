"""
Notification Throttling
Custom throttle classes for rate limiting.
"""
from rest_framework.throttling import UserRateThrottle


class NotificationsInboxThrottle(UserRateThrottle):
    """Throttle for inbox endpoints: 60 requests/minute."""
    scope = 'notifications_inbox'
    rate = '60/min'


class NotificationsAdminThrottle(UserRateThrottle):
    """Throttle for admin log endpoints: 30 requests/minute."""
    scope = 'notifications_admin'
    rate = '30/min'


class NotificationsRetryThrottle(UserRateThrottle):
    """Throttle for retry actions: 10 requests/minute."""
    scope = 'notifications_retry'
    rate = '10/min'
