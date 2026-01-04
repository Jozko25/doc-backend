"""Google Cloud Vision OCR extractor."""

import io
from pathlib import Path

from google.cloud import vision

from ..config import get_settings
from ..utils.file_handlers import FileType
from .base import BaseExtractor, ExtractionResult


class OCRExtractor(BaseExtractor):
    """Extract text from images using Google Cloud Vision OCR."""

    SUPPORTED_TYPES = {
        FileType.IMAGE_JPEG,
        FileType.IMAGE_PNG,
        FileType.IMAGE_TIFF,
        FileType.IMAGE_WEBP,
        FileType.IMAGE_OTHER,
    }

    def __init__(self, credentials_path: Path | None = None):
        """
        Initialize OCR extractor.

        Args:
            credentials_path: Path to Google Cloud service account JSON.
                            If None, uses GOOGLE_APPLICATION_CREDENTIALS env var.
        """
        self.credentials_path = credentials_path or get_settings().google_cloud_credentials
        self._client: vision.ImageAnnotatorClient | None = None

    @property
    def client(self) -> vision.ImageAnnotatorClient:
        """Lazy-load Vision client."""
        if self._client is None:
            if self.credentials_path:
                self._client = vision.ImageAnnotatorClient.from_service_account_file(
                    str(self.credentials_path)
                )
            else:
                # Uses GOOGLE_APPLICATION_CREDENTIALS or default credentials
                self._client = vision.ImageAnnotatorClient()
        return self._client

    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """
        Extract text from image using Google Cloud Vision.

        Args:
            content: Image file bytes
            filename: Original filename (unused for OCR)

        Returns:
            ExtractionResult with extracted text and confidence
        """
        settings = get_settings()

        # Create vision image from bytes
        image = vision.Image(content=content)

        # Configure language hints
        image_context = vision.ImageContext(
            language_hints=settings.ocr_language_hints_list
        )

        # Perform document text detection (better for invoices than plain text_detection)
        response = self.client.document_text_detection(
            image=image,
            image_context=image_context,
        )

        # Check for errors
        if response.error.message:
            return ExtractionResult(
                text=None,
                confidence=0.0,
                warnings=[f"OCR error: {response.error.message}"],
                source_type="ocr_error",
            )

        # Extract full text
        full_text = ""
        confidence_sum = 0.0
        confidence_count = 0

        if response.full_text_annotation:
            full_text = response.full_text_annotation.text

            # Calculate average confidence from pages
            for page in response.full_text_annotation.pages:
                for block in page.blocks:
                    confidence_sum += block.confidence
                    confidence_count += 1

        avg_confidence = confidence_sum / confidence_count if confidence_count > 0 else 0.0

        warnings = []
        if avg_confidence < 0.7:
            warnings.append(
                f"Low OCR confidence ({avg_confidence:.2f}). Document may be hard to read."
            )

        return ExtractionResult(
            text=full_text if full_text else None,
            confidence=avg_confidence,
            warnings=warnings,
            source_type="google_cloud_vision",
        )

    def supports_file_type(self, file_type: str) -> bool:
        """Check if this extractor supports the given file type."""
        try:
            ft = FileType(file_type)
            return ft in self.SUPPORTED_TYPES
        except ValueError:
            return False


class MockOCRExtractor(BaseExtractor):
    """Mock OCR extractor for testing without Google Cloud."""

    SUPPORTED_TYPES = OCRExtractor.SUPPORTED_TYPES

    def __init__(self, mock_text: str = "", mock_confidence: float = 0.95):
        self.mock_text = mock_text
        self.mock_confidence = mock_confidence

    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """Return mock extraction result."""
        return ExtractionResult(
            text=self.mock_text or f"[Mock OCR text for {filename or 'unknown file'}]",
            confidence=self.mock_confidence,
            warnings=[],
            source_type="mock_ocr",
        )

    def supports_file_type(self, file_type: str) -> bool:
        try:
            ft = FileType(file_type)
            return ft in self.SUPPORTED_TYPES
        except ValueError:
            return False
