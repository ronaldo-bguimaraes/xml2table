# Phase 0 Research: Declarative XML-to-Relational Extraction Engine

**Feature**: `001-xml-to-relational-engine`
**Date**: 2026-11-07

All Technical Context unknowns are resolved below. Each decision is scoped to the MVP; alternatives are listed only where a reasonable engineer might have chosen differently.

## R1. Streaming record selection

**Decision**: Compile each table's source XPath into a `SourcePathMatcher` in `src/xml2rel/source_path.py` that supports absolute/relative location paths, `/` child steps, `//` descendant steps, `*`, element names, and attribute predicates (`[@id]`, `[@id='value']`). Match elements on `iterparse` start events. Config validation compiles every matcher before extraction, and unsupported source syntax is rejected there.

**Rationale**: Calling `lxml` XPath on the root for every element is quadratic and defeats large-file streaming. Pre-evaluating all source matches requires a full document. A structural matcher uses only the current ancestor stack, keeps memory bounded, and handles the source expressions used in the specification, including `/Root/Patient` and `//Patient/Appointment`. Start-time matching is required so the parser knows whether an open ancestor is a record when deciding what can be cleared.

**Alternatives considered**:
- Evaluate the source XPath against the growing root on every end event: correct but O(n²) and unacceptable for the large-file requirement.
- Collect record elements with `root.iter()` after parsing: violates incremental processing.
- Use `ElementPath`/`iterfind`: still needs a traversal root and offers weaker expression control than a compiled stack matcher.
- Fall back to slow XPath for unsupported source constructs: unpredictable performance; explicit validation is safer for an MVP.

**Limitations introduced**: Namespaced source paths, numeric positional predicates, XPath functions, unions, `./..` steps, and predicates that depend on child text are not supported in source paths. Column XPath expressions remain full `lxml` expressions relative to the record.

**Dependency note**: Placing the matcher in `source_path.py` avoids a circular import between `config.py` (which validates mappings) and `parser.py` (which imports configuration types and consumes the matcher).

## R2. Memory-safe clearing of nested records

**Decision**: Maintain a stack of open XML frames. Each frame records the element and the tables it matched at start. On an element's end event, extract all matched records, then clear and detach the element only if no ancestor frame is a record. If an ancestor record is open, retain the subtree because that ancestor's columns may still read it. When the ancestor record itself ends, clear its entire subtree.

**Rationale**: Clearing a parent as soon as any child completes breaks `../@id`, parent columns that read child elements, and nested records. Retaining only subtrees beneath open record ancestors bounds memory by the largest record subtree rather than the document size, while preserving the relationships required by the specification.

**Alternatives considered**:
- Clear every element at its end: simple but breaks parent access; explicitly forbidden by the requirements.
- Keep the whole document: correct but fails bounded-memory goals.
- Statically analyze each column XPath to decide which descendants to keep: more precise but complex and easy to get wrong for the MVP.
- Clear all non-record branches immediately: unsafe because an open ancestor record may reference them.

**Consequences**: A single very large record remains in memory until complete. Previously processed sibling branches are unavailable to later XPath expressions; both behaviors are documented.

## R3. Batch insertion mechanism

**Decision**: Insert each logical batch with parameterized multi-row `INSERT INTO ... VALUES (...), (...)` statements, chunked to at most 5,000 bound parameters per statement, wrapped in an explicit per-batch `BEGIN`/`COMMIT` transaction. No extra dependency is required.

**Rationale**: This avoids one statement per row, keeps values parameterized, works on all supported platforms, and does not force users to install a large Arrow stack. DuckDB prepares and executes each chunk efficiently. A conservative parameter cap avoids SQL/placeholder limits with wide tables.

**Alternatives considered**:
- `pyarrow.Table` plus `INSERT ... SELECT * FROM arrow_table`: efficient, but adds a heavy mandatory dependency for an MVP and requires a separate code path and tests.
- `executemany`: prepared once but still row-oriented internally; less clearly batched than multi-row values.
- `duckdb.Appender`: fast but not consistently exposed across DuckDB Python versions and weaker for explicit typing/error context.
- CSV staging: extra I/O and cleanup complexity.

## R4. Type conversion semantics

