## ADDED Requirements

### Requirement: Shared telemetry runtime for API and workers
The application SHALL bootstrap telemetry through a shared runtime abstraction used by the FastAPI API process and by Celery worker and beat processes. The runtime SHALL own provider construction, library instrumentation, and shutdown behavior.

#### Scenario: API bootstrap creates API-scoped resource
- **WHEN** the FastAPI application starts
- **THEN** telemetry resources use the API service name and instrument FastAPI plus common libraries

#### Scenario: Worker bootstrap creates worker-scoped resource
- **WHEN** a Celery worker process starts
- **THEN** telemetry resources use the worker service name and instrument Celery plus common libraries

### Requirement: Collector-first production export
In staging and production, traces and metrics SHALL export to an OpenTelemetry Collector via OTLP. Logs SHALL remain on stdout/stderr and SHALL NOT be exported through OTLP in this refactor.

#### Scenario: Health and docs routes excluded from tracing
- **WHEN** FastAPI telemetry is configured
- **THEN** `/api/v1/health`, `/api/v1/health/ready`, `/docs`, and `/openapi.json` are excluded from request tracing

### Requirement: Registry-backed application metrics
Application metrics SHALL be recorded through a registry-backed facade that permits only declared metric names and whitelisted low-cardinality attributes.

#### Scenario: Invalid metric attribute rejected
- **WHEN** application code records a registered metric with an undeclared attribute key
- **THEN** the metrics facade rejects the call instead of emitting the metric

#### Scenario: Task dispatch preserves correlation and trace headers
- **WHEN** a Celery task is dispatched from request context
- **THEN** the task headers include both the correlation ID and W3C trace propagation headers
