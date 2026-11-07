# xml2rel

A lightweight, declarative XML-to-relational extraction engine for Python. Define tables, record XPaths, and column mappings in YAML; `xml2rel` streams large XML files with `lxml.etree.iterparse`, converts values to explicit SQL types, and writes batches to DuckDB.

`xml2rel` does not require, read, or infer an XSD. The mapping is the source of truth.

## Features

- Multiple output tables from one XML file
- Column XPaths evaluated relative to the current record
- One or many XPath expressions per column
- Strategies: `first_non_empty`, `first`, `concat`, `collect`
- Streaming parser with nested-record-safe memory release
- Independent per-table buffers and configurable batch size
- DuckDB storage with explicit SQL types
- Type conversion for `VARCHAR`, `INTEGER`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP`, and `JSON`
- Configurable conversion error policy: `fail` or `null`
- Python API and CLI
- One Parquet file per mapped table

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

For runtime-only installation from a checkout:

```bash
pip install .
```

## Mapping

```yaml
source:
  file: input.xml

settings:
  batch_size: 10000
  error_policy: fail       # fail | null

output: output.duckdb

tables:
  patients:
    source: "//Patient"
    columns:
      id:
        xpath: "@id"
        type: INTEGER

      name:
        xpath:
          - "Name/text()"
          - "PersonalData/FullName/text()"
        strategy: first_non_empty
        type: VARCHAR

      phones:
        xpath: "Phone/text()"
        strategy: collect
        type: JSON

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

Relative `source.file` and `output` paths resolve against the mapping file's directory. Absolute paths are also accepted.

### Mapping rules

- Table and column names must match `^[A-Za-z_][A-Za-z0-9_]*$`.
- Every table needs a non-empty `source` XPath and at least one column.
- Every column needs `xpath` (string or non-empty list) and `type`.
- `strategy` defaults to `first_non_empty`.
- Duplicate YAML keys are rejected.
- Unknown keys are rejected.
- The output path must not equal the source XML or the mapping file.

### Strategies

| Strategy | Behavior |
|---|---|
| `first_non_empty` | First non-blank value in expression/document order. |
| `first` | First value from the first expression that yields at least one result, even if the value is blank. |
| `concat` | Concatenate all non-blank values with no implicit separator. |
| `collect` | All matched values as a compact JSON array. |

Missing elements, empty text, and whitespace-only text become `NULL`.

### Source XPath support

The streaming source matcher supports location paths anchored at the document root or beginning with `//`, using child/descendant steps, `*`, element names, and attribute predicates:

```text
//Patient
/Root/Patient
//Patient/Appointment
//Patient[@id='1']/Appointment
```

Namespaces, positional predicates (`[1]`), XPath functions, unions, `.`/`..` steps, and predicates depending on child text are rejected during mapping validation.

Column expressions are evaluated by `lxml` relative to the current record and may use `@id`, `../@id`, `text()`, and other expressions supported by `lxml` for the live record.

## Python API

```python
from xml2rel import XMLExtractor

extractor = XMLExtractor.from_yaml("examples/mapping.yaml")
stats = extractor.run()

for name, table in stats.tables.items():
    print(name, table.records_extracted, table.batches_written)

print(stats.total_records, stats.duration_seconds, stats.output_path)
```

Override the output database for one run:

```python
stats = extractor.run(output="result.duckdb")
```

`run()` may be called once per extractor instance. A second call raises `RuntimeError`.

### Export to Parquet

```python
paths = extractor.export_parquet("./parquet")
print(paths)
```

By default `export_parquet` reads the mapping's configured `output`. To export a database produced by a run override, pass `database=`:

```python
stats = extractor.run(output="result.duckdb")
paths = extractor.export_parquet("./parquet", database=stats.output_path)
```

## CLI

```bash
xml2rel run mapping.yaml
xml2rel run mapping.yaml --output result.duckdb
xml2rel export mapping.yaml --output-dir ./parquet
xml2rel export mapping.yaml --output-dir ./parquet --database result.duckdb
```

`run` prints per-table record and batch counts, total records, duration, and the output path. Errors go to stderr and exit with code 1.

## Example

```bash
xml2rel run examples/mapping.yaml --output /tmp/xml2rel-example.duckdb
xml2rel export examples/mapping.yaml --output-dir /tmp/xml2rel-parquet \
  --database /tmp/xml2rel-example.duckdb
```

The example fixture contains 4 patients and 4 appointments, including a fallback name, repeated phones, a missing appointment description, and `../@id` parent linking.

## Tests

```bash
pytest
```

The suite covers parser streaming, nested records, all combination strategies, every supported type, both error policies, batch counts, a 100,000-record memory comparison, mapping validation, Parquet export, CLI/API behavior, and a run with no XSD present.

## Limitations

- One XML source file per run.
- Column XPath expressions are evaluated relative to the current record. Document-wide aggregates, arbitrary document-root queries inside column mappings, and access to already-cleared branches are unsupported.
- Parent access such as `../@id` works while the parent is still attached; the parser guarantees this for records being emitted.
- Namespace-aware mappings are a known MVP limitation; unqualified element names are the supported default.
- The engine does not resolve cross-table foreign keys automatically.
- No incremental append, resume, deduplication, or schema inference. Mapped tables are replaced on each run.
- No callbacks, plugins, or pre/post extraction scripts. Apply custom logic after the run in Python against DuckDB or Parquet.
- A single very large record remains in memory until that record completes.
- No HTTP/web API or GUI.
