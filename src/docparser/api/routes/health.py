"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint.

    Returns service status and version.
    """
    from docparser import __version__

    return {
        "status": "healthy",
        "version": __version__,
        "service": "docparser",
    }


@router.get("/ready")
async def readiness_check() -> dict:
    """
    Readiness check endpoint.

    Verifies that dependencies are available.
    """
    checks = {
        "api": True,
    }

    # Could add checks for:
    # - OpenAI API connectivity
    # - Google Cloud Vision availability
    # - Database connection (when added)

    all_ready = all(checks.values())

    return {
        "ready": all_ready,
        "checks": checks,
    }
