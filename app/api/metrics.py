from fastapi import APIRouter, Response

from app.services.metrics import CONTENT_TYPE_LATEST, export

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus text exposition format."""
    return Response(content=export(), media_type=CONTENT_TYPE_LATEST)
