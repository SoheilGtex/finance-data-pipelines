"""Deterministic offline synthetic event generation."""

from __future__ import annotations

import random

from .model import TIMESTAMP_GRANULARITY_SECONDS, PriceEvent

GENERATOR_VERSION = "1.0.0"
DEFAULT_START_TS_UTC = 1_704_067_200  # 2024-01-01T00:00:00Z


def generate_synthetic(
    *, rows: int, seed: int, start_ts_utc: int = DEFAULT_START_TS_UTC
) -> tuple[PriceEvent, ...]:
    """Generate an exact-size deterministic workload using Python's stable PRNG API."""

    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        raise ValueError("rows must be an integer >= 1")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if start_ts_utc < 0:
        raise ValueError("start_ts_utc must be nonnegative")
    if start_ts_utc % TIMESTAMP_GRANULARITY_SECONDS != 0:
        raise ValueError("start_ts_utc must align to the timestamp granularity")

    rng = random.Random(seed)
    series_count = min(64, rows)
    events: list[PriceEvent] = []
    for index in range(rows):
        series_number = index % series_count
        time_bucket = index // series_count
        baseline = 100_000_000 + series_number * 100_000 + time_bucket * 1_000
        open_micros = baseline + rng.randint(-25_000, 25_000)
        close_micros = open_micros + rng.randint(-20_000, 20_000)
        events.append(
            PriceEvent(
                series_id=f"SYNTH_{series_number:04d}",
                event_ts_utc=start_ts_utc + time_bucket * TIMESTAMP_GRANULARITY_SECONDS,
                revision=1,
                open_micros=open_micros,
                close_micros=max(1, close_micros),
                volume_micros=rng.randint(0, 10_000_000_000),
                source="synthetic",
            )
        )
    return tuple(events)
