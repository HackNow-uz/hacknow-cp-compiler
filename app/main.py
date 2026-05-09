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

# SECURITY: Remove INTERNAL_TOKEN from process environment after Pydantic
# settings have read it. Otherwise a sandboxed process can read it via
# /proc/<api-pid>/environ if /proc is bind-mounted into the sandbox.
os.environ.pop("INTERNAL_TOKEN", None)


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
        "19 languages, and IOI/ICPC/Codeforces scoring modes."
    ),
    version=settings.service_version,
    lifespan=lifespan,
    # Disable interactive docs in production — they expose the API surface
    # to unauthenticated reconnaissance. Set EXPOSE_DOCS=1 for development.
    docs_url="/docs" if os.environ.get("EXPOSE_DOCS") == "1" else None,
    redoc_url="/redoc" if os.environ.get("EXPOSE_DOCS") == "1" else None,
    openapi_url="/openapi.json" if os.environ.get("EXPOSE_DOCS") == "1" else None,
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

# CORS — service-to-service API uses bearer tokens, not cookies.
# allow_credentials=False prevents cookie leaks even if origins are misconfigured.
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def request_size_limit(request, call_next):
    """Reject oversized request bodies before reading them into memory."""
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > settings.max_request_body_bytes:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        except ValueError:
            pass
    return await call_next(request)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": settings.service_version,
        "status": "running",
        "docs": "/docs",
    }
