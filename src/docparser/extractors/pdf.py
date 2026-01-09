"""PDF text extractor using PyMuPDF."""

import io

import fitz  # PyMuPDF

from ..utils.file_handlers import FileType
from .base import BaseExtractor, BoundingBox, ExtractionResult


class PDFExtractor(BaseExtractor):
    """Extract text from native (non-scanned) PDF documents."""

    SUPPORTED_TYPES = {FileType.PDF}

    # Minimum text length to consider a PDF as native (not scanned)
    MIN_TEXT_LENGTH = 50

    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """
        Extract text from PDF with bounding boxes.

        For PDFs with embedded text (native PDFs), extracts the text directly.
        For scanned PDFs with little/no text, returns empty result (should use OCR).

        Args:
            content: PDF file bytes
            filename: Original filename (unused)

        Returns:
            ExtractionResult with extracted text and bounding boxes
        """
        warnings = []
        all_text = []
        bounding_boxes = []
        page_width = None
        page_height = None

        try:
            # Open PDF from bytes
            pdf_stream = io.BytesIO(content)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")

            for page_num, page in enumerate(doc):
                # Get page dimensions (use first page for reference)
                if page_width is None:
                    rect = page.rect
                    page_width = rect.width
                    page_height = rect.height

                # Extract text with layout preservation
                # Using "text" with sort=True to maintain reading order
                # Also try blocks to get structured text
                text_blocks = page.get_text("blocks", sort=True)

                # Reconstruct text preserving table structure
                lines = []
                for block in text_blocks:
                    if block[6] == 0:  # Text block (not image)
                        block_text = block[4].strip()
                        if block_text:
                            lines.append(block_text)

                text = "\n".join(lines)
                if text.strip():
                    all_text.append(f"--- Page {page_num + 1} ---\n{text}")

                # Extract words with positions (only for first page for now)
                if page_num == 0:
                    words = page.get_text("words")  # Returns list of (x0, y0, x1, y1, word, block_no, line_no, word_no)
                    for word_data in words:
                        x0, y0, x1, y1, word_text = word_data[:5]
                        if word_text.strip():
                            # Normalize coordinates to 0-1 range
                            bbox = BoundingBox(
                                text=word_text,
                                x=x0 / page_width,
                                y=y0 / page_height,
                                width=(x1 - x0) / page_width,
                                height=(y1 - y0) / page_height,
                                confidence=1.0,  # Native PDF text is 100% accurate
                            )
                            bounding_boxes.append(bbox)

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
            bounding_boxes = []  # No bounding boxes for scanned PDFs
            warnings.append(
                "PDF appears to be scanned or image-based. "
                "OCR extraction recommended for better results."
            )

        return ExtractionResult(
            text=full_text,
            confidence=1.0 if not is_scanned else 0.0,
            warnings=warnings,
            source_type="pdf_native" if not is_scanned else "pdf_scanned",
            bounding_boxes=bounding_boxes,
            image_width=int(page_width * 2) if page_width else None,  # 2x for rendered image resolution
            image_height=int(page_height * 2) if page_height else None,
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
        Extract text, bounding boxes, and images from PDF.

        For scanned PDFs, the images can be sent to OCR.

        Args:
            content: PDF file bytes

        Returns:
            Tuple of (ExtractionResult, list of image bytes)
        """
        warnings = []
        all_text = []
        images = []
        bounding_boxes = []
        page_width = None
        page_height = None

        try:
            pdf_stream = io.BytesIO(content)
            doc = fitz.open(stream=pdf_stream, filetype="pdf")

            for page_num, page in enumerate(doc):
                # Get page dimensions (use first page for reference)
                if page_width is None:
                    rect = page.rect
                    page_width = rect.width
                    page_height = rect.height

                # Extract text with layout preservation using blocks
                text_blocks = page.get_text("blocks", sort=True)

                # Reconstruct text preserving table structure
                lines = []
                for block in text_blocks:
                    if block[6] == 0:  # Text block (not image)
                        block_text = block[4].strip()
                        if block_text:
                            lines.append(block_text)

                text = "\n".join(lines)
                if text.strip():
                    all_text.append(f"--- Page {page_num + 1} ---\n{text}")

                # Extract words with positions (only for first page for now)
                if page_num == 0:
                    words = page.get_text("words")
                    for word_data in words:
                        x0, y0, x1, y1, word_text = word_data[:5]
                        if word_text.strip():
                            bbox = BoundingBox(
                                text=word_text,
                                x=x0 / page_width,
                                y=y0 / page_height,
                                width=(x1 - x0) / page_width,
                                height=(y1 - y0) / page_height,
                                confidence=1.0,
                            )
                            bounding_boxes.append(bbox)

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
            bounding_boxes = []  # Clear bounding boxes for scanned PDFs

        return ExtractionResult(
            text=full_text,
            confidence=1.0 if not is_scanned else 0.1,
            warnings=warnings,
            source_type="pdf_native" if not is_scanned else "pdf_scanned",
            bounding_boxes=bounding_boxes,
            image_width=int(page_width * 2) if page_width else None,  # 2x for rendered image
            image_height=int(page_height * 2) if page_height else None,
        ), images
