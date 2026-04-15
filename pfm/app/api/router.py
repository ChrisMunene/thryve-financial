from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.transactions import router as transactions_router
from app.core.idempotency import IdempotencyRoute

api_router = APIRouter(route_class=IdempotencyRoute)
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(transactions_router)
