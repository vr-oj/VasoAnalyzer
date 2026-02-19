from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QFontMetricsF

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
        assert first.label.toPlainText() == _truncate_event_label(entries[0].text, max_chars=12)
        assert first.label.toPlainText() != "1"
        assert second.label.toPlainText() == "2"
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()


def test_event_strip_label_truncation_policy() -> None:
    assert _truncate_event_label("Short label", max_chars=12) == "Short label"
    assert _truncate_event_label("  Alpha   Beta   Gamma  ", max_chars=12) == "Alpha Bet..."
    assert _truncate_event_label("ABCDEFGHIJKL", max_chars=12) == "ABCDEFGHIJKL"
    assert _truncate_event_label("ABCDEFGHIJKLM", max_chars=12) == "ABCDEFGHI..."
    assert _truncate_event_label("   ", max_chars=12) == ""


def test_event_strip_lod_switches_between_labels_and_markers(qt_app) -> None:
    widget, strip = _build_strip_track()
    options = LayoutOptionsV3(mode="h_belt", lanes=3, min_px=6, show_numbers_only=True)
    try:
        strip.set_display_mode(EventDisplayMode.INDICES)

        sparse_entries = [
            EventEntryV3(t=float(time_s), text=f"Sparse Event {idx + 1}", index=idx + 1)
            for idx, time_s in enumerate(np.linspace(0.0, 10.0, 6))
        ]
        strip.set_events(sparse_entries, options)
        strip.refresh_for_view(0.0, 10.0, 1000)
        qt_app.processEvents()
        sparse_visible_labels = [
            item.label for item in strip._items_by_id.values() if item.label.isVisible()
        ]
        assert sparse_visible_labels

        dense_entries = [
            EventEntryV3(t=float(time_s), text=f"Dense Event {idx + 1}", index=idx + 1)
            for idx, time_s in enumerate(np.linspace(0.0, 10.0, 100))
        ]
        strip.set_events(dense_entries, options)
        strip.refresh_for_view(0.0, 10.0, 120)
        qt_app.processEvents()
        dense_visible_labels = [
            item.label for item in strip._items_by_id.values() if item.label.isVisible()
        ]
        visible_markers = [item.line for item in strip._items_by_id.values() if item.line.isVisible()]
        assert not dense_visible_labels
        assert visible_markers
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
        strip.refresh_for_view(0.0, 10.0, 800)
        qt_app.processEvents()

        visible_labels = []
        for item in strip._items_by_id.values():
            if not item.label.isVisible():
                continue
            label_text = item.label.toPlainText()
            label_pos = item.label.pos()
            visible_labels.append(
                (
                    float(label_pos.x()),
                    round(float(label_pos.y()), 6),
                    label_text,
                )
            )

        assert visible_labels

        def _x_to_px(x_data: float) -> float:
            return (float(x_data) / 10.0) * 800.0

        by_lane: dict[float, list[tuple[float, float]]] = {}
        metrics = getattr(strip, "_font_metrics", None)
        for x_data, lane_key, label_text in visible_labels:
            if metrics is None:
                width_px = max(8.0, float(len(label_text)) * 7.0)
            else:
                assert isinstance(metrics, QFontMetricsF)
                try:
                    width_px = float(metrics.horizontalAdvance(label_text))
                except AttributeError:
                    width_px = float(metrics.width(label_text))
            center_px = _x_to_px(x_data)
            x0 = center_px - (width_px * 0.5)
            x1 = center_px + (width_px * 0.5)
            by_lane.setdefault(lane_key, []).append((x0, x1))

        min_gap_px = float(options.min_px)
        for intervals in by_lane.values():
            intervals.sort(key=lambda pair: pair[0])
            for left, right in zip(intervals, intervals[1:]):
                assert left[1] + min_gap_px <= right[0]
    finally:
        strip.clear()
        widget.close()
        qt_app.processEvents()
