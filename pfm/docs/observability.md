# Observability Guide

This document explains the design of the logging and telemetry layers in this application, and how to use them correctly when building new features.

It covers:

- The overall design goals
- How logging works across the API and worker processes
- How traces and metrics work through the OpenTelemetry runtime
- How logs and telemetry fit together
- The expected feature-development patterns for routes, services, clients, and Celery tasks

## Goals

The observability stack is designed around a few core rules:

- One shared logging pipeline for app logs, stdlib logs, and worker logs
- One canonical access log event per HTTP request
- One shared OpenTelemetry runtime shape across API, worker, and beat
- Logs remain app-owned and go to stdout
- Traces and metrics export through OpenTelemetry
- Business workflow observability belongs in the application layer, not only in the web server or infrastructure libraries
- Sensitive data must never leak into logs or span attributes

In practice, that means:

- Uvicorn access logs are disabled
- The app emits the canonical `request.completed` event
- Celery does not hijack the root logger
- Structlog and stdlib logging share the same formatter and schema
- OpenTelemetry auto-instrumentation covers FastAPI, HTTPX, SQLAlchemy, Redis, and Celery
- Manual spans are used only at meaningful workflow boundaries

## System Overview

There are two parallel observability systems in this codebase:

- Logging:
  structured events written to stdout through the shared logging pipeline
- Telemetry:
  traces and metrics managed through OpenTelemetry in `app/core/telemetry/`

They are intentionally related, but not identical.

- Logging is the durable operational record used for request diagnostics, worker lifecycle visibility, and event search.
- Tracing is the causal execution graph used to understand cross-process flow and latency.
- Metrics are the aggregated signal used for alerts, dashboards, and throughput/error trends.

The application design is to correlate them through shared identifiers and shared resource metadata, not to collapse them into one system.

## Logging Design

### Bootstrap

Logging is bootstrapped by `configure_logging()` in `app/core/logging.py`.

Important properties:

- It is idempotent
- It is used by all process roles: API, worker, beat
- It uses `logging.config.dictConfig`
- It uses `structlog.stdlib.ProcessorFormatter`
- It unifies structlog events and ordinary `logging` records into one schema

Every process gets stable metadata on every record:

- `timestamp`
- `level`
- `event`
- `logger`
- `service`
- `environment`
- `version`
- `process_role`
- `process_id`

When request-local context is available, logs also get:

- `request_id`
- `user_id`
- `anonymous_id`
- `trace_id`
- `span_id`

### Format and Output

Environment controls whether logs render as JSON or console output.

- Development:
  console by default unless `LOG_FORMAT=json`
- Staging and production:
  JSON by default

Logs are written to stdout and are expected to be collected by the container/runtime/logging platform. We do not export logs through OpenTelemetry from the application process.

### Canonical HTTP Request Logging

The API owns request logging through `RequestLoggingMiddleware` in `app/middleware/request_logging.py`.

This middleware emits exactly one `request.completed` event for each non-skipped HTTP request.

Default behavior:

- Skip `OPTIONS`
- Skip health endpoints
- Log other requests at completion

The canonical request log includes:

- `method`
- `path`
- `route`
- `status_code`
- `duration_ms`
- request context fields when present

This is the canonical access log for the application. Uvicorn access logging is intentionally disabled so we do not end up with duplicate request logs or a second inconsistent schema.

### Error Logging

Error logs are intentionally separate from the completion log.

- `request.problem`:
  handled application problems
- `request.unhandled_exception`:
  unexpected failures
- `request.completed`:
  still emitted for the final response status

This gives us:

- one diagnostic event for the failure
- one canonical completion event for the request

### Worker Logging

Workers use the same logging pipeline as the API process.

Important task lifecycle events:

- `task.dispatched`
- `task.dispatch_failed`
- `task.started`
- `task.completed`
- `task.retrying`
- `task.failed`

These logs are emitted by app code and share the same formatter, schema, redaction rules, and process metadata as API logs.

### Redaction and Safety

The logging layer applies recursive redaction in `app/core/logging.py`.

Sensitive keys are redacted in nested dictionaries, lists, and tuples. Known secret-bearing fields include values like:

- `authorization`
- `token`
- `api_key`
- `apikey`
- `cookie`
- `password`
- `secret`

The following must not be logged in feature code:

- request bodies
- response bodies
- raw authorization payloads
- email addresses unless there is a strong product need and explicit approval
- secrets, tokens, cookies, API keys

The logging contract is intentionally conservative.

## Telemetry Design

### Bootstrap

Telemetry is bootstrapped from `app/core/telemetry/bootstrap.py`.

The runtime owns:

- tracer provider
- meter provider
- instrumentation lifecycle
- shutdown cleanup

