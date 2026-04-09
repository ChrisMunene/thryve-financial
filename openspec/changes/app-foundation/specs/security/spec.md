## ADDED Requirements

### Requirement: CORS per environment
CORS middleware SHALL use allowed origins from configuration. Development: `["http://localhost:3000", "http://localhost:8080"]`. Production: explicit domain list. `allow_origins=["*"]` SHALL NOT be used outside development. Allowed methods, headers, and credentials SHALL be explicit.

#### Scenario: Dev CORS allows localhost
- **WHEN** a request from `http://localhost:3000` arrives in development
- **THEN** CORS headers are set allowing the origin

#### Scenario: Production blocks unknown origin
- **WHEN** a request from an unlisted origin arrives in production
- **THEN** the CORS preflight is rejected

### Requirement: Security headers
Middleware SHALL add the following headers to every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-Request-ID` (from correlation ID). In production, `Strict-Transport-Security: max-age=31536000; includeSubDomains` SHALL be added. Request body size SHALL be limited to 1MB by default (configurable per endpoint for file uploads). Requests exceeding 30 seconds SHALL be terminated.

#### Scenario: Security headers present
- **WHEN** any response is returned
- **THEN** X-Content-Type-Options, X-Frame-Options, and X-Request-ID headers are present

#### Scenario: HSTS in production only
- **WHEN** running in production
- **THEN** Strict-Transport-Security header is present
- **WHEN** running in development
- **THEN** Strict-Transport-Security header is NOT present

### Requirement: Rate limiting
Rate limiting SHALL be enforced per-user (by user_id after auth, or by IP for unauthenticated requests) and optionally per-endpoint. State SHALL be stored in Redis (sliding window counter). Default: 100 requests per minute per user (configurable per env). Responses SHALL include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers. When the limit is exceeded, the response SHALL be 429 with a `Retry-After` header and the standard error envelope.

#### Scenario: Under rate limit
- **WHEN** a user sends 50 requests within a minute (limit: 100)
- **THEN** all requests succeed and include rate limit headers showing 50 remaining

#### Scenario: Rate limit exceeded
- **WHEN** a user sends 101 requests within a minute
- **THEN** the 101st request returns 429 with Retry-After header and error envelope with code "RATE_LIMIT_EXCEEDED"

#### Scenario: Per-endpoint limit
- **WHEN** an endpoint has a custom limit of 10/minute and a user sends 11 requests
- **THEN** the 11th request returns 429, even if the user's global limit is not exceeded
