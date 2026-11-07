from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

from .source_path import SourcePathError, SourcePathMatcher

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TOP_LEVEL_KEYS = {"source", "settings", "output", "tables"}
SOURCE_KEYS = {"file"}
SETTINGS_KEYS = {"batch_size", "error_policy"}
TABLE_KEYS = {"source", "columns"}
COLUMN_KEYS = {"xpath", "strategy", "type"}


class Xml2RelError(Exception):
    """Base class for all user-facing xml2rel errors."""


class ConfigError(Xml2RelError):
    def __init__(
        self,
        mapping_path: Path | str,
        reason: str,
        *,
        table: str | None = None,
        column: str | None = None,
    ) -> None:
        self.mapping_path = Path(mapping_path)
        self.reason = reason
        self.table = table
        self.column = column
        location = str(self.mapping_path)
        if table is not None:
            location += f" [table={table!r}"
            if column is not None:
                location += f", column={column!r}"
            location += "]"
        elif column is not None:
            location += f" [column={column!r}]"
        super().__init__(f"{location}: {reason}")


class ColumnStrategy(str, Enum):
    FIRST_NON_EMPTY = "first_non_empty"
    FIRST = "first"
    CONCAT = "concat"
    COLLECT = "collect"


class ColumnType(str, Enum):
    VARCHAR = "VARCHAR"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    DOUBLE = "DOUBLE"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    JSON = "JSON"


class ErrorPolicy(str, Enum):
    FAIL = "fail"
    NULL = "null"


@dataclass(frozen=True)
class SourceConfig:
    file: Path


@dataclass(frozen=True)
class Settings:
    batch_size: int = 10_000
    error_policy: ErrorPolicy = ErrorPolicy.FAIL


@dataclass(frozen=True)
class ColumnConfig:
    name: str
    xpath: tuple[str, ...]
    strategy: ColumnStrategy
    type: ColumnType

    @property
    def xpath_label(self) -> str:
        if len(self.xpath) == 1:
            return self.xpath[0]
        return " | ".join(self.xpath)


@dataclass(frozen=True)
class TableConfig:
    name: str
    source: str
    columns: dict[str, ColumnConfig]
    matcher: SourcePathMatcher = field(repr=False, compare=False)


@dataclass(frozen=True)
class MappingConfig:
    mapping_path: Path
    source: SourceConfig
    settings: Settings
    output_path: Path
    tables: dict[str, TableConfig]


class DuplicateKeyError(ValueError):
    def __init__(self, key: str, line: int) -> None:
        self.key = key
        self.line = line
        super().__init__(f"duplicate key {key!r} at line {line}")


class _StrictSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKeyError(str(key), key_node.start_mark.line + 1)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _error(mapping_path: Path, reason: str, *, table: str | None = None, column: str | None = None) -> ConfigError:
    return ConfigError(mapping_path, reason, table=table, column=column)


