"""Tax and VAT validation."""

import re
from dataclasses import dataclass
from decimal import Decimal

from .math_validator import ValidationResult


# Standard VAT rates by country (main rate)
COUNTRY_VAT_RATES: dict[str, list[Decimal]] = {
    # EU countries
    "AT": [Decimal("20"), Decimal("10"), Decimal("13")],  # Austria
    "BE": [Decimal("21"), Decimal("12"), Decimal("6")],   # Belgium
    "BG": [Decimal("20"), Decimal("9")],                  # Bulgaria
    "CY": [Decimal("19"), Decimal("9"), Decimal("5")],    # Cyprus
    "CZ": [Decimal("21"), Decimal("15"), Decimal("10")],  # Czech Republic
    "DE": [Decimal("19"), Decimal("7")],                  # Germany
    "DK": [Decimal("25")],                                # Denmark
    "EE": [Decimal("22"), Decimal("9")],                  # Estonia
    "ES": [Decimal("21"), Decimal("10"), Decimal("4")],   # Spain
    "FI": [Decimal("24"), Decimal("14"), Decimal("10")],  # Finland
    "FR": [Decimal("20"), Decimal("10"), Decimal("5.5")], # France
    "GR": [Decimal("24"), Decimal("13"), Decimal("6")],   # Greece
    "HR": [Decimal("25"), Decimal("13"), Decimal("5")],   # Croatia
    "HU": [Decimal("27"), Decimal("18"), Decimal("5")],   # Hungary
    "IE": [Decimal("23"), Decimal("13.5"), Decimal("9")], # Ireland
    "IT": [Decimal("22"), Decimal("10"), Decimal("5")],   # Italy
    "LT": [Decimal("21"), Decimal("9"), Decimal("5")],    # Lithuania
    "LU": [Decimal("17"), Decimal("14"), Decimal("8")],   # Luxembourg
    "LV": [Decimal("21"), Decimal("12"), Decimal("5")],   # Latvia
    "MT": [Decimal("18"), Decimal("7"), Decimal("5")],    # Malta
    "NL": [Decimal("21"), Decimal("9")],                  # Netherlands
    "PL": [Decimal("23"), Decimal("8"), Decimal("5")],    # Poland
    "PT": [Decimal("23"), Decimal("13"), Decimal("6")],   # Portugal
    "RO": [Decimal("19"), Decimal("9"), Decimal("5")],    # Romania
    "SE": [Decimal("25"), Decimal("12"), Decimal("6")],   # Sweden
    "SI": [Decimal("22"), Decimal("9.5")],                # Slovenia
    "SK": [Decimal("20"), Decimal("10")],                 # Slovakia
    # Non-EU
    "GB": [Decimal("20"), Decimal("5")],                  # UK
    "CH": [Decimal("8.1"), Decimal("2.6")],               # Switzerland
    "NO": [Decimal("25"), Decimal("15"), Decimal("12")],  # Norway
    "US": [],  # No federal VAT
}

# VAT ID format patterns by country prefix
VAT_ID_PATTERNS: dict[str, str] = {
    "AT": r"^ATU\d{8}$",
    "BE": r"^BE[01]\d{9}$",
    "BG": r"^BG\d{9,10}$",
    "CY": r"^CY\d{8}[A-Z]$",
    "CZ": r"^CZ\d{8,10}$",
    "DE": r"^DE\d{9}$",
    "DK": r"^DK\d{8}$",
    "EE": r"^EE\d{9}$",
    "ES": r"^ES[A-Z0-9]\d{7}[A-Z0-9]$",
    "FI": r"^FI\d{8}$",
    "FR": r"^FR[A-Z0-9]{2}\d{9}$",
    "GB": r"^GB(\d{9}|\d{12}|(GD|HA)\d{3})$",
    "GR": r"^EL\d{9}$",
    "HR": r"^HR\d{11}$",
    "HU": r"^HU\d{8}$",
    "IE": r"^IE\d{7}[A-Z]{1,2}$",
    "IT": r"^IT\d{11}$",
    "LT": r"^LT(\d{9}|\d{12})$",
    "LU": r"^LU\d{8}$",
    "LV": r"^LV\d{11}$",
    "MT": r"^MT\d{8}$",
    "NL": r"^NL\d{9}B\d{2}$",
    "PL": r"^PL\d{10}$",
    "PT": r"^PT\d{9}$",
    "RO": r"^RO\d{2,10}$",
    "SE": r"^SE\d{12}$",
    "SI": r"^SI\d{8}$",
    "SK": r"^SK\d{10}$",
}


