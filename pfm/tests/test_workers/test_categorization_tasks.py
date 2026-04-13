from contextlib import contextmanager

from app.workers.categorization_tasks import categorize_transactions_task


class _FakeSpan:
    def __init__(self):
        self.attributes = {}

    def is_recording(self):
        return True

    def set_attribute(self, key, value):
        self.attributes[key] = value


def test_categorization_task_wraps_work_in_domain_span(monkeypatch):
    span_calls = []

    @contextmanager
    def fake_operation_span(name, *, attributes):
        span = _FakeSpan()
        span_calls.append((name, attributes, span))
        yield span

    monkeypatch.setattr("app.workers.categorization_tasks.operation_span", fake_operation_span)

    result = categorize_transactions_task.run(
        transactions=[
            {"transaction_id": "tx-1", "name": "Coffee"},
            {"transaction_id": "tx-2", "name": "Groceries"},
        ],
        source="plaid",
    )

    assert result == {"source": "plaid", "received": 2, "categorized": 2}
    assert span_calls[0][0] == "categorization.execute"
    assert span_calls[0][1] == {
        "task_name": "app.workers.categorization_tasks.categorize_transactions",
        "source": "plaid",
        "transaction_count": 2,
    }
    assert span_calls[0][2].attributes["categorized_count"] == 2
