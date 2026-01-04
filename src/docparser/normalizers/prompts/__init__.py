"""LLM prompts for extraction and validation."""

from .extraction import EXTRACTION_PROMPT, get_extraction_prompt
from .validation import REVALIDATION_PROMPT, get_revalidation_prompt

__all__ = [
    "EXTRACTION_PROMPT",
    "REVALIDATION_PROMPT",
    "get_extraction_prompt",
    "get_revalidation_prompt",
]
