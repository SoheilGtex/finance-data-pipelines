"""Validation and deterministic normalization of event Parquet files."""

from __future__ import annotations

from pathlib import Path

from .parquet_io import read_events, write_events
from .validation import ValidatedSnapshot, validate_and_resolve_snapshot


def normalize_events(input_path: Path, output_path: Path) -> ValidatedSnapshot:
    snapshot = validate_and_resolve_snapshot(read_events(input_path))
    write_events(output_path, snapshot.events)
    return snapshot
