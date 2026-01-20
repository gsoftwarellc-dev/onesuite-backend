"""
Notification Exceptions
Custom exceptions for consistent error handling.
"""


class NotificationError(Exception):
    """Base exception for notification errors."""
    error_code = 'notification_error'
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


class NotFoundError(NotificationError):
    """Notification not found."""
    error_code = 'not_found'
    status_code = 404


class ForbiddenError(NotificationError):
    """Not owner or insufficient role."""
    error_code = 'forbidden'
    status_code = 403


class AlreadyProcessedError(NotificationError):
    """Already read/archived/sent/cancelled."""
    error_code = 'already_processed'
    status_code = 409


class ValidationError(NotificationError):
    """Invalid parameters."""
    error_code = 'validation_error'
    status_code = 422
