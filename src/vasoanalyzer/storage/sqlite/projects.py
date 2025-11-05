"""
Project-level SQLite helpers migrated from the legacy sqlite_store module.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

__all__ = [
    "apply_default_pragmas",
    "ensure_schema",
    "run_migrations",
    "get_user_version",
    "set_user_version",
    "read_meta",
    "write_meta",
]


def apply_default_pragmas(conn: sqlite3.Connection) -> None:
    """Apply the default pragmas used across the project store."""

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 268435456;")
    conn.execute("PRAGMA cache_size = -131072;")


def ensure_schema(
    conn: sqlite3.Connection,
    *,
    schema_version: int,
    now: str,
    app_version: str | None = None,
    timezone: str | None = None,
) -> None:
    """
    Ensure that all schema objects exist and seed project metadata defaults.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dataset (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_utc TEXT NOT NULL,
            notes TEXT,
            fps REAL,
            pixel_size_um REAL,
            t0_seconds REAL DEFAULT 0,
            extra_json TEXT
        );

        CREATE TABLE IF NOT EXISTS trace (
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            t_seconds REAL NOT NULL,
            inner_diam REAL,
            outer_diam REAL,
            p_avg REAL,
            p1 REAL,
            p2 REAL,
            PRIMARY KEY (dataset_id, t_seconds)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS trace_ds_t ON trace(dataset_id, t_seconds);

        CREATE TABLE IF NOT EXISTS event (
            id INTEGER PRIMARY KEY,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            t_seconds REAL NOT NULL,
            label TEXT NOT NULL,
            frame INTEGER,
            p_avg REAL,
            p1 REAL,
            p2 REAL,
            temp REAL,
            extra_json TEXT
        );

        CREATE INDEX IF NOT EXISTS event_ds_t ON event(dataset_id, t_seconds);

        CREATE TABLE IF NOT EXISTS asset (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            compressed INTEGER NOT NULL,
            chunk_size INTEGER NOT NULL,
            original_name TEXT,
            mime TEXT
        );

        CREATE TABLE IF NOT EXISTS blob_chunk (
            asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            data BLOB NOT NULL,
            PRIMARY KEY (asset_id, seq)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS ref (
            asset_id INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            note TEXT,
            PRIMARY KEY (asset_id, dataset_id, role)
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX IF NOT EXISTS ref_dataset_role ON ref(dataset_id, role);

        CREATE TABLE IF NOT EXISTS result (
            id INTEGER PRIMARY KEY,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            version TEXT NOT NULL,
            created_utc TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS thumbnail (
            dataset_id INTEGER PRIMARY KEY REFERENCES dataset(id) ON DELETE CASCADE,
            png BLOB NOT NULL
        );
        """
    )
    set_user_version(conn, schema_version)

    meta_values: dict[str, str] = {
        "format": "sqlite-v3",
        "project_version": str(schema_version),
        "schema_version": str(schema_version),
        "created_at": now,
        "modified_at": now,
        "created_utc": now,
        "modified_utc": now,
    }
    if app_version is not None:
        meta_values["app_version"] = str(app_version)
    if timezone is not None:
        meta_values["timezone"] = str(timezone)

    write_meta(conn, meta_values)
    conn.commit()


def run_migrations(
    conn: sqlite3.Connection,
    start: int,
    target: int,
    *,
    now: str,
    app_version: str | None = None,
    timezone: str | None = None,
) -> None:
    """Execute schema migrations between ``start`` and ``target`` versions."""

    version = start
    while version < target:
        if version == 0:
            ensure_schema(
                conn,
                schema_version=target,
                now=now,
                app_version=app_version,
                timezone=timezone,
            )
            version = target
        else:
            raise RuntimeError(
                "This project uses a legacy .vaso format that requires conversion to sqlite-v3."
            )
    set_user_version(conn, target)
    conn.commit()


def get_user_version(conn: sqlite3.Connection) -> int:
    """Return the PRAGMA user_version value."""

    cur = conn.execute("PRAGMA user_version")
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    """Update the PRAGMA user_version value."""

    conn.execute(f"PRAGMA user_version = {int(version)}")


def read_meta(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return all key/value entries from the meta table."""

    cur = conn.execute("SELECT key, value FROM meta")
    return {row[0]: row[1] for row in cur.fetchall()}


def write_meta(conn: sqlite3.Connection, values: Mapping[str, Any]) -> None:
    """Upsert values into the meta table."""

    if not values:
        return
    rows = [(str(key), str(value)) for key, value in values.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        rows,
    )
