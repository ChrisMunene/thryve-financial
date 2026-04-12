"""Tests for the problem taxonomy and response models."""

import pytest

from app.core.exceptions import (
    PROBLEM_DEFINITIONS,
    AuthenticationRequiredError,
    DependencyUnavailableError,
    ExternalActionRequiredError,
    IdempotencyInProgressError,
    PermissionDeniedError,
    ProblemException,
    RateLimitedError,
    RequestDeadlineExceededError,
    RequestTooLargeProblem,
    RequestValidationProblem,
    ResourceNotFoundError,
    UpstreamServiceError,
)
from app.core.responses import (
    ProblemFieldError,
    ProblemResponse,
    ProblemUpstream,
    paginated_response,
    success_response,
)
from app.core.user_actions import UserAction


class TestProblemHierarchy:
    def test_resource_not_found_definition(self):
        exc = ResourceNotFoundError.default()
        assert exc.status == 404
        assert exc.code == "resource_not_found"
        assert exc.type_slug == "resource-not-found"

    def test_raw_problem_construction_is_blocked(self):
        with pytest.raises(TypeError, match="constructed via .default\\(\\)"):
            ResourceNotFoundError()

    def test_validation_problem_carries_field_errors(self):
        exc = RequestValidationProblem.from_errors(
            [
                ProblemFieldError(
                    source="body",
                    field="email",
                    code="string_too_short",
                    message="Email is too short",
                )
            ]
        )
        assert exc.status == 422
        assert exc.errors[0].field == "email"

    def test_authentication_problem_adds_www_authenticate_header(self):
        exc = AuthenticationRequiredError.default()
        assert exc.status == 401
        assert exc.headers["WWW-Authenticate"] == "Bearer"

    def test_authentication_problem_helpers_encode_internal_reason(self):
        exc = AuthenticationRequiredError.token_expired()
        assert exc.status == 401
        assert exc.extra_log_context["auth_reason"] == "token_expired"

    def test_rate_limited_problem_is_retryable(self):
        exc = RateLimitedError.default()
        assert exc.status == 429
        assert exc.retryable is True

    def test_rate_limited_factory_sets_standard_headers(self):
        exc = RateLimitedError.for_window(30, limit=5)
        assert exc.headers["Retry-After"] == "30"
        assert exc.headers["X-RateLimit-Limit"] == "5"

    def test_request_deadline_problem_is_retryable(self):
        exc = RequestDeadlineExceededError.default()
        assert exc.status == 503
        assert exc.retryable is True
        assert exc.headers["Retry-After"] == "1"

    def test_request_too_large_problem(self):
        exc = RequestTooLargeProblem.default()
        assert exc.status == 413
        assert exc.code == "request_too_large"

    def test_upstream_problem_catalog_builds_unavailable_variant(self):
        exc = UpstreamServiceError.provider_unavailable(
            provider_name="plaid",
            upstream=ProblemUpstream(provider="plaid"),
        )
        assert exc.status == 503
        assert exc.code == "upstream_service_error"

    def test_problem_identity_fields_cannot_be_publicly_overridden(self):
        with pytest.raises(TypeError):
            UpstreamServiceError(status=503)

    def test_idempotency_in_progress_sets_retry_after_header(self):
        exc = IdempotencyInProgressError.default()
        assert exc.status == 409
        assert exc.headers["Retry-After"] == "1"

    def test_problem_exception_rejects_invalid_user_action_for_problem_type(self):
        with pytest.raises(ValueError, match="Allowed values"):
            RateLimitedError.default(user_action=UserAction.REAUTHENTICATE_BANK)

    def test_external_action_factories_enforce_supported_user_actions(self):
        bank_exc = ExternalActionRequiredError.bank_reauthentication_required(
            provider_name="plaid",
            upstream=ProblemUpstream(provider="plaid", provider_code="ITEM_LOGIN_REQUIRED"),
        )
        support_exc = ExternalActionRequiredError.support_required(
            provider_name="mx",
            upstream=ProblemUpstream(provider="mx"),
        )

        assert bank_exc.user_action == UserAction.REAUTHENTICATE_BANK
        assert support_exc.user_action == UserAction.CONTACT_SUPPORT

    def test_resource_not_found_factory_builds_message_and_log_context(self):
        exc = ResourceNotFoundError.for_resource("account", "acct_123")
        assert exc.detail == "The requested account was not found."
        assert exc.extra_log_context == {
            "resource_name": "account",
            "resource_id": "acct_123",
        }

    def test_permission_denied_factories_build_log_context(self):
        role_exc = PermissionDeniedError.missing_role("admin", "owner")
        permission_exc = PermissionDeniedError.missing_permission("transactions:write")

        assert role_exc.extra_log_context["required_roles"] == "admin,owner"
        assert permission_exc.extra_log_context["missing_permission"] == "transactions:write"

    def test_dependency_unavailable_factory_builds_service_context(self):
        exc = DependencyUnavailableError.for_service("anthropic", retry_after=2)
        assert exc.detail == "Anthropic is temporarily unavailable."
        assert exc.headers["Retry-After"] == "2"
        assert exc.upstream.provider == "anthropic"

    def test_problem_definitions_registry_contains_known_types(self):
        assert "resource-not-found" in PROBLEM_DEFINITIONS
        assert PROBLEM_DEFINITIONS["resource-not-found"].status == 404
        assert (
            PROBLEM_DEFINITIONS["authentication-required"].user_action
            == UserAction.REAUTHENTICATE
        )

    def test_all_registered_problem_types_inherit_from_problem_exception(self):
        for definition in PROBLEM_DEFINITIONS.values():
            assert isinstance(definition.status, int)
        assert issubclass(ResourceNotFoundError, ProblemException)


class TestResponseModels:
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

    def test_problem_response_model(self):
        result = ProblemResponse(
            type="https://api.example.com/problems/resource-not-found",
            title="Resource Not Found",
            status=404,
            detail="The requested resource was not found.",
            instance="https://api.example.com/requests/req-123",
            code="resource_not_found",
            request_id="req-123",
            retryable=False,
            errors=[
                ProblemFieldError(
                    source="query",
                    field="limit",
                    code="greater_than_equal",
                    message="Input should be greater than or equal to 1",
                )
            ],
            upstream=ProblemUpstream(
                provider="plaid",
                provider_code="ITEM_LOGIN_REQUIRED",
                provider_request_id="plaid-123",
            ),
            user_action=UserAction.REAUTHENTICATE_BANK,
        )

        assert result.request_id == "req-123"
        assert result.errors[0].source == "query"
        assert result.upstream.provider_request_id == "plaid-123"
        assert result.user_action == UserAction.REAUTHENTICATE_BANK
