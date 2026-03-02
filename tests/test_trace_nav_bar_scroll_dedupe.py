from __future__ import annotations

from vasoanalyzer.ui.navigation.trace_nav_bar import TraceNavBar


class _DummyPlotHost:
    def __init__(self) -> None:
        self.window = (0.0, 10.0)
        self.total = (0.0, 100.0)
        self.calls: list[tuple[float, float]] = []

    def get_time_window(self) -> tuple[float, float]:
        return self.window

    def get_total_span(self) -> tuple[float, float]:
        return self.total

    def set_time_window(self, x0: float, x1: float) -> None:
        self.calls.append((float(x0), float(x1)))
        self.window = (float(x0), float(x1))


class _CompressionHost(_DummyPlotHost):
    def __init__(self) -> None:
        super().__init__()
        self.compression_calls: list[float | None] = []

    def set_time_compression_target(self, seconds: float | None) -> None:
        self.compression_calls.append(None if seconds is None else float(seconds))


def test_value_changed_ignored_during_drag_and_release_is_deduped(qt_app) -> None:
    host = _DummyPlotHost()
    nav = TraceNavBar(plot_host=host)
    try:
        nav.refresh_from_host()
        target = max(1, nav.scrollbar.maximum() // 4)

        nav._on_scrollbar_pressed()
        nav.scrollbar.setValue(target)
        nav._on_scrollbar_moved(target)
        assert len(host.calls) == 1

        nav._on_scrollbar_released()
        assert len(host.calls) == 1
    finally:
        nav.close()
        qt_app.processEvents()


def test_time_compression_presets_emit_expected_targets(qt_app) -> None:
    host = _CompressionHost()
    nav = TraceNavBar(plot_host=host)
    try:
        idx_30s = nav.preset_combo.findText("30s")
        assert idx_30s >= 0
        nav._on_preset_selected(idx_30s)
        assert host.compression_calls[-1] == 30.0

        idx_all = nav.preset_combo.findText("All")
        assert idx_all >= 0
        nav._on_preset_selected(idx_all)
        assert host.compression_calls[-1] is None
    finally:
        nav.close()
        qt_app.processEvents()


def test_disabled_state_resets_drag_state(qt_app) -> None:
    host = _DummyPlotHost()
    nav = TraceNavBar(plot_host=host)
    try:
        nav._on_scrollbar_pressed()
        assert nav._scrollbar_dragging is True

        nav._set_disabled_state()
        assert nav._scrollbar_dragging is False
        assert nav._last_applied_scroll_value is None
    finally:
        nav.close()
        qt_app.processEvents()


def test_all_button_tooltip_includes_total_duration(qt_app) -> None:
    host = _DummyPlotHost()
    host.total = (0.0, 5025.0)
    nav = TraceNavBar(plot_host=host)
    try:
        nav.refresh_from_host()
        tooltip = nav.btn_all.toolTip()
        assert tooltip.startswith("All (")
        assert nav._format_seconds(5025.0) in tooltip
    finally:
        nav.close()
        qt_app.processEvents()


def test_single_zoom_authority_hides_nav_zoom_controls(qt_app) -> None:
    host = _DummyPlotHost()
    nav = TraceNavBar(plot_host=host)
    try:
        nav.show()
        qt_app.processEvents()
        nav.set_time_zoom_controls_visible(False)
        qt_app.processEvents()

        assert nav.btn_zoom_out.isVisible() is False
        assert nav.btn_zoom_in.isVisible() is False
        assert nav.btn_all.isVisible() is False
        assert nav.preset_combo.isVisible() is False

        before = list(host.calls)
        nav._zoom_with_center(0.8)
        assert host.calls == before

        idx_10s = nav.preset_combo.findText("10s")
        assert idx_10s >= 0
        nav._on_preset_selected(idx_10s)
        assert host.calls == before
    finally:
        nav.close()
        qt_app.processEvents()
