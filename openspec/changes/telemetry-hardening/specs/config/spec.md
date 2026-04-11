## ADDED Requirements

### Requirement: OTel-aligned observability configuration
The observability configuration SHALL use signal-specific, OpenTelemetry-aligned settings for traces and metrics. It SHALL expose separate exporters for traces, metrics, and logs, OTLP collector endpoint settings, batch processor tuning, metric export interval, excluded FastAPI URLs, and resource attributes.

#### Scenario: Collector-first staging configuration
- **WHEN** `ENVIRONMENT=staging`
- **THEN** traces and metrics use OTLP exporters and an OTLP collector endpoint is required

#### Scenario: Legacy keys rejected
- **WHEN** configuration is provided using legacy observability keys such as `exporter` or `endpoint`
- **THEN** startup validation fails with a clear error explaining the clean cutover

#### Scenario: Excluded URLs parsed from env
- **WHEN** `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` is provided as a comma-separated string
- **THEN** the observability settings expose the URLs as a parsed list usable by FastAPI instrumentation
