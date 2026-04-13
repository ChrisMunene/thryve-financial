"""
PostHog analytics delegate.

Sends events to PostHog API. Used in staging/production.
"""

from collections.abc import Mapping
from typing import Any

import structlog

from app.core.analytics import AnalyticsIdentity

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

    def track(
        self,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None:
        if not self._client or identity.distinct_id is None:
            return
        self._client.capture(
            distinct_id=identity.distinct_id,
            event=event,
            properties=dict(properties),
        )

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None = None,
    ) -> None:
        if not self._client:
            return

        if anonymous_id and anonymous_id != user_id:
            self._client.alias(previous_id=anonymous_id, distinct_id=user_id)

        if traits:
            self._client.set(distinct_id=user_id, properties=dict(traits))

    def close(self) -> None:
        if self._client:
            self._client.shutdown()
