"""SQLite Strategy A: validated atomic full replacement."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .encoding import logical_checksum
from .model import PriceEvent
from .validation import validate_and_resolve_snapshot

TABLE_NAME = "current_prices"
STAGING_TABLE = "current_prices__new"
OLD_TABLE = "current_prices__old"
FINAL_INDEX = "idx_current_prices_ts"
STAGING_INDEX = "idx_current_prices__new_ts"

_TABLE_DDL_TEMPLATE = """
CREATE TABLE {table_name} (
    series_id       TEXT    NOT NULL,
    event_ts_utc    INTEGER NOT NULL,
    revision        INTEGER NOT NULL CHECK (revision >= 1),
    open_micros     INTEGER NOT NULL CHECK (open_micros > 0),
    close_micros    INTEGER NOT NULL CHECK (close_micros > 0),
    volume_micros   INTEGER          CHECK (volume_micros IS NULL OR volume_micros >= 0),
    source          TEXT    NOT NULL,
    PRIMARY KEY (series_id, event_ts_utc)
)
"""


class AtomicReplaceError(RuntimeError):
    """Raised when Strategy A cannot publish a validated replacement."""


@dataclass(frozen=True, slots=True)
class AtomicReplaceResult:
    final_row_count: int
    database_checksum_sha256: str
    exact_duplicate_count: int
    stale_revision_count: int
    integrity_check: str


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=5.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _read_table(connection: sqlite3.Connection, table_name: str) -> tuple[PriceEvent, ...]:
    rows = connection.execute(
        f"""SELECT series_id, event_ts_utc, revision, open_micros,
                   close_micros, volume_micros, source
            FROM {table_name}
            ORDER BY series_id, event_ts_utc"""
    ).fetchall()
    return tuple(PriceEvent(*row) for row in rows)


def _inject(fault_hook: Callable[[str], None] | None, stage: str) -> None:
    if fault_hook is not None:
        fault_hook(stage)


def atomic_full_replace(
    rows: Iterable[PriceEvent],
    *,
    database_path: Path,
    expected_checksum_sha256: str,
    expected_row_count: int,
    fault_hook: Callable[[str], None] | None = None,
) -> AtomicReplaceResult:
    """Publish a complete replacement or preserve the prior committed state."""

    snapshot = validate_and_resolve_snapshot(rows)
    if len(snapshot.current_state) != expected_row_count:
        raise AtomicReplaceError(
            f"Expected {expected_row_count} rows, resolved {len(snapshot.current_state)}"
        )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"DROP TABLE IF EXISTS {STAGING_TABLE}")
        connection.execute(f"DROP TABLE IF EXISTS {OLD_TABLE}")
        connection.execute(_TABLE_DDL_TEMPLATE.format(table_name=STAGING_TABLE))
        connection.executemany(
            f"""INSERT INTO {STAGING_TABLE} (
                    series_id, event_ts_utc, revision, open_micros,
                    close_micros, volume_micros, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    event.series_id,
                    event.event_ts_utc,
                    event.revision,
                    event.open_micros,
                    event.close_micros,
                    event.volume_micros,
                    event.source,
                )
                for event in snapshot.current_state
            ],
        )
        _inject(fault_hook, "after_insert")
        connection.execute(f"CREATE INDEX {STAGING_INDEX} ON {STAGING_TABLE}(event_ts_utc)")
        _inject(fault_hook, "after_staging_index")

        staged = _read_table(connection, STAGING_TABLE)
        staged_checksum = logical_checksum(staged, kind="current-state")
        if len(staged) != expected_row_count:
            raise AtomicReplaceError("Staging row-count validation failed")
        if staged_checksum != expected_checksum_sha256:
            raise AtomicReplaceError("Staging checksum validation failed")
        _inject(fault_hook, "before_publish")

        had_current = _table_exists(connection, TABLE_NAME)
        if had_current:
            connection.execute(f"ALTER TABLE {TABLE_NAME} RENAME TO {OLD_TABLE}")
            _inject(fault_hook, "after_old_renamed")
        connection.execute(f"ALTER TABLE {STAGING_TABLE} RENAME TO {TABLE_NAME}")
        _inject(fault_hook, "after_new_renamed")
        if had_current:
            connection.execute(f"DROP TABLE {OLD_TABLE}")
        connection.execute(f"DROP INDEX {STAGING_INDEX}")
        connection.execute(f"CREATE INDEX {FINAL_INDEX} ON {TABLE_NAME}(event_ts_utc)")
        _inject(fault_hook, "before_commit")

        final_state = _read_table(connection, TABLE_NAME)
        final_checksum = logical_checksum(final_state, kind="current-state")
        if len(final_state) != expected_row_count or final_checksum != expected_checksum_sha256:
            raise AtomicReplaceError("Final pre-commit validation failed")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return AtomicReplaceResult(
            final_row_count=len(final_state),
            database_checksum_sha256=final_checksum,
            exact_duplicate_count=snapshot.exact_duplicate_count,
            stale_revision_count=snapshot.stale_revision_count,
            integrity_check=str(integrity),
        )
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def read_current_state(database_path: Path) -> tuple[PriceEvent, ...]:
    if not database_path.is_file():
        return ()
    connection = _connect(database_path)
    try:
        if not _table_exists(connection, TABLE_NAME):
            return ()
        return _read_table(connection, TABLE_NAME)
    finally:
        connection.close()


def database_status(database_path: Path) -> dict[str, str | int]:
    connection = _connect(database_path)
    try:
        state = _read_table(connection, TABLE_NAME)
        return {
            "final_row_count": len(state),
            "database_checksum_sha256": logical_checksum(state, kind="current-state"),
            "integrity_check": str(connection.execute("PRAGMA integrity_check").fetchone()[0]),
            "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
            "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
            "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
            "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
        }
    finally:
        connection.close()
