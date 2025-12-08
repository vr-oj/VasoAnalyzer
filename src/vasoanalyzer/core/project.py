# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import logging
import os
import string
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from utils.config import APP_VERSION
from vasoanalyzer.app.flags import is_enabled
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.core.repo_factory import get_repo
from vasoanalyzer.services.types import ProjectRepository

__all__ = [
    "Project",
    "Experiment",
    "SampleN",
    "load_project",
    "save_project",
    "pack_project_bundle",
    "unpack_project_bundle",
    "write_project_autosave",
    "restore_project_from_autosave",
    "autosave_path_for",
    "open_project_ctx",
    "close_project_ctx",
    "open_project",
    "close_project",
    "convert_project",
    "ProjectUpgradeRequired",
    "Attachment",
    "export_sample",
    "events_dataframe_from_rows",
    "normalize_event_table_rows",
]


log = logging.getLogger(__name__)

SCHEMA_VERSION = 3  # v3: Full VasoTracker support (Time_s_exact, frame_number, tiff_page, etc.)
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


class ProjectUpgradeRequired(RuntimeError):
    """Raised when a legacy project must be converted to the sqlite-v3 format."""

    def __init__(self, path: str, version: int):
        self.path = path
        self.version = version
        message = (
            f"Project at {path} uses legacy schema version {version}; "
            "conversion to sqlite-v3 is required."
        )
        super().__init__(message)


def open_project_ctx(path: str, repo: ProjectRepository | None = None) -> ProjectContext:
    """
    Open ``path`` and return a :class:`ProjectContext`.

    When ``repo`` is provided it is assumed to be pre-configured; otherwise the
    default repository factory is used.
    """
    from vasoanalyzer.core.file_lock import ProjectFileLock

    path_obj = Path(path)
    log.info(
        "Opening project context path=%s (exists=%s)",
        path_obj,
        path_obj.exists(),
    )

    # Acquire file lock to prevent concurrent access
    file_lock = ProjectFileLock(path)
    log.info("Requesting project lock path=%s lock=%s", path_obj, file_lock.lock_path)
    try:
        file_lock.acquire(timeout=5)
        log.info("Project lock acquired path=%s lock=%s", path_obj, file_lock.lock_path)
    except RuntimeError as e:
        log.error(
            "Failed to acquire lock for %s (lock=%s): %s",
            path_obj,
            file_lock.lock_path,
            e,
        )
        raise ValueError(f"Cannot open project: {e}") from e

    try:
        if repo is not None:
            repository = repo
        else:
            from vasoanalyzer.storage.sqlite_store import LegacyProjectError

            try:
                repository = get_repo(path)
            except LegacyProjectError as exc:
                raise ProjectUpgradeRequired(exc.path.as_posix(), exc.version) from exc
        open_method = getattr(repository, "open", None)
        if repo is not None and callable(open_method):
            open_method(path)
        meta: dict[str, Any] = {}
        read_meta = getattr(repository, "read_meta", None)
        if callable(read_meta):
            try:
                meta = dict(read_meta())
            except Exception:
                meta = {}
        return ProjectContext(path=path, repo=repository, meta=meta, file_lock=file_lock)
    except Exception:
        # If opening fails, release the lock
        file_lock.release()
        raise


def close_project_ctx(ctx: ProjectContext) -> None:
    """Close a :class:`ProjectContext`."""

    ctx.close()


def open_project(path: str, *args, **kwargs) -> ProjectContext:
    """Backwards compatible project opener returning a context."""

    return open_project_ctx(path, *args, **kwargs)


def close_project(obj) -> None:
    """Backwards compatible close wrapper accepting ProjectContext."""

    if isinstance(obj, ProjectContext):
        close_project_ctx(obj)


def convert_project(path: str) -> ProjectContext:
    """Convert a legacy project to sqlite-v3 and return an open context."""

    from vasoanalyzer.services.project_service import convert_project_repository

    repo = convert_project_repository(path)
    meta: dict[str, Any] = {}
    read_meta = getattr(repo, "read_meta", None)
    if callable(read_meta):
        try:
            meta = dict(read_meta())
        except Exception:
            meta = {}
    return ProjectContext(path=path, repo=repo, meta=meta)


@dataclass
class Attachment:
    """Lightweight descriptor for rich assets stored inside a project."""

    name: str
    filename: str | None = None
    description: str | None = None
    media_type: str | None = None
    source_path: str | None = field(default=None, repr=False, compare=False)
    data_path: str | None = field(default=None, repr=False, compare=False)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "filename": self.filename,
            "description": self.description,
            "media_type": self.media_type,
        }

    @classmethod
    def from_metadata(cls, data: dict[str, Any]) -> Attachment:
        return cls(
            name=data.get("name", ""),
            filename=data.get("filename", ""),
            description=data.get("description"),
            media_type=data.get("media_type"),
        )


@dataclass
class SampleN:
    name: str
    # NOTE: These paths are DEPRECATED for database-backed projects (v1.5+)
    # All trace/event data is stored in SQLite (loaded via dataset_id)
    # These fields are kept only for: legacy projects, import metadata, and exports
    trace_path: str | None = None
    events_path: str | None = None
    trace_relative: str | None = None
    events_relative: str | None = None
    trace_hint: str | None = None
    events_hint: str | None = None
    trace_signature: str | None = None
    events_signature: str | None = None
    snapshot_path: str | None = None
    diameter_data: list[float] | None = None
    exported: bool = False
    column: str | None = None
    trace_data: pd.DataFrame | None = None
    trace_column_labels: dict[str, str] | None = None
    events_data: pd.DataFrame | None = None
    ui_state: dict | None = None
    snapshots: np.ndarray | None = None
    notes: str | None = None
    analysis_results: dict[str, Any] | None = None
    figure_configs: dict[str, Any] | None = None
    attachments: list[Attachment] = field(default_factory=list)
    dataset_id: int | None = None
    asset_roles: dict[str, int] = field(default_factory=dict)
    snapshot_role: str | None = None
    snapshot_tiff_role: str | None = None
    snapshot_format: str | None = None
    analysis_result_keys: list[str] | None = None
    edit_history: list[dict[str, Any]] | None = None
    import_metadata: dict[str, Any] | None = None
    """
    VasoTracker import provenance metadata:
    {
        "trace_original_filename": "20251202_Exp01.csv",
        "events_original_filename": "20251202_Exp01_table.csv",
        "tiff_original_filename": "20251202_Exp01_Result.tiff",
        "trace_original_directory": "/path/to/RawFiles",
        "import_timestamp": "2025-12-04T10:30:00Z",
        "canonical_time_source": "Time_s_exact",
        "schema_version": 3,
    }
    """
    # Cache validation fields - track which dataset_id the cached data belongs to
    _trace_cache_dataset_id: int | None = field(default=None, repr=False)
    _events_cache_dataset_id: int | None = field(default=None, repr=False)

    def copy(self) -> SampleN:
        """Return a deep copy of this sample."""
        attachments_copy = [
            Attachment(
                name=att.name,
                filename=att.filename,
                description=att.description,
                media_type=att.media_type,
                source_path=att.source_path,
                data_path=att.data_path,
            )
            for att in self.attachments
        ]

        return SampleN(
            name=self.name,
            trace_path=self.trace_path,
            events_path=self.events_path,
            trace_relative=self.trace_relative,
            events_relative=self.events_relative,
            trace_hint=self.trace_hint,
            events_hint=self.events_hint,
            trace_signature=self.trace_signature,
            events_signature=self.events_signature,
            snapshot_path=self.snapshot_path,
            diameter_data=list(self.diameter_data) if self.diameter_data is not None else None,
            exported=self.exported,
            column=self.column,
            trace_data=self.trace_data.copy() if self.trace_data is not None else None,
            trace_column_labels=dict(self.trace_column_labels)
            if isinstance(self.trace_column_labels, dict)
            else None,
            events_data=self.events_data.copy() if self.events_data is not None else None,
            ui_state=copy.deepcopy(self.ui_state) if self.ui_state is not None else None,
            snapshots=self.snapshots.copy() if isinstance(self.snapshots, np.ndarray) else None,
            notes=self.notes,
            analysis_results=copy.deepcopy(self.analysis_results)
            if isinstance(self.analysis_results, dict)
            else self.analysis_results,
            figure_configs=copy.deepcopy(self.figure_configs)
            if isinstance(self.figure_configs, dict)
            else self.figure_configs,
            attachments=attachments_copy,
            dataset_id=self.dataset_id,
            asset_roles=dict(self.asset_roles) if self.asset_roles else {},
            snapshot_role=self.snapshot_role,
            snapshot_tiff_role=self.snapshot_tiff_role,
            snapshot_format=self.snapshot_format,
            analysis_result_keys=(
                list(self.analysis_result_keys)
                if isinstance(self.analysis_result_keys, list)
                else self.analysis_result_keys
            ),
            edit_history=(list(self.edit_history) if isinstance(self.edit_history, list) else None),
        )


@dataclass
class Experiment:
    name: str
    excel_path: str | None = None
    next_column: str = "B"
    samples: list[SampleN] = field(default_factory=list)
    style: dict | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class Project:
    name: str
    experiments: list[Experiment] = field(default_factory=list)
    path: str | None = None
    ui_state: dict | None = None
    resources: ProjectResources = field(
        default_factory=lambda: ProjectResources(), repr=False, compare=False
    )
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    # Whether to embed snapshot video stacks into the project database
    embed_snapshots: bool = False
    # Whether to embed TIFF snapshots (WARNING: can significantly increase .vaso file size)
    # This is opt-in and requires explicit user confirmation
    embed_tiff_snapshots: bool = False

    # Internal: current open store handle (for persistent connection)
    _store: Any = field(default=None, repr=False, compare=False, init=False)

    # --------------------------------------------------
    def close(self) -> None:
        """Release temporary resources (e.g., extracted archives)."""

        if self.resources is not None:
            self.resources.cleanup()

    # --------------------------------------------------
    def register_resource(self, closer: Callable[[], None]) -> None:
        """Register a callable to be invoked during :meth:`close`."""

        if self.resources is not None and closer is not None:
            self.resources.add_closer(closer)

    # --------------------------------------------------
    def _attach_store(self, store: Any) -> None:
        """Attach a persistent store to this project for efficient data access."""
        # Close old store if exists
        if self._store is not None and self._store is not store:
            try:
                self._store.close()
            except Exception:
                log.debug("Error closing old project store during attach", exc_info=True)

        self._store = store

        # Register cleanup handler that will close whatever store is attached at close time
        # Only register once - it will reference self._store dynamically
        if not hasattr(self, "_store_cleanup_registered"):
            self.register_resource(lambda: self._store.close() if self._store else None)
            self._store_cleanup_registered = True

    # --------------------------------------------------
    def __enter__(self) -> Project:
        return self

    # --------------------------------------------------
    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --------------------------------------------------
    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # pragma: no cover - defensive cleanup
            log.debug("Project cleanup failed during __del__", exc_info=True)


@dataclass
class ProjectResources:
    """Container for temporary resources tied to a :class:`Project`."""

    tempdir_manager: tempfile.TemporaryDirectory[str] | None = None
    tempdir_path: str | None = None
    closers: list[Callable[[], None]] = field(default_factory=list)

    # --------------------------------------------------
    def register_tempdir(self, manager, path: str | None) -> None:
        self.tempdir_manager = manager
        self.tempdir_path = path

    # --------------------------------------------------
    def add_closer(self, closer: Callable[[], None]) -> None:
        self.closers.append(closer)

    # --------------------------------------------------
    def cleanup(self) -> None:
        for closer in reversed(self.closers):
            try:
                closer()
            except Exception:  # pragma: no cover - best effort cleanup
                log.debug("Error during project resource cleanup", exc_info=True)
        self.closers.clear()

        if self.tempdir_manager is not None:
            try:
                self.tempdir_manager.cleanup()
            except Exception:  # pragma: no cover - best effort cleanup
                log.debug("Temporary directory cleanup failed", exc_info=True)
            finally:
                self.tempdir_manager = None
                self.tempdir_path = None


def _safe_name(name: str) -> str:
    """Return ``name`` sanitized for filesystem use."""
    valid = f"-_.() {string.ascii_letters}{string.digits}"
    return "".join(c if c in valid else "_" for c in name)


def _hash_file(path: str) -> str:
    """Return SHA256 hex digest of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_file(z: zipfile.ZipFile, full: str, rel: str) -> None:
    """Add file at ``full`` to ``z`` as ``rel`` with deterministic metadata."""
    info = zipfile.ZipInfo(rel)
    info.date_time = FIXED_ZIP_TIME
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with open(full, "rb") as f:
        z.writestr(info, f.read())


def _safe_extractall(z: zipfile.ZipFile, path: str) -> None:
    """Extract ``z`` into ``path`` ensuring no member escapes ``path``."""
    base = os.path.abspath(path)
    for member in z.namelist():
        dest = os.path.abspath(os.path.join(base, member))
        if not dest.startswith(base + os.sep) and dest != base:
            raise ValueError(f"Unsafe path in archive: {member}")
    z.extractall(path)


def _serialize_analysis_results(results: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serialisable representation of ``results``."""

    serialised: dict[str, Any] = {}
    for name, value in results.items():
        if isinstance(value, pd.DataFrame):
            serialised[name] = {
                "__type__": "dataframe",
                "value": value.to_dict(orient="split"),
            }
        else:
            serialised[name] = value
    return serialised


