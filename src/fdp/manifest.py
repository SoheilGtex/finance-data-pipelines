"""Deterministic dataset and correctness JSON artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .extract import DEFAULT_START_TS_UTC, GENERATOR_VERSION
from .model import (
    SCHEMA_VERSION,
    TIMESTAMP_GRANULARITY_SECONDS,
    TIMESTAMP_UNIT,
    VALUE_SCALE,
)


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def build_dataset_manifest(
    *,
    seed: int,
    requested_rows: int,
    actual_rows: int,
    normalized_logical_sha256: str,
    raw_parquet_sha256: str,
    normalized_parquet_sha256: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "source_type": "synthetic",
        "seed": seed,
        "requested_row_count": requested_rows,
        "actual_row_count": actual_rows,
        "normalized_logical_sha256": normalized_logical_sha256,
        "raw_parquet_sha256": raw_parquet_sha256,
        "normalized_parquet_sha256": normalized_parquet_sha256,
        "generation": {
            "start_event_ts_utc": DEFAULT_START_TS_UTC,
            "timestamp_unit": TIMESTAMP_UNIT,
            "timestamp_granularity_seconds": TIMESTAMP_GRANULARITY_SECONDS,
            "value_scale": VALUE_SCALE,
            "series_count": min(64, requested_rows),
        },
    }
    base["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(base)).hexdigest()
    return base


def verify_manifest(payload: dict[str, Any]) -> bool:
    candidate = dict(payload)
    expected = candidate.pop("manifest_sha256", None)
    return (
        isinstance(expected, str)
        and hashlib.sha256(canonical_json_bytes(candidate)).hexdigest() == expected
    )
