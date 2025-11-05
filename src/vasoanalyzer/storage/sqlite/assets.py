"""Asset management helpers for SQLite projects (v3 single-file format)."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import tempfile
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO, NamedTuple, cast

__all__ = [
    "DEFAULT_STREAM_READ_BYTES",
    "hash_file",
    "prepare_asset_from_bytes",
    "prepare_asset_from_path",
    "register_asset",
    "find_asset_by_sha",
    "write_blob_chunks_from_stream",
    "list_assets",
    "fetch_asset_bytes",
    "get_ref_by_role",
    "upsert_ref",
    "delete_ref",
    "count_refs",
    "delete_asset",
]

DEFAULT_STREAM_READ_BYTES = 512 * 1024  # 512 KiB chunks for hashing/compression


class PreparedAsset(NamedTuple):
    """Staged asset payload ready for persistence."""

    sha256: str
    size_bytes: int
    compressed: bool
    chunk_size: int
    source: BinaryIO
    closer: Callable[[], None]


def hash_file(path: Path, *, read_size: int = DEFAULT_STREAM_READ_BYTES) -> str:
    """Return the SHA-256 hex digest for ``path``."""

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(read_size), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _compress_stream(
    stream: BinaryIO,
    *,
    chunk_size: int,
    read_size: int = DEFAULT_STREAM_READ_BYTES,
    level: int = 6,
) -> PreparedAsset:
    """Compress ``stream`` into a spooled temporary file returning staging info."""

    compressor = zlib.compressobj(level=level)
    sha256 = hashlib.sha256()
    size_bytes = 0
    spool = tempfile.SpooledTemporaryFile(max_size=chunk_size * 4)

    try:
        while True:
            chunk = stream.read(read_size)
            if not chunk:
                break
            size_bytes += len(chunk)
            sha256.update(chunk)
            compressed = compressor.compress(chunk)
            if compressed:
                spool.write(compressed)
        flush_data = compressor.flush()
        if flush_data:
            spool.write(flush_data)
        spool.seek(0)
        return PreparedAsset(
            sha256=sha256.hexdigest(),
            size_bytes=size_bytes,
            compressed=True,
            chunk_size=chunk_size,
            source=cast(BinaryIO, spool),
            closer=spool.close,
        )
    except Exception:
        spool.close()
        raise


def prepare_asset_from_path(path: Path, *, chunk_size: int) -> PreparedAsset:
    """Return a :class:`PreparedAsset` for ``path``."""

    with open(path, "rb") as fh:
        return _compress_stream(fh, chunk_size=chunk_size)


def prepare_asset_from_bytes(data: bytes, *, chunk_size: int) -> PreparedAsset:
    """Return a :class:`PreparedAsset` for raw ``data``."""

    stream = io.BytesIO(data)
    try:
        prepared = _compress_stream(stream, chunk_size=chunk_size)
    finally:
        stream.close()
    return prepared


def register_asset(
    conn: sqlite3.Connection,
    *,
    kind: str,
    sha256: str,
    size_bytes: int,
    compressed: bool,
    chunk_size: int,
    original_name: str | None,
    mime: str | None,
) -> int:
    """Insert a new asset metadata row and return its identifier."""

    cur = conn.execute(
        """
        INSERT INTO asset(kind, sha256, size_bytes, compressed, chunk_size, original_name, mime)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            sha256,
            size_bytes,
            1 if compressed else 0,
            chunk_size,
            original_name,
            mime,
        ),
    )
    rowid = cur.lastrowid
    if rowid is None:
        raise RuntimeError("Failed to insert asset metadata row")
    return int(rowid)


def find_asset_by_sha(conn: sqlite3.Connection, sha256: str) -> tuple[int, dict] | None:
    """Return ``(asset_id, metadata)`` for ``sha256`` when present."""

    row = conn.execute(
        """
        SELECT id, kind, sha256, size_bytes, compressed, chunk_size, original_name, mime
          FROM asset
         WHERE sha256 = ?
        """,
        (sha256,),
    ).fetchone()
    if not row:
        return None
    asset_id = int(row[0])
    return asset_id, {
        "kind": row[1],
        "sha256": row[2],
        "size_bytes": row[3],
        "compressed": bool(row[4]),
        "chunk_size": row[5],
        "original_name": row[6],
        "mime": row[7],
    }


