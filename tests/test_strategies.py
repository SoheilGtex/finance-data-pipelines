from __future__ import annotations

import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from fdp.extract import generate_synthetic
from fdp.oracle import build_oracle
from fdp.strategies import (
    append_history_materialized,
    incremental_upsert,
    inspect_strategy,
)
from fdp.validation import ValidationError


def test_cross_batch_same_revision_conflict_is_rejected(tmp_path):
    events = generate_synthetic(rows=12, seed=1)
    conflict = replace(events[0], close_micros=events[0].close_micros + 1)
    for loader in (incremental_upsert, append_history_materialized):
        database = tmp_path / f"{loader.__name__}.db"
        loader((events[0],), database_path=database)
        with pytest.raises(ValidationError, match="Conflicting payload across batches"):
            loader((conflict,), database_path=database)
        assert inspect_strategy(database, loader.__name__, events[:1])["checksum_equal"] is True


def test_stateful_update_and_stale_revision_semantics(tmp_path):
    events = generate_synthetic(rows=20, seed=2)
    updated = tuple(
        replace(event, revision=2, close_micros=event.close_micros + 5) for event in events[:5]
    )
    stale = tuple(events[:5])
    for loader in (incremental_upsert, append_history_materialized):
        database = tmp_path / f"{loader.__name__}-state.db"
        loader(events, database_path=database)
        loader(updated, database_path=database)
        loader(stale, database_path=database)
        assert (
            inspect_strategy(database, loader.__name__, events + updated)["checksum_equal"] is True
        )


def test_same_revision_duplicate_is_a_noop(tmp_path):
    events = generate_synthetic(rows=10, seed=3)
    for loader in (incremental_upsert, append_history_materialized):
        database = tmp_path / f"{loader.__name__}-duplicate.db"
        first = loader(events, database_path=database)
        second = loader(events, database_path=database)
        assert first.checksum_sha256 == second.checksum_sha256


def test_process_interruption_and_transactional_recovery(tmp_path):
    events = generate_synthetic(rows=30, seed=4)
    database = tmp_path / "interrupted.db"
    incremental_upsert(events, database_path=database)
    changed = tuple(
        replace(event, revision=2, close_micros=event.close_micros + 9) for event in events
    )
    helper = Path(__file__).with_name("helpers_interrupt.py")
    result = subprocess.run([sys.executable, str(helper), str(database)], input="", check=False)
    assert result.returncode == -signal.SIGKILL
    before = inspect_strategy(database, "B_incremental_upsert", events)
    assert before["checksum_equal"] is True
    assert before["integrity_check"] == "ok"
    incremental_upsert(changed, database_path=database)
    after = inspect_strategy(database, "B_incremental_upsert", changed)
    assert after["checksum_equal"] is True
    assert after["integrity_check"] == "ok"
    assert after["oracle_checksum"] == build_oracle(changed).checksum_sha256
