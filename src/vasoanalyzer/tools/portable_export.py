"""Utilities for producing portable, single-file .vaso exports."""

from __future__ import annotations

import contextlib
import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

from vasoanalyzer.storage.sqlite_utils import (
    backup_to_delete_mode,
    connect_rw,
    delete_sidecars,
    vacuum_optimize,
)

__all__ = [
    "export_single_file",
    "externalize_snapshot_tiffs",
    "backup_to_delete_mode",
]


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {c[1] for c in cols}


def _guess_asset_tables(conn: sqlite3.Connection) -> list[tuple[str, set[str]]]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    out = []
    for (tname,) in rows:
        cols = _table_cols(conn, tname)
        if (
            "media_type" in cols
            and any(c in cols for c in ("blob", "data", "bytes", "content"))
            and any(c in cols for c in ("is_embedded", "embedded"))
            and any(c in cols for c in ("sha256", "hash"))
            and any(c in cols for c in ("path_hint", "relative_path", "path"))
        ):
            out.append((tname, cols))
    return out


def _first_in(options: list[str], cols: set[str]) -> str | None:
    for name in options:
        if name in cols:
            return name
    return None


def externalize_snapshot_tiffs(conn: sqlite3.Connection, extract_dir: str | None) -> int:
    """Convert embedded TIFF assets to linked records, optionally extracting them."""

    total = 0
    for tname, cols in _guess_asset_tables(conn):
        emb_col = "is_embedded" if "is_embedded" in cols else "embedded"
        blob_col = _first_in(["blob", "data", "bytes", "content"], cols)
        sha_col = _first_in(["sha256", "hash"], cols)
        path_col = _first_in(["path_hint", "relative_path", "path"], cols)
        if not (emb_col and blob_col and path_col):
            continue

        rows = conn.execute(
            f"SELECT rowid, {blob_col}, {sha_col if sha_col else 'NULL'}, "
            f"{path_col if path_col else 'NULL'}, media_type "
            f"FROM {tname} WHERE {emb_col}=1 AND media_type LIKE 'image/tiff%'"
        ).fetchall()

        for row in rows:
            rowid, blob, sha, path_hint, media_type = row
            if sha is None and blob is not None:
                sha = hashlib.sha256(blob).hexdigest()
            rel = f"assets/{sha}.tif" if sha else None

            if extract_dir and blob:
                dest = Path(extract_dir) / (rel or f"assets/{rowid}.tif")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(blob)

            fields: list[str] = []
            params: list[object] = []
            fields.append(f"{emb_col}=?")
            params.append(0)
            fields.append(f"{blob_col}=?")
            params.append(None)
            if sha_col:
                fields.append(f"{sha_col}=?")
                params.append(sha)
            if path_col:
                fields.append(f"{path_col}=?")
                params.append(rel)
            params.append(rowid)
            conn.execute(f"UPDATE {tname} SET {', '.join(fields)} WHERE rowid=?", params)
            total += 1
    return total


def export_single_file(
    db_path: str,
    out_path: str | None = None,
    *,
    link_snapshot_tiffs: bool = True,
    extract_tiffs_dir: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> str:
    """Create a shareable `.vaso` copy with DELETE journal mode."""

    db_path = str(Path(db_path))
    if out_path is None:
        p = Path(db_path)
        out_path = str(p.with_name(p.stem + ".shareable" + p.suffix))

    if progress_callback:
        progress_callback(20, "Creating backup")

    backup_to_delete_mode(db_path, out_path)

    if link_snapshot_tiffs:
        if progress_callback:
            progress_callback(50, "Externalizing snapshots")

        with connect_rw(out_path) as conn:
            changed = externalize_snapshot_tiffs(conn, extract_tiffs_dir)
            if changed:
                with contextlib.suppress(Exception):
                    conn.commit()

            if progress_callback:
                progress_callback(75, "Optimizing database")

            vacuum_optimize(conn)

    if progress_callback:
        progress_callback(90, "Cleaning up")

    delete_sidecars(out_path)

    if progress_callback:
        progress_callback(100, "Complete")

    return out_path
