"""Export/import helpers for portable dataset packages (.vasods)."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from utils.config import APP_VERSION
from vasoanalyzer.storage import bundle_adapter
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.storage.sqlite import projects as _projects

PACKAGE_FORMAT = "vasods-v1"
_TRACE_FILENAME = "data/trace.csv"
_EVENTS_FILENAME = "data/events.csv"
_DATASET_FILENAME = "data/dataset.json"
_RESULTS_FILENAME = "data/results.json"
_MANIFEST_FILENAME = "manifest.json"


class DatasetPackageError(ValueError):
    """Raised when a dataset package is invalid or cannot be imported."""


class DatasetPackageValidationError(DatasetPackageError):
    """Raised when package contents or manifest fail validation."""


@dataclass
class DatasetPackageManifest:
    format: str
    created_utc: str
    app_version_created: str | None
    schema_version_created: int | None
    source_project_uuid: str | None
    dataset_uuid: str
    dataset_name: str
    includes: Mapping[str, bool]
    counts: Mapping[str, int]
    checksums: Mapping[str, str]


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _ensure_suffix(path: Path, suffix: str) -> Path:
    if path.suffix != suffix:
        return path.with_suffix(suffix)
    return path


def _prepare_events_for_export(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    df_local = df.copy()
    if "extra" in df_local.columns:
        df_local["extra"] = df_local["extra"].apply(
            lambda payload: json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
        )
    return df_local


def _load_events_from_csv(data: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(data.decode("utf-8")))
    if "extra" in df.columns:
        df["extra"] = df["extra"].apply(
            lambda payload: json.loads(payload) if isinstance(payload, str) and payload else payload
        )
    return df


def _dedupe_name(base: str, existing: Sequence[str]) -> str:
    if base not in existing:
        return base
    index = 1
    while True:
        suffix = "" if index == 1 else f" {index}"
        candidate = f"{base} (Copy{suffix})"
        if candidate not in existing:
            return candidate
        index += 1


def export_dataset_package(
    project_path: str | Path,
    dataset_id: int,
    out_path: str | Path,
    *,
    include_results: bool = True,
) -> Path:
    """
    Export ``dataset_id`` from ``project_path`` into a portable .vasods archive.
    """

    project_path = Path(project_path).expanduser()
    out_path = _ensure_suffix(Path(out_path), ".vasods")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    store = sqlite_store.open_project(project_path)
    try:
        dataset_meta = sqlite_store.get_dataset_meta(store, dataset_id)
        if dataset_meta is None:
            raise DatasetPackageValidationError(
                f"Dataset {dataset_id} not found in project {project_path}"
            )

        trace_df = sqlite_store.get_trace(store, dataset_id)
        events_df = sqlite_store.get_events(store, dataset_id)
        results = sqlite_store.get_results(store, dataset_id) if include_results else []
        meta_rows = _projects.read_meta(store.conn)
        project_uuid = meta_rows.get("project_uuid")
    finally:
        store.close()

    events_df = _prepare_events_for_export(events_df)
    dataset_uuid = str(uuid.uuid4())

    dataset_json = {
        "id": dataset_meta.get("id"),
        "name": dataset_meta.get("name"),
        "notes": dataset_meta.get("notes"),
        "fps": dataset_meta.get("fps"),
        "pixel_size_um": dataset_meta.get("pixel_size_um"),
        "t0_seconds": dataset_meta.get("t0_seconds"),
        "created_utc": dataset_meta.get("created_utc"),
        "extra": dataset_meta.get("extra"),
    }

    with tempfile.TemporaryDirectory(dir=out_path.parent) as tmpdir:
        tmp_root = Path(tmpdir)
        data_dir = tmp_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        dataset_json_path = data_dir / "dataset.json"
        dataset_json_path.write_text(json.dumps(dataset_json, ensure_ascii=False, indent=2))

        trace_path = data_dir / "trace.csv"
        trace_included = trace_df is not None and not trace_df.empty
        if trace_included:
            trace_df.to_csv(trace_path, index=False)

        events_path = data_dir / "events.csv"
        events_included = events_df is not None and not events_df.empty
        if events_included:
            events_df.to_csv(events_path, index=False)

        results_path = data_dir / "results.json"
        results_included = bool(include_results and results)
        if results_included:
            trimmed = []
            for row in results:
                trimmed.append(
                    {
                        "kind": row.get("kind"),
                        "version": row.get("version"),
                        "created_utc": row.get("created_utc"),
                        "payload": row.get("payload"),
                    }
                )
            results_path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2))

        checksums: dict[str, str] = {}
        checksums[_DATASET_FILENAME] = _sha256_path(dataset_json_path)
        if trace_included:
            checksums[_TRACE_FILENAME] = _sha256_path(trace_path)
        if events_included:
            checksums[_EVENTS_FILENAME] = _sha256_path(events_path)
        if results_included:
            checksums[_RESULTS_FILENAME] = _sha256_path(results_path)

        manifest = {
            "format": PACKAGE_FORMAT,
            "created_utc": _utc_now_iso(),
            "app_version_created": APP_VERSION,
            "schema_version_created": sqlite_store.SCHEMA_VERSION,
            "source_project_uuid": project_uuid,
            "dataset_export": {
                "dataset_name": dataset_meta.get("name"),
                "dataset_uuid": dataset_uuid,
                "includes": {
                    "trace": bool(trace_included),
                    "events": bool(events_included),
                    "results": bool(results_included),
                },
                "counts": {
                    "trace_rows": len(trace_df.index) if trace_df is not None else 0,
                    "event_rows": len(events_df.index) if events_df is not None else 0,
                    "results": len(results) if results_included else 0,
                },
                "checksums": checksums,
            },
        }

        manifest_path = tmp_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

        tmp_zip = out_path.with_suffix(out_path.suffix + ".tmp")
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(manifest_path, arcname=_MANIFEST_FILENAME)
            zf.write(dataset_json_path, arcname=_DATASET_FILENAME)
            if trace_included:
                zf.write(trace_path, arcname=_TRACE_FILENAME)
            if events_included:
                zf.write(events_path, arcname=_EVENTS_FILENAME)
            if results_included:
                zf.write(results_path, arcname=_RESULTS_FILENAME)

        tmp_zip.replace(out_path)

    return out_path


def _validate_manifest(manifest: Mapping[str, Any]) -> DatasetPackageManifest:
    if not isinstance(manifest, Mapping):
        raise DatasetPackageValidationError("Package manifest is missing or malformed.")
    fmt = manifest.get("format")
    if fmt != PACKAGE_FORMAT:
        raise DatasetPackageValidationError(f"Unsupported dataset package format: {fmt!r}")
    dataset_info = manifest.get("dataset_export") or {}
    includes = dataset_info.get("includes") or {}
    counts = dataset_info.get("counts") or {}
    checksums = dataset_info.get("checksums") or {}
    dataset_uuid = dataset_info.get("dataset_uuid") or str(uuid.uuid4())
    dataset_name = dataset_info.get("dataset_name") or "Imported Dataset"
    return DatasetPackageManifest(
        format=fmt,
        created_utc=str(manifest.get("created_utc") or ""),
        app_version_created=manifest.get("app_version_created"),
        schema_version_created=manifest.get("schema_version_created"),
        source_project_uuid=manifest.get("source_project_uuid"),
        dataset_uuid=str(dataset_uuid),
        dataset_name=str(dataset_name),
        includes={k: bool(v) for k, v in includes.items()},
        counts={k: int(v) for k, v in counts.items()},
        checksums={k: str(v) for k, v in checksums.items()},
    )


def _read_and_verify(zf: zipfile.ZipFile, member: str, expected_sha: str) -> bytes:
    try:
        data = zf.read(member)
    except KeyError as exc:
        raise DatasetPackageValidationError(f"Missing required file in package: {member}") from exc
    actual = _sha256_bytes(data)
    if expected_sha and actual != expected_sha:
        raise DatasetPackageValidationError(f"Checksum mismatch for {member}")
    return data


def _load_experiments_meta(repo: sqlite_store.ProjectStore | Any) -> dict[str, Any]:
    # Keep it tolerant of non-ProjectStore wrappers
    meta_rows = _projects.read_meta(repo.conn if hasattr(repo, "conn") else repo._store.conn)
    experiments_raw = meta_rows.get("experiments_meta") or "{}"
    try:
        return json.loads(experiments_raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _upsert_experiment_meta(experiments_meta: dict[str, Any], name: str) -> str:
    meta = experiments_meta.get(name)
    if not isinstance(meta, dict):
        meta = {}
    exp_id = meta.get("experiment_id")
    try:
        exp_id = str(uuid.UUID(str(exp_id)))
    except Exception:
        exp_id = str(uuid.uuid4())
    meta["experiment_id"] = exp_id
    experiments_meta[name] = meta
    return exp_id


def import_dataset_package(
    dest_project_path: str | Path,
    in_path: str | Path,
    *,
    target_experiment_name: str | None = None,
    create_experiment_if_missing: bool = True,
    name_collision: str = "suffix",
) -> int:
    """
    Import a .vasods package into ``dest_project_path``.

    Returns:
        New dataset_id inserted into the destination project.
    """

    dest_project_path = Path(dest_project_path).expanduser()
    in_path = Path(in_path).expanduser()
    if not in_path.exists():
        raise DatasetPackageError(f"Package not found: {in_path}")

    with zipfile.ZipFile(in_path, "r") as zf:
        try:
            manifest = json.loads(zf.read(_MANIFEST_FILENAME))
        except KeyError as exc:
            raise DatasetPackageValidationError("Package is missing manifest.json") from exc
        except json.JSONDecodeError as exc:
            raise DatasetPackageValidationError("manifest.json is corrupted") from exc
        manifest_obj = _validate_manifest(manifest)

        checksums = manifest_obj.checksums
        dataset_payload = _read_and_verify(
            zf, _DATASET_FILENAME, checksums.get(_DATASET_FILENAME, "")
        )
        try:
            dataset_json = json.loads(dataset_payload)
        except json.JSONDecodeError as exc:
            raise DatasetPackageValidationError("dataset.json is corrupted") from exc

        trace_df: pd.DataFrame | None = None
        events_df: pd.DataFrame | None = None
        results_payload: list[Mapping[str, Any]] = []

        if manifest_obj.includes.get("trace"):
            trace_bytes = _read_and_verify(zf, _TRACE_FILENAME, checksums.get(_TRACE_FILENAME, ""))
            trace_df = pd.read_csv(io.StringIO(trace_bytes.decode("utf-8")))
        if manifest_obj.includes.get("events"):
            events_bytes = _read_and_verify(
                zf, _EVENTS_FILENAME, checksums.get(_EVENTS_FILENAME, "")
            )
            events_df = _load_events_from_csv(events_bytes)
        if manifest_obj.includes.get("results"):
            results_bytes = _read_and_verify(
                zf, _RESULTS_FILENAME, checksums.get(_RESULTS_FILENAME, "")
            )
            try:
                results_payload = json.loads(results_bytes)
            except json.JSONDecodeError as exc:
                raise DatasetPackageValidationError("results.json is corrupted") from exc

    handle, conn = bundle_adapter.open_project_handle(
        dest_project_path,
        readonly=False,
        auto_migrate=True,
        create_if_missing=True,
    )
    db_path = bundle_adapter.get_database_path(handle)
    store = sqlite_store.ProjectStore(
        path=db_path,
        conn=conn,
        dirty=False,
        writer=None,
        is_cloud_path=getattr(handle, "is_cloud_path", False),
        cloud_service=getattr(handle, "cloud_service", None),
        journal_mode=None,
    )
    try:
        experiments_meta = _load_experiments_meta(store)

        preferred_exp = (
            target_experiment_name
            or (dataset_json.get("extra") or {}).get("experiment")
            or "Imported"
        )
        exp_id = experiments_meta.get(preferred_exp, {}).get("experiment_id")
        if exp_id is None and not create_experiment_if_missing:
            raise DatasetPackageValidationError(
                f"Target experiment '{preferred_exp}' was not found."
            )
        exp_id = _upsert_experiment_meta(experiments_meta, preferred_exp)

        existing_names = []
        for row in sqlite_store.iter_datasets(store):
            if not isinstance(row, Mapping):
                continue
            extra = row.get("extra") or {}
            if isinstance(extra, Mapping) and extra.get("experiment") == preferred_exp:
                existing_names.append(str(row.get("name")))

        base_name = dataset_json.get("name") or manifest_obj.dataset_name
        final_name = base_name
        if name_collision == "suffix":
            final_name = _dedupe_name(str(base_name), existing_names)

        extra_payload = dataset_json.get("extra") or {}
        if not isinstance(extra_payload, dict):
            extra_payload = {}
        extra_payload["experiment"] = preferred_exp
        extra_payload["experiment_id"] = exp_id
        extra_payload["experiment_index"] = extra_payload.get("experiment_index")
        extra_payload["imported_from_package"] = {
            "dataset_uuid": manifest_obj.dataset_uuid,
            "source_project_uuid": manifest_obj.source_project_uuid,
        }

        metadata = {
            "notes": dataset_json.get("notes"),
            "fps": dataset_json.get("fps"),
            "pixel_size_um": dataset_json.get("pixel_size_um"),
            "t0_seconds": dataset_json.get("t0_seconds"),
            "extra_json": extra_payload,
        }

        dataset_id = sqlite_store.add_dataset(
            store,
            final_name,
            trace_df if trace_df is not None else pd.DataFrame(),
            events_df,
            metadata=metadata,
        )

        for result in results_payload:
            kind = result.get("kind")
            if not kind:
                continue
            payload = result.get("payload") or {}
            version = result.get("version") or APP_VERSION
            sqlite_store.add_result(
                store,
                dataset_id,
                kind=kind,
                version=str(version),
                payload=dict(payload),
            )

        now_iso = _utc_now_iso()
        _projects.write_meta(
            store.conn,
            {
                "experiments_meta": json.dumps(experiments_meta, ensure_ascii=False),
                "modified_utc": now_iso,
                "modified_at": now_iso,
                "project_updated_at": now_iso,
            },
        )
        store.commit()
        bundle_adapter.save_project_handle(handle)
    finally:
        bundle_adapter.close_project_handle(handle, save_before_close=False)

    return int(dataset_id)
