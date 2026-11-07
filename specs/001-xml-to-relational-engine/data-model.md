# Phase 1 Data Model: Declarative XML-to-Relational Extraction Engine

**Feature**: `001-xml-to-relational-engine`
**Date**: 2026-11-07

The tool has three layers of entities: validated configuration, in-memory runtime state, and generated storage/export artifacts. All names below are conceptual; implementation modules may use private helper types.

## Configuration Entities

### MappingConfig

The validated root of one YAML mapping.

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `source` | SourceConfig | Yes | Must contain a non-empty file path. |
| `settings` | Settings | No | Defaults apply when omitted. |
| `output` | resolved path | No | Defaults to `output.duckdb` beside the mapping file. CLI override wins. Must not resolve to the source XML or mapping file. |
| `tables` | ordered map of TableConfig | Yes | At least one table; names unique and matching `^[A-Za-z_][A-Za-z0-9_]*$`; declaration order preserved for reporting. |
| `mapping_path` | resolved absolute path | Yes | Used for relative path resolution and error messages. |

Unknown top-level keys are rejected.

### SourceConfig

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `file` | resolved path | Yes | Non-empty string; resolved relative to the mapping file when not absolute; must exist, be readable, and differ from the output path. |

### Settings

| Field | Type | Required | Default | Rules |
|-------|------|----------|---------|-------|
| `batch_size` | integer | No | 10,000 | Strictly greater than zero. |
| `error_policy` | enum | No | `fail` | One of `fail`, `null` (case-insensitive input accepted). |

Unknown settings keys are rejected.

### TableConfig

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | Yes | Map key; unique; valid SQL/Parquet-safe identifier. |
| `source` | string | Yes | Non-empty XPath; syntactically valid for `lxml` and supported by the streaming `SourcePathMatcher`. |
| `columns` | ordered map of ColumnConfig | Yes | At least one column; names unique within the table and matching `^[A-Za-z_][A-Za-z0-9_]*$`; declaration order defines output column order. |

Unknown table keys are rejected. A table may match zero records; that is not an error.

### ColumnConfig

| Field | Type | Required | Default | Rules |
|-------|------|----------|---------|-------|
| `name` | string | Yes | — | Map key; unique within its table; safe identifier. |
| `xpath` | string or list of strings | Yes | — | A single expression or a non-empty list of non-empty strings; each must compile as an `lxml` XPath. |
| `strategy` | enum | No | `first_non_empty` | One of `first_non_empty`, `first`, `concat`, `collect`. |
| `type` | enum | Yes | — | One of `VARCHAR`, `INTEGER`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `JSON` (case-insensitive input accepted). |

Unknown column keys are rejected.

### Enumerations

**ColumnStrategy**: `first_non_empty`, `first`, `concat`, `collect`.

**ColumnType**: `VARCHAR`, `INTEGER`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `JSON`.

**ErrorPolicy**: `fail`, `null`.

### SourcePathMatcher

Derived from a table's `source` expression; not user-authored.

| Field | Type | Meaning |
|-------|------|---------|
| `segments` | ordered list of PathSegment | Child and descendant steps, each with a tag or `*` and optional attribute predicates. |
| `anchored_at_root` | boolean | True for leading `/`, leading `//`, or a relative path evaluated from the document node. |
| `expression` | string | Original mapping text, used in validation/runtime messages. |

**Validation rules**:

- Supported: absolute or relative location paths; `/` and `//`; element names; `*`; attribute existence/equality predicates.
- Rejected with a clear table/expression error: namespace prefixes, positional predicates (`[1]`), functions, unions, `..`/`.` steps, child-element predicates, unparseable text.
- Matching occurs on start events so an open ancestor's record status is known before descendants are visited.

## Runtime Entities

### RawValue

One column value after XPath selection but before type conversion.

| Field | Type | Meaning |
|-------|------|---------|
| `value` | string or None | Selected text or JSON-array text; `None` means no match. |
| `xpath_label` | string | The chosen expression for single-expression strategies, or a readable joined label for multi-expression strategies. Used in conversion errors. |

### ExtractedRecord

One completed record, emitted immediately at the record element's end event.

| Field | Type | Meaning |
|-------|------|---------|
| `table_name` | string | Owning table. |
| `values` | ordered map of column name to RawValue | One entry per mapped column. |

### ParseFrame

One entry on the open-element stack.

| Field | Type | Meaning |
|-------|------|---------|
| `element` | lxml element | The live element. |
| `record_tables` | set of table names | Tables whose source matcher matched at start; empty for non-record elements. |
| `parent` | ParseFrame or None | Link to the open parent frame. |

**Invariants**:

- Every start event pushes exactly one frame; every end event pops exactly one frame.
- An element is a record for a table iff its frame's `record_tables` contains that table.
- A frame's element remains attached while any ancestor frame has a non-empty `record_tables`.
- After an end event, an element is cleared/detached only when no remaining ancestor frame is a record.

