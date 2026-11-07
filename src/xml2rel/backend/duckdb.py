from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import duckdb

from ..config import ColumnType, TableConfig, Xml2RelError

MAX_PARAMETERS_PER_STATEMENT = 5_000

_TYPE_MAP = {
    ColumnType.VARCHAR: "VARCHAR",
    ColumnType.INTEGER: "INTEGER",
    ColumnType.BIGINT: "BIGINT",
    ColumnType.DOUBLE: "DOUBLE",
    ColumnType.BOOLEAN: "BOOLEAN",
    ColumnType.DATE: "DATE",
    ColumnType.TIMESTAMP: "TIMESTAMP",
    ColumnType.JSON: "JSON",
}


class BackendError(Xml2RelError):
    def __init__(self, database_path: Path | str, operation: str, reason: str) -> None:
        self.database_path = Path(database_path)
        self.operation = operation
        self.reason = reason
        super().__init__(f"database={self.database_path} operation={operation}: {reason}")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


class DuckDBBackend:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._connection: duckdb.DuckDBPyConnection | None = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            self.connect()
        assert self._connection is not None
        return self._connection

    def connect(self) -> None:
        if self._connection is not None:
            return
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(str(self.database_path))
        except OSError as exc:
            raise BackendError(self.database_path, "connect", str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendError(self.database_path, "connect", str(exc)) from exc

    def create_tables(self, tables: Mapping[str, TableConfig]) -> None:
        try:
            self.connection.execute("BEGIN")
            for table in tables.values():
                self.connection.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table.name)}")
                definitions = ", ".join(
                    f"{_quote_identifier(column.name)} {_TYPE_MAP[column.type]}"
                    for column in table.columns.values()
                )
                self.connection.execute(
                    f"CREATE TABLE {_quote_identifier(table.name)} ({definitions})"
                )
            self.connection.execute("COMMIT")
        except duckdb.Error as exc:
            self._rollback()
            raise BackendError(self.database_path, "create_tables", str(exc)) from exc

    def insert_batch(self, table: TableConfig, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return

        columns = list(table.columns.values())
        quoted_columns = ", ".join(_quote_identifier(column.name) for column in columns)
        row_placeholder = "(" + ", ".join(
            f"CAST(? AS JSON)" if column.type is ColumnType.JSON else "?"
            for column in columns
        ) + ")"
        chunk_size = max(1, MAX_PARAMETERS_PER_STATEMENT // max(1, len(columns)))

        try:
            self.connection.execute("BEGIN")
            for offset in range(0, len(rows), chunk_size):
                chunk = rows[offset : offset + chunk_size]
                values_sql = ", ".join(row_placeholder for _ in chunk)
                sql = (
                    f"INSERT INTO {_quote_identifier(table.name)} ({quoted_columns}) "
                    f"VALUES {values_sql}"
                )
                parameters = [value for row in chunk for value in row]
                self.connection.execute(sql, parameters)
            self.connection.execute("COMMIT")
        except duckdb.Error as exc:
            self._rollback()
            raise BackendError(self.database_path, f"insert_batch({table.name})", str(exc)) from exc

    def table_exists(self, table_name: str) -> bool:
        try:
            row = self.connection.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name = ? LIMIT 1",
                [table_name],
            ).fetchone()
            return row is not None
        except duckdb.Error as exc:
            raise BackendError(self.database_path, f"table_exists({table_name})", str(exc)) from exc

    def export_table_parquet(self, table_name: str, output_path: str | Path) -> Path:
        destination = Path(output_path).expanduser().resolve()
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            sql = (
                f"COPY (SELECT * FROM {_quote_identifier(table_name)}) "
                f"TO '{_escape_literal(str(destination))}' (FORMAT PARQUET)"
            )
            self.connection.execute(sql)
            return destination
        except OSError as exc:
            raise BackendError(self.database_path, f"export({table_name})", str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendError(self.database_path, f"export({table_name})", str(exc)) from exc

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _rollback(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
