"""
Data-safety regression tests.

These tests verify that the save pipeline:
- Preserves all trace rows for all datasets (including unsaved ones)
- Raises hard errors instead of silently dropping data
- Aborts saves when a staging backup cannot be created
- Recovers autosave data after a simulated crash (container format)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    load_project,
    save_project,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace_df(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "t_seconds": [float(i) for i in range(n)],
            "inner_diam": [1.0 + i * 0.1 for i in range(n)],
        }
    )


def _make_events_df() -> pd.DataFrame:
    return pd.DataFrame({"t_seconds": [0.5], "label": ["start"], "frame": [0]})


def _make_project(name: str, n_samples: int = 1) -> Project:
    samples = [
        SampleN(name=f"s{i}", trace_data=_make_trace_df(), events_data=_make_events_df())
        for i in range(n_samples)
    ]
    return Project(name=name, experiments=[Experiment(name="ExpA", samples=samples)])


def _row_count(path: Path, dataset_id: int) -> int:
    """Read trace row count directly from the saved container's current snapshot."""
    import zipfile

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        # Find HEAD.json
        head_names = [n for n in names if n.endswith("HEAD.json")]
        assert head_names, f"No HEAD.json in {path}"
        import json

        head = json.loads(zf.read(head_names[0]))
        current = head.get("current")
        assert current, "HEAD.json has no 'current' key"
        snap_name = [n for n in names if n.endswith(current)]
        assert snap_name, f"Snapshot {current} not in ZIP"
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            snap_path = Path(td) / "snap.sqlite"
            snap_path.write_bytes(zf.read(snap_name[0]))
            with sqlite3.connect(snap_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM trace WHERE dataset_id = ?", (dataset_id,)
                ).fetchone()
                return row[0] if row else 0


# ---------------------------------------------------------------------------
# Test 1: new dataset survives first full save
# ---------------------------------------------------------------------------


def test_new_dataset_survives_full_save(tmp_path):
    """A brand-new project with trace data must have all rows after save/reopen."""
    n_rows = 6
    trace_df = _make_trace_df(n_rows)
    sample = SampleN(name="s1", trace_data=trace_df, events_data=_make_events_df())
    project = Project(name="P", experiments=[Experiment(name="E", samples=[sample])])
    vaso = tmp_path / "test.vaso"
    save_project(project, vaso.as_posix())
    project.close()

    loaded = load_project(vaso.as_posix())
    try:
        assert loaded.experiments, "No experiments after reload"
        assert loaded.experiments[0].samples, "No samples after reload"
        s = loaded.experiments[0].samples[0]
        assert s.dataset_id is not None, "dataset_id not assigned"
        assert s.trace_data is not None or s.dataset_id is not None
        # Verify directly in the snapshot
        count = _row_count(vaso, s.dataset_id)
        assert count == n_rows, f"Expected {n_rows} trace rows, found {count}"
    finally:
        loaded.close()


# ---------------------------------------------------------------------------
# Test 2: new dataset added to existing project survives second save
# ---------------------------------------------------------------------------


def test_new_dataset_survives_second_save(tmp_path):
    """A dataset added in a second session must have all rows after re-save."""
    vaso = tmp_path / "test.vaso"

    # First save: one sample
    project = _make_project("P", n_samples=1)
    save_project(project, vaso.as_posix())
    project.close()

    # Second session: load, add another sample, save again
    project2 = load_project(vaso.as_posix())
    n_rows = 8
    new_sample = SampleN(
        name="new_sample",
        trace_data=_make_trace_df(n_rows),
        events_data=_make_events_df(),
    )
    project2.experiments[0].samples.append(new_sample)
    save_project(project2, vaso.as_posix())
    project2.close()

    # Reopen and verify both samples present
    project3 = load_project(vaso.as_posix())
    try:
        samples = project3.experiments[0].samples
        assert len(samples) == 2, f"Expected 2 samples, found {len(samples)}"

        # Find the new sample by dataset_id (it should be the one with n_rows)
        new_s = next(
            (s for s in samples if s.name == "new_sample"),
            None,
        )
        assert new_s is not None, "New sample not found after reload"
        assert new_s.dataset_id is not None

        count = _row_count(vaso, new_s.dataset_id)
        assert count == n_rows, f"Expected {n_rows} trace rows for new sample, found {count}"
    finally:
        project3.close()


# ---------------------------------------------------------------------------
# Test 3: bulk copy failure raises RuntimeError (no silent data drop)
# ---------------------------------------------------------------------------


