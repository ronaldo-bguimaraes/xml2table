# CLI Contract: `xml2rel`

**Feature**: `001-xml-to-relational-engine`
**Entry point**: `xml2rel = xml2rel.cli:main` (also runnable as `python -m xml2rel`).

## Global behavior

- `xml2rel --help` and `xml2rel <command> --help` print usage and exit 0.
- `xml2rel --version` prints the package version and exits 0.
- Unknown commands/options are handled by argparse and exit 2.
- Configuration, extraction, conversion, and backend errors print a single actionable message to stderr and exit 1.
- Paths supplied on the command line are resolved against the current working directory.
- Paths from the mapping resolve against the mapping file's directory.
- No command reads or requires an XSD.

## `xml2rel run`

```text
xml2rel run MAPPING [--output DATABASE]
```

| Argument/Option | Required | Meaning |
|-----------------|----------|---------|
| `MAPPING` | Yes | Path to the YAML mapping file. |
| `--output DATABASE` | No | DuckDB output path; overrides the mapping's `output` value. |

**Behavior**:

1. Load and validate the mapping.
2. Refuse to proceed if the resolved output path is the source XML or the mapping file.
3. Create the output database's parent directory if needed.
4. Drop and recreate every mapped table, then stream the XML and insert rows in batches.
5. Print statistics to stdout on success.

**Success output** (format may vary in spacing, but these values must be present):

```text
table           records    batches
patients             250         1
appointments        1000         1

total records: 1250
duration: 0.42s
output: /path/to/output.duckdb
```

**Exit codes**:

| Code | Meaning |
|------|---------|
| 0 | Extraction completed and all buffers were written. |
| 1 | Validation, XML parsing, conversion (`fail` policy), path-safety, or database error. |
| 2 | Argparse usage error. |

**Partial-failure rule**: Batches committed before a `fail`-policy conversion error remain in the database, but the command exits 1 and does not print a successful statistics block.

## `xml2rel export`

```text
xml2rel export MAPPING --output-dir DIRECTORY [--database DATABASE]
```

| Argument/Option | Required | Meaning |
|-----------------|----------|---------|
| `MAPPING` | Yes | Path to the YAML mapping file, used to locate the configured output database and table names. |
| `--output-dir DIRECTORY` | Yes | Directory that receives one `<table>.parquet` file per mapped table. Created recursively if absent. |
| `--database DATABASE` | No | DuckDB database to export. Defaults to the mapping's configured `output`; does not implicitly reuse a prior `run --output` value. |

**Behavior**:

1. Load and validate the mapping.
2. Resolve the output database: explicit `--database` when supplied, otherwise the mapping's `output` value.
3. Fail before writing artifacts if the database is missing or any mapped table is missing.
4. Write one Parquet file per mapped table in mapping declaration order.
5. Print each written path to stdout.

**Exit codes**:

| Code | Meaning |
|------|---------|
| 0 | Every mapped table exported. |
| 1 | Validation, missing database/table, filesystem, or DuckDB error. |
| 2 | Argparse usage error. |

## Statistic requirements

The `run` command reports, at minimum:

- Each table name with its extracted record count and batches written.
- Total records across tables.
- Processing duration in seconds.
- Effective output database path.

## Resource behavior

- Files and DuckDB connections are closed on success and failure.
- An open batch transaction is rolled back on failure.
- Re-running `run` with the same mapping replaces mapped tables; unrelated tables in the database are untouched.
