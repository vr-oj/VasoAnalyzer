from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from vasoanalyzer.ui.event_labels_v3 import EventEntryV3, LayoutOptionsV3
from vasoanalyzer.ui.plots.event_display_mode import EventDisplayMode
from vasoanalyzer.ui.plots.pyqtgraph_event_strip import (
    PyQtGraphEventStripTrack,
    _truncate_event_label,
)


def _build_strip_track() -> tuple[pg.PlotWidget, PyQtGraphEventStripTrack]:
    widget = pg.PlotWidget()
    widget.resize(800, 60)
    return widget, PyQtGraphEventStripTrack(widget.getPlotItem())


def test_event_strip_truncates_names_for_labels_lod_and_falls_back_to_index(qt_app) -> None:
    widget, strip = _build_strip_track()
    entries = [
        EventEntryV3(
            t=1.0,
            text="Prolonged Occlusion Response",
            index=1,
        ),
        EventEntryV3(
            t=3.0,
            text="",
            index=2,
        ),
        EventEntryV3(
            t=12.0,
            text="Hidden Event",
            index=3,
        ),
    ]
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)
        strip.set_events(entries, options)
        strip.refresh_for_view(0.0, 5.0, 1000)
        qt_app.processEvents()

        first = strip._items_by_id[1]
        second = strip._items_by_id[2]

        assert first.label.isVisible() is True
        assert second.label.isVisible() is True
        assert first.label.toPlainText() == _truncate_event_label(entries[0].text)
        assert first.label.toPlainText() != "1"
        assert second.label.toPlainText() == "2"
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()


def test_event_strip_label_truncation_policy() -> None:
    assert _truncate_event_label("Short") == "Short"
    assert _truncate_event_label("  Alpha   Beta   Gamma  ") == "Alpha..."
    assert _truncate_event_label("ABCDEFGH") == "ABCDEFGH"
    assert _truncate_event_label("ABCDEFGHI") == "ABCDE..."
    assert _truncate_event_label("   ") == ""


def test_event_strip_lod_switches_between_labels_and_markers(qt_app) -> None:
    widget, strip = _build_strip_track()
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)
        dense_entries = [
            EventEntryV3(t=float(time_s), text=f"Dense Event {idx + 1}", index=idx + 1)
            for idx, time_s in enumerate(np.linspace(0.0, 10.0, 30))
        ]
        strip.set_events(dense_entries, options)
        strip.refresh_for_view(0.0, 10.0, 1000)
        qt_app.processEvents()

        full_range_visible_labels = [
            item.label for item in strip._items_by_id.values() if item.label.isVisible()
        ]
        visible_markers = [item.line for item in strip._items_by_id.values() if item.line.isVisible()]
        assert strip._effective_lod_mode == "markers_only"
        assert not full_range_visible_labels
        assert visible_markers

        strip.refresh_for_view(2.0, 4.0, 1000)
        qt_app.processEvents()
        zoom_visible_labels = [
            item.label for item in strip._items_by_id.values() if item.label.isVisible()
        ]
        assert strip._effective_lod_mode == "labels"
        assert zoom_visible_labels
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()


def test_event_strip_tooltip_includes_full_name_and_time_when_markers_only(qt_app) -> None:
    widget, strip = _build_strip_track()
    entries = [
        EventEntryV3(
            t=float(time_s),
            text=f"Very Long Event Name {idx}",
            index=idx + 1,
        )
        for idx, time_s in enumerate(np.linspace(0.0, 10.0, 60))
    ]
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)
        strip.set_events(entries, options)
        strip.refresh_for_view(0.0, 10.0, 120)
        qt_app.processEvents()

        visible_labels = [
            item.label for item in strip._items_by_id.values() if item.label.isVisible()
        ]
        assert not visible_labels

        sample_entry = entries[9]
        sample_item = strip._items_by_id[int(sample_entry.index or 10)]
        tooltip = sample_item.line.toolTip()
        assert sample_entry.text in tooltip
        assert "Time:" in tooltip
        assert f"{sample_entry.t:.3f} s" in tooltip
        assert sample_item.label.toolTip() == tooltip
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()


def test_event_strip_visible_labels_do_not_overlap_within_each_lane(qt_app) -> None:
    widget, strip = _build_strip_track()
    entries = [
        EventEntryV3(
            t=float(time_s),
            text=f"Collision Label {idx + 1}",
            index=idx + 1,
        )
        for idx, time_s in enumerate(np.linspace(0.0, 10.0, 24))
    ]
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)
        strip.set_events(entries, options)
        strip.refresh_for_view(2.0, 4.0, 800)
        qt_app.processEvents()

        visible_placements = [placement for placement in strip._last_placed if placement.visible]
        assert visible_placements

        by_lane: dict[int, list] = {}
        for placement in visible_placements:
            by_lane.setdefault(int(placement.lane), []).append(placement)

        min_gap_px = max(float(options.min_px), 8.0)
        for lane_placements in by_lane.values():
            lane_placements.sort(key=lambda placement: placement.x_px0)
            for left, right in zip(lane_placements, lane_placements[1:]):
                assert left.x_px1 + min_gap_px <= right.x_px0
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()
