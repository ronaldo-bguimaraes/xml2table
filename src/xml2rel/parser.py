from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lxml import etree

from .config import TableConfig, Xml2RelError
from .xpath import RawValue, select_value


class ExtractionError(Xml2RelError):
    def __init__(self, source_path: Path | str, reason: str) -> None:
        self.source_path = Path(source_path)
        self.reason = reason
        super().__init__(f"source={self.source_path}: {reason}")


@dataclass
class ParseFrame:
    element: etree._Element
    record_tables: tuple[str, ...]
    parent: "ParseFrame | None"


class StreamingXMLParser:
    def __init__(
        self,
        tables: dict[str, TableConfig],
        callback: Callable[[str, dict[str, RawValue]], None],
    ) -> None:
        self.tables = tables
        self.callback = callback
        self.max_stack_depth = 0

    def parse(self, source_path: str | Path) -> None:
        source = Path(source_path)
        stack: list[ParseFrame] = []
        self.max_stack_depth = 0

        try:
            context = etree.iterparse(
                str(source),
                events=("start", "end"),
                recover=False,
                huge_tree=True,
            )
            for event, element in context:
                if event == "start":
                    matched = tuple(
                        name
                        for name, table in self.tables.items()
                        if table.matcher.matches(element)
                    )
                    frame = ParseFrame(
                        element=element,
                        record_tables=matched,
                        parent=stack[-1] if stack else None,
                    )
                    stack.append(frame)
                    if len(stack) > self.max_stack_depth:
                        self.max_stack_depth = len(stack)
                    continue

                frame = stack.pop()
                if frame.record_tables:
                    for table_name in frame.record_tables:
                        table = self.tables[table_name]
                        values = {
                            column.name: select_value(element, column)
                            for column in table.columns.values()
                        }
                        self.callback(table_name, values)

                has_open_record_ancestor = any(item.record_tables for item in stack)
                if not has_open_record_ancestor:
                    parent = element.getparent()
                    element.clear()
                    if parent is not None:
                        parent.remove(element)

        except Xml2RelError:
            raise
        except OSError as exc:
            raise ExtractionError(source, str(exc)) from exc
        except etree.XMLSyntaxError as exc:
            raise ExtractionError(source, f"malformed XML: {exc}") from exc
        except etree.LxmlError as exc:
            raise ExtractionError(source, f"XML parser error: {exc}") from exc
