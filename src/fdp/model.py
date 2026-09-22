"""Frozen logical time-series model used by the baseline and future benchmarks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1.0.0"
TIMESTAMP_UNIT = "unix_seconds_utc"
TIMESTAMP_GRANULARITY_SECONDS = 60
VALUE_SCALE = 1_000_000

EVENT_COLUMNS = (
    "series_id",
    "event_ts_utc",
    "revision",
    "open_micros",
    "close_micros",
    "volume_micros",
    "source",
)


@dataclass(frozen=True, order=True, slots=True)
class PriceEvent:
    series_id: str
    event_ts_utc: int
    revision: int
    open_micros: int
    close_micros: int
    volume_micros: int | None
    source: str

    @property
    def logical_key(self) -> tuple[str, int]:
        return (self.series_id, self.event_ts_utc)

    @property
    def event_identity(self) -> tuple[str, int, int]:
        return (self.series_id, self.event_ts_utc, self.revision)

    @property
    def payload(self) -> tuple[int, int, int | None, str]:
        return (self.open_micros, self.close_micros, self.volume_micros, self.source)

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "series_id": self.series_id,
            "event_ts_utc": self.event_ts_utc,
            "revision": self.revision,
            "open_micros": self.open_micros,
            "close_micros": self.close_micros,
            "volume_micros": self.volume_micros,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> PriceEvent:
        return cls(**{column: row[column] for column in EVENT_COLUMNS})
