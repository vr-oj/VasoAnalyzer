from __future__ import annotations

import pyqtgraph as pg

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.event_display_mode import EventDisplayMode
from vasoanalyzer.ui.plots.pyqtgraph_event_strip import PyQtGraphEventStripTrack


def _build_strip_track() -> tuple[pg.PlotWidget, PyQtGraphEventStripTrack]:
    widget = pg.PlotWidget()
    widget.resize(800, 60)
    return widget, PyQtGraphEventStripTrack(widget.getPlotItem())


def test_required_height_increases_for_multi_lane_layout(qt_app) -> None:
    widget, strip = _build_strip_track()
    entries = [
        EventEntryV3(t=float(0.5 + (idx * 0.15)), text="WWWWWWWW", index=idx + 1)
        for idx in range(20)
    ]
    options = LayoutOptionsV3(
        mode="h_belt",
        lanes=3,
        min_px=8,
        show_numbers_only=True,
        font_size=20.0,
    )
    requested_heights: list[int] = []
    try:
        strip.set_height_change_callback(lambda value: requested_heights.append(int(value)))
        strip.set_display_mode(EventDisplayMode.INDICES)
        strip.set_events(entries, options)
        strip.refresh_for_view(0.0, 2.0, 1000)
        qt_app.processEvents()
        assert strip.required_height_px > 22
        assert requested_heights
        assert requested_heights[-1] == strip.required_height_px
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()
