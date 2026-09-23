"""Stateful SQLite strategies with shared logical semantics."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .encoding import logical_checksum
from .load import _connect, _read_table, atomic_full_replace, read_current_state
from .model import PriceEvent
from .oracle import build_oracle, compare_states
from .validation import ValidationError, validate_and_resolve_snapshot

CURRENT_TABLE = "current_prices"
EVENTS_TABLE = "event_registry"
HISTORY_TABLE = "price_history"

CURRENT_DDL = f"""
CREATE TABLE IF NOT EXISTS {CURRENT_TABLE} (
    series_id TEXT NOT NULL, event_ts_utc INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    open_micros INTEGER NOT NULL CHECK (open_micros > 0),
    close_micros INTEGER NOT NULL CHECK (close_micros > 0),
    volume_micros INTEGER CHECK (volume_micros IS NULL OR volume_micros >= 0),
    source TEXT NOT NULL, PRIMARY KEY(series_id, event_ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_current_prices_ts ON {CURRENT_TABLE}(event_ts_utc);
"""
EVENTS_DDL = f"""
CREATE TABLE IF NOT EXISTS {EVENTS_TABLE} (
    series_id TEXT NOT NULL, event_ts_utc INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    open_micros INTEGER NOT NULL, close_micros INTEGER NOT NULL,
    volume_micros INTEGER, source TEXT NOT NULL,
    PRIMARY KEY(series_id, event_ts_utc, revision)
);
"""
HISTORY_DDL = f"""
CREATE TABLE IF NOT EXISTS {HISTORY_TABLE} (
    series_id TEXT NOT NULL, event_ts_utc INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    open_micros INTEGER NOT NULL CHECK (open_micros > 0),
    close_micros INTEGER NOT NULL CHECK (close_micros > 0),
    volume_micros INTEGER CHECK (volume_micros IS NULL OR volume_micros >= 0),
    source TEXT NOT NULL, PRIMARY KEY(series_id, event_ts_utc, revision)
);
CREATE INDEX IF NOT EXISTS idx_price_history_ts ON {HISTORY_TABLE}(event_ts_utc);
"""


@dataclass(frozen=True, slots=True)
class StrategyResult:
    strategy: str
    final_row_count: int
    checksum_sha256: str
    exact_duplicate_count: int
    stale_revision_count: int
    integrity_check: str


def _params(event: PriceEvent) -> tuple[object, ...]:
    return (
        event.series_id,
        event.event_ts_utc,
        event.revision,
        event.open_micros,
        event.close_micros,
        event.volume_micros,
        event.source,
    )


def _upsert_sql() -> str:
    return f"""INSERT INTO {CURRENT_TABLE} (
        series_id, event_ts_utc, revision, open_micros, close_micros, volume_micros, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(series_id, event_ts_utc) DO UPDATE SET
        revision=excluded.revision, open_micros=excluded.open_micros,
        close_micros=excluded.close_micros, volume_micros=excluded.volume_micros,
        source=excluded.source
    WHERE excluded.revision > {CURRENT_TABLE}.revision"""


def _open(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return _connect(database_path)


def _validate_registry(
    connection: sqlite3.Connection, events: tuple[PriceEvent, ...], table: str
) -> None:
    """Reject cross-batch payload conflicts before any publication."""
    for event in events:
        row = connection.execute(
            f"SELECT open_micros, close_micros, volume_micros, source FROM {table} "
            "WHERE series_id=? AND event_ts_utc=? AND revision=?",
            event.event_identity,
        ).fetchone()
        payload = (event.open_micros, event.close_micros, event.volume_micros, event.source)
        if row is not None and row != payload:
            raise ValidationError(
                "Conflicting payload across batches for event identity "
                f"{event.series_id}/{event.event_ts_utc}/r{event.revision}"
            )


def _integrity(connection: sqlite3.Connection) -> str:
    return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def incremental_upsert(
    rows: Iterable[PriceEvent],
    *,
    database_path: Path,
    fault_hook: Callable[[str], None] | None = None,
) -> StrategyResult:
    """Strategy B: transactional current-state upsert plus conflict registry."""
    snapshot = validate_and_resolve_snapshot(rows)
    connection = _open(database_path)
    try:
        connection.executescript(CURRENT_DDL + EVENTS_DDL)
        connection.execute("BEGIN IMMEDIATE")
        _validate_registry(connection, snapshot.events, EVENTS_TABLE)
        connection.executemany(
            f"INSERT OR IGNORE INTO {EVENTS_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [_params(event) for event in snapshot.events],
        )
        connection.executemany(_upsert_sql(), [_params(event) for event in snapshot.current_state])
        if fault_hook is not None:
            fault_hook("before_commit")
        state = _read_table(connection, CURRENT_TABLE)
        connection.commit()
        return StrategyResult(
            "B_incremental_upsert",
            len(state),
            logical_checksum(state, kind="current-state"),
            snapshot.exact_duplicate_count,
            snapshot.stale_revision_count,
            _integrity(connection),
        )
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def append_history_materialized(
    rows: Iterable[PriceEvent],
    *,
    database_path: Path,
    fault_hook: Callable[[str], None] | None = None,
) -> StrategyResult:
    """Strategy C: append unique history and maintain a current projection."""
    snapshot = validate_and_resolve_snapshot(rows)
    connection = _open(database_path)
    try:
        connection.executescript(CURRENT_DDL + HISTORY_DDL)
        connection.execute("BEGIN IMMEDIATE")
        _validate_registry(connection, snapshot.events, HISTORY_TABLE)
        connection.executemany(
            f"INSERT OR IGNORE INTO {HISTORY_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [_params(event) for event in snapshot.events],
        )
        connection.executemany(_upsert_sql(), [_params(event) for event in snapshot.current_state])
        if fault_hook is not None:
            fault_hook("before_commit")
        state = _read_table(connection, CURRENT_TABLE)
        connection.commit()
        return StrategyResult(
            "C_append_history_materialized",
            len(state),
            logical_checksum(state, kind="current-state"),
            snapshot.exact_duplicate_count,
            snapshot.stale_revision_count,
            _integrity(connection),
        )
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def apply_atomic_stateful(
    rows: Iterable[PriceEvent],
    *,
    database_path: Path,
    fault_hook: Callable[[str], None] | None = None,
) -> StrategyResult:
    """Strategy A adapter: merge incoming events with committed state and replace atomically."""
    incoming = tuple(rows)
    registry_connection = _open(database_path)
    try:
        registry_connection.executescript(EVENTS_DDL)
        _validate_registry(
            registry_connection, validate_and_resolve_snapshot(incoming).events, EVENTS_TABLE
        )
    finally:
        registry_connection.close()
    existing = read_current_state(database_path)
    merged = existing + incoming
    oracle = build_oracle(merged)
    result = atomic_full_replace(
        merged,
        database_path=database_path,
        expected_checksum_sha256=oracle.checksum_sha256,
        expected_row_count=oracle.row_count,
        fault_hook=fault_hook,
    )
    registry_connection = _open(database_path)
    try:
        registry_connection.execute("BEGIN IMMEDIATE")
        registry_connection.executemany(
            f"INSERT OR IGNORE INTO {EVENTS_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [_params(event) for event in validate_and_resolve_snapshot(incoming).events],
        )
        registry_connection.commit()
    except Exception:
        if registry_connection.in_transaction:
            registry_connection.rollback()
        raise
    finally:
        registry_connection.close()
    return StrategyResult(
        "A_atomic_full_replace",
        result.final_row_count,
        result.database_checksum_sha256,
        result.exact_duplicate_count,
        result.stale_revision_count,
        result.integrity_check,
    )


def read_strategy_state(database_path: Path) -> tuple[PriceEvent, ...]:
    if not database_path.is_file():
        return ()
    with sqlite3.connect(database_path) as connection:
        return _read_table(connection, CURRENT_TABLE)


def inspect_strategy(
    database_path: Path, strategy: str, expected: Iterable[PriceEvent]
) -> dict[str, object]:
    actual = read_strategy_state(database_path)
    oracle = build_oracle(expected)
    comparison = compare_states(oracle.state, actual)
    with sqlite3.connect(database_path) as connection:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
        integrity = _integrity(connection)
    checksum = logical_checksum(actual, kind="current-state")
    return {
        "strategy": strategy,
        "row_count": len(actual),
        "checksum": checksum,
        "oracle_checksum": oracle.checksum_sha256,
        "checksum_equal": checksum == oracle.checksum_sha256,
        "integrity_check": integrity,
        "tables": tables,
        **comparison,
    }


def query_sql(events: tuple[PriceEvent, ...]) -> dict[str, tuple[str, tuple[object, ...]]]:
    point = events[len(events) // 2]
    low = min(event.event_ts_utc for event in events)
    high = max(event.event_ts_utc for event in events)
    return {
        "Q1_point": (
            f"SELECT close_micros, revision FROM {CURRENT_TABLE} "
            "WHERE series_id=? AND event_ts_utc=?",
            (point.series_id, point.event_ts_utc),
        ),
        "Q2_range": (
            f"SELECT COUNT(*), COALESCE(SUM(close_micros),0) FROM {CURRENT_TABLE} "
            "WHERE event_ts_utc BETWEEN ? AND ?",
            (low, high),
        ),
        "Q3_period_aggregate": (
            f"SELECT COUNT(*), COALESCE(SUM(volume_micros),0) FROM {CURRENT_TABLE} "
            "WHERE event_ts_utc BETWEEN ? AND ? AND close_micros >= ?",
            (low, high, 100_000_000),
        ),
        "Q4_latest": (
            f"SELECT event_ts_utc, revision FROM {CURRENT_TABLE} "
            "WHERE series_id=? ORDER BY event_ts_utc DESC LIMIT 1",
            (point.series_id,),
        ),
        "Q5_filtered_return": (
            f"SELECT COUNT(*), COALESCE(SUM(close_micros-open_micros),0) "
            f"FROM {CURRENT_TABLE} WHERE series_id=? AND close_micros > open_micros",
            (point.series_id,),
        ),
    }


def query_suite(database_path: Path, events: tuple[PriceEvent, ...]) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        return {
            name: connection.execute(sql, params).fetchone()
            for name, (sql, params) in query_sql(events).items()
        }


def strategy_loader(name: str):
    return {
        "A_atomic_full_replace": apply_atomic_stateful,
        "B_incremental_upsert": incremental_upsert,
        "C_append_history_materialized": append_history_materialized,
    }[name]
