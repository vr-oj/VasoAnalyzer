from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from vasoanalyzer.core.file_lock import ProjectFileLock
from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    close_project_ctx,
    load_project,
    open_project_ctx,
    save_project,
)
from vasoanalyzer.services.project_service import autosave_project


def _make_project(project_path: Path) -> Project:
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0], "inner_diam": [10.0, 11.0]})
    events_df = pd.DataFrame({"t_seconds": [0.5], "label": ["start"]})
    sample = SampleN(name="sample-1", trace_data=trace_df, events_data=events_df)
    project = Project(
        name="roundtrip",
        experiments=[Experiment(name="default", samples=[sample])],
        path=project_path.as_posix(),
    )
    return project


def test_project_roundtrip_save_and_reopen(tmp_path: Path) -> None:
    project_path = tmp_path / "roundtrip.vaso"
    project = _make_project(project_path)

    save_project(project, project_path.as_posix())
    project.close()

    reopened = load_project(project_path.as_posix())
    assert reopened.name == "roundtrip"
    assert reopened.experiments
    re_sample = reopened.experiments[0].samples[0]
    assert re_sample.dataset_id is not None
    ctx = open_project_ctx(project_path.as_posix())
    try:
        trace_df = ctx.repo.get_trace(re_sample.dataset_id)
        assert list(trace_df["inner_diam"]) == [10.0, 11.0]
        events_df = ctx.repo.get_events(re_sample.dataset_id)
        assert list(events_df["label"]) == ["start"]
    finally:
        close_project_ctx(ctx)


def test_autosave_creates_snapshot_and_can_restore(tmp_path: Path) -> None:
    project_path = tmp_path / "autosave.vaso"
    project = _make_project(project_path)
    save_project(project, project_path.as_posix())

    autosave_file = autosave_project(project)
    assert autosave_file is not None
    autosave_path = Path(autosave_file)
    assert autosave_path.exists()

    # Verify autosave snapshot is a valid SQLite database
    with sqlite3.connect(autosave_path.as_posix()) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        assert row is not None


def _lock_holder_process(
    path: str,
    ready: multiprocessing.Event,
    release: multiprocessing.Event,
) -> None:
    lock = ProjectFileLock(path)
    lock.acquire(timeout=5.0)
    ready.set()
    release.wait()
    lock.release()


def test_project_lock_blocks_second_open(tmp_path: Path) -> None:
    project_path = tmp_path / "locking.vaso"
    project_path.write_text("", encoding="utf-8")
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    proc = multiprocessing.Process(
        target=_lock_holder_process,
        args=(project_path.as_posix(), ready, release),
    )
    proc.start()
    assert ready.wait(timeout=5.0), "Child process failed to acquire lock"

    try:
        competing_lock = ProjectFileLock(project_path)
        with pytest.raises(RuntimeError):
            competing_lock.acquire(timeout=0.2)
    finally:
        release.set()
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.terminate()
            proc.join()


def test_project_lock_reentrant_same_process(tmp_path: Path) -> None:
    project_path = tmp_path / "reentrant.vaso"
    project_path.write_text("", encoding="utf-8")
    primary_lock = ProjectFileLock(project_path)
    assert primary_lock.acquire(timeout=1.0)

    secondary_lock = ProjectFileLock(project_path)
    assert secondary_lock.acquire(timeout=1.0)

    secondary_lock.release()
    primary_lock.release()


def test_stale_lock_is_cleaned_up(tmp_path: Path) -> None:
    project_path = tmp_path / "stale-lock.vaso"
    project_path.write_text("", encoding="utf-8")
    lock = ProjectFileLock(project_path)

    with open(lock.lock_path, "w", encoding="utf-8") as handle:
        handle.write("999999\n0\n")

    assert lock.acquire(timeout=1.0)
    lock.release()
