"""Tests for analytics service and delegates."""

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi import Depends

from app.core.analytics.analytics import (
    EVENT_NAME_PATTERN,
    AnalyticsIdentity,
    AnalyticsService,
    ConsoleAnalyticsDelegate,
    get_analytics,
)
from app.core.analytics.analytics_posthog import PostHogAnalyticsDelegate
from app.core.context import (
    clear_current_anonymous_id,
    clear_current_user_id,
    set_current_anonymous_id,
    set_current_user_id,
)


@pytest.fixture(autouse=True)
def clear_identity_context():
    clear_current_user_id()
    clear_current_anonymous_id()
    yield
    clear_current_user_id()
    clear_current_anonymous_id()


class TestEventNameValidation:
    def test_valid_names(self):
        assert EVENT_NAME_PATTERN.match("user.authenticated")
        assert EVENT_NAME_PATTERN.match("transaction.categorized")
        assert EVENT_NAME_PATTERN.match("account.linked")

    def test_invalid_names(self):
        assert not EVENT_NAME_PATTERN.match("userAuthenticated")
        assert not EVENT_NAME_PATTERN.match("categorized transaction")
        assert not EVENT_NAME_PATTERN.match("test")
        assert not EVENT_NAME_PATTERN.match("a.b.c")


class TestConsoleDelegate:
    def test_track_does_not_raise(self):
        delegate = ConsoleAnalyticsDelegate()
        delegate.track(
            "user.authenticated",
            {"method": "jwt"},
            AnalyticsIdentity(user_id="user-123"),
        )

    def test_identify_does_not_raise(self):
        delegate = ConsoleAnalyticsDelegate()
        delegate.identify("user-123", {"email": "test@test.com"}, anonymous_id="anon-123")

    def test_close_does_not_raise(self):
        delegate = ConsoleAnalyticsDelegate()
        delegate.close()


class RecordingDelegate:
    def __init__(self) -> None:
        self.tracked: list[tuple[str, dict[str, Any], AnalyticsIdentity]] = []
        self.identified: list[tuple[str, dict[str, Any], str | None]] = []
        self.closed = False

    def track(
        self,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None:
        self.tracked.append((event, dict(properties), identity))

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None = None,
    ) -> None:
        self.identified.append((user_id, dict(traits), anonymous_id))

    def close(self) -> None:
        self.closed = True


class FailingDelegate:
    def track(
        self,
        event: str,
        properties: Mapping[str, Any],
        identity: AnalyticsIdentity,
    ) -> None:
        raise RuntimeError("track failed")

    def identify(
        self,
        user_id: str,
        traits: Mapping[str, Any],
        anonymous_id: str | None = None,
    ) -> None:
        raise RuntimeError("identify failed")

    def close(self) -> None:
        raise RuntimeError("close failed")


class FakePostHogClient:
    def __init__(self) -> None:
        self.captures: list[dict[str, Any]] = []
        self.aliases: list[dict[str, Any]] = []
        self.sets: list[dict[str, Any]] = []
        self.shutdown_called = False

    def capture(self, **kwargs: Any) -> None:
        self.captures.append(kwargs)

    def alias(self, **kwargs: Any) -> None:
        self.aliases.append(kwargs)

    def set(self, **kwargs: Any) -> None:
        self.sets.append(kwargs)

    def shutdown(self) -> None:
        self.shutdown_called = True


