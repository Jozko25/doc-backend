"""Base extractor interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BoundingBox:
    """Bounding box for a word/block in the document."""

    text: str
    # Normalized coordinates (0-1 relative to image dimensions)
    x: float  # left
    y: float  # top
    width: float
    height: float
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Result from document extraction."""

    # Raw text content (from OCR or PDF text extraction)
    text: str | None = None

    # Structured data (from Excel, CSV, XML, or PDF tables)
    structured_data: dict[str, Any] | None = None

    # Confidence score from OCR (0-1)
    confidence: float | None = None

    # Any warnings or issues during extraction
    warnings: list[str] = field(default_factory=list)

    # Source type for tracking
    source_type: str = "unknown"

    # Word-level bounding boxes for UI annotations
    bounding_boxes: list[BoundingBox] = field(default_factory=list)

    # Image dimensions (for coordinate mapping)
    image_width: int | None = None
    image_height: int | None = None

    @property
    def has_content(self) -> bool:
        """Check if extraction produced any content."""
        return bool(self.text) or bool(self.structured_data)


class BaseExtractor(ABC):
    """Abstract base class for document extractors."""

    @abstractmethod
    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """
        Extract content from document.

        Args:
            content: Raw file bytes
            filename: Original filename (optional, for hints)

        Returns:
            ExtractionResult with text and/or structured data
        """
        pass

    @abstractmethod
    def supports_file_type(self, file_type: str) -> bool:
        """
        Check if this extractor supports the given file type.

        Args:
            file_type: FileType enum value as string

        Returns:
            True if supported
        """
        pass
