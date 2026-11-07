# Tasks: Declarative XML-to-Relational Extraction Engine

**Input**: Design documents from `/specs/001-xml-to-relational-engine/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Included because the feature specification explicitly requires pytest coverage for parsing, XPath strategies, conversion, batching, large files, Parquet, and XSD independence.

**Organization**: Tasks are grouped by user story so each priority slice can be implemented, tested, and validated independently after the shared foundation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story label for story phases only (`US1`–`US5`)
- Every task includes exact repository-relative file paths.

## Path Conventions

Single project:

```text
src/xml2rel/
tests/
examples/
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize the installable package, test harness, examples, and fixtures.

- [ ] T001 Create `pyproject.toml` with Python `>=3.11`, dependencies `lxml`, `duckdb`, `PyYAML`, dev dependency `pytest`, `xml2rel = "xml2rel.cli:main"` entry point, setuptools `src` layout, and pytest settings including `pythonpath = ["src"]`.
- [ ] T002 Create the package skeleton with `src/xml2rel/__init__.py`, `src/xml2rel/__main__.py`, `src/xml2rel/backend/__init__.py`, and empty module files `cli.py`, `config.py`, `parser.py`, `xpath.py`, `converter.py`, `buffers.py`, `engine.py`, `backend/duckdb.py`.
- [ ] T003 [P] Write `README.md` with installation, mapping syntax summary, Python API, CLI usage, statistics, Parquet export, and MVP limitations; leave implementation-specific command examples aligned with `contracts/cli.md`.
- [ ] T004 [P] Validate and update `examples/input.xml` and `examples/mapping.yaml` so the example contains nested patients/appointments, a fallback name, repeated phones, a missing description, `../@id`, and `batch_size: 2`.
- [ ] T005 [P] Validate and update test fixtures `tests/fixtures/patients.xml`, `tests/fixtures/mapping.yaml`, `tests/fixtures/errors.xml`, `tests/fixtures/mapping_fail.yaml`, `tests/fixtures/mapping_null.yaml`, and `tests/fixtures/no_xsd_mapping.yaml`.
- [ ] T006 [P] Create `tests/conftest.py` with a `fixtures_dir` helper, a temporary DuckDB path factory using `tmp_path`, and a helper that returns the example mapping path.

**Checkpoint**: The package is installable in editable mode and the test/data layout exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared configuration, XPath, conversion, buffering, and storage primitives required by every user story.

**⚠️ CRITICAL**: No user story implementation should begin until this phase is complete.

- [ ] T007 [P] Define configuration dataclasses and enums in `src/xml2rel/config.py`: `MappingConfig`, `SourceConfig`, `Settings`, `TableConfig`, `ColumnConfig`, `ColumnStrategy`, `ColumnType`, and `ErrorPolicy` matching `data-model.md`.
- [ ] T008 Implement YAML loading, strict validation, and path resolution in `src/xml2rel/config.py`: use `yaml.safe_load`; reject unknown keys; enforce table/column names matching `^[A-Za-z_][A-Za-z0-9_]*$`; require `batch_size > 0` (default 10,000); accept `error_policy` `fail` or `null` (default `fail`); validate all type/strategy enums; compile every column XPath with `lxml.etree.XPath`; resolve `source.file` and `output` relative to the mapping file (default `output.duckdb`); refuse an output path equal to the source XML or mapping; reject callback/script/plugin keys as unknown (FR-047).
- [ ] T009 [P] Implement `SourcePathMatcher` in `src/xml2rel/parser.py`: parse absolute/relative location paths with `/`, `//`, `*`, element names, and attribute predicates; report the original expression and reject namespaces, positional predicates, functions, unions, `.`/`..`, and child-text predicates with a `ConfigError`.
- [ ] T010 [P] Implement XPath result normalization in `src/xml2rel/xpath.py`: evaluate one expression relative to a record element, normalize elements to full text, stringify scalar results, map booleans to `"true"`/`"false"`, and expose a helper that identifies blank/missing values using `value is None or value.strip() == ""`.
- [ ] T011 [P] Implement `src/xml2rel/converter.py` with a `ConversionError` containing `table`, `column`, `xpath`, `value`, `target_type`, and `reason`, plus conversions for `VARCHAR`, `INTEGER`, `BIGINT`, `DOUBLE`, `BOOLEAN`, `DATE`, `TIMESTAMP`, and `JSON` as specified in `data-model.md` and research R4.
- [ ] T012 [P] Implement `TableBuffer` in `src/xml2rel/buffers.py`: store converted rows, track `records_extracted` and `batches_written`, flush when `len(rows) >= batch_size`, and flush the final partial batch.
- [ ] T013 [P] Implement `DuckDBBackend` in `src/xml2rel/backend/duckdb.py`: create the database parent directory; quote identifiers; map `ColumnType` to DuckDB SQL types; create/replace mapped tables; insert a logical batch with parameterized multi-row `INSERT` statements chunked to at most 5,000 placeholders; use explicit `BEGIN`/`COMMIT` with `ROLLBACK` on failure; cast JSON placeholders; expose table-existence checks and `close()`; define `BackendError`.

