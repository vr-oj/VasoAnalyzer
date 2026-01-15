"""Professional navigation bar for trace time-window control."""

from __future__ import annotations

import math

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from vasoanalyzer.ui.theme import CURRENT_THEME


class ProfessionalNavigationBar(QFrame):
    """Compact navigation controls for time-range awareness and stepping."""

    timeWindowRequested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TraceNavBar")
        self._current_window: tuple[float, float] | None = None
        self._full_range: tuple[float, float] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self._position_label = QLabel("Pos: -- / --", self)
        self._position_label.setObjectName("TraceNavPosition")

        self._scale_label = QLabel("View: --", self)
        self._scale_label.setObjectName("TraceNavScale")

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(6)

        self._step_left = self._make_button("<", "Step left one window")
        self._step_right = self._make_button(">", "Step right one window")
        self._zoom_out = self._make_button("-", "Zoom out (2x)")
        self._zoom_in = self._make_button("+", "Zoom in (2x)")

        self._preset_1s = self._make_button("1s", "Set view to 1 second")
        self._preset_10s = self._make_button("10s", "Set view to 10 seconds")
        self._preset_60s = self._make_button("60s", "Set view to 60 seconds")
        self._preset_all = self._make_button("All", "Show full recording")

        self._step_left.clicked.connect(lambda: self._step_by(-1))
        self._step_right.clicked.connect(lambda: self._step_by(1))
        self._zoom_out.clicked.connect(lambda: self._zoom_by(2.0))
        self._zoom_in.clicked.connect(lambda: self._zoom_by(0.5))

        self._preset_1s.clicked.connect(lambda: self._apply_preset(1.0))
        self._preset_10s.clicked.connect(lambda: self._apply_preset(10.0))
        self._preset_60s.clicked.connect(lambda: self._apply_preset(60.0))
        self._preset_all.clicked.connect(self._apply_full_range)

        for btn in (
            self._step_left,
            self._step_right,
            self._zoom_out,
            self._zoom_in,
            self._preset_1s,
            self._preset_10s,
            self._preset_60s,
            self._preset_all,
        ):
            buttons_layout.addWidget(btn)

        layout.addWidget(self._position_label)
        layout.addStretch(1)
        layout.addLayout(buttons_layout)
        layout.addStretch(1)
        layout.addWidget(self._scale_label)

        self.apply_theme()

    def _make_button(self, text: str, tooltip: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(False)
        btn.setCursor(self.cursor())
        return btn

    def apply_theme(self) -> None:
        bg = CURRENT_THEME.get("plot_bg", CURRENT_THEME.get("table_bg", "#FFFFFF"))
        border = CURRENT_THEME.get("grid_color", "#D0D0D0")
        text = CURRENT_THEME.get("text", "#000000")
        button_bg = CURRENT_THEME.get("button_bg", bg)
        button_hover = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active = CURRENT_THEME.get("button_active_bg", button_hover)
        self.setStyleSheet(
            f"""
QFrame#TraceNavBar {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 10px;
}}
QLabel {{
    color: {text};
    font-size: 12px;
    font-weight: 600;
}}
QToolButton {{
    background: {button_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 2px 8px;
    font-weight: 600;
}}
QToolButton:hover {{
    background: {button_hover};
}}
QToolButton:pressed {{
    background: {button_active};
}}
"""
        )

    def set_full_range(self, start: float | None, end: float | None) -> None:
        if start is None or end is None:
            self._full_range = None
        else:
            self._full_range = (float(start), float(end))
        self._update_labels()

    def set_time_window(self, x0: float | None, x1: float | None) -> None:
        if x0 is None or x1 is None:
            self._current_window = None
        else:
            self._current_window = (float(x0), float(x1))
        self._update_labels()

    def _update_labels(self) -> None:
        if self._current_window is None or self._full_range is None:
            self._position_label.setText("Pos: -- / --")
            self._scale_label.setText("View: --")
            return

        x0, x1 = self._current_window
        fr0, fr1 = self._full_range
        total = max(fr1 - fr0, 0.0)
        center = 0.5 * (x0 + x1)
        span = max(x1 - x0, 0.0)
        self._position_label.setText(
            f"Pos: {self._format_time(center)} / {self._format_time(total)}"
        )
        self._scale_label.setText(f"View: {self._format_span(span)}")

    def _format_time(self, seconds: float) -> str:
        if not math.isfinite(seconds):
            return "--"
        sign = "-" if seconds < 0 else ""
        seconds = abs(float(seconds))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        if hours > 0:
            return f"{sign}{hours:02d}:{minutes:02d}:{secs:05.2f}"
        if minutes > 0:
            return f"{sign}{minutes:02d}:{secs:05.2f}"
        return f"{sign}{secs:.2f}s"

    def _format_span(self, seconds: float) -> str:
        if not math.isfinite(seconds):
            return "--"
        seconds = max(float(seconds), 0.0)
        if seconds >= 60.0:
            minutes = int(seconds // 60)
            secs = seconds % 60
            if minutes >= 60:
                hours = minutes // 60
                minutes = minutes % 60
                return f"{hours:02d}:{minutes:02d}:{secs:04.1f}"
            return f"{minutes:02d}:{secs:04.1f}"
        return f"{seconds:.2f}s"

    def _step_by(self, direction: int) -> None:
        if self._current_window is None:
            return
        x0, x1 = self._current_window
        span = x1 - x0
        if span <= 0:
            return
        shift = span * float(direction)
        self._request_window(x0 + shift, x1 + shift)

    def _zoom_by(self, factor: float) -> None:
        if self._current_window is None:
            return
        x0, x1 = self._current_window
        center = 0.5 * (x0 + x1)
        span = max((x1 - x0) * factor, 1e-9)
        self._request_window(center - span * 0.5, center + span * 0.5)

    def _apply_preset(self, span: float) -> None:
        if self._current_window is None:
            return
        center = 0.5 * (self._current_window[0] + self._current_window[1])
        self._request_window(center - span * 0.5, center + span * 0.5)

    def _apply_full_range(self) -> None:
        if self._full_range is None:
            return
        self.timeWindowRequested.emit(self._full_range[0], self._full_range[1])

    def _request_window(self, x0: float, x1: float) -> None:
        if self._full_range is None:
            return
        fr0, fr1 = self._full_range
        span = max(x1 - x0, 1e-9)
        max_span = fr1 - fr0
        if max_span <= 0:
            return
        if span >= max_span:
            self.timeWindowRequested.emit(fr0, fr1)
            return
        if x0 < fr0:
            x0 = fr0
            x1 = fr0 + span
        if x1 > fr1:
            x1 = fr1
            x0 = fr1 - span
        self.timeWindowRequested.emit(float(x0), float(x1))
