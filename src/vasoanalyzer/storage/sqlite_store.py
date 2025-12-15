"""
SQLite-backed project storage for VasoAnalyzer.

This module implements the new single-file ``.vaso`` project format based on a
SQLite database.  It is responsible for creating projects, inserting datasets,
tracking linked or embedded assets, and producing portable bundles that include
external resources.
"""

from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

log = logging.getLogger(__name__)

from vasoanalyzer.storage.sqlite import assets as _assets
from vasoanalyzer.storage.sqlite import events as _events
from vasoanalyzer.storage.sqlite import projects as _projects
from vasoanalyzer.storage.sqlite import traces as _traces
from vasoanalyzer.storage.sqlite.utils import open_db, transaction

from .sqlite_utils import backup_to_delete_mode as _sqlite_backup_to_delete_mode
from .sqlite_utils import checkpoint_full as _sqlite_checkpoint_full
from .sqlite_utils import optimize as _sqlite_optimize
from .timeout_wrapper import TimeoutError, timeout

__all__ = [
    "ProjectStore",
    "SCHEMA_VERSION",
    "LegacyProjectError",
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
    "convert_legacy_project",
    "add_figure_recipe",
    "update_figure_recipe",
    "list_figure_recipes",
    "get_figure_recipe",
    "delete_figure_recipe",
    "rename_figure_recipe",
]

SCHEMA_VERSION = 5
DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024  # 2 MiB


class LegacyProjectError(RuntimeError):
    """Raised when attempting to open a legacy project that requires conversion."""

    def __init__(self, path: str | os.PathLike[str], version: int):
        self.path = Path(path)
        self.version = version
        super().__init__(
            f"Project at {self.path} uses schema version {version}; conversion to sqlite-v3 is required."
        )


def _detect_cloud_storage(path: Path) -> tuple[bool, str | None]:
    """
    Determine whether ``path`` is inside a known cloud-storage location.

    Uses the central helper in ``vasoanalyzer.core.project`` but keeps the import
    local to avoid circular dependencies at module import time.
    """
    try:
        from vasoanalyzer.core.project import _is_cloud_storage_path

        return _is_cloud_storage_path(path.as_posix())
    except Exception:
        return False, None


@dataclass
class ProjectStore:
    """Lightweight wrapper for an open SQLite project."""

    path: Path
    conn: sqlite3.Connection
    dirty: bool = False
    # Cloud context (used to pick journal/sync mode and surface UI hints)
    is_cloud_path: bool = False
    cloud_service: str | None = None
    journal_mode: str | None = None

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

    def __enter__(self) -> ProjectStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Project lifecycle helpers


def create_project(
    path: str | os.PathLike[str], *, app_version: str, timezone: str
) -> ProjectStore:
    """Create a new SQLite project file at ``path`` and return an open store."""

    project_path = Path(path)
    project_path.parent.mkdir(parents=True, exist_ok=True)

    is_cloud, cloud_service = _detect_cloud_storage(project_path)

    conn = open_db(project_path.as_posix(), apply_pragmas=False)
    pragma_fn = _projects.apply_cloud_safe_pragmas if is_cloud else _projects.apply_default_pragmas
    pragma_fn(conn)
    journal_mode = "DELETE" if is_cloud else "WAL"
    _projects.ensure_schema(
        conn,
        schema_version=SCHEMA_VERSION,
        now=_utc_now(),
        app_version=app_version,
        timezone=timezone,
    )
    return ProjectStore(
        path=project_path,
        conn=conn,
        dirty=False,
        is_cloud_path=is_cloud,
        cloud_service=cloud_service,
        journal_mode=journal_mode,
    )


