"""Tests for telemetry bootstrap and metrics."""

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.telemetry import MetricName, TelemetryProcessRole
from app.core.telemetry import bootstrap as telemetry_bootstrap
from app.core.telemetry.metrics import AppMetrics


class _FakeMetricReader:
    def __init__(self, exporter, export_interval_millis):
        self.exporter = exporter
        self.export_interval_millis = export_interval_millis


class _FakeTracerProvider:
    def __init__(self, resource, sampler):
        self.resource = resource
        self.sampler = sampler
        self.processors = []
        self.force_flush_calls = 0
        self.shutdown_calls = 0

    def add_span_processor(self, processor):
        self.processors.append(processor)

    def force_flush(self):
        self.force_flush_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1


class _FakeMeter:
    def __init__(self):
        self.created = {}

    def create_counter(self, name, **kwargs):
        instrument = _FakeCounter(name)
        self.created[name] = instrument
        return instrument

    def create_histogram(self, name, **kwargs):
        instrument = _FakeHistogram(name)
        self.created[name] = instrument
        return instrument

    def create_up_down_counter(self, name, **kwargs):
        instrument = _FakeCounter(name)
        self.created[name] = instrument
        return instrument


class _FakeMeterProvider:
    def __init__(self, resource, metric_readers):
        self.resource = resource
        self.metric_readers = metric_readers
        self.force_flush_calls = 0
        self.shutdown_calls = 0
        self.meter = _FakeMeter()

    def get_meter(self, name):
        return self.meter

    def force_flush(self):
        self.force_flush_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1


class _FakeSpanProcessor:
    def __init__(self, exporter, **kwargs):
        self.exporter = exporter
        self.kwargs = kwargs


class _FakeExporter:
    def __init__(self, endpoint=None, headers=None, insecure=None):
        self.endpoint = endpoint
        self.headers = headers
        self.insecure = insecure


class _FakeCounter:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def add(self, value, attributes=None):
        self.calls.append((value, attributes or {}))


class _FakeHistogram:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def record(self, value, attributes=None):
        self.calls.append((value, attributes or {}))


class _FakeLibraryInstrumentor:
    def __init__(self, key, captured):
        self._key = key
        self._captured = captured

    def instrument(self, **kwargs):
        self._captured[f"{self._key}_instrument"] = kwargs

    def uninstrument(self):
        self._captured[f"{self._key}_uninstrument"] = self._captured.get(
            f"{self._key}_uninstrument",
            0,
        ) + 1


class _FakeFastAPIInstrumentor:
    @staticmethod
    def instrument_app(app, **kwargs):
        app.state.fastapi_instrumented = kwargs

    @staticmethod
    def uninstrument_app(app):
        app.state.fastapi_uninstrumented = True


class _FakeAsyncEngine:
    sync_engine = object()


def _patch_bootstrap_dependencies(monkeypatch):
    captured = {}

    monkeypatch.setattr(telemetry_bootstrap, "_ACTIVE_RUNTIME", None)
    monkeypatch.setattr(telemetry_bootstrap, "_PROCESS_TRACER_PROVIDER", None)
    monkeypatch.setattr(telemetry_bootstrap, "_PROCESS_METER_PROVIDER", None)
    monkeypatch.setattr(telemetry_bootstrap, "_PROCESS_ROLE", None)
    monkeypatch.setattr(telemetry_bootstrap, "_PROCESS_SHUTDOWN_REGISTERED", False)
    monkeypatch.setattr(telemetry_bootstrap.atexit, "register", lambda callback: None)
    monkeypatch.setattr(telemetry_bootstrap, "TracerProvider", _FakeTracerProvider)
    monkeypatch.setattr(telemetry_bootstrap, "MeterProvider", _FakeMeterProvider)
    monkeypatch.setattr(telemetry_bootstrap, "BatchSpanProcessor", _FakeSpanProcessor)
    monkeypatch.setattr(telemetry_bootstrap, "OTLPSpanExporter", _FakeExporter)
    monkeypatch.setattr(telemetry_bootstrap, "OTLPMetricExporter", _FakeExporter)
    monkeypatch.setattr(telemetry_bootstrap, "ConsoleSpanExporter", _FakeExporter)
    monkeypatch.setattr(telemetry_bootstrap, "ConsoleMetricExporter", _FakeExporter)
    monkeypatch.setattr(telemetry_bootstrap, "PeriodicExportingMetricReader", _FakeMetricReader)
    monkeypatch.setattr(telemetry_bootstrap, "FastAPIInstrumentor", _FakeFastAPIInstrumentor)
    monkeypatch.setattr(
        telemetry_bootstrap,
        "SQLAlchemyInstrumentor",
        lambda: _FakeLibraryInstrumentor("sqlalchemy", captured),
    )
    monkeypatch.setattr(
        telemetry_bootstrap,
        "RedisInstrumentor",
        lambda: _FakeLibraryInstrumentor("redis", captured),
    )
    monkeypatch.setattr(
        telemetry_bootstrap,
        "HTTPXClientInstrumentor",
        lambda: _FakeLibraryInstrumentor("httpx", captured),
    )
    monkeypatch.setattr(
        telemetry_bootstrap,
        "_load_celery_instrumentor",
        lambda: _FakeLibraryInstrumentor("celery", captured),
    )
    monkeypatch.setattr(
        telemetry_bootstrap.trace,
        "set_tracer_provider",
        lambda provider: captured.setdefault("trace_provider_calls", []).append(provider),
    )
    monkeypatch.setattr(
        telemetry_bootstrap.metrics,
        "set_meter_provider",
        lambda provider: captured.setdefault("meter_provider_calls", []).append(provider),
    )
    monkeypatch.setattr(telemetry_bootstrap, "get_engine", lambda: _FakeAsyncEngine())

    return captured


