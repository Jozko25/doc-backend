"""UBL 2.1 Invoice Exporter."""

from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from ..core.models import CanonicalDocument
from .base import BaseExporter


class UBLInvoiceExporter(BaseExporter):
    """Exporter for UBL 2.1 Invoice format."""

    @property
    def format_name(self) -> str:
        return "UBL 2.1 Invoice"

    @property
    def file_extension(self) -> str:
        return "xml"

    @property
    def mime_type(self) -> str:
        return "application/xml"

    @property
    def customization_id(self) -> str:
        return "urn:oasis:names:specification:ubl:xsd:Invoice-2"

    @property
    def profile_id(self) -> str | None:
        return None

    def export(self, document: CanonicalDocument) -> bytes:
        """Generate UBL 2.1 XML."""
        # Namespaces
        ns = {
            "xmlns": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "xmlns:cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "xmlns:cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        }

        # Root element
        root = Element("Invoice", ns)

        # Basic Invoice Info
        self._add_cbc(root, "UBLVersionID", "2.1")
        self._add_cbc(root, "CustomizationID", self.customization_id)
        if self.profile_id:
            self._add_cbc(root, "ProfileID", self.profile_id)
        self._add_cbc(root, "ID", document.document.number or "UNKNOWN")
        self._add_cbc(root, "IssueDate", str(document.document.issue_date) if document.document.issue_date else "")
        self._add_cbc(root, "DueDate", str(document.document.due_date) if document.document.due_date else "")
        self._add_cbc(root, "InvoiceTypeCode", "380")  # 380 = Commercial Invoice
        self._add_cbc(root, "DocumentCurrencyCode", document.document.currency)

        # Supplier (AccountingSupplierParty)
        supplier = SubElement(root, "cac:AccountingSupplierParty")
        party = SubElement(supplier, "cac:Party")
        self._add_party_details(party, document.supplier)

        # Customer (AccountingCustomerParty)
        customer = SubElement(root, "cac:AccountingCustomerParty")
        party = SubElement(customer, "cac:Party")
        self._add_party_details(party, document.customer)

        # Tax Total
        tax_total = SubElement(root, "cac:TaxTotal")
        self._add_cbc(tax_total, "TaxAmount", str(document.totals.total_tax), currency=document.totals.currency)
        
        for tax in document.totals.tax_breakdown:
            subtotal = SubElement(tax_total, "cac:TaxSubtotal")
            self._add_cbc(subtotal, "TaxableAmount", str(tax.taxable_amount), currency=document.totals.currency)
            self._add_cbc(subtotal, "TaxAmount", str(tax.tax_amount), currency=document.totals.currency)
            
            category = SubElement(subtotal, "cac:TaxCategory")
            self._add_cbc(category, "ID", "S") # Standard rate, hardcoded for now
            self._add_cbc(category, "Percent", str(tax.rate))
            scheme = SubElement(category, "cac:TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")

        # Legal Monetary Total
        legal_total = SubElement(root, "cac:LegalMonetaryTotal")
        self._add_cbc(legal_total, "LineExtensionAmount", str(document.totals.subtotal), currency=document.totals.currency)
        self._add_cbc(legal_total, "TaxExclusiveAmount", str(document.totals.subtotal), currency=document.totals.currency)
        self._add_cbc(legal_total, "TaxInclusiveAmount", str(document.totals.total_amount), currency=document.totals.currency)
        if document.totals.amount_due is not None:
             self._add_cbc(legal_total, "PayableAmount", str(document.totals.amount_due), currency=document.totals.currency)
        else:
             self._add_cbc(legal_total, "PayableAmount", str(document.totals.total_amount), currency=document.totals.currency)

        # Line Items
        for item in document.line_items:
            line = SubElement(root, "cac:InvoiceLine")
            self._add_cbc(line, "ID", str(item.line_number))
            self._add_cbc(line, "InvoicedQuantity", str(item.quantity), unit=item.unit or "EA") # EA = Each
            self._add_cbc(line, "LineExtensionAmount", str(item.line_total if item.tax_amount == 0 else (item.line_total - item.tax_amount)), currency=document.totals.currency)

            item_elem = SubElement(line, "cac:Item")
            self._add_cbc(item_elem, "Name", item.description or "Item")
            
            classified_tax = SubElement(item_elem, "cac:ClassifiedTaxCategory")
            self._add_cbc(classified_tax, "ID", "S")
            self._add_cbc(classified_tax, "Percent", str(item.tax_rate) if item.tax_rate else "0")
            scheme = SubElement(classified_tax, "cac:TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")

            price = SubElement(line, "cac:Price")
            self._add_cbc(price, "PriceAmount", str(item.unit_price), currency=document.totals.currency)

        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _add_cbc(self, parent: Element, tag: str, text: str, currency: str = None, unit: str = None):
        """Helper to add CommonBasicComponents."""
        elem = SubElement(parent, f"cbc:{tag}")
        elem.text = text
        if currency:
            elem.set("currencyID", currency)
        if unit:
            elem.set("unitCode", unit)

    def _add_party_details(self, parent: Element, party_data: Any):
        """Helper to add Party details."""
        if party_data.name:
            name_elem = SubElement(parent, "cac:PartyName")
            self._add_cbc(name_elem, "Name", party_data.name)
        
        addr = party_data.address
        if addr:
            addr_elem = SubElement(parent, "cac:PostalAddress")
            if addr.street: self._add_cbc(addr_elem, "StreetName", addr.street)
            if addr.city: self._add_cbc(addr_elem, "CityName", addr.city)
            if addr.postal_code: self._add_cbc(addr_elem, "PostalZone", addr.postal_code)
            if addr.country:
                country = SubElement(addr_elem, "cac:Country")
                self._add_cbc(country, "IdentificationCode", addr.country)

        if party_data.tax_id:
            tax_scheme = SubElement(parent, "cac:PartyTaxScheme")
            self._add_cbc(tax_scheme, "CompanyID", party_data.tax_id)
            scheme = SubElement(tax_scheme, "cac:TaxScheme")
            self._add_cbc(scheme, "ID", "VAT")
        
        legal_entity = SubElement(parent, "cac:PartyLegalEntity")
        self._add_cbc(legal_entity, "RegistrationName", party_data.name or "Unknown")
