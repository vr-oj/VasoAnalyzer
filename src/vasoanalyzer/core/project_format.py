"""Helpers for validating and normalizing .vaso container metadata."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "ProjectFormatError",
    "ProjectMetaInfo",
    "HeadInfo",
    "ValidationResult",
    "iso_utc_now",
    "read_project_meta",
    "read_head",
    "validate_snapshot_schema",
    "validate_bundle_tree",
    "build_head_document",
]


class ProjectFormatError(ValueError):
    """Raised when a .vaso container is invalid or incomplete."""


@dataclass
class ProjectMetaInfo:
    data: dict[str, Any]
    project_uuid: str
    needs_upgrade: bool


@dataclass
class HeadInfo:
    data: dict[str, Any]
    current: str | None
    previous: str | None
    snapshot_path: Path | None
    needs_upgrade: bool


@dataclass
class ValidationResult:
    meta: ProjectMetaInfo
    head: HeadInfo
    schema_version: int | None
    needs_upgrade: bool


def iso_utc_now() -> str:
    """Return current UTC time as ISO8601 string without microseconds."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProjectFormatError(f"Missing required file: {path.name}")
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ProjectFormatError(f"Could not read {path.name}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ProjectFormatError(f"{path.name} is not a JSON object")
    return loaded


def _normalize_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except Exception:
        return None


def read_project_meta(meta_path: Path, *, app_version: str | None = None) -> ProjectMetaInfo:
    """Load and normalize ``project.meta.json``."""

    meta = _load_json_dict(meta_path)
    needs_upgrade = False

    fmt = meta.get("format")
    if fmt in ("vaso-v1", "bundle-v1"):
        if fmt != "vaso-v1":
            meta["format"] = "vaso-v1"
            needs_upgrade = True
    elif fmt is None:
        meta["format"] = "vaso-v1"
        needs_upgrade = True
    else:
        raise ProjectFormatError(f"Unsupported project format: {fmt}")

    raw_uuid = meta.get("project_uuid")
    project_uuid = _normalize_uuid(raw_uuid)
    if project_uuid is None:
        project_uuid = str(uuid.uuid4())
        needs_upgrade = True
    elif raw_uuid != project_uuid:
        needs_upgrade = True
    if meta.get("project_uuid") != project_uuid:
        meta["project_uuid"] = project_uuid
        needs_upgrade = True

    created_utc = meta.get("created_utc")
    if not isinstance(created_utc, str) or not created_utc:
        created_at = meta.get("created_at")
        if isinstance(created_at, (int, float)):
            created_utc = (
                datetime.fromtimestamp(float(created_at), tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        else:
            created_utc = iso_utc_now()
        meta["created_utc"] = created_utc
        needs_upgrade = True

    # Preserve created_at if present; otherwise set a best-effort default for traceability
    if "created_at" not in meta:
        meta["created_at"] = time.time()
        needs_upgrade = True

    app_version_created = meta.get("app_version_created")
    if app_version and (not isinstance(app_version_created, str) or not app_version_created):
        meta["app_version_created"] = app_version
        needs_upgrade = True

    return ProjectMetaInfo(data=meta, project_uuid=project_uuid, needs_upgrade=needs_upgrade)


def read_head(
    head_path: Path,
    snapshots_dir: Path,
    *,
    require_current: bool = True,
) -> HeadInfo:
    """Load and normalize ``HEAD.json``."""

    head = _load_json_dict(head_path)
    needs_upgrade = False

    current = head.get("current")
    if current is None or current == "":
        if require_current:
            raise ProjectFormatError("HEAD.json is missing the current snapshot pointer")
        current = None
    elif not isinstance(current, str):
        raise ProjectFormatError("HEAD.json current snapshot is invalid")

    snapshot_path: Path | None = None
    if current:
        snapshot_path = snapshots_dir / current
        if not snapshot_path.exists():
            raise ProjectFormatError(f"Snapshot referenced by HEAD is missing: {current}")

    previous = head.get("previous")
    if previous is not None and not isinstance(previous, str):
        previous = None
        needs_upgrade = True
        head["previous"] = None

    if "updated_utc" not in head or not isinstance(head.get("updated_utc"), str):
        head["updated_utc"] = iso_utc_now()
        needs_upgrade = True

    if "timestamp" not in head:
        head["timestamp"] = time.time()
        needs_upgrade = True

    write_in_progress = head.get("write_in_progress")
    if write_in_progress is None:
        head["write_in_progress"] = False
        needs_upgrade = True
    elif not isinstance(write_in_progress, bool):
        head["write_in_progress"] = bool(write_in_progress)
        needs_upgrade = True

    return HeadInfo(
        data=head,
        current=current,
        previous=previous if isinstance(previous, str) else None,
        snapshot_path=snapshot_path,
        needs_upgrade=needs_upgrade,
    )


def validate_snapshot_schema(snapshot_path: Path, *, max_schema_version: int) -> int:
    """Validate that snapshot contains a recognized schema version."""

    if not snapshot_path.exists():
        raise ProjectFormatError(f"Snapshot not found: {snapshot_path.name}")

    try:
        with sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True, timeout=5.0) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            schema_value = row[0] if row else None
            if schema_value is None:
                row = conn.execute("PRAGMA user_version").fetchone()
                schema_value = row[0] if row else None
    except sqlite3.Error as exc:
        raise ProjectFormatError(f"Snapshot could not be read: {exc}") from exc

    if schema_value is None:
        raise ProjectFormatError("Snapshot is missing schema_version metadata")

    try:
        schema_int = int(schema_value)
    except (TypeError, ValueError) as exc:
        raise ProjectFormatError(f"Snapshot schema_version is invalid: {schema_value}") from exc

    if schema_int < 1:
        raise ProjectFormatError(f"Unsupported schema version: {schema_int}")
    if schema_int > max_schema_version:
        raise ProjectFormatError(
            f"Project uses schema version {schema_int}, newer than supported ({max_schema_version})."
        )
    return schema_int


def validate_bundle_tree(
    bundle_root: Path, *, schema_version: int, app_version: str | None = None
) -> ValidationResult:
    """Validate bundle metadata and snapshot state."""

    meta_info = read_project_meta(bundle_root / "project.meta.json", app_version=app_version)
    head_info = read_head(bundle_root / "HEAD.json", bundle_root / "snapshots")

    schema_int: int | None = None
    if head_info.snapshot_path:
        schema_int = validate_snapshot_schema(
            head_info.snapshot_path, max_schema_version=schema_version
        )

    needs_upgrade = meta_info.needs_upgrade or head_info.needs_upgrade
    if head_info.data.get("write_in_progress"):
        log.warning(
            "Bundle opened with write_in_progress flag set; a previous save may have failed."
        )
        needs_upgrade = True
    return ValidationResult(
        meta=meta_info,
        head=head_info,
        schema_version=schema_int,
        needs_upgrade=needs_upgrade,
    )


def build_head_document(
    *,
    current: str | None,
    previous: str | None = None,
    updated_utc: str | None = None,
    write_in_progress: bool | None = None,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a normalized HEAD document preserving unknown keys."""

    head = dict(base or {})
    head["current"] = current
    head["previous"] = previous if previous is not None else head.get("previous")
    head["updated_utc"] = updated_utc or iso_utc_now()
    head["timestamp"] = time.time()
    if write_in_progress is not None:
        head["write_in_progress"] = bool(write_in_progress)
    elif "write_in_progress" not in head:
        head["write_in_progress"] = False
    return head
