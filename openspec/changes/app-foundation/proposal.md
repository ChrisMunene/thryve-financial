## Why

The PFM backend is scaffolded (FastAPI, SQLAlchemy, Redis, Celery, basic pytest) but not production-ready. It lacks multi-environment config, structured logging, authentication, error handling, observability, idempotency, rate limiting, and the delegate patterns needed for vendor-agnostic services. This is a fintech app handling bank account data and real money — the reliability, traceability, and security bar is higher than a typical SaaS. Every feature built on a weak foundation inherits its weaknesses. This change builds the foundation before any feature work ships.

## What Changes

- Rewrite config system: multi-environment (dev/staging/prod), grouped settings, startup validation, singleton access
- Harden database layer: connection pool tuning per env, Decimal/integer-cents for money, soft delete mixin
- Harden Alembic: naming convention, env-aware config
- Add structured JSON logging with context injection (correlation ID, user ID, env), sensitive field redaction
- Add request correlation IDs via contextvar middleware, propagated to logs, tasks, and outbound calls
- Add exception hierarchy (AppException → NotFound, Validation, Authentication, Authorization, RateLimit, ExternalService) with global error handler
- Add standardized response envelope: `Response[T]` for success, error envelope for failures, pagination meta slot
- Add authentication via delegate pattern: AuthService + AuthDelegate protocol + SupabaseAuthDelegate + get_current_user dependency
- Add authorization: deny-by-default, require_role/require_permission composable dependencies
- Add CORS middleware configured per environment
- Add security headers middleware (HSTS, X-Frame-Options, X-Content-Type-Options, request size limits)
- Add rate limiting: per-user + per-endpoint, Redis-backed, 429 + Retry-After + X-RateLimit headers
- Add OpenTelemetry: auto-instrument HTTP, DB, Redis, outbound HTTP. Console exporter in dev, OTLP in prod.
- Add event tracking via delegate pattern: AnalyticsService + PostHogDelegate + ConsoleDelegate. Fire-and-forget.
- Add health checks: shallow liveness (GET /health) + deep readiness (GET /health/ready) with dependency status
- Add idempotency layer: Redis-backed, Idempotency-Key header, opt-in per endpoint, concurrent duplicate handling
- Harden Celery: typed inputs, retry with backoff, DLQ, correlation ID propagation, priority queues, graceful shutdown
- Add graceful shutdown in FastAPI lifespan: drain requests, close pools, flush buffers
- Add external service client base: retries, timeouts, correlation propagation, logging, error translation. PlaidClient and AnthropicClient inherit from it.
- Harden testing: test DB with transaction rollback, factories, mock delegates auto-wired via DI
- Add cursor-based pagination as reusable dependency, wired into response envelope

## Capabilities

### New Capabilities
- `config`: Multi-environment configuration system with grouped settings, startup validation, and singleton access
- `logging-and-context`: Structured JSON logging, request correlation IDs, sensitive field redaction, context propagation to background tasks
- `error-handling`: Exception hierarchy, global error handler, standardized response envelope with pagination support
- `authentication`: Auth service with delegate pattern, Supabase delegate, CurrentUser typed object, authorization dependencies
- `security`: CORS, security headers, rate limiting (Redis-backed)
- `observability`: OpenTelemetry auto-instrumentation, event tracking with delegate pattern (PostHog + console)
- `health-checks`: Shallow liveness and deep readiness endpoints with dependency status
- `reliability`: Idempotency layer, hardened Celery (retries, DLQ, correlation IDs, graceful shutdown), external service client base pattern
- `testing`: Test database lifecycle, factories, mock delegates, DI override infrastructure
- `pagination`: Cursor-based pagination dependency, wired into response envelope

### Modified Capabilities

(none — existing scaffolding is being replaced/hardened, not modified incrementally)

## Impact

- **Replaces** existing `app/config.py`, `app/db/session.py`, `app/db/redis.py`, `app/models/base.py`, `app/main.py`, `app/api/router.py`, `app/workers/celery_app.py`, `tests/conftest.py`
- **Adds** `app/core/` (logging, context, exceptions, responses, security), `app/auth/` (service, delegate, supabase), `app/clients/` (base, plaid, anthropic), `app/middleware/`
- **Dependencies added**: opentelemetry-sdk, opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-sqlalchemy, opentelemetry-instrumentation-redis, opentelemetry-instrumentation-httpx, posthog, slowapi or custom rate limiter
- **All existing engine code** (`app/engine/taxonomy.py`, `app/engine/mappings.py`) and tests are unaffected — they have no framework dependency
