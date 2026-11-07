# Quickstart Validation Guide

**Feature**: `001-xml-to-relational-engine`
**Purpose**: Prove the MVP works end to end after implementation. This is a validation guide, not implementation or a replacement for the test suite.

## Prerequisites

- Python 3.11 or newer
- `pip`
- A POSIX-like shell (commands are also adaptable to PowerShell)

## 1. Install the project

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: `xml2rel --help` exits 0 and lists the `run` and `export` commands.

## 2. Run the test suite

```bash
pytest
```

Expected:

- All unit and integration tests pass.
- The parser tests show nested records, parent access, and per-table buffering.
- The converter tests show every supported type and both policies.
- The engine tests show multi-table extraction, batching, Parquet round-tripping, and a run with no XSD present.

## 3. Inspect the example

The example mapping declares `patients` and `appointments`, with appointments nested under patients:

```yaml
source:
  file: input.xml

settings:
  batch_size: 10000

output: output.duckdb

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
      date:
        xpath: "Date/text()"
        type: DATE
      description:
        xpath: "Description/text()"
        type: VARCHAR
```

## 4. Run extraction

```bash
xml2rel run examples/mapping.yaml
```

Expected:

- `x` rows in `patients` and `y` rows in `appointments`, matching the example fixture.
- Appointment `patient_id` values point to the correct patient `id`.
- Output reports per-table records and batches, total records, duration, and the resolved database path.
- `examples/output.duckdb` exists.

Inspect the database independently:

```bash
python - <<'PY'
import duckdb
con = duckdb.connect("examples/output.duckdb", read_only=True)
print(con.execute("select count(*) from patients").fetchone())
print(con.execute("select count(*) from appointments").fetchone())
print(con.execute("select patient_id, count(*) from appointments group by 1 order by 1").fetchall())
con.close()
PY
```

Expected: counts match the mapping run and every appointment resolves to an existing patient.

## 5. Override the output database

```bash
xml2rel run examples/mapping.yaml --output /tmp/xml2rel-result.duckdb
```

Expected: the statistics block reports `/tmp/xml2rel-result.duckdb`; the override file exists; `examples/output.duckdb` is not modified by this run.

## 6. Verify multiple-XPath strategies

Use a fixture whose name exists in one of two locations, or temporarily edit the example mapping:

```yaml
name:
  xpath:
    - "Name/text()"
    - "PersonalData/FullName/text()"
  strategy: first_non_empty
  type: VARCHAR
```

Expected with the provided fixture:

- `first_non_empty` returns the first populated alternative.
- `first` returns the first expression's first value, even when it is empty.
- `concat` joins every populated match with no separator.
- `collect` produces a JSON array in a `VARCHAR` or `JSON` column.

## 7. Verify error policies

Set `settings.error_policy: fail` and point a typed column at a fixture containing an invalid date or integer.

Expected: the command exits non-zero and the error names the table, column, XPath, original value, and target type. No successful statistics block is printed.

Set `settings.error_policy: null` and run the same fixture.

Expected: the run completes, the invalid value is NULL, and the statistics block reports the row.

## 8. Verify large-file streaming

Run the large-file test or generate an input larger than memory is practical for the environment:

```bash
pytest tests/test_parser.py -k large -q
pytest tests/test_engine.py -k large -q
```

Expected:

- The run completes with the expected row and batch counts.
- The parser's open frame stack remains shallow.
- Peak tracked allocations stay below the test's generous ceiling and do not scale with total record count.

## 9. Export to Parquet

```bash
xml2rel export examples/mapping.yaml --output-dir /tmp/xml2rel-parquet
```

Expected:

- One file per mapped table: `/tmp/xml2rel-parquet/patients.parquet` and `/tmp/xml2rel-parquet/appointments.parquet`.
- Each command lists the written paths.

Read them back:

```bash
python - <<'PY'
import duckdb
con = duckdb.connect()
print(con.execute("select * from '/tmp/xml2rel-parquet/patients.parquet' limit 5").fetchall())
print(con.execute("describe select * from '/tmp/xml2rel-parquet/appointments.parquet'").fetchall())
con.close()
PY
```

Expected: row counts match the database, column order matches the mapping, and `DATE`, `INTEGER`, and other declared types are preserved.

## 10. Confirm XSD independence

```bash
python - <<'PY'
from pathlib import Path
xsd = list(Path(".").rglob("*.xsd"))
print("xsd files:", xsd)
assert not xsd
PY

xml2rel run examples/mapping.yaml --output /tmp/xml2rel-no-xsd.duckdb
```

Expected: no XSD files exist anywhere in the project or example input directory, and extraction succeeds.

## Known MVP limitations to observe

- Column XPath expressions that need the entire document, global aggregates, or previously released sibling branches are unsupported.
- `../@id`-style parent access works while the parent is still attached, which the parser guarantees for records being emitted.
- Source paths support location paths with `/`, `//`, `*`, element names, and attribute predicates. Namespace prefixes, positional predicates, functions, and unions are rejected.
- One input XML file per run; no incremental append, resume, deduplication, or automatic foreign-key inference.
- Tables are replaced on each run.
- A very large single record remains in memory until that record completes.

## Related artifacts

- [spec.md](./spec.md)
- [plan.md](./plan.md)
- [data-model.md](./data-model.md)
- [contracts/mapping.schema.json](./contracts/mapping.schema.json)
- [contracts/cli.md](./contracts/cli.md)
- [contracts/public-api.md](./contracts/public-api.md)
