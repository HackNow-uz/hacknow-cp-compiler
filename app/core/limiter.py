from fastapi import Request
from slowapi import Limiter

from app.config import settings


def _real_client_ip(request: Request) -> str:
    """Extract client IP, honoring X-Forwarded-For only from trusted proxies.

    SECURITY: blindly trusting X-Forwarded-For lets attackers bypass rate
    limiting via header spoofing. Only honor it when the direct connection
    comes from a configured trusted proxy.
    """
    direct = request.client.host if request.client else "unknown"
    if settings.trusted_proxies and direct in settings.trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
    return direct


limiter = Limiter(key_func=_real_client_ip)
