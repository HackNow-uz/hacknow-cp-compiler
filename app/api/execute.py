import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from app.schemas.requests import RunRequest
from app.schemas.responses import RunResponse
from app.services.executor import execute_code
from app.api.auth import verify_token
from app.core.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run", response_model=RunResponse)
@limiter.limit("30/minute")
async def run_code(
    request: Request,
    data: RunRequest,
    _: str = Depends(verify_token),
):
    """
    Execute code with a single input.
    Returns stdout, stderr, and execution metrics.
    """
    logger.info("Run request", extra={"language_id": data.language_id, "code_len": len(data.source_code)})

    try:
        return await execute_code(
            language_id=data.language_id,
            source_code=data.source_code,
            input_data=data.input,
            time_limit_ms=data.time_limit_ms,
            memory_limit_mb=data.memory_limit_mb,
        )
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(status_code=500, detail="Internal server error")
