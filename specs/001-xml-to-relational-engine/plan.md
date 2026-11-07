# Implementation Plan: Declarative XML-to-Relational Extraction Engine

**Branch**: `001-xml-to-relational-engine` | **Date**: 2026-11-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-xml-to-relational-engine/spec.md`

## Summary

Build a single installable Python package that reads a YAML mapping, streams an XML file with `lxml.etree.iterparse`, evaluates column XPath expressions relative to each completed record element, converts values to explicit SQL types, and inserts rows into DuckDB in per-table batches. The package exposes a Python API (`XMLExtractor.from_yaml(...).run()`), a `run` CLI, and an `export` CLI that writes one Parquet file per mapped table. The implementation never reads, requires, or infers an XSD.

The critical design choice is memory-safe streaming with nested records: record matches are detected at element start with a compiled structural matcher, rows are emitted at element end, and elements are cleared or detached only when no open ancestor record can still need them. This preserves `../@id`-style parent access and parent columns that read child subtrees while keeping memory bounded by the largest open record subtree.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `lxml` (streaming parse and XPath), `duckdb` (storage and Parquet export), `PyYAML` (mapping input). Development dependency: `pytest`.

**Storage**: DuckDB file database, default `output.duckdb` beside the mapping file; Parquet files exported through DuckDB's `COPY ... TO ... (FORMAT PARQUET)`.

**Testing**: `pytest`, with fixtures for nested and repeated records, missing values, multiple XPath matches, invalid data, large generated input, and end-to-end DuckDB/Parquet assertions.

**Target Platform**: Local developer or analyst workstation on Linux, macOS, or Windows with Python 3.11+.

**Project Type**: Single Python library plus command-line interface.

**Performance Goals**: Process at least 100,000 records with memory bounded by batch size and largest open record subtree rather than total record count; insert one parameterized statement per chunk of a batch, never one statement per row.

**Constraints**: One XML source file per run; no XSD, no schema inference, no Polars, no web service, API server, or GUI. Column XPath expressions are limited to what can be evaluated from the live current record and its still-attached ancestors. Source XPath matching supports absolute/relative location paths using child and descendant axes, `*`, and attribute predicates; unsupported constructs fail mapping validation with a clear message. Custom callbacks, plugins, and pre/post scripts are out of scope; users post-process DuckDB tables or Parquet exports in Python after extraction.

**Scale/Scope**: One mapping may declare many output tables and millions of input records. Batch size defaults to 10,000 records per table. Tables are replaced on each run. No incremental append, resume, deduplication, or automatic foreign-key discovery.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository's `.specify/memory/constitution.md` is still the unmodified example template, so it defines no ratified project principles or enforceable gates. No constitution violations exist to justify.

The plan self-imposes gates derived from the approved specification:

- **G1 — Streaming correctness**: Parent elements remain attached until all nested child records complete; no full-document load.
- **G2 — Schema independence**: No XSD read, required, or inferred at any point.
- **G3 — Batch integrity**: Per-table buffers flush at the configured size; insertion is batched, transactional, and resource-clean.
- **G4 — Explicit typing**: Every column has a declared type and conversions follow the configured error policy with full context.
- **G5 — Testability**: All public behavior is covered by pytest fixtures, including large-file and no-XSD scenarios.
- **G6 — Simplicity**: A single `src/xml2rel` package with focused modules; no plugin system, ORM, or abstraction layer beyond the DuckDB backend boundary.

Result: **PASS** before research. Post-design re-check: **PASS** (see the end of this plan).

## Project Structure

### Documentation (this feature)

```text
specs/001-xml-to-relational-engine/
├── plan.md              # This file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities and validation rules
├── quickstart.md        # Phase 1 end-to-end validation guide
├── contracts/
│   ├── mapping.schema.json
│   ├── cli.md
│   └── public-api.md
└── tasks.md             # Created later by /speckit.tasks
```

### Source Code (repository root)

```text
pyproject.toml
README.md
examples/
├── input.xml
└── mapping.yaml
src/
└── xml2rel/
    ├── __init__.py        # Public exports: XMLExtractor, RunStats, exceptions
    ├── __main__.py        # `python -m xml2rel` entry point
    ├── cli.py             # argparse run/export commands and stats output
    ├── config.py          # YAML loading, dataclasses, validation, path resolution
    ├── parser.py          # iterparse loop, source matching, safe clearing
    ├── xpath.py           # column evaluation and combination strategies
    ├── converter.py       # typed conversion and conversion errors
    ├── buffers.py         # per-table buffers and flush decisions
    ├── engine.py          # orchestration, stats, run/export entry points
    └── backend/
        ├── __init__.py    # Backend protocol/export
        └── duckdb.py      # table DDL, chunked batch inserts, Parquet COPY
tests/
├── test_parser.py
├── test_xpath.py
├── test_converter.py
├── test_engine.py
└── fixtures/
    ├── patients.xml
    ├── mapping.yaml
    ├── errors.xml
    ├── mapping_fail.yaml
    ├── mapping_null.yaml
    └── no_xsd_mapping.yaml
