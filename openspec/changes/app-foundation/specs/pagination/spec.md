## ADDED Requirements

### Requirement: Cursor-based pagination dependency
A reusable `PaginationParams` FastAPI dependency SHALL parse `cursor` (optional str) and `limit` (optional int, default 20, max 100) from query parameters. It SHALL be usable on any list endpoint via `pagination: PaginationParams = Depends(get_pagination)`.

#### Scenario: First page request
- **WHEN** GET /api/v1/transactions?limit=10 is called without a cursor
- **THEN** the first 10 results are returned with a cursor for the next page

#### Scenario: Next page request
- **WHEN** GET /api/v1/transactions?cursor=abc123&limit=10 is called
- **THEN** results starting after the cursor position are returned

#### Scenario: Limit clamped to max
- **WHEN** GET /api/v1/transactions?limit=500 is called
- **THEN** limit is clamped to 100

### Requirement: Pagination in response envelope
Paginated responses SHALL include pagination metadata in the response envelope: `meta.pagination.cursor` (opaque string for next page, null if no more), `meta.pagination.has_more` (bool). The cursor SHALL be a base64-encoded string (typically encoding created_at + id for deterministic ordering).

#### Scenario: Has more results
- **WHEN** there are more results beyond the current page
- **THEN** `meta.pagination.has_more` is true and `meta.pagination.cursor` is a non-null string

#### Scenario: Last page
- **WHEN** there are no more results
- **THEN** `meta.pagination.has_more` is false and `meta.pagination.cursor` is null

### Requirement: API versioning pattern
All API routes SHALL be mounted under `/api/v1/`. When v2 is needed, a separate router SHALL be created and mounted at `/api/v2/`. V1 SHALL continue to function. Deprecated versions SHALL return a `Deprecation` header with a sunset date.

#### Scenario: V1 routes accessible
- **WHEN** GET /api/v1/health is called
- **THEN** the v1 health endpoint responds

#### Scenario: Versioned routing
- **WHEN** v2 routes are added in the future
- **THEN** /api/v1/ and /api/v2/ coexist independently
