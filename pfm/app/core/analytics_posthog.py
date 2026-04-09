"""
PostHog analytics delegate.

Sends events to PostHog API. Used in staging/production.
"""

import asyncio

import structlog

logger = structlog.get_logger()


class PostHogAnalyticsDelegate:
    """Sends analytics events to PostHog."""

    def __init__(self, api_key: str, host: str = "https://app.posthog.com") -> None:
        try:
            from posthog import Posthog
            self._client = Posthog(api_key, host=host)
        except ImportError:
            logger.warning("posthog package not installed, PostHog delegate disabled")
            self._client = None

    async def track(self, event: str, properties: dict, user_id: str | None = None) -> None:
        if not self._client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.capture(
                distinct_id=user_id or "anonymous",
                event=event,
                properties=properties,
            ),
        )

    async def identify(self, user_id: str, traits: dict) -> None:
        if not self._client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.identify(distinct_id=user_id, properties=traits),
        )
