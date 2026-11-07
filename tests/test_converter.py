from __future__ import annotations

from datetime import date, datetime

import pytest

from xml2rel.config import ColumnType
from xml2rel.converter import ConversionError, convert_value


def convert(raw: str | None, column_type: ColumnType):
    return convert_value(
        raw,
        column_type,
        table="records",
        column="value",
        xpath="Value/text()",
    )


@pytest.mark.parametrize(
    ("raw", "column_type", "expected"),
    [
        (" hello ", ColumnType.VARCHAR, " hello "),
        ("42", ColumnType.INTEGER, 42),
        ("2147483647", ColumnType.INTEGER, 2147483647),
        ("9223372036854775807", ColumnType.BIGINT, 9223372036854775807),
        ("3.14", ColumnType.DOUBLE, 3.14),
        ("1e3", ColumnType.DOUBLE, 1000.0),
        ("true", ColumnType.BOOLEAN, True),
        ("FALSE", ColumnType.BOOLEAN, False),
        ("1", ColumnType.BOOLEAN, True),
        ("no", ColumnType.BOOLEAN, False),
        ("2026-11-07", ColumnType.DATE, date(2026, 11, 7)),
        (
            "2026-11-07T12:30:00Z",
            ColumnType.TIMESTAMP,
            datetime(2026, 11, 7, 12, 30),
        ),
        (
            "2026-11-07T12:30:00-03:00",
            ColumnType.TIMESTAMP,
            datetime(2026, 11, 7, 15, 30),
        ),
        ('{"a": 1}', ColumnType.JSON, '{"a":1}'),
        ("[1, 2]", ColumnType.JSON, "[1,2]"),
    ],
)
def test_valid_conversions(raw: str, column_type: ColumnType, expected) -> None:
    assert convert(raw, column_type) == expected


@pytest.mark.parametrize("column_type", list(ColumnType))
@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_values_become_none(raw: str | None, column_type: ColumnType) -> None:
    assert convert(raw, column_type) is None


@pytest.mark.parametrize(
    ("raw", "column_type"),
    [
        ("12.5", ColumnType.INTEGER),
        ("2147483648", ColumnType.INTEGER),
        ("1_000", ColumnType.INTEGER),
        ("9223372036854775808", ColumnType.BIGINT),
        ("NaN", ColumnType.DOUBLE),
        ("inf", ColumnType.DOUBLE),
        ("maybe", ColumnType.BOOLEAN),
        ("2026/11/07", ColumnType.DATE),
        ("2026-11-07", ColumnType.TIMESTAMP),
        ("{bad json", ColumnType.JSON),
    ],
)
def test_invalid_conversions_raise_with_context(raw: str, column_type: ColumnType) -> None:
    with pytest.raises(ConversionError) as captured:
        convert(raw, column_type)

    error = captured.value
    assert error.table == "records"
    assert error.column == "value"
    assert error.xpath == "Value/text()"
    assert error.value == raw
    assert error.target_type == column_type.value
    assert error.reason
