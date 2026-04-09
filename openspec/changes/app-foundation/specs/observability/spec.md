## ADDED Requirements

### Requirement: OpenTelemetry auto-instrumentation
The application SHALL configure OpenTelemetry at startup with auto-instrumentation for: FastAPI HTTP requests (spans with method, path, status), SQLAlchemy queries (spans with query duration), Redis operations (spans with command), and outbound httpx calls (spans with url, status). The exporter SHALL be configurable: `ConsoleSpanExporter` in development, `OTLPSpanExporter` in staging/production. Configuration SHALL be driven by the config system.

#### Scenario: HTTP request traced in dev
- **WHEN** a request hits GET /api/v1/health in development
- **THEN** a span is printed to console with method=GET, path=/api/v1/health, status=200, duration

#### Scenario: DB query traced
- **WHEN** a database query executes during request handling
- **THEN** a child span is created with the query duration and statement (parameterized, not raw values)

#### Scenario: Production exports via OTLP
- **WHEN** running in production with otel_exporter=otlp and otel_endpoint configured
- **THEN** spans are exported to the OTLP collector endpoint

### Requirement: Custom business metrics
A metrics API SHALL be available as a FastAPI dependency, wrapping the OTEL Meter API. It SHALL support `counter(name, value=1, attributes={})`, `histogram(name, value, attributes={})`, and `gauge(name, value, attributes={})`. Metric names SHALL follow the dot-notation convention (e.g., `transactions.categorized`).

#### Scenario: Increment a counter
- **WHEN** a service calls `metrics.counter("transactions.categorized", attributes={"method": "deterministic"})`
- **THEN** the OTEL counter is incremented and exported via the configured exporter

### Requirement: Event tracking with delegate pattern
An `AnalyticsService` SHALL provide `track(event: str, properties: dict, user_id: str | None)` and `identify(user_id: str, traits: dict)`. The service SHALL hold a `list[AnalyticsDelegate]` and iterate all delegates on each call. Delegates: `PostHogDelegate` (sends to PostHog API), `ConsoleDelegate` (logs to stdout in dev). Events SHALL be fired asynchronously (fire-and-forget via asyncio.create_task). Errors in delegates SHALL be logged but not raised. Event names SHALL follow `noun.verb` format (validated at call site).

#### Scenario: Event tracked to all delegates
- **WHEN** `analytics.track("transaction.categorized", {"method": "llm"}, user_id="abc")`
- **THEN** PostHogDelegate sends to PostHog and ConsoleDelegate logs to stdout

#### Scenario: Delegate failure doesn't break the request
- **WHEN** PostHogDelegate fails (network error)
- **THEN** the error is logged at WARNING and the request continues normally

#### Scenario: Invalid event name rejected
- **WHEN** `analytics.track("categorized transaction", ...)` is called (no dot notation)
- **THEN** a validation warning is logged

#### Scenario: Add a new delegate
- **WHEN** the team wants to add Amplitude tracking
- **THEN** an `AmplitudeDelegate` is created and added to the delegates list in config; no app code changes
