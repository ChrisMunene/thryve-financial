## ADDED Requirements

### Requirement: Structured JSON logging
All application logs SHALL be structured JSON with consistent fields: timestamp, level, message, correlation_id, service, environment. The logging library SHALL be structlog. Log level SHALL be configurable per environment (DEBUG in dev, INFO in staging, WARNING in production). Loggers SHALL be obtained via `structlog.get_logger()`.

#### Scenario: Log output in production
- **WHEN** a log statement is emitted in production
- **THEN** the output is a single JSON line with timestamp, level, message, correlation_id, service="pfm", environment="production"

#### Scenario: Log level filtering
- **WHEN** running in production with log_level=WARNING
- **THEN** DEBUG and INFO messages are not emitted

### Requirement: Sensitive field redaction
The logging system SHALL automatically redact any field whose key contains: "password", "secret", "token", "ssn", "api_key", "authorization", or "credit_card". Redacted values SHALL be replaced with `"[REDACTED]"` before the log line is rendered.

#### Scenario: Token redacted in log
- **WHEN** a log line includes `{"authorization": "Bearer sk-ant-xxx"}`
- **THEN** the output contains `{"authorization": "[REDACTED]"}`

### Requirement: Correlation ID middleware
Every inbound request SHALL be assigned a UUID4 correlation ID, stored in a `contextvars.ContextVar`. If the request includes an `X-Request-ID` header, that value SHALL be used instead. The correlation ID SHALL be automatically included in: all log lines, error responses, outbound HTTP request headers, and background task payloads.

#### Scenario: Correlation ID generated
- **WHEN** a request arrives without X-Request-ID header
- **THEN** a UUID4 is generated, stored in the contextvar, and included in all logs for that request

#### Scenario: Correlation ID accepted
- **WHEN** a request arrives with `X-Request-ID: abc-123`
- **THEN** "abc-123" is used as the correlation ID

#### Scenario: Correlation ID in response
- **WHEN** any response is returned
- **THEN** the `X-Request-ID` header is set to the correlation ID

#### Scenario: Correlation ID propagated to background task
- **WHEN** a Celery task is dispatched from a request handler
- **THEN** the task receives the correlation ID and uses it in its own log lines

#### Scenario: Correlation ID in outbound calls
- **WHEN** the external service client makes an outbound HTTP call
- **THEN** the `X-Request-ID` header is set to the current correlation ID
