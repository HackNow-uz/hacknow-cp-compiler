from fastapi import APIRouter
from .health import router as health_router
from .languages import router as languages_router
from .execute import router as execute_router
from .judge import router as judge_router
from .metrics import router as metrics_router

api_router = APIRouter()

# Include all routers
api_router.include_router(health_router, tags=["health"])
api_router.include_router(languages_router, tags=["languages"])
api_router.include_router(execute_router, tags=["execution"])
api_router.include_router(judge_router, tags=["judge"])
api_router.include_router(metrics_router, tags=["metrics"])
