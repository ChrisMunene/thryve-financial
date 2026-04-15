# Authentication Guide

This document describes the production auth foundation used by the PFM API.

The design goal is straightforward:

- one application-facing auth interface we own: `AuthService`
- one clear set of route dependencies for FastAPI
- no provider-specific details leaking into application code
- explicit local user and identity mapping
- strict JWT verification for bearer-token requests
- auth flows that are easy to extend later for B2B, SSO, and service accounts

## Core Principles

The auth layer is intentionally optimized for correctness and team ergonomics,
not cleverness.

- Application code talks to `AuthService`, not directly to Supabase or verifier classes.
- Protected routes use canonical dependencies from `app/dependencies.py`.
- Vendor subject IDs are external identifiers, not local user IDs.
- Local application users are stored in `users`.
- External provider identities are stored in `auth_identities`.
- Request authentication never auto-provisions local users from arbitrary valid tokens.
- Session-producing flows such as sign-in and refresh can create or link local users explicitly.

## Quick Reference

Use this decision matrix when adding or reviewing route code.

| If the route needs... | Use | Route receives |
| --- | --- | --- |
| no authentication | no auth dependency | nothing |
| an authenticated caller only | `Security(require_auth)` | `Principal` |
| an authenticated caller with scopes | `Depends(require_scopes(...))` | `Principal` |
| an authenticated caller with roles | `Depends(require_roles(...))` | `Principal` |
| the local application user plus auth context | `Depends(require_user)` | `AuthContext` |
| both authorization and the local user | `Depends(require_user)` plus `Depends(require_scopes(...))` or `Depends(require_roles(...))` | `AuthContext` |

Rules of thumb:

- If you need permissions, use `require_scopes(...)` or `require_roles(...)`.
- If you need the app-owned user and auth context together, use `require_user`.
- If you only need actor identity, use `require_auth`.
- If the route is public, do not add auth dependencies just for consistency.

## System Overview

The public auth surface is:

- `app/auth/service.py`
  `AuthService`, the auth facade used by the rest of the app
- `app/dependencies.py`
  `get_auth_service`, `require_auth`, `require_user`, `require_scopes`, `require_roles`
- `app/api/auth.py`
  backend-owned `/auth/*` endpoints

The provider-specific pieces are internal to the auth package:

- `app/auth/provider.py`
  internal provider contract
- `app/auth/supabase.py`
  Supabase adapter
- `app/auth/verifier.py`
  strict JWT verification
- `app/auth/jwks.py`
  JWKS fetch and cache

No non-auth application module should import provider adapters, verifier types, or vendor internals.

## Request Authentication Flow

For a normal protected API request, the flow is:

```text
Authorization: Bearer <access-token>
  -> get_bearer_token()
  -> require_auth()
  -> AuthService.authenticate_request()
  -> provider.verify_access_token()
  -> AuthIdentity lookup by (provider, issuer, subject_id)
  -> local User resolution
  -> trusted Principal
  -> route handler
  -> business service
```

Important detail:

- `Principal.user_id` comes from the local `auth_identities` mapping.
- It is not derived by parsing `subject_id` as a UUID.

That means a provider token is only accepted as an application user if the
identity has already been provisioned or linked through an explicit auth flow.

## Data Model

### `users`

`users` is the app-owned user table.

It represents the user as the application understands them.

Key fields include:

- `id`
- `email`
- `display_name`
- `email_verified_at`
- `is_active`
- `last_login_at`

### `auth_identities`

`auth_identities` maps an external provider identity to a local app user.

Key fields include:

- `user_id`
- `provider`
- `issuer`
- `subject_id`
- `email`
- `email_verified_at`
- `last_sign_in_at`
- `provider_metadata`

The unique identity key is:

- `(provider, issuer, subject_id)`

This is the foundation that lets us support future auth providers without
changing application business logic.

## Trusted Auth Objects

### `Principal`

`Principal` is the trusted caller context used for request-time authorization.

Important fields:

- `subject_id`
  external provider subject, always present
- `user_id`
  local application user id, always present for authenticated app users
- `actor_type`
  currently `"user"`, reserved for future service-account support
- `session_id`
  optional provider session identifier
- `tenant_id`
  optional hook for future B2B tenancy
- `roles`
- `scopes`
- `email`

Use `Principal` when route or service logic needs to know:

- who the actor is
- what scopes or roles they have
- what external identity performed the action

### `AuthenticatedUser`

`AuthenticatedUser` is the app-facing local user DTO returned by auth flows.

