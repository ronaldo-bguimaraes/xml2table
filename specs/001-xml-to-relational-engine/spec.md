# Feature Specification: Declarative XML-to-Relational Extraction Engine

**Feature Branch**: `001-xml-to-relational-engine`

**Created**: 2026-11-07

**Status**: Draft

**Input**: User description: "Build a lightweight, declarative XML-to-relational extraction engine in Python that converts large XML files into multiple relational tables using user-defined XPath mappings, works independently of XSD, streams large files incrementally, stores results in DuckDB, converts values to explicit types with configurable error handling, exposes a Python API and CLI, reports execution statistics, and supports Parquet export."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extract multiple related tables from one XML file (Priority: P1)

A data engineer receives a large XML export containing related record types, such as patients and their appointments. They write a YAML mapping that declares one output table per record type, identifies each table's record elements, and maps each column to a relative XPath expression. They run the extractor once and receive a relational database containing all mapped tables, including parent-child keys.

**Why this priority**: This is the core value of the product. Without correct multi-table extraction and parent-child relationships, no other capability is useful.

**Independent Test**: Provide a mapping with two related tables, run the extractor against an XML fixture, and verify that both tables exist with the expected rows, column values, and parent-child identifiers.

**Acceptance Scenarios**:

1. **Given** an XML file with patient records and nested appointment records and a mapping declaring both tables, **When** the user runs the extractor, **Then** both output tables are created and populated with the expected number of rows and matching parent-child identifiers.
2. **Given** a column XPath such as `"Name/text()"`, **When** the extractor evaluates it, **Then** the value is taken from the current record element and not from an unrelated element elsewhere in the document.
3. **Given** a parent record containing child records, **When** the child records are extracted, **Then** the parent element is still available until all of its child records have been processed.
4. **Given** a mapping and XML file with no XSD present, **When** the extractor runs, **Then** extraction succeeds without reading, requiring, or inferring a schema.

---

### User Story 2 - Handle varied and repeated column values (Priority: P1)

A data engineer must map a logical column to several possible source locations because upstream XML is inconsistent: a name may appear under `Name`, `PersonalData/FullName`, or both. They declare multiple XPath expressions for one column and choose how values are combined.

**Why this priority**: Real-world XML is irregular. Flexible per-column extraction is required for the engine to be usable outside a single fixture.

**Independent Test**: Use fixtures where one column has values in multiple locations and run each supported combination strategy, verifying the selected result.

**Acceptance Scenarios**:

1. **Given** a column with multiple XPath expressions and the default strategy, **When** the first expression yields an empty result and a later expression yields a value, **Then** the later non-empty value is used.
2. **Given** the `first` strategy, **When** several expressions match, **Then** the value from the first matching expression is used even if it is empty.
3. **Given** the `concat` strategy, **When** several expressions match, **Then** all matched values are concatenated in declaration/document order.
4. **Given** the `collect` strategy, **When** several expressions or repeated nodes match, **Then** the output is a JSON array containing every matched value.
5. **Given** a column with no matching value, **When** the record is written, **Then** the column is stored as NULL rather than an empty string.

---

### User Story 3 - Stream very large XML files with bounded memory (Priority: P1)

A data engineer needs to process an XML export that is larger than available memory. They configure a batch size and expect the tool to read the file incrementally, write records in batches, release processed XML nodes, and finish without loading the whole document.

**Why this priority**: The primary use case is large files. A correct but memory-unbounded implementation would fail on real data.

**Independent Test**: Process a generated XML file with many records under a configured batch size and verify batch counts, row counts, and that memory use does not scale with total record count.

**Acceptance Scenarios**:

1. **Given** a large XML file and a batch size of 1,000, **When** 10,000 records are extracted, **Then** records are written in 10 batches rather than one row at a time.
2. **Given** a completed record element, **When** extraction advances, **Then** processed elements and unnecessary references are released while ancestors needed by nested records remain available.
3. **Given** multiple output tables, **When** one table's buffer reaches its batch size, **Then** only that table's buffer is flushed and other tables' pending records are preserved.
4. **Given** an input larger than available memory, **When** extraction runs, **Then** memory use remains bounded and does not grow proportionally to the number of records.

---

### User Story 4 - Control data-quality failures (Priority: P2)

A data engineer discovers malformed values in optional or inconsistent XML fields. They configure whether a conversion failure should stop the run or produce NULL, and they need enough context to fix the mapping or the source data.

