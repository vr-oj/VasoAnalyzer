"""Layout and composition controls dock."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.plots.plot_host import LayoutState
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["LayoutDock"]


class LayoutDock(QDockWidget):
    """
    Dockable panel for layout and composition controls.

    Features:
    - Channel track visibility toggles
    - Height ratio sliders with live preview
    - Margin/padding precise controls (mm units)
    - Annotation visibility
    """

    # Signal emitted when layout changes
    layout_changed = pyqtSignal(object)  # LayoutState

    # Signal emitted when margins change
    margins_changed = pyqtSignal(
        dict
    )  # {"left": float, "right": float, "top": float, "bottom": float}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Layout & Composition", parent)
        self.setObjectName("LayoutDock")

        # Current layout state
        self._layout_state: LayoutState | None = None

        # Track controls
        self._track_visibility_checks: dict[str, QCheckBox] = {}
        self._track_height_sliders: dict[str, QSlider] = {}
        self._track_height_labels: dict[str, QLabel] = {}

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ Public API

    def set_layout_state(self, layout_state: LayoutState | None) -> None:
        """Update layout controls from state."""
        self._layout_state = layout_state
        self._populate_controls()

    def get_layout_state(self) -> LayoutState | None:
        """Get current layout state from controls."""
        if not self._layout_state:
            return None

        # Gather visibility and height ratios from controls
        visibility = {}
        height_ratios = {}

        for track_id, check in self._track_visibility_checks.items():
            visibility[track_id] = check.isChecked()

        for track_id, slider in self._track_height_sliders.items():
            # Slider value 0-100 maps to 0.1-10.0 height ratio (logarithmic)
            value = slider.value()
            ratio = 0.1 + (value / 100.0) * 9.9
            height_ratios[track_id] = ratio

        return LayoutState(
            order=self._layout_state.order,
            height_ratios=height_ratios,
            visibility=visibility,
        )

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build dock UI."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        header = QLabel("Channel Layout")
        header.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(header)

        # Track controls group (will be populated dynamically)
        self.tracks_group = QGroupBox("Channel Tracks")
        self.tracks_layout = QVBoxLayout(self.tracks_group)
        self.tracks_layout.setSpacing(12)
        layout.addWidget(self.tracks_group)

        # Margins group
        margins_group = QGroupBox("Figure Margins")
        margins_form = QFormLayout(margins_group)

        self.margin_left_spin = QDoubleSpinBox()
        self.margin_left_spin.setRange(0.0, 0.5)
        self.margin_left_spin.setValue(0.095)
        self.margin_left_spin.setSingleStep(0.005)
        self.margin_left_spin.setDecimals(3)
        self.margin_left_spin.valueChanged.connect(self._on_margins_changed)
        margins_form.addRow("Left:", self.margin_left_spin)

        self.margin_right_spin = QDoubleSpinBox()
        self.margin_right_spin.setRange(0.5, 1.0)
        self.margin_right_spin.setValue(0.985)
        self.margin_right_spin.setSingleStep(0.005)
        self.margin_right_spin.setDecimals(3)
        self.margin_right_spin.valueChanged.connect(self._on_margins_changed)
        margins_form.addRow("Right:", self.margin_right_spin)

        self.margin_top_spin = QDoubleSpinBox()
        self.margin_top_spin.setRange(0.5, 1.0)
        self.margin_top_spin.setValue(0.985)
        self.margin_top_spin.setSingleStep(0.005)
        self.margin_top_spin.setDecimals(3)
        self.margin_top_spin.valueChanged.connect(self._on_margins_changed)
        margins_form.addRow("Top:", self.margin_top_spin)

        self.margin_bottom_spin = QDoubleSpinBox()
        self.margin_bottom_spin.setRange(0.0, 0.5)
        self.margin_bottom_spin.setValue(0.115)
        self.margin_bottom_spin.setSingleStep(0.005)
        self.margin_bottom_spin.setDecimals(3)
        self.margin_bottom_spin.valueChanged.connect(self._on_margins_changed)
        margins_form.addRow("Bottom:", self.margin_bottom_spin)

        layout.addWidget(margins_group)
        layout.addStretch(1)

        scroll.setWidget(container)
        self.setWidget(scroll)

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
        """Populate track controls from layout state."""
        if not self._layout_state:
            return

        # Clear existing track controls
        while self.tracks_layout.count():
            child = self.tracks_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._track_visibility_checks.clear()
        self._track_height_sliders.clear()
        self._track_height_labels.clear()

        # Create controls for each track
        for track_id in self._layout_state.order:
            track_widget = QWidget()
            track_layout = QVBoxLayout(track_widget)
            track_layout.setContentsMargins(0, 0, 0, 0)
            track_layout.setSpacing(4)

            # Visibility checkbox
            visible = self._layout_state.visibility.get(track_id, True)
            check = QCheckBox(f"{track_id.title()} Channel")
            check.setChecked(visible)
            check.toggled.connect(self._on_track_visibility_changed)
            track_layout.addWidget(check)
            self._track_visibility_checks[track_id] = check

            # Height ratio slider
            ratio = self._layout_state.height_ratios.get(track_id, 1.0)
            # Map ratio 0.1-10.0 to slider 0-100
            slider_value = int(((ratio - 0.1) / 9.9) * 100)
            slider_value = max(0, min(100, slider_value))

            slider_label = QLabel(f"Height: {ratio:.2f}")
            track_layout.addWidget(slider_label)
            self._track_height_labels[track_id] = slider_label

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(slider_value)
            slider.setTickPosition(QSlider.TicksBelow)
            slider.setTickInterval(10)
            slider.valueChanged.connect(
                lambda v, tid=track_id: self._on_track_height_changed(tid, v)
            )
            track_layout.addWidget(slider)
            self._track_height_sliders[track_id] = slider

            self.tracks_layout.addWidget(track_widget)

    # ------------------------------------------------------------------ Signal Handlers

    def _on_track_visibility_changed(self) -> None:
        """Handle track visibility toggle."""
        layout_state = self.get_layout_state()
        if layout_state:
            self.layout_changed.emit(layout_state)

    def _on_track_height_changed(self, track_id: str, slider_value: int) -> None:
        """Handle height ratio slider change."""
        # Map slider 0-100 to ratio 0.1-10.0
        ratio = 0.1 + (slider_value / 100.0) * 9.9

        # Update label
        if track_id in self._track_height_labels:
            self._track_height_labels[track_id].setText(f"Height: {ratio:.2f}")

        # Emit layout change
        layout_state = self.get_layout_state()
        if layout_state:
            self.layout_changed.emit(layout_state)

    def _on_margins_changed(self) -> None:
        """Handle margin spin box changes."""
        margins = {
            "left": self.margin_left_spin.value(),
            "right": self.margin_right_spin.value(),
            "top": self.margin_top_spin.value(),
            "bottom": self.margin_bottom_spin.value(),
        }
        self.margins_changed.emit(margins)
