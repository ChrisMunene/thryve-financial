"""
Base external service client.

Wraps httpx.AsyncClient with:
- Retries with exponential backoff (5xx and network errors only)
- Timeout enforcement
- Correlation ID propagation (X-Request-ID header)
- Structured logging with sensitive header redaction
- Error translation to ExternalServiceError
"""

import asyncio
import time

import httpx
import structlog

from app.core.context import get_correlation_id
from app.core.exceptions import ExternalServiceError
from app.core.telemetry import get_metrics

logger = structlog.get_logger()

SENSITIVE_HEADERS = {"authorization", "x-api-key", "x-secret", "cookie"}


def _redact_headers(headers: dict) -> dict:
    return {
        k: "[REDACTED]" if k.lower() in SENSITIVE_HEADERS else v
        for k, v in headers.items()
    }


class BaseClient:
    """Base client for external service communication.

    Concrete clients (PlaidClient, AnthropicClient) extend this.
    """

    def __init__(
        self,
        base_url: str,
        service_name: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> None:
        self._base_url = base_url
        self._service_name = service_name
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with retries, logging, and error handling."""

        # Inject correlation ID
        headers = kwargs.pop("headers", {})
        correlation_id = get_correlation_id()
        if correlation_id:
            headers["X-Request-ID"] = correlation_id
        kwargs["headers"] = headers

        last_exception = None

        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                response = await self._client.request(method, path, **kwargs)
                duration = time.monotonic() - start
                duration_ms = round(duration * 1000)

                logger.info(
                    "http.outbound",
                    service=self._service_name,
                    method=method,
                    path=path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                    headers=_redact_headers(dict(kwargs.get("headers", {}))),
                )
                get_metrics().record_outbound_request(
                    service=self._service_name,
                    method=method,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )

                # Retry on 5xx
                if response.status_code >= 500 and attempt < self._max_retries:
                    logger.warning(
                        "http.outbound.retrying",
                        service=self._service_name,
                        status=response.status_code,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(self._backoff_factor * (2 ** attempt))
                    continue

                # Raise on non-2xx (after retries exhausted for 5xx)
                if response.status_code >= 400:
                    body = response.text[:500]
                    raise ExternalServiceError(
                        f"{self._service_name} returned {response.status_code}: {body}"
                    )

                return response

            except ExternalServiceError:
                raise
            except httpx.TimeoutException as e:
                last_exception = e
                if attempt < self._max_retries:
                    logger.warning(
                        "http.outbound.timeout",
                        service=self._service_name,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(self._backoff_factor * (2 ** attempt))
                    continue
            except httpx.HTTPError as e:
                last_exception = e
                if attempt < self._max_retries:
                    logger.warning(
                        "http.outbound.error",
                        service=self._service_name,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(self._backoff_factor * (2 ** attempt))
                    continue

        raise ExternalServiceError(
            f"{self._service_name} request failed after "
            f"{self._max_retries + 1} attempts: {last_exception}"
        )

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)
