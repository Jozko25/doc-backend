#!/usr/bin/env python3
"""Local testing script for DocParser.

Run this script to test the system locally without setting up a full server.
Useful for development and debugging.

Usage:
    python scripts/local_test.py --file path/to/invoice.pdf
    python scripts/local_test.py --mock  # Use mock data
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docparser.core.models import CanonicalDocument
from docparser.core.pipeline import DocumentPipeline
from docparser.exporters import CSVExporter, ExcelExporter
from docparser.extractors import MockOCRExtractor
from docparser.utils.file_handlers import detect_file_type


async def process_file(file_path: Path) -> None:
    """Process a document file and print results."""
    print(f"\n{'='*60}")
    print(f"Processing: {file_path.name}")
    print(f"{'='*60}\n")

    # Read file
    content = file_path.read_bytes()
    file_type = detect_file_type(content, file_path.name)

    print(f"Detected file type: {file_type.value}")

    # Create pipeline
    pipeline = DocumentPipeline()

    # Process
    result = await pipeline.process(
        content=content,
        filename=file_path.name,
        file_type=file_type,
    )

    # Print results
    print(f"\nStatus: {result.status.value}")
    print(f"Confidence: {result.confidence}")
    print(f"Processing time: {result.processing_time_ms}ms")

    if result.review_required:
        print(f"\n⚠️  Review required!")
        print(f"Message: {result.message}")

        if result.suggestions:
            print("\nSuggestions:")
            for suggestion in result.suggestions:
                print(f"  - {suggestion.field}: {suggestion.reason}")

    # Print extracted data summary
    doc = result.data
    print(f"\n--- Extracted Data ---")
    print(f"Document Type: {doc.document.type.value}")
    print(f"Document Number: {doc.document.number}")
    print(f"Issue Date: {doc.document.issue_date}")
    print(f"Currency: {doc.document.currency}")

    print(f"\nSupplier: {doc.supplier.name}")
    print(f"Customer: {doc.customer.name}")

    print(f"\nLine Items: {len(doc.line_items)}")
    for item in doc.line_items[:5]:  # Show first 5
        print(f"  {item.line_number}. {item.description}: {item.quantity} x {item.unit_price} = {item.line_total}")

    if len(doc.line_items) > 5:
        print(f"  ... and {len(doc.line_items) - 5} more items")

    print(f"\nTotals:")
    print(f"  Subtotal: {doc.totals.subtotal}")
    print(f"  Tax: {doc.totals.total_tax}")
    print(f"  Total: {doc.totals.total_amount}")


async def run_mock_test() -> None:
    """Run a mock test without actual files or API calls."""
    print("\n" + "="*60)
    print("Running mock test (no external APIs)")
    print("="*60 + "\n")

    # Create mock OCR extractor
    mock_ocr = MockOCRExtractor(
        mock_text="""
        INVOICE

        Invoice Number: INV-2024-TEST
        Date: 2024-01-15
        Due Date: 2024-02-15

        From:
        Test Supplier Corp
        123 Main Street
        Prague, 11000
        Czech Republic
        VAT: CZ12345678

        To:
        Test Customer Ltd
        456 Second Ave
        Brno, 60200
        Czech Republic

        Items:
        1. Product Alpha    10 pcs  @ 100.00 EUR = 1000.00 EUR
        2. Service Beta      5 hrs  @  50.00 EUR =  250.00 EUR

        Subtotal: 1250.00 EUR
        VAT (21%):  262.50 EUR
        Total:     1512.50 EUR

        Payment Terms: Net 30
        Bank: CZ6508000000192000145399
        """,
        mock_confidence=0.92,
    )

    # Note: This will still require OpenAI API for LLM extraction
    # In a full mock test, you'd also mock the LLM extractor

    print("Mock OCR text extracted:")
    result = await mock_ocr.extract(b"fake_image_content", "test.jpg")
    print(result.text[:500] + "..." if len(result.text or "") > 500 else result.text)
    print(f"\nConfidence: {result.confidence}")

    # Test exporters with sample document
    from tests.conftest import sample_canonical_document

    # Get fixture manually (since we're not in pytest context)
    from datetime import date
    from decimal import Decimal
    from docparser.core.models import (
        Address, BankInfo, ContactInfo, DocumentInfo, DocumentType,
        LineItem, Metadata, Party, PaymentInfo, SourceType, TaxBreakdown,
        Totals, ValidationStatus
    )

    metadata = Metadata(
        source_file="test_invoice.pdf",
        source_type=SourceType.PDF_NATIVE,
        validation_status=ValidationStatus.VALID,
    )

    doc = CanonicalDocument(
        metadata=metadata,
        document=DocumentInfo(
            type=DocumentType.INVOICE,
            number="INV-2024-TEST",
            issue_date=date(2024, 1, 15),
            currency="EUR",
        ),
        supplier=Party(
            name="Test Supplier Corp",
            tax_id="CZ12345678",
            address=Address(street="123 Main Street", city="Prague", country="CZ"),
        ),
        customer=Party(
            name="Test Customer Ltd",
            address=Address(street="456 Second Ave", city="Brno", country="CZ"),
        ),
        line_items=[
            LineItem(
                line_number=1,
                description="Product Alpha",
                quantity=Decimal("10"),
                unit="pcs",
                unit_price=Decimal("100.00"),
                tax_rate=Decimal("21"),
                tax_amount=Decimal("210.00"),
                line_total=Decimal("1210.00"),
            ),
        ],
        totals=Totals(
            subtotal=Decimal("1000.00"),
            total_tax=Decimal("210.00"),
            total_amount=Decimal("1210.00"),
            currency="EUR",
        ),
    )

    # Test CSV export
    print("\n--- CSV Export ---")
    csv_exporter = CSVExporter()
    csv_output = csv_exporter.export(doc)
    print(csv_output[:500] + "..." if len(csv_output) > 500 else csv_output)

    # Test Excel export
    print("\n--- Excel Export ---")
    excel_exporter = ExcelExporter()
    excel_bytes = excel_exporter.export(doc)
    print(f"Excel file size: {len(excel_bytes)} bytes")

    # Test validation
    print("\n--- Validation Test ---")
    from docparser.validators import MathValidator, TaxValidator

    math_validator = MathValidator()
    tax_validator = TaxValidator()

    math_result = math_validator.validate(doc)
    tax_result = tax_validator.validate(doc)

    print(f"Math validation passed: {math_result.is_valid}")
    if not math_result.is_valid:
        for error in math_result.errors:
            print(f"  Error: {error}")

    print(f"Tax validation passed: {tax_result.is_valid}")
    for warning in tax_result.warnings:
        print(f"  Warning: {warning}")

    print("\n✅ Mock test completed successfully!")


def main():
    parser = argparse.ArgumentParser(description="Local testing for DocParser")
    parser.add_argument("--file", "-f", type=Path, help="File to process")
    parser.add_argument("--mock", action="store_true", help="Run mock test without files")
    parser.add_argument("--output-json", "-o", type=Path, help="Save canonical JSON to file")

    args = parser.parse_args()

    if args.mock:
        asyncio.run(run_mock_test())
    elif args.file:
        if not args.file.exists():
            print(f"Error: File not found: {args.file}")
            sys.exit(1)
        asyncio.run(process_file(args.file))
    else:
        parser.print_help()
        print("\nExample:")
        print("  python scripts/local_test.py --mock")
        print("  python scripts/local_test.py --file invoice.pdf")


if __name__ == "__main__":
    main()
