from __future__ import annotations

from typing import TYPE_CHECKING

import contextlib
import logging
from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, QSize
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
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

    # Canonical snapshot viewer widget (TIFF viewer v2).
    if window.snapshot_widget is not None:
        viewer = window.snapshot_widget
        viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewer.hide()
        viewer.setContextMenuPolicy(Qt.CustomContextMenu)
        viewer.customContextMenuRequested.connect(
            window.show_snapshot_context_menu
        )

        controls = getattr(viewer, "controls", None)
        if controls is not None:
            # Aliases for legacy attribute access in main_window.
            window.snapshot_controls = controls
            window.prev_frame_btn = controls.prev_button
            window.play_pause_btn = controls.play_button
            window.next_frame_btn = controls.next_button
            window.slider = controls.slider
            window.snapshot_time_label = controls.frame_label
            window.snapshot_speed_label = controls.speed_label
            window.snapshot_speed_input = controls.speed_input
            window.snapshot_speed_units_label = controls.speed_units_label
            window.snapshot_sync_checkbox = controls.sync_checkbox
            window.snapshot_loop_checkbox = controls.loop_checkbox
            window.snapshot_sync_label = controls.sync_label

        controller = getattr(viewer, "controller", None)
        if controller is not None:
            controller.page_changed.connect(window._on_snapshot_page_changed_v2)
            controller.playing_changed.connect(window._on_snapshot_playing_changed)
            controller.mapped_time_changed.connect(
                window._on_snapshot_playback_time_changed
            )
        with contextlib.suppress(Exception):
            viewer.set_pps(float(getattr(window, "snapshot_pps", 30.0)))
        with contextlib.suppress(Exception):
            viewer.set_sync_enabled(bool(getattr(window, "snapshot_sync_enabled", True)))
        with contextlib.suppress(Exception):
            viewer.set_loop(bool(getattr(window, "snapshot_loop_enabled", True)))
        if controls is not None:
            controls.pps_changed.connect(window.on_snapshot_speed_changed)
            controls.sync_toggled.connect(window.on_snapshot_sync_toggled)
            controls.loop_toggled.connect(window.on_snapshot_loop_toggled)

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
        button_bg = CURRENT_THEME.get("button_bg", panel_bg)
        button_hover = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active = CURRENT_THEME.get(
            "button_active_bg", CURRENT_THEME.get("selection_bg", button_hover)
        )

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
    background: {panel_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
}}
QWidget#SnapshotControls QToolButton {{
    background: {button_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
    min-width: 30px;
    min-height: 30px;
    padding: 0px;
}}
QWidget#SnapshotControls QToolButton:hover {{
    background: {button_hover};
}}
QWidget#SnapshotControls QToolButton:pressed,
QWidget#SnapshotControls QToolButton:checked {{
    background: {button_active};
}}
QWidget#SnapshotControls QToolButton:disabled {{
    background: {panel_bg};
    border-color: {panel_border};
    color: {status_color};
}}
QWidget#SnapshotControls QDoubleSpinBox#SnapshotSpeedInput {{
    background: {button_bg};
    border: 1px solid {panel_border};
    border-radius: {panel_radius}px;
    padding: 2px 6px;
    min-height: 26px;
    font-size: 11px;
}}
QLabel#SnapshotSpeedLabel,
QLabel#SnapshotSpeedUnitsLabel,
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
