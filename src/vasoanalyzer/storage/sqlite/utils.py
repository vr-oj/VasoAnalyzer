"""
Utility helpers for SQLite-backed project storage.

Initial slice: connection helpers, pragmas, cursor/transaction context managers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

__all__ = ["open_db", "set_pragmas", "db_cursor", "transaction"]


# ---- Connections ------------------------------------------------------------


def open_db(
    path: str,
    *,
    mode: str = "rwc",
    apply_pragmas: bool = False,
    pragmas: Mapping[str, object] | None = None,
) -> sqlite3.Connection:
    """
    Open a SQLite database with predictable defaults.

    mode: "ro" (read-only), "rw", "rwc" (create if needed). Default: "rwc".
    apply_pragmas=False keeps behaviour identical to existing code unless callers opt in.
    """
    if path == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        uri = f"file:{path}?mode={mode}"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if apply_pragmas:
        set_pragmas(conn, pragmas or {})
    return conn


def _to_int(value: object) -> int:
    """Best-effort conversion to ``int`` for pragmatic pragmas."""

    return int(cast(Any, value))


def set_pragmas(conn: sqlite3.Connection, opts: Mapping[str, object]) -> None:
    """Apply selected pragmas.

    Only keys present in ``opts`` are applied. Supported keys include
    ``foreign_keys``, ``journal_mode``, ``synchronous``, ``temp_store``,
    ``cache_size``, and ``busy_timeout_ms``.
    """

    norm = {str(key).lower(): value for key, value in opts.items()}
    for key, value in norm.items():
        if key == "foreign_keys":
            conn.execute(f"PRAGMA foreign_keys={'ON' if value else 'OFF'}")
        elif key == "journal_mode":
            conn.execute(f"PRAGMA journal_mode={value}")
        elif key == "synchronous":
            conn.execute(f"PRAGMA synchronous={value}")
        elif key == "temp_store":
            conn.execute(f"PRAGMA temp_store={value}")
        elif key == "cache_size":
            conn.execute(f"PRAGMA cache_size={_to_int(value)}")
        elif key == "busy_timeout_ms":
            conn.execute(f"PRAGMA busy_timeout={_to_int(value)}")


# ---- Cursors / Transactions -------------------------------------------------


@contextmanager
def db_cursor(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """Context manager that closes the cursor after use."""

    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def transaction(
    conn: sqlite3.Connection,
    *,
    begin: str = "BEGIN IMMEDIATE",
) -> Iterator[sqlite3.Connection]:
    """
    Transaction wrapper that commits on success and rolls back on error.
    Uses BEGIN IMMEDIATE by default to reduce write contention.
    """

    try:
        conn.execute(begin)
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
