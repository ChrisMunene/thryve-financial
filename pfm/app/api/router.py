from fastapi import APIRouter

from app.api.health import router as health_router
from app.core.idempotency import IdempotencyRoute

api_router = APIRouter(route_class=IdempotencyRoute)
api_router.include_router(health_router)
