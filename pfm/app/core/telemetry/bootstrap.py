"""Process bootstrap for OpenTelemetry tracing and metrics."""

from __future__ import annotations

import atexit
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import structlog
from fastapi import FastAPI
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
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from app.config import Settings, TelemetryExporter
from app.db.session import get_engine

from .metrics import configure_metrics_provider, reset_metrics_provider

logger = structlog.get_logger()


class TelemetryProcessRole(StrEnum):
    API = "api"
    WORKER = "worker"
    BEAT = "beat"


@dataclass(slots=True)
class TelemetryRuntime:
    """Owns provider lifecycles and instrumentation cleanup for a process."""

    process_role: TelemetryProcessRole
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    _shutdown_callbacks: list[Callable[[], None]] = field(default_factory=list)
    _instrumented_apps: list[FastAPI] = field(default_factory=list)
    _is_shutdown: bool = False

    def instrument_fastapi_app(self, app: FastAPI, settings: Settings) -> None:
        marker = "_pfm_otel_instrumented"
        if getattr(app.state, marker, False):
            return

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=",".join(settings.observability.excluded_urls),
            tracer_provider=self.tracer_provider,
            meter_provider=self.meter_provider,
            server_request_hook=_server_request_hook,
        )
        setattr(app.state, marker, True)
        self._instrumented_apps.append(app)

    def add_shutdown_callback(self, callback: Callable[[], None]) -> None:
        self._shutdown_callbacks.append(callback)

    def shutdown(self) -> None:
        global _ACTIVE_RUNTIME

        if self._is_shutdown:
            return

        for app in list(self._instrumented_apps):
            try:
                FastAPIInstrumentor.uninstrument_app(app)
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.warning(
                    "telemetry.fastapi_uninstrument_failed",
                    process_role=self.process_role.value,
                    error=str(exc),
                )

        for callback in reversed(self._shutdown_callbacks):
            try:
                callback()
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.warning(
                    "telemetry.uninstrument_failed",
                    process_role=self.process_role.value,
                    error=str(exc),
                )

        try:
            self.tracer_provider.force_flush()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "telemetry.force_flush_failed",
                process_role=self.process_role.value,
                error=str(exc),
            )

        try:
            self.meter_provider.force_flush()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "telemetry.metric_force_flush_failed",
                process_role=self.process_role.value,
                error=str(exc),
            )

        reset_metrics_provider()
        self._is_shutdown = True
        if _ACTIVE_RUNTIME is self:
            _ACTIVE_RUNTIME = None


_ACTIVE_RUNTIME: TelemetryRuntime | None = None
_PROCESS_TRACER_PROVIDER: TracerProvider | None = None
_PROCESS_METER_PROVIDER: MeterProvider | None = None
_PROCESS_ROLE: TelemetryProcessRole | None = None
_PROCESS_SHUTDOWN_REGISTERED = False


def bootstrap_api_telemetry(app: FastAPI, settings: Settings) -> TelemetryRuntime:
    """Bootstrap OpenTelemetry for the FastAPI API process."""
    runtime = _bootstrap_runtime(TelemetryProcessRole.API, settings)
    runtime.instrument_fastapi_app(app, settings)
    return runtime


def bootstrap_worker_telemetry(
    process_role: TelemetryProcessRole,
    settings: Settings,
) -> TelemetryRuntime:
    """Bootstrap OpenTelemetry for Celery worker or beat processes."""
    if process_role == TelemetryProcessRole.API:
        raise ValueError("bootstrap_worker_telemetry does not accept the api process role")
    return _bootstrap_runtime(process_role, settings)


