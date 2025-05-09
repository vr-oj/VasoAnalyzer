# [A] ========================= IMPORTS AND GLOBAL CONFIG ============================
import sys, os, pickle
import numpy as np
import pandas as pd
import tifffile
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib import rcParams
from functools import partial

rcParams.update(
    {
        "axes.labelcolor": "black",
        "xtick.color": "black",
        "ytick.color": "black",
        "text.color": "black",
        "figure.facecolor": "white",
        "figure.edgecolor": "white",
        "savefig.facecolor": "white",
        "savefig.edgecolor": "white",
    }
)

from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QPushButton,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QMessageBox,
    QInputDialog,
    QMenu,
    QSizePolicy,
    QAction,
    QToolBar,
    QToolButton,
    QSpacerItem,
)

from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtCore import Qt, QTimer, QSize, QSettings
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QStatusBar

import requests
def check_for_new_version(current_version="v2.5.1"):
    try:
        response = requests.get("https://api.github.com/repos/vr-oj/VasoAnalyzer_2.0/releases/latest")
        if response.status_code == 200:
            latest_version = response.json().get("tag_name", "")
            if latest_version and latest_version != current_version:
                return latest_version
    except Exception as e:
        print(f"Update check failed: {e}")
    return None

from vasoanalyzer.trace_loader import load_trace
from vasoanalyzer.tiff_loader import load_tiff
from vasoanalyzer.event_loader import load_events
from vasoanalyzer.excel_mapper import ExcelMappingDialog, update_excel_file
from vasoanalyzer.version_checker import check_for_new_version

# [B] ========================= MAIN CLASS DEFINITION ================================
PREVIOUS_PLOT_PATH = os.path.join(
    os.path.expanduser("~"), ".vasoanalyzer_last_plot.pickle"
)
class VasoAnalyzerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(self.icon_path("VasoAnalyzerIcon.icns")))

        self.setStyleSheet(
            """
            QPushButton {
                color: black;
            }
        """
        )

        # ===== Setup App Window =====
        self.setWindowTitle("VasoAnalyzer 2.5 - Python Edition")
        self.setGeometry(100, 100, 1280, 720)

        # ===== Initialize State =====
        self.trace_data = None
        self.trace_file_path = None
        self.snapshot_frames = []
        self.current_frame = 0
        self.event_labels = []
        self.event_times = []
        self.event_text_objects = []
        self.event_table_data = []
        self.selected_event_marker = None
        self.pinned_points = []
        self.slider_marker = None
        self.recording_interval = 0.14  # 140 ms per frame
        self.last_replaced_event = None
        self.excel_auto_path = None  # Path to Excel file for auto-update
        self.excel_auto_column = None  # Column letter to use for auto-update
        self.grid_visible = True  # Track grid visibility
        self.recent_files = []
        self.settings = QSettings("TykockiLab", "VasoAnalyzer")
        self.load_recent_files()
        self.setAcceptDrops(True)
        self.setStatusBar(QStatusBar(self))
        self.setAcceptDrops(True)

        # ===== Axis + Slider State =====
        self.axis_dragging = False
        self.axis_drag_start = None
        self.drag_direction = None
        self.scroll_slider = None
        self.window_width = None

        # ===== Build UI =====
        self.create_menubar()
        self.initUI()
        self.check_for_updates_at_startup()

    def update_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
            return

        for path in self.recent_files:
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.load_trace_and_events, path))
            self.recent_menu.addAction(action)

    def icon_path(self, filename):
        return os.path.join(os.path.dirname(__file__), "..", "icons", filename)

    def create_menubar(self):
        menubar = self.menuBar()

        # ===== FILE MENU =====
        file_menu = menubar.addMenu("File")
        new_action = QAction("Start New Analysis", self)
        new_action.triggered.connect(self.start_new_analysis)
        file_menu.addAction(new_action)

        open_trace_action = QAction("Open Trace + Events", self)
        open_trace_action.setShortcut("Ctrl+O")
        open_trace_action.triggered.connect(lambda: self.load_trace_and_events())
        file_menu.addAction(open_trace_action)

        open_tiff_action = QAction("Open _Result.tiff", self)
        open_tiff_action.setShortcut("Ctrl+T")
        open_tiff_action.triggered.connect(self.load_snapshot)
        file_menu.addAction(open_tiff_action)

        reopen_action = QAction("Reopen Previous Plot", self)
        reopen_action.triggered.connect(self.reopen_previous_plot)
        file_menu.addAction(reopen_action)

        file_menu.addSeparator()

        export_tiff_action = QAction("Export Plot as TIFF", self)
        export_tiff_action.triggered.connect(self.export_high_res_plot)
        file_menu.addAction(export_tiff_action)

        export_csv_action = QAction("Export Events as CSV", self)
        export_csv_action.triggered.connect(self.auto_export_table)
        file_menu.addAction(export_csv_action)

        export_excel_action = QAction("Export to Excel Template", self)
        export_excel_action.triggered.connect(self.open_excel_mapping_dialog)
        file_menu.addAction(export_excel_action)

        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("Recent Files")
        self.build_recent_files_menu()
        self.update_recent_files_menu()

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ===== EDIT MENU =====
        edit_menu = menubar.addMenu("Edit")

        undo_action = QAction("Undo Last Replacement", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo_last_replacement)
        edit_menu.addAction(undo_action)

        edit_menu.addSeparator()

        # Main plot style editor
        style_editor_action = QAction("Customize Plot Style", self)
        style_editor_action.triggered.connect(self.open_plot_style_editor)
        edit_menu.addAction(style_editor_action)

        # Submenu: Customize individual tabs
        customize_menu = edit_menu.addMenu("Customize")

        def open_style_tab(tab_name):
            from .gui import PlotStyleDialog  # Safe local import

            dialog = PlotStyleDialog(self)
            tab_widget = dialog.tabs
            for i in range(tab_widget.count()):
                if tab_widget.widget(i).objectName() == tab_name:
                    tab_widget.setCurrentIndex(i)
                    break
            dialog.exec_()

        tab_names = {
            "Axis Titles": "axis_tab",
            "Tick Labels": "tick_tab",
            "Event Labels": "event_tab",
            "Pinned Labels": "pin_tab",
            "Trace Style": "line_tab",
        }

        for label, tab_obj_name in tab_names.items():
            action = QAction(label, self)
            action.triggered.connect(lambda _, name=tab_obj_name: open_style_tab(name))
            customize_menu.addAction(action)

        # ===== VIEW MENU =====
        view_menu = menubar.addMenu("View")
        toggle_grid_action = QAction("Toggle Grid", self, checkable=True)
        toggle_grid_action.setChecked(self.grid_visible)
        toggle_grid_action.triggered.connect(self.toggle_grid)
        view_menu.addAction(toggle_grid_action)

        # ===== HELP MENU =====
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About VasoAnalyzer", self)
        about_action.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "About VasoAnalyzer",
                "VasoAnalyzer 2.5 (Python Edition)\nDeveloped for the Tykocki Lab\nhttps://github.com/vr-oj/VasoAnalyzer_2.0",
            )
        )
        help_menu.addAction(about_action)

        user_guide_action = QAction("Open User Manual", self)
        user_guide_action.triggered.connect(
            lambda: os.system("open ./docs/VasoAnalyzer_User_Manual.pdf")
        )  # Adjust path for Windows
        help_menu.addAction(user_guide_action)

    def build_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
            return

        for path in self.recent_files:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.load_trace_and_events, path))
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def save_plot_pickle(self):
        try:
            state = {
            "trace_data": self.trace_data,
            "event_labels": self.event_labels,
            "event_times": self.event_times,
            "event_table_data": self.event_table_data,
            "pinned_points": [
                (p.get_xdata()[0], p.get_ydata()[0]) for p, _ in self.pinned_points
            ],
            "grid_visible": self.grid_visible,
            "xlim": self.ax.get_xlim(),
            "ylim": self.ax.get_ylim(),
            "xlabel": self.ax.get_xlabel(),
            "ylabel": self.ax.get_ylabel(),
            "plot_style": getattr(self, "plot_style_dialog", None).get_style()
                if hasattr(self, "plot_style_dialog")
                else {
                    "axis_font_size": 14,
                    "axis_font_family": "Arial",
                    "axis_bold": False,
                    "axis_italic": False,
                    "tick_font_size": 12,
                    "event_font_size": 10,
                    "event_font_family": "Arial",
                    "event_bold": False,
                    "event_italic": False,
                    "pin_font_size": 10,
                    "pin_font_family": "Arial",
                    "pin_bold": False,
                    "pin_italic": False,
                    "pin_size": 6,
                    "line_width": 2,
                },
        }

            pickle_path = os.path.join(
                os.path.abspath(self.trace_file_path or "."), "tracePlot_output.fig.pickle"
            )
            with open(pickle_path, "wb") as f:
                pickle.dump(state, f)

            print(f"✔ Session state saved to:\n{pickle_path}")
        except Exception as e:
            print(f"❌ Failed to save session state:\n{e}")

            with open(PREVIOUS_PLOT_PATH, "wb") as f:
                pickle.dump(state, f)

    # Update reopen_previous_plot to reload all elements
    def reopen_previous_plot(self):
        if not os.path.exists(PREVIOUS_PLOT_PATH):
            QMessageBox.warning(
                self, "No Previous Plot", "No previously saved plot was found."
            )
            return

        self.load_pickle_session(PREVIOUS_PLOT_PATH)

    def rebuild_top_row_with_new_toolbar(self):
        top_row_layout = QHBoxLayout()
        top_row_layout.setContentsMargins(6, 4, 6, 2)
        top_row_layout.setSpacing(8)

        top_row_layout.addWidget(self.toolbar)
        top_row_layout.addWidget(self.loadTraceBtn)
        top_row_layout.addWidget(self.load_snapshot_button)
        top_row_layout.addWidget(self.excel_btn)
        top_row_layout.addWidget(self.trace_file_label)

        # Remove and replace the first layout in the central widget
        main_layout = self.centralWidget().layout()
        item = main_layout.takeAt(0)
        if item:
            item.deleteLater()
        main_layout.insertLayout(0, top_row_layout)

    def load_recent_files(self):
        settings = QSettings("TykockiLab", "VasoAnalyzer")
        recent = settings.value("recentFiles", [])
        if recent is None:
            recent = []
        self.recent_files = recent

    def check_for_updates_at_startup(self):
    latest = check_for_new_version("v2.5.1")
    if latest:
        QMessageBox.information(
            self,
            "Update Available",
            f"A new version ({latest}) of VasoAnalyzer is available!\nVisit GitHub to download the latest release.",
        )