def _mapping(value: Any, mapping_path: Path, location: str, *, table: str | None = None, column: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(mapping_path, f"{location} must be a mapping", table=table, column=column)
    return value


def _reject_unknown_keys(
    value: dict[str, Any],
    allowed: set[str],
    mapping_path: Path,
    location: str,
    *,
    table: str | None = None,
    column: str | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(
            mapping_path,
            f"{location} contains unknown key(s): {', '.join(map(repr, unknown))}",
            table=table,
            column=column,
        )


def _name(value: Any, mapping_path: Path, location: str, *, table: str | None = None, column: str | None = None) -> str:
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise _error(
            mapping_path,
            f"{location} must match ^[A-Za-z_][A-Za-z0-9_]*$",
            table=table,
            column=column,
        )
    return value


def _non_empty_string(
    value: Any,
    mapping_path: Path,
    location: str,
    *,
    table: str | None = None,
    column: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(mapping_path, f"{location} must be a non-empty string", table=table, column=column)
    return value


def _compile_column(
    name: str,
    value: Any,
    mapping_path: Path,
    table_name: str,
) -> ColumnConfig:
    raw = _mapping(value, mapping_path, f"column {name!r}", table=table_name, column=name)
    _reject_unknown_keys(raw, COLUMN_KEYS, mapping_path, f"column {name!r}", table=table_name, column=name)

    xpath_raw = raw.get("xpath")
    if isinstance(xpath_raw, str):
        xpaths = (xpath_raw,)
    elif isinstance(xpath_raw, list) and xpath_raw:
        if not all(isinstance(item, str) and item.strip() for item in xpath_raw):
            raise _error(
                mapping_path,
                "xpath list entries must be non-empty strings",
                table=table_name,
                column=name,
            )
        xpaths = tuple(xpath_raw)
    else:
        raise _error(
            mapping_path,
            "xpath must be a non-empty string or a non-empty list of strings",
            table=table_name,
            column=name,
        )

    for expression in xpaths:
        try:
            etree.XPath(expression)
        except etree.XPathError as exc:
            raise _error(
                mapping_path,
                f"invalid XPath {expression!r}: {exc}",
                table=table_name,
                column=name,
            ) from exc

    strategy_raw = raw.get("strategy", ColumnStrategy.FIRST_NON_EMPTY.value)
    if not isinstance(strategy_raw, str):
        raise _error(mapping_path, "strategy must be a string", table=table_name, column=name)
    try:
        strategy = ColumnStrategy(strategy_raw.strip().lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ColumnStrategy)
        raise _error(
            mapping_path,
            f"unsupported strategy {strategy_raw!r}; expected one of: {allowed}",
            table=table_name,
            column=name,
        ) from exc

    type_raw = raw.get("type")
    if not isinstance(type_raw, str):
        raise _error(mapping_path, "type must be a string", table=table_name, column=name)
    try:
        column_type = ColumnType(type_raw.strip().upper())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ColumnType)
        raise _error(
            mapping_path,
            f"unsupported type {type_raw!r}; expected one of: {allowed}",
            table=table_name,
            column=name,
        ) from exc

    return ColumnConfig(name=name, xpath=xpaths, strategy=strategy, type=column_type)


def _compile_table(name: str, value: Any, mapping_path: Path) -> TableConfig:
    raw = _mapping(value, mapping_path, f"table {name!r}", table=name)
    _reject_unknown_keys(raw, TABLE_KEYS, mapping_path, f"table {name!r}", table=name)

    source = _non_empty_string(raw.get("source"), mapping_path, "source", table=name)
    try:
        matcher = SourcePathMatcher(source)
    except SourcePathError as exc:
        raise _error(mapping_path, f"unsupported source XPath {source!r}: {exc}", table=name) from exc

    columns_raw = _mapping(raw.get("columns"), mapping_path, "columns", table=name)
    if not columns_raw:
        raise _error(mapping_path, "columns must not be empty", table=name)

    columns: dict[str, ColumnConfig] = {}
    for column_name, column_value in columns_raw.items():
        safe_name = _name(column_name, mapping_path, "column name", table=name)
        if safe_name in columns:
            raise _error(mapping_path, f"duplicate column name {safe_name!r}", table=name, column=safe_name)
        columns[safe_name] = _compile_column(safe_name, column_value, mapping_path, name)

    return TableConfig(name=name, source=source, columns=columns, matcher=matcher)


def load_mapping(path: str | Path) -> MappingConfig:
    mapping_path = Path(path).expanduser().resolve()
    if not mapping_path.is_file():
        raise ConfigError(mapping_path, "mapping file does not exist or is not a file")

    try:
        text = mapping_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(mapping_path, f"cannot read mapping file: {exc}") from exc

    try:
        raw = yaml.load(text, Loader=_StrictSafeLoader)
    except DuplicateKeyError as exc:
        raise ConfigError(mapping_path, str(exc)) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(mapping_path, f"invalid YAML: {exc}") from exc

    root = _mapping(raw, mapping_path, "mapping")
    _reject_unknown_keys(root, TOP_LEVEL_KEYS, mapping_path, "mapping")

    source_raw = _mapping(root.get("source"), mapping_path, "source")
    _reject_unknown_keys(source_raw, SOURCE_KEYS, mapping_path, "source")
    source_file = _non_empty_string(source_raw.get("file"), mapping_path, "source.file")
    source_path = Path(source_file).expanduser()
    if not source_path.is_absolute():
        source_path = mapping_path.parent / source_path
    source_path = source_path.resolve()

    settings_raw = root.get("settings", {})
    settings_mapping = _mapping(settings_raw, mapping_path, "settings")
    _reject_unknown_keys(settings_mapping, SETTINGS_KEYS, mapping_path, "settings")

    batch_size = settings_mapping.get("batch_size", 10_000)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ConfigError(mapping_path, "settings.batch_size must be an integer greater than zero")

    policy_raw = settings_mapping.get("error_policy", ErrorPolicy.FAIL.value)
    if policy_raw is None:
        policy_raw = ErrorPolicy.NULL.value
    if not isinstance(policy_raw, str):
        raise ConfigError(mapping_path, "settings.error_policy must be a string or null")
    try:
        error_policy = ErrorPolicy(policy_raw.strip().lower())
    except ValueError as exc:
        raise ConfigError(
            mapping_path,
            "settings.error_policy must be 'fail' or 'null'",
        ) from exc

    output_raw = root.get("output", "output.duckdb")
    output_value = _non_empty_string(output_raw, mapping_path, "output")
    output_path = Path(output_value).expanduser()
    if not output_path.is_absolute():
        output_path = mapping_path.parent / output_path
    output_path = output_path.resolve()

    if output_path == source_path:
        raise ConfigError(mapping_path, "output database path must not equal the source XML path")
    if output_path == mapping_path:
        raise ConfigError(mapping_path, "output database path must not equal the mapping file path")

    tables_raw = _mapping(root.get("tables"), mapping_path, "tables")
    if not tables_raw:
        raise ConfigError(mapping_path, "tables must not be empty")

    tables: dict[str, TableConfig] = {}
    for table_name, table_value in tables_raw.items():
        safe_name = _name(table_name, mapping_path, "table name")
        if safe_name in tables:
            raise ConfigError(mapping_path, f"duplicate table name {safe_name!r}")
        tables[safe_name] = _compile_table(safe_name, table_value, mapping_path)

    return MappingConfig(
        mapping_path=mapping_path,
        source=SourceConfig(file=source_path),
        settings=Settings(batch_size=batch_size, error_policy=error_policy),
        output_path=output_path,
        tables=tables,
    )