It contains:

- local user identity
- current roles and scopes
- linked auth identities

Use `AuthenticatedUser` when business logic needs the application user rather
than only the request principal.

### `AuthContext`

`AuthContext` is the route-facing authenticated user dependency returned by
`require_user`.

It contains:

- `user: AuthenticatedUser`
- `principal: Principal`

Use `AuthContext` for most protected business routes, where you usually need:

- the local application user for ownership or queries
- the principal for auth context, scopes, roles, or auditability

## The Auth Facade

`AuthService` is the single public auth interface the application owns.

Current public methods:

- `authenticate_request`
- `sign_up_with_password`
- `sign_in_with_password`
- `refresh_session`
- `request_password_reset`
- `confirm_password_reset`
- `request_email_verification`
- `confirm_email_verification`
- `logout`
- `get_current_user`
- `validate_configuration`

What `AuthService` owns:

- request authentication
- local user provisioning and linking
- identity lookup
- provider error normalization
- auth event logging
- backend auth flows used by `/auth/*`

What `AuthService` intentionally hides:

- Supabase request shapes
- JWT verification details
- JWKS fetch logic
- provider-specific response payloads

## Backend Auth API

The backend exposes these auth endpoints:

- `POST /api/v1/auth/sign-up/password`
- `POST /api/v1/auth/sign-in/password`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/password-reset/request`
- `POST /api/v1/auth/password-reset/confirm`
- `POST /api/v1/auth/email-verification/request`
- `POST /api/v1/auth/email-verification/confirm`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Response patterns:

- session-producing flows return `AuthSession`
- sign-up may return `PasswordSignUpResult`
- reset and verification request flows return a generic `AuthActionResult`
- `/auth/me` returns `AuthenticatedUser`

The API is intentionally backend-owned. Clients should integrate with these
endpoints instead of talking to the auth vendor directly.

## Canonical FastAPI Dependencies

The only route-facing auth dependencies that application code should use are:

- `require_auth`
- `require_user`
- `require_scopes`
- `require_roles`

They are all exposed from `app/dependencies.py`.

### `require_auth`

Use this when the route only needs an authenticated caller.

```python
from fastapi import APIRouter, Security

from app.auth.principal import Principal
from app.dependencies import require_auth

router = APIRouter()

@router.get("/profile-summary")
async def profile_summary(principal: Principal = Security(require_auth)):
    return {
        "user_id": str(principal.user_id),
        "subject_id": principal.subject_id,
        "email": principal.email,
    }
```

Use `require_auth` for:

- auth-only routes
- routes that only need actor identity
- routes that pass `Principal` into services

### `require_scopes`

Use this when the route needs authentication and one or more scopes.

```python
from fastapi import APIRouter, Depends

from app.auth.principal import Principal
from app.dependencies import require_scopes

router = APIRouter()

@router.post("/transactions/import")
async def import_transactions(
    principal: Principal = Depends(require_scopes("transactions:import")),
):
    return {"actor": principal.subject_id}
```

Important:

- `require_scopes(...)` already performs authentication.
- Do not stack `require_auth` and `require_scopes(...)` on the same route just to “be safe”.

### `require_roles`

Use this when the route is role-gated.

```python
from fastapi import APIRouter, Depends

from app.auth.principal import Principal
from app.dependencies import require_roles

router = APIRouter()

@router.get("/admin/audit-log")
async def audit_log(
    principal: Principal = Depends(require_roles("admin")),
):
    return {"actor": principal.subject_id}
```

### `require_user`

Use this when business logic needs the local application user and the trusted
principal together.

```python
from fastapi import APIRouter, Depends

from app.auth.auth_context import AuthContext
from app.dependencies import require_user

router = APIRouter()

@router.get("/auth/me")
async def me(
    auth_context: AuthContext = Depends(require_user),
):
    return auth_context.user
```

This is the recommended dependency when the route needs:

- the app-owned user id
- the linked auth identities
- the current user profile
- the principal for auth context

## Developer Cookbook

This section is the practical guide for day-to-day feature work.

### Scenario: public route

Do not add auth dependencies.

```python
@router.get("/healthz")
async def healthz():
    return {"ok": True}
```

Use this for:

- health checks
- public metadata endpoints
- webhook endpoints that authenticate through another mechanism

### Scenario: protected route that only needs to know the caller

Use `require_auth`.

```python
from fastapi import APIRouter, Security

from app.auth.principal import Principal
from app.dependencies import require_auth

router = APIRouter()

