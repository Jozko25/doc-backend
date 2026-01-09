"""LLM-based extraction and normalization using OpenAI."""

import json
import logging
from decimal import Decimal
from typing import Any

import pycountry
from openai import AsyncOpenAI

from ..config import get_settings
from ..core.models import (
    Address,
    BankInfo,
    CanonicalDocument,
    ContactInfo,
    DocumentInfo,
    DocumentType,
    LineItem,
    Metadata,
    Party,
    PaymentInfo,
    RawData,
    SourceType,
    TaxBreakdown,
    Totals,
    ValidationStatus,
)
from ..extractors.base import ExtractionResult
from .prompts import get_extraction_prompt, get_revalidation_prompt, get_validation_prompt

logger = logging.getLogger(__name__)


class LLMExtractor:
    """Extract structured data using OpenAI GPT-4."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize LLM extractor.

        Args:
            api_key: OpenAI API key. If None, uses settings.
            model: Model to use. If None, uses settings.
        """
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.llm_model
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy-load OpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def extract_to_canonical(
        self,
        extraction_result: ExtractionResult,
        source_filename: str,
    ) -> CanonicalDocument:
        """
        Extract structured data from raw extraction and convert to canonical format.

        Args:
            extraction_result: Raw extraction from OCR/PDF/Excel
            source_filename: Original filename

        Returns:
            CanonicalDocument with extracted data
        """
        # Prepare content for LLM
        content = self._prepare_content(extraction_result)

        # Get extraction prompt
        prompt = get_extraction_prompt(content)

        # Call LLM for initial extraction
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a document parsing assistant. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                response_format={"type": "json_object"},
            )

            json_text = response.choices[0].message.content
            extracted_data = json.loads(json_text) if json_text else {}

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            extracted_data = {}
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            extracted_data = {}

        # Run AI validation pass to check if extraction makes sense
        if extracted_data:
            extracted_data = await self._validate_extraction(
                extracted_data=extracted_data,
                ocr_text=extraction_result.text or "",
            )

        # Convert to canonical document
        return self._to_canonical_document(
            extracted_data=extracted_data,
            extraction_result=extraction_result,
            source_filename=source_filename,
        )

    async def _validate_extraction(
        self,
        extracted_data: dict[str, Any],
        ocr_text: str,
    ) -> dict[str, Any]:
        """
        Run AI validation pass to verify extraction makes mathematical sense.

        This catches common errors like:
        - Misreading item codes as quantities
        - Wrong decimal placement
        - Math that doesn't add up

        Args:
            extracted_data: Initially extracted data
            ocr_text: Original OCR text

        Returns:
            Corrected or unchanged extracted data
        """
        # Quick sanity check - if math looks reasonable, skip validation
        if self._extraction_looks_valid(extracted_data):
            logger.info("Initial extraction passes sanity check, skipping validation")
            return extracted_data

        logger.info("Initial extraction failed sanity check, running AI validation")

        # Get validation prompt
        extracted_json = json.dumps(extracted_data, indent=2)
        prompt = get_validation_prompt(ocr_text=ocr_text, extracted_json=extracted_json)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a document validation assistant. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            json_text = response.choices[0].message.content
            validated_data = json.loads(json_text) if json_text else extracted_data

            # Check if validation made things better
            if self._extraction_looks_valid(validated_data):
                logger.info("AI validation corrected the extraction")
                return validated_data
            else:
                logger.warning("AI validation did not fix the issues")
                return validated_data

        except Exception as e:
            logger.error(f"AI validation failed: {e}")
            return extracted_data

    def _extraction_looks_valid(self, data: dict[str, Any]) -> bool:
        """
        Quick sanity check to see if extraction looks mathematically valid.

        Returns True if the numbers roughly make sense.
        """
        try:
            line_items = data.get("line_items", [])
            totals = data.get("totals", {})

            if not line_items:
                return True  # No line items to validate

            # Check each line item: quantity * unit_price should be close to line_total
            for item in line_items:
                qty = Decimal(str(item.get("quantity", 0) or 0))
                price = Decimal(str(item.get("unit_price", 0) or 0))
                line_total = Decimal(str(item.get("line_total", 0) or 0))

                if qty == 0 or price == 0 or line_total == 0:
                    continue

                expected = qty * price
                # Allow 5% tolerance for rounding
                tolerance = line_total * Decimal("0.05")
                if abs(expected - line_total) > max(tolerance, Decimal("1")):
                    logger.debug(f"Line item math mismatch: {qty} * {price} = {expected} != {line_total}")
                    return False

            # Check total amount vs sum of line items
            total_amount = Decimal(str(totals.get("total_amount", 0) or 0))
            if total_amount > 0 and line_items:
                sum_lines = sum(
                    Decimal(str(item.get("line_total", 0) or 0))
                    for item in line_items
                )
                # For EU-style receipts, line_total is tax-inclusive and equals total_amount
                # Allow 10% tolerance
                tolerance = total_amount * Decimal("0.1")
                if abs(sum_lines - total_amount) > max(tolerance, Decimal("5")):
                    logger.debug(f"Total mismatch: sum of lines {sum_lines} != {total_amount}")
                    return False

            return True

        except Exception as e:
            logger.debug(f"Validation check failed: {e}")
            return False

    async def revalidate(
        self,
        canonical_doc: CanonicalDocument,
        extraction_result: ExtractionResult,
        errors: list[str],
    ) -> CanonicalDocument:
        """
        Re-validate and attempt to correct extraction errors.

        Args:
            canonical_doc: Current canonical document
            extraction_result: Original extraction result
            errors: List of validation errors

        Returns:
            Corrected CanonicalDocument
        """
        # Prepare original content
        original_content = self._prepare_content(extraction_result)

        # Convert current doc to JSON for the prompt
        doc_dict = canonical_doc.model_dump(mode="json", exclude={"metadata", "raw"})
        extracted_json = json.dumps(doc_dict, indent=2)

        # Get re-validation prompt
        prompt = get_revalidation_prompt(
            errors=errors,
            extracted_json=extracted_json,
            original_content=original_content,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a document validation assistant. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            json_text = response.choices[0].message.content
            corrected_data = json.loads(json_text) if json_text else {}

        except Exception as e:
            logger.error(f"LLM re-validation failed: {e}")
            return canonical_doc

        # Update canonical document with corrections
        return self._to_canonical_document(
            extracted_data=corrected_data,
            extraction_result=extraction_result,
            source_filename=canonical_doc.metadata.source_file,
            existing_metadata=canonical_doc.metadata,
        )

    def _prepare_content(self, extraction_result: ExtractionResult) -> str:
        """Prepare content string for LLM from extraction result."""
        parts = []

        if extraction_result.text:
            parts.append("=== Document Text ===")
            parts.append(extraction_result.text)

        if extraction_result.structured_data:
            parts.append("\n=== Structured Data ===")
            parts.append(json.dumps(extraction_result.structured_data, indent=2))

        return "\n".join(parts) if parts else "[Empty document]"

    def _to_canonical_document(
        self,
        extracted_data: dict[str, Any],
        extraction_result: ExtractionResult,
        source_filename: str,
        existing_metadata: Metadata | None = None,
    ) -> CanonicalDocument:
        """Convert extracted dict to CanonicalDocument."""
        # Determine source type
        source_type_map = {
            "google_cloud_vision": SourceType.IMAGE,
            "mock_ocr": SourceType.IMAGE,
            "pdf_native": SourceType.PDF_NATIVE,
            "pdf_scanned": SourceType.PDF_SCANNED,
            "excel_xlsx": SourceType.EXCEL,
            "excel_xls": SourceType.EXCEL,
            "csv": SourceType.CSV,
            "xml": SourceType.XML,
        }
        source_type = source_type_map.get(extraction_result.source_type, SourceType.IMAGE)

        # Create or update metadata
        if existing_metadata:
            metadata = existing_metadata
        else:
            metadata = Metadata(
                source_file=source_filename,
                source_type=source_type,
                ocr_confidence=extraction_result.confidence,
                validation_status=ValidationStatus.UNCERTAIN,
            )

        # Parse document info
        doc_data = extracted_data.get("document", {})
        document = DocumentInfo(
            type=self._parse_document_type(doc_data.get("type")),
            number=doc_data.get("number"),
            issue_date=self._parse_date(doc_data.get("issue_date")),
            due_date=self._parse_date(doc_data.get("due_date")),
            currency=doc_data.get("currency") or "EUR",
            language=doc_data.get("language"),
        )

        # Parse supplier
        supplier_data = extracted_data.get("supplier", {})
        supplier = self._parse_party(supplier_data)

        # Parse customer (may be null for receipts)
        customer_data = extracted_data.get("customer")
        if customer_data:
            customer = self._parse_party(customer_data)
        else:
            customer = Party()  # Empty party for null customer

        # Parse line items
        line_items = []
        for idx, item_data in enumerate(extracted_data.get("line_items", []), start=1):
            line_item = LineItem(
                line_number=item_data.get("line_number", idx),
                description=item_data.get("description"),
                quantity=self._to_decimal(item_data.get("quantity", 1)),
                unit=item_data.get("unit"),
                unit_price=self._to_decimal(item_data.get("unit_price", 0)),
                tax_rate=self._to_decimal(item_data.get("tax_rate")) if item_data.get("tax_rate") else None,
                tax_amount=self._to_decimal(item_data.get("tax_amount", 0)),
                line_total=self._to_decimal(item_data.get("line_total", 0)),
                notes=item_data.get("notes"),
            )
            line_items.append(line_item)

        # Parse totals
        totals_data = extracted_data.get("totals", {})
        tax_breakdown = []
        for tax_data in totals_data.get("tax_breakdown", []):
            tax_breakdown.append(TaxBreakdown(
                rate=self._to_decimal(tax_data.get("rate", 0)),
                taxable_amount=self._to_decimal(tax_data.get("taxable_amount", 0)),
                tax_amount=self._to_decimal(tax_data.get("tax_amount", 0)),
            ))

        totals = Totals(
            subtotal=self._to_decimal(totals_data.get("subtotal", 0)),
            tax_breakdown=tax_breakdown,
            total_tax=self._to_decimal(totals_data.get("total_tax", 0)),
            shipping_amount=self._to_decimal(totals_data.get("shipping_amount")) if totals_data.get("shipping_amount") else None,
            total_amount=self._to_decimal(totals_data.get("total_amount", 0)),
            amount_due=self._to_decimal(totals_data.get("amount_due")) if totals_data.get("amount_due") else None,
            rounding_amount=self._to_decimal(totals_data.get("rounding_amount")) if totals_data.get("rounding_amount") else None,
            currency=totals_data.get("currency") or document.currency,
        )

        # Parse payment
        payment_data = extracted_data.get("payment", {})
        payment = PaymentInfo(
            method=payment_data.get("method"),
            terms=payment_data.get("terms"),
            reference=payment_data.get("reference"),
        )

        # Raw data for debugging
        raw = RawData(
            ocr_text=extraction_result.text,
            structured_data=extraction_result.structured_data,
            extraction_log=extraction_result.warnings,
        )

        canonical_doc = CanonicalDocument(
            metadata=metadata,
            document=document,
            supplier=supplier,
            customer=customer,
            line_items=line_items,
            totals=totals,
            payment=payment,
            notes=extracted_data.get("notes"),
            raw=raw,
        )

        # Reconcile with printed totals from OCR text to fix common OCR quantity errors.
        self._reconcile_totals_with_ocr(raw.ocr_text or "", canonical_doc)

        return canonical_doc

    def _parse_party(self, data: dict[str, Any]) -> Party:
        """Parse party (supplier/customer) data."""
        address_data = data.get("address") or {}
        address = Address(
            street=address_data.get("street"),
            city=address_data.get("city"),
            postal_code=address_data.get("postal_code"),
            country=self._normalize_country(address_data.get("country")),
        )

        contact_data = data.get("contact") or {}
        contact = ContactInfo(
            email=contact_data.get("email"),
            phone=contact_data.get("phone"),
        )

        bank_data = data.get("bank") or {}
        bank = BankInfo(
            iban=bank_data.get("iban"),
            bic=bank_data.get("bic"),
        )

        return Party(
            name=data.get("name"),
            tax_id=data.get("tax_id"),
            registration_number=data.get("registration_number"),
            address=address,
            contact=contact,
            bank=bank,
        )

    def _parse_document_type(self, type_str: str | None) -> DocumentType:
        """Parse document type string to enum."""
        if not type_str:
            return DocumentType.INVOICE
        type_lower = type_str.lower()
        if "credit" in type_lower:
            return DocumentType.CREDIT_NOTE
        if "receipt" in type_lower:
            return DocumentType.RECEIPT
        return DocumentType.INVOICE

    def _normalize_country(self, value: str | None) -> str | None:
        """
        Normalize country input to ISO alpha-2 codes for model validation.

        Accepts common country names or 2-letter codes; returns None if unresolvable.
        """
        if not value:
            return None

        candidate = str(value).strip()
        if len(candidate) == 2:
            return candidate.upper()

        try:
            match = pycountry.countries.search_fuzzy(candidate)[0]
            return match.alpha_2
        except (LookupError, AttributeError, IndexError):
            return None

    def _reconcile_totals_with_ocr(self, ocr_text: str, doc: CanonicalDocument) -> None:
        """
        Align totals with amounts printed on the document when OCR shows a clear total.

        This guards against line-level OCR mistakes (e.g., quantity misread) by trusting
        the printed TOTAL / TOTAL DUE amounts and minimally adjusting line items.
        """
        import re

        if not ocr_text:
            return

        # Find numeric amounts on lines that look like totals.
        total_candidates: list[Decimal] = []
        lines = ocr_text.splitlines()
        for idx, line in enumerate(lines):
            if "total" not in line.lower():
                continue

            # Numbers on the same line
            for segment in (line, lines[idx + 1] if idx + 1 < len(lines) else ""):
                matches = re.findall(r"[-+]?[0-9]+(?:[.,][0-9]{1,2})?", segment)
                for m in matches:
                    try:
                        total_candidates.append(Decimal(m.replace(",", "")))
                    except Exception:
                        continue

        if not total_candidates:
            return

        # Heuristic: largest total-like number is usually the amount due.
        printed_total = max(total_candidates)

        # If we already match within tolerance, do nothing.
        tolerance = Decimal("0.02")
        if abs(doc.totals.total_amount - printed_total) <= tolerance:
            return

        # Assume tax is already correct; adjust subtotal/amount_due to printed total.
        doc.totals.total_amount = printed_total
        doc.totals.amount_due = printed_total
        doc.totals.subtotal = printed_total - doc.totals.total_tax

        if not doc.line_items:
            return

        # Adjust the last line item to make the sum match the printed total.
        current_sum = sum(item.line_total for item in doc.line_items)
        diff = printed_total - current_sum
        if abs(diff) <= tolerance:
            return

        last_item = doc.line_items[-1]
        last_item.line_total += diff
        # Recompute quantity from unit price if available and non-zero.
        if last_item.unit_price != 0:
            last_item.quantity = (last_item.line_total / last_item.unit_price).quantize(Decimal("1.0000"))

    def _parse_date(self, date_str: str | None):
        """Parse date string to date object."""
        if not date_str:
            return None
        try:
            from datetime import date
            # Handle YYYY-MM-DD format
            parts = date_str.split("-")
            if len(parts) == 3:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            pass
        return None

    def _to_decimal(self, value: Any) -> Decimal:
        """Convert value to Decimal."""
        if value is None:
            return Decimal("0")
        try:
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))
        except Exception:
            return Decimal("0")
