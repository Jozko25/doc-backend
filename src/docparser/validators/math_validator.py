"""Mathematical validation for document totals."""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ValidationResult:
    """Result of validation check."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge two validation results."""
        return ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


class MathValidator:
    """
    Validate mathematical correctness of document totals.

    Supports two invoice styles:
    - EU-style: Tax included per line item, line_total = net + tax
    - US-style: Tax as lump sum at bottom, line_total = net (pre-tax)

    All validation is done in Python without AI - this ensures accuracy.
    """

    # Absolute tolerance for rounding (2 cents)
    ABSOLUTE_TOLERANCE = Decimal("0.02")

    # Relative tolerance for larger amounts (1%)
    RELATIVE_TOLERANCE = 0.01

    def validate(self, doc) -> ValidationResult:
        """
        Validate all mathematical aspects of the document.

        Args:
            doc: CanonicalDocument to validate

        Returns:
            ValidationResult with any errors found
        """
        result = ValidationResult(is_valid=True)

        # Detect invoice style based on line item tax amounts
        is_us_style = self._is_us_style_invoice(doc)

        # Validate line items (different logic per style)
        line_result = self._validate_line_items(doc, is_us_style)
        result = result.merge(line_result)

        # Validate subtotal
        subtotal_result = self._validate_subtotal(doc, is_us_style)
        result = result.merge(subtotal_result)

        # Validate tax calculations (only meaningful for US-style with lump sum)
        if is_us_style:
            tax_result = self._validate_us_style_tax(doc)
        else:
            tax_result = self._validate_eu_style_tax(doc)
        result = result.merge(tax_result)

        # Validate grand total
        total_result = self._validate_grand_total(doc, is_us_style)
        result = result.merge(total_result)

        return result

    def _is_us_style_invoice(self, doc) -> bool:
        """
        Detect if this is a US-style invoice (tax at bottom, not per line).

        US-style indicators:
        - Line items have tax_amount = 0 or None
        - total_tax > 0 as a lump sum
        - Often has shipping
        """
        if not doc.line_items:
            return False

        # Check if all line items have zero/null tax
        line_taxes = [item.tax_amount for item in doc.line_items]
        all_zero_tax = all(t == Decimal("0") or t is None for t in line_taxes)

        # If line taxes are zero but total_tax > 0, it's US-style
        if all_zero_tax and doc.totals.total_tax > Decimal("0"):
            return True

        # Also check if sum of line totals equals subtotal (pre-tax)
        line_sum = sum(item.line_total for item in doc.line_items)
        if self._is_close(line_sum, doc.totals.subtotal):
            return True

        return False

    def _validate_line_items(self, doc, is_us_style: bool) -> ValidationResult:
        """Validate each line item's calculations."""
        errors = []

        for item in doc.line_items:
            # Calculate expected net amount (quantity × unit price)
            expected_net = item.quantity * item.unit_price

            # Apply discount if present
            if item.discount_percent:
                discount = expected_net * (item.discount_percent / Decimal("100"))
                expected_net -= discount
            elif item.discount_amount:
                expected_net -= item.discount_amount

            if is_us_style:
                # US-style: line_total should equal net (pre-tax)
                if not self._is_close(item.line_total, expected_net):
                    errors.append(
                        f"Line {item.line_number}: Total {item.line_total} doesn't match "
                        f"expected {expected_net:.2f} (qty {item.quantity} × price {item.unit_price})"
                    )
            else:
                # EU-style: line_total = net + tax
                if item.tax_rate is not None:
                    expected_tax = expected_net * (item.tax_rate / Decimal("100"))
                else:
                    expected_tax = Decimal("0")

                expected_total = expected_net + expected_tax

                # Check tax amount
                if item.tax_rate is not None and not self._is_close(item.tax_amount, expected_tax):
                    errors.append(
                        f"Line {item.line_number}: Tax amount {item.tax_amount} doesn't match "
                        f"expected {expected_tax:.2f} ({item.tax_rate}% of {expected_net:.2f})"
                    )

                # Check line total
                if not self._is_close(item.line_total, expected_total):
                    errors.append(
                        f"Line {item.line_number}: Total {item.line_total} doesn't match "
                        f"expected {expected_total:.2f} (net {expected_net:.2f} + tax {expected_tax:.2f})"
                    )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _validate_subtotal(self, doc, is_us_style: bool) -> ValidationResult:
        """Validate that subtotal matches sum of line items."""
        errors = []

        if not doc.line_items:
            return ValidationResult(is_valid=True)

        if is_us_style:
            # US-style: subtotal = sum of line_total (which are pre-tax)
            calculated_subtotal = sum(item.line_total for item in doc.line_items)
        else:
            # EU-style: subtotal = sum of (line_total - tax_amount)
            calculated_subtotal = sum(
                item.line_total - item.tax_amount for item in doc.line_items
            )

        if not self._is_close(doc.totals.subtotal, calculated_subtotal):
            errors.append(
                f"Subtotal mismatch: Document shows {doc.totals.subtotal}, "
                f"but sum of line items is {calculated_subtotal:.2f}"
            )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _validate_us_style_tax(self, doc) -> ValidationResult:
        """Validate US-style tax (lump sum at bottom)."""
        errors = []
        warnings = []

        # Check tax breakdown if present
        for tax in doc.totals.tax_breakdown:
            expected_tax = tax.taxable_amount * (tax.rate / Decimal("100"))

            if not self._is_close(tax.tax_amount, expected_tax):
                errors.append(
                    f"Tax breakdown error: {tax.rate}% of {tax.taxable_amount} should be "
                    f"{expected_tax:.2f}, but document shows {tax.tax_amount}"
                )

        # Check total tax matches breakdown sum
        if doc.totals.tax_breakdown:
            breakdown_sum = sum(tax.tax_amount for tax in doc.totals.tax_breakdown)
            if not self._is_close(doc.totals.total_tax, breakdown_sum):
                errors.append(
                    f"Total tax {doc.totals.total_tax} doesn't match sum of "
                    f"tax breakdown {breakdown_sum:.2f}"
                )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _validate_eu_style_tax(self, doc) -> ValidationResult:
        """Validate EU-style tax (per line item)."""
        errors = []
        warnings = []

        # Check tax breakdown
        for tax in doc.totals.tax_breakdown:
            expected_tax = tax.taxable_amount * (tax.rate / Decimal("100"))

            if not self._is_close(tax.tax_amount, expected_tax):
                errors.append(
                    f"Tax breakdown error: {tax.rate}% of {tax.taxable_amount} should be "
                    f"{expected_tax:.2f}, but document shows {tax.tax_amount}"
                )

        # Check total tax matches sum from line items
        line_tax_sum = sum(item.tax_amount for item in doc.line_items)
        if not self._is_close(doc.totals.total_tax, line_tax_sum):
            warnings.append(
                f"Total tax {doc.totals.total_tax} differs from sum of "
                f"line item taxes {line_tax_sum:.2f}"
            )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _validate_grand_total(self, doc, is_us_style: bool) -> ValidationResult:
        """Validate grand total = subtotal + tax + shipping."""
        errors = []

        expected_total = doc.totals.subtotal + doc.totals.total_tax

        # Add shipping if present
        if doc.totals.shipping_amount:
            expected_total += doc.totals.shipping_amount

        # Account for rounding adjustment
        if doc.totals.rounding_amount:
            expected_total += doc.totals.rounding_amount

        # Check total_amount
        if not self._is_close(doc.totals.total_amount, expected_total):
            shipping_str = f" + shipping ({doc.totals.shipping_amount})" if doc.totals.shipping_amount else ""
            errors.append(
                f"Grand total mismatch: Document shows {doc.totals.total_amount}, "
                f"but subtotal ({doc.totals.subtotal}) + tax ({doc.totals.total_tax}){shipping_str} = {expected_total:.2f}"
            )

        # Validate amount_due if present
        if doc.totals.amount_due is not None:
            # amount_due should equal total_amount (or total_amount minus prepaid)
            expected_due = doc.totals.total_amount
            if doc.totals.prepaid_amount:
                expected_due -= doc.totals.prepaid_amount

            # For US-style with shipping, amount_due often equals total_amount
            # Allow amount_due to match either total_amount or expected_total
            if not self._is_close(doc.totals.amount_due, expected_due):
                if not self._is_close(doc.totals.amount_due, expected_total):
                    errors.append(
                        f"Amount due {doc.totals.amount_due} doesn't match "
                        f"expected {expected_due:.2f}"
                    )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _is_close(self, a: Decimal, b: Decimal) -> bool:
        """
        Check if two decimal values are close enough.

        Uses both relative and absolute tolerance.
        """
        diff = abs(a - b)

        # Check absolute tolerance first (for small amounts)
        if diff <= self.ABSOLUTE_TOLERANCE:
            return True

        # Check relative tolerance
        max_val = max(abs(a), abs(b))
        if max_val > 0:
            relative_diff = diff / max_val
            return float(relative_diff) <= self.RELATIVE_TOLERANCE

        return True
