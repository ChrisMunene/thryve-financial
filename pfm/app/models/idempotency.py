"""Durable idempotency records for public mutation endpoints."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class IdempotencyRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )

    scope: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    result_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_ref: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