class TestAnalyticsService:
    def test_track_with_no_delegates(self):
        service = AnalyticsService(delegates=[])
        service.track("user.authenticated", {"test": True}, user_id="user-123")

    def test_track_prefers_current_user_id_over_anonymous_id(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        set_current_user_id("user-123")
        set_current_anonymous_id("anon-123")
        service.track("test.event", {"key": "value"})

        assert delegate.tracked[0][2].user_id == "user-123"
        assert delegate.tracked[0][2].distinct_id == "user-123"

    def test_track_falls_back_to_anonymous_context(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        set_current_anonymous_id("anon-123")
        service.track("test.event", {"key": "value"})

        assert delegate.tracked[0][2] == AnalyticsIdentity(
            user_id=None,
            anonymous_id="anon-123",
        )

    def test_track_uses_explicit_identity_over_context(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        set_current_user_id("context-user")
        set_current_anonymous_id("context-anon")
        service.track(
            "test.event",
            {"key": "value"},
            user_id="explicit-user",
            anonymous_id="explicit-anon",
        )

        assert delegate.tracked[0][2] == AnalyticsIdentity(
            user_id="explicit-user",
            anonymous_id="explicit-anon",
        )

    def test_track_skips_when_identity_is_missing(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        service.track("test.event", {"key": "value"})

        assert delegate.tracked == []

    def test_identify_with_no_delegates(self):
        service = AnalyticsService(delegates=[])
        service.identify("user-123", {"email": "test@test.com"})

    def test_identify_passes_anonymous_context_to_delegate(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        set_current_anonymous_id("anon-123")
        service.identify("user-123", {"email": "test@test.com"})

        assert delegate.identified == [
            ("user-123", {"email": "test@test.com"}, "anon-123")
        ]

    def test_identify_normalizes_matching_anonymous_id(self):
        delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[delegate])

        set_current_anonymous_id("user-123")
        service.identify("user-123", {"email": "test@test.com"})

        assert delegate.identified == [
            ("user-123", {"email": "test@test.com"}, None)
        ]

    def test_delegate_failures_are_contained(self):
        recording_delegate = RecordingDelegate()
        service = AnalyticsService(delegates=[FailingDelegate(), recording_delegate])

        service.track("test.event", {"key": "value"}, user_id="user-123")
        service.identify("user-123", {"email": "test@test.com"}, anonymous_id="anon-123")
        service.close()

        assert recording_delegate.tracked[0][0] == "test.event"
        assert recording_delegate.identified == [
            ("user-123", {"email": "test@test.com"}, "anon-123")
        ]
        assert recording_delegate.closed is True


class TestGetAnalyticsDependency:
    async def test_returns_app_scoped_service(self, app, client):
        @app.get("/analytics-service")
        async def analytics_service(
            analytics: AnalyticsService = Depends(get_analytics),
        ):
            return {"same_instance": analytics is app.state.analytics}

        response = await client.get("/analytics-service")

        assert response.status_code == 200
        assert response.json() == {"same_instance": True}


class TestPostHogAnalyticsDelegate:
    def test_track_uses_resolved_distinct_id(self):
        delegate = PostHogAnalyticsDelegate.__new__(PostHogAnalyticsDelegate)
        delegate._client = FakePostHogClient()

        delegate.track(
            "test.event",
            {"key": "value"},
            AnalyticsIdentity(user_id=None, anonymous_id="anon-123"),
        )

        assert delegate._client.captures == [
            {
                "distinct_id": "anon-123",
                "event": "test.event",
                "properties": {"key": "value"},
            }
        ]

    def test_identify_aliases_then_sets_traits(self):
        delegate = PostHogAnalyticsDelegate.__new__(PostHogAnalyticsDelegate)
        delegate._client = FakePostHogClient()

        delegate.identify("user-123", {"email": "test@test.com"}, anonymous_id="anon-123")

        assert delegate._client.aliases == [
            {"previous_id": "anon-123", "distinct_id": "user-123"}
        ]
        assert delegate._client.sets == [
            {"distinct_id": "user-123", "properties": {"email": "test@test.com"}}
        ]

    def test_identify_skips_alias_when_anonymous_id_missing(self):
        delegate = PostHogAnalyticsDelegate.__new__(PostHogAnalyticsDelegate)
        delegate._client = FakePostHogClient()

        delegate.identify("user-123", {"email": "test@test.com"})

        assert delegate._client.aliases == []
        assert delegate._client.sets == [
            {"distinct_id": "user-123", "properties": {"email": "test@test.com"}}
        ]

    def test_close_shuts_down_client(self):
        delegate = PostHogAnalyticsDelegate.__new__(PostHogAnalyticsDelegate)
        delegate._client = FakePostHogClient()

        delegate.close()

        assert delegate._client.shutdown_called is True