def test_bootstrap_api_telemetry_uses_otlp_and_instruments_fastapi(monkeypatch):
    captured = _patch_bootstrap_dependencies(monkeypatch)
    app = FastAPI()
    settings = Settings(
        environment="development",
        observability={
            "traces_exporter": "otlp",
            "metrics_exporter": "otlp",
            "otlp_endpoint": "http://collector:4317",
        },
    )

    runtime = telemetry_bootstrap.bootstrap_api_telemetry(app, settings)

    assert runtime.process_role == TelemetryProcessRole.API
    assert app.state.fastapi_instrumented["excluded_urls"] == ",".join(
        settings.observability.excluded_urls
    )
    trace_provider = captured["trace_provider_calls"][0]
    meter_provider = captured["meter_provider_calls"][0]
    assert trace_provider.resource.attributes["service.name"] == "pfm-api"
    metric_reader = meter_provider.metric_readers[0]
    assert metric_reader.exporter.endpoint == "http://collector:4317"
    assert "request_hook" in captured["httpx_instrument"]

    runtime.shutdown()
    assert app.state.fastapi_uninstrumented is True
    assert trace_provider.force_flush_calls == 1
    assert trace_provider.shutdown_calls == 0
    assert meter_provider.force_flush_calls == 1
    assert meter_provider.shutdown_calls == 0


def test_bootstrap_worker_telemetry_is_idempotent_and_uses_worker_service_name(monkeypatch):
    captured = _patch_bootstrap_dependencies(monkeypatch)
    settings = Settings(
        environment="development",
        observability={
            "traces_exporter": "otlp",
            "metrics_exporter": "otlp",
            "otlp_endpoint": "http://collector:4317",
        },
    )

    runtime_one = telemetry_bootstrap.bootstrap_worker_telemetry(
        TelemetryProcessRole.WORKER,
        settings,
    )
    runtime_two = telemetry_bootstrap.bootstrap_worker_telemetry(
        TelemetryProcessRole.WORKER,
        settings,
    )

    assert runtime_one is runtime_two
    trace_provider = captured["trace_provider_calls"][0]
    assert trace_provider.resource.attributes["service.name"] == "pfm-worker"

    runtime_one.shutdown()
    runtime_one.shutdown()
    assert captured["celery_uninstrument"] == 1


def test_bootstrap_api_telemetry_does_not_require_celery_instrumentation(monkeypatch):
    _patch_bootstrap_dependencies(monkeypatch)
    app = FastAPI()
    settings = Settings(
        environment="development",
        observability={
            "traces_exporter": "otlp",
            "metrics_exporter": "otlp",
            "otlp_endpoint": "http://collector:4317",
        },
    )

    monkeypatch.setattr(telemetry_bootstrap, "_load_celery_instrumentor", lambda: None)

    runtime = telemetry_bootstrap.bootstrap_api_telemetry(app, settings)

    assert runtime.process_role == TelemetryProcessRole.API
    assert app.state.fastapi_instrumented["excluded_urls"] == ",".join(
        settings.observability.excluded_urls
    )

    runtime.shutdown()


def test_bootstrap_api_telemetry_reuses_process_providers_after_shutdown(monkeypatch):
    captured = _patch_bootstrap_dependencies(monkeypatch)
    settings = Settings(
        environment="development",
        observability={
            "traces_exporter": "otlp",
            "metrics_exporter": "otlp",
            "otlp_endpoint": "http://collector:4317",
        },
    )

    first_app = FastAPI()
    first_runtime = telemetry_bootstrap.bootstrap_api_telemetry(first_app, settings)
    first_trace_provider = first_runtime.tracer_provider
    first_meter_provider = first_runtime.meter_provider

    first_runtime.shutdown()

    second_app = FastAPI()
    second_runtime = telemetry_bootstrap.bootstrap_api_telemetry(second_app, settings)

    assert second_runtime is not first_runtime
    assert second_runtime.tracer_provider is first_trace_provider
    assert second_runtime.meter_provider is first_meter_provider
    assert len(captured["trace_provider_calls"]) == 1
    assert len(captured["meter_provider_calls"]) == 1

    second_runtime.shutdown()


def test_metrics_facade_validates_attributes_and_caches_instruments():
    provider = _FakeMeterProvider(resource=None, metric_readers=[])
    metrics = AppMetrics(provider)

    attributes = {"service": "plaid", "method": "GET", "status_class": "2xx"}
    metrics.counter(MetricName.OUTBOUND_REQUESTS, attributes=attributes)
    metrics.counter(MetricName.OUTBOUND_REQUESTS, attributes=attributes)

    counter = provider.meter.created[MetricName.OUTBOUND_REQUESTS.value]
    assert len(counter.calls) == 2
    assert len(provider.meter.created) == 1

    with pytest.raises(ValueError, match="does not allow attributes"):
        metrics.counter(
            MetricName.OUTBOUND_REQUESTS,
            attributes={"service": "plaid", "path": "/secret"},
        )