def _bootstrap_runtime(
    process_role: TelemetryProcessRole,
    settings: Settings,
) -> TelemetryRuntime:
    global _ACTIVE_RUNTIME, _PROCESS_METER_PROVIDER, _PROCESS_ROLE, _PROCESS_TRACER_PROVIDER

    if _ACTIVE_RUNTIME is not None and not _ACTIVE_RUNTIME._is_shutdown:
        if _ACTIVE_RUNTIME.process_role != process_role:
            raise RuntimeError(
                "Telemetry is already active in this process. Shut it down before "
                f"bootstrapping {process_role.value}."
            )
        return _ACTIVE_RUNTIME

    if _PROCESS_TRACER_PROVIDER is None or _PROCESS_METER_PROVIDER is None:
        resource = _build_resource(settings, process_role)
        tracer_provider = _build_tracer_provider(settings, resource)
        meter_provider = _build_meter_provider(settings, resource)
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        _PROCESS_TRACER_PROVIDER = tracer_provider
        _PROCESS_METER_PROVIDER = meter_provider
        _PROCESS_ROLE = process_role
        _register_process_shutdown()
    else:
        if _PROCESS_ROLE != process_role:
            raise RuntimeError(
                "Telemetry providers are already initialized for this process as "
                f"{_PROCESS_ROLE.value}. Start a new process to bootstrap "
                f"{process_role.value} telemetry."
            )
        tracer_provider = _PROCESS_TRACER_PROVIDER
        meter_provider = _PROCESS_METER_PROVIDER

    configure_metrics_provider(meter_provider)

    runtime = TelemetryRuntime(
        process_role=process_role,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
    _instrument_common_libraries(runtime)

    if process_role in (TelemetryProcessRole.WORKER, TelemetryProcessRole.BEAT):
        celery_instrumentor = _load_celery_instrumentor()
        if celery_instrumentor is not None:
            celery_instrumentor.instrument(
                tracer_provider=tracer_provider,
                meter_provider=meter_provider,
            )
            runtime.add_shutdown_callback(celery_instrumentor.uninstrument)

    _ACTIVE_RUNTIME = runtime
    logger.info(
        "telemetry.bootstrapped",
        process_role=process_role.value,
        traces_exporter=settings.observability.traces_exporter.value,
        metrics_exporter=settings.observability.metrics_exporter.value,
    )
    return runtime


def _build_resource(settings: Settings, process_role: TelemetryProcessRole) -> Resource:
    attributes = {
        "service.namespace": settings.observability.service_namespace,
        "service.name": settings.observability.service_name_for_role(process_role.value),
        "service.version": _resolve_service_version(),
        "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        "deployment.environment.name": settings.environment.value,
    }
    attributes.update(settings.observability.resource_attributes)
    return Resource.create(attributes)


def _build_tracer_provider(settings: Settings, resource: Resource) -> TracerProvider:
    sampler = ParentBased(TraceIdRatioBased(settings.observability.sampling_ratio))
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)

    span_exporter = _build_span_exporter(settings)
    if span_exporter is not None:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                span_exporter,
                schedule_delay_millis=settings.observability.bsp_schedule_delay_millis,
                export_timeout_millis=settings.observability.bsp_export_timeout_millis,
                max_queue_size=settings.observability.bsp_max_queue_size,
                max_export_batch_size=settings.observability.bsp_max_export_batch_size,
            )
        )

    return tracer_provider


def _build_meter_provider(settings: Settings, resource: Resource) -> MeterProvider:
    metric_readers = []
    metric_exporter = _build_metric_exporter(settings)
    if metric_exporter is not None:
        metric_readers.append(
            PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=settings.observability.metric_export_interval_millis,
            )
        )
    return MeterProvider(resource=resource, metric_readers=metric_readers)


def _build_span_exporter(settings: Settings) -> Any | None:
    if settings.observability.traces_exporter == TelemetryExporter.NONE:
        return None
    if settings.observability.traces_exporter == TelemetryExporter.CONSOLE:
        return ConsoleSpanExporter()
    return OTLPSpanExporter(
        endpoint=settings.observability.signal_endpoint("traces"),
        headers=settings.observability.otlp_headers,
        insecure=settings.observability.otlp_insecure,
    )


