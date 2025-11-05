# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import tifffile

from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    autosave_path_for,
    events_dataframe_from_rows,
    load_project,
    normalize_event_table_rows,
    pack_project_bundle,
    restore_project_from_autosave,
    save_project,
    unpack_project_bundle,
    write_project_autosave,
)
from vasoanalyzer.services.types import (
    ProjectRepository,
)
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.storage.sqlite import events as _events
from vasoanalyzer.storage.sqlite import projects as _projects
from vasoanalyzer.storage.sqlite import traces as _traces
from vasoanalyzer.storage.sqlite.utils import transaction
from vasoanalyzer.tools.portable_export import export_single_file

LARGE_TIFF_MEMMAP_THRESHOLD = 8 * 1024**2  # 8 MiB

log = logging.getLogger(__name__)


def _load_tiff_stack(
    path: str, *, compressed: bool | None
) -> tuple[Any, Callable[[], None] | None]:
    """Return a TIFF stack together with an optional cleanup callback."""

    try:
        size = os.path.getsize(path)
    except OSError:
        size = None

    if not compressed and size is not None and size >= LARGE_TIFF_MEMMAP_THRESHOLD:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                logger_factory = getattr(tifffile, "logger", None)
                logger_obj = logger_factory() if callable(logger_factory) else None
                if logger_obj is not None:
                    previous_level = logger_obj.level
                    logger_obj.setLevel(max(logging.ERROR, previous_level))
                try:
                    with tifffile.TiffFile(path) as tif:
                        page_count = len(tif.pages)
                        if page_count == 0:
                            raise ValueError(f"TIFF file {path!r} contains no frames")
                        first_page = tif.pages[0]
                        frame_shape = first_page.shape
                finally:
                    if logger_obj is not None:
                        logger_obj.setLevel(previous_level)

            raw_stack = tifffile.memmap(path, page=None)

            if raw_stack.ndim == len(frame_shape):
                raw_stack = raw_stack.reshape((page_count, *frame_shape))

            view = raw_stack
            if page_count > 1:
                try:
                    if not np.any(raw_stack[-1]) and np.any(raw_stack[-2]):
                        view = raw_stack[:-1]
                        log.debug("Dropped trailing blank frame from %s", path)
                except (IndexError, TypeError, ValueError):
                    # Any issue checking the tail should not block loading.
                    view = raw_stack

            def _closer(memmap_obj=raw_stack) -> None:
                mm_handle = getattr(memmap_obj, "_mmap", None)
                close_handle = getattr(mm_handle, "close", None)
                if callable(close_handle):
                    close_handle()

            return view, _closer
        except (ValueError, TypeError, tifffile.TiffFileError, OSError) as exc:
            log.debug("Falling back to eager TIFF load for %s (%s)", path, exc)

    stack = tifffile.imread(path)
    return stack, None


def manifest_to_project(manifest: dict[str, Any], state: dict[str, Any], path: str) -> Project:
    """Convert ``manifest`` and ``state`` dictionaries into a :class:`Project`."""

    project_state = state.get("project_ui", state)
    sample_states = state.get("samples", {})

    experiments = []
    closers_map: dict[str, list[Callable[[], None]]] = manifest.pop("_resource_closers", {})

    for exp_id, meta in manifest.get("experiments", {}).items():
        trace_df = meta.pop("_trace_standardized", None)
        if trace_df is None:
            trace_df = meta.get("trace")

        events_df = meta.pop("_events_user_standardized", None)
        if events_df is None:
            events_df = meta.pop("_events_standardized", None)
        if events_df is None:
            events_df = meta.get("events_user")
        if events_df is None:
            events_df = meta.get("events")

        sample_state = sample_states.get(exp_id)
        events_from_state = None
        if isinstance(sample_state, dict):
            sample_state["event_table_data"] = normalize_event_table_rows(
                sample_state.get("event_table_data")
            )
            events_from_state = events_dataframe_from_rows(sample_state.get("event_table_data"))

        if events_from_state is not None:
            events_df = events_from_state

        stack = meta.pop("tiff_stack", None)

        sample = SampleN(
            name=exp_id,
            trace_data=trace_df,
            events_data=events_df,
            snapshots=stack,
            ui_state=sample_state,
        )
        experiments.append(Experiment(name=exp_id, samples=[sample]))

    project_name = os.path.splitext(os.path.basename(path))[0]
    project = Project(name=project_name, experiments=experiments, path=path, ui_state=project_state)

    tmp_manager = manifest.pop("_tempdir_manager", None)
    tmpdir_path = manifest.pop("_tempdir", None)
    if tmp_manager is not None:
        project.resources.register_tempdir(tmp_manager, tmpdir_path)

    for closers in closers_map.values():
        for closer in closers:
            project.register_resource(closer)

    return project


