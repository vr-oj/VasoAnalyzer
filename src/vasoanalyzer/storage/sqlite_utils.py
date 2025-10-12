"""Shared SQLite utility helpers for VasoAnalyzer."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

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

    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass


def set_delete_mode(conn: sqlite3.Connection) -> None:
    """Configure ``conn`` to use DELETE journal mode when possible."""

    try:
        conn.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        pass


def optimize(conn: sqlite3.Connection) -> None:
    """Run ``PRAGMA optimize`` when available."""

    try:
        conn.execute("PRAGMA optimize")
    except Exception:
        pass


def vacuum_optimize(conn: sqlite3.Connection) -> None:
    """VACUUM and optimize the database for maximum portability."""

    try:
        conn.execute("VACUUM")
    except Exception:
        pass
    optimize(conn)


def delete_sidecars(path: str | os.PathLike[str]) -> None:
    """Remove ``-wal``/``-shm`` files adjacent to ``path`` if present."""

    base = str(Path(path))
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(base + suffix)
        except FileNotFoundError:
            continue


def backup_to_delete_mode(src_path: str | os.PathLike[str], dst_path: str | os.PathLike[str]) -> None:
    """Copy ``src_path`` into ``dst_path`` ensuring DELETE journal mode."""

    src_path = str(Path(src_path))
    dst_path = str(Path(dst_path))

    with connect_rw(src_path) as src:
        checkpoint_full(src)
        dst_dir = os.path.dirname(os.path.abspath(dst_path)) or "."
        os.makedirs(dst_dir, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            prefix=Path(dst_path).name + ".", suffix=".tmp", dir=dst_dir, delete=False
        )
        tmp_path = tmp.name
        tmp.close()
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
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    delete_sidecars(dst_path)
