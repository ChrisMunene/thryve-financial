## Context

We have a scaffolded FastAPI project at `pfm/` with basic config, SQLAlchemy async session, Alembic, Redis client, Celery beat schedule, and pytest. The categorization engine taxonomy and mappings are implemented and tested (40 passing tests). But the scaffolding is a skeleton — it lacks the infrastructure required to safely deploy a fintech application.

This design covers the 22 foundation pillars that must be in place before any user-facing feature ships.

## Goals / Non-Goals

**Goals:**
- Every foundation pillar implemented and tested
- No vendor lock-in on auth, analytics, or event tracking — delegate pattern everywhere
- Trivial to add/remove vendors or change implementations without touching app code
- Crash-fast on misconfiguration — the app should fail at startup, not at runtime
- Every request traceable end-to-end via correlation IDs (request → logs → tasks → outbound calls)
- Financial-grade reliability: idempotent mutations, Decimal precision, graceful shutdown
- Developer experience: writing a new endpoint should be straightforward, tests easy to write

**Non-Goals:**
- Feature flags (trivial to add via DI when needed)
- Audit logging (correction_events serves as domain audit; generic system deferred to compliance phase)
- Secrets manager integration (env vars on Railway sufficient; add AWS SSM when moving to AWS)
- Full RBAC (all users equal at launch; auth returns roles field ready for when tiers ship)

## Decisions

### 1. Multi-environment config: grouped Pydantic settings with validation

**Decision:** Single `Settings` class with nested groups (database, redis, auth, plaid, anthropic, observability, app). Three environments: development, staging, production — controlled by `ENVIRONMENT` env var. Singleton via `@lru_cache`. Validators crash the process on startup if required values are missing or malformed.

**Config groups:**
```python
class DatabaseConfig:
    url, pool_size, pool_overflow, echo

class RedisConfig:
    url, cache_ttl

class AuthConfig:
    supabase_jwt_secret, supabase_url (required in staging/prod)

class PlaidConfig:
    client_id, secret, env

class AnthropicConfig:
    api_key, model, max_retries

class ObservabilityConfig:
    otel_exporter (console/otlp), otel_endpoint, log_level, posthog_api_key

class AppConfig:
    environment (dev/staging/prod), debug, cors_origins, rate_limit_default
```

**Behavioral differences via config, not conditionals:**
- `debug=True` in dev → stack traces in error responses, SQL echo on
- `otel_exporter=console` in dev → traces to stdout. `otlp` in prod → to collector
- `cors_origins=["http://localhost:3000"]` in dev → `["https://app.example.com"]` in prod

No `if environment == "production"` anywhere in application code.

### 2. Database hardening

**Decision:** Existing async SQLAlchemy session stays. Add:
- Pool size from config: 5 in dev, 20 in prod, overflow proportional
- `DecimalMixin` for monetary columns: `Numeric(precision=12, scale=2)` — never float
- `SoftDeleteMixin`: `deleted_at` nullable timestamp, query helpers to filter
- `get_db` dependency auto-commits on success, auto-rolls-back on exception (already done, verify)

### 3. Alembic hardening

**Decision:** Naming convention for migration files: `YYYY_MM_DD_HHMM_short_description`. Alembic reads DB URL from the same config system. Autogenerate wired to Base metadata (already done). Down-migrations required during development.

### 4. Structured logging

**Decision:** Python `structlog` library for JSON-structured logging. Processors chain: add timestamp, add log level, add correlation ID (from contextvar), add environment, add service name, redact sensitive fields, render as JSON.

**Sensitive field redaction:** Any log field containing "password", "secret", "token", "ssn", "api_key", or "authorization" is automatically replaced with `"[REDACTED]"`.

**Logger access:** Via `structlog.get_logger()` — standard structlog pattern. No custom factory needed.

### 5. Correlation IDs

**Decision:** `contextvars.ContextVar` stores the correlation ID. Middleware assigns a UUID4 or accepts from `X-Request-ID` header. The contextvar is read by: structlog processors (auto-attached to logs), error handler (included in error responses), Celery task dispatch (passed as task header), outbound HTTP calls (set as `X-Request-ID` header via base client).

### 6. Exception hierarchy and error handler

**Decision:** Base `AppException` with fields: status_code, error_code (string), message (user-facing), details (optional list). Subclasses:
- `NotFoundError(404, "RESOURCE_NOT_FOUND")`
- `ValidationError(422, "VALIDATION_ERROR")`
- `AuthenticationError(401, "AUTHENTICATION_FAILED")`
- `AuthorizationError(403, "FORBIDDEN")`
- `RateLimitError(429, "RATE_LIMIT_EXCEEDED")`
- `ExternalServiceError(502, "EXTERNAL_SERVICE_ERROR")`
- `IdempotencyConflictError(409, "IDEMPOTENCY_CONFLICT")`

