"""TraceNav-style navigation bar for host-driven time window control."""

from __future__ import annotations

import contextlib
import math
from typing import Any

from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QWidget,
)

from vasoanalyzer.ui.formatting.time_format import TimeFormatter, TimeMode, coerce_time_mode
from vasoanalyzer.ui.parity_flags import chart_view_parity_v1_enabled
from vasoanalyzer.ui.theme import CURRENT_THEME


class TraceNavBar(QFrame):
    """Bottom navigation strip with step, compression, presets, and scrollbar pan."""

    timeModeChanged = pyqtSignal(str)
    timeCompressionRequested = pyqtSignal(object)

    _SLIDER_UNITS_PER_SECOND = 1000.0
    _SLIDER_MAX_UNITS = 2_000_000_000
    _PRESETS: tuple[tuple[str, float | None], ...] = (
        ("0.5s", 0.5),
        ("1s", 1.0),
        ("2s", 2.0),
        ("5s", 5.0),
        ("10s", 10.0),
        ("30s", 30.0),
        ("60s", 60.0),
        ("120s", 120.0),
        ("5m", 300.0),
        ("All", None),
    )

    def __init__(self, *, plot_host: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TraceNavBar")
        self._plot_host = plot_host
        self._time_zoom_controls_visible = True
        self._updating_slider = False
        self._scrollbar_dragging = False
        self._last_applied_scroll_value: int | None = None
        self._current_units_per_second = float(self._SLIDER_UNITS_PER_SECOND)
        self._window_listener = self._on_time_window_changed
        self._listener_attached = False
        self._signal_attached = False
        self._time_formatter = TimeFormatter(TimeMode.AUTO)
        self._chart_parity_v1 = chart_view_parity_v1_enabled()

        self._build_ui()
        self.apply_theme()
        self.timeCompressionRequested.connect(self._on_time_compression_requested)
        self._attach_listeners()
        self._sync_time_mode_from_host()
        self.refresh_from_host()

    def set_time_zoom_controls_visible(self, visible: bool) -> None:
        """Show/hide zoom/compression controls on the nav strip.

        When hidden, toolbar actions remain the single authority for zooming.
        """
        desired = bool(visible)
        if desired == self._time_zoom_controls_visible:
            return
        self._time_zoom_controls_visible = desired
        for widget in (
            self.btn_zoom_out,
            self.btn_zoom_in,
            self.preset_combo,
            self.btn_all,
        ):
            widget.setVisible(desired)
            if not desired:
                widget.setEnabled(False)
        self.refresh_from_host()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self.btn_step_left = self._make_button("<", "Step left by one window")
        self.btn_step_right = self._make_button(">", "Step right by one window")
        self.btn_zoom_out = self._make_button("-", "Time compression: show more time")
        self.btn_zoom_in = self._make_button("+", "Time expansion: show less time")
        self.btn_all = self._make_button("All", "Show full recording")
        self.btn_autoscale_all = self._make_button(
            "Auto Y (All)",
            "Autoscale all channels once",
        )

        self.preset_combo = QComboBox(self)
        self.preset_combo.setObjectName("TraceNavPresetCombo")
        for label, seconds in self._PRESETS:
            self.preset_combo.addItem(label, seconds)
        self.preset_combo.setCurrentText("10s")
        self.preset_combo.setToolTip("Time compression presets")
        self.preset_combo.setMinimumWidth(74)

        self.time_mode_combo = QComboBox(self)
        self.time_mode_combo.setObjectName("TraceNavTimeModeCombo")
        self.time_mode_combo.addItem("Auto", TimeMode.AUTO.value)
        self.time_mode_combo.addItem("Seconds", TimeMode.SECONDS.value)
        self.time_mode_combo.addItem("MM:SS", TimeMode.MMSS.value)
        self.time_mode_combo.addItem("HH:MM:SS", TimeMode.HHMMSS.value)
        self.time_mode_combo.setMinimumWidth(94)

        self.scrollbar = QScrollBar(Qt.Horizontal, self)
        self.scrollbar.setObjectName("TraceNavTimeScrollbar")
        self.scrollbar.setMinimum(0)
        self.scrollbar.setMaximum(0)
        self.scrollbar.setSingleStep(1)
        self.scrollbar.setPageStep(1)
        self.scrollbar.setTracking(True)
        self.scrollbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.duration_label = QLabel("Dur --", self)
        self.duration_label.setObjectName("TraceNavDurationLabel")
        self.duration_label.setMinimumWidth(92)
        self.duration_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.view_label = QLabel("View --", self)
        self.view_label.setObjectName("TraceNavViewLabel")
        self.view_label.setMinimumWidth(260)
        self.view_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.view_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.btn_step_left.clicked.connect(lambda: self._step_pages(-1))
        self.btn_step_right.clicked.connect(lambda: self._step_pages(1))
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_with_center(1.25))
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_with_center(0.8))
        self.btn_all.clicked.connect(self._show_all)
        self.btn_autoscale_all.clicked.connect(self._autoscale_all_y_once)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.time_mode_combo.currentIndexChanged.connect(self._on_time_mode_selected)
        self.scrollbar.sliderPressed.connect(self._on_scrollbar_pressed)
        self.scrollbar.sliderReleased.connect(self._on_scrollbar_released)
        self.scrollbar.sliderMoved.connect(self._on_scrollbar_moved)
        self.scrollbar.valueChanged.connect(self._on_scrollbar_value_changed)
        self._apply_logical_control_sizes()

        layout.addWidget(self.btn_step_left)
        layout.addWidget(self.btn_step_right)
        layout.addWidget(self.btn_zoom_out)
        layout.addWidget(self.btn_zoom_in)
        layout.addWidget(self.preset_combo)
        layout.addWidget(self.time_mode_combo)
        layout.addWidget(self.btn_all)
        layout.addWidget(self.scrollbar, 1)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.view_label)
        layout.addWidget(self.btn_autoscale_all)

    def _current_dpr(self) -> float:
        with contextlib.suppress(Exception):
            window = self.window()
            if window is not None:
                handle = window.windowHandle()
                if handle is not None and handle.screen() is not None:
                    ratio = float(handle.screen().devicePixelRatio())
                    if ratio > 0.0:
                        return ratio
        app = QApplication.instance()
        if app is not None:
            with contextlib.suppress(Exception):
                screen = app.primaryScreen()
                if screen is not None:
                    ratio = float(screen.devicePixelRatio())
                    if ratio > 0.0:
                        return ratio
        return 1.0

    def _logical_size(self, base_px: int) -> int:
        factor = min(max(self._current_dpr(), 1.0), 1.5)
        return max(int(round(float(base_px) * factor)), 1)

    def _apply_logical_control_sizes(self) -> None:
        button_h = self._logical_size(24)
        for button in (
            self.btn_step_left,
            self.btn_step_right,
            self.btn_zoom_out,
            self.btn_zoom_in,
            self.btn_all,
            self.btn_autoscale_all,
        ):
            button.setMinimumHeight(button_h)
            button.setMinimumWidth(self._logical_size(24))
        self.preset_combo.setMinimumHeight(button_h)
        self.time_mode_combo.setMinimumHeight(button_h)
        self.scrollbar.setFixedHeight(max(self._logical_size(14), 12))

    def _make_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setToolTip(tooltip)
        button.setObjectName("TraceNavButton")
        return button

    def _units_per_second(self, total_span_seconds: float) -> float:
        """Pick an integer-safe units/second scale for the current dataset span."""
        if not math.isfinite(total_span_seconds) or total_span_seconds <= 0.0:
            return float(self._SLIDER_UNITS_PER_SECOND)
        max_units = float(self._SLIDER_MAX_UNITS)
        for candidate in (float(self._SLIDER_UNITS_PER_SECOND), 100.0, 10.0, 1.0):
            if total_span_seconds * candidate <= max_units:
                return candidate
        return max(1.0, math.floor(max_units / total_span_seconds))

    def _s_to_u(self, seconds: float, *, units_per_second: float | None = None) -> int:
        """Convert seconds to stable integer scrollbar units."""
        if not math.isfinite(seconds):
            return 0
        ups = float(units_per_second or self._SLIDER_UNITS_PER_SECOND)
        return int(round(float(seconds) * ups))

    def _u_to_s(self, units: int, *, units_per_second: float | None = None) -> float:
        """Convert integer scrollbar units back to seconds."""
        ups = float(units_per_second or self._SLIDER_UNITS_PER_SECOND)
        return float(units) / ups

    def _attach_listeners(self) -> None:
        if hasattr(self._plot_host, "add_time_window_listener"):
            with contextlib.suppress(Exception):
                self._plot_host.add_time_window_listener(self._window_listener)
                self._listener_attached = True
        signal = getattr(self._plot_host, "time_window_changed", None)
        if not self._listener_attached and signal is not None and hasattr(signal, "connect"):
            with contextlib.suppress(Exception):
                signal.connect(self._on_time_window_changed)
                self._signal_attached = True

    def _detach_listeners(self) -> None:
        if self._listener_attached and hasattr(self._plot_host, "remove_time_window_listener"):
            with contextlib.suppress(Exception):
                self._plot_host.remove_time_window_listener(self._window_listener)
        self._listener_attached = False
        signal = getattr(self._plot_host, "time_window_changed", None)
        if self._signal_attached and signal is not None and hasattr(signal, "disconnect"):
            with contextlib.suppress(Exception):
                signal.disconnect(self._on_time_window_changed)
        self._signal_attached = False

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._detach_listeners()
        super().closeEvent(event)

    def apply_theme(self) -> None:
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#D0D0D0"))
        text = CURRENT_THEME.get("text", "#000000")
        status_text = CURRENT_THEME.get("text_disabled", text)
        button_bg = CURRENT_THEME.get("button_bg", bg)
        button_hover = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active = CURRENT_THEME.get("button_active_bg", button_hover)
        selection = CURRENT_THEME.get("selection_bg", button_hover)
        radius = int(CURRENT_THEME.get("panel_radius", 4))
        self.setStyleSheet(
            f"""
QFrame#TraceNavBar {{
    background: {bg};
    border: 1px solid {border};
    border-radius: {radius}px;
}}
QPushButton#TraceNavButton {{
    background: {button_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 1px 7px;
    font-weight: 500;
}}
QPushButton#TraceNavButton:hover {{
    background: {button_hover};
}}
QPushButton#TraceNavButton:pressed {{
    background: {button_active};
}}
QPushButton#TraceNavButton:disabled {{
    color: {status_text};
}}
QComboBox#TraceNavPresetCombo,
QComboBox#TraceNavTimeModeCombo {{
    background: {button_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius}px;
    padding: 1px 6px;
}}
QComboBox#TraceNavPresetCombo:hover,
QComboBox#TraceNavTimeModeCombo:hover {{
    background: {button_hover};
}}
QComboBox#TraceNavPresetCombo QAbstractItemView,
QComboBox#TraceNavTimeModeCombo QAbstractItemView {{
    background: {bg};
    color: {text};
    selection-background-color: {selection};
}}
QScrollBar#TraceNavTimeScrollbar:horizontal {{
    height: 14px;
    border: 1px solid {border};
    border-radius: 6px;
    background: {button_bg};
}}
QScrollBar#TraceNavTimeScrollbar::handle:horizontal {{
    background: {selection};
    border: 1px solid {border};
    border-radius: 5px;
    min-width: 26px;
}}
QScrollBar#TraceNavTimeScrollbar::add-line:horizontal,
QScrollBar#TraceNavTimeScrollbar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar#TraceNavTimeScrollbar::add-page:horizontal,
QScrollBar#TraceNavTimeScrollbar::sub-page:horizontal {{
    background: transparent;
}}
QLabel#TraceNavDurationLabel, QLabel#TraceNavViewLabel {{
    color: {text};
    font-size: 9.5pt;
    font-weight: 500;
}}
"""
        )

    def _on_time_window_changed(self, *_args) -> None:
        self._sync_time_mode_from_host()
        self.refresh_from_host()

    def refresh_from_host(self) -> None:
        window = self._get_time_window()
        total = self._get_total_span()
        if window is None or total is None:
            self._set_disabled_state()
            return

        t0, t1 = window
        total_min, total_max = total
        if not (
            math.isfinite(t0)
            and math.isfinite(t1)
            and math.isfinite(total_min)
            and math.isfinite(total_max)
        ):
            self._set_disabled_state()
            return
        total_span = max(total_max - total_min, 0.0)
        duration = max(t1 - t0, 0.0)
        units_per_second = self._units_per_second(total_span)
        self._current_units_per_second = units_per_second

        self.duration_label.setText(f"Dur {self._format_seconds(duration)}")
        self.view_label.setText(
            f"View {self._format_seconds(t0)} - {self._format_seconds(t1)} / {self._format_seconds(total_span)}"
        )
        self.btn_all.setToolTip(f"All ({self._format_seconds(total_span)})")

        travel = max(total_span - duration, 0.0)
        slider_max = max(0, self._s_to_u(travel, units_per_second=units_per_second))
        slider_page = max(1, self._s_to_u(duration, units_per_second=units_per_second))
        slider_val = self._s_to_u(
            max(0.0, min(t0 - total_min, travel)),
            units_per_second=units_per_second,
        )
        slider_val = max(0, min(slider_val, slider_max))

        self._updating_slider = True
        blocker = QSignalBlocker(self.scrollbar)
        try:
            self.scrollbar.setRange(0, slider_max)
            self.scrollbar.setPageStep(slider_page)
            self.scrollbar.setSingleStep(max(1, slider_page // 20))
            self.scrollbar.setValue(slider_val)
        finally:
            del blocker
            self._updating_slider = False
        self._last_applied_scroll_value = int(slider_val)

        enabled = total_span > 0.0
        self.scrollbar.setEnabled(enabled and travel > 0.0)
        self._update_autoscale_button_hint()
        for widget in (
            self.btn_step_left,
            self.btn_step_right,
            self.time_mode_combo,
            self.btn_autoscale_all,
        ):
            widget.setEnabled(enabled)
        if self._time_zoom_controls_visible:
            for widget in (
                self.btn_zoom_out,
                self.btn_zoom_in,
                self.btn_all,
                self.preset_combo,
            ):
                widget.setEnabled(enabled)

    def _set_disabled_state(self) -> None:
        self.duration_label.setText("Dur --")
        self.view_label.setText("View --")
        self.btn_all.setToolTip("Show full recording")
        self._scrollbar_dragging = False
        self._updating_slider = True
        blocker = QSignalBlocker(self.scrollbar)
        try:
            self.scrollbar.setRange(0, 0)
            self.scrollbar.setValue(0)
        finally:
            del blocker
            self._updating_slider = False
        self._current_units_per_second = float(self._SLIDER_UNITS_PER_SECOND)
        self._last_applied_scroll_value = None
        for widget in (
            self.scrollbar,
            self.btn_step_left,
            self.btn_step_right,
            self.btn_zoom_out,
            self.btn_zoom_in,
            self.btn_all,
            self.preset_combo,
            self.time_mode_combo,
            self.btn_autoscale_all,
        ):
            widget.setEnabled(False)

    def _sync_time_mode_from_host(self) -> None:
        getter = getattr(self._plot_host, "time_mode", None)
        if not callable(getter):
            return
        with contextlib.suppress(Exception):
            mode = coerce_time_mode(getter())
            self.set_time_mode(mode, emit_signal=False)

    def set_time_mode(self, mode: TimeMode | str, *, emit_signal: bool = False) -> None:
        resolved = coerce_time_mode(mode)
        self._time_formatter.set_mode(resolved)
        idx = self.time_mode_combo.findData(resolved.value)
        if idx >= 0 and self.time_mode_combo.currentIndex() != idx:
            blocker = QSignalBlocker(self.time_mode_combo)
            try:
                self.time_mode_combo.setCurrentIndex(idx)
            finally:
                del blocker
        if emit_signal:
            self.timeModeChanged.emit(resolved.value)

    def _on_time_mode_selected(self, index: int) -> None:
        if index < 0:
            return
        mode = coerce_time_mode(self.time_mode_combo.itemData(index))
        self.set_time_mode(mode, emit_signal=False)
        setter = getattr(self._plot_host, "set_time_mode", None)
        if callable(setter):
            with contextlib.suppress(Exception):
                setter(mode.value)
        self.timeModeChanged.emit(mode.value)
        self.refresh_from_host()

    def _update_autoscale_button_hint(self) -> None:
        track_count = None
        getter = getattr(self._plot_host, "visible_track_count", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                track_count = int(getter())
        self.btn_autoscale_all.setText("Auto Y (All)")
        if track_count is None:
            self.btn_autoscale_all.setToolTip("Autoscale all visible channels once")
        else:
            self.btn_autoscale_all.setToolTip(
                f"Autoscale all visible channels once ({track_count} tracks)"
            )

    def _get_time_window(self) -> tuple[float, float] | None:
        getter = getattr(self._plot_host, "get_time_window", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                window = getter()
                if window is not None:
                    return float(window[0]), float(window[1])
        getter = getattr(self._plot_host, "current_window", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                window = getter()
                if window is not None:
                    return float(window[0]), float(window[1])
        return None

    def _get_total_span(self) -> tuple[float, float] | None:
        getter = getattr(self._plot_host, "get_total_span", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                t0, t1 = getter()
                if t0 is not None and t1 is not None:
                    return float(t0), float(t1)
        getter = getattr(self._plot_host, "full_range", None)
        if callable(getter):
            with contextlib.suppress(Exception):
                full = getter()
                if full is not None:
                    return float(full[0]), float(full[1])
        return None

    def _set_time_window(self, x0: float, x1: float) -> None:
        setter = getattr(self._plot_host, "set_time_window", None)
        if callable(setter):
            with contextlib.suppress(Exception):
                setter(float(x0), float(x1))

    def _on_scrollbar_moved(self, value: int) -> None:
        if self._updating_slider:
            return
        if self._scrollbar_dragging:
            self._apply_scroll_value(int(value))

    def _on_scrollbar_value_changed(self, value: int) -> None:
        if self._updating_slider:
            return
        if self._scrollbar_dragging:
            return
        self._apply_scroll_value(int(value))

    def _on_scrollbar_pressed(self) -> None:
        self._scrollbar_dragging = True
        self._last_applied_scroll_value = int(self.scrollbar.value())

    def _on_scrollbar_released(self) -> None:
        self._scrollbar_dragging = False
        if self._updating_slider:
            return
        current_value = int(self.scrollbar.value())
        if self._last_applied_scroll_value == current_value:
            return
        self._apply_scroll_value(current_value)

    def _apply_scroll_value(self, value: int) -> None:
        if self._updating_slider:
            return
        window = self._get_time_window()
        total = self._get_total_span()
        if window is None or total is None:
            return
        t0, t1 = window
        total_min, total_max = total
        if not (
            math.isfinite(t0)
            and math.isfinite(t1)
            and math.isfinite(total_min)
            and math.isfinite(total_max)
        ):
            return
        duration = max(t1 - t0, 0.0)
        total_span = max(total_max - total_min, 0.0)
        travel = max(total_span - duration, 0.0)
        if duration <= 0.0 or total_span <= 0.0:
            return

        units_per_second = float(
            self._current_units_per_second or self._units_per_second(total_span)
        )
        start = total_min + self._u_to_s(int(value), units_per_second=units_per_second)
        start = max(total_min, min(start, total_min + travel))
        end = start + duration
        self._set_time_window(start, end)
        applied_value = self._s_to_u(start - total_min, units_per_second=units_per_second)
        self._last_applied_scroll_value = int(applied_value)

    def _step_pages(self, direction: int) -> None:
        window = self._get_time_window()
        if window is None:
            return
        x0, x1 = window
        shift = (x1 - x0) * float(direction)
        self._set_time_window(x0 + shift, x1 + shift)

    def _zoom_with_center(self, factor: float) -> None:
        if not self._time_zoom_controls_visible:
            return
        window = self._get_time_window()
        if window is None:
            return
        x0, x1 = window
        anchor = 0.5 * (x0 + x1)
        request_zoom = getattr(self._plot_host, "request_zoom_x", None)
        if callable(request_zoom):
            with contextlib.suppress(Exception):
                request_zoom(float(factor), float(anchor), "trace_nav")
                return
        duration = max((x1 - x0) * float(factor), 1e-9)
        self._set_time_window(anchor - duration * 0.5, anchor + duration * 0.5)

    def _on_preset_selected(self, index: int) -> None:
        if not self._time_zoom_controls_visible:
            return
        if index < 0:
            return
        duration = self.preset_combo.itemData(index)
        if self._chart_parity_v1:
            target = None if duration is None else float(duration)
            self.timeCompressionRequested.emit(target)
            return
        self._apply_duration_target_legacy(duration)

    def _apply_duration_target_legacy(self, duration: float | None) -> None:
        if duration is None:
            self._show_all_legacy()
            return
        window = self._get_time_window()
        total = self._get_total_span()
        if window is None or total is None:
            return
        x0, x1 = window
        total_min, total_max = total
        target_duration = max(float(duration), 1e-9)
        center = 0.5 * (x0 + x1)
        new_x0 = center - target_duration * 0.5
        new_x1 = center + target_duration * 0.5
        if new_x0 < total_min:
            new_x0 = total_min
            new_x1 = new_x0 + target_duration
        if new_x1 > total_max:
            new_x1 = total_max
            new_x0 = new_x1 - target_duration
        self._set_time_window(new_x0, new_x1)

    def _show_all(self) -> None:
        if not self._time_zoom_controls_visible:
            return
        if self._chart_parity_v1:
            self.timeCompressionRequested.emit(None)
            return
        self._show_all_legacy()

    def _show_all_legacy(self) -> None:
        full = self._get_total_span()
        if full is None:
            return
        self._set_time_window(full[0], full[1])

    def _on_time_compression_requested(self, seconds: object) -> None:
        target: float | None
        if seconds is None:
            target = None
        else:
            try:
                target = float(seconds)
            except (TypeError, ValueError):
                return

        setter = getattr(self._plot_host, "set_time_compression_target", None)
        if callable(setter):
            with contextlib.suppress(Exception):
                setter(target)
                return
        self._apply_duration_target_legacy(target)

    def _autoscale_all_y_once(self) -> None:
        method = getattr(self._plot_host, "autoscale_all_y_once", None)
        if callable(method):
            with contextlib.suppress(Exception):
                method()
                return
        fallback = getattr(self._plot_host, "autoscale_all", None)
        if callable(fallback):
            with contextlib.suppress(Exception):
                fallback()

    def _format_seconds(self, value: float) -> str:
        if not math.isfinite(value):
            return "--"
        return self._time_formatter.format(float(value))
