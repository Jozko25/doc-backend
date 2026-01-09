"""Document processing endpoints."""

import logging
from pathlib import Path
import shutil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...config import get_settings
from ...core.models import ProcessingResult, ValidationStatus
from ...core.pipeline import DocumentPipeline
from ...utils.file_handlers import FileHandler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

# In-memory storage for processed documents (replace with DB later)
_document_store: dict[UUID, ProcessingResult] = {}


class ParseOptions(BaseModel):
    """Options for document parsing."""

    output_format: str = "canonical"  # canonical, csv, excel, ubl21, en16931
    language_hint: str | None = None
    document_type_hint: str | None = None


class BoundingBoxResponse(BaseModel):
    """Bounding box for UI annotations."""

    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float
    field_path: str | None = None  # JSON path to linked document field


class ParseResponse(BaseModel):
    """Response for document parsing."""

    status: ValidationStatus
    document_id: UUID
    confidence: str
    processing_time_ms: int | None
    review_required: bool
    message: str | None
    document: dict  # Full canonical document
    bounding_boxes: list[BoundingBoxResponse]
    image_width: int | None
    image_height: int | None


@router.post("/parse", response_model=ParseResponse)
async def parse_document(
    file: Annotated[UploadFile, File(description="Document file to parse")],
    output_format: Annotated[str, Form()] = "canonical",
    language_hint: Annotated[str | None, Form()] = None,
) -> ParseResponse:
    """
    Upload and parse a document.

    Accepts PDF, images (JPG, PNG, TIFF), Excel, CSV, and XML files.
    Returns full parsing result with document data and bounding boxes.
    """
    settings = get_settings()
    file_handler = FileHandler(settings.max_file_size_bytes)
    
    # Ensure upload directory exists
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

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
    
    # Save the original file for UI display
    try:
        # Determine extension from filename or file_type
        suffix = Path(file.filename).suffix if file.filename else ""
        if not suffix and file_handler.is_image_type(file_type):
            suffix = ".jpg" # Default fallback
            
        file_path = settings.upload_dir / f"{result.document_id}{suffix}"
        
        # Save content to file (if HEIC, this will be the source for conversion)
        with open(file_path, "wb") as f:
            f.write(content)
            
        # Handle HEIC conversion for browser compatibility
        if suffix.lower() in (".heic", ".heif"):
            import subprocess
            jpg_path = file_path.with_suffix(".jpg")
            try:
                # Use sips (macOS) or other tools if available
                # Fallback to just keeping it if conversion fails (user might have Safari)
                subprocess.run(
                    ["sips", "-s", "format", "jpeg", str(file_path), "--out", str(jpg_path)],
                    check=True,
                    capture_output=True
                )
                # If successful, remove original HEIC to avoid ambiguity
                file_path.unlink()
                logger.info(f"Converted HEIC to JPEG: {jpg_path}")
            except Exception as e:
                logger.warning(f"HEIC conversion failed (sips might be missing): {e}")
                
        logger.info(f"Saved uploaded file to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        # Continue anyway, just image won't be available


    # Convert bounding boxes
    bounding_boxes = [
        BoundingBoxResponse(
            text=box.text,
            x=box.x,
            y=box.y,
            width=box.width,
            height=box.height,
            confidence=box.confidence,
        )
        for box in result.bounding_boxes
    ]

    return ParseResponse(
        status=result.status,
        document_id=result.document_id,
        confidence=result.confidence,
        processing_time_ms=result.processing_time_ms,
        review_required=result.review_required,
        message=result.message,
        document=result.data.model_dump(mode="json", by_alias=True),
        bounding_boxes=bounding_boxes,
        image_width=result.image_width,
        image_height=result.image_height,
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


@router.get("/{document_id}/image")
async def get_document_image(document_id: UUID, page: int = 1):
    """
    Get the document as an image.

    For PDFs, renders the specified page as a PNG image.
    For images, returns the original file.

    Args:
        document_id: Document UUID
        page: Page number for PDFs (1-indexed, default 1)
    """
    settings = get_settings()

    # Find file with any extension for this ID
    files = list(settings.upload_dir.glob(f"{document_id}.*"))

    if not files:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = files[0]

    # If it's a PDF, render the page as an image
    if file_path.suffix.lower() == ".pdf":
        import io
        import fitz  # PyMuPDF
        from fastapi.responses import StreamingResponse

        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)

            if page < 1 or page > total_pages:
                doc.close()
                raise HTTPException(status_code=400, detail=f"Invalid page number. PDF has {total_pages} pages.")

            # Render page at 2x resolution for better quality
            pdf_page = doc[page - 1]
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
            pix = pdf_page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            img_bytes = pix.tobytes("png")
            doc.close()

            return StreamingResponse(
                io.BytesIO(img_bytes),
                media_type="image/png",
                headers={"X-PDF-Page": str(page), "X-PDF-Total-Pages": str(total_pages)}
            )
        except Exception as e:
            logger.error(f"Failed to render PDF page: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to render PDF: {str(e)}")

    # If it's a HEIC/HEIF image, convert to PNG for browser compatibility
    if file_path.suffix.lower() in {".heic", ".heif"}:
        import io
        import pillow_heif
        from fastapi.responses import StreamingResponse

        try:
            heif_file = pillow_heif.read_heif(file_path)
            image = heif_file.to_pillow()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="image/png",
                headers={"X-Converted-From": file_path.suffix.lower()},
            )
        except Exception as e:
            logger.error(f"Failed to convert HEIC/HEIF to PNG: {e}")
            raise HTTPException(status_code=500, detail="Failed to render image")

    return FileResponse(files[0])


