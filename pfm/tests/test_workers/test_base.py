"""Tests for Celery task helpers."""

import json
from contextlib import contextmanager

import pytest

from app.config import get_settings
from app.core.context import clear_correlation_id, set_correlation_id
from app.core.logging import configure_logging
from app.core.telemetry import TelemetryProcessRole
from app.workers.base import dispatch_task
from app.workers.idempotency_tasks import cleanup_expired_idempotency_requests_task


def _json_log_events(raw: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


class _FakeMetrics:
    def __init__(self):
        self.dispatched = []

    def record_task_dispatch(self, *, task_name: str) -> None:
        self.dispatched.append(task_name)


class _FakeTask:
    name = "app.workers.example"

    def __init__(self):
        self.calls = []

    def apply_async(self, args, kwargs, headers, **options):
        self.calls.append((args, kwargs, headers, options))
        return _FakeAsyncResult(options["task_id"])


class _FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


class _FailingTask(_FakeTask):
    def apply_async(self, args, kwargs, headers, **options):
        self.calls.append((args, kwargs, headers, options))
        raise RuntimeError("broker unavailable")


class _FakeSpan:
    def __init__(self):
        self.attributes = {}

    def is_recording(self):
        return True

    def set_attribute(self, key, value):
        self.attributes[key] = value


@pytest.fixture
def json_logging_env(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_dispatch_task_propagates_headers_logs_success_and_records_metrics(
    monkeypatch,
    json_logging_env,
    capsys,
):
    fake_metrics = _FakeMetrics()
    fake_task = _FakeTask()
    span_calls = []

    monkeypatch.setattr("app.workers.base.get_metrics", lambda: fake_metrics)
    monkeypatch.setattr(
        "app.workers.base.inject",
        lambda headers: headers.update({"traceparent": "00-test-trace"}),
    )
    settings = get_settings()
    configure_logging(settings, TelemetryProcessRole.API)

    @contextmanager
    def fake_operation_span(name, *, attributes):
        span = _FakeSpan()
        span_calls.append((name, attributes, span))
        yield span

    monkeypatch.setattr("app.workers.base.operation_span", fake_operation_span)
    capsys.readouterr()

    set_correlation_id("req-123")
    try:
        result = dispatch_task(fake_task, 1, user_id="user-1")
    finally:
        clear_correlation_id()

    assert result.id
    assert fake_metrics.dispatched == ["app.workers.example"]
    assert span_calls[0][0] == "task.enqueue"
    assert span_calls[0][1]["task_name"] == "app.workers.example"

    args, kwargs, headers, options = fake_task.calls[0]
    assert args == (1,)
    assert kwargs == {"user_id": "user-1"}
    assert headers["correlation_id"] == "req-123"
    assert headers["traceparent"] == "00-test-trace"
    assert options["task_id"] == result.id

    events = _json_log_events(capsys.readouterr().out)
    dispatch_event = next(event for event in events if event["event"] == "task.dispatched")
    assert dispatch_event["task_name"] == "app.workers.example"
    assert dispatch_event["task_id"] == result.id


def test_dispatch_task_logs_failures_and_skips_metrics(monkeypatch, json_logging_env, capsys):
    fake_metrics = _FakeMetrics()
    fake_task = _FailingTask()

    monkeypatch.setattr("app.workers.base.get_metrics", lambda: fake_metrics)
    monkeypatch.setattr("app.workers.base.inject", lambda headers: None)
    settings = get_settings()
    configure_logging(settings, TelemetryProcessRole.API)

    @contextmanager
    def fake_operation_span(name, *, attributes):
        yield _FakeSpan()

    monkeypatch.setattr("app.workers.base.operation_span", fake_operation_span)
    capsys.readouterr()

    with pytest.raises(RuntimeError, match="broker unavailable"):
        dispatch_task(fake_task, 1)

    assert fake_metrics.dispatched == []
    events = _json_log_events(capsys.readouterr().out)
    failure_event = next(event for event in events if event["event"] == "task.dispatch_failed")
    assert failure_event["task_name"] == "app.workers.example"
    assert failure_event["exception_type"] == "RuntimeError"
    assert "task_id" in failure_event
    assert "exception" in failure_event


def test_idempotency_cleanup_task_wraps_work_in_domain_span(monkeypatch):
    span_calls = []

    async def fake_cleanup():
        return 7

    @contextmanager
    def fake_operation_span(name, *, attributes):
        span = _FakeSpan()
        span_calls.append((name, attributes, span))
        yield span

    monkeypatch.setattr(
        "app.workers.idempotency_tasks.cleanup_expired_idempotency_requests",
        fake_cleanup,
    )
    monkeypatch.setattr("app.workers.idempotency_tasks.operation_span", fake_operation_span)

    result = cleanup_expired_idempotency_requests_task.run()

    assert result == 7
    assert span_calls[0][0] == "idempotency.cleanup"
    assert (
        span_calls[0][1]["task_name"]
        == "app.workers.idempotency_tasks.cleanup_expired_idempotency_requests"
    )
    assert span_calls[0][2].attributes["deleted_count"] == 7
