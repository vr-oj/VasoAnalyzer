# [A] ========================= IMPORTS AND GLOBAL CONFIG ============================
import sys, os, pickle, requests
import numpy as np, pandas as pd, tifffile
import h5py
from datetime import datetime
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from utils.config import APP_VERSION
from functools import partial
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib import rcParams
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
    QStatusBar,
    QDesktopWidget,
    QStackedWidget,
    QUndoStack,
    QUndoView,
    QUndoCommand,
)

from PyQt5.QtGui import QPixmap, QImage, QIcon, QFont, QBrush, QColor, QCursor
from PyQt5.QtCore import Qt, QTimer, QSize, QSettings, QEvent, QPoint

from vasoanalyzer.dual_view_panel import DataViewPanel, DualViewWidget
from vasoanalyzer.trace_loader import load_trace
from vasoanalyzer.tiff_loader import load_tiff
from vasoanalyzer.event_loader import load_events
from vasoanalyzer.excel_mapper import ExcelMappingDialog, update_excel_file
from vasoanalyzer.version_checker import check_for_new_version

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


def check_for_new_version(current_version="v1.6"):
    try:
        response = requests.get(
            "https://api.github.com/repos/vr-oj/VasoAnalyzer_2.0/releases/latest"
        )
        if response.status_code == 200:
            latest_version = response.json().get("tag_name", "")
            if latest_version and latest_version != current_version:
                return latest_version
    except Exception as e:
        print(f"Update check failed: {e}")
    return None


PREVIOUS_PLOT_PATH = os.path.join(
    os.path.expanduser("~"), ".vasoanalyzer_last_plot.pickle"
)
DEFAULT_STYLE = dict(
    axis_font_size=14,
    axis_font_family="Arial",
    axis_bold=False,
    axis_italic=False,
    tick_font_size=12,
    event_font_size=10,
    event_font_family="Arial",
    event_bold=False,
    event_italic=False,
    pin_font_size=10,
    pin_font_family="Arial",
    pin_bold=False,
    pin_italic=False,
    pin_size=6,
    line_width=2,
)