There are three process roles:

- `api`
- `worker`
- `beat`

Each role gets a distinct service name through settings:

- `pfm-api`
- `pfm-worker`
- `pfm-beat`

That separation matters because it makes traces and dashboards easier to interpret across HTTP requests, background work, and scheduling.

### Export Model

Current export model:

- Traces:
  OpenTelemetry exporter
- Metrics:
  OpenTelemetry exporter
- Logs:
  application-managed stdout, not OTEL log export

Production and staging are collector-first. The application should point only at an OpenTelemetry Collector, not directly at a vendor endpoint.

### Auto-Instrumentation

The telemetry runtime instruments:

- FastAPI
- HTTPX
- SQLAlchemy
- Redis
- Celery

This gives us infrastructure-level spans and metrics without requiring app code to create them manually.

Examples:

- incoming HTTP request span
- outbound HTTP client span
- DB spans
- Redis spans
- Celery producer and consumer spans

### Manual Domain Spans

Auto-instrumentation gives strong infrastructure visibility, but it does not know where your business workflow begins and ends.

That is why the application also uses `operation_span()` in `app/core/telemetry/tracing.py`.

Use `operation_span()` for business workflow boundaries such as:

- `transactions.import`
- `categorization.execute`
- `idempotency.cleanup`

Do not use it for every helper function. The point is to create a clean high-level shape in traces, not a noisy trace with hundreds of tiny spans.

### Metrics

The metrics facade lives in `app/core/telemetry/metrics.py`.

This is the application-owned metrics layer, separate from the automatic OpenTelemetry instrumentation metrics.

Current application metrics include:

- `http.server.errors`
- `http.client.requests`
- `http.client.duration`
- `idempotency.requests`
- `idempotency.lease_steals`
- `worker.tasks.dispatched`
- `worker.tasks.in_flight`

Important rule:

- Only use allowed low-cardinality attributes when recording app metrics.

The metric facade validates allowed attributes for each metric so we do not accidentally create unbounded cardinality.

## How Logging and Telemetry Fit Together

Logs and telemetry share context, but they are not duplicates.

Examples of how they fit together:

- `request_id` appears in logs for search and correlation
- `trace_id` and `span_id` appear in logs when a span is active
- traces show cross-process causal flow
- metrics show aggregate rates and latency
- logs show exact structured events and diagnostic details

An example request flow looks like this:

1. Incoming API request creates a FastAPI server span
2. Application service creates a business span like `transactions.import`
3. Plaid client creates an HTTP client span and app emits `http.outbound`
4. `dispatch_task()` creates a short `task.enqueue` span and emits `task.dispatched`
5. Worker receives the task and Celery creates a consumer span
6. Task body creates a business span like `categorization.execute`
7. Task lifecycle logs and metrics reflect start, completion, retry, or failure

This is the intended model:

- auto-instrumentation explains infrastructure execution
- manual spans explain business workflows
- logs record application events

## Developer Guide

### The Standard Feature Pattern

When building a new feature, the preferred structure is:

1. API route:
   thin, validates input, calls a service, returns a response
2. Service:
   owns orchestration and business workflow span
3. Client:
   wraps an external dependency and relies on shared outbound logging and metrics
4. Worker task:
   owns background execution span and task-specific logs

The transaction import workflow is the reference implementation:

- Route:
  `app/api/transactions.py`
- Service:
  `app/services/transactions.py`
- Outbound client:
  `app/clients/plaid.py`
- Worker task:
  `app/workers/categorization_tasks.py`

### When to Log

Use structured application logs for:

- meaningful lifecycle events
- important state transitions
- dependency interactions
- retries
- failures
- background task publish/start/finish/failure

Good examples:

- `transactions.import_accepted`
- `http.outbound`
- `task.dispatched`
- `task.failed`
- `categorization.completed`

Do not log:

- every helper function entry/exit
- request or response bodies
- raw SQL
- secrets
- high-volume noisy debug events at `INFO`

### How to Log

Use structlog:

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "transactions.import_accepted",
    provider="plaid",
    task_id=task_id,
    imported_count=imported_count,
)
```

Rules:

- The event name should describe what happened
- Use stable field names
- Prefer app vocabulary over transport vocabulary where possible
- Keep values structured and machine-readable

Preferred field names:

- `request_id`
- `status_code`
- `task_name`
- `task_id`
- `dependency`
- `provider`
- `attempt`
- `duration_ms`

### When to Add a Manual Span

Add `operation_span()` when you are marking a business step, not a low-level implementation detail.

Good places:

- service orchestration methods
- a workflow boundary inside a task
- a meaningful multi-step operation

Good example:

```python
from app.core.telemetry import operation_span

