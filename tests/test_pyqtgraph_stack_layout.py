from __future__ import annotations

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.axis_width_sync import AxisWidthSync
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost
from vasoanalyzer.ui.plots.track_frame import TRACK_DIVIDER_THICKNESS_PX, TrackFrame


def _build_host_with_three_tracks() -> PyQtGraphPlotHost:
    df = pd.DataFrame(
        {
            "Time (s)": np.linspace(0.0, 30.0, 301),
            "Inner Diameter": np.linspace(40.0, 50.0, 301),
        }
    )
    model = TraceModel.from_dataframe(df)
    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels(
        [
            ChannelTrackSpec(track_id="a", component="inner", label="A"),
            ChannelTrackSpec(track_id="b", component="inner", label="B"),
            ChannelTrackSpec(track_id="c", component="inner", label="C"),
        ]
    )
    host.set_trace_model(model)
    return host


def test_only_last_visible_track_shows_bottom_axis(qt_app) -> None:
    host = _build_host_with_three_tracks()

    track_a = host.track("a")
    track_b = host.track("b")
    track_c = host.track("c")
    assert track_a is not None
    assert track_b is not None
    assert track_c is not None

    assert track_a.view.bottom_axis_visible() is False
    assert track_b.view.bottom_axis_visible() is False
    assert track_c.view.bottom_axis_visible() is True

    host.set_channel_visible("c", False)

    assert track_a.view.bottom_axis_visible() is False
    assert track_b.view.bottom_axis_visible() is True
    assert track_c.view.bottom_axis_visible() is False

    host.set_channel_visible("b", False)
    assert track_a.view.bottom_axis_visible() is True
    assert track_b.view.bottom_axis_visible() is False
    assert track_c.view.bottom_axis_visible() is False


def test_shared_xlabel_tracks_bottom_visible_channel(qt_app) -> None:
    host = _build_host_with_three_tracks()

    track_a = host.track("a")
    track_b = host.track("b")
    track_c = host.track("c")
    assert track_a is not None
    assert track_b is not None
    assert track_c is not None

    host.set_shared_xlabel("Time (s)")

    axis_a = track_a.view.get_widget().getPlotItem().getAxis("bottom")
    axis_b = track_b.view.get_widget().getPlotItem().getAxis("bottom")
    axis_c = track_c.view.get_widget().getPlotItem().getAxis("bottom")
    assert str(axis_a.labelText or "") == ""
    assert str(axis_b.labelText or "") == ""
    assert str(axis_c.labelText or "") == ""

    host.set_channel_visible("c", False)
    assert str(axis_a.labelText or "") == ""
    assert str(axis_b.labelText or "") == ""
    assert str(axis_c.labelText or "") == ""


def test_tracks_stack_without_vertical_gaps_and_divider_visibility(qt_app) -> None:
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 600)
        widget.show()
        qt_app.processEvents()

        assert host.layout.spacing() == 0
        margins = host.layout.contentsMargins()
        assert margins.left() == 0
        assert margins.top() == 0
        assert margins.right() == 0
        assert margins.bottom() == 0

        track_a = host.track("a")
        track_b = host.track("b")
        track_c = host.track("c")
        assert track_a is not None
        assert track_b is not None
        assert track_c is not None

        frames = [track_a.widget, track_b.widget, track_c.widget]
        for frame in frames:
            frame_layout = frame.layout()
            assert frame_layout is not None
            assert frame_layout.spacing() == 0
            frame_margins = frame_layout.contentsMargins()
            assert frame_margins.left() == 0
            assert frame_margins.top() == 0
            assert frame_margins.right() == 0
            assert frame_margins.bottom() == 0

        for upper, lower in zip(frames, frames[1:]):
            assert upper.geometry().bottom() + 1 == lower.geometry().top()

        assert track_a.divider_visible() is True
        assert track_b.divider_visible() is True
        assert track_c.divider_visible() is False
        assert track_a.widget.divider_thickness() == TRACK_DIVIDER_THICKNESS_PX
    finally:
        widget.close()
        qt_app.processEvents()


def test_channel_track_uses_track_frame_divider(qt_app) -> None:
    track = PyQtGraphChannelTrack(
        ChannelTrackSpec(track_id="inner", component="inner"),
        enable_opengl=False,
    )
    assert isinstance(track.widget, TrackFrame)
    assert track.widget.divider_thickness() == TRACK_DIVIDER_THICKNESS_PX
    track.set_divider_visible(False)
    assert track.divider_visible() is False


def test_channel_viewboxes_use_no_border_pen(qt_app) -> None:
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 600)
        widget.show()
        qt_app.processEvents()
        host.apply_theme()
        qt_app.processEvents()

        for track_id in ("a", "b", "c"):
            track = host.track(track_id)
            assert track is not None
            border_pen = track.view.get_widget().getPlotItem().getViewBox().border
            assert border_pen.style() == Qt.NoPen
    finally:
        widget.close()
        qt_app.processEvents()


