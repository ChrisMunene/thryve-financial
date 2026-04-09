## ADDED Requirements

### Requirement: Test database with transaction rollback
Tests SHALL use a separate `pfm_test` Postgres database. Each test SHALL run inside a database transaction that is rolled back after the test completes, ensuring no test pollution. The test database fixture SHALL create the async engine, run Alembic migrations, and provide a session that auto-rolls-back.

#### Scenario: Test isolation
- **WHEN** Test A creates a user and Test B queries all users
- **THEN** Test B does not see Test A's user (transaction was rolled back)

### Requirement: Async test client
An `httpx.AsyncClient` fixture with `ASGITransport` SHALL be configured for testing FastAPI endpoints. All dependency overrides (mock auth, test DB session) SHALL be applied before the client is created.

#### Scenario: Test sends authenticated request
- **WHEN** a test uses the `client` fixture and sends a request with a Bearer token
- **THEN** MockAuthDelegate processes the token and returns the configured test user

### Requirement: Mock delegates auto-wired in tests
Every delegate (AuthDelegate, AnalyticsDelegate) SHALL have a mock/test implementation. These SHALL be automatically registered via `app.dependency_overrides` in the test fixtures, so tests never hit real external services.

#### Scenario: Analytics events in tests
- **WHEN** a test triggers code that calls `analytics.track(...)`
- **THEN** ConsoleDelegate logs the event; PostHogDelegate is not called

### Requirement: Factory functions
Test factories SHALL be available for creating model instances with sensible defaults and overrides: `create_user(**overrides)`, `create_transaction(**overrides)`. Factories SHALL insert into the test database and return the created instance.

#### Scenario: Create test user with override
- **WHEN** `create_user(email="test@example.com")` is called
- **THEN** a user is inserted into the test DB with the specified email and default values for all other fields
