"""Core, GUI-independent operations for PDFPad.

Nothing in this package imports Qt or touches the network. Every operation
accepts filesystem paths and returns plain data (paths, strings, PIL images)
so it can be tested headlessly and reused by the future GUI.
"""

from .errors import (
    EncryptedPdfError,
    OfficeUnavailableError,
    OperationCancelled,
    PdfOperationError,
    PdfPadError,
    RangeSpecError,
    UnsupportedFileError,
)
from .ranges import parse_ranges

__all__ = [
    "EncryptedPdfError",
    "OfficeUnavailableError",
    "OperationCancelled",
    "PdfOperationError",
    "PdfPadError",
    "RangeSpecError",
    "UnsupportedFileError",
    "parse_ranges",
]