def test_bulk_copy_failure_raises(tmp_path):
    """If _bulk_copy_traces_attach raises, save must propagate the error."""
    # First create a valid project with one sample
    vaso = tmp_path / "test.vaso"
    project = _make_project("P")
    save_project(project, vaso.as_posix())
    project.close()

    # Reload — samples loaded from disk use the deferred fast-copy path
    project2 = load_project(vaso.as_posix())
    try:
        with patch(
            "vasoanalyzer.core.project._bulk_copy_traces_attach",
            side_effect=RuntimeError("simulated bulk copy failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated bulk copy failure"):
                save_project(project2, vaso.as_posix())
    finally:
        project2.close()


# ---------------------------------------------------------------------------
# Test 4: staging backup failure aborts save when unsaved data exists
# ---------------------------------------------------------------------------


def test_staging_backup_failure_aborts_save_with_unsaved_data(tmp_path):
    """If staging backup fails and there are unsaved datasets, save must abort with RuntimeError.

    Tests the abort path by patching the helper that detects unsaved datasets to return True,
    and patching the staging DB path check so no backup file is created (simulating disk full).
    """
    from vasoanalyzer.core import project as _proj_module

    vaso = tmp_path / "test.vaso"
    project = _make_project("P", n_samples=1)
    save_project(project, vaso.as_posix())
    project.close()

    project2 = load_project(vaso.as_posix())
    try:
        # Patch _staging_has_datasets_beyond_source to always return True (unsaved data exists)
        # AND make the backup file appear not to exist (so _staging_backup_path stays None).
        # This simulates: backup failed (disk full) + unsaved datasets present → abort.
        def _always_has_unsaved(staging_conn, source_ctx):
            return True

        # Patch Path.is_file to return False for presave_bak files only, simulating backup failure
        original_is_file = Path.is_file

        def _is_file_patched(self):
            if "presave_bak" in self.name:
                raise OSError("simulated disk full — presave backup cannot be created")
            return original_is_file(self)

        with (
            patch.object(_proj_module, "_staging_has_datasets_beyond_source", _always_has_unsaved),
            patch.object(Path, "is_file", _is_file_patched),
        ):
            with pytest.raises(RuntimeError, match="staging backup failed"):
                save_project(project2, vaso.as_posix())
    finally:
        project2.close()


# ---------------------------------------------------------------------------
# Test 5: autosave sidecar recovery after simulated crash (container format)
# ---------------------------------------------------------------------------


def test_autosave_recovery_after_crash(tmp_path):
    """Autosave data in the sidecar is recovered on next open after a crash."""
    from vasoanalyzer.storage.bundle_adapter import open_project_handle, close_project_handle

    vaso = tmp_path / "test.vaso"

    # Create initial project with one row
    project = _make_project("P", n_samples=1)
    save_project(project, vaso.as_posix())
    project.close()

    # Record container mtime before autosave so sidecar will be newer
    import time
    time.sleep(0.01)  # ensure filesystem time difference

    # Simulate an autosave: load project, add a new event to staging, autosave
    project2 = load_project(vaso.as_posix())
    # Manually write a new sample directly to the staging DB before autosave
    store = getattr(project2, "_store", None)
    if store is None:
        project2.close()
        pytest.skip("Project has no _store attribute — cannot simulate autosave")

    # Add a new dataset + trace rows directly into the staging DB (not snapshotted)
    import time as _time
    _now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    try:
        store.conn.execute(
            "INSERT INTO dataset(name, created_utc) VALUES (?, ?)",
            ("crash_test_ds", _now),
        )
        store.conn.commit()
        new_ds_id = store.conn.execute(
            "SELECT id FROM dataset WHERE name = 'crash_test_ds'"
        ).fetchone()[0]
        store.conn.executemany(
            "INSERT INTO trace(dataset_id, t_seconds, inner_diam) VALUES (?, ?, ?)",
            [(new_ds_id, float(i), 1.0 + i * 0.1) for i in range(3)],
        )
        store.conn.commit()
    except Exception as exc:
        project2.close()
        pytest.skip(f"Could not insert test data into staging DB: {exc}")

    # Simulate autosave: write sidecar, but DON'T repack container
    container_path = getattr(store, "container_path", None)
    if container_path is None:
        project2.close()
        pytest.skip("store.container_path not available — container format not active")

    sidecar = Path(container_path).with_suffix(".autosave.sqlite")
    sidecar_dst = sqlite3.connect(str(sidecar))
    try:
        store.conn.backup(sidecar_dst)
    finally:
        sidecar_dst.close()

    # Simulate crash: close project without saving (sidecar remains, container unchanged)
    # We detach the store to avoid cleanup repacking
    project2._store = None
    try:
        store.conn.close()
    except Exception:
        pass

    assert sidecar.is_file(), "Sidecar file should exist before recovery test"

    # Reopen — recovery path should detect sidecar and restore it
    time.sleep(0.01)  # ensure sidecar mtime > container mtime
    handle, conn = open_project_handle(vaso, readonly=False, auto_migrate=False)
    try:
        # The new dataset should now be in the staging DB
        row = conn.execute(
            "SELECT id FROM dataset WHERE name = 'crash_test_ds'"
        ).fetchone()
        assert row is not None, "crash_test_ds dataset not found after autosave recovery"

        trace_count = conn.execute(
            "SELECT COUNT(*) FROM trace WHERE dataset_id = ?", (row[0],)
        ).fetchone()[0]
        assert trace_count == 3, (
            f"Expected 3 recovered trace rows, found {trace_count}"
        )

        # Sidecar should be gone after recovery
        assert not sidecar.is_file(), "Sidecar should be removed after recovery"
    finally:
        close_project_handle(handle)
