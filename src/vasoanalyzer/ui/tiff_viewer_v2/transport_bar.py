# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Transport bar widgets for the TIFF viewer v2."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from vasoanalyzer.ui.icons import snapshot_icon
from vasoanalyzer.ui.theme import CURRENT_THEME


class TiffScrubBar(QtWidgets.QSlider):
    """Custom scrub bar with a physical rail + handle."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self.setObjectName("TiffScrubBar")
        self.setMouseTracking(True)
        self.setTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setRange(0, 0)
        self.setFixedHeight(24)
        self._track_height = 8
        self._handle_radius = 7
        self._hovering = False
        self._dragging = False

    def _theme_color(self, key: str, fallback: QtGui.QColor) -> QtGui.QColor:
        if isinstance(CURRENT_THEME, dict):
            value = CURRENT_THEME.get(key)
            if value:
                color = QtGui.QColor(value)
                if color.isValid():
                    return color
        return QtGui.QColor(fallback)

    def _track_rect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF(self.rect())
        margin = max(6, int(self._handle_radius + 4))
        width = max(1.0, rect.width() - margin * 2)
        center_y = rect.center().y()
        return QtCore.QRectF(
            rect.left() + margin,
            center_y - self._track_height / 2,
            width,
            self._track_height,
        )

    def _handle_center_x(self) -> float:
        track = self._track_rect()
        span = max(1.0, track.width())
        minimum = self.minimum()
        maximum = self.maximum()
        current = self.sliderPosition() if self.isSliderDown() else self.value()
        if maximum <= minimum:
            return track.left()
        ratio = (current - minimum) / float(maximum - minimum)
        ratio = max(0.0, min(ratio, 1.0))
        return track.left() + span * ratio

    def _handle_rect(self) -> QtCore.QRectF:
        track = self._track_rect()
        radius = self._handle_radius + (2 if self._hovering or self._dragging else 0)
        center_x = self._handle_center_x()
        return QtCore.QRectF(
            center_x - radius,
            track.center().y() - radius,
            radius * 2,
            radius * 2,
        )

    def _value_from_pos(self, pos: QtCore.QPointF) -> int:
        track = self._track_rect()
        if track.width() <= 0:
            return self.minimum()
        x = pos.x()
        ratio = (x - track.left()) / track.width()
        ratio = max(0.0, min(ratio, 1.0))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def _update_cursor(self, pos: QtCore.QPointF | None = None) -> None:
        hover = self._hovering
        if pos is not None:
            handle = self._handle_rect().adjusted(-4, -4, 4, 4)
            hover = handle.contains(pos)
        self.setCursor(
            QtCore.Qt.CursorShape.SizeHorCursor if hover or self._dragging else QtCore.Qt.CursorShape.ArrowCursor
        )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        palette = self.palette()
        window = palette.window().color()
        is_dark = window.lightness() < 128
        rail = self._theme_color("grid_color", palette.mid().color())
        rail = rail.lighter(120) if is_dark else rail.darker(108)
        rail_border = rail.lighter(115) if is_dark else rail.darker(115)
        fill = self._theme_color("time_cursor", palette.highlight().color())
        handle_fill = self._theme_color("button_bg", palette.button().color())
        handle_border = self._theme_color("panel_border", palette.mid().color())
        shadow = QtGui.QColor(0, 0, 0, 70 if is_dark else 50)

        track = self._track_rect()
        radius = track.height() / 2

        painter.setPen(QtGui.QPen(rail_border, 1))
        painter.setBrush(rail)
        painter.drawRoundedRect(track, radius, radius)

        progress_width = max(0.0, self._handle_center_x() - track.left())
        if progress_width > 0:
            progress_rect = QtCore.QRectF(track)
            progress_rect.setWidth(progress_width)
            clip_path = QtGui.QPainterPath()
            clip_path.addRoundedRect(track, radius, radius)
            painter.save()
            painter.setClipPath(clip_path)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(progress_rect, radius, radius)
            painter.restore()

        handle_rect = self._handle_rect()
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(handle_rect.translated(0, 1))

        painter.setPen(QtGui.QPen(handle_border, 1))
        painter.setBrush(handle_fill)
        painter.drawEllipse(handle_rect)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setSliderDown(True)
            self.setValue(self._value_from_pos(event.position()))
            self._update_cursor(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setSliderDown(True)
            self.setValue(self._value_from_pos(event.position()))
        self._hovering = self._handle_rect().adjusted(-4, -4, 4, 4).contains(event.position())
        self._update_cursor(event.position())
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setSliderDown(False)
            self._update_cursor(event.position())
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._update_cursor()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovering = False
        self._dragging = False
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)


class TiffTransportBar(QtWidgets.QFrame):
    """Two-row transport bar for TIFF playback."""

    frameRequested = QtCore.pyqtSignal(int)
    playToggled = QtCore.pyqtSignal(bool)
    speedChanged = QtCore.pyqtSignal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TiffTransportBar")
        self._icon_size = QtCore.QSize(14, 14)
        self._button_size = 26
        self._page_count = 0
        self._page_index = 0
        self._speed_multiplier = 1.0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(2)

        self.scrub_bar = TiffScrubBar(self)
        self.scrub_bar.valueChanged.connect(self._on_scrub_changed)
        layout.addWidget(self.scrub_bar)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.start_button = QtWidgets.QToolButton(self)
        self.start_button.setAutoRaise(False)
        self.start_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.start_button.setIconSize(self._icon_size)
        self.start_button.setFixedSize(self._button_size, self._button_size)
        self.start_button.setToolTip("Jump to first frame")
        self.start_button.clicked.connect(self._on_jump_start)
        row.addWidget(self.start_button)

        self.play_button = QtWidgets.QToolButton(self)
        self.play_button.setAutoRaise(False)
        self.play_button.setCheckable(True)
        self.play_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.play_button.setIconSize(self._icon_size)
        self.play_button.setFixedSize(self._button_size, self._button_size)
        self.play_button.setToolTip("Play")
        self.play_button.toggled.connect(self._on_play_toggled)
        row.addWidget(self.play_button)

        self.end_button = QtWidgets.QToolButton(self)
        self.end_button.setAutoRaise(False)
        self.end_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.end_button.setIconSize(self._icon_size)
        self.end_button.setFixedSize(self._button_size, self._button_size)
        self.end_button.setToolTip("Jump to last frame")
        self.end_button.clicked.connect(self._on_jump_end)
        row.addWidget(self.end_button)

        row.addStretch(1)

        self.speed_combo = QtWidgets.QComboBox(self)
        self.speed_combo.setObjectName("SnapshotSpeedCombo")
        self.speed_combo.setToolTip("Playback speed multiplier")
        self.speed_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        for value in (0.25, 0.5, 1.0, 2.0, 5.0, 10.0):
            self.speed_combo.addItem(_format_multiplier(value), value)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        row.addWidget(self.speed_combo)
        # Backward-compat aliases used by snapshot_manager
        self.speed_label = self.speed_combo
        self.speed_pill = self.speed_combo

        self.time_label = QtWidgets.QLabel("Frame 0 / 0")
        self.time_label.setObjectName("SnapshotTimeLabel")
        self.time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.time_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)
        row.addWidget(self.time_label)
        layout.addLayout(row)
        self._apply_control_styles()
        self._apply_icons()
        self.set_speed_multiplier(1.0)

    def _on_play_toggled(self, checked: bool) -> None:
        self.play_button.setToolTip("Pause" if checked else "Play")
        self._apply_icons()
        self.playToggled.emit(checked)

    def _on_scrub_changed(self, value: int) -> None:
        self._page_index = int(value)
        self._update_frame_label()
        self.frameRequested.emit(self._page_index)

    def _on_jump_start(self) -> None:
        if self._page_count <= 0:
            return
        self.scrub_bar.setValue(0)

    def _on_jump_end(self) -> None:
        if self._page_count <= 0:
            return
        self.scrub_bar.setValue(max(0, self._page_count - 1))

    def _on_speed_changed(self, index: int) -> None:
        value = self.speed_combo.itemData(index)
        try:
            multiplier = float(value)
        except (TypeError, ValueError):
            multiplier = 1.0
        if multiplier <= 0:
            multiplier = 1.0
        self._speed_multiplier = multiplier
        self.speedChanged.emit(multiplier)

    def _apply_icons(self) -> None:
        self.start_button.setIcon(snapshot_icon("prev"))
        self.end_button.setIcon(snapshot_icon("next"))
        icon_name = "pause" if self.play_button.isChecked() else "play"
        self.play_button.setIcon(snapshot_icon(icon_name))

    def _apply_control_styles(self) -> None:
        palette = self.palette()
        button_bg = QtGui.QColor(palette.button().color())
        border = QtGui.QColor(palette.mid().color())
        text = QtGui.QColor(palette.windowText().color())
        field = QtGui.QColor(palette.base().color())
        is_dark = palette.window().color().lightness() < 128
        hover = button_bg.lighter(112) if is_dark else button_bg.darker(106)
        pressed = button_bg.lighter(125) if is_dark else button_bg.darker(118)
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
        combo_style = f"""