# [C] ========================= UI SETUP (initUI) ======================================
    def initUI(self):
        self.setStyleSheet(
            """
            QWidget {
                background-color: #F5F5F5;
                font-family: 'Arial';
                font-size: 13px;
                color: black;  /* Ensure all default widget text is black */
            }
            QPushButton {
                background-color: #FFFFFF;
                color: black;  /* <-- Add this */
                border: 1px solid #CCCCCC;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #E6F0FF;
            }
            QToolButton {
                background-color: #FFFFFF;
                color: black;  /* <-- Add this */
                border: 1px solid #CCCCCC;
                border-radius: 6px;
                padding: 6px;
                margin: 2px;
            }
            QToolButton:hover {
                background-color: #D6E9FF;
            }
            QToolButton:checked {
                background-color: #CCE5FF;
                border: 1px solid #3399FF;
            }
            QHeaderView::section {
                background-color: #E0E0E0;
                color: black;
                font-weight: bold;
                padding: 6px;
                border-bottom: 1px solid #AAAAAA;
            }
            QTableWidget {
                gridline-color: #DDDDDD;
                color: black;
                background-color: white;
            }
            QTableWidget::item {
                padding: 6px;
                color: black;  /* <-- Ensure table item text is black */
            }
        """
        )

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.fig = Figure(figsize=(8, 4), facecolor="white")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.toolbar = None
        self.ax = self.fig.add_subplot(111)

        # ===== Initialize Matplotlib Toolbar =====
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.canvas.toolbar = self.toolbar
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setStyleSheet(
            """
            QToolBar {
                background-color: #F0F0F0;
                padding: 2px;
                border: none;
            }
        """
        )
        self.toolbar.setContentsMargins(0, 0, 0, 0)

        # Remove stray/empty buttons
        if hasattr(self.toolbar, "coordinates"):
            self.toolbar.coordinates = lambda *args, **kwargs: None
            for act in self.toolbar.actions():
                if isinstance(act, QAction) and act.text() == "":
                    self.toolbar.removeAction(act)

        visible_buttons = [a for a in self.toolbar.actions() if not a.icon().isNull()]
        if len(visible_buttons) >= 8:
            visible_buttons[0].setToolTip("Home: Reset zoom and pan")
            visible_buttons[1].setToolTip("Back: Previous view")
            visible_buttons[2].setToolTip("Forward: Next view")
            visible_buttons[3].setToolTip("Pan: Click and drag plot")
            visible_buttons[4].setToolTip("Zoom: Draw box to zoom in")

            # [5] Subplot layout (borders + spacings)
            layout_btn = visible_buttons[5]
            layout_btn.setToolTip("Configure subplot layout")
            layout_btn.triggered.disconnect()
            layout_btn.triggered.connect(self.toolbar.configure_subplots)

            # [6] Axes and title editor
            axes_btn = visible_buttons[6]
            axes_btn.setToolTip("Edit axis ranges and titles")
            axes_btn.triggered.disconnect()
            axes_btn.triggered.connect(self.toolbar.edit_parameters)

            # [Inject] Aa: Plot style editor
            style_btn = QToolButton()
            style_btn.setText("Aa")
            style_btn.setToolTip("Customize plot fonts and layout")
            style_btn.setStyleSheet(
                """
                QToolButton {
                    background-color: #FFFFFF;
                    border: 1px solid #CCCCCC;
                    border-radius: 6px;
                    padding: 6px;
                    margin: 2px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QToolButton:hover {
                    background-color: #E0F0FF;
                }
            """
            )
            style_btn.clicked.connect(self.open_plot_style_editor)
            self.toolbar.insertWidget(visible_buttons[7], style_btn)

            # [Inject] Grid toggle button
            grid_btn = QToolButton()
            grid_btn.setText("Grid")
            grid_btn.setToolTip("Toggle grid visibility")
            grid_btn.setCheckable(True)
            grid_btn.setChecked(self.grid_visible)
            grid_btn.clicked.connect(self.toggle_grid)
            self.toolbar.insertWidget(visible_buttons[7], grid_btn)

            # [7] Save/export button
            save_btn = visible_buttons[7]
            save_btn.setToolTip("Save As… Export high-res plot")
            save_btn.triggered.disconnect()
            save_btn.triggered.connect(self.export_high_res_plot)

        # ===== Unified Top Row: Toolbar + Load Buttons =====
        top_row_layout = QHBoxLayout()
        top_row_layout.setContentsMargins(6, 4, 6, 2)
        top_row_layout.setSpacing(16)

        top_row_layout.addWidget(self.toolbar)

        self.loadTraceBtn = QPushButton("📂 Load Trace + Events")
        self.loadTraceBtn.setToolTip(
            "Load .csv trace file and auto-load matching event table"
        )
        self.loadTraceBtn.clicked.connect(
            lambda: print("📂 Button clicked") or self.load_trace_and_events()
        )

        self.load_snapshot_button = QPushButton("🖼️ Load _Result.tiff")
        self.load_snapshot_button.setToolTip("Load Vasotracker _Result.tiff snapshot")
        self.load_snapshot_button.clicked.connect(self.load_snapshot)

        self.excel_btn = QPushButton("📊 Excel")
        self.excel_btn.setToolTip("Map Events to Excel Template")
        self.excel_btn.setEnabled(False)
        self.excel_btn.clicked.connect(self.open_excel_mapping_dialog)

        self.trace_file_label = QLabel("No trace loaded")
        self.trace_file_label.setStyleSheet(
            "color: gray; font-size: 12px; padding-left: 10px;"
        )
        self.trace_file_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred
        )

        top_row_layout.addWidget(self.loadTraceBtn)
        top_row_layout.addWidget(self.load_snapshot_button)
        top_row_layout.addWidget(self.excel_btn)
        top_row_layout.addWidget(self.trace_file_label)

        main_layout.addLayout(top_row_layout)

        # ===== Plot and Scroll Slider =====
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setMinimum(0)
        self.scroll_slider.setMaximum(1000)
        self.scroll_slider.setSingleStep(1)
        self.scroll_slider.setValue(0)
        self.scroll_slider.valueChanged.connect(self.scroll_plot)
        self.scroll_slider.hide()
        self.scroll_slider.setToolTip("Scroll timeline (X-axis)")

        plot_layout = QVBoxLayout()
        plot_layout.setContentsMargins(6, 0, 6, 6)
        plot_layout.setSpacing(4)
        plot_layout.addWidget(self.canvas)
        plot_layout.addWidget(self.scroll_slider)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(0)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(plot_layout)

        # ===== Snapshot Viewer and Table =====
        self.snapshot_label = QLabel("Snapshot will appear here")
        self.snapshot_label.setAlignment(Qt.AlignCenter)
        self.snapshot_label.setFixedSize(400, 300)
        self.snapshot_label.setStyleSheet(
            "background-color: white; border: 1px solid #999;"
        )
        self.snapshot_label.hide()

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self.change_frame)
        self.slider.hide()
        self.slider.setToolTip("Navigate TIFF frames")

        self.event_table = QTableWidget()
        self.event_table.setColumnCount(3)
        self.event_table.setHorizontalHeaderLabels(["Event", "Time (s)", "ID (µm)"])
        self.event_table.setMinimumWidth(400)
        self.event_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.event_table.setStyleSheet("background-color: white; color: black;")
        self.event_table.horizontalHeader().setStretchLastSection(True)
        self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.event_table.cellClicked.connect(self.table_row_clicked)
        self.event_table.itemChanged.connect(self.handle_table_edit)
        self.event_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.event_table.customContextMenuRequested.connect(
            self.show_event_table_context_menu
        )

        snapshot_layout = QVBoxLayout()
        snapshot_layout.setSpacing(4)
        snapshot_layout.setContentsMargins(0, 0, 0, 0)
        snapshot_layout.addWidget(self.snapshot_label)
        snapshot_layout.addWidget(self.slider)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(snapshot_layout)
        right_layout.addWidget(self.event_table)

        # ===== Top-Level Layout (Left + Right) =====
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addLayout(left_layout, 4)
        top_layout.addLayout(right_layout, 1)

        main_layout.addLayout(top_layout)

        # ===== Hover Label =====
        self.hover_label = QLabel("", self)
        self.hover_label.setStyleSheet(
            """
            background-color: rgba(255, 255, 255, 220);
            border: 1px solid #888;
            border-radius: 5px;
            padding: 2px 6px;
            font-size: 12px;
        """
        )
        self.hover_label.hide()

        # ===== Canvas Interactions =====
        self.canvas.mpl_connect("draw_event", self.update_event_label_positions)
        self.canvas.mpl_connect(
            "motion_notify_event", self.update_event_label_positions
        )
        self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
        self.canvas.mpl_connect("button_press_event", self.handle_click_on_plot)
        self.canvas.mpl_connect(
            "button_release_event",
            lambda event: QTimer.singleShot(100, lambda: self.on_mouse_release(event)),
        )

