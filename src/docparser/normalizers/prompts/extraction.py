"""Extraction prompt for LLM."""

EXTRACTION_PROMPT = '''You are an expert document parser specializing in extracting structured data from invoices, receipts, and financial documents.

Your task is to extract information from the provided document content and return it as a structured JSON object.

## CRITICAL: Tax Handling - Two Common Styles

### Style 1: EU-style (tax per line)
- Each line item has its own tax amount
- line_total = (quantity × unit_price) + tax_amount
- subtotal = sum of all line_total values

### Style 2: US-style (tax at bottom)
- Line items show PRE-TAX amounts only
- Tax is calculated as a lump sum on the subtotal
- line_total = quantity × unit_price (NO tax included)
- tax_amount per line = 0 (or null)
- total_tax shown separately at bottom
- Often includes shipping as a separate charge

**How to detect:** If you see "Sales Tax: $X.XX" or "Tax (X%): $X.XX" at the bottom near TOTAL, it's US-style.

## CRITICAL: Line Items Extraction Rules

**ALWAYS extract ALL line items from the document.**

**Verify your extraction:**
1. Count the line items in the document
2. Make sure you extracted the same number
3. Check: subtotal = sum of all line_total values (for US-style invoices)
4. Check: total_due = subtotal + total_tax + shipping (if present)

**For US-style invoices:**
- line_total is the TOTAL column value (pre-tax)
- tax_amount per line should be 0 or null
- total_tax is the lump sum at the bottom
- shipping_amount is separate if present

**Common OCR table parsing issues:**
- OCR may split table rows across multiple text lines
- Numbers like "400.00" may appear as "4000" then "400.00" on separate lines
- The QUANTITY column typically has small integers (1, 2, 3...) not large numbers

## Important Guidelines:

1. **OCR Errors**: The text may contain OCR errors. Common issues:
   - 0 (zero) confused with O (letter)
   - 1 (one) confused with l (lowercase L) or I
   - Numbers from adjacent cells bleeding into wrong columns

2. **Dates**: Normalize to YYYY-MM-DD format.

3. **Currency**: Extract currency codes (EUR, USD, CZK, GBP, etc.). Use $ = USD, € = EUR, £ = GBP.

4. **Missing Data**: Use null for fields not present. Don't invent data.

5. **Shipping/Delivery**: If shipping cost is present, include it in totals.shipping_amount.

## Output JSON Schema:

Return a JSON object with these fields:
- document: type (invoice/credit_note/receipt), number, issue_date (YYYY-MM-DD), due_date, currency (3-letter), language (2-letter)
- supplier: name, tax_id, address (street, city, postal_code, country), contact (email, phone), bank (iban, bic)
- customer: name, tax_id, address (street, city, postal_code, country)
- line_items: array of objects with:
  - line_number, description, quantity, unit, unit_price
  - tax_rate (percentage, e.g., 8.5 for 8.5%), tax_amount (0 for US-style)
  - line_total (the TOTAL column value from the document)
- totals:
  - subtotal (sum of line_total values)
  - tax_breakdown: array of {rate, taxable_amount, tax_amount}
  - total_tax
  - shipping_amount (null if no shipping)
  - total_amount (subtotal + tax + shipping)
  - amount_due
  - currency
- payment: method, terms, reference
- notes: string or null

## Document Content:

'''


def get_extraction_prompt(content: str) -> str:
    """
    Generate extraction prompt with document content.

    Args:
        content: Document text content

    Returns:
        Complete prompt for LLM
    """
    return EXTRACTION_PROMPT + content + "\n\n---\n\nExtract the information and return ONLY the JSON object, no additional text or explanation."
