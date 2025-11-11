"""Comprehensive PyQtGraph plot settings dialog.

This dialog provides full control over PyQtGraph renderer settings, matching
and exceeding the capabilities of the matplotlib-based settings dialog.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
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
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:
    from vasoanalyzer.ui.plots.pyqtgraph_channel_track import PyQtGraphChannelTrack
    from vasoanalyzer.ui.plots.pyqtgraph_plot_host import PyQtGraphPlotHost

log = logging.getLogger(__name__)


class ColorPickerWidget(TypedDict):
    widget: QWidget
    label: QLabel
    button: QPushButton


class TrackWidgetControls(TypedDict):
    y_min: QDoubleSpinBox
    y_max: QDoubleSpinBox
    autoscale: QCheckBox
    visible: QCheckBox


class AxisTitleWidgets(TypedDict):
    title: QLineEdit
    font_family: QComboBox
    font_size: QSpinBox
    color_btn: QPushButton
    color_label: QLabel


class LineStyleWidgets(TypedDict):
    line_width: QDoubleSpinBox
    line_style: QComboBox
    color_btn: QPushButton
    color_label: QLabel
    alpha: QDoubleSpinBox


class PyQtGraphSettingsDialog(QDialog):
    """Comprehensive settings dialog for PyQtGraph renderer.

    Provides full control over:
    - Per-track appearance (y-axis, line styling, visibility)
    - Axis titles, fonts, colors, and tick configuration
    - Trace line colors, widths, styles
    - Event markers and highlights
    - Event labels (mode, clustering, fonts, colors)
    - Grid, background, and overall appearance
    """

    def __init__(self, parent, plot_host: PyQtGraphPlotHost):
        super().__init__(parent)
        self.plot_host = plot_host
        self.parent_window = parent

        self.setWindowTitle("Plot Settings")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        self.setSizeGripEnabled(True)

        # Font choices
        self._font_choices = [
            "Arial",
            "Helvetica",
            "Times New Roman",
            "Courier New",
            "Courier",
            "Verdana",
            "Georgia",
        ]

        self.track_widgets: dict[str, tuple[PyQtGraphChannelTrack, TrackWidgetControls]] = {}
        self.y_axis_widgets: dict[str, tuple[PyQtGraphChannelTrack, AxisTitleWidgets]] = {}
        self.line_widgets: dict[str, tuple[PyQtGraphChannelTrack, LineStyleWidgets]] = {}

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self):
        """Create the dialog UI."""
        layout = QVBoxLayout(self)

        # Info label
        intro = QLabel(
            "Adjust track appearance, axis styling, and event labels. "
            "Changes apply immediately when you click Apply."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(intro)

        # Tab widget for different settings categories
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Create tabs
        self.tabs.addTab(self._create_tracks_tab(), "Tracks")
        self.tabs.addTab(self._create_axis_titles_tab(), "Axis && Titles")
        self.tabs.addTab(self._create_lines_markers_tab(), "Lines && Markers")
        self.tabs.addTab(self._create_event_labels_tab(), "Event Labels")
        self.tabs.addTab(self._create_appearance_tab(), "Grid && Appearance")

        layout.addWidget(self.tabs, 1)

        # Action buttons
        actions = QHBoxLayout()
        actions.addStretch()

        self.defaults_btn = QPushButton("Restore Defaults")
        self.defaults_btn.clicked.connect(self._restore_defaults)
        actions.addWidget(self.defaults_btn)

        layout.addLayout(actions)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply_settings)
        layout.addWidget(buttons)

    # ========================================================================
    # TAB 1: TRACKS
    # ========================================================================
    def _create_tracks_tab(self) -> QWidget:
        """Create tracks/channels settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel("Configure Y-axis range, autoscaling, and visibility for each track.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(info)

        # Scroll area for multiple tracks
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

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
        group = QGroupBox(f"Track {idx + 1}: {spec.label}")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)

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

        form.addRow("Y-Axis Range:", y_limits_widget)

        # Auto-scale checkbox
        auto_scale_cb = QCheckBox("Auto-scale Y-axis")
        auto_scale_cb.setChecked(track.view._autoscale_y)
        form.addRow("", auto_scale_cb)

        # Visibility
        visible_cb = QCheckBox("Show Track")
        visible_cb.setChecked(track.is_visible())
        form.addRow("", visible_cb)

        widgets: TrackWidgetControls = {
            "y_min": y_min_spin,
            "y_max": y_max_spin,
            "autoscale": auto_scale_cb,
            "visible": visible_cb,
        }

        self.track_widgets[spec.track_id] = (track, widgets)

        return group

    # ========================================================================
    # TAB 2: AXIS & TITLES
    # ========================================================================
    def _create_axis_titles_tab(self) -> QWidget:
        """Create axis titles and styling tab."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # X Axis Title Section
        x_axis_group = QGroupBox("X Axis Title")
        x_form = QFormLayout(x_axis_group)
        x_form.setLabelAlignment(Qt.AlignRight)

        self.x_axis_title_edit = QLineEdit()
        self.x_axis_title_edit.setPlaceholderText("Time (s)")
        x_form.addRow("Label:", self.x_axis_title_edit)

        self.x_axis_font_family = QComboBox()
        self.x_axis_font_family.addItems(self._font_choices)
        x_form.addRow("Font Family:", self.x_axis_font_family)

        self.x_axis_font_size = QSpinBox()
        self.x_axis_font_size.setRange(6, 48)
        self.x_axis_font_size.setValue(18)
        x_form.addRow("Font Size:", self.x_axis_font_size)

        x_color_widget = self._create_color_picker_widget()
        self.x_axis_color_btn = x_color_widget["button"]
        self.x_axis_color_label = x_color_widget["label"]
        x_form.addRow("Label Color:", x_color_widget["widget"])

        layout.addWidget(x_axis_group)

        # Y Axis Titles Section (per track)
        y_axis_group = QGroupBox("Y Axis Titles (Per Track)")
        y_layout = QVBoxLayout(y_axis_group)

        self.y_axis_widgets = {}
        for idx, (track_id, track) in enumerate(self.plot_host._tracks.items()):
            track_group = QGroupBox(f"Track {idx + 1}: {track.spec.label}")
            track_form = QFormLayout(track_group)
            track_form.setLabelAlignment(Qt.AlignRight)

            title_edit = QLineEdit()
            title_edit.setPlaceholderText(track.spec.label)
            track_form.addRow("Label:", title_edit)

            font_family = QComboBox()
            font_family.addItems(self._font_choices)
            track_form.addRow("Font Family:", font_family)

            font_size = QSpinBox()
            font_size.setRange(6, 48)
            font_size.setValue(18)
            track_form.addRow("Font Size:", font_size)

            color_widget = self._create_color_picker_widget()
            track_form.addRow("Label Color:", color_widget["widget"])

            track_widgets: AxisTitleWidgets = {
                "title": title_edit,
                "font_family": font_family,
                "font_size": font_size,
                "color_btn": color_widget["button"],
                "color_label": color_widget["label"],
            }

            y_layout.addWidget(track_group)
            self.y_axis_widgets[track_id] = (track, track_widgets)

        layout.addWidget(y_axis_group)

        # Tick Configuration Section
        tick_group = QGroupBox("Tick Configuration")
        tick_form = QFormLayout(tick_group)
        tick_form.setLabelAlignment(Qt.AlignRight)

        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(12)
        tick_form.addRow("Tick Label Font Size:", self.tick_font_size)

        self.x_tick_length = QSpinBox()
        self.x_tick_length.setRange(0, 20)
        self.x_tick_length.setValue(5)
        self.x_tick_length.setSuffix(" px")
        tick_form.addRow("X Tick Length:", self.x_tick_length)

        self.y_tick_length = QSpinBox()
        self.y_tick_length.setRange(0, 20)
        self.y_tick_length.setValue(5)
        self.y_tick_length.setSuffix(" px")
        tick_form.addRow("Y Tick Length:", self.y_tick_length)

        tick_color_widget = self._create_color_picker_widget()
        self.tick_color_btn = tick_color_widget["button"]
        self.tick_color_label = tick_color_widget["label"]
        tick_form.addRow("Tick Color:", tick_color_widget["widget"])

        layout.addWidget(tick_group)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        return tab

    # ========================================================================
    # TAB 3: LINES & MARKERS
    # ========================================================================
    def _create_lines_markers_tab(self) -> QWidget:
        """Create lines and markers styling tab."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Trace Lines Section (per track)
        lines_group = QGroupBox("Trace Line Styling (Per Track)")
        lines_layout = QVBoxLayout(lines_group)

        self.line_widgets = {}
        for idx, (track_id, track) in enumerate(self.plot_host._tracks.items()):
            track_group = QGroupBox(f"Track {idx + 1}: {track.spec.label}")
            track_form = QFormLayout(track_group)
            track_form.setLabelAlignment(Qt.AlignRight)

            line_width_spin = QDoubleSpinBox()
            line_width_spin.setRange(0.5, 10.0)
            line_width_spin.setSingleStep(0.5)
            line_width_spin.setDecimals(1)
            try:
                current_width = track.primary_line.get_linewidth()
                line_width_spin.setValue(current_width)
            except:
                line_width_spin.setValue(1.5)
            track_form.addRow("Line Width:", line_width_spin)

            line_style_combo = QComboBox()
            line_style_combo.addItems(["Solid", "Dashed", "Dotted", "DashDot"])
            track_form.addRow("Line Style:", line_style_combo)

            color_widget = self._create_color_picker_widget()
            track_form.addRow("Line Color:", color_widget["widget"])

            line_alpha_spin = QDoubleSpinBox()
            line_alpha_spin.setRange(0.0, 1.0)
            line_alpha_spin.setSingleStep(0.1)
            line_alpha_spin.setDecimals(2)
            line_alpha_spin.setValue(1.0)
            track_form.addRow("Line Alpha (Opacity):", line_alpha_spin)

            track_widgets: LineStyleWidgets = {
                "line_width": line_width_spin,
                "line_style": line_style_combo,
                "color_btn": color_widget["button"],
                "color_label": color_widget["label"],
                "alpha": line_alpha_spin,
            }

            lines_layout.addWidget(track_group)
            self.line_widgets[track_id] = (track, track_widgets)

        layout.addWidget(lines_group)

        # Event Markers Section
        markers_group = QGroupBox("Event Markers")
        markers_form = QFormLayout(markers_group)
        markers_form.setLabelAlignment(Qt.AlignRight)

        self.event_marker_enabled_cb = QCheckBox("Show Event Markers")
        self.event_marker_enabled_cb.setChecked(True)
        markers_form.addRow("", self.event_marker_enabled_cb)

        self.event_marker_size = QSpinBox()
        self.event_marker_size.setRange(2, 20)
        self.event_marker_size.setValue(8)
        self.event_marker_size.setSuffix(" px")
        markers_form.addRow("Marker Size:", self.event_marker_size)

        self.event_marker_shape = QComboBox()
        self.event_marker_shape.addItems(
            ["Circle", "Square", "Triangle", "Diamond", "Cross", "Plus"]
        )
        markers_form.addRow("Marker Shape:", self.event_marker_shape)

        marker_color_widget = self._create_color_picker_widget("#FF0000")
        self.event_marker_color_btn = marker_color_widget["button"]
        self.event_marker_color_label = marker_color_widget["label"]
        markers_form.addRow("Marker Color:", marker_color_widget["widget"])

        self.event_marker_edge_width = QDoubleSpinBox()
        self.event_marker_edge_width.setRange(0.0, 5.0)
        self.event_marker_edge_width.setSingleStep(0.5)
        self.event_marker_edge_width.setDecimals(1)
        self.event_marker_edge_width.setValue(1.0)
        markers_form.addRow("Edge Width:", self.event_marker_edge_width)

        marker_edge_color_widget = self._create_color_picker_widget("#000000")
        self.event_marker_edge_color_btn = marker_edge_color_widget["button"]
        self.event_marker_edge_color_label = marker_edge_color_widget["label"]
        markers_form.addRow("Edge Color:", marker_edge_color_widget["widget"])

        layout.addWidget(markers_group)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        return tab

    # ========================================================================
    # TAB 4: EVENT LABELS
    # ========================================================================
    def _create_event_labels_tab(self) -> QWidget:
        """Create event labels settings tab."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Enable/disable
        enable_group = QGroupBox("Event Labels")
        enable_layout = QVBoxLayout(enable_group)

        self.event_labels_enabled_cb = QCheckBox("Show Event Labels")
        self.event_labels_enabled_cb.setChecked(True)
        enable_layout.addWidget(self.event_labels_enabled_cb)

        layout.addWidget(enable_group)

        # Font Styling
        font_group = QGroupBox("Font Styling")
        font_form = QFormLayout(font_group)
        font_form.setLabelAlignment(Qt.AlignRight)

        self.event_font_family = QComboBox()
        self.event_font_family.addItems(self._font_choices)
        font_form.addRow("Font Family:", self.event_font_family)

        self.event_font_size_spin = QSpinBox()
        self.event_font_size_spin.setRange(6, 24)
        self.event_font_size_spin.setValue(10)
        self.event_font_size_spin.setSuffix(" pt")
        font_form.addRow("Font Size:", self.event_font_size_spin)

        event_font_style_widget = QWidget()
        event_font_style_layout = QHBoxLayout(event_font_style_widget)
        event_font_style_layout.setContentsMargins(0, 0, 0, 0)
        self.event_font_bold = QCheckBox("Bold")
        self.event_font_italic = QCheckBox("Italic")
        event_font_style_layout.addWidget(self.event_font_bold)
        event_font_style_layout.addWidget(self.event_font_italic)
        event_font_style_layout.addStretch()
        font_form.addRow("Font Style:", event_font_style_widget)

        event_color_widget = self._create_color_picker_widget("#000000")
        self.event_label_color_btn = event_color_widget["button"]
        self.event_label_color_label = event_color_widget["label"]
        font_form.addRow("Label Color:", event_color_widget["widget"])

        layout.addWidget(font_group)

        # Layout Options
        layout_group = QGroupBox("Layout & Clustering")
        layout_form = QFormLayout(layout_group)
        layout_form.setLabelAlignment(Qt.AlignRight)

        self.event_mode_combo = QComboBox()
        self.event_mode_combo.addItem("Vertical")
        self.event_mode_combo.setEnabled(False)
        layout_form.addRow("Label Mode:", self.event_mode_combo)

        mode_hint = QLabel("PyQtGraph currently renders event labels vertically.")
        mode_hint.setStyleSheet("color: gray; font-style: italic;")
        layout_form.addRow("", mode_hint)

        self.event_cluster_spin = QSpinBox()
        self.event_cluster_spin.setRange(10, 100)
        self.event_cluster_spin.setValue(24)
        self.event_cluster_spin.setSuffix(" px")
        layout_form.addRow("Clustering Threshold:", self.event_cluster_spin)

        self.event_max_per_cluster = QSpinBox()
        self.event_max_per_cluster.setRange(1, 10)
        self.event_max_per_cluster.setValue(1)
        layout_form.addRow("Max Labels Per Cluster:", self.event_max_per_cluster)

        self.event_lanes_spin = QSpinBox()
        self.event_lanes_spin.setRange(1, 10)
        self.event_lanes_spin.setValue(3)
        layout_form.addRow("Number of Lanes:", self.event_lanes_spin)

        self.event_span_siblings_cb = QCheckBox("Span Siblings")
        self.event_span_siblings_cb.setChecked(True)
        layout_form.addRow("", self.event_span_siblings_cb)

        layout.addWidget(layout_group)

        # Outline Options
        outline_group = QGroupBox("Label Outline")
        outline_form = QFormLayout(outline_group)
        outline_form.setLabelAlignment(Qt.AlignRight)

        self.event_outline_enabled_cb = QCheckBox("Enable Outline")
        self.event_outline_enabled_cb.setChecked(False)
        outline_form.addRow("", self.event_outline_enabled_cb)

        self.event_outline_width = QDoubleSpinBox()
        self.event_outline_width.setRange(0.0, 5.0)
        self.event_outline_width.setSingleStep(0.5)
        self.event_outline_width.setDecimals(1)
        self.event_outline_width.setValue(1.0)
        outline_form.addRow("Outline Width:", self.event_outline_width)

        outline_color_widget = self._create_color_picker_widget("#FFFFFF")
        self.event_outline_color_btn = outline_color_widget["button"]
        self.event_outline_color_label = outline_color_widget["label"]
        outline_form.addRow("Outline Color:", outline_color_widget["widget"])

        layout.addWidget(outline_group)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        return tab

    # ========================================================================
    # TAB 5: GRID & APPEARANCE
    # ========================================================================
    def _create_appearance_tab(self) -> QWidget:
        """Create grid and appearance tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Grid Section
        grid_group = QGroupBox("Grid")
        grid_form = QFormLayout(grid_group)
        grid_form.setLabelAlignment(Qt.AlignRight)

        self.grid_visible_cb = QCheckBox("Show Grid")
        self.grid_visible_cb.setChecked(True)
        grid_form.addRow("", self.grid_visible_cb)

        self.grid_alpha = QDoubleSpinBox()
        self.grid_alpha.setRange(0.0, 1.0)
        self.grid_alpha.setSingleStep(0.1)
        self.grid_alpha.setDecimals(2)
        self.grid_alpha.setValue(0.3)
        grid_form.addRow("Grid Alpha (Opacity):", self.grid_alpha)

        grid_color_widget = self._create_color_picker_widget("#CCCCCC")
        self.grid_color_btn = grid_color_widget["button"]
        self.grid_color_label = grid_color_widget["label"]
        grid_form.addRow("Grid Color:", grid_color_widget["widget"])

        layout.addWidget(grid_group)

        # Background Section
        bg_group = QGroupBox("Background")
        bg_form = QFormLayout(bg_group)
        bg_form.setLabelAlignment(Qt.AlignRight)

        bg_color_widget = self._create_color_picker_widget(CURRENT_THEME["window_bg"])
        self.bg_color_btn = bg_color_widget["button"]
        self.bg_color_label = bg_color_widget["label"]
        bg_form.addRow("Background Color:", bg_color_widget["widget"])

        plot_bg_color_widget = self._create_color_picker_widget("#FFFFFF")
        self.plot_bg_color_btn = plot_bg_color_widget["button"]
        self.plot_bg_color_label = plot_bg_color_widget["label"]
        bg_form.addRow("Plot Area Color:", plot_bg_color_widget["widget"])

        layout.addWidget(bg_group)

        # Hover Tooltip Section
        tooltip_group = QGroupBox("Hover Tooltips")
        tooltip_form = QFormLayout(tooltip_group)
        tooltip_form.setLabelAlignment(Qt.AlignRight)

        self.tooltip_enabled_cb = QCheckBox("Enable Hover Tooltips")
        self.tooltip_enabled_cb.setChecked(True)
        self.tooltip_enabled_cb.setToolTip("Show data point values when hovering over traces")
        tooltip_form.addRow("", self.tooltip_enabled_cb)

        self.tooltip_precision = QSpinBox()
        self.tooltip_precision.setRange(0, 6)
        self.tooltip_precision.setValue(3)
        self.tooltip_precision.setSuffix(" decimals")
        tooltip_form.addRow("Value Precision:", self.tooltip_precision)

        layout.addWidget(tooltip_group)

        layout.addStretch()

        return tab

    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    def _create_color_picker_widget(self, default_color: str = "#000000") -> ColorPickerWidget:
        """Create a color picker widget with label and button.

        Returns:
            dict with 'widget', 'label', and 'button' keys
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        color_label = QLabel()
        color_label.setFixedSize(40, 24)
        color_label.setStyleSheet(f"background-color: {default_color}; border: 1px solid #999;")

        color_btn = QPushButton("Choose...")
        color_btn.clicked.connect(lambda: self._pick_color(color_label))

        layout.addWidget(color_label)
        layout.addWidget(color_btn)
        layout.addStretch()

        return {
            "widget": widget,
            "label": color_label,
            "button": color_btn,
        }

    def _pick_color(self, label: QLabel):
        """Open color picker and update label background."""
        # Extract current color from label stylesheet
        style = label.styleSheet()
        current_color = style.split("background-color: ")[1].split(";")[0]

        color = QColorDialog.getColor(QColor(current_color), self, "Choose Color")
        if color.isValid():
            label.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #999;")

    def _get_label_color(self, label: QLabel) -> str:
        """Extract color from label stylesheet."""
        style = label.styleSheet()
        return style.split("background-color: ")[1].split(";")[0]

    def _set_label_color(self, label: QLabel, color: str) -> None:
        """Apply a hex color to a preview swatch label."""
        if not color:
            color = "#000000"
        label.setStyleSheet(f"background-color: {color}; border: 1px solid #999;")

    # ========================================================================
    # LOAD/SAVE SETTINGS
    # ========================================================================
    def _load_current_settings(self):
        """Load current settings from plot host."""
        try:
            # Load X axis title
            if self.plot_host._tracks:
                first_track = next(iter(self.plot_host._tracks.values()))
                plot_item = first_track.view.get_widget().getPlotItem()
                x_label = plot_item.getAxis("bottom").label.toPlainText()
                if x_label:
                    self.x_axis_title_edit.setText(x_label)

            # Load Y axis titles
            for _track_id, (track, widgets) in self.y_axis_widgets.items():
                plot_item = track.view.get_widget().getPlotItem()
                y_label = plot_item.getAxis("left").label.toPlainText()
                if y_label:
                    widgets["title"].setText(y_label)

            # Load event label settings from first track that has a labeler
            for track in self.plot_host._tracks.values():
                if track.view._event_labeler is not None:
                    labeler = track.view._event_labeler
                    options = labeler.options

                    # Load enabled state
                    self.event_labels_enabled_cb.setChecked(track.view._event_labels_visible)

                    # Load mode
                    self.event_mode_combo.setCurrentIndex(0)

                    # Load clustering threshold
                    self.event_cluster_spin.setValue(options.min_px)

                    # Load max per cluster
                    self.event_max_per_cluster.setValue(options.max_labels_per_cluster)

                    # Load lanes
                    self.event_lanes_spin.setValue(options.lanes)

                    # Load span siblings
                    self.event_span_siblings_cb.setChecked(options.span_siblings)

                    # Load outline settings
                    self.event_outline_enabled_cb.setChecked(options.outline_enabled)
                    self.event_outline_width.setValue(options.outline_width)

                    # Load font settings
                    if getattr(options, "font_family", None):
                        self.event_font_family.setCurrentText(options.font_family)
                    self.event_font_size_spin.setValue(int(getattr(options, "font_size", 10)))
                    self.event_font_bold.setChecked(bool(getattr(options, "font_bold", False)))
                    self.event_font_italic.setChecked(bool(getattr(options, "font_italic", False)))
                    color_value = getattr(options, "font_color", "#000000")
                    self._set_label_color(self.event_label_color_label, color_value)

                    break

            # Load grid visibility
            if self.plot_host._tracks:
                first_track = next(iter(self.plot_host._tracks.values()))
                plot_item = first_track.view.get_widget().getPlotItem()
                grid_visible = plot_item.ctrl.xGridCheck.isChecked()
                self.grid_visible_cb.setChecked(grid_visible)

        except Exception as e:
            log.error(f"Failed to load PyQtGraph settings: {e}", exc_info=True)

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
            for _track_id, (track, widgets) in self.track_widgets.items():
                # Y-axis limits
                if not widgets["autoscale"].isChecked():
                    y_min = widgets["y_min"].value()
                    y_max = widgets["y_max"].value()
                    track.set_ylim(y_min, y_max)
                else:
                    track.view.set_autoscale_y(True)

                # Visibility
                track.set_visible(widgets["visible"].isChecked())

            # Apply axis titles
            self._apply_axis_titles()

            # Apply line styling
            self._apply_line_styling()

            # Apply event label settings
            self._apply_event_label_settings()

            # Apply grid and appearance
            self._apply_grid_appearance()

            # Apply hover tooltips
            self._apply_hover_tooltips()

            # Notify parent window
            if hasattr(self.parent_window, "on_plot_settings_changed"):
                self.parent_window.on_plot_settings_changed()

        except Exception as e:
            log.error(f"Failed to apply PyQtGraph settings: {e}", exc_info=True)

    def _apply_axis_titles(self):
        """Apply axis title settings."""
        try:
            # X axis title
            x_title = self.x_axis_title_edit.text()
            x_font_family = self.x_axis_font_family.currentText()
            x_font_size = self.x_axis_font_size.value()
            x_color = self._get_label_color(self.x_axis_color_label)

            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                axis = plot_item.getAxis("bottom")
                if x_title:
                    axis.setLabel(x_title)
                # PyQtGraph axis styling is more limited - font size can be set via CSS
                axis.label.setFont(QFont(x_font_family, x_font_size))
                # Color would need custom CSS or stylesheet

            # Y axis titles (per track)
            for _track_id, (track, widgets) in self.y_axis_widgets.items():
                y_title = widgets["title"].text()
                y_font_family = widgets["font_family"].currentText()
                y_font_size = widgets["font_size"].value()

                plot_item = track.view.get_widget().getPlotItem()
                axis = plot_item.getAxis("left")
                if y_title:
                    axis.setLabel(y_title)
                axis.label.setFont(QFont(y_font_family, y_font_size))

            # Tick styling
            tick_font_size = self.tick_font_size.value()
            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                font = QFont("Arial", tick_font_size)
                plot_item.getAxis("bottom").setTickFont(font)
                plot_item.getAxis("left").setTickFont(font)

        except Exception as e:
            log.error(f"Failed to apply axis titles: {e}", exc_info=True)

    def _apply_line_styling(self):
        """Apply line styling settings."""
        try:
            for _track_id, (track, widgets) in self.line_widgets.items():
                line_width = widgets["line_width"].value()
                line_style = widgets["line_style"].currentText()
                line_color = self._get_label_color(widgets["color_label"])
                line_alpha = widgets["alpha"].value()

                # Set line width
                track.set_line_width(line_width)

                # Set line color and alpha
                color = QColor(line_color)
                color.setAlphaF(line_alpha)
                track.primary_line.set_color(color)

                # Set line style
                style_map = {
                    "Solid": Qt.SolidLine,
                    "Dashed": Qt.DashLine,
                    "Dotted": Qt.DotLine,
                    "DashDot": Qt.DashDotLine,
                }
                qt_style = style_map.get(line_style, Qt.SolidLine)
                track.primary_line.set_linestyle(qt_style)

        except Exception as e:
            log.error(f"Failed to apply line styling: {e}", exc_info=True)

    def _apply_event_label_settings(self):
        """Apply event label settings."""
        try:
            from vasoanalyzer.ui.event_labels_v3 import LayoutOptionsV3

            enabled = self.event_labels_enabled_cb.isChecked()

            # Create options from dialog values
            mode = "vertical"

            # Get outline color
            outline_color = None
            if self.event_outline_enabled_cb.isChecked():
                color_hex = self._get_label_color(self.event_outline_color_label)
                color = QColor(color_hex)
                outline_color = (color.redF(), color.greenF(), color.blueF(), 1.0)

            options = LayoutOptionsV3(
                mode=mode,
                min_px=self.event_cluster_spin.value(),
                max_labels_per_cluster=self.event_max_per_cluster.value(),
                lanes=self.event_lanes_spin.value(),
                span_siblings=self.event_span_siblings_cb.isChecked(),
                outline_enabled=self.event_outline_enabled_cb.isChecked(),
                outline_width=self.event_outline_width.value(),
                outline_color=outline_color,
                font_family=self.event_font_family.currentText(),
                font_size=float(self.event_font_size_spin.value()),
                font_bold=self.event_font_bold.isChecked(),
                font_italic=self.event_font_italic.isChecked(),
                font_color=self._get_label_color(self.event_label_color_label),
            )

            # Apply to all tracks
            for track in self.plot_host._tracks.values():
                track.view.enable_event_labels(enabled, options=options if enabled else None)

            # Also update visibility flag
            self.plot_host.set_event_labels_visible(enabled)

        except Exception as e:
            log.error(f"Failed to apply event label settings: {e}", exc_info=True)

    def _apply_grid_appearance(self):
        """Apply grid and appearance settings."""
        try:
            # Grid visibility and styling
            grid_visible = self.grid_visible_cb.isChecked()
            grid_alpha = float(self.grid_alpha.value())

            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                plot_item.showGrid(x=grid_visible, y=grid_visible, alpha=grid_alpha)

            # Background colors
            bg_color = self._get_label_color(self.bg_color_label)
            plot_bg_color = self._get_label_color(self.plot_bg_color_label)

            self.plot_host.widget.setStyleSheet(f"background-color: {bg_color};")

            for track in self.plot_host._tracks.values():
                plot_widget = track.view.get_widget()
                plot_widget.setBackground(plot_bg_color)

        except Exception as e:
            log.error(f"Failed to apply grid/appearance settings: {e}", exc_info=True)

    def _apply_hover_tooltips(self):
        """Apply hover tooltip settings."""
        try:
            enabled = self.tooltip_enabled_cb.isChecked()
            precision = self.tooltip_precision.value()

            # Enable/disable tooltips on all tracks
            for track in self.plot_host._tracks.values():
                track.view.enable_hover_tooltip(enabled, precision=precision)

        except Exception as e:
            log.error(f"Failed to apply hover tooltip settings: {e}", exc_info=True)

    def _restore_defaults(self):
        """Restore default settings."""
        # This would reset all controls to default values
        # Implementation depends on what defaults should be
        pass
