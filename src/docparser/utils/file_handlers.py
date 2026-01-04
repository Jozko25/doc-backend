"""File type detection and handling utilities."""

import io
import tempfile
from enum import Enum
from pathlib import Path
from typing import BinaryIO

import magic
from fastapi import UploadFile


class FileType(str, Enum):
    """Detected file types."""

    IMAGE_JPEG = "image_jpeg"
    IMAGE_PNG = "image_png"
    IMAGE_TIFF = "image_tiff"
    IMAGE_WEBP = "image_webp"
    IMAGE_OTHER = "image_other"
    PDF = "pdf"
    EXCEL_XLSX = "excel_xlsx"
    EXCEL_XLS = "excel_xls"
    CSV = "csv"
    XML = "xml"
    UNKNOWN = "unknown"


# MIME type to FileType mapping
MIME_TO_FILETYPE: dict[str, FileType] = {
    "image/jpeg": FileType.IMAGE_JPEG,
    "image/png": FileType.IMAGE_PNG,
    "image/tiff": FileType.IMAGE_TIFF,
    "image/webp": FileType.IMAGE_WEBP,
    "image/gif": FileType.IMAGE_OTHER,
    "image/bmp": FileType.IMAGE_OTHER,
    "application/pdf": FileType.PDF,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileType.EXCEL_XLSX,
    "application/vnd.ms-excel": FileType.EXCEL_XLS,
    "text/csv": FileType.CSV,
    "text/plain": FileType.CSV,  # Often CSV files are detected as text/plain
    "application/xml": FileType.XML,
    "text/xml": FileType.XML,
}

# File extensions as fallback
EXTENSION_TO_FILETYPE: dict[str, FileType] = {
    ".jpg": FileType.IMAGE_JPEG,
    ".jpeg": FileType.IMAGE_JPEG,
    ".png": FileType.IMAGE_PNG,
    ".tiff": FileType.IMAGE_TIFF,
    ".tif": FileType.IMAGE_TIFF,
    ".webp": FileType.IMAGE_WEBP,
    ".gif": FileType.IMAGE_OTHER,
    ".bmp": FileType.IMAGE_OTHER,
    ".pdf": FileType.PDF,
    ".xlsx": FileType.EXCEL_XLSX,
    ".xls": FileType.EXCEL_XLS,
    ".csv": FileType.CSV,
    ".xml": FileType.XML,
}


def detect_file_type(
    file_content: bytes | None = None,
    filename: str | None = None,
) -> FileType:
    """
    Detect file type from content and/or filename.

    Uses libmagic for content detection, falls back to extension.

    Args:
        file_content: File bytes for magic detection
        filename: Filename for extension-based fallback

    Returns:
        Detected FileType
    """
    detected_type: FileType | None = None

    # Try magic detection first if content provided
    if file_content:
        mime = magic.from_buffer(file_content, mime=True)
        detected_type = MIME_TO_FILETYPE.get(mime)

        # Special case: text/plain could be CSV or other
        if mime == "text/plain" and filename:
            ext = Path(filename).suffix.lower()
            if ext == ".csv":
                detected_type = FileType.CSV
            elif ext == ".xml":
                detected_type = FileType.XML

    # Fall back to extension if needed
    if detected_type is None and filename:
        ext = Path(filename).suffix.lower()
        detected_type = EXTENSION_TO_FILETYPE.get(ext)

    return detected_type or FileType.UNKNOWN


def is_image_type(file_type: FileType) -> bool:
    """Check if file type is an image."""
    return file_type in {
        FileType.IMAGE_JPEG,
        FileType.IMAGE_PNG,
        FileType.IMAGE_TIFF,
        FileType.IMAGE_WEBP,
        FileType.IMAGE_OTHER,
    }


def is_structured_type(file_type: FileType) -> bool:
    """Check if file type is structured (Excel, CSV, XML)."""
    return file_type in {
        FileType.EXCEL_XLSX,
        FileType.EXCEL_XLS,
        FileType.CSV,
        FileType.XML,
    }


class FileHandler:
    """Handle file operations for uploaded documents."""

    def __init__(self, max_size_bytes: int = 50 * 1024 * 1024):
        self.max_size_bytes = max_size_bytes

    async def read_upload(self, upload: UploadFile) -> tuple[bytes, FileType]:
        """
        Read uploaded file and detect its type.

        Args:
            upload: FastAPI UploadFile

        Returns:
            Tuple of (file_content, file_type)

        Raises:
            ValueError: If file exceeds max size
        """
        content = await upload.read()

        if len(content) > self.max_size_bytes:
            raise ValueError(
                f"File size {len(content)} bytes exceeds maximum "
                f"{self.max_size_bytes} bytes"
            )

        file_type = detect_file_type(content, upload.filename)
        return content, file_type

    def save_temp(self, content: bytes, suffix: str = "") -> Path:
        """
        Save content to a temporary file.

        Args:
            content: File bytes
            suffix: File extension (e.g., '.pdf')

        Returns:
            Path to temporary file
        """
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(content)
            return Path(f.name)

    def content_to_stream(self, content: bytes) -> BinaryIO:
        """Convert bytes to a file-like stream."""
        return io.BytesIO(content)
