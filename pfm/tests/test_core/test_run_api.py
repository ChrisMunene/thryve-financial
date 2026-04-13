"""Tests for the blessed API runner."""

from app.run_api import main


def test_runner_disables_uvicorn_access_logs(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("app.run_api.uvicorn.run", fake_run)

    main(["--host", "127.0.0.1", "--port", "9001", "--reload"])

    assert captured["app"] == "app.main:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["reload"] is True
    assert captured["access_log"] is False
    assert captured["log_config"] is None
