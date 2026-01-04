"""Pytest configuration and fixtures."""

import pytest
from decimal import Decimal
from datetime import date

from docparser.core.models import (
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
    SourceType,
    TaxBreakdown,
    Totals,
    ValidationStatus,
)


@pytest.fixture
def sample_canonical_document() -> CanonicalDocument:
    """Create a sample canonical document for testing."""
    metadata = Metadata(
        source_file="test_invoice.pdf",
        source_type=SourceType.PDF_NATIVE,
        ocr_confidence=None,
        validation_status=ValidationStatus.VALID,
    )

    document = DocumentInfo(
        type=DocumentType.INVOICE,
        number="INV-2024-001",
        issue_date=date(2024, 1, 15),
        due_date=date(2024, 2, 15),
        currency="EUR",
        language="en",
    )

    supplier = Party(
        name="Acme Corporation",
        tax_id="CZ12345678",
        address=Address(
            street="Main Street 123",
            city="Prague",
            postal_code="11000",
            country="CZ",
        ),
        contact=ContactInfo(
            email="billing@acme.cz",
            phone="+420123456789",
        ),
        bank=BankInfo(
            iban="CZ6508000000192000145399",
            bic="GIBACZPX",
        ),
    )

    customer = Party(
        name="Customer Ltd",
        tax_id="CZ87654321",
        address=Address(
            street="Second Street 456",
            city="Brno",
            postal_code="60200",
            country="CZ",
        ),
    )

    line_items = [
        LineItem(
            line_number=1,
            description="Widget A",
            quantity=Decimal("10"),
            unit="pcs",
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("21"),
            tax_amount=Decimal("210.00"),
            line_total=Decimal("1210.00"),
        ),
        LineItem(
            line_number=2,
            description="Widget B",
            quantity=Decimal("5"),
            unit="pcs",
            unit_price=Decimal("50.00"),
            tax_rate=Decimal("21"),
            tax_amount=Decimal("52.50"),
            line_total=Decimal("302.50"),
        ),
    ]

    totals = Totals(
        subtotal=Decimal("1250.00"),
        tax_breakdown=[
            TaxBreakdown(
                rate=Decimal("21"),
                taxable_amount=Decimal("1250.00"),
                tax_amount=Decimal("262.50"),
            )
        ],
        total_tax=Decimal("262.50"),
        total_amount=Decimal("1512.50"),
        amount_due=Decimal("1512.50"),
        currency="EUR",
    )

    payment = PaymentInfo(
        method="bank_transfer",
        terms="Net 30",
        reference="VS2024001",
    )

    return CanonicalDocument(
        metadata=metadata,
        document=document,
        supplier=supplier,
        customer=customer,
        line_items=line_items,
        totals=totals,
        payment=payment,
        notes="Thank you for your business!",
    )


@pytest.fixture
def invalid_math_document(sample_canonical_document) -> CanonicalDocument:
    """Create a document with mathematical errors for testing validation."""
    doc = sample_canonical_document

    # Introduce errors
    doc.totals.subtotal = Decimal("1000.00")  # Wrong subtotal
    doc.totals.total_amount = Decimal("1500.00")  # Wrong total

    return doc
