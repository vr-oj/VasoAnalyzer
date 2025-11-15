import sqlite3

import pandas as pd

from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.storage.sqlite.traces import fetch_trace_dataframe, prepare_trace_rows


def _write_csv(path, df):
    df.to_csv(path, index=False)


def _sample_trace_df():
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0, 2.0],
            "Inner Diameter": [10.0, 11.0, 12.0],
            "Outer Diameter": [20.0, 21.0, 22.0],
            "Avg Pressure (mmHg)": [50.0, 50.5, 51.0],
            "Set Pressure (mmHg)": [60.0, 60.5, 61.0],
        }
    )


def _sample_events_df():
    return pd.DataFrame(
        {
            "EventLabel": ["StimA", "StimB"],
            "Time": [0.5, 1.5],
            "DiamBefore": [10.5, 11.5],
            "OuterDiamBefore": [20.5, 21.5],
        }
    )


def test_trace_pipeline_preserves_all_channels(tmp_path):
    trace_path = tmp_path / "trace.csv"
    events_path = tmp_path / "trace_table.csv"
    _write_csv(trace_path, _sample_trace_df())
    _write_csv(events_path, _sample_events_df())

    trace_df, *_ = load_trace_and_events(trace_path.as_posix(), events_path.as_posix())

    expected_cols = {
        "Time (s)",
        "Inner Diameter",
        "Outer Diameter",
        "Avg Pressure (mmHg)",
        "Set Pressure (mmHg)",
    }
    assert expected_cols.issubset(set(trace_df.columns))

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE trace(
            dataset_id INTEGER,
            t_seconds REAL,
            inner_diam REAL,
            outer_diam REAL,
            p_avg REAL,
            p1 REAL,
            p2 REAL
        )
        """
    )
    rows = list(prepare_trace_rows(1, trace_df))
    assert len(rows) == len(trace_df.index)
    conn.executemany(
        """
        INSERT INTO trace(dataset_id, t_seconds, inner_diam, outer_diam, p_avg, p1, p2)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    fetched = fetch_trace_dataframe(conn, 1)
    assert len(fetched.index) == len(trace_df.index)
    assert fetched["inner_diam"].tolist() == trace_df["Inner Diameter"].tolist()
    assert fetched["outer_diam"].tolist() == trace_df["Outer Diameter"].tolist()
    assert fetched["p_avg"].tolist() == trace_df["Avg Pressure (mmHg)"].tolist()
    assert fetched["p2"].tolist() == trace_df["Set Pressure (mmHg)"].tolist()
