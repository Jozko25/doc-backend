"""Tests for CSV exporter."""

import pytest

from docparser.exporters import CSVExporter


class TestCSVExporter:
    """Test cases for CSVExporter."""

    def setup_method(self):
        """Setup test fixtures."""
        self.exporter = CSVExporter()

    def test_export_produces_csv_string(self, sample_canonical_document):
        """Test that export produces a CSV string."""
        result = self.exporter.export(sample_canonical_document)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_export_contains_document_info(self, sample_canonical_document):
        """Test that CSV contains document information."""
        result = self.exporter.export(sample_canonical_document)

        assert "INV-2024-001" in result
        assert "invoice" in result.lower()

    def test_export_contains_supplier_info(self, sample_canonical_document):
        """Test that CSV contains supplier information."""
        result = self.exporter.export(sample_canonical_document)

        assert "Acme Corporation" in result
        assert "CZ12345678" in result

    def test_export_contains_line_items(self, sample_canonical_document):
        """Test that CSV contains line items."""
        result = self.exporter.export(sample_canonical_document)

        assert "Widget A" in result
        assert "Widget B" in result

    def test_export_contains_totals(self, sample_canonical_document):
        """Test that CSV contains totals."""
        result = self.exporter.export(sample_canonical_document)

        assert "1512.50" in result  # Grand total
        assert "262.50" in result   # Total tax

    def test_format_properties(self):
        """Test exporter format properties."""
        assert self.exporter.format_name == "CSV"
        assert self.exporter.file_extension == ".csv"
        assert self.exporter.mime_type == "text/csv"
