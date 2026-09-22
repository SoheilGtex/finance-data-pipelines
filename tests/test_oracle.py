from __future__ import annotations

from dataclasses import replace

import pytest

from fdp.oracle import OracleError, build_oracle, compare_states


def test_oracle_is_order_independent_and_revision_aware(base_events):
    first = base_events[0]
    updated = replace(first, revision=2, close_micros=first.close_micros + 10)
    left = build_oracle((*base_events, updated, first))
    right = build_oracle(tuple(reversed((*base_events, updated, first))))
    assert left == right
    assert {event.logical_key: event for event in left.state}[first.logical_key] == updated


def test_oracle_rejects_same_revision_conflict(base_events):
    conflict = replace(base_events[0], close_micros=base_events[0].close_micros + 1)
    with pytest.raises(OracleError, match="conflicting payloads"):
        build_oracle((*base_events, conflict))


def test_state_comparison_reports_all_error_classes(base_events):
    expected = base_events[:3]
    wrong = replace(expected[0], close_micros=expected[0].close_micros + 1)
    extra = replace(expected[0], series_id="EXTRA")
    actual = (wrong, expected[1], extra, extra)
    result = compare_states(expected, actual)
    assert result == {
        "duplicate_logical_key_count": 1,
        "missing_key_count": 1,
        "extra_key_count": 1,
        "stale_or_wrong_value_count": 1,
    }
