"""Health check API endpoints."""

from fastapi import APIRouter, status
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Health Check",
    description="Returns service status, environment details, and storage health."
)
async def get_health() -> HealthResponse:
    """Perform a health check of the application and critical local dependencies."""
    storage_accessible = False
    try:
        settings.STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        # Test write and removal of a sentinel file
        test_file = settings.STORAGE_PATH / ".healthcheck"
        test_file.touch()
        test_file.unlink()
        storage_accessible = True
    except Exception as e:
        logger.error(f"Storage health check error: {str(e)}")
        storage_accessible = False

    logger.debug(f"Health check executed. Storage accessible: {storage_accessible}")

    return HealthResponse(
        status="healthy" if storage_accessible else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG,
        storage_accessible=storage_accessible,
        details={
            "default_llm": settings.DEFAULT_LLM_PROVIDER,
            "llm_provider": settings.DEFAULT_LLM_PROVIDER,
            "llm_model": settings.GROQ_MODEL if settings.DEFAULT_LLM_PROVIDER == "groq" else settings.DEFAULT_LLM_PROVIDER,
            "default_tts": settings.DEFAULT_TTS_PROVIDER,
            "default_avatar": settings.DEFAULT_AVATAR_PROVIDER,
            "enable_live_heygen": getattr(settings, "ENABLE_LIVE_HEYGEN", False),
            "storage_path": str(settings.STORAGE_PATH),
        }
    )
