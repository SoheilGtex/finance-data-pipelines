from __future__ import annotations

import json

from fdp.encoding import logical_checksum
from fdp.extract import GENERATOR_VERSION, generate_synthetic
from fdp.manifest import verify_manifest
from fdp.pipeline import run_synthetic_baseline
from fdp.validation import validate_and_resolve_snapshot


def test_generator_is_exact_and_deterministic():
    left = generate_synthetic(rows=100, seed=77)
    right = generate_synthetic(rows=100, seed=77)
    assert left == right
    assert len(left) == 100
    assert logical_checksum(left, kind="normalized-events") == logical_checksum(
        right, kind="normalized-events"
    )


def test_generator_seed_changes_hash():
    left = generate_synthetic(rows=100, seed=77)
    right = generate_synthetic(rows=100, seed=78)
    assert logical_checksum(left, kind="normalized-events") != logical_checksum(
        right, kind="normalized-events"
    )


def test_generator_values_satisfy_frozen_contract():
    events = generate_synthetic(rows=129, seed=20270916)
    validated = validate_and_resolve_snapshot(events)
    assert validated.events == tuple(sorted(events, key=lambda event: event.event_identity))
    assert len({event.logical_key for event in events}) == 129
    assert all(event.revision == 1 for event in events)
    assert all(event.open_micros > 0 and event.close_micros > 0 for event in events)
    assert all(event.volume_micros is not None and event.volume_micros >= 0 for event in events)
    assert abs(events[0].close_micros - events[0].open_micros) <= 20_000


def test_generator_rejects_invalid_parameters():
    for rows, seed in ((0, 1), (-1, 1), (1, -1), (True, 1), (1, False)):
        try:
            generate_synthetic(rows=rows, seed=seed)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid generator parameters were accepted")


def test_manifest_matches_deterministic_output(tmp_path):
    result = run_synthetic_baseline(seed=91, rows=20, output_dir=tmp_path / "output")
    payload = json.loads(result.artifacts.manifest.read_text(encoding="utf-8"))
    assert payload["generator_version"] == GENERATOR_VERSION
    assert payload["requested_row_count"] == payload["actual_row_count"] == 20
    assert payload["seed"] == 91
    assert verify_manifest(payload)
    assert payload == result.manifest


def test_two_runs_have_identical_logical_and_manifest_hashes(tmp_path):
    first = run_synthetic_baseline(seed=91, rows=20, output_dir=tmp_path / "one")
    second = run_synthetic_baseline(seed=91, rows=20, output_dir=tmp_path / "two")
    assert first.manifest == second.manifest
    assert (
        first.correctness["oracle_checksum_sha256"] == second.correctness["oracle_checksum_sha256"]
    )
