from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QPointF

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.event_display_mode import EventDisplayMode
from vasoanalyzer.ui.plots.pyqtgraph_event_strip import PyQtGraphEventStripTrack


def _build_strip_track() -> tuple[pg.PlotWidget, PyQtGraphEventStripTrack]:
    widget = pg.PlotWidget()
    widget.resize(800, 60)
    return widget, PyQtGraphEventStripTrack(widget.getPlotItem())


def test_hidden_or_truncated_hover_shows_full_tooltip(qt_app, monkeypatch) -> None:
    widget, strip = _build_strip_track()
    entries = [
        EventEntryV3(t=float(time_s), text=f"Very Long Hidden Label {idx + 1}", index=idx + 1)
        for idx, time_s in enumerate(np.linspace(0.0, 10.0, 60))
    ]
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    captured: dict[str, str] = {}
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)
        strip.set_events(entries, options)
        strip.refresh_for_view(0.0, 10.0, 120)
        qt_app.processEvents()
        time.sleep(0.18)
        strip.refresh_for_view(0.0, 10.0, 120)
        qt_app.processEvents()

        sample = strip._items_by_id[10]
        vb = strip.plot_item.getViewBox()
        vb.setXRange(0.0, 10.0, padding=0.0)
        vb.setYRange(0.0, 1.0, padding=0.0)
        qt_app.processEvents()
        scene_pos = vb.mapViewToScene(QPointF(float(sample.entry.t), 0.5))

        def _capture_show(_pos, text: str) -> None:
            captured["text"] = str(text)

        monkeypatch.setattr("vasoanalyzer.ui.plots.pyqtgraph_event_strip.QToolTip.showText", _capture_show)
        strip._on_mouse_moved(scene_pos)
        assert "Very Long Hidden Label" in captured.get("text", "")
        assert "s" in captured.get("text", "")
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()
