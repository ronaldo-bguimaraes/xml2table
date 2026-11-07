from __future__ import annotations

from pathlib import Path

import pytest

from xml2rel.buffers import TableBuffer
from xml2rel.config import ColumnConfig, ColumnStrategy, ColumnType, TableConfig
from xml2rel.parser import ExtractionError, StreamingXMLParser
from xml2rel.source_path import SourcePathMatcher
from xml2rel.xpath import RawValue


def make_column(
    name: str,
    xpath: str | list[str],
    strategy: ColumnStrategy = ColumnStrategy.FIRST_NON_EMPTY,
) -> ColumnConfig:
    expressions = (xpath,) if isinstance(xpath, str) else tuple(xpath)
    return ColumnConfig(name=name, xpath=expressions, strategy=strategy, type=ColumnType.VARCHAR)


def make_table(name: str, source: str, columns: list[ColumnConfig]) -> TableConfig:
    return TableConfig(
        name=name,
        source=source,
        columns={column.name: column for column in columns},
        matcher=SourcePathMatcher(source),
    )


def test_streams_nested_records_and_parent_access(tmp_path: Path) -> None:
    xml_path = tmp_path / "patients.xml"
    xml_path.write_text(
        """
        <Clinic>
          <Patient id="1">
            <Name>Alice</Name>
            <Phone>1</Phone>
            <Phone>2</Phone>
            <Appointment id="10"><Date>2026-01-01</Date></Appointment>
            <Appointment id="11"><Date>2026-02-01</Date></Appointment>
          </Patient>
          <Patient id="2">
            <Name>Bob</Name>
            <Appointment id="12"><Date>2026-03-01</Date></Appointment>
          </Patient>
        </Clinic>
        """,
        encoding="utf-8",
    )

    patients = make_table(
        "patients",
        "//Patient",
        [
            make_column("id", "@id"),
            make_column("name", "Name/text()"),
            make_column("phones", "Phone/text()", ColumnStrategy.COLLECT),
        ],
    )
    appointments = make_table(
        "appointments",
        "//Patient/Appointment",
        [
            make_column("id", "@id"),
            make_column("patient_id", "../@id"),
            make_column("date", "Date/text()"),
        ],
    )

    rows: list[tuple[str, dict[str, RawValue]]] = []
    parser = StreamingXMLParser(
        {"patients": patients, "appointments": appointments},
        lambda table, values: rows.append((table, values)),
    )
    parser.parse(xml_path)

    appointment_rows = [values for table, values in rows if table == "appointments"]
    patient_rows = [values for table, values in rows if table == "patients"]

    assert [row["id"].value for row in appointment_rows] == ["10", "11", "12"]
    assert [row["patient_id"].value for row in appointment_rows] == ["1", "1", "2"]
    assert [row["id"].value for row in patient_rows] == ["1", "2"]
    assert [row["name"].value for row in patient_rows] == ["Alice", "Bob"]
    assert patient_rows[0]["phones"].value == '["1","2"]'


def test_source_attribute_predicate(tmp_path: Path) -> None:
    xml_path = tmp_path / "patients.xml"
    xml_path.write_text(
        '<Clinic><Patient id="1"><Name>Alice</Name></Patient>'
        '<Patient id="2"><Name>Bob</Name></Patient></Clinic>',
        encoding="utf-8",
    )
    table = make_table("patients", "//Patient[@id='2']", [make_column("name", "Name/text()")])
    rows: list[str | None] = []

    StreamingXMLParser({"patients": table}, lambda _table, values: rows.append(values["name"].value)).parse(xml_path)

    assert rows == ["Bob"]


def test_zero_match_table_is_not_an_error(tmp_path: Path) -> None:
    xml_path = tmp_path / "empty.xml"
    xml_path.write_text("<Root><Other/></Root>", encoding="utf-8")
    table = make_table("records", "//Record", [make_column("id", "@id")])
    rows: list[dict[str, RawValue]] = []

    StreamingXMLParser({"records": table}, lambda _table, values: rows.append(values)).parse(xml_path)

    assert rows == []


def test_missing_file_raises_extraction_error(tmp_path: Path) -> None:
    table = make_table("records", "//Record", [make_column("id", "@id")])
    parser = StreamingXMLParser({"records": table}, lambda _table, _values: None)

    with pytest.raises(ExtractionError) as captured:
        parser.parse(tmp_path / "missing.xml")

    assert "missing.xml" in str(captured.value)


def test_malformed_xml_raises_extraction_error(tmp_path: Path) -> None:
    xml_path = tmp_path / "broken.xml"
    xml_path.write_text("<Root><Record></Root>", encoding="utf-8")
    table = make_table("records", "//Record", [make_column("id", "@id")])
    parser = StreamingXMLParser({"records": table}, lambda _table, _values: None)

    with pytest.raises(ExtractionError) as captured:
        parser.parse(xml_path)

    assert "malformed XML" in str(captured.value)


def test_frame_stack_stays_shallow_for_many_records(tmp_path: Path) -> None:
    xml_path = tmp_path / "many.xml"
    with xml_path.open("w", encoding="utf-8") as handle:
        handle.write("<Records>")
        for index in range(1000):
            handle.write(f'<Record id="{index}"><Value>v</Value></Record>')
        handle.write("</Records>")

    table = make_table("records", "//Record", [make_column("id", "@id")])
    count = 0

    def callback(_table: str, _values: dict[str, RawValue]) -> None:
        nonlocal count
        count += 1

    parser = StreamingXMLParser({"records": table}, callback)
    parser.parse(xml_path)

    assert count == 1000
    assert parser.max_stack_depth <= 3


def test_buffers_are_independent() -> None:
    table_a = make_table("a", "//A", [make_column("id", "@id")])
    table_b = make_table("b", "//B", [make_column("id", "@id")])
    buffer_a = TableBuffer(table=table_a, batch_size=2)
    buffer_b = TableBuffer(table=table_b, batch_size=2)

    buffer_a.append(("1",))
    buffer_a.append(("2",))
    buffer_b.append(("1",))

    assert buffer_a.should_flush() is True
    assert buffer_b.should_flush() is False
    batch = buffer_a.take_batch()
    assert batch == [("1",), ("2",)]
    assert buffer_a.batches_written == 1
    assert buffer_b.rows == [("1",)]


def test_source_path_rejects_positional_predicate() -> None:
    from xml2rel.source_path import SourcePathError

    with pytest.raises(SourcePathError):
        SourcePathMatcher("//Patient[1]")