# [D] ========================= FILE LOADERS: TRACE / EVENTS / TIFF =====================
    def load_trace_and_events(self, file_path=None):
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Trace File", "", "CSV Files (*.csv)"
            )
            if not file_path:
                return

        try:
            # Load trace
            self.trace_data = load_trace(file_path)
            self.trace_file_path = os.path.dirname(file_path)
            trace_filename = os.path.basename(file_path)
            self.trace_file_label.setText(f"🧪 {trace_filename}")
            self.update_plot()
        except Exception as e:
            QMessageBox.critical(
                self, "Trace Load Error", f"Failed to load trace file:\n{e}"
            )
            return

        # Store in recent files
        if file_path not in self.recent_files:
            self.recent_files = [file_path] + self.recent_files[:4]  # Keep max 5
            self.settings.setValue("recentFiles", self.recent_files)
            self.update_recent_files_menu()

        # Try to load matching _table.csv file
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        event_filename = f"{base_name}_table.csv"
        event_path = os.path.join(self.trace_file_path, event_filename)

        if os.path.exists(event_path):
            try:
                self.event_labels, self.event_times = load_events(event_path)

                # Generate table data by sampling diameters
                diam_trace = self.trace_data["Inner Diameter"]
                time_trace = self.trace_data["Time (s)"]
                self.event_table_data = []

                for i in range(len(self.event_times)):
                    if i < len(self.event_times) - 1:
                        t_sample = self.event_times[i + 1] - 2  # 2 sec before next
                        idx_pre = np.argmin(np.abs(time_trace - t_sample))
                    else:
                        idx_pre = -1
                    diam_pre = diam_trace.iloc[idx_pre]
                    self.event_table_data.append(
                        (
                            self.event_labels[i],
                            round(self.event_times[i], 2),
                            round(diam_pre, 2),
                        )
                    )

                self.populate_table()
                self.update_plot()
                self.excel_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Event Load Error",
                    f"Trace loaded, but failed to load events:\n{e}",
                )
        else:
            QMessageBox.information(
                self,
                "Event File Not Found",
                f"No matching event file found:\n{event_filename}",
            )

    def load_snapshot(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if file_path:
            try:
                frames = load_tiff(file_path)
                valid_frames = [f for f in frames if f is not None and f.size > 0]

                if len(valid_frames) < len(frames):
                    QMessageBox.warning(
                        self,
                        "TIFF Warning",
                        "Some TIFF frames were empty or corrupted and were skipped.",
                    )

                self.snapshot_frames = valid_frames
                if self.snapshot_frames:
                    self.display_frame(0)
                    self.slider.setMaximum(len(self.snapshot_frames) - 1)
                    self.slider.setValue(0)
                    self.snapshot_label.show()
                    self.slider.show()
                    self.slider_marker = None
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load TIFF file:\n{e}")

    def display_frame(self, index):
        if not self.snapshot_frames:
            return

        # Clamp index to valid range
        if index < 0 or index >= len(self.snapshot_frames):
            print(f"⚠️ Frame index {index} out of bounds.")
            return

        frame = self.snapshot_frames[index]

        # Skip if frame is empty or corrupted
        if frame is None or frame.size == 0:
            print(f"⚠️ Skipping empty or corrupted frame at index {index}")
            return

        try:
            if frame.ndim == 2:
                height, width = frame.shape
                q_img = QImage(frame.data, width, height, QImage.Format_Grayscale8)
            elif frame.ndim == 3:
                height, width, channels = frame.shape
                if channels == 3:
                    q_img = QImage(
                        frame.data, width, height, 3 * width, QImage.Format_RGB888
                    )
                else:
                    raise ValueError(f"Unsupported TIFF frame format: {frame.shape}")
            else:
                raise ValueError(f"Unknown TIFF frame dimensions: {frame.shape}")

            self.snapshot_label.setPixmap(
                QPixmap.fromImage(q_img).scaled(
                    self.snapshot_label.width(),
                    self.snapshot_label.height(),
                    Qt.KeepAspectRatio,
                )
            )
        except Exception as e:
            print(f"⚠️ Error displaying frame {index}: {e}")

    def change_frame(self):
        if not self.snapshot_frames:
            return

        idx = self.slider.value()
        self.current_frame = idx
        self.display_frame(idx)
        self.update_slider_marker()

    def update_slider_marker(self):
        if self.trace_data is None or not self.snapshot_frames:
            return

        t_current = self.slider.value() * self.recording_interval

        if self.slider_marker is None:
            self.slider_marker = self.ax.axvline(
                x=t_current,
                color="red",
                linestyle="--",
                linewidth=1.5,
                label="TIFF Frame",
            )
        else:
            self.slider_marker.set_xdata([t_current, t_current])

        self.canvas.draw_idle()
        self.canvas.flush_events()

    def update_event_label_positions(self, event=None):
        if not self.event_text_objects:
            return

        y_min, y_max = self.ax.get_ylim()
        y_top = min(y_max - 5, y_max * 0.95)

        for txt, x in self.event_text_objects:
            txt.set_position((x, y_top))

    def populate_event_table_from_df(self, df):
        self.event_table.setRowCount(len(df))
        for row in range(len(df)):
            self.event_table.setItem(
                row, 0, QTableWidgetItem(str(df.iloc[row].get("EventLabel", "")))
            )
            self.event_table.setItem(
                row, 1, QTableWidgetItem(str(df.iloc[row].get("Time (s)", "")))
            )
            self.event_table.setItem(
                row, 2, QTableWidgetItem(str(df.iloc[row].get("ID (µm)", "")))
            )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().endswith(".fig.pickle"):
                    event.accept()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.endswith(".fig.pickle"):
                self.load_pickle_session(file_path)

    def load_pickle_session(self, file_path):
        try:
            with open(file_path, "rb") as f:
                state = pickle.load(f)

            # Restore basic session state
            self.trace_data = state.get("trace_data", None)
            self.event_labels = state.get("event_labels", [])
            self.event_times = state.get("event_times", [])
            self.event_table_data = state.get("event_table_data", [])

            # Temporarily store plot style before update_plot() wipes things
            plot_style = state.get("plot_style", None)
            if plot_style:
                self.apply_plot_style(plot_style)
            self.canvas.draw_idle()

            # Redraw plot (this resets styles, so it must come before applying style)
            self.update_plot()

            # Restore axis labels, limits, grid
            self.ax.set_xlabel(state.get("xlabel", "Time (s)"))
            self.ax.set_ylabel(state.get("ylabel", "Inner Diameter (µm)"))
            self.ax.set_xlim(*state.get("xlim", self.ax.get_xlim()))
            self.ax.set_ylim(*state.get("ylim", self.ax.get_ylim()))
            self.grid_visible = state.get("grid_visible", True)
            self.ax.grid(self.grid_visible, color="#CCC")

            # Re-plot pinned points
            self.pinned_points.clear()
            for x, y in state.get("pinned_points", []):
                marker = self.ax.plot(x, y, "ro", markersize=6)[0]
                label = self.ax.annotate(
                    f"{x:.2f} s\n{y:.1f} µm",
                    xy=(x, y),
                    xytext=(6, 6),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=1),
                    fontsize=8,
                )
                self.pinned_points.append((marker, label))

            # Apply saved style LAST so it overrides any plot resets
            if plot_style:
                self.apply_plot_style(plot_style)

            # Final UI updates
            self.canvas.draw_idle()
            self.populate_table()
            self.trace_file_label.setText(f"Restored from: {os.path.basename(file_path)}")
            self.statusBar().showMessage("Session restored successfully.")
            print("✅ Session reloaded with full metadata.")

        except Exception as e:
            QMessageBox.critical(self, "Load Failed", f"Error loading session:\n{e}")

    # [E] ========================= PLOTTING AND EVENT SYNC ============================
    def update_plot(self):
        if self.trace_data is None:
            return

        self.ax.clear()
        self.ax.set_facecolor("white")
        self.ax.tick_params(colors="black")
        self.ax.xaxis.label.set_color("black")
        self.ax.yaxis.label.set_color("black")
        self.ax.title.set_color("black")
        self.event_text_objects = []

        # Plot trace
        t = self.trace_data["Time (s)"]
        d = self.trace_data["Inner Diameter"]
        self.ax.plot(t, d, "k-", linewidth=1.5)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Inner Diameter (µm)")
        self.ax.grid(True, color="#CCC")

        # Plot events if available
        if self.event_labels and self.event_times:
            self.event_table_data = []
            offset_sec = 2
            nEv = len(self.event_times)
            diam_trace = self.trace_data["Inner Diameter"]
            time_trace = self.trace_data["Time (s)"]

            for i in range(nEv):
                idx_ev = np.argmin(np.abs(time_trace - self.event_times[i]))
                diam_at_ev = diam_trace.iloc[idx_ev]

                if i < nEv - 1:
                    t_sample = self.event_times[i + 1] - offset_sec
                    idx_pre = np.argmin(np.abs(time_trace - t_sample))
                else:
                    idx_pre = -1
                diam_pre = diam_trace.iloc[idx_pre]

                # Vertical line
                self.ax.axvline(
                    x=self.event_times[i], color="black", linestyle="--", linewidth=0.8
                )

                # Label on plot
                txt = self.ax.text(
                    self.event_times[i],
                    0,
                    self.event_labels[i],
                    rotation=90,
                    verticalalignment="top",
                    horizontalalignment="right",
                    fontsize=8,
                    color="black",
                    clip_on=True,
                )
                self.event_text_objects.append((txt, self.event_times[i]))

                # Table entry
                self.event_table_data.append(
                    (
                        self.event_labels[i],
                        round(self.event_times[i], 2),
                        round(diam_pre, 2),
                    )
                )

            self.populate_table()
            self.auto_export_table()

        self.canvas.draw_idle()

    def scroll_plot(self):
        if self.trace_data is None:
            return

        full_t_min = self.trace_data["Time (s)"].min()
        full_t_max = self.trace_data["Time (s)"].max()
        xlim = self.ax.get_xlim()
        window_width = xlim[1] - xlim[0]

        max_scroll = self.scroll_slider.maximum()
        slider_pos = self.scroll_slider.value()
        fraction = slider_pos / max_scroll

        new_left = full_t_min + (full_t_max - full_t_min - window_width) * fraction
        new_right = new_left + window_width

        self.ax.set_xlim(new_left, new_right)
        self.canvas.draw_idle()

    # [F] ========================= EVENT TABLE MANAGEMENT ================================
    def populate_table(self):
        self.event_table.blockSignals(True)
        self.event_table.setRowCount(len(self.event_table_data))
        for row, (label, t, d) in enumerate(self.event_table_data):
            self.event_table.setItem(row, 0, QTableWidgetItem(str(label)))
            self.event_table.setItem(row, 1, QTableWidgetItem(str(t)))
            self.event_table.setItem(row, 2, QTableWidgetItem(str(d)))
        self.event_table.blockSignals(False)

    def handle_table_edit(self, item):
        row = item.row()
        col = item.column()

        # Only allow editing the third column (ID)
        if col != 2:
            self.populate_table()
            return

        try:
            new_val = float(item.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please enter a valid number.")
            self.populate_table()
            return

        label = self.event_table_data[row][0]
        time = self.event_table_data[row][1]
        old_val = self.event_table_data[row][2]

        self.last_replaced_event = (row, old_val)
        self.event_table_data[row] = (label, time, round(new_val, 2))

        self.auto_export_table()
        print(f"✏️ ID updated at {time:.2f}s → {new_val:.2f} µm")

    def table_row_clicked(self, row, col):
        if not self.event_table_data:
            return

        t = self.event_table_data[row][1]

        if self.selected_event_marker:
            self.selected_event_marker.remove()

        self.selected_event_marker = self.ax.axvline(
            x=t, color="blue", linestyle="--", linewidth=1.2
        )
        self.canvas.draw()

    # [G] ========================= PIN INTERACTION LOGIC ================================
    def handle_click_on_plot(self, event):
        if event.inaxes != self.ax:
            return

        x = event.xdata
        if x is None:
            return

        # 🔴 Right-click = open pin context menu
        if event.button == 3:
            click_x, click_y = event.x, event.y

            for marker, label in self.pinned_points:
                data_x = marker.get_xdata()[0]
                data_y = marker.get_ydata()[0]
                pixel_x, pixel_y = self.ax.transData.transform((data_x, data_y))
                pixel_distance = np.hypot(pixel_x - click_x, pixel_y - click_y)

                if pixel_distance < 10:
                    menu = QMenu(self)
                    replace_action = menu.addAction("Replace Event Value…")
                    delete_action = menu.addAction("Delete Pin")
                    undo_action = menu.addAction("Undo Last Replacement")
                    add_new_action = menu.addAction("➕ Add as New Event")

                    action = menu.exec_(self.canvas.mapToGlobal(event.guiEvent.pos()))
                    if action == delete_action:
                        marker.remove()
                        label.remove()
                        self.pinned_points.remove((marker, label))
                        self.canvas.draw_idle()
                        return
                    elif action == replace_action:
                        self.handle_event_replacement(data_x, data_y)
                        return
                    elif action == undo_action:
                        self.undo_last_replacement()
                        return
                    elif action == add_new_action:
                        self.prompt_add_event(data_x, data_y)
                        return
            return

        # 🟢 Left-click = add pin (unless toolbar zoom/pan is active)
        if event.button == 1 and not self.toolbar.mode:
            time_array = self.trace_data["Time (s)"].values
            id_array = self.trace_data["Inner Diameter"].values
            nearest_idx = np.argmin(np.abs(time_array - x))
            y = id_array[nearest_idx]

            marker = self.ax.plot(x, y, "ro", markersize=6)[0]
            label = self.ax.annotate(
                f"{x:.2f} s\n{y:.1f} µm",
                xy=(x, y),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=1),
                fontsize=8,
            )

            self.pinned_points.append((marker, label))
            self.canvas.draw_idle()

    def handle_event_replacement(self, x, y):
        if not self.event_labels or not self.event_times:
            print("No events available to replace.")
            return

        options = [
            f"{label} at {time:.2f}s"
            for label, time in zip(self.event_labels, self.event_times)
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "Select Event to Replace",
            "Choose the event whose value you want to replace:",
            options,
            0,
            False,
        )

        if ok and selected:
            index = options.index(selected)
            event_label = self.event_labels[index]
            event_time = self.event_times[index]

            confirm = QMessageBox.question(
                self,
                "Confirm Replacement",
                f"Replace ID for '{event_label}' at {event_time:.2f}s with {y:.1f} µm?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if confirm == QMessageBox.Yes:
                old_value = self.event_table_data[index][2]
                self.last_replaced_event = (index, old_value)

                self.event_table_data[index] = (
                    event_label,
                    round(event_time, 2),
                    round(y, 2),
                )
                self.populate_table()
                self.auto_export_table()
                print(f"✅ Replaced value at {event_time:.2f}s with {y:.1f} µm.")

    def prompt_add_event(self, x, y):
        if not self.event_table_data:
            QMessageBox.warning(
                self, "No Events", "You must load events before adding new ones."
            )
            return

        # Build label options and insertion points
        insert_labels = [
            f"{label} at {t:.2f}s" for label, t, _ in self.event_table_data
        ]
        insert_labels.append("↘️ Add to end")  # final option

        selected, ok = QInputDialog.getItem(
            self,
            "Insert Event",
            "Insert new event before which existing event?",
            insert_labels,
            0,
            False,
        )

        if not ok or not selected:
            return

        # Choose label for new event
        new_label, label_ok = QInputDialog.getText(
            self, "New Event Label", "Enter label for the new event:"
        )

        if not label_ok or not new_label.strip():
            return

        insert_idx = insert_labels.index(selected)
        new_entry = (new_label.strip(), round(x, 2), round(y, 2))

        # Insert into data
        if insert_idx == len(self.event_table_data):  # Add to end
            self.event_labels.append(new_label.strip())
            self.event_times.append(x)
            self.event_table_data.append(new_entry)
        else:
            self.event_labels.insert(insert_idx, new_label.strip())
            self.event_times.insert(insert_idx, x)
            self.event_table_data.insert(insert_idx, new_entry)

        self.populate_table()
        self.auto_export_table()
        print(f"➕ Inserted new event: {new_entry}")

    def undo_last_replacement(self):
        if self.last_replaced_event is None:
            QMessageBox.information(self, "Undo", "No replacement to undo.")
            return

        index, old_val = self.last_replaced_event
        label, time, _ = self.event_table_data[index]

        self.event_table_data[index] = (label, time, old_val)
        self.populate_table()
        self.auto_export_table()

        QMessageBox.information(
            self, "Undo", f"Restored value for '{label}' at {time:.2f}s."
        )
        self.last_replaced_event = None

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
    def update_hover_label(self, event):
        if event.inaxes != self.ax or self.trace_data is None:
            self.hover_label.hide()
            return

        x_val = event.xdata
        if x_val is None:
            self.hover_label.hide()
            return

        time_array = self.trace_data["Time (s)"].values
        id_array = self.trace_data["Inner Diameter"].values
        nearest_idx = np.argmin(np.abs(time_array - x_val))
        y_val = id_array[nearest_idx]

        text = f"Time: {x_val:.2f} s\nID: {y_val:.2f} µm"
        self.hover_label.setText(text)

        cursor_offset_x = 10
        cursor_offset_y = -30
        self.hover_label.move(
            int(
                self.canvas.geometry().left()
                + event.guiEvent.pos().x()
                + cursor_offset_x
            ),
            int(
                self.canvas.geometry().top()
                + event.guiEvent.pos().y()
                + cursor_offset_y
            ),
        )
        self.hover_label.adjustSize()
        self.hover_label.show()

    # [I] ========================= ZOOM + SLIDER LOGIC ================================
    def on_mouse_release(self, event):
        self.update_event_label_positions(event)

        # Deselect zoom after box zoom
        if self.toolbar.mode == "zoom":
            self.toolbar.zoom()  # toggles off
            self.toolbar.mode = ""
            self.toolbar._active = None
            self.canvas.setCursor(Qt.ArrowCursor)

        self.update_scroll_slider()

    def update_scroll_slider(self):
        if self.trace_data is None:
            return

        full_t_min = self.trace_data["Time (s)"].min()
        full_t_max = self.trace_data["Time (s)"].max()
        xlim = self.ax.get_xlim()
        self.window_width = xlim[1] - xlim[0]

        if self.window_width < (full_t_max - full_t_min):
            self.scroll_slider.show()
        else:
            self.scroll_slider.hide()

    # [J] ========================= PLOT STYLE EDITOR ================================
    def open_plot_style_editor(self, tab_name=None):
        from PyQt5.QtWidgets import QDialog

        dialog = PlotStyleDialog(self)
        self.plot_style_dialog = dialog

        if tab_name:
            index = dialog.tabs.indexOf(dialog.tabs.findChild(QWidget, tab_name))
            if index != -1:
                dialog.tabs.setCurrentIndex(index)

        prev_style = dialog.get_style()

        if dialog.exec_() == QDialog.Accepted:
            style = dialog.get_style()
            self.apply_plot_style(style)
        else:
            self.apply_plot_style(prev_style)

    def apply_plot_style(self, style):
        # Axis Titles
        self.ax.xaxis.label.set_fontsize(style["axis_font_size"])
        self.ax.xaxis.label.set_fontname(style["axis_font_family"])
        self.ax.xaxis.label.set_fontstyle(
            "italic" if style["axis_italic"] else "normal"
        )
        self.ax.xaxis.label.set_fontweight("bold" if style["axis_bold"] else "normal")

        self.ax.yaxis.label.set_fontsize(style["axis_font_size"])
        self.ax.yaxis.label.set_fontname(style["axis_font_family"])
        self.ax.yaxis.label.set_fontstyle(
            "italic" if style["axis_italic"] else "normal"
        )
        self.ax.yaxis.label.set_fontweight("bold" if style["axis_bold"] else "normal")

        # Tick Labels
        self.ax.tick_params(axis="x", labelsize=style["tick_font_size"])
        self.ax.tick_params(axis="y", labelsize=style["tick_font_size"])

        # Event Labels
        for txt, _ in self.event_text_objects:
            txt.set_fontsize(style["event_font_size"])
            txt.set_fontname(style["event_font_family"])
            txt.set_fontstyle("italic" if style["event_italic"] else "normal")
            txt.set_fontweight("bold" if style["event_bold"] else "normal")

        # Pinned Labels
        for marker, label in self.pinned_points:
            marker.set_markersize(style["pin_size"])
            label.set_fontsize(style["pin_font_size"])
            label.set_fontname(style["pin_font_family"])
            label.set_fontstyle("italic" if style["pin_italic"] else "normal")
            label.set_fontweight("bold" if style["pin_bold"] else "normal")

        # Line Width — ONLY change the main trace line
        main_line = self.ax.lines[0] if self.ax.lines else None
        if main_line:
            main_line.set_linewidth(style["line_width"])

        self.canvas.draw_idle()

    def open_customize_dialog(self):
        # Check visibility of any existing grid line
        is_grid_visible = any(line.get_visible() for line in self.ax.get_xgridlines())
        self.ax.grid(not is_grid_visible)
        self.toolbar.edit_parameters()
        self.canvas.draw_idle()

    def start_new_analysis(self):
        confirm = QMessageBox.question(
            self,
            "Start New Analysis",
            "Clear current session and start fresh?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.clear_current_session()

    def clear_current_session(self):
        self.trace_data = None
        self.trace_file_path = None
        self.snapshot_frames = []
        self.current_frame = 0
        self.event_labels = []
        self.event_times = []
        self.event_text_objects = []
        self.event_table_data = []
        self.pinned_points = []
        self.selected_event_marker = None
        self.slider_marker = None
        self.ax.clear()
        self.canvas.draw()
        self.event_table.setRowCount(0)
        self.snapshot_label.clear()
        self.trace_file_label.setText("No trace loaded")
        self.slider.hide()
        self.snapshot_label.hide()
        self.excel_btn.setEnabled(False)
        print("🧼 Cleared session.")

    def show_event_table_context_menu(self, position):
        index = self.event_table.indexAt(position)
        if not index.isValid():
            return

        row = index.row()
        menu = QMenu()

        # Group 1: Edit & Delete
        edit_action = menu.addAction("✏️ Edit ID (µm)…")
        delete_action = menu.addAction("🗑️ Delete Event")
        menu.addSeparator()

        # Group 2: Plot Navigation
        jump_action = menu.addAction("🔍 Jump to Event on Plot")
        pin_action = menu.addAction("📌 Pin to Plot")
        menu.addSeparator()

        # Group 3: Pin Utilities
        replace_with_pin_action = menu.addAction("🔄 Replace ID with Pinned Value")
        clear_pins_action = menu.addAction("❌ Clear All Pins")

        # Show menu
        action = menu.exec_(self.event_table.viewport().mapToGlobal(position))

        # Group 1 actions
        if action == edit_action:
            old_val = self.event_table.item(row, 2).text()
            new_val, ok = QInputDialog.getDouble(
                self, "Edit ID", "Enter new ID (µm):", float(old_val), 0, 10000, 2
            )
            if ok:
                self.event_table_data[row] = (
                    self.event_table_data[row][0],
                    self.event_table_data[row][1],
                    round(new_val, 2),
                )
                self.populate_table()
                self.auto_export_table()

        elif action == delete_action:
            confirm = QMessageBox.question(
                self,
                "Delete Event",
                f"Delete event: {self.event_table_data[row][0]}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                del self.event_labels[row]
                del self.event_times[row]
                del self.event_table_data[row]
                self.populate_table()
                self.update_plot()

        # Group 2 actions
        elif action == jump_action:
            t = self.event_table_data[row][1]
            if self.selected_event_marker:
                self.selected_event_marker.remove()
            self.selected_event_marker = self.ax.axvline(
                x=t, color="blue", linestyle="--", linewidth=1.2
            )
            self.canvas.draw()

        elif action == pin_action:
            t = self.event_table_data[row][1]
            id_val = self.event_table_data[row][2]
            marker = self.ax.plot(t, id_val, "ro", markersize=6)[0]
            label = self.ax.annotate(
                f"{t:.2f} s\n{round(id_val,1)} µm",
                xy=(t, id_val),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=1),
                fontsize=8,
            )
            self.pinned_points.append((marker, label))
            self.canvas.draw_idle()

        # Group 3 actions
        elif action == replace_with_pin_action:
            t_event = self.event_table_data[row][1]
            if not self.pinned_points:
                QMessageBox.information(
                    self, "No Pins", "There are no pinned points to use."
                )
                return
            closest_pin = min(
                self.pinned_points, key=lambda p: abs(p[0].get_xdata()[0] - t_event)
            )
            pin_time = closest_pin[0].get_xdata()[0]
            pin_id = closest_pin[0].get_ydata()[0]
            confirm = QMessageBox.question(
                self,
                "Confirm Replacement",
                f"Replace ID at {t_event:.2f}s with pinned value: {pin_id:.2f} µm?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self.last_replaced_event = (row, self.event_table_data[row][2])
                self.event_table_data[row] = (
                    self.event_table_data[row][0],
                    t_event,
                    round(pin_id, 2),
                )
                self.populate_table()
                self.auto_export_table()
                print(
                    f"🔄 Replaced ID at {t_event:.2f}s with pinned value {pin_id:.2f} µm."
                )

        elif action == clear_pins_action:
            if not self.pinned_points:
                QMessageBox.information(self, "No Pins", "There are no pins to clear.")
                return
            for marker, label in self.pinned_points:
                marker.remove()
                label.remove()
            self.pinned_points.clear()
            self.canvas.draw_idle()
            print("🧹 Cleared all pins.")

    def save_recent_files(self):
        self.settings.setValue("recentFiles", self.recent_files)

    def clear_recent_files(self):
        self.recent_files = []
        self.save_recent_files()
        self.build_recent_files_menu()

    def get_current_plot_style(self):
        try:
            return self.plot_style_dialog.get_style()
        except AttributeError:
            # Return default style dict manually
            return {
                "axis_font_size": 14,
                "axis_font_family": "Arial",
                "axis_bold": False,
                "axis_italic": False,
                "tick_font_size": 12,
                "event_font_size": 10,
                "event_font_family": "Arial",
                "event_bold": False,
                "event_italic": False,
                "pin_font_size": 10,
                "pin_font_family": "Arial",
                "pin_bold": False,
                "pin_italic": False,
                "pin_size": 6,
                "line_width": 2,
            }

    # [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
    def auto_export_table(self):
        if not self.trace_file_path:
            print("⚠️ No trace path set. Cannot export event table.")
            return

        try:
            output_dir = os.path.abspath(self.trace_file_path)
            csv_path = os.path.join(output_dir, "eventDiameters_output.csv")
            df = pd.DataFrame(
                self.event_table_data, columns=["Event", "Time (s)", "ID (µm)"]
            )
            df.to_csv(csv_path, index=False)
            print(f"✔ Event table auto-exported to:\n{csv_path}")
        except Exception as e:
            print(f"❌ Failed to auto-export event table:\n{e}")

        if self.excel_auto_path and self.excel_auto_column:
            update_excel_file(
                self.excel_auto_path,
                self.event_table_data,
                start_row=3,
                column_letter=self.excel_auto_column,
            )

    def auto_export_editable_plot(self):
        if not self.trace_file_path:
            return
        try:
            pickle_path = os.path.join(
                os.path.abspath(self.trace_file_path), "tracePlot_output.fig.pickle"
            )
            state = {
                "trace_data": self.trace_data,
                "event_labels": self.event_labels,
                "event_times": self.event_times,
                "event_table_data": self.event_table_data,
            }
            with open(pickle_path, "wb") as f:
                pickle.dump(state, f)
            print(f"✔ Editable trace figure state saved to:\n{pickle_path}")
        except Exception as e:
            print(f"❌ Failed to save .pickle figure:\n{e}")

    def export_high_res_plot(self):
        if not self.trace_file_path:
            QMessageBox.warning(self, "Export Error", "No trace file loaded.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save High-Resolution Plot",
            os.path.join(
                os.path.abspath(self.trace_file_path), "tracePlot_highres.tiff"
            ),
            "TIFF Image (*.tiff);;SVG Vector (*.svg)",
        )

        if save_path:
            try:
                ext = os.path.splitext(save_path)[1].lower()
                if ext == ".svg":
                    self.fig.savefig(save_path, format="svg", bbox_inches="tight")
                else:
                    self.fig.savefig(
                        save_path, format="tiff", dpi=600, bbox_inches="tight"
                    )
                    self.auto_export_editable_plot()

                QMessageBox.information(
                    self, "Export Complete", f"Plot exported:\n{save_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def open_excel_mapping_dialog(self):
        if not self.event_table_data:
            QMessageBox.warning(self, "No Data", "No event data available to export.")
            return

        dialog = ExcelMappingDialog(
            self,
            [
                {"EventLabel": label, "Time (s)": time, "ID (µm)": idval}
                for label, time, idval in self.event_table_data
            ],
        )
        if dialog.exec_():
            # Only remember file path and column – don't trigger auto-write!
            self.excel_auto_path = dialog.excel_path
            self.excel_auto_column = dialog.column_selector.currentText()

    def toggle_grid(self):
        self.grid_visible = not self.grid_visible
        if self.grid_visible:
            self.ax.grid(True, color="#CCC")
        else:
            self.ax.grid(False)
        self.canvas.draw_idle()


# [L] ========================= PlotStyleDialog =========================
from PyQt5.QtWidgets import (
    QDialog,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QFormLayout,
)


class PlotStyleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setMinimumWidth(400)

        self.tabs = QTabWidget()
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        # ===== Bottom OK / Apply / Cancel =====
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(10, 4, 10, 10)

        self.ok_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        self.apply_btn = QPushButton("Apply")

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self.handle_apply_all)

        btn_row.addStretch()
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)

        main_layout.addLayout(btn_row)

        # Track settings per tab
        self.init_axis_tab()
        self.init_tick_tab()
        self.init_event_tab()
        self.init_pin_tab()
        self.init_line_tab()

    def init_axis_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.axis_font_size = QSpinBox()
        self.axis_font_size.setRange(6, 32)
        self.axis_font_size.setValue(14)

        self.axis_font_family = QComboBox()
        self.axis_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )

        self.axis_bold = QCheckBox("Bold")
        self.axis_italic = QCheckBox("Italic")

        form.addRow("Font Size:", self.axis_font_size)
        form.addRow("Font Family:", self.axis_font_family)
        form.addRow("", self.axis_bold)
        form.addRow("", self.axis_italic)

        layout.addLayout(form)
        layout.addLayout(self.button_row("axis"))
        self.tabs.addTab(tab, "Axis Titles")
        tab.setObjectName("Axis Titles")

    def init_tick_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(12)

        form.addRow("Tick Label Font Size:", self.tick_font_size)

        layout.addLayout(form)
        layout.addLayout(self.button_row("tick"))
        self.tabs.addTab(tab, "Tick Labels")
        tab.setObjectName("Tick Labels")

    def init_event_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.event_font_size = QSpinBox()
        self.event_font_size.setRange(6, 32)
        self.event_font_size.setValue(10)

        self.event_font_family = QComboBox()
        self.event_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )

        self.event_bold = QCheckBox("Bold")
        self.event_italic = QCheckBox("Italic")

        form.addRow("Font Size:", self.event_font_size)
        form.addRow("Font Family:", self.event_font_family)
        form.addRow("", self.event_bold)
        form.addRow("", self.event_italic)

        layout.addLayout(form)
        layout.addLayout(self.button_row("event"))
        self.tabs.addTab(tab, "Event Labels")
        tab.setObjectName("Event Labels")

    def init_pin_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.pin_font_size = QSpinBox()
        self.pin_font_size.setRange(6, 32)
        self.pin_font_size.setValue(10)

        self.pin_font_family = QComboBox()
        self.pin_font_family.addItems(
            ["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"]
        )

        self.pin_bold = QCheckBox("Bold")
        self.pin_italic = QCheckBox("Italic")

        self.pin_size = QSpinBox()
        self.pin_size.setRange(2, 20)
        self.pin_size.setValue(6)

        form.addRow("Font Size:", self.pin_font_size)
        form.addRow("Font Family:", self.pin_font_family)
        form.addRow("", self.pin_bold)
        form.addRow("", self.pin_italic)
        form.addRow("Marker Size:", self.pin_size)

        layout.addLayout(form)
        layout.addLayout(self.button_row("pin"))
        self.tabs.addTab(tab, "Pinned Labels")
        tab.setObjectName("Pinned Labels")

    def init_line_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        self.line_width = QSpinBox()
        self.line_width.setRange(1, 10)
        self.line_width.setValue(2)

        form.addRow("Trace Line Width:", self.line_width)
        layout.addLayout(form)
        layout.addLayout(self.button_row("line"))
        self.tabs.addTab(tab, "Trace Style")
        tab.setObjectName("Trace Style")

    def button_row(self, section):
        layout = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        default_btn = QPushButton("Default")

        apply_btn.clicked.connect(lambda: self.handle_apply_tab(section))
        default_btn.clicked.connect(lambda: self.reset_defaults(section))

        layout.addStretch()
        layout.addWidget(apply_btn)
        layout.addWidget(default_btn)
        return layout

    def handle_apply_tab(self, section):
        if hasattr(self.parent(), "apply_plot_style"):
            self.parent().apply_plot_style(self.get_style())

    def handle_apply_all(self):
        if hasattr(self.parent(), "apply_plot_style"):
            self.parent().apply_plot_style(self.get_style())

    def reset_defaults(self, section):
        if section == "axis":
            self.axis_font_size.setValue(14)
            self.axis_font_family.setCurrentText("Arial")
            self.axis_bold.setChecked(False)
            self.axis_italic.setChecked(False)
        elif section == "tick":
            self.tick_font_size.setValue(12)
        elif section == "event":
            self.event_font_size.setValue(10)
            self.event_font_family.setCurrentText("Arial")
            self.event_bold.setChecked(False)
            self.event_italic.setChecked(False)
        elif section == "pin":
            self.pin_font_size.setValue(10)
            self.pin_font_family.setCurrentText("Arial")
            self.pin_bold.setChecked(False)
            self.pin_italic.setChecked(False)
            self.pin_size.setValue(6)
        elif section == "line":
            self.line_width.setValue(2)

    def get_style(self):
        return {
            "axis_font_size": self.axis_font_size.value(),
            "axis_font_family": self.axis_font_family.currentText(),
            "axis_bold": self.axis_bold.isChecked(),
            "axis_italic": self.axis_italic.isChecked(),
            "tick_font_size": self.tick_font_size.value(),
            "event_font_size": self.event_font_size.value(),
            "event_font_family": self.event_font_family.currentText(),
            "event_bold": self.event_bold.isChecked(),
            "event_italic": self.event_italic.isChecked(),
            "pin_font_size": self.pin_font_size.value(),
            "pin_font_family": self.pin_font_family.currentText(),
            "pin_bold": self.pin_bold.isChecked(),
            "pin_italic": self.pin_italic.isChecked(),
            "pin_size": self.pin_size.value(),
            "line_width": self.line_width.value(),
        }
