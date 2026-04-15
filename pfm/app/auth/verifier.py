"""Token verification interfaces and implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import jwt
from pydantic import ValidationError

from app.auth.claims import VerifiedClaims
from app.auth.jwks import JwksCache
from app.core.exceptions import AuthenticationRequiredError


@runtime_checkable
class TokenVerifier(Protocol):
    """Protocol for strict access-token verification."""

    async def verify_token(self, token: str) -> VerifiedClaims:
        """Verify an access token and return normalized claims."""
        ...

    def validate_configuration(self) -> None:
        """Validate verifier configuration for readiness checks."""
        ...


class JwtVerifier:
    """Strict JWT verifier backed by a JWKS cache."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: Sequence[str],
        required_claims: Sequence[str],
        clock_skew_seconds: int,
        jwks_cache: JwksCache,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._algorithms = tuple(algorithms)
        self._required_claims = tuple(required_claims)
        self._clock_skew_seconds = clock_skew_seconds
        self._jwks_cache = jwks_cache

    async def verify_token(self, token: str) -> VerifiedClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthenticationRequiredError.invalid_token(
                jwt_error_type=type(exc).__name__
            ) from exc

        algorithm = header.get("alg")
        if algorithm not in self._algorithms:
            raise AuthenticationRequiredError.invalid_token(
                jwt_error_type="UnsupportedAlgorithm"
            )

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthenticationRequiredError.invalid_token(jwt_error_type="MissingKeyId")

        key = await self._jwks_cache.get_signing_key(kid)

        try:
            payload = jwt.decode(
                token,
                key=key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={
                    "require": list(self._required_claims),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationRequiredError.token_expired() from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationRequiredError.invalid_token(
                jwt_error_type=type(exc).__name__
            ) from exc

        try:
            return VerifiedClaims.model_validate(payload)
        except ValidationError as exc:
            raise AuthenticationRequiredError.invalid_token(
                jwt_error_type="ClaimsValidationError"
            ) from exc

    def validate_configuration(self) -> None:
        if not self._issuer:
            raise RuntimeError("AUTH_ISSUER or AUTH_SUPABASE_URL is required for auth readiness")
        if not self._audience:
            raise RuntimeError("AUTH_AUDIENCE is required for auth readiness")
        if not self._algorithms:
            raise RuntimeError("AUTH_ACCEPTED_ALGORITHMS is required for auth readiness")
        if not self._required_claims:
            raise RuntimeError("AUTH_REQUIRED_CLAIMS is required for auth readiness")
