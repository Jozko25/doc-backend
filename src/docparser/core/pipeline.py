"""Main document processing pipeline."""

import logging
import time
from typing import Any

from ..config import get_settings
from ..extractors import ExcelExtractor, ExtractionResult, OCRExtractor, PDFExtractor, XMLExtractor
from ..normalizers import LLMExtractor
from ..utils.file_handlers import FileHandler, FileType, is_image_type, is_structured_type
from ..validators import MathValidator, TaxValidator, ValidationResult
from .models import (
    AISuggestion,
    CanonicalDocument,
    ProcessingResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


class DocumentPipeline:
    """
    Main document processing pipeline.

    Orchestrates: Detection -> Extraction -> Normalization -> Validation -> Result
    """

    def __init__(
        self,
        ocr_extractor: OCRExtractor | None = None,
        pdf_extractor: PDFExtractor | None = None,
        excel_extractor: ExcelExtractor | None = None,
        xml_extractor: XMLExtractor | None = None,
        llm_extractor: LLMExtractor | None = None,
        math_validator: MathValidator | None = None,
        tax_validator: TaxValidator | None = None,
    ):
        """
        Initialize pipeline with extractors and validators.

        If not provided, creates default instances.
        """
        settings = get_settings()

        self.ocr_extractor = ocr_extractor or OCRExtractor()
        self.pdf_extractor = pdf_extractor or PDFExtractor()
        self.excel_extractor = excel_extractor or ExcelExtractor()
        self.xml_extractor = xml_extractor or XMLExtractor()
        self.math_validator = math_validator or MathValidator()
        self.tax_validator = tax_validator or TaxValidator()

        # Always use OpenAI LLM extractor (Gemini and regex fallbacks removed)
        self.llm_extractor = llm_extractor or LLMExtractor()
        logger.info("Using OpenAI for extraction")

        self.max_retries = settings.max_validation_retries
        self.file_handler = FileHandler(settings.max_file_size_bytes)

    async def process(
        self,
        content: bytes,
        filename: str,
        file_type: FileType | None = None,
    ) -> ProcessingResult:
        """
        Process a document through the full pipeline.

        Args:
            content: Raw file bytes
            filename: Original filename
            file_type: Detected file type (if known)

        Returns:
            ProcessingResult with canonical document and status
        """
        start_time = time.time()

        # Step 1: Detect file type if not provided
        if file_type is None:
            from ..utils.file_handlers import detect_file_type
            file_type = detect_file_type(content, filename)

        logger.info(f"Processing {filename} as {file_type.value}")

        # Step 2: Extract content
        extraction_result = await self._extract(content, filename, file_type)

        if not extraction_result.has_content:
            return self._create_error_result(
                filename=filename,
                error="Failed to extract content from document",
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Step 3: Normalize to canonical JSON using LLM
        canonical_doc = await self.llm_extractor.extract_to_canonical(
            extraction_result=extraction_result,
            source_filename=filename,
        )

        # Extra guard: reconcile totals with printed OCR totals (helps when the extractor
        # returns mathematically consistent but OCR-misread quantities).
        self._align_totals_with_ocr(extraction_result.text or "", canonical_doc)

        # Step 4: Validate
        validation_result = self._validate(canonical_doc)

        # Step 5: Retry if validation failed
        retry_count = 0
        while not validation_result.is_valid and retry_count < self.max_retries:
            logger.info(f"Validation failed, retry {retry_count + 1}/{self.max_retries}")

            canonical_doc = await self.llm_extractor.revalidate(
                canonical_doc=canonical_doc,
                extraction_result=extraction_result,
                errors=validation_result.errors,
            )

            validation_result = self._validate(canonical_doc)
            retry_count += 1

        # Step 6: Build final result
        processing_time_ms = int((time.time() - start_time) * 1000)

        if validation_result.is_valid:
            canonical_doc.metadata.validation_status = ValidationStatus.VALID
            return ProcessingResult(
                status=ValidationStatus.VALID,
                document_id=canonical_doc.metadata.document_id,
                confidence="high",
                data=canonical_doc,
                processing_time_ms=processing_time_ms,
                review_required=False,
                suggestions=[],
                message="Document processed and validated successfully.",
            )
        else:
            # Build suggestions from validation errors
            suggestions = self._build_suggestions(validation_result, canonical_doc)

            canonical_doc.metadata.validation_status = ValidationStatus.UNCERTAIN
            canonical_doc.metadata.validation_issues = validation_result.errors
            canonical_doc.metadata.ai_suggestions = suggestions

            return ProcessingResult(
                status=ValidationStatus.UNCERTAIN,
                document_id=canonical_doc.metadata.document_id,
                confidence="low",
                data=canonical_doc,
                processing_time_ms=processing_time_ms,
                review_required=True,
                suggestions=suggestions,
                message=(
                    "Document processed but some values could not be verified. "
                    "Please review the highlighted fields before export."
                ),
            )

    async def _extract(
        self,
        content: bytes,
        filename: str,
        file_type: FileType,
    ) -> ExtractionResult:
        """Extract content based on file type."""
        # Images -> OCR
        if is_image_type(file_type):
            return await self.ocr_extractor.extract(content, filename)

        # PDFs need special handling
        if file_type == FileType.PDF:
            pdf_result, images = await self.pdf_extractor.extract_with_images(content)

            # If it's a scanned PDF, use OCR on the images
            if pdf_result.source_type == "pdf_scanned" and images:
                logger.info("Scanned PDF detected, running OCR on extracted images")
                ocr_texts = []
                total_confidence = 0.0

                for idx, img_bytes in enumerate(images):
                    ocr_result = await self.ocr_extractor.extract(img_bytes, f"page_{idx}.png")
                    if ocr_result.text:
                        ocr_texts.append(f"--- Page {idx + 1} ---\n{ocr_result.text}")
                        total_confidence += ocr_result.confidence or 0

                avg_confidence = total_confidence / len(images) if images else 0

                return ExtractionResult(
                    text="\n\n".join(ocr_texts) if ocr_texts else None,
                    confidence=avg_confidence,
                    warnings=["PDF was scanned, OCR applied to page images"],
                    source_type="pdf_scanned_ocr",
                )

            return pdf_result

        # Excel/CSV
        if file_type in {FileType.EXCEL_XLSX, FileType.EXCEL_XLS, FileType.CSV}:
            return await self.excel_extractor.extract(content, filename)

        # XML
        if file_type == FileType.XML:
            return await self.xml_extractor.extract(content, filename)

        # Unknown type - try OCR as fallback
        logger.warning(f"Unknown file type {file_type}, attempting OCR")
        return await self.ocr_extractor.extract(content, filename)

    def _align_totals_with_ocr(self, ocr_text: str, doc: CanonicalDocument) -> None:
        """
        Align totals with amounts printed on the document when available.

        This mitigates cases where OCR misreads a quantity but the printed TOTAL/TOTAL DUE
        makes the correct amount clear.
        """
        if not ocr_text:
            return

        import re
        from decimal import Decimal

        lines = ocr_text.splitlines()
        total_candidates: list[Decimal] = []

        for idx, line in enumerate(lines):
            if "total" not in line.lower():
                continue

            for segment in (line, lines[idx + 1] if idx + 1 < len(lines) else ""):
                matches = re.findall(r"[-+]?[0-9]+(?:[.,][0-9]{1,2})?", segment)
                for m in matches:
                    try:
                        total_candidates.append(Decimal(m.replace(",", "")))
                    except Exception:
                        continue

        if not total_candidates:
            return

        printed_total = max(total_candidates)
        logger.info("OCR printed totals detected: %s -> using %s", total_candidates, printed_total)
        tolerance = Decimal("0.02")

        if abs(doc.totals.total_amount - printed_total) <= tolerance:
            return

        # Adjust totals to match printed figure.
        doc.totals.total_amount = printed_total
        doc.totals.amount_due = printed_total
        doc.totals.subtotal = printed_total - doc.totals.total_tax

        if not doc.line_items:
            return

        current_sum = sum(item.line_total for item in doc.line_items)
        diff = printed_total - current_sum
        if abs(diff) <= tolerance:
            return

        logger.info("Adjusting last line by %s to match printed total", diff)
        last_item = doc.line_items[-1]
        last_item.line_total += diff
        if last_item.unit_price != 0:
            last_item.quantity = (last_item.line_total / last_item.unit_price).quantize(Decimal("1.0000"))

    def _validate(self, doc: CanonicalDocument) -> ValidationResult:
        """Run all validators on the document."""
        # Math validation
        math_result = self.math_validator.validate(doc)

        # Tax validation
        tax_result = self.tax_validator.validate(doc)

        # Merge results
        return math_result.merge(tax_result)

    def _build_suggestions(
        self,
        validation_result: ValidationResult,
        doc: CanonicalDocument,
    ) -> list[AISuggestion]:
        """Build AI suggestions from validation errors."""
        suggestions = []

        for error in validation_result.errors:
            # Parse error to identify field
            suggestion = AISuggestion(
                field=self._extract_field_from_error(error),
                extracted_value=self._get_extracted_value(error, doc),
                ai_suggestion=self._get_suggested_value(error),
                reason=error,
                confidence=0.5,  # Medium confidence for suggestions
                needs_human_review=True,
            )
            suggestions.append(suggestion)

        return suggestions

    def _extract_field_from_error(self, error: str) -> str:
        """Extract field path from error message."""
        error_lower = error.lower()

        # Check for line item errors (e.g., "Line 1: tax amount mismatch")
        if "line" in error_lower and ":" in error:
            try:
                # Line item error - try to extract line number
                line_part = error.split(":")[0]
                # Find digits in the line part
                import re
                line_match = re.search(r'\d+', line_part)
                if line_match:
                    line_num = int(line_match.group())
                    if "tax amount" in error_lower:
                        return f"line_items[{line_num-1}].tax_amount"
                    elif "total" in error_lower:
                        return f"line_items[{line_num-1}].line_total"
            except (ValueError, IndexError):
                pass  # Fall through to other checks

        if "subtotal" in error_lower:
            return "totals.subtotal"
        if "grand total" in error_lower or "total amount" in error_lower:
            return "totals.total_amount"
        if "total tax" in error_lower:
            return "totals.total_tax"
        if "amount due" in error_lower:
            return "totals.amount_due"
        if "tax breakdown" in error_lower:
            return "totals.tax_breakdown"

        return "unknown"

    def _get_extracted_value(self, error: str, doc: CanonicalDocument) -> Any:
        """Get the extracted value mentioned in the error."""
        # Try to extract the value from the error message
        import re
        numbers = re.findall(r"[\d.]+", error)
        if numbers:
            return numbers[0]
        return "unknown"

    def _get_suggested_value(self, error: str) -> Any:
        """Get the suggested value from the error message."""
        import re
        # Look for "expected X" or "should be X" patterns
        if "expected" in error.lower():
            parts = error.lower().split("expected")
            if len(parts) > 1:
                numbers = re.findall(r"[\d.]+", parts[1])
                if numbers:
                    return numbers[0]
        if "should be" in error.lower():
            parts = error.lower().split("should be")
            if len(parts) > 1:
                numbers = re.findall(r"[\d.]+", parts[1])
                if numbers:
                    return numbers[0]
        return "review required"

    def _create_error_result(
        self,
        filename: str,
        error: str,
        processing_time_ms: int,
    ) -> ProcessingResult:
        """Create an error result."""
        from uuid import uuid4
        from datetime import datetime
        from .models import Metadata, SourceType

        metadata = Metadata(
            source_file=filename,
            source_type=SourceType.IMAGE,
            validation_status=ValidationStatus.INVALID,
            validation_issues=[error],
        )

        empty_doc = CanonicalDocument(metadata=metadata)

        return ProcessingResult(
            status=ValidationStatus.INVALID,
            document_id=metadata.document_id,
            confidence="none",
            data=empty_doc,
            processing_time_ms=processing_time_ms,
            review_required=False,
            suggestions=[],
            message=error,
        )
