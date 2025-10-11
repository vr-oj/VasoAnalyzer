# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# PlotStyleEditor - redesigned dialog with live preview
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QPushButton,
    QDialogButtonBox,
)
from ..constants import DEFAULT_STYLE
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class PlotStyleEditor(QDialog):
    """Dialog for adjusting plot fonts, colors and line styles."""

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setFont(QFont("Arial", 10))
        self.initial = initial or {}
        self.apply_callback = None

        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(8)

        # Tabs
        tabs = QTabWidget()
        main.addWidget(tabs, 1)
        self.tabs = tabs
        self._tab_aliases = {}

        def register_tab(widget, title, aliases):
            widget.setObjectName(title.replace(" ", "") + "Tab")
            index = self.tabs.addTab(widget, title)
            for alias in {title.lower(), *aliases}:
                self._tab_aliases[alias] = index

        register_tab(
            self._make_axis_titles_tab(),
            "Axis Titles",
            {"axis", "axis_titles", "titles"},
        )
        register_tab(
            self._make_tick_labels_tab(),
            "Tick Labels",
            {"tick", "ticks", "tick_labels"},
        )
        register_tab(
            self._make_event_labels_tab(),
            "Event Labels",
            {"event", "events", "event_labels"},
        )
        register_tab(
            self._make_pinned_labels_tab(),
            "Pinned Labels",
            {"pinned", "pins", "pinned_labels"},
        )
        register_tab(
            self._make_trace_style_tab(),
            "Trace Style",
            {"trace", "traces", "trace_style", "line", "lines"},
        )
        register_tab(
            self._make_highlights_tab(),
            "Highlights",
            {"highlight", "highlights", "event_highlight"},
        )

        # Preview canvas
        dpi = QApplication.primaryScreen().logicalDotsPerInch()
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(3, 2), dpi=dpi))
        self.ax = self.canvas.figure.subplots()
        main.addWidget(self.canvas, 1)
        self._update_preview()

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply
            | QDialogButtonBox.Reset
            | QDialogButtonBox.RestoreDefaults
            | QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._reset)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._defaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self._updating = False

    # ------------------------------------------------------------------
    # Tab builders
    def _make_axis_titles_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Axis Title Font & Color")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.axis_font_size = QSpinBox()
        self.axis_font_size.setRange(6, 48)
        self.axis_font_size.setValue(
            int(round(self.initial.get("axis_font_size", DEFAULT_STYLE["axis_font_size"])))
        )
        self.axis_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.axis_font_size)

        self.axis_font_family = QComboBox()
        self.axis_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier New"]
        )
        self.axis_font_family.setCurrentText(
            self.initial.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
        )
        self.axis_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.axis_font_family)

        self.axis_bold = QCheckBox("Bold")
        self.axis_bold.setChecked(
            self.initial.get("axis_bold", DEFAULT_STYLE["axis_bold"])
        )
        self.axis_bold.stateChanged.connect(self._on_change)
        self.axis_italic = QCheckBox("Italic")
        self.axis_italic.setChecked(
            self.initial.get("axis_italic", DEFAULT_STYLE["axis_italic"])
        )
        self.axis_italic.stateChanged.connect(self._on_change)
        form.addRow(self.axis_bold, self.axis_italic)

        self.axis_color = QPushButton()
        self.axis_color.setFixedWidth(60)
        self._set_button_color(
            self.axis_color,
            self.initial.get("axis_color", DEFAULT_STYLE["axis_color"]),
        )
        self.axis_color.clicked.connect(
            lambda: self._choose_color(self.axis_color, self._on_change)
        )
        form.addRow("Color:", self.axis_color)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_tick_labels_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Tick Label Style")
        form = QFormLayout()

        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(
            int(
                round(
                    self.initial.get(
                        "tick_font_size", DEFAULT_STYLE["tick_font_size"]
                    )
                )
            )
        )
        self.tick_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.tick_font_size)

        self.tick_color = QPushButton()
        self.tick_color.setFixedWidth(60)
        self._set_button_color(
            self.tick_color,
            self.initial.get("tick_color", DEFAULT_STYLE["tick_color"]),
        )
        self.tick_color.clicked.connect(
            lambda: self._choose_color(self.tick_color, self._on_change)
        )
        form.addRow("Color:", self.tick_color)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_event_labels_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Event Label Style")
        form = QFormLayout()

        self.event_font_size = QSpinBox()
        self.event_font_size.setRange(6, 32)
        self.event_font_size.setValue(
            int(
                round(
                    self.initial.get(
                        "event_font_size", DEFAULT_STYLE["event_font_size"]
                    )
                )
            )
        )
        self.event_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.event_font_size)

        self.event_font_family = QComboBox()
        self.event_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier New"]
        )
        self.event_font_family.setCurrentText(
            self.initial.get("event_font_family", DEFAULT_STYLE["event_font_family"])
        )
        self.event_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.event_font_family)

        self.event_bold = QCheckBox("Bold")
        self.event_bold.setChecked(
            self.initial.get("event_bold", DEFAULT_STYLE["event_bold"])
        )
        self.event_bold.stateChanged.connect(self._on_change)
        self.event_italic = QCheckBox("Italic")
        self.event_italic.setChecked(
            self.initial.get("event_italic", DEFAULT_STYLE["event_italic"])
        )
        self.event_italic.stateChanged.connect(self._on_change)
        form.addRow(self.event_bold, self.event_italic)

        self.event_color = QPushButton()
        self.event_color.setFixedWidth(60)
        self._set_button_color(
            self.event_color,
            self.initial.get("event_color", DEFAULT_STYLE["event_color"]),
        )
        self.event_color.clicked.connect(
            lambda: self._choose_color(self.event_color, self._on_change)
        )
        form.addRow("Color:", self.event_color)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_pinned_labels_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Pinned Label Style")
        form = QFormLayout()

        self.pin_font_size = QSpinBox()
        self.pin_font_size.setRange(6, 32)
        self.pin_font_size.setValue(
            int(
                round(
                    self.initial.get("pin_font_size", DEFAULT_STYLE["pin_font_size"])
                )
            )
        )
        self.pin_font_size.valueChanged.connect(self._on_change)
        form.addRow("Font Size:", self.pin_font_size)

        self.pin_font_family = QComboBox()
        self.pin_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier New"]
        )
        self.pin_font_family.setCurrentText(
            self.initial.get("pin_font_family", DEFAULT_STYLE["pin_font_family"])
        )
        self.pin_font_family.currentIndexChanged.connect(self._on_change)
        form.addRow("Font Family:", self.pin_font_family)

        self.pin_bold = QCheckBox("Bold")
        self.pin_bold.setChecked(
            self.initial.get("pin_bold", DEFAULT_STYLE["pin_bold"])
        )
        self.pin_bold.stateChanged.connect(self._on_change)
        self.pin_italic = QCheckBox("Italic")
        self.pin_italic.setChecked(
            self.initial.get("pin_italic", DEFAULT_STYLE["pin_italic"])
        )
        self.pin_italic.stateChanged.connect(self._on_change)
        form.addRow(self.pin_bold, self.pin_italic)

        self.pin_color = QPushButton()
        self.pin_color.setFixedWidth(60)
        self._set_button_color(
            self.pin_color,
            self.initial.get("pin_color", DEFAULT_STYLE["pin_color"]),
        )
        self.pin_color.clicked.connect(
            lambda: self._choose_color(self.pin_color, self._on_change)
        )
        form.addRow("Color:", self.pin_color)

        self.pin_size = QSpinBox()
        self.pin_size.setRange(2, 20)
        self.pin_size.setValue(
            int(
                round(
                    self.initial.get("pin_size", DEFAULT_STYLE["pin_size"])
                )
            )
        )
        self.pin_size.valueChanged.connect(self._on_change)
        form.addRow("Marker Size:", self.pin_size)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    def _make_trace_style_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp_in = QGroupBox("Inner Trace Style")
        form_in = QFormLayout()
        self.line_width = QDoubleSpinBox()
        self.line_width.setRange(0.5, 10)
        self.line_width.setValue(
            self.initial.get("line_width", DEFAULT_STYLE["line_width"])
        )
        self.line_width.valueChanged.connect(self._on_change)
        form_in.addRow("Line Width:", self.line_width)

        styles = ["Solid", "Dashed", "Dotted", "DashDot"]
        self.line_style = QComboBox()
        self.line_style.addItems(styles)
        self.line_style.setCurrentText(
            self.initial.get("line_style", DEFAULT_STYLE.get("line_style", "solid")).capitalize()
        )
        self.line_style.currentIndexChanged.connect(self._on_change)
        form_in.addRow("Line Style:", self.line_style)

        self.line_color = QPushButton()
        self.line_color.setFixedWidth(60)
        self._set_button_color(
            self.line_color,
            self.initial.get("line_color", DEFAULT_STYLE["line_color"]),
        )
        self.line_color.clicked.connect(
            lambda: self._choose_color(self.line_color, self._on_change)
        )
        form_in.addRow("Color:", self.line_color)
        grp_in.setLayout(form_in)
        layout.addWidget(grp_in)

        grp_out = QGroupBox("Outer Trace Style")
        form_out = QFormLayout()
        self.outer_line_width = QDoubleSpinBox()
        self.outer_line_width.setRange(0.5, 10)
        self.outer_line_width.setValue(
            self.initial.get("outer_line_width", DEFAULT_STYLE["outer_line_width"])
        )
        self.outer_line_width.valueChanged.connect(self._on_change)
        form_out.addRow("Line Width:", self.outer_line_width)

        self.outer_line_style = QComboBox()
        self.outer_line_style.addItems(styles)
        self.outer_line_style.setCurrentText(
            self.initial.get(
                "outer_line_style",
                DEFAULT_STYLE.get("outer_line_style", "solid"),
            ).capitalize()
        )
        self.outer_line_style.currentIndexChanged.connect(self._on_change)
        form_out.addRow("Line Style:", self.outer_line_style)

        self.outer_line_color = QPushButton()
        self.outer_line_color.setFixedWidth(60)
        self._set_button_color(
            self.outer_line_color,
            self.initial.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
        )
        self.outer_line_color.clicked.connect(
            lambda: self._choose_color(self.outer_line_color, self._on_change)
        )
        form_out.addRow("Color:", self.outer_line_color)
        grp_out.setLayout(form_out)
        layout.addWidget(grp_out)

        layout.addStretch()
        return w

    def _make_highlights_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Event Highlight")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.event_highlight_color_btn = QPushButton()
        self.event_highlight_color_btn.setFixedWidth(60)
        self._set_button_color(
            self.event_highlight_color_btn,
            self.initial.get(
                "event_highlight_color",
                DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF"),
            ),
        )
        self.event_highlight_color_btn.clicked.connect(
            lambda: self._choose_color(self.event_highlight_color_btn, self._on_change)
        )
        form.addRow("Color:", self.event_highlight_color_btn)

        self.event_highlight_alpha_spin = QDoubleSpinBox()
        self.event_highlight_alpha_spin.setRange(0.0, 1.0)
        self.event_highlight_alpha_spin.setSingleStep(0.05)
        self.event_highlight_alpha_spin.setDecimals(2)
        self.event_highlight_alpha_spin.setValue(
            float(
                self.initial.get(
                    "event_highlight_alpha",
                    DEFAULT_STYLE.get("event_highlight_alpha", 0.95),
                )
            )
        )
        self.event_highlight_alpha_spin.valueChanged.connect(self._on_change)
        form.addRow("Base Opacity:", self.event_highlight_alpha_spin)

        self.event_highlight_duration_spin = QSpinBox()
        self.event_highlight_duration_spin.setRange(0, 60000)
        self.event_highlight_duration_spin.setSingleStep(100)
        self.event_highlight_duration_spin.setSuffix(" ms")
        self.event_highlight_duration_spin.setValue(
            int(
                self.initial.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
                )
            )
        )
        self.event_highlight_duration_spin.valueChanged.connect(self._on_change)
        form.addRow("Fade Duration:", self.event_highlight_duration_spin)

        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # Helpers
    def _set_button_color(self, btn, hexcolor):
        btn.setStyleSheet(f"background:{hexcolor};border:1px solid #888;")
        btn.setProperty("color", hexcolor)

    def _choose_color(self, btn, callback):
        from PyQt5.QtWidgets import QColorDialog

        col = QColorDialog.getColor(QColor(btn.property("color")), self)
        if col.isValid():
            self._set_button_color(btn, col.name())
            callback()

    def _on_change(self):
        if self._updating:
            return
        style = self._gather()
        if callable(self.apply_callback):
            self.apply_callback(style)
        elif self.parent() is not None and hasattr(self.parent(), "apply_plot_style"):
            self.parent().apply_plot_style(style)
        self._update_preview()

    def _populate(self, style):
        self._updating = True
        self.axis_font_size.setValue(
            int(round(style.get("axis_font_size", DEFAULT_STYLE["axis_font_size"])))
        )
        self.axis_font_family.setCurrentText(
            style.get("axis_font_family", DEFAULT_STYLE["axis_font_family"])
        )
        self.axis_bold.setChecked(
            style.get("axis_bold", DEFAULT_STYLE["axis_bold"])
        )
        self.axis_italic.setChecked(
            style.get("axis_italic", DEFAULT_STYLE["axis_italic"])
        )
        self._set_button_color(
            self.axis_color, style.get("axis_color", DEFAULT_STYLE["axis_color"])
        )

        self.tick_font_size.setValue(
            int(round(style.get("tick_font_size", DEFAULT_STYLE["tick_font_size"])))
        )
        self._set_button_color(
            self.tick_color, style.get("tick_color", DEFAULT_STYLE["tick_color"])
        )

        self.event_font_size.setValue(
            int(round(style.get("event_font_size", DEFAULT_STYLE["event_font_size"])))
        )
        self.event_font_family.setCurrentText(
            style.get("event_font_family", DEFAULT_STYLE["event_font_family"])
        )
        self.event_bold.setChecked(
            style.get("event_bold", DEFAULT_STYLE["event_bold"])
        )
        self.event_italic.setChecked(
            style.get("event_italic", DEFAULT_STYLE["event_italic"])
        )
        self._set_button_color(
            self.event_color, style.get("event_color", DEFAULT_STYLE["event_color"])
        )

        self.pin_font_size.setValue(
            int(round(style.get("pin_font_size", DEFAULT_STYLE["pin_font_size"])))
        )
        self.pin_font_family.setCurrentText(
            style.get("pin_font_family", DEFAULT_STYLE["pin_font_family"])
        )
        self.pin_bold.setChecked(
            style.get("pin_bold", DEFAULT_STYLE["pin_bold"])
        )
        self.pin_italic.setChecked(
            style.get("pin_italic", DEFAULT_STYLE["pin_italic"])
        )
        self._set_button_color(
            self.pin_color, style.get("pin_color", DEFAULT_STYLE["pin_color"])
        )
        self.pin_size.setValue(
            int(round(style.get("pin_size", DEFAULT_STYLE["pin_size"])))
        )

        self.line_width.setValue(style.get("line_width", DEFAULT_STYLE["line_width"]))
        self.line_style.setCurrentText(
            style.get("line_style", DEFAULT_STYLE.get("line_style", "solid")).capitalize()
        )
        self._set_button_color(
            self.line_color, style.get("line_color", DEFAULT_STYLE["line_color"])
        )
        self.outer_line_width.setValue(
            style.get("outer_line_width", DEFAULT_STYLE["outer_line_width"])
        )
        self.outer_line_style.setCurrentText(
            style.get(
                "outer_line_style",
                DEFAULT_STYLE.get("outer_line_style", "solid"),
            ).capitalize()
        )
        self._set_button_color(
            self.outer_line_color,
            style.get("outer_line_color", DEFAULT_STYLE["outer_line_color"]),
        )
        self._set_button_color(
            self.event_highlight_color_btn,
            style.get(
                "event_highlight_color",
                DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF"),
            ),
        )
        self.event_highlight_alpha_spin.setValue(
            float(
                style.get(
                    "event_highlight_alpha",
                    DEFAULT_STYLE.get("event_highlight_alpha", 0.95),
                )
            )
        )
        self.event_highlight_duration_spin.setValue(
            int(
                style.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
                )
            )
        )
        self._updating = False
        self._update_preview()

    def _gather(self):
        return {
            "axis_font_size": self.axis_font_size.value(),
            "axis_font_family": self.axis_font_family.currentText(),
            "axis_bold": self.axis_bold.isChecked(),
            "axis_italic": self.axis_italic.isChecked(),
            "axis_color": self.axis_color.property("color"),
            "tick_font_size": self.tick_font_size.value(),
            "tick_color": self.tick_color.property("color"),
            "event_font_size": self.event_font_size.value(),
            "event_font_family": self.event_font_family.currentText(),
            "event_bold": self.event_bold.isChecked(),
            "event_italic": self.event_italic.isChecked(),
            "event_color": self.event_color.property("color"),
            "pin_font_size": self.pin_font_size.value(),
            "pin_font_family": self.pin_font_family.currentText(),
            "pin_bold": self.pin_bold.isChecked(),
            "pin_italic": self.pin_italic.isChecked(),
            "pin_color": self.pin_color.property("color"),
            "pin_size": self.pin_size.value(),
            "line_width": self.line_width.value(),
            "line_style": self.line_style.currentText().lower(),
            "line_color": self.line_color.property("color"),
            "outer_line_width": self.outer_line_width.value(),
            "outer_line_style": self.outer_line_style.currentText().lower(),
            "outer_line_color": self.outer_line_color.property("color"),
            "event_highlight_color": self.event_highlight_color_btn.property("color"),
            "event_highlight_alpha": self.event_highlight_alpha_spin.value(),
            "event_highlight_duration_ms": self.event_highlight_duration_spin.value(),
        }

    def get_style(self):
        """Public accessor for the current style settings."""
        return self._gather()

    def set_style(self, style):
        """Update the dialog controls to reflect ``style``."""
        self._populate(style)

    def _apply(self):
        params = self._gather()
        if callable(self.apply_callback):
            self.apply_callback(params)
        elif self.parent() is not None and hasattr(self.parent(), "apply_plot_style"):
            self.parent().apply_plot_style(params)
        self._update_preview()

    def _reset(self):
        self._populate(self.initial)

    def _defaults(self):
        self._populate(DEFAULT_STYLE)

    def select_tab(self, key):
        """Focus the tab matching ``key`` if available."""

        if not key:
            return
        key = str(key).strip().lower()
        index = self._tab_aliases.get(key)
        if index is None:
            for alias, idx in self._tab_aliases.items():
                if key in alias:
                    index = idx
                    break
        if index is not None:
            self.tabs.setCurrentIndex(index)

    def _update_preview(self):
        p = self._gather()
        self.ax.clear()
        x = [0, 1, 2, 3, 4]
        self.ax.plot(
            x,
            x,
            linewidth=p["line_width"],
            color=p["line_color"],
            linestyle=p.get("line_style", "solid"),
        )
        self.ax.plot(
            x,
            [4 - i for i in x],
            linewidth=p["outer_line_width"],
            color=p["outer_line_color"],
            linestyle=p.get("outer_line_style", "solid"),
        )
        for lbl in (self.ax.xaxis.get_label(), self.ax.yaxis.get_label()):
            lbl.set_fontsize(p["axis_font_size"])
            lbl.set_fontfamily(p["axis_font_family"])
            lbl.set_fontweight("bold" if p["axis_bold"] else "normal")
            lbl.set_fontstyle("italic" if p["axis_italic"] else "normal")
            lbl.set_color(p["axis_color"])
        for tick in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            tick.set_fontsize(p["tick_font_size"])
            tick.set_color(p["tick_color"])
        self.canvas.draw_idle()
