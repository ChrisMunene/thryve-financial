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
import json
import time

import httpx
import structlog

from app.core.context import get_correlation_id
from app.core.exceptions import (
    DependencyUnavailableError,
    ExternalActionRequiredError,
    UpstreamServiceError,
    UpstreamTimeoutError,
)
from app.core.responses import ProblemUpstream
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

    def _upstream_metadata(self, response: httpx.Response, payload: dict | None) -> ProblemUpstream:
        provider_request_id = (
            response.headers.get("request-id")
            or response.headers.get("x-request-id")
            or (payload or {}).get("request_id")
        )
        provider_code = (
            (payload or {}).get("error_code")
            or (payload or {}).get("code")
            or (payload or {}).get("type")
        )
        return ProblemUpstream(
            provider=self._service_name,
            provider_code=str(provider_code) if provider_code is not None else None,
            provider_request_id=(
                str(provider_request_id) if provider_request_id is not None else None
            ),
        )

    def _provider_error_payload(self, response: httpx.Response) -> dict | None:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _response_problem(self, response: httpx.Response):
        payload = self._provider_error_payload(response)
        upstream = self._upstream_metadata(response, payload)

        if response.status_code >= 500:
            return UpstreamServiceError.provider_unavailable(
                provider_name=self._service_name,
                upstream=upstream,
            )

        if self._service_name == "plaid":
            return ExternalActionRequiredError.bank_reauthentication_required(
                provider_name=self._service_name,
                upstream=upstream,
            )

        return ExternalActionRequiredError.support_required(
            provider_name=self._service_name,
            upstream=upstream,
        )

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
                    raise self._response_problem(response)

                return response

            except (
                UpstreamServiceError,
                ExternalActionRequiredError,
                UpstreamTimeoutError,
                DependencyUnavailableError,
            ):
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
                raise UpstreamTimeoutError.for_service(
                    self._service_name,
                    upstream=ProblemUpstream(provider=self._service_name),
                ) from e
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
                raise DependencyUnavailableError.for_service(
                    self._service_name,
                    upstream=ProblemUpstream(provider=self._service_name),
                ) from e

        raise DependencyUnavailableError.for_service(
            self._service_name,
            upstream=ProblemUpstream(provider=self._service_name),
            extra_log_context={
                "last_exception_type": type(last_exception).__name__
                if last_exception is not None
                else "unknown"
            },
        )

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)
