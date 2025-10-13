from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from vasoanalyzer.ui.event_table import EventTableWidget
from vasoanalyzer.ui.event_table_controller import EventTableController
from vasoanalyzer.ui.interactions import InteractionController
from vasoanalyzer.ui.panels.home_page import HomePage
from vasoanalyzer.ui.plots.plot_host import PlotHost
from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def init_ui(window: "VasoAnalyzerApp") -> None:
    """Initialise stacked layout, plot host, and ancillary widgets."""

    window.stack = QStackedWidget()
    window.setCentralWidget(window.stack)

    window.home_page = HomePage(window)
    window.stack.addWidget(window.home_page)

    window.data_page = QWidget()
    window.data_page.setObjectName("DataPage")
    window.stack.addWidget(window.data_page)

    window.main_layout = QVBoxLayout(window.data_page)
    window.main_layout.setContentsMargins(16, 8, 16, 16)
    window.main_layout.setSpacing(12)

    dpi = int(QApplication.primaryScreen().logicalDotsPerInch())
    window.plot_host = PlotHost(dpi=dpi)
    window.fig = window.plot_host.figure
    window.canvas = window.plot_host.canvas
    window.canvas.setMouseTracking(True)
    window.canvas.toolbar = None
    initial_specs = [
        ChannelTrackSpec(
            track_id="inner",
            component="inner",
            label="Inner Diameter (µm)",
            height_ratio=1.0,
        )
    ]
    window.plot_host.ensure_channels(initial_specs)
    window.plot_host.set_event_highlight_style(
        color=window._event_highlight_color,
        alpha=window._event_highlight_base_alpha,
    )
    inner_track = window.plot_host.track("inner")
    window.ax = inner_track.ax if inner_track else None
    window.ax2 = None
    window._bind_primary_axis_callbacks()

    window._init_hover_artists()
    window.active_canvas = window.canvas

    window.toolbar = window.build_toolbar_for_canvas(window.canvas)
    window.toolbar.setObjectName("PlotToolbar")
    window.toolbar.setAllowedAreas(Qt.TopToolBarArea)
    window.toolbar.setMovable(False)
    window.canvas.toolbar = window.toolbar
    window.toolbar.setMouseTracking(True)

    window.trace_file_label = QLabel("No trace loaded")
    window.trace_file_label.setObjectName("TraceChip")
    window.trace_file_label.setSizePolicy(
        QSizePolicy.Preferred,
        QSizePolicy.Preferred,
    )
    window.trace_file_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    window.trace_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    window.trace_file_label.setMinimumWidth(260)
    window._status_base_label = "No trace loaded"
    window.trace_file_label.installEventFilter(window)

    window.primary_toolbar = window._create_primary_toolbar()
    window.primary_toolbar.setAllowedAreas(Qt.TopToolBarArea)
    window.addToolBar(Qt.TopToolBarArea, window.primary_toolbar)
    window.addToolBarBreak(Qt.TopToolBarArea)
    window.addToolBar(Qt.TopToolBarArea, window.toolbar)
    window._interaction_controller = InteractionController(
        window.plot_host,
        toolbar=window.toolbar,
        on_drag_state=window._set_plot_drag_state,
    )

    window.toolbar.addAction(window.id_toggle_act)
    window.toolbar.addAction(window.od_toggle_act)
    window.toolbar.addSeparator()

    window._update_toolbar_compact_mode(window.width())

    window.scroll_slider = QSlider(Qt.Horizontal)
    window.scroll_slider.setMinimum(0)
    window.scroll_slider.setMaximum(1000)
    window.scroll_slider.setSingleStep(1)
    window.scroll_slider.setValue(0)
    window.scroll_slider.valueChanged.connect(window.scroll_plot)
    window.scroll_slider.hide()
    window.scroll_slider.setToolTip("Scroll timeline (X-axis)")

    window.snapshot_label = QLabel("Snapshot preview")
    window.snapshot_label.setObjectName("SnapshotPreview")
    window.snapshot_label.setAlignment(Qt.AlignCenter)
    window.snapshot_label.setMinimumHeight(220)
    window.snapshot_label.hide()
    window.snapshot_label.setContextMenuPolicy(Qt.CustomContextMenu)
    window.snapshot_label.customContextMenuRequested.connect(
        window.show_snapshot_context_menu
    )

    window.slider = QSlider(Qt.Horizontal)
    window.slider.setMinimum(0)
    window.slider.setValue(0)
    window.slider.valueChanged.connect(window.change_frame)
    window.slider.hide()
    window.slider.setToolTip("Navigate TIFF frames")

    window.snapshot_controls = QWidget()
    window.snapshot_controls.setObjectName("SnapshotControls")
    controls_layout = QHBoxLayout(window.snapshot_controls)
    controls_layout.setContentsMargins(0, 0, 0, 0)
    controls_layout.setSpacing(8)

    window.prev_frame_btn = QToolButton(window.snapshot_controls)
    window.prev_frame_btn.setIcon(window.style().standardIcon(QStyle.SP_MediaSkipBackward))
    window.prev_frame_btn.setToolTip("Previous frame")
    window.prev_frame_btn.clicked.connect(window.step_previous_frame)
    window.prev_frame_btn.setEnabled(False)
    controls_layout.addWidget(window.prev_frame_btn)

    window.play_pause_btn = QToolButton(window.snapshot_controls)
    window.play_pause_btn.setCheckable(True)
    window.play_pause_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    window.play_pause_btn.setIcon(window.style().standardIcon(QStyle.SP_MediaPlay))
    window.play_pause_btn.setText("Play")
    window.play_pause_btn.setToolTip("Play snapshot sequence")
    window.play_pause_btn.clicked.connect(window.toggle_snapshot_playback)
    window.play_pause_btn.setEnabled(False)
    controls_layout.addWidget(window.play_pause_btn)

    window.next_frame_btn = QToolButton(window.snapshot_controls)
    window.next_frame_btn.setIcon(window.style().standardIcon(QStyle.SP_MediaSkipForward))
    window.next_frame_btn.setToolTip("Next frame")
    window.next_frame_btn.clicked.connect(window.step_next_frame)
    window.next_frame_btn.setEnabled(False)
    controls_layout.addWidget(window.next_frame_btn)

    window.snapshot_speed_label = QLabel("Speed:")
    window.snapshot_speed_label.setObjectName("SnapshotSpeedLabel")
    window.snapshot_speed_label.setEnabled(False)
    controls_layout.addWidget(window.snapshot_speed_label)

    window.snapshot_speed_combo = QComboBox(window.snapshot_controls)
    window.snapshot_speed_combo.setObjectName("SnapshotSpeedCombo")
    window.snapshot_speed_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    window.snapshot_speed_presets = [
        ("0.25x", 0.25),
        ("0.5x", 0.5),
        ("1x", 1.0),
        ("1.5x", 1.5),
        ("2x", 2.0),
        ("3x", 3.0),
        ("4x", 4.0),
    ]
    for label, value in window.snapshot_speed_presets:
        window.snapshot_speed_combo.addItem(label, value)
    window.snapshot_speed_default_index = next(
        (idx for idx, (_, val) in enumerate(window.snapshot_speed_presets) if val == 1.0),
        0,
    )
    window.snapshot_speed_combo.setCurrentIndex(window.snapshot_speed_default_index)
    window.snapshot_speed_combo.setEnabled(False)
    window.snapshot_speed_label.setToolTip("Adjust snapshot playback speed")
    window.snapshot_speed_combo.setToolTip("Adjust snapshot playback speed")
    window.snapshot_speed_combo.currentIndexChanged.connect(
        window.on_snapshot_speed_changed
    )
    controls_layout.addWidget(window.snapshot_speed_combo)

    controls_layout.addStretch()

    window.snapshot_time_label = QLabel("Frame 0 / 0")
    window.snapshot_time_label.setObjectName("SnapshotStatusLabel")
    window.snapshot_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    controls_layout.addWidget(window.snapshot_time_label)
    window.snapshot_controls.hide()

    window.snapshot_timer = QTimer(window)
    window.snapshot_timer.timeout.connect(window.advance_snapshot_frame)

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
    window.event_table.setMinimumWidth(560)
    window.event_table.setContextMenuPolicy(Qt.CustomContextMenu)
    window.event_table.customContextMenuRequested.connect(window.show_event_table_context_menu)
    window.event_table.installEventFilter(window)
    window.event_table.cellClicked.connect(window.table_row_clicked)
    window.event_table_controller = EventTableController(window.event_table, window)
    window.event_table_controller.cell_edited.connect(window.handle_table_edit)
    window.event_table_controller.rows_changed.connect(window._on_event_rows_changed)

    window.header_frame = window._build_data_header()
    window.main_layout.addWidget(window.header_frame)

    window.data_splitter = window.rebuild_default_main_layout()
    window.main_layout.addWidget(window.data_splitter, 1)
    window.toggle_snapshot_viewer(False)

    window._update_status_chip()

    border_color = CURRENT_THEME["grid_color"]
    text_color = CURRENT_THEME["text"]
    hover_bg = CURRENT_THEME["button_hover_bg"]
    window_bg = CURRENT_THEME["window_bg"]

    window.data_page.setStyleSheet(
        window._shared_button_css()
        + f"""
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
    color: #5b6375;
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
    background: {window_bg};
    border: 1px solid {border_color};
    border-radius: 16px;
}}
QFrame#SnapshotCard, QFrame#TableCard {{
    background: {window_bg};
    border: 1px solid {border_color};
    border-radius: 16px;
}}
QWidget#SnapshotControls {{
    background: transparent;
}}
QLabel#SnapshotStatusLabel {{
    color: #4d5466;
    font-size: 12px;
}}
QLabel#SectionTitle {{
    font-weight: 600;
    color: #3a4255;
    padding-bottom: 4px;
}}
QLabel#SnapshotPreview {{
    background: {window_bg};
    border: 1px dashed {border_color};
    border-radius: 12px;
    color: #7a8194;
}}
QSplitter#DataSplitter::handle {{
    background: {border_color};
    width: 6px;
    border-radius: 3px;
}}
QFrame#MetadataPanel {{
    background: {window_bg};
    border: 1px solid {border_color};
    border-radius: 12px;
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

    window.stack.setCurrentWidget(window.home_page)
    window._set_toolbars_visible(False)

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
