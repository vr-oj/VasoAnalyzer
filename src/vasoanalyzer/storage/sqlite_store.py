"""
SQLite-backed project storage for VasoAnalyzer.

This module implements the new single-file ``.vaso`` project format based on a
SQLite database.  It is responsible for creating projects, inserting datasets,
tracking linked or embedded assets, and producing portable bundles that include
external resources.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

import mimetypes
import pandas as pd
from vasoanalyzer.storage.sqlite import projects as _projects
from vasoanalyzer.storage.sqlite.utils import open_db
from vasoanalyzer.storage.sqlite import traces as _traces
from vasoanalyzer.storage.sqlite import events as _events
from vasoanalyzer.storage.sqlite import assets as _assets
from .sqlite_utils import checkpoint_full as _sqlite_checkpoint_full
from .sqlite_utils import optimize as _sqlite_optimize

__all__ = [
    "ProjectStore",
    "SCHEMA_VERSION",
    "create_project",
    "open_project",
    "close_project",
    "save_project",
    "save_project_as",
    "add_dataset",
    "update_dataset_meta",
    "add_or_update_asset",
    "get_trace",
    "get_events",
    "add_result",
    "get_results",
    "get_asset_bytes",
    "list_assets",
    "iter_datasets",
    "get_dataset_meta",
    "pack_bundle",
    "unpack_bundle",
    "write_autosave",
    "restore_autosave",
]

SCHEMA_VERSION = 1
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


@dataclass
class ProjectStore:
    """Lightweight wrapper for an open SQLite project."""

    path: Path
    conn: sqlite3.Connection
    dirty: bool = False

    def mark_dirty(self) -> None:
        self.dirty = True

    def commit(self) -> None:
        self.conn.commit()
        self.dirty = False

    def close(self) -> None:
        try:
            if self.dirty:
                self.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "ProjectStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Project lifecycle helpers


def create_project(path: str | os.PathLike[str], *, app_version: str, timezone: str) -> ProjectStore:
    """Create a new SQLite project file at ``path`` and return an open store."""

    project_path = Path(path)
    project_path.parent.mkdir(parents=True, exist_ok=True)

    conn = open_db(project_path.as_posix(), apply_pragmas=False)
    _projects.apply_default_pragmas(conn)
    _projects.ensure_schema(
        conn,
        schema_version=SCHEMA_VERSION,
        now=_utc_now(),
        app_version=app_version,
        timezone=timezone,
    )
    return ProjectStore(path=project_path, conn=conn, dirty=False)


def open_project(path: str | os.PathLike[str]) -> ProjectStore:
    """Open an existing SQLite project and return a :class:`ProjectStore`."""

    project_path = Path(path)
    if not project_path.exists():
        raise FileNotFoundError(path)

    conn = open_db(project_path.as_posix(), apply_pragmas=False)
    _projects.apply_default_pragmas(conn)

    version = _projects.get_user_version(conn)
    if version == 0:
        # A bare database; initialise it now.
        _projects.ensure_schema(
            conn,
            schema_version=SCHEMA_VERSION,
            now=_utc_now(),
        )
    elif version < SCHEMA_VERSION:
        _projects.run_migrations(
            conn,
            version,
            SCHEMA_VERSION,
            now=_utc_now(),
        )
    elif version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Project schema version {version} is newer than supported {SCHEMA_VERSION}"
        )

    return ProjectStore(path=project_path, conn=conn, dirty=False)


def save_project(store: ProjectStore) -> None:
    """Flush pending changes and update ``modified_utc`` metadata."""

    now = _utc_now()
    _projects.write_meta(store.conn, {"modified_utc": now})
    store.commit()
    _sqlite_checkpoint_full(store.conn)
    _sqlite_optimize(store.conn)


def save_project_as(store: ProjectStore, new_path: str | os.PathLike[str]) -> None:
    """Persist ``store`` to ``new_path`` atomically and retarget the connection."""

    dest_path = Path(new_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        suffix=dest_path.suffix or ".vaso", dir=dest_path.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with sqlite3.connect(tmp_path.as_posix()) as out_conn:
            store.conn.backup(out_conn)
        os.replace(tmp_path, dest_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # Re-open connection so WAL and temp files point at the new location.
    store.conn.close()
    conn = open_db(dest_path.as_posix(), apply_pragmas=False)
    _projects.apply_default_pragmas(conn)
    store.conn = conn
    store.path = dest_path
    store.dirty = False
    _sqlite_checkpoint_full(store.conn)
    _sqlite_optimize(store.conn)


def close_project(store: ProjectStore) -> None:
    """Close ``store`` committing pending work if necessary."""

    store.close()


# ---------------------------------------------------------------------------
# Dataset helpers


def add_dataset(
    store: ProjectStore,
    name: str,
    trace_df: pd.DataFrame,
    events_df: Optional[pd.DataFrame],
    *,
    metadata: Optional[dict] = None,
    tiff_path: Optional[str] = None,
    embed_tiff: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    thumbnail_png: Optional[bytes] = None,
) -> int:
    """Insert a dataset with trace/events rows and optional TIFF asset."""

    metadata = metadata or {}
    now = _utc_now()
    extra_json = json.dumps(metadata.get("extra_json", {})) if metadata.get("extra_json") else None

    with store.conn:
        cur = store.conn.execute(
            """
            INSERT INTO dataset(name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                now,
                metadata.get("notes"),
                metadata.get("fps"),
                metadata.get("pixel_size_um"),
                metadata.get("t0_seconds", 0.0),
                extra_json,
            ),
        )
        dataset_id = cur.lastrowid

        trace_rows = list(_traces.prepare_trace_rows(dataset_id, trace_df))
        if trace_rows:
            store.conn.executemany(
                """
                INSERT INTO trace(dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                trace_rows,
            )

        if events_df is not None and not events_df.empty:
            event_rows = list(_events.prepare_event_rows(dataset_id, events_df))
            if event_rows:
                store.conn.executemany(
                    """
                    INSERT INTO event(dataset_id, t_seconds, label, frame, p_avg, p1, p2, temp, extra_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    event_rows,
                )

        if thumbnail_png:
            store.conn.execute(
                "INSERT OR REPLACE INTO thumbnail(dataset_id, png) VALUES(?, ?)",
                (dataset_id, sqlite3.Binary(thumbnail_png)),
            )

        if tiff_path:
            add_or_update_asset(
                store,
                dataset_id,
                role="tiff",
                path_or_bytes=tiff_path,
                embed=embed_tiff,
                chunk_size=chunk_size,
            )

    store.mark_dirty()
    return dataset_id


def update_dataset_meta(store: ProjectStore, dataset_id: int, **fields) -> None:
    """Update metadata columns for ``dataset_id``."""

    if not fields:
        return

    allowed = {"name", "notes", "fps", "pixel_size_um", "t0_seconds"}
    extra = fields.pop("extra_json", None)
    to_update = {k: v for k, v in fields.items() if k in allowed}
    assignments = ", ".join(f"{col} = ?" for col in to_update)
    params: list[object] = list(to_update.values())

    if extra is not None:
        assignments = f"{assignments}, extra_json = ?" if assignments else "extra_json = ?"
        params.append(json.dumps(extra) if isinstance(extra, dict) else extra)

    params.extend([dataset_id])
    store.conn.execute(f"UPDATE dataset SET {assignments} WHERE id = ?", params)
    store.mark_dirty()


def add_or_update_asset(
    store: ProjectStore,
    dataset_id: int,
    role: str,
    path_or_bytes: str | os.PathLike[str] | bytes | bytearray,
    *,
    embed: bool,
    mime: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    """Insert or replace an asset for ``dataset_id``."""

    if isinstance(path_or_bytes, (bytes, bytearray)):
        data_bytes = bytes(path_or_bytes)
        sha256 = hashlib.sha256(data_bytes).hexdigest()
        size = len(data_bytes)
        rel_path = None
        storage = "embedded" if embed else "external"
    else:
        asset_path = Path(path_or_bytes)
        if not asset_path.exists():
            raise FileNotFoundError(asset_path)
        sha256 = _assets.hash_file(asset_path)
        size = asset_path.stat().st_size
        storage = "embedded" if embed else "external"
        rel_path = (
            asset_path
            if storage == "embedded"
            else os.path.relpath(asset_path, store.path.parent)
        )
        data_bytes = None

    mime = mime or _guess_mime(rel_path if isinstance(rel_path, str) else path_or_bytes)

    with store.conn:
        cur = store.conn.execute(
            """
            SELECT id FROM asset
            WHERE dataset_id = ? AND role = ?
            """,
            (dataset_id, role),
        )
        row = cur.fetchone()
        if row:
            asset_id = int(row[0])
            store.conn.execute(
                """
                UPDATE asset
                   SET storage = ?, rel_path = ?, sha256 = ?, bytes = ?, mime = ?
                 WHERE id = ?
                """,
                (
                    storage,
                    rel_path,
                    sha256,
                    size,
                    mime,
                    asset_id,
                ),
            )
            store.conn.execute("DELETE FROM blob_chunk WHERE asset_id = ?", (asset_id,))
        else:
            cur = store.conn.execute(
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
                    size,
                    mime,
                ),
            )
            asset_id = cur.lastrowid

        if storage == "embedded":
            if data_bytes is not None:
                _assets.write_blob_chunks(
                    store.conn,
                    asset_id,
                    _assets.iter_chunks_from_bytes(data_bytes, chunk_size),
                )
            else:
                assert not isinstance(path_or_bytes, (bytes, bytearray))
                _assets.write_blob_chunks(
                    store.conn,
                    asset_id,
                    _assets.iter_chunks_from_file(Path(path_or_bytes), chunk_size),
                )

    store.mark_dirty()
    return asset_id


def get_trace(
    store: ProjectStore,
    dataset_id: int,
    t0: Optional[float] = None,
    t1: Optional[float] = None,
) -> pd.DataFrame:
    """Return a trace DataFrame for ``dataset_id`` filtered to ``[t0, t1]``."""

    return _traces.fetch_trace_dataframe(store.conn, dataset_id, t0, t1)


def get_events(
    store: ProjectStore,
    dataset_id: int,
    t0: Optional[float] = None,
    t1: Optional[float] = None,
) -> pd.DataFrame:
    """Return events for ``dataset_id``."""

    return _events.fetch_events_dataframe(store.conn, dataset_id, t0, t1)


def add_result(
    store: ProjectStore,
    dataset_id: int,
    kind: str,
    version: str,
    payload: dict,
) -> int:
    """Insert a new result row for ``dataset_id``."""

    now = _utc_now()
    cur = store.conn.execute(
        """
        INSERT INTO result(dataset_id, kind, version, created_utc, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (dataset_id, kind, version, now, json.dumps(payload)),
    )
    store.mark_dirty()
    return int(cur.lastrowid)


def get_results(
    store: ProjectStore,
    dataset_id: int,
    kind: Optional[str] = None,
) -> list[dict]:
    """Return result payloads for ``dataset_id`` (optionally filtered by kind)."""

    query = "SELECT id, kind, version, created_utc, payload_json FROM result WHERE dataset_id = ?"
    params: list[object] = [dataset_id]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_utc DESC"

    rows = store.conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        payload_json = row[4]
        payload = json.loads(payload_json) if payload_json else {}
        results.append(
            {
                "id": row[0],
                "kind": row[1],
                "version": row[2],
                "created_utc": row[3],
                "payload": payload,
            }
        )
    return results


def list_assets(store: ProjectStore, dataset_id: int) -> list[dict]:
    """Return metadata for assets linked to ``dataset_id``."""

    return _assets.list_assets(store.conn, dataset_id)


def get_asset_bytes(store: ProjectStore, asset_id: int) -> bytes:
    """Return the binary payload for ``asset_id``."""

    return _assets.fetch_asset_bytes(store.conn, store.path, asset_id)


def iter_datasets(store: ProjectStore) -> Iterator[dict]:
    """Yield metadata dictionaries for all datasets in the project."""

    cursor = store.conn.execute(
        """
        SELECT id, name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json
          FROM dataset
         ORDER BY id ASC
        """
    )
    for row in cursor:
        extra = json.loads(row[7]) if row[7] else None
        yield {
            "id": row[0],
            "name": row[1],
            "created_utc": row[2],
            "notes": row[3],
            "fps": row[4],
            "pixel_size_um": row[5],
            "t0_seconds": row[6],
            "extra": extra,
        }


def get_dataset_meta(store: ProjectStore, dataset_id: int) -> dict | None:
    """Return metadata for a single dataset."""

    row = store.conn.execute(
        """
        SELECT id, name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json
          FROM dataset
         WHERE id = ?
        """,
        (dataset_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "created_utc": row[2],
        "notes": row[3],
        "fps": row[4],
        "pixel_size_um": row[5],
        "t0_seconds": row[6],
        "extra": json.loads(row[7]) if row[7] else None,
    }


# ---------------------------------------------------------------------------
# Bundling helpers


def pack_bundle(
    vaso_path: str | os.PathLike[str],
    vasopack_path: str | os.PathLike[str],
    *,
    embed_threshold_mb: int = 64,
) -> None:
    """Create a ``.vasopack`` bundle containing the project and its assets."""

    project_path = Path(vaso_path)
    if not project_path.exists():
        raise FileNotFoundError(project_path)

    bundle_path = Path(vasopack_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)

        # Copy project file to allow modifications without touching the original.
        temp_project = tmp_root / "project.vaso"
        shutil.copy2(project_path, temp_project)

        with sqlite3.connect(temp_project.as_posix()) as conn:
            _projects.apply_default_pragmas(conn)
            asset_rows = conn.execute(
                "SELECT id, storage, rel_path, sha256, role FROM asset"
            ).fetchall()
            project_dir = project_path.parent
            assets_dir = tmp_root / "assets"
            assets_dir.mkdir(exist_ok=True)

            for asset_id, storage, rel_path, sha256, role in asset_rows:
                if storage == "embedded":
                    continue

                if not rel_path:
                    continue

                abs_path = project_dir / rel_path
                if not abs_path.exists():
                    continue

                size_mb = abs_path.stat().st_size / (1024 * 1024)
                target_name = f"{sha256}{abs_path.suffix or ''}"
                target_path = assets_dir / target_name
                shutil.copy2(abs_path, target_path)

                if size_mb <= embed_threshold_mb:
                    _assets.write_blob_chunks(
                        conn,
                        asset_id,
                        _assets.iter_chunks_from_file(abs_path, DEFAULT_CHUNK_SIZE),
                    )
                    conn.execute(
                        "UPDATE asset SET storage = ?, rel_path = ? WHERE id = ?",
                        ("embedded", None, asset_id),
                    )
                    if target_path.exists():
                        target_path.unlink()
                else:
                    new_rel = os.path.join("assets", target_name)
                    conn.execute(
                        "UPDATE asset SET rel_path = ? WHERE id = ?",
                        (new_rel, asset_id),
                    )

            _projects.write_meta(conn, {"packed_utc": _utc_now()})
            conn.commit()

        bundle_tmp = bundle_path.with_suffix(bundle_path.suffix + ".tmp")
        with zipfile.ZipFile(
            bundle_tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zf:
            for root, _dirs, files in os.walk(tmp_root):
                for file in files:
                    full = Path(root) / file
                    rel = full.relative_to(tmp_root)
                    zf.write(full, rel.as_posix())
        os.replace(bundle_tmp, bundle_path)


def unpack_bundle(vasopack_path: str | os.PathLike[str], dest_dir: str | os.PathLike[str]) -> Path:
    """Extract ``vasopack_path`` into ``dest_dir`` returning the project path."""

    bundle_path = Path(vasopack_path)
    if not bundle_path.exists():
        raise FileNotFoundError(bundle_path)

    import zipfile

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(bundle_path, "r") as zf:
        zf.extractall(dest)

    project_path = dest / "project.vaso"
    if not project_path.exists():
        raise FileNotFoundError("Bundle did not contain project.vaso")
    final_path = dest / bundle_path.with_suffix(".vaso").name
    if final_path.exists():
        final_path.unlink()
    project_path.rename(final_path)

    assets_dir = dest / "assets"
    if assets_dir.exists():
        assets_dir.mkdir(exist_ok=True)
        with sqlite3.connect(final_path.as_posix()) as conn:
            _projects.apply_default_pragmas(conn)
            rows = conn.execute(
                "SELECT id, storage, rel_path, mime FROM asset WHERE storage = 'embedded' AND rel_path IS NULL"
            ).fetchall()
            for asset_id, _storage, _rel_path, mime in rows:
                blob = _assets.reassemble_blob(conn, asset_id)
                if not blob:
                    continue
                sha = hashlib.sha256(blob).hexdigest()
                # Store the asset alongside the bundle for convenience.
                ext = _extension_for_mime(mime)
                out_path = assets_dir / f"{sha}{ext}"
                with open(out_path, "wb") as fh:
                    fh.write(blob)
                conn.execute(
                    "UPDATE asset SET storage = ?, rel_path = ? WHERE id = ?",
                    ("external", os.path.relpath(out_path, final_path.parent), asset_id),
                )
            conn.commit()

    return final_path


# ---------------------------------------------------------------------------
# Autosave helpers


def write_autosave(
    store: ProjectStore,
    autosave_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Write an autosave snapshot for ``store``."""

    if store.path is None:
        raise ValueError("Project store has no associated path")

    autosave = Path(autosave_path) if autosave_path else store.path.with_suffix(
        store.path.suffix + ".autosave"
    )
    autosave.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=autosave.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with sqlite3.connect(tmp_path.as_posix()) as out_conn:
            store.conn.backup(out_conn)
        os.replace(tmp_path, autosave)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return autosave


def restore_autosave(
    autosave_path: str | os.PathLike[str],
    dest_path: str | os.PathLike[str],
) -> Path:
    """Restore an autosave snapshot to ``dest_path``."""

    autosave = Path(autosave_path)
    if not autosave.exists():
        raise FileNotFoundError(autosave)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(autosave.as_posix()) as src, sqlite3.connect(dest.as_posix()) as dst:
        src.backup(dst)
    return dest


# ---------------------------------------------------------------------------
# Internal helpers


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _guess_mime(path: str | os.PathLike[str] | None) -> Optional[str]:
    if not path:
        return None
    guess, _ = mimetypes.guess_type(str(path))
    return guess


def _extension_for_mime(mime: Optional[str]) -> str:
    if not mime:
        return ''
    ext = mimetypes.guess_extension(mime)
    return ext or ''
