"""Bearer token parsing helpers."""

from __future__ import annotations

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AuthenticationRequiredError

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Bearer access token for the PFM API.",
)


async def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str:
    """Extract the bearer token from the request."""
    if credentials is None:
        raise AuthenticationRequiredError.missing_or_invalid_authorization_header()

    if credentials.scheme.lower() != "bearer":
        raise AuthenticationRequiredError.missing_or_invalid_authorization_header()

    token = credentials.credentials.strip()
    if not token:
        raise AuthenticationRequiredError.empty_bearer_token()

    return token
