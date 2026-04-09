## 1. Multi-Environment Config

- [x] 1.1 Rewrite app/config.py: define Environment enum (development/staging/production), nested config groups (DatabaseConfig, RedisConfig, AuthConfig, PlaidConfig, AnthropicConfig, ObservabilityConfig, AppConfig), all reading from env vars via pydantic-settings
- [x] 1.2 Add startup validators: required fields in staging/prod (auth secret, API keys, plaid credentials), sensible defaults for development matching docker-compose
- [x] 1.3 Singleton access via @lru_cache get_settings() function
- [x] 1.4 Update .env.example with all config groups and ENVIRONMENT var
- [x] 1.5 Write tests: dev loads with defaults, prod crashes without required vars, settings are singleton

## 2. Database Hardening

- [x] 2.1 Update app/db/session.py: pool_size and max_overflow from config (5/5 dev, 20/10 prod), engine configured per environment
- [x] 2.2 Add MoneyColumn helper to app/models/base.py: Numeric(precision=12, scale=2) column type for monetary values
- [x] 2.3 Add SoftDeleteMixin to app/models/base.py: deleted_at nullable timestamp, with_deleted() query helper
- [x] 2.4 Verify get_db dependency auto-commits on success, auto-rolls-back on exception
- [x] 2.5 Write tests: pool size matches config, Decimal storage roundtrips correctly, soft delete filters work

## 3. Alembic Hardening

- [x] 3.1 Update alembic/env.py to read database URL from get_settings()
- [x] 3.2 Configure file naming convention: YYYY_MM_DD_HHMM_short_description via file_template in alembic.ini
- [x] 3.3 Verify autogenerate works with the Base metadata import

## 4. Structured Logging

- [x] 4.1 Add structlog to dependencies in pyproject.toml
- [x] 4.2 Create app/core/logging.py: configure structlog with JSON renderer, processors for timestamp, log level, correlation_id, service name, environment
- [x] 4.3 Implement sensitive field redaction processor: keys containing password/secret/token/ssn/api_key/authorization/credit_card → "[REDACTED]"
- [x] 4.4 Configure log level from settings (DEBUG dev, INFO staging, WARNING prod)
- [x] 4.5 Initialize logging in FastAPI lifespan startup
- [x] 4.6 Write tests: JSON output format, redaction works, correlation_id attached, log level filtering

## 5. Request Context & Correlation IDs

- [x] 5.1 Create app/core/context.py: ContextVar for correlation_id, get/set helpers
- [x] 5.2 Create correlation ID middleware: generate UUID4 or accept X-Request-ID header, store in contextvar, set X-Request-ID response header
- [x] 5.3 Wire correlation_id into structlog processor (reads from contextvar)
- [x] 5.4 Write tests: generated when missing, accepted from header, present in response header, present in log output

## 6. Error Handling & Response Envelope

- [x] 6.1 Create app/core/exceptions.py: AppException base class, NotFoundError, ValidationError, AuthenticationError, AuthorizationError, RateLimitError, ExternalServiceError, IdempotencyConflictError — each with status_code, error_code, message, details
- [x] 6.2 Create app/core/responses.py: Response[T] generic, ErrorResponse, ErrorDetail, PaginatedResponse[T] with meta.pagination, PaginationMeta
- [x] 6.3 Register global exception handler on FastAPI app: catches AppException → error envelope, catches Exception → logs full trace + returns 500 envelope. Stack trace in response in dev only.
- [x] 6.4 Write tests: each exception returns correct status code + envelope, unhandled exception returns 500, dev shows trace, prod hides trace

## 7. Authentication

