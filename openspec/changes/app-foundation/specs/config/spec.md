## ADDED Requirements

### Requirement: Multi-environment configuration
The application SHALL support three environments: development, staging, and production, controlled by an `ENVIRONMENT` env var. Settings SHALL be organized into nested groups (database, redis, auth, plaid, anthropic, observability, app). The settings object SHALL be a singleton resolved once at startup via `@lru_cache`. All environment-specific behavioral differences SHALL be expressed through config values — no `if environment == "production"` conditionals in application code.

#### Scenario: App starts in development
- **WHEN** `ENVIRONMENT=development` is set
- **THEN** debug is True, SQL echo is on, OTEL exports to console, CORS allows localhost origins

#### Scenario: App starts in production
- **WHEN** `ENVIRONMENT=production` is set
- **THEN** debug is False, SQL echo is off, OTEL exports via OTLP, CORS allows only specified domains

### Requirement: Startup validation
The application SHALL validate all configuration on startup and crash immediately if a required value is missing or malformed. Required values in staging/production include: database URL, Redis URL, auth secret, Plaid credentials, Anthropic API key. In development, sensible defaults SHALL be provided for local infrastructure (matching docker-compose).

#### Scenario: Missing required config in production
- **WHEN** `ENVIRONMENT=production` and `ANTHROPIC_API_KEY` is not set
- **THEN** the application fails to start with a clear error message identifying the missing variable

#### Scenario: Development starts with defaults
- **WHEN** `ENVIRONMENT=development` and no `.env` file exists
- **THEN** the application starts using default values that work with docker-compose (postgres://localhost, redis://localhost)

### Requirement: Database pool tuning per environment
The database connection pool SHALL be configured per environment: small pool (5 connections, 5 overflow) in development, larger pool (20 connections, 10 overflow) in production. Pool settings SHALL be configurable via environment variables.

#### Scenario: Development pool size
- **WHEN** running in development
- **THEN** SQLAlchemy engine uses pool_size=5, max_overflow=5

#### Scenario: Production pool size
- **WHEN** running in production
- **THEN** SQLAlchemy engine uses pool_size=20, max_overflow=10

### Requirement: Decimal precision for monetary values
All monetary values in SQLAlchemy models SHALL use `Numeric(precision=12, scale=2)` via a `DecimalMixin` or column type helper. Float SHALL NOT be used for any monetary column. A `MoneyColumn` helper SHALL be available for model definitions.

#### Scenario: Money stored as Decimal
- **WHEN** a transaction amount of $19.99 is stored
- **THEN** the database column stores it as Decimal("19.99"), not float 19.99

### Requirement: Soft delete mixin
A `SoftDeleteMixin` SHALL be available for SQLAlchemy models. It adds a `deleted_at` nullable timestamp column. Models using the mixin SHALL provide query helpers to filter out soft-deleted records by default while allowing explicit inclusion when needed.

#### Scenario: Soft delete a record
- **WHEN** a record with SoftDeleteMixin is soft-deleted
- **THEN** `deleted_at` is set to the current timestamp and the record is excluded from default queries

#### Scenario: Query includes soft-deleted
- **WHEN** a query explicitly requests soft-deleted records
- **THEN** records with non-null `deleted_at` are included in results

### Requirement: Alembic naming convention
Migration files SHALL follow the naming convention `YYYY_MM_DD_HHMM_short_description`. Alembic SHALL read the database URL from the same config system as the application. Autogenerate SHALL be wired to the SQLAlchemy Base metadata. Down-migrations SHALL be required during development.

#### Scenario: Migration file created
- **WHEN** `alembic revision --autogenerate -m "add transactions"` is run
- **THEN** the file is named like `2026_04_07_1430_add_transactions.py`