**Checkpoint**: Shared primitives are unit-ready; user stories can start.

---

## Phase 3: User Story 1 - Extract multiple related tables from one XML file (Priority: P1) 🎯 MVP

**Goal**: Declare two related tables in YAML, stream the XML, evaluate relative column XPath expressions, and populate DuckDB with correct parent-child identifiers without any XSD.

**Independent Test**: Run `examples/mapping.yaml` against `examples/input.xml` and verify 4 patients, 4 appointments, correct `patient_id` links, relative name/date values, and no XSD file present.

### Tests for User Story 1

- [ ] T014 [P] [US1] Write parser tests in `tests/test_parser.py` for record extraction on end events, relative `Name/text()` evaluation, `../@id` parent access, zero-match tables, nested appointments, and malformed/missing XML errors.
- [ ] T015 [P] [US1] Write engine integration tests in `tests/test_engine.py` for multi-table creation and row counts, parent-child identifiers, table replacement on repeated runs, output-path safety, rejection of callback/script keys, invalid config values (batch size, enums, identifiers, malformed XPath), and extraction with no XSD present.

### Implementation for User Story 1

- [ ] T016 [US1] Implement the streaming loop in `src/xml2rel/parser.py`: `lxml.etree.iterparse` with `start`/`end` events, a frame stack, start-time source matching, end-time record emission through a callback, and the open-record-ancestor clearing rule from research R2.
- [ ] T017 [US1] Implement `XMLExtractor.from_yaml()` and `run()` orchestration in `src/xml2rel/engine.py`: load config, open the backend, create tables, stream records, convert values, append to per-table buffers, flush, and close resources in `finally`.
- [ ] T018 [US1] Implement `RunStats` and `TableStats` in `src/xml2rel/engine.py` and export `XMLExtractor`, `RunStats`, `TableStats`, `ConfigError`, `ExtractionError`, `ConversionError`, and `BackendError` from `src/xml2rel/__init__.py`.
- [ ] T019 [US1] Wire table creation and batch insertion into `src/xml2rel/engine.py` and `src/xml2rel/backend/duckdb.py`, ensuring rows are converted in column declaration order and inserted through `DuckDBBackend.insert_batch()`.
- [ ] T020 [US1] Run `pytest tests/test_parser.py tests/test_engine.py -q` and fix all User Story 1 failures, including the no-XSD scenario.

**Checkpoint**: User Story 1 is the working MVP and can be demonstrated with `examples/mapping.yaml`.

---

## Phase 4: User Story 2 - Handle varied and repeated column values (Priority: P1)