### TableBuffer

One independent buffer per output table.

| Field | Type | Meaning |
|-------|------|---------|
| `table` | TableConfig | Owning table; supplies column order and types. |
| `rows` | list of ordered value tuples | Converted rows awaiting insertion. |
| `batch_size` | integer | Global configured size. |
| `batches_written` | integer | Count of completed logical batches. |

**Transitions**:

1. Append a converted row.
2. If `len(rows) >= batch_size`, hand the rows to the backend as one logical batch, clear the list, and increment `batches_written`.
3. At document end, if `rows` is non-empty, flush it as one final logical batch.
4. On failure, stop appending; the backend rolls back any open chunk transaction and closes.

### TableStats / RunStats

| Entity | Fields |
|--------|--------|
| TableStats | `table_name`, `records_extracted`, `batches_written` |
| RunStats | ordered per-table stats, `total_records`, `duration_seconds` |

**Invariants**:

- `records_extracted` equals rows appended for that table.
- `batches_written` equals the number of logical flushes, including the final partial flush.
- `total_records` equals the sum of per-table `records_extracted`.
- Statistics are returned only after all buffers flush successfully.

### Exceptions

| Exception | Carries | Raised when |
|-----------|---------|-------------|
| `ConfigError` | mapping path, table, column, reason | YAML/shape/type/strategy/XPath/path/identifier validation fails. |
| `ExtractionError` | source path, parse position if available, reason | XML cannot be opened/parsed, or the parser encounters an unrecoverable state. |
| `ConversionError` | table, column, xpath label, original value, target type, reason | A selected value cannot be converted and policy is `fail`. |
| `BackendError` | database path, operation, reason | DuckDB connection, DDL, insertion, or export fails. |

`ConversionError` is the only error whose behavior depends on policy: with `null`, the engine logs no error and substitutes NULL; with `fail`, it propagates.

## Storage Entities

### Output Table

Generated dynamically from TableConfig.

| Aspect | Rule |
|--------|------|
| Name | TableConfig.name, quoted in SQL. |
| Columns | TableConfig.columns in declaration order, quoted in SQL. |
| Types | Direct mapping from ColumnType to DuckDB type. |
| Lifecycle | `DROP TABLE IF EXISTS` then `CREATE TABLE` inside the run's table-creation transaction; every run replaces mapped tables. |
| Row source | One row per completed record; rows inserted in batches. |
| JSON | Stored in a DuckDB `JSON` column; bound as canonical JSON text/cast. |
| Nullability | All columns nullable, because missing/empty values become NULL. |

### Parquet Artifact

One per mapped table.

| Aspect | Rule |
|--------|------|
| File | `<output-dir>/<table_name>.parquet`; output directory created if absent. |
| Content | Full table selected in column order. |
| Schema | Inherited from the DuckDB table; column names, order, and types preserved. |
| Preconditions | Configured output database exists and every mapped table exists; otherwise export fails before writing partial artifacts. |

## Relationships

```text
MappingConfig 1 ── 1 SourceConfig
MappingConfig 1 ── 1 Settings
MappingConfig 1 ── * TableConfig
TableConfig   1 ── 1 SourcePathMatcher
TableConfig   1 ── * ColumnConfig
TableConfig   1 ── 1 TableBuffer (runtime)
TableConfig   1 ── 1 Output Table (storage)
TableConfig   1 ── 0..1 Parquet Artifact (export)
ExtractedRecord * ── 1 TableConfig
TableBuffer   1 ── * ExtractedRecord-derived rows
RunStats      1 ── * TableStats
```

## Validation Map

| Requirement | Validation point |
|-------------|------------------|
| FR-001, FR-002 | YAML root shape, source/settings/output/tables presence and types. |
| FR-003, FR-004 | Table source non-empty; columns non-empty; each column has xpath and type. |
| FR-005 | Unknown keys, duplicates, enum values, batch size, identifier patterns, XPath compilation, source matcher support. |
| FR-006, FR-007 | Path resolution relative to mapping; CLI override precedence. |
| FR-009, FR-010 | Source matcher compiled per table; column expressions compiled and evaluated against the record element. |
| FR-011–FR-016 | Strategy enum and resolver behavior, including `None` for no matches and JSON serialization for `collect`. |
| FR-017, FR-018 | Missing/blank detection before conversion; text preservation for non-blank VARCHAR. |
| FR-019–FR-025 | ParseFrame invariants, per-table buffers, batch flush thresholds, clear/detach rules. |
| FR-026–FR-031 | Backend DDL, batch transaction, output path safety, table replacement, cleanup. |
| FR-032–FR-036 | Type enum and per-type conversion formats. |
| FR-037–FR-039 | ConversionError fields and policy branch. |
| FR-040–FR-046 | API/CLI signatures, stats return/print, export preconditions, failure reporting. |