- [x] 7.1 Create app/auth/delegate.py: AuthDelegate Protocol (verify_token, refresh_token), TokenPayload Pydantic model
- [x] 7.2 Create app/auth/schemas.py: CurrentUser Pydantic model (user_id UUID, email str, roles list[str], metadata dict)
- [x] 7.3 Create app/auth/supabase.py: SupabaseAuthDelegate implementing AuthDelegate — JWT verification with PyJWT, JWKS key rotation support
- [x] 7.4 Create app/auth/mock.py: MockAuthDelegate — returns configurable CurrentUser for any token
- [x] 7.5 Create app/auth/service.py: AuthService wrapping delegate — logging, analytics tracking, error wrapping → returns CurrentUser
- [x] 7.6 Create get_current_user dependency in app/dependencies.py: extracts Bearer token, calls AuthService.authenticate
- [x] 7.7 Create require_role(*roles) composable dependency in app/dependencies.py
- [x] 7.8 Add PyJWT and cryptography to dependencies in pyproject.toml
- [x] 7.9 Write tests: valid token returns CurrentUser, expired token returns 401, missing token returns 401, role check passes/fails correctly, mock delegate works in tests

## 8. Security Middleware

- [x] 8.1 Create app/core/security.py: security headers middleware — X-Content-Type-Options, X-Frame-Options, X-Request-ID, HSTS (prod only)
- [x] 8.2 Add CORS middleware in app/main.py: origins from config, explicit methods/headers
- [x] 8.3 Add request body size limit (1MB default from config)
- [x] 8.4 Add request timeout (30s default from config)
- [x] 8.5 Write tests: security headers present in responses, HSTS only in prod, CORS allows configured origins, rejects unconfigured

## 9. Rate Limiting

- [x] 9.1 Create app/core/rate_limit.py: Redis sliding window counter implementation — per-key limit check with window size
- [x] 9.2 Create rate limit middleware: extract user_id (or IP if unauthenticated), check global limit, add X-RateLimit-* headers to response, return 429 with Retry-After + error envelope on exceed
- [x] 9.3 Create per-endpoint rate limit dependency: `rate_limit(limit=10, window=60)` decorator/dependency for custom limits
- [x] 9.4 Limits configurable from config (default per env), overridable per tier (future)
- [x] 9.5 Write tests: under limit passes with headers, over limit returns 429 with Retry-After, per-endpoint limit works independently of global

## 10. OpenTelemetry

- [x] 10.1 Add OTEL dependencies: opentelemetry-sdk, opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-sqlalchemy, opentelemetry-instrumentation-redis, opentelemetry-instrumentation-httpx, opentelemetry-exporter-otlp (optional)
- [x] 10.2 Create app/core/telemetry.py: configure TracerProvider and MeterProvider, set exporter from config (console/otlp), instrument FastAPI, SQLAlchemy, Redis, httpx
- [x] 10.3 Initialize OTEL in FastAPI lifespan startup, flush on shutdown
- [x] 10.4 Create custom metrics dependency: counter, histogram, gauge wrappers over OTEL Meter API
- [x] 10.5 Write tests: OTEL configured without errors, metrics dependency injectable

## 11. Event Tracking

- [x] 11.1 Create app/core/analytics.py: AnalyticsDelegate Protocol (track, identify), AnalyticsService with list[AnalyticsDelegate], fire-and-forget via asyncio.create_task, event name validation (noun.verb format)
- [x] 11.2 Create app/core/analytics_posthog.py: PostHogDelegate implementation
- [x] 11.3 Create app/core/analytics_console.py: ConsoleDelegate — logs events to structlog
- [x] 11.4 Add posthog to dependencies in pyproject.toml
- [x] 11.5 Wire AnalyticsService into DI: configured from settings (dev: console only, staging/prod: posthog + console)
- [x] 11.6 Write tests: track calls all delegates, identify calls all delegates, delegate failure doesn't propagate, invalid event name logs warning

## 12. Health Checks

- [x] 12.1 Rewrite app/api/health.py: GET /health (shallow, 200 if alive), GET /health/ready (deep: check DB SELECT 1, Redis PING, auth JWKS fetch — each with 2s timeout)
- [x] 12.2 Return 503 during graceful shutdown (reads shutdown flag)
- [x] 12.3 Write tests: healthy returns 200, unhealthy DB returns 503 with detail, shutdown returns 503