def _deserialize_analysis_results(data: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct analysis results from a JSON payload."""

    restored: dict[str, Any] = {}
    for name, value in data.items():
        if isinstance(value, dict) and value.get("__type__") == "dataframe":
            payload = value.get("value", {})
            restored[name] = pd.DataFrame(
                data=payload.get("data", []),
                columns=payload.get("columns"),
                index=payload.get("index"),
            )
        else:
            restored[name] = value
    return restored


# JSON I/O --------------------------------------------------------------


def _normalise_path_value(value: str | os.PathLike[str] | Path | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value.as_posix()
    try:
        return os.fspath(value)
    except TypeError:
        return str(value)


def _path_signature(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_size}-{int(stat.st_mtime)}"


def _sample_link_payload(
    *,
    path_value: str | os.PathLike[str] | Path | None,
    relative_hint: str | os.PathLike[str] | Path | None,
    absolute_hint: str | os.PathLike[str] | Path | None,
    base_dir: Path | None,
    signature_hint: str | None = None,
) -> dict[str, str] | None:
    path_str = _normalise_path_value(path_value)
    relative_str = _normalise_path_value(relative_hint)
    absolute_str = _normalise_path_value(absolute_hint)
    payload: dict[str, str] = {}

    if relative_str:
        payload["relative"] = os.path.normpath(relative_str)
    elif base_dir is not None and path_str:
        try:
            payload["relative"] = os.path.normpath(os.path.relpath(path_str, os.fspath(base_dir)))
        except Exception:
            payload["relative"] = os.path.normpath(path_str)

    if absolute_str:
        payload["hint"] = absolute_str
    elif path_str:
        payload["hint"] = path_str

    signature = signature_hint
    candidate_paths: list[Path] = []
    if path_str:
        if base_dir is not None:
            candidate = _absolute_path(path_str, base_dir)
            if candidate is not None:
                candidate_paths.append(candidate)
        else:
            candidate_paths.append(Path(path_str).expanduser().resolve(strict=False))
    if "relative" in payload and base_dir is not None:
        relative_candidate = _absolute_path(payload["relative"], base_dir)
        if relative_candidate is not None:
            candidate_paths.append(relative_candidate)
    if "hint" in payload:
        with contextlib.suppress(Exception):
            candidate_paths.append(Path(payload["hint"]).expanduser().resolve(strict=False))

    if not signature:
        for candidate in candidate_paths:
            if candidate is None:
                continue
            sig = _path_signature(candidate)
            if sig:
                signature = sig
                break
    if signature:
        payload["sig"] = signature

    return payload if payload else None


def _resolve_linked_path(
    path_entry: str | None,
    link_meta: dict[str, Any] | None,
    base_dir: Path,
) -> str | None:
    candidates: list[Path] = []
    entry_str = _normalise_path_value(path_entry)
    if entry_str:
        candidate = _absolute_path(entry_str, base_dir)
        if candidate:
            candidates.append(candidate)
    if isinstance(link_meta, dict):
        rel = _normalise_path_value(link_meta.get("relative"))
        if rel:
            candidate = _absolute_path(rel, base_dir)
            if candidate:
                candidates.append(candidate)
        hint = _normalise_path_value(link_meta.get("hint"))
        if hint:
            try:
                candidates.append(Path(hint).expanduser().resolve(strict=False))
            except Exception:
                candidates.append(Path(hint))
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate.exists():
            return candidate.as_posix()
    first = next((c for c in candidates if c is not None), None)
    if isinstance(first, Path):
        return first.as_posix()
    return str(first) if first else entry_str


def _populate_link_metadata(
    sample: SampleN,
    prefix: str,
    path_value: str | None,
    link_meta: dict[str, Any] | None,
    base_dir: Path,
) -> None:
    path_attr = f"{prefix}_path"
    relative_attr = f"{prefix}_relative"
    hint_attr = f"{prefix}_hint"
    signature_attr = f"{prefix}_signature"

    if isinstance(link_meta, dict):
        if link_meta.get("relative") and not getattr(sample, relative_attr):
            setattr(sample, relative_attr, os.path.normpath(str(link_meta.get("relative"))))
        if link_meta.get("hint") and not getattr(sample, hint_attr):
            setattr(sample, hint_attr, str(link_meta.get("hint")))
        if link_meta.get("sig") and not getattr(sample, signature_attr):
            setattr(sample, signature_attr, str(link_meta.get("sig")))

    path_str = _normalise_path_value(path_value)
    if not path_str:
        return

    setattr(sample, path_attr, path_str)

    if not getattr(sample, hint_attr):
        setattr(sample, hint_attr, path_str)

    if not getattr(sample, relative_attr):
        try:
            rel = os.path.relpath(path_str, os.fspath(base_dir))
        except Exception:
            rel = Path(path_str).name
        setattr(sample, relative_attr, os.path.normpath(rel))

    if not getattr(sample, signature_attr):
        path_obj = Path(path_str).expanduser().resolve(strict=False)
        sig = _path_signature(path_obj)
        if sig:
            setattr(sample, signature_attr, sig)


def sample_to_dict(sample: SampleN, base_dir: str | None = None) -> dict:
    data = asdict(sample)
    data.pop("snapshots", None)
    data.pop("attachments", None)
    if isinstance(sample.trace_data, pd.DataFrame):
        data["trace_data"] = sample.trace_data.to_dict(orient="list")
        edit_log = sample.trace_data.attrs.get("edit_log")
        if edit_log is not None:
            data["trace_edit_log"] = edit_log
    if sample.trace_column_labels:
        data["trace_column_labels"] = dict(sample.trace_column_labels)
    if isinstance(sample.events_data, pd.DataFrame):
        data["events_data"] = sample.events_data.to_dict(orient="list")
    if isinstance(sample.analysis_results, dict):
        serialized = _serialize_analysis_results(sample.analysis_results)
        if serialized:
            data["analysis_results"] = serialized
        elif "analysis_results" in data:
            data.pop("analysis_results", None)
    elif data.get("analysis_results") is None:
        data.pop("analysis_results", None)
    if sample.figure_configs is None:
        data.pop("figure_configs", None)
    if sample.edit_history:
        data["edit_history"] = sample.edit_history
    if sample.notes is None:
        data.pop("notes", None)
    if sample.attachments:
        data["attachments"] = [att.to_metadata() for att in sample.attachments]
    if sample.snapshot_path is None:
        data.pop("snapshot_path", None)
    for key in (
        "trace_hint",
        "trace_relative",
        "trace_signature",
        "events_hint",
        "events_relative",
        "events_signature",
    ):
        if data.get(key) is None:
            data.pop(key, None)
    if base_dir:
        if sample.trace_path:
            data["trace_path"] = os.path.relpath(sample.trace_path, base_dir)
        if sample.trace_relative:
            data["trace_relative"] = os.path.normpath(sample.trace_relative)
        elif sample.trace_path:
            data["trace_relative"] = os.path.relpath(sample.trace_path, base_dir)
        if sample.events_path:
            data["events_path"] = os.path.relpath(sample.events_path, base_dir)
        if sample.events_relative:
            data["events_relative"] = os.path.normpath(sample.events_relative)
        elif sample.events_path:
            data["events_relative"] = os.path.relpath(sample.events_path, base_dir)
        if sample.snapshot_path:
            data["snapshot_path"] = os.path.relpath(sample.snapshot_path, base_dir)
    link = _sample_link_payload(
        path_value=sample.trace_path,
        relative_hint=sample.trace_relative,
        absolute_hint=sample.trace_hint,
        base_dir=Path(base_dir) if base_dir else None,
        signature_hint=sample.trace_signature,
    )
    if link:
        data["trace_link"] = link
    ev_link = _sample_link_payload(
        path_value=sample.events_path,
        relative_hint=sample.events_relative,
        absolute_hint=sample.events_hint,
        base_dir=Path(base_dir) if base_dir else None,
        signature_hint=sample.events_signature,
    )
    if ev_link:
        data["events_link"] = ev_link
    return data


def project_to_dict(project: Project, manifest: dict | None = None) -> dict:
    """Return ``project`` serialized to a dictionary."""
    base_dir = os.path.dirname(project.path) if project.path else None

    proj_dict: dict[str, Any] = {
        "name": project.name,
        "path": project.path,
        "experiments": [],
        "ui_state": project.ui_state,
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    if project.description is not None:
        proj_dict["description"] = project.description
    if project.tags:
        proj_dict["tags"] = list(project.tags)
    if project.created_at is not None:
        proj_dict["created_at"] = project.created_at
    if project.updated_at is not None:
        proj_dict["updated_at"] = project.updated_at
    if project.attachments:
        proj_dict["attachments"] = [att.to_metadata() for att in project.attachments]
    if manifest is not None:
        proj_dict["manifest"] = manifest

    for exp in project.experiments:
        exp_dict: dict[str, Any] = {
            "name": exp.name,
            "excel_path": os.path.relpath(exp.excel_path, base_dir)
            if base_dir and exp.excel_path
            else exp.excel_path,
            "next_column": exp.next_column,
            "samples": [sample_to_dict(s, base_dir) for s in exp.samples],
        }
        if exp.style is not None:
            exp_dict["style"] = exp.style
        if exp.notes is not None:
            exp_dict["notes"] = exp.notes
        if exp.tags:
            exp_dict["tags"] = list(exp.tags)
        experiments_list = cast(list[dict[str, Any]], proj_dict["experiments"])
        experiments_list.append(exp_dict)

    return proj_dict


def events_dataframe_from_rows(rows: list | None) -> pd.DataFrame | None:
    """Return a DataFrame representation of event rows stored in UI state."""

    if not rows:
        return None

    has_od = any(len(row) >= 5 for row in rows)
    has_frame = any(len(row) >= 4 for row in rows)

    records = []
    for row in rows:
        label = row[0] if len(row) >= 1 else ""
        time_val = row[1] if len(row) >= 2 else None
        id_val = row[2] if len(row) >= 3 else None
        record: dict[str, object] = {
            "Event": label,
            "Time (s)": time_val,
            "ID (µm)": id_val,
        }
        if has_od:
            record["OD (µm)"] = row[3] if len(row) >= 4 else None
            if has_frame:
                record["Frame"] = row[4] if len(row) >= 5 else None
        elif has_frame:
            record["Frame"] = row[3] if len(row) >= 4 else None
        records.append(record)

    columns = ["Event", "Time (s)", "ID (µm)"]
    if has_od:
        columns.append("OD (µm)")
    if has_frame:
        columns.append("Frame")

    df_state = pd.DataFrame(records, columns=columns)
    for col in ["Time (s)", "ID (µm)", "OD (µm)"]:
        if col in df_state.columns:
            df_state[col] = pd.to_numeric(df_state[col], errors="coerce")
    if "Frame" in df_state.columns:
        df_state["Frame"] = pd.to_numeric(df_state["Frame"], errors="coerce")

    return df_state


def normalize_event_table_rows(rows: list | None) -> list | None:
    if not rows:
        return rows
    return [tuple(row) if not isinstance(row, tuple) else row for row in rows]


def sample_from_dict(data: dict) -> SampleN:
    trace_data = data.get("trace_data")
    if isinstance(trace_data, dict):
        trace_data = pd.DataFrame(trace_data)

    if isinstance(trace_data, pd.DataFrame):
        edit_log = data.get("trace_edit_log")
        if isinstance(edit_log, list):
            trace_data.attrs["edit_log"] = edit_log
        else:
            trace_data.attrs.setdefault("edit_log", [])

    events_data = data.get("events_data")
    if isinstance(events_data, dict):
        events_data = pd.DataFrame(events_data)

    edit_history = data.get("edit_history")
    if not isinstance(edit_history, list):
        edit_history = None

    analysis_payload = data.get("analysis_results")
    analysis_results = None
    if isinstance(analysis_payload, dict):
        analysis_results = _deserialize_analysis_results(analysis_payload)
    elif analysis_payload is not None:
        analysis_results = analysis_payload

    trace_column_labels_raw = data.get("trace_column_labels")
    trace_column_labels = None
    if isinstance(trace_column_labels_raw, dict):
        trace_column_labels = {
            str(k): str(v)
            for k, v in trace_column_labels_raw.items()
            if isinstance(k, str) and isinstance(v, str)
        } or None
        trace_column_labels = _normalize_trace_column_labels(trace_column_labels)

    attachments_payload = data.get("attachments") or []
    attachments = []
    if isinstance(attachments_payload, list):
        for raw in attachments_payload:
            if isinstance(raw, dict):
                attachments.append(Attachment.from_metadata(raw))

    if isinstance(trace_data, pd.DataFrame) and edit_history is not None:
        trace_data.attrs["edit_log"] = edit_history

    return SampleN(
        name=data.get("name", ""),
        trace_path=data.get("trace_path"),
        events_path=data.get("events_path"),
        snapshot_path=data.get("snapshot_path"),
        diameter_data=data.get("diameter_data"),
        exported=data.get("exported", False),
        column=data.get("column"),
        trace_data=trace_data,
        trace_column_labels=trace_column_labels,
        events_data=events_data,
        ui_state=data.get("ui_state"),
        snapshots=None,
        notes=data.get("notes"),
        analysis_results=analysis_results,
        figure_configs=data.get("figure_configs"),
        attachments=attachments,
        edit_history=edit_history,
    )


def project_from_dict(data: dict) -> Project:
    experiments = []
    for exp in data.get("experiments", []):
        samples = [sample_from_dict(s) for s in exp.get("samples", [])]
        experiments.append(
            Experiment(
                name=exp.get("name", ""),
                excel_path=exp.get("excel_path"),
                next_column=exp.get("next_column", "B"),
                samples=samples,
                style=exp.get("style"),
                notes=exp.get("notes"),
                tags=list(exp.get("tags", [])) if isinstance(exp.get("tags"), list) else [],
            )
        )

    attachments_payload = data.get("attachments") or []
    project_attachments = []
    if isinstance(attachments_payload, list):
        for raw in attachments_payload:
            if isinstance(raw, dict):
                project_attachments.append(Attachment.from_metadata(raw))

    return Project(
        name=data.get("name", ""),
        experiments=experiments,
        path=data.get("path"),
        ui_state=data.get("ui_state"),
        description=data.get("description"),
        tags=list(data.get("tags", [])) if isinstance(data.get("tags"), list) else [],
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        attachments=project_attachments,
    )


def _save_project_legacy_zip(project: Project, path: str) -> None:
    """Save ``project`` to ``path`` as a zipped .vaso archive."""
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest: dict[str, str] = {}

        def _attachment_source(att: Attachment) -> str | None:
            for candidate in (att.source_path, att.data_path):
                if candidate and os.path.exists(candidate):
                    return candidate
            return None

        def _determine_filename(att: Attachment, fallback: str, used: set[str]) -> str:
            filename = (att.filename or "").strip()
            if filename:
                filename = _safe_name(filename)
            else:
                ext = ""
                for candidate in (att.source_path, att.data_path):
                    if candidate:
                        _base, ext = os.path.splitext(candidate)
                        break
                base = _safe_name(att.name or fallback) or fallback
                filename = f"{base}{ext}" if ext else base
                filename = _safe_name(filename)
            if not filename:
                filename = fallback
            root, ext = os.path.splitext(filename)
            candidate = filename
            counter = 2
            while candidate in used:
                candidate = f"{root}_{counter}{ext}"
                counter += 1
            used.add(candidate)
            att.filename = candidate
            return candidate

        def _embed_attachments(
            attachments: list[Attachment],
            dest_dir: str,
            fallback: str,
            used: set[str],
        ) -> None:
            for att in attachments:
                source = _attachment_source(att)
                if source is None:
                    log.warning(
                        "Skipping attachment %s; source unavailable", att.name or att.filename
                    )
                    continue
                filename = _determine_filename(att, fallback, used)
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                shutil.copy2(source, dest_path)
                manifest[os.path.relpath(dest_path, tmpdir)] = _hash_file(dest_path)

        for exp in project.experiments:
            exp_dir = os.path.join(tmpdir, _safe_name(exp.name))
            os.makedirs(exp_dir, exist_ok=True)
            for sample in exp.samples:
                s_dir = os.path.join(exp_dir, _safe_name(sample.name))
                os.makedirs(s_dir, exist_ok=True)

                t_path = None
                if sample.trace_data is not None:
                    t_path = os.path.join(s_dir, "trace.csv")
                    sample.trace_data.to_csv(t_path, index=False)
                elif sample.trace_path and os.path.exists(sample.trace_path):
                    t_path = os.path.join(s_dir, "trace.csv")
                    shutil.copy2(sample.trace_path, t_path)
                if t_path:
                    manifest[os.path.relpath(t_path, tmpdir)] = _hash_file(t_path)

                e_path_file = None
                events_df_to_save = sample.events_data

                if isinstance(sample.ui_state, dict):
                    ui_rows = normalize_event_table_rows(sample.ui_state.get("event_table_data"))
                    if ui_rows:
                        events_from_state = events_dataframe_from_rows(ui_rows)
                        if events_from_state is not None:
                            events_df_to_save = events_from_state
                            sample.events_data = events_df_to_save
                            sample.ui_state["event_table_data"] = ui_rows

                if events_df_to_save is not None:
                    e_path_file = os.path.join(s_dir, "events.csv")
                    events_df_to_save.to_csv(e_path_file, index=False)
                elif sample.events_path and os.path.exists(sample.events_path):
                    e_path_file = os.path.join(s_dir, "events.csv")
                    shutil.copy2(sample.events_path, e_path_file)
                if e_path_file:
                    manifest[os.path.relpath(e_path_file, tmpdir)] = _hash_file(e_path_file)

                if sample.snapshots is not None:
                    snap_path = os.path.join(s_dir, "snapshots.tiff")
                    import tifffile

                    tifffile.imwrite(snap_path, sample.snapshots, compression="lzw")
                    manifest[os.path.relpath(snap_path, tmpdir)] = _hash_file(snap_path)

                if sample.attachments:
                    attachments_dir = os.path.join(s_dir, "attachments")
                    _embed_attachments(
                        sample.attachments,
                        attachments_dir,
                        fallback="attachment",
                        used=set(),
                    )

        if project.attachments:
            project_attach_dir = os.path.join(tmpdir, "attachments")
            _embed_attachments(
                project.attachments,
                project_attach_dir,
                fallback="project_attachment",
                used=set(),
            )

        now_iso = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        if not project.created_at:
            project.created_at = now_iso
        project.updated_at = now_iso

        meta_path = os.path.join(tmpdir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(project_to_dict(project, manifest), f, indent=2)

        tmp_zip = f"{path}.tmp"
        with zipfile.ZipFile(tmp_zip, "w") as z:
            for root, _dirs, files in os.walk(tmpdir):
                for file in files:
                    full = os.path.join(root, file)
                    rel = os.path.relpath(full, tmpdir)
                    _add_file(z, full, rel)

        if os.path.exists(path):
            shutil.copy2(path, f"{path}.bak")
        os.replace(tmp_zip, path)


def _load_project_legacy_zip(path: str) -> Project:
    """Load a zipped ``.vaso`` project, falling back to ``.bak`` if needed."""
    import os
    import tempfile
    import zipfile

    def _read_archive(archive_path: str) -> Project:
        with zipfile.ZipFile(archive_path, "r") as z:
            tmp_manager = tempfile.TemporaryDirectory()
            tmpdir = tmp_manager.name
            try:
                _safe_extractall(z, tmpdir)
                meta_path = os.path.join(tmpdir, "metadata.json")
                if os.path.exists(meta_path):
                    with open(meta_path, encoding="utf-8") as f:
                        data = json.load(f)
                    manifest = data.get("manifest", {})
                    for rel, checksum in manifest.items():
                        file_path = os.path.join(tmpdir, rel)
                        if not os.path.exists(file_path) or _hash_file(file_path) != checksum:
                            raise ValueError(f"Checksum mismatch for {rel}")

                    proj = project_from_dict(data)
                    base_dir = os.path.dirname(archive_path)
                    for exp in proj.experiments:
                        exp_dir = os.path.join(tmpdir, _safe_name(exp.name))
                        for sample in exp.samples:
                            s_dir = os.path.join(exp_dir, _safe_name(sample.name))
                            t_path = os.path.join(s_dir, "trace.csv")
                            if os.path.exists(t_path) and sample.trace_data is None:
                                sample.trace_data = pd.read_csv(t_path)
                            e_path = os.path.join(s_dir, "events.csv")
                            if os.path.exists(e_path) and sample.events_data is None:
                                df_evt = pd.read_csv(e_path)
                                sample.events_data = df_evt

                            # Legacy projects may contain snapshot TIFFs. Load
                            # them if present but ignore any errors.
                            snap_path = os.path.join(s_dir, "snapshots.tiff")
                            if os.path.exists(snap_path) and sample.snapshots is None:
                                try:
                                    import tifffile

                                    sample.snapshots = tifffile.imread(snap_path)
                                except Exception:
                                    npy = snap_path + ".npy"
                                    if os.path.exists(npy):
                                        sample.snapshots = np.load(npy)

                            if sample.attachments:
                                attachments_dir = os.path.join(s_dir, "attachments")
                                for att in sample.attachments:
                                    if not att.filename:
                                        continue
                                    candidate = os.path.join(attachments_dir, att.filename)
                                    if os.path.exists(candidate):
                                        att.data_path = candidate

                            if sample.trace_path and not os.path.isabs(sample.trace_path):
                                sample.trace_path = os.path.normpath(
                                    os.path.join(base_dir, sample.trace_path)
                                )
                            if sample.events_path and not os.path.isabs(sample.events_path):
                                sample.events_path = os.path.normpath(
                                    os.path.join(base_dir, sample.events_path)
                                )
                            if (
                                isinstance(sample.ui_state, dict)
                                and "event_table_data" in sample.ui_state
                            ):
                                sample.ui_state["event_table_data"] = normalize_event_table_rows(
                                    sample.ui_state.get("event_table_data")
                                )
                                events_df = events_dataframe_from_rows(
                                    sample.ui_state.get("event_table_data")
                                )
                                if events_df is not None:
                                    sample.events_data = events_df

                    if proj.attachments:
                        project_attach_dir = os.path.join(tmpdir, "attachments")
                        for att in proj.attachments:
                            if not att.filename:
                                continue
                            candidate = os.path.join(project_attach_dir, att.filename)
                            if os.path.exists(candidate):
                                att.data_path = candidate

                    proj.resources.register_tempdir(tmp_manager, tmpdir)
                    return proj
                else:
                    manifest_file = os.path.join(tmpdir, "manifest.json")
                    state_file = os.path.join(tmpdir, "state.json")
                    if not (os.path.exists(manifest_file) and os.path.exists(state_file)):
                        raise FileNotFoundError(
                            "metadata.json not found and archive lacks manifest.json/state.json"
                        )

                    with open(manifest_file, encoding="utf-8") as f:
                        manifest = json.load(f)
                    with open(state_file, encoding="utf-8") as f:
                        state = json.load(f)

                    project_state = state.get("project_ui", state)
                    sample_states = state.get("samples", {})

                    experiments = []
                    for exp_id, meta in manifest.get("experiments", {}).items():
                        trace_df = pd.read_csv(os.path.join(tmpdir, meta["trace_file"]))
                        events_df = pd.read_csv(os.path.join(tmpdir, meta["events_file"]))

                        events_user_df = None
                        if "events_user_file" in meta:
                            path_evt_user = os.path.join(tmpdir, meta["events_user_file"])
                            if os.path.exists(path_evt_user):
                                events_user_df = pd.read_csv(path_evt_user)

                        snapshots = None
                        tiff = (
                            os.path.join(tmpdir, meta["tiff_file"])
                            if meta.get("tiff_file")
                            else None
                        )
                        if tiff and os.path.exists(tiff):
                            try:
                                import tifffile

                                snapshots = tifffile.imread(tiff)
                            except Exception:
                                pass

                        events_loaded = events_user_df if events_user_df is not None else events_df

                        sample = SampleN(
                            name=exp_id,
                            trace_data=trace_df,
                            events_data=events_loaded,
                            snapshots=snapshots,
                            ui_state=sample_states.get(exp_id),
                        )
                        experiments.append(Experiment(name=exp_id, samples=[sample]))

                    proj = Project(
                        name=os.path.splitext(os.path.basename(archive_path))[0],
                        experiments=experiments,
                        ui_state=project_state,
                    )
                    proj.resources.register_tempdir(tmp_manager, tmpdir)
                    return proj
            except Exception:
                tmp_manager.cleanup()
                raise

    try:
        proj = _read_archive(path)
    except Exception:
        bak = f"{path}.bak"
        if os.path.exists(bak):
            proj = _read_archive(bak)
            path = bak
        else:
            raise

    proj.path = path
    return proj


# SQLite-backed persistence -------------------------------------------------


def save_project(project: Project, path: str, *, skip_optimize: bool = False) -> None:
    """Persist ``project`` to ``path`` using SQLite format (bundle or legacy).

    Automatically handles both bundle (.vasopack) and legacy (.vaso) formats.
    New projects use cloud-safe bundle format by default.

    Args:
        project: The project to save
        path: Path to save to (bundle dir or legacy file)
        skip_optimize: If True, skip expensive OPTIMIZE operation (useful during app close)
    """
    from ..storage.project_storage import get_project_format

    log.info(
        "SAVE: save_project entry path=%s skip_optimize=%s project_path=%s",
        path,
        skip_optimize,
        getattr(project, "path", None),
    )

    # Check if path is a bundle
    path_obj = Path(path)
    fmt = get_project_format(path_obj) if path_obj.exists() else "unknown"

    # Use bundle format for bundles, containers, or new .vaso/.vasopack files
    if fmt in ("bundle-v1", "zip-bundle-v1") or (
        not path_obj.exists() and path.endswith((".vasopack", ".vaso"))
    ):
        log.info("SAVE: routing to _save_project_bundle fmt=%s path=%s", fmt, path)
        _save_project_bundle(project, path, skip_optimize=skip_optimize)
    else:
        log.info("SAVE: routing to _save_project_sqlite fmt=%s path=%s", fmt, path)
        _save_project_sqlite(project, path, skip_optimize=skip_optimize)

    log.info(
        "SAVE: save_project completed path=%s skip_optimize=%s",
        path,
        skip_optimize,
    )


def load_project(path: str) -> Project:
    """Open ``path`` returning a populated :class:`Project` instance.

    Automatically handles:
    - Container format (.vaso single-file containers)
    - Bundle format (.vasopack directories)
    - Legacy SQLite format (.vaso files)
    - Auto-migration from legacy to bundle
    - Recovery from corrupted databases
    """

    import time

    from ..storage.project_storage import get_project_format

    start_time = time.time()
    log.info(f"Loading project: {path}")

    path_obj = Path(path)

    # Detect format
    fmt = get_project_format(path_obj)

    # Handle bundle and container formats
    if fmt in ("bundle-v1", "zip-bundle-v1") or (path_obj.is_dir() and path.endswith(".vasopack")):
        project = _load_project_bundle(path)
        elapsed = time.time() - start_time
        log.info(f"Project loaded successfully in {elapsed:.2f}s: {path}")
        return project

    # Handle SQLite formats (with corruption recovery)
    if _is_sqlite_file(path):
        try:
            project = _load_project_sqlite(path)
            elapsed = time.time() - start_time
            log.info(f"Project loaded successfully in {elapsed:.2f}s: {path}")
            return project
        except Exception as e:
            import sqlite3

            # Check if this is a database corruption error
            error_msg = str(e).lower()
            corruption_keywords = [
                "malformed",
                "corrupt",
                "damaged",
                "disk image",
                "could not decode",
                "utf-8",
            ]
            is_corruption_error = isinstance(e, sqlite3.DatabaseError) or any(
                keyword in error_msg for keyword in corruption_keywords
            )
            if is_corruption_error:
                log.warning(f"Database corruption detected in {path}, attempting recovery...")

                # Attempt recovery
                if _attempt_database_recovery(path):
                    log.info("Database recovery successful, retrying load...")
                    try:
                        project = _load_project_sqlite(path)
                        elapsed = time.time() - start_time
                        log.info(
                            f"Project loaded successfully in {elapsed:.2f}s (after recovery): {path}"
                        )
                        return project
                    except Exception as retry_error:
                        raise RuntimeError(
                            f"Database was recovered but still cannot be loaded: {retry_error}"
                        ) from retry_error
                else:
                    raise RuntimeError(
                        f"Database is corrupted and recovery failed. "
                        f"A backup was created at {path}.backup. "
                        f"Original error: {e}"
                    ) from e
            else:
                # Re-raise non-corruption errors as-is
                raise

    return _load_project_legacy_zip(path)


# Bundle format save/load ------------------------------------------------


def _save_project_bundle(project: Project, path: str, *, skip_optimize: bool = False) -> None:
    """
    Save project to bundle format (.vasopack) or container format (.vaso).

    Creates a snapshot in the bundle's snapshot directory. Cloud-safe by design.

    OPTIMIZATION: Reuses existing store if available to avoid redundant unpack/pack cycles.
    """
    from ..storage.project_storage import (
        USE_BUNDLE_FORMAT_BY_DEFAULT,
        create_unified_project,
        open_unified_project,
    )

    dest = Path(path)

    # Determine format based on extension
    use_container_format = dest.suffix == ".vaso"

    # Ensure proper extension
    if not dest.suffix in (".vaso", ".vasopack"):
        # Default to container format (.vaso)
        dest = dest.with_suffix(".vaso")
        use_container_format = True

    format_name = "container" if use_container_format else "bundle"
    log.info(f"Saving project to {format_name} format: {dest}")

    # Update timestamps
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not project.created_at:
        project.created_at = now_iso
    project.updated_at = now_iso

    # OPTIMIZATION: Check if we can reuse the existing store
    store_needs_close = False
    store = None

    if project._store is not None:
        # Check if existing store is for the same path
        existing_path = getattr(
            project._store, "container_path", getattr(project._store, "path", None)
        )
        if existing_path and Path(existing_path).resolve() == dest.resolve():
            # Check if readonly
            is_readonly = getattr(project._store, "readonly", True)
            if is_readonly:
                # Need to close readonly and reopen as writable
                log.debug("Reopening readonly store as writable for save")
                project._store.close()
                project._store = None
                store = open_unified_project(dest, readonly=False, auto_migrate=False)
                store_needs_close = False  # Will attach to project
            else:
                # Can reuse existing writable store!
                log.debug("Reusing existing writable store (avoiding unpack/pack)")
                store = project._store
                store_needs_close = False  # Already attached to project

    # If we don't have a reusable store, open/create one
    if store is None:
        if not dest.exists():
            # Create new bundle/container
            log.info(f"Creating new {format_name}: {dest}")
            tz_name = _project_timezone()
            store = create_unified_project(
                dest,
                app_version=APP_VERSION,
                timezone=tz_name,
                use_bundle_format=True,
                use_container_format=use_container_format,
            )
            store_needs_close = False  # Will attach to project
        else:
            # Open existing bundle/container
            store = open_unified_project(dest, readonly=False, auto_migrate=False)
            store_needs_close = False  # Will attach to project

    try:
        # Get repository from store connection
        from vasoanalyzer.services.project_service import SQLiteProjectRepository
        from vasoanalyzer.storage.sqlite_store import ProjectStore

        # Wrap the UnifiedProjectStore as a ProjectStore for compatibility
        legacy_store = ProjectStore(
            path=store.path,
            conn=store.conn,
            dirty=store.dirty,
            is_cloud_path=getattr(store, "is_cloud_path", False),
            cloud_service=getattr(store, "cloud_service", None),
            journal_mode=getattr(store, "journal_mode", None),
        )

        # Create repository wrapper
        repo = SQLiteProjectRepository(legacy_store)

        # Populate repository from project
        base_dir = Path(project.path).resolve().parent if project.path else dest.parent
        _populate_store_from_project(project, repo, base_dir)

        # Save (creates snapshot for bundles/containers)
        if not skip_optimize:
            store.save(skip_snapshot=False)
        else:
            # During app close, skip snapshot creation for speed
            store.commit()

        log.info(f"{format_name.capitalize()} saved successfully: {dest}")

        # OPTIMIZATION: Attach store to project for reuse on next save
        # This ensures the same unpacked container is reused, avoiding redundant pack/unpack
        if project._store is not store:
            project._attach_store(store)

    except Exception:
        # On error, close the store if it's not already attached to the project
        if store is not None and project._store is not store:
            try:
                store.close()
            except Exception:
                log.debug("Error closing store after save failure", exc_info=True)
        raise

    project.path = dest.as_posix()


def _load_project_bundle(path: str) -> Project:
    """
    Load project from bundle format (.vasopack) or container format (.vaso).

    Automatically handles snapshot recovery if current snapshot is corrupted.
    """
    t_start = time.perf_counter()
    from vasoanalyzer.services.project_service import SQLiteProjectRepository
    from vasoanalyzer.storage.sqlite_store import ProjectStore

    from ..storage.project_storage import open_unified_project

    path_obj = Path(path)
    format_name = "container" if path_obj.suffix == ".vaso" else "bundle"
    log.info(f"Loading project from {format_name}: {path_obj}")

    # Open using unified project storage (handles both bundles and containers)
    # NOTE: Open with readonly=False to ensure staging database is created
    # This allows background jobs to read embedded data from the staging DB
    t_open_start = time.perf_counter()
    store = open_unified_project(path, readonly=False, auto_migrate=False)
    t_open = time.perf_counter() - t_open_start

    # Wrap the UnifiedProjectStore as a ProjectStore for compatibility
    legacy_store = ProjectStore(path=store.path, conn=store.conn, dirty=store.dirty)

    # Create repository wrapper
    repo = SQLiteProjectRepository(legacy_store)

    try:
        meta_rows = repo.read_meta()
        experiments_meta = _json_loads(meta_rows.get("experiments_meta"), default={})

        project_name = meta_rows.get("project_name") or path_obj.stem
        project_description = meta_rows.get("project_description")
        project_tags = _json_loads(meta_rows.get("project_tags"), default=[])
        project_ui = _json_loads(meta_rows.get("project_ui_state"))
        project_created = meta_rows.get("project_created_at")
        project_updated = meta_rows.get("project_updated_at")

        base_dir = path_obj.resolve().parent
        tmp_manager = tempfile.TemporaryDirectory()
        tmp_root = Path(tmp_manager.name)

        experiments_map: dict[str, Experiment] = {}
        project_attachments: list[Attachment] = []

        t_load_start = time.perf_counter()
        for record in repo.iter_datasets():
            dataset_id = record["id"]
            extra = record.get("extra") or {}
            if extra.get("kind") == "project_attachments":
                project_attachments.extend(
                    _load_project_attachments(repo, dataset_id, extra, tmp_root, base_dir)
                )
                continue

            sample, experiment_name = _dataset_to_sample(
                repo=repo,
                dataset=record,
                base_dir=base_dir,
                tmp_root=tmp_root,
            )

            exp_meta = experiments_meta.get(experiment_name, {})
            experiment = experiments_map.get(experiment_name)
            if experiment is None:
                excel_meta = exp_meta.get("excel_path")
                excel_path_value: str | None = None
                if isinstance(excel_meta, str):
                    absolute_excel = _absolute_path(excel_meta, base_dir)
                    excel_path_value = absolute_excel.as_posix() if absolute_excel else excel_meta

                experiment = Experiment(
                    name=experiment_name,
                    excel_path=excel_path_value,
                    next_column=exp_meta.get("next_column", "B"),
                    samples=[],
                    style=exp_meta.get("style"),
                    notes=exp_meta.get("notes"),
                    tags=list(exp_meta.get("tags", []))
                    if isinstance(exp_meta.get("tags"), list)
                    else [],
                )
                experiments_map[experiment_name] = experiment

            experiment.samples.append(sample)
        t_load = time.perf_counter() - t_load_start

        project = Project(
            name=project_name,
            experiments=list(experiments_map.values()),
            path=path,
            ui_state=project_ui,
            description=project_description,
            tags=project_tags if isinstance(project_tags, list) else [],
            created_at=project_created,
            updated_at=project_updated,
            attachments=project_attachments,
        )

        project.resources.register_tempdir(tmp_manager, tmp_root.as_posix())

        # CRITICAL FIX: Keep database connection open for project lifetime
        # Attach store to project so it can be reused during save operations
        # This ensures:
        # 1. Database stays open for lazy data loading (traces, events, snapshots)
        # 2. Save operations can reuse the same store (avoiding redundant unpack/pack)
        # 3. Store is properly cleaned up when project is closed
        project._attach_store(store)

        t_total = time.perf_counter() - t_start
        log.info(
            "Project load (bundle): open=%.3fs, samples=%.3fs, total=%.3fs, path=%s",
            t_open,
            t_load,
            t_total,
            path,
        )

        log.info(f"{format_name.capitalize()} loaded successfully: {path_obj}")
        return project

    except Exception as e:
        # On error, close store immediately and re-raise
        log.error(
            f"🔍 DIAGNOSTIC - Exception during project load, closing store: {e}", exc_info=True
        )
        store.close()
        raise


def _save_project_sqlite(project: Project, path: str, *, skip_optimize: bool = False) -> None:
    """Serialize ``project`` into a fresh SQLite database."""
    import time

    start_time = time.time()
    log.info(f"Saving project to: {path}")
    log.info(
        "SAVE: _save_project_sqlite entry path=%s skip_optimize=%s project_name=%s",
        path,
        skip_optimize,
        getattr(project, "name", None),
    )

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # BLOCK saves to cloud storage (data safety)
    is_cloud, cloud_service = _is_cloud_storage_path(str(dest))
    if is_cloud:
        error_msg = (
            f"Cannot save to {cloud_service}: SQLite databases are INCOMPATIBLE with cloud sync.\n\n"
            f"Why: Cloud sync services can interrupt database writes mid-transaction, causing guaranteed corruption.\n\n"
            f"Solution: Save to a local folder:\n"
            f"  • Windows: C:\\Users\\YourName\\Documents\\VasoAnalyzer\\\n"
            f"  • macOS: /Users/YourName/Documents/VasoAnalyzer/\n"
            f"  • Linux: /home/yourname/Documents/VasoAnalyzer/\n\n"
            f"You can export .vasopack bundles to cloud storage for backup/sharing."
        )
        log.error(f"BLOCKED save to cloud storage: {dest} ({cloud_service})")
        raise ValueError(error_msg)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not project.created_at:
        project.created_at = now_iso
    project.updated_at = now_iso

    if dest.exists():
        backup = dest.with_suffix(dest.suffix + ".bak")
        try:
            import shutil

            shutil.copy2(dest, backup)
        except Exception:
            log.debug("Failed to create backup for %s", dest, exc_info=True)

    tz_name = _project_timezone()
    base_dir = Path(project.path).resolve().parent if project.path else dest.parent
    _write_sqlite_project(
        project, dest, timezone_name=tz_name, base_dir=base_dir, skip_optimize=skip_optimize
    )

    project.path = dest.as_posix()

    elapsed = time.time() - start_time
    log.info(
        f"Project saved successfully in {elapsed:.2f}s (optimized={not skip_optimize}): {path}"
    )
    log.info(
        "SAVE: _save_project_sqlite completed path=%s duration=%.2fs optimized=%s",
        path,
        elapsed,
        not skip_optimize,
    )


def _write_sqlite_project(
    project: Project,
    dest: Path,
    *,
    timezone_name: str,
    base_dir: Path,
    skip_optimize: bool = False,
) -> None:
    """Serialise ``project`` into ``dest`` without mutating the caller."""

    dest.parent.mkdir(parents=True, exist_ok=True)

    from vasoanalyzer.services.project_service import create_project_repository

    t_start = time.perf_counter()
    log.info(
        "SAVE: _write_sqlite_project start dest=%s timezone=%s base_dir=%s skip_optimize=%s",
        dest,
        timezone_name,
        base_dir,
        skip_optimize,
    )

    with tempfile.TemporaryDirectory(dir=dest.parent) as tmpdir:
        tmp_path = Path(tmpdir) / dest.name
        repo = create_project_repository(
            tmp_path.as_posix(),
            app_version=APP_VERSION,
            timezone=timezone_name,
        )
        try:
            _populate_store_from_project(project, repo, base_dir)
            log.info("SAVE: repo.save start path=%s", tmp_path)
            repo.save(skip_optimize=skip_optimize)
            log.info("SAVE: repo.save finished path=%s", tmp_path)
        finally:
            repo.close()

        os.replace(tmp_path, dest)

    if is_enabled("pkg_save", default=False):
        try:
            from vasoanalyzer.pkg.exporter import export_project_to_package

            package_path = dest.parent / f"{dest.stem}.pkg.vaso"
            export_project_to_package(
                project,
                package_path,
                base_dir=base_dir,
                timezone=timezone_name,
            )
        except Exception:  # pragma: no cover - best effort sidecar export
            log.debug("Failed to export pkg.vaso sidecar", exc_info=True)

    log.info(
        "SAVE: _write_sqlite_project finished dest=%s duration=%.2fs skip_optimize=%s",
        dest,
        time.perf_counter() - t_start,
        skip_optimize,
    )


def _populate_store_from_project(project: Project, repo: ProjectRepository, base_dir: Path) -> None:
    """Populate ``store`` with the contents of ``project``."""

    t_start = time.perf_counter()
    base_dir = base_dir.resolve()
    embed_snapshots = getattr(project, "embed_snapshots", False)
    embed_tiff_snapshots = getattr(project, "embed_tiff_snapshots", False)

    # DEBUG: _populate_store_from_project instrumentation start
    project_name = getattr(project, "name", None) or getattr(project, "path", None)
    total_samples = (
        sum(len(exp.samples) for exp in project.experiments) if project.experiments else 0
    )
    log.info(
        "SAVE: _populate_store_from_project start project=%s samples=%d base_dir=%s",
        project_name,
        total_samples,
        base_dir,
    )
    datasets_before = None
    try:
        store_obj = getattr(repo, "store", None)
        conn = getattr(store_obj, "conn", None) if store_obj is not None else None
        if conn is not None:
            cur = conn.execute("SELECT COUNT(*) FROM dataset")
            row = cur.fetchone()
            datasets_before = row[0] if row else None
    except Exception:
        datasets_before = None
    log.debug(
        "_populate_store_from_project: start project=%r total_samples=%d datasets_before=%r",
        project_name,
        total_samples,
        datasets_before,
    )
    log.debug(
        "_populate_store_from_project: source_repo initial=%r",
        None,
    )
    # DEBUG: _populate_store_from_project instrumentation end

    # CRITICAL: Clear all existing datasets to avoid duplication
    # When saving, we want to REPLACE the database contents, not append to them
    try:
        # Get the store's connection and clear all datasets
        if hasattr(repo, "store") and hasattr(repo.store, "conn"):
            conn = repo.store.conn
            # DEBUG: _populate_store_from_project dataset wipe instrumentation start
            log.debug(
                "_populate_store_from_project: about to clear all dataset rows (datasets_before=%r)",
                datasets_before,
            )
            # DEBUG: _populate_store_from_project dataset wipe instrumentation end
            # Delete all datasets (this will cascade to related tables via foreign keys)
            conn.execute("DELETE FROM dataset")
            conn.commit()
            log.debug("Cleared existing datasets before repopulating")
    except Exception as e:
        log.warning(f"Failed to clear datasets before save: {e}")

    meta_entries: list[tuple[str, str]] = []

    meta_entries.append(("project_name", project.name or ""))
    if project.description:
        meta_entries.append(("project_description", project.description))
    if project.created_at:
        meta_entries.append(("project_created_at", project.created_at))
    if project.updated_at:
        meta_entries.append(("project_updated_at", project.updated_at))
    if project.tags:
        meta_entries.append(("project_tags", _json_dumps(project.tags)))
    if project.ui_state is not None:
        meta_entries.append(
            ("project_ui_state", _json_dumps(_normalise_json_data(project.ui_state)))
        )
    if project.path:
        meta_entries.append(("project_path", project.path))

    experiments_payload: dict[str, dict[str, Any]] = {}
    for exp in project.experiments:
        experiments_payload[exp.name] = {
            "excel_path": _relativize_path(exp.excel_path, base_dir),
            "next_column": exp.next_column,
            "style": _normalise_json_data(exp.style),
            "notes": exp.notes,
            "tags": list(exp.tags),
        }
    meta_entries.append(("experiments_meta", _json_dumps(experiments_payload)))

    repo.write_meta(dict(meta_entries))

    source_ctx: ProjectContext | None = None
    source_repo: ProjectRepository | None = None
    if project.path:
        try:
            candidate = Path(project.path).expanduser().resolve(strict=False)
        except Exception:
            candidate = Path(project.path)
        if candidate.exists():
            try:
                source_ctx = open_project_ctx(candidate.as_posix())
                source_repo = source_ctx.repo
            except Exception:
                source_ctx = None
                source_repo = None

    try:
        for _exp_index, exp in enumerate(project.experiments):
            for sample_index, sample in enumerate(exp.samples):
                # DEBUG: _populate_store_from_project per-sample instrumentation start
                log.debug(
                    "_populate_store_from_project: writing sample name=%r experiment=%r dataset_id_before=%r",
                    getattr(sample, "name", None),
                    getattr(exp, "name", None),
                    getattr(sample, "dataset_id", None),
                )
                # DEBUG: _populate_store_from_project per-sample instrumentation end
                _save_sample_to_store(
                    repo=repo,
                    base_dir=base_dir,
                    experiment=exp,
                    sample=sample,
                    sample_index=sample_index,
                    source_repo=source_repo,
                    embed_snapshots=embed_snapshots,
                    embed_tiff_snapshots=embed_tiff_snapshots,
                )

        if project.attachments:
            _store_project_attachments(repo, project.attachments, base_dir)
    finally:
        if source_ctx is not None:
            close_project_ctx(source_ctx)
        duration = time.perf_counter() - t_start
        sample_count = sum(len(exp.samples) for exp in project.experiments)
        datasets_after = None
        try:
            store_obj = getattr(repo, "store", None)
            conn = getattr(store_obj, "conn", None) if store_obj is not None else None
            if conn is not None:
                cur = conn.execute("SELECT COUNT(*) FROM dataset")
                row = cur.fetchone()
                datasets_after = row[0] if row else None
        except Exception:
            datasets_after = None
        mapping_summary: list[tuple[str | None, str | None, int | None]] = []
        for exp in project.experiments:
            for sample in exp.samples:
                mapping_summary.append(
                    (
                        getattr(exp, "name", None),
                        getattr(sample, "name", None),
                        getattr(sample, "dataset_id", None),
                    )
                )
        # DEBUG: _populate_store_from_project final summary instrumentation start
        log.debug(
            "_populate_store_from_project: done project=%r datasets_after=%r sample_dataset_map=%r",
            project_name,
            datasets_after,
            mapping_summary,
        )
        log.info(
            "SAVE: _populate_store_from_project finished project=%s samples=%d datasets_before=%s datasets_after=%s duration=%.2fs",
            project_name,
            sample_count,
            datasets_before,
            datasets_after,
            duration,
        )
        # DEBUG: _populate_store_from_project final summary instrumentation end
        log.info(
            "Save: _populate_store_from_project path=%s samples=%d time=%.3fs",
            getattr(project, "path", None),
            sample_count,
            duration,
        )


def _save_sample_to_store(
    repo: ProjectRepository,
    base_dir: Path,
    experiment: Experiment,
    sample: SampleN,
    sample_index: int,
    source_repo: ProjectRepository | None = None,
    embed_snapshots: bool = False,
    embed_tiff_snapshots: bool = False,
) -> None:
    """Serialize an individual ``sample`` into ``store``."""

    # DEBUG: _save_sample_to_store entry instrumentation start
    existing_dataset_id = getattr(sample, "dataset_id", None)
    log.debug(
        "_save_sample_to_store: entry sample=%r experiment=%r dataset_id_before=%r source_repo=%r",
        getattr(sample, "name", None),
        getattr(experiment, "name", None),
        existing_dataset_id,
        type(source_repo).__name__ if source_repo is not None else None,
    )
    # DEBUG: _save_sample_to_store entry instrumentation end

    t_start = time.perf_counter()
    trace_df = _resolve_trace_dataframe(sample, base_dir, source_repo)
    events_df = _resolve_events_dataframe(sample, base_dir, source_repo)

    # DEBUG: Log events DataFrame info
    if events_df is not None:
        log.info(f"💾 Saving {len(events_df)} events for sample '{sample.name}'")
        log.debug(f"   Events columns: {list(events_df.columns)}")
    else:
        log.warning(f"⚠️  No events DataFrame for sample '{sample.name}'")

    extra = _build_sample_extra(experiment, sample, base_dir, trace_df=trace_df)
    metadata = {
        "notes": sample.notes,
        "extra_json": extra,
    }

    # DEBUG: _save_sample_to_store add_dataset instrumentation start
    log.debug(
        "_save_sample_to_store: about to add dataset for sample=%r dataset_id_before=%r",
        getattr(sample, "name", None),
        existing_dataset_id,
    )
    # DEBUG: _save_sample_to_store add_dataset instrumentation end

    dataset_id = repo.add_dataset(
        sample.name or f"Sample {sample_index + 1}",
        trace_df,
        events_df,
        metadata=metadata,
    )
    is_new = existing_dataset_id is None or existing_dataset_id != dataset_id
    # DEBUG: _save_sample_to_store post-add_dataset instrumentation start
    log.debug(
        "_save_sample_to_store: sample=%r dataset_id_assigned=%r is_new=%r",
        getattr(sample, "name", None),
        dataset_id,
        is_new,
    )
    # DEBUG: _save_sample_to_store post-add_dataset instrumentation end
    sample.dataset_id = dataset_id

    attachments_payload = _persist_sample_attachments(repo, dataset_id, sample, base_dir)
    snapshot_info = _persist_sample_snapshots(
        repo,
        dataset_id,
        sample,
        base_dir,
        source_repo=source_repo,
        embed_snapshots=embed_snapshots,
        embed_tiff_snapshots=embed_tiff_snapshots,
    )
    analysis_keys = _persist_sample_results(repo, dataset_id, sample)

    if attachments_payload:
        extra["attachments"] = attachments_payload
    if snapshot_info:
        extra.update(snapshot_info)
    sample.analysis_result_keys = list(analysis_keys)
    if analysis_keys:
        extra["analysis_result_keys"] = analysis_keys
    else:
        extra.pop("analysis_result_keys", None)

    assets = repo.list_assets(dataset_id)
    sample.asset_roles = {asset["role"]: asset["id"] for asset in assets if asset.get("role")}

    repo.update_dataset_meta(dataset_id, extra_json=extra)
    duration = time.perf_counter() - t_start
    # DEBUG: _save_sample_to_store final instrumentation start
    try:
        elapsed = duration
    except Exception:
        elapsed = None
    log.debug(
        "_save_sample_to_store: exit sample=%r final_dataset_id=%r elapsed=%r",
        getattr(sample, "name", None),
        getattr(sample, "dataset_id", None),
        elapsed,
    )
    # DEBUG: _save_sample_to_store final instrumentation end
    log.info(
        "Save: sample '%s' (index=%s) dataset_id=%s time=%.3fs",
        getattr(sample, "name", None),
        sample_index,
        dataset_id,
        duration,
    )


def _resolve_trace_dataframe(
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
) -> pd.DataFrame:
    # DEBUG: _resolve_trace_dataframe entry instrumentation start
    dataset_id = getattr(sample, "dataset_id", None)
    sample_name = getattr(sample, "name", None)
    source_repo_type = type(source_repo).__name__ if source_repo is not None else None
    log.debug(
        "_resolve_trace_dataframe: start sample=%r dataset_id=%r source_repo=%r",
        sample_name,
        dataset_id,
        source_repo_type,
    )
    # DEBUG: _resolve_trace_dataframe entry instrumentation end
    if isinstance(sample.trace_data, pd.DataFrame):
        df = sample.trace_data
        # DEBUG: _resolve_trace_dataframe in-memory path instrumentation start
        try:
            shape = df.shape
            is_empty = df.empty
        except Exception:
            shape = None
            is_empty = None
        log.debug(
            "_resolve_trace_dataframe: using in-memory trace_data sample=%r dataset_id=%r df_shape=%r empty=%r",
            sample_name,
            dataset_id,
            shape,
            is_empty,
        )
        # DEBUG: _resolve_trace_dataframe in-memory path instrumentation end
        return df
    if sample.trace_path:
        path = _absolute_path(sample.trace_path, base_dir)
        if path and path.exists():
            try:
                # DEBUG: _resolve_trace_dataframe file path instrumentation start
                log.debug(
                    "_resolve_trace_dataframe: attempting file load for sample=%r dataset_id=%r path=%r exists=%r",
                    sample_name,
                    dataset_id,
                    str(path),
                    path.exists(),
                )
                # DEBUG: _resolve_trace_dataframe file path instrumentation end
                df = pd.read_csv(path)
                # DEBUG: _resolve_trace_dataframe final instrumentation start
                try:
                    shape = df.shape
                    is_empty = df.empty
                except Exception:
                    shape = None
                    is_empty = None
                log.debug(
                    "_resolve_trace_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
                    sample_name,
                    dataset_id,
                    shape,
                    is_empty,
                )
                # DEBUG: _resolve_trace_dataframe final instrumentation end
                return df
            except Exception:
                log.debug("Failed to reload trace CSV from %s", path, exc_info=True)
    if source_repo is not None and sample.dataset_id is not None:
        get_trace = getattr(source_repo, "get_trace", None)
        if callable(get_trace):
            try:
                # DEBUG: _resolve_trace_dataframe repo path instrumentation start
                log.debug(
                    "_resolve_trace_dataframe: using source_repo=%r for dataset_id=%r",
                    source_repo_type,
                    dataset_id,
                )
                # DEBUG: _resolve_trace_dataframe repo path instrumentation end
                df = cast(pd.DataFrame, get_trace(sample.dataset_id))
                # DEBUG: _resolve_trace_dataframe final instrumentation start
                try:
                    shape = df.shape
                    is_empty = df.empty
                except Exception:
                    shape = None
                    is_empty = None
                log.debug(
                    "_resolve_trace_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
                    sample_name,
                    dataset_id,
                    shape,
                    is_empty,
                )
                # DEBUG: _resolve_trace_dataframe final instrumentation end
                return df
            except Exception:
                log.debug(
                    "Failed to copy trace data from source repo for dataset %s",
                    sample.dataset_id,
                    exc_info=True,
                )
    df = pd.DataFrame()
    # DEBUG: _resolve_trace_dataframe final instrumentation start
    try:
        shape = df.shape
        is_empty = df.empty
    except Exception:
        shape = None
        is_empty = None
    log.debug(
        "_resolve_trace_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
        sample_name,
        dataset_id,
        shape,
        is_empty,
    )
    # DEBUG: _resolve_trace_dataframe final instrumentation end
    return df


def _resolve_events_dataframe(
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
) -> pd.DataFrame | None:
    # DEBUG: _resolve_events_dataframe entry instrumentation start
    dataset_id = getattr(sample, "dataset_id", None)
    sample_name = getattr(sample, "name", None)
    source_repo_type = type(source_repo).__name__ if source_repo is not None else None
    log.debug(
        "_resolve_events_dataframe: start sample=%r dataset_id=%r source_repo=%r",
        sample_name,
        dataset_id,
        source_repo_type,
    )
    # DEBUG: _resolve_events_dataframe entry instrumentation end
    # DEBUG: Check if events_data exists
    if isinstance(sample.events_data, pd.DataFrame):
        df = sample.events_data
        # DEBUG: _resolve_events_dataframe in-memory path instrumentation start
        try:
            shape = df.shape
            is_empty = df.empty
        except Exception:
            shape = None
            is_empty = None
        log.debug(
            "_resolve_events_dataframe: using in-memory events_data sample=%r dataset_id=%r df_shape=%r empty=%r",
            sample_name,
            dataset_id,
            shape,
            is_empty,
        )
        # DEBUG: _resolve_events_dataframe in-memory path instrumentation end
        log.info(
            f"✓ Found events_data DataFrame for '{sample.name}' ({len(sample.events_data)} rows)"
        )
        return df

    log.info(f"⚠️  No events_data in memory for '{sample.name}', checking other sources...")

    if sample.events_path:
        log.debug(f"  Trying events_path: {sample.events_path}")
        path = _absolute_path(sample.events_path, base_dir)
        if path and path.exists():
            try:
                # DEBUG: _resolve_events_dataframe file path instrumentation start
                log.debug(
                    "_resolve_events_dataframe: attempting file load for sample=%r dataset_id=%r path=%r exists=%r",
                    sample_name,
                    dataset_id,
                    str(path),
                    path.exists(),
                )
                # DEBUG: _resolve_events_dataframe file path instrumentation end
                df = pd.read_csv(path)
                log.debug(f"  ✓ Loaded {len(df)} events from CSV")
                # DEBUG: _resolve_events_dataframe final instrumentation start
                try:
                    shape = df.shape
                    is_empty = df.empty
                except Exception:
                    shape = None
                    is_empty = None
                log.debug(
                    "_resolve_events_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
                    sample_name,
                    dataset_id,
                    shape,
                    is_empty,
                )
                # DEBUG: _resolve_events_dataframe final instrumentation end
                return df
            except Exception:
                log.debug("Failed to reload events CSV from %s", path, exc_info=True)

    if source_repo is not None and sample.dataset_id is not None:
        log.debug(f"  Trying source_repo for dataset_id={sample.dataset_id}")
        get_events = getattr(source_repo, "get_events", None)
        if callable(get_events):
            try:
                # DEBUG: _resolve_events_dataframe repo path instrumentation start
                log.debug(
                    "_resolve_events_dataframe: using source_repo=%r for dataset_id=%r",
                    source_repo_type,
                    dataset_id,
                )
                # DEBUG: _resolve_events_dataframe repo path instrumentation end
                df = cast(pd.DataFrame, get_events(sample.dataset_id))
                log.debug(f"  ✓ Loaded {len(df)} events from source repo")
                # DEBUG: _resolve_events_dataframe final instrumentation start
                try:
                    shape = df.shape
                    is_empty = df.empty
                except Exception:
                    shape = None
                    is_empty = None
                log.debug(
                    "_resolve_events_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
                    sample_name,
                    dataset_id,
                    shape,
                    is_empty,
                )
                # DEBUG: _resolve_events_dataframe final instrumentation end
                return df
            except Exception:
                log.debug(
                    "Failed to copy events data from source repo for dataset %s",
                    sample.dataset_id,
                    exc_info=True,
                )

    log.debug(f"  ✗ No events found for '{sample.name}'")
    df = None
    # DEBUG: _resolve_events_dataframe final instrumentation start
    log.debug(
        "_resolve_events_dataframe: end sample=%r dataset_id=%r df_shape=%r empty=%r",
        sample_name,
        dataset_id,
        None,
        None,
    )
    # DEBUG: _resolve_events_dataframe final instrumentation end
    return None


P2_CANONICAL_LABEL = "Set Pressure (mmHg)"
_P2_LABEL_ALIASES = (
    "Pressure 2 (mmHg)",
    "Pressure2 (mmHg)",
    "Pressure 2",
    "Pressure2",
    "P2 (mmHg)",
    "P2",
    "Set P (mmHg)",
)


def normalize_p2_label(label: str | None) -> str:
    if not isinstance(label, str) or not label.strip():
        return P2_CANONICAL_LABEL
    normalized = _normalize_column_label(label)
    alias_norms = {
        _normalize_column_label(alias) for alias in (_P2_LABEL_ALIASES + (P2_CANONICAL_LABEL,))
    }
    if normalized in alias_norms:
        return P2_CANONICAL_LABEL
    return label


def _normalize_trace_column_labels(labels: dict[str, str] | None) -> dict[str, str] | None:
    if labels is None:
        return {"p2": P2_CANONICAL_LABEL}
    normalized = dict(labels)
    normalized["p2"] = normalize_p2_label(normalized.get("p2"))
    return normalized


_TRACE_COLUMN_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "p_avg": (
        "Avg Pressure (mmHg)",
        "Average Pressure (mmHg)",
        "Avg Pressure",
        "Average Pressure",
        "Avg P (mmHg)",
        "Average P (mmHg)",
    ),
    "p1": (
        "Pressure 1 (mmHg)",
        "Pressure1 (mmHg)",
        "Pressure 1",
        "P1 (mmHg)",
        "P1",
    ),
    "p2": (
        *_P2_LABEL_ALIASES,
        "Set Pressure (mmHg)",
        "Set Pressure",
    ),
}


def _normalize_column_label(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _detect_trace_column_labels(trace_df: pd.DataFrame | None) -> dict[str, str]:
    if trace_df is None or trace_df.empty:
        return {}
    normalized_columns = {
        _normalize_column_label(col): col for col in trace_df.columns if isinstance(col, str)
    }
    labels: dict[str, str] = {}
    for canonical, aliases in _TRACE_COLUMN_LABEL_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize_column_label(alias)
            if alias_norm in normalized_columns:
                labels[canonical] = normalized_columns[alias_norm]
                break
    normalized = _normalize_trace_column_labels(labels) or {}
    return normalized


def _build_sample_extra(
    experiment: Experiment,
    sample: SampleN,
    base_dir: Path,
    trace_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    trace_link = _sample_link_payload(
        path_value=sample.trace_path,
        relative_hint=sample.trace_relative,
        absolute_hint=sample.trace_hint,
        base_dir=base_dir,
        signature_hint=sample.trace_signature,
    )
    events_link = _sample_link_payload(
        path_value=sample.events_path,
        relative_hint=sample.events_relative,
        absolute_hint=sample.events_hint,
        base_dir=base_dir,
        signature_hint=sample.events_signature,
    )
    payload: dict[str, Any] = {
        "experiment": experiment.name,
        "experiment_index": experiment.samples.index(sample)
        if sample in experiment.samples
        else None,
        "exported": sample.exported,
        "column": sample.column,
        "trace_path": _relativize_path(sample.trace_path, base_dir),
        "events_path": _relativize_path(sample.events_path, base_dir),
        "snapshot_path": _relativize_path(sample.snapshot_path, base_dir),
        "ui_state": sample.ui_state,
        "figure_configs": sample.figure_configs,
    }
    if trace_link:
        payload["trace_link"] = trace_link
    if events_link:
        payload["events_link"] = events_link

    trace_labels: dict[str, str] | None = None
    if sample.trace_column_labels:
        trace_labels = _normalize_trace_column_labels(sample.trace_column_labels)
    else:
        trace_source = trace_df if trace_df is not None else sample.trace_data
        trace_labels = _detect_trace_column_labels(trace_source)
    if trace_labels:
        payload["trace_column_labels"] = trace_labels

    if sample.edit_history:
        payload["edit_history"] = sample.edit_history

    return cast(dict[str, Any], _normalise_json_data(payload))


def _persist_sample_attachments(
    repo: ProjectRepository,
    dataset_id: int,
    sample: SampleN,
    base_dir: Path,
) -> list[dict[str, Any]]:
    t_start = time.perf_counter()
    payload: list[dict[str, Any]] = []
    for index, att in enumerate(sample.attachments or []):
        meta = att.to_metadata()
        role = f"attachment:{index}"
        meta["asset_role"] = role
        meta["source_path"] = _relativize_path(att.source_path, base_dir)
        meta["data_path"] = _relativize_path(att.data_path, base_dir)
        payload.append(cast(dict[str, Any], _normalise_json_data(meta)))

        source = att.source_path or att.data_path
        path = _absolute_path(source, base_dir) if source else None
        if source and source.lower().endswith((".tif", ".tiff")):
            log.info(
                "Save: skipping TIFF embedding for sample=%s role=%s path=%s "
                "(temporary large-file limit)",
                getattr(sample, "name", None),
                role,
                source,
            )
            continue
        if path and path.exists():
            try:
                data = path.read_bytes()
                repo.add_or_update_asset(
                    dataset_id,
                    role,
                    data,
                    embed=True,
                    mime=None,
                )
            except Exception:
                log.debug("Failed to embed attachment %s", path, exc_info=True)
    duration = time.perf_counter() - t_start
    log.info(
        "Save: attachments sample=%s dataset_id=%s count=%d time=%.3fs",
        sample.name,
        dataset_id,
        len(sample.attachments or []),
        duration,
    )
    return payload


def get_file_size_mb(file_path: str) -> float:
    """Get file size in megabytes.

    Args:
        file_path: Path to file

    Returns:
        File size in MB, or 0 if file doesn't exist
    """
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    except (OSError, FileNotFoundError):
        return 0.0


def _persist_sample_snapshots(
    repo: ProjectRepository,
    dataset_id: int,
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
    embed_snapshots: bool = False,
    embed_tiff_snapshots: bool = False,
) -> dict[str, Any]:
    t_start = time.perf_counter()
    payload: dict[str, Any] = {}

    snapshot_role = sample.snapshot_role or "snapshot_stack"
    snapshot_bytes: bytes | None = None
    snapshot_format = (sample.snapshot_format or "").lower() or "npz"
    snapshot_mime = "application/x-npz"

    if embed_snapshots:
        # Embedding is opt-in to keep saves lightweight by default
        if isinstance(sample.snapshots, np.ndarray):
            buffer = io.BytesIO()
            np.savez_compressed(buffer, stack=sample.snapshots)
            snapshot_bytes = buffer.getvalue()
            snapshot_format = "npz"
            snapshot_mime = "application/x-npz"
        elif source_repo is not None and sample.dataset_id is not None:
            asset_roles = sample.asset_roles or {}
            asset_id = asset_roles.get(snapshot_role)
            if asset_id:
                existing = None
                get_asset_bytes = getattr(source_repo, "get_asset_bytes", None)
                if callable(get_asset_bytes):
                    try:
                        existing = cast(bytes, get_asset_bytes(asset_id))
                    except Exception:
                        existing = None
                if existing:
                    snapshot_bytes = existing
                    if existing.startswith(b"PK"):
                        snapshot_format = "npz"
                        snapshot_mime = "application/x-npz"
                    elif existing.startswith(b"\x93NUMPY"):
                        snapshot_format = "npy"
                        snapshot_mime = "application/x-npy"
                    else:
                        snapshot_format = sample.snapshot_format or snapshot_format
                        snapshot_mime = (
                            f"application/x-{snapshot_format}"
                            if snapshot_format in {"npz", "npy"}
                            else "application/octet-stream"
                        )

    if snapshot_bytes is not None:
        repo.add_or_update_asset(
            dataset_id,
            snapshot_role,
            snapshot_bytes,
            embed=True,
            mime=snapshot_mime,
        )
        payload["snapshot_role"] = snapshot_role
        payload["snapshot_format"] = snapshot_format
        sample.snapshot_role = snapshot_role
        sample.snapshot_format = snapshot_format
    else:
        sample.snapshot_role = None
        sample.snapshot_format = None

    snapshot_path = sample.snapshot_path
    if snapshot_path:
        abs_path = _absolute_path(snapshot_path, base_dir)
        rel_path = _relativize_path(abs_path.as_posix(), base_dir) if abs_path else snapshot_path
        payload["snapshot_path"] = rel_path

        # Optional TIFF embedding (requires explicit opt-in via embed_tiff_snapshots flag)
        if embed_tiff_snapshots and abs_path and abs_path.exists():
            # Check if file is a TIFF
            if abs_path.suffix.lower() in {".tiff", ".tif"}:
                file_size_mb = get_file_size_mb(str(abs_path))
                log.warning(
                    "Embedding TIFF snapshot for sample=%s (size=%.1f MB). "
                    "This will increase .vaso file size significantly.",
                    sample.name,
                    file_size_mb,
                )
                try:
                    with open(abs_path, "rb") as f:
                        tiff_bytes = f.read()

                    tiff_role = "snapshot_tiff"
                    repo.add_or_update_asset(
                        dataset_id,
                        tiff_role,
                        tiff_bytes,
                        embed=True,
                        mime="image/tiff",
                    )
                    sample.snapshot_tiff_role = tiff_role
                    payload["snapshot_tiff_role"] = tiff_role
                    log.info(
                        "Embedded TIFF snapshot for sample=%s (size=%.1f MB)",
                        sample.name,
                        file_size_mb,
                    )
                except Exception as e:
                    log.error("Failed to embed TIFF snapshot: %s", e)
                    sample.snapshot_tiff_role = None
            else:
                sample.snapshot_tiff_role = None
        else:
            # Default: Do NOT embed TIFF snapshots to avoid ballooning .vaso size.
            # They are used only for local playback; keeping the path is sufficient.
            sample.snapshot_tiff_role = None
    duration = time.perf_counter() - t_start
    log.info(
        "Save: snapshots sample=%s dataset_id=%s time=%.3fs",
        sample.name,
        dataset_id,
        duration,
    )
    return payload


def _persist_sample_results(
    repo: ProjectRepository,
    dataset_id: int,
    sample: SampleN,
) -> list[str]:
    if not isinstance(sample.analysis_results, dict):
        return []
    serialized = _serialize_analysis_results(sample.analysis_results)
    keys: list[str] = []
    for kind, payload in serialized.items():
        repo.add_result(
            dataset_id,
            kind=kind,
            version=APP_VERSION,
            payload=payload,
        )
        keys.append(kind)
    return keys


def _store_project_attachments(
    repo: ProjectRepository,
    attachments: list[Attachment],
    base_dir: Path,
) -> None:
    base_dir = base_dir.resolve()
    metadata = {"extra_json": {"kind": "project_attachments"}}
    dataset_id = repo.add_dataset(
        "__project_attachments__",
        pd.DataFrame(),
        None,
        metadata=metadata,
    )
    payload: list[dict[str, Any]] = []
    for index, att in enumerate(attachments):
        meta = att.to_metadata()
        role = f"project_attachment:{index}"
        meta["asset_role"] = role
        meta["source_path"] = _relativize_path(att.source_path, base_dir)
        meta["data_path"] = _relativize_path(att.data_path, base_dir)
        payload.append(cast(dict[str, Any], _normalise_json_data(meta)))

        source = att.source_path or att.data_path
        path = _absolute_path(source, base_dir) if source else None
        if path and path.exists():
            try:
                data = path.read_bytes()
                repo.add_or_update_asset(
                    dataset_id,
                    role,
                    data,
                    embed=True,
                    mime=None,
                )
            except Exception:
                log.debug("Failed to embed project attachment %s", path, exc_info=True)

    extra = {"kind": "project_attachments", "attachments": payload}
    repo.update_dataset_meta(dataset_id, extra_json=extra)


def _is_cloud_storage_path(path: str) -> tuple[bool, str | None]:
    """
    Check if the path is in a cloud storage location.

    Detects major cloud storage services across macOS, Windows, and Linux.
    Enhanced to catch more path variations and ensure reliable detection.

    Args:
        path: Path to check

    Returns:
        Tuple of (is_cloud, cloud_service_name)
    """
    from pathlib import Path

    path_lower = path.lower()

    # Normalize path for better matching
    try:
        path_normalized = Path(path).expanduser().resolve(strict=False).as_posix().lower()
    except Exception:
        # If path normalization fails, use original path
        path_normalized = path_lower.replace("\\", "/")

    # macOS iCloud Drive (multiple possible formats)
    icloud_patterns = [
        "library/mobile documents/com~apple~clouddocs",  # Fixed typo
        "library/mobile documents/com~apple~",           # More general
        "/icloud drive/",
        "/icloud/",
    ]
    if any(pattern in path_normalized for pattern in icloud_patterns):
        return True, "iCloud Drive"

    # Dropbox (all platforms)
    if "dropbox" in path_lower:
        return True, "Dropbox"

    # Google Drive (all platforms)
    google_patterns = ["google drive", "googledrive", "google-drive-desktop"]
    if any(pattern in path_lower for pattern in google_patterns):
        return True, "Google Drive"

    # OneDrive (Windows and macOS)
    if "onedrive" in path_lower:
        return True, "OneDrive"

    # Box (Box Sync and Box Drive)
    box_patterns = ["box sync", "box.com", "box drive", "box/"]
    if any(pattern in path_lower for pattern in box_patterns):
        return True, "Box"

    # Nextcloud/ownCloud (Linux/cross-platform)
    if "nextcloud" in path_lower or "owncloud" in path_lower:
        return True, "Nextcloud/ownCloud"

    # Sync.com
    if "sync.com" in path_lower or "/sync/" in path_normalized:
        return True, "Sync.com"

    return False, None


def _attempt_database_recovery(db_path: str) -> bool:
    """
    Attempt to recover a corrupted SQLite database using multiple methods.

    This function tries three recovery strategies in order:
    1. CLI sqlite3 tool (most robust)
    2. Python iterdump() method (fallback)
    3. PRAGMA recovery mode (last resort)

    Args:
        db_path: Path to the corrupted database file

    Returns:
        True if recovery was successful, False otherwise
    """
    import shutil
    import sqlite3
    import subprocess

    # Check if database is in cloud storage
    is_cloud, cloud_service = _is_cloud_storage_path(db_path)
    if is_cloud:
        log.warning(
            f"Database is located in {cloud_service}. "
            f"SQLite databases are INCOMPATIBLE with cloud storage sync and will become corrupted. "
            "Please move your project to a local folder (e.g., Documents, Desktop) "
            "to prevent future corruption."
        )

    backup_path = f"{db_path}.backup"
    recovered_path = f"{db_path}.recovered"
    dump_path = f"{db_path}.sql"

    try:
        # Create backup of corrupted file
        shutil.copy2(db_path, backup_path)
        log.info(f"Created backup of corrupted database: {backup_path}")

        # Method 1: Try CLI sqlite3 tool (most robust for corrupted databases)
        log.info("Recovery Method 1: Attempting CLI sqlite3 .dump...")
        try:
            # Try to dump using command-line sqlite3
            result = subprocess.run(
                ["sqlite3", db_path, ".dump"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0 and result.stdout:
                # Create new database from dump
                log.info("CLI dump succeeded, creating new database...")
                recovery_conn = sqlite3.connect(recovered_path)
                recovery_conn.executescript(result.stdout)
                recovery_conn.commit()
                recovery_conn.close()

                # Replace original with recovered
                shutil.move(recovered_path, db_path)
                log.info(f"Database recovery successful (CLI method): {db_path}")
                return True
            else:
                log.warning(f"CLI sqlite3 failed: {result.stderr}")

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            log.warning(f"CLI sqlite3 method failed: {e}")

        # Method 2: Try Python iterdump() (fallback)
        log.info("Recovery Method 2: Attempting Python iterdump()...")
        try:
            conn = sqlite3.connect(db_path)
            recovery_conn = sqlite3.connect(recovered_path)

            # Attempt to recover what we can
            recovered_lines = 0
            for line in conn.iterdump():
                try:
                    recovery_conn.execute(line)
                    recovered_lines += 1
                except sqlite3.Error:
                    pass  # Skip corrupted rows

            recovery_conn.commit()
            recovery_conn.close()
            conn.close()

            if recovered_lines > 0:
                # Replace original with recovered
                shutil.move(recovered_path, db_path)
                log.info(
                    "Database recovery successful (Python iterdump, %s lines): %s",
                    recovered_lines,
                    db_path,
                )
                return True
            else:
                log.warning("Python iterdump recovered 0 lines")

        except Exception as e:
            log.warning(f"Python iterdump method failed: {e}")

        # Method 3: Try PRAGMA recovery mode (last resort)
        log.info("Recovery Method 3: Attempting PRAGMA recovery mode...")
        try:
            conn = sqlite3.connect(db_path)
            recovery_conn = sqlite3.connect(recovered_path)

            # Enable recovery mode
            conn.execute("PRAGMA writable_schema=ON")

            # Try to copy readable tables
            tables_recovered = 0
            try:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                for (table_name,) in tables:
                    try:
                        # Get table schema
                        cursor = conn.execute(
                            f"SELECT sql FROM sqlite_master WHERE name='{table_name}'"
                        )
                        schema = cursor.fetchone()
                        if schema and schema[0]:
                            recovery_conn.execute(schema[0])

                        # Copy data
                        cursor = conn.execute(f"SELECT * FROM {table_name}")
                        rows = cursor.fetchall()
                        if rows:
                            placeholders = ",".join(["?"] * len(rows[0]))
                            recovery_conn.executemany(
                                f"INSERT INTO {table_name} VALUES ({placeholders})", rows
                            )
                            tables_recovered += 1
                    except sqlite3.Error:
                        pass  # Skip corrupted tables

            except sqlite3.Error:
                pass

            recovery_conn.commit()
            recovery_conn.close()
            conn.close()

            if tables_recovered > 0:
                shutil.move(recovered_path, db_path)
                log.info(
                    "Database recovery successful (PRAGMA recovery, %s tables): %s",
                    tables_recovered,
                    db_path,
                )
                return True
            else:
                log.warning("PRAGMA recovery mode recovered 0 tables")

        except Exception as e:
            log.error(f"PRAGMA recovery method failed: {e}", exc_info=True)

        # All methods failed
        log.error("All recovery methods failed")
        # Restore from backup
        if Path(backup_path).exists():
            shutil.copy2(backup_path, db_path)
        return False

    except Exception as e:
        log.error(f"Could not create database backup: {e}", exc_info=True)
        return False
    finally:
        # Cleanup temporary files
        for temp_file in [recovered_path, dump_path]:
            if Path(temp_file).exists():
                with contextlib.suppress(Exception):
                    Path(temp_file).unlink()


def _load_project_sqlite(path: str) -> Project:
    """Load a SQLite project file into memory."""

    ctx = open_project_ctx(path)
    repo = ctx.repo
    try:
        meta_rows = repo.read_meta()
        experiments_meta = _json_loads(meta_rows.get("experiments_meta"), default={})

        project_name = meta_rows.get("project_name") or Path(path).stem
        project_description = meta_rows.get("project_description")
        project_tags = _json_loads(meta_rows.get("project_tags"), default=[])
        project_ui = _json_loads(meta_rows.get("project_ui_state"))
        project_created = meta_rows.get("project_created_at")
        project_updated = meta_rows.get("project_updated_at")

        base_dir = Path(path).resolve().parent
        tmp_manager = tempfile.TemporaryDirectory()
        tmp_root = Path(tmp_manager.name)

        experiments_map: dict[str, Experiment] = {}
        project_attachments: list[Attachment] = []

        for record in repo.iter_datasets():
            dataset_id = record["id"]
            extra = record.get("extra") or {}
            if extra.get("kind") == "project_attachments":
                project_attachments.extend(
                    _load_project_attachments(repo, dataset_id, extra, tmp_root, base_dir)
                )
                continue

            sample, experiment_name = _dataset_to_sample(
                repo=repo,
                dataset=record,
                base_dir=base_dir,
                tmp_root=tmp_root,
            )

            exp_meta = experiments_meta.get(experiment_name, {})
            experiment = experiments_map.get(experiment_name)
            if experiment is None:
                excel_meta = exp_meta.get("excel_path")
                excel_path_value: str | None = None
                if isinstance(excel_meta, str):
                    absolute_excel = _absolute_path(excel_meta, base_dir)
                    excel_path_value = absolute_excel.as_posix() if absolute_excel else excel_meta

                experiment = Experiment(
                    name=experiment_name,
                    excel_path=excel_path_value,
                    next_column=exp_meta.get("next_column", "B"),
                    samples=[],
                    style=exp_meta.get("style"),
                    notes=exp_meta.get("notes"),
                    tags=list(exp_meta.get("tags", []))
                    if isinstance(exp_meta.get("tags"), list)
                    else [],
                )
                experiments_map[experiment_name] = experiment

            experiment.samples.append(sample)

        project = Project(
            name=project_name,
            experiments=list(experiments_map.values()),
            path=path,
            ui_state=project_ui,
            description=project_description,
            tags=project_tags if isinstance(project_tags, list) else [],
            created_at=project_created,
            updated_at=project_updated,
            attachments=project_attachments,
        )

        project.resources.register_tempdir(tmp_manager, tmp_root.as_posix())

        # CRITICAL FIX: Keep database connection open for project lifetime
        # Register context close as a project resource to ensure:
        # 1. Database stays open for lazy data loading (traces, events, snapshots)
        # 2. File lock is held to prevent concurrent access
        # 3. Both are properly cleaned up when project is closed
        project.register_resource(lambda: close_project_ctx(ctx))

        return project
    except Exception as e:
        # On error, close context immediately and re-raise
        log.error(
            f"🔍 DIAGNOSTIC - Exception during SQLite project load, closing context: {e}",
            exc_info=True,
        )
        close_project_ctx(ctx)
        raise


def autosave_path_for(project_path: str | Path) -> Path:
    path = Path(project_path)
    return path.with_suffix(path.suffix + ".autosave")


def write_project_autosave(project: Project, autosave_path: str | None = None) -> str:
    """Write an autosave snapshot for ``project`` and return its path."""

    if not project.path:
        raise ValueError("Autosave requires the project to have a primary path")

    dest = Path(autosave_path) if autosave_path else autosave_path_for(project.path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")

    original_created = project.created_at
    original_updated = project.updated_at

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        if not project.created_at:
            project.created_at = now_iso
        project.updated_at = now_iso

        tz_name = _project_timezone()
        base_dir = Path(project.path).resolve().parent
        _write_sqlite_project(project, tmp_dest, timezone_name=tz_name, base_dir=base_dir)
        os.replace(tmp_dest, dest)
    finally:
        project.created_at = original_created
        project.updated_at = original_updated
        with contextlib.suppress(OSError):
            if tmp_dest.exists():
                tmp_dest.unlink()

    return dest.as_posix()


def restore_project_from_autosave(
    autosave_path: str | Path,
    project_path: str | None = None,
) -> Project:
    """Restore ``autosave_path`` to ``project_path`` and load the project."""

    autosave_path = Path(autosave_path)
    if not autosave_path.exists():
        raise FileNotFoundError(autosave_path)
    if project_path is None:
        project_path = autosave_path.with_suffix("").as_posix()
    dest = Path(project_path)
    from vasoanalyzer.services.project_service import restore_sqlite_autosave

    restore_sqlite_autosave(autosave_path, dest)
    return load_project(dest.as_posix())


def pack_project_bundle(
    project: Project,
    bundle_path: str | Path,
    *,
    embed_threshold_mb: int = 64,
) -> str:
    """Persist ``project`` and create a shareable ``.vasopack`` bundle."""

    if not project.path:
        raise ValueError("Project must be saved before bundling")

    save_project(project, project.path)
    from vasoanalyzer.services.project_service import pack_sqlite_bundle

    pack_sqlite_bundle(project.path, bundle_path, embed_threshold_mb=embed_threshold_mb)
    return str(bundle_path)


def unpack_project_bundle(
    bundle_path: str | Path,
    dest_dir: str | Path | None = None,
) -> Project:
    """Unpack ``bundle_path`` into ``dest_dir`` and load the resulting project."""

    bundle_path = Path(bundle_path)
    destination = Path(dest_dir) if dest_dir else bundle_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    from vasoanalyzer.services.project_service import unpack_sqlite_bundle

    project_path = unpack_sqlite_bundle(bundle_path, destination)
    return load_project(Path(project_path).as_posix())


def _dataset_to_sample(
    repo: ProjectRepository,
    dataset: dict[str, Any],
    base_dir: Path,
    tmp_root: Path,
) -> tuple[SampleN, str]:
    dataset_id = dataset["id"]
    extra = dataset.get("extra") or {}

    assets = repo.list_assets(dataset_id)
    assets_by_role = {asset["role"]: asset for asset in assets if asset.get("role")}
    attachments = _load_sample_attachments(
        repo,
        dataset_id,
        extra,
        base_dir,
        tmp_root,
        assets_by_role,
    )

    trace_link_meta = extra.get("trace_link") if isinstance(extra, dict) else None
    events_link_meta = extra.get("events_link") if isinstance(extra, dict) else None
    trace_column_labels = None
    if isinstance(extra, dict):
        raw_labels = extra.get("trace_column_labels")
        if isinstance(raw_labels, dict):
            trace_column_labels = {
                str(k): str(v)
                for k, v in raw_labels.items()
                if isinstance(k, str) and isinstance(v, str)
            } or None
    trace_path = _resolve_linked_path(extra.get("trace_path"), trace_link_meta, base_dir)
    events_path = _resolve_linked_path(extra.get("events_path"), events_link_meta, base_dir)
    raw_snapshot = extra.get("snapshot_path")
    if raw_snapshot:
        abs_snapshot = _absolute_path(raw_snapshot, base_dir)
        snapshot_path = abs_snapshot.as_posix() if abs_snapshot else raw_snapshot
    else:
        snapshot_path = None
    snapshot_role = extra.get("snapshot_role")
    if snapshot_role is None and "snapshot_stack" in assets_by_role:
        snapshot_role = "snapshot_stack"
    snapshot_tiff_role = None  # TIFF snapshots are kept external
    result_keys_meta = extra.get("analysis_result_keys")
    analysis_result_keys = list(result_keys_meta) if isinstance(result_keys_meta, list) else None
    edit_history = extra.get("edit_history") if isinstance(extra, dict) else None
    if not isinstance(edit_history, list):
        edit_history = None

    sample = SampleN(
        name=dataset.get("name", f"Dataset {dataset_id}"),
        trace_path=trace_path,
        events_path=events_path,
        diameter_data=None,
        exported=bool(extra.get("exported")),
        column=extra.get("column"),
        trace_data=None,
        trace_column_labels=trace_column_labels,
        events_data=None,
        ui_state=extra.get("ui_state"),
        snapshots=None,
        snapshot_path=snapshot_path,
        notes=dataset.get("notes"),
        analysis_results=None,
        figure_configs=extra.get("figure_configs"),
        attachments=attachments,
        dataset_id=dataset_id,
        asset_roles={role: asset["id"] for role, asset in assets_by_role.items()},
        snapshot_role=snapshot_role,
        snapshot_tiff_role=snapshot_tiff_role,
        snapshot_format=extra.get("snapshot_format"),
        analysis_result_keys=analysis_result_keys,
        edit_history=edit_history,
    )

    _populate_link_metadata(sample, "trace", trace_path, trace_link_meta, base_dir)
    _populate_link_metadata(sample, "events", events_path, events_link_meta, base_dir)

    experiment = extra.get("experiment") or "Default"
    return sample, experiment


def _format_trace_df(
    df: pd.DataFrame,
    column_labels: dict[str, str] | None = None,
    sample_name: str | None = None,
) -> pd.DataFrame | None:
    """
    Convert canonical trace columns (t_seconds, inner_diam, outer_diam, p_avg, p1, p2)
    into UI-facing labels using per-sample metadata. The `p2` channel is always treated
    as the Set Pressure channel unless metadata explicitly sets a custom label.
    """

    if df is None or df.empty:
        return None

    sample_label = sample_name or "<unknown>"

    def _label_for(key: str, default: str) -> str:
        if not column_labels:
            return default
        raw_value = column_labels.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return default
        if key == "p2":
            return normalize_p2_label(raw_value)
        return raw_value

    time_label = _label_for("t_seconds", "Time (s)")
    inner_label = _label_for("inner_diam", "Inner Diameter")
    outer_label = _label_for("outer_diam", "Outer Diameter")
    p_avg_label = _label_for("p_avg", "Avg Pressure (mmHg)")
    p1_label = _label_for("p1", "Pressure 1 (mmHg)")
    p2_label = _label_for("p2", P2_CANONICAL_LABEL)

    log.info("Trace format raw columns=%s for sample=%s", list(df.columns), sample_label)
    log.info(
        "Trace format labels: t_seconds=%r inner_diam=%r outer_diam=%r " "p_avg=%r p1=%r p2=%r",
        time_label,
        inner_label,
        outer_label,
        p_avg_label,
        p1_label,
        p2_label,
    )

    columns: dict[str, pd.Series] = {}

    if "t_seconds" in df.columns:
        columns[time_label] = df["t_seconds"]
    if "inner_diam" in df.columns:
        columns[inner_label] = df["inner_diam"]
    if "outer_diam" in df.columns:
        columns[outer_label] = df["outer_diam"]
    if "p_avg" in df.columns:
        columns[p_avg_label] = df["p_avg"]
    if "p1" in df.columns:
        columns[p1_label] = df["p1"]
    if "p2" in df.columns:
        columns[p2_label] = df["p2"]

    formatted = pd.DataFrame(columns)
    log.info(
        "Trace format final UI columns=%s for sample=%s", list(formatted.columns), sample_label
    )
    if P2_CANONICAL_LABEL in formatted.columns:
        col = formatted[P2_CANONICAL_LABEL]
        log.info(
            "Format: UI Set Pressure for sample %s -> non_null=%d of %d, head=%s",
            sample_label,
            int(col.notna().sum()),
            len(col),
            col.head(5).tolist(),
        )
    else:
        log.info(
            "Format: UI trace for sample %s has no '%s' column; columns=%s",
            sample_label,
            P2_CANONICAL_LABEL,
            list(formatted.columns),
        )
    return formatted


def _format_events_df(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df_local = df.copy()
    # pandas DataFrame.pop() doesn't accept default parameter in newer versions
    extras = df_local.pop("extra") if "extra" in df_local.columns else None
    if extras is not None:
        all_keys: set[str] = set()
        for payload in extras:
            if isinstance(payload, dict):
                all_keys.update(payload.keys())
        for key in all_keys:
            df_local[key] = [
                payload.get(key) if isinstance(payload, dict) else None for payload in extras
            ]

    rename_map = {
        "label": "Event",
        "t_seconds": "Time (s)",
        "frame": "Frame",
        "p_avg": "p_avg",
        "p1": "p1",
        "p2": "p2",
        "temp": "temp",
    }
    present = {k: v for k, v in rename_map.items() if k in df_local.columns}
    formatted = df_local.rename(columns=present)
    return formatted


def _load_sample_results(repo: ProjectRepository, dataset_id: int) -> dict[str, Any] | None:
    rows = repo.get_results(dataset_id)
    if not rows:
        return None
    results: dict[str, Any] = {}
    for row in rows:
        payload = row["payload"]
        key = row["kind"]
        if isinstance(payload, dict) and payload.get("__type__") == "dataframe":
            restored = _deserialize_analysis_results({key: payload})
            results[key] = restored.get(key)
        else:
            results[key] = payload
    return results


def _load_sample_attachments(
    repo: ProjectRepository,
    dataset_id: int,
    extra: dict[str, Any],
    base_dir: Path,
    tmp_root: Path,
    assets: dict[str, dict[str, Any]],
) -> list[Attachment]:
    t_start = time.perf_counter()
    attachments: list[Attachment] = []

    for meta in extra.get("attachments", []) or []:
        attachment = Attachment.from_metadata(meta)
        role = meta.get("asset_role")
        rel_source = meta.get("source_path")
        rel_data = meta.get("data_path")
        if rel_source:
            abs_source = _absolute_path(rel_source, base_dir)
            attachment.source_path = abs_source.as_posix() if abs_source else rel_source
        if rel_data:
            abs_data = _absolute_path(rel_data, base_dir)
            attachment.data_path = abs_data.as_posix() if abs_data else rel_data

        if role and role in assets:
            asset = assets[role]
            data = repo.get_asset_bytes(asset["id"])
            if data:
                target_dir = tmp_root / f"dataset_{dataset_id}" / "attachments"
                target_dir.mkdir(parents=True, exist_ok=True)
                filename = attachment.filename or f"{role}.bin"
                target_path = target_dir / filename
                with open(target_path, "wb") as fh:
                    fh.write(data)
                attachment.data_path = target_path.as_posix()
        attachments.append(attachment)
    duration = time.perf_counter() - t_start
    log.info(
        "Loaded sample attachments dataset_id=%s count=%d time=%.3fs",
        dataset_id,
        len(attachments),
        duration,
    )
    return attachments


def _load_sample_snapshots(
    repo: ProjectRepository,
    dataset_id: int,
    extra: dict[str, Any],
    base_dir: Path,
    tmp_root: Path,
) -> tuple[np.ndarray | None, str | None]:
    assets = {asset["role"]: asset for asset in repo.list_assets(dataset_id)}

    snapshot_role = extra.get("snapshot_role", "snapshot_stack")
    snapshot_asset = assets.get(snapshot_role)
    stack_array: np.ndarray | None = None
    if snapshot_asset:
        data = repo.get_asset_bytes(snapshot_asset["id"])
        if data:
            try:
                buffer = io.BytesIO(data)
                stack_array = np.load(buffer, allow_pickle=False)
            except Exception:
                log.debug("Failed to load snapshot stack for dataset %s", dataset_id, exc_info=True)

    snapshot_path: str | None = None
    raw = extra.get("snapshot_path")
    if raw:
        abs_path = _absolute_path(raw, base_dir)
        snapshot_path = abs_path.as_posix() if abs_path else raw

    return stack_array, snapshot_path


def _load_project_attachments(
    repo: ProjectRepository,
    dataset_id: int,
    extra: dict[str, Any],
    tmp_root: Path,
    base_dir: Path,
) -> list[Attachment]:
    attachments: list[Attachment] = []
    assets = {asset["role"]: asset for asset in repo.list_assets(dataset_id)}
    for meta in extra.get("attachments", []) or []:
        attachment = Attachment.from_metadata(meta)
        role = meta.get("asset_role")
        rel_source = meta.get("source_path")
        rel_data = meta.get("data_path")
        if rel_source:
            abs_source = _absolute_path(rel_source, base_dir)
            attachment.source_path = abs_source.as_posix() if abs_source else rel_source
        if rel_data:
            abs_data = _absolute_path(rel_data, base_dir)
            attachment.data_path = abs_data.as_posix() if abs_data else rel_data
        if role and role in assets:
            asset = assets[role]
            data = repo.get_asset_bytes(asset["id"])
            if data:
                target_dir = tmp_root / "project_attachments"
                target_dir.mkdir(parents=True, exist_ok=True)
                filename = attachment.filename or f"{role}.bin"
                target_path = target_dir / filename
                with open(target_path, "wb") as fh:
                    fh.write(data)
                attachment.data_path = target_path.as_posix()
        attachments.append(attachment)
    return attachments


def _project_timezone() -> str:
    try:
        tzname = time.tzname[0]
        if tzname:
            return tzname
    except Exception:
        pass
    return "UTC"


def _relativize_path(path: str | None, base_dir: Path) -> str | None:
    if not path:
        return None
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            return os.path.normpath(path)
        return os.path.relpath(candidate, base_dir)
    except Exception:
        return path


def _absolute_path(path: str | None, base_dir: Path) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    try:
        return (base_dir / candidate).resolve(strict=False)
    except Exception:
        return base_dir / candidate


def _is_sqlite_file(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            header = fh.read(16)
        return header.startswith(b"SQLite format 3")
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def _json_loads(payload: str | None, default=None):
    if not payload:
        return default
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return default


def _json_default(value: Any):
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, set):
        return list(value)
    return str(value)


def _normalise_json_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalise_json_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise_json_data(v) for v in value]
    if isinstance(value, tuple):
        return [_normalise_json_data(v) for v in value]
    if isinstance(value, set):
        return [_normalise_json_data(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, np.generic):
        try:
            return value.item()
        except Exception:
            return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return [_normalise_json_data(v) for v in value.tolist()]
    if isinstance(value, pd.Index):
        return [_normalise_json_data(v) for v in value.tolist()]
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return value


# Export helpers --------------------------------------------------------


def _column_to_number(col: str) -> int:
    """Convert an Excel style column label (e.g. 'A', 'AA') to a 1-based number."""
    import string

    letters = string.ascii_uppercase
    num = 0
    for c in col.upper():
        num = num * 26 + letters.index(c) + 1
    return num


def _number_to_column(n: int) -> str:
    """Convert a 1-based column number to its Excel style label."""
    import string

    letters = string.ascii_uppercase
    col = ""
    while n > 0:
        n -= 1
        col = letters[n % 26] + col
        n //= 26
    return col


def _increment_column(col: str) -> str:
    """Return the next column label after ``col``."""
    return _number_to_column(_column_to_number(col) + 1)


def export_sample(exp: Experiment, sample: SampleN) -> None:
    """Mark ``sample`` as exported and update ``exp.next_column``."""
    sample.exported = True
    sample.column = exp.next_column
    exp.next_column = _increment_column(exp.next_column)