def test_all_plot_items_hide_buttons_and_disable_menus(qt_app) -> None:
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 600)
        widget.show()
        qt_app.processEvents()

        for track_id in ("a", "b", "c"):
            track = host.track(track_id)
            assert track is not None
            plot_item = track.view.get_widget().getPlotItem()
            assert bool(getattr(plot_item, "buttonsHidden", False)) is True
            assert bool(plot_item.menuEnabled()) is False
            assert bool(plot_item.getViewBox().menuEnabled()) is False

        strip_track = host._event_strip_track
        assert strip_track is not None
        strip_plot_item = strip_track.plot_item
        assert bool(getattr(strip_plot_item, "buttonsHidden", False)) is True
        assert bool(strip_plot_item.menuEnabled()) is False
        assert bool(strip_plot_item.getViewBox().menuEnabled()) is False
    finally:
        widget.close()
        qt_app.processEvents()


class _FakeRect:
    def __init__(self, width: float) -> None:
        self._width = float(width)

    def width(self) -> float:
        return float(self._width)


class _FakeAxis:
    def __init__(self, natural_width: float) -> None:
        self._width = float(natural_width)
        self.style: dict[str, object] = {}
        self.label = None
        self.applied_widths: list[int] = []

    def isVisible(self) -> bool:
        return True

    def boundingRect(self) -> _FakeRect:
        return _FakeRect(self._width)

    def size(self) -> _FakeRect:
        return _FakeRect(self._width)

    def width(self) -> float:
        return float(self._width)

    def linkedView(self):
        return None

    def setWidth(self, width: int) -> None:
        value = int(width)
        self.applied_widths.append(value)
        self._width = float(value)


def test_axis_width_sync_applies_uniform_width(qt_app) -> None:
    axis_a = _FakeAxis(72.0)
    axis_b = _FakeAxis(45.0)
    sync = AxisWidthSync(
        shrink_delay_s=0.5,
        axis_padding_px=0.0,
        min_axis_width_px=0,
        left_gutter_px=0,
    )

    sync.set_axes([axis_a, axis_b])

    assert axis_a.applied_widths
    assert axis_b.applied_widths
    assert axis_a.applied_widths[-1] == axis_b.applied_widths[-1] == 72


def test_axis_width_sync_applies_sample_text_floor(qt_app) -> None:
    axis = _FakeAxis(24.0)
    sync = AxisWidthSync(
        shrink_delay_s=0.5,
        axis_padding_px=0.0,
        min_axis_width_px=0,
        left_gutter_px=0,
    )
    sync.set_min_from_sample_text("-00:00:00.000", QApplication.font())
    sync.set_axes([axis])
    assert axis.applied_widths
    assert axis.applied_widths[-1] >= 24


def test_axis_width_sync_aligns_waveform_columns_across_tracks(qt_app) -> None:
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 620)
        widget.show()
        qt_app.processEvents()

        track_a = host.track("a")
        track_b = host.track("b")
        track_c = host.track("c")
        assert track_a is not None
        assert track_b is not None
        assert track_c is not None

        track_a.set_ylim(0.0, 1.0)
        track_b.set_ylim(0.0, 150000.0)
        track_c.set_ylim(-0.0015, 0.0015)
        host.refresh_axes_and_fonts(reason="test-waveform-alignment")
        qt_app.processEvents()

        viewbox_lefts: list[int] = []
        for track in (track_a, track_b, track_c):
            rect = track.view._viewbox_rect_in_widget()
            assert rect is not None
            viewbox_lefts.append(int(rect.left()))

        assert max(viewbox_lefts) - min(viewbox_lefts) <= 1
    finally:
        widget.close()
        qt_app.processEvents()


def test_top_event_lane_is_first_item_in_layout(qt_app) -> None:
    """Top lane widget must sit at layout index 0 so it renders above all tracks."""
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 600)
        widget.show()
        qt_app.processEvents()

        assert host._event_top_lane_widget is not None
        layout = host.layout
        first_item = layout.itemAt(0)
        assert first_item is not None
        # Top lane is wrapped in a container (gutter spacer + PlotWidget).
        expected = host._event_top_lane_container or host._event_top_lane_widget
        assert first_item.widget() is expected
    finally:
        widget.close()
        qt_app.processEvents()


def test_top_event_lane_does_not_affect_track_equal_heights(qt_app) -> None:
    """Adding the top lane (stretch=0) must not skew the equal-height channel rows."""
    host = _build_host_with_three_tracks()
    widget = host.get_widget()
    try:
        widget.resize(900, 600)
        widget.show()
        qt_app.processEvents()

        heights: list[int] = []
        for track_id in ("a", "b", "c"):
            track = host.track(track_id)
            assert track is not None
            heights.append(int(track.widget.height()))

        assert heights
        assert max(heights) - min(heights) <= 2
    finally:
        widget.close()
        qt_app.processEvents()
