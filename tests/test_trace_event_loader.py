import pandas as pd
from vasoanalyzer.trace_event_loader import load_trace_and_events


def test_load_trace_and_events_legacy_file(tmp_path):
    trace_path = tmp_path / "trace.csv"
    pd.DataFrame({"T (s)": [0, 1], "ID": [10, 11]}).to_csv(trace_path, index=False)
    event_path = tmp_path / "trace_table.csv"
    pd.DataFrame({
        "Time": [0, 1],
        "Event": ["A", "B"],
        "Diameter": [10, 11],
        "Frame": [0, 1],
    }).to_csv(event_path, index=False)

    df, labels, times, frames, diam = load_trace_and_events(str(trace_path))

    assert df["Time (s)"].tolist() == [0, 1]
    assert labels == ["A", "B"]
    assert times == [0, 1]
    assert frames == [0, 1]
    assert diam == [10, 11]


def test_load_trace_and_events_dataframe(tmp_path):
    trace_path = tmp_path / "trace.csv"
    pd.DataFrame({"Time (s)": [0, 1, 2], "Inner Diameter": [5, 6, 7]}).to_csv(trace_path, index=False)

    events_df = pd.DataFrame({
        "Event": ["A", "B"],
        "Time (s)": [0, 1],
        "diameter before": [5, 6],
    })

    df, labels, times, frames, diam = load_trace_and_events(str(trace_path), events_df)

    assert labels == ["A", "B"]
    assert times == [0, 1]
    assert frames == [0, 1]
    assert diam == [5, 6]

