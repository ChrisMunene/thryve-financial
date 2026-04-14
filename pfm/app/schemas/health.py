"""Schemas for health and readiness responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AuthHealthCheck(BaseModel):
    status: Literal["healthy", "unhealthy"]
    provider: str | None = None


class LatencyHealthCheck(BaseModel):
    status: Literal["healthy", "unhealthy"]
    latency_ms: int | None = None


class CeleryHealthCheck(BaseModel):
    status: Literal["healthy", "unhealthy"]
    workers: int | None = None
    queues: dict[str, int] | None = None


class HealthChecks(BaseModel):
    database: LatencyHealthCheck
    redis: LatencyHealthCheck
    auth: AuthHealthCheck
    celery: CeleryHealthCheck


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    checks: HealthChecks
    version: str
    uptime_seconds: int


class ReadinessResponseData(BaseModel):
    status: Literal["healthy"] = "healthy"
    dependencies: dict[str, Literal["ok"]]