def open_project_file(path: str) -> Project:
    """Open ``path`` and return a fully populated :class:`Project`."""

    return load_project(path)


def save_project_file(
    project: Project, path: str | None = None, *, skip_optimize: bool = False
) -> None:
    """Save ``project`` to ``path``.

    Args:
        project: The project to save
        path: Optional path to save to (updates project.path if provided)
        skip_optimize: If True, skip expensive OPTIMIZE operation (useful during app close)
    """

    if path is not None:
        project.path = path
    if not project.path:
        raise ValueError("Project path is not set")

    save_project(project, project.path, skip_optimize=skip_optimize)


def autosave_project(project: Project, autosave_path: str | None = None) -> str | None:
    """Write an autosave snapshot for ``project``."""

    if project is None or not project.path:
        return None
    return cast(str | None, write_project_autosave(project, autosave_path))


def pending_autosave_path(project_path: str) -> str | None:
    """Return autosave path for ``project_path`` if it exists."""

    candidate = autosave_path_for(project_path)
    return candidate.as_posix() if os.path.exists(candidate) else None


def restore_autosave(project_path: str) -> Project:
    """Restore the autosave snapshot for ``project_path``."""

    autosave = autosave_path_for(project_path)
    if not os.path.exists(autosave):
        raise FileNotFoundError(autosave)
    return restore_project_from_autosave(autosave, project_path)


# ---------------------------------------------------------------------------
# Repository façade ---------------------------------------------------------


class SQLiteProjectRepository(ProjectRepository):
    """Typed façade over :mod:`sqlite_store` for service-level consumers."""

    def __init__(self, store: sqlite_store.ProjectStore):
        self._store = store

    # Context manager support
    def __enter__(self) -> SQLiteProjectRepository:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ProjectRepository interface
    @property
    def path(self) -> Path | None:
        return cast(Path, self._store.path)

    def mark_dirty(self) -> None:
        self._store.mark_dirty()

    def commit(self) -> None:
        self._store.commit()

    def close(self) -> None:
        self._store.close()

    # TraceProvider
    def get_trace(
        self,
        dataset_id: int,
        t0: float | None = None,
        t1: float | None = None,
    ) -> pd.DataFrame:
        return cast(pd.DataFrame, sqlite_store.get_trace(self._store, dataset_id, t0, t1))

    # EventProvider
    def get_events(
        self,
        dataset_id: int,
        t0: float | None = None,
        t1: float | None = None,
    ) -> pd.DataFrame:
        return cast(pd.DataFrame, sqlite_store.get_events(self._store, dataset_id, t0, t1))

    def read_meta(self) -> dict[str, Any]:
        return dict(_projects.read_meta(self._store.conn))

    # AssetProvider
    def list_assets(self, dataset_id: int) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], sqlite_store.list_assets(self._store, dataset_id))

    def get_asset_bytes(self, asset_id: int) -> bytes:
        return cast(bytes, sqlite_store.get_asset_bytes(self._store, asset_id))

    def add_or_update_asset(
        self,
        dataset_id: int,
        role: str,
        payload: Any,
        *,
        embed: bool,
        mime: str | None = None,
        chunk_size: int = 2 * 1024 * 1024,
        note: str | None = None,
        original_name: str | None = None,
    ) -> int:
        return cast(
            int,
            sqlite_store.add_or_update_asset(
                self._store,
                dataset_id,
                role=role,
                path_or_bytes=payload,
                embed=embed,
                mime=mime,
                chunk_size=chunk_size,
                note=note,
                original_name=original_name,
            ),
        )

    def add_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        with transaction(self._store.conn):
            return cast(int, _events.add_events(self._store.conn, rows))

    def update_event(self, event_id: int, values: Mapping[str, Any]) -> None:
        with transaction(self._store.conn):
            _events.update_event(self._store.conn, event_id, values)

    def delete_events(self, ids: Sequence[int]) -> int:
        with transaction(self._store.conn):
            return cast(int, _events.delete_events(self._store.conn, ids))

    def write_trace(self, trace_id: Any, data: Any) -> None:
        with transaction(self._store.conn):
            _traces.write_trace(self._store.conn, trace_id, data)

    def write_meta(self, values: Mapping[str, Any]) -> None:
        if not values:
            return
        _projects.write_meta(self._store.conn, values)
        self._store.mark_dirty()

    def add_dataset(
        self,
        name: str,
        trace_data: Any,
        events_data: Any | None,
        *,
        metadata: Mapping[str, Any] | None = None,
        tiff_path: str | None = None,
        embed_tiff: bool = False,
        chunk_size: int = 2 * 1024 * 1024,
        thumbnail_png: bytes | None = None,
    ) -> int:
        return cast(
            int,
            sqlite_store.add_dataset(
                self._store,
                name,
                trace_data,
                events_data,
                metadata=dict(metadata) if metadata is not None else None,
                tiff_path=tiff_path,
                embed_tiff=embed_tiff,
                chunk_size=chunk_size,
                thumbnail_png=thumbnail_png,
            ),
        )

    def update_dataset_meta(self, dataset_id: int, **fields: Any) -> None:
        sqlite_store.update_dataset_meta(self._store, dataset_id, **fields)

    def add_result(
        self, dataset_id: int, kind: str, version: str, payload: Mapping[str, Any]
    ) -> int:
        return cast(
            int,
            sqlite_store.add_result(
                self._store,
                dataset_id,
                kind,
                version,
                dict(payload),
            ),
        )

    def get_results(self, dataset_id: int, kind: str | None = None) -> Sequence[Mapping[str, Any]]:
        return cast(
            Sequence[Mapping[str, Any]],
            sqlite_store.get_results(self._store, dataset_id, kind),
        )

    def iter_datasets(self) -> Sequence[Mapping[str, Any]]:
        return list(sqlite_store.iter_datasets(self._store))

    def save(self, *, skip_optimize: bool = False) -> None:
        sqlite_store.save_project(self._store, skip_optimize=skip_optimize)

    @property
    def store(self) -> sqlite_store.ProjectStore:
        """Return the underlying :class:`ProjectStore`."""

        return self._store