QComboBox#SnapshotSpeedCombo {{
    background: {_rgba(button_bg)};
    border: 1px solid {_rgba(border)};
    border-radius: {radius}px;
    padding: 2px 6px 2px 6px;
    min-height: 22px;
    color: {_rgba(text)};
    font-size: 10px;
}}
QComboBox#SnapshotSpeedCombo:hover {{
    background: {_rgba(hover)};
}}
QComboBox#SnapshotSpeedCombo::drop-down {{
    border: none;
    width: 14px;
}}
QComboBox#SnapshotSpeedCombo QAbstractItemView {{
    background: {_rgba(field)};
    color: {_rgba(text)};
    selection-background-color: {_rgba(pressed)};
}}
"""
        label_style = (
            f"color: {_rgba(text)}; font-size: 11px; "
            "font-family: Menlo, Consolas, 'Courier New', monospace;"
        )
        for button in (self.start_button, self.play_button, self.end_button):
            button.setStyleSheet(button_style)
        self.speed_combo.setStyleSheet(combo_style)
        self.time_label.setStyleSheet(label_style)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            self._apply_control_styles()
            self._apply_icons()
        super().changeEvent(event)

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.start_button,
            self.play_button,
            self.end_button,
            self.scrub_bar,
            self.speed_combo,
        ):
            widget.setEnabled(enabled)
        self.time_label.setEnabled(True)

    def set_page_count(self, page_count: int) -> None:
        self._page_count = max(0, int(page_count))
        self.scrub_bar.setRange(0, max(0, self._page_count - 1))
        self.set_controls_enabled(self._page_count > 0)
        self._lock_time_label_width()
        self._update_frame_label()

    def set_page_index(self, page_index: int) -> None:
        self._page_index = int(page_index)
        self.scrub_bar.blockSignals(True)
        self.scrub_bar.setValue(self._page_index)
        self.scrub_bar.blockSignals(False)
        self._update_frame_label()

    def set_playing(self, playing: bool) -> None:
        self.play_button.blockSignals(True)
        self.play_button.setChecked(bool(playing))
        self.play_button.blockSignals(False)
        self.play_button.setToolTip("Pause" if playing else "Play")
        self._apply_icons()

    def set_speed_multiplier(self, multiplier: float) -> None:
        try:
            value = float(multiplier)
        except (TypeError, ValueError):
            value = 1.0
        value = max(0.1, value)
        self._speed_multiplier = value
        for idx in range(self.speed_combo.count()):
            if abs(float(self.speed_combo.itemData(idx)) - value) < 0.01:
                self.speed_combo.blockSignals(True)
                self.speed_combo.setCurrentIndex(idx)
                self.speed_combo.blockSignals(False)
                return

    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    def set_time_readout(self, text: str) -> None:
        self.time_label.setText(text)
        fm = self.time_label.fontMetrics()
        needed = fm.horizontalAdvance(text) + 8
        if needed > self.time_label.minimumWidth():
            self.time_label.setMinimumWidth(needed)

    def _lock_time_label_width(self) -> None:
        """Set a stable minimum width so the label doesn't resize during scrub."""
        if self._page_count <= 0:
            self.time_label.setMinimumWidth(0)
            return
        n = str(self._page_count)
        # Use the widest plausible text for this page count
        sample = f"Frame {n} / {n}   00000.00 s / 00000.00 s"
        fm = self.time_label.fontMetrics()
        self.time_label.setMinimumWidth(fm.horizontalAdvance(sample) + 8)

    def _update_frame_label(self) -> None:
        if self._page_count <= 0:
            self.time_label.setText("No TIFF loaded")
            return
        index = min(max(self._page_index, 0), self._page_count - 1)
        self.time_label.setText(f"Frame {index + 1} / {self._page_count}")


def _format_multiplier(value: float) -> str:
    text = f"{value:g}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}×"


def _rgba(color: QtGui.QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


__all__ = ["TiffScrubBar", "TiffTransportBar"]
