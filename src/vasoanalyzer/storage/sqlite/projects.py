"""
Project-level SQLite helpers migrated from the legacy sqlite_store module.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

__all__ = [
    "apply_default_pragmas",
    "apply_cloud_safe_pragmas",  # New: cloud-safe pragma configuration
    "ensure_schema",
    "run_migrations",
    "get_user_version",
    "set_user_version",
    "read_meta",
    "write_meta",
]


def apply_default_pragmas(conn: sqlite3.Connection) -> None:
    """
    Apply default pragmas for LOCAL storage (fast, optimized).

    Uses WAL mode with NORMAL synchronous for optimal performance on local disks.
    NORMAL is safe with WAL mode because:
    - WAL provides atomicity without fsync on every commit
    - Checkpoint before snapshot ensures durability
    - Only staging databases use this (snapshots are the durable artifact)
    """
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")  # Changed from FULL - safe with WAL
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 268435456;")  # 256MB memory mapping
    conn.execute("PRAGMA cache_size = -131072;")    # 128MB cache


def apply_cloud_safe_pragmas(conn: sqlite3.Connection) -> None:
    """
    Apply cloud-safe pragmas for CLOUD storage (reliable, slower).

    Uses DELETE journal mode which is compatible with cloud sync services.
    DELETE mode characteristics:
    - Single-file database (no separate -wal or -shm files)
    - Atomic rollback via journal file
    - Cloud sync services can handle single-file changes reliably
    - Slower than WAL but prevents hangs on cloud storage

    Use this for: iCloud Drive, Dropbox, Google Drive, OneDrive, etc.
    """
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = DELETE;")  # Cloud-safe mode
    conn.execute("PRAGMA synchronous = FULL;")      # Ensure durability
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -131072;")    # 128MB cache
    # NOTE: No mmap_size for cloud storage - can cause issues with sync


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
            extra_json TEXT,
            trace_checksum TEXT,
            events_checksum TEXT
        );

        CREATE TABLE IF NOT EXISTS trace (
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            t_seconds REAL NOT NULL,
            inner_diam REAL,
            outer_diam REAL,
            p_avg REAL,
            p1 REAL,
            p2 REAL,
            frame_number INTEGER,
            tiff_page INTEGER,
            temp REAL,
            table_marker INTEGER,
            caliper_length REAL,
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
            od REAL,
            id_diam REAL,
            caliper REAL,
            od_ref_pct REAL,
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

        CREATE TABLE IF NOT EXISTS figure_recipe (
            recipe_id TEXT PRIMARY KEY,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            source TEXT NOT NULL,
            trace_key TEXT,
            x_min REAL,
            x_max REAL,
            y_min REAL,
            y_max REAL,
            export_background TEXT NOT NULL DEFAULT 'white'
        );

        CREATE INDEX IF NOT EXISTS figure_recipe_ds_updated ON figure_recipe(dataset_id, updated_at DESC);
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
        elif version == 2:
            # Migration from v2 to v3: Add VasoTracker full support columns
            log.info("Migrating schema from v2 to v3 (VasoTracker full support)")

            # Add new columns to trace table
            conn.execute("ALTER TABLE trace ADD COLUMN frame_number INTEGER")
            conn.execute("ALTER TABLE trace ADD COLUMN tiff_page INTEGER")
            conn.execute("ALTER TABLE trace ADD COLUMN temp REAL")
            conn.execute("ALTER TABLE trace ADD COLUMN table_marker INTEGER")
            conn.execute("ALTER TABLE trace ADD COLUMN caliper_length REAL")

            # Add new columns to event table
            conn.execute("ALTER TABLE event ADD COLUMN od REAL")
            conn.execute("ALTER TABLE event ADD COLUMN id_diam REAL")
            conn.execute("ALTER TABLE event ADD COLUMN caliper REAL")
            conn.execute("ALTER TABLE event ADD COLUMN od_ref_pct REAL")

            version = 3

        elif version == 3:
            # Migration from v3 to v4: Add checksum columns for data integrity
            log.info("Migrating schema from v3 to v4 (checksum validation)")

            # Add checksum columns to dataset table
            # These are optional and will be computed on next save if missing
            try:
                conn.execute("ALTER TABLE dataset ADD COLUMN trace_checksum TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise

            try:
                conn.execute("ALTER TABLE dataset ADD COLUMN events_checksum TEXT")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise

            log.info("Schema migration to v4 complete (checksums added)")
            version = 4

        elif version == 4:
            # Migration from v4 to v5: Add figure_recipe table
            log.info("Migrating schema from v4 to v5 (figure recipes)")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS figure_recipe (
                    recipe_id TEXT PRIMARY KEY,
                    dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    trace_key TEXT,
                    x_min REAL,
                    x_max REAL,
                    y_min REAL,
                    y_max REAL,
                    export_background TEXT NOT NULL DEFAULT 'white'
                );
                CREATE INDEX IF NOT EXISTS figure_recipe_ds_updated ON figure_recipe(dataset_id, updated_at DESC);
                """
            )
            version = 5

        else:
            raise RuntimeError(
                f"Unknown schema version {version}. Cannot migrate."
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
