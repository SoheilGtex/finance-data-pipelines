"""Strict validation and loader-side snapshot resolution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .model import EVENT_COLUMNS, TIMESTAMP_GRANULARITY_SECONDS, PriceEvent

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_MAX_TIMESTAMP = 253_402_300_799  # 9999-12-31T23:59:59Z


class ValidationError(ValueError):
    """Raised when a batch violates the frozen logical contract."""


@dataclass(frozen=True, slots=True)
class ValidatedSnapshot:
    events: tuple[PriceEvent, ...]
    current_state: tuple[PriceEvent, ...]
    exact_duplicate_count: int
    stale_revision_count: int


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _coerce_event(item: PriceEvent | Mapping[str, Any], row_number: int) -> PriceEvent:
    if isinstance(item, PriceEvent):
        event = item
    elif isinstance(item, Mapping):
        missing = [column for column in EVENT_COLUMNS if column not in item]
        extra = sorted(set(item) - set(EVENT_COLUMNS))
        if missing:
            raise ValidationError(f"Row {row_number}: missing columns: {', '.join(missing)}")
        if extra:
            raise ValidationError(f"Row {row_number}: unexpected columns: {', '.join(extra)}")
        try:
            event = PriceEvent.from_mapping(item)
        except (KeyError, TypeError) as exc:
            raise ValidationError(f"Row {row_number}: invalid event structure") from exc
    else:
        raise ValidationError(f"Row {row_number}: event must be a mapping or PriceEvent")

    if not isinstance(event.series_id, str) or not event.series_id:
        raise ValidationError(f"Row {row_number}: series_id must be a non-empty string")
    if not _IDENTIFIER.fullmatch(event.series_id):
        raise ValidationError(f"Row {row_number}: series_id contains unsupported characters")
    if not _is_int(event.event_ts_utc):
        raise ValidationError(f"Row {row_number}: event_ts_utc must be an integer")
    if not 0 <= event.event_ts_utc <= _MAX_TIMESTAMP:
        raise ValidationError(f"Row {row_number}: event_ts_utc is outside the supported range")
    if event.event_ts_utc % TIMESTAMP_GRANULARITY_SECONDS != 0:
        raise ValidationError(
            f"Row {row_number}: event_ts_utc must align to "
            f"{TIMESTAMP_GRANULARITY_SECONDS}-second granularity"
        )
    if not _is_int(event.revision) or event.revision < 1:
        raise ValidationError(f"Row {row_number}: revision must be an integer >= 1")
    if not _is_int(event.open_micros) or event.open_micros <= 0:
        raise ValidationError(f"Row {row_number}: open_micros must be a positive integer")
    if not _is_int(event.close_micros) or event.close_micros <= 0:
        raise ValidationError(f"Row {row_number}: close_micros must be a positive integer")
    if event.volume_micros is not None and (
        not _is_int(event.volume_micros) or event.volume_micros < 0
    ):
        raise ValidationError(f"Row {row_number}: volume_micros must be null or nonnegative")
    if not isinstance(event.source, str) or not event.source:
        raise ValidationError(f"Row {row_number}: source must be a non-empty string")
    if not _IDENTIFIER.fullmatch(event.source):
        raise ValidationError(f"Row {row_number}: source contains unsupported characters")
    return event


def validate_and_resolve_snapshot(
    rows: Iterable[PriceEvent | Mapping[str, Any]], *, allow_empty: bool = False
) -> ValidatedSnapshot:
    """Validate a complete snapshot and resolve its loader-side current state.

    Exact duplicates collapse. A conflicting payload for the same event identity
    rejects the entire batch. The highest revision wins for each logical key.
    """

    identities: dict[tuple[str, int, int], PriceEvent] = {}
    exact_duplicates = 0
    saw_row = False
    for row_number, item in enumerate(rows, start=1):
        saw_row = True
        event = _coerce_event(item, row_number)
        previous = identities.get(event.event_identity)
        if previous is None:
            identities[event.event_identity] = event
        elif previous.payload == event.payload:
            exact_duplicates += 1
        else:
            raise ValidationError(
                "Conflicting payloads for event identity "
                f"{event.series_id}/{event.event_ts_utc}/r{event.revision}"
            )

    if not saw_row and not allow_empty:
        raise ValidationError("Empty full replacement is rejected by default.")

    canonical_events = tuple(sorted(identities.values(), key=lambda event: event.event_identity))
    current_by_key: dict[tuple[str, int], PriceEvent] = {}
    for event in canonical_events:
        previous = current_by_key.get(event.logical_key)
        if previous is None or event.revision > previous.revision:
            current_by_key[event.logical_key] = event

    current_state = tuple(sorted(current_by_key.values(), key=lambda event: event.logical_key))
    stale_revisions = len(canonical_events) - len(current_state)
    return ValidatedSnapshot(
        events=canonical_events,
        current_state=current_state,
        exact_duplicate_count=exact_duplicates,
        stale_revision_count=stale_revisions,
    )
