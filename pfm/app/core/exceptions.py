"""
Application exception hierarchy.

Every exception maps to an HTTP status code and error code string.
The global error handler catches these and returns a standardized envelope.
"""


class AppException(Exception):
    """Base application exception."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        details: list[str] | None = None,
    ):
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(AppException):
    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"

    def __init__(self, message: str = "Resource not found", **kwargs):
        super().__init__(message, **kwargs)


class ValidationError(AppException):
    status_code = 422
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Validation failed", **kwargs):
        super().__init__(message, **kwargs)


class AuthenticationError(AppException):
    status_code = 401
    error_code = "AUTHENTICATION_FAILED"

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, **kwargs)


class AuthorizationError(AppException):
    status_code = 403
    error_code = "FORBIDDEN"

    def __init__(self, message: str = "Forbidden", **kwargs):
        super().__init__(message, **kwargs)


class RateLimitError(AppException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, **kwargs)


class RequestTimeoutError(AppException):
    status_code = 504
    error_code = "REQUEST_TIMEOUT"

    def __init__(self, message: str = "Request processing timed out", **kwargs):
        super().__init__(message, **kwargs)


class RequestTooLargeError(AppException):
    status_code = 413
    error_code = "REQUEST_TOO_LARGE"

    def __init__(self, message: str = "Request body exceeds the maximum allowed size", **kwargs):
        super().__init__(message, **kwargs)


class ExternalServiceError(AppException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, message: str = "External service error", **kwargs):
        super().__init__(message, **kwargs)


class IdempotencyConflictError(AppException):
    status_code = 409
    error_code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, message: str = "Idempotency conflict", **kwargs):
        super().__init__(message, **kwargs)
