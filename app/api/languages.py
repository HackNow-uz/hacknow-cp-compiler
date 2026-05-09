"""Languages endpoint"""
from fastapi import APIRouter
from typing import List
from app.languages import get_all_languages
from app.schemas.responses import LanguageInfo

router = APIRouter()


@router.get("/languages", response_model=List[LanguageInfo])
async def list_languages():
    """
    Get list of supported programming languages.
    Returns language info with default time/memory limits.
    """
    languages = get_all_languages()
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
        for lang in languages
    ]
