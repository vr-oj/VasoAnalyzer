# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
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

    log.info(f"📂 Opening project: {path}")
    project = load_project(path)
    log.info(f"✓ Project loaded successfully: {Path(path).name}")
    return project


def _cleanup_project_sidecars(project_path: Path | str) -> None:
    """
    Best-effort cleanup of project sidecar artifacts.

    Removes:
    - <project>.vaso.autosave
    - project-local cache directory (<stem>.vaso.cache or .vaso_cache inside a folder project)
    """

    try:
        project_path = Path(project_path)
    except Exception:
        log.warning("cleanup_project_sidecars: invalid project_path %r", project_path)
        return

    # Remove autosave file
    try:
        autosave = autosave_path_for(project_path)
    except Exception:
        autosave = None
        log.exception("Failed to compute autosave path for %s", project_path)

    if autosave:
        autosave_path = Path(autosave)
        if autosave_path.exists():
            try:
                autosave_path.unlink()
                log.debug("Removed autosave snapshot: %s", autosave_path)
            except Exception:
                log.exception("Failed to remove autosave snapshot: %s", autosave_path)

    # Remove project-local cache directory (skip system-level caches)
    try:
        from vasoanalyzer.services.cache_service import cache_dir_for_project

        cache_dir = Path(cache_dir_for_project(project_path))
    except Exception:
        cache_dir = None
        log.exception("Failed to compute cache dir for project: %s", project_path)

    if cache_dir is not None and cache_dir.exists():
        project_dir = project_path.parent
        project_stem = project_path.stem
        is_sibling_cache = cache_dir.parent == project_dir and cache_dir.name.startswith(
            project_stem
        )
        is_inside_project_dir = cache_dir.parent == project_path

        if is_sibling_cache or is_inside_project_dir:
            try:
                shutil.rmtree(cache_dir)
                log.debug("Removed project cache directory: %s", cache_dir)
            except Exception:
                log.exception("Failed to remove project cache directory: %s", cache_dir)
        else:
            log.debug("Skipping non-local cache dir during cleanup: %s", cache_dir)


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

    _sync_events_from_ui_state(project)
    for experiment in project.experiments:
        for sample in experiment.samples:
            df = getattr(sample, "events_data", None)
            row_count = len(df.index) if isinstance(df, pd.DataFrame) else None
            first_label = (
                df.iloc[0]["Event"]
                if isinstance(df, pd.DataFrame) and not df.empty and "Event" in df.columns
                else None
            )
            log.info(
                "DEBUG save: sample '%s' final events_data rows=%s first_label=%r",
                sample.name,
                row_count,
                first_label,
            )

    path_obj = Path(project.path).expanduser()
    project.path = str(path_obj)
    was_new_file = not path_obj.exists()

    log.debug("Saving project to %s", path_obj)
    save_project(project, project.path, skip_optimize=skip_optimize)

    if was_new_file:
        format_hint = path_obj.suffix.lstrip(".") or "directory"
        log.info("Project: Created new project at %s (format=%s)", path_obj, format_hint)
    else:
        log.debug("Project saved successfully: %s", path_obj.name)

    _cleanup_project_sidecars(path_obj)


def is_valid_autosave_snapshot(path: str | Path) -> bool:
    """Return True when ``path`` looks like a readable SQLite autosave."""

    autosave = Path(path)
    try:
        if not autosave.exists():
            return False
        if autosave.stat().st_size < 1024:
            return False
    except OSError:
        return False

    try:
        conn = sqlite3.connect(f"file:{autosave.as_posix()}?mode=ro", uri=True)
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False
    return True


def quarantine_autosave_snapshot(path: str | Path) -> Path | None:
    """Rename or delete a corrupt autosave so it will not be offered again."""

    autosave = Path(path)
    if not autosave.exists():
        return None

    target = autosave.with_suffix(autosave.suffix + ".corrupt")
    counter = 1
    while target.exists():
        counter += 1
        target = autosave.with_suffix(autosave.suffix + f".corrupt{counter}")

    try:
        autosave.rename(target)
        log.warning("Autosave snapshot quarantined: %s → %s", autosave, target)
        return target
    except OSError:
        with contextlib.suppress(OSError):
            autosave.unlink()
        log.warning("Autosave snapshot %s removed after failed quarantine", autosave)
        return None


def _sync_events_from_ui_state(project: Project | None) -> None:
    """Copy per-sample event rows from UI state into ``events_data`` before persisting."""

    if project is None:
        return
    for experiment in project.experiments:
        for sample in experiment.samples:
            state = getattr(sample, "ui_state", None)
            if not isinstance(state, dict) or "event_table_data" not in state:
                continue
            rows = normalize_event_table_rows(state.get("event_table_data"))
            row_count = len(rows or [])
            if row_count:
                df = events_dataframe_from_rows(rows)
                sample.events_data = df
                first_label = rows[0][0] if rows and len(rows[0]) > 0 else None
            else:
                sample.events_data = None
                first_label = None
            log.info(
                "Project save: synced %d UI events into sample '%s' (first=%r)",
                row_count,
                sample.name,
                first_label,
            )


def autosave_project(project: Project, autosave_path: str | None = None) -> str | None:
    """Write an autosave snapshot for ``project``."""

    if project is None or not project.path:
        return None

    _sync_events_from_ui_state(project)
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
    try:
        return restore_project_from_autosave(autosave, project_path)
    except sqlite3.DatabaseError as exc:
        log.warning("Could not restore autosave '%s': %s", autosave, exc)
        quarantine_autosave_snapshot(autosave)
        raise


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

    # Figure recipes
    def add_figure_recipe(
        self,
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
        return sqlite_store.add_figure_recipe(
            self._store,
            dataset_id,
            name,
            spec_json,
            source=source,
            trace_key=trace_key,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            export_background=export_background,
            recipe_id=recipe_id,
        )

    def update_figure_recipe(
        self,
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
        sqlite_store.update_figure_recipe(
            self._store,
            recipe_id,
            name=name,
            spec_json=spec_json,
            source=source,
            trace_key=trace_key,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            export_background=export_background,
        )

    def list_figure_recipes(self, dataset_id: int) -> list[dict[str, Any]]:
        return sqlite_store.list_figure_recipes(self._store, dataset_id)

    def get_figure_recipe(self, recipe_id: str) -> dict[str, Any] | None:
        return sqlite_store.get_figure_recipe(self._store, recipe_id)

    def delete_figure_recipe(self, recipe_id: str) -> None:
        sqlite_store.delete_figure_recipe(self._store, recipe_id)

    def rename_figure_recipe(self, recipe_id: str, name: str) -> None:
        sqlite_store.rename_figure_recipe(self._store, recipe_id, name)

    def save(self, *, skip_optimize: bool = False) -> None:
        log.info(
            "SAVE: SQLiteProjectRepository.save entry path=%s skip_optimize=%s",
            getattr(self._store, "path", None),
            skip_optimize,
        )
        sqlite_store.save_project(self._store, skip_optimize=skip_optimize)
        log.info(
            "SAVE: SQLiteProjectRepository.save completed path=%s skip_optimize=%s",
            getattr(self._store, "path", None),
            skip_optimize,
        )

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
