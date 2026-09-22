"""Independent correctness oracle for canonical current-state resolution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .encoding import logical_checksum
from .model import EVENT_COLUMNS, TIMESTAMP_GRANULARITY_SECONDS, PriceEvent

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_MAX_TIMESTAMP = 253_402_300_799


class OracleError(ValueError):
    """Raised when the oracle rejects an input event set."""


@dataclass(frozen=True, slots=True)
class OracleResult:
    state: tuple[PriceEvent, ...]
    row_count: int
    checksum_sha256: str


def _oracle_event(item: PriceEvent | Mapping[str, Any], row_number: int) -> PriceEvent:
    if isinstance(item, PriceEvent):
        event = item
    elif isinstance(item, Mapping):
        if set(item) != set(EVENT_COLUMNS):
            raise OracleError(f"Row {row_number}: oracle schema mismatch")
        try:
            event = PriceEvent.from_mapping(item)
        except (KeyError, TypeError) as exc:
            raise OracleError(f"Row {row_number}: invalid oracle event") from exc
    else:
        raise OracleError(f"Row {row_number}: invalid oracle event type")

    integer_values = (
        event.event_ts_utc,
        event.revision,
        event.open_micros,
        event.close_micros,
    )
    if (
        not isinstance(event.series_id, str)
        or not event.series_id
        or not _IDENTIFIER.fullmatch(event.series_id)
    ):
        raise OracleError(f"Row {row_number}: invalid series_id")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in integer_values):
        raise OracleError(f"Row {row_number}: non-integer numeric field")
    if (
        not 0 <= event.event_ts_utc <= _MAX_TIMESTAMP
        or event.event_ts_utc % TIMESTAMP_GRANULARITY_SECONDS
    ):
        raise OracleError(f"Row {row_number}: invalid timestamp")
    if event.revision < 1 or event.open_micros <= 0 or event.close_micros <= 0:
        raise OracleError(f"Row {row_number}: invalid revision or price")
    if event.volume_micros is not None and (
        not isinstance(event.volume_micros, int)
        or isinstance(event.volume_micros, bool)
        or event.volume_micros < 0
    ):
        raise OracleError(f"Row {row_number}: invalid volume")
    if (
        not isinstance(event.source, str)
        or not event.source
        or not _IDENTIFIER.fullmatch(event.source)
    ):
        raise OracleError(f"Row {row_number}: invalid source")
    return event


def build_oracle(
    rows: Iterable[PriceEvent | Mapping[str, Any]], *, allow_empty: bool = False
) -> OracleResult:
    """Resolve revisions without calling loader validation or loading code."""

    by_identity: dict[tuple[str, int, int], PriceEvent] = {}
    saw_row = False
    for row_number, item in enumerate(rows, start=1):
        saw_row = True
        event = _oracle_event(item, row_number)
        previous = by_identity.get(event.event_identity)
        if previous is not None and previous.payload != event.payload:
            raise OracleError(
                "Oracle found conflicting payloads for "
                f"{event.series_id}/{event.event_ts_utc}/r{event.revision}"
            )
        by_identity[event.event_identity] = event
    if not saw_row and not allow_empty:
        raise OracleError("Oracle rejects an empty full snapshot.")

    by_key: dict[tuple[str, int], PriceEvent] = {}
    for event in sorted(by_identity.values(), key=lambda value: value.event_identity):
        previous = by_key.get(event.logical_key)
        if previous is None or event.revision > previous.revision:
            by_key[event.logical_key] = event
    state = tuple(sorted(by_key.values(), key=lambda value: value.logical_key))
    return OracleResult(
        state=state,
        row_count=len(state),
        checksum_sha256=logical_checksum(state, kind="current-state"),
    )


def compare_states(expected: Iterable[PriceEvent], actual: Iterable[PriceEvent]) -> dict[str, int]:
    expected_events = tuple(expected)
    actual_events = tuple(actual)
    expected_by_key = {event.logical_key: event for event in expected_events}
    actual_by_key = {event.logical_key: event for event in actual_events}
    expected_keys = set(expected_by_key)
    actual_keys = set(actual_by_key)
    shared = expected_keys & actual_keys
    return {
        "duplicate_logical_key_count": len(actual_events) - len(actual_keys),
        "missing_key_count": len(expected_keys - actual_keys),
        "extra_key_count": len(actual_keys - expected_keys),
        "stale_or_wrong_value_count": sum(
            expected_by_key[key] != actual_by_key[key] for key in shared
        ),
    }
