"""PDF text extractor using PyMuPDF."""

import io

import fitz  # PyMuPDF

from ..utils.file_handlers import FileType
from .base import BaseExtractor, ExtractionResult


class PDFExtractor(BaseExtractor):
    """Extract text from native (non-scanned) PDF documents."""

    SUPPORTED_TYPES = {FileType.PDF}

    # Minimum text length to consider a PDF as native (not scanned)
    MIN_TEXT_LENGTH = 50

    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """
        Extract text from PDF.

        For PDFs with embedded text (native PDFs), extracts the text directly.
        For scanned PDFs with little/no text, returns empty result (should use OCR).

        Args:
            content: PDF file bytes
            filename: Original filename (unused)

        Returns:
            ExtractionResult with extracted text
        """
        warnings = []
        all_text = []

        try:
            # Open PDF from bytes
            pdf_stream = io.BytesIO(content)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")

            for page_num, page in enumerate(doc):
                # Extract text from page
                text = page.get_text("text")
                if text.strip():
                    all_text.append(f"--- Page {page_num + 1} ---\n{text}")

            doc.close()

        except Exception as e:
            return ExtractionResult(
                text=None,
                warnings=[f"PDF extraction error: {str(e)}"],
                source_type="pdf_error",
            )

        full_text = "\n\n".join(all_text) if all_text else None

        # Check if this appears to be a scanned PDF
        is_scanned = False
        if full_text is None or len(full_text.strip()) < self.MIN_TEXT_LENGTH:
            is_scanned = True
            warnings.append(
                "PDF appears to be scanned or image-based. "
                "OCR extraction recommended for better results."
            )

        return ExtractionResult(
            text=full_text,
            confidence=1.0 if not is_scanned else 0.0,  # Native PDFs have perfect accuracy
            warnings=warnings,
            source_type="pdf_native" if not is_scanned else "pdf_scanned",
        )

    def supports_file_type(self, file_type: str) -> bool:
        """Check if this extractor supports the given file type."""
        try:
            ft = FileType(file_type)
            return ft in self.SUPPORTED_TYPES
        except ValueError:
            return False

    async def is_scanned_pdf(self, content: bytes) -> bool:
        """
        Check if a PDF is scanned (image-based) vs native (text-based).

        Args:
            content: PDF file bytes

        Returns:
            True if PDF appears to be scanned
        """
        result = await self.extract(content)
        return result.source_type == "pdf_scanned"

    async def extract_with_images(self, content: bytes) -> tuple[ExtractionResult, list[bytes]]:
        """
        Extract text and images from PDF.

        For scanned PDFs, the images can be sent to OCR.

        Args:
            content: PDF file bytes

        Returns:
            Tuple of (ExtractionResult, list of image bytes)
        """
        warnings = []
        all_text = []
        images = []

        try:
            pdf_stream = io.BytesIO(content)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")

            for page_num, page in enumerate(doc):
                # Extract text
                text = page.get_text("text")
                if text.strip():
                    all_text.append(f"--- Page {page_num + 1} ---\n{text}")

                # Extract images from page
                image_list = page.get_images(full=True)
                for img_index, img_info in enumerate(image_list):
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    if base_image:
                        images.append(base_image["image"])

            doc.close()

        except Exception as e:
            return ExtractionResult(
                text=None,
                warnings=[f"PDF extraction error: {str(e)}"],
                source_type="pdf_error",
            ), []

        full_text = "\n\n".join(all_text) if all_text else None

        # If we got images but little text, it's likely scanned
        is_scanned = len(full_text or "") < self.MIN_TEXT_LENGTH and len(images) > 0
        if is_scanned:
            warnings.append("PDF appears to be scanned. Extracted page images for OCR.")

        return ExtractionResult(
            text=full_text,
            confidence=1.0 if not is_scanned else 0.1,
            warnings=warnings,
            source_type="pdf_native" if not is_scanned else "pdf_scanned",
        ), images
