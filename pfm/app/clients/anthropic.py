"""
Anthropic client — wraps the Anthropic SDK with BaseClient patterns.

Uses the official anthropic Python SDK for API calls,
but adds structured logging, correlation ID propagation, and error translation.
"""

import structlog

from app.config import get_settings
from app.core.exceptions import DependencyUnavailableError
from app.core.responses import ProblemUpstream

logger = structlog.get_logger()


class AnthropicClient:
    """Wraps the Anthropic SDK with our logging and error patterns."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.anthropic.api_key.get_secret_value()
        self._model = settings.anthropic.model
        self._max_retries = settings.anthropic.max_retries
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                max_retries=self._max_retries,
            )
        return self._client

    async def create_message(
        self,
        system: str,
        user_message: str,
        max_tokens: int = 500,
    ) -> str:
        """Send a message to Claude and return the text response."""
        import time
        start = time.monotonic()

        try:
            client = self._get_client()
            response = await client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            duration = time.monotonic() - start

            logger.info(
                "http.outbound",
                dependency="anthropic",
                model=self._model,
                duration_ms=round(duration * 1000),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            return response.content[0].text

        except Exception as e:
            duration = time.monotonic() - start
            logger.error(
                "http.outbound.error",
                dependency="anthropic",
                error=str(e),
                duration_ms=round(duration * 1000),
                exception_type=type(e).__name__,
                exc_info=(type(e), e, e.__traceback__),
            )
            raise DependencyUnavailableError.for_service(
                "anthropic",
                upstream=ProblemUpstream(provider="anthropic"),
                extra_log_context={"sdk_error_type": type(e).__name__},
            ) from e

    async def close(self) -> None:
        if self._client:
            await self._client.close()


_instance: AnthropicClient | None = None


def get_anthropic_client() -> AnthropicClient:
    """Return a module-level singleton. Use as a FastAPI dependency.

    Safe under GIL: __init__ is synchronous and idempotent, so concurrent
    coroutines in a single-process async server cannot create duplicates.
    """
    global _instance
    if _instance is None:
        _instance = AnthropicClient()
    return _instance


async def close_client() -> None:
    """Close the singleton client during shutdown."""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
