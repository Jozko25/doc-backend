"""Re-validation prompt for correcting extraction errors."""

REVALIDATION_PROMPT = """You are reviewing a document extraction that failed mathematical validation. Your task is to correct the errors.

## Validation Errors Found:

{errors}

## Original Extracted Data:

```json
{extracted_json}
```

## Original Document Content:

{original_content}

---

## Instructions:

1) Use the totals printed on the document ("TOTAL", "TOTAL DUE", etc.) as the source of truth.
2) Recompute each line: expected_line_total = quantity * unit_price (+ tax). If the printed line total is visible, prefer that exact amount; adjust quantity (not price) when the total block demands it.
3) Fix common OCR errors:
   - 1 vs l/I, 0 vs O, 5 vs S, 8 vs B
   - Missing/extra line breaks that split a single value into two lines (e.g., "1\n4" should likely be "1").
4) Ensure:
   - Sum of line totals (net) = subtotal
   - subtotal + total_tax (+ rounding) = total_amount
   - amount_due matches the printed total due
5) Make the minimal changes needed to satisfy the math using numbers visible in the original content. Do not invent data; leave fields null if absent.
6) Return only the corrected JSON with the same structure.

Return ONLY the corrected JSON object, no additional text or explanation."""


def get_revalidation_prompt(
    errors: list[str],
    extracted_json: str,
    original_content: str,
) -> str:
    """
    Generate re-validation prompt.

    Args:
        errors: List of validation error messages
        extracted_json: The extracted JSON that failed validation
        original_content: Original document content for reference

    Returns:
        Complete prompt for LLM
    """
    errors_text = "\n".join(f"- {error}" for error in errors)

    return REVALIDATION_PROMPT.format(
        errors=errors_text,
        extracted_json=extracted_json,
        original_content=original_content,
    )
