"""XML document extractor."""

import io
from typing import Any
from xml.etree import ElementTree as ET

from lxml import etree

from ..utils.file_handlers import FileType
from .base import BaseExtractor, ExtractionResult


class XMLExtractor(BaseExtractor):
    """Extract structured data from XML documents."""

    SUPPORTED_TYPES = {FileType.XML}

    async def extract(self, content: bytes, filename: str | None = None) -> ExtractionResult:
        """
        Extract structured data from XML file.

        Args:
            content: XML file bytes
            filename: Original filename (unused)

        Returns:
            ExtractionResult with structured data and text representation
        """
        warnings = []

        try:
            # Parse XML using lxml for better namespace handling
            root = etree.fromstring(content)

            # Convert to dict
            structured_data = self._element_to_dict(root)

            # Create text representation
            text_repr = self._to_text(root)

            # Detect if this might be a UBL or other invoice format
            root_tag = etree.QName(root.tag).localname if root.tag else "unknown"
            namespaces = dict(root.nsmap)

            structured_data["_metadata"] = {
                "root_element": root_tag,
                "namespaces": {k or "default": v for k, v in namespaces.items()},
            }

            return ExtractionResult(
                text=text_repr,
                structured_data=structured_data,
                confidence=1.0,
                warnings=warnings,
                source_type="xml",
            )

        except etree.XMLSyntaxError as e:
            return ExtractionResult(
                text=None,
                warnings=[f"XML parsing error: {str(e)}"],
                source_type="xml_error",
            )
        except Exception as e:
            return ExtractionResult(
                text=None,
                warnings=[f"XML extraction error: {str(e)}"],
                source_type="xml_error",
            )

    def _element_to_dict(self, element: etree._Element) -> dict[str, Any]:
        """
        Recursively convert XML element to dictionary.

        Args:
            element: lxml Element

        Returns:
            Dictionary representation
        """
        result: dict[str, Any] = {}

        # Get tag name without namespace
        tag = etree.QName(element.tag).localname if element.tag else "unknown"

        # Add attributes
        if element.attrib:
            result["@attributes"] = dict(element.attrib)

        # Add text content
        if element.text and element.text.strip():
            result["@text"] = element.text.strip()

        # Process children
        children: dict[str, list[Any]] = {}
        for child in element:
            child_tag = etree.QName(child.tag).localname if child.tag else "unknown"
            child_dict = self._element_to_dict(child)

            if child_tag in children:
                children[child_tag].append(child_dict)
            else:
                children[child_tag] = [child_dict]

        # Flatten single-item lists
        for key, value in children.items():
            if len(value) == 1:
                result[key] = value[0]
            else:
                result[key] = value

        return {tag: result} if result else {tag: element.text}

    def _to_text(self, root: etree._Element, indent: int = 0) -> str:
        """
        Convert XML to readable text representation.

        Args:
            root: Root element
            indent: Current indentation level

        Returns:
            Text representation
        """
        lines = []
        prefix = "  " * indent

        tag = etree.QName(root.tag).localname if root.tag else "unknown"

        # Element with text content
        if root.text and root.text.strip():
            lines.append(f"{prefix}{tag}: {root.text.strip()}")
        elif len(root) == 0:
            lines.append(f"{prefix}{tag}: (empty)")
        else:
            lines.append(f"{prefix}{tag}:")

        # Process children
        for child in root:
            lines.append(self._to_text(child, indent + 1))

        return "\n".join(lines)

    def supports_file_type(self, file_type: str) -> bool:
        """Check if this extractor supports the given file type."""
        try:
            ft = FileType(file_type)
            return ft in self.SUPPORTED_TYPES
        except ValueError:
            return False
