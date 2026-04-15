"""
Application problem taxonomy.

Internal code raises typed exceptions. The HTTP edge serializes them into
RFC 9457 problem details responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, ClassVar, Self

from app.core.responses import ProblemFieldError, ProblemUpstream
from app.core.user_actions import UserAction

_USER_ACTION_UNSET = object()


@dataclass(frozen=True, slots=True)
class ProblemDefinition:
    type_slug: str
    title: str
    status: int
    code: str
    description: str
    default_detail: str
    retryable: bool
    user_action: UserAction | None = None


class ProblemException(Exception):  # noqa: N818
    """Base application exception translated at the HTTP boundary."""

    status: ClassVar[int] = 500
    type_slug: ClassVar[str] = "internal-error"
    title: ClassVar[str] = "Internal Server Error"
    code: ClassVar[str] = "internal_error"
    description: ClassVar[str] = "The server encountered an unexpected condition."
    default_detail: ClassVar[str] = "An unexpected error occurred."
    retryable_default: ClassVar[bool] = False
    default_user_action: ClassVar[UserAction | None] = None
    allowed_user_actions: ClassVar[frozenset[UserAction | None]] = frozenset({None})
    default_log_level: ClassVar[str] = "error"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.default_user_action not in cls.allowed_user_actions:
            raise TypeError(
                f"{cls.__name__} default_user_action must be in allowed_user_actions"
            )

    def __init__(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        raise TypeError(
            f"{type(self).__name__} must be constructed via .default() "
            "or a named factory method."
        )

    @classmethod
    def _default_headers(cls) -> dict[str, str]:
        return {}

    @classmethod
    def _build(
        cls,
        detail: str | None = None,
        *,
        errors: list[ProblemFieldError] | None = None,
        details: list[str] | None = None,
        upstream: ProblemUpstream | None = None,
        user_action: UserAction | None | object = _USER_ACTION_UNSET,
        log_level: str | None = None,
        extra_log_context: dict[str, Any] | None = None,
        status: int | None = None,
        title: str | None = None,
        type_slug: str | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        retryable: bool | None = None,
    ) -> Self:
        self = Exception.__new__(cls)

        resolved_detail = detail or cls.default_detail
        self.detail = resolved_detail
        self.status = cls.status if status is None else status
        self.title = cls.title if title is None else title
        self.type_slug = cls.type_slug if type_slug is None else type_slug
        self.code = cls.code if code is None else code

        resolved_headers = cls._default_headers()
        resolved_headers.update(headers or {})
        self.headers = resolved_headers
        self.errors = errors
        self.details = details
        self.upstream = upstream
        self.retryable = (
            cls.retryable_default if retryable is None else retryable
        )
        resolved_user_action = (
            cls.default_user_action
            if user_action is _USER_ACTION_UNSET
            else user_action
        )
        if resolved_user_action not in cls.allowed_user_actions:
            allowed = sorted(
                action.value if isinstance(action, UserAction) else "none"
                for action in cls.allowed_user_actions
            )
            raise ValueError(
                f"{cls.__name__} does not allow user_action="
                f"{resolved_user_action!r}. Allowed values: {', '.join(allowed)}"
            )
        self.user_action = resolved_user_action
        self.log_level = log_level or cls.default_log_level
        self.extra_log_context = extra_log_context or {}
        Exception.__init__(self, resolved_detail)
        return self

    @classmethod
    def default(
        cls,
        detail: str | None = None,
        *,
        errors: list[ProblemFieldError] | None = None,
        details: list[str] | None = None,
        upstream: ProblemUpstream | None = None,
        user_action: UserAction | None | object = _USER_ACTION_UNSET,
        log_level: str | None = None,
        extra_log_context: dict[str, Any] | None = None,
    ) -> Self:
        return cls._build(
            detail=detail,
            errors=errors,
            details=details,
            upstream=upstream,
            user_action=user_action,
            log_level=log_level,
            extra_log_context=extra_log_context,
        )

    @property
    def message(self) -> str:
        return self.detail

    @property
    def status_code(self) -> int:
        return self.status

    @property
    def error_code(self) -> str:
        return self.code

    @classmethod
    def definition(cls) -> ProblemDefinition:
        return ProblemDefinition(
            type_slug=cls.type_slug,
            title=cls.title,
            status=cls.status,
            code=cls.code,
            description=cls.description,
            default_detail=cls.default_detail,
            retryable=cls.retryable_default,
            user_action=cls.default_user_action,
        )


class MalformedRequestError(ProblemException):
    status = 400
    type_slug = "malformed-request"
    title = "Malformed Request"
    code = "malformed_request"
    description = "The request body or framing was syntactically invalid."
    default_detail = "The request body could not be parsed."
    default_log_level = "warning"


class UnsupportedMediaTypeError(ProblemException):
    status = 415
    type_slug = "unsupported-media-type"
    title = "Unsupported Media Type"
    code = "unsupported_media_type"
    description = "The request content type is not supported by this endpoint."
    default_detail = "The request content type is not supported."
    default_log_level = "warning"


class RequestValidationProblem(ProblemException):
    status = 422
    type_slug = "request-validation"
    title = "Request Validation Failed"
    code = "request_validation_failed"
    description = "The request was well formed but failed schema validation."
    default_detail = "One or more request fields are invalid."
    default_log_level = "warning"

    @classmethod
    def from_errors(
        cls,
        errors: list[ProblemFieldError],
    ) -> RequestValidationProblem:
        return cls.default(errors=errors)


class AuthenticationRequiredError(ProblemException):
    status = 401
    type_slug = "authentication-required"
    title = "Authentication Required"
    code = "authentication_required"
    description = "Authentication credentials were missing or invalid."
    default_detail = "Authentication credentials were missing or invalid."
    default_user_action = UserAction.REAUTHENTICATE
    allowed_user_actions = frozenset({UserAction.REAUTHENTICATE, None})
    default_log_level = "warning"

    @classmethod
    def _default_headers(cls) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}

    @classmethod
    def missing_or_invalid_authorization_header(cls) -> AuthenticationRequiredError:
        return cls.default(
            extra_log_context={"auth_reason": "missing_or_invalid_authorization_header"}
        )

    @classmethod
    def empty_bearer_token(cls) -> AuthenticationRequiredError:
        return cls.default(extra_log_context={"auth_reason": "empty_token"})

    @classmethod
    def token_expired(cls) -> AuthenticationRequiredError:
        return cls.default(extra_log_context={"auth_reason": "token_expired"})

    @classmethod
    def invalid_token(
        cls,
        *,
        jwt_error_type: str | None = None,
    ) -> AuthenticationRequiredError:
        extra_log_context = {"auth_reason": "invalid_token"}
        if jwt_error_type is not None:
            extra_log_context["jwt_error_type"] = jwt_error_type
        return cls.default(extra_log_context=extra_log_context)

    @classmethod
    def missing_subject_claim(cls) -> AuthenticationRequiredError:
        return cls.default(extra_log_context={"auth_reason": "missing_subject_claim"})

    @classmethod
    def unsupported_refresh_path(cls) -> AuthenticationRequiredError:
        return cls.default(extra_log_context={"auth_reason": "unsupported_refresh_path"})

    @classmethod
    def delegate_error(
        cls,
        *,
        delegate_error_type: str,
    ) -> AuthenticationRequiredError:
        return cls.default(
            extra_log_context={
                "auth_reason": "delegate_error",
                "delegate_error_type": delegate_error_type,
            }
        )

    @classmethod
    def malformed_user_id(cls) -> AuthenticationRequiredError:
        return cls.default(extra_log_context={"auth_reason": "malformed_user_id"})


class InvalidCredentialsError(ProblemException):
    status = 401
    type_slug = "invalid-credentials"
    title = "Invalid Credentials"
    code = "invalid_credentials"
    description = "The supplied authentication credentials are invalid."
    default_detail = "The supplied credentials are invalid."
    default_user_action = UserAction.REAUTHENTICATE
    allowed_user_actions = frozenset({UserAction.REAUTHENTICATE, None})
    default_log_level = "warning"


class InvalidVerificationCodeError(ProblemException):
    status = 400
    type_slug = "invalid-verification-code"
    title = "Invalid Verification Code"
    code = "invalid_verification_code"
    description = "The verification code is invalid or expired."
    default_detail = "The verification code is invalid or expired."
    default_log_level = "warning"


class AccountNotProvisionedError(ProblemException):
    status = 401
    type_slug = "account-not-provisioned"
    title = "Account Not Provisioned"
    code = "account_not_provisioned"
    description = "The authenticated identity has not been provisioned for this application."
    default_detail = "The authenticated identity is not provisioned for this application."
    default_user_action = UserAction.CONTACT_SUPPORT
    allowed_user_actions = frozenset({UserAction.CONTACT_SUPPORT, None})
    default_log_level = "warning"


class PermissionDeniedError(ProblemException):
    status = 403
    type_slug = "permission-denied"
    title = "Permission Denied"
    code = "permission_denied"
    description = "The authenticated caller is not allowed to perform the action."
    default_detail = "You are not allowed to perform this action."
    default_log_level = "warning"

    @classmethod
    def missing_role(
        cls,
        *required_roles: str,
    ) -> PermissionDeniedError:
        return cls.default(
            extra_log_context={"required_roles": ",".join(required_roles)}
        )

    @classmethod
    def missing_permission(
        cls,
        permission: str,
    ) -> PermissionDeniedError:
        return cls.default(extra_log_context={"missing_permission": permission})


class ResourceNotFoundError(ProblemException):
    status = 404
    type_slug = "resource-not-found"
    title = "Resource Not Found"
    code = "resource_not_found"
    description = "The requested resource does not exist."
    default_detail = "The requested resource was not found."
    default_log_level = "warning"

    @classmethod
    def for_resource(
        cls,
        resource_name: str,
        resource_id: object | None = None,
        *,
        detail: str | None = None,
    ) -> ResourceNotFoundError:
        context: dict[str, Any] = {"resource_name": resource_name}
        if resource_id is not None:
            context["resource_id"] = str(resource_id)

        message = detail or f"The requested {resource_name} was not found."
        return cls.default(detail=message, extra_log_context=context)


class MethodNotAllowedProblem(ProblemException):
    status = 405
    type_slug = "method-not-allowed"
    title = "Method Not Allowed"
    code = "method_not_allowed"
    description = "The request method is not allowed for this route."
    default_detail = "The request method is not allowed for this endpoint."
    default_log_level = "warning"

class ConflictError(ProblemException):
    status = 409
    type_slug = "conflict"
    title = "Conflict"
    code = "conflict"
    description = "The request could not be completed because of a resource conflict."
    default_detail = "The request conflicts with the current resource state."
    default_log_level = "warning"

    @classmethod
    def already_exists(
        cls,
        resource_name: str,
        resource_id: object | None = None,
        *,
        detail: str | None = None,
    ) -> ConflictError:
        context: dict[str, Any] = {"resource_name": resource_name}
        if resource_id is not None:
            context["resource_id"] = str(resource_id)

        message = detail or f"The requested {resource_name} already exists."
        return cls.default(detail=message, extra_log_context=context)


class IdempotencyKeyRequiredError(ProblemException):
    status = 428
    type_slug = "idempotency-key-required"
    title = "Idempotency Key Required"
    code = "idempotency_key_required"
    description = "Mutation requests must include an Idempotency-Key header."
    default_detail = "This mutation requires an Idempotency-Key header."
    default_log_level = "warning"


class IdempotencyScopeRequiredError(ProblemException):
    status = 400
    type_slug = "idempotency-scope-required"
    title = "Idempotency Scope Required"
    code = "idempotency_scope_required"
    description = "Anonymous mutation requests require a validated anonymous ID."
    default_detail = (
        "Provide a valid X-Anonymous-ID header or authenticate before retrying."
    )
    default_log_level = "warning"


class IdempotencyInProgressError(ProblemException):
    status = 409
    type_slug = "idempotency-request-in-progress"
    title = "Request Already In Progress"
    code = "idempotency_request_in_progress"
    description = "A request with the same idempotency key is still being processed."
    default_detail = "A matching request is still being processed."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})
    default_log_level = "warning"

    @classmethod
    def _default_headers(cls) -> dict[str, str]:
        return {"Retry-After": "1"}

    @classmethod
    def for_retry_after(cls, retry_after_seconds: int) -> IdempotencyInProgressError:
        return cls._build(headers={"Retry-After": str(retry_after_seconds)})


class IdempotencyPayloadMismatchError(ProblemException):
    status = 409
    type_slug = "idempotency-payload-mismatch"
    title = "Idempotency Payload Mismatch"
    code = "idempotency_payload_mismatch"
    description = "The idempotency key was reused with a different request payload."
    default_detail = "The idempotency key was reused with a different request payload."
    default_log_level = "warning"


class RequestTooLargeProblem(ProblemException):
    status = 413
    type_slug = "request-too-large"
    title = "Request Too Large"
    code = "request_too_large"
    description = "The request body exceeded the configured size limit."
    default_detail = "The request body exceeds the maximum allowed size."
    default_log_level = "warning"


class RateLimitedError(ProblemException):
    status = 429
    type_slug = "rate-limited"
    title = "Rate Limited"
    code = "rate_limited"
    description = "The caller has exceeded the configured rate limit."
    default_detail = "Too many requests were made in a short period."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})
    default_log_level = "warning"

    @classmethod
    def for_window(
        cls,
        window_seconds: int,
        *,
        limit: int | None = None,
    ) -> RateLimitedError:
        headers = {"Retry-After": str(window_seconds)}
        if limit is not None:
            headers["X-RateLimit-Limit"] = str(limit)
        return cls._build(
            detail=f"Too many requests were made. Retry in {window_seconds} seconds.",
            headers=headers,
        )


class RequestDeadlineExceededError(ProblemException):
    status = 503
    type_slug = "request-deadline-exceeded"
    title = "Request Deadline Exceeded"
    code = "request_deadline_exceeded"
    description = "The server aborted the request after exceeding its deadline."
    default_detail = "The request took too long to process."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})

    @classmethod
    def _default_headers(cls) -> dict[str, str]:
        return {"Retry-After": "1"}


class DependencyUnavailableError(ProblemException):
    status = 503
    type_slug = "dependency-unavailable"
    title = "Dependency Unavailable"
    code = "dependency_unavailable"
    description = "A required dependency was unavailable."
    default_detail = "A required upstream dependency is temporarily unavailable."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})

    @classmethod
    def for_service(
        cls,
        service_name: str,
        *,
        upstream: ProblemUpstream | None = None,
        detail: str | None = None,
        retry_after: int | None = None,
        extra_log_context: dict[str, Any] | None = None,
    ) -> DependencyUnavailableError:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return cls._build(
            detail=detail or f"{service_name.capitalize()} is temporarily unavailable.",
            upstream=upstream or ProblemUpstream(provider=service_name),
            headers=headers,
            extra_log_context=extra_log_context,
        )


class UpstreamTimeoutError(ProblemException):
    status = 504
    type_slug = "upstream-timeout"
    title = "Upstream Timeout"
    code = "upstream_timeout"
    description = "An upstream dependency timed out while handling the request."
    default_detail = "An upstream dependency took too long to respond."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})

    @classmethod
    def _default_headers(cls) -> dict[str, str]:
        return {"Retry-After": "1"}

    @classmethod
    def for_service(
        cls,
        service_name: str,
        *,
        upstream: ProblemUpstream | None = None,
        detail: str | None = None,
        retry_after: int = 1,
    ) -> UpstreamTimeoutError:
        headers = {"Retry-After": str(retry_after)}
        return cls._build(
            detail=detail or f"{service_name.capitalize()} timed out.",
            upstream=upstream or ProblemUpstream(provider=service_name),
            headers=headers,
        )


class UpstreamServiceError(ProblemException):
    status = 502
    type_slug = "upstream-service-error"
    title = "Upstream Service Error"
    code = "upstream_service_error"
    description = "An upstream provider returned an error."
    default_detail = "An upstream provider could not complete the request."
    retryable_default = True
    default_user_action = UserAction.RETRY
    allowed_user_actions = frozenset({UserAction.RETRY, None})

    @classmethod
    def bad_gateway(
        cls,
        *,
        upstream: ProblemUpstream,
        detail: str | None = None,
    ) -> UpstreamServiceError:
        return cls.default(detail=detail, upstream=upstream)

    @classmethod
    def provider_unavailable(
        cls,
        *,
        provider_name: str,
        upstream: ProblemUpstream,
        detail: str | None = None,
        retry_after: int | None = None,
    ) -> UpstreamServiceError:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return cls._build(
            detail=detail or f"{provider_name.capitalize()} is temporarily unavailable.",
            upstream=upstream,
            headers=headers,
            status=503,
            retryable=True,
        )


class ExternalActionRequiredError(ProblemException):
    status = 409
    type_slug = "external-action-required"
    title = "External Action Required"
    code = "external_action_required"
    description = "The request requires a user-facing action in an external system."
    default_detail = "Additional action is required to complete this request."
    default_user_action = UserAction.CONTACT_SUPPORT
    allowed_user_actions = frozenset(
        {UserAction.REAUTHENTICATE_BANK, UserAction.CONTACT_SUPPORT, None}
    )
    default_log_level = "warning"

    @classmethod
    def bank_reauthentication_required(
        cls,
        *,
        provider_name: str,
        upstream: ProblemUpstream,
        detail: str | None = None,
        retryable: bool = False,
    ) -> ExternalActionRequiredError:
        message = (
            detail
            or f"{provider_name.capitalize()} requires additional action to continue."
        )
        return cls._build(
            detail=message,
            upstream=upstream,
            retryable=retryable,
            user_action=UserAction.REAUTHENTICATE_BANK,
        )

    @classmethod
    def support_required(
        cls,
        *,
        provider_name: str,
        upstream: ProblemUpstream,
        detail: str | None = None,
        retryable: bool = False,
    ) -> ExternalActionRequiredError:
        message = (
            detail
            or f"{provider_name.capitalize()} requires additional action to continue."
        )
        return cls._build(
            detail=message,
            upstream=upstream,
            retryable=retryable,
            user_action=UserAction.CONTACT_SUPPORT,
        )


class InternalServerProblem(ProblemException):
    status = 500
    type_slug = "internal-error"
    title = "Internal Server Error"
    code = "internal_error"
    description = "The server encountered an unexpected condition."
    default_detail = "An unexpected error occurred."


class GenericHTTPProblem(ProblemException):
    """Fallback problem for uncommon HTTP status codes."""

    @classmethod
    def default(cls, *args: object, **kwargs: object) -> GenericHTTPProblem:
        raise TypeError("GenericHTTPProblem must be constructed via .from_status().")

    @classmethod
    def from_status(
        cls,
        status: int,
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> GenericHTTPProblem:
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = "HTTP Error"

        type_slug = f"http-{status}"
        code = f"http_{status}"
        default_detail = detail or phrase
        return cls._build(
            detail=default_detail,
            status=status,
            title=phrase,
            type_slug=type_slug,
            code=code,
            headers=headers,
            retryable=status >= 500,
            log_level="warning" if status < 500 else "error",
        )

    @classmethod
    def definition(cls) -> ProblemDefinition:
        raise TypeError("GenericHTTPProblem does not have a static problem definition")


_PROBLEM_TYPES: tuple[type[ProblemException], ...] = (
    MalformedRequestError,
    UnsupportedMediaTypeError,
    RequestValidationProblem,
    AuthenticationRequiredError,
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    AccountNotProvisionedError,
    PermissionDeniedError,
    ResourceNotFoundError,
    MethodNotAllowedProblem,
    ConflictError,
    IdempotencyKeyRequiredError,
    IdempotencyScopeRequiredError,
    IdempotencyInProgressError,
    IdempotencyPayloadMismatchError,
    RequestTooLargeProblem,
    RateLimitedError,
    RequestDeadlineExceededError,
    DependencyUnavailableError,
    UpstreamTimeoutError,
    UpstreamServiceError,
    ExternalActionRequiredError,
    InternalServerProblem,
)

PROBLEM_DEFINITIONS: dict[str, ProblemDefinition] = {
    problem_type.type_slug: problem_type.definition()
    for problem_type in _PROBLEM_TYPES
}


def problem_for_status(
    status_code: int,
    *,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> ProblemException:
    mapping: dict[int, type[ProblemException]] = {
        400: MalformedRequestError,
        401: AuthenticationRequiredError,
        403: PermissionDeniedError,
        404: ResourceNotFoundError,
        405: MethodNotAllowedProblem,
        409: ConflictError,
        413: RequestTooLargeProblem,
        415: UnsupportedMediaTypeError,
        422: RequestValidationProblem,
        428: IdempotencyKeyRequiredError,
        429: RateLimitedError,
        500: InternalServerProblem,
        503: DependencyUnavailableError,
        504: UpstreamTimeoutError,
    }
    problem_type = mapping.get(status_code)
    if problem_type is None:
        return GenericHTTPProblem.from_status(
            status=status_code,
            detail=detail,
            headers=headers,
        )
    return problem_type._build(detail=detail, headers=headers)


# Backwards-compatible aliases used throughout the current codebase/tests.
AppException = ProblemException
NotFoundError = ResourceNotFoundError
ValidationError = RequestValidationProblem
AuthenticationError = AuthenticationRequiredError
AuthorizationError = PermissionDeniedError
RateLimitError = RateLimitedError
RequestTimeoutError = RequestDeadlineExceededError
RequestTooLargeError = RequestTooLargeProblem
ExternalServiceError = UpstreamServiceError
IdempotencyConflictError = IdempotencyInProgressError


__all__ = [
    "PROBLEM_DEFINITIONS",
    "AppException",
    "AccountNotProvisionedError",
    "AuthenticationError",
    "AuthenticationRequiredError",
    "AuthorizationError",
    "ConflictError",
    "DependencyUnavailableError",
    "ExternalActionRequiredError",
    "ExternalServiceError",
    "GenericHTTPProblem",
    "InvalidCredentialsError",
    "InvalidVerificationCodeError",
    "IdempotencyConflictError",
    "IdempotencyKeyRequiredError",
    "IdempotencyInProgressError",
    "IdempotencyPayloadMismatchError",
    "IdempotencyScopeRequiredError",
    "InternalServerProblem",
    "MalformedRequestError",
    "MethodNotAllowedProblem",
    "NotFoundError",
    "PermissionDeniedError",
    "ProblemDefinition",
    "ProblemException",
    "RateLimitError",
    "RateLimitedError",
    "RequestDeadlineExceededError",
    "RequestTimeoutError",
    "RequestTooLargeError",
    "RequestTooLargeProblem",
    "RequestValidationProblem",
    "ResourceNotFoundError",
    "UnsupportedMediaTypeError",
    "UpstreamServiceError",
    "UpstreamTimeoutError",
    "ValidationError",
    "problem_for_status",
]
