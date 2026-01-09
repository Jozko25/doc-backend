"""Extraction prompt for LLM."""

EXTRACTION_PROMPT = '''You are an expert document parser specializing in extracting structured data from ALL types of payment documents.

## Supported Document Types:
- **Gas station receipts** (fuel purchases with liters/gallons)
- **Retail receipts** (store purchases)
- **Invoices** (B2B, services, products)
- **Utility bills** (electricity, gas, water, internet)
- **Restaurant bills** (food, tips)
- **Medical bills** (healthcare invoices)
- **Credit card statements**
- **Any other payment/financial document**

## CRITICAL: Understand the Document Structure First

Before extracting, identify:
1. **Document type**: Is it a receipt, invoice, bill, statement?
2. **Country/Region**: EU receipts show VAT differently than US sales tax
3. **Business type**: Gas stations, retail, services each have unique formats

## CRITICAL: Gas Station / Fuel Receipts

Gas station receipts have a SPECIFIC format:
- **Quantity is in LITERS or GALLONS** (large decimals like 59.22, not small integers)
- Format often: `[item code] [product name] [quantity] [unit] [unit_price] [tax%] [total]`
- Example: `3 03 OMV Diesel 59.2200 l 1.469 23% 86.99`
  - Item code: "3 03" (ignore this, NOT the quantity!)
  - Product: "OMV Diesel"
  - Quantity: 59.2200 liters
  - Unit price: 1.469 per liter
  - Tax rate: 23%
  - Line total: 86.99

**VERIFY**: quantity * unit_price should approximately equal line_total (within rounding)

## CRITICAL: Tax Handling Styles

### EU-style (VAT included, common in Europe)
- Receipts show: ZAKLAD (base/net) + DAN/DPH (VAT) = SPOLU/CELKOM (total)
- Tax breakdown shown at bottom: e.g., "DPH 23%: ZAKLAD 70.72 + DAN 16.27 = SPOLU 86.99"
- subtotal = taxable base (ZAKLAD)
- total_tax = DAN/DPH amount
- total_amount = CELKOM/SPOLU (the final amount)

### US-style (tax added at bottom)
- Line items are PRE-TAX
- Sales tax added as separate line at bottom
- total_amount = subtotal + sales_tax

## CRITICAL: Line Items vs Summary/Discount Rows

**ONLY PRODUCTS/SERVICES are line items!** Summary rows are NOT line items:
- Subtotal, Discount, Shipping, Tax, Total → These go in TOTALS section, NOT line_items
- "Discount (10%): $644.44" → Put in totals.discount_amount, NOT as a line item!
- NEVER create line items with negative quantities

**Product descriptions often have multiple lines:**
```
Smead Lockers, Industrial          6    $1,074.06    $6,444.36
Storage, Office Supplies, OFF-ST-6047
```
This is ONE line item:
- description: "Smead Lockers, Industrial - Storage, Office Supplies, OFF-ST-6047"
- quantity: 6
- unit_price: 1074.06
- line_total: 6444.36

**Summary section at bottom (NOT line items!):**
```
Subtotal:        $6,444.36   → totals.subtotal
Discount (10%):    $644.44   → totals.discount_amount
Shipping:           $94.20   → totals.shipping_amount
Total:           $5,894.12   → totals.total_amount
```

**CRITICAL RULES:**
1. Count actual products in the items table - usually 1-10 items, NOT 20+
2. Category codes like "OFF-ST-6047" or "Tables, Furniture" are part of the product description
3. If you see "Subtotal", "Discount", "Shipping", "Tax", "Total" - these are SUMMARY rows
4. The total_amount should match "Balance Due" or "Total" on the document (e.g., $5,894.12)
5. NEVER use discount values as unit prices for fake line items

## CRITICAL: Mathematical Verification

**ALWAYS verify your extraction makes sense:**
1. quantity * unit_price should be close to line_total (allow small rounding differences)
2. sum of line_totals should be close to subtotal OR total_amount
3. subtotal - discount + shipping + tax should equal total_amount
4. Look for the FINAL TOTAL on the document - this is the most reliable number

**If math does not work, you likely misread a field. Common errors:**
- Confusing item codes with quantities (codes like "3 03" are NOT quantities)
- Missing decimal points (59.22 vs 5922)
- Reading adjacent column values
- Treating discount rows as line items (NEVER do this!)

## Important Guidelines:

1. **OCR Errors**: Common issues:
   - 0/O confusion, 1/l/I confusion
   - Decimal separators: EU uses comma (1,469), US uses period (1.469)
   - Numbers bleeding across columns

2. **Dates**: Normalize to YYYY-MM-DD. Handle formats like "2025.12.05", "05.12.2025", "12/05/2025"

3. **Currency**: EUR, USD, GBP, CZK, etc.

4. **Missing Data**: Use null for fields not present. Do not invent data.

5. **Rounding**: Many receipts show rounding adjustments (Zaokruhlenie). Include in rounding_amount.

6. **Payment method**: Look for "Hotovost/Cash", "Karta/Card", etc.

## CRITICAL: Customer vs Location

**For RECEIPTS (gas stations, retail stores, restaurants):**
- There is usually NO CUSTOMER information
- Multiple addresses on a receipt are usually SUPPLIER locations (headquarters vs store location)
- Set customer fields to null unless there's clearly a "Bill To" or "Customer" section
- Example: "95187 Volkovce cast Olichov 48" on a gas receipt is the STATION LOCATION, not a customer

**For INVOICES:**
- There IS a customer (the person/company being billed)
- Look for "Bill To", "Customer", "Sold To", "Odberatel" sections

## Output JSON Schema:

Return a JSON object with these fields:
- document: type (invoice/credit_note/receipt), number, issue_date (YYYY-MM-DD), due_date, currency (3-letter), language (2-letter)
- supplier: name, tax_id, address (street, city, postal_code, country), contact (email, phone), bank (iban, bic)
- customer: name, tax_id, address - SET TO NULL FOR RECEIPTS unless explicitly labeled as customer/buyer
- line_items: array of objects with:
  - line_number, description, quantity (DECIMAL - can be large for fuel!), unit (l, gal, pcs, kg, etc.)
  - unit_price (price per unit), tax_rate (percentage), tax_amount
  - line_total (the amount shown for this line on the document)
- totals:
  - subtotal (net/base amount before tax, or sum of lines if tax-inclusive)
  - discount_amount (total discount applied - from "Discount X%" rows, NOT a line item!)
  - tax_breakdown: array of {rate, taxable_amount, tax_amount}
  - total_tax (total VAT/sales tax)
  - shipping_amount (null if none)
  - total_amount (the FINAL total shown on document - Balance Due, Total, etc.)
  - amount_due (what customer must pay - same as total for receipts)
  - rounding_amount (if shown)
  - currency
- payment: method (cash/card/transfer), terms, reference
- notes: any additional info

## FINAL CHECK before returning JSON:
1. Does total_amount match "Balance Due" or "Total" on the document? (e.g., $2,921.43)
2. Does quantity make sense? (usually 1-100, NOT decimals like 0.016 or 0.399)
3. Does quantity * unit_price ≈ line_total? If not, fix quantity!
4. Are there any negative quantities? If yes, REMOVE that line item - it's probably a discount row
5. Is discount_amount filled for any "Discount (X%)" rows?

## Document Content:

'''


