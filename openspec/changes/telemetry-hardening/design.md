## Context

The existing `app/core/telemetry.py` configures OpenTelemetry for FastAPI only. It sets providers globally, instruments common libraries in-place, and exposes an unbounded string-based metrics helper. Worker and beat processes have no equivalent bootstrap, and structured logs carry correlation IDs but not span identifiers.

This change hardens telemetry around a process runtime boundary rather than a single setup function.

## Decisions

### 1. Shared runtime bootstrap

Telemetry bootstraps through an explicit runtime handle:
- `bootstrap_api_telemetry(app, settings) -> TelemetryRuntime`
- `bootstrap_worker_telemetry(process_role, settings) -> TelemetryRuntime`
- `TelemetryRuntime.shutdown()`

The runtime owns providers, instrumentation cleanup, and app-specific FastAPI uninstrumentation. The API process instruments FastAPI plus common libraries. Worker and beat processes instrument common libraries plus Celery.

### 2. Collector-first config surface

Observability settings move to OTel-aligned, per-signal fields:
- `traces_exporter`
- `metrics_exporter`
- `logs_exporter`
- `otlp_endpoint` with per-signal overrides
- batch processor tuning, metric export interval, excluded URLs, and resource attributes

Production policy:
- staging and production require `traces_exporter=otlp`
- staging and production require `metrics_exporter=otlp`
- `logs_exporter` remains `none` in this refactor

Legacy `exporter` and `endpoint` keys are rejected to make the cutover explicit.

### 3. Log and request correlation

The existing `X-Request-ID` contract remains unchanged for inbound requests, outbound HTTP, task dispatch, and error responses. Structured logs gain `trace_id` and `span_id` when a valid span is active. Logs continue to emit via structlog to stdout/stderr instead of OTLP logs.

### 4. Registry-backed metrics

`get_metrics()` remains the DI entry point, but returns `AppMetrics`, a facade over predeclared metric definitions. It supports:
- validated `counter()`
- validated `histogram()`
- validated `up_down_counter()`
- typed helper methods for outbound requests and task dispatch/in-flight tracking

Only registered metric names and whitelisted attributes are accepted.
