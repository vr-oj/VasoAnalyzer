"""Asset management helpers for SQLite projects."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

__all__ = [
    "hash_file",
    "iter_chunks_from_file",
    "iter_chunks_from_bytes",
    "write_blob_chunks",
    "reassemble_blob",
    "register_asset",
    "list_assets",
    "fetch_asset_bytes",
]


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest for ``path``."""

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_chunks_from_file(path: Path, chunk_size: int) -> Iterator[bytes]:
    """Yield binary chunks from ``path``."""

    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


def iter_chunks_from_bytes(data: bytes, chunk_size: int) -> Iterator[bytes]:
    """Yield slices of ``data`` sized ``chunk_size``."""

    view = memoryview(data)
    for offset in range(0, len(view), chunk_size):
        yield bytes(view[offset : offset + chunk_size])


def write_blob_chunks(conn: sqlite3.Connection, asset_id: int, chunks: Iterable[bytes]) -> None:
    """Persist blob chunks for an embedded asset."""

    conn.execute("DELETE FROM blob_chunk WHERE asset_id = ?", (asset_id,))
    for seq, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO blob_chunk(asset_id, seq, data) VALUES(?, ?, ?)",
            (asset_id, seq, sqlite3.Binary(chunk)),
        )


def reassemble_blob(conn: sqlite3.Connection, asset_id: int) -> bytes:
    """Reconstruct the blob payload for ``asset_id``."""

    rows = conn.execute(
        "SELECT data FROM blob_chunk WHERE asset_id = ? ORDER BY seq ASC",
        (asset_id,),
    ).fetchall()
    if not rows:
        return b""
    return b"".join(row[0] for row in rows if row[0] is not None)


def register_asset(
    conn: sqlite3.Connection,
    dataset_id: int,
    role: str,
    storage: str,
    *,
    rel_path: str | None,
    sha256: str,
    size_bytes: int,
    mime: str | None,
) -> int:
    """Insert a new asset metadata row and return its ID."""

    cur = conn.execute(
        """
        INSERT INTO asset(dataset_id, role, storage, rel_path, sha256, bytes, mime)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            role,
            storage,
            rel_path,
            sha256,
            size_bytes,
            mime,
        ),
    )
    last_rowid = cur.lastrowid
    if last_rowid is None:
        raise RuntimeError("Failed to insert asset metadata row")
    return int(last_rowid)


def list_assets(conn: sqlite3.Connection, dataset_id: int) -> list[dict]:
    """Return asset metadata for ``dataset_id``."""

    rows = conn.execute(
        """
        SELECT id, role, storage, rel_path, sha256, bytes, mime
          FROM asset
         WHERE dataset_id = ?
         ORDER BY id ASC
        """,
        (dataset_id,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "role": row[1],
            "storage": row[2],
            "rel_path": row[3],
            "sha256": row[4],
            "bytes": row[5],
            "mime": row[6],
        }
        for row in rows
    ]


def fetch_asset_bytes(conn: sqlite3.Connection, project_path: Path, asset_id: int) -> bytes:
    """Return the byte payload for ``asset_id`` respecting storage mode."""

    row = conn.execute(
        "SELECT storage, rel_path FROM asset WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Asset {asset_id} does not exist")
    storage, rel_path = row
    if storage == "embedded":
        return cast(bytes, reassemble_blob(conn, asset_id))
    if storage == "external" and rel_path:
        asset_path = project_path.parent / rel_path
        if asset_path.exists():
            return cast(bytes, asset_path.read_bytes())
    return b""
