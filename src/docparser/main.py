"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.middleware.error_handler import setup_error_handlers
from .api.routes import documents_router, exports_router, health_router
from .config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="DocParser API",
        description=(
            "Universal document parser API. Converts PDF, images, Excel, XML to "
            "canonical JSON with AI-powered extraction and validation."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Setup error handlers
    setup_error_handlers(app)

    # Include routers
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(exports_router, prefix="/api/v1/exports")

    @app.on_event("startup")
    async def startup_event():
        logger.info("DocParser API starting up...")
        logger.info(f"Debug mode: {settings.debug}")
        logger.info(f"LLM Model: {settings.llm_model}")

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("DocParser API shutting down...")

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "docparser.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

for route in app.routes:
    print(route.path, route.methods)