class TaxValidator:
    """
    Validate tax-related information.

    Checks VAT rates against country standards and validates VAT ID formats.
    """

    def validate(self, doc) -> ValidationResult:
        """
        Validate tax-related aspects of the document.

        Args:
            doc: CanonicalDocument to validate

        Returns:
            ValidationResult with any issues found
        """
        result = ValidationResult(is_valid=True)

        # Validate VAT IDs
        vat_result = self._validate_vat_ids(doc)
        result = result.merge(vat_result)

        # Validate tax rates against country
        rate_result = self._validate_tax_rates(doc)
        result = result.merge(rate_result)

        return result

    def _validate_vat_ids(self, doc) -> ValidationResult:
        """Validate VAT ID formats."""
        warnings = []

        # Check supplier VAT ID
        if doc.supplier.tax_id:
            if not self._is_valid_vat_format(doc.supplier.tax_id):
                warnings.append(
                    f"Supplier VAT ID '{doc.supplier.tax_id}' may have invalid format"
                )

        # Check customer VAT ID
        if doc.customer.tax_id:
            if not self._is_valid_vat_format(doc.customer.tax_id):
                warnings.append(
                    f"Customer VAT ID '{doc.customer.tax_id}' may have invalid format"
                )

        # Warnings don't fail validation
        return ValidationResult(is_valid=True, warnings=warnings)

    def _validate_tax_rates(self, doc) -> ValidationResult:
        """Validate tax rates against country standards."""
        warnings = []

        # Determine country from supplier
        country = doc.supplier.address.country

        if not country:
            return ValidationResult(is_valid=True)

        country = country.upper()
        valid_rates = COUNTRY_VAT_RATES.get(country, [])

        if not valid_rates:
            # Country not in our list, skip validation
            return ValidationResult(is_valid=True)

        # Check each tax rate used in the document
        used_rates = set()

        # From line items
        for item in doc.line_items:
            if item.tax_rate is not None:
                used_rates.add(item.tax_rate)

        # From tax breakdown
        for tax in doc.totals.tax_breakdown:
            used_rates.add(tax.rate)

        # Check if rates are valid for country
        for rate in used_rates:
            if rate not in valid_rates and rate != Decimal("0"):
                warnings.append(
                    f"Tax rate {rate}% is not a standard VAT rate for {country}. "
                    f"Standard rates: {', '.join(str(r) + '%' for r in valid_rates)}"
                )

        return ValidationResult(is_valid=True, warnings=warnings)

    def _is_valid_vat_format(self, vat_id: str) -> bool:
        """
        Check if VAT ID matches expected format for its country.

        Args:
            vat_id: VAT ID to validate

        Returns:
            True if format is valid or unknown country
        """
        # Clean the VAT ID
        vat_id = vat_id.upper().replace(" ", "").replace("-", "").replace(".", "")

        # Try to determine country from prefix
        for country_code, pattern in VAT_ID_PATTERNS.items():
            if vat_id.startswith(country_code) or (country_code == "GR" and vat_id.startswith("EL")):
                return bool(re.match(pattern, vat_id))

        # Unknown format, assume valid
        return True

    def get_valid_rates_for_country(self, country_code: str) -> list[Decimal]:
        """
        Get valid VAT rates for a country.

        Args:
            country_code: 2-letter country code

        Returns:
            List of valid VAT rates
        """
        return COUNTRY_VAT_RATES.get(country_code.upper(), [])
