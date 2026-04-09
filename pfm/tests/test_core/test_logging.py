"""Tests for structured logging and correlation IDs."""

from app.core.context import (
    clear_correlation_id,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)
from app.core.logging import redact_sensitive_fields


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
        assert len(cid) == 36  # UUID format

    def test_set_and_get(self):
        set_correlation_id("test-123")
        assert get_correlation_id() == "test-123"

    def test_get_returns_none_when_unset(self):
        clear_correlation_id()
        assert get_correlation_id() is None