**Why this priority**: Production data is rarely clean. Predictable error handling makes runs repeatable and diagnosable.

**Independent Test**: Run fixtures containing invalid dates, numbers, and booleans under both error policies and verify stopping behavior, NULL substitution, and error context.

**Acceptance Scenarios**:

1. **Given** the default `fail` policy and an invalid typed value, **When** conversion is attempted, **Then** processing stops and the error identifies the table, column, XPath expression, and original value.
2. **Given** the `null` policy and an invalid typed value, **When** conversion is attempted, **Then** the value is replaced with NULL and processing continues.
3. **Given** a missing element, empty text, or whitespace-only text, **When** the column is converted, **Then** the result is consistently NULL regardless of target type.

---

### User Story 5 - Run via API or CLI and inspect results (Priority: P2)

A developer embeds the extractor in a script, while an analyst uses a command-line tool. Both need to point at a mapping, optionally override the output database, see per-table statistics, and export results to Parquet for downstream use.

**Why this priority**: The engine must be operable by both programmatic and command-line users to fit existing data workflows.

**Independent Test**: Run the same mapping through the Python API and CLI, compare outputs and statistics, then export all mapped tables to Parquet and read them back.

**Acceptance Scenarios**:

1. **Given** a mapping file, **When** the user invokes the `run` command with no output override, **Then** the configured output database is written.
2. **Given** a mapping file and an output override, **When** the user invokes `run`, **Then** results are written to the override path instead.
3. **Given** a successful run, **When** it completes, **Then** the user sees records extracted per table, batches written per table, total records processed, and processing duration.
4. **Given** an existing output database, **When** the user invokes the `export` command, **Then** one Parquet file is produced per mapped table in the requested directory.
5. **Given** exported Parquet files, **When** they are read back, **Then** row counts, column names, column order, and declared data types match the extracted tables.

---

### Edge Cases

- A source XPath matches zero elements: the run completes successfully with zero records for that table.
- The source file is missing, unreadable, or not well-formed XML: the run fails with a clear message naming the file and the underlying parse problem.
- The mapping is missing required keys, declares an unsupported type or strategy, uses duplicate table names, or references an invalid XPath: validation fails before any table is written, naming the offending table or column.
- A column's XPath matches multiple nodes with a single-value strategy: the first applicable node is used according to the strategy.
- A column's XPath requires access to a document-wide aggregate, a previously cleared sibling, or an ancestor outside the retained ancestor chain: the MVP documents this as unsupported rather than silently returning wrong data.
- Nested records are encountered before their parent record is complete: child records are emitted without clearing the parent, and the parent is cleared only after all of its descendants have been processed.
- A record has more than one source match for the same table: each match produces a separate row.
- The final buffer for each table contains fewer records than the batch size: it is flushed before the run completes.
- The output database parent directory does not exist or is not writable: the run fails before extraction with an actionable message.
- Tables already exist in the target database: mapped output tables are replaced on each run so repeated runs are deterministic.
- The XML uses namespaces: namespace-aware mapping behavior is limited in the MVP and is documented; mappings without namespace prefixes are the supported default.
- A conversion succeeds only after trimming surrounding whitespace: leading and trailing whitespace is ignored for typed values and preserved for text values.
- The output path equals the input XML path or the mapping path: the run refuses to proceed to avoid destroying the source.

## Requirements *(mandatory)*

### Functional Requirements

**Mapping configuration**

- **FR-001**: The system MUST load extraction definitions from a YAML mapping file.
- **FR-002**: The mapping MUST support a source file location, an optional batch size, an optional output database location, and one or more table definitions.
- **FR-003**: Each table definition MUST include a table name, a source XPath selecting record elements, and at least one named column.
- **FR-004**: Each column definition MUST include one XPath expression or an ordered list of XPath expressions plus an explicit target type.
- **FR-005**: The system MUST validate mappings before extraction, rejecting missing required fields, unknown types, unknown strategies, duplicate table names, empty column sets, malformed XPath expressions, and invalid batch sizes with errors that name the offending table or column.
- **FR-006**: The system MUST resolve relative source and output paths against the mapping file's directory, while allowing absolute paths.
- **FR-007**: The system MUST accept a command-line output path override that takes precedence over the mapping's output setting.
- **FR-008**: The system MUST NOT require, read, or infer an XSD or any other schema for extraction.

**Record and value extraction**

