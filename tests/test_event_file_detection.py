import pandas as pd

from vasoanalyzer.event_loader import find_matching_event_file, load_events
from vasoanalyzer.trace_loader import load_trace


def test_find_matching_event_file_modern(tmp_path):
    trace = tmp_path / "sample.csv"
    trace.touch()
    events = tmp_path / "sample_table.csv"
    events.touch()
    assert find_matching_event_file(str(trace)) == str(events)


def test_find_matching_event_file_legacy(tmp_path):
    trace = tmp_path / "20191008 MBFA.csv"
    trace.touch()
    events = tmp_path / "20191008 MBFA Table.csv"
    events.touch()
    assert find_matching_event_file(str(trace)) == str(events)


def test_find_matching_event_file_dash(tmp_path):
    trace = tmp_path / "20210309 H89 + 8BcAMP-Hist.csv"
    trace.touch()
    events = tmp_path / "20210309 H89 + 8BcAMP-Hist - Table.csv"
    events.touch()
    assert find_matching_event_file(str(trace)) == str(events)


def test_load_trace_legacy_columns(tmp_path):
    csv_path = tmp_path / "trace.csv"
    df = pd.DataFrame({"T": [0, 1], "I.D.": [10, 11]})
    df.to_csv(csv_path, index=False)

    loaded = load_trace(str(csv_path))
    assert "Time (s)" in loaded.columns
    assert "Inner Diameter" in loaded.columns
    assert loaded["Time (s)"].tolist() == [0, 1]
    assert loaded["Inner Diameter"].tolist() == [10, 11]


def test_load_trace_semicolon_delimiter(tmp_path):
    csv_path = tmp_path / "trace.csv"
    with open(csv_path, "w") as f:
        f.write("Time;ID\n0;5\n1;6\n")
    df = load_trace(str(csv_path))
    assert df["Time (s)"].tolist() == [0, 1]
    assert df["Inner Diameter"].tolist() == [5, 6]


def test_load_events_numeric_strings(tmp_path):
    event_path = tmp_path / "events.csv"
    pd.DataFrame({"Label": ["A", "B"], "Time": ["1", "2"]}).to_csv(event_path, index=False)
    labels, times, frames = load_events(str(event_path))
    assert times == [1.0, 2.0]