**Decision**: Convert in Python before binding parameters. Trim surrounding whitespace for every typed value; treat `None`, empty string, and whitespace-only text as missing → `NULL`. Support:
- `VARCHAR`: text preserved as authored when non-blank.
- `INTEGER`: base-10 integer, range -2,147,483,648 to 2,147,483,647.
- `BIGINT`: base-10 integer, 64-bit signed range.
- `DOUBLE`: finite floating-point value; reject `NaN`/infinity.
- `BOOLEAN`: case-insensitive `true`/`false`, `1`/`0`, `yes`/`no`.
- `DATE`: ISO-8601 `YYYY-MM-DD`.
- `TIMESTAMP`: ISO-8601 date-time; `Z` and numeric offsets are normalized to UTC and stored as a naive UTC datetime.
- `JSON`: parse with `json.loads`, reject invalid JSON, store a canonical compact JSON string.

**Rationale**: Explicit, documented formats make mappings portable and errors testable. Python-side conversion produces precise context (`table`, `column`, XPath, original value, target type) that raw database casts do not.

**Alternatives considered**:
- Let DuckDB cast strings on insert: loses per-value context and mixes policies.
- Accept locale-specific dates/booleans: ambiguous and hard to test.
- Preserve timezone-aware timestamps: the supported `TIMESTAMP` type has no timezone; normalizing to naive UTC is deterministic.
- Treat whitespace-only text as a string: conflicts with the specification's consistent missing-value rule.

## R5. Multiple-XPath strategies and JSON

**Decision**: Evaluate expressions in declaration order. Normalize each result to a list of strings. `first_non_empty` returns the first non-blank value; `first` returns the first value from the first expression that yields at least one result, even when that value is blank; `concat` joins all non-blank values with no separator; `collect` returns `json.dumps(values)` for all matches. All strategies return `None` when there are no usable matches. `collect` is JSON text even for `VARCHAR`; a `JSON` target validates/canonicalizes it.

**Spec clarification needed**: FR-014's phrase "the first expression's first matched value" does not explicitly say whether a later expression is consulted when the first yields no result. This plan adopts "first expression that yields any result"; the spec should be updated to match before implementation.

**Rationale**: These semantics are deterministic and directly testable. Producing JSON text for `collect` satisfies the required "JSON array" behavior without requiring a JSON-native Python column in every backend. Returning `None` for no matches keeps missing-value handling uniform.

**Alternatives considered**:
- `collect` returns `[]` for no matches: conflicts with the uniform NULL-for-missing rule; users can distinguish missing from an explicitly empty array only if the source provides one.
- Automatic delimiter for `concat`: not specified; a delimiter can be embedded in the mapping/data, and adding a setting is out of scope.
- Native Python lists bound to DuckDB JSON: DuckDB accepts JSON strings more predictably through parameter binding.

## R6. Error policy

**Decision**: A `ConversionError` carries table, column, XPath label, original value, target type, and the underlying parse message. With `fail`, it propagates and stops the run after flushing nothing further; already committed batches remain. With `null`, the engine records a NULL for that value and continues. The policy is configured as `settings.error_policy` and defaults to `fail`.

**Rationale**: `fail` must make the run visibly unsuccessful, while `null` must allow partial data quality. Per-value substitution matches the requirement and avoids dropping an otherwise valid row. Per-batch commits bound transaction size but mean a failed run can leave earlier batches; this is documented as MVP behavior.

**Alternatives considered**:
- Wrap the whole run in one transaction: memory and lock costs grow with input size; not appropriate for streaming.
- Drop the entire row on a bad value: not requested and loses usable data.
- Continue silently: hides data-quality problems.

## R7. Parquet export

**Decision**: The `export` command reads an explicit `database` path when supplied and otherwise the mapping's configured output database, then runs DuckDB `COPY (SELECT * FROM "table") TO '<output-dir>/<table>.parquet' (FORMAT PARQUET)` for every mapped table. The CLI exposes `--database` for the explicit case; the Python API exposes `database=None`. It creates the output directory, rejects missing databases/tables, and refuses unsafe table names at validation time. It never implicitly reuses a prior run override.

**Rationale**: DuckDB's Parquet writer preserves schema and types without an extra dependency and handles large tables efficiently. One file per mapped table matches the requirement.

**Alternatives considered**:
- PyArrow Parquet writer: extra dependency and duplicate schema handling.
- Export during `run`: the interface requires an explicit export command; separating it also allows re-export.
- Reading the XML again during export: wasteful and can diverge from the database.

## R8. Configuration shape and defaults

**Decision**: Support this shape:

