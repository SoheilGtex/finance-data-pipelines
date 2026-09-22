from __future__ import annotations

from dataclasses import replace

import pytest

from fdp.validation import ValidationError, validate_and_resolve_snapshot


def test_exact_duplicate_collapses(base_events):
    snapshot = validate_and_resolve_snapshot((*base_events, base_events[0]))
    assert snapshot.exact_duplicate_count == 1
    assert len(snapshot.current_state) == len(base_events)


def test_higher_revision_wins_and_stale_revision_is_counted(base_events):
    first = base_events[0]
    updated = replace(first, revision=2, close_micros=first.close_micros + 1)
    snapshot = validate_and_resolve_snapshot((*base_events, updated))
    selected = {event.logical_key: event for event in snapshot.current_state}[first.logical_key]
    assert selected == updated
    assert snapshot.stale_revision_count == 1


def test_same_revision_conflict_rejects_entire_snapshot(base_events):
    conflict = replace(base_events[0], close_micros=base_events[0].close_micros + 1)
    with pytest.raises(ValidationError, match="Conflicting payloads"):
        validate_and_resolve_snapshot((*base_events, conflict))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("series_id", "", "series_id"),
        ("series_id", "bad value", "series_id"),
        ("event_ts_utc", "bad", "event_ts_utc"),
        ("event_ts_utc", 1, "granularity"),
        ("revision", 0, "revision"),
        ("open_micros", 0, "open_micros"),
        ("close_micros", -1, "close_micros"),
        ("volume_micros", -1, "volume_micros"),
        ("source", "", "source"),
    ],
)
def test_malformed_field_is_rejected(base_events, field, value, message):
    malformed = replace(base_events[0], **{field: value})
    with pytest.raises(ValidationError, match=message):
        validate_and_resolve_snapshot((malformed,))


def test_missing_or_extra_column_is_rejected(base_events):
    row = base_events[0].as_dict()
    row.pop("source")
    with pytest.raises(ValidationError, match="missing columns"):
        validate_and_resolve_snapshot((row,))

    row = base_events[0].as_dict()
    row["unexpected"] = 1
    with pytest.raises(ValidationError, match="unexpected columns"):
        validate_and_resolve_snapshot((row,))


def test_empty_full_snapshot_is_rejected():
    with pytest.raises(ValidationError, match="Empty full replacement"):
        validate_and_resolve_snapshot(())