def open_project(path: str | os.PathLike[str]) -> ProjectStore:
    """Open an existing SQLite project (bundle or legacy) and return a :class:`ProjectStore`.

    Automatically handles both .vasopack bundle directories and legacy .vaso files.
    """

    project_path = Path(path)
    if not project_path.exists():
        raise FileNotFoundError(path)

    is_cloud, cloud_service = _detect_cloud_storage(project_path)
    pragma_fn = _projects.apply_cloud_safe_pragmas if is_cloud else _projects.apply_default_pragmas
    journal_mode = "DELETE" if is_cloud else "WAL"

    # Check if this is a bundle format
    from .project_storage import get_project_format, open_unified_project

    fmt = get_project_format(project_path)

    if fmt in ("bundle-v1", "zip-bundle-v1"):
        # Open as bundle and return wrapped ProjectStore
        unified_store = open_unified_project(project_path, readonly=False, auto_migrate=False)
        # Return the unified store (which is already a ProjectStore-compatible object)
        return ProjectStore(
            path=unified_store.path,
            conn=unified_store.conn,
            dirty=unified_store.dirty,
            is_cloud_path=getattr(unified_store, "is_cloud_path", is_cloud),
            cloud_service=getattr(unified_store, "cloud_service", cloud_service),
            journal_mode=getattr(unified_store, "journal_mode", journal_mode),
        )

    # Legacy format: open directly
    conn = open_db(project_path.as_posix(), apply_pragmas=False)
    pragma_fn(conn)

    version = _projects.get_user_version(conn)
    if version == 0:
        # A bare database; initialise it now.
        _projects.ensure_schema(
            conn,
            schema_version=SCHEMA_VERSION,
            now=_utc_now(),
        )
    elif version < SCHEMA_VERSION:
        # Auto-migrate from older schema version
        if version == 1:
            # v1 requires conversion to sqlite-v3 format (cannot auto-migrate)
            conn.close()
            raise LegacyProjectError(project_path, version)
        else:
            # v2 → v3: Auto-migrate with backup
            log.info(f"Auto-migrating project from v{version} to v{SCHEMA_VERSION}")

            # Create backup before migration
            import shutil
            backup_path = project_path.as_posix().replace('.vaso', f'.v{version}.backup.vaso')
            conn.close()  # Close before copying
            shutil.copy2(project_path.as_posix(), backup_path)
            log.info(f"Created backup: {backup_path}")

            # Reopen and migrate
            conn = open_db(project_path.as_posix(), apply_pragmas=False)
            pragma_fn(conn)
            _projects.run_migrations(
                conn,
                start=version,
                target=SCHEMA_VERSION,
                now=_utc_now(),
            )
            log.info(f"Migration complete: v{version} → v{SCHEMA_VERSION}")
    elif version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Project schema version {version} is newer than supported {SCHEMA_VERSION}"
        )

    return ProjectStore(
        path=project_path,
        conn=conn,
        dirty=False,
        is_cloud_path=is_cloud,
        cloud_service=cloud_service,
        journal_mode=journal_mode,
    )


