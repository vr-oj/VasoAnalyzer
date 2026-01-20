from __future__ import annotations

from typing import TYPE_CHECKING

import logging
from PyQt5.QtCore import QEvent, QObject, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.event_table import EventTableWidget
from vasoanalyzer.ui.event_table_controller import EventTableController
from vasoanalyzer.ui.interactions import InteractionController
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.mpl_interactions import MplInteractionHost
from vasoanalyzer.ui.plots.overview_strip import OverviewStrip
from vasoanalyzer.ui.plots.renderer_factory import create_plot_host
from vasoanalyzer.ui.snapshot_viewer import SnapshotTimelineWidget
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


log = logging.getLogger(__name__)


class _PlotLeaveFilter(QObject):
    """Event filter to forward leave events from PG widget to handler."""

    def __init__(self, on_leave, parent=None):
        super().__init__(parent)
        self._on_leave = on_leave

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Leave:
            try:
                self._on_leave()
            except Exception:
                pass
        return False


class _SnapshotPreviewLabel(QLabel):
    """QLabel used for the legacy snapshot viewer with resize logging."""

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        log.debug(
            "LegacySnapshotView.resizeEvent: size=%dx%d",
            self.width(),
            self.height(),
        )


def init_ui(window: VasoAnalyzerApp) -> None:
    """Initialise stacked layout, plot host, and ancillary widgets."""

    window.stack = QStackedWidget()
    window.setCentralWidget(window.stack)

    window.data_page = QWidget()
    window.data_page.setObjectName("DataPage")
    window.stack.addWidget(window.data_page)

    window.main_layout = QVBoxLayout(window.data_page)
    window.main_layout.setContentsMargins(16, 8, 16, 16)
    window.main_layout.setSpacing(12)

    dpi = int(QApplication.primaryScreen().logicalDotsPerInch())
    # Main trace view uses PyQtGraph by default:
    # - renderer_factory.get_default_renderer_type() -> "pyqtgraph"
    # - window.fig stays None for this backend
    # - window.canvas is a PyQtGraphCanvasCompat wrapper around plot_host.widget()
    # Matplotlib is reserved for static exports, not the live trace view.
    window.plot_host = create_plot_host(dpi=dpi)
    backend = (
        window.plot_host.get_render_backend()
        if hasattr(window.plot_host, "get_render_backend")
        else "matplotlib"
    )
    use_pyqtgraph = backend == "pyqtgraph"
    window.fig = window.plot_host.figure if not use_pyqtgraph else None
    window.canvas = window.plot_host.canvas if not use_pyqtgraph else window.plot_host.canvas
    window.trace_widget = window.plot_host.widget() if use_pyqtgraph else window.canvas
    if hasattr(window.plot_host, "set_click_handler"):
        window.plot_host.set_click_handler(window._handle_pyqtgraph_click)
    target_mouse_widget = window.plot_host.widget() if use_pyqtgraph else window.canvas
    target_mouse_widget.setMouseTracking(True)
    if use_pyqtgraph:
        target_mouse_widget.setFocusPolicy(Qt.StrongFocus)
        # For any legacy draw_idle calls, forward to the native PG redraw.
        if hasattr(window, "plot_host") and hasattr(window.plot_host, "redraw"):
            window.canvas.draw_idle = window.plot_host.redraw  # type: ignore[attr-defined]
        # Handle leave events via Qt for PyQtGraph backend
        window._pg_leave_filter = _PlotLeaveFilter(window._handle_figure_leave, target_mouse_widget)
        target_mouse_widget.installEventFilter(window._pg_leave_filter)
    if not use_pyqtgraph:
        window.canvas.toolbar = None

    window.overview_strip = OverviewStrip(window)
    window.overview_strip.timeWindowRequested.connect(
        window._on_trace_nav_window_requested
    )
    window.overview_strip.setVisible(False)
    initial_specs = [
        ChannelTrackSpec(
            track_id="inner",
            component="inner",
            label="Inner Diameter (µm)",
            height_ratio=1.0,
        )
    ]
    window.plot_host.ensure_channels(initial_specs)
    if hasattr(window, "_attach_plot_host_window_listener"):
        window._attach_plot_host_window_listener()
    window.plot_host.set_event_highlight_style(
        color=window._event_highlight_color,
        alpha=window._event_highlight_base_alpha,
    )
    inner_track = window.plot_host.track("inner")
    window.ax = inner_track.ax if inner_track and not use_pyqtgraph else None
    window.ax2 = None
    if not use_pyqtgraph:
        window._bind_primary_axis_callbacks()

    window._init_hover_artists()
    window.active_canvas = window.canvas

    window.toolbar = window.build_toolbar_for_canvas(window.canvas)
    window.toolbar.setObjectName("PlotToolbar")
    window.toolbar.setAllowedAreas(Qt.TopToolBarArea)
    window.toolbar.setMovable(False)
    window.canvas.toolbar = window.toolbar
    window.toolbar.setMouseTracking(True)
    if use_pyqtgraph:
        interaction_host = window.plot_host
    else:
        track_lookup = getattr(window.plot_host, "track_for_axes", None)
        if not callable(track_lookup):
            track_lookup = None
        interaction_host = MplInteractionHost(window.canvas, track_lookup=track_lookup)

    window.trace_file_label = QLabel("No trace loaded")
    window.trace_file_label.setObjectName("TraceChip")
    window.trace_file_label.setSizePolicy(
        QSizePolicy.Expanding,
        QSizePolicy.Preferred,
    )
    window.trace_file_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    window.trace_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    window.trace_file_label.setMinimumWidth(260)
    window.trace_file_label.setContentsMargins(12, 0, 0, 0)
    window._status_base_label = "No trace loaded"
    window.trace_file_label.installEventFilter(window)

    window.primary_toolbar = window._create_primary_toolbar()
    window.primary_toolbar.setAllowedAreas(Qt.TopToolBarArea)
    window.addToolBar(Qt.TopToolBarArea, window.primary_toolbar)
    window.addToolBarBreak(Qt.TopToolBarArea)
    window.addToolBar(Qt.TopToolBarArea, window.toolbar)
    window._interaction_controller = InteractionController(
        window.plot_host,
        interaction_host,
        toolbar=window.toolbar,
        on_drag_state=window._set_plot_drag_state,
    )

    window.toolbar.addSeparator()
    window.toolbar.addAction(window.id_toggle_act)
    window.toolbar.addAction(window.od_toggle_act)
    window.toolbar.addAction(window.avg_pressure_toggle_act)
    window.toolbar.addAction(window.set_pressure_toggle_act)
    window.toolbar.addSeparator()

    window._update_toolbar_compact_mode(window.width())

    window.scroll_slider = QScrollBar(Qt.Horizontal)
    window.scroll_slider.setObjectName("TimeScrollbar")
    window.scroll_slider.setMinimum(0)
    window.scroll_slider.setMaximum(1_000_000)
    window.scroll_slider.setSingleStep(1)
    window.scroll_slider.setValue(0)
    window.scroll_slider.sliderMoved.connect(window._on_scrollbar_moved)
    window.scroll_slider.sliderPressed.connect(window._on_scrollbar_pressed)
    window.scroll_slider.sliderReleased.connect(window._on_scrollbar_released)
    window.scroll_slider.valueChanged.connect(window._on_scrollbar_value_changed)
    window.scroll_slider.hide()
    window.scroll_slider.setToolTip("Scroll timeline (X-axis)")
    window.scroll_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # Canonical snapshot viewer widget (replaces legacy QLabel/PG instantiation).
    if window.snapshot_widget is not None:
        window.snapshot_widget.setObjectName("SnapshotPreview")
        window.snapshot_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        window.snapshot_widget.hide()
        window.snapshot_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        window.snapshot_widget.customContextMenuRequested.connect(
            window.show_snapshot_context_menu
        )

    window.snapshot_timeline = SnapshotTimelineWidget()
    window.snapshot_timeline.setObjectName("SnapshotTimeline")
    window.snapshot_timeline.seek_requested.connect(window.change_frame_from_timeline)
    window.snapshot_timeline.hide()
    window.snapshot_timeline.setToolTip("Click or drag to navigate snapshot frames")

    # Legacy compatibility: some code may reference window.slider
    window.slider = window.snapshot_timeline

    window.snapshot_controls = QWidget()
    window.snapshot_controls.setObjectName("SnapshotControls")
    controls_layout = QHBoxLayout(window.snapshot_controls)
    controls_layout.setContentsMargins(0, 0, 0, 0)
    controls_layout.setSpacing(6)

    window.prev_frame_btn = QToolButton(window.snapshot_controls)
    window.prev_frame_btn.setIcon(QIcon(window.icon_path("fast_rewind.svg")))
    window.prev_frame_btn.setToolTip("Previous frame")
    window.prev_frame_btn.clicked.connect(window.step_previous_frame)
    window.prev_frame_btn.setEnabled(False)
    controls_layout.addWidget(window.prev_frame_btn)

    window.play_pause_btn = QToolButton(window.snapshot_controls)
    window.play_pause_btn.setCheckable(True)
    window.play_pause_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    window.play_pause_btn.setIcon(QIcon(window.icon_path("play_arrow.svg")))
    window.play_pause_btn.setText("Play")
    window.play_pause_btn.setToolTip("Play snapshot sequence")
    window.play_pause_btn.clicked.connect(window.toggle_snapshot_playback)
    window.play_pause_btn.setEnabled(False)
    controls_layout.addWidget(window.play_pause_btn)

    window.next_frame_btn = QToolButton(window.snapshot_controls)
    window.next_frame_btn.setIcon(QIcon(window.icon_path("fast_forward.svg")))
    window.next_frame_btn.setToolTip("Next frame")
    window.next_frame_btn.clicked.connect(window.step_next_frame)
    window.next_frame_btn.setEnabled(False)
    controls_layout.addWidget(window.next_frame_btn)

    window.snapshot_speed_label = QLabel("Playback speed")
    window.snapshot_speed_label.setObjectName("SnapshotSpeedLabel")
    window.snapshot_speed_label.setEnabled(False)
    controls_layout.addWidget(window.snapshot_speed_label)

    window.snapshot_speed_input = QDoubleSpinBox(window.snapshot_controls)
    window.snapshot_speed_input.setObjectName("SnapshotSpeedInput")
    window.snapshot_speed_input.setDecimals(1)
    window.snapshot_speed_input.setSingleStep(1.0)
    window.snapshot_speed_input.setRange(1.0, 120.0)
    default_pps = 30.0
    try:
        default_pps = float(getattr(window, "snapshot_pps", default_pps))
    except (TypeError, ValueError):
        default_pps = 30.0
    window.snapshot_speed_input.setValue(max(1.0, min(float(default_pps), 120.0)))
    window.snapshot_speed_input.setEnabled(False)
    window.snapshot_speed_label.setToolTip("Adjust snapshot playback speed (pages / second)")
    window.snapshot_speed_input.setToolTip("Adjust snapshot playback speed (pages / second)")
    window.snapshot_speed_input.valueChanged.connect(window.on_snapshot_speed_changed)
    controls_layout.addWidget(window.snapshot_speed_input)

    window.snapshot_speed_units_label = QLabel("pages / second")
    window.snapshot_speed_units_label.setObjectName("SnapshotSpeedUnitsLabel")
    window.snapshot_speed_units_label.setEnabled(False)
    window.snapshot_speed_units_label.setToolTip("Playback speed units")
    controls_layout.addWidget(window.snapshot_speed_units_label)

    window.snapshot_sync_checkbox = QCheckBox("Sync to trace")
    window.snapshot_sync_checkbox.setObjectName("SnapshotSyncCheckbox")
    window.snapshot_sync_checkbox.setChecked(True)
    window.snapshot_sync_checkbox.setEnabled(False)
    window.snapshot_sync_checkbox.setToolTip("Sync snapshot playback to trace cursor")
    window.snapshot_sync_checkbox.toggled.connect(window.on_snapshot_sync_toggled)
    controls_layout.addWidget(window.snapshot_sync_checkbox)

    window.snapshot_loop_checkbox = QCheckBox("Loop playback")
    window.snapshot_loop_checkbox.setObjectName("SnapshotLoopCheckbox")
    window.snapshot_loop_checkbox.setChecked(False)
    window.snapshot_loop_checkbox.setEnabled(False)
    window.snapshot_loop_checkbox.setToolTip("Restart playback from beginning when reaching last frame")
    window.snapshot_loop_checkbox.toggled.connect(window.on_snapshot_loop_toggled)
    controls_layout.addWidget(window.snapshot_loop_checkbox)

    controls_layout.addStretch()

    window.snapshot_sync_label = QLabel("Synced: —")
    window.snapshot_sync_label.setObjectName("SnapshotSyncLabel")
    window.snapshot_sync_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    window.snapshot_sync_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
    controls_layout.addWidget(window.snapshot_sync_label)

    window.snapshot_subsample_label = QLabel("")
    window.snapshot_subsample_label.setObjectName("SnapshotSubsampleLabel")
    window.snapshot_subsample_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    window.snapshot_subsample_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
    window.snapshot_subsample_label.setVisible(False)
    window.snapshot_subsample_label.setToolTip("Loaded a reduced subset of the TIFF stack")
    controls_layout.addWidget(window.snapshot_subsample_label)

    window.snapshot_time_label = QLabel("Frame 0 / 0")
    window.snapshot_time_label.setObjectName("SnapshotStatusLabel")
    window.snapshot_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    controls_layout.addWidget(window.snapshot_time_label)
    window.snapshot_controls.hide()

    if window.snapshot_controller is not None:
        window.snapshot_controller.sync_mode_changed.connect(
            window._update_snapshot_sync_label
        )
        window.snapshot_controller.page_changed.connect(
            window._on_snapshot_page_changed
        )
        window.snapshot_controller.playback_time_changed.connect(
            window._on_snapshot_playback_time_changed
        )
        window.snapshot_controller.playing_changed.connect(
            window._on_snapshot_playing_changed
        )
        window.snapshot_controller.set_playback_pps(
            float(getattr(window, "snapshot_pps", 30.0))
        )
        window.snapshot_controller.set_sync_enabled(
            bool(getattr(window, "snapshot_sync_enabled", True))
        )
        window._update_snapshot_sync_label("none")

    window.metadata_panel = QFrame()
    window.metadata_panel.setObjectName("MetadataPanel")
    metadata_layout = QVBoxLayout(window.metadata_panel)
    metadata_layout.setContentsMargins(10, 8, 10, 8)
    metadata_layout.setSpacing(6)

    window.metadata_scroll = QScrollArea()
    window.metadata_scroll.setWidgetResizable(True)
    window.metadata_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    window.metadata_scroll.setObjectName("MetadataScroll")
    metadata_layout.addWidget(window.metadata_scroll)

    metadata_inner = QWidget()
    inner_layout = QVBoxLayout(metadata_inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(6)
    window.metadata_details_label = QLabel("No metadata available.")
    window.metadata_details_label.setObjectName("MetadataDetails")
    window.metadata_details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    window.metadata_details_label.setWordWrap(True)
    window.metadata_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    window.metadata_details_label.setTextFormat(Qt.RichText)
    inner_layout.addWidget(window.metadata_details_label)
    inner_layout.addStretch()
    window.metadata_scroll.setWidget(metadata_inner)

    window.metadata_panel.hide()

    window.event_table = EventTableWidget(window)
    window.event_table.setMinimumWidth(0)
    window.event_table.setContextMenuPolicy(Qt.CustomContextMenu)
    window.event_table.customContextMenuRequested.connect(window.show_event_table_context_menu)
    window.event_table.installEventFilter(window)
    window.event_table.cellClicked.connect(window.table_row_clicked)
    window.event_table_controller = EventTableController(window.event_table, window)
    window.event_table_controller.cell_edited.connect(window.handle_table_edit)
    window.event_table_controller.label_edited.connect(window.handle_event_label_edit)
    window.event_table_controller.rows_changed.connect(window._on_event_rows_changed)
    selection_model = window.event_table.selectionModel()
    if selection_model is not None:
        selection_model.selectionChanged.connect(window._on_event_table_selection_changed)

    window.header_frame = window._build_data_header()
    window.main_layout.addWidget(window.header_frame)

    window.data_splitter = window.rebuild_default_main_layout()
    window.main_layout.addWidget(window.data_splitter, 1)
    window.toggle_snapshot_viewer(False)

    window._update_status_chip()

    def _apply_data_page_style() -> None:
        border_color = CURRENT_THEME["grid_color"]
        text_color = CURRENT_THEME["text"]
        hover_bg = CURRENT_THEME["button_hover_bg"]
        content_bg = CURRENT_THEME.get("table_bg", CURRENT_THEME["window_bg"])
        panel_bg = CURRENT_THEME.get("panel_bg", content_bg)
        panel_border = CURRENT_THEME.get("panel_border", border_color)
        panel_radius = int(CURRENT_THEME.get("panel_radius", 6))
        snapshot_bg = CURRENT_THEME.get("snapshot_bg", panel_bg)

        def rgba_from_hex(color: str, alpha: float) -> str:
            """Return rgba string from a hex color with alpha applied."""
            color = (color or "").strip()
            if color.startswith("rgba"):
                return color
            color = color.lstrip("#")
            if len(color) == 3:
                color = "".join(ch * 2 for ch in color)
            try:
                r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
            except Exception:
                return color or "transparent"
            alpha = max(0.0, min(1.0, float(alpha)))
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"

        subtitle_color = rgba_from_hex(text_color, 0.70)
        section_color = rgba_from_hex(text_color, 0.82)
        status_color = rgba_from_hex(text_color, 0.60)
        preview_color = rgba_from_hex(text_color, 0.58)
        preview_border = rgba_from_hex(panel_border, 0.45)
        preview_radius = max(2, panel_radius - 2)

        window.data_page.setStyleSheet(
            window._shared_button_css()
            + f"""
QWidget#DataPage {{
    background: {content_bg};
}}
QFrame#DataHeader {{
    background: transparent;
    border: none;
    padding: 0px;
}}
QLabel#HeaderTitle {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel#HeaderSubtitle {{
    color: {subtitle_color};
}}
QLabel#TraceChip {{
    background: {hover_bg};
    color: {text_color};
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: 500;
}}
QFrame#PlotPanel, QFrame#SidePanel {{
    background: transparent;
    border: none;
}}
QFrame#PlotContainer {{
    background: {panel_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
}}
QFrame#SnapshotCard, QFrame#TableCard {{
    background: {panel_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
}}
QWidget#SnapshotControls {{
    background: transparent;
}}
QLabel#SnapshotSpeedLabel,
QLabel#SnapshotSyncLabel {{
    color: {status_color};
    font-size: 10px;
}}
QLabel#SnapshotStatusLabel {{
    color: {status_color};
    font-size: 11px;
}}
QLabel#SnapshotSubsampleLabel {{
    background: {hover_bg};
    color: {text_color};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    font-weight: 600;
    color: {section_color};
    padding-bottom: 4px;
}}
QWidget#SnapshotPreview {{
    background: {snapshot_bg};
    border: 1px solid {preview_border};
    border-radius: {preview_radius}px;
    color: {preview_color};
}}
QWidget#SnapshotPreview QLabel {{
    color: {preview_color};
}}
QSplitter#DataSplitter::handle {{
    background: {panel_border};
    width: 4px;
    border-radius: 2px;
}}
QFrame#MetadataPanel {{
    background: {panel_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
}}
QScrollArea#MetadataScroll {{
    border: none;
    background: transparent;
}}
QScrollArea#MetadataScroll QWidget {{
    background: transparent;
}}
QLabel#MetadataDetails {{
    color: {text_color};
}}
"""
        )

    window._apply_data_page_style = _apply_data_page_style
    window._apply_data_page_style()

    window.stack.setCurrentWidget(window.data_page)
    window._set_toolbars_visible(True)

    backend = window.plot_host.get_render_backend() if hasattr(window.plot_host, "get_render_backend") else ""
    if backend == "matplotlib":
        window.canvas.mpl_connect("draw_event", window.update_event_label_positions)
        window.canvas.mpl_connect("draw_event", window.sync_slider_with_plot)
        window.canvas.mpl_connect("motion_notify_event", window.update_hover_label)
        window.canvas.mpl_connect("figure_leave_event", window._handle_figure_leave)
        window.canvas.mpl_connect("button_press_event", window.handle_click_on_plot)
        window.canvas.mpl_connect(
            "button_release_event",
            lambda event: QTimer.singleShot(
                100,
                lambda: window.on_mouse_release(event),
            ),
        )
        window.canvas.mpl_connect("draw_event", window.sync_slider_with_plot)

    window._refresh_home_recent()
    QTimer.singleShot(0, lambda: window._update_toolbar_compact_mode(window.width()))
