# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

from typing import Optional, Any, Callable, Dict, List, Tuple

import logging
import warnings

from pathlib import Path
from vasoanalyzer.services.types import ProjectRepository
from vasoanalyzer.core.project import (
    Project,
    Experiment,
    SampleN,
    save_project,
    load_project,
    pack_project_bundle,
    unpack_project_bundle,
    write_project_autosave,
    restore_project_from_autosave,
    autosave_path_for,
    events_dataframe_from_rows,
    normalize_event_table_rows,
)
from vasoanalyzer.tools.portable_export import export_single_file
from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.io.events import _standardize_headers
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.storage.sqlite import projects as _projects
from vasoanalyzer.storage.sqlite import events as _events
from vasoanalyzer.storage.sqlite import traces as _traces
from vasoanalyzer.storage.sqlite import assets as _assets
from vasoanalyzer.storage.sqlite.utils import transaction
import numpy as np
import os
import pandas as pd
import tifffile


LARGE_TIFF_MEMMAP_THRESHOLD = 8 * 1024 ** 2  # 8 MiB

log = logging.getLogger(__name__)


def _load_tiff_stack(path: str, *, compressed: bool | None) -> Tuple[Any, Optional[Callable[[], None]]]:
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
                except Exception:
                    # Any issue checking the tail should not block loading.
                    view = raw_stack

            def _closer(memmap_obj=raw_stack) -> None:
                mm_handle = getattr(memmap_obj, "_mmap", None)
                if hasattr(mm_handle, "close"):
                    mm_handle.close()

            return view, _closer
        except (ValueError, TypeError, tifffile.TiffFileError, OSError) as exc:
            log.debug("Falling back to eager TIFF load for %s (%s)", path, exc)

    stack = tifffile.imread(path)
    return stack, None


def manifest_to_project(
    manifest: Dict[str, Any], state: Dict[str, Any], path: str
) -> Project:
    """Convert ``manifest`` and ``state`` dictionaries into a :class:`Project`."""

    project_state = state.get("project_ui", state)
    sample_states = state.get("samples", {})

    experiments = []
    closers_map: Dict[str, List[Callable[[], None]]] = manifest.pop(
        "_resource_closers", {}
    )

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
            events_from_state = events_dataframe_from_rows(
                sample_state.get("event_table_data")
            )

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


def save_project_file(project: Project, path: Optional[str] = None) -> None:
    """Save ``project`` to ``path``."""

    if path is not None:
        project.path = path
    if not project.path:
        raise ValueError("Project path is not set")

    save_project(project, project.path)


def autosave_project(project: Project, autosave_path: Optional[str] = None) -> Optional[str]:
    """Write an autosave snapshot for ``project``."""

    if project is None or not project.path:
        return None
    return write_project_autosave(project, autosave_path)


def pending_autosave_path(project_path: str) -> Optional[str]:
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
    def __enter__(self) -> "SQLiteProjectRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ProjectRepository interface
    @property
    def path(self) -> Optional[Path]:
        return self._store.path

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
        t0: Optional[float] = None,
        t1: Optional[float] = None,
    ) -> pd.DataFrame:
        return sqlite_store.get_trace(self._store, dataset_id, t0, t1)

    # EventProvider
    def get_events(
        self,
        dataset_id: int,
        t0: Optional[float] = None,
        t1: Optional[float] = None,
    ) -> pd.DataFrame:
        return sqlite_store.get_events(self._store, dataset_id, t0, t1)

    def read_meta(self) -> Dict[str, Any]:
        return dict(_projects.read_meta(self._store.conn))

    # AssetProvider
    def list_assets(self, dataset_id: int) -> List[Dict[str, Any]]:
        return sqlite_store.list_assets(self._store, dataset_id)

    def get_asset_bytes(self, asset_id: int) -> bytes:
        return sqlite_store.get_asset_bytes(self._store, asset_id)

    def add_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        with transaction(self._store.conn):
            return _events.add_events(self._store.conn, rows)

    def update_event(self, event_id: int, values: Mapping[str, Any]) -> None:
        with transaction(self._store.conn):
            _events.update_event(self._store.conn, event_id, values)

    def delete_events(self, ids: Sequence[int]) -> int:
        with transaction(self._store.conn):
            return _events.delete_events(self._store.conn, ids)

    def write_trace(self, trace_id: str, data: Any) -> None:
        with transaction(self._store.conn):
            _traces.write_trace(self._store.conn, trace_id, data)

    @property
    def store(self) -> sqlite_store.ProjectStore:
        """Return the underlying :class:`ProjectStore`."""

        return self._store


def open_project_repository(path: str) -> SQLiteProjectRepository:
    """Open an existing SQLite project as a typed repository façade."""

    store = sqlite_store.open_project(path)
    return SQLiteProjectRepository(store)


def create_project_repository(
    path: str,
    *,
    app_version: str,
    timezone: str,
) -> SQLiteProjectRepository:
    """Create a new SQLite project and return the repository façade."""

    store = sqlite_store.create_project(path, app_version=app_version, timezone=timezone)
    return SQLiteProjectRepository(store)


def export_project_bundle(project: Project, bundle_path: str, *, embed_threshold_mb: int = 64) -> str:
    """Create a shareable bundle for ``project``."""

    if project is None:
        raise ValueError("Project is required")
    return pack_project_bundle(project, bundle_path, embed_threshold_mb=embed_threshold_mb)


def import_project_bundle(bundle_path: str, dest_dir: Optional[str] = None) -> Project:
    """Unpack a bundle and return the loaded project."""

    return unpack_project_bundle(bundle_path, dest_dir)


def export_project_single_file(
    project: Project,
    destination: Optional[str] = None,
    *,
    extract_tiffs_dir: Optional[str] = None,
    ensure_saved: bool = True,
) -> str:
    """Export ``project`` as a DELETE-mode single-file .vaso copy."""

    if project is None:
        raise ValueError("Project is required")
    if not project.path:
        raise ValueError("Project path is not set; save the project first")

    if ensure_saved:
        save_project(project, project.path)

    return export_single_file(
        project.path,
        out_path=destination,
        link_snapshot_tiffs=True,
        extract_tiffs_dir=extract_tiffs_dir,
    )
