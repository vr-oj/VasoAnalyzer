# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# [L] ========================= PlotStyleDialog =========================
from PyQt5.QtWidgets import (
    QDialog,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QColorDialog,
)
from PyQt5.QtGui import QColor
from ..constants import DEFAULT_STYLE


class PlotStyleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setMinimumWidth(400)
        self.apply_callback = None

        # Consistent styling across tabs and buttons
        self.setStyleSheet(
            """
            QDialog {
                font-family: Arial;
                font-size: 12px;
            }
            QTabWidget::pane {
                margin: 6px;
            }
            QFormLayout {
                margin-top: 4px;
                margin-bottom: 4px;
            }
            QPushButton {
                min-width: 70px;
                padding: 4px 8px;
            }
            """
        )

        # Tab widget
        self.tabs = QTabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)
        main_layout.addWidget(self.tabs)

        # Bottom row: Apply All / Cancel / OK
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.apply_all_btn = QPushButton("Apply")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("OK")
        btn_row.addWidget(self.apply_all_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        main_layout.addLayout(btn_row)

        # Connect them
        self.apply_all_btn.clicked.connect(self.handle_apply_all)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)

        # Create each tab
        self._init_axis_tab()
        self._init_tick_tab()
        self._init_event_tab()
        self._init_pin_tab()
        self._init_line_tab()

    def _set_button_color(self, btn, color):
        btn.color = color
        btn.setStyleSheet(f"background-color: {color}")

    def _make_color_button(self, color):
        btn = QPushButton()
        btn.setFixedWidth(60)
        self._set_button_color(btn, color)

        def choose():
            qcol = QColorDialog.getColor(QColor(btn.color), self)
            if qcol.isValid():
                self._set_button_color(btn, qcol.name())

        btn.clicked.connect(choose)
        return btn

    def handle_apply_all(self):
        """Apply *all* settings at once."""
        style = self.get_style()
        if callable(self.apply_callback):
            self.apply_callback(style)
        else:
            self.parent().apply_plot_style(style)

    def handle_apply_tab(self, section):
        """Apply only one section (axis/tick/event/pin/line)."""
        style = self.get_style()
        if callable(self.apply_callback):
            self.apply_callback(style)
        else:
            parent = self.parent()
            if section == "axis":
                parent.ax.xaxis.label.set_fontsize(style["axis_font_size"])
                parent.ax.xaxis.label.set_fontname(style["axis_font_family"])
                parent.ax.xaxis.label.set_fontweight(
                    "bold" if style["axis_bold"] else "normal"
                )
                parent.ax.xaxis.label.set_fontstyle(
                    "italic" if style["axis_italic"] else "normal"
                )
                parent.ax.yaxis.label.set_fontsize(style["axis_font_size"])
                parent.ax.yaxis.label.set_fontname(style["axis_font_family"])
                parent.ax.yaxis.label.set_fontweight(
                    "bold" if style["axis_bold"] else "normal"
                )
                parent.ax.yaxis.label.set_fontstyle(
                    "italic" if style["axis_italic"] else "normal"
                )

            elif section == "tick":
                parent.ax.tick_params(axis="x", labelsize=style["tick_font_size"])
                parent.ax.tick_params(axis="y", labelsize=style["tick_font_size"])

            elif section == "event":
                for entry in parent.event_text_objects:
                    txt = entry[0]
                    txt.set_fontsize(style["event_font_size"])
                    txt.set_fontname(style["event_font_family"])
                    txt.set_fontweight("bold" if style["event_bold"] else "normal")
                    txt.set_fontstyle("italic" if style["event_italic"] else "normal")

            elif section == "pin":
                for marker, label in parent.pinned_points:
                    marker.set_markersize(style["pin_size"])
                    label.set_fontsize(style["pin_font_size"])
                    label.set_fontname(style["pin_font_family"])
                    label.set_fontweight("bold" if style["pin_bold"] else "normal")
                    label.set_fontstyle("italic" if style["pin_italic"] else "normal")

            elif section == "line":
                if parent.ax.lines:
                    parent.ax.lines[0].set_linewidth(style["line_width"])

            parent.canvas.draw_idle()

    def _make_section_widgets(self, section):
        """Helper: create section's Apply/Default row."""
        h = QHBoxLayout()
        h.setSpacing(6)
        h.addStretch()
        apply_btn = QPushButton("Apply")
        default_btn = QPushButton("Default")
        apply_btn.clicked.connect(lambda _, sec=section: self.handle_apply_tab(sec))
        default_btn.clicked.connect(lambda _, sec=section: self.reset_defaults(sec))
        h.addWidget(apply_btn)
        h.addWidget(default_btn)
        return h

    def _init_axis_tab(self):
        tab = QWidget()
        tab.setObjectName("axis_tab")
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        desc = QLabel("Adjust axis title fonts")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        form = QFormLayout()
        self.axis_font_size = QSpinBox()
        self.axis_font_size.setRange(6, 32)
        self.axis_font_size.setValue(int(DEFAULT_STYLE["axis_font_size"]))
        self.axis_font_family = QComboBox()
        self.axis_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )
        self.axis_font_family.setCurrentText(DEFAULT_STYLE["axis_font_family"])
        self.axis_bold = QCheckBox("Bold")
        self.axis_bold.setChecked(bool(DEFAULT_STYLE["axis_bold"]))
        self.axis_italic = QCheckBox("Italic")
        self.axis_italic.setChecked(bool(DEFAULT_STYLE["axis_italic"]))
        self.axis_color_btn = self._make_color_button(DEFAULT_STYLE["axis_color"])
        form.addRow("Font Size:", self.axis_font_size)
        form.addRow("Font Family:", self.axis_font_family)
        form.addRow("", self.axis_bold)
        form.addRow("", self.axis_italic)
        form.addRow("Color:", self.axis_color_btn)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("axis"))
        self.tabs.addTab(tab, "Axis Titles")

    def _init_tick_tab(self):
        tab = QWidget()
        tab.setObjectName("tick_tab")
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        desc = QLabel("Set tick label font size")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        form = QFormLayout()
        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(int(DEFAULT_STYLE["tick_font_size"]))
        self.tick_color_btn = self._make_color_button(DEFAULT_STYLE["tick_color"])
        form.addRow("Tick Font Size:", self.tick_font_size)
        form.addRow("Color:", self.tick_color_btn)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("tick"))
        self.tabs.addTab(tab, "Tick Labels")

    def _init_event_tab(self):
        tab = QWidget()
        tab.setObjectName("event_tab")
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        desc = QLabel("Customize event annotation fonts")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        form = QFormLayout()
        self.event_font_size = QSpinBox()
        self.event_font_size.setRange(6, 32)
        self.event_font_size.setValue(int(DEFAULT_STYLE["event_font_size"]))
        self.event_font_family = QComboBox()
        self.event_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )
        self.event_font_family.setCurrentText(DEFAULT_STYLE["event_font_family"])
        self.event_bold = QCheckBox("Bold")
        self.event_bold.setChecked(bool(DEFAULT_STYLE["event_bold"]))
        self.event_italic = QCheckBox("Italic")
        self.event_italic.setChecked(bool(DEFAULT_STYLE["event_italic"]))
        self.event_color_btn = self._make_color_button(DEFAULT_STYLE["event_color"])
        form.addRow("Font Size:", self.event_font_size)
        form.addRow("Font Family:", self.event_font_family)
        form.addRow("", self.event_bold)
        form.addRow("", self.event_italic)
        form.addRow("Color:", self.event_color_btn)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("event"))
        self.tabs.addTab(tab, "Event Labels")

    def _init_pin_tab(self):
        tab = QWidget()
        tab.setObjectName("pin_tab")
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        desc = QLabel("Pinned point labels and marker size")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        form = QFormLayout()
        self.pin_font_size = QSpinBox()
        self.pin_font_size.setRange(6, 32)
        self.pin_font_size.setValue(int(DEFAULT_STYLE["pin_font_size"]))
        self.pin_font_family = QComboBox()
        self.pin_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )
        self.pin_font_family.setCurrentText(DEFAULT_STYLE["pin_font_family"])
        self.pin_bold = QCheckBox("Bold")
        self.pin_bold.setChecked(bool(DEFAULT_STYLE["pin_bold"]))
        self.pin_italic = QCheckBox("Italic")
        self.pin_italic.setChecked(bool(DEFAULT_STYLE["pin_italic"]))
        self.pin_color_btn = self._make_color_button(DEFAULT_STYLE["pin_color"])
        self.pin_size = QSpinBox()
        self.pin_size.setRange(2, 20)
        self.pin_size.setValue(int(DEFAULT_STYLE["pin_size"]))
        form.addRow("Font Size:", self.pin_font_size)
        form.addRow("Font Family:", self.pin_font_family)
        form.addRow("", self.pin_bold)
        form.addRow("", self.pin_italic)
        form.addRow("Color:", self.pin_color_btn)
        form.addRow("Marker Size:", self.pin_size)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("pin"))
        self.tabs.addTab(tab, "Pinned Labels")

    def _init_line_tab(self):
        tab = QWidget()
        tab.setObjectName("line_tab")
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        desc = QLabel("Trace line thickness")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        form = QFormLayout()
        self.line_width = QSpinBox()
        self.line_width.setRange(1, 10)
        self.line_width.setValue(int(DEFAULT_STYLE["line_width"]))
        self.line_color_btn = self._make_color_button(DEFAULT_STYLE["line_color"])
        self.outer_line_width = QSpinBox()
        self.outer_line_width.setRange(1, 10)
        self.outer_line_width.setValue(DEFAULT_STYLE["outer_line_width"])
        self.outer_line_color_btn = self._make_color_button(
            DEFAULT_STYLE["outer_line_color"]
        )
        form.addRow("Inner Width:", self.line_width)
        form.addRow("Inner Color:", self.line_color_btn)
        form.addRow("Outer Width:", self.outer_line_width)
        form.addRow("Outer Color:", self.outer_line_color_btn)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("line"))
        self.tabs.addTab(tab, "Trace Style")

    def reset_defaults(self, section):
        defaults = {
            "axis": {
                "axis_font_size": DEFAULT_STYLE["axis_font_size"],
                "axis_font_family": DEFAULT_STYLE["axis_font_family"],
                "axis_bold": DEFAULT_STYLE["axis_bold"],
                "axis_italic": DEFAULT_STYLE["axis_italic"],
                "axis_color": DEFAULT_STYLE["axis_color"],
            },
            "tick": {
                "tick_font_size": DEFAULT_STYLE["tick_font_size"],
                "tick_color": DEFAULT_STYLE["tick_color"],
            },
            "event": {
                "event_font_size": DEFAULT_STYLE["event_font_size"],
                "event_font_family": DEFAULT_STYLE["event_font_family"],
                "event_bold": DEFAULT_STYLE["event_bold"],
                "event_italic": DEFAULT_STYLE["event_italic"],
                "event_color": DEFAULT_STYLE["event_color"],
            },
            "pin": {
                "pin_font_size": DEFAULT_STYLE["pin_font_size"],
                "pin_font_family": DEFAULT_STYLE["pin_font_family"],
                "pin_bold": DEFAULT_STYLE["pin_bold"],
                "pin_italic": DEFAULT_STYLE["pin_italic"],
                "pin_size": DEFAULT_STYLE["pin_size"],
                "pin_color": DEFAULT_STYLE["pin_color"],
            },
            "line": {
                "line_width": DEFAULT_STYLE["line_width"],
                "line_color": DEFAULT_STYLE["line_color"],
                "outer_line_width": DEFAULT_STYLE["outer_line_width"],
                "outer_line_color": DEFAULT_STYLE["outer_line_color"],
            },
        }
        for attr, val in defaults[section].items():
            widget = getattr(self, attr)
            if isinstance(widget, QSpinBox):
                widget.setValue(val)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(val)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(val)
            elif isinstance(widget, QPushButton) and hasattr(widget, "color"):
                self._set_button_color(widget, val)

    def get_style(self):
        return {
            "axis_font_size": self.axis_font_size.value(),
            "axis_font_family": self.axis_font_family.currentText(),
            "axis_bold": self.axis_bold.isChecked(),
            "axis_italic": self.axis_italic.isChecked(),
            "axis_color": self.axis_color_btn.color,
            "tick_font_size": self.tick_font_size.value(),
            "tick_color": self.tick_color_btn.color,
            "event_font_size": self.event_font_size.value(),
            "event_font_family": self.event_font_family.currentText(),
            "event_bold": self.event_bold.isChecked(),
            "event_italic": self.event_italic.isChecked(),
            "event_color": self.event_color_btn.color,
            "pin_font_size": self.pin_font_size.value(),
            "pin_font_family": self.pin_font_family.currentText(),
            "pin_bold": self.pin_bold.isChecked(),
            "pin_italic": self.pin_italic.isChecked(),
            "pin_size": self.pin_size.value(),
            "pin_color": self.pin_color_btn.color,
            "line_width": self.line_width.value(),
            "line_color": self.line_color_btn.color,
            "outer_line_width": self.outer_line_width.value(),
            "outer_line_color": self.outer_line_color_btn.color,
        }

    def set_style(self, style):
        """Populate widgets based on a style dictionary."""
        for key, val in style.items():
            if not hasattr(self, key):
                continue
            widget = getattr(self, key)
            if isinstance(widget, QSpinBox):
                widget.setValue(int(val))
            elif isinstance(widget, QComboBox):
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                else:
                    widget.setCurrentText(str(val))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(val))
            elif isinstance(widget, QPushButton) and hasattr(widget, "color"):
                self._set_button_color(widget, val)