@router.get("/profile-summary")
async def profile_summary(principal: Principal = Security(require_auth)):
    return {
        "user_id": str(principal.user_id),
        "subject_id": principal.subject_id,
    }
```

### Scenario: protected route that needs the local app user

```python
from fastapi import APIRouter, Depends

from app.auth.auth_context import AuthContext
from app.dependencies import require_user

router = APIRouter()

@router.get("/profile")
async def profile(auth_context: AuthContext = Depends(require_user)):
    return auth_context.user
```

### Scenario: protected route that needs both permissions and the local user

Use `require_user` plus the appropriate authorization guard.

```python
from fastapi import APIRouter, Depends

from app.auth.auth_context import AuthContext
from app.dependencies import require_scopes, require_user

router = APIRouter()

@router.post("/budgets", dependencies=[Depends(require_scopes("budgets:write"))])
async def create_budget(
    auth_context: AuthContext = Depends(require_user),
):
    return {
        "subject_id": auth_context.principal.subject_id,
        "owner_user_id": str(auth_context.user.id),
    }
```

If you only need the guard and not the returned `Principal`, you can also put
`require_scopes(...)` or `require_roles(...)` in the route decorator
`dependencies=[...]`.

### Scenario: backend-owned auth route

Auth API routes should use `AuthService` directly through `get_auth_service`.

```python
from fastapi import APIRouter, Depends

from app.auth.service import AuthService
from app.dependencies import get_auth_service

router = APIRouter(prefix="/auth")

@router.post("/sign-in/password")
async def sign_in(payload: PasswordSignInRequest, auth_service: AuthService = Depends(get_auth_service)):
    return await auth_service.sign_in_with_password(
        email=payload.email,
        password=payload.password.get_secret_value(),
    )
```

Use this pattern for:

- sign-up
- sign-in
- refresh
- password reset
- email verification
- logout
- `/auth/me`

### Scenario: service layer needs actor identity

Pass the actor explicitly.

Good:

```python
result = await service.import_transactions(
    subject_id=principal.subject_id,
    access_token=payload.access_token.get_secret_value(),
)
```

Also good:

```python
result = await service.create_budget(
    user_id=auth_context.user.id,
    subject_id=auth_context.principal.subject_id,
    payload=payload,
)
```

Avoid:

- reading auth from `request.state` in normal service code
- decoding JWTs inside services
- reaching into provider internals from services

### Scenario: background jobs, scripts, or non-route app code need auth behavior

Use `AuthService`, not provider classes.

Typical examples:

- admin tooling that needs to inspect the current authenticated user
- future invitation or account-linking flows
- internal auth orchestration outside HTTP handlers

The rule is the same:

- application code depends on `AuthService`
- only the auth subsystem depends on `AuthProvider`

## Recommended Usage Patterns

These are the canonical patterns for the auth scenarios we care about today.

### Scenario: authenticated route with no extra authorization

Use:

- `Security(require_auth)`

Route receives:

- `Principal`

Best when:

- the service only needs actor identity
- the route only needs `subject_id`, `user_id`, roles, or scopes

### Scenario: authenticated route that needs scopes

Use:

- `Depends(require_scopes("some:scope"))`

Route receives:

- `Principal`

Best when:

- scope checks are the main authorization rule

### Scenario: authenticated route that needs roles

Use:

- `Depends(require_roles("admin"))`

Route receives:

- `Principal`

Best when:

- the route is admin-only or otherwise role-gated

### Scenario: route needs the local current user plus auth context

Use:

- `Depends(require_user)`

Route receives:

- `AuthContext`

Best when:

- business logic needs the local user profile
- you also want access to the principal without adding another dependency
- code should work with app-owned user identity rather than vendor subject ids

### Scenario: route needs both permissions and current user

Use both:

- `Depends(require_user)`
- `Depends(require_scopes(...))` or `Depends(require_roles(...))`

Example:

```python
from fastapi import APIRouter, Depends

from app.auth.auth_context import AuthContext
from app.dependencies import require_scopes, require_user

router = APIRouter()

@router.post("/reports/export", dependencies=[Depends(require_scopes("reports:export"))])
async def export_report(
    auth_context: AuthContext = Depends(require_user),
):
    return {
        "subject_id": auth_context.principal.subject_id,
        "user_id": str(auth_context.user.id),
    }