def _build_metric_exporter(settings: Settings) -> Any | None:
    if settings.observability.metrics_exporter == TelemetryExporter.NONE:
        return None
    if settings.observability.metrics_exporter == TelemetryExporter.CONSOLE:
        return ConsoleMetricExporter()
    return OTLPMetricExporter(
        endpoint=settings.observability.signal_endpoint("metrics"),
        headers=settings.observability.otlp_headers,
        insecure=settings.observability.otlp_insecure,
    )


def _instrument_common_libraries(runtime: TelemetryRuntime) -> None:
    engine = get_engine()
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=runtime.tracer_provider,
        meter_provider=runtime.meter_provider,
    )
    runtime.add_shutdown_callback(lambda: SQLAlchemyInstrumentor().uninstrument())

    RedisInstrumentor().instrument(
        tracer_provider=runtime.tracer_provider,
        meter_provider=runtime.meter_provider,
    )
    runtime.add_shutdown_callback(lambda: RedisInstrumentor().uninstrument())

    HTTPXClientInstrumentor().instrument(
        tracer_provider=runtime.tracer_provider,
        meter_provider=runtime.meter_provider,
        request_hook=_httpx_request_hook,
    )
    runtime.add_shutdown_callback(lambda: HTTPXClientInstrumentor().uninstrument())


def _server_request_hook(span: Any, scope: dict[str, Any]) -> None:
    if span is None or not span.is_recording():
        return
    span.set_attribute(
        "pfm.request_id_present",
        _headers_contain(scope.get("headers", []), "x-request-id"),
    )


def _httpx_request_hook(span: Any, request: Any) -> None:
    if span is None or not span.is_recording():
        return
    headers = request[2] if isinstance(request, tuple) and len(request) > 2 else request
    span.set_attribute(
        "pfm.request_id_propagated",
        _headers_contain(headers, "x-request-id"),
    )


def _headers_contain(headers: Any, header_name: str) -> bool:
    normalized = header_name.lower()
    if isinstance(headers, dict):
        return any(str(key).lower() == normalized for key in headers)

    for item in headers or []:
        if not isinstance(item, tuple) or len(item) < 1:
            continue
        key = item[0]
        if isinstance(key, bytes):
            key = key.decode("latin-1")
        if str(key).lower() == normalized:
            return True
    return False


def _resolve_service_version() -> str:
    try:
        return version("pfm")
    except PackageNotFoundError:
        return "0.0.0"


def _load_celery_instrumentor() -> Any | None:
    try:
        module = import_module("opentelemetry.instrumentation.celery")
    except ModuleNotFoundError as exc:
        logger.warning(
            "telemetry.celery_instrumentation_unavailable",
            error=str(exc),
        )
        return None

    return module.CeleryInstrumentor()


def _register_process_shutdown() -> None:
    global _PROCESS_SHUTDOWN_REGISTERED

    if _PROCESS_SHUTDOWN_REGISTERED:
        return

    atexit.register(_shutdown_process_providers)
    _PROCESS_SHUTDOWN_REGISTERED = True


def _shutdown_process_providers() -> None:
    global _PROCESS_METER_PROVIDER, _PROCESS_ROLE, _PROCESS_TRACER_PROVIDER

    tracer_provider = _PROCESS_TRACER_PROVIDER
    meter_provider = _PROCESS_METER_PROVIDER

    if tracer_provider is None or meter_provider is None:
        return

    try:
        tracer_provider.force_flush()
    except Exception:  # pragma: no cover - interpreter shutdown cleanup
        pass

    try:
        meter_provider.force_flush()
    except Exception:  # pragma: no cover - interpreter shutdown cleanup
        pass

    try:
        tracer_provider.shutdown()
    except Exception:  # pragma: no cover - interpreter shutdown cleanup
        pass

    try:
        meter_provider.shutdown()
    except Exception:  # pragma: no cover - interpreter shutdown cleanup
        pass

    _PROCESS_TRACER_PROVIDER = None
    _PROCESS_METER_PROVIDER = None
    _PROCESS_ROLE = None
