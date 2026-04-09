from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database.url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )


@lru_cache
def get_async_session_factory():
    engine = get_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def __getattr__(name: str):
    if name == "engine":
        return get_engine()
    if name == "async_session_factory":
        return get_async_session_factory()
    raise AttributeError(name)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async_session_factory = get_async_session_factory()
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
