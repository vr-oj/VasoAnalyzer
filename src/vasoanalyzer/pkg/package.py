from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from . import paths
from .blobs import add_blob_file, compute_sha256
from .catalog import DatasetCatalog, DatasetEntry
from .io_zip import exists, read_bytes, write_bytes, write_text
from .models import (
    DatasetMeta,
    Event,
    GeneratorInfo,
    Manifest,
    ManifestSummary,
    ProjectMeta,
    RefEntry,
)

APP_GENERATOR = {"app": "VasoAnalyzer", "version": "2.0.0"}


def _generator_info() -> GeneratorInfo:
    return GeneratorInfo(**APP_GENERATOR)


class VasoPackage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.manifest: Manifest = Manifest(generator=_generator_info(), summary=ManifestSummary())
        self.project: ProjectMeta = ProjectMeta()
        self.datasets: dict[str, DatasetMeta] = {}
        self.refs: dict[str, list[RefEntry]] = {}
        self.events: list[Event] = []
        self.catalog: DatasetCatalog = DatasetCatalog()
        self.linkmap: dict[str, str] = {}

    @classmethod
    def create(cls, path: str | Path, title: str = "") -> VasoPackage:
        pkg = cls(Path(path))
        pkg.project.title = title
        pkg.manifest.summary.title = title or ""
        with ZipFile(pkg.path, "w", compression=ZIP_DEFLATED) as z:
            write_text(z, paths.PROJECT_JSON, _dump_json(pkg.project))
            write_text(z, paths.MANIFEST, _dump_json(pkg.manifest))
            write_text(z, paths.EVENTS_JSONL, "")
            write_text(z, paths.AUDIT_JSONL, "")
            write_text(z, "README.md", "# Vaso Project\n")
            write_text(z, paths.LINKMAP_JSON, _dump_json({}))
            write_bytes(z, paths.CATALOG_SQLITE, pkg.catalog.to_bytes(), stored=True)
        return pkg

    @classmethod
    def open(cls, path: str | Path) -> VasoPackage:
        pkg = cls(Path(path))
        with ZipFile(pkg.path, "r") as z:
            manifest_data = json.loads(read_bytes(z, paths.MANIFEST).decode("utf-8"))
            project_data = json.loads(read_bytes(z, paths.PROJECT_JSON).decode("utf-8"))
            pkg.manifest = Manifest(**_coerce_datetimes(manifest_data))
            pkg.project = ProjectMeta(**project_data)
            dataset_ids = _scan_datasets(z)
            for ds_id in dataset_ids:
                dataset_meta = json.loads(
                    read_bytes(z, f"datasets/{ds_id}/dataset.json").decode("utf-8")
                )
                pkg.datasets[ds_id] = DatasetMeta(**dataset_meta)
                refs_path = f"datasets/{ds_id}/refs.json"
                if exists(z, refs_path):
                    ref_entries = json.loads(read_bytes(z, refs_path).decode("utf-8"))
                    pkg.refs[ds_id] = [RefEntry(**entry) for entry in ref_entries]
            events_text = read_bytes(z, paths.EVENTS_JSONL).decode("utf-8")
            if events_text.strip():
                pkg.events = [
                    Event(**json.loads(line)) for line in events_text.splitlines() if line.strip()
                ]
            if exists(z, paths.LINKMAP_JSON):
                pkg.linkmap = json.loads(read_bytes(z, paths.LINKMAP_JSON).decode("utf-8"))
            if exists(z, paths.CATALOG_SQLITE):
                pkg.catalog = DatasetCatalog.from_bytes(read_bytes(z, paths.CATALOG_SQLITE))
            else:
                for ds_id in dataset_ids:
                    pkg._update_catalog_entry(ds_id)
        pkg._apply_linkmap()
        return pkg

    def add_dataset(
        self,
        meta: DatasetMeta,
        refs: list[RefEntry] | None = None,
        channels_parquet: bytes | None = None,
        channels_csv: bytes | None = None,
    ) -> None:
        self.datasets[meta.id] = meta
        self.refs[meta.id] = refs or []
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            write_text(z, f"datasets/{meta.id}/dataset.json", _dump_json(meta))
            write_text(
                z,
                f"datasets/{meta.id}/timebase.json",
                _dump_json(meta.sampling),
            )
            write_text(z, f"datasets/{meta.id}/qc.json", "{}")
            if channels_parquet:
                write_bytes(z, f"datasets/{meta.id}/channels.parquet", channels_parquet)
            if channels_csv:
                write_bytes(z, f"datasets/{meta.id}/channels.csv", channels_csv)
            self._write_refs(z, meta.id)
        self._update_catalog_entry(meta.id)
        self._touch_manifest()

    def add_event(self, event: Event) -> None:
        self.events.append(event)
        self._write_events()
        self._touch_manifest()

    def set_events(self, events: Iterable[Event]) -> None:
        self.events = list(events)
        self._write_events()
        self._touch_manifest()

    def pack_file_into_blobs(
        self,
        dataset_id: str,
        fs_path: str | Path,
        role: str,
        mime: str,
        rel_hint: str | None = None,
    ) -> RefEntry:
        fs_path = Path(fs_path)
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            digest = add_blob_file(z, fs_path)
        ref = RefEntry(
            sha256=digest,
            size=fs_path.stat().st_size,
            mime=mime,
            role=role,
            uri=f"vaso://blobs/{digest}",
            rel_hint=rel_hint,
        )
        self.refs.setdefault(dataset_id, []).append(ref)
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            self._write_refs(z, dataset_id)
        self._update_catalog_entry(dataset_id)
        self._touch_manifest()
        return ref

    def save_project_meta(self) -> None:
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            write_text(z, paths.PROJECT_JSON, _dump_json(self.project))
            write_text(z, paths.MANIFEST, _dump_json(self.manifest))
            write_bytes(z, paths.CATALOG_SQLITE, self.catalog.to_bytes(), stored=True)
            write_text(z, paths.LINKMAP_JSON, _dump_json(self.linkmap))

    def verify(self) -> dict[str, Any]:
        problems: list[str] = []
        with ZipFile(self.path, "r") as z:
            for arc in (paths.MANIFEST, paths.PROJECT_JSON, paths.EVENTS_JSONL):
                if not exists(z, arc):
                    problems.append(f"missing:{arc}")
            dataset_ids = self.datasets or _scan_datasets(z)
            for ds_id in dataset_ids:
                for arc in (
                    f"datasets/{ds_id}/dataset.json",
                    f"datasets/{ds_id}/timebase.json",
                    f"datasets/{ds_id}/refs.json",
                ):
                    if not exists(z, arc):
                        problems.append(f"missing:{arc}")
        return {"ok": len(problems) == 0, "problems": problems}

    def _touch_manifest(self) -> None:
        self.manifest.modified_utc = datetime.now(timezone.utc)
        self.manifest.summary.datasets = len(self.datasets)
        self.manifest.summary.events = len(self.events)
        has_embedded = any(
            any(ref.uri.startswith("vaso://blobs/") for ref in entries)
            for entries in self.refs.values()
        )
        self.manifest.summary.has_embedded_blobs = has_embedded
        self.save_project_meta()

    def _write_events(self) -> None:
        lines = [json.dumps(event.model_dump(mode="json")) for event in self.events]
        content = "\n".join(lines)
        if content:
            content += "\n"
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            write_bytes(z, paths.EVENTS_JSONL, content.encode("utf-8"))

    def _write_refs(self, z: ZipFile, dataset_id: str) -> None:
        payload = [ref.model_dump(mode="json") for ref in self.refs.get(dataset_id, [])]
        write_text(z, f"datasets/{dataset_id}/refs.json", _dump_json(payload))

    def _rewrite_refs(self, dataset_id: str) -> None:
        with ZipFile(self.path, "a", compression=ZIP_DEFLATED) as z:
            self._write_refs(z, dataset_id)

    def _update_catalog_entry(self, dataset_id: str) -> None:
        meta = self.datasets.get(dataset_id)
        if meta is None:
            return
        refs = self.refs.get(dataset_id, [])
        entry = DatasetEntry(
            dataset_id=dataset_id,
            title=meta.name,
            has_embedded_blobs=any(ref.uri.startswith("vaso://blobs/") for ref in refs),
            ref_count=len(refs),
        )
        self.catalog.register(entry)

    def _apply_linkmap(self) -> None:
        if not self.linkmap:
            return
        for dataset_id, ref_entries in self.refs.items():
            changed = False
            for ref in ref_entries:
                key = ref.rel_hint or ref.uri
                mapped = self.linkmap.get(key)
                if not mapped:
                    continue
                if not ref.rel_hint:
                    ref.rel_hint = ref.uri
                ref.uri = mapped
                changed = True
            if changed:
                self._update_catalog_entry(dataset_id)

    def _resolve_reference(self, ref: RefEntry, pkg_dir: Path, root_path: Path) -> str | None:
        candidate_path = self._uri_to_path(ref.uri)
        if candidate_path is not None and candidate_path.exists():
            return candidate_path.resolve().as_posix()

        if candidate_path is not None and not candidate_path.is_absolute():
            sibling = (pkg_dir / candidate_path).resolve()
            if sibling.exists():
                return sibling.as_posix()

        key = ref.rel_hint or ref.uri
        mapped = self.linkmap.get(key)
        if mapped:
            mapped_path = Path(mapped)
            if mapped_path.exists():
                return mapped_path.resolve().as_posix()

        return self._scan_for_checksum(root_path, ref)

    def _scan_for_checksum(self, root_path: Path, ref: RefEntry) -> str | None:
        if not root_path.is_dir():
            return None

        target_name = Path(ref.uri).name
        try:
            candidates = root_path.rglob(target_name)
        except (OSError, ValueError):
            return None

        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                if ref.size and candidate.stat().st_size != ref.size:
                    continue
            except OSError:
                continue
            try:
                if _sha_matches(candidate, ref.sha256):
                    return candidate.resolve().as_posix()
            except OSError:
                continue
        return None

    @staticmethod
    def _uri_to_path(uri: str) -> Path | None:
        if uri.startswith("vaso://"):
            return None
        if uri.startswith("file://"):
            return Path(uri[7:])
        if "://" in uri:
            return None
        return Path(uri)

    def relink(self, root: str | Path) -> dict[str, str]:
        root_path = Path(root)
        if not root_path.exists():
            raise FileNotFoundError(root)

        pkg_dir = self.path.parent
        updates: dict[str, str] = {}

        for dataset_id, ref_entries in list(self.refs.items()):
            changed = False
            for ref in ref_entries:
                if ref.uri.startswith("vaso://blobs/"):
                    continue
                resolved = self._resolve_reference(ref, pkg_dir, root_path)
                if resolved is None:
                    continue
                original = ref.rel_hint or ref.uri
                if resolved != ref.uri:
                    if not ref.rel_hint:
                        ref.rel_hint = ref.uri
                    ref.uri = resolved
                    updates[original] = resolved
                    changed = True
            if changed:
                self._rewrite_refs(dataset_id)
                self._update_catalog_entry(dataset_id)

        if updates:
            self.linkmap.update(updates)
            self._touch_manifest()
        return updates


def _scan_datasets(z: ZipFile) -> list[str]:
    ids: set[str] = set()
    for info in z.infolist():
        if (
            info.filename.startswith("datasets/")
            and info.filename.endswith("dataset.json")
            and info.filename.count("/") >= 2
        ):
            ids.add(info.filename.split("/")[1])
    return sorted(ids)


def _coerce_datetimes(data: dict[str, Any]) -> dict[str, Any]:
    return data


def _dump_json(value: Any) -> str:
    model_dump = getattr(value, "model_dump", None)
    payload = model_dump(mode="json", by_alias=True) if callable(model_dump) else value
    return json.dumps(payload, indent=2)


def _sha_matches(path: Path, expected: str) -> bool:
    return compute_sha256(path) == expected
