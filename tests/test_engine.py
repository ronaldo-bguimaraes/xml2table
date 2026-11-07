from __future__ import annotations

import json
import tracemalloc
from pathlib import Path

import duckdb
import pytest

from xml2rel import (
    BackendError,
    ConfigError,
    ConversionError,
    XMLExtractor,
)
from xml2rel.cli import main

REPO_ROOT = Path(__file__).parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def query(database: Path, sql: str):
    connection = duckdb.connect(str(database), read_only=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def write_mapping(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def basic_mapping(source: Path, output: str = "output.duckdb", batch_size: int = 1000) -> str:
    return f"""
source:
  file: {source}
settings:
  batch_size: {batch_size}
  error_policy: fail
output: {output}
tables:
  records:
    source: "//Record"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
      value:
        xpath: "Value/text()"
        type: VARCHAR
"""


def test_example_extraction(tmp_path: Path) -> None:
    extractor = XMLExtractor.from_yaml(EXAMPLES_DIR / "mapping.yaml")
    database = tmp_path / "example.duckdb"
    stats = extractor.run(output=database)

    assert stats.total_records == 8
    assert stats.tables["patients"].records_extracted == 4
    assert stats.tables["patients"].batches_written == 2
    assert stats.tables["appointments"].records_extracted == 4
    assert stats.tables["appointments"].batches_written == 2
    assert stats.output_path == database.resolve()
    assert extractor.output_path == database.resolve()

    assert query(database, "select count(*) from patients") == [(4,)]
    assert query(database, "select count(*) from appointments") == [(4,)]
    assert query(database, "select name from patients order by id") == [
        ("Alice Johnson",),
        ("Bob Jones",),
        ("Carol White",),
        ("David Brown",),
    ]
    phones = query(database, "select phones from patients where id = 1")[0][0]
    assert json.loads(phones) == ["555-0101", "555-0102"]
    assert query(database, "select phones from patients where id = 3") == [(None,)]
    assert query(database, "select patient_id from appointments where id = 104") == [(4,)]
    assert query(database, "select description from appointments where id = 104") == [(None,)]


def test_table_replacement_is_deterministic(tmp_path: Path) -> None:
    database = tmp_path / "replace.duckdb"
    XMLExtractor.from_yaml(EXAMPLES_DIR / "mapping.yaml").run(output=database)
    XMLExtractor.from_yaml(EXAMPLES_DIR / "mapping.yaml").run(output=database)

    assert query(database, "select count(*) from patients") == [(4,)]
    assert query(database, "select count(*) from appointments") == [(4,)]


def test_example_works_without_xsd(tmp_path: Path) -> None:
    xsd_files = list((REPO_ROOT / "examples").rglob("*.xsd")) + list(
        (REPO_ROOT / "tests").rglob("*.xsd")
    )
    assert xsd_files == []

    extractor = XMLExtractor.from_yaml(FIXTURES_DIR / "no_xsd_mapping.yaml")
    stats = extractor.run(output=tmp_path / "no-xsd.duckdb")
    assert stats.tables["patients"].records_extracted == 4


def test_mapping_schema_contract(validate_mapping_contract) -> None:
    for mapping_path in [
        EXAMPLES_DIR / "mapping.yaml",
        FIXTURES_DIR / "mapping.yaml",
        FIXTURES_DIR / "mapping_fail.yaml",
        FIXTURES_DIR / "mapping_null.yaml",
        FIXTURES_DIR / "no_xsd_mapping.yaml",
    ]:
        validate_mapping_contract(mapping_path)


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    mapping = write_mapping(
        tmp_path / "duplicate.yaml",
        """
source:
  file: input.xml
tables:
  records:
    source: "//Record"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
  records:
    source: "//Other"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
""",
    )

    with pytest.raises(ConfigError) as captured:
        XMLExtractor.from_yaml(mapping)
    assert "duplicate key" in str(captured.value)


def test_callback_and_script_keys_are_rejected(tmp_path: Path) -> None:
    mapping = write_mapping(
        tmp_path / "callback.yaml",
        """
source:
  file: input.xml
transform: my_function
tables:
  records:
    source: "//Record"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
""",
    )

    with pytest.raises(ConfigError) as captured:
        XMLExtractor.from_yaml(mapping)
    assert "unknown key" in str(captured.value)


@pytest.mark.parametrize(
    "body",
    [
        "source: {file: input.xml}\nsettings: {batch_size: 0}\ntables: {}\n",
        "source: {file: input.xml}\ntables: {records: {source: '//R', columns: {id: {xpath: '@id', type: NOPE}}}}\n",
        "source: {file: input.xml}\ntables: {bad-name: {source: '//R', columns: {id: {xpath: '@id', type: INTEGER}}}}\n",
        "source: {file: input.xml}\ntables: {records: {source: '//R[', columns: {id: {xpath: '@id', type: INTEGER}}}}\n",
        "source: {file: input.xml}\ntables: {records: {source: '//R[1]', columns: {id: {xpath: '@id', type: INTEGER}}}}\n",
        "source: {file: input.xml}\ntables: {records: {source: '//R', columns: {id: {xpath: '@id', type: INTEGER}, id: {xpath: '@id', type: INTEGER}}}}\n",
    ],
)
def test_invalid_configurations_are_rejected(tmp_path: Path, body: str) -> None:
    mapping = write_mapping(tmp_path / "invalid.yaml", body)
    with pytest.raises(ConfigError):
        XMLExtractor.from_yaml(mapping)


def test_output_must_not_overwrite_source() -> None:
    extractor = XMLExtractor.from_yaml(EXAMPLES_DIR / "mapping.yaml")
    with pytest.raises(ConfigError):
        extractor.run(output=EXAMPLES_DIR / "input.xml")


def test_fail_policy_reports_context(tmp_path: Path, fixtures_dir: Path) -> None:
    extractor = XMLExtractor.from_yaml(fixtures_dir / "mapping_fail.yaml")
    with pytest.raises(ConversionError) as captured:
        extractor.run(output=tmp_path / "fail.duckdb")

    error = captured.value
    assert error.table == "records"
    assert error.column == "event_date"
    assert error.xpath == "Date/text()"
    assert error.value == "not-a-date"
    assert error.target_type == "DATE"


def test_null_policy_continues_and_stores_nulls(tmp_path: Path, fixtures_dir: Path) -> None:
    extractor = XMLExtractor.from_yaml(fixtures_dir / "mapping_null.yaml")
    database = tmp_path / "null.duckdb"
    stats = extractor.run(output=database)

    assert stats.tables["records"].records_extracted == 3
    assert query(database, "select event_date from records where id = 2") == [(None,)]
    assert query(database, "select amount from records where id = 3") == [(None,)]
    assert query(database, "select active from records where id = 3") == [(None,)]
    assert query(database, "select active from records where id = 2") == [(True,)]


def test_batches_and_large_file_memory(tmp_path: Path, large_xml_writer) -> None:
    source_10k = large_xml_writer(10_000, "large10k.xml")
    source_100k = large_xml_writer(100_000, "large100k.xml")
    mapping_10k = write_mapping(
        tmp_path / "mapping10k.yaml",
        basic_mapping(source_10k, output="db10k.duckdb"),
    )
    mapping_100k = write_mapping(
        tmp_path / "mapping100k.yaml",
        basic_mapping(source_100k, output="db100k.duckdb"),
    )

    tracemalloc.start()
    stats_10k = XMLExtractor.from_yaml(mapping_10k).run(output=tmp_path / "db10k.duckdb")
    _, peak_10k = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    stats_100k = XMLExtractor.from_yaml(mapping_100k).run(output=tmp_path / "db100k.duckdb")
    _, peak_100k = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert stats_10k.tables["records"].records_extracted == 10_000
    assert stats_10k.tables["records"].batches_written == 10
    assert stats_100k.tables["records"].records_extracted == 100_000
    assert stats_100k.tables["records"].batches_written == 100
    assert query(tmp_path / "db10k.duckdb", "select count(*) from records") == [(10_000,)]
    assert query(tmp_path / "db100k.duckdb", "select count(*) from records") == [(100_000,)]
    assert peak_100k < peak_10k * 4 + 32 * 1024 * 1024


def test_cli_run_export_and_database_override(tmp_path: Path, capsys) -> None:
    mapping = write_mapping(
        tmp_path / "mapping.yaml",
        f"""
source:
  file: {EXAMPLES_DIR / "input.xml"}
settings:
  batch_size: 2
output: configured.duckdb
tables:
  patients:
    source: "//Patient"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
      name:
        xpath: "Name/text()"
        type: VARCHAR
  appointments:
    source: "//Patient/Appointment"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
      patient_id:
        xpath: "../@id"
        type: INTEGER
""",
    )
    override = tmp_path / "override.duckdb"
    parquet_dir = tmp_path / "parquet"

    assert main(["run", str(mapping), "--output", str(override)]) == 0
    output = capsys.readouterr().out
    assert "total records: 8" in output
    assert str(override) in output

    assert main(["export", str(mapping), "--output-dir", str(parquet_dir), "--database", str(override)]) == 0
    assert (parquet_dir / "patients.parquet").is_file()
    assert (parquet_dir / "appointments.parquet").is_file()

    assert main(["export", str(mapping), "--output-dir", str(parquet_dir)]) == 1
    assert "database does not exist" in capsys.readouterr().err


def test_api_export_defaults_to_configured_output(tmp_path: Path, examples_dir: Path) -> None:
    mapping = write_mapping(
        tmp_path / "mapping.yaml",
        f"""
source:
  file: {examples_dir / "input.xml"}
settings:
  batch_size: 2
output: configured.duckdb
tables:
  patients:
    source: "//Patient"
    columns:
      id:
        xpath: "@id"
        type: INTEGER
      name:
        xpath: "Name/text()"
        type: VARCHAR
""",
    )
    extractor = XMLExtractor.from_yaml(mapping)
    stats = extractor.run()
    assert stats.output_path == (tmp_path / "configured.duckdb").resolve()

    parquet_dir = tmp_path / "parquet"
    paths = extractor.export_parquet(parquet_dir)
    assert paths == [(parquet_dir / "patients.parquet").resolve()]
    assert paths[0].is_file()


def test_parquet_preserves_types(tmp_path: Path, examples_dir: Path) -> None:
    database = tmp_path / "types.duckdb"
    extractor = XMLExtractor.from_yaml(examples_dir / "mapping.yaml")
    extractor.run(output=database)
    parquet_dir = tmp_path / "parquet"
    extractor.export_parquet(parquet_dir, database=database)

    patients = duckdb.connect()
    try:
        description = patients.execute(
            f"describe select * from '{parquet_dir / 'patients.parquet'}'"
        ).fetchall()
        appointment_description = patients.execute(
            f"describe select * from '{parquet_dir / 'appointments.parquet'}'"
        ).fetchall()
    finally:
        patients.close()

    patient_types = {row[0]: row[1] for row in description}
    appointment_types = {row[0]: row[1] for row in appointment_description}
    assert patient_types["id"] == "INTEGER"
    assert patient_types["name"] == "VARCHAR"
    assert patient_types["phones"] == "JSON"
    assert appointment_types["date"] == "DATE"
    assert appointment_types["patient_id"] == "INTEGER"


def test_export_missing_database_raises(tmp_path: Path, examples_dir: Path) -> None:
    extractor = XMLExtractor.from_yaml(examples_dir / "mapping.yaml")
    with pytest.raises(BackendError):
        extractor.export_parquet(tmp_path / "parquet", database=tmp_path / "missing.duckdb")


def test_export_missing_table_raises(tmp_path: Path, examples_dir: Path) -> None:
    database = tmp_path / "empty.duckdb"
    connection = duckdb.connect(str(database))
    connection.close()
    extractor = XMLExtractor.from_yaml(examples_dir / "mapping.yaml")
    with pytest.raises(BackendError):
        extractor.export_parquet(tmp_path / "parquet", database=database)


def test_second_run_raises(tmp_path: Path, examples_dir: Path) -> None:
    extractor = XMLExtractor.from_yaml(examples_dir / "mapping.yaml")
    extractor.run(output=tmp_path / "first.duckdb")
    with pytest.raises(RuntimeError):
        extractor.run(output=tmp_path / "second.duckdb")