```

**Structure Decision**: Single-project layout because the deliverable is one library with one CLI. The only interface boundary is `backend/duckdb.py`; the parser is storage-agnostic and emits extracted records through a callback so batch conversion and persistence remain in `engine.py`.

## Design Details

### Mapping lifecycle

1. `XMLExtractor.from_yaml(path)` loads YAML with `yaml.safe_load`, validates all sections, compiles source matchers and per-column XPath expressions, resolves the source and output paths relative to the mapping file, and constructs the DuckDB backend.
2. `run(output_override=None)` creates the output database directory if needed, opens DuckDB, drops and recreates all mapped tables in one transaction, streams the XML, converts and buffers records, flushes at batch size, writes final buffers, collects statistics, and closes resources.
3. `export_parquet(output_dir)` opens the effective output database (the mapping's configured path, or the last `run(output=...)` override), verifies every mapped table exists, creates the output directory, and writes `<table>.parquet` for each table.

### Streaming and record matching

- A `SourcePathMatcher` compiles each table's source XPath into ordered segments. Supported syntax is location paths anchored at the document or using `//`, with child/descendant steps, element names, `*`, and attribute predicates such as `[@id]`, `[@id='x']`. Numeric positional predicates, functions, unions, and unprefixed default-namespace handling are rejected at validation time with the table name and expression.
- `iterparse` uses `events=("start", "end")`. Match detection happens on start so the parser knows whether an open ancestor is a record before children arrive; attributes needed by supported predicates are available at start.
- A frame records the element, matched table names, and parent link. On end, each matched table emits a raw record.
- After extraction, if any ancestor frame is a record, the element is retained because an open ancestor record may read it. If no ancestor is a record, the element is cleared and detached from its parent. When an outer record ends, its full retained subtree is cleared, releasing all nested child records that were kept for parent columns.
- Buffers are per table. A flush occurs as soon as the table's buffer reaches `batch_size`; remaining buffers flush at document end.

### Column evaluation

- Expressions are evaluated with `record.xpath(expr)` so they are relative to the record element. Attribute and parent expressions such as `@id` and `../@id` work because ancestors remain attached.
- XPath results are normalized to a list of strings. Elements contribute their full text content; strings, numbers, and booleans are stringified (`true`/`false` for booleans).
- `first_non_empty` selects the first value whose stripped form is non-empty; `first` selects the first value from the first expression that yields any result; `concat` joins all non-empty values with no separator; `collect` serializes all matched values as a JSON array. No matches produce `None`, which becomes SQL NULL.
- `collect` always produces a JSON array string, even when the target type is `VARCHAR`. A `JSON` target validates and canonicalizes the selected value.

### Batch storage

- DDL uses quoted identifiers and explicit DuckDB types. `INTEGER` maps to `INTEGER`, `BIGINT` to `BIGINT`, `DOUBLE` to `DOUBLE`, `BOOLEAN` to `BOOLEAN`, `DATE` to `DATE`, `TIMESTAMP` to `TIMESTAMP`, and `JSON` to `JSON`; `VARCHAR` maps to `VARCHAR`.
- Each logical batch is written in an explicit `BEGIN`/`COMMIT` transaction. Rows are sent as parameterized multi-row `INSERT ... VALUES` statements chunked so the placeholder count stays below a conservative 5,000-parameter limit. JSON placeholders are cast to `JSON`. `ROLLBACK` runs on any failure.
- The backend exposes `create_tables`, `insert_batch`, `table_exists`, `export_table_parquet`, and `close`. Cleanup runs in `finally` blocks so failed runs do not leak connections.

### Parquet export

- `export` uses the effective output database (configured path, or a prior API run override); it does not re-run extraction.
- DuckDB `COPY (SELECT * FROM "table") TO 'directory/table.parquet' (FORMAT PARQUET)` preserves column names, order, and types. Unsafe characters in table names are rejected at validation so file names are predictable and cannot escape the output directory.

### Statistics

`RunStats` contains ordered per-table `records_extracted` and `batches_written`, plus `total_records` and `duration_seconds`. The CLI prints a compact table to stdout and prints errors to stderr with a non-zero exit code.

## Phase 0: Research

Research decisions and alternatives are recorded in [research.md](./research.md). All unknowns are resolved: source matching strategy, clearing policy, batch insertion mechanism, conversion formats, JSON/collect handling, export mechanism, and large-file testing approach.

## Phase 1: Design Artifacts

- [data-model.md](./data-model.md) defines configuration, runtime, and storage entities plus validation rules and state transitions.
- [contracts/mapping.schema.json](./contracts/mapping.schema.json) defines the accepted YAML mapping shape.
- [contracts/cli.md](./contracts/cli.md) defines commands, options, exit codes, and statistic output.
- [contracts/public-api.md](./contracts/public-api.md) defines the Python surface.
- [quickstart.md](./quickstart.md) defines runnable end-to-end validation scenarios.

## Post-Design Constitution Re-Check

- **G1 PASS**: The frame stack and open-record-ancestor rule preserve ancestors and retained subtrees; no document-wide tree is built.
- **G2 PASS**: No XSD path, parser, or inference step exists anywhere in the design.
- **G3 PASS**: Per-table buffers, chunked parameterized inserts, explicit per-batch transactions, and `finally` cleanup are specified.
- **G4 PASS**: Every column has a type; conversion errors carry table, column, XPath, and original value.
- **G5 PASS**: Unit, integration, large-file, error-policy, Parquet, CLI, and no-XSD scenarios are planned.
- **G6 PASS**: Modules stay small and single-purpose; no unnecessary abstraction or dependency is introduced.

## Complexity Tracking

No constitution violations. No additional projects, services, plugin layers, or storage engines are introduced.