```yaml
source:
  file: input.xml
settings:
  batch_size: 10000          # optional, default 10000
  error_policy: fail         # optional, fail|null
output: output.duckdb        # optional, relative to mapping file
tables:
  name:
    source: "//Record"
    columns:
      column:
        xpath: "..."         # string or non-empty list
        strategy: first_non_empty  # optional
        type: VARCHAR        # required
```

Load YAML with a strict safe loader that rejects duplicate mapping keys (including duplicate table and column names) instead of silently keeping the last value. Reject unknown keys, invalid identifiers (`^[A-Za-z_][A-Za-z0-9_]*$`), unsupported types/strategies, empty column sets, invalid batch sizes, non-string XPaths, and invalid XPath syntax. Resolve source/output paths relative to the mapping file; CLI `--output` overrides `output` for a run.

**Rationale**: A strict schema catches typos early and keeps SQL identifiers and Parquet file names safe. The example in the specification remains valid. Defaults keep the smallest mapping working.

**Alternatives considered**:
- Allow arbitrary keys for forward compatibility: silently hides mistakes in an MVP.
- Per-table batch sizes: not requested; global setting is sufficient.
- Nested `output.database`: the flat `output` key is simpler and matches the CLI override concept.

## R9. Large-file verification

**Decision**: Add a test that generates a temporary XML file with 100,000 records and a 10,000-record baseline, processes both with the same small batch size, verifies row and batch counts, and uses `tracemalloc` to confirm peak allocations do not scale proportionally with record count. Complement it with a parser-level test that asserts the open frame stack stays shallow and that processed elements are detached.

**Rationale**: A memory assertion alone can be flaky, so the suite combines a behavioral streaming assertion (bounded frame stack, incremental callbacks) with a generous allocation ceiling. This demonstrates the requirement without depending on machine-specific RSS.

**Alternatives considered**:
- Only run a large file and check completion: does not prove incremental behavior.
- Assert exact RSS: platform- and allocator-dependent.
- Skip the large-file test: violates the testing requirements.

## R10. XSD independence

**Decision**: No code path discovers, opens, validates against, or infers from `.xsd` files. The test suite includes a fixture directory with no XSD and an extraction test that succeeds there.

**Rationale**: The mapping is the sole source of truth. This keeps the tool usable when source schemas are absent or stale.

**Alternatives considered**: Optional XSD validation is explicitly outside MVP scope.

## R11. Namespace handling

**Decision**: Treat namespace-aware mappings as an MVP limitation. The default supported input uses unqualified element names. A source path containing a namespace prefix is rejected by the source matcher with a clear message; column XPath expressions containing prefixes will fail at evaluation with the underlying `lxml` error.

**Rationale**: Correct namespace mapping requires a user-supplied prefix map and increases configuration scope. Documenting the limitation is preferable to silently matching the wrong nodes.

**Alternatives considered**: A `namespaces` mapping key and prefix resolution is a natural future extension but is not required by the specification.

## R12. Resource lifecycle

**Decision**: The engine owns one DuckDB connection per run/export, uses `try/finally` to close it, and rolls back an open batch transaction on failure. `XMLExtractor.run()` may be called once per extractor instance; a second call raises `RuntimeError` with a clear message. Export opens a fresh connection to the selected database and closes it.

**Rationale**: Predictable cleanup is required by the specification and avoids locked database files on Windows. Preventing repeated `run()` calls avoids ambiguous "replace tables again" behavior in the MVP.

**Alternatives considered**: Reusable extractor instances with reset semantics add state complexity without a user requirement.

## R13. Custom logic and code hooks

**Decision**: Keep extraction declarative. The MVP does not execute user-supplied callbacks, plugins, or pre/post scripts. Users who need domain-specific logic do it after extraction with Python against the DuckDB database or Parquet exports.

**Rationale**: The specification's goal is a lightweight declarative engine. Adding execution hooks would expand the public API, error model, security surface, and test matrix beyond MVP scope. The API already returns the output path and statistics, so post-processing is straightforward.

**Alternatives considered**:
- Per-row or per-column Python callbacks: useful, but a material feature expansion with serialization and failure-policy questions.
- YAML-embedded expressions/SQL: introduces an expression language and injection concerns.
- External pre/post scripts: easiest to add later, but still outside the MVP.

**Consequences**: A mapping that declares callback/script/plugin keys is rejected as an unknown key. This decision was confirmed during clarification on 2026-11-07.
