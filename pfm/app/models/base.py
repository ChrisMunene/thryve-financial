"""
SQLAlchemy base model with shared mixins.

UUIDMixin: UUID primary key
TimestampMixin: created_at, updated_at auto-managed
SoftDeleteMixin: deleted_at for soft deletes
MoneyColumn: Numeric(12, 2) for financial values — never use float for money
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        self.deleted_at = None


def MoneyColumn(**kwargs) -> Mapped[Decimal]:  # noqa: N802 — intentional PascalCase for column factory
    """Column type for monetary values. Uses Numeric(12, 2) — never float.

    Usage:
        amount: Mapped[Decimal] = MoneyColumn(nullable=False)
    """
    return mapped_column(Numeric(precision=12, scale=2), **kwargs)
