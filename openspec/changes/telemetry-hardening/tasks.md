## 1. OpenSpec and config cutover

- [x] 1.1 Create a new OpenSpec change for telemetry hardening with proposal, design, tasks, and spec deltas
- [x] 1.2 Replace legacy observability config keys with OTel-aligned per-signal settings
- [x] 1.3 Add validation for collector-first staging/production rules and reject non-`none` OTEL log exporters in this refactor
- [x] 1.4 Add `.env.example` and README guidance for the new observability config

## 2. Shared telemetry runtime

- [x] 2.1 Replace the single telemetry module with a package exposing bootstrap functions and `TelemetryRuntime`
- [x] 2.2 Instrument FastAPI, SQLAlchemy, Redis, and HTTPX through the shared runtime
- [x] 2.3 Add Celery worker/beat bootstrap and shutdown wiring with role-specific service names
- [x] 2.4 Preserve health/docs exclusion and low-cardinality request propagation attributes

## 3. Logging and metrics hardening

- [x] 3.1 Inject `trace_id` and `span_id` into structured logs when spans are active
- [x] 3.2 Preserve `X-Request-ID` on handled and unhandled error responses
- [x] 3.3 Replace the string-based metrics helper with a registry-backed `AppMetrics` facade
- [x] 3.4 Propagate W3C trace context through Celery task dispatch alongside correlation IDs

## 4. Tests and documentation

- [x] 4.1 Rewrite config tests for the clean observability cutover
- [x] 4.2 Add telemetry runtime tests for API bootstrap, worker bootstrap, and metric validation
- [x] 4.3 Add logging tests for trace/log correlation
- [x] 4.4 Add worker helper tests for correlation and trace header propagation
