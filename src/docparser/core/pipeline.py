"""Main document processing pipeline."""

import logging
import time
from typing import TYPE_CHECKING, Any

from ..config import get_settings
from ..extractors import ExtractionResult, OCRExtractor, PDFExtractor, XMLExtractor
from ..normalizers import LLMExtractor
from ..utils.file_handlers import FileHandler, FileType, is_image_type, is_structured_type
from ..validators import MathValidator, TaxValidator, ValidationResult
from .models import (
    AISuggestion,
    BoundingBoxModel,
    CanonicalDocument,
    ProcessingResult,
    ValidationStatus,
)

# Lazy import for ExcelExtractor to avoid pandas import issues with Python 3.14
if TYPE_CHECKING:
    from ..extractors.excel import ExcelExtractor


def _get_excel_extractor():
    """Lazy load ExcelExtractor to avoid pandas import at module load."""
    from ..extractors.excel import ExcelExtractor
    return ExcelExtractor()

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
        excel_extractor: "ExcelExtractor | None" = None,
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
        self._excel_extractor = excel_extractor  # Lazy loaded
        self.xml_extractor = xml_extractor or XMLExtractor()
        self.math_validator = math_validator or MathValidator()
        self.tax_validator = tax_validator or TaxValidator()

        # Always use OpenAI LLM extractor (Gemini and regex fallbacks removed)
        self.llm_extractor = llm_extractor or LLMExtractor()
        logger.info("Using OpenAI for extraction")

        self.max_retries = settings.max_validation_retries
        self.file_handler = FileHandler(settings.max_file_size_bytes)

    @property
    def excel_extractor(self):
        """Lazy load ExcelExtractor on first access."""
        if self._excel_extractor is None:
            self._excel_extractor = _get_excel_extractor()
        return self._excel_extractor

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

        # Convert bounding boxes to model format and link to document fields
        bounding_boxes = self._link_bounding_boxes_to_fields(
            extraction_result.bounding_boxes, canonical_doc
        )

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
                bounding_boxes=bounding_boxes,
                image_width=extraction_result.image_width,
                image_height=extraction_result.image_height,
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
                bounding_boxes=bounding_boxes,
                image_width=extraction_result.image_width,
                image_height=extraction_result.image_height,
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

    def _link_bounding_boxes_to_fields(
        self,
        raw_boxes: list,
        doc: CanonicalDocument,
    ) -> list[BoundingBoxModel]:
        """
        Link bounding boxes to document fields by matching text values.

        This enables automatic syncing when annotations are edited.
        """
        from decimal import Decimal
        import re

        # Build a map of field values to their paths
        # We add multiple format variants for each value to improve matching
        field_map: dict[str, str] = {}

        def add_number_variants(value: Decimal | None, field_path: str):
            """Add multiple format variants for a number to improve OCR matching."""
            if value is None:
                return
            # Normalized form (e.g., "86.99")
            normalized = str(value.normalize())
            field_map[normalized] = field_path
            # With comma as decimal separator (European: "86,99")
            field_map[normalized.replace('.', ',')] = field_path
            # Without trailing zeros
            try:
                clean = str(Decimal(normalized).quantize(Decimal('0.01')))
                field_map[clean] = field_path
                field_map[clean.replace('.', ',')] = field_path
            except Exception:
                pass
            # Integer form if whole number
            if value == value.to_integral_value():
                field_map[str(int(value))] = field_path

        def add_text_variants(value: str | None, field_path: str):
            """Add text value and common variants."""
            if not value:
                return
            stripped = value.strip()
            field_map[stripped] = field_path
            # Also add individual words for multi-word values (helps with OCR word splitting)
            words = stripped.split()
            if len(words) > 1:
                for word in words:
                    clean_word = word.strip('.,;:')
                    if len(clean_word) > 3:  # Only meaningful words
                        # Don't overwrite existing mappings with partial matches
                        if clean_word not in field_map:
                            field_map[clean_word] = field_path

        # Add totals fields (with priority - add unique values first)
        if doc.totals:
            totals = doc.totals
            # Add in order of priority (most specific first)
            add_number_variants(totals.total_tax, "totals.total_tax")
            add_number_variants(totals.subtotal, "totals.subtotal")
            add_number_variants(totals.total_amount, "totals.total_amount")
            add_number_variants(totals.amount_due, "totals.amount_due")

        # Add document info fields
        if doc.document:
            add_text_variants(doc.document.number, "document.number")
            # Add date variants
            if doc.document.issue_date:
                date_str = str(doc.document.issue_date)
                field_map[date_str] = "document.issue_date"
                # Common date formats
                field_map[date_str.replace('-', '.')] = "document.issue_date"
                field_map[date_str.replace('-', '/')] = "document.issue_date"
            if doc.document.due_date:
                date_str = str(doc.document.due_date)
                field_map[date_str] = "document.due_date"
                field_map[date_str.replace('-', '.')] = "document.due_date"
                field_map[date_str.replace('-', '/')] = "document.due_date"
            # Currency
            if doc.document.currency:
                field_map[doc.document.currency] = "document.currency"

        # Add party fields
        for party_type in ["supplier", "customer"]:
            party = getattr(doc, party_type, None)
            if party:
                add_text_variants(party.name, f"{party_type}.name")
                add_text_variants(party.tax_id, f"{party_type}.tax_id")
                # IBAN
                if party.bank and party.bank.iban:
                    add_text_variants(party.bank.iban, f"{party_type}.bank.iban")

        # Add line item fields
        for i, item in enumerate(doc.line_items or []):
            add_text_variants(item.description, f"line_items[{i}].description")
            add_number_variants(item.quantity, f"line_items[{i}].quantity")
            add_number_variants(item.unit_price, f"line_items[{i}].unit_price")
            add_number_variants(item.line_total, f"line_items[{i}].line_total")
            add_number_variants(item.tax_amount, f"line_items[{i}].tax_amount")
            add_number_variants(item.tax_rate, f"line_items[{i}].tax_rate")

        logger.debug(f"Field map has {len(field_map)} entries for linking")

        # Now link bounding boxes to fields (only first match per field)
        used_fields: set[str] = set()
        result = []
        for box in raw_boxes:
            box_text = box.text.strip()
            normalized_text = self._normalize_number_text(box_text)

            # Try to find a matching field (try multiple formats)
            field_path = (
                field_map.get(normalized_text) or
                field_map.get(box_text) or
                field_map.get(box_text.replace('.', ',')) or
                field_map.get(box_text.replace(',', '.'))
            )

            # Only assign field_path if this field hasn't been used yet
            if field_path and field_path in used_fields:
                field_path = None  # Don't link duplicate matches
            elif field_path:
                used_fields.add(field_path)
                logger.debug(f"Linked box '{box_text}' to {field_path}")

            result.append(BoundingBoxModel(
                text=box.text,
                x=box.x,
                y=box.y,
                width=box.width,
                height=box.height,
                confidence=box.confidence,
                field_path=field_path,
            ))

        logger.info(f"Linked {len(used_fields)} bounding boxes to document fields")
        return result

    def _normalize_number(self, value: Any) -> str:
        """Normalize a numeric value for comparison."""
        from decimal import Decimal

        if isinstance(value, Decimal):
            # Remove trailing zeros and convert to string
            normalized = value.normalize()
            return str(normalized)
        return str(value)

    def _normalize_number_text(self, text: str) -> str:
        """Normalize text that might be a number for comparison."""
        import re

        # Remove common currency symbols and whitespace
        cleaned = re.sub(r'[€$£¥\s]', '', text)

        # Handle comma as decimal separator (European format)
        if ',' in cleaned and '.' not in cleaned:
            cleaned = cleaned.replace(',', '.')
        elif ',' in cleaned and '.' in cleaned:
            # Assume comma is thousands separator
            cleaned = cleaned.replace(',', '')

        # Try to parse as decimal and normalize
        try:
            from decimal import Decimal
            return str(Decimal(cleaned).normalize())
        except Exception:
            return text
