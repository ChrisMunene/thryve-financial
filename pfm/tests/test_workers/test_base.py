"""Tests for Celery task helpers."""

from app.core.context import clear_correlation_id, set_correlation_id
from app.workers.base import dispatch_task


class _FakeMetrics:
    def __init__(self):
        self.dispatched = []

    def record_task_dispatch(self, *, task_name: str) -> None:
        self.dispatched.append(task_name)


class _FakeTask:
    name = "app.workers.example"

    def __init__(self):
        self.calls = []

    def apply_async(self, args, kwargs, headers):
        self.calls.append((args, kwargs, headers))
        return "queued"


def test_dispatch_task_propagates_correlation_and_trace_headers(monkeypatch):
    fake_metrics = _FakeMetrics()
    fake_task = _FakeTask()

    monkeypatch.setattr("app.workers.base.get_metrics", lambda: fake_metrics)
    monkeypatch.setattr(
        "app.workers.base.inject",
        lambda headers: headers.update({"traceparent": "00-test-trace"}),
    )

    set_correlation_id("req-123")
    try:
        result = dispatch_task(fake_task, 1, user_id="user-1")
    finally:
        clear_correlation_id()

    assert result == "queued"
    assert fake_metrics.dispatched == ["app.workers.example"]

    args, kwargs, headers = fake_task.calls[0]
    assert args == (1,)
    assert kwargs == {"user_id": "user-1"}
    assert headers["correlation_id"] == "req-123"
    assert headers["traceparent"] == "00-test-trace"
