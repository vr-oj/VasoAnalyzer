"""Shared SQLite utility helpers for VasoAnalyzer."""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from pathlib import Path

__all__ = [
    "connect_rw",
    "checkpoint_full",
    "set_delete_mode",
    "optimize",
    "vacuum_optimize",
    "delete_sidecars",
    "backup_to_delete_mode",
]


def connect_rw(path: str | os.PathLike[str], *, timeout: float = 30.0) -> sqlite3.Connection:
    """Open ``path`` in read/write mode with autocommit semantics."""

    return sqlite3.connect(str(path), timeout=timeout, isolation_level=None)


def checkpoint_full(conn: sqlite3.Connection) -> None:
    """Request a FULL WAL checkpoint, ignoring unsupported configurations."""

    with contextlib.suppress(Exception):
        conn.execute("PRAGMA wal_checkpoint(FULL)")


def set_delete_mode(conn: sqlite3.Connection) -> None:
    """Configure ``conn`` to use DELETE journal mode when possible."""

    with contextlib.suppress(Exception):
        conn.execute("PRAGMA journal_mode=DELETE")


def optimize(conn: sqlite3.Connection) -> None:
    """Run ``PRAGMA optimize`` when available."""

    with contextlib.suppress(Exception):
        conn.execute("PRAGMA optimize")


def vacuum_optimize(conn: sqlite3.Connection) -> None:
    """VACUUM and optimize the database for maximum portability."""

    with contextlib.suppress(Exception):
        conn.execute("VACUUM")
    optimize(conn)


def delete_sidecars(path: str | os.PathLike[str]) -> None:
    """Remove ``-wal``/``-shm`` files adjacent to ``path`` if present."""

    base = str(Path(path))
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(base + suffix)
        except FileNotFoundError:
            continue


def backup_to_delete_mode(
    src_path: str | os.PathLike[str], dst_path: str | os.PathLike[str]
) -> None:
    """Copy ``src_path`` into ``dst_path`` ensuring DELETE journal mode."""

    src_path = str(Path(src_path))
    dst_path = str(Path(dst_path))

    with connect_rw(src_path) as src:
        checkpoint_full(src)
        dst_dir = os.path.dirname(os.path.abspath(dst_path)) or "."
        os.makedirs(dst_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=Path(dst_path).name + ".", suffix=".tmp", dir=dst_dir, delete=False
        ) as tmp:
            tmp_path = tmp.name
        try:
            with connect_rw(tmp_path) as dst:
                src.backup(dst)
                set_delete_mode(dst)
                checkpoint_full(dst)
                vacuum_optimize(dst)
            delete_sidecars(tmp_path)
            os.replace(tmp_path, dst_path)
        finally:
            if os.path.exists(tmp_path):
                with contextlib.suppress(Exception):
                    os.remove(tmp_path)
    delete_sidecars(dst_path)
