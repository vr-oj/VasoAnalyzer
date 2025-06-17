import pandas as pd

from vasoanalyzer.event_loader import (
    find_matching_event_file,
    load_events,
    _standardize_headers,
)
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


def test_load_events_frame_column_not_label(tmp_path):
    event_path = tmp_path / "events_with_frame.csv"
    df = pd.DataFrame({
        "Time": [0.1, 0.2],
        "Frame Number": [1, 2],
        "Label": ["A", "B"],
    })
    df.to_csv(event_path, index=False)

    labels, times, frames = load_events(str(event_path))

    assert labels == ["A", "B"]
    assert frames == [1, 2]


def test_load_events_header_aliases(tmp_path):
    event_path = tmp_path / "legacy.csv"
    df = pd.DataFrame({
        "event": ["A", "B"],
        "t (s)": [0.1, 0.2],
        "diameter before": [10, 11],
        "Frame": [1, 2],
    })
    df.to_csv(event_path, index=False)

    labels, times, frames = load_events(str(event_path))

    assert labels == ["A", "B"]
    assert times == [0.1, 0.2]
    assert frames == [1, 2]


def test_load_events_ignore_event_time(tmp_path):
    """Label column should not confuse 'Event Time' for an event label."""
    event_path = tmp_path / "complex.csv"
    df = pd.DataFrame({
        "Event Time": [0.1, 0.2],
        "EventLabel": ["A", "B"],
    })
    df.to_csv(event_path, index=False)

    labels, times, _ = load_events(str(event_path))

    assert labels == ["A", "B"]
    assert times == [0.1, 0.2]


def test_load_events_no_headers(tmp_path):
    event_path = tmp_path / "no_headers.csv"
    pd.DataFrame([["A", 0.1], ["B", 0.2]]).to_csv(event_path, index=False, header=False)

    labels, times, _ = load_events(str(event_path))

    assert labels == ["A", "B"]
    assert times == [0.1, 0.2]


def test_standardize_headers_additional_aliases():
    df = pd.DataFrame({
        "Label": ["A"],
        "Time (s)": [1.0],
        "Diameter": [10],
    })

    std = _standardize_headers(df)

    assert list(std.columns) == ["EventLabel", "Time", "DiamBefore"]


def test_load_events_multiheader(tmp_path):
    event_path = tmp_path / "multi.csv"
    df = pd.DataFrame(
        [["A", 0.1], ["B", 0.2]],
        columns=pd.MultiIndex.from_tuples([("Label", ""), ("Time", "(s)")]),
    )
    df.to_csv(event_path, index=False)

    labels, times, frames = load_events(str(event_path))

    assert labels == ["A", "B"]
    assert times == [0.1, 0.2]
    assert frames is None
