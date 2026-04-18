"""Registry-backed application metrics facade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from opentelemetry import metrics as otel_metrics


class MetricKind(StrEnum):
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    UP_DOWN_COUNTER = "up_down_counter"


class MetricName(StrEnum):
    API_ERRORS = "http.server.errors"
    OUTBOUND_REQUESTS = "http.client.requests"
    OUTBOUND_REQUEST_DURATION = "http.client.duration"
    IDEMPOTENCY_REQUESTS = "idempotency.requests"
    IDEMPOTENCY_LEASE_STEALS = "idempotency.lease_steals"
    REDIS_SERVICE_EVENTS = "redis.service.events"
    TASKS_DISPATCHED = "worker.tasks.dispatched"
    TASKS_IN_FLIGHT = "worker.tasks.in_flight"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: MetricName
    kind: MetricKind
    description: str
    unit: str = "1"
    allowed_attributes: frozenset[str] = frozenset()


METRIC_DEFINITIONS: dict[MetricName, MetricDefinition] = {
    MetricName.API_ERRORS: MetricDefinition(
        name=MetricName.API_ERRORS,
        kind=MetricKind.COUNTER,
        description="Count of API errors emitted by the service.",
        allowed_attributes=frozenset({"code", "status_class", "retryable"}),
    ),
    MetricName.OUTBOUND_REQUESTS: MetricDefinition(
        name=MetricName.OUTBOUND_REQUESTS,
        kind=MetricKind.COUNTER,
        description="Count of outbound HTTP requests made by the service.",
        allowed_attributes=frozenset({"service", "method", "status_class"}),
    ),
    MetricName.OUTBOUND_REQUEST_DURATION: MetricDefinition(
        name=MetricName.OUTBOUND_REQUEST_DURATION,
        kind=MetricKind.HISTOGRAM,
        description="Outbound HTTP request duration in milliseconds.",
        unit="ms",
        allowed_attributes=frozenset({"service", "method", "status_class"}),
    ),
    MetricName.IDEMPOTENCY_REQUESTS: MetricDefinition(
        name=MetricName.IDEMPOTENCY_REQUESTS,
        kind=MetricKind.COUNTER,
        description="Count of idempotent request outcomes.",
        allowed_attributes=frozenset({"status", "storage_source"}),
    ),
    MetricName.IDEMPOTENCY_LEASE_STEALS: MetricDefinition(
        name=MetricName.IDEMPOTENCY_LEASE_STEALS,
        kind=MetricKind.COUNTER,
        description="Count of expired idempotency leases that were reclaimed.",
    ),
    MetricName.REDIS_SERVICE_EVENTS: MetricDefinition(
        name=MetricName.REDIS_SERVICE_EVENTS,
        kind=MetricKind.COUNTER,
        description="Count of Redis service lifecycle and recovery events.",
        allowed_attributes=frozenset({"event", "source"}),
    ),
    MetricName.TASKS_DISPATCHED: MetricDefinition(
        name=MetricName.TASKS_DISPATCHED,
        kind=MetricKind.COUNTER,
        description="Count of Celery tasks dispatched from the application.",
        allowed_attributes=frozenset({"task_name"}),
    ),
    MetricName.TASKS_IN_FLIGHT: MetricDefinition(
        name=MetricName.TASKS_IN_FLIGHT,
        kind=MetricKind.UP_DOWN_COUNTER,
        description="Number of tasks currently in progress.",
        allowed_attributes=frozenset({"task_name"}),
    ),
}

_meter_provider: Any | None = None
_metrics_instance: AppMetrics | None = None


def configure_metrics_provider(meter_provider: Any) -> None:
    """Bind the process-local meter provider used by the application facade."""
    global _meter_provider, _metrics_instance
    _meter_provider = meter_provider
    _metrics_instance = None


def reset_metrics_provider() -> None:
    """Reset process-local metric state after telemetry shutdown."""
    global _meter_provider, _metrics_instance
    _meter_provider = None
    _metrics_instance = None


class AppMetrics:
    """Small validated facade over a fixed metric registry."""

    def __init__(self, meter_provider: Any) -> None:
        self._meter = meter_provider.get_meter("pfm")
        self._instruments: dict[MetricName, Any] = {}

    def counter(
        self,
        name: MetricName,
        value: int = 1,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        definition = self._definition(name, expected_kind=MetricKind.COUNTER)
        instrument = self._instrument_for(definition)
        instrument.add(value, attributes=self._validated_attributes(definition, attributes))

    def histogram(
        self,
        name: MetricName,
        value: float,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        definition = self._definition(name, expected_kind=MetricKind.HISTOGRAM)
        instrument = self._instrument_for(definition)
        instrument.record(value, attributes=self._validated_attributes(definition, attributes))

    def up_down_counter(
        self,
        name: MetricName,
        value: int,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        definition = self._definition(name, expected_kind=MetricKind.UP_DOWN_COUNTER)
        instrument = self._instrument_for(definition)
        instrument.add(value, attributes=self._validated_attributes(definition, attributes))

    def record_outbound_request(
        self,
        *,
        service: str,
        method: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        attributes = {
            "service": service,
            "method": method.upper(),
            "status_class": f"{status_code // 100}xx",
        }
        self.counter(MetricName.OUTBOUND_REQUESTS, attributes=attributes)
        self.histogram(
            MetricName.OUTBOUND_REQUEST_DURATION,
            value=duration_ms,
            attributes=attributes,
        )

    def record_api_error(
        self,
        *,
        code: str,
        status_code: int,
        retryable: bool,
    ) -> None:
        self.counter(
            MetricName.API_ERRORS,
            attributes={
                "code": code,
                "status_class": f"{status_code // 100}xx",
                "retryable": str(retryable).lower(),
            },
        )

    def record_idempotency_request(
        self,
        *,
        status: str,
        storage_source: str,
    ) -> None:
        self.counter(
            MetricName.IDEMPOTENCY_REQUESTS,
            attributes={
                "status": status,
                "storage_source": storage_source,
            },
        )

    def record_idempotency_lease_steal(self) -> None:
        self.counter(MetricName.IDEMPOTENCY_LEASE_STEALS)

    def record_redis_reconnect_attempt(self, *, source: str) -> None:
        self._record_redis_service_event(event="reconnect_attempt", source=source)

    def record_redis_reconnect_cooldown_skip(self, *, source: str) -> None:
        self._record_redis_service_event(event="cooldown_skip", source=source)

    def record_redis_stopped_access(self, *, source: str) -> None:
        self._record_redis_service_event(event="stopped_access", source=source)

    def record_task_dispatch(self, *, task_name: str) -> None:
        self.counter(MetricName.TASKS_DISPATCHED, attributes={"task_name": task_name})

    def adjust_in_flight_tasks(self, *, task_name: str, delta: int) -> None:
        self.up_down_counter(
            MetricName.TASKS_IN_FLIGHT,
            value=delta,
            attributes={"task_name": task_name},
        )

    def _definition(self, name: MetricName, *, expected_kind: MetricKind) -> MetricDefinition:
        definition = METRIC_DEFINITIONS[name]
        if definition.kind != expected_kind:
            raise ValueError(
                f"Metric {name.value} is registered as {definition.kind.value}, "
                f"not {expected_kind.value}"
            )
        return definition

    def _record_redis_service_event(self, *, event: str, source: str) -> None:
        self.counter(
            MetricName.REDIS_SERVICE_EVENTS,
            attributes={
                "event": event,
                "source": source,
            },
        )

    def _instrument_for(self, definition: MetricDefinition) -> Any:
        instrument = self._instruments.get(definition.name)
        if instrument is not None:
            return instrument

        if definition.kind == MetricKind.COUNTER:
            instrument = self._meter.create_counter(
                definition.name.value,
                description=definition.description,
                unit=definition.unit,
            )
        elif definition.kind == MetricKind.HISTOGRAM:
            instrument = self._meter.create_histogram(
                definition.name.value,
                description=definition.description,
                unit=definition.unit,
            )
        elif definition.kind == MetricKind.UP_DOWN_COUNTER:
            instrument = self._meter.create_up_down_counter(
                definition.name.value,
                description=definition.description,
                unit=definition.unit,
            )
        else:
            raise ValueError(f"Unsupported metric kind: {definition.kind}")

        self._instruments[definition.name] = instrument
        return instrument

    @staticmethod
    def _validated_attributes(
        definition: MetricDefinition,
        attributes: dict[str, str | int | float | bool] | None,
    ) -> dict[str, str | int | float | bool]:
        if not attributes:
            return {}

        invalid_keys = sorted(set(attributes) - set(definition.allowed_attributes))
        if invalid_keys:
            raise ValueError(
                f"Metric {definition.name.value} does not allow attributes: "
                f"{', '.join(invalid_keys)}"
            )

        return dict(attributes)


def get_metrics() -> AppMetrics:
    """FastAPI dependency for application metrics."""
    global _metrics_instance
    if _metrics_instance is None:
        meter_provider = _meter_provider or otel_metrics.get_meter_provider()
        _metrics_instance = AppMetrics(meter_provider)
    return _metrics_instance
