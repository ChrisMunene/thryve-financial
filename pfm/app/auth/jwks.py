"""JWKS fetching and key caching."""

from __future__ import annotations

import asyncio
import time

import httpx
import jwt

from app.core.exceptions import AuthenticationRequiredError, DependencyUnavailableError


class JwksCache:
    """Async JWKS cache with TTL-based refresh."""

    def __init__(
        self,
        *,
        jwks_url: str,
        cache_ttl_seconds: int,
        refresh_timeout_seconds: float,
    ) -> None:
        self._jwks_url = jwks_url
        self._cache_ttl_seconds = cache_ttl_seconds
        self._refresh_timeout_seconds = refresh_timeout_seconds
        self._keys_by_kid: dict[str, dict] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_signing_key(self, kid: str) -> object:
        keys = await self._get_keys()
        jwk = keys.get(kid)
        if jwk is None:
            keys = await self._refresh_keys(force=True)
            jwk = keys.get(kid)
        if jwk is None:
            raise AuthenticationRequiredError.invalid_token(jwt_error_type="UnknownKeyId")
        return jwt.PyJWK.from_dict(jwk).key

    async def _get_keys(self) -> dict[str, dict]:
        now = time.monotonic()
        if self._keys_by_kid and now < self._expires_at:
            return self._keys_by_kid
        return await self._refresh_keys(force=False)

    async def _refresh_keys(self, *, force: bool) -> dict[str, dict]:
        async with self._lock:
            now = time.monotonic()
            if not force and self._keys_by_kid and now < self._expires_at:
                return self._keys_by_kid

            try:
                async with httpx.AsyncClient(timeout=self._refresh_timeout_seconds) as client:
                    response = await client.get(self._jwks_url)
                    response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise DependencyUnavailableError.for_service(
                    "auth",
                    detail="The auth keyset endpoint timed out.",
                    extra_log_context={"auth_reason": "jwks_timeout"},
                ) from exc
            except httpx.HTTPError as exc:
                raise DependencyUnavailableError.for_service(
                    "auth",
                    detail="The auth keyset endpoint is unavailable.",
                    extra_log_context={"auth_reason": "jwks_unavailable"},
                ) from exc

            try:
                payload = response.json()
            except ValueError as exc:
                raise DependencyUnavailableError.for_service(
                    "auth",
                    detail="The auth keyset response was not valid JSON.",
                    extra_log_context={"auth_reason": "jwks_invalid_json"},
                ) from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
                raise DependencyUnavailableError.for_service(
                    "auth",
                    detail="The auth keyset response was malformed.",
                    extra_log_context={"auth_reason": "jwks_malformed"},
                )

            parsed: dict[str, dict] = {}
            for item in payload["keys"]:
                if not isinstance(item, dict):
                    continue
                kid = item.get("kid")
                if isinstance(kid, str) and kid:
                    parsed[kid] = item

            if not parsed:
                raise DependencyUnavailableError.for_service(
                    "auth",
                    detail="The auth keyset did not contain any signing keys.",
                    extra_log_context={"auth_reason": "jwks_empty"},
                )

            self._keys_by_kid = parsed
            self._expires_at = time.monotonic() + self._cache_ttl_seconds
            return self._keys_by_kid
