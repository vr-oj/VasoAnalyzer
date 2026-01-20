import numpy as np
import pandas as pd
import pytest

from vasoanalyzer.core.timebase import (
    TIME_EPS_S,
    TimebaseSource,
    resolve_tiff_frame_times,
    resolve_trace_timebase,
    validate_and_normalize_events,
)
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.ui.gif_animator.frame_synchronizer import FrameSynchronizer


def test_schema_variance_trace_timebase_resolution():
    df = pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0, 2.0],
            "Time_s_exact": [0.0, 1.01, 2.02],
            "Inner Diameter": [50.0, 50.1, 50.2],
        }
    )

    result = resolve_trace_timebase(df)

    assert result.source == TimebaseSource.TIME_S_EXACT
    assert result.source_column == "Time_s_exact"
    assert result.time_s[0] == pytest.approx(0.0, abs=TIME_EPS_S)
    assert np.all(np.diff(result.time_s) >= -TIME_EPS_S)


def test_event_clamping_and_flagging():
    trace_time = np.linspace(0.0, 100.0, 101)
    events_df = pd.DataFrame(
        {
            "Time": [-0.02, 100.01, 120.0],
            "EventLabel": ["A", "B", "C"],
        }
    )

    df_norm, report = validate_and_normalize_events(
        events_df, trace_time, range_tol_s=0.05, eps_s=TIME_EPS_S
    )

    assert df_norm.loc[0, "_time_seconds"] == pytest.approx(0.0, abs=TIME_EPS_S)
    assert df_norm.loc[1, "_time_seconds"] == pytest.approx(100.0, abs=TIME_EPS_S)
    assert df_norm.loc[2, "_time_seconds"] == pytest.approx(120.0, abs=TIME_EPS_S)
    assert df_norm.loc[2, "_time_status"] == "out_of_range"
    assert bool(df_norm.loc[2, "_time_valid"]) is False

    assert report.clamped == 2
    assert report.out_of_range == 1


def test_tiff_frame_timing_mapping():
    info = {"n_frames": 50, "frames_metadata": []}
    result = resolve_tiff_frame_times(info, fps=10.0)

    assert len(result.frame_times_s) == 50
    assert result.frame_times_s[0] == pytest.approx(0.0, abs=TIME_EPS_S)
    assert result.frame_times_s[-1] == pytest.approx(4.9, abs=TIME_EPS_S)


def test_end_to_end_trace_events_frame_sync(tmp_path):
    trace_df = pd.DataFrame(
        {
            "Time_s_exact": np.arange(0.0, 10.1, 0.1),
            "Inner Diameter": 50.0 + np.arange(0.0, 10.1, 0.1),
            "TiffPage": np.arange(0, 101, 1),
        }
    )
    events_df = pd.DataFrame({"Time": [1.0, 4.0], "EventLabel": ["A", "B"]})

    trace_path = tmp_path / "trace.csv"
    events_path = tmp_path / "events.csv"
    trace_df.to_csv(trace_path, index=False)
    events_df.to_csv(events_path, index=False)

    df, labels, times, frames, diam, od_diam, extras = load_trace_and_events(
        str(trace_path), str(events_path)
    )

    assert df["Time (s)"].iloc[0] == pytest.approx(0.0, abs=TIME_EPS_S)
    assert labels == ["A", "B"]
    assert times[0] == pytest.approx(1.0, abs=TIME_EPS_S)

    trace_model = TraceModel.from_dataframe(df)
    tiff_map = {
        int(tp): int(i)
        for i, tp in enumerate(pd.to_numeric(df["TiffPage"], errors="coerce").to_numpy())
        if pd.notna(tp)
    }
    frame_result = resolve_tiff_frame_times(
        {"n_frames": 50, "frames_metadata": []},
        trace_time_s=df["Time (s)"].to_numpy(dtype=float),
        tiff_page_to_trace_idx=tiff_map,
        allow_fallback=False,
    )

    synchronizer = FrameSynchronizer(
        frame_result.frame_times_s, trace_model.time_full, 0.0, 4.9
    )
    timing = synchronizer.get_frame_for_time(2.0)
    assert timing.tiff_frame_index == 20
