## ADDED Requirements

### Requirement: Exception hierarchy
The application SHALL define an `AppException` base class with fields: status_code (int), error_code (str), message (str), details (list[str] | None). Subclasses: `NotFoundError(404)`, `ValidationError(422)`, `AuthenticationError(401)`, `AuthorizationError(403)`, `RateLimitError(429)`, `ExternalServiceError(502)`, `IdempotencyConflictError(409)`. Each subclass SHALL have a default error_code string (e.g., "RESOURCE_NOT_FOUND").

#### Scenario: Raise NotFoundError
- **WHEN** a service raises `NotFoundError("Transaction not found")`
- **THEN** the error carries status_code=404, error_code="RESOURCE_NOT_FOUND"

### Requirement: Global error handler
A global exception handler SHALL be registered on the FastAPI app. It SHALL catch `AppException` subclasses and return the standardized error envelope with the appropriate HTTP status code. Unhandled exceptions SHALL be caught, logged at ERROR with full stack trace and request context (path, method, user_id, correlation_id), and return a 500 error envelope. In development, the stack trace SHALL be included in the response. In production, only the error code and message SHALL be returned.

#### Scenario: AppException returns correct envelope
- **WHEN** `NotFoundError("User 123 not found")` is raised during request handling
- **THEN** the response is 404 with body `{"error": {"code": "RESOURCE_NOT_FOUND", "message": "User 123 not found", "request_id": "..."}}`

#### Scenario: Unhandled exception in production
- **WHEN** an unhandled `ValueError` is raised in production
- **THEN** the response is 500 with body `{"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "request_id": "..."}}` and the full stack trace is logged

#### Scenario: Unhandled exception in development
- **WHEN** an unhandled `ValueError` is raised in development
- **THEN** the response is 500 and includes the stack trace in `error.details`

### Requirement: Standardized response envelope
All successful API responses SHALL use `Response[T]` with fields: `data` (the payload) and `meta` (optional metadata dict). All error responses SHALL use `ErrorResponse` with field: `error` containing `code`, `message`, `details` (optional), and `request_id`. Paginated responses SHALL use `PaginatedResponse[T]` which extends `Response[list[T]]` with `meta.pagination` containing `cursor`, `has_more`, and optionally `total`.

#### Scenario: Success response
- **WHEN** an endpoint returns a transaction object
- **THEN** the response body is `{"data": {...transaction...}, "meta": null}`

#### Scenario: Paginated response
- **WHEN** an endpoint returns a list of transactions with pagination
- **THEN** the response body is `{"data": [...], "meta": {"pagination": {"cursor": "...", "has_more": true}}}`

#### Scenario: Error response
- **WHEN** any error occurs
- **THEN** the response body is `{"error": {"code": "...", "message": "...", "request_id": "..."}}`
