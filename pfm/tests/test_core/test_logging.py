"""Tests for structured logging and correlation IDs."""

from app.core.context import (
    clear_correlation_id,
    clear_current_anonymous_id,
    clear_current_user_id,
    generate_correlation_id,
    get_correlation_id,
    get_current_anonymous_id,
    get_current_user_id,
    set_correlation_id,
    set_current_anonymous_id,
    set_current_user_id,
)
from app.core.logging import add_current_user_id, add_trace_context, redact_sensitive_fields


class TestSensitiveRedaction:
    def test_redacts_password(self):
        event = {"password": "secret123", "username": "chris"}
        result = redact_sensitive_fields(None, None, event)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "chris"

    def test_redacts_api_key(self):
        event = {"api_key": "sk-ant-xxx", "data": "safe"}
        result = redact_sensitive_fields(None, None, event)
        assert result["api_key"] == "[REDACTED]"
        assert result["data"] == "safe"

    def test_redacts_authorization(self):
        event = {"authorization": "Bearer token123"}
        result = redact_sensitive_fields(None, None, event)
        assert result["authorization"] == "[REDACTED]"

    def test_redacts_token(self):
        event = {"access_token": "abc", "refresh_token": "def"}
        result = redact_sensitive_fields(None, None, event)
        assert result["access_token"] == "[REDACTED]"
        assert result["refresh_token"] == "[REDACTED]"

    def test_redacts_ssn(self):
        event = {"ssn": "123-45-6789"}
        result = redact_sensitive_fields(None, None, event)
        assert result["ssn"] == "[REDACTED]"

    def test_redacts_credit_card(self):
        event = {"credit_card": "4111111111111111"}
        result = redact_sensitive_fields(None, None, event)
        assert result["credit_card"] == "[REDACTED]"

    def test_does_not_redact_normal_fields(self):
        event = {"user_id": "123", "amount": 19.99, "merchant": "Walmart"}
        result = redact_sensitive_fields(None, None, event)
        assert result == event

    def test_redacts_nested_dict(self):
        event = {"headers": {"authorization": "Bearer xxx", "content-type": "json"}}
        result = redact_sensitive_fields(None, None, event)
        assert result["headers"]["authorization"] == "[REDACTED]"
        assert result["headers"]["content-type"] == "json"


class TestCorrelationId:
    def test_generate_creates_uuid(self):
        cid = generate_correlation_id()
        assert cid is not None
        assert len(cid) == 36

    def test_set_and_get(self):
        set_correlation_id("test-123")
        assert get_correlation_id() == "test-123"

    def test_get_returns_none_when_unset(self):
        clear_correlation_id()
        assert get_correlation_id() is None


class TestCurrentUserId:
    def test_set_and_get(self):
        set_current_user_id("user-123")
        assert get_current_user_id() == "user-123"

    def test_get_returns_none_when_cleared(self):
        clear_current_user_id()
        assert get_current_user_id() is None

    def test_logging_processor_adds_current_user_id(self):
        set_current_user_id("user-123")
        event = add_current_user_id(None, "", {"event": "test"})
        assert event["current_user_id"] == "user-123"


class TestCurrentAnonymousId:
    def test_set_and_get(self):
        set_current_anonymous_id("anon-123")
        assert get_current_anonymous_id() == "anon-123"

    def test_get_returns_none_when_cleared(self):
        clear_current_anonymous_id()
        assert get_current_anonymous_id() is None


class TestTraceContext:
    def test_logging_processor_adds_trace_context(self, monkeypatch):
        class _FakeSpanContext:
            is_valid = True
            trace_id = int("1234", 16)
            span_id = int("abcd", 16)

        class _FakeSpan:
            @staticmethod
            def get_span_context():
                return _FakeSpanContext()

        monkeypatch.setattr("app.core.logging.trace.get_current_span", lambda: _FakeSpan())

        event = add_trace_context(None, "", {"event": "test"})

        assert event["trace_id"] == "00000000000000000000000000001234"
        assert event["span_id"] == "000000000000abcd"

    def test_logging_processor_skips_invalid_span(self, monkeypatch):
        class _FakeSpanContext:
            is_valid = False
            trace_id = 0
            span_id = 0

        class _FakeSpan:
            @staticmethod
            def get_span_context():
                return _FakeSpanContext()

        monkeypatch.setattr("app.core.logging.trace.get_current_span", lambda: _FakeSpan())

        event = add_trace_context(None, "", {"event": "test"})

        assert "trace_id" not in event
        assert "span_id" not in event
