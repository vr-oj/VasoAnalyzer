"""Simplified PyQtGraph plot settings dialog - Pure PyQtGraph defaults."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, TypedDict

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
    from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec

log = logging.getLogger(__name__)


class TrackWidgetControls(TypedDict):
    y_min: QDoubleSpinBox
    y_max: QDoubleSpinBox
    autoscale: QCheckBox
    visible: QCheckBox


class PyQtGraphSettingsDialog(QDialog):
    """Simplified settings dialog for PyQtGraph renderer - Pure PyQtGraph defaults only.

    Provides essential analysis controls:
    - Per-track visibility and Y-axis scaling
    - Grid on/off toggle
    - Hover tooltip enable/precision
    - Event labels enable/numbers-only

    No publication-style customization (fonts, colors, line styling, etc.)
    """

    def __init__(self, parent, plot_host: PyQtGraphPlotHost):
        super().__init__(parent)
        self.plot_host = plot_host
        self.parent_window = parent

        self.setWindowTitle("Plot Settings")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.setSizeGripEnabled(True)

        self.track_widgets: dict[str, tuple[PyQtGraphChannelTrack | None, TrackWidgetControls]] = {}

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self):
        """Create the simplified single-tab dialog UI."""
        layout = QVBoxLayout(self)

        # Info label
        intro = QLabel(
            "Configure basic plot settings for analysis. "
            "Uses PyQtGraph defaults for fonts, colors, and styling."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; font-style: italic; margin-bottom: 8px;")
        layout.addWidget(intro)

        # Main scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)

        # Create group boxes
        content_layout.addWidget(self._create_tracks_group())
        content_layout.addWidget(self._create_grid_group())
        content_layout.addWidget(self._create_tooltips_group())
        content_layout.addWidget(self._create_event_labels_group())
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._save_settings)
        layout.addWidget(buttons)

    def _create_tracks_group(self) -> QGroupBox:
        """Create tracks visibility and Y-axis range controls."""
        group = QGroupBox("Tracks")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)

        # Headers
        headers = ["Track", "Show", "Auto Y", "Y min", "Y max"]
        for col, text in enumerate(headers):
            header_label = QLabel(text)
            header_label.setStyleSheet("font-weight: bold;")
            grid.addWidget(header_label, 0, col)

        # Per-track controls
        row = 1
        for idx, spec in enumerate(self.plot_host.iter_channels()):
            track = self.plot_host.track(spec.track_id)
            label_text, widgets = self._create_track_widgets(spec, track, idx)

            name_label = QLabel(label_text)
            grid.addWidget(name_label, row, 0)
            grid.addWidget(widgets["visible"], row, 1, alignment=Qt.AlignCenter)
            grid.addWidget(widgets["autoscale"], row, 2, alignment=Qt.AlignCenter)
            grid.addWidget(widgets["y_min"], row, 3)
            grid.addWidget(widgets["y_max"], row, 4)
            row += 1

        return group

    def _create_grid_group(self) -> QGroupBox:
        """Create simple grid on/off control."""
        group = QGroupBox("Grid")
        form = QFormLayout(group)

        self.grid_visible_cb = QCheckBox("Show Grid")
        self.grid_visible_cb.setChecked(True)
        form.addRow("", self.grid_visible_cb)

        return group

    def _create_tooltips_group(self) -> QGroupBox:
        """Create hover tooltip controls."""
        group = QGroupBox("Tooltips")
        form = QFormLayout(group)

        self.tooltip_enabled_cb = QCheckBox("Enable Hover Tooltips")
        self.tooltip_enabled_cb.setChecked(True)
        self.tooltip_enabled_cb.setToolTip("Show data point values when hovering over traces")
        form.addRow("", self.tooltip_enabled_cb)

        self.tooltip_precision = QSpinBox()
        self.tooltip_precision.setRange(0, 6)
        self.tooltip_precision.setValue(3)
        self.tooltip_precision.setSuffix(" decimals")
        form.addRow("Value Precision:", self.tooltip_precision)

        return group

    def _create_event_labels_group(self) -> QGroupBox:
        """Create simple event labels controls."""
        group = QGroupBox("Event Labels")
        form = QFormLayout(group)

        self.event_labels_enabled_cb = QCheckBox("Show Event Labels")
        self.event_labels_enabled_cb.setChecked(True)
        form.addRow("", self.event_labels_enabled_cb)

        self.event_show_numbers_cb = QCheckBox("Show Numbers Only")
        self.event_show_numbers_cb.setChecked(True)
        self.event_show_numbers_cb.setToolTip("Display only event numbers instead of full text")
        form.addRow("", self.event_show_numbers_cb)

        return group

    def _create_track_widgets(
        self, spec: ChannelTrackSpec, track: PyQtGraphChannelTrack | None, idx: int
    ) -> tuple[str, TrackWidgetControls]:
        """Create widgets for a single track row."""
        y_min_spin = QDoubleSpinBox()
        y_min_spin.setRange(-10000, 10000)
        y_min_spin.setDecimals(2)
        y_min_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        y_min_spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)

        y_max_spin = QDoubleSpinBox()
        y_max_spin.setRange(-10000, 10000)
        y_max_spin.setDecimals(2)
        y_max_spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        y_max_spin.setButtonSymbols(QAbstractSpinBox.UpDownArrows)

        try:
            if track is not None:
                ylim = track.ax.get_ylim()
                y_min_spin.setValue(ylim[0])
                y_max_spin.setValue(ylim[1])
            else:
                raise ValueError("missing track")
        except Exception:
            y_min_spin.setValue(0)
            y_max_spin.setValue(100)

        auto_scale_cb = QCheckBox()
        auto_scale_cb.setToolTip("Enable automatic Y scaling for this track")
        auto_scale_cb.setChecked(
            track.view.is_autoscale_enabled() if track is not None else True
        )

        visible_cb = QCheckBox()
        visible_cb.setToolTip("Show or hide this track")
        visible_cb.setChecked(self.plot_host.is_channel_visible(spec.track_id))

        widgets: TrackWidgetControls = {
            "y_min": y_min_spin,
            "y_max": y_max_spin,
            "autoscale": auto_scale_cb,
            "visible": visible_cb,
        }

        self.track_widgets[spec.track_id] = (track, widgets)

        auto_scale_cb.toggled.connect(
            lambda checked, track_id=spec.track_id: self._on_track_autoscale_toggled(
                track_id, checked
            )
        )

        self._on_track_autoscale_toggled(spec.track_id, auto_scale_cb.isChecked())

        label_text = spec.label
        return label_text, widgets

    def _on_track_autoscale_toggled(self, track_id: str, checked: bool):
        """Enable/disable Y-axis spinboxes based on autoscale state."""
        if track_id in self.track_widgets:
            _track, widgets = self.track_widgets[track_id]
            widgets["y_min"].setEnabled(not checked)
            widgets["y_max"].setEnabled(not checked)

    def _load_current_settings(self):
        """Load current settings from plot host."""
        try:
            # Grid
            x_visible, y_visible, _grid_alpha = self.plot_host.grid_state()
            self.grid_visible_cb.setChecked(x_visible or y_visible)

            # Tooltips
            tooltip_enabled = self.plot_host.label_tooltips_enabled()
            tooltip_precision = self.plot_host.tooltip_precision()
            self.tooltip_enabled_cb.setChecked(tooltip_enabled)
            self.tooltip_precision.setValue(tooltip_precision)

            # Event labels
            event_enabled = self.plot_host.event_labels_visible()
            options = self.plot_host.event_label_options()
            show_numbers_only = getattr(options, "show_numbers_only", False)
            self.event_labels_enabled_cb.setChecked(bool(event_enabled))
            self.event_show_numbers_cb.setChecked(bool(show_numbers_only))

        except Exception as e:
            log.warning(f"Could not load current settings: {e}")

    def accept(self):
        """Apply settings and close dialog."""
        self._save_settings()
        super().accept()

    def _save_settings(self):
        """Save settings to plot host."""
        try:
            if self.plot_host is not None and hasattr(self.plot_host, "debug_dump_state"):
                self.plot_host.debug_dump_state("pyqtgraph_settings_apply (before)")

            # Apply track settings
            for track_id, (track, widgets) in self.track_widgets.items():
                if track is None:
                    continue
                # Y-axis limits
                if not widgets["autoscale"].isChecked():
                    y_min = widgets["y_min"].value()
                    y_max = widgets["y_max"].value()
                    track.set_ylim(y_min, y_max)
                else:
                    track.view.set_autoscale_y(True)

                # Visibility
                self.plot_host.set_channel_visible(track_id, widgets["visible"].isChecked())

            # Apply grid (simple on/off, no alpha parameter)
            self._apply_grid_settings()

            # Apply tooltips
            self._apply_hover_tooltips()

            # Apply event labels (only enabled/numbers-only)
            self._apply_event_label_settings()

            # Notify parent window
            if hasattr(self.parent_window, "on_plot_settings_changed"):
                self.parent_window.on_plot_settings_changed()
            if hasattr(self.parent_window, "_sync_track_visibility_from_host"):
                with contextlib.suppress(Exception):
                    self.parent_window._sync_track_visibility_from_host()
            if self.plot_host is not None and hasattr(self.plot_host, "debug_dump_state"):
                self.plot_host.debug_dump_state("pyqtgraph_settings_apply (after)")

        except Exception as e:
            log.error(f"Failed to apply PyQtGraph settings: {e}", exc_info=True)

    def _apply_grid_settings(self):
        """Apply simple grid on/off (PyQtGraph defaults)."""
        try:
            grid_visible = self.grid_visible_cb.isChecked()
            # Use PyQtGraph default grid appearance (no custom alpha)
            self.plot_host.set_grid_visible(grid_visible)

            # Keep toolbar and persisted flag in sync with the host state
            owner = getattr(self, "parent_window", None) or self.parent()
            while owner is not None and not hasattr(owner, "grid_visible"):
                owner = owner.parent()
            if owner is not None:
                with contextlib.suppress(Exception):
                    owner.grid_visible = grid_visible
                    if hasattr(owner, "_sync_grid_action"):
                        owner._sync_grid_action()

        except Exception as e:
            log.error(f"Failed to apply grid settings: {e}", exc_info=True)

    def _apply_hover_tooltips(self):
        """Apply hover tooltip settings."""
        try:
            enabled = self.tooltip_enabled_cb.isChecked()
            precision = self.tooltip_precision.value()

            self.plot_host.set_label_tooltips_enabled(enabled)
            self.plot_host.set_tooltip_precision(precision)

        except Exception as e:
            log.error(f"Failed to apply tooltip settings: {e}", exc_info=True)

    def _apply_event_label_settings(self):
        """Apply minimal event label settings (enabled + numbers-only)."""
        try:
            enabled = self.event_labels_enabled_cb.isChecked()
            show_numbers_only = self.event_show_numbers_cb.isChecked()

            self.plot_host.set_event_labels_visible(enabled)
            self.plot_host.set_event_base_style(show_numbers_only=show_numbers_only)

        except Exception as e:
            log.error(f"Failed to apply event label settings: {e}", exc_info=True)