- **FR-009**: The system MUST evaluate each table's source XPath against the XML document to identify record elements.
- **FR-010**: The system MUST evaluate every column XPath relative to the current record element, not relative to the document root.
- **FR-011**: The system MUST support single and multiple XPath expressions per column.
- **FR-012**: The system MUST support the strategies `first_non_empty` (default), `first`, `concat`, and `collect`.
- **FR-013**: `first_non_empty` MUST return the first non-empty value in expression order; if none is non-empty, the result MUST be NULL.
- **FR-014**: `first` MUST return the first expression's first matched value, even when empty, and MUST return NULL when no expression matches.
- **FR-015**: `concat` MUST evaluate expressions in declaration order, concatenate all matched values from each expression in document order, insert no implicit separator, omit NULL/empty results, and yield NULL when nothing matches.
- **FR-016**: `collect` MUST return all matched values as a JSON array when at least one value matches, and MUST return NULL when there are no matches.
- **FR-017**: The system MUST treat a missing element, empty text, and whitespace-only text as missing input consistently across all types.
- **FR-018**: For text columns, the system MUST preserve meaningful internal and surrounding text as present in the source, except that completely whitespace-only values are treated as missing.

**Streaming and buffering**

- **FR-019**: The system MUST parse XML incrementally so that the entire document is never held in memory at once.
- **FR-020**: The system MUST recognize a record as complete when its element's end event is reached and emit exactly one row per completed record match.
- **FR-021**: The system MUST support nested record types and MUST keep a parent element available until all child records beneath it have been processed before clearing it.
- **FR-022**: The system MUST maintain an independent buffer for each output table.
- **FR-023**: The system MUST flush a table's buffer when it reaches the configured batch size and MUST flush all remaining records before completion.
- **FR-024**: The system MUST release processed XML elements and unnecessary references to keep memory bounded.
- **FR-025**: The system MUST allow records from different tables to be emitted in document order without requiring their ancestors or siblings to remain indefinitely.

**Storage and insertion**

- **FR-026**: The system MUST create output tables in a DuckDB database using the table names, column names, and explicit types from the mapping.
- **FR-027**: The system MUST insert records in batches rather than one row at a time.
- **FR-028**: The system MUST support a configurable output database path, defaulting to a documented location when none is provided.
- **FR-029**: The system MUST replace mapped output tables on each run so repeated runs are deterministic.
- **FR-030**: The system MUST commit completed batches in transactions and close all database and file resources cleanly, including on failure.
- **FR-031**: The system MUST refuse to run when the resolved output database path would overwrite the source XML or the mapping file.

**Type conversion**

