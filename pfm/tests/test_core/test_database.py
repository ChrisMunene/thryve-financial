"""Tests for database hardening: pool config, Decimal types, soft delete."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric

from app.config import get_settings
from app.models.base import MoneyColumn, SoftDeleteMixin


class TestPoolConfig:
    def test_pool_size_from_config(self):
        settings = get_settings()
        from app.db.session import engine
        assert engine.pool.size() == settings.database.pool_size

    def test_pool_overflow_from_config(self):
        settings = get_settings()
        from app.db.session import engine
        assert engine.pool._max_overflow == settings.database.max_overflow


class TestMoneyColumn:
    def test_money_column_is_numeric(self):
        col = MoneyColumn()
        # MappedColumn wraps a Numeric — verify via the column property
        assert col.column.type.precision == 12
        assert col.column.type.scale == 2


class TestSoftDeleteMixin:
    def test_not_deleted_by_default(self):
        class FakeModel(SoftDeleteMixin):
            deleted_at = None

        obj = FakeModel()
        assert not obj.is_deleted

    def test_soft_delete_sets_timestamp(self):
        class FakeModel(SoftDeleteMixin):
            deleted_at = None

        obj = FakeModel()
        obj.soft_delete()
        assert obj.is_deleted
        assert isinstance(obj.deleted_at, datetime)

    def test_restore_clears_timestamp(self):
        class FakeModel(SoftDeleteMixin):
            deleted_at = None

        obj = FakeModel()
        obj.soft_delete()
        assert obj.is_deleted
        obj.restore()
        assert not obj.is_deleted
        assert obj.deleted_at is None