**Goal**: Support one or many XPath expressions per column with `first_non_empty`, `first`, `concat`, and `collect`, including JSON arrays and consistent NULL behavior.

**Independent Test**: Use a fixture whose name exists in `Name` or `PersonalData/FullName`, run all four strategies, and verify each documented result plus missing/empty behavior.

### Tests for User Story 2

- [ ] T021 [P] [US2] Write strategy tests in `tests/test_xpath.py` covering single and multiple expressions, `first_non_empty` fallback, `first` with an empty first match, `concat` ordering without a separator, `collect` JSON arrays, repeated nodes, and no-match NULL.

### Implementation for User Story 2

- [ ] T022 [US2] Implement the multi-expression resolver in `src/xml2rel/xpath.py`: declaration-order evaluation, value normalization, `first_non_empty`, `first`, `concat` with blank omission, and `collect` via compact JSON serialization.
- [ ] T023 [US2] Integrate the resolver into `src/xml2rel/parser.py` so every column uses the configured strategy, and ensure `collect` stays JSON text for both `VARCHAR` and `JSON` targets.
- [ ] T024 [US2] Extend `tests/fixtures/mapping.yaml` and `tests/test_engine.py` assertions to cover the fallback name and `phones` JSON array end to end.
- [ ] T025 [US2] Run `pytest tests/test_xpath.py tests/test_engine.py -q` and fix all strategy failures.

**Checkpoint**: All four strategies work independently and through the engine.

---

## Phase 5: User Story 3 - Stream very large XML files with bounded memory (Priority: P1)

**Goal**: Prove incremental processing, independent per-table buffers, configured batch flushes, and safe release of processed XML while retaining nested parent data.

**Independent Test**: Process a generated 10,000-record file with `batch_size: 1000`, verify 10 batches and exact row counts, and confirm the open frame stack and tracked allocations stay bounded.

### Tests for User Story 3

- [ ] T026 [P] [US3] Write parser streaming tests in `tests/test_parser.py` for shallow frame-stack depth, processed-element detachment, nested-subtree retention while an ancestor record is open, independent table buffers, and immediate flush at the batch threshold.
- [ ] T027 [P] [US3] Write engine large-file tests in `tests/test_engine.py` using a generated XML file, `batch_size: 1000`, 10,000 records, exact 10/10 batch counts, and a generous `tracemalloc` ceiling compared with a smaller baseline.

### Implementation for User Story 3

- [ ] T028 [US3] Harden the clear/detach logic in `src/xml2rel/parser.py` so non-record branches are cleared and detached only when no ancestor frame is a record, and retained subtrees are released when the outer record ends.
- [ ] T029 [US3] Implement and verify per-table buffer flushing in `src/xml2rel/engine.py` and `src/xml2rel/buffers.py`, including final partial flushes at document end and accurate `batches_written`.
- [ ] T030 [US3] Add a reusable large-XML generator helper to `tests/conftest.py` that writes N records to `tmp_path` without constructing the document in memory.
- [ ] T031 [US3] Run `pytest tests/test_parser.py tests/test_engine.py -q -k "large or batch or stream"` and tune the tests or implementation until they pass without skips.

**Checkpoint**: Large inputs stream with bounded memory and reliable batch counts.

---

## Phase 6: User Story 4 - Control data-quality failures (Priority: P2)

**Goal**: Convert all supported types with precise error context and honor `fail` versus `null` policies.

**Independent Test**: Run `tests/fixtures/errors.xml` with `mapping_fail.yaml` and `mapping_null.yaml`; `fail` stops with table/column/XPath/value context, while `null` completes with NULLs.

### Tests for User Story 4

- [ ] T032 [P] [US4] Write converter tests in `tests/test_converter.py` for every type, integer ranges, finite doubles, boolean spellings, ISO dates/timestamps including `Z`/offset normalization, JSON validation, blank/missing values, and `ConversionError` fields.
- [ ] T033 [P] [US4] Write policy integration tests in `tests/test_engine.py` using `mapping_fail.yaml` and `mapping_null.yaml`, asserting the error context under `fail` and NULL substitution with continued processing under `null`.

