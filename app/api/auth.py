"""Bearer token authentication for API endpoints."""

import logging
import secrets
from fastapi import Request, HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)

_INSECURE_DEFAULT_TOKENS = {
    "",
    "change-me",
    "change-me-to-secure-token",
    "change-me-to-a-secure-random-token",  # .env.example default
}


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def verify_token(request: Request) -> str:
    """
    Verify the internal service token supplied in the Authorization: Bearer header.
    Compared in constant time. Refuses insecure defaults.
    """
    expected = (settings.internal_token or "").strip()
    if expected in _INSECURE_DEFAULT_TOKENS:
        logger.critical("INTERNAL_TOKEN is unset or insecure — rejecting request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service token is not configured",
        )

    if len(expected) < 32 or len(set(expected)) < 10:
        logger.error("INTERNAL_TOKEN is too weak (short or low entropy)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service token is not configured",
        )

    provided = _extract_bearer(request)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(provided, expected):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning("Invalid token from %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid service token",
        )

    return "authenticated"
