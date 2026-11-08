"""User-facing error types shared by the core operations."""

from __future__ import annotations


class PdfPadError(Exception):
    """Base class for errors that should be shown to the user as-is."""


class RangeSpecError(PdfPadError, ValueError):
    """A page selection or page index is invalid."""


class PdfOperationError(PdfPadError):
    """A PDF could not be read, written, or manipulated."""


class EncryptedPdfError(PdfOperationError):
    """A PDF is encrypted and needs a (correct) password."""


class OperationCancelled(PdfPadError):
    """The user cancelled a long-running operation."""


class UnsupportedFileError(PdfPadError):
    """The input file is missing or is not a supported format."""


class OfficeUnavailableError(PdfPadError):
    """The optional LibreOffice add-on is not installed."""
