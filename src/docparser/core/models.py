"""Pydantic models for the canonical JSON schema."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    """Status of document validation."""

    VALID = "valid"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"


class DocumentType(str, Enum):
    """Type of document."""

    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    RECEIPT = "receipt"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    """Type of source file."""

    IMAGE = "image"
    PDF_SCANNED = "pdf_scanned"
    PDF_NATIVE = "pdf_native"
    EXCEL = "excel"
    CSV = "csv"
    XML = "xml"


class AISuggestion(BaseModel):
    """AI suggestion for uncertain field values."""

    field: str = Field(..., description="JSON path to the field (e.g., 'totals.total_amount')")
    extracted_value: Any = Field(..., description="Value extracted from document")
    ai_suggestion: Any = Field(..., description="What AI thinks the value should be")
    reason: str = Field(..., description="Explanation of why AI suggests this")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    needs_human_review: bool = Field(default=True)


class Metadata(BaseModel):
    """Document processing metadata."""

    document_id: UUID = Field(default_factory=uuid4)
    source_file: str = Field(..., description="Original filename")
    source_type: SourceType
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_status: ValidationStatus = Field(default=ValidationStatus.UNCERTAIN)
    validation_issues: list[str] = Field(default_factory=list)
    ai_suggestions: list[AISuggestion] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    """Core document information."""

    type: DocumentType = Field(default=DocumentType.INVOICE)
    number: str | None = Field(default=None, description="Document number (e.g., INV-2024-001)")
    issue_date: date | None = Field(default=None)
    due_date: date | None = Field(default=None)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    language: str | None = Field(default=None, min_length=2, max_length=2)


class Address(BaseModel):
    """Address information."""

    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = None


class ContactInfo(BaseModel):
    """Contact information."""

    email: str | None = None
    phone: str | None = None
    website: str | None = None


class BankInfo(BaseModel):
    """Bank account information."""

    iban: str | None = None
    bic: str | None = None
    account_number: str | None = None
    bank_name: str | None = None


class Party(BaseModel):
    """Supplier or customer party."""

    name: str | None = None
    tax_id: str | None = Field(default=None, description="VAT/Tax ID")
    registration_number: str | None = Field(default=None, description="Company registration number")
    address: Address = Field(default_factory=Address)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    bank: BankInfo = Field(default_factory=BankInfo)


class LineItem(BaseModel):
    """Invoice line item."""

    line_number: int = Field(..., ge=1)
    description: str | None = None
    quantity: Decimal = Field(default=Decimal("1"))
    unit: str | None = Field(default=None, description="Unit of measure (pcs, kg, etc.)")
    unit_price: Decimal = Field(default=Decimal("0"))
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    discount_amount: Decimal | None = Field(default=None)
    tax_rate: Decimal | None = Field(default=None, description="Tax rate percentage")
    tax_amount: Decimal = Field(default=Decimal("0"))
    line_total: Decimal = Field(default=Decimal("0"), description="Total including tax")
    notes: str | None = None

    @property
    def net_amount(self) -> Decimal:
        """Calculate net amount (before tax)."""
        return self.line_total - self.tax_amount


class TaxBreakdown(BaseModel):
    """Tax breakdown by rate."""

    rate: Decimal = Field(..., description="Tax rate percentage")
    taxable_amount: Decimal = Field(..., description="Amount subject to this tax rate")
    tax_amount: Decimal = Field(..., description="Calculated tax amount")


class Totals(BaseModel):
    """Document totals."""

    subtotal: Decimal = Field(default=Decimal("0"), description="Sum before tax")
    tax_breakdown: list[TaxBreakdown] = Field(default_factory=list)
    total_tax: Decimal = Field(default=Decimal("0"))
    shipping_amount: Decimal | None = Field(default=None, description="Shipping/delivery cost")
    total_amount: Decimal = Field(default=Decimal("0"), description="Grand total including tax")
    amount_due: Decimal | None = Field(default=None, description="Amount remaining to be paid")
    prepaid_amount: Decimal | None = Field(default=None)
    rounding_amount: Decimal | None = Field(default=None)
    currency: str = Field(default="EUR", min_length=3, max_length=3)


class PaymentInfo(BaseModel):
    """Payment information."""

    method: str | None = Field(default=None, description="bank_transfer, card, cash, etc.")
    terms: str | None = Field(default=None, description="Payment terms (Net 30, etc.)")
    reference: str | None = Field(default=None, description="Payment reference / variable symbol")
    paid_amount: Decimal | None = Field(default=None)
    paid_date: date | None = Field(default=None)


class RawData(BaseModel):
    """Raw extraction data for debugging and re-processing."""

    ocr_text: str | None = None
    structured_data: dict[str, Any] | None = None
    extraction_log: list[str] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    """
    The canonical JSON document format.

    This is the internal representation that all documents are normalized to,
    and from which all exports are generated.
    """

    schema_version: str = Field(default="1.0.0")
    metadata: Metadata
    document: DocumentInfo = Field(default_factory=DocumentInfo)
    supplier: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    line_items: list[LineItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    payment: PaymentInfo = Field(default_factory=PaymentInfo)
    notes: str | None = None
    raw: RawData = Field(default_factory=RawData, alias="_raw")

    class Config:
        populate_by_name = True


class ProcessingResult(BaseModel):
    """Result of document processing."""

    status: ValidationStatus
    document_id: UUID
    confidence: str = Field(..., description="high, medium, or low")
    data: CanonicalDocument
    processing_time_ms: int | None = None
    review_required: bool = False
    suggestions: list[AISuggestion] = Field(default_factory=list)
    message: str | None = None
