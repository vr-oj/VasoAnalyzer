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
    "Attachment",
    "export_sample",
    "events_dataframe_from_rows",
    "normalize_event_table_rows",
]


log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)

# Snapshot media policy defaults
EMBED_SNAPSHOT_TIFFS: bool = False
EMBED_SNAPSHOT_MAX_MB: int = 4


def open_project_ctx(path: str, repo: ProjectRepository | None = None) -> ProjectContext:
    """
    Open ``path`` and return a :class:`ProjectContext`.

    When ``repo`` is provided it is assumed to be pre-configured; otherwise the
    default repository factory is used.
    """

    repository = repo or get_repo(path)
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
    return ProjectContext(path=path, repo=repository, meta=meta)


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

    analysis_payload = data.get("analysis_results")
    analysis_results = None
    if isinstance(analysis_payload, dict):
        analysis_results = _deserialize_analysis_results(analysis_payload)
    elif analysis_payload is not None:
        analysis_results = analysis_payload

    attachments_payload = data.get("attachments") or []
    attachments = []
    if isinstance(attachments_payload, list):
        for raw in attachments_payload:
            if isinstance(raw, dict):
                attachments.append(Attachment.from_metadata(raw))

    return SampleN(
        name=data.get("name", ""),
        trace_path=data.get("trace_path"),
        events_path=data.get("events_path"),
        snapshot_path=data.get("snapshot_path"),
        diameter_data=data.get("diameter_data"),
        exported=data.get("exported", False),
        column=data.get("column"),
        trace_data=trace_data,
        events_data=events_data,
        ui_state=data.get("ui_state"),
        snapshots=None,
        notes=data.get("notes"),
        analysis_results=analysis_results,
        figure_configs=data.get("figure_configs"),
        attachments=attachments,
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


def save_project(project: Project, path: str) -> None:
    """Persist ``project`` to ``path`` using the SQLite .vaso format."""

    _save_project_sqlite(project, path)


def load_project(path: str) -> Project:
    """Open ``path`` returning a populated :class:`Project` instance."""

    if _is_sqlite_file(path):
        return _load_project_sqlite(path)
    return _load_project_legacy_zip(path)


def _save_project_sqlite(project: Project, path: str) -> None:
    """Serialize ``project`` into a fresh SQLite database."""

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

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
    _write_sqlite_project(project, dest, timezone_name=tz_name, base_dir=base_dir)

    project.path = dest.as_posix()


def _write_sqlite_project(
    project: Project,
    dest: Path,
    *,
    timezone_name: str,
    base_dir: Path,
) -> None:
    """Serialise ``project`` into ``dest`` without mutating the caller."""

    dest.parent.mkdir(parents=True, exist_ok=True)

    from vasoanalyzer.services.project_service import create_project_repository

    with tempfile.TemporaryDirectory(dir=dest.parent) as tmpdir:
        tmp_path = Path(tmpdir) / dest.name
        repo = create_project_repository(
            tmp_path.as_posix(),
            app_version=APP_VERSION,
            timezone=timezone_name,
        )
        try:
            _populate_store_from_project(project, repo, base_dir)
            repo.save()
        finally:
            repo.close()

        os.replace(tmp_path, dest)


def _populate_store_from_project(project: Project, repo: ProjectRepository, base_dir: Path) -> None:
    """Populate ``store`` with the contents of ``project``."""

    base_dir = base_dir.resolve()
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
                _save_sample_to_store(
                    repo=repo,
                    base_dir=base_dir,
                    experiment=exp,
                    sample=sample,
                    sample_index=sample_index,
                    source_repo=source_repo,
                )

        if project.attachments:
            _store_project_attachments(repo, project.attachments, base_dir)
    finally:
        if source_ctx is not None:
            close_project_ctx(source_ctx)


def _save_sample_to_store(
    repo: ProjectRepository,
    base_dir: Path,
    experiment: Experiment,
    sample: SampleN,
    sample_index: int,
    source_repo: ProjectRepository | None = None,
) -> None:
    """Serialize an individual ``sample`` into ``store``."""

    trace_df = _resolve_trace_dataframe(sample, base_dir, source_repo)
    events_df = _resolve_events_dataframe(sample, base_dir, source_repo)

    extra = _build_sample_extra(experiment, sample, base_dir)
    metadata = {
        "notes": sample.notes,
        "extra_json": extra,
    }

    dataset_id = repo.add_dataset(
        sample.name or f"Sample {sample_index + 1}",
        trace_df,
        events_df,
        metadata=metadata,
    )
    sample.dataset_id = dataset_id

    attachments_payload = _persist_sample_attachments(repo, dataset_id, sample, base_dir)
    snapshot_info = _persist_sample_snapshots(
        repo,
        dataset_id,
        sample,
        base_dir,
        source_repo=source_repo,
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


def _resolve_trace_dataframe(
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
) -> pd.DataFrame:
    if isinstance(sample.trace_data, pd.DataFrame):
        return sample.trace_data
    if sample.trace_path:
        path = _absolute_path(sample.trace_path, base_dir)
        if path and path.exists():
            try:
                return pd.read_csv(path)
            except Exception:
                log.debug("Failed to reload trace CSV from %s", path, exc_info=True)
    if source_repo is not None and sample.dataset_id is not None:
        get_trace = getattr(source_repo, "get_trace", None)
        if callable(get_trace):
            try:
                return cast(pd.DataFrame, get_trace(sample.dataset_id))
            except Exception:
                log.debug(
                    "Failed to copy trace data from source repo for dataset %s",
                    sample.dataset_id,
                    exc_info=True,
                )
    return pd.DataFrame()


def _resolve_events_dataframe(
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
) -> pd.DataFrame | None:
    if isinstance(sample.events_data, pd.DataFrame):
        return sample.events_data
    if sample.events_path:
        path = _absolute_path(sample.events_path, base_dir)
        if path and path.exists():
            try:
                return pd.read_csv(path)
            except Exception:
                log.debug("Failed to reload events CSV from %s", path, exc_info=True)
    if source_repo is not None and sample.dataset_id is not None:
        get_events = getattr(source_repo, "get_events", None)
        if callable(get_events):
            try:
                return cast(pd.DataFrame, get_events(sample.dataset_id))
            except Exception:
                log.debug(
                    "Failed to copy events data from source repo for dataset %s",
                    sample.dataset_id,
                    exc_info=True,
                )
    return None


def _build_sample_extra(experiment: Experiment, sample: SampleN, base_dir: Path) -> dict[str, Any]:
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
    return cast(dict[str, Any], _normalise_json_data(payload))


def _persist_sample_attachments(
    repo: ProjectRepository,
    dataset_id: int,
    sample: SampleN,
    base_dir: Path,
) -> list[dict[str, Any]]:
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
    return payload


def _persist_sample_snapshots(
    repo: ProjectRepository,
    dataset_id: int,
    sample: SampleN,
    base_dir: Path,
    source_repo: ProjectRepository | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    snapshot_role = sample.snapshot_role or "snapshot_stack"
    snapshot_bytes: bytes | None = None
    snapshot_format = (sample.snapshot_format or "").lower() or "npz"
    snapshot_mime = "application/x-npz"

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

    if snapshot_bytes:
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

    snapshot_path = sample.snapshot_path
    if snapshot_path:
        abs_path = _absolute_path(snapshot_path, base_dir)
        rel_path = _relativize_path(abs_path.as_posix(), base_dir) if abs_path else snapshot_path
        payload["snapshot_path"] = rel_path
        if abs_path and abs_path.exists():
            try:
                embed_tiff = False
                if EMBED_SNAPSHOT_TIFFS:
                    try:
                        stat_result = abs_path.stat()
                    except OSError:
                        pass
                    else:
                        size_mb = stat_result.st_size / (1024 * 1024)
                        embed_tiff = size_mb <= EMBED_SNAPSHOT_MAX_MB
                repo.add_or_update_asset(
                    dataset_id,
                    "snapshot_tiff",
                    abs_path,
                    embed=embed_tiff,
                    mime="image/tiff",
                )
                payload["snapshot_tiff_role"] = "snapshot_tiff"
                sample.snapshot_tiff_role = "snapshot_tiff"
            except Exception:
                log.debug("Failed to register snapshot TIFF %s", abs_path, exc_info=True)
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
        return project
    finally:
        close_project_ctx(ctx)


def autosave_path_for(project_path: str | Path) -> Path:
    path = Path(project_path)
    return path.with_suffix(path.suffix + ".autosave")


def write_project_autosave(project: Project, autosave_path: str | None = None) -> str:
    """Write an autosave snapshot for ``project`` and return its path."""

    if not project.path:
        raise ValueError("Autosave requires the project to have a primary path")

    dest = Path(autosave_path) if autosave_path else autosave_path_for(project.path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    original_created = project.created_at
    original_updated = project.updated_at

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        if not project.created_at:
            project.created_at = now_iso
        project.updated_at = now_iso

        tz_name = _project_timezone()
        base_dir = Path(project.path).resolve().parent
        _write_sqlite_project(project, dest, timezone_name=tz_name, base_dir=base_dir)
    finally:
        project.created_at = original_created
        project.updated_at = original_updated

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
    trace_path = _resolve_linked_path(extra.get("trace_path"), trace_link_meta, base_dir)
    events_path = _resolve_linked_path(extra.get("events_path"), events_link_meta, base_dir)
    raw_snapshot = extra.get("snapshot_path")
    if raw_snapshot:
        abs_snapshot = _absolute_path(raw_snapshot, base_dir)
        snapshot_path = abs_snapshot.as_posix() if abs_snapshot else raw_snapshot
    else:
        snapshot_path = None
        snapshot_tiff_role = extra.get("snapshot_tiff_role")
        if snapshot_tiff_role:
            asset = assets_by_role.get(snapshot_tiff_role)
            if asset and asset.get("storage") == "external" and asset.get("rel_path"):
                abs_path = _absolute_path(asset["rel_path"], base_dir)
                snapshot_path = abs_path.as_posix() if abs_path else asset["rel_path"]
    snapshot_role = extra.get("snapshot_role")
    if snapshot_role is None and "snapshot_stack" in assets_by_role:
        snapshot_role = "snapshot_stack"
    snapshot_tiff_role = extra.get("snapshot_tiff_role")
    result_keys_meta = extra.get("analysis_result_keys")
    analysis_result_keys = list(result_keys_meta) if isinstance(result_keys_meta, list) else None

    sample = SampleN(
        name=dataset.get("name", f"Dataset {dataset_id}"),
        trace_path=trace_path,
        events_path=events_path,
        diameter_data=None,
        exported=bool(extra.get("exported")),
        column=extra.get("column"),
        trace_data=None,
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
    )

    _populate_link_metadata(sample, "trace", trace_path, trace_link_meta, base_dir)
    _populate_link_metadata(sample, "events", events_path, events_link_meta, base_dir)

    experiment = extra.get("experiment") or "Default"
    return sample, experiment


def _format_trace_df(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    rename_map = {
        "t_seconds": "Time (s)",
        "inner_diam": "Inner Diameter",
        "outer_diam": "Outer Diameter",
        "p_avg": "p_avg",
        "p1": "p1",
        "p2": "p2",
    }
    present = {k: v for k, v in rename_map.items() if k in df.columns}
    formatted = df.rename(columns=present)
    return formatted


def _format_events_df(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df_local = df.copy()
    extras = df_local.pop("extra", None)
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
    tiff_role = extra.get("snapshot_tiff_role")
    if tiff_role and tiff_role in assets:
        asset = assets[tiff_role]
        rel_path = asset.get("rel_path")
        storage = asset.get("storage")
        if storage == "external" and rel_path:
            abs_path = _absolute_path(rel_path, base_dir)
            snapshot_path = abs_path.as_posix() if abs_path else rel_path
        else:
            data = repo.get_asset_bytes(asset["id"])
            if data:
                out_dir = tmp_root / f"dataset_{dataset_id}" / "snapshots"
                out_dir.mkdir(parents=True, exist_ok=True)
                ext = ".tif"
                if asset.get("mime") and not asset["mime"].endswith("tiff"):
                    ext = ".bin"
                sha = asset.get("sha256") or "snapshot"
                out_path = out_dir / f"{sha[:16]}{ext}"
                try:
                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    snapshot_path = out_path.as_posix()
                except OSError:
                    snapshot_path = None

    if snapshot_path is None:
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
