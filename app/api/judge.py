import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from app.config import settings
from app.schemas.requests import JudgeRequest
from app.schemas.responses import JudgeResponse
from app.services.judge import judge_submission
from app.api.auth import verify_token
from app.core.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

# Backpressure: limits concurrent /judge requests.
# When exceeded, 503 is returned so the caller (or LB) can retry on another replica.
_max_inflight = settings.max_inflight_judge_requests
if _max_inflight <= 0:
    from app.sandbox import nsjail_runner
    _max_inflight = nsjail_runner._global_slots + 4
_judge_semaphore = asyncio.Semaphore(_max_inflight)
logger.info("Judge backpressure: max_inflight=%d", _max_inflight)


@router.post("/judge", response_model=JudgeResponse)
@limiter.limit("120/minute")
async def judge(
    request: Request,
    data: JudgeRequest,
    _: str = Depends(verify_token),
):
    """
    Judge a submission against multiple test cases.

    Supports ICPC (fail-fast), Codeforces (partial), and IOI (subtask) scoring.
    Returns per-test results with scores.

    Returns 503 if the service is overloaded (backpressure).
    """
    if _judge_semaphore.locked():
        logger.warning(
            "Backpressure: rejecting (inflight >= %d)",
            _max_inflight,
            extra={"submission_id": data.submission_id},
        )
        raise HTTPException(status_code=503, detail="Judge overloaded — retry later")

    async with _judge_semaphore:
        logger.info(
            "Judge request",
            extra={
                "submission_id": data.submission_id,
                "language_id": data.language_id,
                "tests_count": len(data.tests),
            },
        )

        try:
            result = await judge_submission(data)

            logger.info(
                "Judge complete",
                extra={
                    "submission_id": data.submission_id,
                    "status": str(result.status),
                    "score": result.score,
                    "max_score": result.max_score,
                },
            )

            return result

        except Exception:
            logger.exception("Internal error")
            raise HTTPException(status_code=500, detail="Internal server error")
