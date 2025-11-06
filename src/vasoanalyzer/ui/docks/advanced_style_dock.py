"""Advanced style controls dock with tabbed interface."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.constants import FACTORY_STYLE_DEFAULTS
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["AdvancedStyleDock"]


class AdvancedStyleDock(QDockWidget):
    """
    Dockable panel for advanced style controls.

    Provides tabbed interface for:
    - Canvas (DPI, size, background)
    - Axes (titles, labels, fonts, colors)
    - Lines (width, style, colors)
    - Events (label font, mode, clustering)
    - Typography (font families, sizes)
    - Colors (axis colors, event colors)
    """

    # Signal emitted when style changes
    style_changed = pyqtSignal(dict)

    # Signal emitted when user clicks Apply
    apply_requested = pyqtSignal()

    # Signal emitted when user clicks Revert
    revert_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Advanced Style", parent)
        self.setObjectName("AdvancedStyleDock")

        # Current style dictionary (nested structure)
        self._style: dict[str, Any] = self._flat_to_nested(FACTORY_STYLE_DEFAULTS)

        # Font choices
        self._font_families = [
            "Arial",
            "Helvetica",
            "Times New Roman",
            "Courier New",
            "DejaVu Sans",
        ]

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ Public API

    def set_style(self, style: dict[str, Any]) -> None:
        """Update style controls from dictionary (expects flat structure)."""
        self._style = self._flat_to_nested(style)
        self._populate_controls()

    def get_style(self) -> dict[str, Any]:
        """Get current style from controls (returns flat structure)."""
        return self._nested_to_flat(self._style)

    # ------------------------------------------------------------------ Style Conversion

    def _flat_to_nested(self, flat_style: dict[str, Any]) -> dict[str, Any]:
        """Convert flat style dictionary to nested structure for internal use."""
        nested: dict[str, Any] = {
            "axis": {
                "font": {
                    "family": flat_style.get("axis_font_family", "Arial"),
                    "size": flat_style.get("axis_font_size", 12),
                    "bold": flat_style.get("axis_bold", False),
                    "italic": flat_style.get("axis_italic", False),
                }
            },
            "ticks": {
                "font_size": flat_style.get("tick_font_size", 10),
                "length": flat_style.get("tick_length", 4.0),
                "width": flat_style.get("tick_width", 1.0),
            },
            "lines": {
                "inner_width": flat_style.get("line_width", 1.5),
                "inner_color": flat_style.get("line_color", "#000000"),
                "outer_width": flat_style.get("outer_line_width", 1.5),
                "outer_color": flat_style.get("outer_line_color", "tab:orange"),
            },
            "events": {
                "font": {
                    "family": flat_style.get("event_font_family", "Arial"),
                    "size": flat_style.get("event_font_size", 15.0),
                    "bold": flat_style.get("event_bold", False),
                    "italic": flat_style.get("event_italic", False),
                },
                "mode": flat_style.get("event_label_mode", "vertical"),
                "max_per_cluster": flat_style.get("event_label_max_per_cluster", 1),
                "lanes": flat_style.get("event_label_lanes", 3),
                "outline_enabled": flat_style.get("event_label_outline_enabled", True),
                "outline_width": flat_style.get("event_label_outline_width", 2.0),
            },
        }
        return nested

    def _nested_to_flat(self, nested_style: dict[str, Any]) -> dict[str, Any]:
        """Convert nested style dictionary to flat structure for external use."""
        axis = nested_style.get("axis", {})
        axis_font = axis.get("font", {})
        ticks = nested_style.get("ticks", {})
        lines = nested_style.get("lines", {})
        events = nested_style.get("events", {})
        event_font = events.get("font", {})

        flat: dict[str, Any] = {
            # Axis fonts
            "axis_font_family": axis_font.get("family", "Arial"),
            "axis_font_size": axis_font.get("size", 12),
            "axis_bold": axis_font.get("bold", False),
            "axis_italic": axis_font.get("italic", False),
            # Ticks
            "tick_font_size": ticks.get("font_size", 10),
            "tick_length": ticks.get("length", 4.0),
            "tick_width": ticks.get("width", 1.0),
            # Lines
            "line_width": lines.get("inner_width", 1.5),
            "line_color": lines.get("inner_color", "#000000"),
            "outer_line_width": lines.get("outer_width", 1.5),
            "outer_line_color": lines.get("outer_color", "tab:orange"),
            # Events
            "event_font_family": event_font.get("family", "Arial"),
            "event_font_size": event_font.get("size", 15.0),
            "event_bold": event_font.get("bold", False),
            "event_italic": event_font.get("italic", False),
            "event_label_mode": events.get("mode", "vertical"),
            "event_label_max_per_cluster": events.get("max_per_cluster", 1),
            "event_label_lanes": events.get("lanes", 3),
            "event_label_outline_enabled": events.get("outline_enabled", True),
            "event_label_outline_width": events.get("outline_width", 2.0),
        }
        return flat

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dock UI with tabs."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Create tabs
        self._create_axis_tab()
        self._create_lines_tab()
        self._create_events_tab()

        # Action buttons
        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setToolTip("Apply current style settings")
        self.apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(self.apply_btn)

        self.revert_btn = QPushButton("Revert")
        self.revert_btn.setToolTip("Revert to previous style")
        self.revert_btn.clicked.connect(self._on_revert)
        button_layout.addWidget(self.revert_btn)

        layout.addLayout(button_layout)

        self.setWidget(container)

    def _create_axis_tab(self) -> None:
        """Create Axis settings tab."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(8)

        # Axis titles group
        titles_group = QGroupBox("Axis Titles")
        titles_form = QFormLayout(titles_group)

        self.axis_title_font_combo = QComboBox()
        self.axis_title_font_combo.addItems(self._font_families)
        self.axis_title_font_combo.currentTextChanged.connect(self._on_axis_title_font_changed)
        titles_form.addRow("Font Family:", self.axis_title_font_combo)

        self.axis_title_size_spin = QSpinBox()
        self.axis_title_size_spin.setRange(6, 48)
        self.axis_title_size_spin.setValue(12)
        self.axis_title_size_spin.valueChanged.connect(self._on_axis_title_size_changed)
        titles_form.addRow("Font Size:", self.axis_title_size_spin)

        self.axis_title_bold_check = QCheckBox("Bold")
        self.axis_title_bold_check.toggled.connect(self._on_axis_title_bold_changed)
        titles_form.addRow("", self.axis_title_bold_check)

        self.axis_title_italic_check = QCheckBox("Italic")
        self.axis_title_italic_check.toggled.connect(self._on_axis_title_italic_changed)
        titles_form.addRow("", self.axis_title_italic_check)

        tab_layout.addWidget(titles_group)

        # Ticks group
        ticks_group = QGroupBox("Tick Labels")
        ticks_form = QFormLayout(ticks_group)

        self.tick_font_size_spin = QSpinBox()
        self.tick_font_size_spin.setRange(6, 24)
        self.tick_font_size_spin.setValue(10)
        self.tick_font_size_spin.valueChanged.connect(self._on_tick_font_size_changed)
        ticks_form.addRow("Font Size:", self.tick_font_size_spin)

        self.tick_length_spin = QDoubleSpinBox()
        self.tick_length_spin.setRange(0.0, 20.0)
        self.tick_length_spin.setValue(4.0)
        self.tick_length_spin.setSingleStep(0.5)
        self.tick_length_spin.valueChanged.connect(self._on_tick_length_changed)
        ticks_form.addRow("Tick Length:", self.tick_length_spin)

        self.tick_width_spin = QDoubleSpinBox()
        self.tick_width_spin.setRange(0.0, 10.0)
        self.tick_width_spin.setValue(1.0)
        self.tick_width_spin.setSingleStep(0.1)
        self.tick_width_spin.valueChanged.connect(self._on_tick_width_changed)
        ticks_form.addRow("Tick Width:", self.tick_width_spin)

        tab_layout.addWidget(ticks_group)
        tab_layout.addStretch(1)

        scroll.setWidget(tab_widget)
        self.tabs.addTab(scroll, "Axes")

    def _create_lines_tab(self) -> None:
        """Create Lines settings tab."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(8)

        # Line width group
        lines_group = QGroupBox("Trace Lines")
        lines_form = QFormLayout(lines_group)

        self.inner_line_width_spin = QDoubleSpinBox()
        self.inner_line_width_spin.setRange(0.1, 10.0)
        self.inner_line_width_spin.setValue(1.5)
        self.inner_line_width_spin.setSingleStep(0.1)
        self.inner_line_width_spin.valueChanged.connect(self._on_inner_line_width_changed)
        lines_form.addRow("Inner Width:", self.inner_line_width_spin)

        self.outer_line_width_spin = QDoubleSpinBox()
        self.outer_line_width_spin.setRange(0.1, 10.0)
        self.outer_line_width_spin.setValue(1.5)
        self.outer_line_width_spin.setSingleStep(0.1)
        self.outer_line_width_spin.valueChanged.connect(self._on_outer_line_width_changed)
        lines_form.addRow("Outer Width:", self.outer_line_width_spin)

        # Color pickers
        self.inner_line_color_btn = QPushButton("Choose Color")
        self.inner_line_color_btn.clicked.connect(self._on_inner_line_color_clicked)
        lines_form.addRow("Inner Color:", self.inner_line_color_btn)

        self.outer_line_color_btn = QPushButton("Choose Color")
        self.outer_line_color_btn.clicked.connect(self._on_outer_line_color_clicked)
        lines_form.addRow("Outer Color:", self.outer_line_color_btn)

        tab_layout.addWidget(lines_group)
        tab_layout.addStretch(1)

        scroll.setWidget(tab_widget)
        self.tabs.addTab(scroll, "Lines")

    def _create_events_tab(self) -> None:
        """Create Event Labels settings tab."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(8)

        # Event label font group
        events_group = QGroupBox("Event Labels")
        events_form = QFormLayout(events_group)

        self.event_font_combo = QComboBox()
        self.event_font_combo.addItems(self._font_families)
        self.event_font_combo.currentTextChanged.connect(self._on_event_font_changed)
        events_form.addRow("Font Family:", self.event_font_combo)

        self.event_font_size_spin = QDoubleSpinBox()
        self.event_font_size_spin.setRange(6.0, 48.0)
        self.event_font_size_spin.setValue(15.0)
        self.event_font_size_spin.setSingleStep(0.5)
        self.event_font_size_spin.valueChanged.connect(self._on_event_font_size_changed)
        events_form.addRow("Font Size:", self.event_font_size_spin)

        self.event_font_bold_check = QCheckBox("Bold")
        self.event_font_bold_check.toggled.connect(self._on_event_font_bold_changed)
        events_form.addRow("", self.event_font_bold_check)

        self.event_font_italic_check = QCheckBox("Italic")
        self.event_font_italic_check.toggled.connect(self._on_event_font_italic_changed)
        events_form.addRow("", self.event_font_italic_check)

        # Event label mode
        self.event_mode_combo = QComboBox()
        self.event_mode_combo.addItems(["Vertical", "Horizontal", "Outside"])
        self.event_mode_combo.currentTextChanged.connect(self._on_event_mode_changed)
        events_form.addRow("Label Mode:", self.event_mode_combo)

        # Clustering
        self.event_max_per_cluster_spin = QSpinBox()
        self.event_max_per_cluster_spin.setRange(1, 20)
        self.event_max_per_cluster_spin.setValue(1)
        self.event_max_per_cluster_spin.valueChanged.connect(self._on_event_max_per_cluster_changed)
        events_form.addRow("Max Per Cluster:", self.event_max_per_cluster_spin)

        # Lanes
        self.event_lanes_spin = QSpinBox()
        self.event_lanes_spin.setRange(1, 10)
        self.event_lanes_spin.setValue(3)
        self.event_lanes_spin.valueChanged.connect(self._on_event_lanes_changed)
        events_form.addRow("Label Lanes:", self.event_lanes_spin)

        # Outline
        self.event_outline_check = QCheckBox("Enable label outline")
        self.event_outline_check.setChecked(True)
        self.event_outline_check.toggled.connect(self._on_event_outline_changed)
        events_form.addRow("", self.event_outline_check)

        self.event_outline_width_spin = QDoubleSpinBox()
        self.event_outline_width_spin.setRange(0.0, 10.0)
        self.event_outline_width_spin.setValue(2.0)
        self.event_outline_width_spin.setSingleStep(0.1)
        self.event_outline_width_spin.valueChanged.connect(self._on_event_outline_width_changed)
        events_form.addRow("Outline Width:", self.event_outline_width_spin)

        tab_layout.addWidget(events_group)
        tab_layout.addStretch(1)

        scroll.setWidget(tab_widget)
        self.tabs.addTab(scroll, "Events")

    def _apply_theme(self) -> None:
        """Apply current theme to dock."""
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text = CURRENT_THEME.get("text", "#000000")
        self.setStyleSheet(f"""
            QDockWidget {{
                background-color: {bg};
                color: {text};
            }}
        """)

    # ------------------------------------------------------------------ Control Population

    def _populate_controls(self) -> None:
        """Populate controls from current style dictionary."""
        # Axis settings
        axis_style = self._style.get("axis", {})
        font_style = axis_style.get("font", {})
        self.axis_title_font_combo.setCurrentText(font_style.get("family", "Arial"))
        self.axis_title_size_spin.setValue(font_style.get("size", 12))
        self.axis_title_bold_check.setChecked(font_style.get("bold", False))
        self.axis_title_italic_check.setChecked(font_style.get("italic", False))

        # Ticks
        ticks_style = self._style.get("ticks", {})
        self.tick_font_size_spin.setValue(ticks_style.get("font_size", 10))
        self.tick_length_spin.setValue(ticks_style.get("length", 4.0))
        self.tick_width_spin.setValue(ticks_style.get("width", 1.0))

        # Lines
        lines_style = self._style.get("lines", {})
        self.inner_line_width_spin.setValue(lines_style.get("inner_width", 1.5))
        self.outer_line_width_spin.setValue(lines_style.get("outer_width", 1.5))

        # Events
        events_style = self._style.get("events", {})
        event_font = events_style.get("font", {})
        self.event_font_combo.setCurrentText(event_font.get("family", "Arial"))
        self.event_font_size_spin.setValue(event_font.get("size", 15.0))
        self.event_font_bold_check.setChecked(event_font.get("bold", False))
        self.event_font_italic_check.setChecked(event_font.get("italic", False))

        mode_map = {"vertical": "Vertical", "horizontal": "Horizontal", "outside": "Outside"}
        mode = events_style.get("mode", "vertical")
        self.event_mode_combo.setCurrentText(mode_map.get(mode, "Vertical"))

        self.event_max_per_cluster_spin.setValue(events_style.get("max_per_cluster", 1))
        self.event_lanes_spin.setValue(events_style.get("lanes", 3))
        self.event_outline_check.setChecked(events_style.get("outline_enabled", True))
        self.event_outline_width_spin.setValue(events_style.get("outline_width", 2.0))

    # ------------------------------------------------------------------ Signal Handlers

    def _on_axis_title_font_changed(self, family: str) -> None:
        self._style.setdefault("axis", {}).setdefault("font", {})["family"] = family
        self.style_changed.emit(self._style)

    def _on_axis_title_size_changed(self, size: int) -> None:
        self._style.setdefault("axis", {}).setdefault("font", {})["size"] = size
        self.style_changed.emit(self._style)

    def _on_axis_title_bold_changed(self, bold: bool) -> None:
        self._style.setdefault("axis", {}).setdefault("font", {})["bold"] = bold
        self.style_changed.emit(self._style)

    def _on_axis_title_italic_changed(self, italic: bool) -> None:
        self._style.setdefault("axis", {}).setdefault("font", {})["italic"] = italic
        self.style_changed.emit(self._style)

    def _on_tick_font_size_changed(self, size: int) -> None:
        self._style.setdefault("ticks", {})["font_size"] = size
        self.style_changed.emit(self._style)

    def _on_tick_length_changed(self, length: float) -> None:
        self._style.setdefault("ticks", {})["length"] = length
        self.style_changed.emit(self._style)

    def _on_tick_width_changed(self, width: float) -> None:
        self._style.setdefault("ticks", {})["width"] = width
        self.style_changed.emit(self._style)

    def _on_inner_line_width_changed(self, width: float) -> None:
        self._style.setdefault("lines", {})["inner_width"] = width
        self.style_changed.emit(self._style)

    def _on_outer_line_width_changed(self, width: float) -> None:
        self._style.setdefault("lines", {})["outer_width"] = width
        self.style_changed.emit(self._style)

    def _on_inner_line_color_clicked(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self._style.setdefault("lines", {})["inner_color"] = color.name()
            self.style_changed.emit(self._style)

    def _on_outer_line_color_clicked(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self._style.setdefault("lines", {})["outer_color"] = color.name()
            self.style_changed.emit(self._style)

    def _on_event_font_changed(self, family: str) -> None:
        self._style.setdefault("events", {}).setdefault("font", {})["family"] = family
        self.style_changed.emit(self._style)

    def _on_event_font_size_changed(self, size: float) -> None:
        self._style.setdefault("events", {}).setdefault("font", {})["size"] = size
        self.style_changed.emit(self._style)

    def _on_event_font_bold_changed(self, bold: bool) -> None:
        self._style.setdefault("events", {}).setdefault("font", {})["bold"] = bold
        self.style_changed.emit(self._style)

    def _on_event_font_italic_changed(self, italic: bool) -> None:
        self._style.setdefault("events", {}).setdefault("font", {})["italic"] = italic
        self.style_changed.emit(self._style)

    def _on_event_mode_changed(self, mode: str) -> None:
        mode_map = {"Vertical": "vertical", "Horizontal": "horizontal", "Outside": "outside"}
        self._style.setdefault("events", {})["mode"] = mode_map.get(mode, "vertical")
        self.style_changed.emit(self._style)

    def _on_event_max_per_cluster_changed(self, value: int) -> None:
        self._style.setdefault("events", {})["max_per_cluster"] = value
        self.style_changed.emit(self._style)

    def _on_event_lanes_changed(self, lanes: int) -> None:
        self._style.setdefault("events", {})["lanes"] = lanes
        self.style_changed.emit(self._style)

    def _on_event_outline_changed(self, enabled: bool) -> None:
        self._style.setdefault("events", {})["outline_enabled"] = enabled
        self.style_changed.emit(self._style)

    def _on_event_outline_width_changed(self, width: float) -> None:
        self._style.setdefault("events", {})["outline_width"] = width
        self.style_changed.emit(self._style)

    def _on_apply(self) -> None:
        """Handle Apply button click."""
        self.apply_requested.emit()

    def _on_revert(self) -> None:
        """Handle Revert button click."""
        self.revert_requested.emit()
