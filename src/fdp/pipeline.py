"""Ordinary Python orchestration for the deterministic offline baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .encoding import logical_checksum
from .extract import GENERATOR_VERSION, generate_synthetic
from .load import atomic_full_replace, database_status, read_current_state
from .manifest import build_dataset_manifest, write_json
from .model import SCHEMA_VERSION
from .oracle import build_oracle, compare_states
from .parquet_io import write_events
from .transform import normalize_events
from .utils.io import ensure_dirs, sha256_file


@dataclass(frozen=True, slots=True)
class PipelineArtifacts:
    output_dir: Path
    raw_parquet: Path
    normalized_parquet: Path
    database: Path
    manifest: Path
    correctness: Path


@dataclass(frozen=True, slots=True)
class PipelineRun:
    artifacts: PipelineArtifacts
    manifest: dict[str, Any]
    correctness: dict[str, Any]


def run_synthetic_baseline(
    *, seed: int, rows: int, output_dir: Path, database_path: Path | None = None
) -> PipelineRun:
    paths = RuntimePaths.from_output_dir(output_dir, database_path)
    ensure_dirs(paths)
    raw_path = paths.raw_dir / "prices_raw.parquet"
    normalized_path = paths.normalized_dir / "prices_normalized.parquet"

    generated = generate_synthetic(rows=rows, seed=seed)
    write_events(raw_path, generated)
    normalized = normalize_events(raw_path, normalized_path)

    oracle = build_oracle(normalized.events)
    normalized_logical_hash = logical_checksum(normalized.events, kind="normalized-events")
    manifest = build_dataset_manifest(
        seed=seed,
        requested_rows=rows,
        actual_rows=len(normalized.events),
        normalized_logical_sha256=normalized_logical_hash,
        raw_parquet_sha256=sha256_file(raw_path),
        normalized_parquet_sha256=sha256_file(normalized_path),
    )
    write_json(paths.manifest_path, manifest)

    first = atomic_full_replace(
        normalized.events,
        database_path=paths.database_path,
        expected_checksum_sha256=oracle.checksum_sha256,
        expected_row_count=oracle.row_count,
    )
    first_checksum = first.database_checksum_sha256
    second = atomic_full_replace(
        normalized.events,
        database_path=paths.database_path,
        expected_checksum_sha256=oracle.checksum_sha256,
        expected_row_count=oracle.row_count,
    )
    actual_state = read_current_state(paths.database_path)
    comparison = compare_states(oracle.state, actual_state)
    status = database_status(paths.database_path)
    correctness: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "requested_row_count": rows,
        "actual_normalized_row_count": len(normalized.events),
        "manifest_sha256": manifest["manifest_sha256"],
        "oracle_expected_row_count": oracle.row_count,
        "database_final_row_count": status["final_row_count"],
        "oracle_checksum_sha256": oracle.checksum_sha256,
        "database_checksum_sha256": status["database_checksum_sha256"],
        "checksum_equal": status["database_checksum_sha256"] == oracle.checksum_sha256,
        "idempotent_exact_rerun": first_checksum == second.database_checksum_sha256,
        "integrity_check": status["integrity_check"],
        "journal_mode": status["journal_mode"],
        "synchronous": status["synchronous"],
        "foreign_keys": status["foreign_keys"],
        "busy_timeout": status["busy_timeout"],
        **comparison,
    }
    write_json(paths.correctness_path, correctness)
    return PipelineRun(
        artifacts=PipelineArtifacts(
            output_dir=paths.output_dir,
            raw_parquet=raw_path,
            normalized_parquet=normalized_path,
            database=paths.database_path,
            manifest=paths.manifest_path,
            correctness=paths.correctness_path,
        ),
        manifest=manifest,
        correctness=correctness,
    )
