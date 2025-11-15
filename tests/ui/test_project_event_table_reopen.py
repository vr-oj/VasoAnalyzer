from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from PyQt5.QtGui import QCloseEvent

from vasoanalyzer.core.project import Experiment, Project, SampleN, save_project
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def _make_trace_df() -> pd.DataFrame:
    times = np.linspace(0.0, 12.0, 480, dtype=float)
    inner = 40.0 + 5.0 * np.sin(times / 3.0)
    outer = 44.0 + 4.0 * np.cos(times / 2.0)
    avg_pressure = 60.0 + 0.5 * np.sin(times / 4.0)
    set_pressure = 70.0 + 0.25 * np.cos(times / 5.0)
    return pd.DataFrame(
        {
            "Time (s)": times,
            "Inner Diameter": inner,
            "Outer Diameter": outer,
            "Avg Pressure (mmHg)": avg_pressure,
            "Set Pressure (mmHg)": set_pressure,
        }
    )


def _make_events(count: int, offset: float) -> pd.DataFrame:
    times = [offset + idx * 0.5 for idx in range(count)]
    return pd.DataFrame(
        {
            "t_seconds": times,
            "label": [f"Event-{offset:.1f}-{idx}" for idx in range(count)],
            "frame": [int(t * 4) for t in times],
        }
    )


def _create_saved_project(tmp_path: Path) -> tuple[Path, list[int]]:
    trace_df = _make_trace_df()
    sample_counts = [5, 6, 7]
    samples: list[SampleN] = []
    for idx, count in enumerate(sample_counts, start=1):
        sample = SampleN(
            name=f"Sample-{idx}",
            trace_data=trace_df.copy(),
            events_data=_make_events(count, offset=idx * 2.5),
        )
        samples.append(sample)
    project = Project(
        name="UI Project",
        experiments=[Experiment(name="Experiment-A", samples=samples)],
        path=str(tmp_path / "ui_event_table.vaso"),
    )
    save_project(project, project.path)
    project.close()
    return Path(project.path), sample_counts


def _wait_for(qapp, predicate, timeout_ms: int = 10000) -> None:
    expiry = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < expiry:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for condition")


def _activate_and_assert(
    window: VasoAnalyzerApp,
    qapp,
    sample: SampleN,
    experiment,
    expected_rows: int,
) -> None:
    window._activate_sample(sample, experiment, ensure_loaded=True)

    def _has_rows() -> bool:
        return len(window.event_table_data) == expected_rows

    _wait_for(qapp, _has_rows)
    model = window.event_table_controller.model
    assert model.rowCount() == expected_rows
    assert window.event_table.isVisible()
    assert window._event_panel_has_data is True


def test_event_table_visible_after_reopen(qapp, tmp_path):
    project_path, counts = _create_saved_project(tmp_path)
    window = VasoAnalyzerApp(check_updates=False)
    window._onboarding_checked = True
    window.autosave_timer.stop()
    window._event_highlight_timer.stop()
    window.show()
    qapp.processEvents()

    try:
        window.open_project_file(project_path.as_posix())

        def _project_ready() -> bool:
            return window.current_project is not None and window.project_ctx is not None

        _wait_for(qapp, _project_ready)
        assert window.current_project is not None
        assert window.project_ctx is not None
        window.show_analysis_workspace()
        qapp.processEvents()
        active_experiments = list(window.current_project.experiments)
        assert active_experiments, "Expected experiments after reopening project"

        sample_pairs: list[tuple[SampleN, Experiment]] = []
        for experiment in active_experiments:
            for sample in experiment.samples:
                sample_pairs.append((sample, experiment))

        assert len(sample_pairs) == len(counts)

        for (sample, experiment), expected_rows in zip(sample_pairs, counts, strict=False):
            _activate_and_assert(window, qapp, sample, experiment, expected_rows)
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_close_event_skips_save_when_clean(qapp, tmp_path, monkeypatch):
    window = VasoAnalyzerApp(check_updates=False)
    window._onboarding_checked = True
    window.autosave_timer.stop()
    window._event_highlight_timer.stop()
    window._deferred_autosave_timer.stop()

    project_path = tmp_path / "skip-close.vaso"
    project_path.write_text("", encoding="utf-8")
    window.current_project = Project(name="Skip", experiments=[], path=project_path.as_posix())
    window.session_dirty = False

    invoked = False

    def fake_save(project, path=None, skip_optimize=False):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr("vasoanalyzer.ui.main_window.save_project_file", fake_save)

    event = QCloseEvent()
    window.closeEvent(event)
    assert invoked is False

    window.deleteLater()
    qapp.processEvents()


def test_view_range_change_marks_dirty(qapp):
    window = VasoAnalyzerApp(check_updates=False)
    window._onboarding_checked = True
    window.autosave_timer.stop()
    window._event_highlight_timer.stop()
    window._deferred_autosave_timer.stop()

    class DummyHost:
        def is_user_range_change_active(self) -> bool:
            return True

        def get_render_backend(self) -> str:
            return "pyqtgraph"

    window.plot_host = DummyHost()
    window.session_dirty = False

    # Avoid heavy UI work during the test
    window.update_scroll_slider = lambda: None
    window._invalidate_sample_state_cache = lambda: None

    window._on_plot_host_time_window_changed(0.0, 1.0)
    assert window.session_dirty is True

    window.deleteLater()
    qapp.processEvents()


def test_scroll_slider_marks_dirty(qapp):
    window = VasoAnalyzerApp(check_updates=False)
    window._onboarding_checked = True
    window.autosave_timer.stop()
    window._event_highlight_timer.stop()
    window._deferred_autosave_timer.stop()

    class AxisStub:
        def __init__(self) -> None:
            self._xlim = (0.0, 2.0)

        def get_xlim(self):
            return self._xlim

        def set_xlim(self, left, right):
            self._xlim = (left, right)
            return self._xlim

    axis = AxisStub()
    window.ax = axis

    class HostStub:
        def __init__(self, stub_axis):
            self._axis = stub_axis

        def primary_axis(self):
            return self._axis

        def set_time_window(self, x0, x1):
            self._axis.set_xlim(x0, x1)

        def get_render_backend(self):
            return "pyqtgraph"

        def is_user_range_change_active(self):
            return False

    window.plot_host = HostStub(axis)
    window.trace_data = pd.DataFrame({"Time (s)": [0.0, 10.0]})
    window.trace_model = None
    window.session_dirty = False

    window.scroll_slider.setValue(500)
    window.scroll_plot()

    assert window.session_dirty is True

    window.deleteLater()
    qapp.processEvents()