@router.get("/{document_id}/pdf-info")
async def get_pdf_info(document_id: UUID):
    """
    Get PDF metadata (page count, dimensions).

    Returns info needed for pagination in the UI.
    """
    settings = get_settings()

    files = list(settings.upload_dir.glob(f"{document_id}.*"))

    if not files:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = files[0]

    if file_path.suffix.lower() != ".pdf":
        return {"is_pdf": False, "page_count": 1}

    import fitz

    try:
        doc = fitz.open(file_path)
        page_count = len(doc)

        # Get first page dimensions
        first_page = doc[0]
        rect = first_page.rect

        doc.close()

        return {
            "is_pdf": True,
            "page_count": page_count,
            "width": rect.width,
            "height": rect.height,
        }
    except Exception as e:
        logger.error(f"Failed to get PDF info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.put("/{document_id}")
async def update_document(document_id: UUID, document: Annotated[dict, "CanonicalDocument JSON data"]) -> ProcessingResult:
    """
    Update a processed document.

    Overwrites the stored document data with the provided JSON.
    Used for saving user edits before export.
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    from ...core.models import CanonicalDocument

    try:
        # Validate data against model
        new_doc = CanonicalDocument(**document)

        # Update store
        result = _document_store[document_id]
        result.data = new_doc

        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(document_id: UUID) -> dict:
    """Delete a processed document from storage."""
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    del _document_store[document_id]

    return {"status": "deleted", "document_id": str(document_id)}


class UpdateAnnotationsRequest(BaseModel):
    """Request to update bounding box annotations."""

    bounding_boxes: list[BoundingBoxResponse]


@router.put("/{document_id}/annotations")
async def update_annotations(
    document_id: UUID, request: UpdateAnnotationsRequest
) -> ProcessingResult:
    """
    Update document annotations.

    Allows correcting OCR text or adjusting bounding boxes.
    Also syncs changes to the canonical document when field_path is set.
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    result = _document_store[document_id]

    from ...core.models import BoundingBoxModel

    new_boxes = []
    for box in request.bounding_boxes:
        new_boxes.append(BoundingBoxModel(
            text=box.text,
            x=box.x,
            y=box.y,
            width=box.width,
            height=box.height,
            confidence=box.confidence,
            field_path=box.field_path
        ))

        # Sync annotation change to document field if field_path is set
        if box.field_path:
            _update_document_field(result.data, box.field_path, box.text)

    result.bounding_boxes = new_boxes

    return result


def _update_document_field(doc, field_path: str, value: str) -> None:
    """
    Update a document field based on JSON path.

    Supports paths like:
    - "totals.total_amount"
    - "totals.subtotal"
    - "line_items[0].line_total"
    - "document.number"
    - "document.issue_date"
    - "supplier.bank.iban"
    """
    import re
    from datetime import date
    from decimal import Decimal, InvalidOperation

    parts = re.split(r'\.|\[|\]', field_path)
    parts = [p for p in parts if p]  # Remove empty strings

    obj = doc
    for i, part in enumerate(parts[:-1]):
        if part.isdigit():
            obj = obj[int(part)]
        else:
            obj = getattr(obj, part, None)
            if obj is None:
                logger.warning(f"Could not traverse path {field_path} at {part}")
                return

    final_key = parts[-1]
    if final_key.isdigit():
        # List index - unlikely for final key but handle it
        return

    # Get current value to determine type
    current_value = getattr(obj, final_key, None)

    # Convert value to appropriate type
    try:
        if isinstance(current_value, Decimal):
            # Clean the value: remove currency symbols, spaces, handle comma as decimal
            cleaned = re.sub(r'[^\d.,\-]', '', value)
            # Handle European format (comma as decimal separator)
            if ',' in cleaned and '.' not in cleaned:
                cleaned = cleaned.replace(',', '.')
            elif ',' in cleaned and '.' in cleaned:
                # Assume comma is thousands separator
                cleaned = cleaned.replace(',', '')
            new_value = Decimal(cleaned)
        elif isinstance(current_value, date):
            # Parse date from various formats
            cleaned = value.replace('.', '-').replace('/', '-')
            # Try to parse YYYY-MM-DD format
            parts_date = cleaned.split('-')
            if len(parts_date) == 3:
                # Check if year is first or last
                if len(parts_date[0]) == 4:
                    new_value = date(int(parts_date[0]), int(parts_date[1]), int(parts_date[2]))
                else:
                    new_value = date(int(parts_date[2]), int(parts_date[1]), int(parts_date[0]))
            else:
                new_value = value  # Keep as string if can't parse
        elif isinstance(current_value, int):
            new_value = int(value)
        elif isinstance(current_value, float):
            new_value = float(value)
        else:
            new_value = value

        setattr(obj, final_key, new_value)
        logger.info(f"Updated {field_path} to {new_value}")
    except (InvalidOperation, ValueError) as e:
        logger.warning(f"Could not convert '{value}' for {field_path}: {e}")
