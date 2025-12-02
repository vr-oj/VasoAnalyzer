from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedSettingsDialog

from vasoanalyzer.ui.constants import DEFAULT_STYLE

__all__ = ["build_style_tab"]


def build_style_tab(dialog: UnifiedSettingsDialog) -> QWidget:
    fonts = list(dialog._font_choices)

    content = QWidget()
    grid = QGridLayout(content)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)

    # Axis titles ---------------------------------------------------
    axis_box = QGroupBox("Axis Titles")
    axis_form = QFormLayout(axis_box)
    axis_form.setLabelAlignment(Qt.AlignRight)

    dialog.title_edit = QLineEdit(dialog.ax.get_title())
    dialog.title_edit.setPlaceholderText("Plot title")
    axis_form.addRow("Plot Title:", dialog.title_edit)

    dialog.xlabel_edit = QLineEdit(dialog._current_xlabel())
    dialog.xlabel_edit.setPlaceholderText("X axis title")
    axis_form.addRow("X Axis Title:", dialog.xlabel_edit)

    dialog.yi_label_edit = QLineEdit(dialog.ax.get_ylabel())
    dialog.yi_label_edit.setPlaceholderText("Top plot axis title")
    axis_form.addRow("Top Plot Axis Title:", dialog.yi_label_edit)

    if dialog.ax2 is not None:
        dialog.yo_label_edit = QLineEdit(dialog.ax2.get_ylabel())
        dialog.yo_label_edit.setPlaceholderText("Bottom plot axis title")
        axis_form.addRow("Bottom Plot Axis Title:", dialog.yo_label_edit)

    dialog.axis_font_family = QComboBox()
    dialog.axis_font_family.addItems(fonts)
    dialog.axis_font_family.setCurrentText(
        dialog.style.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
    )
    axis_form.addRow("Font Family:", dialog.axis_font_family)

    dialog.axis_font_size = QSpinBox()
    dialog.axis_font_size.setRange(6, 48)
    dialog.axis_font_size.setValue(
        int(dialog.style.get("axis_font_size", DEFAULT_STYLE["axis_font_size"]))
    )
    axis_form.addRow("Font Size:", dialog.axis_font_size)

    axis_style_row = QWidget()
    axis_style_layout = QHBoxLayout(axis_style_row)
    axis_style_layout.setContentsMargins(0, 0, 0, 0)
    axis_style_layout.setSpacing(8)
    dialog.axis_bold = QCheckBox("Bold")
    dialog.axis_italic = QCheckBox("Italic")
    axis_style_layout.addWidget(dialog.axis_bold)
    axis_style_layout.addWidget(dialog.axis_italic)
    axis_style_layout.addStretch(1)
    axis_form.addRow("Text Style:", axis_style_row)

    x_color_source = dialog._x_axis_target or dialog.ax
    x_color = None
    if x_color_source is not None:
        try:
            x_color = dialog._normalize_color(
                x_color_source.xaxis.label.get_color(),
                dialog.style.get("x_axis_color"),
            )
        except Exception:
            x_color = None
    x_color = x_color or dialog._normalize_color(
        dialog.style.get("x_axis_color", DEFAULT_STYLE.get("x_axis_color", "#000000")),
        DEFAULT_STYLE.get("x_axis_color", "#000000"),
    )
    dialog.x_axis_color_btn = dialog._make_color_button(x_color)
    axis_form.addRow("X Title Color:", dialog.x_axis_color_btn)

    dialog.yi_axis_color_btn = dialog._make_color_button(
        dialog.style.get("y_axis_color", dialog.ax.yaxis.label.get_color())
    )
    axis_form.addRow("Top Plot Title Color:", dialog.yi_axis_color_btn)

    if dialog.ax2 is not None:
        dialog.yo_axis_color_btn = dialog._make_color_button(
            dialog.style.get("right_axis_color", dialog.ax2.yaxis.label.get_color())
        )
        axis_form.addRow("Bottom Plot Title Color:", dialog.yo_axis_color_btn)

    grid.addWidget(axis_box, 0, 0)

    # Tick labels ---------------------------------------------------
    tick_box = QGroupBox("Tick Labels")
    tick_form = QFormLayout(tick_box)
    tick_form.setLabelAlignment(Qt.AlignRight)

    dialog.tick_font_size = QSpinBox()
    dialog.tick_font_size.setRange(6, 32)
    dialog.tick_font_size.setValue(
        int(dialog.style.get("tick_font_size", DEFAULT_STYLE["tick_font_size"]))
    )
    tick_form.addRow("Font Size:", dialog.tick_font_size)

    dialog.x_tick_color_btn = dialog._make_color_button(
        dialog.style.get("x_tick_color", dialog.ax.xaxis.label.get_color())
    )
    tick_form.addRow("X Tick Color:", dialog.x_tick_color_btn)

    dialog.yi_tick_color_btn = dialog._make_color_button(
        dialog.style.get("y_tick_color", dialog.ax.yaxis.label.get_color())
    )
    tick_form.addRow("Top Plot Tick Color:", dialog.yi_tick_color_btn)

    if dialog.ax2 is not None:
        dialog.yo_tick_color_btn = dialog._make_color_button(
            dialog.style.get("right_tick_color", dialog.ax2.yaxis.label.get_color())
        )
        tick_form.addRow("Bottom Plot Tick Color:", dialog.yo_tick_color_btn)

    grid.addWidget(tick_box, 0, 1)

    # Pinned annotations -------------------------------------------
    pin_box = QGroupBox("Pinned Labels")
    pin_form = QFormLayout(pin_box)
    pin_form.setLabelAlignment(Qt.AlignRight)

    dialog.pin_font_family = QComboBox()
    dialog.pin_font_family.addItems(fonts)
    dialog.pin_font_family.setCurrentText(
        dialog.style.get("pin_font_family", DEFAULT_STYLE["pin_font_family"])
    )
    pin_form.addRow("Font Family:", dialog.pin_font_family)

    dialog.pin_font_size = QSpinBox()
    dialog.pin_font_size.setRange(6, 32)
    dialog.pin_font_size.setValue(
        int(dialog.style.get("pin_font_size", DEFAULT_STYLE["pin_font_size"]))
    )
    pin_form.addRow("Font Size:", dialog.pin_font_size)

    pin_style_row = QWidget()
    pin_style_layout = QHBoxLayout(pin_style_row)
    pin_style_layout.setContentsMargins(0, 0, 0, 0)
    pin_style_layout.setSpacing(8)
    dialog.pin_bold = QCheckBox("Bold")
    dialog.pin_italic = QCheckBox("Italic")
    pin_style_layout.addWidget(dialog.pin_bold)
    pin_style_layout.addWidget(dialog.pin_italic)
    pin_style_layout.addStretch(1)
    pin_form.addRow("Text Style:", pin_style_row)

    dialog.pin_color_btn = dialog._make_color_button(
        dialog.style.get("pin_color", DEFAULT_STYLE["pin_color"])
    )
    pin_form.addRow("Label Color:", dialog.pin_color_btn)

    dialog.pin_marker_size = QSpinBox()
    dialog.pin_marker_size.setRange(2, 20)
    dialog.pin_marker_size.setValue(int(dialog.style.get("pin_size", DEFAULT_STYLE["pin_size"])))
    pin_form.addRow("Marker Size:", dialog.pin_marker_size)

    grid.addWidget(pin_box, 1, 0, 1, 2)

    # Trace lines ---------------------------------------------------
    line_box = QGroupBox("Trace Lines")
    line_form = QFormLayout(line_box)
    line_form.setLabelAlignment(Qt.AlignRight)

    dialog.line_width = QDoubleSpinBox()
    dialog.line_width.setRange(0.5, 10)
    dialog.line_width.setValue(float(dialog.style.get("line_width", DEFAULT_STYLE["line_width"])))
    line_form.addRow("Inner Line Width:", dialog.line_width)

    dialog.line_style_combo = QComboBox()
    for code, label in (
        ("solid", "Solid"),
        ("dashed", "Dashed"),
        ("dotted", "Dotted"),
        ("dashdot", "DashDot"),
    ):
        dialog.line_style_combo.addItem(label, code)
    line_form.addRow("Inner Line Style:", dialog.line_style_combo)

    primary_line = dialog._primary_trace_line()
    primary_color = None
    if primary_line is not None:
        primary_color = dialog._normalize_color(
            primary_line.get_color(), dialog.style.get("line_color")
        )
    primary_color = primary_color or dialog._normalize_color(
        dialog.style.get("line_color", DEFAULT_STYLE["line_color"]),
        DEFAULT_STYLE["line_color"],
    )
    dialog.line_color_btn = dialog._make_color_button(primary_color)
    line_form.addRow("Inner Line Color:", dialog.line_color_btn)

    if dialog.ax2 is not None:
        dialog.od_line_width = QDoubleSpinBox()
        dialog.od_line_width.setRange(0.5, 10)
        dialog.od_line_width.setValue(
            float(dialog.style.get("outer_line_width", DEFAULT_STYLE["outer_line_width"]))
        )
        line_form.addRow("Outer Line Width:", dialog.od_line_width)

        dialog.od_line_style_combo = QComboBox()
        for code, label in (
            ("solid", "Solid"),
            ("dashed", "Dashed"),
            ("dotted", "Dotted"),
            ("dashdot", "DashDot"),
        ):
            dialog.od_line_style_combo.addItem(label, code)
        line_form.addRow("Outer Line Style:", dialog.od_line_style_combo)

        secondary_line = dialog._secondary_trace_line()
        secondary_color = None
        if secondary_line is not None:
            secondary_color = dialog._normalize_color(
                secondary_line.get_color(),
                dialog.style.get("outer_line_color"),
            )
        secondary_color = secondary_color or dialog._normalize_color(
            dialog.style.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
            DEFAULT_STYLE["outer_line_color"],
        )
        dialog.od_line_color_btn = dialog._make_color_button(secondary_color)
        line_form.addRow("Outer Line Color:", dialog.od_line_color_btn)

    grid.addWidget(line_box, 2, 0, 1, 2)

    # Event highlights ----------------------------------------------
    highlight_box = QGroupBox("Event Highlights")
    highlight_form = QFormLayout(highlight_box)
    highlight_form.setLabelAlignment(Qt.AlignRight)

    dialog.event_highlight_color_btn = dialog._make_color_button(
        dialog.style.get(
            "event_highlight_color", DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF")
        )
    )
    highlight_form.addRow("Highlight Color:", dialog.event_highlight_color_btn)

    dialog.event_highlight_alpha = QDoubleSpinBox()
    dialog.event_highlight_alpha.setRange(0.0, 1.0)
    dialog.event_highlight_alpha.setSingleStep(0.05)
    dialog.event_highlight_alpha.setDecimals(2)
    dialog.event_highlight_alpha.setValue(
        float(
            dialog.style.get(
                "event_highlight_alpha", DEFAULT_STYLE.get("event_highlight_alpha", 0.95)
            )
        )
    )
    highlight_form.addRow("Base Opacity:", dialog.event_highlight_alpha)

    dialog.event_highlight_duration = QSpinBox()
    dialog.event_highlight_duration.setRange(0, 60000)
    dialog.event_highlight_duration.setSingleStep(100)
    dialog.event_highlight_duration.setSuffix(" ms")
    dialog.event_highlight_duration.setValue(
        int(
            dialog.style.get(
                "event_highlight_duration_ms",
                DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
            )
        )
    )
    highlight_form.addRow("Fade Duration:", dialog.event_highlight_duration)

    grid.addWidget(highlight_box, 3, 0, 1, 2)

    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    grid.setRowStretch(4, 1)

    scroll = QScrollArea()
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)

    return scroll
