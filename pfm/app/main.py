from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.redis import redis_client
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Startup
    await redis_client.initialize()
    # TODO: Load pattern rules into memory
    # TODO: Load few-shot pool into memory
    yield
    # Shutdown
    await redis_client.close()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="PFM API",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # Mount routers
    from app.api.router import api_router

    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()