def save_project(store: ProjectStore, *, skip_optimize: bool = False) -> None:
    """Flush pending changes and update ``modified_utc`` metadata.

    Args:
        store: The ProjectStore to save
        skip_optimize: If True, skip the expensive OPTIMIZE operation (useful during app close)
    """

    log.info(
        "SAVE: store.save_project entry path=%s skip_optimize=%s",
        getattr(store, "path", None),
        skip_optimize,
    )

    now = _utc_now()
    _projects.write_meta(store.conn, {"modified_utc": now, "modified_at": now})
    log.info("SAVE: store.save_project checkpoint/commit start")
    store.commit()
    _sqlite_checkpoint_full(store.conn)
    log.info("SAVE: store.save_project checkpoint/commit finished")

    project_path = getattr(store, "path", None)
    if not project_path:
        log.info("SAVE: store.save_project exit (no path attached)")
        return

    tmp_path = project_path.with_suffix(project_path.suffix + ".tmp")
    try:
        _sqlite_backup_to_delete_mode(project_path, tmp_path)
        with open(tmp_path, "rb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        store.conn.close()
        os.replace(tmp_path, project_path)
        conn = open_db(project_path.as_posix(), apply_pragmas=False)
        pragma_fn = (
            _projects.apply_cloud_safe_pragmas
            if getattr(store, "is_cloud_path", False)
            else _projects.apply_default_pragmas
        )
        pragma_fn(conn)
        store.journal_mode = "DELETE" if getattr(store, "is_cloud_path", False) else "WAL"
        store.conn = conn
        store.dirty = False
        if not skip_optimize:
            log.info("SAVE: store.save_project optimizing database path=%s", project_path)
            _sqlite_optimize(store.conn)
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()

    log.info(
        "SAVE: store.save_project completed path=%s skip_optimize=%s",
        project_path,
        skip_optimize,
    )


def save_project_as(store: ProjectStore, new_path: str | os.PathLike[str]) -> None:
    """Persist ``store`` to ``new_path`` atomically and retarget the connection."""

    dest_path = Path(new_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(suffix=dest_path.suffix or ".vaso", dir=dest_path.parent)
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
    is_cloud, cloud_service = _detect_cloud_storage(dest_path)
    pragma_fn = _projects.apply_cloud_safe_pragmas if is_cloud else _projects.apply_default_pragmas
    pragma_fn(conn)
    store.is_cloud_path = is_cloud
    store.cloud_service = cloud_service
    store.journal_mode = "DELETE" if is_cloud else "WAL"
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
    events_df: pd.DataFrame | None,
    *,
    metadata: dict | None = None,
    tiff_path: str | None = None,
    embed_tiff: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    thumbnail_png: bytes | None = None,
) -> int:
    """Insert a dataset with trace/events rows and optional TIFF asset."""

    dataset_timer = time.perf_counter()
    trace_len = len(trace_df.index) if isinstance(trace_df, pd.DataFrame) else 0
    event_len = len(events_df.index) if isinstance(events_df, pd.DataFrame) else 0
    log.info(
        "TRACE-SAVE: add_dataset start name=%s trace_rows=%d event_rows=%d embed_tiff=%s",
        name,
        trace_len,
        event_len,
        embed_tiff,
    )

    metadata = metadata or {}
    now = _utc_now()

    # Safely serialize extra_json with proper UTF-8 encoding
    extra_json = None
    if metadata.get("extra_json"):
        try:
            # Use ensure_ascii=False to properly handle Unicode paths,
            # but JSON will be stored as UTF-8 text in SQLite
            extra_json = json.dumps(metadata["extra_json"], ensure_ascii=False)
        except (TypeError, ValueError) as e:
            import logging

            logging.getLogger(__name__).error(
                f"Failed to serialize extra_json for dataset '{name}': {e}", exc_info=True
            )
            # Continue with None rather than failing the entire operation
            extra_json = None

    log.info("TRACE-SAVE: begin transaction for dataset name=%s", name)
    with store.conn:
        dataset_sql = (
            "INSERT INTO dataset(name, created_utc, notes, fps, pixel_size_um, "
            "t0_seconds, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        cur = store.conn.execute(
            dataset_sql,
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
        dataset_rowid = cur.lastrowid
        if dataset_rowid is None:
            raise RuntimeError("Failed to insert dataset row")
        dataset_id = int(dataset_rowid)

        trace_prep_start = time.perf_counter()
        trace_rows = list(_traces.prepare_trace_rows(dataset_id, trace_df))
        log.info(
            "TRACE-SAVE: prepare_trace_rows finished dataset_id=%s rows=%d duration=%.2fs",
            dataset_id,
            len(trace_rows),
            time.perf_counter() - trace_prep_start,
        )
        if trace_rows:
            log.info(
                "TRACE-SAVE: inserting %d trace rows into DB for dataset_id=%s",
                len(trace_rows),
                dataset_id,
            )
            TRACE_INSERT_TIMEOUT = 180  # seconds; adjust if needed

            try:
                with timeout(TRACE_INSERT_TIMEOUT):
                    store.conn.executemany(
                        """
                        INSERT INTO trace(dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        trace_rows,
                    )
            except TimeoutError:
                log.error(
                    "TRACE-SAVE: trace insert timed out for dataset_id=%s after %ss "
                    "(rows=%d) - likely slow/locked storage backend",
                    dataset_id,
                    TRACE_INSERT_TIMEOUT,
                    len(trace_rows),
                    exc_info=True,
                )
                raise

            log.info(
                "TRACE-SAVE: insert completed for dataset_id=%s (rows=%d)",
                dataset_id,
                len(trace_rows),
            )

        if events_df is not None and not events_df.empty:
            event_rows = list(_events.prepare_event_rows(dataset_id, events_df))
            log.debug("Prepared %d event rows for dataset_id=%s", len(event_rows), dataset_id)
            if event_rows:
                log.debug("Executing SQL INSERT for %d events", len(event_rows))
                log.info(
                    "TRACE-SAVE: inserting %d event rows into DB for dataset_id=%s",
                    len(event_rows),
                    dataset_id,
                )
                store.conn.executemany(
                    (
                        "INSERT INTO event("
                        "dataset_id, t_seconds, label, frame, p_avg, p1, p2, temp, extra_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    event_rows,
                )
                log.info(
                    "TRACE-SAVE: event insert completed for dataset_id=%s rows=%d",
                    dataset_id,
                    len(event_rows),
                )
                log.debug("SQL INSERT completed for %d events", len(event_rows))

                # DEBUG: Verify the data was written
                cursor = store.conn.execute(
                    "SELECT COUNT(*) FROM event WHERE dataset_id = ?", (dataset_id,)
                )
                count = cursor.fetchone()[0]
                log.debug(
                    "Verification: %d events now in database for dataset_id=%s",
                    count,
                    dataset_id,
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
                embed=True,
                chunk_size=chunk_size,
                note="source-tiff",
            )

    store.mark_dirty()
    log.info(
        "TRACE-SAVE: dataset_id=%s transaction committed name=%s elapsed=%.2fs",
        dataset_id,
        name,
        time.perf_counter() - dataset_timer,
    )
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
        # Safely serialize extra JSON
        if isinstance(extra, dict):
            try:
                params.append(json.dumps(extra, ensure_ascii=False))
            except (TypeError, ValueError) as e:
                import logging

                logging.getLogger(__name__).error(
                    f"Failed to serialize extra_json for dataset {dataset_id}: {e}", exc_info=True
                )
                params.append(None)
        else:
            params.append(extra)

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
    mime: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    note: str | None = None,
    original_name: str | None = None,
) -> int:
    """Insert or replace an embedded asset reference for ``dataset_id``."""

    if not embed:
        raise ValueError("External assets are not supported in the sqlite-v3 project format")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    mime_source: str | os.PathLike[str] | None = None
    original_name_hint = original_name

    if isinstance(path_or_bytes, bytes | bytearray):
        payload_bytes = bytes(path_or_bytes)
        prepared = _assets.prepare_asset_from_bytes(payload_bytes, chunk_size=chunk_size)
    else:
        asset_path = Path(path_or_bytes)
        if not asset_path.exists():
            raise FileNotFoundError(asset_path)
        prepared = _assets.prepare_asset_from_path(asset_path, chunk_size=chunk_size)
        mime_source = asset_path
        original_name_hint = asset_path.name

    if mime_source is None and isinstance(path_or_bytes, str | os.PathLike):
        mime_source = path_or_bytes
    mime = mime or _guess_mime(mime_source)

    asset_id: int
    previous_asset_id: int | None = None

    try:
        with store.conn:
            ref_row = _assets.get_ref_by_role(store.conn, dataset_id, role)
            if ref_row:
                previous_asset_id = ref_row[0]

            existing = _assets.find_asset_by_sha(store.conn, prepared.sha256)
            if existing:
                asset_id = existing[0]
            else:
                asset_id = _assets.register_asset(
                    store.conn,
                    kind=role,
                    sha256=prepared.sha256,
                    size_bytes=prepared.size_bytes,
                    compressed=prepared.compressed,
                    chunk_size=prepared.chunk_size,
                    original_name=original_name_hint,
                    mime=mime,
                )
                prepared.source.seek(0)
                _assets.write_blob_chunks_from_stream(
                    store.conn,
                    asset_id,
                    prepared.source,
                    chunk_size=prepared.chunk_size,
                )

            _assets.upsert_ref(
                store.conn,
                asset_id=asset_id,
                dataset_id=dataset_id,
                role=role,
                note=note,
            )

            if previous_asset_id is not None and previous_asset_id != asset_id:
                _assets.delete_ref(
                    store.conn,
                    asset_id=previous_asset_id,
                    dataset_id=dataset_id,
                    role=role,
                )
                if _assets.count_refs(store.conn, previous_asset_id) == 0:
                    _assets.delete_asset(store.conn, previous_asset_id)
    finally:
        prepared.closer()

    store.mark_dirty()
    return asset_id


def get_trace(
    store: ProjectStore,
    dataset_id: int,
    t0: float | None = None,
    t1: float | None = None,
) -> pd.DataFrame:
    """Return a trace DataFrame for ``dataset_id`` filtered to ``[t0, t1]``."""

    return _traces.fetch_trace_dataframe(store.conn, dataset_id, t0, t1)


def get_events(
    store: ProjectStore,
    dataset_id: int,
    t0: float | None = None,
    t1: float | None = None,
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
    result_rowid = cur.lastrowid
    if result_rowid is None:
        raise RuntimeError("Failed to insert result row")
    return int(result_rowid)


def get_results(
    store: ProjectStore,
    dataset_id: int,
    kind: str | None = None,
) -> list[dict[str, Any]]:
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


def list_assets(store: ProjectStore, dataset_id: int) -> list[dict[str, Any]]:
    """Return metadata for assets linked to ``dataset_id``."""

    return cast(list[dict[str, Any]], _assets.list_assets(store.conn, dataset_id))


def get_asset_bytes(store: ProjectStore, asset_id: int) -> bytes:
    """Return the binary payload for ``asset_id``."""

    return cast(bytes, _assets.fetch_asset_bytes(store.conn, asset_id))


def iter_datasets(store: ProjectStore) -> Iterator[dict[str, Any]]:
    """Yield metadata dictionaries for all datasets in the project."""

    cursor = store.conn.execute(
        """
        SELECT id, name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json
          FROM dataset
         ORDER BY id ASC
        """
    )

    import logging

    log = logging.getLogger(__name__)

    for row in cursor:
        extra = None
        extra_json_str = row[7]

        if extra_json_str:
            try:
                extra = json.loads(extra_json_str)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
                # Corrupted JSON - log error with diagnostic info
                truncated = extra_json_str[:200] if len(extra_json_str) > 200 else extra_json_str
                log.error(
                    f"Could not decode to UTF-8 column 'extra_json' with text '{truncated}...'. "
                    f"Dataset ID: {row[0]}, Name: '{row[1]}'. "
                    f"Error: {e}. This dataset's metadata will be skipped.",
                    exc_info=True,
                )
                # Continue with None - don't fail the entire load
                extra = None

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

    # Safely decode extra_json with error recovery
    extra = None
    extra_json_str = row[7]
    if extra_json_str:
        try:
            extra = json.loads(extra_json_str)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            import logging

            log = logging.getLogger(__name__)
            truncated = extra_json_str[:200] if len(extra_json_str) > 200 else extra_json_str
            log.error(
                f"Could not decode extra_json for dataset {dataset_id}: {truncated}...Error: {e}",
                exc_info=True,
            )
            extra = None

    return {
        "id": row[0],
        "name": row[1],
        "created_utc": row[2],
        "notes": row[3],
        "fps": row[4],
        "pixel_size_um": row[5],
        "t0_seconds": row[6],
        "extra": extra,
    }


# ---------------------------------------------------------------------------
# Bundling helpers


def pack_bundle(
    vaso_path: str | os.PathLike[str],
    vasopack_path: str | os.PathLike[str],
    *,
    embed_threshold_mb: int = 64,
) -> None:
    """Create a ``.vasopack`` bundle containing the project file."""

    del embed_threshold_mb  # Threshold unused in single-file format.

    project_path = Path(vaso_path)
    if not project_path.exists():
        raise FileNotFoundError(project_path)

    bundle_path = Path(vasopack_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_project = tmp_root / "project.vaso"
        shutil.copy2(project_path, temp_project)

        bundle_tmp = bundle_path.with_suffix(bundle_path.suffix + ".tmp")
        with zipfile.ZipFile(
            bundle_tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zf:
            zf.write(temp_project, "project.vaso")
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
    return final_path


def convert_legacy_project(
    path: str | os.PathLike[str],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> ProjectStore:
    """
    Convert a legacy project file in-place to the sqlite-v3 single-file format.
    """

    src_path = Path(path)
    if not src_path.exists():
        raise FileNotFoundError(src_path)

    tmp_path = src_path.with_suffix(src_path.suffix + ".v3tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    project_dir = src_path.parent

    with sqlite3.connect(src_path.as_posix()) as legacy_conn:
        legacy_conn.row_factory = sqlite3.Row
        legacy_version = _projects.get_user_version(legacy_conn)
        if legacy_version >= SCHEMA_VERSION:
            return open_project(src_path)

        legacy_meta = _projects.read_meta(legacy_conn)
        timezone = legacy_meta.get("timezone", "UTC")
        app_version = legacy_meta.get("app_version", "legacy")

        new_store = create_project(tmp_path, app_version=app_version, timezone=timezone)
        try:
            _copy_legacy_tables(legacy_conn, new_store.conn)
            _copy_legacy_assets(
                legacy_conn,
                new_store,
                project_dir=project_dir,
                chunk_size=chunk_size,
            )
            _write_converted_meta(new_store.conn, legacy_meta, legacy_version)
            new_store.conn.commit()
        finally:
            new_store.close()

    _rotate_backups(src_path)
    os.replace(tmp_path, src_path)
    return open_project(src_path)


def _copy_legacy_tables(src_conn: sqlite3.Connection, dst_conn: sqlite3.Connection) -> None:
    dataset_rows = src_conn.execute(
        """
        SELECT id, name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json
          FROM dataset
        ORDER BY id
        """
    ).fetchall()
    if dataset_rows:
        dst_conn.executemany(
            """
            INSERT INTO dataset(id, name, created_utc, notes, fps, pixel_size_um, t0_seconds, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(row) for row in dataset_rows],
        )

    with contextlib.suppress(sqlite3.OperationalError):
        trace_rows = src_conn.execute(
            """
            SELECT dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2
              FROM trace
            ORDER BY dataset_id, t_seconds
            """
        ).fetchall()
        if trace_rows:
            dst_conn.executemany(
                """
                INSERT INTO trace(dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in trace_rows],
            )

    with contextlib.suppress(sqlite3.OperationalError):
        event_rows = src_conn.execute(
            """
            SELECT id, dataset_id, t_seconds, label, frame, p_avg, p1, p2, temp, extra_json
              FROM event
            ORDER BY id
            """
        ).fetchall()
        if event_rows:
            dst_conn.executemany(
                """
                INSERT INTO event(
                    id, dataset_id, t_seconds, label, frame, p_avg, p1, p2, temp, extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in event_rows],
            )

    with contextlib.suppress(sqlite3.OperationalError):
        result_rows = src_conn.execute(
            """
            SELECT id, dataset_id, kind, version, created_utc, payload_json
              FROM result
            ORDER BY id
            """
        ).fetchall()
        if result_rows:
            dst_conn.executemany(
                """
                INSERT INTO result(id, dataset_id, kind, version, created_utc, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in result_rows],
            )

    with contextlib.suppress(sqlite3.OperationalError):
        thumbnail_rows = src_conn.execute("SELECT dataset_id, png FROM thumbnail").fetchall()
        if thumbnail_rows:
            dst_conn.executemany(
                "INSERT INTO thumbnail(dataset_id, png) VALUES (?, ?)",
                [tuple(row) for row in thumbnail_rows],
            )


def _copy_legacy_assets(
    src_conn: sqlite3.Connection,
    dst_store: ProjectStore,
    *,
    project_dir: Path,
    chunk_size: int,
) -> None:
    asset_rows = src_conn.execute(
        """
        SELECT id, dataset_id, role, storage, rel_path, mime
          FROM asset
        ORDER BY id
        """
    ).fetchall()

    for row in asset_rows:
        asset_id = int(row["id"])
        dataset_id = int(row["dataset_id"])
        role = row["role"]
        storage = (row["storage"] or "embedded").lower()
        rel_path = row["rel_path"]
        mime = row["mime"]

        note = rel_path if rel_path else None
        original_name = Path(rel_path).name if rel_path else None

        if storage == "embedded" or not rel_path:
            payload = _legacy_reassemble_blob(src_conn, asset_id)
        else:
            asset_path = _resolve_legacy_asset_path(project_dir, rel_path)
            if not asset_path.exists():
                raise FileNotFoundError(f"Linked asset not found: {rel_path}")
            original_name = original_name or asset_path.name
            payload = asset_path.read_bytes()

        add_or_update_asset(
            dst_store,
            dataset_id,
            role,
            payload,
            embed=True,
            mime=mime,
            chunk_size=chunk_size,
            note=note,
            original_name=original_name,
        )


def _write_converted_meta(
    conn: sqlite3.Connection, legacy_meta: dict[str, str], legacy_version: int
) -> None:
    now = _utc_now()
    meta = dict(legacy_meta)

    for key in (
        "format",
        "project_version",
        "schema_version",
        "modified_at",
        "modified_utc",
        "converted_at",
        "converted_from_version",
    ):
        meta.pop(key, None)

    created_at = meta.get("created_at") or meta.get("created_utc")

    meta_updates: dict[str, str] = {
        "format": "sqlite-v3",
        "project_version": str(SCHEMA_VERSION),
        "schema_version": str(SCHEMA_VERSION),
        "modified_at": now,
        "modified_utc": now,
        "converted_at": now,
        "converted_from_version": str(legacy_version),
    }
    if created_at:
        meta_updates["created_at"] = created_at
        meta_updates["created_utc"] = created_at

    meta.update(meta_updates)
    _projects.write_meta(conn, meta)


def _legacy_reassemble_blob(conn: sqlite3.Connection, asset_id: int) -> bytes:
    rows = conn.execute(
        "SELECT data FROM blob_chunk WHERE asset_id = ? ORDER BY seq ASC",
        (asset_id,),
    ).fetchall()
    if not rows:
        return b""
    return b"".join(row["data"] for row in rows if row["data"])


def _resolve_legacy_asset_path(project_dir: Path, rel_path: str) -> Path:
    candidate = Path(rel_path)
    if not candidate.is_absolute():
        candidate = project_dir / rel_path
    return candidate


def _rotate_backups(path: Path) -> None:
    bak1 = path.with_suffix(path.suffix + ".bak1")
    bak2 = path.with_suffix(path.suffix + ".bak2")
    if bak2.exists():
        bak2.unlink()
    if bak1.exists():
        os.replace(bak1, bak2)
    os.replace(path, bak1)


# ---------------------------------------------------------------------------
# Autosave helpers


def write_autosave(
    store: ProjectStore,
    autosave_path: str | os.PathLike[str] | None = None,
) -> Path:
    """Write an autosave snapshot for ``store``."""

    if store.path is None:
        raise ValueError("Project store has no associated path")

    autosave = (
        Path(autosave_path)
        if autosave_path
        else store.path.with_suffix(store.path.suffix + ".autosave")
    )
    autosave.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(suffix=".tmp", dir=autosave.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        _sqlite_backup_to_delete_mode(store.path, tmp_path)
        with open(tmp_path, "rb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, autosave)
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
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
# Figure recipes
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    import datetime

    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _ensure_figure_recipe_table(store: ProjectStore) -> None:
    """Ensure the figure_recipe table exists (for projects that haven't migrated to v5)."""
    try:
        # Check if table exists by querying it
        store.conn.execute("SELECT 1 FROM figure_recipe LIMIT 1")
    except sqlite3.OperationalError:
        # Table doesn't exist - create it
        log.warning("figure_recipe table missing - creating it now (project may need migration)")
        with transaction(store.conn):
            store.conn.executescript(
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
        store.mark_dirty()
        log.info("Created figure_recipe table successfully")


def add_figure_recipe(
    store: ProjectStore,
    dataset_id: int,
    name: str,
    spec_json: str,
    *,
    source: str = "current_view",
    trace_key: str | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    export_background: str = "white",
    recipe_id: str | None = None,
) -> str:
    """Insert a new figure recipe row."""
    _ensure_figure_recipe_table(store)
    rid = recipe_id or str(uuid.uuid4())
    now = _now_iso()
    with transaction(store.conn):
        store.conn.execute(
            """
            INSERT INTO figure_recipe (
                recipe_id, dataset_id, name, created_at, updated_at,
                spec_json, source, trace_key, x_min, x_max, y_min, y_max, export_background
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                dataset_id,
                name,
                now,
                now,
                spec_json,
                source,
                trace_key,
                x_min,
                x_max,
                y_min,
                y_max,
                export_background,
            ),
        )
    store.mark_dirty()
    return rid


def update_figure_recipe(
    store: ProjectStore,
    recipe_id: str,
    *,
    name: str | None = None,
    spec_json: str | None = None,
    source: str | None = None,
    trace_key: str | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    export_background: str | None = None,
) -> None:
    """Update an existing figure recipe row."""
    _ensure_figure_recipe_table(store)
    now = _now_iso()
    fields = ["updated_at = ?"]
    params: list[Any] = [now]
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if spec_json is not None:
        fields.append("spec_json = ?")
        params.append(spec_json)
    if source is not None:
        fields.append("source = ?")
        params.append(source)
    if trace_key is not None:
        fields.append("trace_key = ?")
        params.append(trace_key)
    if x_min is not None:
        fields.append("x_min = ?")
        params.append(x_min)
    if x_max is not None:
        fields.append("x_max = ?")
        params.append(x_max)
    if y_min is not None:
        fields.append("y_min = ?")
        params.append(y_min)
    if y_max is not None:
        fields.append("y_max = ?")
        params.append(y_max)
    if export_background is not None:
        fields.append("export_background = ?")
        params.append(export_background)
    if len(fields) == 1:
        return
    params.append(recipe_id)
    with transaction(store.conn):
        store.conn.execute(
            f"UPDATE figure_recipe SET {', '.join(fields)} WHERE recipe_id = ?",
            params,
        )
    store.mark_dirty()


def list_figure_recipes(store: ProjectStore, dataset_id: int) -> list[dict[str, Any]]:
    _ensure_figure_recipe_table(store)
    cur = store.conn.execute(
        """
        SELECT recipe_id, name, updated_at, trace_key, x_min, x_max, y_min, y_max, export_background
        FROM figure_recipe
        WHERE dataset_id = ?
        ORDER BY updated_at DESC
        """,
        (dataset_id,),
    )
    return [
        {
            "recipe_id": row[0],
            "name": row[1],
            "updated_at": row[2],
            "trace_key": row[3],
            "x_min": row[4],
            "x_max": row[5],
            "y_min": row[6],
            "y_max": row[7],
            "export_background": row[8],
        }
        for row in cur.fetchall()
    ]


def get_figure_recipe(store: ProjectStore, recipe_id: str) -> dict[str, Any] | None:
    _ensure_figure_recipe_table(store)
    cur = store.conn.execute(
        """
        SELECT recipe_id, dataset_id, name, created_at, updated_at, spec_json, source,
               trace_key, x_min, x_max, y_min, y_max, export_background
        FROM figure_recipe
        WHERE recipe_id = ?
        """,
        (recipe_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "recipe_id": row[0],
        "dataset_id": row[1],
        "name": row[2],
        "created_at": row[3],
        "updated_at": row[4],
        "spec_json": row[5],
        "source": row[6],
        "trace_key": row[7],
        "x_min": row[8],
        "x_max": row[9],
        "y_min": row[10],
        "y_max": row[11],
        "export_background": row[12],
    }


def delete_figure_recipe(store: ProjectStore, recipe_id: str) -> None:
    _ensure_figure_recipe_table(store)
    with transaction(store.conn):
        store.conn.execute("DELETE FROM figure_recipe WHERE recipe_id = ?", (recipe_id,))
    store.mark_dirty()


def rename_figure_recipe(store: ProjectStore, recipe_id: str, name: str) -> None:
    update_figure_recipe(store, recipe_id, name=name)


# ---------------------------------------------------------------------------
# Internal helpers


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _guess_mime(path: str | os.PathLike[str] | None) -> str | None:
    if not path:
        return None
    guess, _ = mimetypes.guess_type(str(path))
    return guess
