import logging
import os
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.core.limiter import limiter
from app.core.logging_config import configure_logging
from app.api.router import api_router

configure_logging(log_level=settings.log_level)
logger = logging.getLogger(__name__)


def _cleanup_stale_temp() -> int:
    """Remove leftover temp directories from a previous crash.
    Preserves ccache_ prefixed dirs (compile cache)."""
    temp_dir = settings.compiler_temp_dir
    if not os.path.isdir(temp_dir):
        return 0
    removed = 0
    for entry in os.scandir(temp_dir):
        if entry.is_dir(follow_symlinks=False):
            if entry.name.startswith("ccache_"):
                continue
            try:
                shutil.rmtree(entry.path, ignore_errors=True)
                removed += 1
            except OSError:
                pass
    return removed


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.service_name, settings.service_version)
    removed = _cleanup_stale_temp()
    if removed:
        logger.info("Cleaned up %d stale temp directories", removed)
    yield
    logger.info("Shutting down %s", settings.service_name)


app = FastAPI(
    title="CP Compiler",
    description=(
        "Competitive programming judge with nsjail sandboxing, "
        "19 languages, and IOI/ICPC/Codeforces scoring modes. "
        "See /api/v1/health for diagnostics and /api/v1/languages for supported languages."
    ),
    version=settings.service_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Trusted hosts
_trusted_hosts = [
    h.strip()
    for h in (settings.trusted_hosts or "").split(",")
    if h.strip()
] or ["localhost", "127.0.0.1"]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)

# CORS
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": settings.service_version,
        "status": "running",
        "docs": "/docs",
    }