### Implementation for User Story 4

- [ ] T034 [US4] Complete type conversion formats and range checks in `src/xml2rel/converter.py`, including typed whitespace trimming, naive UTC timestamps, canonical JSON, and non-finite double rejection.
- [ ] T035 [US4] Implement the error-policy branch in `src/xml2rel/engine.py` and `src/xml2rel/converter.py`: `fail` propagates `ConversionError`; `null` stores `None` and continues; load the policy from `settings.error_policy`.
- [ ] T036 [US4] Run `pytest tests/test_converter.py tests/test_engine.py -q -k "convert or fail or null or error"` and fix all failures.

**Checkpoint**: Invalid data is handled predictably under both policies.

---

## Phase 7: User Story 5 - Run via API or CLI and inspect results (Priority: P2)

**Goal**: Provide `xml2rel run`, `xml2rel export`, the documented Python API, execution statistics, and Parquet export with preserved schema.

**Independent Test**: Run the same mapping through the API and CLI, compare statistics and database rows, export all tables to Parquet, and verify row counts, column order, and declared types after reading the files back.

### Tests for User Story 5

- [ ] T037 [P] [US5] Write CLI and API tests in `tests/test_engine.py` for `run` with and without `--output`, statistics fields, exit codes, argument errors, `from_yaml`/`run`/`export_parquet`, one-run-per-extractor behavior, and effective `output_path`.
- [ ] T038 [P] [US5] Write Parquet tests in `tests/test_engine.py` for one file per mapped table, output-directory creation, row counts, column order, inferred DuckDB types, and clear errors for missing databases/tables.

### Implementation for User Story 5

- [ ] T039 [US5] Implement `src/xml2rel/cli.py` and `src/xml2rel/__main__.py` with argparse `run MAPPING [--output DATABASE]`, `export MAPPING --output-dir DIRECTORY`, `--version`, help, stdout statistics, stderr errors, and exit codes 0/1/2.
- [ ] T040 [US5] Implement statistics formatting in `src/xml2rel/cli.py` so output includes per-table records, per-table batches, total records, duration, and effective output path.
- [ ] T041 [US5] Implement `export_parquet()` in `src/xml2rel/engine.py` and `export_table_parquet()` in `src/xml2rel/backend/duckdb.py` using DuckDB `COPY (SELECT * FROM "table") TO '<dir>/<table>.parquet' (FORMAT PARQUET)`, with preflight checks for the database, every mapped table, and a writable output directory.
- [ ] T042 [US5] Implement effective output-path tracking in `src/xml2rel/engine.py`: `run(output=...)` overrides the mapping output and updates `output_path` for later export; expose `mapping_path` and `output_path`.
- [ ] T043 [US5] Update `README.md` with final CLI examples, statistics sample, Parquet export, Python post-processing guidance, and the known limitations.
- [ ] T044 [US5] Run `pytest tests/test_engine.py -q -k "cli or api or parquet or stats or export"` and fix all failures.

**Checkpoint**: API, CLI, statistics, and Parquet export work end to end.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all stories and delivery readiness.

