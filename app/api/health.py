import os
import time
from fastapi import APIRouter, Depends
from app.api.auth import verify_token
from app.config import settings
from app.schemas.responses import (
    CompileCacheStats, ConcurrencyStats, HealthResponse,
)

router = APIRouter()

_start_time = time.time()


def _temp_dir_size_mb() -> int:
    """Approximate temp directory disk usage in MB."""
    try:
        total = 0
        base = settings.compiler_temp_dir
        for entry in os.scandir(base):
            if entry.is_dir(follow_symlinks=False):
                for sub in os.scandir(entry.path):
                    try:
                        total += sub.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
            else:
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
        return total // (1024 * 1024)
    except OSError:
        return -1


@router.get("/health")
async def health_check():
    """Public liveness probe — returns minimal info."""
    return {"status": "ok"}


@router.get("/health/detail", response_model=HealthResponse)
async def health_detail(_: str = Depends(verify_token)):
    """Detailed health with cache stats, concurrency, and disk usage. Requires token."""
    from app.sandbox import nsjail_runner

    uptime = int(time.time() - _start_time)
    cache_stats = nsjail_runner._compile_cache.stats

    return HealthResponse(
        status="ok",
        version=settings.service_version,
        uptime_seconds=uptime,
        compile_cache=CompileCacheStats(**cache_stats),
        concurrency=ConcurrencyStats(
            global_slots=nsjail_runner._global_slots,
            per_language_slots=nsjail_runner.slots_per_language,
        ),
        temp_dir_mb=_temp_dir_size_mb(),
    )
