from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any

from .config import ColumnType, Xml2RelError

_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_DOUBLE_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}


class ConversionError(Xml2RelError):
    def __init__(
        self,
        *,
        table: str,
        column: str,
        xpath: str,
        value: str | None,
        target_type: str,
        reason: str,
    ) -> None:
        self.table = table
        self.column = column
        self.xpath = xpath
        self.value = value
        self.target_type = target_type
        self.reason = reason
        super().__init__(
            f"conversion failed for table={table!r}, column={column!r}, "
            f"xpath={xpath!r}, value={value!r}, target_type={target_type}: {reason}"
        )


def convert_value(
    raw: str | None,
    target_type: ColumnType,
    *,
    table: str,
    column: str,
    xpath: str,
) -> Any:
    if target_type is ColumnType.VARCHAR:
        if raw is None or raw.strip() == "":
            return None
        return raw

    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None

    try:
        if target_type is ColumnType.INTEGER:
            return _convert_integer(text, -(2**31), 2**31 - 1)
        if target_type is ColumnType.BIGINT:
            return _convert_integer(text, -(2**63), 2**63 - 1)
        if target_type is ColumnType.DOUBLE:
            return _convert_double(text)
        if target_type is ColumnType.BOOLEAN:
            return _convert_boolean(text)
        if target_type is ColumnType.DATE:
            return _convert_date(text)
        if target_type is ColumnType.TIMESTAMP:
            return _convert_timestamp(text)
        if target_type is ColumnType.JSON:
            return _convert_json(text)
    except ConversionError:
        raise
    except (ValueError, TypeError, OverflowError, json.JSONDecodeError) as exc:
        raise ConversionError(
            table=table,
            column=column,
            xpath=xpath,
            value=raw,
            target_type=target_type.value,
            reason=str(exc),
        ) from exc

    raise ConversionError(
        table=table,
        column=column,
        xpath=xpath,
        value=raw,
        target_type=str(target_type),
        reason=f"unsupported target type {target_type!r}",
    )


def _fail(reason: str) -> None:
    raise ValueError(reason)


def _convert_integer(text: str, minimum: int, maximum: int) -> int:
    if not _INTEGER_RE.match(text):
        _fail(f"{text!r} is not a base-10 integer")
    value = int(text, 10)
    if value < minimum or value > maximum:
        _fail(f"{value} is outside the range {minimum}..{maximum}")
    return value


def _convert_double(text: str) -> float:
    if not _DOUBLE_RE.match(text):
        _fail(f"{text!r} is not a floating-point number")
    value = float(text)
    if not math.isfinite(value):
        _fail("non-finite doubles are not supported")
    return value


def _convert_boolean(text: str) -> bool:
    lowered = text.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    _fail(f"{text!r} is not a recognized boolean; expected true/false, 1/0, or yes/no")


def _convert_date(text: str) -> date:
    if not _DATE_RE.match(text):
        _fail(f"{text!r} is not an ISO-8601 date (YYYY-MM-DD)")
    return date.fromisoformat(text)


def _convert_timestamp(text: str) -> datetime:
    if not _TIMESTAMP_RE.match(text):
        _fail(f"{text!r} is not an ISO-8601 date-time")
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _convert_json(text: str) -> str:
    value = json.loads(text)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
