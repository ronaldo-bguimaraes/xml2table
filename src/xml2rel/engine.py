from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from .backend.duckdb import BackendError, DuckDBBackend
from .buffers import TableBuffer
from .config import (
    ConfigError,
    ErrorPolicy,
    MappingConfig,
    load_mapping,
)
from .converter import ConversionError, convert_value
from .parser import StreamingXMLParser
from .xpath import RawValue


@dataclass(frozen=True)
class TableStats:
    name: str
    records_extracted: int
    batches_written: int


@dataclass(frozen=True)
class RunStats:
    tables: dict[str, TableStats]
    total_records: int
    duration_seconds: float
    output_path: Path


class XMLExtractor:
    def __init__(self, config: MappingConfig) -> None:
        self._config = config
        self._run_started = False
        self._output_path = config.output_path

    @classmethod
    def from_yaml(cls, mapping_path: str | Path) -> "XMLExtractor":
        return cls(load_mapping(mapping_path))

    @property
    def mapping_path(self) -> Path:
        return self._config.mapping_path

    @property
    def output_path(self) -> Path:
        return self._output_path

    def run(self, output: str | Path | None = None) -> RunStats:
        if self._run_started:
            raise RuntimeError("XMLExtractor.run() may only be called once per instance")
        self._run_started = True

        output_path = (
            self._config.output_path
            if output is None
            else Path(output).expanduser().resolve()
        )
        if output_path == self._config.source.file:
            raise ConfigError(self._config.mapping_path, "output database path must not equal the source XML path")
        if output_path == self._config.mapping_path:
            raise ConfigError(self._config.mapping_path, "output database path must not equal the mapping file path")
        self._output_path = output_path

        backend = DuckDBBackend(output_path)
        buffers = {
            name: TableBuffer(table=table, batch_size=self._config.settings.batch_size)
            for name, table in self._config.tables.items()
        }
        start = perf_counter()

        def on_record(table_name: str, raw_values: dict[str, RawValue]) -> None:
            table = self._config.tables[table_name]
            row: list[Any] = []
            for column in table.columns.values():
                raw = raw_values[column.name]
                try:
                    value = convert_value(
                        raw.value,
                        column.type,
                        table=table.name,
                        column=column.name,
                        xpath=raw.xpath_label,
                    )
                except ConversionError:
                    if self._config.settings.error_policy is ErrorPolicy.FAIL:
                        raise
                    value = None
                row.append(value)

            buffer = buffers[table_name]
            buffer.append(tuple(row))
            if buffer.should_flush():
                backend.insert_batch(table, buffer.take_batch())

        try:
            backend.connect()
            backend.create_tables(self._config.tables)
            parser = StreamingXMLParser(self._config.tables, on_record)
            parser.parse(self._config.source.file)

            for table_name, buffer in buffers.items():
                if buffer.rows:
                    backend.insert_batch(self._config.tables[table_name], buffer.take_batch())
        finally:
            backend.close()

        duration = perf_counter() - start
        table_stats = {
            name: TableStats(
                name=name,
                records_extracted=buffer.records_extracted,
                batches_written=buffer.batches_written,
            )
            for name, buffer in buffers.items()
        }
        return RunStats(
            tables=table_stats,
            total_records=sum(item.records_extracted for item in table_stats.values()),
            duration_seconds=duration,
            output_path=output_path,
        )

    def export_parquet(
        self,
        output_dir: str | Path,
        database: str | Path | None = None,
    ) -> list[Path]:
        destination_dir = Path(output_dir).expanduser().resolve()
        database_path = (
            self._config.output_path
            if database is None
            else Path(database).expanduser().resolve()
        )

        if not database_path.is_file():
            raise BackendError(database_path, "export", "database does not exist")

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackendError(database_path, "export", f"cannot create output directory: {exc}") from exc

        backend = DuckDBBackend(database_path)
        try:
            backend.connect()
            missing = [
                table.name
                for table in self._config.tables.values()
                if not backend.table_exists(table.name)
            ]
            if missing:
                raise BackendError(
                    database_path,
                    "export",
                    f"missing mapped table(s): {', '.join(missing)}",
                )

            paths: list[Path] = []
            for table in self._config.tables.values():
                paths.append(
                    backend.export_table_parquet(
                        table.name,
                        destination_dir / f"{table.name}.parquet",
                    )
                )
            return paths
        finally:
            backend.close()
