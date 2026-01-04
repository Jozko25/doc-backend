"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from .routes import documents_router, exports_router, health_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

settings = get_settings()

app = FastAPI(
    title="Document Parser API",
    description="Universal document parsing API for invoices, receipts, and financial documents",
    version="1.0.0",
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

# Include routers
app.include_router(health_router, prefix="/api/v1", tags=["health"])
app.include_router(documents_router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(exports_router, prefix="/api/v1/exports", tags=["exports"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Document Parser API",
        "version": "1.0.0",
        "docs": "/docs",
    }
