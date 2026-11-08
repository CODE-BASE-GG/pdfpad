from __future__ import annotations

import pytest

from core.errors import RangeSpecError
from core.ranges import parse_ranges, validate_indices


@pytest.mark.parametrize(
    ("spec", "total", "expected"),
    [
        ("1", 10, [0]),
        ("1-3", 10, [0, 1, 2]),
        ("3-", 5, [2, 3, 4]),
        ("-3", 5, [0, 1, 2]),
        ("1,3,5", 5, [0, 2, 4]),
        ("1 3 5", 5, [0, 2, 4]),
        ("1 - 3", 5, [0, 1, 2]),
        ("3,1-2", 5, [2, 0, 1]),
        ("2,2,1", 5, [1, 0]),
        (" 1 , 2 - 3 ", 5, [0, 1, 2]),
        ("5-5", 5, [4]),
        ("1,", 3, [0]),
        ("1,,2", 3, [0, 1]),
        ("1-2,2-3", 3, [0, 1, 2]),
        ("3-,1", 4, [2, 3, 0]),
    ],
)
def test_parse_ranges_valid(spec, total, expected):
    assert parse_ranges(spec, total) == expected


@pytest.mark.parametrize(
    ("spec", "total"),
    [
        ("", 5),
        ("   ", 5),
        (",", 5),
        ("0", 5),
        ("0-3", 5),
        ("1-0", 5),
        ("6", 5),
        ("4-6", 5),
        ("5-2", 5),
        ("3-", 2),
        ("3-", 0),
        ("-3", 0),
        ("abc", 5),
        ("1;2", 5),
        ("1.5", 5),
        ("1-2-3", 5),
        ("1 2 x", 5),
    ],
)
def test_parse_ranges_invalid(spec, total):
    with pytest.raises(RangeSpecError):
        parse_ranges(spec, total)


def test_parse_ranges_type_errors():
    with pytest.raises(TypeError):
        parse_ranges(123, 5)
    with pytest.raises(TypeError):
        parse_ranges("1", "5")
    with pytest.raises(TypeError):
        parse_ranges("1", True)


def test_parse_ranges_negative_total():
    with pytest.raises(ValueError):
        parse_ranges("1", -1)


def test_parse_ranges_zero_total_with_empty_spec():
    with pytest.raises(RangeSpecError):
        parse_ranges("", 0)


def test_validate_indices_preserves_order_and_duplicates():
    assert validate_indices([2, 0, 2], 3) == [2, 0, 2]


def test_validate_indices_accepts_generator():
    assert validate_indices((index for index in (1, 0)), 2) == [1, 0]


@pytest.mark.parametrize("indices", [[], [3], [-1], [0, 3]])
def test_validate_indices_invalid_values(indices):
    with pytest.raises(RangeSpecError):
        validate_indices(indices, 3)


def test_validate_indices_type_errors():
    with pytest.raises(TypeError):
        validate_indices(0, 3)
    with pytest.raises(TypeError):
        validate_indices(["0"], 3)
    with pytest.raises(TypeError):
        validate_indices([True], 3)
