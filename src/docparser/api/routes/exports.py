"""Export endpoints for different formats."""

import io
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...core.models import CanonicalDocument

exports_router = APIRouter(prefix="/documents", tags=["exports"])

# Reference to document store (same as in documents.py)
from .documents import _document_store


# Debug endpoint to list all documents in memory
@exports_router.get("/debug/list")
async def list_documents():
    return {"documents": list(_document_store.keys())}

@exports_router.get("/{document_id}/export/{format}")
async def export_document(document_id: UUID, format: str) -> StreamingResponse:
    """
    Export document to specified format.

    Supported formats:
    - csv: Comma-separated values (line items)
    - xlsx: Excel spreadsheet
    - ubl21: UBL 2.1 Invoice XML
    - en16931: EN 16931 / CII XML
    """
    if document_id not in _document_store:
        raise HTTPException(status_code=404, detail="Document not found")

    result = _document_store[document_id]
    doc = result.data

    format_lower = format.lower()

    if format_lower == "csv":
        from ...exporters import CSVExporter
        exporter = CSVExporter()
        content = exporter.export(doc)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}.csv"'
            },
        )

    elif format_lower in ("xlsx", "excel"):
        from ...exporters import ExcelExporter
        exporter = ExcelExporter()
        content = exporter.export(doc)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}.xlsx"'
            },
        )

    elif format_lower == "ubl21":
        from ...exporters import UBLInvoiceExporter
        exporter = UBLInvoiceExporter()
        content = exporter.export(doc)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}_ubl.xml"'
            },
        )

    elif format_lower == "en16931":
        from ...exporters import EN16931Exporter
        exporter = EN16931Exporter()
        content = exporter.export(doc)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}_en16931.xml"'
            },
        )

    elif format_lower == "json":
        # Return canonical JSON
        import json
        content = doc.model_dump_json(indent=2, by_alias=True)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}.json"'
            },
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {format}. Supported: csv, xlsx, json, ubl21, en16931"
        )


