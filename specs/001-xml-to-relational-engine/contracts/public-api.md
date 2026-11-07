# Public API Contract: `xml2rel`

**Feature**: `001-xml-to-relational-engine`

## Import surface

```python
from xml2rel import (
    XMLExtractor,
    RunStats,
    TableStats,
    ConfigError,
    ExtractionError,
    ConversionError,
    BackendError,
)
```

## `XMLExtractor`

```python
class XMLExtractor:
    @classmethod
    def from_yaml(cls, mapping_path: str | Path) -> "XMLExtractor": ...

    def run(self, output: str | Path | None = None) -> RunStats: ...

    def export_parquet(self, output_dir: str | Path) -> list[Path]: ...

    @property
    def mapping_path(self) -> Path: ...

    @property
    def output_path(self) -> Path: ...
```

### `from_yaml(mapping_path)`

- Loads the YAML mapping and validates it completely before returning.
- Resolves source and output paths relative to the mapping file.
- Compiles every source matcher and column XPath expression.
- Raises `ConfigError` for any invalid shape, duplicate/unsafe name, unsupported enum, malformed XPath, unsupported source expression, invalid batch size, or unsafe output path.
- Does not read the XML file or open the database.

### `run(output=None)`

- Runs extraction once for this instance.
- `output` overrides the mapping's output database for this run and becomes the extractor's effective `output_path` for later export.
- Creates/replaces mapped tables, streams the XML, converts values, flushes batches, and returns statistics.
- Raises `ConfigError` (already validated at construction unless state is invalid), `ExtractionError` for XML access/parse failure, `ConversionError` under the `fail` policy, or `BackendError` for database failures.
- Under the `null` policy, invalid values become NULL and no `ConversionError` is raised.
- Calling `run` a second time raises `RuntimeError` with a clear message.
- Resources are closed on success and failure.

### `export_parquet(output_dir)`

- Opens the effective output database without re-running extraction.
- Creates `output_dir` recursively.
- Writes `<table>.parquet` for every mapped table, in declaration order.
- Returns the written paths in the same order.
- Raises `ConfigError`/`BackendError` if the database or any mapped table is missing, or if the directory cannot be written.
- Does not modify the source XML or the database.

### Properties

- `mapping_path`: absolute path of the loaded mapping.
- `output_path`: absolute effective output database path (configured value unless overridden by a prior `run(output=...)`).

## `RunStats`

Immutable result object.

| Attribute | Type | Meaning |
|-----------|------|---------|
| `tables` | ordered mapping of table name to `TableStats` | Declaration order. |
| `total_records` | int | Sum of table record counts. |
| `duration_seconds` | float | Wall-clock extraction duration. |
| `output_path` | Path | Effective database path. |

`TableStats`:

| Attribute | Type | Meaning |
|-----------|------|---------|
| `records_extracted` | int | Rows appended for the table. |
| `batches_written` | int | Logical batch flushes, including the final partial batch. |

## Exceptions

| Exception | Attributes | Meaning |
|-----------|------------|---------|
| `ConfigError` | `mapping_path`, optional `table`, optional `column`, `reason` | Invalid mapping or unsafe path. |
| `ExtractionError` | `source_path`, `reason` | XML cannot be opened or parsed. |
| `ConversionError` | `table`, `column`, `xpath`, `value`, `target_type`, `reason` | A value cannot be converted under `fail`. |
| `BackendError` | `database_path`, `operation`, `reason` | DuckDB or export failure. |

All inherit from `Xml2RelError`, which inherits from `Exception`. Error messages include the fields above in readable form.

## Example

```python
from xml2rel import XMLExtractor

extractor = XMLExtractor.from_yaml("examples/mapping.yaml")
stats = extractor.run(output="/tmp/results.duckdb")

for name, table in stats.tables.items():
    print(name, table.records_extracted, table.batches_written)

paths = extractor.export_parquet("/tmp/parquet")
print(paths)
```
