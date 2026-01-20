from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    load_project,
    save_project,
)
from vasoanalyzer.ui.plots.renderer_factory import create_plot_host
from vasoanalyzer.ui.plots.session_state import (
    apply_session_state_to_plot_host,
    bind_project_dataset_to_plot_host,
)


def _make_trace_df() -> pd.DataFrame:
    t = np.arange(0.0, 101.0, 1.0)
    return pd.DataFrame(
        {
            "Time (s)": t,
            "Inner Diameter": 50.0 + 0.1 * t,
            "Outer Diameter": 60.0 + 0.1 * t,
            "Avg Pressure (mmHg)": 80.0 + 0.05 * t,
            "Set Pressure (mmHg)": 90.0 + 0.0 * t,
        }
    )


def _make_events_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time": [20.0, 50.0],
            "Label": ["A", "B"],
        }
    )


def _save_project(tmp_path: Path, *, with_external_paths: bool) -> str:
    trace_df = _make_trace_df()
    events_df = _make_events_df()

    trace_path = None
    events_path = None
    if with_external_paths:
        trace_path = tmp_path / "trace.csv"
        events_path = tmp_path / "events.csv"
        trace_df.to_csv(trace_path, index=False)
        events_df.to_csv(events_path, index=False)

    sample = SampleN(
        name="SampleA",
        trace_data=trace_df,
        events_data=events_df,
        trace_path=str(trace_path) if trace_path else None,
        events_path=str(events_path) if events_path else None,
    )
    project = Project(name="TestProject", experiments=[Experiment(name="ExpA", samples=[sample])])
    vaso_path = tmp_path / "project.vaso"
    save_project(project, vaso_path.as_posix())
    project.close()
    return vaso_path.as_posix()


def _persist_project_state(vaso_path: str, sample_state: dict) -> int:
    project = load_project(vaso_path)
    try:
        sample = project.experiments[0].samples[0]
        dataset_id = sample.dataset_id
        assert dataset_id is not None
        project.ui_state = {
            "last_experiment": project.experiments[0].name,
            "last_sample": sample.name,
            "last_dataset_id": int(dataset_id),
        }
        sample.ui_state = sample_state
        save_project(project, vaso_path)
        return int(dataset_id)
    finally:
        project.close()


def _plot_host_time_window(plot_host) -> tuple[float, float]:
    window = plot_host.current_window()
    if window is None:
        return (0.0, 0.0)
    return (float(window[0]), float(window[1]))


def test_save_reopen_restores_core_state_nonembedded(tmp_path: Path, qt_app):
    _ = qt_app
    vaso_path = _save_project(tmp_path, with_external_paths=True)

    sample_state = {
        "axis_xlim": (10.0, 40.0),
        "avg_pressure_visible": False,
        "set_pressure_visible": True,
        "inner_trace_visible": True,
        "outer_trace_visible": False,
        "event_lines_visible": True,
        "event_label_mode": "horizontal_outside",
        "event_table_visible": True,
        "snapshot_viewer_visible": False,
    }
    dataset_id = _persist_project_state(vaso_path, sample_state)

    project_reopen = load_project(vaso_path)
    try:
        ui_state = project_reopen.ui_state or {}
        assert ui_state.get("last_dataset_id") == dataset_id

        plot_host = create_plot_host(renderer="matplotlib", dpi=96)
        bound_sample = bind_project_dataset_to_plot_host(
            project_reopen, dataset_id, plot_host
        )
        restored = bound_sample.ui_state or {}

        xlim = restored.get("axis_xlim")
        assert xlim is not None
        assert float(xlim[0]) == pytest.approx(10.0, abs=0.01)
        assert float(xlim[1]) == pytest.approx(40.0, abs=0.01)
        assert restored.get("event_lines_visible") is True
        assert restored.get("event_label_mode") == "horizontal_outside"
        assert restored.get("event_table_visible") is True
        assert restored.get("snapshot_viewer_visible") is False

        apply_session_state_to_plot_host(plot_host, restored)
        x0, x1 = _plot_host_time_window(plot_host)
        assert x0 == pytest.approx(10.0, abs=0.01)
        assert x1 == pytest.approx(40.0, abs=0.01)

        avg_track = plot_host.track("avg_pressure")
        assert avg_track is not None
        assert avg_track.is_visible() is False
        assert getattr(plot_host, "_event_lines_visible", None) is True
    finally:
        project_reopen.close()


def test_save_reopen_restores_minimal_state_embedded(tmp_path: Path, qt_app):
    _ = qt_app
    vaso_path = _save_project(tmp_path, with_external_paths=False)

    sample_state = {
        "axis_xlim": (15.0, 35.0),
        "avg_pressure_visible": False,
    }
    dataset_id = _persist_project_state(vaso_path, sample_state)

    project_reopen = load_project(vaso_path)
    try:
        ui_state = project_reopen.ui_state or {}
        assert ui_state.get("last_dataset_id") == dataset_id

        plot_host = create_plot_host(renderer="matplotlib", dpi=96)
        bound_sample = bind_project_dataset_to_plot_host(
            project_reopen, dataset_id, plot_host
        )
        restored = bound_sample.ui_state or {}

        xlim = restored.get("axis_xlim")
        assert xlim is not None
        assert float(xlim[0]) == pytest.approx(15.0, abs=0.01)
        assert float(xlim[1]) == pytest.approx(35.0, abs=0.01)
        assert restored.get("event_table_visible") is None
        assert restored.get("snapshot_viewer_visible") is None

        apply_session_state_to_plot_host(plot_host, restored)
        x0, x1 = _plot_host_time_window(plot_host)
        assert x0 == pytest.approx(15.0, abs=0.01)
        assert x1 == pytest.approx(35.0, abs=0.01)

        avg_track = plot_host.track("avg_pressure")
        assert avg_track is not None
        assert avg_track.is_visible() is False
    finally:
        project_reopen.close()
