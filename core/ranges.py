"""Page-selection parsing and index validation.

The user-facing grammar is 1-based and inclusive::

    1           page 1
    1-3         pages 1, 2 and 3
    3-          page 3 through the last page
    -3          pages 1 through 3
    1,4-6,9     comma or whitespace separated items

Duplicates are removed while preserving the order in which pages were first
selected. Reversed ranges (``5-2``), zero/negative page numbers, and pages
beyond the document are rejected with :class:`RangeSpecError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .errors import RangeSpecError

# A range with both ends, an open start ("-3"), or a single page. Order matters:
# the range alternative must be tried before the single-number one.
_TOKEN_RE = re.compile(r"\d+\s*-\s*\d*|-\s*\d+|\d+")
_GAP_CHARS = frozenset(" \t\r\n,")


def parse_ranges(spec: str, total: int) -> list[int]:
    """Parse a 1-based page selection into 0-based page indices.

    Args:
        spec: Page selection such as ``"1-3,7"``.
        total: Number of pages in the document.

    Returns:
        Page indices in selection order, without duplicates.

    Raises:
        TypeError: If *spec* is not a string or *total* is not an int.
        ValueError: If *total* is negative.
        RangeSpecError: If the selection is empty, malformed, reversed, or
            refers to pages outside ``1..total``.
    """
    if isinstance(total, bool) or not isinstance(total, int):
        raise TypeError("total must be an int")
    if total < 0:
        raise ValueError("total must be >= 0")
    if not isinstance(spec, str):
        raise TypeError("spec must be a string")

    text = spec.strip()
    if not text:
        raise RangeSpecError("Page selection is empty.")

    tokens: list[str] = []
    position = 0
    for match in _TOKEN_RE.finditer(text):
        gap = text[position : match.start()]
        if set(gap) - _GAP_CHARS:
            raise RangeSpecError(
                f"Unexpected text {gap.strip()!r} in page selection."
            )
        if tokens and not gap:
            raise RangeSpecError(
                "Page selections must be separated by a comma or whitespace."
            )
        tokens.append(match.group(0))
        position = match.end()

    tail = text[position:]
    if set(tail) - _GAP_CHARS:
        raise RangeSpecError(
            f"Unexpected text {tail.strip()!r} in page selection."
        )
    if not tokens:
        raise RangeSpecError("Page selection is empty.")

    selected: list[int] = []
    seen: set[int] = set()
    for token in tokens:
        for index in _expand_token(token, total):
            if index not in seen:
                seen.add(index)
                selected.append(index)
    return selected


def _expand_token(token: str, total: int) -> range:
    """Expand one token into a range of 0-based indices."""
    compact = "".join(token.split())

    if compact.startswith("-"):
        start, end = 1, int(compact[1:])
    elif compact.endswith("-"):
        start, end = int(compact[:-1]), total
        if start > total:
            raise RangeSpecError(
                f"Page {start} is out of range; the document has "
                f"{total} page(s)."
            )
    elif "-" in compact:
        left, right = compact.split("-", 1)
        start, end = int(left), int(right)
    else:
        start = end = int(compact)

    if start < 1 or end < 1:
        raise RangeSpecError("Page numbers start at 1.")
    if start > end:
        raise RangeSpecError(
            f"Reversed page range {token.strip()!r}; "
            f"use {end}-{start} instead."
        )
    if end > total:
        raise RangeSpecError(
            f"Page {end} is out of range; the document has {total} page(s)."
        )
    return range(start - 1, end)


def validate_indices(indices: Iterable[int], total: int) -> list[int]:
    """Validate a sequence of 0-based page indices against *total* pages.

    Unlike :func:`parse_ranges`, this preserves duplicates and order exactly as
    given; it only rejects empty selections, non-integers, and out-of-range
    values. Used by the core operations so programmatic callers get the same
    clear errors as GUI users.
    """
    if isinstance(indices, bool) or not isinstance(indices, Iterable):
        raise TypeError("indices must be an iterable of page indices")
    result = list(indices)
    if not result:
        raise RangeSpecError("No pages selected.")
    for index in result:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("page indices must be integers")
        if index < 0 or index >= total:
            raise RangeSpecError(
                f"Page {index + 1} is out of range; the document has "
                f"{total} page(s)."
            )
    return result
