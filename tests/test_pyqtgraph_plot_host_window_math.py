import numpy as np
import pandas as pd
import pytest

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost


def _build_host() -> PyQtGraphPlotHost:
    df = pd.DataFrame(
        {
            "Time (s)": np.linspace(0.0, 100.0, 1001),
            "Inner Diameter": np.linspace(50.0, 60.0, 1001),
        }
    )
    model = TraceModel.from_dataframe(df)
    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels([ChannelTrackSpec(track_id="inner", component="inner")])
    host.set_trace_model(model)
    return host


def _build_host_two_tracks() -> PyQtGraphPlotHost:
    df = pd.DataFrame(
        {
            "Time (s)": np.linspace(0.0, 100.0, 1001),
            "Inner Diameter": np.linspace(50.0, 60.0, 1001),
        }
    )
    model = TraceModel.from_dataframe(df)
    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels(
        [
            ChannelTrackSpec(track_id="inner_a", component="inner"),
            ChannelTrackSpec(track_id="inner_b", component="inner"),
        ]
    )
    host.set_trace_model(model)
    return host


def test_request_zoom_x_preserves_anchor_ratio(qt_app) -> None:
    host = _build_host()
    host.set_time_window(20.0, 40.0)

    anchor = 25.0
    before = host.current_window()
    assert before is not None
    before_ratio = (anchor - before[0]) / (before[1] - before[0])

    host.request_zoom_x(0.5, anchor, reason="test")
    after = host.current_window()
    assert after is not None
    after_ratio = (anchor - after[0]) / (after[1] - after[0])

    assert after_ratio == pytest.approx(before_ratio, abs=1e-6)


def test_clamp_preserves_duration_at_edges(qt_app) -> None:
    host = _build_host()
    host.set_time_window(80.0, 95.0)

    host.request_pan_x(10.0, reason="test")
    right = host.current_window()
    assert right is not None
    assert right[0] == pytest.approx(85.0, abs=1e-6)
    assert right[1] == pytest.approx(100.0, abs=1e-6)
    assert (right[1] - right[0]) == pytest.approx(15.0, abs=1e-6)

    host.set_time_window(-10.0, 5.0)
    left = host.current_window()
    assert left is not None
    assert left[0] == pytest.approx(0.0, abs=1e-6)
    assert left[1] == pytest.approx(15.0, abs=1e-6)
    assert (left[1] - left[0]) == pytest.approx(15.0, abs=1e-6)


def test_time_compression_target_sets_duration_and_supports_all(qt_app) -> None:
    host = _build_host()
    host.set_time_window(20.0, 40.0)

    host.set_time_compression_target(10.0)
    compressed = host.current_window()
    assert compressed is not None
    assert compressed[0] == pytest.approx(25.0, abs=1e-6)
    assert compressed[1] == pytest.approx(35.0, abs=1e-6)

    host.set_time_compression_target(None)
    full = host.current_window()
    assert full is not None
    assert full[0] == pytest.approx(0.0, abs=1e-6)
    assert full[1] == pytest.approx(100.0, abs=1e-6)


def test_y_actions_preserve_host_owned_x_window(qt_app) -> None:
    host = _build_host()
    host.set_time_window(30.0, 50.0)
    before = host.current_window()
    assert before is not None

    track = host.track("inner")
    assert track is not None
    track.scale_y_about(None, 1.25)
    track.autoscale_y_once()

    after = host.current_window()
    assert after is not None
    assert after[0] == pytest.approx(before[0], abs=1e-6)
    assert after[1] == pytest.approx(before[1], abs=1e-6)


def test_host_navigation_uses_host_writer_without_track_setx_calls(qt_app, monkeypatch) -> None:
    host = _build_host_two_tracks()
    track_a = host.track("inner_a")
    track_b = host.track("inner_b")
    assert track_a is not None
    assert track_b is not None

    set_xlim_calls: list[tuple[str, float, float]] = []
    setxrange_calls: list[tuple[str, float, float, float]] = []
    host_writer_calls: list[tuple[float, float]] = []

    original_host_writer = host._apply_primary_xrange

    def _host_writer_probe(x0: float, x1: float) -> None:
        host_writer_calls.append((float(x0), float(x1)))
        original_host_writer(x0, x1)

    monkeypatch.setattr(host, "_apply_primary_xrange", _host_writer_probe)

    for track in (track_a, track_b):
        view = track.view
        original_set_xlim = view.set_xlim

        def _set_xlim_probe(
            x0: float,
            x1: float,
            *,
            _track_id: str = track.id,
            _original=original_set_xlim,
        ) -> None:
            set_xlim_calls.append((_track_id, float(x0), float(x1)))
            _original(x0, x1)

        monkeypatch.setattr(view, "set_xlim", _set_xlim_probe)

        plot_item = view.get_widget().getPlotItem()
        original_setxrange = plot_item.setXRange

        def _setxrange_probe(
            left: float,
            right: float,
            padding: float = 0.0,
            *,
            _track_id: str = track.id,
            _original=original_setxrange,
        ) -> None:
            setxrange_calls.append((_track_id, float(left), float(right), float(padding)))
            _original(left, right, padding=padding)

        monkeypatch.setattr(plot_item, "setXRange", _setxrange_probe)

    host.set_time_window(30.0, 50.0)
    host.request_pan_x(5.0, reason="test-host-authority-pan")
    host.request_zoom_x(0.5, 45.0, reason="test-host-authority-zoom")
    qt_app.processEvents()

    window = host.current_window()
    assert window is not None
    assert host_writer_calls
    assert not set_xlim_calls
    assert not setxrange_calls
