"""CSV exporter for canonical documents."""

import csv
import io
from decimal import Decimal

from ..core.models import CanonicalDocument
from .base import BaseExporter


class CSVExporter(BaseExporter):
    """Export canonical document to CSV format."""

    @property
    def format_name(self) -> str:
        return "CSV"

    @property
    def file_extension(self) -> str:
        return ".csv"

    @property
    def mime_type(self) -> str:
        return "text/csv"

    def export(self, document: CanonicalDocument) -> str:
        """
        Export document to CSV string.

        Creates a CSV with:
        - Header section with document info
        - Line items table
        - Totals section

        Args:
            document: CanonicalDocument to export

        Returns:
            CSV content as string
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Document header section
        writer.writerow(["Document Information"])
        writer.writerow(["Type", document.document.type.value])
        writer.writerow(["Number", document.document.number or ""])
        writer.writerow(["Issue Date", str(document.document.issue_date) if document.document.issue_date else ""])
        writer.writerow(["Due Date", str(document.document.due_date) if document.document.due_date else ""])
        writer.writerow(["Currency", document.document.currency])
        writer.writerow([])

        # Supplier section
        writer.writerow(["Supplier"])
        writer.writerow(["Name", document.supplier.name or ""])
        writer.writerow(["Tax ID", document.supplier.tax_id or ""])
        writer.writerow([
            "Address",
            ", ".join(filter(None, [
                document.supplier.address.street,
                document.supplier.address.city,
                document.supplier.address.postal_code,
                document.supplier.address.country,
            ])),
        ])
        writer.writerow(["IBAN", document.supplier.bank.iban or ""])
        writer.writerow([])

        # Customer section
        writer.writerow(["Customer"])
        writer.writerow(["Name", document.customer.name or ""])
        writer.writerow(["Tax ID", document.customer.tax_id or ""])
        writer.writerow([
            "Address",
            ", ".join(filter(None, [
                document.customer.address.street,
                document.customer.address.city,
                document.customer.address.postal_code,
                document.customer.address.country,
            ])),
        ])
        writer.writerow([])

        # Line items header
        writer.writerow(["Line Items"])
        writer.writerow([
            "Line",
            "Description",
            "Quantity",
            "Unit",
            "Unit Price",
            "Tax Rate %",
            "Tax Amount",
            "Line Total",
        ])

        # Line items data
        for item in document.line_items:
            writer.writerow([
                item.line_number,
                item.description or "",
                self._format_decimal(item.quantity),
                item.unit or "",
                self._format_decimal(item.unit_price),
                self._format_decimal(item.tax_rate) if item.tax_rate else "",
                self._format_decimal(item.tax_amount),
                self._format_decimal(item.line_total),
            ])

        writer.writerow([])

        # Totals section
        writer.writerow(["Totals"])
        writer.writerow(["Subtotal", self._format_decimal(document.totals.subtotal)])

        # Tax breakdown
        for tax in document.totals.tax_breakdown:
            writer.writerow([
                f"Tax ({self._format_decimal(tax.rate)}%)",
                self._format_decimal(tax.tax_amount),
            ])

        writer.writerow(["Total Tax", self._format_decimal(document.totals.total_tax)])
        writer.writerow(["Grand Total", self._format_decimal(document.totals.total_amount)])

        if document.totals.amount_due is not None:
            writer.writerow(["Amount Due", self._format_decimal(document.totals.amount_due)])

        writer.writerow([])

        # Payment info
        if document.payment.reference or document.payment.terms:
            writer.writerow(["Payment Information"])
            if document.payment.terms:
                writer.writerow(["Terms", document.payment.terms])
            if document.payment.reference:
                writer.writerow(["Reference", document.payment.reference])
            if document.payment.method:
                writer.writerow(["Method", document.payment.method])

        # Notes
        if document.notes:
            writer.writerow([])
            writer.writerow(["Notes", document.notes])

        return output.getvalue()

    def _format_decimal(self, value: Decimal | None) -> str:
        """Format decimal for CSV output."""
        if value is None:
            return ""
        # Format with 2 decimal places for currency
        return f"{value:.2f}"
