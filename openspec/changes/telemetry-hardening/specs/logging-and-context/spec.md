## ADDED Requirements

### Requirement: Trace and span identifiers in logs
All structured log lines emitted while a valid OpenTelemetry span is active SHALL include `trace_id` and `span_id` in addition to the existing `correlation_id`, service, and environment fields.

#### Scenario: Request log carries trace identifiers
- **WHEN** an application log line is emitted during a traced HTTP request
- **THEN** the log contains `trace_id`, `span_id`, and the existing `correlation_id`

### Requirement: Request ID contract preserved on errors
Handled and unhandled API error responses SHALL continue to include `request_id` in the response body and `X-Request-ID` in the response headers.

#### Scenario: Handled error preserves request ID header
- **WHEN** an `AppException` is returned
- **THEN** the response body `request_id` matches the `X-Request-ID` response header
