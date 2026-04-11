## Why

The current telemetry implementation is functional but not production-hardened. It is API-only, configured through an app-specific OTEL surface, lacks role-specific runtime bootstrap for Celery, does not inject trace identifiers into logs, and exposes an unbounded string-based metrics API.

That leaves three operational gaps:
- staging/production can drift away from a collector-first topology;
- workers do not share the same telemetry bootstrap contract as the API;
- application metrics and log correlation are too loose for incident response and long-term maintenance.

## What Changes

- Replace the single-file telemetry setup with a shared telemetry package and explicit runtime handle for API, worker, and beat processes.
- Cut over observability config to signal-specific, OTel-aligned fields and require OTLP traces/metrics in staging and production.
- Add trace/log correlation while preserving the external `X-Request-ID` contract.
- Replace the open-ended metrics singleton with a registry-backed `AppMetrics` facade.
- Add tests, README guidance, and a new `.env.example` that document the clean cutover.

## Impact

- Breaking config change: legacy observability keys such as `exporter` and `endpoint` are removed.
- FastAPI and Celery now share the same telemetry bootstrap model, but logs remain on stdout/stderr in every environment.
- The OpenSpec delta updates observability, logging/context, and config requirements without reopening `app-foundation`.
