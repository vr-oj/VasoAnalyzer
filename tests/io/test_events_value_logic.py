import pandas as pd

from vasoanalyzer.io.trace_events import load_trace_and_events


def _write_csv(path, df):
    df.to_csv(path, index=False)


def _make_trace_df():
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0, 2.0],
            "Inner Diameter": [100.0, 101.0, 102.0],
            "Outer Diameter": [150.0, 151.0, 152.0],
            "Avg Pressure (mmHg)": [50.0, 50.5, 51.0],
            "Set Pressure (mmHg)": [70.0, 70.5, 71.0],
        }
    )


def test_events_preserve_diam_before_values(tmp_path):
    trace_path = tmp_path / "trace.csv"
    event_path = tmp_path / "trace_table.csv"

    _write_csv(trace_path, _make_trace_df())

    events = pd.DataFrame(
        {
            "EventLabel": ["StimA", "StimB"],
            "Time": [1.0, 2.0],
            "DiamBefore": [123.4, 222.2],
            "OuterDiamBefore": [150.5, 250.5],
        }
    )
    _write_csv(event_path, events)

    (
        _trace_df,
        labels,
        times,
        _frames,
        diam_before,
        od_before,
        extras,
    ) = load_trace_and_events(trace_path.as_posix(), event_path.as_posix())

    assert labels == ["StimA", "StimB"]
    assert times == [1.0, 2.0]
    assert diam_before == [123.4, 222.2]
    assert od_before == [150.5, 250.5]
    assert extras["event_file"] == event_path.as_posix()


def test_events_fallback_to_trace_when_diam_before_missing(tmp_path):
    trace_path = tmp_path / "trace.csv"
    event_path = tmp_path / "trace_table.csv"

    _write_csv(trace_path, _make_trace_df())

    # No DiamBefore columns; loader must sample from trace values.
    events = pd.DataFrame(
        {
            "EventLabel": ["StimA", "StimB"],
            "Time": [0.0, 1.9],  # second event closer to t=2 sample
        }
    )
    _write_csv(event_path, events)

    (
        _trace_df,
        _labels,
        _times,
        _frames,
        diam_before,
        od_before,
        extras,
    ) = load_trace_and_events(trace_path.as_posix(), event_path.as_posix())

    # Should match trace Inner/Outer diameters at nearest time index
    assert diam_before == [100.0, 102.0]
    assert od_before == [150.0, 152.0]
    assert extras["auto_detected"] is False
