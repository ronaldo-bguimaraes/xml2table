from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import Xml2RelError
from .engine import RunStats, XMLExtractor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xml2rel",
        description="Extract XML records into DuckDB using declarative YAML mappings.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an extraction mapping.")
    run_parser.add_argument("mapping", type=Path, help="Path to the YAML mapping file.")
    run_parser.add_argument("--output", type=Path, help="Override the DuckDB output path.")

    export_parser = subparsers.add_parser("export", help="Export mapped tables to Parquet.")
    export_parser.add_argument("mapping", type=Path, help="Path to the YAML mapping file.")
    export_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory that receives one Parquet file per mapped table.",
    )
    export_parser.add_argument(
        "--database",
        type=Path,
        help="DuckDB database to export (defaults to the mapping's output).",
    )
    return parser


def format_stats(stats: RunStats) -> str:
    lines = [
        f"{'table':<20} {'records':>10} {'batches':>10}",
    ]
    for name, table in stats.tables.items():
        lines.append(f"{name:<20} {table.records_extracted:>10} {table.batches_written:>10}")
    lines.append("")
    lines.append(f"total records: {stats.total_records}")
    lines.append(f"duration: {stats.duration_seconds:.2f}s")
    lines.append(f"output: {stats.output_path}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        extractor = XMLExtractor.from_yaml(args.mapping)
        if args.command == "run":
            stats = extractor.run(args.output)
            print(format_stats(stats))
            return 0

        paths = extractor.export_parquet(args.output_dir, database=args.database)
        for path in paths:
            print(path)
        return 0
    except (Xml2RelError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
