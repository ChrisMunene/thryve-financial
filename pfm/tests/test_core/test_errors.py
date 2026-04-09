"""Tests for exception hierarchy and response envelope."""

from app.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    ExternalServiceError,
    IdempotencyConflictError,
    NotFoundError,
    RateLimitError,
    RequestTimeoutError,
    RequestTooLargeError,
    ValidationError,
)
from app.core.responses import error_response, paginated_response, success_response


class TestExceptionHierarchy:
    def test_not_found_error(self):
        exc = NotFoundError("User 123 not found")
        assert exc.status_code == 404
        assert exc.error_code == "RESOURCE_NOT_FOUND"
        assert exc.message == "User 123 not found"

    def test_validation_error(self):
        exc = ValidationError("Invalid email", details=["email must contain @"])
        assert exc.status_code == 422
        assert exc.error_code == "VALIDATION_ERROR"
        assert exc.details == ["email must contain @"]

    def test_authentication_error(self):
        exc = AuthenticationError()
        assert exc.status_code == 401
        assert exc.error_code == "AUTHENTICATION_FAILED"

    def test_authorization_error(self):
        exc = AuthorizationError()
        assert exc.status_code == 403
        assert exc.error_code == "FORBIDDEN"

    def test_rate_limit_error(self):
        exc = RateLimitError()
        assert exc.status_code == 429
        assert exc.error_code == "RATE_LIMIT_EXCEEDED"

    def test_external_service_error(self):
        exc = ExternalServiceError("Plaid API returned 503")
        assert exc.status_code == 502
        assert exc.error_code == "EXTERNAL_SERVICE_ERROR"

    def test_request_timeout_error(self):
        exc = RequestTimeoutError()
        assert exc.status_code == 504
        assert exc.error_code == "REQUEST_TIMEOUT"

    def test_request_too_large_error(self):
        exc = RequestTooLargeError()
        assert exc.status_code == 413
        assert exc.error_code == "REQUEST_TOO_LARGE"

    def test_idempotency_conflict(self):
        exc = IdempotencyConflictError()
        assert exc.status_code == 409
        assert exc.error_code == "IDEMPOTENCY_CONFLICT"

    def test_all_inherit_from_app_exception(self):
        for exc_class in [
            NotFoundError, ValidationError, AuthenticationError,
            AuthorizationError, RateLimitError, RequestTimeoutError,
            RequestTooLargeError, ExternalServiceError,
            IdempotencyConflictError,
        ]:
            assert issubclass(exc_class, AppException)

    def test_base_exception_defaults(self):
        exc = AppException()
        assert exc.status_code == 500
        assert exc.error_code == "INTERNAL_ERROR"
        assert exc.message == "An unexpected error occurred"
        assert exc.details is None


class TestResponseEnvelope:
    def test_success_response(self):
        result = success_response({"id": "123", "name": "Chris"})
        assert result.data["id"] == "123"

    def test_paginated_response(self):
        result = paginated_response(
            data=[{"id": "1"}, {"id": "2"}],
            cursor="abc123",
            has_more=True,
            total=42,
        )
        assert len(result.data) == 2
        assert result.pagination.cursor == "abc123"
        assert result.pagination.has_more is True
        assert result.pagination.total == 42

    def test_paginated_response_last_page(self):
        result = paginated_response(data=[], cursor=None, has_more=False)
        assert result.data == []
        assert result.pagination.has_more is False
        assert result.pagination.cursor is None

    def test_error_response(self):
        result = error_response(
            code="RESOURCE_NOT_FOUND",
            message="User 123 not found",
            request_id="req-abc",
        )
        assert result.error.code == "RESOURCE_NOT_FOUND"
        assert result.error.message == "User 123 not found"
        assert result.error.request_id == "req-abc"
        assert result.error.details is None

    def test_error_response_with_details(self):
        result = error_response(
            code="VALIDATION_ERROR",
            message="Invalid input",
            details=["field 'email' is required", "field 'name' too short"],
        )
        assert len(result.error.details) == 2
