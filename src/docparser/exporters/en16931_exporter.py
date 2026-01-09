"""EN 16931 Invoice Exporter (compliant with EU e-invoicing)."""

from .ubl_exporter import UBLInvoiceExporter


class EN16931Exporter(UBLInvoiceExporter):
    """
    Exporter for EN 16931 compliant UBL Invoice.
    
    This uses the same structure as UBL 2.1 but enforces specific
    CustomizationID and ProfileID values required for EU compliance.
    """

    @property
    def format_name(self) -> str:
        return "EN 16931 (EU E-Invoicing)"
        
    @property
    def customization_id(self) -> str:
        return "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"

    @property
    def profile_id(self) -> str | None:
        return "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
