from fastapi import APIRouter, Depends, Response

from app.api.auth import verify_token
from app.services.metrics import CONTENT_TYPE_LATEST, export

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(_: str = Depends(verify_token)):
    """Prometheus text exposition format. Requires bearer token."""
    return Response(content=export(), media_type=CONTENT_TYPE_LATEST)
