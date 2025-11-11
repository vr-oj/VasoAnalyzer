"""PyQtGraph-compatible plot settings dialog.

This dialog provides settings for PyQtGraph renderer without depending on
matplotlib Figure objects. It focuses on the most commonly used settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost

log = logging.getLogger(__name__)


class PyQtGraphSettingsDialog(QDialog):
    """Settings dialog for PyQtGraph renderer.

    Provides controls for:
    - Track/channel appearance (colors, line width, y-axis)
    - Event labels (mode, clustering, font)
    - General plot settings (grid, background)
    """

    def __init__(self, parent, plot_host: "PyQtGraphPlotHost"):
        super().__init__(parent)
        self.plot_host = plot_host
        self.parent_window = parent

        self.setWindowTitle("Plot Settings (PyQtGraph)")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self):
        """Create the dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget for different settings categories
        tabs = QTabWidget()

        # Create tabs
        tabs.addTab(self._create_tracks_tab(), "Tracks")
        tabs.addTab(self._create_event_labels_tab(), "Event Labels")
        tabs.addTab(self._create_general_tab(), "General")

        layout.addWidget(tabs)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply_settings)
        layout.addWidget(buttons)

    def _create_tracks_tab(self) -> QWidget:
        """Create tracks/channels settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Scroll area for multiple tracks
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        container_layout = QVBoxLayout(container)

        # Get all tracks from plot host
        tracks = list(self.plot_host._tracks.values())

        self.track_widgets = {}

        for idx, track in enumerate(tracks):
            group = self._create_track_group(track, idx)
            container_layout.addWidget(group)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        return tab

    def _create_track_group(self, track, idx: int) -> QGroupBox:
        """Create settings group for a single track."""
        spec = track.spec
        group = QGroupBox(f"Track: {spec.label}")
        form = QFormLayout(group)

        # Store widgets for this track
        widgets = {}

        # Y-axis label
        # Note: Would need to add getter/setter methods to track

        # Y-axis limits
        y_limits_widget = QWidget()
        y_limits_layout = QHBoxLayout(y_limits_widget)
        y_limits_layout.setContentsMargins(0, 0, 0, 0)

        y_min_spin = QDoubleSpinBox()
        y_min_spin.setRange(-10000, 10000)
        y_min_spin.setDecimals(2)
        y_min_spin.setPrefix("Min: ")

        y_max_spin = QDoubleSpinBox()
        y_max_spin.setRange(-10000, 10000)
        y_max_spin.setDecimals(2)
        y_max_spin.setPrefix("Max: ")

        # Get current limits
        try:
            ylim = track.ax.get_ylim()
            y_min_spin.setValue(ylim[0])
            y_max_spin.setValue(ylim[1])
        except:
            y_min_spin.setValue(0)
            y_max_spin.setValue(100)

        y_limits_layout.addWidget(y_min_spin)
        y_limits_layout.addWidget(y_max_spin)

        widgets['y_min'] = y_min_spin
        widgets['y_max'] = y_max_spin

        form.addRow("Y-Axis Range:", y_limits_widget)

        # Auto-scale checkbox
        auto_scale_cb = QCheckBox("Auto-scale Y-axis")
        auto_scale_cb.setChecked(track.view._autoscale_y)
        widgets['autoscale'] = auto_scale_cb
        form.addRow("", auto_scale_cb)

        # Line width
        line_width_spin = QDoubleSpinBox()
        line_width_spin.setRange(0.5, 10.0)
        line_width_spin.setSingleStep(0.5)
        line_width_spin.setDecimals(1)

        # Get current line width
        try:
            current_width = track.primary_line.get_linewidth()
            line_width_spin.setValue(current_width)
        except:
            line_width_spin.setValue(1.5)  # Default

        widgets['line_width'] = line_width_spin
        form.addRow("Line Width:", line_width_spin)

        # Visibility
        visible_cb = QCheckBox("Show Track")
        visible_cb.setChecked(track.is_visible())
        widgets['visible'] = visible_cb
        form.addRow("", visible_cb)

        self.track_widgets[spec.track_id] = (track, widgets)

        return group

    def _create_event_labels_tab(self) -> QWidget:
        """Create event labels settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Enable/disable
        enable_group = QGroupBox("Event Labels")
        enable_layout = QVBoxLayout(enable_group)

        self.event_labels_enabled_cb = QCheckBox("Show Event Labels")
        self.event_labels_enabled_cb.setChecked(True)  # Will load from settings
        enable_layout.addWidget(self.event_labels_enabled_cb)

        layout.addWidget(enable_group)

        # Layout options
        layout_group = QGroupBox("Layout")
        form = QFormLayout(layout_group)

        # Mode
        self.event_mode_combo = QComboBox()
        self.event_mode_combo.addItems(["Vertical", "Horizontal Inside", "Horizontal Belt"])
        form.addRow("Label Mode:", self.event_mode_combo)

        # Clustering threshold
        self.event_cluster_spin = QSpinBox()
        self.event_cluster_spin.setRange(10, 100)
        self.event_cluster_spin.setValue(24)
        self.event_cluster_spin.setSuffix(" px")
        form.addRow("Clustering Threshold:", self.event_cluster_spin)

        # Number of lanes
        self.event_lanes_spin = QSpinBox()
        self.event_lanes_spin.setRange(1, 10)
        self.event_lanes_spin.setValue(3)
        form.addRow("Number of Lanes:", self.event_lanes_spin)

        # Font size
        self.event_font_size_spin = QSpinBox()
        self.event_font_size_spin.setRange(6, 24)
        self.event_font_size_spin.setValue(10)
        self.event_font_size_spin.setSuffix(" pt")
        form.addRow("Font Size:", self.event_font_size_spin)

        layout.addWidget(layout_group)
        layout.addStretch()

        return tab

    def _create_general_tab(self) -> QWidget:
        """Create general settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Grid
        grid_group = QGroupBox("Grid")
        grid_layout = QVBoxLayout(grid_group)

        self.grid_visible_cb = QCheckBox("Show Grid")
        self.grid_visible_cb.setChecked(True)
        grid_layout.addWidget(self.grid_visible_cb)

        layout.addWidget(grid_group)

        # Background
        bg_group = QGroupBox("Appearance")
        bg_form = QFormLayout(bg_group)

        bg_color_widget = QWidget()
        bg_color_layout = QHBoxLayout(bg_color_widget)
        bg_color_layout.setContentsMargins(0, 0, 0, 0)

        self.bg_color_label = QLabel()
        self.bg_color_label.setFixedSize(40, 24)
        self.bg_color_label.setStyleSheet(f"background-color: {CURRENT_THEME['window_bg']}; border: 1px solid #ccc;")

        bg_color_btn = QPushButton("Choose...")
        bg_color_btn.clicked.connect(self._choose_background_color)

        bg_color_layout.addWidget(self.bg_color_label)
        bg_color_layout.addWidget(bg_color_btn)
        bg_color_layout.addStretch()

        bg_form.addRow("Background Color:", bg_color_widget)

        layout.addWidget(bg_group)
        layout.addStretch()

        return tab

    def _load_current_settings(self):
        """Load current settings from plot host."""
        try:
            # Load event label settings from first track that has a labeler
            for track in self.plot_host._tracks.values():
                if track.view._event_labeler is not None:
                    labeler = track.view._event_labeler
                    options = labeler.options

                    # Load enabled state
                    self.event_labels_enabled_cb.setChecked(track.view._event_labels_visible)

                    # Load mode
                    mode_map = {
                        "vertical": 0,
                        "h_inside": 1,
                        "h_belt": 2,
                    }
                    mode_idx = mode_map.get(options.mode, 0)
                    self.event_mode_combo.setCurrentIndex(mode_idx)

                    # Load clustering threshold
                    self.event_cluster_spin.setValue(options.min_px)

                    # Load lanes
                    self.event_lanes_spin.setValue(options.lanes)

                    # Font size would be in the renderer's font configuration
                    # For now, keep the default

                    break

            # Load grid visibility from first track
            if self.plot_host._tracks:
                first_track = next(iter(self.plot_host._tracks.values()))
                plot_item = first_track.view.get_widget().getPlotItem()
                grid_visible = plot_item.ctrl.xGridCheck.isChecked()
                self.grid_visible_cb.setChecked(grid_visible)

        except Exception as e:
            log.error(f"Failed to load PyQtGraph settings: {e}", exc_info=True)

    def _choose_background_color(self):
        """Open color picker for background color."""
        current_color = QColor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
        color = QColorDialog.getColor(current_color, self, "Choose Background Color")

        if color.isValid():
            self.bg_color_label.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #ccc;"
            )

    def _apply_settings(self):
        """Apply settings to plot host without closing dialog."""
        self._save_settings()

    def accept(self):
        """Apply settings and close dialog."""
        self._save_settings()
        super().accept()

    def _save_settings(self):
        """Save settings to plot host."""
        try:
            # Apply track settings
            for track_id, (track, widgets) in self.track_widgets.items():
                # Y-axis limits
                if not widgets['autoscale'].isChecked():
                    y_min = widgets['y_min'].value()
                    y_max = widgets['y_max'].value()
                    track.set_ylim(y_min, y_max)
                else:
                    track.view.set_autoscale_y(True)

                # Visibility
                track.set_visible(widgets['visible'].isChecked())

                # Line width
                track.set_line_width(widgets['line_width'].value())

            # Apply event label settings
            from vasoanalyzer.ui.event_labels_v3 import LayoutOptionsV3

            enabled = self.event_labels_enabled_cb.isChecked()

            # Create options from dialog values
            mode_map = {
                0: "vertical",
                1: "h_inside",
                2: "h_belt",
            }
            mode = mode_map.get(self.event_mode_combo.currentIndex(), "vertical")

            options = LayoutOptionsV3(
                mode=mode,
                min_px=self.event_cluster_spin.value(),
                lanes=self.event_lanes_spin.value(),
                # Keep other options at defaults for now
            )

            # Apply to all tracks
            for track in self.plot_host._tracks.values():
                track.view.enable_event_labels(enabled, options=options if enabled else None)

            # Also update visibility flag
            self.plot_host.set_event_labels_visible(enabled)

            # Apply general settings
            # Grid visibility
            grid_visible = self.grid_visible_cb.isChecked()
            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                plot_item.showGrid(x=grid_visible, y=grid_visible)

            # Background color
            bg_color = self.bg_color_label.styleSheet().split("background-color: ")[1].split(";")[0]
            self.plot_host.widget.setStyleSheet(f"background-color: {bg_color};")

            # Notify parent window if it has a method to handle setting changes
            if hasattr(self.parent_window, 'on_plot_settings_changed'):
                self.parent_window.on_plot_settings_changed()

        except Exception as e:
            log.error(f"Failed to apply PyQtGraph settings: {e}", exc_info=True)
