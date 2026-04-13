"""Schemas for problem documentation endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.user_actions import UserAction


class ProblemDefinitionResponse(BaseModel):
    type: str
    title: str
    status: int
    code: str
    description: str
    default_detail: str
    retryable: bool
    user_action: UserAction | None = None
