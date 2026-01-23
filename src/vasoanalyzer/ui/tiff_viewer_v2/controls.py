# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Control strip widget for the TIFF viewer v2."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from vasoanalyzer.ui.icons import snapshot_icon
from vasoanalyzer.ui.theme import CURRENT_THEME

from .snapshot_timeline import SnapshotTimelineSlider


class ControlsStrip(QtWidgets.QFrame):
    """Two-row playback controls."""

    prev_clicked = QtCore.pyqtSignal()
    next_clicked = QtCore.pyqtSignal()
    play_toggled = QtCore.pyqtSignal(bool)
    page_changed = QtCore.pyqtSignal(int)
    pps_changed = QtCore.pyqtSignal(float)
    loop_toggled = QtCore.pyqtSignal(bool)
    sync_toggled = QtCore.pyqtSignal(bool)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SnapshotControls")
        self._icon_size = QtCore.QSize(16, 16)
        self._button_size = 30
        self._page_count = 0
        self._page_index = 0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        row1 = QtWidgets.QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        layout.addLayout(row1)
        layout.addLayout(row2)

        self.prev_button = QtWidgets.QToolButton(self)
        self.prev_button.setAutoRaise(False)
        self.prev_button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.prev_button.setIconSize(self._icon_size)
        self.prev_button.setFixedSize(self._button_size, self._button_size)
        self.prev_button.setText("")
        self.prev_button.setToolTip("Previous frame")
        self.prev_button.clicked.connect(self.prev_clicked.emit)
        row1.addWidget(self.prev_button)

        self.play_button = QtWidgets.QToolButton(self)
        self.play_button.setAutoRaise(False)
        self.play_button.setCheckable(True)
        self.play_button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.play_button.setIconSize(self._icon_size)
        self.play_button.setFixedSize(self._button_size, self._button_size)
        self.play_button.setText("")
        self.play_button.setToolTip("Play")
        self.play_button.toggled.connect(self._on_play_toggled)
        row1.addWidget(self.play_button)

        self.next_button = QtWidgets.QToolButton(self)
        self.next_button.setAutoRaise(False)
        self.next_button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.next_button.setIconSize(self._icon_size)
        self.next_button.setFixedSize(self._button_size, self._button_size)
        self.next_button.setText("")
        self.next_button.setToolTip("Next frame")
        self.next_button.clicked.connect(self.next_clicked.emit)
        row1.addWidget(self.next_button)

        self.slider = SnapshotTimelineSlider(self)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        row1.addWidget(self.slider, 1)

        self.frame_label = QtWidgets.QLabel("Frame 0 / 0")
        self.frame_label.setObjectName("SnapshotFrameLabel")
        self.frame_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.frame_label.setSizePolicy(
            QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed
        )
        row1.addWidget(self.frame_label)

        self.speed_label = QtWidgets.QLabel("Playback")
        self.speed_label.setObjectName("SnapshotSpeedLabel")
        row2.addWidget(self.speed_label)

        self.speed_input = QtWidgets.QDoubleSpinBox(self)
        self.speed_input.setObjectName("SnapshotSpeedInput")
        self.speed_input.setDecimals(1)
        self.speed_input.setSingleStep(1.0)
        self.speed_input.setRange(1.0, 120.0)
        self.speed_input.setValue(30.0)
        self.speed_input.setToolTip("Adjust snapshot playback speed (pages / second)")
        self.speed_input.valueChanged.connect(self.pps_changed.emit)
        row2.addWidget(self.speed_input)

        self.speed_units_label = QtWidgets.QLabel("pages/sec")
        self.speed_units_label.setObjectName("SnapshotSpeedUnitsLabel")
        row2.addWidget(self.speed_units_label)

        self.loop_checkbox = QtWidgets.QCheckBox("Loop")
        self.loop_checkbox.setObjectName("SnapshotLoopCheckbox")
        self.loop_checkbox.setChecked(True)
        self.loop_checkbox.setToolTip(
            "Restart playback from beginning when reaching last frame"
        )
        self.loop_checkbox.toggled.connect(self.loop_toggled.emit)
        row2.addWidget(self.loop_checkbox)

        self.sync_checkbox = QtWidgets.QCheckBox("Sync")
        self.sync_checkbox.setObjectName("SnapshotSyncCheckbox")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.setToolTip("Sync snapshot playback to trace cursor")
        self.sync_checkbox.toggled.connect(self.sync_toggled.emit)
        row2.addWidget(self.sync_checkbox)

        row2.addStretch()

        self.sync_label = QtWidgets.QLabel("Synced: —")
        self.sync_label.setObjectName("SnapshotSyncLabel")
        self.sync_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.sync_label.setSizePolicy(
            QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred
        )
        row2.addWidget(self.sync_label)

        self._apply_control_styles()
        self._apply_icons()

    def _on_play_toggled(self, checked: bool) -> None:
        self.play_button.setToolTip("Pause" if checked else "Play")
        self._apply_icons()
        self.play_toggled.emit(checked)

    def _on_slider_value_changed(self, value: int) -> None:
        self._page_index = int(value)
        self._update_frame_label()
        self.page_changed.emit(value)

    def _apply_icons(self) -> None:
        self.prev_button.setIcon(snapshot_icon("prev"))
        self.next_button.setIcon(snapshot_icon("next"))
        icon_name = "pause" if self.play_button.isChecked() else "play"
        self.play_button.setIcon(snapshot_icon(icon_name))

    def _apply_control_styles(self) -> None:
        palette = self.palette()
        button_bg = QtGui.QColor(palette.button().color())
        border = QtGui.QColor(palette.mid().color())
        text = QtGui.QColor(palette.windowText().color())
        track = QtGui.QColor(palette.base().color())
        accent = QtGui.QColor(palette.highlight().color())
        is_dark = palette.window().color().lightness() < 128
        hover = button_bg.lighter(112) if is_dark else button_bg.darker(105)
        pressed = button_bg.lighter(125) if is_dark else button_bg.darker(115)
        disabled = QtGui.QColor(palette.window().color())

        radius = 6
        if isinstance(CURRENT_THEME, dict):
            radius = int(CURRENT_THEME.get("panel_radius", radius))

        button_style = f"""
QToolButton {{
    background: {_rgba(button_bg)};
    border: 1px solid {_rgba(border)};
    border-radius: {radius}px;
    min-width: {self._button_size}px;
    min-height: {self._button_size}px;
    padding: 0px;
}}
QToolButton:hover {{
    background: {_rgba(hover)};
}}
QToolButton:pressed,
QToolButton:checked {{
    background: {_rgba(pressed)};
}}
QToolButton:disabled {{
    background: {_rgba(disabled)};
    border-color: {_rgba(border)};
}}
"""
        slider_style = f"""
QSlider#SnapshotTimeline::groove:horizontal {{
    background: {_rgba(track)};
    border-radius: 4px;
    height: 8px;
}}
QSlider#SnapshotTimeline::sub-page:horizontal {{
    background: {_rgba(accent)};
    border-radius: 4px;
    height: 8px;
}}
QSlider#SnapshotTimeline::add-page:horizontal {{
    background: {_rgba(track)};
    border-radius: 4px;
    height: 8px;
}}
QSlider#SnapshotTimeline::handle:horizontal {{
    background: transparent;
    border: none;
    width: 14px;
    margin: -8px 0;
}}
"""
        frame_label_style = f"color: {_rgba(text)}; font-size: 11px;"
        for button in (self.prev_button, self.play_button, self.next_button):
            button.setStyleSheet(button_style)
        self.slider.setStyleSheet(slider_style)
        self.frame_label.setStyleSheet(frame_label_style)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.PaletteChange:
            self._apply_control_styles()
            self._apply_icons()
        super().changeEvent(event)

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.prev_button,
            self.play_button,
            self.next_button,
            self.slider,
            self.speed_label,
            self.speed_input,
            self.speed_units_label,
            self.loop_checkbox,
            self.sync_checkbox,
            self.sync_label,
        ):
            widget.setEnabled(enabled)

    def set_page_count(self, page_count: int) -> None:
        self._page_count = max(0, int(page_count))
        self.slider.setRange(0, max(0, self._page_count - 1))
        self.set_controls_enabled(self._page_count > 0)
        self._update_frame_label()

    def set_page_index(self, page_index: int) -> None:
        self._page_index = int(page_index)
        self.slider.blockSignals(True)
        self.slider.setValue(self._page_index)
        self.slider.blockSignals(False)
        self._update_frame_label()

    def set_playing(self, playing: bool) -> None:
        self.play_button.blockSignals(True)
        self.play_button.setChecked(bool(playing))
        self.play_button.blockSignals(False)
        self.play_button.setToolTip("Pause" if playing else "Play")
        self._apply_icons()

    def set_sync_checked(self, checked: bool) -> None:
        self.sync_checkbox.blockSignals(True)
        self.sync_checkbox.setChecked(bool(checked))
        self.sync_checkbox.blockSignals(False)

    def set_sync_available(self, available: bool) -> None:
        self.sync_checkbox.setEnabled(bool(available))

    def set_mapped_time_text(self, text: str) -> None:
        self.sync_label.setText(text)

    def _update_frame_label(self) -> None:
        if self._page_count <= 0:
            self.frame_label.setText("Frame 0 / 0")
            return
        index = min(max(self._page_index, 0), self._page_count - 1)
        self.frame_label.setText(f"Frame {index + 1} / {self._page_count}")


def _rgba(color: QtGui.QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


__all__ = ["ControlsStrip"]