def open_project_repository(path: str) -> SQLiteProjectRepository:
    """Open an existing SQLite project as a typed repository façade."""

    store = sqlite_store.open_project(path)
    return SQLiteProjectRepository(store)


def convert_project_repository(path: str) -> SQLiteProjectRepository:
    """Convert a legacy project in-place and return an open repository façade."""

    store = sqlite_store.convert_legacy_project(path)
    return SQLiteProjectRepository(store)


def export_project_bundle(
    project: Project, bundle_path: str, *, embed_threshold_mb: int = 64
) -> str:
    """Create a shareable bundle for ``project``."""

    if project is None:
        raise ValueError("Project is required")
    return cast(
        str,
        pack_project_bundle(project, bundle_path, embed_threshold_mb=embed_threshold_mb),
    )


def import_project_bundle(bundle_path: str, dest_dir: str | None = None) -> Project:
    """Unpack a bundle and return the loaded project."""

    return cast(Project, unpack_project_bundle(bundle_path, dest_dir))


def export_project_single_file(
    project: Project,
    destination: str | None = None,
    *,
    extract_tiffs_dir: str | None = None,
    ensure_saved: bool = True,
) -> str:
    """Export ``project`` as a DELETE-mode single-file .vaso copy."""

    if project is None:
        raise ValueError("Project is required")
    if not project.path:
        raise ValueError("Project path is not set; save the project first")

    if ensure_saved:
        save_project(project, project.path)

    return cast(
        str,
        export_single_file(
            project.path,
            out_path=destination,
            link_snapshot_tiffs=True,
            extract_tiffs_dir=extract_tiffs_dir,
        ),
    )


def pack_sqlite_bundle(path: str, bundle_path: str | Path, *, embed_threshold_mb: int = 64) -> str:
    sqlite_store.pack_bundle(path, bundle_path, embed_threshold_mb=embed_threshold_mb)
    return str(bundle_path)


def unpack_sqlite_bundle(bundle_path: str | Path, dest_dir: str | Path) -> str:
    return cast(str, sqlite_store.unpack_bundle(bundle_path, dest_dir))


def restore_sqlite_autosave(autosave_path: str | Path, dest_path: str | Path) -> None:
    sqlite_store.restore_autosave(autosave_path, dest_path)


def create_project_repository(
    path: str, *, app_version: str, timezone: str
) -> SQLiteProjectRepository:
    store = sqlite_store.create_project(path, app_version=app_version, timezone=timezone)
    return SQLiteProjectRepository(store)