Global handler registered on FastAPI: catches `AppException` → returns envelope. Catches unhandled `Exception` → logs ERROR with full trace, returns 500 envelope. In dev: includes stack trace in response. In prod: error code + message only.

### 7. Response envelope

**Decision:** Pydantic generics:
```python
class Response(BaseModel, Generic[T]):
    data: T
    meta: dict | None = None

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[str] | None = None
    request_id: str | None = None

class ErrorResponse(BaseModel):
    error: ErrorDetail

class PaginatedResponse(Response[list[T]], Generic[T]):
    # meta.pagination populated automatically
```

Endpoints return the inner type; a response middleware or utility wraps it in the envelope. Error handler returns `ErrorResponse`.

### 8. Authentication — delegate pattern

**Decision:**
- `AuthDelegate` (Protocol): `verify_token(token: str) -> TokenPayload`, `refresh_token(token: str) -> str`
- `SupabaseAuthDelegate`: implements the protocol using Supabase JWT verification (PyJWT + JWKS)
- `MockAuthDelegate`: returns a configurable test user, used in tests
- `AuthService`: wraps delegate. On `authenticate`: calls `delegate.verify_token`, logs `user.authenticated`, tracks analytics event, returns `CurrentUser` Pydantic model. On failure: raises `AuthenticationError`.
- `get_current_user` dependency: extracts `Authorization: Bearer <token>` header, calls `AuthService.authenticate`, returns `CurrentUser`.
- `CurrentUser`: user_id (UUID), email, roles (list[str]), metadata (dict)

### 9. Authorization

**Decision:** Composable dependencies:
- `require_role(*roles)` → returns a dependency that checks `current_user.roles`
- `require_permission(permission)` → for future ABAC extension
- Resource-level: services check `user_id == resource.owner_id` explicitly — not a framework concern

Deny-by-default: endpoints that don't use `get_current_user` are public. All others require a valid token.

### 10. CORS

**Decision:** FastAPI `CORSMiddleware` with `allow_origins` from config. Dev: `["http://localhost:3000", "http://localhost:8080"]`. Prod: explicit domain list. Never `["*"]` outside dev.

### 11. Security headers

