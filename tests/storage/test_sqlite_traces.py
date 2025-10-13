import pandas as pd

from vasoanalyzer.storage.sqlite import projects, traces
from vasoanalyzer.storage.sqlite.utils import open_db
from vasoanalyzer.storage.sqlite_store import SCHEMA_VERSION


def test_prepare_trace_rows_normalizes_columns():
    df = pd.DataFrame(
        {
            "Time": [0.0, 1.0],
            "InnerDiameter": [10, 11],
            "OuterDiameter": [12, 13],
            "Pavg": [1.0, 2.0],
        }
    )
    rows = list(traces.prepare_trace_rows(7, df))
    assert len(rows) == 2
    first = rows[0]
    assert first[0] == 7
    assert first[1] == 0.0
    assert first[2] == 10.0
    assert first[3] == 12.0
    assert first[4] == 1.0


def test_fetch_trace_dataframe_filters(tmp_path):
    db_path = tmp_path / "trace.db"
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
        rows = [(1, 0.0, 10.0, 12.0, 1.0, None, None), (1, 1.0, 11.0, 13.0, 2.0, None, None)]
        conn.executemany(
            "INSERT INTO trace(dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        df = traces.fetch_trace_dataframe(conn, 1, t0=0.5, t1=1.5)
        assert list(df["t_seconds"]) == [1.0]
        assert list(df["inner_diam"]) == [11.0]
    finally:
        conn.close()
