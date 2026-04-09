"""
Event tracking — delegate pattern, multi-delegate.

AnalyticsService fans events out to all registered delegates.
Fire-and-forget: errors in delegates are logged, not raised.
Event names must follow noun.verb format.
"""

import asyncio
import re
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()

EVENT_NAME_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")

_background_tasks: set[asyncio.Task] = set()


@runtime_checkable
class AnalyticsDelegate(Protocol):
    """Protocol for analytics delegates."""

    async def track(self, event: str, properties: dict, user_id: str | None = None) -> None: ...
    async def identify(self, user_id: str, traits: dict) -> None: ...


class ConsoleAnalyticsDelegate:
    """Logs events to structlog. Used in dev and tests."""

    async def track(self, event: str, properties: dict, user_id: str | None = None) -> None:
        logger.debug("analytics.track", event_name=event, properties=properties, user_id=user_id)

    async def identify(self, user_id: str, traits: dict) -> None:
        logger.debug("analytics.identify", user_id=user_id, traits=traits)


class AnalyticsService:
    """Application-facing analytics service.

    Fans events to all delegates. Fire-and-forget.
    Add/remove vendors by adding/removing delegates — no app code changes.
    """

    def __init__(self, delegates: list[AnalyticsDelegate] | None = None) -> None:
        self._delegates = delegates or []

    def track(self, event: str, properties: dict | None = None, user_id: str | None = None) -> None:
        """Track an event. Fire-and-forget."""
        if not EVENT_NAME_PATTERN.match(event):
            logger.warning("analytics.invalid_event_name", event=event)

        props = properties or {}
        for delegate in self._delegates:
            task = asyncio.create_task(self._safe_track(delegate, event, props, user_id))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    def identify(self, user_id: str, traits: dict | None = None) -> None:
        """Identify a user. Fire-and-forget."""
        user_traits = traits or {}
        for delegate in self._delegates:
            task = asyncio.create_task(self._safe_identify(delegate, user_id, user_traits))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    @staticmethod
    async def _safe_track(
        delegate: AnalyticsDelegate, event: str, properties: dict, user_id: str | None
    ) -> None:
        try:
            await delegate.track(event, properties, user_id)
        except Exception as e:
            logger.warning("analytics.delegate_error", delegate=type(delegate).__name__, error=str(e))

    @staticmethod
    async def _safe_identify(delegate: AnalyticsDelegate, user_id: str, traits: dict) -> None:
        try:
            await delegate.identify(user_id, traits)
        except Exception as e:
            logger.warning("analytics.delegate_error", delegate=type(delegate).__name__, error=str(e))


def get_analytics() -> AnalyticsService:
    """FastAPI dependency for analytics."""
    from app.config import get_settings

    settings = get_settings()
    delegates: list[AnalyticsDelegate] = [ConsoleAnalyticsDelegate()]

    if settings.observability.posthog_api_key:
        from app.core.analytics_posthog import PostHogAnalyticsDelegate
        delegates.append(PostHogAnalyticsDelegate(
            api_key=settings.observability.posthog_api_key,
            host=settings.observability.posthog_host,
        ))

    return AnalyticsService(delegates=delegates)
