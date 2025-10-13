import pandas as pd

from vasoanalyzer.storage.sqlite import events, projects
from vasoanalyzer.storage.sqlite.utils import open_db
from vasoanalyzer.storage.sqlite_store import SCHEMA_VERSION


def test_prepare_event_rows_handles_extra_columns():
    df = pd.DataFrame(
        {
            "Time": [0.0, 1.0],
            "Label": ["a", "b"],
            "Frame": [1, None],
            "Temp": [36.5, 36.7],
            "Custom": ["x", "y"],
        }
    )
    rows = list(events.prepare_event_rows(5, df))
    assert len(rows) == 2
    first = rows[0]
    assert first[0] == 5
    assert first[1] == 0.0
    assert first[2] == "a"
    assert first[3] == 1
    assert first[-1] == '{"Custom": "x"}'


def test_fetch_events_dataframe_roundtrip(tmp_path):
    db_path = tmp_path / "events.db"
    conn = open_db(db_path.as_posix())
    try:
        projects.apply_default_pragmas(conn)
        projects.ensure_schema(
            conn,
            schema_version=SCHEMA_VERSION,
            now="2000-01-01T00:00:00Z",
        )
        conn.execute(
            "INSERT INTO dataset(id, name, created_utc) VALUES (?, ?, ?)",
            (1, "sample", "2000-01-01T00:00:00Z"),
        )
        rows = [
            (1, 0.0, "a", 1, 1.0, None, None, None, '{"note":"x"}'),
            (1, 2.0, "b", 2, 2.0, None, None, None, None),
        ]
        conn.executemany(
            "INSERT INTO event(dataset_id, t_seconds, label, frame, p_avg, p1, p2, temp, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        df = events.fetch_events_dataframe(conn, 1, t0=1.0, t1=3.0)
        assert list(df["t_seconds"]) == [2.0]
        assert df.iloc[0]["label"] == "b"
    finally:
        conn.close()
