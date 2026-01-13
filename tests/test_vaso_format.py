import hashlib
import json
import shutil
import sqlite3
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from vasoanalyzer.core.project import Experiment, Project, SampleN, load_project, save_project
from vasoanalyzer.storage import container_fs
from vasoanalyzer.storage.bundle_adapter import (
    close_project_handle,
    open_project_handle,
    save_project_handle,
)
from vasoanalyzer.storage.snapshots import get_current_snapshot


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_basic_project(tmp_path: Path) -> Path:
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "inner_diam": [1.0, 1.1]})
    events_df = pd.DataFrame({"t_seconds": [0.0], "label": ["start"], "frame": [0]})
    sample = SampleN(name="s1", trace_data=trace_df, events_data=events_df)
    project = Project(name="LegacyProject", experiments=[Experiment(name="ExpA", samples=[sample])])
    vaso_path = tmp_path / "project.vaso"
    save_project(project, vaso_path.as_posix())
    project.close()
    return vaso_path


def _make_legacy_container(tmp_path: Path) -> Path:
    vaso_path = _build_basic_project(tmp_path)
    bundle_root = container_fs.unpack_container_to_temp(vaso_path)

    meta_path = bundle_root / "project.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["format"] = "bundle-v1"
    meta.pop("project_uuid", None)
    meta.pop("app_version_created", None)
    meta.pop("created_utc", None)
    meta_path.write_text(json.dumps(meta))

    head_path = bundle_root / "HEAD.json"
    head = json.loads(head_path.read_text())
    head_path.write_text(json.dumps({"current": head.get("current")}))

    snap_path = next((bundle_root / "snapshots").glob("*.sqlite"))
    with sqlite3.connect(snap_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='experiments_meta'").fetchone()
        if row and row[0]:
            experiments_meta = json.loads(row[0])
            for exp_meta in experiments_meta.values():
                exp_meta.pop("experiment_id", None)
            conn.execute(
                "UPDATE meta SET value=? WHERE key='experiments_meta'",
                (json.dumps(experiments_meta),),
            )
        for ds_id, extra_json in conn.execute("SELECT id, extra_json FROM dataset"):
            if not extra_json:
                continue
            extra = json.loads(extra_json)
            extra.pop("experiment_id", None)
            conn.execute(
                "UPDATE dataset SET extra_json=? WHERE id=?",
                (json.dumps(extra), ds_id),
            )
        conn.commit()

    container_fs.pack_temp_bundle_to_container(bundle_root, vaso_path)
    shutil.rmtree(bundle_root.parent, ignore_errors=True)
    return vaso_path


def test_legacy_vaso_upgrades_on_save(tmp_path: Path):
    vaso_path = _make_legacy_container(tmp_path)
    initial_hash = _hash_file(vaso_path)

    project = load_project(vaso_path.as_posix())
    assert project.experiments and project.experiments[0].experiment_id
    uuid.UUID(str(project.experiments[0].experiment_id))

    save_project(project, vaso_path.as_posix())
    project.close()

    bundle_root = container_fs.unpack_container_to_temp(vaso_path)
    meta = json.loads((bundle_root / "project.meta.json").read_text())
    head = json.loads((bundle_root / "HEAD.json").read_text())

    assert meta["format"] == "vaso-v1"
    uuid.UUID(meta["project_uuid"])
    assert meta.get("created_utc")

    assert head.get("current")
    assert "previous" in head
    assert head.get("updated_utc")
    assert head.get("write_in_progress") is False

    snap_path = bundle_root / "snapshots" / head["current"]
    with sqlite3.connect(snap_path) as conn:
        meta_row = conn.execute("SELECT value FROM meta WHERE key='experiments_meta'").fetchone()
        experiments_meta = json.loads(meta_row[0]) if meta_row and meta_row[0] else {}
        assert experiments_meta
        for exp_meta in experiments_meta.values():
            uuid.UUID(exp_meta.get("experiment_id"))

        extra_json = conn.execute("SELECT extra_json FROM dataset LIMIT 1").fetchone()[0]
        extra = json.loads(extra_json)
        uuid.UUID(extra.get("experiment_id"))
        assert extra.get("experiment")

    shutil.rmtree(bundle_root.parent, ignore_errors=True)

    assert _hash_file(vaso_path) != initial_hash


def test_atomic_save_failure_keeps_original(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    vaso_path = _build_basic_project(tmp_path)
    original_hash = _hash_file(vaso_path)
    handle, _ = open_project_handle(vaso_path, readonly=False, auto_migrate=False)

    original_zip = container_fs.zipfile.ZipFile

    class BoomZip(original_zip):
        def write(self, *args, **kwargs):
            super().write(*args, **kwargs)
            raise RuntimeError("boom")

    monkeypatch.setattr(container_fs.zipfile, "ZipFile", BoomZip)

    with pytest.raises(Exception):
        save_project_handle(handle)

    close_project_handle(handle, save_before_close=False)

    with zipfile.ZipFile(vaso_path, "r") as zf:
        names = zf.namelist()
        assert any(name.endswith("HEAD.json") for name in names)

    handle_ro, _ = open_project_handle(vaso_path, readonly=True, auto_migrate=False)
    close_project_handle(handle_ro, save_before_close=False)

    assert _hash_file(vaso_path) == original_hash


def test_write_in_progress_uses_previous_snapshot(tmp_path: Path):
    vaso_path = _build_basic_project(tmp_path)
    bundle_root = container_fs.unpack_container_to_temp(vaso_path)

    head_path = bundle_root / "HEAD.json"
    head = json.loads(head_path.read_text())
    previous = head.get("previous") or head.get("current")

    # Remove current snapshot and mark interrupted save
    current_path = bundle_root / "snapshots" / head["current"]
    if current_path.exists():
        current_path.unlink()
    head["current"] = head.get("current")
    head["previous"] = previous
    head["write_in_progress"] = True
    head_path.write_text(json.dumps(head))

    recovered = get_current_snapshot(bundle_root)
    assert recovered is not None
    assert recovered.path.name == previous

    updated_head = json.loads(head_path.read_text())
    assert updated_head["current"] == previous
    assert updated_head.get("write_in_progress") is False

    with sqlite3.connect(recovered.path) as conn:
        status = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert str(status).lower() == "ok"

    shutil.rmtree(bundle_root.parent, ignore_errors=True)
