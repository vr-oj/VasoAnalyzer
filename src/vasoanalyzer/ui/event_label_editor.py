"""Property editor widget for fine-grained event label styling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, cast

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _color_to_hex(color: QColor) -> str:
    color = QColor(color)
    if not color.isValid():
        return ""
    return color.name(QColor.HexRgb)


def _hex_to_color(value: str) -> QColor:
    color = QColor(value)
    if color.isValid():
        return color
    return QColor()


class EventLabelOverrides(TypedDict, total=False):
    visible: bool
    font: str
    fontfamily: str
    fontsize: float
    x_offset_px: float
    y_offset_axes: float
    lane: int
    color: str
    pinned: bool
    priority: int


class EventLabelEditor(QWidget):
    """Compact editor for per-event label typography and placement."""

    styleChanged = pyqtSignal(int, dict)
    labelTextChanged = pyqtSignal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_index: int | None = None
        self._updating = False
        self._max_lanes = 3

        self.setObjectName("EventLabelEditor")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(6)

        heading = QLabel("Event Label Properties")
        heading.setObjectName("SectionTitle")
        root_layout.addWidget(heading)

        self.summary_label = QLabel("Select an event to edit its label.")
        self.summary_label.setWordWrap(True)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        self.summary_label.setAlignment(cast(Qt.AlignmentFlag, alignment))
        root_layout.addWidget(self.summary_label)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Event label text")
        root_layout.addWidget(self.label_edit)

        visibility_row = QHBoxLayout()
        visibility_row.setSpacing(8)
        self.visible_check = QCheckBox("Show label")
        self.visible_check.setChecked(True)
        visibility_row.addWidget(self.visible_check)

        self.pinned_check = QCheckBox("Pin")
        visibility_row.addWidget(self.pinned_check)

        self.color_button = QPushButton("Text Color…")
        self.color_button.setToolTip("Choose a custom color (leave blank for default).")
        self.color_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        visibility_row.addWidget(self.color_button)
        visibility_row.addStretch(1)
        root_layout.addLayout(visibility_row)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        font_row.addWidget(self.font_combo, 1)

        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setPrefix("Size ")
        self.font_size_spin.setRange(0.0, 96.0)
        self.font_size_spin.setSingleStep(1.0)
        self.font_size_spin.setDecimals(1)
        self.font_size_spin.setSpecialValueText("Auto")
        font_row.addWidget(self.font_size_spin)
        root_layout.addLayout(font_row)

        offset_row = QHBoxLayout()
        offset_row.setSpacing(8)
        self.x_offset_spin = QDoubleSpinBox()
        self.x_offset_spin.setPrefix("X ")
        self.x_offset_spin.setSuffix(" px")
        self.x_offset_spin.setRange(-400.0, 400.0)
        self.x_offset_spin.setDecimals(1)
        self.x_offset_spin.setSingleStep(1.0)
        offset_row.addWidget(self.x_offset_spin)

        self.y_offset_spin = QDoubleSpinBox()
        self.y_offset_spin.setPrefix("Y ")
        self.y_offset_spin.setSuffix(" ax")
        self.y_offset_spin.setRange(-1.5, 1.5)
        self.y_offset_spin.setDecimals(3)
        self.y_offset_spin.setSingleStep(0.01)
        offset_row.addWidget(self.y_offset_spin)
        root_layout.addLayout(offset_row)

        lane_row = QHBoxLayout()
        lane_row.setSpacing(8)
        self.lane_combo = QComboBox()
        lane_row.addWidget(QLabel("Lane"))
        lane_row.addWidget(self.lane_combo, 1)

        self.reset_button = QPushButton("Reset Overrides")
        lane_row.addWidget(self.reset_button)
        root_layout.addLayout(lane_row)

        priority_row = QHBoxLayout()
        priority_row.setSpacing(8)
        priority_row.addWidget(QLabel("Priority"))
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-999, 999)
        self.priority_spin.setValue(0)
        priority_row.addWidget(self.priority_spin)
        priority_row.addStretch(1)
        root_layout.addLayout(priority_row)

        root_layout.addStretch(1)

        self._default_font: QFont = self.font_combo.currentFont()
        self._default_color = ""

        self.label_edit.editingFinished.connect(self._emit_label_change)
        self.visible_check.toggled.connect(self._emit_style_change)
        self.pinned_check.toggled.connect(self._emit_style_change)
        self.font_combo.currentFontChanged.connect(self._emit_style_change)
        self.font_size_spin.valueChanged.connect(self._emit_style_change)
        self.x_offset_spin.valueChanged.connect(self._emit_style_change)
        self.y_offset_spin.valueChanged.connect(self._emit_style_change)
        self.color_button.clicked.connect(self._select_color)
        self.lane_combo.currentIndexChanged.connect(self._emit_style_change)
        self.reset_button.clicked.connect(self._reset_overrides)
        self.priority_spin.valueChanged.connect(self._emit_style_change)

        self._populate_lane_combo(self._max_lanes)
        self._set_controls_enabled(False)

    # Public API -------------------------------------------------------
    def clear(self) -> None:
        self._current_index = None
        self._set_controls_enabled(False)
        self.summary_label.setText("Select an event to edit its label.")
        self._default_color = ""
        self._render_color_button(self._default_color)
        self.pinned_check.setChecked(False)
        self.priority_spin.setValue(0)

    def set_event(
        self,
        index: int,
        label: str,
        time_seconds: float,
        meta: Mapping[str, Any] | None,
        *,
        max_lanes: int | None = None,
    ) -> None:
        self._current_index = index
        self._set_controls_enabled(True)
        if max_lanes is not None and max_lanes != self._max_lanes:
            self._populate_lane_combo(max(1, max_lanes))

        meta_mapping = dict(meta or {})
        self._updating = True

        self.summary_label.setText(f"{label} — {time_seconds:.2f} s")
        self.label_edit.setText(label)
        self.visible_check.setChecked(bool(meta_mapping.get("visible", True)))
        self.pinned_check.setChecked(bool(meta_mapping.get("pinned", False)))

        font_override = meta_mapping.get("font") or meta_mapping.get("fontfamily")
        if isinstance(font_override, str) and font_override.strip():
            self.font_combo.setCurrentFont(QFont(font_override))
        else:
            self.font_combo.setCurrentFont(self._default_font)

        fontsize = meta_mapping.get("fontsize")
        if fontsize is None:
            self.font_size_spin.setValue(0.0)
        else:
            try:
                self.font_size_spin.setValue(float(fontsize))
            except (TypeError, ValueError):
                self.font_size_spin.setValue(0.0)

        try:
            self.x_offset_spin.setValue(float(meta_mapping.get("x_offset_px", 0.0) or 0.0))
        except (TypeError, ValueError):
            self.x_offset_spin.setValue(0.0)
        try:
            self.y_offset_spin.setValue(float(meta_mapping.get("y_offset_axes", 0.0) or 0.0))
        except (TypeError, ValueError):
            self.y_offset_spin.setValue(0.0)

        lane_value = meta_mapping.get("lane")
        self._select_lane(lane_value)

        color_value = meta_mapping.get("color") or ""
        self._default_color = color_value if isinstance(color_value, str) else ""
        self._render_color_button(self._default_color)

        priority_value = meta_mapping.get("priority")
        if isinstance(priority_value, int | float | str):
            try:
                self.priority_spin.setValue(int(priority_value))
            except (TypeError, ValueError):
                self.priority_spin.setValue(0)
        else:
            self.priority_spin.setValue(0)

        self._updating = False

    # Internal helpers -------------------------------------------------
    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.label_edit,
            self.visible_check,
            self.pinned_check,
            self.font_combo,
            self.font_size_spin,
            self.x_offset_spin,
            self.y_offset_spin,
            self.lane_combo,
            self.color_button,
            self.reset_button,
            self.priority_spin,
        ):
            widget.setEnabled(enabled)

    def _populate_lane_combo(self, max_lanes: int) -> None:
        self._max_lanes = max_lanes
        self.lane_combo.blockSignals(True)
        self.lane_combo.clear()
        self.lane_combo.addItem("Auto", None)
        for lane in range(max_lanes):
            self.lane_combo.addItem(f"Lane {lane + 1}", lane)
        self.lane_combo.blockSignals(False)

    def _select_lane(self, value: Any) -> None:
        self.lane_combo.blockSignals(True)
        if value is None or not isinstance(value, int) or value < 0:
            self.lane_combo.setCurrentIndex(0)
        else:
            lane_idx = min(value, self._max_lanes - 1)
            data_index = self.lane_combo.findData(lane_idx)
            if data_index == -1:
                self.lane_combo.addItem(f"Lane {lane_idx + 1}", lane_idx)
                data_index = self.lane_combo.findData(lane_idx)
            self.lane_combo.setCurrentIndex(max(data_index, 0))
        self.lane_combo.blockSignals(False)

    def _gather_meta(self) -> EventLabelOverrides:
        meta: EventLabelOverrides = {}
        if not self.visible_check.isChecked():
            meta["visible"] = False

        if self.pinned_check.isChecked():
            meta["pinned"] = True

        current_font = self.font_combo.currentFont()
        if current_font.family() != self._default_font.family():
            meta["font"] = current_font.family()

        size_value = self.font_size_spin.value()
        if size_value > 0:
            meta["fontsize"] = float(size_value)

        x_offset = self.x_offset_spin.value()
        if abs(x_offset) > 1e-6:
            meta["x_offset_px"] = float(x_offset)

        y_offset = self.y_offset_spin.value()
        if abs(y_offset) > 1e-6:
            meta["y_offset_axes"] = float(y_offset)

        lane_data = self.lane_combo.currentData()
        if lane_data is not None:
            meta["lane"] = int(lane_data)

        if self._default_color:
            meta["color"] = self._default_color

        priority_value = int(self.priority_spin.value())
        if priority_value != 0:
            meta["priority"] = priority_value

        return meta

    def _emit_style_change(self) -> None:
        if self._updating or self._current_index is None:
            return
        meta = self._gather_meta()
        self.styleChanged.emit(self._current_index, meta)

    def _emit_label_change(self) -> None:
        if self._updating or self._current_index is None:
            return
        text = self.label_edit.text() or ""
        self.labelTextChanged.emit(self._current_index, text)

    def _select_color(self) -> None:
        if self._current_index is None:
            return
        initial = _hex_to_color(self._default_color)
        color = QColorDialog.getColor(initial, self, "Select Label Color")
        if not color.isValid():
            return
        self._default_color = _color_to_hex(color)
        self._render_color_button(self._default_color)
        self._emit_style_change()

    def _render_color_button(self, hex_color: str) -> None:
        if hex_color:
            self.color_button.setText(hex_color.upper())
            self.color_button.setStyleSheet(
                f"QPushButton {{ background-color: {hex_color}; color: white; }}"
            )
        else:
            self.color_button.setText("Text Color…")
            self.color_button.setStyleSheet("")

    def _reset_overrides(self) -> None:
        if self._current_index is None:
            return
        self._updating = True
        self.visible_check.setChecked(True)
        self.font_combo.setCurrentFont(self._default_font)
        self.font_size_spin.setValue(0.0)
        self.x_offset_spin.setValue(0.0)
        self.y_offset_spin.setValue(0.0)
        self.lane_combo.setCurrentIndex(0)
        self._default_color = ""
        self._render_color_button(self._default_color)
        self.pinned_check.setChecked(False)
        self.priority_spin.setValue(0)
        self._updating = False
        self.styleChanged.emit(self._current_index, {})
