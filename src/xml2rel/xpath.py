from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from lxml import etree

from .config import ColumnConfig, ColumnStrategy


@dataclass(frozen=True)
class RawValue:
    value: str | None
    xpath_label: str


def is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def normalize_result(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, bool):
        return ["true" if result else "false"]
    if isinstance(result, str):
        return [str(result)]
    if isinstance(result, (int, float)):
        return [str(result)]
    if isinstance(result, list):
        values: list[str] = []
        for item in result:
            if isinstance(item, etree._Element):
                values.append("".join(item.itertext()))
            else:
                values.append(str(item))
        return values
    if isinstance(result, etree._Element):
        return ["".join(result.itertext())]
    return [str(result)]


def evaluate_expression(record: etree._Element, expression: str) -> list[str]:
    return normalize_result(record.xpath(expression))


def select_value(record: etree._Element, column: ColumnConfig) -> RawValue:
    expressions = column.xpath
    label = " | ".join(expressions)

    if column.strategy is ColumnStrategy.FIRST_NON_EMPTY:
        for expression in expressions:
            for value in evaluate_expression(record, expression):
                if not is_blank(value):
                    return RawValue(value=value, xpath_label=expression)
        return RawValue(value=None, xpath_label=label)

    if column.strategy is ColumnStrategy.FIRST:
        for expression in expressions:
            values = evaluate_expression(record, expression)
            if values:
                return RawValue(value=values[0], xpath_label=expression)
        return RawValue(value=None, xpath_label=label)

    if column.strategy is ColumnStrategy.CONCAT:
        values: list[str] = []
        for expression in expressions:
            values.extend(value for value in evaluate_expression(record, expression) if not is_blank(value))
        if not values:
            return RawValue(value=None, xpath_label=label)
        return RawValue(value="".join(values), xpath_label=label)

    if column.strategy is ColumnStrategy.COLLECT:
        values: list[str] = []
        for expression in expressions:
            values.extend(evaluate_expression(record, expression))
        if not values:
            return RawValue(value=None, xpath_label=label)
        return RawValue(
            value=json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            xpath_label=label,
        )

    raise ValueError(f"unsupported strategy: {column.strategy!r}")
