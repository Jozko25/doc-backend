"""Error handling middleware."""

import logging
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def error_handler_middleware(
    request: Request,
    call_next: Callable,
) -> Response:
    """
    Global error handler middleware.

    Catches unhandled exceptions and returns proper JSON error responses.
    """
    try:
        return await call_next(request)
    except Exception as e:
        logger.exception(f"Unhandled error processing {request.method} {request.url.path}")

        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(e) if logger.level <= logging.DEBUG else "An unexpected error occurred",
            },
        )


def setup_error_handlers(app: FastAPI) -> None:
    """Setup exception handlers for the FastAPI app."""

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "Validation error", "detail": str(exc)},
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "Not found", "detail": str(exc)},
        )
