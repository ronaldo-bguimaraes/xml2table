from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import TableConfig


@dataclass
class TableBuffer:
    table: TableConfig
    batch_size: int
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    records_extracted: int = 0
    batches_written: int = 0

    def append(self, row: tuple[Any, ...]) -> None:
        self.rows.append(row)
        self.records_extracted += 1

    def should_flush(self) -> bool:
        return len(self.rows) >= self.batch_size

    def take_batch(self) -> list[tuple[Any, ...]]:
        if not self.rows:
            return []
        batch = self.rows
        self.rows = []
        self.batches_written += 1
        return batch