## 13. Idempotency

- [x] 13.1 Create app/core/idempotency.py: Redis-backed idempotency — check key, acquire lock, store response, handle concurrent duplicates
- [x] 13.2 Create require_idempotency FastAPI dependency: extracts Idempotency-Key header, checks/stores via idempotency module
- [x] 13.3 Configurable TTL from settings (default 24h)
- [x] 13.4 Write tests: first request executes and stores, duplicate returns cached, concurrent duplicates handled, missing key executes normally, non-opt-in endpoints ignore header

## 14. Background Task Hardening

- [x] 14.1 Create base task class in app/workers/base.py: auto-retry with configurable backoff (3 attempts, 60/120/240s), correlation ID injection from task headers, structured logging of start/success/failure
- [x] 14.2 Configure DLQ: tasks exhausting retries routed to dead-letter queue
- [x] 14.3 Configure priority queues in celery_app.py: default, high, low
- [x] 14.4 Add correlation ID dispatch: when dispatching a task from request context, inject correlation_id into task headers
- [x] 14.5 Write tests: retry logic works, correlation ID propagated, task logged on success/failure

## 15. Graceful Shutdown

- [x] 15.1 Add shutdown flag (contextvar or module-level) set on lifespan shutdown
- [x] 15.2 Update lifespan shutdown: close SQLAlchemy engine, close Redis, flush OTEL buffers, log completion
- [x] 15.3 Health readiness check reads shutdown flag → returns 503
- [x] 15.4 Celery worker graceful shutdown: worker_shutting_down signal handler
- [x] 15.5 Write tests: shutdown flag set on lifespan exit, health returns 503 after shutdown

## 16. External Service Client

- [x] 16.1 Create app/clients/base.py: BaseClient wrapping httpx.AsyncClient — configurable timeout, max_retries, backoff. Retry on 5xx/network errors only. Correlation ID in X-Request-ID header. Structured logging with sensitive header redaction. Error translation to ExternalServiceError.
- [x] 16.2 Create app/clients/plaid.py: PlaidClient extending BaseClient — Plaid API methods (stubbed for now, implemented in categorization-engine change)
- [x] 16.3 Create app/clients/anthropic.py: AnthropicClient extending BaseClient — wraps Anthropic SDK with BaseClient logging/retry patterns
- [x] 16.4 Write tests: retry on 5xx, no retry on 4xx, correlation ID propagated, sensitive headers redacted, ExternalServiceError raised on failure

## 17. Testing Infrastructure

- [x] 17.1 Update tests/conftest.py: test database (pfm_test), async engine, per-test transaction rollback fixture
- [x] 17.2 Create test fixtures: get_test_db session, override get_db dependency, override auth with MockAuthDelegate, override analytics with ConsoleDelegate
- [x] 17.3 Create tests/factories.py: create_user(), create_transaction() with sensible defaults and overrides
- [x] 17.4 Verify all foundation tests pass: config, logging, correlation IDs, error handling, auth, security, rate limiting, health checks, idempotency, external client

## 18. Pagination

- [x] 18.1 Create app/core/pagination.py: PaginationParams dependency (parses cursor + limit, clamps limit to max 100), cursor encode/decode helpers (base64 of created_at + id)
- [x] 18.2 Wire PaginationMeta into PaginatedResponse in responses.py
- [x] 18.3 Write tests: first page returns cursor, next page uses cursor, limit clamped, last page has has_more=false

## 19. Integration & Cleanup

- [x] 19.1 Wire all middleware in correct order in app/main.py: correlation ID → logging → security headers → CORS → error handler → auth (on endpoints, not global)
- [x] 19.2 Update docker-compose.yml if needed (test database, any new services)
- [x] 19.3 Update README.md with foundation architecture, new config groups, delegate patterns, testing patterns
- [x] 19.4 Run full test suite, verify all passing
- [x] 19.5 Verify app starts cleanly in dev (docker-compose up, uvicorn, hit /health and /health/ready)
