"""Parquet serialization for the frozen event schema."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .model import EVENT_COLUMNS, PriceEvent

EVENT_SCHEMA = pa.schema(
    [
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("event_ts_utc", pa.int64(), nullable=False),
        pa.field("revision", pa.int64(), nullable=False),
        pa.field("open_micros", pa.int64(), nullable=False),
        pa.field("close_micros", pa.int64(), nullable=False),
        pa.field("volume_micros", pa.int64(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
    ]
)


def write_events(path: Path, events: Iterable[PriceEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [event.as_dict() for event in events]
    table = pa.Table.from_pylist(rows, schema=EVENT_SCHEMA)
    pq.write_table(
        table,
        path,
        compression="zstd",
        version="2.6",
        write_statistics=True,
    )


def read_events(path: Path) -> tuple[PriceEvent, ...]:
    table = pq.read_table(path)
    if tuple(table.column_names) != EVENT_COLUMNS:
        raise ValueError(
            f"Unexpected Parquet columns: {table.column_names}; expected {list(EVENT_COLUMNS)}"
        )
    if not table.schema.equals(EVENT_SCHEMA, check_metadata=False):
        raise ValueError(f"Unexpected Parquet schema: {table.schema}")
    return tuple(PriceEvent.from_mapping(row) for row in table.to_pylist())
