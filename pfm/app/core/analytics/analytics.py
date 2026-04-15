"""
Event tracking via a multi-delegate service.

AnalyticsService fans events out to all registered delegates and owns the
delegate lifecycle. Delegate failures are logged and never raised back into
application request paths.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

import structlog
from fastapi import Request

from app.core.context import get_current_anonymous_id, get_current_user_id

logger = structlog.get_logger()

EVENT_NAME_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")


@dataclass(frozen=True, slots=True)
class AnalyticsIdentity:
    """Resolved analytics identity for a single event."""

    user_id: str | None = None
    anonymous_id: str | None = None

    @property
    def distinct_id(self) -> str | None:
        return self.user_id or self.anonymous_id

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None and self.anonymous_id is not None


@runtime_checkable
class AnalyticsDelegate(Protocol):
    """Protocol for analytics delegates."""

    def track(
        self,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None: ...

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None = None,
    ) -> None: ...

    def close(self) -> None: ...


class ConsoleAnalyticsDelegate:
    """Logs events to structlog. Used in dev and tests."""

    def track(
        self,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None:
        logger.debug(
            "analytics.track",
            event_name=event,
            properties=dict(properties),
            user_id=identity.user_id,
            anonymous_id=identity.anonymous_id,
            distinct_id=identity.distinct_id,
        )

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None = None,
    ) -> None:
        logger.debug(
            "analytics.identify",
            user_id=user_id,
            anonymous_id=anonymous_id,
            traits=dict(traits),
        )

    def close(self) -> None:
        return


class AnalyticsService:
    """Application-facing analytics service."""

    def __init__(self, delegates: list[AnalyticsDelegate] | None = None) -> None:
        self._delegates = delegates or []

    def track(
        self,
        event: str,
        properties: Mapping[str, Any] | None = None,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
    ) -> None:
        """Track an event using the best available identity."""
        if not EVENT_NAME_PATTERN.match(event):
            logger.warning("analytics.invalid_event_name", event_name=event)

        identity = self._resolve_identity(user_id=user_id, anonymous_id=anonymous_id)
        if identity.distinct_id is None:
            logger.debug("analytics.skipped_missing_identity", event_name=event)
            return

        props = dict(properties or {})
        for delegate in self._delegates:
            self._safe_track(delegate, event, props, identity)

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any] | None = None,
        *,
        anonymous_id: str | None = None,
    ) -> None:
        """Identify a known user and carry any anonymous predecessor to delegates."""
        resolved_anonymous_id = anonymous_id or get_current_anonymous_id()
        if resolved_anonymous_id == user_id:
            resolved_anonymous_id = None

        user_traits = dict(traits or {})
        for delegate in self._delegates:
            self._safe_identify(delegate, user_id, user_traits, resolved_anonymous_id)

    def close(self) -> None:
        """Flush and close all delegates."""
        for delegate in self._delegates:
            self._safe_close(delegate)

    @staticmethod
    def _resolve_identity(
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
    ) -> AnalyticsIdentity:
        resolved_user_id = user_id or get_current_user_id()
        resolved_anonymous_id = anonymous_id or get_current_anonymous_id()
        return AnalyticsIdentity(
            user_id=resolved_user_id,
            anonymous_id=resolved_anonymous_id,
        )

    @staticmethod
    def _safe_track(
        delegate: AnalyticsDelegate,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None:
        try:
            delegate.track(event, properties, identity)
        except Exception as exc:
            logger.warning(
                "analytics.delegate_error",
                action="track",
                delegate=type(delegate).__name__,
                error=str(exc),
            )

    @staticmethod
    def _safe_identify(
        delegate: AnalyticsDelegate,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None,
    ) -> None:
        try:
            delegate.identify(user_id, traits, anonymous_id=anonymous_id)
        except Exception as exc:
            logger.warning(
                "analytics.delegate_error",
                action="identify",
                delegate=type(delegate).__name__,
                error=str(exc),
            )

    @staticmethod
    def _safe_close(delegate: AnalyticsDelegate) -> None:
        try:
            delegate.close()
        except Exception as exc:
            logger.warning(
                "analytics.delegate_error",
                action="close",
                delegate=type(delegate).__name__,
                error=str(exc),
            )


def create_analytics_service() -> AnalyticsService:
    """Build the process-scoped analytics service."""
    from app.config import get_settings

    settings = get_settings()
    delegates: list[AnalyticsDelegate] = [ConsoleAnalyticsDelegate()]

    if settings.observability.posthog_api_key:
        from app.core.analytics.analytics_posthog import PostHogAnalyticsDelegate

        delegates.append(
            PostHogAnalyticsDelegate(
                api_key=settings.observability.posthog_api_key,
                host=settings.observability.posthog_host,
            )
        )

    return AnalyticsService(delegates=delegates)


def get_analytics(request: Request) -> AnalyticsService:
    """FastAPI dependency for the process-scoped analytics service."""
    analytics = getattr(request.app.state, "analytics", None)
    if analytics is None:
        raise RuntimeError("Analytics service is not initialized on app.state")
    return cast(AnalyticsService, analytics)
