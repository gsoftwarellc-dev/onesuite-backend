"""
Analytics Exceptions
Custom exceptions for consistent error handling across analytics services.
"""


class AnalyticsError(Exception):
    """Base exception for analytics errors."""
    error_code = 'analytics_error'
    status_code = 400
    
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self):
        return {
            'error': self.error_code,
            'message': self.message,
            'details': self.details
        }


class ForbiddenScopeError(AnalyticsError):
    """Raised when user tries to access a scope they don't have permission for."""
    error_code = 'forbidden'
    status_code = 403
    
    def __init__(self, message: str = "You do not have permission to access this scope", 
                 required_role: str = None, current_role: str = None):
        details = {}
        if required_role:
            details['required_role'] = required_role
        if current_role:
            details['current_role'] = current_role
        super().__init__(message, details)


class ValidationError(AnalyticsError):
    """Raised for invalid parameters."""
    error_code = 'validation_error'
    status_code = 422
    
    def __init__(self, message: str, field: str = None, **kwargs):
        details = kwargs
        if field:
            details['field'] = field
        super().__init__(message, details)


class ExportLimitExceededError(AnalyticsError):
    """Raised when export exceeds row limit."""
    error_code = 'validation_error'
    status_code = 422
    
    def __init__(self, max_rows: int, requested_rows: int):
        super().__init__(
            message="Export exceeds maximum row limit",
            details={
                'max_rows': max_rows,
                'requested_rows': requested_rows,
                'suggestion': "Narrow the date range"
            }
        )


class NotFoundError(AnalyticsError):
    """Raised when requested resource is not found."""
    error_code = 'not_found'
    status_code = 404