# [B] ========================= MAIN CLASS DEFINITION ================================
class VasoAnalyzerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(self.icon_path("VasoAnalyzerIcon.icns")))
        self.setMouseTracking(True)

        # ===== Setup App Window =====
        self.setWindowTitle("VasoAnalyzer 1.6 - Python Edition")
        self.setGeometry(100, 100, 1280, 720)
        screen_size = QDesktopWidget().availableGeometry()
        self.resize(screen_size.width(), screen_size.height())

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
        self.recording_interval = 0.14  # 0.14	# 140 ms per frame
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
        self.setAcceptDrops(True)
        # ——— undo/redo ———
        self.undo_stack = QUndoStack(self)

        # ===== Axis + Slider State =====
        self.axis_dragging = False
        self.axis_drag_start = None
        self.drag_direction = None
        self.scroll_slider = None
        self.window_width = None

        # ===== Build UI =====
        self.create_menubar()
        self.initUI()
        self._wrap_views()

        self.modeStack.setMouseTracking(True)
        self.modeStack.widget(0).setMouseTracking(True)
        self.canvas.setMouseTracking(True)

        self.check_for_updates_at_startup()

    def _wrap_views(self):
        # Create the three modes:
        self.singleMode = QWidget()  # placeholder for your existing GUI
        self.dualMode = DualViewWidget(self)

        # Extract current central widget (your single view)
        old = self.centralWidget().children()
        # We’ll assume initUI placed everything inside self.main_layout of centralWidget()
        # So just wrap the existing layout in a container:
        container = QWidget()
        container.setLayout(self.main_layout)

        # Now set up the stack
        self.modeStack = QStackedWidget(self)
        self.modeStack.addWidget(container)  # index 0: single view
        self.modeStack.addWidget(self.dualMode)  # index 1: dual view

        # Replace central widget’s layout
        self.setCentralWidget(self.modeStack)
        self.modeStack.setCurrentIndex(0)

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

    def sync_slider_with_plot(self, event=None):
        if self.trace_data is None:
            return

        full_t = self.trace_data["Time (s)"]
        tmin, tmax = full_t.min(), full_t.max()
        xmin, xmax = self.ax.get_xlim()
        window = xmax - xmin

        scroll_max = tmax - window
        if scroll_max <= tmin:
            val = self.scroll_slider.minimum()
        else:
            val = np.interp(
                xmin,
                [tmin, scroll_max],
                [self.scroll_slider.minimum(), self.scroll_slider.maximum()],
            )

        self.scroll_slider.blockSignals(True)
        self.scroll_slider.setValue(int(val))
        self.scroll_slider.blockSignals(False)

    def create_menubar(self):
        menubar = self.menuBar()
        self._build_file_menu(menubar)
        self._build_edit_menu(menubar)
        self._build_view_menu(menubar)
        self._build_help_menu(menubar)

    def _build_file_menu(self, menubar):
        file_menu = menubar.addMenu("File")

        # 1) New Analysis…
        self.action_new = QAction("Start New Analysis…", self)
        self.action_new.setShortcut("Ctrl+N")
        self.action_new.triggered.connect(self.start_new_analysis)
        file_menu.addAction(self.action_new)

        start_new = QAction("Start New Dual Analysis", self)
        start_new.triggered.connect(self.clear_dual_view)
        file_menu.addAction(start_new)

        # 2) Open Trace & Events…
        self.action_open_trace = QAction("Open Trace & Events…", self)
        self.action_open_trace.setShortcut("Ctrl+O")
        self.action_open_trace.triggered.connect(self._handle_load_trace)
        file_menu.addAction(self.action_open_trace)

        # 3) Open Result TIFF…
        self.action_open_tiff = QAction("Open Result TIFF…", self)
        self.action_open_tiff.setShortcut("Ctrl+T")
        self.action_open_tiff.triggered.connect(self.load_snapshot)
        file_menu.addAction(self.action_open_tiff)

        file_menu.addSeparator()

        # 4) Export ▶
        export_menu = file_menu.addMenu("Export ▶")

        self.action_export_tiff = QAction("High‑Res Plot…", self)
        self.action_export_tiff.triggered.connect(self.export_high_res_plot)
        export_menu.addAction(self.action_export_tiff)

        self.action_export_csv = QAction("Events as CSV…", self)
        self.action_export_csv.triggered.connect(self.auto_export_table)
        export_menu.addAction(self.action_export_csv)

        self.action_export_excel = QAction("To Excel Template…", self)
        self.action_export_excel.triggered.connect(self.open_excel_mapping_dialog)
        export_menu.addAction(self.action_export_excel)

        file_menu.addSeparator()

        # 5) Recent Files ▶
        self.recent_menu = file_menu.addMenu("Recent Files ▶")
        self.build_recent_files_menu()
        self.update_recent_files_menu()

        file_menu.addSeparator()

        # 6) Preferences… (stub)
        self.action_preferences = QAction("Preferences…", self)
        self.action_preferences.setShortcut("Ctrl+,")
        self.action_preferences.triggered.connect(self.open_preferences_dialog)
        file_menu.addAction(self.action_preferences)

        # 7) Exit
        self.action_exit = QAction("Exit", self)
        self.action_exit.setShortcut("Ctrl+Q")
        self.action_exit.triggered.connect(self.close)
        file_menu.addAction(self.action_exit)

    def _build_edit_menu(self, menubar):
        edit_menu = menubar.addMenu("Edit")

        # Undo / Redo
        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo)

        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut("Ctrl+Y")
        edit_menu.addAction(redo)

        edit_menu.addSeparator()

        # Clear / Reset
        clear_pins = QAction("❌ Clear All Pins", self)
        clear_pins.triggered.connect(self.clear_all_pins)
        edit_menu.addAction(clear_pins)
        clear_events = QAction("🧼 Clear All Events", self)
        clear_events.triggered.connect(self.clear_current_session)
        edit_menu.addAction(clear_events)

        edit_menu.addSeparator()

        # Customize ▶  (drills down to style tabs)
        customize_menu = edit_menu.addMenu("Customize ▶")
        #  – Axis Titles
        a = QAction("Axis Titles…", self)
        a.setShortcut("Ctrl+Alt+A")
        a.triggered.connect(lambda: self.open_plot_style_editor("axis_tab"))
        customize_menu.addAction(a)
        #  – Tick Labels
        t = QAction("Tick Labels…", self)
        t.setShortcut("Ctrl+Alt+T")
        t.triggered.connect(lambda: self.open_plot_style_editor("tick_tab"))
        customize_menu.addAction(t)
        #  – Event Labels
        e = QAction("Event Labels…", self)
        e.triggered.connect(lambda: self.open_plot_style_editor("event_tab"))
        customize_menu.addAction(e)
        #  – Pinned Labels
        p = QAction("Pinned Labels…", self)
        p.triggered.connect(lambda: self.open_plot_style_editor("pin_tab"))
        customize_menu.addAction(p)
        #  – Trace Style
        l = QAction("Trace Style…", self)
        l.triggered.connect(lambda: self.open_plot_style_editor("line_tab"))
        customize_menu.addAction(l)

        edit_menu.addSeparator()

    def _build_view_menu(self, menubar):
        view_menu = menubar.addMenu("View")

        # 1) Reset / Fit / Zoom
        reset_act = QAction("Reset View", self)
        reset_act.setShortcut("Ctrl+R")
        reset_act.triggered.connect(self.reset_view)
        view_menu.addAction(reset_act)

        fit_act = QAction("Fit to Data", self)
        fit_act.setShortcut("Ctrl+F")
        fit_act.triggered.connect(self.fit_to_data)
        view_menu.addAction(fit_act)

        zoom_sel_act = QAction("Zoom to Selection", self)
        zoom_sel_act.setShortcut("Ctrl+E")
        zoom_sel_act.triggered.connect(self.zoom_to_selection)
        view_menu.addAction(zoom_sel_act)

        view_menu.addSeparator()

        # 2) Annotations ▶
        anno_menu = view_menu.addMenu("Annotations ▶")
        ev_lines = QAction("Event Lines", self, checkable=True, checked=True)
        ev_lbls = QAction("Event Labels", self, checkable=True, checked=True)
        pin_lbls = QAction("Pinned Labels", self, checkable=True, checked=True)
        frame_mk = QAction("Frame Marker", self, checkable=True, checked=True)
        ev_lines.triggered.connect(lambda _: self.toggle_annotation("lines"))
        ev_lbls.triggered.connect(lambda _: self.toggle_annotation("evt_labels"))
        pin_lbls.triggered.connect(lambda _: self.toggle_annotation("pin_labels"))
        frame_mk.triggered.connect(lambda _: self.toggle_annotation("frame_marker"))
        for a in (ev_lines, ev_lbls, pin_lbls, frame_mk):
            anno_menu.addAction(a)

        view_menu.addSeparator()

        # 3) Show / Hide ▶
        showhide = view_menu.addMenu("Show/Hide ▶")
        evt_tbl = QAction("Event Table", self, checkable=True, checked=True)
        snap_vw = QAction("Snapshot Viewer", self, checkable=True, checked=True)
        evt_tbl.triggered.connect(self.toggle_event_table)
        snap_vw.triggered.connect(self.toggle_snapshot_viewer)
        showhide.addAction(evt_tbl)
        showhide.addAction(snap_vw)

        view_menu.addSeparator()

        # 4) Single / Dual
        self.action_single = QAction("Single View", self, checkable=True)
        self.action_dual = QAction("Dual View", self, checkable=True)
        self.action_single.setShortcut("Ctrl+1")
        self.action_dual.setShortcut("Ctrl+2")
        self.action_single.setChecked(True)
        self.action_single.triggered.connect(lambda: self._switch_mode(0))
        self.action_dual.triggered.connect(lambda: self._switch_mode(1))
        view_menu.addAction(self.action_single)
        view_menu.addAction(self.action_dual)

        view_menu.addSeparator()

        # 5) Full‑Screen
        fs_act = QAction("Full‑Screen Mode", self)
        fs_act.setShortcut("F11")
        fs_act.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fs_act)

    def _build_help_menu(self, menubar):
        help_menu = menubar.addMenu("Help")
        # About
        self.action_about = QAction("About VasoAnalyzer", self)
        self.action_about.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "About VasoAnalyzer",
                "VasoAnalyzer 1.6 (Python Edition)\nhttps://github.com/vr-oj/VasoAnalyzer",
            )
        )
        help_menu.addAction(self.action_about)
        # User Manual
        manual_path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "VasoAnalyzer_User_Manual.pdf"
        )
        self.action_user_manual = QAction("Open User Manual", self)
        self.action_user_manual.triggered.connect(
            lambda: os.system(f'open "{manual_path}"')
        )
        help_menu.addAction(self.action_user_manual)

        help_menu.addSeparator()

        # Check for Updates
        act_update = QAction("Check for Updates", self)
        act_update.triggered.connect(self.check_for_updates_at_startup)
        help_menu.addAction(act_update)

        # Keyboard Shortcuts
        act_keys = QAction("Keyboard Shortcuts…", self)
        act_keys.triggered.connect(self.show_shortcuts)
        help_menu.addAction(act_keys)

        # Report a Bug
        act_bug = QAction("Report a Bug…", self)
        act_bug.triggered.connect(
            lambda: webbrowser.open(
                "https://github.com/vr-oj/VasoAnalyzer_2.0/issues/new"
            )
        )
        help_menu.addAction(act_bug)

        # Release Notes
        act_rel = QAction("Release Notes…", self)
        act_rel.triggered.connect(self.show_release_notes)
        help_menu.addAction(act_rel)

    def clear_dual_view(self):
        """
        Clear both DataViewPanelA and DataViewPanelB for dual view.
        """
        # The DualViewWidget instance is `self.dualMode`, so use its `panelA` and `panelB` attributes
        self.dualMode.panelA.clear_data()
        self.dualMode.panelB.clear_data()

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

    def _switch_mode(self, idx):
        self.modeStack.setCurrentIndex(idx)
        self.action_single.setChecked(idx == 0)
        self.action_dual.setChecked(idx == 1)

    def open_preferences_dialog(self):
        QMessageBox.information(
            self, "Preferences", "Preferences will be implemented soon(ish)."
        )

    def clear_all_pins(self):
        for marker, label in self.pinned_points:
            marker.remove()
            label.remove()
        self.pinned_points.clear()
        self.canvas.draw_idle()

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
                "plot_style": (
                    getattr(self, "plot_style_dialog", None).get_style()
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
                    }
                ),
            }

            pickle_path = os.path.join(
                os.path.abspath(self.trace_file_path or "."),
                "tracePlot_output.fig.pickle",
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
        self.main_layout = self.centralWidget().layout()
        item = self.main_layout.takeAt(0)
        if item:
            item.deleteLater()
        self.main_layout.insertLayout(0, top_row_layout)

    def load_recent_files(self):
        settings = QSettings("TykockiLab", "VasoAnalyzer")
        recent = settings.value("recentFiles", [])
        if recent is None:
            recent = []
        self.recent_files = recent

    def check_for_updates_at_startup(self):
        latest = check_for_new_version("v1.6")
        if latest:
            QMessageBox.information(
                self,
                "Update Available",
                f"A new version ({latest}) of VasoAnalyzer is available!\nVisit GitHub to download the latest release.",
            )

    @property
    def trace_loader(self):
        from vasoanalyzer.trace_loader import load_trace

        return load_trace

    @property
    def event_loader(self):
        from vasoanalyzer.event_loader import load_events

        return load_events

    def reset_view(self):
        self.toolbar.home()  # same as the Home button

    def fit_to_data(self):
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def zoom_to_selection(self):
        # if you later add box‐select, you’ll grab the extents here;
        # for now just stub it to full‐data
        self.fit_to_data()

    def toggle_annotation(self, kind: str):
        if kind == "lines":
            for line in self.ax.get_lines():
                if line.get_linestyle() == "--" and line.get_color() == "black":
                    line.set_visible(not line.get_visible())
        elif kind == "evt_labels":
            for txt, _ in self.event_text_objects:
                txt.set_visible(not txt.get_visible())
        elif kind == "pin_labels":
            for marker, lbl in self.pinned_points:
                lbl.set_visible(not lbl.get_visible())
        elif kind == "frame_marker" and self.slider_marker:
            vis = not self.slider_marker.get_visible()
            self.slider_marker.set_visible(vis)
        self.canvas.draw_idle()

    def toggle_event_table(self, checked: bool):
        self.event_table.setVisible(checked)

    def toggle_snapshot_viewer(self, checked: bool):
        self.snapshot_label.setVisible(checked)
        self.slider.setVisible(checked)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.statusBar().show()
        else:
            self.showFullScreen()
            self.menuBar().hide()
            self.statusBar().hide()

    def show_shortcuts(self):
        text = (
            "Ctrl+N: New Analysis\n"
            "Ctrl+O: Open Trace & Events\n"
            "Ctrl+T: Open TIFF…\n"
            "Ctrl+P: Detect Peaks\n"
            "Ctrl+M: Find Minima\n"
            "Ctrl+I: Compute Statistics\n"
            "Ctrl+R: Generate Report\n"
            "Ctrl+Z/Y: Undo/Redo\n"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def show_release_notes(self):
        # You could load a local CHANGELOG.md and display it
        QMessageBox.information(self, "Release Notes", "Release 2.5.1:\n- Foo\n- Bar\n")

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
                background: #FFFFFF; color: black;
                border: 1px solid #CCCCCC; border-radius:6px; padding:6px 12px;
            }
            QPushButton:hover {
                background: #E6F0FF;
            }
            QToolButton {
                background: #FFFFFF; color: black;
                border: 1px solid #CCCCCC; border-radius:6px; padding:6px; margin:2px;
            }
            QToolButton:hover {
                background: #D6E9FF;
            }
            QToolButton:checked {
                background: #CCE5FF; border:1px solid #3399FF;
            }
            QHeaderView::section {
                background: #E0E0E0; font-weight: bold; padding:6px; color:black;
            }
            QTableWidget {
                background: white; gridline-color: #DDDDDD; color: black;
            }
            QTableWidget::item {
                padding:6px; color: black;
            }
        """
        )

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.fig = Figure(figsize=(8, 4), facecolor="white")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMouseTracking(True)
        self.canvas.toolbar = None
        self.ax = self.fig.add_subplot(111)
        # ——— in‑canvas hover annotation ———
        self.hover_annotation = self.ax.annotate(
            text="",
            xy=(0, 0),
            xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=1),
            arrowprops=dict(arrowstyle="->"),
            fontsize=9,
        )
        self.hover_annotation.set_visible(False)
        # ————————————————————————————————
        self.active_canvas = self.canvas
        self.default_main_layout = self.main_layout
        # ===== Initialize Matplotlib Toolbar =====
        self.active_canvas = self.canvas
        self.toolbar = self.build_toolbar_for_canvas(self.active_canvas)
        self.canvas.toolbar = self.toolbar
        self.canvas.setMouseTracking(True)
        self.toolbar.setMouseTracking(True)
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
            # force the toolbar to re‑polish its children under the global QSS
            self.toolbar.style().polish(self.toolbar)
            for btn in self.toolbar.findChildren(QToolButton):
                self.toolbar.style().polish(btn)

            # [Inject] Grid toggle button
            grid_btn = QToolButton()
            grid_btn.setText("Grid")
            grid_btn.setToolTip("Toggle grid visibility")
            grid_btn.setCheckable(True)
            grid_btn.setChecked(self.grid_visible)
            grid_btn.clicked.connect(self.toggle_grid)
            self.toolbar.insertWidget(visible_buttons[7], grid_btn)
            # force the toolbar to re‑polish its children under the global QSS
            self.toolbar.style().polish(self.toolbar)
            for btn in self.toolbar.findChildren(QToolButton):
                self.toolbar.style().polish(btn)

            # [7] Save/export button
            save_btn = visible_buttons[7]
            save_btn.setToolTip("Save As… Export high-res plot")
            save_btn.triggered.disconnect()
            save_btn.triggered.connect(self.export_high_res_plot)
            self.toolbar.style().polish(self.toolbar)
            for btn in self.toolbar.findChildren(QToolButton):
                self.toolbar.style().polish(btn)

        # ===== Unified Top Row: Toolbar + Load Buttons =====
        top_row_layout = QHBoxLayout()
        top_row_layout.setContentsMargins(6, 4, 6, 2)
        top_row_layout.setSpacing(16)

        top_row_layout.addWidget(self.toolbar)

        self.loadTraceBtn = QPushButton("📂 Load Trace + Events")
        self.loadTraceBtn.setToolTip(
            "Load .csv trace file and auto-load matching event table"
        )

        self.loadTraceBtn.clicked.connect(self._handle_load_trace)

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

        self.main_layout.addLayout(top_row_layout)

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
        self.snapshot_label.setFixedSize(500, 300)
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
        self.event_table.setColumnCount(4)
        self.event_table.setHorizontalHeaderLabels(
            ["Event", "Time (s)", "ID (µm)", "Frame"]
        )
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

        self.default_main_layout = self.rebuild_default_main_layout()
        self.main_layout.addLayout(self.default_main_layout)

        # ===== Canvas Interactions =====
        self.canvas.mpl_connect("draw_event", self.update_event_label_positions)
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)
        self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
        self.canvas.mpl_connect("button_press_event", self.handle_click_on_plot)
        self.canvas.mpl_connect(
            "button_release_event",
            lambda event: QTimer.singleShot(100, lambda: self.on_mouse_release(event)),
        )
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)

    def build_toolbar_for_canvas(self, canvas):
        toolbar = NavigationToolbar(canvas, self)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setStyleSheet(
            """
            QToolBar {
                background-color: #F0F0F0;
                padding: 2px;
                border: none;
            }
        """
        )

        # Remove blank actions
        if hasattr(toolbar, "coordinates"):
            toolbar.coordinates = lambda *args, **kwargs: None
            for act in toolbar.actions():
                if isinstance(act, QAction) and act.text() == "":
                    toolbar.removeAction(act)

        visible_buttons = [a for a in toolbar.actions() if not a.icon().isNull()]
        if len(visible_buttons) >= 8:
            visible_buttons[0].setToolTip("Home: Reset zoom and pan")
            visible_buttons[1].setToolTip("Back: Previous view")
            visible_buttons[2].setToolTip("Forward: Next view")
            visible_buttons[3].setToolTip("Pan: Click and drag plot")
            visible_buttons[4].setToolTip("Zoom: Draw box to zoom in")

            layout_btn = visible_buttons[5]
            layout_btn.setToolTip("Configure subplot layout")
            layout_btn.triggered.disconnect()
            layout_btn.triggered.connect(toolbar.configure_subplots)

            axes_btn = visible_buttons[6]
            axes_btn.setToolTip("Edit axis ranges and titles")
            axes_btn.triggered.disconnect()
            axes_btn.triggered.connect(toolbar.edit_parameters)

            # Inject custom "Aa" button
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
            toolbar.insertWidget(visible_buttons[7], style_btn)

            # Inject grid toggle
            grid_btn = QToolButton()
            grid_btn.setText("Grid")
            grid_btn.setToolTip("Toggle grid visibility")
            grid_btn.setCheckable(True)
            grid_btn.setChecked(self.grid_visible)
            grid_btn.clicked.connect(self.toggle_grid)
            toolbar.insertWidget(visible_buttons[7], grid_btn)

            # Override Save
            save_btn = visible_buttons[7]
            save_btn.setToolTip("Save As… Export high-res plot")
            save_btn.triggered.disconnect()
            save_btn.triggered.connect(self.export_high_res_plot)

        return toolbar

        # Add context menu to snapshot label
        self.snapshot_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.snapshot_label.customContextMenuRequested.connect(
            self.show_snapshot_context_menu
        )

    def show_snapshot_context_menu(self, pos):
        if not hasattr(self, "snapshot_frames") or not self.snapshot_frames:
            return

        menu = QMenu(self)
        view_metadata_action = menu.addAction("📋 View Frame Metadata")
        view_metadata_action.triggered.connect(self.show_current_frame_metadata)

        menu.exec_(self.snapshot_label.mapToGlobal(pos))

    # [D] ========================= FILE LOADERS: TRACE / EVENTS / TIFF =====================
    def load_trace_and_events(self, file_path=None):
        # 1) Prompt for CSV if needed
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Trace File", "", "CSV Files (*.csv)"
            )
            if not file_path:
                return

        # 2) Load the trace
        try:
            self.trace_data = load_trace(file_path)
            self.trace_file_path = os.path.dirname(file_path)
            trace_filename = os.path.basename(file_path)
            self.trace_file_label.setText(f"🧪 {trace_filename}")
        except Exception as e:
            QMessageBox.critical(
                self, "Trace Load Error", f"Failed to load trace file:\n{e}"
            )
            return

        # 3) Remember in Recent Files
        if file_path not in self.recent_files:
            self.recent_files = [file_path] + self.recent_files[:4]
            self.settings.setValue("recentFiles", self.recent_files)
            self.update_recent_files_menu()

        # 4) Load the matching events CSV (if it exists)
        base = os.path.splitext(os.path.basename(file_path))[0]
        event_path = os.path.join(self.trace_file_path, f"{base}_table.csv")
        if os.path.exists(event_path):
            try:
                self.event_labels, self.event_times, _ = load_events(event_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Event Load Error",
                    f"Trace loaded, but failed to load events:\n{e}",
                )
                self.event_labels = []
                self.event_times = []
        else:
            QMessageBox.information(
                self,
                "Event File Not Found",
                f"No matching event file:\n{base}_table.csv",
            )
            self.event_labels = []
            self.event_times = []

        # 5) Build event_table_data purely from trace times & diameters
        self.event_table_data = []
        if self.event_times:
            times = self.trace_data["Time (s)"].values
            diam = self.trace_data["Inner Diameter"].values
            for i, t_evt in enumerate(self.event_times):
                # sample diameter at the event time
                idx_evt = int(np.argmin(np.abs(times - t_evt)))
                diam_evt = float(diam[idx_evt])
                self.event_table_data.append(
                    (
                        self.event_labels[i],
                        round(t_evt, 2),
                        idx_evt,
                        round(diam_evt, 2),
                    )
                )

        # 6) Refresh the UI
        self.update_plot()  # draws trace + event lines
        self.populate_table()  # populates the QTableWidget
        self.excel_btn.setEnabled(bool(self.event_table_data))
        self.update_scroll_slider()  # shows or hides the pan‑slider
        self.style_event_table()

    def populate_table_widget(self, table_widget, data):
        table_widget.setRowCount(len(data))
        for row, (label, t, d) in enumerate(data):
            table_widget.setItem(row, 0, QTableWidgetItem(str(label)))
            table_widget.setItem(row, 1, QTableWidgetItem(str(t)))
            table_widget.setItem(row, 2, QTableWidgetItem(str(d)))
            self.style_event_table()

    def populate_table(self):
        self.event_table.blockSignals(True)
        self.event_table.setRowCount(len(self.event_table_data))
        for row, (label, t, idval, frame) in enumerate(self.event_table_data):
            self.event_table.setItem(row, 0, QTableWidgetItem(str(label)))
            self.event_table.setItem(row, 1, QTableWidgetItem(str(t)))
            self.event_table.setItem(row, 2, QTableWidgetItem(str(idval)))
            self.event_table.setItem(row, 3, QTableWidgetItem(str(frame)))
        self.event_table.blockSignals(False)
        self.style_event_table()

    def style_event_table(self):
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)

        for col in range(self.event_table.columnCount()):
            header_item = self.event_table.horizontalHeaderItem(col)
            header_item.setFont(header_font)
            header_item.setBackground(QBrush(QColor("#D3D3D3")))

        for row in range(self.event_table.rowCount()):
            row_color = QColor("#FFFFFF") if row % 2 == 0 else QColor("#F0F0F0")
            for col in range(self.event_table.columnCount()):
                item = self.event_table.item(row, col)
                if item:
                    item.setBackground(QBrush(row_color))

    def load_snapshot(self):
        # 1) Prompt for TIFF
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if not file_path:
            return

        try:
            # 2) Load all frames + metadata
            frames, metadata = load_tiff(file_path)

            # 3) Filter out empty/corrupt frames
            valid_frames, valid_meta = [], []
            for i, frame in enumerate(frames):
                if frame is not None and frame.size > 0:
                    valid_frames.append(frame)
                    valid_meta.append(metadata[i] if i < len(metadata) else {})

            if len(valid_frames) < len(frames):
                QMessageBox.warning(
                    self, "TIFF Warning", "Skipped empty or corrupted TIFF frames."
                )

            self.snapshot_frames = valid_frames
            self.frames_metadata = valid_meta

            # 4) Build a time‑array for each frame
            self.frame_times = []
            for idx, meta in enumerate(self.frames_metadata):
                # use FrameTime tag if present, else uniform interval
                self.frame_times.append(
                    meta.get("FrameTime", idx * self.recording_interval)
                )

            # 5) Initialize the image viewer & slider
            self.display_frame(0)
            self.slider.setMinimum(0)
            self.slider.setMaximum(len(self.snapshot_frames) - 1)
            self.slider.setValue(0)
            self.snapshot_label.show()
            self.slider.show()

            # 6) Reset the red‑line marker so next scroll redraws it
            self.slider_marker = None

        except Exception as e:
            QMessageBox.critical(self, "TIFF Load Error", f"Failed to load TIFF:\n{e}")

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "Vaso Projects (*.vaso)"
        )
        if not path:
            return
        if not path.endswith(".vaso"):
            path += ".vaso"
        try:
            with h5py.File(path, "w") as f:
                grp = f.create_group("trace")
                if self.trace_data is not None:
                    grp.create_dataset("time", data=self.trace_data["Time (s)"].values)
                    grp.create_dataset(
                        "diameter", data=self.trace_data["Inner Diameter"].values
                    )
                ev = f.create_group("events")
                labels = np.array([row[0] for row in self.event_table_data], dtype="S")
                ev.create_dataset("labels", data=labels)
                diam_b = [row[3] for row in self.event_table_data]
                ev.create_dataset("diam_before", data=diam_b)
                if self.snapshot_frames:
                    f.create_dataset(
                        "snapshots/frames",
                        data=np.stack(self.snapshot_frames),
                        compression="gzip",
                    )
                style = {
                    "xlim": self.ax.get_xlim(),
                    "ylim": self.ax.get_ylim(),
                    "xscale": self.ax.get_xscale(),
                    "yscale": self.ax.get_yscale(),
                    "lines": [line.properties() for line in self.ax.get_lines()],
                    "table_fontsize": self.event_table.font().pointSize(),
                    "current_frame_idx": self.current_frame,
                }
                pdata = pickle.dumps(style)
                f.create_dataset(
                    "style_meta",
                    data=np.frombuffer(pdata, dtype="uint8"),
                    dtype="uint8",
                )
                f.attrs["app_version"] = APP_VERSION
                f.attrs["saved_on"] = datetime.now().isoformat()
                f.attrs["current_frame_idx"] = self.current_frame
            QMessageBox.information(self, "Save Project", f"Saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Vaso Projects (*.vaso)"
        )
        if not path:
            return
        try:
            with h5py.File(path, "r") as f:
                t = f["trace/time"][...]
                d = f["trace/diameter"][...]
                labels = [s.decode() for s in f["events/labels"][...]]
                diam_before = f["events/diam_before"][...]
                stack = f["snapshots/frames"][...] if "snapshots/frames" in f else None
                raw = f["style_meta"][...].tobytes()
                style = pickle.loads(raw)
                idx = f.attrs.get("current_frame_idx", 0)
            self.load_trace(t, d)
            self.load_events(labels, diam_before)
            if stack is not None:
                self.load_snapshots(stack)
            self.apply_style(style)
            self.set_current_frame(idx)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def load_trace(self, t, d):
        import pandas as pd

        self.trace_data = pd.DataFrame({"Time (s)": t, "Inner Diameter": d})
        self.update_plot()
        self.update_scroll_slider()

    def load_events(self, labels, diam_before):
        self.event_labels = list(labels)
        self.event_table_data = []
        for lbl, diam in zip(labels, diam_before):
            self.event_table_data.append((lbl, 0.0, 0, diam))
        self.populate_table()

    def load_snapshots(self, stack):
        self.snapshot_frames = [frame for frame in stack]
        if self.snapshot_frames:
            self.slider.setMinimum(0)
            self.slider.setMaximum(len(self.snapshot_frames) - 1)
            self.slider.setValue(0)
            self.display_frame(0)

    def apply_style(self, style):
        self.ax.set_xlim(*style.get("xlim", self.ax.get_xlim()))
        self.ax.set_ylim(*style.get("ylim", self.ax.get_ylim()))
        self.ax.set_xscale(style.get("xscale", self.ax.get_xscale()))
        self.ax.set_yscale(style.get("yscale", self.ax.get_yscale()))
        font = self.event_table.font()
        font.setPointSize(style.get("table_fontsize", font.pointSize()))
        self.event_table.setFont(font)
        self.canvas.draw_idle()

    def set_current_frame(self, idx):
        if not self.snapshot_frames:
            return
        idx = int(idx)
        self.current_frame = idx
        self.slider.setValue(idx)
        self.display_frame(idx)
        self.update_slider_marker()

    def show_current_frame_metadata(self):
        """Show metadata for the currently displayed frame"""
        if not hasattr(self, "frames_metadata") or not self.frames_metadata:
            QMessageBox.information(
                self, "Metadata", "No metadata available for this TIFF file."
            )
            return

        current_idx = self.slider.value()
        if current_idx >= len(self.frames_metadata):
            QMessageBox.information(
                self, "Metadata", "No metadata available for this frame."
            )
            return

        # Get metadata for current frame
        metadata = self.frames_metadata[current_idx]

        # Format metadata as text
        metadata_text = f"Frame {current_idx} Metadata:\n" + "-" * 40 + "\n"

        # Sort keys alphabetically for consistent display
        for key in sorted(metadata.keys()):
            value = metadata[key]
            # Handle arrays specially to avoid overwhelming the display
            if isinstance(value, (list, tuple, np.ndarray)) and len(str(value)) > 100:
                metadata_text += f"{key}: [Array with shape {np.array(value).shape}]\n"
            else:
                metadata_text += f"{key}: {value}\n"

        # Show dialog with metadata
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Frame {current_idx} Metadata")
        msg.setText(metadata_text)
        msg.setDetailedText(str(metadata))  # Full metadata in detailed view
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setIcon(QMessageBox.Information)

        # Make the dialog bigger
        msg.setStyleSheet("QLabel{min-width: 500px; min-height: 400px;}")

        msg.exec_()

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
        # Add a small indicator that shows metadata is available
        if hasattr(self, "metadata_btn") and idx < len(self.frames_metadata):
            num_tags = len(self.frames_metadata[idx])
            self.metadata_btn.setText(f"📋 View Metadata ({num_tags} tags)")

    def update_slider_marker(self):
        # Make sure we have a trace and some TIFF frames
        if self.trace_data is None or not self.snapshot_frames:
            return

        # 1) Get the current slider index
        idx = self.slider.value()

        # 2) Convert index → time (seconds)
        t_current = idx * self.recording_interval

        # 3) Draw or move the red line at that time
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

        # 4) Refresh the plot
        self.canvas.draw_idle()

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

    def update_event_label_positions(self, event=None):
        if not hasattr(self, "event_text_objects") or not self.event_text_objects:
            return

        y_min, y_max = self.ax.get_ylim()
        y_top = min(y_max - 5, y_max * 0.95)

        for txt, x in self.event_text_objects:
            txt.set_position((x, y_top))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().endswith(".fig.pickle"):
                    event.accept()
                    return
        event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        idx = self.modeStack.currentIndex()

        # SINGLE‑VIEW: unchanged
        if idx == 0:
            for p in paths:
                if p.endswith(".fig.pickle"):
                    self.load_pickle_session(p)
            return

        # DUAL‑VIEW: expect exactly two pickles
        panels = [self.dualMode.panelA, self.dualMode.panelB]
        for i, p in enumerate(paths[:2]):
            if p.endswith(".fig.pickle"):
                panels[i].load_pickle_session(p)

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
            self.trace_file_label.setText(
                f"Restored from: {os.path.basename(file_path)}"
            )
            self.statusBar().showMessage("Session restored successfully.")
            print("✅ Session reloaded with full metadata.")

        except Exception as e:
            QMessageBox.critical(self, "Load Failed", f"Error loading session:\n{e}")

    def _handle_load_trace(self):
        # Prompt for the trace file
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return

        # SINGLE‑VIEW: just forward to your existing method
        if self.modeStack.currentIndex() == 0:
            self.load_trace_and_events(file_path)
            return

        # DUAL‑VIEW: decide which panel
        from PyQt5.QtWidgets import QMessageBox

        choice = QMessageBox.question(
            self,
            "Load Into…",
            "Load this dataset into Panel A?\n(Select No to load into Panel B.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        panel = (
            self.dualMode.panelA if choice == QMessageBox.Yes else self.dualMode.panelB
        )

        # Load the trace DataFrame
        df = load_trace(file_path)

        # Attempt to find matching events file
        base = os.path.splitext(os.path.basename(file_path))[0]
        ev_path = os.path.join(os.path.dirname(file_path), f"{base}_table.csv")
        events = []
        if os.path.exists(ev_path):
            try:
                labels, times, _ = load_events(ev_path)
                events = list(zip(labels, times))
            except:
                pass

        # Feed into the chosen panel
        panel.load_trace_and_events(df, events)

    # [E] ========================= PLOTTING AND EVENT SYNC ============================
    def update_plot(self):
        if self.trace_data is None:
            return

        # clear everything (old lines, texts, etc)
        self.ax.clear()

        # re‑create the in‑canvas hover annotation on this fresh axes
        self.hover_annotation = self.ax.annotate(
            text="",
            xy=(0, 0),
            xytext=(6, 6),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc=(1, 1, 1, 0.85), ec="#888888", lw=1),
            arrowprops=dict(arrowstyle="->"),
            fontsize=12,
        )
        self.hover_annotation.set_visible(False)

        self.ax.set_facecolor("white")
        self.ax.tick_params(colors="black")
        self.ax.xaxis.label.set_color("black")
        self.ax.yaxis.label.set_color("black")
        self.ax.title.set_color("black")
        self.event_text_objects = []

        # Plot trace and keep a handle for .contains()
        t = self.trace_data["Time (s)"]
        d = self.trace_data["Inner Diameter"]
        (self.trace_line,) = self.ax.plot(t, d, "k-", linewidth=1.5)
        self.ax.set_xlabel("Time (s or frames)")
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
                # compute where the event falls on your time axis
                idx_ev = int(np.argmin(np.abs(time_trace - self.event_times[i])))
                diam_at_ev = diam_trace.iloc[idx_ev]

                # sample just before next event (or at end)
                if i < nEv - 1:
                    t_sample = self.event_times[i + 1] - offset_sec
                    idx_pre = int(np.argmin(np.abs(time_trace - t_sample)))
                else:
                    idx_pre = -1
                diam_pre = diam_trace.iloc[idx_pre]

                # use idx_ev as the “frame number” for plotting
                frame_number = idx_ev

                # draw the vertical line at the event time
                self.ax.axvline(
                    x=self.event_times[i], color="black", linestyle="--", linewidth=0.8
                )

                # place the text at the same time coordinate
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

                # populate your table row
                self.event_table_data.append(
                    (
                        self.event_labels[i],
                        round(self.event_times[i], 2),
                        frame_number,  # now the idx_ev
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
        for row, (label, t, frame, d) in enumerate(self.event_table_data):
            self.event_table.setItem(row, 0, QTableWidgetItem(str(label)))
            self.event_table.setItem(row, 1, QTableWidgetItem(str(t)))
            self.event_table.setItem(row, 2, QTableWidgetItem(str(d)))
        self.event_table.blockSignals(False)

    def handle_table_edit(self, item):
        row = item.row()
        col = item.column()

        # Only allow editing the third column (ID)
        if col != 3:
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
        frame = self.event_table_data[row][2]  # Get the frame value
        old_val = self.event_table_data[row][3]  # Changed from index 2 to 3

        old_val = self.event_table_data[row][3]
        cmd = ReplaceEventCommand(self, row, old_val, round(new_val, 2))
        self.undo_stack.push(cmd)
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

    # [F2] ===================== TABLE B MANAGEMENT =========================

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
                old_value = self.event_table_data[index][3]
                new_value = round(y, 2)
                cmd = ReplaceEventCommand(self, index, old_value, new_value)
                self.undo_stack.push(cmd)

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

        # Calculate frame number based on time
        frame_number = int(x / self.recording_interval)

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

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
    def update_hover_label(self, event):
        # only over the main axes and with data loaded
        if event.inaxes != self.ax or self.trace_data is None:
            if self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        # show only when cursor is actually on the line
        contains, info = self.trace_line.contains(event)
        if not contains:
            if self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        # get the exact index & value
        idx = info["ind"][0]
        times = self.trace_data["Time (s)"].values
        diams = self.trace_data["Inner Diameter"].values
        x_near, y_near = times[idx], diams[idx]

        # update and show the annotation
        self.hover_annotation.xy = (x_near, y_near)
        self.hover_annotation.set_text(f"{x_near:.2f}s\n{y_near:.2f}µm")
        self.hover_annotation.set_visible(True)
        self.canvas.draw_idle()

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

    def open_plot_style_editor_for(
        self, ax, canvas, event_text_objects=None, pinned_points=None
    ):
        dialog = PlotStyleDialog(self)
        prev_style = dialog.get_style()

        def apply_local_style():
            style = dialog.get_style()
            # Apply style to the specified axis, not globally
            ax.xaxis.label.set_fontsize(style["axis_font_size"])
            ax.xaxis.label.set_fontname(style["axis_font_family"])
            ax.xaxis.label.set_fontstyle("italic" if style["axis_italic"] else "normal")
            ax.xaxis.label.set_fontweight("bold" if style["axis_bold"] else "normal")
            ax.yaxis.label.set_fontsize(style["axis_font_size"])
            ax.yaxis.label.set_fontname(style["axis_font_family"])
            ax.yaxis.label.set_fontstyle("italic" if style["axis_italic"] else "normal")
            ax.yaxis.label.set_fontweight("bold" if style["axis_bold"] else "normal")
            ax.tick_params(axis="x", labelsize=style["tick_font_size"])
            ax.tick_params(axis="y", labelsize=style["tick_font_size"])

            if event_text_objects:
                for txt, _ in event_text_objects:
                    txt.set_fontsize(style["event_font_size"])
                    txt.set_fontname(style["event_font_family"])
                    txt.set_fontstyle("italic" if style["event_italic"] else "normal")
                    txt.set_fontweight("bold" if style["event_bold"] else "normal")

            if pinned_points:
                for marker, label in pinned_points:
                    marker.set_markersize(style["pin_size"])
                    label.set_fontsize(style["pin_font_size"])
                    label.set_fontname(style["pin_font_family"])
                    label.set_fontstyle("italic" if style["pin_italic"] else "normal")
                    label.set_fontweight("bold" if style["pin_bold"] else "normal")

            if ax.lines:
                ax.lines[0].set_linewidth(style["line_width"])

            canvas.draw_idle()

        # Inject the apply method into the dialog
        dialog.apply_callback = apply_local_style

        if dialog.exec_():
            dialog.apply_callback()
        else:
            # Optional: revert or keep previous style
            pass

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
        self.scroll_slider.setValue(0)
        self.scroll_slider.hide()

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
                "axis_font_size": 16,
                "axis_font_family": "Arial",
                "axis_bold": False,
                "axis_italic": False,
                "tick_font_size": 10,
                "event_font_size": 11,
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

    def rebuild_default_main_layout(self):
        # Rebuild left layout (plot + slider)
        plot_layout = QVBoxLayout()
        plot_layout.setContentsMargins(6, 0, 6, 6)
        plot_layout.setSpacing(4)
        plot_layout.addWidget(self.canvas)
        plot_layout.addWidget(self.scroll_slider)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(0)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(plot_layout)

        # Rebuild right layout (snapshot + table)
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

        # Combine left + right into top layout
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addLayout(left_layout, 4)
        top_layout.addLayout(right_layout, 1)

        return top_layout

    # [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
    def auto_export_table(self):
        if not self.trace_file_path:
            print("⚠️ No trace path set. Cannot export event table.")
            return

        try:
            output_dir = os.path.abspath(self.trace_file_path)
            csv_path = os.path.join(output_dir, "eventDiameters_output.csv")
            df = pd.DataFrame(
                self.event_table_data, columns=["Event", "Time (s)", "Frame", "ID (µm)"]
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

        # Format the data as dictionaries with all four fields
        dialog_data = [
            {"EventLabel": label, "Time (s)": time, "Frame": frame, "ID (µm)": idval}
            for label, time, frame, idval in self.event_table_data
        ]

        dialog = ExcelMappingDialog(self, dialog_data)
        if dialog.exec_():
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
    QFormLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QSpinBox,
    QCheckBox,
)


class PlotStyleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setMinimumWidth(400)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)

        # Bottom row: Apply All / Cancel / OK
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.apply_all_btn = QPushButton("Apply")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("OK")
        btn_row.addWidget(self.apply_all_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        main_layout.addLayout(btn_row)

        # Connect them
        self.apply_all_btn.clicked.connect(self.handle_apply_all)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)

        # Create each tab
        self._init_axis_tab()
        self._init_tick_tab()
        self._init_event_tab()
        self._init_pin_tab()
        self._init_line_tab()

    def handle_apply_all(self):
        """Apply *all* settings at once."""
        style = self.get_style()
        self.parent().apply_plot_style(style)

    def handle_apply_tab(self, section):
        """Apply only one section (axis/tick/event/pin/line)."""
        style = self.get_style()
        parent = self.parent()
        if section == "axis":
            # Axis titles
            parent.ax.xaxis.label.set_fontsize(style["axis_font_size"])
            parent.ax.xaxis.label.set_fontname(style["axis_font_family"])
            parent.ax.xaxis.label.set_fontweight(
                "bold" if style["axis_bold"] else "normal"
            )
            parent.ax.xaxis.label.set_fontstyle(
                "italic" if style["axis_italic"] else "normal"
            )
            parent.ax.yaxis.label.set_fontsize(style["axis_font_size"])
            parent.ax.yaxis.label.set_fontname(style["axis_font_family"])
            parent.ax.yaxis.label.set_fontweight(
                "bold" if style["axis_bold"] else "normal"
            )
            parent.ax.yaxis.label.set_fontstyle(
                "italic" if style["axis_italic"] else "normal"
            )

        elif section == "tick":
            # Tick labels
            parent.ax.tick_params(axis="x", labelsize=style["tick_font_size"])
            parent.ax.tick_params(axis="y", labelsize=style["tick_font_size"])

        elif section == "event":
            # Event labels
            for txt, _ in parent.event_text_objects:
                txt.set_fontsize(style["event_font_size"])
                txt.set_fontname(style["event_font_family"])
                txt.set_fontweight("bold" if style["event_bold"] else "normal")
                txt.set_fontstyle("italic" if style["event_italic"] else "normal")

        elif section == "pin":
            # Pinned labels
            for marker, label in parent.pinned_points:
                marker.set_markersize(style["pin_size"])
                label.set_fontsize(style["pin_font_size"])
                label.set_fontname(style["pin_font_family"])
                label.set_fontweight("bold" if style["pin_bold"] else "normal")
                label.set_fontstyle("italic" if style["pin_italic"] else "normal")

        elif section == "line":
            # Trace line
            if parent.ax.lines:
                parent.ax.lines[0].set_linewidth(style["line_width"])

        parent.canvas.draw_idle()

    def _make_section_widgets(self, section):
        """Helper: create section's Apply/Default row."""
        h = QHBoxLayout()
        h.addStretch()
        apply_btn = QPushButton("Apply")
        default_btn = QPushButton("Default")
        apply_btn.clicked.connect(lambda _, sec=section: self.handle_apply_tab(sec))
        default_btn.clicked.connect(lambda _, sec=section: self.reset_defaults(sec))
        h.addWidget(apply_btn)
        h.addWidget(default_btn)
        return h

    def _init_axis_tab(self):
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
        layout.addLayout(self._make_section_widgets("axis"))
        self.tabs.addTab(tab, "Axis Titles")

    def _init_tick_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.tick_font_size = QSpinBox()
        self.tick_font_size.setRange(6, 32)
        self.tick_font_size.setValue(12)
        form.addRow("Tick Font Size:", self.tick_font_size)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("tick"))
        self.tabs.addTab(tab, "Tick Labels")

    def _init_event_tab(self):
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
        layout.addLayout(self._make_section_widgets("event"))
        self.tabs.addTab(tab, "Event Labels")

    def _init_pin_tab(self):
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
        layout.addLayout(self._make_section_widgets("pin"))
        self.tabs.addTab(tab, "Pinned Labels")

    def _init_line_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.line_width = QSpinBox()
        self.line_width.setRange(1, 10)
        self.line_width.setValue(2)
        form.addRow("Line Width:", self.line_width)
        layout.addLayout(form)
        layout.addLayout(self._make_section_widgets("line"))
        self.tabs.addTab(tab, "Trace Style")

    def reset_defaults(self, section):
        defaults = {
            "axis": {
                "axis_font_size": 14,
                "axis_font_family": "Arial",
                "axis_bold": False,
                "axis_italic": False,
            },
            "tick": {"tick_font_size": 12},
            "event": {
                "event_font_size": 10,
                "event_font_family": "Arial",
                "event_bold": False,
                "event_italic": False,
            },
            "pin": {
                "pin_font_size": 10,
                "pin_font_family": "Arial",
                "pin_bold": False,
                "pin_italic": False,
                "pin_size": 6,
            },
            "line": {"line_width": 2},
        }
        for attr, val in defaults[section].items():
            widget = getattr(self, attr)
            if isinstance(widget, QSpinBox):
                widget.setValue(val)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(val)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(val)

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


class ReplaceEventCommand(QUndoCommand):
    def __init__(self, app, index, old_val, new_val):
        super().__init__(f"Replace Event #{index}")
        self.app = app
        self.i = index
        self.old = old_val
        self.new = new_val

    def redo(self):
        lbl, t, frame, _ = self.app.event_table_data[self.i]
        self.app.event_table_data[self.i] = (lbl, t, frame, self.new)
        self.app.populate_table()
        self.app.auto_export_table()

    def undo(self):
        lbl, t, frame, _ = self.app.event_table_data[self.i]
        self.app.event_table_data[self.i] = (lbl, t, frame, self.old)
        self.app.populate_table()
        self.app.auto_export_table()
