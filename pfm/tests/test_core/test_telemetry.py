"""Tests for telemetry configuration."""

from app.core import telemetry


class _FakeMetricReader:
    def __init__(self, exporter, export_interval_millis):
        self.exporter = exporter
        self.export_interval_millis = export_interval_millis


class _FakeTracerProvider:
    def __init__(self, resource):
        self.resource = resource
        self.processors = []

    def add_span_processor(self, processor):
        self.processors.append(processor)


class _FakeMeterProvider:
    def __init__(self, resource, metric_readers):
        self.resource = resource
        self.metric_readers = metric_readers


class _FakeSpanProcessor:
    def __init__(self, exporter):
        self.exporter = exporter


class _FakeExporter:
    def __init__(self, endpoint=None):
        self.endpoint = endpoint


class _FakeInstrumentor:
    def instrument(self):
        return None


def test_configure_telemetry_uses_otlp_metric_exporter(monkeypatch):
    captured = {}

    monkeypatch.setattr(telemetry, "TracerProvider", _FakeTracerProvider)
    monkeypatch.setattr(telemetry, "MeterProvider", _FakeMeterProvider)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _FakeSpanProcessor)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", _FakeExporter)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", _FakeExporter)
    monkeypatch.setattr(telemetry, "ConsoleSpanExporter", _FakeExporter)
    monkeypatch.setattr(telemetry, "ConsoleMetricExporter", _FakeExporter)
    monkeypatch.setattr(telemetry, "PeriodicExportingMetricReader", _FakeMetricReader)
    monkeypatch.setattr(telemetry, "SQLAlchemyInstrumentor", lambda: _FakeInstrumentor())
    monkeypatch.setattr(telemetry, "RedisInstrumentor", lambda: _FakeInstrumentor())
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", lambda: _FakeInstrumentor())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: captured.setdefault("trace", provider))
    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", lambda provider: captured.setdefault("metrics", provider))

    telemetry.configure_telemetry(
        service_name="pfm",
        environment="production",
        exporter_type="otlp",
        otlp_endpoint="http://otel:4317",
    )

    metric_reader = captured["metrics"].metric_readers[0]
    assert isinstance(metric_reader.exporter, _FakeExporter)
    assert metric_reader.exporter.endpoint == "http://otel:4317"