VALIDATION_PROMPT = '''You are a document validation expert. Review the extracted data and verify it makes mathematical and logical sense.

## Your Task:
1. Check if the extracted numbers are mathematically consistent
2. Identify any obvious extraction errors
3. Return corrected data if needed

## CRITICAL: Check for These Common Mistakes

### Discounts Wrongly as Line Items:
- If you see a line item with NEGATIVE quantity - THIS IS WRONG!
- "Discount (10%)" should be in totals.discount_amount, NOT as a line item
- Product categories/SKUs (like "OFF-ST-6047") are part of product description, not separate items

### Wrong Totals:
- total_amount should match the "Balance Due" or "Total" on the document
- If total_amount is tiny (like 10 or 40) but the document shows thousands - FIX IT!
- Formula: subtotal - discount_amount + shipping_amount + total_tax = total_amount

### Gas Station Receipts:
- Quantity should be liters/gallons (large decimals like 59.22), NOT small integers
- quantity * unit_price should approximately equal line_total

### All Documents:
- sum of line_totals should match subtotal
- Usually only 1-10 line items, not 20+ (summary rows are not items!)
- Look for the FINAL TOTAL shown on document - use that value

## Original OCR Text:
{ocr_text}

## Current Extracted Data:
{extracted_json}

## Instructions:
1. Compare the extracted data against the OCR text
2. Check if the math adds up
3. If you find errors, return the CORRECTED JSON
4. If everything looks correct, return the same JSON unchanged

Return ONLY the JSON object (corrected or unchanged), no explanation.
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


def get_validation_prompt(ocr_text: str, extracted_json: str) -> str:
    """
    Generate validation prompt to verify extraction.

    Args:
        ocr_text: Original OCR text
        extracted_json: Extracted JSON as string

    Returns:
        Complete prompt for validation
    """
    return VALIDATION_PROMPT.format(ocr_text=ocr_text, extracted_json=extracted_json)
