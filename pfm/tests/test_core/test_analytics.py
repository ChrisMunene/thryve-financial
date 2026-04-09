"""Tests for analytics service and delegates."""

import pytest

from app.core.analytics import (
    AnalyticsService,
    ConsoleAnalyticsDelegate,
    EVENT_NAME_PATTERN,
)


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
    async def test_track_does_not_raise(self):
        delegate = ConsoleAnalyticsDelegate()
        await delegate.track("user.authenticated", {"method": "jwt"}, "user-123")

    async def test_identify_does_not_raise(self):
        delegate = ConsoleAnalyticsDelegate()
        await delegate.identify("user-123", {"email": "test@test.com"})


class TestAnalyticsService:
    async def test_track_with_no_delegates(self):
        service = AnalyticsService(delegates=[])
        # Should not raise
        service.track("user.authenticated", {"test": True})

    async def test_track_calls_delegates(self):
        service = AnalyticsService(delegates=[ConsoleAnalyticsDelegate()])
        # track is fire-and-forget via create_task — verify no exception
        service.track("test.event", {"key": "value"}, "user-1")

    async def test_identify_with_no_delegates(self):
        service = AnalyticsService(delegates=[])
        service.identify("user-123", {"email": "test@test.com"})
