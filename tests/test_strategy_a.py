from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from fdp.load import (
    FINAL_INDEX,
    TABLE_NAME,
    atomic_full_replace,
    database_status,
    read_current_state,
)
from fdp.oracle import build_oracle
from fdp.validation import ValidationError


def _load(database_path, events):
    oracle = build_oracle(events)
    return atomic_full_replace(
        events,
        database_path=database_path,
        expected_checksum_sha256=oracle.checksum_sha256,
        expected_row_count=oracle.row_count,
    )


def _raise_at(target):
    def hook(stage):
        if stage == target:
            raise RuntimeError(f"injected failure at {stage}")

    return hook


def test_first_load_matches_oracle_and_integrity(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    oracle = build_oracle(base_events)
    result = _load(database, base_events)
    assert result.final_row_count == oracle.row_count
    assert result.database_checksum_sha256 == oracle.checksum_sha256
    assert result.integrity_check == "ok"
    assert read_current_state(database) == oracle.state


def test_exact_rerun_is_idempotent(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    first = _load(database, base_events)
    second = _load(database, base_events)
    assert first.database_checksum_sha256 == second.database_checksum_sha256
    assert read_current_state(database) == build_oracle(base_events).state


def test_duplicates_higher_and_stale_revisions_match_oracle(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    first = base_events[0]
    updated = replace(first, revision=2, close_micros=first.close_micros + 300)
    events = (*base_events, first, updated)
    result = _load(database, events)
    assert result.exact_duplicate_count == 1
    assert result.stale_revision_count == 1
    assert read_current_state(database) == build_oracle(events).state


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("series_id", ""),
        ("event_ts_utc", 1),
        ("revision", 0),
        ("open_micros", 0),
        ("close_micros", 0),
        ("volume_micros", -1),
    ],
)
def test_malformed_replacement_preserves_previous_state(tmp_path, base_events, field, value):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    before = read_current_state(database)
    malformed = replace(base_events[0], **{field: value})
    with pytest.raises(ValidationError):
        atomic_full_replace(
            (malformed,),
            database_path=database,
            expected_checksum_sha256="0" * 64,
            expected_row_count=1,
        )
    assert read_current_state(database) == before


def test_same_revision_conflict_preserves_previous_state(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    before = read_current_state(database)
    conflict = replace(base_events[0], close_micros=base_events[0].close_micros + 1)
    with pytest.raises(ValidationError, match="Conflicting payloads"):
        atomic_full_replace(
            (*base_events, conflict),
            database_path=database,
            expected_checksum_sha256="0" * 64,
            expected_row_count=len(base_events),
        )
    assert read_current_state(database) == before


def test_empty_replacement_preserves_previous_state(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    before = read_current_state(database)
    with pytest.raises(ValidationError, match="Empty full replacement"):
        atomic_full_replace(
            (),
            database_path=database,
            expected_checksum_sha256="0" * 64,
            expected_row_count=0,
        )
    assert read_current_state(database) == before


@pytest.mark.parametrize(
    "stage",
    [
        "after_insert",
        "after_staging_index",
        "before_publish",
        "after_old_renamed",
        "after_new_renamed",
        "before_commit",
    ],
)
def test_injected_failure_never_publishes_hybrid_state(
    tmp_path, base_events, changed_events, stage
):
    database = tmp_path / f"{stage}.db"
    _load(database, base_events)
    before = read_current_state(database)
    oracle = build_oracle(changed_events)
    with pytest.raises(RuntimeError, match="injected failure"):
        atomic_full_replace(
            changed_events,
            database_path=database,
            expected_checksum_sha256=oracle.checksum_sha256,
            expected_row_count=oracle.row_count,
            fault_hook=_raise_at(stage),
        )
    assert read_current_state(database) == before
    assert database_status(database)["integrity_check"] == "ok"


def test_recovery_after_injected_failure_reaches_oracle(tmp_path, base_events, changed_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    oracle = build_oracle(changed_events)
    with pytest.raises(RuntimeError):
        atomic_full_replace(
            changed_events,
            database_path=database,
            expected_checksum_sha256=oracle.checksum_sha256,
            expected_row_count=oracle.row_count,
            fault_hook=_raise_at("after_new_renamed"),
        )
    result = _load(database, changed_events)
    assert result.database_checksum_sha256 == oracle.checksum_sha256
    assert read_current_state(database) == oracle.state


def test_wrong_expected_checksum_rolls_back(tmp_path, base_events, changed_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    before = read_current_state(database)
    with pytest.raises(RuntimeError, match="checksum"):
        atomic_full_replace(
            changed_events,
            database_path=database,
            expected_checksum_sha256="0" * 64,
            expected_row_count=build_oracle(changed_events).row_count,
        )
    assert read_current_state(database) == before


def test_physical_schema_index_and_pragmas(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    with sqlite3.connect(database) as connection:
        columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({TABLE_NAME})")}
        indexes = {row[1] for row in connection.execute(f"PRAGMA index_list({TABLE_NAME})")}
        schema_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE_NAME,)
        ).fetchone()[0]
    status = database_status(database)
    assert columns["series_id"][5] == 1
    assert columns["event_ts_utc"][5] == 2
    assert FINAL_INDEX in indexes
    assert "revision >= 1" in schema_sql
    assert "open_micros > 0" in schema_sql
    assert status == {
        **status,
        "integrity_check": "ok",
        "journal_mode": "wal",
        "synchronous": 2,
        "foreign_keys": 1,
        "busy_timeout": 5000,
    }


def test_no_staging_tables_remain_after_success(tmp_path, base_events):
    database = tmp_path / "warehouse.db"
    _load(database, base_events)
    with sqlite3.connect(database) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert names == {TABLE_NAME}