- **FR-032**: The system MUST support target types `VARCHAR`, `INTEGER`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP`, and `JSON`.
- **FR-033**: The system MUST convert numeric text to the declared integer or floating-point type and MUST reject values outside the type's representable range or with invalid syntax.
- **FR-034**: The system MUST accept case-insensitive `true`/`false`, `1`/`0`, and `yes`/`no` for booleans and MUST reject other values.
- **FR-035**: The system MUST accept ISO-8601 calendar dates (`YYYY-MM-DD`) for `DATE` and ISO-8601 date-time values for `TIMESTAMP`.
- **FR-036**: The system MUST validate `JSON` values and store them as valid JSON rather than arbitrary text.
- **FR-037**: Conversion errors MUST identify the table name, column name, XPath expression that produced the value, and the original value.
- **FR-038**: The system MUST support an error policy of `fail` (default) or `null`; `fail` stops execution, and `null` substitutes NULL and continues.
- **FR-039**: The error policy MUST be configurable per run.

**Interfaces and export**

- **FR-040**: The system MUST expose a Python API that constructs an extractor from a YAML file and runs extraction.
- **FR-041**: The system MUST expose a command-line `run` command that accepts a mapping file and an optional `--output` database path.
- **FR-042**: The system MUST print or otherwise return per-table extracted record counts, per-table batch counts, total records processed, and processing duration.
- **FR-043**: The system MUST expose a command-line `export` command that accepts a mapping file and an output directory and writes one Parquet file per mapped table.
- **FR-044**: Parquet exports MUST preserve table row counts, column names, column order, and declared data types.
- **FR-045**: The system MUST locate the tables to export from the mapping's configured output database and MUST fail with a clear message when that database or a mapped table is missing.
- **FR-046**: On failure, the system MUST report the failure clearly, close all open resources, and MUST NOT present the run as successful or emit statistics as if all tables completed.

### Key Entities

- **Mapping**: The user-authored declaration of source data, execution settings, and output tables. It is the sole source of truth for extraction shape and types.
- **Table Definition**: A named output relation with a record-selecting XPath and an ordered set of column definitions.
- **Column Definition**: A named output field with one or more XPath expressions, a combination strategy, and an explicit target type.
- **Record**: One XML element matched by a table's source XPath, converted into one row.
- **Batch**: A bounded collection of converted rows for one table, written as a unit.
- **Extraction Run**: One execution over one source file, producing statistics, a target database, and optional Parquet artifacts.
- **Export Artifact**: One Parquet file corresponding to one mapped table.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can declare two or more related tables in one mapping and extract correct rows and parent-child identifiers from a single XML file with no schema file present.
- **SC-002**: 100% of column values in the acceptance fixtures are derived from the current record element or its in-scope ancestors, never from unrelated document locations.
- **SC-003**: All four combination strategies produce their documented results across single-expression, multi-expression, repeated-node, empty, and missing-value fixtures.
- **SC-004**: Processing a 100,000-record XML file uses memory that does not grow proportionally with record count, as measured against a 10,000-record baseline with the same batch size.
- **SC-005**: With 10,000 records and a batch size of 1,000, the run reports 10 batches per table and exactly 10,000 inserted rows.
- **SC-006**: Under the `fail` policy, 100% of invalid typed values stop the run with table, column, XPath, and original value reported; under the `null` policy, 100% of invalid typed values become NULL and the run completes.
- **SC-007**: Reported per-table record counts and batch counts exactly match the resulting database and export contents for every acceptance fixture.
- **SC-008**: Every mapped table exports to Parquet with matching row count, column names, column order, and target types, verifiable by reading the files back.
- **SC-009**: A new user can install the tool, edit the example mapping, and complete a first extraction in under 10 minutes using only the README.
- **SC-010**: Extraction succeeds on fixtures where no XSD file exists anywhere in the project or input directory.

## Assumptions

- Users are comfortable writing YAML and XPath expressions; the tool does not provide a graphical mapping editor.
- The XML source is well-formed; malformed XML is reported as a fatal error rather than repaired.
- Source file paths in mappings are resolved relative to the mapping file, so examples are portable when the directory is moved.
- When no output database is configured or overridden, the default is `output.duckdb` in the mapping file's directory.
- When no batch size is configured, the default is 10,000 records per table.
- Multiple records for the same logical entity produce multiple rows; the MVP does not deduplicate or infer uniqueness.
- `concat` uses no implicit delimiter; users can include literal separators in their XPath expressions or source data. An explicit separator setting is out of scope.
- Typed conversions trim surrounding whitespace before parsing; text values remain as authored.
- Dates and timestamps follow ISO-8601 conventions, and booleans accept the common textual/numeric forms listed in FR-034.
- Each run replaces mapped tables in the target database; historical versions and incremental appends are out of scope.
- The implementation is delivered as a locally installable Python package for Python 3.11+ using the user-mandated libraries lxml, DuckDB, and PyYAML, with pytest for tests. These are delivery constraints, not additional user-facing features.
- The CLI is the only supported operational interface; web services, APIs, GUIs, distributed execution, and Polars are out of scope.
- The MVP supports the XPath subset available through lxml relative to a live record element. Document-wide aggregates, arbitrary document-root queries inside column mappings, and access to already-cleared nodes are documented limitations.
- XSD-based validation, schema inference, and automatic type discovery are explicitly out of scope; explicit mapping types are authoritative.
- Namespace-aware mappings are a known MVP limitation; the default supported inputs use unqualified element names.

## Limitations

- Column XPath expressions are evaluated relative to the current record element. Expressions that require the entire document, global aggregates, preceding or following siblings already released by streaming, or ancestors outside the still-retained ancestor chain are unsupported and must be documented rather than emulated.
- Parent/ancestor access such as `../@id` works only while the relevant ancestor remains in the live parse tree; the engine guarantees this for ancestors of records that are still being emitted but not for arbitrary previously completed branches.
- XPath results are converted to scalar values; node-set strategies beyond the four documented combination strategies are out of scope.
- The tool does not resolve cross-table foreign keys automatically; users map them explicitly with XPath expressions.
- Namespace prefixes require explicit handling that is not part of the MVP's default mapping syntax.
