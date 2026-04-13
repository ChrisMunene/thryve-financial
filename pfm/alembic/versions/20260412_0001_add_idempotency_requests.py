"""add idempotency requests

Revision ID: 20260412_0001
Revises:
Create Date: 2026-04-12 21:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=191), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_type", sa.String(length=128), nullable=True),
        sa.Column("result_ref", sa.JSON(), nullable=True),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )
    op.create_index(
        "ix_idempotency_requests_scope",
        "idempotency_requests",
        ["scope"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_requests_status",
        "idempotency_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_requests_lease_expires_at",
        "idempotency_requests",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_requests_expires_at",
        "idempotency_requests",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_requests_expires_at", table_name="idempotency_requests")
    op.drop_index("ix_idempotency_requests_lease_expires_at", table_name="idempotency_requests")
    op.drop_index("ix_idempotency_requests_status", table_name="idempotency_requests")
    op.drop_index("ix_idempotency_requests_scope", table_name="idempotency_requests")
    op.drop_table("idempotency_requests")