```

FastAPI dependency caching keeps this ergonomic. We still write route code in a
clear, explicit way without manually plumbing provider internals.

### Scenario: service layer needs the actor

Pass actor information explicitly into the service.

Good:

```python
result = await service.import_transactions(
    subject_id=principal.subject_id,
    access_token=payload.access_token.get_secret_value(),
)
```

Also good when the local user matters:

```python
result = await service.create_budget(
    user_id=auth_context.user.id,
    subject_id=auth_context.principal.subject_id,
    payload=payload,
)
```

Avoid hiding auth inside deep service calls by reading from `request.state` or
global context unless you are working on logging or middleware infrastructure.

### Scenario: authenticated request succeeds at JWT verification but has no local user mapping

Current behavior:

- request authentication fails
- the API returns `401 account_not_provisioned`

Why:

- a valid vendor identity is not automatically an application user
- local user access must be created through explicit auth flows

This is expected and correct behavior.

## Request State

`require_auth` stores a few trusted values on `request.state`:

- `request.state.principal`
- `request.state.subject_id`
- `request.state.user_id`

This is mainly for middleware, logging, and rare integration cases.

For normal application code, prefer explicit function parameters.

## When To Use `subject_id` vs `user_id`

Use `user_id` when:

- working with app-owned records
- assigning ownership in the local database
- writing business logic that is about the application user

Use `subject_id` when:

- you need the external provider identity
- you are correlating provider-side events or logs
- you need a stable external actor identifier

In many cases, passing both is appropriate:

- `user_id` for internal ownership
- `subject_id` for auditability and provider correlation

## Identity Provisioning Rules

This is a critical production rule:

- `authenticate_request` does not silently create local users.

Why:

- a valid vendor token should not automatically create access to the app
- user creation and account linking should happen in explicit auth flows
- this prevents accidental or unsafe provisioning paths

Provisioning and linking happen during:

- sign-up when a session is returned immediately
- sign-in
- refresh
- email verification confirmation
- future OAuth / SSO completion flows

## Extending The System

### Adding a new auth provider

Only the auth subsystem should know about this.

Typical steps:

1. Implement the internal `AuthProvider` contract in `app/auth/`.
2. Normalize vendor responses into provider DTOs such as `ProviderSession` and `ProviderUserProfile`.
3. Reuse or add strict token verification behind the provider adapter.
4. Wire the provider into `get_auth_service()`.
5. Keep route code, service code, and business logic unchanged.

This is the whole point of the facade: provider swaps should not ripple through the app.

### Adding new auth features

New auth features should be added:

- as public methods on `AuthService`
- as internal capabilities behind the provider adapter as needed
- without exposing vendor-specific request or response shapes to the app

## Error and Security Model

Security-sensitive behavior:

- bearer parsing is strict
- JWT verification checks signature, issuer, audience, lifetime, and key id
- security-critical claims are not synthesized
- password reset and email verification request endpoints return generic anti-enumeration responses
- auth endpoints are rate limited
- provider failures are normalized to safe application errors

Typical status behavior:

- `401`
  missing, invalid, expired, or unprovisioned auth
- `403`
  authenticated caller lacks required scope or role
- `503`
  auth infrastructure or provider is unavailable

## Testing Authenticated Code

Tests should override `get_auth_service`, not provider internals.

Example:

```python
from app.auth.mock import MockAuthService
from app.dependencies import get_auth_service

app.dependency_overrides[get_auth_service] = lambda: MockAuthService(
    roles=["admin"],
    scopes=["transactions:import"],
)
```

Why this is the recommended test seam:

- it matches the public app contract
- it keeps tests provider-agnostic
- it avoids coupling test code to JWT verification or vendor behavior

For deeper auth tests:

- use `MockAuthService` for route and contract tests
- use real `AuthService` plus a mock provider for auth integration tests
- avoid mocking verifier or provider internals in non-auth tests

## What To Avoid

Do not do these in application code:

- import `SupabaseAuthProvider`
- import provider contracts outside the auth package and DI wiring
- import verifier or JWKS types into routes or business services
- parse `Authorization` headers manually
- decode JWTs directly in route code
- infer local `user_id` by parsing `subject_id`
- silently provision app users during bearer-token request authentication

## Future Extensions

This design is intentionally consumer-first, but it already has the right hooks
for future growth:

- `tenant_id` on `Principal` and `AuthenticatedUser`
- `actor_type` for future service accounts
- provider-neutral identity mapping in `auth_identities`
- a single `AuthService` facade where SSO, invitations, org membership, and
  service-account flows can be added without leaking vendor details into the app

When new auth features are added, they should be exposed through `AuthService`
and implemented behind the internal `AuthProvider` contract.
