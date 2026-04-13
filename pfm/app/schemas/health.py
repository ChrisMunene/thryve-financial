"""Schemas for health and readiness responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LivenessResponseData(BaseModel):
    status: Literal["healthy"] = "healthy"


class ReadinessResponseData(BaseModel):
    status: Literal["healthy"] = "healthy"
    dependencies: dict[str, Literal["ok"]]
