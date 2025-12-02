"""Comprehensive PyQtGraph plot settings dialog.

This dialog provides full control over PyQtGraph renderer settings, matching
and exceeding the capabilities of the matplotlib-based settings dialog.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, TypedDict

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
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
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec

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

        self.track_widgets: dict[str, tuple[PyQtGraphChannelTrack | None, TrackWidgetControls]] = {}
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

        # Make the tabs a bit wider and nicely padded
        self.tabs.setStyleSheet(
            """
            QTabBar::tab {
                padding: 6px 18px;   /* top/bottom, left/right */
                min-width: 110px;    /* make each tab a bit longer */
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
        """
        )

        # Create tabs
        self.tabs.addTab(self._create_traces_lines_tab(), "Traces && Lines")
        self.tabs.addTab(self._create_axes_grid_tab(), "Axes && Grid")
        self.tabs.addTab(self._create_event_labels_tab(), "Event Labels")

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

        intro = QLabel(
            "Control per-track visibility and Y-axis scaling. " "X-range is controlled elsewhere."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(intro)

        # Scroll area for multiple tracks
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)

        tracks_group = QGroupBox("Tracks")
        grid = QGridLayout(tracks_group)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)
        headers = ["Track", "Show", "Auto Y", "Y min", "Y max"]
        for col, text in enumerate(headers):
            header_label = QLabel(text)
            header_label.setStyleSheet("font-weight: bold;")
            grid.addWidget(header_label, 0, col)

        self.track_widgets = {}
        row = 1
        for idx, spec in enumerate(self.plot_host.iter_channels()):
            track = self.plot_host.track(spec.track_id)
            label_text, widgets = self._create_track_group(spec, track, idx)
            name_label = QLabel(label_text)
            grid.addWidget(name_label, row, 0)
            grid.addWidget(widgets["visible"], row, 1, alignment=Qt.AlignCenter)
            grid.addWidget(widgets["autoscale"], row, 2, alignment=Qt.AlignCenter)
            grid.addWidget(widgets["y_min"], row, 3)
            grid.addWidget(widgets["y_max"], row, 4)
            row += 1

        container_layout.addWidget(tracks_group)
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        return tab

    def _create_traces_lines_tab(self) -> QWidget:
        """Composite tab combining Tracks and Lines & Markers for analysis."""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        tracks_widget = self._create_tracks_tab()
        lines_widget = self._create_lines_markers_tab()

        content_layout.addWidget(tracks_widget)
        content_layout.addWidget(lines_widget)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        return tab

    def _create_axes_grid_tab(self) -> QWidget:
        """Composite tab combining Tick Style (Axes) and Grid & Appearance."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._create_axis_titles_tab())
        layout.addWidget(self._create_appearance_tab())
        layout.addStretch(1)
        return tab

    def _create_track_group(
        self, spec: ChannelTrackSpec, track: PyQtGraphChannelTrack | None, idx: int
    ) -> tuple[str, TrackWidgetControls]:
        """Create widgets for a single track row and register them."""
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
        auto_scale_cb.setChecked(track.view._autoscale_y if track is not None else True)

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

        intro = QLabel("Set axis titles, fonts, and global tick style for all tracks.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: gray; margin-bottom: 8px;")
        layout.addWidget(intro)

        x_axis_group = QGroupBox("X Axis", content)
        x_form = QFormLayout(x_axis_group)
        x_form.setLabelAlignment(Qt.AlignRight)

        self.x_axis_title_edit = QLineEdit()
        self.x_axis_title_edit.setPlaceholderText("Time (s)")
        x_form.addRow("Title:", self.x_axis_title_edit)

        font_row = QWidget()
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.setSpacing(8)
        self.x_axis_font_family = QComboBox()
        self.x_axis_font_family.addItems(self._font_choices)
        font_layout.addWidget(self.x_axis_font_family, 2)
        self.x_axis_font_size = QSpinBox()
        self.x_axis_font_size.setRange(6, 48)
        self.x_axis_font_size.setValue(20)
        font_layout.addWidget(self.x_axis_font_size, 1)
        x_form.addRow("Font:", font_row)

        # X and Y axis title/font controls are omitted from the visible layout in
        # the PyQtGraph dialog to keep this tab focused on analysis-time tick styling.
        # They remain constructed here so we can re-enable them later if needed.

        y_axis_group = QGroupBox("Y Axes (per track)", content)
        y_grid = QGridLayout(y_axis_group)
        y_grid.setHorizontalSpacing(16)
        y_grid.setVerticalSpacing(12)
        y_grid.setColumnStretch(0, 1)
        y_grid.setColumnStretch(1, 1)

        helper_box = QGroupBox("All Y Axes", y_axis_group)
        helper_form = QFormLayout(helper_box)
        helper_form.setLabelAlignment(Qt.AlignRight)
        helper_row = QWidget()
        helper_layout = QHBoxLayout(helper_row)
        helper_layout.setContentsMargins(0, 0, 0, 0)
        helper_layout.setSpacing(8)
        self.y_all_font_family = QComboBox()
        self.y_all_font_family.addItems(self._font_choices)
        self.y_all_font_family.setMaximumWidth(160)
        helper_layout.addWidget(self.y_all_font_family, 2)
        self.y_all_font_size = QSpinBox()
        self.y_all_font_size.setRange(6, 48)
        self.y_all_font_size.setValue(20)
        self.y_all_font_size.setMaximumWidth(70)
        helper_layout.addWidget(self.y_all_font_size, 1)
        self.y_all_apply_btn = QPushButton("Apply to all")
        helper_layout.addWidget(self.y_all_apply_btn)
        helper_form.addRow("Font:", helper_row)
        y_grid.addWidget(helper_box, 0, 0, 1, 2)

        self._y_all_helper_ready = False
        self.y_all_font_family.currentTextChanged.connect(self._on_y_all_helper_changed)
        self.y_all_font_size.valueChanged.connect(self._on_y_all_helper_changed)
        self.y_all_apply_btn.clicked.connect(self._on_apply_y_axis_font_to_all_clicked)

        self.y_axis_widgets = {}
        for idx, (track_id, track) in enumerate(self.plot_host._tracks.items()):
            track_box = QGroupBox(track.spec.label, y_axis_group)
            track_form = QFormLayout(track_box)
            track_form.setLabelAlignment(Qt.AlignRight)

            title_edit = QLineEdit()
            title_edit.setPlaceholderText(track.spec.label)
            track_form.addRow("Label:", title_edit)

            font_row = QWidget()
            font_layout = QHBoxLayout(font_row)
            font_layout.setContentsMargins(0, 0, 0, 0)
            font_layout.setSpacing(8)
            font_family = QComboBox()
            font_family.addItems(self._font_choices)
            font_family.setMaximumWidth(160)
            font_layout.addWidget(font_family, 2)
            font_size = QSpinBox()
            font_size.setRange(6, 48)
            font_size.setValue(20)
            font_size.setMaximumWidth(70)
            font_layout.addWidget(font_size, 1)

            track_form.addRow("Font:", font_row)

            track_widgets: AxisTitleWidgets = {
                "title": title_edit,
                "font_family": font_family,
                "font_size": font_size,
            }

            row = 1 + idx // 2
            col = idx % 2
            y_grid.addWidget(track_box, row, col)
            self.y_axis_widgets[track_id] = (track, track_widgets)

        tick_group = QGroupBox("Tick Style (global)")
        tick_form = QFormLayout(tick_group)
        tick_form.setLabelAlignment(Qt.AlignRight)

        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(16)
        tick_form.addRow("Font size:", self.tick_font_size)

        tick_length_row = QWidget()
        tick_length_layout = QHBoxLayout(tick_length_row)
        tick_length_layout.setContentsMargins(0, 0, 0, 0)
        tick_length_layout.setSpacing(8)
        self.x_tick_length = QSpinBox()
        self.x_tick_length.setRange(0, 20)
        self.x_tick_length.setValue(5)
        self.x_tick_length.setSuffix(" px")
        tick_length_layout.addWidget(QLabel("X"))
        tick_length_layout.addWidget(self.x_tick_length)
        self.y_tick_length = QSpinBox()
        self.y_tick_length.setRange(0, 20)
        self.y_tick_length.setValue(5)
        self.y_tick_length.setSuffix(" px")
        tick_length_layout.addSpacing(12)
        tick_length_layout.addWidget(QLabel("Y"))
        tick_length_layout.addWidget(self.y_tick_length)
        tick_form.addRow("Tick length:", tick_length_row)

        tick_color_widget = self._create_color_picker_widget()
        self.tick_color_btn = tick_color_widget["button"]
        self.tick_color_label = tick_color_widget["label"]
        tick_form.addRow("Tick color:", tick_color_widget["widget"])

        layout.addWidget(tick_group)
        # Keep axis title/font controls hidden (out of layout) but alive to avoid crashes
        x_axis_group.hide()
        y_axis_group.hide()

        layout.addStretch(1)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        return tab

    def _on_apply_y_axis_font_to_all_clicked(self) -> None:
        family = self.y_all_font_family.currentText()
        size = self.y_all_font_size.value()
        if not family:
            return

        for _track, widgets in self.y_axis_widgets.values():
            widgets["font_family"].setCurrentText(family)
            widgets["font_size"].setValue(size)

    def _on_apply_line_style_to_all_clicked(self) -> None:
        width = self.lines_all_width.value()
        style = self.lines_all_style.currentText()
        color_hex = self._get_label_color(self.lines_all_color_label)
        alpha = self.lines_all_alpha.value()

        for _track, widgets in self.line_widgets.values():
            widgets["line_width"].setValue(width)
            widgets["line_style"].setCurrentText(style)
            self._set_label_color(widgets["color_label"], color_hex)
            widgets["alpha"].setValue(alpha)

    def _on_y_all_helper_changed(self) -> None:
        if not getattr(self, "_y_all_helper_ready", False):
            return
        self._on_apply_y_axis_font_to_all_clicked()

    # ========================================================================
    # TAB 3: LINES & MARKERS
    # ========================================================================
    def _create_lines_markers_tab(self) -> QWidget:
        """Create lines and markers styling tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        # Trace Lines Section (per track)
        lines_group = QGroupBox("Trace Line Styling (Per Track)")
        lines_grid = QGridLayout(lines_group)
        lines_grid.setHorizontalSpacing(16)
        lines_grid.setVerticalSpacing(12)
        lines_grid.setColumnStretch(0, 1)
        lines_grid.setColumnStretch(1, 1)

        helper_box = QGroupBox("All Lines")
        helper_layout = QVBoxLayout(helper_box)
        helper_layout.setContentsMargins(8, 8, 8, 8)
        hint = QLabel(
            "Copies this style into all trace controls. Click Apply in the dialog to commit to the plot."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        helper_layout.addWidget(hint)

        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(8)
        self.lines_all_width = QDoubleSpinBox()
        self.lines_all_width.setRange(0.5, 10.0)
        self.lines_all_width.setSingleStep(0.5)
        self.lines_all_width.setDecimals(1)
        self.lines_all_width.setMaximumWidth(80)
        row1_layout.addWidget(QLabel("Width:"))
        row1_layout.addWidget(self.lines_all_width)
        self.lines_all_style = QComboBox()
        self.lines_all_style.addItems(["Solid", "Dashed", "Dotted", "DashDot"])
        self.lines_all_style.setMaximumWidth(140)
        row1_layout.addSpacing(6)
        row1_layout.addWidget(QLabel("Style:"))
        row1_layout.addWidget(self.lines_all_style)
        row1_layout.addStretch()
        helper_layout.addWidget(row1)

        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(8)
        all_color_widget = self._create_color_picker_widget()
        self.lines_all_color_btn = all_color_widget["button"]
        self.lines_all_color_label = all_color_widget["label"]
        row2_layout.addWidget(QLabel("Color:"))
        row2_layout.addWidget(all_color_widget["widget"])
        self.lines_all_alpha = QDoubleSpinBox()
        self.lines_all_alpha.setRange(0.0, 1.0)
        self.lines_all_alpha.setSingleStep(0.1)
        self.lines_all_alpha.setDecimals(2)
        self.lines_all_alpha.setMaximumWidth(80)
        self.lines_all_alpha.setToolTip("0 = fully transparent, 1 = fully opaque")
        row2_layout.addSpacing(6)
        row2_layout.addWidget(QLabel("Opacity:"))
        row2_layout.addWidget(self.lines_all_alpha)
        row2_layout.addStretch()
        self.lines_all_apply_btn = QPushButton("Apply to all traces")
        row2_layout.addWidget(self.lines_all_apply_btn)
        helper_layout.addWidget(row2)

        lines_grid.addWidget(helper_box, 0, 0, 1, 2)

        self.lines_all_apply_btn.clicked.connect(self._on_apply_line_style_to_all_clicked)

        self.line_widgets = {}
        for idx, (track_id, track) in enumerate(self.plot_host._tracks.items()):
            track_box = QGroupBox(track.spec.label)
            track_form = QFormLayout(track_box)
            track_form.setLabelAlignment(Qt.AlignRight)

            line_width_spin = QDoubleSpinBox()
            line_width_spin.setRange(0.5, 10.0)
            line_width_spin.setSingleStep(0.5)
            line_width_spin.setDecimals(1)
            line_width_spin.setMaximumWidth(80)
            try:
                current_width = track.primary_line.get_linewidth()
                line_width_spin.setValue(current_width)
            except Exception:
                line_width_spin.setValue(4.0)
            line_style_combo = QComboBox()
            line_style_combo.addItems(["Solid", "Dashed", "Dotted", "DashDot"])
            line_style_combo.setMaximumWidth(140)
            try:
                current_style = None
                if track.primary_line:
                    current_style = track.primary_line.get_linestyle()
                style_lookup = {
                    "-": "Solid",
                    "solid": "Solid",
                    "--": "Dashed",
                    "dashed": "Dashed",
                    ":": "Dotted",
                    "dotted": "Dotted",
                    "-.": "DashDot",
                    "dashdot": "DashDot",
                }
                style_key = current_style.lower() if isinstance(current_style, str) else ""
                display_style = style_lookup.get(style_key, "Solid")
                index = line_style_combo.findText(display_style)
                if index >= 0:
                    line_style_combo.setCurrentIndex(index)
            except Exception:
                pass

            current_color = "#000000"
            current_alpha = 1.0
            try:
                if track.primary_line:
                    current_color = track.primary_line.get_color()
                    current_alpha = track.primary_line.get_alpha()
            except Exception:
                pass

            color_widget = self._create_color_picker_widget(current_color)

            line_alpha_spin = QDoubleSpinBox()
            line_alpha_spin.setRange(0.0, 1.0)
            line_alpha_spin.setSingleStep(0.1)
            line_alpha_spin.setDecimals(2)
            line_alpha_spin.setValue(current_alpha)
            line_alpha_spin.setMaximumWidth(80)
            line_alpha_spin.setToolTip("0 = fully transparent, 1 = fully opaque")

            # Compact 2-row layout inside each track block
            row1 = QWidget()
            row1_layout = QHBoxLayout(row1)
            row1_layout.setContentsMargins(0, 0, 0, 0)
            row1_layout.setSpacing(8)
            row1_layout.addWidget(line_width_spin)
            row1_layout.addWidget(line_style_combo)
            row1_layout.addStretch()
            track_form.addRow("Line:", row1)

            row2 = QWidget()
            row2_layout = QHBoxLayout(row2)
            row2_layout.setContentsMargins(0, 0, 0, 0)
            row2_layout.setSpacing(8)
            row2_layout.addWidget(color_widget["widget"])
            row2_layout.addWidget(line_alpha_spin)
            row2_layout.addStretch()
            track_form.addRow("Color / opacity:", row2)

            track_widgets: LineStyleWidgets = {
                "line_width": line_width_spin,
                "line_style": line_style_combo,
                "color_btn": color_widget["button"],
                "color_label": color_widget["label"],
                "alpha": line_alpha_spin,
            }

            row = 1 + idx // 2
            col = idx % 2
            lines_grid.addWidget(track_box, row, col)
            self.line_widgets[track_id] = (track, track_widgets)

        first_line_widgets = next(iter(self.line_widgets.values()), None)
        if first_line_widgets:
            _track, widgets = first_line_widgets
            self.lines_all_width.setValue(widgets["line_width"].value())
            self.lines_all_style.setCurrentText(widgets["line_style"].currentText())
            self._set_label_color(
                self.lines_all_color_label,
                self._get_label_color(widgets["color_label"]),
            )
            self.lines_all_alpha.setValue(widgets["alpha"].value())

        layout.addWidget(lines_group)

        # Event Markers Section
        markers_group = QGroupBox("Event Markers (future)")
        markers_placeholder = QVBoxLayout(markers_group)
        markers_placeholder.setContentsMargins(8, 8, 8, 8)
        markers_placeholder.setSpacing(4)
        placeholder_label = QLabel("Event marker styling will be available in a future release.")
        placeholder_label.setWordWrap(True)
        placeholder_label.setStyleSheet("color: gray;")
        markers_placeholder.addWidget(placeholder_label)
        markers_group.setEnabled(False)
        # Not added to layout to avoid unused controls overwhelming the tab

        # Event Lines Section (vertical dashed lines)
        event_lines_group = QGroupBox("Event Lines (Vertical Markers)")
        event_lines_form = QFormLayout(event_lines_group)
        event_lines_form.setLabelAlignment(Qt.AlignRight)

        self.event_line_width_spin = QDoubleSpinBox()
        self.event_line_width_spin.setRange(0.5, 5.0)
        self.event_line_width_spin.setSingleStep(0.1)
        self.event_line_width_spin.setDecimals(1)
        self.event_line_width_spin.setValue(2.0)
        event_lines_form.addRow("Line Width:", self.event_line_width_spin)

        self.event_line_style_combo = QComboBox()
        self.event_line_style_combo.addItems(["Solid", "Dashed", "Dotted", "DashDot"])
        self.event_line_style_combo.setCurrentIndex(1)  # Default to Dashed
        event_lines_form.addRow("Line Style:", self.event_line_style_combo)

        event_line_color_widget = self._create_color_picker_widget("#8A8A8A")
        self.event_line_color_btn = event_line_color_widget["button"]
        self.event_line_color_label = event_line_color_widget["label"]
        event_lines_form.addRow("Line Color:", event_line_color_widget["widget"])

        self.event_line_alpha_spin = QDoubleSpinBox()
        self.event_line_alpha_spin.setRange(0.0, 1.0)
        self.event_line_alpha_spin.setSingleStep(0.1)
        self.event_line_alpha_spin.setDecimals(2)
        self.event_line_alpha_spin.setToolTip("0 = fully transparent, 1 = fully opaque")
        self.event_line_alpha_spin.setValue(1.0)
        event_lines_form.addRow("Line opacity:", self.event_line_alpha_spin)

        layout.addWidget(event_lines_group)

        layout.addStretch()
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

        scope_label = QLabel("Event label settings apply to all PyQtGraph tracks in this view.")
        scope_label.setWordWrap(True)
        scope_label.setStyleSheet("color: gray;")
        layout.addWidget(scope_label)

        # Enable/disable
        enable_group = QGroupBox("Event Labels")
        enable_layout = QVBoxLayout(enable_group)

        self.event_labels_enabled_cb = QCheckBox("Show Event Labels")
        self.event_labels_enabled_cb.setChecked(True)
        enable_layout.addWidget(self.event_labels_enabled_cb)

        self.event_show_numbers_cb = QCheckBox("Show Numbers Only (instead of full text)")
        self.event_show_numbers_cb.setChecked(True)
        self.event_show_numbers_cb.setToolTip(
            "Display event index numbers (1, 2, 3...) instead of full event labels"
        )
        enable_layout.addWidget(self.event_show_numbers_cb)

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
        self.event_mode_combo.setToolTip(
            "PyQtGraph currently renders event labels vertically; other modes are unavailable."
        )
        layout_form.addRow("Label Mode (fixed to Vertical):", self.event_mode_combo)

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
        self.grid_alpha.setToolTip("0 = fully transparent, 1 = fully opaque")
        self.grid_alpha.setValue(0.10)
        grid_form.addRow("Grid Alpha (Opacity):", self.grid_alpha)

        grid_color_widget = self._create_color_picker_widget("#CCCCCC")
        self.grid_color_btn = grid_color_widget["button"]
        self.grid_color_label = grid_color_widget["label"]
        grid_form.addRow("Grid Color:", grid_color_widget["widget"])

        layout.addWidget(grid_group)

        with contextlib.suppress(Exception):
            self.grid_color_btn.setEnabled(False)
            self.grid_color_label.setEnabled(False)
            self.grid_color_btn.setToolTip(
                "Grid line color follows tick color settings on the 'Axis & Titles' tab."
            )

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
        color_label.setCursor(Qt.PointingHandCursor)

        color_btn = QPushButton("Choose...")
        color_btn.clicked.connect(lambda: self._pick_color(color_label))

        # Allow clicking the swatch itself to open the color picker
        def _on_label_click(event):
            self._pick_color(color_label)

        color_label.mousePressEvent = _on_label_click  # type: ignore[method-assign]

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
            if label is getattr(self, "y_all_color_label", None):
                self._on_y_all_helper_changed()

    def _get_label_color(self, label: QLabel) -> str:
        """Extract color from label stylesheet."""
        style = label.styleSheet()
        return style.split("background-color: ")[1].split(";")[0]

    def _on_track_autoscale_toggled(self, track_id: str, checked: bool) -> None:
        entry = self.track_widgets.get(track_id)
        if not entry:
            return
        widgets = entry[1]
        widgets["y_min"].setEnabled(not checked)
        widgets["y_max"].setEnabled(not checked)

    def _set_label_color(self, label: QLabel, color: str) -> None:
        """Apply a hex color to a preview swatch label."""
        if not color:
            color = "#000000"
        label.setStyleSheet(f"background-color: {color}; border: 1px solid #999;")

    def _color_tuple_to_hex(self, color) -> str:
        if not color:
            return "#000000"
        try:
            r, g, b, *_ = list(color) + [1.0]

            def _component(value):
                value = float(value)
                if value <= 1.0:
                    value *= 255.0
                return max(0, min(255, int(round(value))))

            return f"#{_component(r):02X}{_component(g):02X}{_component(b):02X}"
        except Exception:
            return "#000000"

    def _hex_to_rgb_tuple(self, color_hex: str) -> tuple[int, int, int]:
        color = QColor(color_hex)
        return (color.red(), color.green(), color.blue())

    def _rgb_to_hex(self, color: tuple[int, int, int]) -> str:
        try:
            r, g, b = color
            return f"#{int(r):02X}{int(g):02X}{int(b):02X}"
        except Exception:
            return "#000000"

    def _set_event_label_controls(self, options, enabled: bool) -> None:
        self.event_labels_enabled_cb.setChecked(bool(enabled))
        mode_map = {"vertical": 0, "h_inside": 1, "h_belt": 2}
        mode_idx = mode_map.get(getattr(options, "mode", "vertical"), 0)
        self.event_mode_combo.setCurrentIndex(mode_idx)
        self.event_cluster_spin.setValue(int(getattr(options, "min_px", 24)))
        self.event_max_per_cluster.setValue(int(getattr(options, "max_labels_per_cluster", 1)))
        self.event_lanes_spin.setValue(int(getattr(options, "lanes", 3)))
        self.event_span_siblings_cb.setChecked(bool(getattr(options, "span_siblings", True)))
        self.event_outline_enabled_cb.setChecked(bool(getattr(options, "outline_enabled", False)))
        self.event_outline_width.setValue(float(getattr(options, "outline_width", 1.0)))
        outline_color = getattr(options, "outline_color", None)
        if outline_color:
            self._set_label_color(
                self.event_outline_color_label, self._color_tuple_to_hex(outline_color)
            )
        font_family = getattr(options, "font_family", None)
        if font_family:
            self.event_font_family.setCurrentText(font_family)
        self.event_font_size_spin.setValue(int(getattr(options, "font_size", 10)))
        self.event_font_bold.setChecked(bool(getattr(options, "font_bold", False)))
        self.event_font_italic.setChecked(bool(getattr(options, "font_italic", False)))
        font_color = getattr(options, "font_color", "#000000") or "#000000"
        self._set_label_color(self.event_label_color_label, font_color)
        show_numbers_only = getattr(options, "show_numbers_only", False)
        self.event_show_numbers_cb.setChecked(bool(show_numbers_only))

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
            axis_font_family = None
            axis_font_size = None
            with contextlib.suppress(Exception):
                axis_font_family, axis_font_size = self.plot_host.axis_font()
            if axis_font_family:
                self.x_axis_font_family.setCurrentText(axis_font_family)
            if axis_font_size:
                self.x_axis_font_size.setValue(int(axis_font_size))
            with contextlib.suppress(Exception):
                tick_size = self.plot_host.tick_font_size()
                self.tick_font_size.setValue(int(tick_size))

            # Track visibility from host state
            for track_id, (_track, widgets) in self.track_widgets.items():
                widgets["visible"].setChecked(self.plot_host.is_channel_visible(track_id))

            # Load Y axis titles
            first_widgets = None
            for _track_id, (track, widgets) in self.y_axis_widgets.items():
                if first_widgets is None:
                    first_widgets = widgets
                plot_item = track.view.get_widget().getPlotItem()
                y_label = plot_item.getAxis("left").label.toPlainText()
                if y_label:
                    widgets["title"].setText(y_label)
            if first_widgets is not None:
                self.y_all_font_family.setCurrentText(first_widgets["font_family"].currentText())
                self.y_all_font_size.setValue(first_widgets["font_size"].value())
                self._y_all_helper_ready = True

            # Load event label settings from first track that has a labeler
            label_options_loaded = False
            for track in self.plot_host._tracks.values():
                if track.view._event_labeler is not None:
                    options = track.view._event_labeler.options
                    self._set_event_label_controls(options, track.view._event_labels_visible)
                    label_options_loaded = True
                    break
            if not label_options_loaded:
                options = getattr(self.plot_host, "_event_label_options", None)
                if options is not None:
                    enabled_flag = getattr(self.plot_host, "_event_labels_enabled", True)
                    self._set_event_label_controls(options, enabled_flag)

            with contextlib.suppress(Exception):
                x_visible, y_visible, grid_alpha = self.plot_host.grid_state()
                self.grid_visible_cb.setChecked(bool(x_visible and y_visible))
                self.grid_alpha.setValue(float(grid_alpha))

            bg_color = getattr(self.plot_host, "window_background_color", None)
            if callable(bg_color):
                bg_color = bg_color()
            if bg_color:
                self._set_label_color(self.bg_color_label, self._rgb_to_hex(bg_color))

            plot_bg_color = getattr(self.plot_host, "plot_background_color", None)
            if callable(plot_bg_color):
                plot_bg_color = plot_bg_color()
            if plot_bg_color:
                self._set_label_color(self.plot_bg_color_label, self._rgb_to_hex(plot_bg_color))

            with contextlib.suppress(Exception):
                self.tooltip_enabled_cb.setChecked(self.plot_host.label_tooltips_enabled())
                self.tooltip_precision.setValue(int(self.plot_host.tooltip_precision()))

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
                    with contextlib.suppress(Exception):
                        track.autoscale()

                # Visibility
                self.plot_host.set_channel_visible(track_id, widgets["visible"].isChecked())

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
            if hasattr(self.parent_window, "_sync_track_visibility_from_host"):
                with contextlib.suppress(Exception):
                    self.parent_window._sync_track_visibility_from_host()
            if self.plot_host is not None and hasattr(self.plot_host, "debug_dump_state"):
                self.plot_host.debug_dump_state("pyqtgraph_settings_apply (after)")

        except Exception as e:
            log.error(f"Failed to apply PyQtGraph settings: {e}", exc_info=True)

    def _apply_axis_titles(self):
        """Apply axis title settings."""
        try:
            # X axis title
            x_title = self.x_axis_title_edit.text()
            x_font_family = self.x_axis_font_family.currentText()
            x_font_size = self.x_axis_font_size.value()
            tick_color = QColor(self._get_label_color(self.tick_color_label))
            x_tick_length = int(self.x_tick_length.value())
            y_tick_length = int(self.y_tick_length.value())
            tick_font_size = self.tick_font_size.value()
            self.plot_host.set_axis_font(family=x_font_family, size=x_font_size)
            self.plot_host.set_tick_font_size(tick_font_size)
            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                axis = plot_item.getAxis("bottom")
                axis.label.setFont(QFont(x_font_family, x_font_size))
            # Y axis titles (per track)
            for _track_id, (track, widgets) in self.y_axis_widgets.items():
                y_title = widgets["title"].text()
                y_font_family = widgets["font_family"].currentText()
                y_font_size = widgets["font_size"].value()

                plot_item = track.view.get_widget().getPlotItem()
                axis = plot_item.getAxis("left")
                axis.label.setFont(QFont(y_font_family, y_font_size))

            # Tick styling
            tick_font = QFont("Arial", tick_font_size)
            for track in self.plot_host._tracks.values():
                plot_item = track.view.get_widget().getPlotItem()
                bottom_axis = plot_item.getAxis("bottom")
                left_axis = plot_item.getAxis("left")
                bottom_axis.setTickFont(tick_font)
                left_axis.setTickFont(tick_font)
                bottom_axis.setStyle(tickLength=x_tick_length)
                left_axis.setStyle(tickLength=y_tick_length)
                bottom_axis.setTextPen(tick_color)
                bottom_axis.setPen(tick_color)
                left_axis.setTextPen(tick_color)
                left_axis.setPen(tick_color)

        except Exception as e:
            log.error(f"Failed to apply axis titles: {e}", exc_info=True)

    def _apply_line_styling(self):
        """Apply line styling settings."""
        try:
            default_width = None
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
                if default_width is None:
                    default_width = line_width

            if default_width is not None:
                with contextlib.suppress(Exception):
                    self.plot_host.set_default_line_width(default_width)

            # Apply event line styling
            event_line_width = self.event_line_width_spin.value()
            event_line_style_text = self.event_line_style_combo.currentText()
            event_line_color = self._get_label_color(self.event_line_color_label)
            event_line_alpha = self.event_line_alpha_spin.value()

            # Map style text to Qt style
            style_map = {
                "Solid": Qt.SolidLine,
                "Dashed": Qt.DashLine,
                "Dotted": Qt.DotLine,
                "DashDot": Qt.DashDotLine,
            }
            event_line_qt_style = style_map.get(event_line_style_text, Qt.DashLine)

            # Apply to all tracks
            for _track_id, track in self.plot_host._tracks.items():
                track.view.set_event_line_style(
                    width=event_line_width,
                    style=event_line_qt_style,
                    color=event_line_color,
                    alpha=event_line_alpha,
                )

        except Exception as e:
            log.error(f"Failed to apply line styling: {e}", exc_info=True)

    def _apply_event_label_settings(self):
        """Apply event label settings."""
        try:
            enabled = self.event_labels_enabled_cb.isChecked()

            # Create options from dialog values
            mode_map = {
                0: "vertical",
                1: "h_inside",
                2: "h_belt",
            }
            mode = mode_map.get(self.event_mode_combo.currentIndex(), "vertical")

            # Get outline color
            outline_color = None
            if self.event_outline_enabled_cb.isChecked():
                color_hex = self._get_label_color(self.event_outline_color_label)
                color = QColor(color_hex)
                outline_color = (color.redF(), color.greenF(), color.blueF(), 1.0)

            host = self.plot_host
            host.set_event_labels_visible(enabled)
            host.set_event_label_mode(mode)
            host.set_event_label_gap(self.event_cluster_spin.value())
            host.set_max_labels_per_cluster(self.event_max_per_cluster.value())
            host.set_label_lanes(self.event_lanes_spin.value())
            host.set_event_label_span_siblings(self.event_span_siblings_cb.isChecked())
            host.set_label_outline_enabled(self.event_outline_enabled_cb.isChecked())
            host.set_label_outline(self.event_outline_width.value(), outline_color)
            host.set_event_base_style(
                font_family=self.event_font_family.currentText(),
                font_size=float(self.event_font_size_spin.value()),
                bold=self.event_font_bold.isChecked(),
                italic=self.event_font_italic.isChecked(),
                color=self._get_label_color(self.event_label_color_label),
                show_numbers_only=self.event_show_numbers_cb.isChecked(),
            )

        except Exception as e:
            log.error(f"Failed to apply event label settings: {e}", exc_info=True)

    def _apply_grid_appearance(self):
        """Apply grid and appearance settings."""
        try:
            # Grid visibility and styling
            grid_visible = self.grid_visible_cb.isChecked()
            grid_alpha = float(self.grid_alpha.value())
            self.plot_host.set_grid_visible(grid_visible, alpha=grid_alpha)

            # Keep toolbar and persisted flag in sync with the host state
            owner = getattr(self, "parent_window", None) or self.parent()
            while owner is not None and not hasattr(owner, "grid_visible"):
                owner = owner.parent()
            if owner is not None:
                with contextlib.suppress(Exception):
                    owner.grid_visible = grid_visible
                    if hasattr(owner, "_sync_grid_action"):
                        owner._sync_grid_action()

            bg_color_hex = self._get_label_color(self.bg_color_label)
            plot_bg_hex = self._get_label_color(self.plot_bg_color_label)

            self.plot_host.set_window_background_color(self._hex_to_rgb_tuple(bg_color_hex))
            self.plot_host.set_plot_background_color(self._hex_to_rgb_tuple(plot_bg_hex))

        except Exception as e:
            log.error(f"Failed to apply grid/appearance settings: {e}", exc_info=True)

    def _apply_hover_tooltips(self):
        """Apply hover tooltip settings."""
        try:
            enabled = self.tooltip_enabled_cb.isChecked()
            precision = self.tooltip_precision.value()

            self.plot_host.set_label_tooltips_enabled(enabled)
            self.plot_host.set_tooltip_precision(precision)

        except Exception as e:
            log.error(f"Failed to apply hover tooltip settings: {e}", exc_info=True)

    def _restore_defaults(self):
        """Restore default settings."""
        # This would reset all controls to default values
        # Implementation depends on what defaults should be
        pass
