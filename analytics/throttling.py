"""
Analytics Throttling
Custom throttle classes for rate limiting.
"""
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import exception_handler
from rest_framework.response import Response


class AnalyticsDashboardThrottle(UserRateThrottle):
    """
    Throttle for dashboard endpoints: 60 requests/minute.
    """
    scope = 'analytics_dashboard'
    rate = '60/min'


class AnalyticsMetricsThrottle(UserRateThrottle):
    """
    Throttle for analytics metrics endpoints: 60 requests/minute.
    """
    scope = 'analytics_metrics'
    rate = '60/min'


class AnalyticsExportThrottle(UserRateThrottle):
    """
    Throttle for export endpoints: 10 requests/minute.
    """
    scope = 'analytics_export'
    rate = '10/min'


def analytics_exception_handler(exc, context):
    """
    Custom exception handler that returns standard error envelope for 429.
    """
    from rest_framework.exceptions import Throttled
    from .exceptions import AnalyticsError
    
    # Handle Throttled exceptions
    if isinstance(exc, Throttled):
        return Response(
            {
                'error': 'rate_limited',
                'message': 'Too many requests',
                'details': {
                    'retry_after': exc.wait
                }
            },
            status=429
        )
    
    # Handle custom analytics exceptions
    if isinstance(exc, AnalyticsError):
        return Response(
            exc.to_dict(),
            status=exc.status_code
        )
    
    # Default handling for other exceptions
    response = exception_handler(exc, context)
    
    # Wrap DRF validation errors in standard envelope
    if response is not None and response.status_code == 400:
        original_data = response.data
        response.data = {
            'error': 'validation_error',
            'message': 'Invalid request parameters',
            'details': original_data
        }
    
    return response
