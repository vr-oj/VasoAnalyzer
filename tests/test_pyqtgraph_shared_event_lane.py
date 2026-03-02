"""Tests for the shared top event lane in PyQtGraphPlotHost."""
from __future__ import annotations

import numpy as np
import pandas as pd

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.event_display_mode import EventDisplayMode
from vasoanalyzer.ui.plots.pyqtgraph_event_strip import PyQtGraphEventStripTrack
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost


def _build_host(n_tracks: int = 2) -> PyQtGraphPlotHost:
    t = np.linspace(0.0, 30.0, 301)
    df = pd.DataFrame({"Time (s)": t, "Inner Diameter": 45.0 + np.sin(t)})
    model = TraceModel.from_dataframe(df)
    host = PyQtGraphPlotHost(enable_opengl=False)
    specs = [
        ChannelTrackSpec(track_id=f"ch{i}", component="inner", label=f"Ch{i}")
        for i in range(n_tracks)
    ]
    host.ensure_channels(specs)
    host.set_trace_model(model)
    return host


# ---------------------------------------------------------------------------
# Top lane instance
# ---------------------------------------------------------------------------

def test_top_lane_created_after_ensure_channels(qt_app) -> None:
    host = _build_host()
    assert host._event_top_lane_widget is not None
    assert host._event_top_lane_track is not None


def test_top_lane_track_is_event_strip_track(qt_app) -> None:
    host = _build_host()
    assert isinstance(host._event_top_lane_track, PyQtGraphEventStripTrack)


# ---------------------------------------------------------------------------
# Layout position
# ---------------------------------------------------------------------------

def test_top_lane_position_before_first_channel_track(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()

        layout = host.layout
        assert layout.count() >= 3  # top lane + 2 tracks (+ optional strip)
        first_item = layout.itemAt(0)
        assert first_item is not None
        # The top lane is now wrapped in a container (gutter spacer + PlotWidget).
        # The container (or the PlotWidget directly if no container) is at index 0.
        expected = host._event_top_lane_container or host._event_top_lane_widget
        assert first_item.widget() is expected
    finally:
        widget.close()
        qt_app.processEvents()


# ---------------------------------------------------------------------------
# Visibility matrix
# ---------------------------------------------------------------------------

def test_top_lane_visible_when_events_and_mode_not_off(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0, 20.0], labels=["A", "B"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is True
    finally:
        widget.close()
        qt_app.processEvents()


def test_top_lane_hidden_when_mode_off(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0], labels=["A"])
        host.set_event_display_mode(EventDisplayMode.OFF)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is False
    finally:
        widget.close()
        qt_app.processEvents()


def test_top_lane_hidden_when_no_events(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([], labels=[])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is False
    finally:
        widget.close()
        qt_app.processEvents()


def test_top_lane_hidden_initially_before_events(qt_app) -> None:
    host = _build_host()
    # Before any set_events call the top lane should start hidden (height 0)
    assert host._event_top_lane_widget is not None
    assert host._event_top_lane_widget.isVisible() is False


def test_top_lane_visible_with_indices_mode(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([5.0, 15.0], labels=["X", "Y"])
        host.set_event_display_mode(EventDisplayMode.INDICES)
        qt_app.processEvents()
        assert host._event_top_lane_widget is not None
        assert host._event_top_lane_widget.isVisible() is True
    finally:
        widget.close()
        qt_app.processEvents()


# ---------------------------------------------------------------------------
# Selection sync
# ---------------------------------------------------------------------------

def test_selected_event_synced_to_top_lane(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0, 20.0], labels=["A", "B"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.set_selected_event_index(0)
        qt_app.processEvents()
        assert host._event_top_lane_track is not None
        assert host._event_top_lane_track._selected_event_id is not None
    finally:
        widget.close()
        qt_app.processEvents()


def test_selected_event_cleared_when_none(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0], labels=["A"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host.set_selected_event_index(0)
        host.set_selected_event_index(None)
        qt_app.processEvents()
        assert host._event_top_lane_track is not None
        assert host._event_top_lane_track._selected_event_id is None
    finally:
        widget.close()
        qt_app.processEvents()


# ---------------------------------------------------------------------------
# Hover sync
# ---------------------------------------------------------------------------

def test_hover_event_propagates_to_top_lane(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0, 20.0], labels=["A", "B"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host._on_track_event_hover(1)
        qt_app.processEvents()
        assert host._event_top_lane_track is not None
        assert host._event_top_lane_track._hovered_event_id is not None
    finally:
        widget.close()
        qt_app.processEvents()


def test_hover_clear_propagates_to_top_lane(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_events([10.0], labels=["A"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        host._on_track_event_hover(0)
        host._on_track_event_hover(None)
        qt_app.processEvents()
        assert host._event_top_lane_track is not None
        assert host._event_top_lane_track._hovered_event_id is None
    finally:
        widget.close()
        qt_app.processEvents()


# ---------------------------------------------------------------------------
# Legacy footer strip unaffected
# ---------------------------------------------------------------------------

def test_footer_strip_still_visible_when_shared_time_axis_enabled(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        host.set_shared_time_axis_footer_enabled(True)
        host.set_events([10.0], labels=["A"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        assert host._event_strip_widget is not None
        assert host._event_strip_widget.isVisible() is True
    finally:
        widget.close()
        qt_app.processEvents()


def test_footer_strip_hidden_in_default_top_lane_mode_with_no_footer(qt_app) -> None:
    host = _build_host()
    widget = host.get_widget()
    try:
        widget.resize(800, 400)
        widget.show()
        qt_app.processEvents()
        assert not host._shared_time_axis_footer_enabled
        host.set_events([10.0], labels=["A"])
        host.set_event_display_mode(EventDisplayMode.NAMES_ALWAYS)
        qt_app.processEvents()
        assert host._event_strip_widget is not None
        # Strip hidden; top lane handles labels in default mode
        assert host._event_strip_widget.isVisible() is False
    finally:
        widget.close()
        qt_app.processEvents()
