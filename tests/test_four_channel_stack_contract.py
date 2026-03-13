from __future__ import annotations

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QFrame

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost
from vasoanalyzer.ui.plots.track_frame import TRACK_DIVIDER_THICKNESS_PX


def _build_host_with_four_channels() -> PyQtGraphPlotHost:
    t = np.linspace(0.0, 30.0, 301)
    df = pd.DataFrame(
        {
            "Time (s)": t,
            "Inner Diameter": 45.0 + 0.8 * np.sin(t / 2.0),
            "Outer Diameter": 95.0 + 1.2 * np.cos(t / 3.0),
            "Avg Pressure (mmHg)": 60.0 + 5.0 * np.sin(t / 5.0),
            "Set Pressure (mmHg)": 60.0 + 10.0 * ((t % 8.0) > 4.0).astype(float),
        }
    )
    model = TraceModel.from_dataframe(df)

    host = PyQtGraphPlotHost(enable_opengl=False)
    host.ensure_channels(
        [
            ChannelTrackSpec(track_id="inner", component="inner", label="ID"),
            ChannelTrackSpec(track_id="outer", component="outer", label="OD"),
            ChannelTrackSpec(track_id="avg_pressure", component="avg_pressure", label="Avg P"),
            ChannelTrackSpec(track_id="set_pressure", component="set_pressure", label="Set P"),
        ]
    )
    host.set_trace_model(model)
    return host


def test_four_channel_stack_shows_three_structural_separators(qt_app) -> None:
    host = _build_host_with_four_channels()
    widget = host.get_widget()
    try:
        widget.resize(960, 720)
        widget.show()
        qt_app.processEvents()

        ordered_ids = ("inner", "outer", "avg_pressure", "set_pressure")
        tracks = []
        for track_id in ordered_ids:
            track = host.track(track_id)
            assert track is not None
            assert track.is_visible() is True
            tracks.append(track)

        assert tracks[0].divider_visible() is True
        assert tracks[1].divider_visible() is True
        assert tracks[2].divider_visible() is True
        assert tracks[3].divider_visible() is False

        separator_heights: list[int] = []
        for track in tracks:
            separator = track.widget.findChild(QFrame, "TrackSeparatorBar")
            assert separator is not None
            separator_heights.append(int(separator.height()))

        assert separator_heights[:3] == [TRACK_DIVIDER_THICKNESS_PX] * 3
        assert separator_heights[3] == 0
    finally:
        widget.close()
        qt_app.processEvents()


def test_four_channel_stack_uses_equal_row_heights(qt_app) -> None:
    host = _build_host_with_four_channels()
    widget = host.get_widget()
    try:
        widget.resize(960, 720)
        widget.show()
        qt_app.processEvents()

        ordered_ids = ("inner", "outer", "avg_pressure", "set_pressure")
        heights: list[int] = []
        for track_id in ordered_ids:
            track = host.track(track_id)
            assert track is not None
            assert track.is_visible() is True
            heights.append(int(track.widget.height()))

        assert heights
        assert max(heights) - min(heights) <= 2
    finally:
        widget.close()
        qt_app.processEvents()


def test_four_channel_left_axis_spans_viewbox_height(qt_app) -> None:
    host = _build_host_with_four_channels()
    widget = host.get_widget()
    try:
        widget.resize(960, 720)
        widget.show()
        qt_app.processEvents()

        ordered_ids = ("inner", "outer", "avg_pressure", "set_pressure")
        tolerance_px = 4.0
        for track_id in ordered_ids:
            track = host.track(track_id)
            assert track is not None
            plot_item = track.view.get_widget().getPlotItem()
            left_axis = plot_item.getAxis("left")
            view_box = plot_item.getViewBox()
            axis_rect = left_axis.sceneBoundingRect()
            view_rect = view_box.sceneBoundingRect()
            assert abs(float(axis_rect.top()) - float(view_rect.top())) <= tolerance_px
            assert abs(float(axis_rect.bottom()) - float(view_rect.bottom())) <= tolerance_px
    finally:
        widget.close()
        qt_app.processEvents()
