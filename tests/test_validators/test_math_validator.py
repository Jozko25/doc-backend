"""Tests for mathematical validator."""

import pytest
from decimal import Decimal

from docparser.validators import MathValidator


class TestMathValidator:
    """Test cases for MathValidator."""

    def setup_method(self):
        """Setup test fixtures."""
        self.validator = MathValidator()

    def test_valid_document_passes(self, sample_canonical_document):
        """Test that a valid document passes validation."""
        result = self.validator.validate(sample_canonical_document)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_invalid_subtotal_fails(self, sample_canonical_document):
        """Test that wrong subtotal is detected."""
        doc = sample_canonical_document
        doc.totals.subtotal = Decimal("999.00")  # Wrong

        result = self.validator.validate(doc)

        assert not result.is_valid
        assert any("subtotal" in err.lower() for err in result.errors)

    def test_invalid_total_fails(self, sample_canonical_document):
        """Test that wrong grand total is detected."""
        doc = sample_canonical_document
        doc.totals.total_amount = Decimal("9999.00")  # Wrong

        result = self.validator.validate(doc)

        assert not result.is_valid
        assert any("total" in err.lower() for err in result.errors)

    def test_invalid_line_item_total_fails(self, sample_canonical_document):
        """Test that wrong line item total is detected."""
        doc = sample_canonical_document
        doc.line_items[0].line_total = Decimal("9999.00")  # Wrong

        result = self.validator.validate(doc)

        assert not result.is_valid
        assert any("line 1" in err.lower() for err in result.errors)

    def test_tolerance_allows_small_differences(self, sample_canonical_document):
        """Test that small rounding differences are tolerated."""
        doc = sample_canonical_document
        # Add a tiny difference within tolerance
        doc.totals.total_amount = Decimal("1512.51")  # Off by 0.01

        result = self.validator.validate(doc)

        # Should still pass due to tolerance
        assert result.is_valid

    def test_empty_document_passes(self, sample_canonical_document):
        """Test that document with no line items passes."""
        doc = sample_canonical_document
        doc.line_items = []
        doc.totals.subtotal = Decimal("0")
        doc.totals.total_tax = Decimal("0")
        doc.totals.total_amount = Decimal("0")

        result = self.validator.validate(doc)

        assert result.is_valid
