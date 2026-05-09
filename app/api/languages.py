from fastapi import APIRouter, Depends

from app.api.auth import verify_token
from app.languages import get_all_languages
from app.schemas.responses import LanguageInfo

router = APIRouter()


@router.get("/languages", response_model=list[LanguageInfo])
async def list_languages(_: str = Depends(verify_token)):
    """List supported languages with default limits. Requires bearer token."""
    return [
        LanguageInfo(
            id=lang.id,
            name=lang.name,
            version=lang.version,
            time_limit_ms=lang.time_limit_ms,
            memory_limit_mb=lang.memory_limit_mb,
            time_multiplier=lang.time_multiplier,
            memory_multiplier=lang.memory_multiplier,
        )
        for lang in get_all_languages()
    ]