- [ ] T045 Run the full suite with `pytest -q tests/` and fix every failure; no test may be skipped or mocked.
- [ ] T046 Review every module under `src/xml2rel/` for complete type hints, unused imports, placeholder code, and unfinished markers; remove or implement anything incomplete.
- [ ] T047 [P] Execute the validation scenarios in `specs/001-xml-to-relational-engine/quickstart.md` against `examples/` and confirm the documented outcomes.
- [ ] T048 [P] Verify `examples/mapping.yaml` produces the expected 4 patients/4 appointments, correct parent links, JSON phone arrays, NULL description, and 2/2 batches; confirm no `*.xsd` exists.
- [ ] T049 [P] Verify editable installation from `pyproject.toml` with `pip install -e ".[dev]"`, then confirm `xml2rel --help`, `xml2rel run`, and `xml2rel export` resolve through the entry point.
- [ ] T050 Run a final clean regression: `pytest -q tests/` plus extraction and Parquet export from `examples/`, then report the observed statistics and artifact paths.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Starts immediately.
- **Foundational (Phase 2)**: Depends on Setup; blocks every user story.
- **User Story 1 (Phase 3)**: Depends on Foundational; delivers the MVP.
- **User Story 2 (Phase 4)**: Depends on US1 because it extends `xpath.py` integration.
- **User Story 3 (Phase 5)**: Depends on US1 because it hardens `parser.py` and buffers.
- **User Story 4 (Phase 6)**: Depends on US1 because it extends conversion and engine error handling.
- **User Story 5 (Phase 7)**: Depends on US1; run after US4 so Parquet type assertions cover every type.
- **Polish (Phase 8)**: Depends on all desired stories.

### User Story Dependencies

- **US1**: No story dependency; MVP.
- **US2**: Requires US1; independently testable with `tests/test_xpath.py` and strategy fixtures.
- **US3**: Requires US1; independently testable with generated large input.
- **US4**: Requires US1; independently testable with error fixtures.
- **US5**: Requires US1; independently testable through CLI/API/Parquet.

### Within Each Story

- Tests are written first and must fail before implementation.
- Shared primitives come from Phase 2.
- Parser/engine integration precedes end-to-end assertions.
- Run the story-specific pytest command before moving on.

### Parallel Opportunities

- Setup: T003, T004, T005, T006 are independent files.
- Foundational: T007, T009, T010, T011, T012, T013 target different files; T008 depends on T007.
- US1: T014 and T015 can be written in parallel before T016–T019.
- US3: T026 and T027 target different test files and can run in parallel.
- US4: T032 and T033 target different test files and can run in parallel.
- Polish: T047, T048, T049 do not modify overlapping code files.

## Parallel Example: User Story 1

```bash
# Write both MVP test files together:
Task: "Write parser tests in tests/test_parser.py"
Task: "Write engine integration tests in tests/test_engine.py"

# Then implement parser and engine in sequence:
Task: "Implement streaming loop in src/xml2rel/parser.py"
Task: "Implement XMLExtractor orchestration in src/xml2rel/engine.py"
```

## Parallel Example: User Story 3

```bash
Task: "Write streaming/clearing tests in tests/test_parser.py"
Task: "Write large-file tests in tests/test_engine.py"
```

## Parallel Example: User Story 4

```bash
Task: "Write converter tests in tests/test_converter.py"
Task: "Write policy integration tests in tests/test_engine.py"
```

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Phase 1 (Setup).
2. Complete Phase 2 (Foundational).
3. Complete Phase 3 (US1).
4. Stop and validate: `pytest tests/test_parser.py tests/test_engine.py -q`.
5. Demo the example extraction and confirm no XSD is needed.

### Incremental Delivery

1. Setup + Foundational → shared primitives ready.
2. US1 → multi-table MVP.
3. US2 → flexible value strategies.
4. US3 → large-file and batching guarantees.
5. US4 → data-quality policies.
6. US5 → CLI, statistics, and Parquet.
7. Polish → full regression and quickstart validation.

### Parallel Team Strategy

1. Team completes Setup + Foundational together.
2. One developer completes US1.
3. After US1, US2/US3/US4 can proceed in parallel with coordination on `engine.py`; otherwise follow priority order.
4. US5 follows US1/US4.
5. Whole team runs Phase 8.

## Notes

- `[P]` means different files and no dependency on an incomplete task.
- Tests are required by the specification and must be written before their implementation tasks.
- No task may introduce callbacks, plugins, or pre/post extraction scripts; custom logic is post-processing only.
- Commit after each checkpoint or logical task group.
