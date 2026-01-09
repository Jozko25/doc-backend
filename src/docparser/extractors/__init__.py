"""Document extractors for various file types."""

from .base import BaseExtractor, ExtractionResult
from .ocr import OCRExtractor
from .pdf import PDFExtractor
from .xml import XMLExtractor

# Lazy import for ExcelExtractor due to pandas compatibility issues
def __getattr__(name):
    if name == "ExcelExtractor":
        from .excel import ExcelExtractor
        return ExcelExtractor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BaseExtractor",
    "ExcelExtractor",
    "ExtractionResult",
    "OCRExtractor",
    "PDFExtractor",
    "XMLExtractor",
]
