## ADDED Requirements

### Requirement: Shallow liveness check
`GET /health` SHALL return 200 `{"status": "healthy"}` if the process is alive. It SHALL NOT touch the database, Redis, or any external service. It SHALL respond in under 10ms. Used by load balancer liveness probes.

#### Scenario: Process is alive
- **WHEN** GET /health is called
- **THEN** 200 is returned with `{"status": "healthy"}`

### Requirement: Deep readiness check
`GET /health/ready` SHALL verify connectivity to all critical dependencies: database (SELECT 1), Redis (PING), and auth provider (JWKS endpoint fetch). Each check SHALL have a 2-second timeout. The response SHALL list each dependency and its status. If all pass: 200 with `{"status": "healthy", "dependencies": {"database": "ok", "redis": "ok", "auth": "ok"}}`. If any fail: 503 with the failing dependency marked.

#### Scenario: All dependencies healthy
- **WHEN** GET /health/ready is called and DB, Redis, and auth are reachable
- **THEN** 200 with all dependencies listed as "ok"

#### Scenario: Database unreachable
- **WHEN** GET /health/ready is called and the database connection times out
- **THEN** 503 with `{"status": "unhealthy", "dependencies": {"database": "timeout", "redis": "ok", "auth": "ok"}}`

#### Scenario: During graceful shutdown
- **WHEN** GET /health/ready is called after the shutdown signal
- **THEN** 503 is returned regardless of dependency status
