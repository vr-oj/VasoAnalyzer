"""Go-to-time dialog for trace navigation."""

from __future__ import annotations

import math
import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME


class GotoTimeDialog(QDialog):
    """Dialog that parses and validates time strings for navigation."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        full_range: tuple[float, float] | None = None,
        current_window: tuple[float, float] | None = None,
        cursor_available: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to Time")
        self.setModal(True)

        self._full_range = full_range
        self._current_window = current_window
        self._cursor_available = cursor_available
        self._time_value: float | None = None
        self._mode: str = "center"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignLeft)

        self._time_input = QLineEdit(self)
        self._time_input.setPlaceholderText("e.g. 45.5, 1:30, 01:02:30.5")
        form.addRow("Time:", self._time_input)

        self._hint = QLabel("Formats: seconds, mm:ss, or hh:mm:ss.ms", self)
        self._hint.setObjectName("GotoTimeHint")
        form.addRow("", self._hint)

        layout.addLayout(form)

        self._center_radio = QRadioButton("Center view on time", self)
        self._cursor_radio = QRadioButton("Move cursor only", self)
        self._center_radio.setChecked(True)
        self._cursor_radio.setEnabled(bool(cursor_available))

        layout.addWidget(self._center_radio)
        layout.addWidget(self._cursor_radio)

        self._error = QLabel("", self)
        self._error.setObjectName("GotoTimeError")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_theme()
        self._seed_default_time()

    def _apply_theme(self) -> None:
        text = CURRENT_THEME.get("text", "#000000")
        warning = CURRENT_THEME.get("warning_text", "#B91C1C")
        self.setStyleSheet(
            f"""
QLabel#GotoTimeHint {{
    color: {text};
    font-size: 11px;
}}
QLabel#GotoTimeError {{
    color: {warning};
    font-weight: 600;
}}
"""
        )

    def _seed_default_time(self) -> None:
        center = None
        if self._current_window is not None:
            center = 0.5 * (self._current_window[0] + self._current_window[1])
        elif self._full_range is not None:
            center = 0.5 * (self._full_range[0] + self._full_range[1])
        if center is not None and math.isfinite(center):
            self._time_input.setText(f"{center:.2f}")

    def _set_error(self, message: str | None) -> None:
        if message:
            self._error.setText(message)
            self._error.setVisible(True)
        else:
            self._error.setText("")
            self._error.setVisible(False)

    def _on_accept(self) -> None:
        try:
            value = self.parse_time(self._time_input.text())
        except ValueError as exc:
            self._set_error(str(exc))
            return

        if self._full_range is not None:
            start, end = self._full_range
            if value < start or value > end:
                self._set_error(f"Time must be between {start:.2f}s and {end:.2f}s.")
                return

        self._time_value = value
        if self._cursor_radio.isChecked() and self._cursor_available:
            self._mode = "cursor"
        else:
            self._mode = "center"
        self._set_error(None)
        self.accept()

    def time_value(self) -> float | None:
        return self._time_value

    def mode(self) -> str:
        return self._mode

    @staticmethod
    def parse_time(text: str) -> float:
        raw = (text or "").strip()
        if not raw:
            raise ValueError("Enter a time value.")

        if re.fullmatch(r"[+-]?\d+(\.\d+)?", raw):
            return float(raw)

        parts = raw.split(":")
        if len(parts) == 2:
            minutes, seconds = parts
            try:
                minutes_val = int(minutes)
                seconds_val = float(seconds)
            except ValueError:
                raise ValueError("Invalid mm:ss format.") from None
            if seconds_val >= 60 or seconds_val < 0:
                raise ValueError("Seconds must be between 0 and 59.99.")
            return minutes_val * 60.0 + seconds_val

        if len(parts) == 3:
            hours, minutes, seconds = parts
            try:
                hours_val = int(hours)
                minutes_val = int(minutes)
                seconds_val = float(seconds)
            except ValueError:
                raise ValueError("Invalid hh:mm:ss format.") from None
            if minutes_val < 0 or minutes_val >= 60:
                raise ValueError("Minutes must be between 0 and 59.")
            if seconds_val < 0 or seconds_val >= 60:
                raise ValueError("Seconds must be between 0 and 59.99.")
            return hours_val * 3600.0 + minutes_val * 60.0 + seconds_val

        raise ValueError("Use seconds, mm:ss, or hh:mm:ss.ms.")
