"""Canonical binary encoding used for stable SHA-256 checksums."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable

from .model import SCHEMA_VERSION, PriceEvent


def _encode_text(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def _encode_int(value: int) -> bytes:
    return struct.pack(">q", value)


def encode_event(event: PriceEvent) -> bytes:
    volume = b"\x00" if event.volume_micros is None else b"\x01" + _encode_int(event.volume_micros)
    return b"".join(
        (
            _encode_text(event.series_id),
            _encode_int(event.event_ts_utc),
            _encode_int(event.revision),
            _encode_int(event.open_micros),
            _encode_int(event.close_micros),
            volume,
            _encode_text(event.source),
        )
    )


def logical_checksum(events: Iterable[PriceEvent], *, kind: str) -> str:
    digest = hashlib.sha256()
    digest.update(_encode_text(SCHEMA_VERSION))
    digest.update(_encode_text(kind))
    ordered = tuple(events)
    digest.update(struct.pack(">Q", len(ordered)))
    for event in ordered:
        encoded = encode_event(event)
        digest.update(struct.pack(">Q", len(encoded)))
        digest.update(encoded)
    return digest.hexdigest()