with operation_span(
    "transactions.import",
    attributes={"provider": "plaid", "operation": "transactions.sync"},
) as span:
    result = await plaid_client.sync_transactions(...)
    if span.is_recording():
        span.set_attribute("imported_count", len(result.added))
```

Avoid using manual spans for:

- trivial property mapping
- one-line helpers
- code paths that are already fully described by a single infrastructure span

### Span Attribute Rules

Span attributes must be:

- low-cardinality
- safe to export
- useful for filtering and grouping

Good span attributes:

- `provider="plaid"`
- `operation="transactions.sync"`
- `task_name="app.workers.categorization_tasks.categorize_transactions"`
- `source="plaid"`
- `imported_count=42`
- `has_more=false`

Bad span attributes:

- email addresses
- raw access tokens
- request bodies
- response payloads
- free-form error detail copied from users
- large arrays or nested objects
- high-cardinality identifiers unless there is a very strong reason

Note that `request_id`, `user_id`, and `anonymous_id` already flow well through logs. Do not automatically mirror them into span attributes.

### How to Enqueue Tasks

Always enqueue application tasks through `dispatch_task()` in `app/workers/base.py`.

Why:

- it propagates `request_id`
- it injects trace context
- it emits `task.dispatched` and `task.dispatch_failed`
- it records `worker.tasks.dispatched`
- it creates the short `task.enqueue` domain span

Correct pattern:

```python
queued_task = dispatch_task(
    categorize_transactions_task,
    transactions=batch,
    source="plaid",
    apply_async_options={"queue": "default"},
)
```

Do not call `apply_async()` directly from feature code unless you are intentionally bypassing the shared observability contract.

### How to Write Worker Tasks

Worker tasks should:

- inherit from `BaseTask`
- add one business span around the actual task work
- emit only a few high-signal app logs
- return structured results when useful

Pattern:

```python
@celery_app.task(bind=True, base=BaseTask, name="app.workers.example.do_work")
def do_work(self, *, item_count: int) -> dict[str, int]:
    with operation_span(
        "example.execute",
        attributes={"task_name": self.name, "item_count": item_count},
    ) as span:
        processed = item_count
        if span.is_recording():
            span.set_attribute("processed_count", processed)

    logger.info("example.completed", processed_count=processed)
    return {"processed": processed}
```

### How to Build API Routes

Routes should stay thin.

Good route responsibilities:

- validate request payload
- resolve dependencies
- call the service
- return the response

Bad route responsibilities:

- orchestrating multiple dependency calls
- building Celery publish logic inline
- creating several business spans directly in the route
- duplicating logging that belongs in the service

The service layer is the preferred place for business spans and orchestration logs.

### How to Build External Clients

External clients should extend the shared client patterns whenever possible.

For HTTP-based dependencies:

- use `BaseClient`
- let it handle outbound request logging
- let it handle retry logging
- let it record outbound request metrics
- return typed response models

This keeps all outbound dependency observability consistent.

### Testing Expectations

When you add a feature with logs, spans, or metrics, add tests for the observability contract as part of the feature.

Typical expectations:

- route or service emits the expected business span
- task publish goes through `dispatch_task()`
- worker task creates its business span
- logs use the right event names
- metrics increment only on the intended success/failure path

The transaction import flow and categorization task tests are reference examples:

- `tests/test_api/test_transactions.py`
- `tests/test_workers/test_categorization_tasks.py`
- `tests/test_workers/test_base.py`

## Practical Checklist

Before merging a feature, check:

- Is the route thin?
- Is there one service-level business span if the workflow is meaningful?
- Are outbound calls going through the shared client layer?
- Are tasks enqueued through `dispatch_task()`?
- Does the worker task have one business span around the main operation?
- Are logs structured and high-signal?
- Are secrets and bodies excluded?
- Are metric attributes low-cardinality?
- Are tests asserting the observability contract where it matters?

## What Not To Do

Avoid these anti-patterns:

- using `logging.basicConfig()` anywhere in app code
- turning Uvicorn access logs back on
- calling Celery `apply_async()` directly in feature code without `dispatch_task()`
- adding span attributes with secrets or high-cardinality payloads
- logging raw request or response bodies
- adding dozens of tiny manual spans for helper functions
- exporting logs through OTEL from the app process in this codebase

## Summary

The design here is intentional:

- logs are app-owned structured events
- traces and metrics are OTEL-managed telemetry signals
- auto-instrumentation covers infrastructure
- manual spans cover business workflows
- services own orchestration
- workers own background execution

If contributors follow the route -> service -> client/task pattern and use `operation_span()` plus `dispatch_task()` consistently, new features will fit cleanly into the existing observability model.