**Decision:** Custom middleware adds: `Strict-Transport-Security` (prod only), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Request-ID` (from correlation ID). Request body size limit: 1MB default (configurable). Request timeout: 30s.

### 12. Rate limiting

**Decision:** Custom middleware (not slowapi — it's unmaintained). Redis-backed with sliding window counter.
- Per-user limits (identified by user_id after auth, or IP for unauthenticated)
- Per-endpoint limits via dependency decorator
- Global backstop: 100 req/s per user default (configurable)
- Returns 429 with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- Limits configurable per env and overridable per subscription tier (future)

### 13. OpenTelemetry

**Decision:** OTEL SDK with auto-instrumentation packages:
- `opentelemetry-instrumentation-fastapi` (HTTP spans)
- `opentelemetry-instrumentation-sqlalchemy` (DB query spans)
- `opentelemetry-instrumentation-redis` (cache spans)
- `opentelemetry-instrumentation-httpx` (outbound call spans)

Configured at startup in lifespan handler. Exporter from config: `ConsoleSpanExporter` in dev, `OTLPSpanExporter` in staging/prod. Trace context propagated to Celery tasks.

Custom business metrics: OTEL Meter API. Injected as dependency. Example: `metrics.counter("transactions.categorized", attributes={"method": "deterministic"})`.

No abstraction layer — OTEL is the standard.

### 14. Event tracking — delegate pattern

**Decision:**
- `AnalyticsDelegate` (Protocol): `track(event: str, properties: dict, user_id: str | None)`, `identify(user_id: str, traits: dict)`
- `PostHogDelegate`: sends to PostHog API
- `ConsoleDelegate`: logs to stdout (dev)
- `AnalyticsService`: holds `list[AnalyticsDelegate]`, iterates all on each call. Fire-and-forget (asyncio.create_task, errors logged not raised). Naming convention enforced: `noun.verb` format validated at call site.

### 15. Health checks

**Decision:**
- `GET /health` — returns 200 `{"status": "healthy"}`. No dependency checks. Used by load balancer liveness probe.
- `GET /health/ready` — checks DB (SELECT 1), Redis (PING), auth provider (JWKS fetch). Each with 2s timeout. Returns 200 with dependency breakdown if all pass, 503 if any fail. Used by readiness probe.

### 16. Idempotency

**Decision:** Middleware/dependency that intercepts `Idempotency-Key` header on POST/PUT/PATCH:
- Key present + seen in Redis → return cached response (exact same status code + body)
- Key present + not seen → acquire Redis lock, execute endpoint, store response with configurable TTL (default 24h), release lock, return response
- Key absent → execute normally (no idempotency)
- Concurrent duplicates: Redis lock prevents double execution. Second request waits briefly, then returns cached response.

Opt-in via dependency: `idempotent: None = Depends(require_idempotency)` on endpoints that need it.

### 17. Celery hardening

**Decision:** Build on existing celery_app.py. Add:
- Base task class with: automatic retry (3 attempts, exponential backoff), correlation ID injection from task headers, structured logging per task
- DLQ: failed tasks after all retries routed to a dead-letter queue for manual inspection
- Priority queues: `default`, `high` (real-time categorization), `low` (batch reports)
- Graceful shutdown: `worker_shutdown` signal handler, finish current task, don't ack new ones

### 18. Graceful shutdown

**Decision:** FastAPI lifespan `shutdown` event:
1. Set shutdown flag (health readiness returns 503)
2. Wait for in-flight requests (configurable timeout, default 15s)
3. Close SQLAlchemy engine (drains connection pool)
4. Close Redis connection
5. Flush OTEL spans and metrics
6. Log shutdown complete

Celery workers: `worker_shutting_down` signal, finish current task, stop consuming.

### 19. External service client

**Decision:** `BaseClient` class wrapping `httpx.AsyncClient`:
- Configurable timeout, max retries, backoff factor
- Automatic retry on 5xx and network errors (not on 4xx)
- Correlation ID injected as `X-Request-ID` header on every outbound call
- Structured logging: request method/url/duration logged at INFO, response status logged, full body logged at DEBUG. Sensitive headers (`Authorization`, `X-Api-Key`) auto-redacted.
- On non-2xx: raises `ExternalServiceError` with service name, status code, and response body (truncated)

Concrete clients:
- `PlaidClient(BaseClient)`: Plaid API methods, token exchange, transaction fetch
- `AnthropicClient(BaseClient)`: LLM categorization call (wraps the Anthropic SDK but uses BaseClient patterns for logging/retry)

### 20. Testing infrastructure

**Decision:**
- Test database: same Postgres, separate `pfm_test` database. Fixture creates async engine, runs migrations, wraps each test in a transaction that rolls back.
- `client` fixture: httpx.AsyncClient with ASGITransport, dependency overrides applied
- `MockAuthDelegate`: returns configurable `CurrentUser`, auto-wired in test DI
- `ConsoleAnalyticsDelegate`: already the dev delegate, also used in tests
- Factory functions: `create_user(**overrides)`, `create_transaction(**overrides)` — return model instances with sensible defaults
- Override pattern: `app.dependency_overrides[get_auth_service] = lambda: mock_auth_service`

### 21. API versioning

**Decision:** Already using `/api/v1/` prefix. Documented as the pattern. When v2 is needed, create a separate router mounted at `/api/v2/`. V1 continues to work. Deprecation header strategy documented in README.

### 22. Pagination

**Decision:** Cursor-based as default:
- `PaginationParams` dependency: parses `cursor` and `limit` query params (default limit 20, max 100)
- Returns `PaginationMeta(cursor: str | None, has_more: bool)` in response envelope meta
- Cursor is an opaque base64-encoded string (typically the last item's created_at + id for deterministic ordering)
- Offset-based available as separate dependency for admin/reporting endpoints

## Risks / Trade-offs

**[Foundation scope vs feature velocity]** → 22 pillars is substantial work (~2 weeks). But every pillar prevents a class of production incidents. The alternative — building features on a weak foundation — compounds technical debt and creates incidents that are harder to fix than the foundation work itself.

**[Custom rate limiter vs library]** → Building a simple Redis sliding window counter (~50 lines) instead of using slowapi (unmaintained). Risk: edge cases in distributed rate limiting. Mitigation: thorough tests, conservative defaults.

**[OTEL overhead in dev]** → Auto-instrumentation adds overhead. Mitigation: console exporter in dev is lightweight. Can disable entirely via config if it becomes annoying.

**[structlog dependency]** → Adding structlog rather than using stdlib logging. Risk: another dependency. Benefit: dramatically better structured logging with minimal code. structlog is mature (10+ years), widely used, and unlikely to be abandoned.
