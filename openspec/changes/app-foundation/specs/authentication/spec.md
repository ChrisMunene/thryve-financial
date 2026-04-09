## ADDED Requirements

### Requirement: Auth delegate pattern
Authentication SHALL be implemented via a delegate pattern. An `AuthService` (what the app sees) wraps an `AuthDelegate` (Protocol) with methods: `verify_token(token: str) -> TokenPayload` and `refresh_token(token: str) -> str`. The service handles cross-cutting concerns (logging, event tracking, error wrapping). The delegate handles vendor-specific implementation. Swapping vendors requires changing only the delegate registration.

#### Scenario: Authenticate a request
- **WHEN** a request with `Authorization: Bearer <token>` arrives
- **THEN** AuthService calls delegate.verify_token, logs "user.authenticated", tracks an analytics event, and returns a CurrentUser object

#### Scenario: Swap auth provider
- **WHEN** the team decides to switch from Supabase to Clerk
- **THEN** only the delegate implementation changes; AuthService, get_current_user, and all application code remain unchanged

### Requirement: Supabase auth delegate
A `SupabaseAuthDelegate` SHALL implement the `AuthDelegate` protocol using Supabase JWT verification (PyJWT with JWKS key rotation support). It SHALL validate the JWT signature, expiry, and issuer.

#### Scenario: Valid Supabase token
- **WHEN** a valid Supabase JWT is presented
- **THEN** the delegate returns a TokenPayload with user_id, email, and metadata

#### Scenario: Expired token
- **WHEN** an expired JWT is presented
- **THEN** the delegate raises AuthenticationError

### Requirement: Mock auth delegate for tests
A `MockAuthDelegate` SHALL be available that returns a configurable `TokenPayload` for any token. It SHALL be automatically wired into the DI container during tests.

#### Scenario: Test with authenticated user
- **WHEN** a test sends a request with any Bearer token
- **THEN** MockAuthDelegate returns the configured test user without network calls

### Requirement: CurrentUser typed object
The `get_current_user` dependency SHALL return a `CurrentUser` Pydantic model with fields: user_id (UUID), email (str), roles (list[str]), metadata (dict). No raw dicts or untyped token payloads SHALL be used in application code.

#### Scenario: Endpoint accesses current user
- **WHEN** an endpoint uses `user: CurrentUser = Depends(get_current_user)`
- **THEN** it receives a typed object with user_id, email, and roles

### Requirement: Authorization dependencies
The application SHALL provide composable authorization dependencies: `require_role(*roles)` returns a dependency that checks `current_user.roles` and raises `AuthorizationError(403)` if the user lacks the required role. Deny-by-default: endpoints without `get_current_user` are public; all others require a valid token.

#### Scenario: User lacks required role
- **WHEN** an endpoint requires `require_role("admin")` and the user has roles `["user"]`
- **THEN** a 403 response is returned with error code "FORBIDDEN"

#### Scenario: User has required role
- **WHEN** an endpoint requires `require_role("user")` and the user has roles `["user"]`
- **THEN** the request proceeds normally
