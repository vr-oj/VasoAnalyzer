import sqlite3
import threading
import time
from pathlib import Path

import pandas as pd

from vasoanalyzer.storage import validation
from vasoanalyzer.storage.repair import repair_dataset_from_raw, soft_delete_events
from vasoanalyzer.storage.snapshots import create_bundle, create_snapshot
from vasoanalyzer.storage.sqlite import events as _events
from vasoanalyzer.storage.sqlite_store import (
    add_dataset,
    create_project,
    open_project,
    save_project,
)


def _make_project(tmp_path: Path):
    store = create_project(tmp_path / "project.vaso", app_version="test", timezone="UTC")
    trace_df = pd.DataFrame(
        {
            "t_seconds": [0.0, 1.0, 2.0, 3.0],
            "inner_diam": [1.0, 1.1, 1.2, 1.3],
        }
    )
    events_df = pd.DataFrame({"t_seconds": [0.5, 1.5], "label": ["a", "b"], "frame": [1, 2]})
    dataset_id = add_dataset(store, "sample", trace_df, events_df)
    return store, dataset_id


def _insert_event_via_writer(store, dataset_id: int, t_seconds: float, label: str):
    rows = list(
        _events.prepare_event_rows(
            dataset_id,
            pd.DataFrame({"t_seconds": [t_seconds], "label": [label], "frame": [int(t_seconds * 10)]}),
        )
    )

    def _write(conn: sqlite3.Connection):
        conn.executemany(
            """
            INSERT INTO event(
                dataset_id, t_seconds, t_us, label, frame, source_frame, source_row, source_time_str,
                p_avg, p1, p2, temp, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    if getattr(store, "writer", None):
        store.writer.submit(_write).result()
    else:
        _write(store.conn)
    validation.update_dataset_signatures(store.conn, dataset_id)


def test_snapshot_is_consistent_under_autosave(tmp_path):
    store, dataset_id = _make_project(tmp_path)
    bundle = create_bundle(tmp_path / "bundle.vasopack")
    snapshots = []

    def background_edits():
        for i in range(10):
            _insert_event_via_writer(store, dataset_id, 2.0 + 0.05 * i, f"bg-{i}")
            time.sleep(0.01)

    thread = threading.Thread(target=background_edits)
    thread.start()

    for _ in range(3):
        snapshots.append(create_snapshot(bundle, store.path, db_writer=getattr(store, "writer", None)))
        time.sleep(0.02)

    thread.join()

    for snap in snapshots:
        with sqlite3.connect(snap.path) as conn:
            status = conn.execute("PRAGMA integrity_check").fetchone()[0]
            assert str(status).lower() == "ok"
            issues = validation.quick_validate_project(conn)
            assert not issues


def test_open_save_close_soak_no_unexpected_signature_drift(tmp_path):
    store, dataset_id = _make_project(tmp_path)
    base_row = store.conn.execute(
        "SELECT events_signature, trace_signature FROM dataset WHERE id = ?", (dataset_id,)
    ).fetchone()
    base = (base_row[0], base_row[1])
    project_path = store.path
    store.close()

    for _ in range(50):
        reopened = open_project(project_path)
        issues = validation.quick_validate_project(reopened.conn)
        assert not issues
        row = reopened.conn.execute(
            "SELECT events_signature, trace_signature FROM dataset WHERE id = ?", (dataset_id,)
        ).fetchone()
        assert (row[0], row[1]) == base
        save_project(reopened)
        reopened.close()


def test_repair_preserves_user_deletes(tmp_path):
    store, dataset_id = _make_project(tmp_path)
    rows = store.conn.execute(
        "SELECT id FROM event WHERE dataset_id = ? AND deleted_utc IS NULL ORDER BY id", (dataset_id,)
    ).fetchall()
    deleted_id = int(rows[0][0])
    soft_delete_events(store.conn, dataset_id, [deleted_id], reason="user_test", deleted_by="ui")
    store.conn.commit()

    store.conn.execute("UPDATE event SET t_us = t_us + 250000 WHERE dataset_id = ?", (dataset_id,))
    store.conn.commit()

    raw_events = pd.DataFrame({"t_seconds": [0.5, 1.5], "label": ["a", "b"], "frame": [1, 2]})
    summary = repair_dataset_from_raw(store.conn, dataset_id, raw_events=raw_events, source="repair")

    reapplied = store.conn.execute(
        "SELECT COUNT(*) FROM event WHERE dataset_id = ? AND deleted_reason = 'repair_replay'",
        (dataset_id,),
    ).fetchone()[0]
    assert reapplied == 1
    assert summary["deleted_reapplied"] == 1

    issues = validation.quick_validate_project(store.conn)
    assert not issues


def test_dataset_switch_during_autosave_no_contamination(tmp_path):
    store = create_project(tmp_path / "project.vaso", app_version="test", timezone="UTC")
    trace_df = pd.DataFrame({"t_seconds": [0.0, 1.0, 2.0], "inner_diam": [1.0, 1.0, 1.0]})
    events_df = pd.DataFrame({"t_seconds": [0.25], "label": ["base"], "frame": [1]})
    ds_a = add_dataset(store, "A", trace_df, events_df)
    ds_b = add_dataset(store, "B", trace_df, events_df)

    def _insert(ds_id: int, t_seconds: float, label: str):
        rows = list(
            _events.prepare_event_rows(
                ds_id, pd.DataFrame({"t_seconds": [t_seconds], "label": [label], "frame": [1]})
            )
        )
        with store.conn:
            store.conn.executemany(
                """
                INSERT INTO event(
                    dataset_id, t_seconds, t_us, label, frame, source_frame, source_row, source_time_str,
                    p_avg, p1, p2, temp, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    iterations = 20
    for i in range(iterations):
        target = ds_a if i % 2 == 0 else ds_b
        _insert(target, 5.0 + i, f"loop-{target}-{i}")
        save_project(store, skip_optimize=True)

    count_a = store.conn.execute("SELECT COUNT(*) FROM event WHERE dataset_id = ?", (ds_a,)).fetchone()[0]
    count_b = store.conn.execute("SELECT COUNT(*) FROM event WHERE dataset_id = ?", (ds_b,)).fetchone()[0]

    expected_a = 1 + ((iterations + 1) // 2)
    expected_b = 1 + (iterations // 2)
    assert count_a == expected_a
    assert count_b == expected_b

    validation.update_dataset_signatures(store.conn, ds_a)
    validation.update_dataset_signatures(store.conn, ds_b)
    issues = validation.quick_validate_project(store.conn)
    assert not issues
    sig_a = store.conn.execute("SELECT events_signature FROM dataset WHERE id = ?", (ds_a,)).fetchone()[0]
    sig_b = store.conn.execute("SELECT events_signature FROM dataset WHERE id = ?", (ds_b,)).fetchone()[0]
    assert sig_a != sig_b
