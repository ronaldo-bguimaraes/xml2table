# xml2rel Constitution

## Core Principles

### I. Declarative Mapping as Source of Truth

The mapping artifact is the sole authority over tables, columns, XPaths, combination
strategies, and target SQL types. The engine MUST NOT require, read, or infer an XSD.
Unknown keys, duplicate keys, invalid identifiers, and unsupported XPath constructs
MUST be rejected during validation, before any record is parsed. Target types MUST be
declared explicitly; inferring schema from data is prohibited.

Rationale: a single, explicit, reviewable contract keeps runs reproducible and prevents
silent behavior changes when input data shifts.

### II. Streaming, Bounded-Memory Processing

XML input MUST be processed with a streaming parser; the engine MUST NOT materialize the
entire document. Memory held by a record MUST be released as soon as that record and
the branches that depend on it have been emitted. Per-table buffers MUST be bounded by
the configured batch size, and each batch MUST be flushed independently. Any case that
necessarily breaks bounded memory (for example, a single very large record) MUST be
documented in the project limitations.

Rationale: the tool targets files larger than memory; a regression to whole-document
loading silently converts a usable pipeline into an outage.

### III. Bidirectional Transformations (NON-NEGOTIABLE)

Every conversion boundary in the pipeline — XML ↔ canonical AST (xast) ↔ normalized
document ↔ relational/Parquet output — MUST define both directions. A boundary MAY be
one-way only when the loss is explicitly declared, enumerated, and versioned.

- The canonical AST MUST preserve element order, attributes, text, and mixed content.
- Normalization MUST be invertible modulo a declared loss set; the loss set and the
  conventions version MUST be recorded alongside every output artifact.
- Round-trip tests MUST exist for every fixture: applying the forward transform and then
  its inverse MUST reproduce the source at the declared semantic level.
- No stage may drop information silently. Destructive rules MUST be opt-in and
  documented.
- Export MUST reconstruct a well-formed XML document from the stored canonical form and
  mapping metadata, or fail with an explicit error naming the declared loss.

Rationale: an extraction pipeline without an inverse is a one-way shredder; the
structure that was not projected becomes unrecoverable, and the mapping can never be
re-validated against its source.

### IV. Fail-Fast, Explicit Contracts

Invalid input MUST fail loudly rather than degrade silently. Conversion errors MUST
follow the configured policy (`fail` or `null`) and, under `fail`, MUST identify table,
column, XPath, value, and target type. Missing or blank values MUST map to `NULL`
deterministically. CLI failures MUST go to stderr with a non-zero exit code. Public API
and CLI signatures, output file names, and error messages are contracts and MUST NOT
change without a documented migration.

Rationale: silent coercion produces plausible but wrong tables, which is more damaging
than a failed run.

### V. Test-First and Reproducible Outputs

Behavior MUST be covered by automated tests before it is considered complete. The suite
MUST cover every strategy, every supported type, both error policies, batch boundaries,
mapping validation, export, and CLI/API behavior, and MUST include a memory regression
test for large inputs. Given identical input, mapping, and code, output MUST be
reproducible: stable table and column order, stable row order, and a stable Parquet
schema.

Rationale: reproducibility is what allows results to be reviewed, diffed, and trusted
across runs and environments.

## Technical Constraints

- Runtime: Python 3.11+.
- Dependencies: `lxml` for streaming parse and XPath, `duckdb` for storage and Parquet
  export, `PyYAML` for mapping input. New runtime dependencies MUST be justified against
  this set.
- Execution model: a single local process; no server, daemon, or background service.
- One XML source per run; input XML and output database are execution parameters, never
  mapping fields.
- No XSD requirement, no schema inference, no automatic foreign-key resolution.
- Mapping rules and limitations MUST remain documented in the README; any new documented
  limitation MUST state whether it affects bidirectionality.

## Development Workflow

- Work follows the Spec Kit flow: specify → plan → tasks → implement.
- The plan phase MUST include a Constitution Check gate covering every principle above,
  and the gate MUST be re-checked after design.
- A change that violates a principle MUST be rejected or accompanied by a constitutional
  amendment; complexity MUST be justified in the plan.
- Tests MUST pass, including the memory regression test, before a change is merged.
- Every change that touches a transform boundary MUST state its direction(s), its
  declared loss set, and the round-trip test that proves it.
- Public behavior changes MUST update the README, the mapping contract, and the relevant
  spec artifacts in the same change.

## Governance

The constitution supersedes other project practices. Amendments require a documented
proposal, review and approval, a Sync Impact Report describing the change, and a
migration plan when existing behavior is affected. Versioning follows semantic
versioning: MAJOR for incompatible governance or principle redefinitions, MINOR for new
or materially expanded principles and sections, PATCH for clarifications and
non-semantic refinements. Every plan and review MUST verify compliance with this
constitution; non-compliance MUST be recorded with a justification and a remediation
plan. Runtime development guidance lives in `README.md` and in the specs under `specs/`.

**Version**: 1.0.0 | **Ratified**: 2026-11-07 | **Last Amended**: 2026-11-07
