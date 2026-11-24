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


def semaphore_in_use(sem, total: int) -> int | None:
    """Semafor orqali band slotlar soni: jami − bo'sh.

    `asyncio.Semaphore` bo'sh sonni faqat ichki `_value` da saqlaydi (ochiq API yo'q). Atribut topilmasa yoki
    kutilmagan qiymat bo'lsa `None` qaytadi — noto'g'ri son ko'rsatgandan ko'ra «noma'lum» afzal.
    """
    free = getattr(sem, "_value", None)
    if not isinstance(free, int) or isinstance(free, bool) or total <= 0:
        return None
    return max(0, min(total, total - free))


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

    judge_inflight = judge_max = None
    try:
        from app.api import judge as judge_api
        judge_max = judge_api._max_inflight
        judge_inflight = semaphore_in_use(judge_api._judge_semaphore, judge_max)
    except Exception:  # pragma: no cover — health hech qachon shu sababli yiqilmasin
        import logging
        logging.getLogger(__name__).warning("health: judge bandligi o'qilmadi", exc_info=True)

    return HealthResponse(
        status="ok",
        version=settings.service_version,
        uptime_seconds=uptime,
        compile_cache=CompileCacheStats(**cache_stats),
        concurrency=ConcurrencyStats(
            global_slots=nsjail_runner._global_slots,
            per_language_slots=nsjail_runner.slots_per_language,
            global_in_use=semaphore_in_use(nsjail_runner._global_semaphore, nsjail_runner._global_slots),
            judge_inflight=judge_inflight,
            judge_max_inflight=judge_max,
        ),
        temp_dir_mb=_temp_dir_size_mb(),
    )
