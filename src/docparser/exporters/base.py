"""Base exporter interface."""

from abc import ABC, abstractmethod
from typing import Any

from ..core.models import CanonicalDocument


class BaseExporter(ABC):
    """Abstract base class for document exporters."""

    @abstractmethod
    def export(self, document: CanonicalDocument) -> Any:
        """
        Export canonical document to target format.

        Args:
            document: CanonicalDocument to export

        Returns:
            Exported content (format depends on implementation)
        """
        pass

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Return the name of the export format."""
        pass

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Return the file extension for the export format."""
        pass

    @property
    @abstractmethod
    def mime_type(self) -> str:
        """Return the MIME type for the export format."""
        pass
