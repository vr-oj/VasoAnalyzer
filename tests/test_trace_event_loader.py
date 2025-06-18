import pandas as pd
from vasoanalyzer.trace_event_loader import load_trace_and_events

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

