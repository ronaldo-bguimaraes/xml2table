from __future__ import annotations

import json

from lxml import etree

from xml2rel.config import ColumnConfig, ColumnStrategy, ColumnType
from xml2rel.xpath import select_value


def column(
    xpath: str | list[str],
    strategy: ColumnStrategy = ColumnStrategy.FIRST_NON_EMPTY,
    column_type: ColumnType = ColumnType.VARCHAR,
) -> ColumnConfig:
    expressions = (xpath,) if isinstance(xpath, str) else tuple(xpath)
    return ColumnConfig(
        name="value",
        xpath=expressions,
        strategy=strategy,
        type=column_type,
    )


def test_relative_expression_uses_record_not_document() -> None:
    record = etree.fromstring(
        "<Patient><Name>Alice</Name><Other><Name>Wrong</Name></Other></Patient>"
    )
    result = select_value(record, column("Name/text()"))
    assert result.value == "Alice"


def test_first_non_empty_falls_back() -> None:
    record = etree.fromstring(
        "<Patient><PersonalData><FullName>Bob Jones</FullName></PersonalData></Patient>"
    )
    result = select_value(
        record,
        column(["Name/text()", "PersonalData/FullName/text()"]),
    )
    assert result.value == "Bob Jones"


def test_first_non_empty_skips_blank_values() -> None:
    record = etree.fromstring("<Patient><Name>   </Name><Fallback>Carol</Fallback></Patient>")
    result = select_value(record, column(["Name/text()", "Fallback/text()"]))
    assert result.value == "Carol"


def test_first_uses_later_expression_when_first_has_no_match() -> None:
    record = etree.fromstring("<Patient><Fallback>Carol</Fallback></Patient>")
    result = select_value(
        record,
        column(["Name/text()", "Fallback/text()"], ColumnStrategy.FIRST),
    )
    assert result.value == "Carol"


def test_first_preserves_a_blank_first_value() -> None:
    record = etree.fromstring("<Patient><Name> </Name><Fallback>Carol</Fallback></Patient>")
    result = select_value(
        record,
        column(["Name/text()", "Fallback/text()"], ColumnStrategy.FIRST),
    )
    assert result.value == " "


def test_concat_joins_all_non_blank_matches_in_order() -> None:
    record = etree.fromstring("<Record><A>one</A><B>two</B><C>   </C></Record>")
    result = select_value(
        record,
        column(["A/text()", "B/text()", "C/text()"], ColumnStrategy.CONCAT),
    )
    assert result.value == "onetwo"


def test_concat_returns_none_when_nothing_matches() -> None:
    record = etree.fromstring("<Record><A/></Record>")
    result = select_value(record, column(["Missing/text()"], ColumnStrategy.CONCAT))
    assert result.value is None


def test_collect_returns_json_array() -> None:
    record = etree.fromstring("<Patient><Phone>1</Phone><Phone>2</Phone></Patient>")
    result = select_value(record, column("Phone/text()", ColumnStrategy.COLLECT))
    assert result.value is not None
    assert json.loads(result.value) == ["1", "2"]


def test_collect_returns_none_when_nothing_matches() -> None:
    record = etree.fromstring("<Patient/>")
    result = select_value(record, column("Phone/text()", ColumnStrategy.COLLECT))
    assert result.value is None


def test_first_non_empty_returns_none_when_all_blank() -> None:
    record = etree.fromstring("<Patient><Name> </Name></Patient>")
    result = select_value(record, column("Name/text()"))
    assert result.value is None
