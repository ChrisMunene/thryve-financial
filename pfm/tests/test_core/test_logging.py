"""Tests for structured logging and correlation IDs."""

import json
import logging

import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
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
from app.core.exceptions import AuthenticationRequiredError
from app.core.logging import (
    add_current_anonymous_id,
    add_current_user_id,
    add_trace_context,
    configure_logging,
    redact_sensitive_fields,
)
from app.core.telemetry import TelemetryProcessRole
from app.main import create_app


def _json_log_events(raw: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


@pytest.fixture
def json_logging_env(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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

    def test_redacts_nested_lists_and_tuples(self):
        event = {
            "payload": [
                {"api_key": "secret"},
                ("safe", {"cookie": "session=123"}),
            ]
        }
        result = redact_sensitive_fields(None, None, event)
        assert result["payload"][0]["api_key"] == "[REDACTED]"
        assert result["payload"][1][1]["cookie"] == "[REDACTED]"


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
        assert event["user_id"] == "user-123"


class TestCurrentAnonymousId:
    def test_set_and_get(self):
        set_current_anonymous_id("anon-123")
        assert get_current_anonymous_id() == "anon-123"

    def test_get_returns_none_when_cleared(self):
        clear_current_anonymous_id()
        assert get_current_anonymous_id() is None

    def test_logging_processor_adds_current_anonymous_id(self):
        set_current_anonymous_id("anon-123")
        event = add_current_anonymous_id(None, "", {"event": "test"})
        assert event["anonymous_id"] == "anon-123"


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


class TestLoggingRuntime:
    def test_structlog_and_stdlib_logs_share_json_schema(self, json_logging_env, capsys):
        settings = get_settings()
        configure_logging(settings, TelemetryProcessRole.API)
        capsys.readouterr()

        structlog.get_logger("demo").info("demo.event", foo="bar")
        logging.getLogger("stdlib.demo").warning("stdlib event")

        events = _json_log_events(capsys.readouterr().out)
        assert [event["event"] for event in events] == ["demo.event", "stdlib event"]
        assert all(event["service"] == "pfm-api" for event in events)
        assert all(event["process_role"] == "api" for event in events)
        assert all(event["environment"] == settings.environment.value for event in events)

    def test_exception_logs_stay_single_structured_records(self, json_logging_env, capsys):
        settings = get_settings()
        configure_logging(settings, TelemetryProcessRole.API)
        capsys.readouterr()

        try:
            1 / 0
        except ZeroDivisionError as exc:
            structlog.get_logger("demo").error("structlog.failed", exc_info=exc)
            logging.getLogger("stdlib.demo").exception("stdlib failed")

        raw = capsys.readouterr().out
        events = _json_log_events(raw)
        assert len(events) == 2
        assert all("exception" in event for event in events)
        assert all("ZeroDivisionError" in str(event["exception"]) for event in events)

    def test_worker_and_beat_logs_include_role_specific_service_names(
        self,
        json_logging_env,
        capsys,
    ):
        settings = get_settings()

        configure_logging(settings, TelemetryProcessRole.WORKER)
        capsys.readouterr()
        structlog.get_logger("worker.demo").info("worker.event")
        worker_event = _json_log_events(capsys.readouterr().out)[0]

        configure_logging(settings, TelemetryProcessRole.BEAT)
        capsys.readouterr()
        logging.getLogger("beat.demo").warning("beat event")
        beat_event = _json_log_events(capsys.readouterr().out)[0]

        assert worker_event["service"] == "pfm-worker"
        assert worker_event["process_role"] == "worker"
        assert beat_event["service"] == "pfm-beat"
        assert beat_event["process_role"] == "beat"


class TestRequestLogging:
    @pytest.mark.asyncio
    async def test_request_completed_includes_request_context(self, json_logging_env, capsys):
        application = create_app()

        @application.get("/logging-test")
        async def logging_test():
            set_current_user_id("user-123")
            return {"ok": True}

        capsys.readouterr()

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/logging-test",
                headers={
                    "x-request-id": "req-123",
                    "x-anonymous-id": "anon-123",
                },
            )

        assert response.status_code == 200

        events = _json_log_events(capsys.readouterr().out)
        request_events = [event for event in events if event["event"] == "request.completed"]
        assert len(request_events) == 1
        event = request_events[0]
        assert event["request_id"] == "req-123"
        assert event["user_id"] == "user-123"
        assert event["anonymous_id"] == "anon-123"
        assert event["method"] == "GET"
        assert event["path"] == "/logging-test"
        assert event["route"] == "/logging-test"
        assert event["status_code"] == 200

    @pytest.mark.asyncio
    async def test_health_and_options_requests_are_skipped_by_default(
        self,
        json_logging_env,
        capsys,
    ):
        application = create_app()

        @application.get("/skip-options")
        async def skip_options():
            return {"ok": True}

        capsys.readouterr()

        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/v1/health")
            await client.options("/skip-options")

        events = _json_log_events(capsys.readouterr().out)
        request_paths = {
            event.get("path")
            for event in events
            if event.get("event") == "request.completed"
        }
        assert "/api/v1/health" not in request_paths
        assert "/skip-options" not in request_paths

    @pytest.mark.asyncio
    async def test_handled_and_unhandled_errors_emit_diagnostic_and_completion_logs(
        self,
        json_logging_env,
        capsys,
    ):
        application = create_app()

        @application.get("/handled-log-error")
        async def handled_log_error():
            raise AuthenticationRequiredError.default()

        @application.get("/unhandled-log-error")
        async def unhandled_log_error():
            raise RuntimeError("boom")

        capsys.readouterr()

        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            handled = await client.get("/handled-log-error")
            unhandled = await client.get("/unhandled-log-error")

        assert handled.status_code == 401
        assert unhandled.status_code == 500

        events = _json_log_events(capsys.readouterr().out)

        handled_problem = next(
            event
            for event in events
            if event.get("event") == "request.problem"
            and event.get("path") == "/handled-log-error"
        )
        assert handled_problem["status_code"] == 401
        assert handled_problem["error_code"] == "authentication_required"

        unhandled_problem = next(
            event
            for event in events
            if event.get("event") == "request.unhandled_exception"
            and event.get("path") == "/unhandled-log-error"
        )
        assert unhandled_problem["status_code"] == 500
        assert unhandled_problem["error_code"] == "internal_error"
        assert unhandled_problem["exception_type"] == "RuntimeError"
        assert "exception" in unhandled_problem

        completions = {
            event["path"]: event["status_code"]
            for event in events
            if event.get("event") == "request.completed"
        }
        assert completions["/handled-log-error"] == 401
        assert completions["/unhandled-log-error"] == 500
