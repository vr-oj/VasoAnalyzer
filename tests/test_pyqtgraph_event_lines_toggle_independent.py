"""Tests that event lines and top event lane text are independent controls."""
from __future__ import annotations

import numpy as np
import pandas as pd

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.event_display_mode import EventDisplayMode
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost


def _build_host() -> PyQtGraphPlotHost:
    t = np.linspace(0.0, 30.0, 301)
    df = pd.DataFrame({"Time (s)": t, "Inner Diameter": 45.0 + np.sin(t)})
    model = TraceModel.from_dataframe(df)
    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels(
        [
            ChannelTrackSpec(track_id="a", component="inner", label="A"),
            ChannelTrackSpec(track_id="b", component="inner", label="B"),
        ]
    )
    host.set_trace_model(model)
    return host


def _open(host: PyQtGraphPlotHost, qt_app):
    """Show widget and process events, returning the widget."""
    w = host.get_widget()
    w.resize(800, 400)
    w.show()
    qt_app.processEvents()
    return w


def _close(w, qt_app):
    w.close()
    qt_app.processEvents()


def _track_has_events(host: PyQtGraphPlotHost, track_id: str) -> bool:
    """Return True if the marker layer for a track has event items."""
    track = host.track(track_id)
    if track is None:
        return False
    return len(track.view._event_layer._items) > 0


# ---------------------------------------------------------------------------
# set_event_lines_visible
# ---------------------------------------------------------------------------

def test_lines_hidden_top_lane_still_shows_text(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.set_event_lines_visible(False)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is True
        assert not _track_has_events(host, "a")
        assert not _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


def test_lines_visible_true_restores_track_events(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.set_event_lines_visible(False)
        host.set_event_lines_visible(True)
        qt_app.processEvents()
        assert _track_has_events(host, "a")
        assert _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


def test_lines_start_visible_by_default(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        assert host._event_lines_visible is True
        assert _track_has_events(host, "a")
        assert _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


# ---------------------------------------------------------------------------
# use_track_event_lines
# ---------------------------------------------------------------------------

def test_use_track_event_lines_false_clears_track_events(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.use_track_event_lines(False)
        qt_app.processEvents()
        assert not _track_has_events(host, "a")
        assert not _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


def test_use_track_event_lines_false_does_not_hide_top_lane(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.use_track_event_lines(False)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is True
    finally:
        _close(w, qt_app)


def test_use_track_event_lines_true_restores_events(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.use_track_event_lines(False)
        host.use_track_event_lines(True)
        qt_app.processEvents()
        assert _track_has_events(host, "a")
        assert _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


# ---------------------------------------------------------------------------
# Mode OFF hides top lane but is independent of line toggle
# ---------------------------------------------------------------------------

def test_mode_off_hides_top_lane_but_lines_remain_if_visible(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        host.set_event_display_mode(EventDisplayMode.OFF)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is False
        # Lines should still exist in tracks (line visibility is independent)
        assert _track_has_events(host, "a")
        assert _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


def test_lines_invisible_and_mode_off_both_conditions(qt_app) -> None:
    host = _build_host()
    w = _open(host, qt_app)
    try:
        host.set_events([10.0, 20.0], labels=["Ev1", "Ev2"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        host.set_event_lines_visible(False)
        host.set_event_display_mode(EventDisplayMode.OFF)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is False
        assert not _track_has_events(host, "a")
        assert not _track_has_events(host, "b")
    finally:
        _close(w, qt_app)


# ---------------------------------------------------------------------------
# State flags (no widget show needed)
# ---------------------------------------------------------------------------

def test_use_track_event_lines_updates_state_flag(qt_app) -> None:
    host = _build_host()
    host.use_track_event_lines(False)
    assert host._use_track_event_lines is False
    host.use_track_event_lines(True)
    assert host._use_track_event_lines is True


def test_set_event_lines_visible_updates_state_flag(qt_app) -> None:
    host = _build_host()
    host.set_event_lines_visible(False)
    assert host._event_lines_visible is False
    host.set_event_lines_visible(True)
    assert host._event_lines_visible is True
