"""Document processing endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ...config import get_settings
from ...core.models import ProcessingResult, ValidationStatus
from ...core.pipeline import DocumentPipeline
from ...utils.file_handlers import FileHandler

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

# In-memory storage for processed documents (replace with DB later)
_document_store: dict[UUID, ProcessingResult] = {}


class ParseOptions(BaseModel):
    """Options for document parsing."""

    output_format: str = "canonical"  # canonical, csv, excel, ubl21, en16931
    language_hint: str | None = None
    document_type_hint: str | None = None


class ParseResponse(BaseModel):
    """Response for document parsing."""

    status: ValidationStatus
    document_id: UUID
    confidence: str
    processing_time_ms: int | None
    review_required: bool
    message: str | None
    # Note: Full data is available via /documents/{id} endpoint


@router.post("/parse", response_model=ParseResponse)
async def parse_document(
    file: Annotated[UploadFile, File(description="Document file to parse")],
    output_format: Annotated[str, Form()] = "canonical",
    language_hint: Annotated[str | None, Form()] = None,
) -> ParseResponse:
    """
    Upload and parse a document.

    Accepts PDF, images (JPG, PNG, TIFF), Excel, CSV, and XML files.
    Returns parsing status and document ID for retrieving results.
    """
    settings = get_settings()
    file_handler = FileHandler(settings.max_file_size_bytes)

    # Read and validate file
    try:
        content, file_type = await file_handler.read_upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    logger.info(f"Processing document: {file.filename} ({file_type.value})")

    # Process document
    pipeline = DocumentPipeline()
    result = await pipeline.process(
        content=content,
        filename=file.filename,
        file_type=file_type,
    )

    # Store result for later retrieval
    _document_store[result.document_id] = result

    return ParseResponse(
        status=result.status,
        document_id=result.document_id,
        confidence=result.confidence,
        processing_time_ms=result.processing_time_ms,
        review_required=result.review_required,
        message=result.message,
    )


@router.get("/{document_id}")
async def get_document(document_id: UUID) -> ProcessingResult:
    """
    Get processed document by ID.

    Returns the full canonical document with all extracted data.
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    return _document_store[document_id]


@router.get("/{document_id}/canonical")
async def get_canonical(document_id: UUID) -> dict:
    """
    Get canonical JSON for a processed document.

    Returns only the canonical document data (without processing metadata).
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    result = _document_store[document_id]
    return result.data.model_dump(mode="json", by_alias=True)


class ConfirmRequest(BaseModel):
    """Request to confirm/correct uncertain values."""

    corrections: dict[str, str | float | int]  # field path -> corrected value


@router.post("/{document_id}/confirm")
async def confirm_document(document_id: UUID, request: ConfirmRequest) -> dict:
    """
    Confirm or correct uncertain values in a document.

    Used by human-in-the-loop UI to finalize document before export.
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    result = _document_store[document_id]

    # Apply corrections (simplified - would need proper nested field handling)
    # For now, just mark as confirmed
    result.data.metadata.validation_status = ValidationStatus.VALID
    result.data.metadata.validation_issues = []
    result.data.metadata.ai_suggestions = []

    result.status = ValidationStatus.VALID
    result.review_required = False
    result.suggestions = []
    result.message = "Document confirmed by user"

    return {
        "status": "confirmed",
        "document_id": str(document_id),
        "message": "Document has been confirmed and is ready for export",
    }


@router.delete("/{document_id}")
async def delete_document(document_id: UUID) -> dict:
    """Delete a processed document from storage."""
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    del _document_store[document_id]

    return {"status": "deleted", "document_id": str(document_id)}
