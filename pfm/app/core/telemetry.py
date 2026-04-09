"""
OpenTelemetry setup.

Auto-instruments FastAPI, SQLAlchemy, Redis, and httpx.
Console exporter in dev, OTLP in staging/prod.
Custom business metrics API available as dependency.
"""

import structlog
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = structlog.get_logger()


def configure_telemetry(
    service_name: str = "pfm",
    environment: str = "development",
    exporter_type: str = "console",
    otlp_endpoint: str = "",
) -> None:
    """Configure OpenTelemetry tracing and metrics."""

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": environment}
    )

    # --- Tracing ---
    tracer_provider = TracerProvider(resource=resource)

    if exporter_type == "otlp" and otlp_endpoint:
        span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    else:
        span_exporter = ConsoleSpanExporter()

    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    if exporter_type == "console":
        metric_reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(), export_interval_millis=60000
        )
    else:
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=otlp_endpoint), export_interval_millis=30000
        )

    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- Auto-instrumentation ---
    # FastAPI is instrumented at app level (see instrument_app)
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    logger.info(
        "telemetry.configured",
        exporter=exporter_type,
        environment=environment,
    )


def instrument_app(app) -> None:
    """Instrument a FastAPI app with OTEL."""
    FastAPIInstrumentor.instrument_app(app)


def shutdown_telemetry() -> None:
    """Flush and shut down OTEL providers."""
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()


# --- Business metrics API ---

_meter = None


def _get_meter():
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("pfm")
    return _meter


class MetricsService:
    """Custom business metrics. Inject via Depends()."""

    def __init__(self) -> None:
        self._counters: dict[str, metrics.Counter] = {}
        self._histograms: dict[str, metrics.Histogram] = {}

    def counter(self, name: str, value: int = 1, attributes: dict | None = None) -> None:
        if name not in self._counters:
            self._counters[name] = _get_meter().create_counter(name)
        self._counters[name].add(value, attributes=attributes or {})

    def histogram(self, name: str, value: float, attributes: dict | None = None) -> None:
        if name not in self._histograms:
            self._histograms[name] = _get_meter().create_histogram(name)
        self._histograms[name].record(value, attributes=attributes or {})


_metrics_instance: MetricsService | None = None


def get_metrics() -> MetricsService:
    """FastAPI dependency for business metrics. Returns a cached singleton."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = MetricsService()
    return _metrics_instance
