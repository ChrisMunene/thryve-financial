from contextlib import contextmanager

from app.dependencies import get_transaction_import_service
from app.services.transactions import TransactionImportService


class _FakePlaidClient:
    def __init__(self):
        self.calls = []

    async def sync_transactions(self, *, access_token: str, cursor: str | None = None):
        self.calls.append({"access_token": access_token, "cursor": cursor})

        class _Result:
            added = [
                {"transaction_id": "tx-1", "name": "Coffee", "amount": 4.5},
                {"transaction_id": "tx-2", "name": "Groceries", "amount": 26.0},
            ]
            next_cursor = "cursor-2"
            has_more = False

        return _Result()


class _FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


async def test_import_transactions_returns_202_and_uses_workflow_span(app, client, monkeypatch):
    fake_plaid = _FakePlaidClient()
    dispatch_calls = []
    span_calls = []

    class _FakeSpan:
        def __init__(self):
            self.attributes = {}

        def is_recording(self):
            return True

        def set_attribute(self, key, value):
            self.attributes[key] = value

    @contextmanager
    def fake_operation_span(name, *, attributes):
        span = _FakeSpan()
        span_calls.append((name, attributes, span))
        yield span

    def fake_dispatch_task(task, *args, **kwargs):
        dispatch_calls.append({"task": task, "args": args, "kwargs": kwargs})
        return _FakeAsyncResult("task-123")

    monkeypatch.setattr("app.services.transactions.operation_span", fake_operation_span)
    monkeypatch.setattr("app.services.transactions.dispatch_task", fake_dispatch_task)
    app.dependency_overrides[get_transaction_import_service] = lambda: TransactionImportService(
        plaid_client=fake_plaid
    )
    try:
        response = await client.post(
            "/api/v1/transactions/import",
            headers={
                "Authorization": "Bearer test-token",
                "Idempotency-Key": "import-req-123",
            },
            json={
                "access_token": "access-sandbox-123",
                "cursor": "cursor-1",
            },
        )

        assert response.status_code == 202
        assert response.json() == {
            "ok": True,
            "data": {
                "task_id": "task-123",
                "imported_count": 2,
                "next_cursor": "cursor-2",
                "has_more": False,
            },
        }
        assert fake_plaid.calls == [
            {"access_token": "access-sandbox-123", "cursor": "cursor-1"}
        ]
        assert span_calls[0][0] == "transactions.import"
        assert span_calls[0][1]["user_id"]
        assert span_calls[0][1]["provider"] == "plaid"
        assert span_calls[0][1]["operation"] == "transactions.sync"
        assert span_calls[0][1]["subject_id"]
        assert span_calls[0][2].attributes["imported_count"] == 2
        assert span_calls[0][2].attributes["has_more"] is False
        assert dispatch_calls[0]["kwargs"]["transactions"] == [
            {"transaction_id": "tx-1", "name": "Coffee", "amount": 4.5},
            {"transaction_id": "tx-2", "name": "Groceries", "amount": 26.0},
        ]
        assert dispatch_calls[0]["kwargs"]["source"] == "plaid"
        assert dispatch_calls[0]["kwargs"]["apply_async_options"] == {"queue": "default"}
    finally:
        app.dependency_overrides.clear()


async def test_import_transactions_requires_authentication(client):
    response = await client.post(
        "/api/v1/transactions/import",
        headers={"Idempotency-Key": "import-req-unauth"},
        json={"access_token": "access-sandbox-123"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