def write_blob_chunks_from_stream(
    conn: sqlite3.Connection,
    asset_id: int,
    source: BinaryIO,
    *,
    chunk_size: int,
) -> None:
    """Persist compressed payload for ``asset_id`` from ``source``."""

    conn.execute("DELETE FROM blob_chunk WHERE asset_id = ?", (asset_id,))
    seq = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        conn.execute(
            "INSERT INTO blob_chunk(asset_id, seq, data) VALUES(?, ?, ?)",
            (asset_id, seq, sqlite3.Binary(chunk)),
        )
        seq += 1


def list_assets(conn: sqlite3.Connection, dataset_id: int) -> list[dict]:
    """Return asset/ref metadata for ``dataset_id``."""

    rows = conn.execute(
        """
        SELECT a.id, r.role, r.note, a.kind, a.sha256, a.size_bytes,
               a.compressed, a.chunk_size, a.original_name, a.mime
          FROM ref AS r
          JOIN asset AS a ON a.id = r.asset_id
         WHERE r.dataset_id = ?
         ORDER BY a.id ASC
        """,
        (dataset_id,),
    ).fetchall()
    return [
        {
            "id": int(row[0]),
            "role": row[1],
            "note": row[2],
            "kind": row[3],
            "sha256": row[4],
            "size_bytes": row[5],
            "compressed": bool(row[6]),
            "chunk_size": row[7],
            "original_name": row[8],
            "mime": row[9],
        }
        for row in rows
    ]


def _iter_blob_chunks(conn: sqlite3.Connection, asset_id: int) -> Iterator[bytes]:
    for row in conn.execute(
        "SELECT data FROM blob_chunk WHERE asset_id = ? ORDER BY seq ASC",
        (asset_id,),
    ):
        data = row[0]
        if data:
            yield bytes(data)


def fetch_asset_bytes(conn: sqlite3.Connection, asset_id: int) -> bytes:
    """Return the (decompressed) payload for ``asset_id``."""

    row = conn.execute(
        "SELECT compressed FROM asset WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Asset {asset_id} does not exist")
    compressed = bool(row[0])
    chunk_iter = _iter_blob_chunks(conn, asset_id)
    if not compressed:
        return b"".join(chunk_iter)
    decompressor = zlib.decompressobj()
    buffer = bytearray()
    seen = False
    for chunk in chunk_iter:
        seen = True
        buffer.extend(decompressor.decompress(chunk))
    if not seen:
        return b""
    buffer.extend(decompressor.flush())
    return bytes(buffer)


def get_ref_by_role(
    conn: sqlite3.Connection, dataset_id: int, role: str
) -> tuple[int, str | None] | None:
    """Return ``(asset_id, note)`` for ``dataset_id``/``role``."""

    row = conn.execute(
        """
        SELECT asset_id, note
          FROM ref
         WHERE dataset_id = ? AND role = ?
        """,
        (dataset_id, role),
    ).fetchone()
    if not row:
        return None
    return int(row[0]), row[1]


def upsert_ref(
    conn: sqlite3.Connection, *, asset_id: int, dataset_id: int, role: str, note: str | None
) -> None:
    """Create or update a reference between ``dataset_id`` and ``asset_id``."""

    conn.execute(
        """
        INSERT INTO ref(asset_id, dataset_id, role, note)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(asset_id, dataset_id, role)
        DO UPDATE SET note = excluded.note
        """,
        (asset_id, dataset_id, role, note),
    )


def delete_ref(conn: sqlite3.Connection, *, asset_id: int, dataset_id: int, role: str) -> None:
    """Remove ``role`` reference for ``dataset_id``."""

    conn.execute(
        "DELETE FROM ref WHERE asset_id = ? AND dataset_id = ? AND role = ?",
        (asset_id, dataset_id, role),
    )


def count_refs(conn: sqlite3.Connection, asset_id: int) -> int:
    """Return number of references pointing at ``asset_id``."""

    row = conn.execute(
        "SELECT COUNT(*) FROM ref WHERE asset_id = ?",
        (asset_id,),
    ).fetchone()
    return int(row[0] if row and row[0] is not None else 0)


def delete_asset(conn: sqlite3.Connection, asset_id: int) -> None:
    """Delete asset metadata and payload."""

    conn.execute("DELETE FROM asset WHERE id = ?", (asset_id,))
