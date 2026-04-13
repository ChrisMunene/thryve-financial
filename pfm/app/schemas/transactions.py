"""Schemas for transaction import workflows."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class TransactionImportRequest(BaseModel):
    access_token: SecretStr
    cursor: str | None = None


class TransactionImportResponse(BaseModel):
    task_id: str = Field(description="Celery task identifier for the categorization job.")
    imported_count: int = Field(ge=0)
    next_cursor: str | None = None
    has_more: bool = False
