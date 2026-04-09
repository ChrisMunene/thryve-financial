## ADDED Requirements

### Requirement: Idempotency layer
Mutating endpoints (POST, PUT, PATCH) SHALL support an `Idempotency-Key` header. When present: if the key has been seen in Redis, return the stored response (exact status code + body) without re-executing. If not seen, acquire a Redis lock, execute the endpoint, store the response (configurable TTL, default 24h), release the lock. When absent, execute normally. Concurrent duplicate requests SHALL be handled via Redis lock — the second request waits briefly then returns the cached response. Idempotency SHALL be opt-in per endpoint via a FastAPI dependency.

#### Scenario: First request with idempotency key
- **WHEN** POST /api/v1/corrections with `Idempotency-Key: abc-123` is called for the first time
- **THEN** the endpoint executes, the response is stored in Redis, and the response is returned

#### Scenario: Duplicate request with same key
- **WHEN** POST /api/v1/corrections with `Idempotency-Key: abc-123` is called again
- **THEN** the stored response is returned without re-executing the endpoint

#### Scenario: Concurrent duplicate requests
- **WHEN** two requests with the same idempotency key arrive simultaneously
- **THEN** one acquires the lock and executes; the other waits and returns the cached response

#### Scenario: Endpoint without idempotency
- **WHEN** a POST endpoint that doesn't opt in receives an Idempotency-Key header
- **THEN** the header is ignored and the endpoint executes normally

### Requirement: Celery hardened tasks
Celery tasks SHALL use a base task class that provides: automatic retry with configurable exponential backoff (default: 3 attempts, 60s/120s/240s delays), correlation ID injection from task headers into structlog context, structured logging of task start/success/failure. Tasks that fail after all retries SHALL be routed to a dead-letter queue. Priority queues SHALL be available: `default`, `high` (real-time categorization), `low` (batch reports). Task inputs SHALL be typed via Pydantic schemas.

#### Scenario: Task retries on failure
- **WHEN** a Celery task raises an exception
- **THEN** it retries up to 3 times with exponential backoff (60s, 120s, 240s)

#### Scenario: Task exhausts retries
- **WHEN** a task fails on all 3 retry attempts
- **THEN** it is routed to the dead-letter queue with full error context

#### Scenario: Correlation ID in task logs
- **WHEN** a Celery task executes that was dispatched from a request with correlation_id "abc-123"
- **THEN** all log lines within the task include correlation_id="abc-123"

#### Scenario: High priority task
- **WHEN** a real-time categorization task is dispatched
- **THEN** it is sent to the `high` priority queue and processed before `default` queue tasks

### Requirement: Graceful shutdown
On receiving a shutdown signal, the FastAPI application SHALL: (1) set a shutdown flag causing health readiness to return 503, (2) stop accepting new requests, (3) wait for in-flight requests to complete (configurable timeout, default 15s), (4) close the SQLAlchemy connection pool, (5) close Redis connections, (6) flush OTEL span and metric buffers, (7) log shutdown complete. Celery workers SHALL finish their current task and stop consuming new ones on shutdown signal.

#### Scenario: Clean shutdown
- **WHEN** SIGTERM is sent to the API process
- **THEN** in-flight requests complete, connections are closed, and the process exits cleanly

#### Scenario: Shutdown timeout exceeded
- **WHEN** in-flight requests don't complete within 15 seconds
- **THEN** the process force-exits

#### Scenario: Health returns 503 during shutdown
- **WHEN** GET /health/ready is called after shutdown signal received
- **THEN** 503 is returned

### Requirement: External service client base
A `BaseClient` class SHALL wrap `httpx.AsyncClient` and provide: configurable timeout and max retries, automatic retry on 5xx and network errors (not on 4xx) with exponential backoff, correlation ID injected as `X-Request-ID` on every outbound call, structured logging of request method/url/duration at INFO (response body at DEBUG), automatic redaction of sensitive headers (`Authorization`, `X-Api-Key`), and error translation — non-2xx responses raise `ExternalServiceError` with service name, status code, and truncated response body. Concrete clients (PlaidClient, AnthropicClient) SHALL extend BaseClient.

#### Scenario: Outbound call succeeds
- **WHEN** PlaidClient calls the Plaid API and receives a 200
- **THEN** the request is logged at INFO with method, url, duration, and status

#### Scenario: Outbound call retried on 5xx
- **WHEN** the Anthropic API returns a 503
- **THEN** the client retries with exponential backoff up to max_retries

#### Scenario: Outbound call fails with 4xx
- **WHEN** the Plaid API returns a 400 (bad request)
- **THEN** the client does NOT retry and raises ExternalServiceError immediately

#### Scenario: Correlation ID propagated
- **WHEN** an outbound call is made from a request with correlation_id "abc-123"
- **THEN** the outbound request includes header `X-Request-ID: abc-123`

#### Scenario: Authorization header redacted in logs
- **WHEN** an outbound call with Authorization header is logged
- **THEN** the log shows `Authorization: [REDACTED]`
