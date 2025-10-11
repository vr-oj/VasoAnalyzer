# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# [A] ========================= IMPORTS AND GLOBAL CONFIG ============================
import sys, os, json, webbrowser, html, copy, io
from pathlib import Path
import numpy as np, pandas as pd, tifffile
import logging
from datetime import datetime
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QApplication
from utils.config import APP_VERSION
from functools import partial
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib import rcParams
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QPushButton,
    QFileDialog,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QSlider,
    QLabel,
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
    QDockWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
    QStyle,
    QScrollArea,
    QComboBox,
)

from PyQt5.QtGui import (
    QPixmap,
    QImage,
    QIcon,
    QCursor,
    QPainter,
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QDesktopServices,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QSize,
    QSettings,
    QEvent,
    QUrl,
    QObject,
    QRunnable,
    QThreadPool,
    pyqtSignal,
)
from PyQt5.QtSvg import QSvgWidget
from typing import Optional, List, Tuple, Dict, Any, Sequence

from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.io.tiffs import load_tiff, load_tiff_preview
from vasoanalyzer.io.events import load_events, find_matching_event_file
from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.ui.dialogs.excel_mapping_dialog import update_excel_file
from vasoanalyzer.ui.theme import (
    CURRENT_THEME,
    apply_light_theme,
    css_rgba_to_mpl,
)
import vasoanalyzer.core.project as project_module
from vasoanalyzer.core.project import (
    Attachment,
    Project,
    Experiment,
    SampleN,
    export_sample,
    save_project,
    load_project,
)
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.services.project_service import (
    save_project_file,
    autosave_project,
    pending_autosave_path,
    restore_autosave,
    export_project_bundle,
    import_project_bundle,
)
from vasoanalyzer.services.cache_service import DataCache, cache_dir_for_project
from vasoanalyzer.ui.dialogs.axis_settings_dialog import AxisSettingsDialog
from vasoanalyzer.ui.dialogs.legend_settings_dialog import LegendSettingsDialog
from vasoanalyzer.ui.dialogs.plot_style_editor import PlotStyleEditor
from vasoanalyzer.ui.dialogs.subplot_layout_dialog import SubplotLayoutDialog
from vasoanalyzer.ui.dialogs.unified_settings_dialog import (
    UnifiedPlotSettingsDialog,
)
from vasoanalyzer.ui.dialogs.relink_dialog import MissingAsset, RelinkDialog
from vasoanalyzer.ui.commands import ReplaceEventCommand, PointEditCommand
from vasoanalyzer.ui.point_editor_session import PointEditorSession, SessionSummary
from vasoanalyzer.ui.point_editor_view import PointEditorDialog

log = logging.getLogger(__name__)

from .constants import PREVIOUS_PLOT_PATH, DEFAULT_STYLE

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.core.audit import serialize_edit_log
from vasoanalyzer.ui.plot_core import PlotHost
from vasoanalyzer.ui.interactions import InteractionController
from vasoanalyzer.ui.zoom_window import ZoomWindowDock
from vasoanalyzer.ui.scope_view import ScopeDock
from vasoanalyzer.ui.tracks import ChannelTrackSpec
from vasoanalyzer.ui.overlays import AnnotationSpec

from .widgets import CustomToolbar
from .plotting import auto_export_editable_plot, export_high_res_plot, toggle_grid
from .project_management import (
    save_data_as_n,
    show_save_menu,
    open_excel_mapping_dialog,
)
from .dialogs.welcome_dialog import WelcomeGuideDialog
from .dialogs.new_project_dialog import NewProjectDialog
from .metadata_panel import MetadataDock
from .update_checker import UpdateChecker
from .event_table import EventTableWidget
from .event_table_controller import EventTableController
from .style_manager import PlotStyleManager


class _StyleHolder:
    def __init__(self, style):
        self._style = style

    def get_style(self):
        return self._style

    def set_style(self, style):
        self._style = style


class _SampleLoadSignals(QObject):
    finished = pyqtSignal(object, object, object, object, object)
    error = pyqtSignal(object, object, str)


class _SampleLoadJob(QRunnable):
    """Background job that materialises trace/events/results for a sample."""

    def __init__(
        self,
        project_path: str,
        sample: SampleN,
        token: object,
        *,
        load_trace: bool,
        load_events: bool,
        load_results: bool,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = _SampleLoadSignals()
        self._project_path = project_path
        self._sample = sample
        self._token = token
        self._load_trace = load_trace
        self._load_events = load_events
        self._load_results = load_results
        self._dataset_id = sample.dataset_id

    def run(self) -> None:  # type: ignore[override]
        trace_df = None
        events_df = None
        analysis_results = None

        if self._dataset_id is None:
            self.signals.finished.emit(self._token, self._sample, None, None, None)
            return

        try:
            store = sqlite_store.open_project(self._project_path)
            try:
                if self._load_trace:
                    trace_raw = sqlite_store.get_trace(store, self._dataset_id)
                    trace_df = project_module._format_trace_df(trace_raw)
                if self._load_events:
                    events_raw = sqlite_store.get_events(store, self._dataset_id)
                    events_df = project_module._format_events_df(events_raw)
                if self._load_results:
                    analysis_results = project_module._load_sample_results(
                        store, self._dataset_id
                    )
            finally:
                store.close()
        except Exception as exc:  # pragma: no cover - defensive UI logging
            self.signals.error.emit(self._token, self._sample, str(exc))
            return

        self.signals.finished.emit(
            self._token, self._sample, trace_df, events_df, analysis_results
        )


class _MissingAssetScanSignals(QObject):
    finished = pyqtSignal(object, object)
    error = pyqtSignal(object, str)


class _MissingAssetScanJob(QRunnable):
    """Scan project links off the main thread."""

    def __init__(self, project: Project, token: object) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._project = project
        self._token = token
        self.signals = _MissingAssetScanSignals()

    def run(self) -> None:  # type: ignore[override]
        try:
            payload = _collect_missing_assets(self._project)
        except Exception as exc:  # pragma: no cover - defensive UI logging
            self.signals.error.emit(self._token, str(exc))
            return
        self.signals.finished.emit(self._token, payload)


def _collect_missing_assets(project: Project) -> tuple[list[MissingAsset], list[str]]:
    missing: list[MissingAsset] = []
    project_missing: list[str] = []

    base_dir = Path(project.path).resolve().parent if project.path else Path.cwd()

    def _resolve(candidate: Optional[str]) -> Optional[Path]:
        if not candidate:
            return None
        path_obj = Path(candidate)
        if not path_obj.is_absolute():
            path_obj = base_dir / path_obj
        return path_obj

    for experiment in project.experiments:
        for sample in experiment.samples:
            for kind, label in (("trace", "Trace"), ("events", "Events")):
                current_path = getattr(sample, f"{kind}_path", None)
                resolved = _resolve(current_path)
                if current_path and (resolved is None or not resolved.exists()):
                    missing.append(
                        MissingAsset(
                            sample=sample,
                            kind=kind,
                            label=f"{sample.name} · {label}",
                            current_path=current_path,
                            relative=getattr(sample, f"{kind}_relative", None),
                            hint=getattr(sample, f"{kind}_hint", None),
                            signature=getattr(sample, f"{kind}_signature", None),
                        )
                    )

    for attachment in project.attachments or []:
        candidate = attachment.data_path or attachment.source_path
        resolved = _resolve(candidate)
        if candidate and (resolved is None or not resolved.exists()):
            label = attachment.name or attachment.filename or "Attachment"
            project_missing.append(f"{label} ({candidate})")

    return missing, project_missing


ONBOARDING_SETTINGS_ORG = "VasoAnalyzer"
ONBOARDING_SETTINGS_APP = "VasoAnalyzer"

LEGEND_LABEL_DEFAULTS = {
    "inner": "Inner diameter (µm)",
    "outer": "Outer diameter (µm)",
}

DEFAULT_LEGEND_SETTINGS = {
    "visible": True,
    "location": "upper right",
    "frame_on": False,
    "font_family": "",
    "font_size": 9,
    "font_bold": False,
    "font_italic": False,
    "ncol": 1,
    "title": "",
    "labels": {},
}


def onboarding_needed(settings: QSettings) -> bool:
    """Return True when the onboarding guide should be displayed."""

    raw = settings.value("ui/show_welcome", None)
    if raw is not None:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"true", "1", "yes", "on"}
        try:
            return bool(int(raw))
        except Exception:
            return bool(raw)

    show_value = str(settings.value("general/show_onboarding", "true")).lower()
    return show_value in {"true", "1", "yes", "on"}


# [B] ========================= MAIN CLASS DEFINITION ================================
class VasoAnalyzerApp(QMainWindow):
    def __init__(self, check_updates: bool = True):
        super().__init__()

        icon_ext = "svg"
        if sys.platform.startswith("win"):
            icon_ext = "ico"
        elif sys.platform == "darwin":
            icon_ext = "icns"

        icon_path = self._brand_icon_path(icon_ext)
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setMouseTracking(True)

        # ===== Setup App Window =====
        self.setWindowTitle(f"VasoAnalyzer {APP_VERSION} - Python Edition")
        self.setGeometry(100, 100, 1280, 720)
        screen_size = QDesktopWidget().availableGeometry()
        self.resize(screen_size.width(), screen_size.height())

        # ===== Initialize State =====
        self.trace_data = None
        self.trace_file_path = None
        self.trace_model: Optional[TraceModel] = None
        self.snapshot_frames = []
        self.frames_metadata = []
        self.frame_times = []
        self.frame_trace_indices = []
        self.current_frame = 0
        self.snapshot_speed_multiplier = 1.0
        self.event_labels = []
        self.event_times = []
        self.event_frames = []
        self.event_annotations: list[AnnotationSpec] = []
        self._annotation_lane_visible = True
        self.event_text_objects = []
        self.event_table_data = []
        self.pinned_points = []
        self.slider_markers = {}
        self._time_cursor_time: Optional[float] = None
        self._time_cursor_visible: bool = True
        self.trace_line = None
        self.od_line = None
        # Explicit references to the plotted lines
        self.inner_line = None
        self.outer_line = None
        self.plot_legend = None
        self.legend_settings = copy.deepcopy(DEFAULT_LEGEND_SETTINGS)
        self.event_metadata = []
        self._last_event_import = {}
        self.sampling_rate_hz: Optional[float] = None
        self.session_dirty = False
        self.last_autosave_path: Optional[str] = None
        self.autosave_interval_ms = 5 * 60 * 1000  # 5 minutes by default
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(self.autosave_interval_ms)
        self.autosave_timer.setSingleShot(False)
        self.autosave_timer.timeout.connect(self._autosave_tick)
        self.autosave_timer.start()
        self._event_highlight_color = DEFAULT_STYLE.get(
            "event_highlight_color", "#1D5CFF"
        )
        self._event_highlight_base_alpha = float(
            DEFAULT_STYLE.get("event_highlight_alpha", 0.95)
        )
        self._event_highlight_duration_ms = int(
            DEFAULT_STYLE.get("event_highlight_duration_ms", 2000)
        )
        self._event_highlight_elapsed_ms = 0
        self._event_highlight_timer = QTimer(self)
        self._event_highlight_timer.setSingleShot(False)
        self._event_highlight_timer.setInterval(40)
        self._event_highlight_timer.timeout.connect(self._on_event_highlight_tick)
        self.ax2 = None
        self.xlim_full = None
        self.ylim_full = None
        # Default time between frames when metadata is unavailable
        self.recording_interval = 0.14  # 140 ms per frame
        self.last_replaced_event = None
        self.excel_auto_path = None  # Path to Excel file for auto-update
        self.excel_auto_column = None  # Column letter to use for auto-update
        self.grid_visible = True  # Track grid visibility
        self.snapshot_card = None
        self.snapshot_viewer_action = None
        self.recent_files = []
        self.settings = QSettings("TykockiLab", "VasoAnalyzer")
        self.onboarding_settings = QSettings(
            ONBOARDING_SETTINGS_ORG, ONBOARDING_SETTINGS_APP
        )
        self._syncing_time_window = False
        self._axis_source_axis = None
        self._axis_xlim_cid: Optional[int] = None
        self._welcome_dialog = None
        self._update_check_in_progress = False
        self._update_checker = UpdateChecker(self)
        self._update_checker.completed.connect(self._on_update_check_completed)
        self.load_recent_files()
        self.recent_projects = []
        self.load_recent_projects()
        self.setAcceptDrops(True)
        self.setStatusBar(QStatusBar(self))
        self.current_project = None
        self.project_tree = None
        self.metadata_dock = None
        self.zoom_dock = None
        self.scope_dock = None
        self.current_experiment = None
        self.current_sample = None
        self.data_cache: DataCache | None = None
        self._cache_root_hint: Optional[str] = None
        self._mirror_sources_enabled = False
        self._missing_assets: dict[tuple[int, str], MissingAsset] = {}
        self._relink_dialog: RelinkDialog | None = None
        self.action_relink_assets: Optional[QAction] = None
        self.project_state = {}
        self._style_holder = _StyleHolder(DEFAULT_STYLE.copy())
        self._style_manager = PlotStyleManager(self._style_holder.get_style())
        self.zoom_toggle_btn: Optional[QToolButton] = None
        self.scope_toggle_btn: Optional[QToolButton] = None
        self.actGrid: Optional[QAction] = None
        self.actStyle: Optional[QAction] = None
        self._nav_mode_actions: list[QAction] = []
        self.actEventLines: Optional[QAction] = None
        self.actEventLabelsAuto: Optional[QAction] = None
        self.actEventLabelsAll: Optional[QAction] = None
        self.actEventLabelsNone: Optional[QAction] = None
        self._event_label_mode: str = "none"
        self._event_lines_visible: bool = True
        self._event_label_gap_default: int = 22
        self.menu_event_lines_action: Optional[QAction] = None
        self.menu_event_labels_action: Optional[QAction] = None
        # ——— undo/redo ———
        self.undo_stack = QUndoStack(self)
        self._thread_pool = QThreadPool.globalInstance()
        self._current_sample_token: Optional[object] = None
        self._pending_asset_scan_token: Optional[object] = None
        self._project_missing_messages: list[str] = []
        self._last_missing_assets_snapshot: Optional[tuple[int, int]] = None

        # ===== Axis + Slider State =====
        self.axis_dragging = False
        self.axis_drag_start = None
        self.drag_direction = None
        self.scroll_slider = None
        self.window_width = None
        self._plot_drag_in_progress = False
        self._last_hover_time: Optional[float] = None
        self._pending_plot_layout: Optional[dict] = None

        # ===== Build UI =====
        self.create_menubar()
        self.initUI()
        self._wrap_views()
        self.setup_project_sidebar()
        self.setup_metadata_panel()
        self.setup_zoom_dock()
        self.setup_scope_dock()
        self._update_excel_controls()

        self.modeStack.setMouseTracking(True)
        self.modeStack.widget(0).setMouseTracking(True)
        self.canvas.setMouseTracking(True)

        if check_updates and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.check_for_updates_at_startup()

        QTimer.singleShot(0, self._maybe_run_onboarding)

    def setup_project_sidebar(self):
        from .project_explorer import ProjectExplorerWidget

        self.project_dock = ProjectExplorerWidget(self)
        self.project_tree = self.project_dock.tree
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemClicked.connect(self.on_tree_item_clicked)
        self.project_tree.itemChanged.connect(self.on_tree_item_changed)
        self.project_tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        # Single-click opens a sample; double-click is reserved for editing
        self.project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(
            self.show_project_context_menu
        )
        self.project_tree.setAlternatingRowColors(True)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)
        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.project_dock.toggleViewAction())

        # Toggle button in toolbar
        self.project_toggle_btn = QToolButton()
        self.project_toggle_btn.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.project_toggle_btn.setCheckable(True)
        self.project_toggle_btn.setChecked(False)
        self.project_toggle_btn.setToolTip("Project")
        self.project_toggle_btn.clicked.connect(
            lambda checked: self.project_dock.setVisible(checked)
        )
        self.project_dock.visibilityChanged.connect(self.project_toggle_btn.setChecked)
        self.toolbar.addWidget(self.project_toggle_btn)
        self.project_dock.hide()

    def setup_metadata_panel(self):
        self.metadata_dock = MetadataDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.metadata_dock)

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.metadata_dock.toggleViewAction())

        # Keep toggle button state in sync with dock visibility.
        self.metadata_dock.visibilityChanged.connect(
            self._on_metadata_visibility_changed
        )

        project_form = self.metadata_dock.project_form
        project_form.description_changed.connect(self.on_project_description_changed)
        project_form.tags_changed.connect(self.on_project_tags_changed)
        project_form.attachment_add_requested.connect(self.on_project_add_attachment)
        project_form.attachment_remove_requested.connect(
            self.on_project_remove_attachment
        )
        project_form.attachment_open_requested.connect(self.on_project_open_attachment)

        experiment_form = self.metadata_dock.experiment_form
        experiment_form.notes_changed.connect(self.on_experiment_notes_changed)
        experiment_form.tags_changed.connect(self.on_experiment_tags_changed)

        sample_form = self.metadata_dock.sample_form
        sample_form.notes_changed.connect(self.on_sample_notes_changed)
        sample_form.attachment_add_requested.connect(self.on_sample_add_attachment)
        sample_form.attachment_remove_requested.connect(
            self.on_sample_remove_attachment
        )
        sample_form.attachment_open_requested.connect(self.on_sample_open_attachment)

        self.metadata_toggle_btn = QToolButton()
        self.metadata_toggle_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.metadata_toggle_btn.setCheckable(True)
        self.metadata_toggle_btn.setChecked(False)
        self.metadata_toggle_btn.setToolTip("Details")
        self.metadata_toggle_btn.clicked.connect(
            lambda checked: self.metadata_dock.setVisible(checked)
        )
        self.toolbar.addWidget(self.metadata_toggle_btn)
        self.metadata_dock.hide()

    def setup_zoom_dock(self):
        self.zoom_dock = ZoomWindowDock(self)
        self.zoom_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.zoom_dock)
        self.zoom_dock.hide()

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.zoom_dock.toggleViewAction())

        self.zoom_dock.visibilityChanged.connect(self._on_zoom_visibility_changed)

        self.zoom_toggle_btn = QToolButton()
        self.zoom_toggle_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        )
        self.zoom_toggle_btn.setCheckable(True)
        self.zoom_toggle_btn.setChecked(False)
        self.zoom_toggle_btn.setToolTip("Zoom window")
        self.zoom_toggle_btn.clicked.connect(
            lambda checked: self.zoom_dock.setVisible(checked)
        )
        self.zoom_dock.visibilityChanged.connect(self.zoom_toggle_btn.setChecked)
        self.toolbar.addWidget(self.zoom_toggle_btn)

    def setup_scope_dock(self):
        self.scope_dock = ScopeDock(self)
        self.scope_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.scope_dock)
        self.scope_dock.hide()

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.scope_dock.toggleViewAction())

        self.scope_dock.visibilityChanged.connect(self._on_scope_visibility_changed)

        self.scope_toggle_btn = QToolButton()
        self.scope_toggle_btn.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.scope_toggle_btn.setCheckable(True)
        self.scope_toggle_btn.setChecked(False)
        self.scope_toggle_btn.setToolTip("Trigger sweeps")
        self.scope_toggle_btn.clicked.connect(
            lambda checked: self.scope_dock.setVisible(checked)
        )
        self.scope_dock.visibilityChanged.connect(self.scope_toggle_btn.setChecked)
        self.toolbar.addWidget(self.scope_toggle_btn)

    # ---------- Project Menu Actions ----------
    def _replace_current_project(self, project):
        """Swap the active project, ensuring old resources are released."""

        if project is self.current_project:
            return

        old_project = self.current_project
        self.current_project = project
        self.current_experiment = None
        self.current_sample = None
        self.project_state.clear()
        self._cache_root_hint = (
            project.path if project and getattr(project, "path", None) else None
        )
        self.data_cache = None
        self._missing_assets.clear()
        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(False)
        if self._relink_dialog:
            self._relink_dialog.hide()
        self._update_metadata_panel(project)
        self._update_window_title()

        if old_project is not None:
            try:
                old_project.close()
            except Exception:
                log.debug("Failed to close previous project resources", exc_info=True)

    def _ensure_data_cache(self, hint_path: Optional[str] = None) -> DataCache:
        """Return the active DataCache, creating it when necessary."""

        if self.current_project and getattr(self.current_project, "path", None):
            base_hint = self.current_project.path
        elif hint_path:
            try:
                base_hint = (
                    Path(hint_path).expanduser().resolve(strict=False).parent.as_posix()
                )
            except Exception:
                base_hint = Path(hint_path).expanduser().parent.as_posix()
        else:
            base_hint = self._cache_root_hint

        cache_root = cache_dir_for_project(base_hint)
        cache_root = cache_root.expanduser().resolve(strict=False)

        if self.data_cache is None or self.data_cache.root != cache_root:
            self.data_cache = DataCache(cache_root)
            self.data_cache.mirror_sources = self._mirror_sources_enabled
        self._cache_root_hint = base_hint
        return self.data_cache

    def _project_base_dir(self) -> Optional[Path]:
        if self.current_project and self.current_project.path:
            try:
                return (
                    Path(self.current_project.path)
                    .expanduser()
                    .resolve(strict=False)
                    .parent
                )
            except Exception:
                return Path(self.current_project.path).expanduser().parent
        return None

    @staticmethod
    def _compute_path_signature(path: Path) -> Optional[str]:
        try:
            stat = path.stat()
        except OSError:
            return None
        return f"{stat.st_size}-{int(stat.st_mtime)}"

    def _update_sample_link_metadata(
        self, sample: SampleN, kind: str, path_obj: Path
    ) -> None:
        path_attr = f"{kind}_path"
        hint_attr = f"{kind}_hint"
        relative_attr = f"{kind}_relative"
        signature_attr = f"{kind}_signature"

        path_str = path_obj.expanduser().resolve(strict=False).as_posix()
        setattr(sample, path_attr, path_str)
        setattr(sample, hint_attr, path_str)

        signature = self._compute_path_signature(path_obj)
        if signature:
            setattr(sample, signature_attr, signature)

        base_dir = self._project_base_dir()
        if base_dir:
            try:
                rel = os.path.relpath(path_str, os.fspath(base_dir))
            except Exception:
                rel = path_obj.name
        else:
            rel = path_obj.name
        setattr(sample, relative_attr, os.path.normpath(rel))

    def _resolve_sample_link(self, sample: SampleN, kind: str) -> Optional[str]:
        path_attr = f"{kind}_path"
        hint_attr = f"{kind}_hint"
        relative_attr = f"{kind}_relative"

        current_path = getattr(sample, path_attr, None)
        if current_path and Path(current_path).exists():
            return current_path

        candidates: list[Path] = []
        base_dir = self._project_base_dir()
        relative = getattr(sample, relative_attr, None)
        if relative and base_dir:
            candidates.append((base_dir / Path(relative)).resolve(strict=False))

        hint = getattr(sample, hint_attr, None)
        if hint:
            candidates.append(Path(hint).expanduser().resolve(strict=False))

        if current_path:
            candidates.append(Path(current_path).expanduser().resolve(strict=False))

        for candidate in candidates:
            if candidate.exists():
                self._update_sample_link_metadata(sample, kind, candidate)
                self._clear_missing_asset(sample, kind)
                return candidate.as_posix()

        return current_path

    def _ensure_relink_dialog(self) -> RelinkDialog:
        if self._relink_dialog is None:
            self._relink_dialog = RelinkDialog(self)
            self._relink_dialog.relink_applied.connect(self._apply_relinked_assets)
        return self._relink_dialog

    def show_relink_dialog(self):
        if not self._missing_assets:
            QMessageBox.information(
                self, "Relink Files", "All linked files are currently reachable."
            )
            return
        dialog = self._ensure_relink_dialog()
        dialog.set_assets(self._missing_assets.values())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_relinked_assets(self, assets: List[MissingAsset]) -> None:
        if not self.current_project:
            return
        updated_sample_ids: set[int] = set()
        for asset in assets:
            if not asset.new_path:
                continue
            path_obj = Path(asset.new_path).expanduser().resolve(strict=False)
            if not path_obj.exists():
                QMessageBox.warning(
                    self,
                    "Relink Failed",
                    f"The file {path_obj} could not be found. Please choose a different location.",
                )
                continue
            self._update_sample_link_metadata(asset.sample, asset.kind, path_obj)
            key = (id(asset.sample), asset.kind)
            self._missing_assets.pop(key, None)
            updated_sample_ids.add(id(asset.sample))

        if self.action_relink_assets and not self._missing_assets:
            self.action_relink_assets.setEnabled(False)

        if self._relink_dialog:
            if self._missing_assets:
                self._relink_dialog.set_assets(self._missing_assets.values())
            else:
                self._relink_dialog.hide()

        if not updated_sample_ids:
            return

        self.mark_session_dirty()
        self.refresh_project_tree()
        if self.current_sample and id(self.current_sample) in updated_sample_ids:
            self.load_sample_into_view(self.current_sample)
        self.statusBar().showMessage("Missing files relinked.", 4000)

    def _handle_missing_asset(
        self,
        sample: SampleN,
        kind: str,
        path: Optional[str],
        error: Optional[str] = None,
    ) -> None:
        key = (id(sample), kind)
        asset = self._missing_assets.get(key)
        if not asset:
            label_kind = "Trace" if kind == "trace" else "Events"
            asset = MissingAsset(
                sample=sample,
                kind=kind,
                label=f"{sample.name} · {label_kind}",
                current_path=path,
                relative=getattr(sample, f"{kind}_relative", None),
                hint=getattr(sample, f"{kind}_hint", None),
                signature=getattr(sample, f"{kind}_signature", None),
            )
            self._missing_assets[key] = asset
        else:
            asset.current_path = path or asset.current_path
            asset.new_path = None
        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(True)
        dialog = self._ensure_relink_dialog()
        dialog.set_assets(self._missing_assets.values())
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.statusBar().showMessage(
            "Some linked files are missing. Use Tools → Relink Missing Files… to repair.",
            6000,
        )
        if error:
            log.debug("Missing asset detected: %s", error)

    def _clear_missing_asset(self, sample: SampleN, kind: str) -> None:
        key = (id(sample), kind)
        removed = self._missing_assets.pop(key, None)
        if removed and self._missing_assets:
            if self._relink_dialog:
                self._relink_dialog.set_assets(self._missing_assets.values())
        elif removed:
            if self.action_relink_assets:
                self.action_relink_assets.setEnabled(False)
            if self._relink_dialog:
                self._relink_dialog.hide()

    def new_project(self):
        dialog = NewProjectDialog(self, settings=self.settings)
        if dialog.exec_() != QDialog.Accepted:
            return

        name = dialog.project_name()
        path = dialog.project_path()
        exp_name = dialog.experiment_name()

        if not name or not path:
            return

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vaso":
            path_obj = path_obj.with_suffix(".vaso")
        normalised_path = str(path_obj.resolve(strict=False))

        project = Project(name=name, path=normalised_path)
        if exp_name:
            project.experiments.append(Experiment(name=exp_name))
            if project.ui_state is None:
                project.ui_state = {}
            project.ui_state["last_experiment"] = exp_name

        self._replace_current_project(project)
        if project.experiments:
            self.current_experiment = project.experiments[0]

        save_project_file(self.current_project, normalised_path)
        self.update_recent_projects(normalised_path)
        self.refresh_project_tree()

        if self.project_tree and project.experiments:
            root_item = self.project_tree.topLevelItem(0)
            if root_item and root_item.childCount():
                first_exp_item = root_item.child(0)
                self.project_tree.setCurrentItem(first_exp_item)

        self.statusBar().showMessage(
            "Project created. Use the Add Data actions to start populating your experiment.",
            6000,
        )

    def open_project_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            "Vaso Projects (*.vaso *.vasopack);;All Files (*)",
        )
        if not path:
            return

        path_obj = Path(path).expanduser().resolve(strict=False)
        path = str(path_obj)

        self._clear_canvas_and_table()

        project: Optional[Project] = None
        project_path = path
        restored_from_autosave = False

        if path_obj.suffix.lower() == ".vasopack":
            base_dir = QFileDialog.getExistingDirectory(
                self,
                "Select Folder to Unpack Bundle",
                path_obj.parent.as_posix(),
            )
            if not base_dir:
                return
            stem = path_obj.stem
            target_dir = Path(base_dir).expanduser().resolve(strict=False) / stem
            counter = 1
            while target_dir.exists():
                counter += 1
                target_dir = Path(base_dir) / f"{stem}_{counter}"
            try:
                project = import_project_bundle(path, target_dir.as_posix())
                project_path = (
                    project.path or target_dir.joinpath(f"{stem}.vaso").as_posix()
                )
                self.statusBar().showMessage(
                    f"\u2713 Bundle unpacked to {target_dir}", 5000
                )
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Bundle Import Error",
                    f"Could not unpack bundle:\n{exc}",
                )
                return
        else:
            autosave_candidate = pending_autosave_path(path)
            if autosave_candidate:
                try:
                    autosave_mtime = os.path.getmtime(autosave_candidate)
                    project_mtime = os.path.getmtime(path)
                except OSError:
                    autosave_mtime = project_mtime = 0

                if autosave_mtime > project_mtime:
                    choice = QMessageBox.question(
                        self,
                        "Recover Autosave?",
                        (
                            "An autosave snapshot newer than this project was found.\n"
                            "Would you like to recover it?"
                        ),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if choice == QMessageBox.Yes:
                        try:
                            project = restore_autosave(path)
                            restored_from_autosave = True
                            try:
                                os.remove(autosave_candidate)
                            except OSError:
                                pass
                        except Exception as exc:
                            QMessageBox.warning(
                                self,
                                "Autosave Recovery Failed",
                                f"Could not restore autosave:\n{exc}\n\nOpening original file instead.",
                            )

            if project is None:
                try:
                    project = load_project(path)
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "Project Load Error",
                        f"Could not open project:\n{exc}",
                    )
                    return

        self._replace_current_project(project)
        self.apply_ui_state(getattr(self.current_project, "ui_state", None))
        self.refresh_project_tree()
        self.show_analysis_workspace()

        status = f"\u2713 Project loaded: {self.current_project.name}"
        if restored_from_autosave:
            status += " (autosave recovered)"
        self.statusBar().showMessage(status, 5000)

        if project_path:
            self.update_recent_projects(project_path)
        tree = self.project_tree
        restored = self.restore_last_selection()
        if not restored:
            first_sample_item = None
            first_exp_item = None
            if tree and self.current_project.experiments:
                root_item = tree.topLevelItem(0)
                first_exp = self.current_project.experiments[0]
                if root_item is not None:
                    for i in range(root_item.childCount()):
                        child = root_item.child(i)
                        if child.data(0, Qt.UserRole) is first_exp:
                            first_exp_item = child
                            if first_exp.samples:
                                target_sample = first_exp.samples[0]
                                for j in range(child.childCount()):
                                    sample_child = child.child(j)
                                    if sample_child.data(0, Qt.UserRole) is target_sample:
                                        first_sample_item = sample_child
                                        break
                            break

            if first_sample_item is not None and tree:
                tree.setCurrentItem(first_sample_item)
                self.on_tree_item_clicked(first_sample_item, 0)
            elif (
                self.current_project.experiments
                and self.current_project.experiments[0].samples
            ):
                first_sample = self.current_project.experiments[0].samples[0]
                self.load_sample_into_view(first_sample)
            else:
                if first_exp_item is not None and tree:
                    tree.setCurrentItem(first_exp_item)
                    self.on_tree_item_clicked(first_exp_item, 0)
                elif tree and tree.topLevelItemCount():
                    root = tree.topLevelItem(0)
                    if root is not None:
                        tree.setCurrentItem(root)
                        self.on_tree_item_clicked(root, 0)
                self.show_analysis_workspace()
        self._reset_session_dirty()

    def save_project_file(self):
        if self.current_project and self.current_project.path:
            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state
            save_project_file(self.current_project)
            self.update_recent_projects(self.current_project.path)
            self.statusBar().showMessage("\u2713 Project saved", 3000)
            self._reset_session_dirty()
            self._update_window_title()
        elif self.current_project:
            self.save_project_file_as()

    def save_project_file_as(self):
        if not self.current_project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            self.current_project.path or "",
            "Vaso Files (*.vaso)",
        )
        if path:
            path_obj = Path(path).expanduser()
            if path_obj.suffix.lower() != ".vaso":
                path_obj = path_obj.with_suffix(".vaso")
            path = str(path_obj.resolve(strict=False))
            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state
            save_project_file(self.current_project, path)
            self.update_recent_projects(path)
        self.statusBar().showMessage("\u2713 Project saved", 3000)
        self._reset_session_dirty()
        self._update_window_title()

    def export_project_bundle_action(self):
        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before exporting."
            )
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        default_stem = Path(self.current_project.path).with_suffix("").name
        default_path = (
            Path(self.current_project.path)
            .with_name(f"{default_stem}.vasopack")
            .as_posix()
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project Bundle",
            default_path,
            "Vaso Bundles (*.vasopack)",
        )
        if not path:
            return
        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vasopack":
            path_obj = path_obj.with_suffix(".vasopack")
        path = str(path_obj.resolve(strict=False))

        self.current_project.ui_state = self.gather_ui_state()
        if self.current_sample:
            state = self.gather_sample_state()
            self.current_sample.ui_state = state
            self.project_state[id(self.current_sample)] = state

        try:
            export_project_bundle(self.current_project, path)
            self.statusBar().showMessage(f"\u2713 Bundle saved: {path}", 5000)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export bundle:\n{exc}",
            )

    def auto_save_project(self, reason: Optional[str] = None):
        """Write an autosave snapshot when a project is available."""

        if not self.current_project or not self.current_project.path:
            return

        try:
            self.current_project.ui_state = self.gather_ui_state()
            if self.current_sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state

            autosave_path = autosave_project(self.current_project)
            if autosave_path:
                self.last_autosave_path = autosave_path
                log.debug(
                    "Autosave written to %s (reason=%s)",
                    autosave_path,
                    reason or "manual",
                )
        except Exception as exc:
            log.error("Failed to write autosave (%s): %s", reason or "manual", exc)

    def _autosave_tick(self):
        if not self.current_project or not self.current_project.path:
            return
        if not self.session_dirty:
            return
        self.auto_save_project(reason="timer")

    def refresh_project_tree(self):
        if not self.project_tree:
            return
        self.project_tree.clear()
        if not self.current_project:
            return
        root = QTreeWidgetItem([self.current_project.name])
        root.setData(0, Qt.UserRole, self.current_project)
        root.setFlags(root.flags() | Qt.ItemIsEditable)
        root.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
        self.project_tree.addTopLevelItem(root)
        for exp in self.current_project.experiments:
            exp_item = QTreeWidgetItem([exp.name])
            exp_item.setData(0, Qt.UserRole, exp)
            exp_item.setFlags(exp_item.flags() | Qt.ItemIsEditable)
            exp_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileDialogListView))
            root.addChild(exp_item)
            for s in exp.samples:
                has_data = bool(
                    s.trace_path or s.trace_data is not None or s.dataset_id is not None
                )
                status = "✓" if has_data else "✗"
                item = QTreeWidgetItem([f"{s.name} {status}"])
                item.setData(0, Qt.UserRole, s)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                exp_item.addChild(item)
        self.project_tree.expandAll()
        self._update_metadata_panel(self.current_project)
        self._schedule_missing_asset_scan()

    def _schedule_missing_asset_scan(self) -> None:
        if self.current_project is None or not getattr(
            self.current_project, "experiments", None
        ):
            return
        if getattr(self.current_project, "path", None) is None:
            return
        token = object()
        self._pending_asset_scan_token = token
        job = _MissingAssetScanJob(self.current_project, token)
        job.signals.finished.connect(self._on_missing_asset_scan_finished)
        job.signals.error.connect(self._on_missing_asset_scan_error)
        self._thread_pool.start(job)

    def _on_missing_asset_scan_finished(
        self,
        token: object,
        payload: tuple[list[MissingAsset], list[str]],
    ) -> None:
        if token != self._pending_asset_scan_token:
            return
        self._pending_asset_scan_token = None

        sample_assets, project_messages = payload
        self._project_missing_messages = project_messages

        updated = False
        for asset in sample_assets:
            key = (id(asset.sample), asset.kind)
            existing = self._missing_assets.get(key)
            if existing is None:
                self._missing_assets[key] = asset
                updated = True
            else:
                existing.current_path = asset.current_path
                existing.relative = asset.relative
                existing.hint = asset.hint
                existing.signature = asset.signature

        if updated and self._relink_dialog:
            self._relink_dialog.set_assets(self._missing_assets.values())

        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(bool(self._missing_assets))

        snapshot = (len(sample_assets), len(project_messages))
        if snapshot != self._last_missing_assets_snapshot and (
            sample_assets or project_messages
        ):
            self._report_missing_assets(sample_assets, project_messages)
            self._last_missing_assets_snapshot = snapshot

    def _on_missing_asset_scan_error(self, token: object, message: str) -> None:
        if token != self._pending_asset_scan_token:
            return
        self._pending_asset_scan_token = None
        log.debug("Missing asset scan failed: %s", message)

    def _report_missing_assets(
        self,
        sample_assets: List[MissingAsset],
        project_messages: List[str],
    ) -> None:
        entries: List[str] = []
        for asset in sample_assets:
            path_text = asset.current_path or "—"
            entries.append(f"{asset.label}: {path_text}")
        for message in project_messages:
            entries.append(f"Project: {message}")

        if not entries:
            return

        summary = "\n".join(f"• {entry}" for entry in entries[:6])
        if len(entries) > 6:
            summary += f"\n… and {len(entries) - 6} more."
        QMessageBox.warning(
            self,
            "Missing Linked Files",
            (
                "Some linked resources could not be found. "
                "You may need to relink them before continuing.\n\n"
                f"{summary}"
            ),
        )

    def on_tree_item_clicked(self, item, _):
        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, SampleN):
            if self.current_sample and self.current_sample is not obj:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state
            self.current_sample = obj
            parent = item.parent()
            self.current_experiment = parent.data(0, Qt.UserRole) if parent else None
            # Open the sample on single-click
            self.load_sample_into_view(obj)
        elif isinstance(obj, Experiment):
            self.current_experiment = obj
            self.current_sample = None
            if self.current_project is not None:
                if not isinstance(self.current_project.ui_state, dict):
                    self.current_project.ui_state = {}
                self.current_project.ui_state["last_experiment"] = obj.name
                self.current_project.ui_state.pop("last_sample", None)
        else:
            self.current_sample = None
            self.current_experiment = None
        self._update_metadata_panel(obj)

    def on_tree_item_changed(self, item, _):
        obj = item.data(0, Qt.UserRole)
        if obj is None:
            return

        text = item.text(0)

        def _clean(txt: str) -> str:
            txt = txt.strip()
            if txt.endswith(" \u2713") or txt.endswith(" \u2717"):
                txt = txt[:-2]
            return txt.strip()

        name = _clean(text)

        if isinstance(obj, SampleN):
            obj.name = name
            has_data = bool(
                obj.trace_path
                or obj.trace_data is not None
                or obj.dataset_id is not None
            )
            status = "\u2713" if has_data else "\u2717"
            self.project_tree.blockSignals(True)
            item.setText(0, f"{name} {status}")
            self.project_tree.blockSignals(False)
        elif isinstance(obj, Experiment):
            obj.name = name
        elif isinstance(obj, Project):
            obj.name = name

    def on_tree_item_double_clicked(self, item, _):
        """Deprecated handler kept for backward compatibility."""
        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, SampleN):
            self.load_sample_into_view(obj)

    def on_tree_selection_changed(self):
        if not self.project_tree:
            return
        selection = self.project_tree.selectedItems()
        if not selection:
            self._update_metadata_panel()
            return
        obj = selection[0].data(0, Qt.UserRole)
        self._update_metadata_panel(obj)

    def _on_metadata_visibility_changed(self, visible: bool) -> None:
        if not hasattr(self, "metadata_toggle_btn") or self.metadata_toggle_btn is None:
            return
        self.metadata_toggle_btn.blockSignals(True)
        self.metadata_toggle_btn.setChecked(bool(visible))
        self.metadata_toggle_btn.blockSignals(False)

    def _update_metadata_panel(self, obj=None) -> None:
        if not self.metadata_dock:
            return

        target = obj
        if target is None:
            if self.current_sample is not None:
                target = self.current_sample
            elif self.current_experiment is not None:
                target = self.current_experiment
            else:
                target = self.current_project

        if isinstance(target, SampleN):
            self.metadata_dock.show_sample(target)
        elif isinstance(target, Experiment):
            self.metadata_dock.show_experiment(target)
        elif isinstance(target, Project):
            self.metadata_dock.show_project(target)
        else:
            if self.current_project is not None:
                self.metadata_dock.show_project(self.current_project)
            else:
                self.metadata_dock.show_blank()

    # ---------- Metadata form callbacks ----------
    def on_project_description_changed(self, text: str) -> None:
        if not self.current_project:
            return
        description = text.strip() or None
        if self.current_project.description != description:
            self.current_project.description = description
            if self.metadata_dock:
                self.metadata_dock.project_form.set_metadata(self.current_project)
            self.mark_session_dirty()

    def on_project_tags_changed(self, tags: list[str]) -> None:
        if not self.current_project:
            return
        if self.current_project.tags != tags:
            self.current_project.tags = tags
            if self.metadata_dock:
                self.metadata_dock.project_form.set_metadata(self.current_project)
            self.mark_session_dirty()

    def on_project_add_attachment(self) -> None:
        if not self.current_project:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Project Attachment",
            "",
            "All Files (*.*)",
        )
        added = False
        for path in paths:
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            attachment = Attachment(name=name, filename=os.path.basename(path))
            attachment.source_path = path
            self.current_project.attachments.append(attachment)
            added = True
        if added:
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(self.current_project.attachments)
            self.mark_session_dirty()

    def on_project_remove_attachment(self, index: int) -> None:
        if not self.current_project:
            return
        attachments = self.current_project.attachments
        if 0 <= index < len(attachments):
            attachments.pop(index)
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(attachments)
            self.mark_session_dirty()

    def on_project_open_attachment(self, index: int) -> None:
        if not self.current_project:
            return
        self._open_attachment_for(self.current_project.attachments, index)

    def on_experiment_notes_changed(self, text: str) -> None:
        if not isinstance(self.current_experiment, Experiment):
            return
        notes = text.strip() or None
        if self.current_experiment.notes != notes:
            self.current_experiment.notes = notes
            if self.metadata_dock:
                self.metadata_dock.experiment_form.set_metadata(self.current_experiment)
            self.mark_session_dirty()

    def on_experiment_tags_changed(self, tags: list[str]) -> None:
        if not isinstance(self.current_experiment, Experiment):
            return
        if self.current_experiment.tags != tags:
            self.current_experiment.tags = tags
            if self.metadata_dock:
                self.metadata_dock.experiment_form.set_metadata(self.current_experiment)
            self.mark_session_dirty()

    def on_sample_notes_changed(self, text: str) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        notes = text.strip() or None
        if self.current_sample.notes != notes:
            self.current_sample.notes = notes
            if self.metadata_dock:
                self.metadata_dock.sample_form.set_metadata(self.current_sample)
            self.mark_session_dirty()

    def on_sample_add_attachment(self) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Sample Attachment",
            "",
            "All Files (*.*)",
        )
        added = False
        for path in paths:
            if not path:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            attachment = Attachment(name=name, filename=os.path.basename(path))
            attachment.source_path = path
            self.current_sample.attachments.append(attachment)
            added = True
        if added:
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(self.current_sample.attachments)
            self.mark_session_dirty()

    def on_sample_remove_attachment(self, index: int) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        attachments = self.current_sample.attachments
        if 0 <= index < len(attachments):
            attachments.pop(index)
            if self.metadata_dock:
                self.metadata_dock.refresh_attachments(attachments)
            self.mark_session_dirty()

    def on_sample_open_attachment(self, index: int) -> None:
        if not isinstance(self.current_sample, SampleN):
            return
        self._open_attachment_for(self.current_sample.attachments, index)

    def _open_attachment_for(self, attachments: list[Attachment], index: int) -> None:
        if not (0 <= index < len(attachments)):
            return
        att = attachments[index]
        path = self._resolve_attachment_path(att)
        if not path:
            QMessageBox.warning(
                self,
                "Attachment Missing",
                "The attachment file is no longer available on disk.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _resolve_attachment_path(self, att: Attachment) -> Optional[str]:
        for candidate in (att.data_path, att.source_path):
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def load_sample_into_view(self, sample: SampleN):
        """Load a sample's trace and events into the main view."""
        log.info("Loading sample %s", sample.name)

        if self.current_sample and self.current_sample is not sample:
            state = self.gather_sample_state()
            self.current_sample.ui_state = state
            self.project_state[id(self.current_sample)] = state

        self.current_sample = sample

        token = object()
        self._current_sample_token = token

        needs_trace = sample.trace_data is None and sample.dataset_id is not None
        needs_events = sample.events_data is None and sample.dataset_id is not None
        needs_results = (
            sample.analysis_results is None
            and sample.dataset_id is not None
            and (
                sample.analysis_result_keys is None or bool(sample.analysis_result_keys)
            )
        )

        project_path = getattr(self.current_project, "path", None)
        load_async = bool(
            project_path and (needs_trace or needs_events or needs_results)
        )

        self._prepare_sample_view(sample)

        if load_async and project_path:
            self.statusBar().showMessage(f"Loading {sample.name}…", 2000)
            self._begin_sample_load_job(
                sample,
                token,
                project_path,
                load_trace=needs_trace,
                load_events=needs_events,
                load_results=needs_results,
            )
            return

        self._render_sample(sample)

    def _prepare_sample_view(self, sample: SampleN) -> None:
        self.show_analysis_workspace()
        self._clear_canvas_and_table()
        self.snapshot_frames = []
        self.frames_metadata = []
        self.toggle_snapshot_viewer(False)
        self.snapshot_label.hide()
        self.slider.hide()
        self.snapshot_controls.hide()
        self.prev_frame_btn.setEnabled(False)
        self.next_frame_btn.setEnabled(False)
        self.play_pause_btn.setEnabled(False)
        self.snapshot_speed_label.setEnabled(False)
        self.snapshot_speed_combo.setEnabled(False)
        self._reset_snapshot_speed()
        self._set_playback_state(False)
        self.metadata_details_label.setText("No metadata available.")
        self._clear_slider_markers()
        self._clear_event_highlight()
        self.trace_data = None
        self.event_labels = []
        self.event_times = []
        self.event_frames = []
        self.event_table_data = []

    def _begin_sample_load_job(
        self,
        sample: SampleN,
        token: object,
        project_path: str,
        *,
        load_trace: bool,
        load_events: bool,
        load_results: bool,
    ) -> None:
        job = _SampleLoadJob(
            project_path,
            sample,
            token,
            load_trace=load_trace,
            load_events=load_events,
            load_results=load_results,
        )
        job.signals.finished.connect(self._on_sample_load_finished)
        job.signals.error.connect(self._on_sample_load_error)
        self._thread_pool.start(job)

    def _on_sample_load_finished(
        self,
        token: object,
        sample: SampleN,
        trace_df: Optional[pd.DataFrame],
        events_df: Optional[pd.DataFrame],
        analysis_results: Optional[Dict[str, Any]],
    ) -> None:
        if token != self._current_sample_token or sample is not self.current_sample:
            return
        if trace_df is not None:
            sample.trace_data = trace_df
        if events_df is not None:
            sample.events_data = events_df
        if analysis_results:
            sample.analysis_results = analysis_results
            sample.analysis_result_keys = list(analysis_results.keys())
        elif sample.analysis_result_keys is None:
            sample.analysis_result_keys = []
        self.statusBar().showMessage(f"{sample.name} ready", 2000)
        self._render_sample(sample)

    def _on_sample_load_error(
        self, token: object, sample: SampleN, message: str
    ) -> None:
        if token != self._current_sample_token or sample is not self.current_sample:
            return
        log.warning("Embedded data load failed for %s: %s", sample.name, message)
        self.statusBar().showMessage(
            f"Embedded data not available ({message})",
            6000,
        )
        self._render_sample(sample)

    def _render_sample(self, sample: SampleN) -> None:
        style = None
        if isinstance(sample.ui_state, dict):
            style = sample.ui_state.get("style_settings") or sample.ui_state.get(
                "plot_style"
            )
        merged_style = {**DEFAULT_STYLE, **style} if style else DEFAULT_STYLE.copy()
        self._style_holder = _StyleHolder(merged_style.copy())
        self._style_manager.replace(merged_style)

        cache: DataCache | None = None
        try:
            trace_source = None
            if sample.trace_data is not None:
                trace = sample.trace_data.copy()
                trace_source = sample.trace_path or sample.name
            elif sample.trace_path:
                resolved_trace = self._resolve_sample_link(sample, "trace")
                if not resolved_trace or not Path(resolved_trace).exists():
                    raise FileNotFoundError(str(sample.trace_path))
                cache = self._ensure_data_cache(resolved_trace)
                trace = load_trace(resolved_trace, cache=cache)
                sample.trace_path = resolved_trace
                self._clear_missing_asset(sample, "trace")
                self.trace_file_path = os.path.dirname(resolved_trace)
                trace_source = resolved_trace
            else:
                QMessageBox.warning(self, "No Trace", "Sample has no trace data.")
                return
        except FileNotFoundError as exc:
            missing = getattr(exc, "filename", None) or sample.trace_path
            self._handle_missing_asset(sample, "trace", missing, str(exc))
            QMessageBox.warning(
                self,
                "Trace File Missing",
                "The trace file could not be located. Use Relink Missing Files to update the link.",
            )
            return
        except Exception as error:
            QMessageBox.critical(self, "Trace Load Error", str(error))
            return

        self.sampling_rate_hz = self._compute_sampling_rate(trace)
        if trace_source:
            display_name = os.path.basename(trace_source)
            prefix = (
                "Trace"
                if isinstance(trace_source, str) and os.path.exists(trace_source)
                else "Sample"
            )
            tooltip = trace_source if isinstance(trace_source, str) else sample.name
            self._set_status_source(f"{prefix} · {display_name}", tooltip)
            if isinstance(trace_source, str) and os.path.exists(trace_source):
                self.trace_file_path = os.path.dirname(trace_source)
            else:
                self.trace_file_path = None
        else:
            self._set_status_source(f"Sample · {sample.name}", sample.name)
            self.trace_file_path = None
        self._reset_session_dirty()

        labels, times, frames, diam, od = [], [], [], [], []
        try:
            if sample.events_data is not None:
                labels, times, frames = load_events(sample.events_data)
                self._clear_missing_asset(sample, "events")
            elif sample.events_path:
                resolved_events = self._resolve_sample_link(sample, "events")
                if not resolved_events or not Path(resolved_events).exists():
                    raise FileNotFoundError(str(sample.events_path))
                event_cache = cache or self._ensure_data_cache(resolved_events)
                labels, times, frames = load_events(resolved_events, cache=event_cache)
                sample.events_path = resolved_events
                self._clear_missing_asset(sample, "events")
            else:
                labels, times, frames = [], [], []

            diam = []
            if times:
                arr_t = trace["Time (s)"].values
                arr_d = trace["Inner Diameter"].values
                arr_od = (
                    trace["Outer Diameter"].values
                    if "Outer Diameter" in trace.columns
                    else None
                )
                for t in times:
                    idx_evt = int(np.argmin(np.abs(arr_t - t)))
                    diam.append(float(arr_d[idx_evt]))
                    if arr_od is not None:
                        od.append(float(arr_od[idx_evt]))
        except FileNotFoundError as exc:
            missing = getattr(exc, "filename", None) or sample.events_path
            self._handle_missing_asset(sample, "events", missing, str(exc))
        except Exception as error:
            QMessageBox.warning(self, "Event Load Error", str(error))

        self.trace_data = self._prepare_trace_dataframe(trace)
        self.xlim_full = None
        self.ylim_full = None
        self.legend_settings = copy.deepcopy(DEFAULT_LEGEND_SETTINGS)
        self.update_plot()
        self.compute_frame_trace_indices()
        self.load_project_events(labels, times, frames, diam, od)
        state_to_apply = self.project_state.get(
            id(sample), getattr(sample, "ui_state", None)
        )
        self.apply_sample_state(state_to_apply)
        log.info("Sample loaded with %d events", len(labels))

        if self.current_project is not None:
            if not isinstance(self.current_project.ui_state, dict):
                self.current_project.ui_state = {}
            if self.current_experiment:
                self.current_project.ui_state["last_experiment"] = (
                    self.current_experiment.name
                )
            self.current_project.ui_state["last_sample"] = sample.name

        self._update_snapshot_viewer_state(sample)
        self._update_home_resume_button()
        self._update_metadata_panel(sample)

    def _update_snapshot_viewer_state(self, sample: SampleN) -> None:
        has_stack = (
            isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
        )
        asset_available = bool(
            sample.snapshot_role and sample.asset_roles.get(sample.snapshot_role)
        )
        path_available = bool(sample.snapshot_path)
        should_enable = has_stack or asset_available or path_available

        if self.snapshot_viewer_action:
            self.snapshot_viewer_action.setEnabled(should_enable)
            if not should_enable:
                self.snapshot_viewer_action.blockSignals(True)
                self.snapshot_viewer_action.setChecked(False)
                self.snapshot_viewer_action.blockSignals(False)

        if has_stack:
            try:
                self.load_snapshots(sample.snapshots)
                self.toggle_snapshot_viewer(True)
            except Exception:
                self.toggle_snapshot_viewer(False)

    def _ensure_sample_snapshots_loaded(self, sample: SampleN) -> Optional[np.ndarray]:
        if isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0:
            return sample.snapshots

        project_path = getattr(self.current_project, "path", None)
        asset_id = None
        if sample.snapshot_role and sample.asset_roles:
            asset_id = sample.asset_roles.get(sample.snapshot_role)

        if project_path and asset_id:
            try:
                store = sqlite_store.open_project(project_path)
                try:
                    data = sqlite_store.get_asset_bytes(store, asset_id)
                finally:
                    store.close()
            except Exception:
                data = None
            else:
                if data:
                    try:
                        buffer = io.BytesIO(data)
                        fmt = (sample.snapshot_format or "").lower()
                        if not fmt:
                            fmt = "npz" if data.startswith(b"PK") else "npy"
                        if fmt == "npz":
                            with np.load(buffer, allow_pickle=False) as npz_file:
                                stack = npz_file["stack"]
                        else:
                            stack = np.load(buffer, allow_pickle=False)
                        if isinstance(stack, np.ndarray):
                            sample.snapshots = stack
                        else:
                            sample.snapshots = np.stack(stack)
                        return sample.snapshots
                    except Exception:
                        log.debug(
                            "Failed to decode snapshot stack for %s",
                            sample.name,
                            exc_info=True,
                        )

        if sample.snapshot_path and Path(sample.snapshot_path).exists():
            try:
                frames, _ = load_tiff(sample.snapshot_path, metadata=False)
                if frames:
                    sample.snapshots = np.stack(frames)
                    return sample.snapshots
            except Exception:
                log.debug(
                    "Failed to load snapshot TIFF for %s", sample.name, exc_info=True
                )

        return None

    def open_samples_in_new_windows(self, samples):
        """Open each sample in its own window for side-by-side comparison."""
        if not hasattr(self, "compare_windows"):
            self.compare_windows = []
        for s in samples:
            win = VasoAnalyzerApp()
            win.show()
            sample_copy = s.copy()
            win.load_sample_into_view(sample_copy)
            self.compare_windows.append(win)

    def open_samples_in_dual_view(self, samples):
        """Display two samples stacked vertically in a single window."""
        if len(samples) != 2:
            QMessageBox.warning(self, "Dual View", "Please select exactly two N's.")
            return

        class DualViewWindow(QMainWindow):
            def __init__(self, parent, pair):
                super().__init__(parent)
                self.setWindowTitle("Dual View")
                self.views = []
                self._syncing = False
                self._cursor_guides = []
                self._pin_signatures: List[Tuple[float, ...]] = []

                splitter = QSplitter(Qt.Vertical, self)

                parent_style = (
                    parent.get_current_plot_style()
                    if parent is not None
                    else DEFAULT_STYLE.copy()
                )

                for index, sample in enumerate(pair):
                    view = VasoAnalyzerApp(check_updates=False)
                    view.setParent(splitter)
                    view.project_dock.hide()
                    splitter.addWidget(view)

                    sample_copy = sample.copy()
                    view.load_sample_into_view(sample_copy)
                    view.apply_plot_style(parent_style, persist=False)

                    self.views.append(view)
                    self._attach_sync_handlers(view, index)
                    self._init_cursor_guides(view)

                self._pin_signatures = [tuple()] * len(self.views)

                self.setCentralWidget(splitter)

                status = QStatusBar(self)
                self.setStatusBar(status)
                self.cursor_label = QLabel("Cursor: —")
                status.addWidget(self.cursor_label, 1)
                self.delta_label = QLabel(
                    "Δ metrics: add ≥2 inner-diameter pins in each view"
                )
                status.addPermanentWidget(self.delta_label, 0)
                self._refresh_metrics()

            # ----- dual view helpers ---------------------------------
            def _attach_sync_handlers(self, view, index: int) -> None:
                view.ax.callbacks.connect(
                    "xlim_changed",
                    lambda _ax: self._sync_xlim(index),
                )

                view.canvas.mpl_connect(
                    "motion_notify_event",
                    lambda event, idx=index: self._handle_motion(idx, event),
                )
                view.canvas.mpl_connect(
                    "figure_leave_event",
                    lambda _event: self._hide_cursor(),
                )
                view.canvas.mpl_connect(
                    "button_release_event",
                    lambda _event: self._update_metrics_if_changed(),
                )
                view.canvas.mpl_connect(
                    "draw_event",
                    lambda _event: self._update_metrics_if_changed(),
                )

            def _init_cursor_guides(self, view: "VasoAnalyzerApp") -> None:
                color = view.get_current_plot_style().get("event_color", "#d43d51")
                primary = view.ax.axvline(
                    view.ax.get_xlim()[0], color=color, alpha=0.35
                )
                primary.set_linestyle("--")
                primary.set_visible(False)
                secondary = None
                if view.ax2 is not None:
                    secondary = view.ax2.axvline(
                        view.ax2.get_xlim()[0], color=color, alpha=0.25
                    )
                    secondary.set_linestyle(":")
                    secondary.set_visible(False)
                self._cursor_guides.append({"primary": primary, "secondary": secondary})

            def _sync_xlim(self, source_index: int) -> None:
                if self._syncing or not self.views:
                    return
                source = self.views[source_index]
                xlim = source.ax.get_xlim()
                self._syncing = True
                try:
                    for idx, target in enumerate(self.views):
                        if idx == source_index:
                            continue
                        target.ax.set_xlim(xlim)
                        if target.ax2 is not None:
                            target.ax2.set_xlim(xlim)
                        target.canvas.draw_idle()
                        try:
                            target.update_scroll_slider()
                        except Exception:
                            pass
                finally:
                    self._syncing = False

            def _handle_motion(self, index: int, event) -> None:
                if event.inaxes is None or event.xdata is None:
                    self._hide_cursor()
                    return

                view = self.views[index]
                if event.inaxes not in (view.ax, view.ax2):
                    return

                x = event.xdata
                for guides, target in zip(self._cursor_guides, self.views):
                    guides["primary"].set_xdata((x, x))
                    guides["primary"].set_visible(True)
                    if guides["secondary"] is not None:
                        guides["secondary"].set_xdata((x, x))
                        guides["secondary"].set_visible(True)
                    target.canvas.draw_idle()

                self._update_cursor_label(x)

            def _hide_cursor(self) -> None:
                for guides, view in zip(self._cursor_guides, self.views):
                    guides["primary"].set_visible(False)
                    if guides["secondary"] is not None:
                        guides["secondary"].set_visible(False)
                    view.canvas.draw_idle()
                self.cursor_label.setText("Cursor: —")

            def _update_cursor_label(self, x: float) -> None:
                samples = [v.sample_inner_diameter(x) for v in self.views]
                if any(val is None for val in samples):
                    self.cursor_label.setText(f"Cursor: {x:.2f} s")
                    return
                delta = samples[0] - samples[1]
                self.cursor_label.setText(f"Cursor: {x:.2f} s · ΔID {delta:+.2f} µm")

            def _update_metrics_if_changed(self) -> None:
                signatures = []
                changed = False
                for idx, view in enumerate(self.views):
                    pins = tuple(
                        sorted(
                            round(marker.get_xdata()[0], 4)
                            for marker, _ in view.pinned_points
                            if getattr(marker, "trace_type", "inner") == "inner"
                        )
                    )
                    signatures.append(pins)
                    if pins != self._pin_signatures[idx]:
                        changed = True
                if changed:
                    self._pin_signatures = signatures
                    self._refresh_metrics()

            def _refresh_metrics(self) -> None:
                if not getattr(self, "delta_label", None):
                    return

                metrics = [view.compute_interval_metrics() for view in self.views]
                if any(m is None for m in metrics):
                    self.delta_label.setText(
                        "Δ metrics: add ≥2 inner-diameter pins in each view"
                    )
                    return

                delta_baseline = metrics[0]["baseline"] - metrics[1]["baseline"]
                delta_peak = metrics[0]["peak"] - metrics[1]["peak"]
                delta_auc = metrics[0]["auc"] - metrics[1]["auc"]
                window = metrics[0]["start"], metrics[0]["end"]

                self.delta_label.setText(
                    (
                        f"Window {window[0]:.2f}–{window[1]:.2f} s · "
                        f"Δbaseline {delta_baseline:+.2f} µm | "
                        f"Δpeak {delta_peak:+.2f} µm | "
                        f"ΔAUC {delta_auc:+.2f} µm·s"
                    )
                )

        self.dual_window = DualViewWindow(self, samples)
        self.dual_window.show()

    def show_project_context_menu(self, pos):
        item = self.project_tree.itemAt(pos)
        menu = QMenu()

        selected_samples = [
            it.data(0, Qt.UserRole)
            for it in self.project_tree.selectedItems()
            if isinstance(it.data(0, Qt.UserRole), SampleN)
        ]
        open_act = None
        dual_act = None
        if selected_samples:
            open_act = menu.addAction("Open Selected N's…")
            if len(selected_samples) == 2:
                dual_act = menu.addAction("Open Dual View…")

        if item is None:
            add_exp = menu.addAction("Add Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_exp:
                self.add_experiment()
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
            return

        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, Project):
            add_exp = menu.addAction("Add Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_exp:
                self.add_experiment()
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, Experiment):
            add_n = menu.addAction("Add N")
            del_exp = menu.addAction("Delete Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_n:
                self.add_sample(obj)
            elif action == del_exp:
                self.delete_experiment(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, SampleN):
            load_data = menu.addAction("Load Data Into N…")
            save_n = menu.addAction("Save N As…")
            del_n = menu.addAction("Delete N")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == load_data:
                self.load_data_into_sample(obj)
            elif action == save_n:
                self.save_sample_as(obj)
            elif action == del_n:
                self.delete_sample(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)

    def add_experiment(self):
        if not self.current_project:
            return
        name, ok = QInputDialog.getText(self, "Experiment Name", "Name:")
        if ok and name:
            exp = Experiment(name=name)
            self.current_project.experiments.append(exp)
            self.current_experiment = exp
            self.refresh_project_tree()

    def delete_experiment(self, experiment: Experiment) -> None:
        if (
            not self.current_project
            or experiment not in self.current_project.experiments
        ):
            return

        sample_count = len(experiment.samples)
        message = "Delete this experiment?"
        if sample_count:
            message = (
                f"Delete experiment '{experiment.name}' and its {sample_count} sample(s)?\n"
                "This action cannot be undone."
            )

        confirm = QMessageBox.question(
            self,
            "Delete Experiment",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        for sample in experiment.samples:
            self.project_state.pop(id(sample), None)
            if self.current_sample is sample:
                self.current_sample = None

        self.current_project.experiments.remove(experiment)

        if self.current_experiment is experiment:
            self.current_experiment = None

        self.refresh_project_tree()
        self.mark_session_dirty()
        self.auto_save_project(reason="delete_experiment")
        self._update_home_resume_button()
        self._update_metadata_panel(self.current_project)

    def add_sample(self, experiment):
        nname, ok = QInputDialog.getText(self, "Sample Name", "Name:")
        if ok and nname:
            experiment.samples.append(SampleN(name=nname))
            self.refresh_project_tree()

    def add_sample_to_current_experiment(self):
        if not self.current_experiment:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment first.",
            )
            return
        self.add_sample(self.current_experiment)

    def add_data_to_current_experiment(self):
        if not self.current_experiment:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment first.",
            )
            return

        nname, ok = QInputDialog.getText(self, "Sample Name", "Name:")
        if not ok or not nname:
            return
        sample = SampleN(name=nname)
        self.current_experiment.samples.append(sample)
        self.refresh_project_tree()
        self.load_data_into_sample(sample)
        self.statusBar().showMessage(
            f"\u2713 {nname} loaded into Experiment '{self.current_experiment.name}'",
            3000,
        )
        if self.current_project and self.current_project.path:
            save_project(self.current_project, self.current_project.path)

    def load_data_into_sample(self, sample: SampleN):
        log.info("Loading data into sample %s", sample.name)
        trace_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not trace_path:
            return

        try:
            df = self.load_trace_and_event_files(trace_path)
        except Exception:
            return

        trace_obj = Path(trace_path).expanduser().resolve(strict=False)
        self._update_sample_link_metadata(sample, "trace", trace_obj)
        sample.trace_data = df
        event_path = find_matching_event_file(trace_path)
        if event_path and os.path.exists(event_path):
            event_obj = Path(event_path).expanduser().resolve(strict=False)
            self._update_sample_link_metadata(sample, "events", event_obj)

        self.refresh_project_tree()

        log.info("Sample %s updated with data", sample.name)

        if self.current_project and self.current_project.path:
            save_project(self.current_project, self.current_project.path)

    def delete_sample(self, sample: SampleN):
        if not self.current_project:
            return
        for exp in self.current_project.experiments:
            if sample in exp.samples:
                exp.samples.remove(sample)
                if self.current_sample is sample:
                    self.current_sample = None
                self.refresh_project_tree()
                if self.current_project.path:
                    save_project_file(self.current_project, self.current_project.path)
                break

    def save_sample_as(self, sample):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Sample", f"{sample.name}.vaso", "Vaso Sample (*.vaso)"
        )
        if path:
            tmp_proj = Project(
                name=sample.name, experiments=[Experiment(name="exp", samples=[sample])]
            )
            save_project(tmp_proj, path)

    def _wrap_views(self):
        """Wrap the main stacked widget in another QStackedWidget."""

        self.modeStack = QStackedWidget(self)
        self.modeStack.addWidget(self.stack)

        self.setCentralWidget(self.modeStack)
        self.modeStack.setCurrentIndex(0)

    def update_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
        else:
            for path in self.recent_files:
                action = QAction(os.path.basename(path), self)
                action.setToolTip(path)
                action.triggered.connect(partial(self.load_trace_and_events, path))
                self.recent_menu.addAction(action)

        self._refresh_home_recent()

    def icon_path(self, filename):
        """Return absolute path to an icon shipped with the application."""
        from utils import resource_path

        return resource_path("icons", filename)

    def _brand_icon_path(self, extension: str) -> str:
        """Return the absolute path to the main VasoAnalyzer app icon."""
        from utils import resource_path

        if not extension:
            return ""

        filename = f"VasoAnalyzerIcon.{extension}"
        search_roots = [
            ("icons", filename),
            ("vasoanalyzer", filename),
            ("src", "vasoanalyzer", filename),
        ]

        for parts in search_roots:
            candidate = resource_path(*parts)
            if os.path.exists(candidate):
                return candidate

        return ""

    def text_icon(self, text: str) -> QIcon:
        """Return a simple text-based QIcon used for toolbar buttons."""
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setPen(QColor(0, 0, 0))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, text)
        painter.end()
        return QIcon(pix)

    def sync_slider_with_plot(self, event=None):
        if self.trace_data is None:
            return

        primary_ax = (
            self.plot_host.primary_axis() if hasattr(self, "plot_host") else None
        )
        if primary_ax is None and self.ax is not None:
            primary_ax = self.ax
        if primary_ax is None:
            return

        if self.trace_model is not None and self.trace_model.time_full.size:
            time_full = self.trace_model.time_full
            tmin, tmax = float(time_full[0]), float(time_full[-1])
        else:
            full_t = self.trace_data["Time (s)"]
            tmin, tmax = float(full_t.min()), float(full_t.max())

        xmin, xmax = primary_ax.get_xlim()
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

    def _assign_menu_role(self, action, role_name):
        menu_role_enum = getattr(QAction, "MenuRole", None)
        menu_role = None
        if menu_role_enum is not None and hasattr(menu_role_enum, role_name):
            menu_role = getattr(menu_role_enum, role_name)
        elif hasattr(QAction, role_name):
            menu_role = getattr(QAction, role_name)
        if menu_role is not None:
            action.setMenuRole(menu_role)

    def create_menubar(self):
        menubar = self.menuBar()
        menubar.clear()

        if hasattr(menubar, "setNativeMenuBar"):
            menubar.setNativeMenuBar(sys.platform == "darwin")

        self._build_file_menu(menubar)
        self._build_edit_menu(menubar)
        self._build_view_menu(menubar)
        self._build_tools_menu(menubar)
        self._build_help_menu(menubar)

    def _build_file_menu(self, menubar):
        file_menu = menubar.addMenu("&File")

        # Project workspace submenu
        project_menu = file_menu.addMenu("Project")

        self.action_new_project = QAction("New Project…", self)
        self.action_new_project.setShortcut("Ctrl+Shift+N")
        self.action_new_project.triggered.connect(self.new_project)
        project_menu.addAction(self.action_new_project)

        self.action_open_project = QAction("Open Project…", self)
        self.action_open_project.setShortcut("Ctrl+Shift+O")
        self.action_open_project.triggered.connect(self.open_project_file)
        project_menu.addAction(self.action_open_project)

        self.recent_projects_menu = project_menu.addMenu("Recent Projects")
        self.build_recent_projects_menu()

        project_menu.addSeparator()

        self.action_save_project = QAction("Save Project", self)
        self.action_save_project.setShortcut("Ctrl+Shift+S")
        self.action_save_project.triggered.connect(self.save_project_file)
        project_menu.addAction(self.action_save_project)

        self.action_save_project_as = QAction("Save Project As…", self)
        self.action_save_project_as.triggered.connect(self.save_project_file_as)
        project_menu.addAction(self.action_save_project_as)

        project_menu.addSeparator()

        self.action_add_experiment = QAction("Add Experiment", self)
        self.action_add_experiment.triggered.connect(self.add_experiment)
        project_menu.addAction(self.action_add_experiment)

        self.action_add_sample = QAction("Add N", self)
        self.action_add_sample.triggered.connect(self.add_sample_to_current_experiment)
        project_menu.addAction(self.action_add_sample)

        file_menu.addSection("Session Data")

        self.action_new = QAction("Start New Analysis…", self)
        self.action_new.setShortcut(QKeySequence.New)
        self.action_new.triggered.connect(self.start_new_analysis)
        file_menu.addAction(self.action_new)

        self.action_open_trace = QAction("Open Trace & Events…", self)
        self.action_open_trace.setShortcut(QKeySequence.Open)
        self.action_open_trace.triggered.connect(self._handle_load_trace)
        file_menu.addAction(self.action_open_trace)

        self.action_open_tiff = QAction("Open Result TIFF…", self)
        self.action_open_tiff.setShortcut("Ctrl+Shift+T")
        self.action_open_tiff.triggered.connect(self.load_snapshot)
        file_menu.addAction(self.action_open_tiff)

        self.recent_menu = file_menu.addMenu("Recent Files")
        self.update_recent_files_menu()

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("Export")

        self.action_export_tiff = QAction("High-Res Plot…", self)
        self.action_export_tiff.triggered.connect(self.export_high_res_plot)
        export_menu.addAction(self.action_export_tiff)

        self.action_export_bundle = QAction("Project Bundle (.vasopack)…", self)
        self.action_export_bundle.triggered.connect(self.export_project_bundle_action)
        export_menu.addAction(self.action_export_bundle)

        self.action_export_csv = QAction("Events as CSV…", self)
        self.action_export_csv.triggered.connect(self.auto_export_table)
        export_menu.addAction(self.action_export_csv)

        self.action_export_excel = QAction("To Excel Template…", self)
        self.action_export_excel.triggered.connect(self.open_excel_mapping_dialog)
        export_menu.addAction(self.action_export_excel)

        file_menu.addSeparator()

        self.action_preferences = QAction("Preferences…", self)
        self.action_preferences.setShortcut("Ctrl+,")
        self.action_preferences.triggered.connect(self.open_preferences_dialog)
        self._assign_menu_role(self.action_preferences, "PreferencesRole")
        file_menu.addAction(self.action_preferences)

        quit_text = "Quit VasoAnalyzer" if sys.platform == "darwin" else "Exit"
        self.action_exit = QAction(quit_text, self)
        self.action_exit.setShortcut(QKeySequence.Quit)
        self.action_exit.triggered.connect(self.close)
        self._assign_menu_role(self.action_exit, "QuitRole")
        file_menu.addAction(self.action_exit)

    def _build_edit_menu(self, menubar):
        edit_menu = menubar.addMenu("&Edit")

        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(undo)

        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(redo)

        edit_menu.addSeparator()

        clear_pins = QAction("Clear All Pins", self)
        clear_pins.triggered.connect(self.clear_all_pins)
        edit_menu.addAction(clear_pins)

        clear_events = QAction("Clear All Events", self)
        clear_events.triggered.connect(self.clear_current_session)
        edit_menu.addAction(clear_events)

    def _build_view_menu(self, menubar):
        view_menu = menubar.addMenu("&View")

        home_act = QAction("Show Home Screen", self)
        home_act.setShortcut("Ctrl+Shift+H")
        home_act.triggered.connect(self.show_home_screen)
        view_menu.addAction(home_act)

        view_menu.addSeparator()

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

        anno_menu = view_menu.addMenu("Annotations")
        ev_lines = QAction("Event Lines", self, checkable=True, checked=True)
        ev_lbls = QAction("Event Labels", self, checkable=True, checked=True)
        pin_lbls = QAction("Pinned Labels", self, checkable=True, checked=True)
        frame_mk = QAction("Frame Marker", self, checkable=True, checked=True)
        ev_lines.triggered.connect(lambda _: self.toggle_annotation("lines"))
        ev_lbls.triggered.connect(lambda _: self.toggle_annotation("evt_labels"))
        pin_lbls.triggered.connect(lambda _: self.toggle_annotation("pin_labels"))
        frame_mk.triggered.connect(lambda _: self.toggle_annotation("frame_marker"))
        for action in (ev_lines, ev_lbls, pin_lbls, frame_mk):
            anno_menu.addAction(action)
        self.menu_event_lines_action = ev_lines
        self.menu_event_labels_action = ev_lbls

        view_menu.addSeparator()

        self.showhide_menu = view_menu.addMenu("Panels")
        evt_tbl = QAction("Event Table", self, checkable=True, checked=True)
        snap_vw = QAction("Snapshot Viewer", self, checkable=True, checked=False)
        evt_tbl.triggered.connect(self.toggle_event_table)
        snap_vw.triggered.connect(self.toggle_snapshot_viewer)
        self.showhide_menu.addAction(evt_tbl)
        self.showhide_menu.addAction(snap_vw)
        self.snapshot_viewer_action = snap_vw

        shortcut = "Meta+M" if sys.platform == "darwin" else "Ctrl+M"
        self.action_snapshot_metadata = QAction("Metadata…", self)
        self.action_snapshot_metadata.setShortcut(shortcut)
        self.action_snapshot_metadata.setCheckable(True)
        self.action_snapshot_metadata.setEnabled(False)
        self.action_snapshot_metadata.triggered.connect(
            lambda checked: self.set_snapshot_metadata_visible(bool(checked))
        )
        view_menu.addAction(self.action_snapshot_metadata)

        self.id_toggle_act = QAction("Inner", self, checkable=True, checked=True)
        self.id_toggle_act.setStatusTip("Show inner diameter trace")
        self.id_toggle_act.setToolTip("Toggle inner diameter trace")
        self.od_toggle_act = QAction("Outer", self, checkable=True, checked=True)
        self.od_toggle_act.setStatusTip("Show outer diameter trace")
        self.od_toggle_act.setToolTip("Toggle outer diameter trace")
        self.id_toggle_act.setShortcut("I")
        self.od_toggle_act.setShortcut("O")
        self.id_toggle_act.setIcon(QIcon(self.icon_path("ID.svg")))
        self.od_toggle_act.setIcon(QIcon(self.icon_path("OD.svg")))
        self.id_toggle_act.toggled.connect(self.toggle_inner_diameter)
        self.od_toggle_act.toggled.connect(self.toggle_outer_diameter)
        self.showhide_menu.addAction(self.id_toggle_act)
        self.showhide_menu.addAction(self.od_toggle_act)

        view_menu.addSeparator()

        fs_act = QAction("Full Screen", self)
        fs_act.setShortcut("F11")
        fs_act.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fs_act)

    def _build_tools_menu(self, menubar):
        tools_menu = menubar.addMenu("&Tools")

        self.action_map_excel = QAction("Map Events to Excel…", self)
        self.action_map_excel.triggered.connect(self.open_excel_mapping_dialog)
        tools_menu.addAction(self.action_map_excel)

        self.action_plot_settings = QAction("Plot Settings…", self)
        self.action_plot_settings.triggered.connect(
            self.open_unified_plot_settings_dialog
        )
        tools_menu.addAction(self.action_plot_settings)

        layout_act = QAction("Subplot Layout…", self)
        layout_act.triggered.connect(self.open_subplot_layout_dialog)
        tools_menu.addAction(layout_act)

        tools_menu.addSeparator()

        self.action_relink_assets = QAction("Relink Missing Files…", self)
        self.action_relink_assets.setEnabled(False)
        self.action_relink_assets.triggered.connect(self.show_relink_dialog)
        tools_menu.addAction(self.action_relink_assets)

    def _build_help_menu(self, menubar):
        help_menu = menubar.addMenu("&Help")

        self.action_about = QAction("About VasoAnalyzer", self)
        self.action_about.triggered.connect(self.show_about)
        self._assign_menu_role(self.action_about, "AboutRole")
        help_menu.addAction(self.action_about)

        self.action_user_manual = QAction("User Manual…", self)
        self.action_user_manual.triggered.connect(self.open_user_manual)
        help_menu.addAction(self.action_user_manual)

        guide_act = QAction("Welcome Guide…", self)
        guide_act.setShortcut("Ctrl+/")
        guide_act.triggered.connect(lambda: self.show_welcome_guide(modal=False))
        help_menu.addAction(guide_act)

        tut_act = QAction("Quick Start Tutorial…", self)
        tut_act.triggered.connect(self.show_tutorial)
        help_menu.addAction(tut_act)

        help_menu.addSeparator()

        act_update = QAction("Check for Updates", self)
        act_update.triggered.connect(self.check_for_updates)
        help_menu.addAction(act_update)

        act_keys = QAction("Keyboard Shortcuts…", self)
        act_keys.triggered.connect(self.show_shortcuts)
        help_menu.addAction(act_keys)

        act_bug = QAction("Report a Bug…", self)
        act_bug.triggered.connect(
            lambda: webbrowser.open("https://github.com/vr-oj/VasoAnalyzer/issues/new")
        )
        help_menu.addAction(act_bug)

        act_rel = QAction("Release Notes…", self)
        act_rel.triggered.connect(self.show_release_notes)
        help_menu.addAction(act_rel)

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

    def build_recent_projects_menu(self):
        if (
            not hasattr(self, "recent_projects_menu")
            or self.recent_projects_menu is None
        ):
            return
        self.recent_projects_menu.clear()

        if not self.recent_projects:
            self.recent_projects_menu.addAction("No recent projects").setEnabled(False)
            return

        for path in self.recent_projects:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.open_recent_project, path))
            self.recent_projects_menu.addAction(action)

        self.recent_projects_menu.addSeparator()
        clear_action = QAction("Clear Recent Projects", self)
        clear_action.triggered.connect(self.clear_recent_projects)
        self.recent_projects_menu.addAction(clear_action)

    def open_preferences_dialog(self):
        QMessageBox.information(
            self, "Preferences", "Preferences will be implemented soon(ish)."
        )

    def clear_all_pins(self):
        for marker, label in self.pinned_points:
            marker.remove()
            label.remove()
        self.pinned_points.clear()
        # Apply current (or default) font style after rebuilding the plot
        self.apply_plot_style(self.get_current_plot_style(), persist=False)
        self.mark_session_dirty()

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
                "plot_style": self.get_current_plot_style(),
            }

            pickle_path = os.path.join(
                os.path.abspath(self.trace_file_path or "."),
                "tracePlot_output.fig.json",
            )
            with open(pickle_path, "w", encoding="utf-8") as f:
                json.dump(state, f)

            log.info("Session state saved to:\n%s", pickle_path)
        except Exception as e:
            log.error("Failed to save session state:\n%s", e)

            with open(PREVIOUS_PLOT_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f)

    # Update reopen_previous_plot to reload all elements
    def reopen_previous_plot(self):
        if not os.path.exists(PREVIOUS_PLOT_PATH):
            QMessageBox.warning(
                self, "No Previous Plot", "No previously saved plot was found."
            )
            return

        self.load_pickle_session(PREVIOUS_PLOT_PATH)

    def rebuild_top_row_with_new_toolbar(self):
        if not hasattr(self, "main_layout"):
            return

        if hasattr(self, "header_frame"):
            self.main_layout.removeWidget(self.header_frame)
            self.header_frame.deleteLater()

        self.header_frame = self._build_data_header()
        self.main_layout.insertWidget(0, self.header_frame)

    def load_recent_files(self):
        recent = self.settings.value("recentFiles", [])
        if recent is None:
            recent = []
        self.recent_files = recent

    def load_recent_projects(self):
        recent = self.settings.value("recentProjects", [])
        if recent is None:
            recent = []
        self.recent_projects = recent

    def update_recent_projects(self, path):
        if path not in self.recent_projects:
            self.recent_projects = [path] + self.recent_projects[:4]
            self.settings.setValue("recentProjects", self.recent_projects)
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def save_recent_projects(self):
        self.settings.setValue("recentProjects", self.recent_projects)

    def remove_recent_project(self, path: str) -> None:
        if path not in self.recent_projects:
            return
        self.recent_projects = [p for p in self.recent_projects if p != path]
        self.save_recent_projects()
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def clear_recent_projects(self):
        self.recent_projects = []
        self.save_recent_projects()
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def open_recent_project(self, path):
        try:
            self._clear_canvas_and_table()
            project = load_project(path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Project Load Error",
                f"Could not open project:\n{e}",
            )
            return
        self._replace_current_project(project)
        self.apply_ui_state(getattr(self.current_project, "ui_state", None))
        self.refresh_project_tree()
        self.statusBar().showMessage(
            f"\u2713 Project loaded: {self.current_project.name}", 3000
        )
        self.update_recent_projects(path)
        if (
            self.current_project.experiments
            and self.current_project.experiments[0].samples
        ):
            first_sample = self.current_project.experiments[0].samples[0]
            self.load_sample_into_view(first_sample)

    def _start_update_check(self, *, silent: bool = False) -> None:
        if self._update_check_in_progress or self._update_checker.is_running:
            return

        if not silent:
            self.statusBar().showMessage("Checking for updates…", 3000)
        started = self._update_checker.start(f"v{APP_VERSION}", silent=silent)
        if started:
            self._update_check_in_progress = True

    def check_for_updates_at_startup(self) -> None:
        self._start_update_check(silent=True)

    def check_for_updates(self) -> None:
        self._start_update_check(silent=False)

    def _on_update_check_completed(
        self, silent: bool, latest: object, error: object
    ) -> None:
        self._update_check_in_progress = False

        if error:
            if isinstance(error, BaseException):
                log.warning("Update check failed: %s", error)
            else:
                log.warning("Update check failed: %r", error)
            if not silent:
                QMessageBox.warning(
                    self,
                    "Update Check Failed",
                    "Could not determine whether a new version is available.\n"
                    "Please check your network connection and try again.",
                )
            return

        latest_str = latest if isinstance(latest, str) and latest else None
        if latest_str:
            QMessageBox.information(
                self,
                "Update Available",
                (
                    f"A new version ({latest_str}) of VasoAnalyzer is available!\n"
                    "Visit GitHub to download the latest release."
                ),
            )
            self.statusBar().showMessage("Update available", 3000)
        elif not silent:
            QMessageBox.information(
                self,
                "Up to Date",
                f"You are running the latest release (v{APP_VERSION}).",
            )
            self.statusBar().showMessage("Up to date", 3000)

    @property
    def trace_loader(self):
        from vasoanalyzer.io.traces import load_trace

        return load_trace

    @property
    def event_loader(self):
        from vasoanalyzer.io.events import load_events

        return load_events

    def reset_to_full_view(self):
        """Restore the plot to the stored full-view limits."""
        if self.xlim_full is None:
            self.xlim_full = self.ax.get_xlim()
        if self.ylim_full is None:
            self.ylim_full = self.ax.get_ylim()

        if self.xlim_full is not None:
            self._apply_time_window(self.xlim_full)
        self.ax.set_ylim(self.ylim_full)
        self.canvas.draw()

    def reset_view(self):
        self.reset_to_full_view()

    def fit_to_data(self):
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def zoom_to_selection(self):
        # if you later add box‐select, you’ll grab the extents here;
        # for now just stub it to full‐data
        self.fit_to_data()

    def zoom_out(self, factor: float = 1.5, x_only: bool = True):
        """Zoom out by ``factor`` around the current view's center.

        ``factor`` is relative to the current axis span. Limits are clamped to
        the full data range so repeated zooming never drifts beyond the
        available data. This ensures zooming always begins from the current
        view rather than an arbitrary level.
        """

        if self.xlim_full is None:
            self.xlim_full = self.ax.get_xlim()
        if self.ylim_full is None:
            self.ylim_full = self.ax.get_ylim()

        xmin, xmax = self.ax.get_xlim()
        ymin, ymax = self.ax.get_ylim()

        x_center = (xmin + xmax) / 2
        y_center = (ymin + ymax) / 2

        x_half = (xmax - xmin) * factor / 2
        y_half = (ymax - ymin) * factor / 2

        new_xmin, new_xmax = x_center - x_half, x_center + x_half
        new_ymin, new_ymax = y_center - y_half, y_center + y_half

        if self.xlim_full is not None:
            new_xmin = max(new_xmin, self.xlim_full[0])
            new_xmax = min(new_xmax, self.xlim_full[1])
        if self.ylim_full is not None:
            new_ymin = max(new_ymin, self.ylim_full[0])
            new_ymax = min(new_ymax, self.ylim_full[1])

        self._apply_time_window((new_xmin, new_xmax))
        if not x_only:
            self.ax.set_ylim(new_ymin, new_ymax)
        self.canvas.draw_idle()
        self.update_scroll_slider()

    def fit_x_full(self):
        if self.trace_data is None or self.ax is None:
            return
        if (
            self.trace_model is not None
            and getattr(self.trace_model, "time_full", None) is not None
        ):
            times = self.trace_model.time_full
            if getattr(times, "size", 0):
                span = (float(times[0]), float(times[-1]))
            else:
                span = self.ax.get_xlim()
        else:
            series = self.trace_data.get("Time (s)")
            if series is None or series.empty:
                return
            values = series.to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size == 0:
                return
            span = (float(values.min()), float(values.max()))
        self._apply_time_window(span)
        self.update_scroll_slider()
        self.canvas.draw_idle()

    def fit_y_in_current_x(self):
        if self.trace_data is None or self.ax is None:
            return
        x0, x1 = self.ax.get_xlim()
        if not np.isfinite(x0) or not np.isfinite(x1) or x0 == x1:
            return
        times = self.trace_data["Time (s)"].to_numpy(dtype=float)
        mask = (times >= x0) & (times <= x1)
        inner = self.trace_data["Inner Diameter"].to_numpy(dtype=float)
        y_min, y_max = self._value_range(inner, mask)
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return
        pad = max((y_max - y_min) * 0.05, 0.5)
        self.ax.set_ylim(y_min - pad, y_max + pad)

        if self.ax2 is not None and "Outer Diameter" in self.trace_data.columns:
            outer = self.trace_data["Outer Diameter"].to_numpy(dtype=float)
            o_min, o_max = self._value_range(outer, mask)
            if np.isfinite(o_min) and np.isfinite(o_max):
                opad = max((o_max - o_min) * 0.05, 0.5)
                self.ax2.set_ylim(o_min - opad, o_max + opad)
        self.canvas.draw_idle()

    def _value_range(self, values: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
        if values.size == 0:
            return float("nan"), float("nan")
        subset = values
        if (
            isinstance(mask, np.ndarray)
            and mask.dtype == bool
            and mask.size == values.size
        ):
            if mask.any():
                subset = values[mask]
        subset = subset[np.isfinite(subset)]
        if subset.size == 0:
            subset = values[np.isfinite(values)]
        if subset.size == 0:
            return float("nan"), float("nan")
        return float(np.min(subset)), float(np.max(subset))

    def copy_figure_to_clipboard(self):
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        pix = canvas.grab()
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(pix)
        self.statusBar().showMessage("Plot copied to clipboard", 2000)

    def toggle_annotation(self, kind: str):
        if kind == "lines":
            new_state = not self._event_lines_visible
            self._event_lines_visible = new_state
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_event_lines_visible(new_state)
            else:
                self._toggle_event_lines_legacy(new_state)
            self._sync_event_controls()
        elif kind == "evt_labels":
            if self._event_label_mode == "none":
                self._set_event_label_mode("auto")
            else:
                self._set_event_label_mode("none")
        elif kind == "pin_labels":
            for marker, lbl in self.pinned_points:
                lbl.set_visible(not lbl.get_visible())
        elif kind == "frame_marker":
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                self._time_cursor_visible = not self._time_cursor_visible
                plot_host.set_time_cursor(
                    self._time_cursor_time,
                    visible=self._time_cursor_visible,
                )
            else:
                markers = getattr(self, "slider_markers", None) or {}
                lines = [line for line in markers.values() if line.axes is not None]
                if lines:
                    vis = not lines[0].get_visible()
                    for line in lines:
                        line.set_visible(vis)
        self.canvas.draw_idle()

    def _refresh_event_annotation_artists(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            self.event_text_objects = []
            self._apply_current_style()
            return
        getter = getattr(plot_host, "annotation_text_objects", None)
        if callable(getter):
            self.event_text_objects = list(getter())
        else:
            self.event_text_objects = []
        self._apply_current_style()

    def _apply_current_style(self, *, redraw: bool = False) -> None:
        """Reapply the current plot style to reflect updated artists."""

        if not hasattr(self, "ax") or self.ax is None:
            return
        manager = self._ensure_style_manager()
        main_line = self.trace_line
        if main_line is None and self.ax.lines:
            main_line = self.ax.lines[0]
        x_axis = self._x_axis_for_style()
        manager.apply(
            ax=self.ax,
            ax_secondary=self.ax2,
            x_axis=x_axis,
            event_text_objects=self.event_text_objects,
            pinned_points=self.pinned_points,
            main_line=main_line,
            od_line=self.od_line,
        )
        style_snapshot = manager.style()
        self._event_highlight_color = style_snapshot.get(
            "event_highlight_color",
            DEFAULT_STYLE.get("event_highlight_color", self._event_highlight_color),
        )
        self._event_highlight_base_alpha = max(
            0.0,
            min(
                float(
                    style_snapshot.get(
                        "event_highlight_alpha",
                        DEFAULT_STYLE.get(
                            "event_highlight_alpha", self._event_highlight_base_alpha
                        ),
                    )
                ),
                1.0,
            ),
        )
        self._event_highlight_duration_ms = max(
            0,
            int(
                style_snapshot.get(
                    "event_highlight_duration_ms",
                    DEFAULT_STYLE.get(
                        "event_highlight_duration_ms",
                        self._event_highlight_duration_ms,
                    ),
                )
            ),
        )
        self._event_highlight_elapsed_ms = 0
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_event_highlight_style(
                color=self._event_highlight_color,
                alpha=self._event_highlight_base_alpha,
            )
        if redraw:
            self.canvas.draw_idle()

    def _on_event_rows_changed(self) -> None:
        """Sync cached event state after the table model mutates."""

        controller = getattr(self, "event_table_controller", None)
        if controller is None:
            return
        try:
            rows = controller.rows
        except Exception:
            rows = []
        self.event_table_data = [tuple(row) for row in rows]
        self._sync_event_data_from_table()

    def _sync_event_data_from_table(self) -> None:
        """Recompute cached event arrays, metadata, and annotation entries."""

        rows = list(getattr(self, "event_table_data", []) or [])
        controller = getattr(self, "event_table_controller", None)
        if controller is not None and hasattr(controller, "has_outer"):
            has_outer = bool(controller.has_outer)
        else:
            has_outer = False

        if not rows:
            self.event_labels = []
            self.event_times = []
            self.event_frames = []
            self.event_annotations = []
            self.event_metadata = []
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_annotation_entries([])
                self._refresh_event_annotation_artists()
            else:
                self.event_text_objects = []
                self._apply_current_style()
            return

        new_labels: list[str] = []
        new_times: list[float] = []
        new_frames: list[Optional[int]] = []
        annotations: list[AnnotationSpec] = []
        metadata: list[dict[str, Any]] = []

        for row in rows:
            if not row or len(row) < 2:
                continue
            label_raw = row[0]
            label = str(label_raw) if label_raw is not None else ""
            try:
                time_val = float(row[1])
            except (TypeError, ValueError):
                log.debug(
                    "Skipping event annotation update due to invalid time: %s", row[1]
                )
                return

            id_val = None
            try:
                id_val = float(row[2])
            except (TypeError, ValueError, IndexError):
                id_val = None

            od_val = None
            if has_outer and len(row) > 3:
                try:
                    od_val = float(row[3])
                except (TypeError, ValueError):
                    od_val = None

            if has_outer:
                frame_source = row[4] if len(row) > 4 else None
            else:
                frame_source = row[3] if len(row) > 3 else None
            try:
                frame_val = int(frame_source) if frame_source is not None else None
            except (TypeError, ValueError):
                frame_val = None

            new_labels.append(label)
            new_times.append(time_val)
            new_frames.append(frame_val)
            annotations.append(AnnotationSpec(time_s=time_val, label=label))

            tooltip_parts = [label, f"{time_val:.2f} s"]
            if id_val is not None and np.isfinite(id_val):
                tooltip_parts.append(f"ID {id_val:.2f} µm")
            if od_val is not None and np.isfinite(od_val):
                tooltip_parts.append(f"OD {od_val:.2f} µm")
            metadata.append(
                {
                    "time": time_val,
                    "label": label,
                    "tooltip": " · ".join(part for part in tooltip_parts if part),
                }
            )

        self.event_labels = new_labels
        self.event_times = new_times
        self.event_frames = new_frames
        self.event_annotations = annotations
        self.event_metadata = metadata

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            visible_entries = annotations if self._annotation_lane_visible else []
            plot_host.set_annotation_entries(visible_entries)
            self._refresh_event_annotation_artists()
        else:
            self.event_text_objects = []
            self._apply_current_style()

    def toggle_event_table(self, checked: bool):
        self.event_table.setVisible(checked)

    def toggle_snapshot_viewer(self, checked: bool):
        if (
            checked
            and not self.snapshot_frames
            and isinstance(self.current_sample, SampleN)
        ):
            stack = self._ensure_sample_snapshots_loaded(self.current_sample)
            if stack is not None:
                try:
                    self.load_snapshots(stack)
                except Exception:
                    log.debug("Failed to initialise snapshot viewer", exc_info=True)
                    self.snapshot_frames = []
        has_snapshots = bool(self.snapshot_frames)
        should_show = bool(checked) and has_snapshots

        if (
            self.snapshot_viewer_action
            and self.snapshot_viewer_action.isChecked() != should_show
        ):
            self.snapshot_viewer_action.blockSignals(True)
            self.snapshot_viewer_action.setChecked(should_show)
            self.snapshot_viewer_action.blockSignals(False)

        if self.snapshot_card:
            self.snapshot_card.setVisible(should_show)

        self.snapshot_label.setVisible(should_show)
        self.slider.setVisible(should_show)
        self.snapshot_controls.setVisible(should_show)

        if not should_show:
            self.set_snapshot_metadata_visible(False)

        self._update_metadata_button_state()

    def _outer_channel_available(self) -> bool:
        if self.trace_data is None:
            return False
        if "Outer Diameter" not in self.trace_data.columns:
            return False
        series = self.trace_data["Outer Diameter"]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _current_channel_presence(self) -> tuple[bool, bool]:
        if not hasattr(self, "plot_host"):
            return (False, False)
        specs = self.plot_host.channel_specs()
        ids = {spec.track_id for spec in specs} if specs else set()
        return ("inner" in ids, "outer" in ids)

    def _ensure_valid_channel_selection(
        self,
        inner_on: bool,
        outer_on: bool,
        *,
        toggled: str,
        outer_supported: bool,
    ) -> tuple[bool, bool]:
        inner_on = bool(inner_on)
        outer_on = bool(outer_on and outer_supported)
        if not inner_on and not outer_on:
            if toggled == "inner" and outer_supported:
                outer_on = True
            else:
                inner_on = True
        return inner_on, outer_on

    def _apply_toggle_state(
        self,
        inner_on: bool,
        outer_on: bool,
        *,
        outer_supported: Optional[bool] = None,
    ) -> None:
        if outer_supported is None:
            outer_supported = self._outer_channel_available()
        if self.id_toggle_act is not None:
            if self.id_toggle_act.isChecked() != inner_on:
                self.id_toggle_act.blockSignals(True)
                self.id_toggle_act.setChecked(inner_on)
                self.id_toggle_act.blockSignals(False)
        if self.od_toggle_act is not None:
            self.od_toggle_act.setEnabled(outer_supported)
            desired_checked = outer_on if outer_supported else False
            if self.od_toggle_act.isChecked() != desired_checked:
                self.od_toggle_act.blockSignals(True)
                self.od_toggle_act.setChecked(desired_checked)
                self.od_toggle_act.blockSignals(False)

    def _rebuild_channel_layout(
        self, inner_on: bool, outer_on: bool, *, redraw: bool = True
    ) -> None:
        specs: list[ChannelTrackSpec] = []
        if inner_on:
            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )
        if outer_on:
            specs.append(
                ChannelTrackSpec(
                    track_id="outer",
                    component="outer",
                    label="Outer Diameter (µm)",
                    height_ratio=1.0,
                )
            )
        if not specs:
            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )

        self._unbind_primary_axis_callbacks()
        self.plot_host.ensure_channels(specs)

        inner_track = self.plot_host.track("inner") if inner_on else None
        outer_track = self.plot_host.track("outer") if outer_on else None

        primary_track = inner_track or outer_track
        self.ax = primary_track.ax if primary_track else None
        self.ax2 = outer_track.ax if inner_track and outer_track else None
        self._bind_primary_axis_callbacks()
        self._init_hover_artists()

        self.trace_line = (
            inner_track.primary_line
            if inner_track
            else (outer_track.primary_line if outer_track else None)
        )
        self.inner_line = inner_track.primary_line if inner_track else None
        self.od_line = outer_track.primary_line if outer_track else None
        self.outer_line = self.od_line

        for axis in self.plot_host.axes():
            if self.grid_visible:
                axis.grid(True, color=CURRENT_THEME["grid_color"])
            else:
                axis.grid(False)

        stored_xlabel = getattr(self, "_shared_xlabel", None)
        if stored_xlabel is not None:
            self._set_shared_xlabel(stored_xlabel)

        self._apply_current_style(redraw=False)
        self._refresh_plot_legend()
        if redraw:
            self.canvas.draw_idle()

    def _apply_channel_toggle(self, channel: str, checked: bool) -> None:
        outer_supported = self._outer_channel_available()
        previous_inner, previous_outer = self._current_channel_presence()
        inner_on = (
            self.id_toggle_act.isChecked()
            if self.id_toggle_act is not None
            else previous_inner
        )
        outer_on = (
            self.od_toggle_act.isChecked()
            if self.od_toggle_act is not None
            else previous_outer
        )

        if channel == "inner":
            inner_on = bool(checked)
        else:
            if checked and not outer_supported:
                self._apply_toggle_state(inner_on, False, outer_supported=False)
                self._update_trace_controls_state()
                return
            outer_on = bool(checked)

        inner_on, outer_on = self._ensure_valid_channel_selection(
            inner_on,
            outer_on,
            toggled=channel,
            outer_supported=outer_supported,
        )

        current_inner, current_outer = self._current_channel_presence()
        self._apply_toggle_state(inner_on, outer_on, outer_supported=outer_supported)
        self._update_trace_controls_state()

        if inner_on == current_inner and outer_on == current_outer:
            return

        self._rebuild_channel_layout(inner_on, outer_on)
        self._refresh_zoom_window()

    def toggle_inner_diameter(self, checked: bool):
        self._apply_channel_toggle("inner", checked)

    def toggle_outer_diameter(self, checked: bool):
        self._apply_channel_toggle("outer", checked)

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
            "Ctrl+Z/Y: Undo/Redo\n"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def open_user_manual(self):
        manual_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "docs",
                "VasoAnalyzer_User_Manual.pdf",
            )
        )

        if not os.path.exists(manual_path):
            QMessageBox.warning(
                self,
                "Manual Not Found",
                "The user manual could not be located.",
            )
            return

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(manual_path))
        if not opened:
            QMessageBox.warning(
                self,
                "Open Failed",
                "Unable to open the user manual on this system.",
            )

    def show_release_notes(self):
        # You could load a local CHANGELOG.md and display it
        QMessageBox.information(
            self,
            "Release Notes",
            (
                f"Release {APP_VERSION}:\n"
                "- Packaging metadata refreshed for distribution.\n"
                "- Documentation updated for the 2.5 onboarding flow.\n"
                "- General maintenance and stability work.\n"
            ),
        )

    def show_about(self):
        QMessageBox.information(
            self,
            "About VasoAnalyzer",
            f"VasoAnalyzer {APP_VERSION} (Python Edition)\nhttps://github.com/vr-oj/VasoAnalyzer",
        )

    def show_tutorial(self):
        from .dialogs.tutorial_dialog import TutorialDialog

        dlg = TutorialDialog(self)
        dont_show = dlg.exec_()
        if dont_show:
            settings = QSettings("TykockiLab", "VasoAnalyzer")
            settings.setValue("tutorialShown", True)

    def show_tutorial_if_first_time(self):
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        seen = settings.value("tutorialShown", False, type=bool)
        if not seen:
            from .dialogs.tutorial_dialog import TutorialDialog

            dlg = TutorialDialog(self)
            dont_show = dlg.exec_()
            if dont_show:
                settings.setValue("tutorialShown", True)

    def _maybe_run_onboarding(self) -> None:
        if getattr(self, "_onboarding_checked", False):
            return
        self._onboarding_checked = True
        if onboarding_needed(self.onboarding_settings):
            self.show_welcome_guide(modal=False)

    def show_welcome_dialog(self) -> None:
        """Backward compatibility alias for legacy launcher entry point."""
        self._maybe_run_onboarding()

    def show_welcome_guide(self, modal: bool = False) -> None:
        if modal:
            dlg = WelcomeGuideDialog(self)
            dlg.openRequested.connect(self.open_project_file)
            dlg.createRequested.connect(self.new_project)
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.finished.connect(lambda _: self._handle_welcome_guide_closed(dlg))
            dlg.exec_()
            return

        existing = getattr(self, "_welcome_dialog", None)
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dlg = WelcomeGuideDialog(self)
        dlg.openRequested.connect(self.open_project_file)
        dlg.createRequested.connect(self.new_project)
        dlg.finished.connect(lambda _: self._handle_welcome_guide_closed(dlg))
        dlg.show()
        self._welcome_dialog = dlg

    def _handle_welcome_guide_closed(self, dialog: WelcomeGuideDialog) -> None:
        hide = bool(getattr(dialog, "hide_for_version", False))

        self.onboarding_settings.setValue("ui/show_welcome", not hide)
        self.onboarding_settings.setValue(
            "general/show_onboarding", "false" if hide else "true"
        )

        if getattr(self, "_welcome_dialog", None) is dialog:
            self._welcome_dialog = None

    # [C] ========================= UI SETUP (initUI) ======================================
    def initUI(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_page = self._build_home_page()
        self.stack.addWidget(self.home_page)

        self.data_page = QWidget()
        self.data_page.setObjectName("DataPage")
        self.stack.addWidget(self.data_page)

        self.main_layout = QVBoxLayout(self.data_page)
        self.main_layout.setContentsMargins(16, 8, 16, 16)
        self.main_layout.setSpacing(12)

        dpi = int(QApplication.primaryScreen().logicalDotsPerInch())
        self.plot_host = PlotHost(dpi=dpi)
        self.fig = self.plot_host.figure
        self.canvas = self.plot_host.canvas
        self.canvas.setMouseTracking(True)
        self.canvas.toolbar = None
        initial_specs = [
            ChannelTrackSpec(
                track_id="inner",
                component="inner",
                label="Inner Diameter (µm)",
                height_ratio=1.0,
            )
        ]
        self.plot_host.ensure_channels(initial_specs)
        self.plot_host.set_event_highlight_style(
            color=self._event_highlight_color,
            alpha=self._event_highlight_base_alpha,
        )
        inner_track = self.plot_host.track("inner")
        self.ax = inner_track.ax if inner_track else None
        self.ax2 = None
        self._bind_primary_axis_callbacks()

        self._init_hover_artists()
        self.active_canvas = self.canvas

        self.toolbar = self.build_toolbar_for_canvas(self.canvas)
        self.toolbar.setObjectName("PlotToolbar")
        self.toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.toolbar.setMovable(False)
        self.canvas.toolbar = self.toolbar
        self.toolbar.setMouseTracking(True)

        self.trace_file_label = QLabel("No trace loaded")
        self.trace_file_label.setObjectName("TraceChip")
        self.trace_file_label.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )
        self.trace_file_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.trace_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.trace_file_label.setMinimumWidth(260)
        self._status_base_label = "No trace loaded"
        self.trace_file_label.installEventFilter(self)

        self.primary_toolbar = self._create_primary_toolbar()
        self.primary_toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.primary_toolbar)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        self._interaction_controller = InteractionController(
            self.plot_host,
            toolbar=self.toolbar,
            on_drag_state=self._set_plot_drag_state,
        )

        self.toolbar.addAction(self.id_toggle_act)
        self.toolbar.addAction(self.od_toggle_act)
        self.toolbar.addSeparator()

        self._update_toolbar_compact_mode(self.width())

        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setMinimum(0)
        self.scroll_slider.setMaximum(1000)
        self.scroll_slider.setSingleStep(1)
        self.scroll_slider.setValue(0)
        self.scroll_slider.valueChanged.connect(self.scroll_plot)
        self.scroll_slider.hide()
        self.scroll_slider.setToolTip("Scroll timeline (X-axis)")

        self.snapshot_label = QLabel("Snapshot preview")
        self.snapshot_label.setObjectName("SnapshotPreview")
        self.snapshot_label.setAlignment(Qt.AlignCenter)
        self.snapshot_label.setMinimumHeight(220)
        self.snapshot_label.hide()
        self.snapshot_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.snapshot_label.customContextMenuRequested.connect(
            self.show_snapshot_context_menu
        )

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self.change_frame)
        self.slider.hide()
        self.slider.setToolTip("Navigate TIFF frames")

        # Snapshot playback controls
        self.snapshot_controls = QWidget()
        self.snapshot_controls.setObjectName("SnapshotControls")
        controls_layout = QHBoxLayout(self.snapshot_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.prev_frame_btn = QToolButton(self.snapshot_controls)
        self.prev_frame_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipBackward)
        )
        self.prev_frame_btn.setToolTip("Previous frame")
        self.prev_frame_btn.clicked.connect(self.step_previous_frame)
        self.prev_frame_btn.setEnabled(False)
        controls_layout.addWidget(self.prev_frame_btn)

        self.play_pause_btn = QToolButton(self.snapshot_controls)
        self.play_pause_btn.setCheckable(True)
        self.play_pause_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setText("Play")
        self.play_pause_btn.setToolTip("Play snapshot sequence")
        self.play_pause_btn.clicked.connect(self.toggle_snapshot_playback)
        self.play_pause_btn.setEnabled(False)
        controls_layout.addWidget(self.play_pause_btn)

        self.next_frame_btn = QToolButton(self.snapshot_controls)
        self.next_frame_btn.setIcon(
            self.style().standardIcon(QStyle.SP_MediaSkipForward)
        )
        self.next_frame_btn.setToolTip("Next frame")
        self.next_frame_btn.clicked.connect(self.step_next_frame)
        self.next_frame_btn.setEnabled(False)
        controls_layout.addWidget(self.next_frame_btn)

        self.snapshot_speed_label = QLabel("Speed:")
        self.snapshot_speed_label.setObjectName("SnapshotSpeedLabel")
        self.snapshot_speed_label.setEnabled(False)
        controls_layout.addWidget(self.snapshot_speed_label)

        self.snapshot_speed_combo = QComboBox(self.snapshot_controls)
        self.snapshot_speed_combo.setObjectName("SnapshotSpeedCombo")
        self.snapshot_speed_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.snapshot_speed_presets = [
            ("0.25x", 0.25),
            ("0.5x", 0.5),
            ("1x", 1.0),
            ("1.5x", 1.5),
            ("2x", 2.0),
            ("3x", 3.0),
            ("4x", 4.0),
        ]
        for label, value in self.snapshot_speed_presets:
            self.snapshot_speed_combo.addItem(label, value)
        self.snapshot_speed_default_index = next(
            (
                idx
                for idx, (_, val) in enumerate(self.snapshot_speed_presets)
                if val == 1.0
            ),
            0,
        )
        self.snapshot_speed_combo.setCurrentIndex(self.snapshot_speed_default_index)
        self.snapshot_speed_combo.setEnabled(False)
        self.snapshot_speed_label.setToolTip("Adjust snapshot playback speed")
        self.snapshot_speed_combo.setToolTip("Adjust snapshot playback speed")
        self.snapshot_speed_combo.currentIndexChanged.connect(
            self.on_snapshot_speed_changed
        )
        controls_layout.addWidget(self.snapshot_speed_combo)

        controls_layout.addStretch()

        self.snapshot_time_label = QLabel("Frame 0 / 0")
        self.snapshot_time_label.setObjectName("SnapshotStatusLabel")
        self.snapshot_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls_layout.addWidget(self.snapshot_time_label)
        self.snapshot_controls.hide()

        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.timeout.connect(self.advance_snapshot_frame)

        self.metadata_panel = QFrame()
        self.metadata_panel.setObjectName("MetadataPanel")
        metadata_layout = QVBoxLayout(self.metadata_panel)
        metadata_layout.setContentsMargins(10, 8, 10, 8)
        metadata_layout.setSpacing(6)

        self.metadata_scroll = QScrollArea()
        self.metadata_scroll.setWidgetResizable(True)
        self.metadata_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.metadata_scroll.setObjectName("MetadataScroll")
        metadata_layout.addWidget(self.metadata_scroll)

        metadata_inner = QWidget()
        inner_layout = QVBoxLayout(metadata_inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(6)
        self.metadata_details_label = QLabel("No metadata available.")
        self.metadata_details_label.setObjectName("MetadataDetails")
        self.metadata_details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.metadata_details_label.setWordWrap(True)
        self.metadata_details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.metadata_details_label.setTextFormat(Qt.RichText)
        inner_layout.addWidget(self.metadata_details_label)
        inner_layout.addStretch()
        self.metadata_scroll.setWidget(metadata_inner)

        self.metadata_panel.hide()

        self.event_table = EventTableWidget(self)
        self.event_table.setMinimumWidth(560)
        self.event_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.event_table.customContextMenuRequested.connect(
            self.show_event_table_context_menu
        )
        self.event_table.installEventFilter(self)
        self.event_table.cellClicked.connect(self.table_row_clicked)
        self.event_table_controller = EventTableController(self.event_table, self)
        self.event_table_controller.cell_edited.connect(self.handle_table_edit)
        self.event_table_controller.rows_changed.connect(self._on_event_rows_changed)

        self.header_frame = self._build_data_header()
        self.main_layout.addWidget(self.header_frame)

        self.data_splitter = self.rebuild_default_main_layout()
        self.main_layout.addWidget(self.data_splitter, 1)
        self.toggle_snapshot_viewer(False)

        self._update_status_chip()

        border_color = CURRENT_THEME["grid_color"]
        text_color = CURRENT_THEME["text"]
        header_bg = "#f5f7ff"
        card_bg = CURRENT_THEME["button_bg"]
        hover_bg = CURRENT_THEME["button_hover_bg"]
        window_bg = CURRENT_THEME["window_bg"]

        self.data_page.setStyleSheet(
            self._shared_button_css()
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

        self.stack.setCurrentWidget(self.home_page)
        self._set_toolbars_visible(False)

        self.canvas.mpl_connect("draw_event", self.update_event_label_positions)
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)
        self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
        self.canvas.mpl_connect("figure_leave_event", self._handle_figure_leave)
        self.canvas.mpl_connect("button_press_event", self.handle_click_on_plot)
        self.canvas.mpl_connect(
            "button_release_event",
            lambda event: QTimer.singleShot(100, lambda: self.on_mouse_release(event)),
        )
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)

        self._refresh_home_recent()
        QTimer.singleShot(0, lambda: self._update_toolbar_compact_mode(self.width()))

    def _create_primary_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Primary")
        toolbar.setObjectName("PrimaryToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setContextMenuPolicy(Qt.PreventContextMenu)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        self.home_action = QAction(
            QIcon(self.icon_path("Home.svg")), "Home screen", self
        )
        self.home_action.setToolTip("Show the startup home screen")
        self.home_action.triggered.connect(self.show_home_screen)
        self.home_action.setVisible(False)
        toolbar.addAction(self.home_action)

        self.load_trace_action = QAction(
            QIcon(self.icon_path("folder-open.svg")), "Open trace…", self
        )
        self.load_trace_action.setToolTip(
            "Open a CSV trace file and auto-detect matching events"
        )
        self.load_trace_action.setShortcut(QKeySequence.Open)
        self.load_trace_action.triggered.connect(self._handle_load_trace)
        toolbar.addAction(self.load_trace_action)

        self.load_events_action = QAction(
            QIcon(self.icon_path("folder-plus.svg")), "Load events…", self
        )
        self.load_events_action.setToolTip(
            "Load an events table without reloading the trace"
        )
        self.load_events_action.setEnabled(False)
        self.load_events_action.triggered.connect(self._handle_load_events)
        toolbar.addAction(self.load_events_action)

        self.load_snapshot_action = QAction(
            QIcon(self.icon_path("empty-box.svg")), "Load Result TIFF…", self
        )
        self.load_snapshot_action.setToolTip("Load Vasotracker _Result.tiff snapshot")
        self.load_snapshot_action.triggered.connect(self.load_snapshot)
        toolbar.addAction(self.load_snapshot_action)

        self.excel_action = QAction(
            QIcon(self.icon_path("chart-bar.svg")), "Excel mapper…", self
        )
        self.excel_action.setToolTip("Map events to an Excel template")
        self.excel_action.setEnabled(False)
        self.excel_action.triggered.connect(self.open_excel_mapping_dialog)
        toolbar.addAction(self.excel_action)

        self.save_session_action = QAction(
            QIcon(self.icon_path("Save.svg")), "Save session", self
        )
        self.save_session_action.setToolTip("Save session outputs or export plots")
        self.save_session_action.setShortcut(QKeySequence.Save)
        self.save_session_action.triggered.connect(self.show_save_menu)
        toolbar.addAction(self.save_session_action)

        self.welcome_action = QAction(
            QIcon(self.icon_path("info-circle.svg")), "Welcome guide", self
        )
        self.welcome_action.setToolTip("Open the welcome guide")
        self.welcome_action.triggered.connect(
            lambda: self.show_welcome_guide(modal=False)
        )
        toolbar.addAction(self.welcome_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self.trace_file_label)

        return toolbar

    def _update_toolbar_compact_mode(self, width: Optional[int] = None) -> None:
        if width is None:
            width = self.width()
        compact = width < 1280
        style = Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextUnderIcon
        for toolbar in (
            getattr(self, "primary_toolbar", None),
            getattr(self, "toolbar", None),
        ):
            if toolbar is None:
                continue
            toolbar.setToolButtonStyle(style)
        self._update_primary_toolbar_button_widths(compact)

    def _primary_toolbar_buttons(self) -> List[QToolButton]:
        toolbar = getattr(self, "primary_toolbar", None)
        if toolbar is None:
            return []
        buttons: List[QToolButton] = []
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if isinstance(widget, QToolButton):
                buttons.append(widget)
        if not buttons:
            buttons = toolbar.findChildren(QToolButton)
        return buttons

    def _update_primary_toolbar_button_widths(self, compact: bool) -> None:
        buttons = self._primary_toolbar_buttons()
        if not buttons:
            return

        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly
                if compact
                else Qt.ToolButtonTextUnderIcon
            )

        if compact:
            return

        widths = []
        for button in buttons:
            hint = button.sizeHint()
            metrics = button.fontMetrics()
            text_width = metrics.horizontalAdvance(button.text() or "")
            icon_width = button.iconSize().width()
            base_width = 0
            if hint.isValid():
                base_width = hint.width()
            base_width = max(base_width, text_width + 32, icon_width + 35)
            widths.append(base_width)
        if not widths:
            return

        target_width = max(widths)
        target_width = max(target_width, 200)
        for button in buttons:
            button.setMinimumWidth(target_width)
            button.setMaximumWidth(target_width)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            button.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_toolbar_compact_mode(event.size().width())

    def _set_plot_drag_state(self, active: bool) -> None:
        self._plot_drag_in_progress = bool(active)

    def _refresh_zoom_window(self) -> None:
        if not self.zoom_dock:
            return
        current_window = None
        if hasattr(self, "plot_host"):
            current_window = self.plot_host.current_window()
        if current_window is None:
            self.zoom_dock.clear_span()
            return
        start, end = current_window
        self.zoom_dock.show_span(start, end)

    def _on_zoom_visibility_changed(self, visible: bool) -> None:
        if self.zoom_toggle_btn and self.zoom_toggle_btn.isChecked() != visible:
            self.zoom_toggle_btn.blockSignals(True)
            self.zoom_toggle_btn.setChecked(visible)
            self.zoom_toggle_btn.blockSignals(False)
        if visible:
            self._refresh_zoom_window()

    def _on_scope_visibility_changed(self, visible: bool) -> None:
        if self.scope_toggle_btn and self.scope_toggle_btn.isChecked() != visible:
            self.scope_toggle_btn.blockSignals(True)
            self.scope_toggle_btn.setChecked(visible)
            self.scope_toggle_btn.blockSignals(False)
        if visible and self.scope_dock and self.trace_model is not None:
            self.scope_dock.set_trace_model(self.trace_model)

    def _serialize_plot_layout(self) -> Optional[dict]:
        if not hasattr(self, "plot_host"):
            return None
        layout = self.plot_host.layout_state()
        specs = self.plot_host.channel_specs()
        return {
            "order": list(layout.order),
            "height_ratios": {k: float(v) for k, v in layout.height_ratios.items()},
            "visibility": {k: bool(v) for k, v in layout.visibility.items()},
            "channels": [
                {
                    "track_id": spec.track_id,
                    "component": spec.component,
                    "label": spec.label,
                    "height_ratio": float(spec.height_ratio),
                }
                for spec in specs
            ],
        }

    def _apply_pending_plot_layout(self) -> None:
        layout = getattr(self, "_pending_plot_layout", None)
        if not layout:
            return
        if not hasattr(self, "plot_host"):
            return
        specs_map = {spec.track_id: spec for spec in self.plot_host.channel_specs()}
        order = layout.get("order") or list(specs_map.keys())
        height_ratios = layout.get("height_ratios", {}) or {}
        new_specs: list[ChannelTrackSpec] = []
        added_ids: set[str] = set()
        for track_id in order:
            spec = specs_map.get(track_id)
            if not spec:
                continue
            ratio = float(height_ratios.get(track_id, spec.height_ratio))
            new_specs.append(
                ChannelTrackSpec(
                    track_id=spec.track_id,
                    component=spec.component,
                    label=spec.label,
                    height_ratio=ratio,
                )
            )
            added_ids.add(track_id)
        for track_id, spec in specs_map.items():
            if track_id in added_ids:
                continue
            new_specs.append(
                ChannelTrackSpec(
                    track_id=spec.track_id,
                    component=spec.component,
                    label=spec.label,
                    height_ratio=spec.height_ratio,
                )
            )
        if new_specs:
            self.plot_host.ensure_channels(new_specs)
        self._pending_plot_layout = None

    def _build_data_header(self):
        header = QFrame()
        header.setObjectName("DataHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        return header

    def _build_home_page(self):
        page = QWidget()
        page.setObjectName("HomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        hero = QFrame()
        hero.setObjectName("HeroFrame")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(24)

        brand_icon_path = self._brand_icon_path("svg")
        hero_icon = (
            QSvgWidget(brand_icon_path)
            if brand_icon_path
            else QSvgWidget(self.icon_path("Home.svg"))
        )
        hero_icon.setFixedSize(72, 72)
        hero_layout.addWidget(hero_icon, alignment=Qt.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(12)

        title = QLabel("Welcome to VasoAnalyzer")
        title.setObjectName("HeroTitle")
        subtitle = QLabel(
            "Follow the buttons below to import traces, continue a project, or review the welcome guide."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("HeroSubtitle")
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)

        action_row1 = QHBoxLayout()
        action_row1.setSpacing(12)
        self.home_resume_btn = self._make_home_button(
            "Return to workspace",
            "Back.svg",
            self.show_analysis_workspace,
            secondary=True,
        )
        self.home_resume_btn.hide()
        action_row1.addWidget(self.home_resume_btn)
        action_row1.addWidget(
            self._make_home_button(
                "Load trace & events",
                "folder-open.svg",
                self._handle_load_trace,
                primary=True,
            )
        )
        action_row1.addWidget(
            self._make_home_button(
                "Open Project",
                "folder-open.svg",
                self.open_project_file,
                secondary=True,
            )
        )
        hero_text.addLayout(action_row1)

        action_row2 = QHBoxLayout()
        action_row2.setSpacing(12)
        action_row2.addWidget(
            self._make_home_button(
                "Create Project",
                "folder-plus.svg",
                self.new_project,
                secondary=True,
            )
        )
        action_row2.addWidget(
            self._make_home_button(
                "Welcome guide",
                "info-circle.svg",
                lambda: self.show_welcome_guide(modal=False),
                secondary=True,
            )
        )
        hero_text.addLayout(action_row2)
        hero_text.addStretch()

        hero_layout.addLayout(hero_text)
        layout.addWidget(hero)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)

        recent_traces = QFrame()
        recent_traces.setObjectName("HomeCard")
        recent_traces_layout = QVBoxLayout(recent_traces)
        recent_traces_layout.setContentsMargins(20, 20, 20, 20)
        recent_traces_layout.setSpacing(12)
        traces_header = QHBoxLayout()
        traces_header.setContentsMargins(0, 0, 0, 0)
        traces_header.setSpacing(8)
        traces_title = QLabel("Recent Sessions")
        traces_title.setObjectName("CardTitle")
        traces_header.addWidget(traces_title)
        traces_header.addStretch(1)
        self.home_clear_sessions_button = QToolButton()
        self.home_clear_sessions_button.setObjectName("HomeClearButton")
        self.home_clear_sessions_button.setText("Clear all")
        self.home_clear_sessions_button.setCursor(Qt.PointingHandCursor)
        self.home_clear_sessions_button.clicked.connect(self.clear_recent_files)
        self.home_clear_sessions_button.setVisible(False)
        traces_header.addWidget(self.home_clear_sessions_button, 0, Qt.AlignRight)
        recent_traces_layout.addLayout(traces_header)
        self.home_recent_sessions_layout = QVBoxLayout()
        self.home_recent_sessions_layout.setSpacing(8)
        recent_traces_layout.addLayout(self.home_recent_sessions_layout)
        recent_traces_layout.addStretch()

        recent_projects = QFrame()
        recent_projects.setObjectName("HomeCard")
        recent_projects_layout = QVBoxLayout(recent_projects)
        recent_projects_layout.setContentsMargins(20, 20, 20, 20)
        recent_projects_layout.setSpacing(12)
        projects_header = QHBoxLayout()
        projects_header.setContentsMargins(0, 0, 0, 0)
        projects_header.setSpacing(8)
        projects_title = QLabel("Recent Projects")
        projects_title.setObjectName("CardTitle")
        projects_header.addWidget(projects_title)
        projects_header.addStretch(1)
        self.home_clear_projects_button = QToolButton()
        self.home_clear_projects_button.setObjectName("HomeClearButton")
        self.home_clear_projects_button.setText("Clear all")
        self.home_clear_projects_button.setCursor(Qt.PointingHandCursor)
        self.home_clear_projects_button.clicked.connect(self.clear_recent_projects)
        self.home_clear_projects_button.setVisible(False)
        projects_header.addWidget(self.home_clear_projects_button, 0, Qt.AlignRight)
        recent_projects_layout.addLayout(projects_header)
        self.home_recent_projects_layout = QVBoxLayout()
        self.home_recent_projects_layout.setSpacing(8)
        recent_projects_layout.addLayout(self.home_recent_projects_layout)
        recent_projects_layout.addStretch()

        cards_row.addWidget(recent_traces, 1)
        cards_row.addWidget(recent_projects, 1)
        layout.addLayout(cards_row)
        layout.addStretch()

        border_color = CURRENT_THEME["grid_color"]
        text_color = CURRENT_THEME["text"]
        window_bg = CURRENT_THEME["window_bg"]
        hero_bg = CURRENT_THEME.get("button_bg", window_bg)
        card_bg = CURRENT_THEME.get("table_bg", window_bg)
        hover_bg = CURRENT_THEME.get("button_hover_bg", border_color)

        def rgba_from_hex(color: str, alpha: float) -> str:
            color = color.strip()
            if color.startswith("rgba"):
                return color
            color = color.lstrip("#")
            if len(color) == 3:
                color = "".join(ch * 2 for ch in color)
            try:
                r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return text_color
            alpha = max(0.0, min(1.0, alpha))
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"

        subtitle_color = rgba_from_hex(text_color, 0.72)
        card_title_color = rgba_from_hex(text_color, 0.86)
        placeholder_color = rgba_from_hex(text_color, 0.55)
        muted_action_color = rgba_from_hex(text_color, 0.68)

        page.setStyleSheet(
            self._shared_button_css()
            + f"""
QWidget#HomePage {{
    background: {window_bg};
}}
QFrame#HeroFrame {{
    background: {hero_bg};
    border: 1px solid {border_color};
    border-radius: 16px;
}}
QFrame#HomeCard {{
    background: {card_bg};
    border: 1px solid {border_color};
    border-radius: 14px;
}}
QLabel#HeroTitle {{
    font-size: 24px;
    font-weight: 600;
}}
QLabel#HeroSubtitle {{
    color: {subtitle_color};
}}
QLabel#CardTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {card_title_color};
}}
QLabel#CardPlaceholder {{
    color: {placeholder_color};
}}
QToolButton#HomeClearButton,
QToolButton#HomeRemoveButton {{
    background: transparent;
    color: {muted_action_color};
    border: none;
    padding: 4px 6px;
    font-weight: 500;
}}
QToolButton#HomeClearButton:hover,
QToolButton#HomeRemoveButton:hover {{
    color: {card_title_color};
    background: {hover_bg};
    border-radius: 6px;
}}
"""
        )

        self._refresh_home_recent()
        return page

    def _make_home_button(
        self,
        text: str,
        icon_name: str,
        callback,
        *,
        primary: bool = False,
        secondary: bool = False,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(44)
        if icon_name:
            button.setIcon(QIcon(self.icon_path(icon_name)))
            button.setIconSize(QSize(20, 20))
        if primary:
            button.setProperty("isPrimary", True)
        elif secondary:
            button.setProperty("isSecondary", True)
        else:
            button.setProperty("isGhost", True)
        button.clicked.connect(callback)
        self._apply_button_style(button)
        return button

    def _set_toolbars_visible(self, visible: bool) -> None:
        for name in ("primary_toolbar", "toolbar"):
            toolbar = getattr(self, name, None)
            if isinstance(toolbar, QToolBar):
                toolbar.setVisible(visible)

    def show_home_screen(self):
        self.stack.setCurrentWidget(self.home_page)
        self._refresh_home_recent()
        self._update_home_resume_button()
        if hasattr(self, "home_action") and self.home_action is not None:
            self.home_action.setVisible(False)
        self._set_toolbars_visible(False)

    def show_analysis_workspace(self):
        self.stack.setCurrentWidget(self.data_page)
        if hasattr(self, "home_action") and self.home_action is not None:
            self.home_action.setVisible(True)
        self._update_home_resume_button()
        self._set_toolbars_visible(True)

    def _update_home_resume_button(self):
        if not hasattr(self, "home_resume_btn"):
            return

        has_session = self.trace_data is not None
        self.home_resume_btn.setVisible(has_session)
        self.home_resume_btn.setEnabled(has_session)

        if has_session:
            status = ""
            if hasattr(self, "trace_file_label"):
                status = self.trace_file_label.property("_full_status_text") or ""
            tooltip = (
                f"Return to workspace · {status}" if status else "Return to workspace"
            )
            self.home_resume_btn.setToolTip(tooltip)
        else:
            self.home_resume_btn.setToolTip("Return to workspace")

    @staticmethod
    def _apply_button_style(button: QPushButton) -> None:
        button.style().unpolish(button)
        button.style().polish(button)

    def _shared_button_css(self) -> str:
        border = CURRENT_THEME["grid_color"]
        text = CURRENT_THEME["text"]
        hover = CURRENT_THEME["button_hover_bg"]
        return """
QPushButton[isPrimary="true"] {
    background-color: #2c6bed;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 600;
}
QPushButton[isPrimary="true"]:hover {
    background-color: #1f4fcc;
}
QPushButton[isSecondary="true"] {
    background-color: #edf2ff;
    color: %s;
    border: 1px solid #c6d4ff;
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 500;
}
QPushButton[isSecondary="true"]:hover {
    background-color: #dfe7ff;
}
QPushButton[isGhost="true"] {
    background-color: transparent;
    color: %s;
    border: 1px solid %s;
    border-radius: 10px;
    padding: 8px 20px;
}
QPushButton[isGhost="true"]:hover {
    background-color: %s;
}
""" % (
            text,
            text,
            border,
            hover,
        )

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_home_placeholder(
        self,
        layout: QVBoxLayout,
        message: str,
        button_text: str,
        callback,
        icon_name: str = "folder-open.svg",
    ) -> None:
        placeholder = QLabel(message)
        placeholder.setObjectName("CardPlaceholder")
        placeholder.setWordWrap(True)
        layout.addWidget(placeholder)
        button = self._make_home_button(
            button_text,
            icon_name,
            callback,
            primary=True,
        )
        layout.addWidget(button)

    def _make_home_recent_row(
        self, label: str, path: str, open_callback, remove_callback
    ) -> QWidget:
        row = QWidget()
        row.setObjectName("HomeRecentRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        open_btn = QPushButton(label)
        open_btn.setProperty("isGhost", True)
        open_btn.setMinimumHeight(36)
        open_btn.setToolTip(path)
        open_btn.clicked.connect(open_callback)
        self._apply_button_style(open_btn)
        row_layout.addWidget(open_btn, 1)

        remove_btn = QToolButton()
        remove_btn.setObjectName("HomeRemoveButton")
        remove_btn.setAutoRaise(True)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setText("Remove")
        remove_btn.setToolTip(f"Remove {path}")
        remove_btn.clicked.connect(remove_callback)
        row_layout.addWidget(remove_btn, 0, Qt.AlignRight)

        return row

    def _set_status_source(self, label: str, tooltip: str = "") -> None:
        self._status_base_label = label
        self.trace_file_label.setToolTip(tooltip)
        self._update_status_chip()

    def _update_status_chip(
        self, label: Optional[str] = None, tooltip: Optional[str] = None
    ) -> None:
        if label is not None:
            self._status_base_label = label
        if tooltip is not None:
            self.trace_file_label.setToolTip(tooltip)

        base = getattr(self, "_status_base_label", "No trace loaded")
        parts = [base]
        effective_rate = self.sampling_rate_hz
        if (not effective_rate or effective_rate <= 0) and getattr(
            self, "recording_interval", 0
        ) > 0:
            try:
                effective_rate = 1.0 / float(self.recording_interval)
            except ZeroDivisionError:
                effective_rate = None
        if effective_rate and effective_rate > 0:
            parts.append(f"{effective_rate:.2f} Hz")
        full_text = " · ".join(parts)
        if self.session_dirty:
            full_text = f"● {full_text}"

        if self.trace_file_label.width() > 0:
            metrics = QFontMetrics(self.trace_file_label.font())
            display = metrics.elidedText(
                full_text, Qt.ElideMiddle, self.trace_file_label.width()
            )
        else:
            display = full_text
        self.trace_file_label.setText(display)
        self.trace_file_label.setProperty("_full_status_text", full_text)

    def _reset_session_dirty(self) -> None:
        self.session_dirty = False
        self._update_status_chip()

    def mark_session_dirty(self) -> None:
        if not self.session_dirty:
            self.session_dirty = True
            self._update_status_chip()

    # ------------------------------------------------------------------ trace editing helpers
    def _prepare_trace_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        trace = df.copy()
        if "Time (s)" in trace.columns:
            trace["Time (s)"] = pd.to_numeric(trace["Time (s)"], errors="coerce")

        if "Inner Diameter" in trace.columns:
            trace["Inner Diameter"] = pd.to_numeric(trace["Inner Diameter"], errors="coerce")
            inner_raw_name = "Inner Diameter (raw)"
            inner_clean_name = "Inner Diameter (clean)"
            inner_values = trace["Inner Diameter"].to_numpy(dtype=float, copy=True)

            if inner_raw_name in trace.columns:
                trace[inner_raw_name] = pd.to_numeric(trace[inner_raw_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc("Inner Diameter") + 1
                trace.insert(insert_at, inner_raw_name, inner_values.copy())

            if inner_clean_name in trace.columns:
                trace[inner_clean_name] = pd.to_numeric(trace[inner_clean_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc(inner_raw_name) + 1 if inner_raw_name in trace.columns else trace.columns.get_loc("Inner Diameter") + 1
                trace.insert(insert_at, inner_clean_name, inner_values.copy())
        if "Outer Diameter" in trace.columns:
            trace["Outer Diameter"] = pd.to_numeric(trace["Outer Diameter"], errors="coerce")
            outer_raw_name = "Outer Diameter (raw)"
            outer_clean_name = "Outer Diameter (clean)"
            outer_values = trace["Outer Diameter"].to_numpy(dtype=float, copy=True)

            if outer_raw_name in trace.columns:
                trace[outer_raw_name] = pd.to_numeric(trace[outer_raw_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc("Outer Diameter") + 1
                trace.insert(insert_at, outer_raw_name, outer_values.copy())

            if outer_clean_name in trace.columns:
                trace[outer_clean_name] = pd.to_numeric(trace[outer_clean_name], errors="coerce")
            else:
                insert_at = trace.columns.get_loc(outer_raw_name) + 1 if outer_raw_name in trace.columns else trace.columns.get_loc("Outer Diameter") + 1
                trace.insert(insert_at, outer_clean_name, outer_values.copy())

        trace.attrs.setdefault("edit_log", [])
        return trace

    def _sync_trace_dataframe_from_model(self) -> None:
        if self.trace_data is None or self.trace_model is None:
            return

        inner_clean = self.trace_model.inner_full.copy()
        inner_raw = self.trace_model.inner_raw.copy()
        self.trace_data.loc[:, "Inner Diameter"] = inner_clean
        if "Inner Diameter (clean)" in self.trace_data.columns:
            self.trace_data.loc[:, "Inner Diameter (clean)"] = inner_clean
        if "Inner Diameter (raw)" in self.trace_data.columns:
            self.trace_data.loc[:, "Inner Diameter (raw)"] = inner_raw
        else:
            self.trace_data["Inner Diameter (raw)"] = inner_raw

        if self.trace_model.outer_full is not None and "Outer Diameter" in self.trace_data.columns:
            outer_clean = self.trace_model.outer_full.copy()
            self.trace_data.loc[:, "Outer Diameter"] = outer_clean
            if "Outer Diameter (clean)" in self.trace_data.columns:
                self.trace_data.loc[:, "Outer Diameter (clean)"] = outer_clean
            if self.trace_model.outer_raw is not None:
                if "Outer Diameter (raw)" in self.trace_data.columns:
                    self.trace_data.loc[:, "Outer Diameter (raw)"] = self.trace_model.outer_raw.copy()
                else:
                    self.trace_data["Outer Diameter (raw)"] = self.trace_model.outer_raw.copy()

        self.trace_data.attrs["edit_log"] = serialize_edit_log(self.trace_model.edit_log)

        if self.current_sample is not None:
            synchronized = self.trace_data.copy()
            synchronized.attrs = dict(self.trace_data.attrs)
            self.current_sample.trace_data = synchronized

    def _refresh_views_after_edit(self) -> None:
        if self.trace_model is None:
            return
        current_window: Optional[Tuple[float, float]] = None
        if hasattr(self, "plot_host") and self.plot_host is not None:
            current_window = self.plot_host.current_window()
        if current_window is None:
            current_window = self.trace_model.full_range

        self.trace_model.clear_cache()
        if self.plot_host is not None:
            self.plot_host.set_trace_model(self.trace_model)
            if current_window is not None:
                self.plot_host.set_time_window(*current_window)
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(self.trace_model)
        if self.scope_dock:
            self.scope_dock.set_trace_model(self.trace_model)
        if hasattr(self, "_refresh_zoom_window"):
            try:
                self._refresh_zoom_window()
            except Exception:
                pass
        self._update_trace_controls_state()
        if hasattr(self, "canvas"):
            try:
                self.canvas.draw_idle()
            except Exception:
                pass

    def _apply_point_editor_actions(self, actions: Sequence, summary: Optional[SessionSummary]) -> None:
        if self.trace_model is None or not actions:
            return
        self.trace_model.apply_actions(actions)
        self._sync_trace_dataframe_from_model()
        self._refresh_views_after_edit()
        self.mark_session_dirty()

        if summary is None:
            point_count = sum(getattr(action, "count", 0) for action in actions)
            total_samples = max(len(self.trace_model.inner_full), 1)
            percent = (point_count / total_samples) * 100.0
            channel_label = ", ".join(sorted({"ID" if getattr(action, "channel", "inner") == "inner" else "OD" for action in actions}))
            message = f"Edited {point_count} points ({percent:.3f}%) [{channel_label}] — Undo available"
        else:
            message = (
                f"Edited {summary.point_count} points "
                f"({summary.percent_of_trace * 100:.3f}%) "
                f"[{summary.channel}] — Undo available"
            )
        self.statusBar().showMessage(message, 7000)

    def _revert_point_editor_actions(self, count: int) -> None:
        if self.trace_model is None or count <= 0:
            return
        removed = self.trace_model.pop_actions(count)
        if not removed:
            return
        self._sync_trace_dataframe_from_model()
        self._refresh_views_after_edit()
        self.mark_session_dirty()

        point_count = sum(action.count for action in removed)
        channels = ", ".join(sorted({"ID" if action.channel == "inner" else "OD" for action in removed}))
        self.statusBar().showMessage(f"Point edits undone ({point_count} pts) [{channels}]", 6000)

    def _on_edit_points_triggered(self) -> None:
        if self.trace_model is None:
            return
        channels: List[Tuple[str, str]] = []
        has_outer = self.trace_model.outer_full is not None
        if self.id_toggle_act is None or self.id_toggle_act.isChecked():
            channels.append(("inner", "Inner Diameter (ID)"))
        if has_outer and (self.od_toggle_act is None or self.od_toggle_act.isChecked()):
            channels.append(("outer", "Outer Diameter (OD)"))

        if not channels:
            channels.append(("inner", "Inner Diameter (ID)"))
            if has_outer:
                channels.append(("outer", "Outer Diameter (OD)"))

        if len(channels) == 1:
            self._launch_point_editor(channels[0][0])
            return

        menu = QMenu(self)
        for channel_key, label in channels:
            action = menu.addAction(label)
            action.triggered.connect(lambda _, key=channel_key: self._launch_point_editor(key))
        menu.exec_(QCursor.pos())

    def _launch_point_editor(self, channel: str) -> None:
        if self.trace_model is None:
            return
        window = None
        if hasattr(self, "plot_host") and self.plot_host is not None:
            window = self.plot_host.current_window()
        if window is None:
            window = self.trace_model.full_range

        try:
            session = PointEditorSession(self.trace_model, channel, window)
        except ValueError as exc:
            QMessageBox.warning(self, "Point Editor", str(exc))
            return

        dialog = PointEditorDialog(session, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        actions = tuple(dialog.committed_actions() or ())
        if not actions:
            return
        summary = dialog.session_summary()
        if summary is None:
            point_count = sum(action.count for action in actions)
            percent = point_count / max(len(self.trace_model.inner_full), 1)
            label = "ID" if channel == "inner" else "OD"
            times = [bounds for action in actions for bounds in action.t_bounds]
            t0 = min(times) if times else window[0]
            t1 = max(times) if times else window[1]
            summary = SessionSummary(
                channel=label,
                point_count=point_count,
                percent_of_trace=percent,
                action_count=len(actions),
                time_bounds=(t0, t1),
            )

        command = PointEditCommand(self, actions, summary)
        self.undo_stack.push(command)

    def _update_window_title(self) -> None:
        base = f"VasoAnalyzer {APP_VERSION} - Python Edition"
        if not self.current_project:
            self.setWindowTitle(base)
            return

        name = self.current_project.name or ""
        path_hint = ""
        if self.current_project.path:
            try:
                path_hint = Path(self.current_project.path).name
            except Exception:
                path_hint = self.current_project.path

        if name and path_hint and name != path_hint:
            suffix = f"{name} — {path_hint}"
        elif name or path_hint:
            suffix = name or path_hint
        else:
            suffix = ""

        self.setWindowTitle(f"{base} — {suffix}" if suffix else base)

    def _compute_sampling_rate(
        self, trace_df: Optional[pd.DataFrame]
    ) -> Optional[float]:
        if trace_df is None or "Time (s)" not in trace_df.columns:
            return None
        times = trace_df["Time (s)"].dropna().values
        if len(times) < 2:
            return None
        diffs = np.diff(times)
        diffs = diffs[(~np.isnan(diffs)) & (diffs > 0)]
        if len(diffs) == 0:
            return None
        try:
            hz = 1.0 / float(np.mean(diffs))
        except ZeroDivisionError:
            return None
        return hz if np.isfinite(hz) and hz > 0 else None

    def _refresh_home_recent(self) -> None:
        if hasattr(self, "home_recent_sessions_layout"):
            layout = self.home_recent_sessions_layout
            self._clear_layout(layout)
            paths = [p for p in (self.recent_files or []) if isinstance(p, str) and p]
            has_sessions = bool(paths)
            if hasattr(self, "home_clear_sessions_button"):
                self.home_clear_sessions_button.setVisible(has_sessions)
                self.home_clear_sessions_button.setEnabled(has_sessions)
            if not has_sessions:
                self._add_home_placeholder(
                    layout,
                    "No recent sessions yet. Load a trace to populate this list.",
                    "Load trace & events",
                    self._handle_load_trace,
                    "folder-open.svg",
                )
            else:
                for path in paths[:3]:
                    name = os.path.basename(path) or path
                    row = self._make_home_recent_row(
                        name,
                        path,
                        partial(self.load_trace_and_events, path),
                        partial(self.remove_recent_file, path),
                    )
                    layout.addWidget(row)
            layout.addStretch()

        if hasattr(self, "home_recent_projects_layout"):
            layout = self.home_recent_projects_layout
            self._clear_layout(layout)
            projects = [
                p for p in (self.recent_projects or []) if isinstance(p, str) and p
            ]
            has_projects = bool(projects)
            if hasattr(self, "home_clear_projects_button"):
                self.home_clear_projects_button.setVisible(has_projects)
                self.home_clear_projects_button.setEnabled(has_projects)
            if not has_projects:
                self._add_home_placeholder(
                    layout,
                    "No recent projects yet. Open or create a project to see it here.",
                    "Open project",
                    self.open_project_file,
                    "folder-open.svg",
                )
            else:
                for path in projects[:3]:
                    name = os.path.basename(path) or path
                    row = self._make_home_recent_row(
                        name,
                        path,
                        partial(self.open_recent_project, path),
                        partial(self.remove_recent_project, path),
                    )
                    layout.addWidget(row)
            layout.addStretch()

        self._update_home_resume_button()

    def build_toolbar_for_canvas(self, canvas):
        toolbar = CustomToolbar(canvas, self, reset_callback=self.reset_to_full_view)
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            f"""
            QToolBar {{
                background: transparent;
                border: none;
                padding: 0px;
                spacing: 0px;
            }}
            QToolBar > QToolButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                margin: 0px 5px;
                padding: 6px 8px;
                color: {CURRENT_THEME['text']};
            }}
            QToolBar > QToolButton:hover {{
                background: {CURRENT_THEME['button_hover_bg']};
            }}
            QToolBar > QToolButton:checked {{
                background: {CURRENT_THEME['button_active_bg']};
            }}
        """
        )

        if hasattr(toolbar, "coordinates"):
            toolbar.coordinates = lambda *args, **kwargs: None
            for act in list(toolbar.actions()):
                if isinstance(act, QAction) and act.text() == "":
                    toolbar.removeAction(act)

        base_actions = getattr(toolbar, "_actions", {})
        home_act = base_actions.get("home")
        back_act = base_actions.get("back")
        forward_act = base_actions.get("forward")
        pan_act = base_actions.get("pan")
        zoom_act = base_actions.get("zoom")
        subplots_act = base_actions.get("subplots")
        save_act = base_actions.get("save")

        # Clear default ordering; we'll re‑add in grouped clusters
        for action in list(toolbar.actions()):
            toolbar.removeAction(action)

        if home_act:
            home_act.setText("Reset view")
            home_act.setShortcut(QKeySequence("R"))
            home_act.setToolTip("Reset view (R) — show entire trace")
            home_act.setStatusTip("Reset the plot to the full time range.")
            home_act.setIcon(QIcon(self.icon_path("Home.svg")))

        if back_act:
            back_act.setText("Back")
            back_act.setToolTip("Back — previous view")
            back_act.setIcon(QIcon(self.icon_path("Back.svg")))

        if forward_act:
            forward_act.setText("Forward")
            forward_act.setToolTip("Forward — next view")
            forward_act.setIcon(QIcon(self.icon_path("Forward.svg")))

        if pan_act:
            pan_act.setText("Pan")
            pan_act.setToolTip("Pan (P) — drag to move")
            pan_act.setStatusTip("Drag to move the view. Press Esc to exit.")
            pan_act.setIcon(QIcon(self.icon_path("Pan.svg")))
            pan_act.setShortcut(QKeySequence("P"))
            pan_act.setCheckable(True)

        if zoom_act:
            zoom_act.setText("Zoom")
            zoom_act.setToolTip("Zoom (Z) — draw a box to zoom")
            zoom_act.setStatusTip("Drag a rectangle to zoom in. Press Esc to exit.")
            zoom_act.setIcon(QIcon(self.icon_path("Zoom.svg")))
            zoom_act.setShortcut(QKeySequence("Z"))
            zoom_act.setCheckable(True)

        if subplots_act:
            subplots_act.setVisible(False)

        if save_act:
            toolbar.removeAction(save_act)

        self.actReset = home_act
        self.actBack = back_act
        self.actForward = forward_act
        self.actPan = pan_act
        self.actZoom = zoom_act

        if self.actReset:
            toolbar.addAction(self.actReset)
        if self.actBack:
            toolbar.addAction(self.actBack)
        if self.actForward:
            toolbar.addAction(self.actForward)

        toolbar.addSeparator()

        if self.actPan:
            toolbar.addAction(self.actPan)
        if self.actZoom:
            toolbar.addAction(self.actZoom)

        self._nav_mode_actions = [
            act for act in (self.actPan, self.actZoom) if act is not None
        ]
        for action in self._nav_mode_actions:
            try:
                action.toggled.disconnect(self._handle_nav_mode_toggled)
            except Exception:
                pass
            action.toggled.connect(self._handle_nav_mode_toggled)

        toolbar.addSeparator()

        self.actGrid = QAction(QIcon(self.icon_path("Grid.svg")), "Grid", self)
        self.actGrid.setCheckable(True)
        self.actGrid.setChecked(self.grid_visible)
        self.actGrid.setShortcut(QKeySequence("G"))
        self.actGrid.setToolTip("Toggle grid (G)")
        try:
            self.actGrid.triggered.disconnect(self._on_grid_action_triggered)
        except Exception:
            pass
        self.actGrid.triggered.connect(self._on_grid_action_triggered)
        toolbar.addAction(self.actGrid)

        self.actStyle = QAction(
            QIcon(self.icon_path("plot-settings.svg")), "Style", self
        )
        self.actStyle.setToolTip("Open plot style settings")
        try:
            self.actStyle.triggered.disconnect(self.open_unified_plot_settings_dialog)
        except Exception:
            pass
        self.actStyle.triggered.connect(self.open_unified_plot_settings_dialog)
        toolbar.addAction(self.actStyle)

        self.actEditPoints = QAction(
            QIcon(self.icon_path("tour-pencil.svg")), "Edit Points", self
        )
        self.actEditPoints.setToolTip(
            "Edit raw points in the current view (opens the Point Editor)"
        )
        self.actEditPoints.setEnabled(False)
        self.actEditPoints.triggered.connect(self._on_edit_points_triggered)
        toolbar.addAction(self.actEditPoints)

        self._sync_event_controls()
        self._sync_grid_action()
        self._update_trace_controls_state()

        return toolbar

    def _handle_nav_mode_toggled(self, checked: bool) -> None:
        if not checked:
            return
        sender = self.sender()
        for action in self._nav_mode_actions:
            if action is sender:
                continue
            if action.isChecked():
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)

    def _on_grid_action_triggered(self) -> None:
        self.toggle_grid()
        self._sync_grid_action()

    def _sync_grid_action(self) -> None:
        if self.actGrid is None:
            return
        desired = bool(self.grid_visible)
        if self.actGrid.isChecked() != desired:
            self.actGrid.blockSignals(True)
            self.actGrid.setChecked(desired)
            self.actGrid.blockSignals(False)

    def _on_event_lines_toggled(self, checked: bool) -> None:
        self._event_lines_visible = bool(checked)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_event_lines_visible(self._event_lines_visible)
        else:
            self._toggle_event_lines_legacy(self._event_lines_visible)
        self._sync_event_controls()

    def _on_event_label_mode_auto(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("auto")

    def _on_event_label_mode_all(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("all")

    def _on_event_label_mode_none(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("none")

    def _set_event_label_mode(self, mode: str) -> None:
        normalized = mode.lower()
        if normalized not in {"auto", "all", "none"}:
            normalized = "auto"
        if normalized == self._event_label_mode:
            return
        self._event_label_mode = normalized
        self._apply_event_label_mode()
        self._sync_event_controls()

    def _apply_event_label_mode(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            self._annotation_lane_visible = self._event_label_mode != "none"
            self._refresh_event_annotation_artists()
            self.canvas.draw_idle()
            return

        if self._event_label_mode == "none":
            self._annotation_lane_visible = False
            plot_host.set_event_labels_visible(False)
            plot_host.set_annotation_entries([])
        else:
            self._annotation_lane_visible = True
            gap = (
                8 if self._event_label_mode == "all" else self._event_label_gap_default
            )
            plot_host.set_event_label_gap(gap)
            plot_host.set_event_labels_visible(True)
            entries = self.event_annotations if self._annotation_lane_visible else []
            plot_host.set_annotation_entries(entries)
        self._refresh_event_annotation_artists()
        self.canvas.draw_idle()

    def _sync_event_controls(self) -> None:
        if (
            self.actEventLines is not None
            and self.actEventLines.isChecked() != self._event_lines_visible
        ):
            self.actEventLines.blockSignals(True)
            self.actEventLines.setChecked(self._event_lines_visible)
            self.actEventLines.blockSignals(False)

        if (
            self.menu_event_lines_action is not None
            and self.menu_event_lines_action.isChecked() != self._event_lines_visible
        ):
            self.menu_event_lines_action.blockSignals(True)
            self.menu_event_lines_action.setChecked(self._event_lines_visible)
            self.menu_event_lines_action.blockSignals(False)

        mode = self._event_label_mode
        mapping = {
            "auto": self.actEventLabelsAuto,
            "all": self.actEventLabelsAll,
            "none": self.actEventLabelsNone,
        }
        for key, action in mapping.items():
            if action is None:
                continue
            should_check = mode == key
            if action.isChecked() != should_check:
                action.blockSignals(True)
                action.setChecked(should_check)
                action.blockSignals(False)
            if key == "all":
                action.setEnabled(self._event_label_mode != "none")
            else:
                action.setEnabled(True)

        if self.menu_event_labels_action is not None:
            should = mode != "none"
            if self.menu_event_labels_action.isChecked() != should:
                self.menu_event_labels_action.blockSignals(True)
                self.menu_event_labels_action.setChecked(should)
                self.menu_event_labels_action.blockSignals(False)

    def _update_trace_controls_state(self) -> None:
        has_trace = (
            self.trace_data is not None
            and getattr(self.trace_data, "empty", False) is False
        )
        if self.id_toggle_act is not None:
            self.id_toggle_act.setEnabled(has_trace)
        has_outer = bool(
            has_trace
            and self.trace_data is not None
            and "Outer Diameter" in self.trace_data.columns
        )
        if self.od_toggle_act is not None:
            self.od_toggle_act.setEnabled(has_outer)
            if not has_outer and self.od_toggle_act.isChecked():
                self.od_toggle_act.blockSignals(True)
                self.od_toggle_act.setChecked(False)
                self.od_toggle_act.blockSignals(False)
        if getattr(self, "actEditPoints", None) is not None:
            self.actEditPoints.setEnabled(has_trace)

    def _toggle_event_lines_legacy(self, visible: bool) -> None:
        ax = getattr(self, "ax", None)
        if ax is None:
            return
        for line in ax.get_lines():
            if line.get_gid() == "event_line":
                line.set_visible(visible)
        self.canvas.draw_idle()

    def show_snapshot_context_menu(self, pos):
        if not hasattr(self, "snapshot_frames") or not self.snapshot_frames:
            return

        menu = QMenu(self)
        action = getattr(self, "action_snapshot_metadata", None)
        if action is not None:
            menu.addAction(action)

        has_metadata = bool(getattr(self, "frames_metadata", []))
        copy_action = None
        if has_metadata:
            if action is not None:
                menu.addSeparator()
            copy_action = menu.addAction("📄 Copy Metadata to Clipboard")

        chosen = menu.exec_(self.snapshot_label.mapToGlobal(pos))
        if chosen is copy_action and has_metadata:
            self.copy_current_frame_metadata_to_clipboard()

    def copy_current_frame_metadata_to_clipboard(self) -> None:
        if not getattr(self, "frames_metadata", None):
            return

        idx = min(self.current_frame, len(self.frames_metadata) - 1)
        if idx < 0:
            return

        metadata = self.frames_metadata[idx] or {}
        if not metadata:
            QApplication.clipboard().setText("")
            return

        lines = []
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, (list, tuple, np.ndarray)):
                arr = np.array(value)
                if arr.size > 16:
                    value_repr = f"Array shape {arr.shape}"
                else:
                    value_repr = np.array2string(arr, separator=", ")
            else:
                value_repr = value
            lines.append(f"{key}: {value_repr}")

        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Frame metadata copied to clipboard", 2000)

    # [D] ========================= FILE LOADERS: TRACE / EVENTS / TIFF =====================
    def load_trace_and_event_files(self, trace_path):
        """Load a trace file and its matching events if available."""
        log.info("Importing trace file %s", trace_path)
        cache = self._ensure_data_cache(trace_path)
        (
            df,
            labels,
            times,
            frames,
            diam,
            od_diam,
            import_meta,
        ) = load_trace_and_events(trace_path, cache=cache)

        self.trace_data = self._prepare_trace_dataframe(df)
        self._last_event_import = import_meta or {}
        self.trace_file_path = os.path.dirname(trace_path)
        trace_filename = os.path.basename(trace_path)
        self.sampling_rate_hz = self._compute_sampling_rate(self.trace_data)
        self._set_status_source(f"Trace · {trace_filename}", trace_path)
        self._reset_session_dirty()
        self.show_analysis_workspace()

        if labels:
            self.load_project_events(labels, times, frames, diam, od_diam)
        else:
            self.event_labels = []
            self.event_times = []
            self.event_frames = []
            self.event_table_data = []
            self.populate_table()
            self.xlim_full = None
            self.ylim_full = None
            self.update_plot()

        status_notes: list[str] = []
        neg_inner = int(self.trace_data.attrs.get("negative_inner_diameters", 0) or 0)
        if neg_inner:
            status_notes.append(f"Ignored {neg_inner} negative inner-diameter samples")
        neg_outer = int(self.trace_data.attrs.get("negative_outer_diameters", 0) or 0)
        if neg_outer:
            status_notes.append(f"Ignored {neg_outer} negative outer-diameter samples")

        if import_meta:
            event_file = import_meta.get("event_file")
            if import_meta.get("auto_detected") and event_file:
                event_name = os.path.basename(str(event_file))
                if "_table" in event_name.lower():
                    status_notes.append(f"Matched events: {event_name}")

            ignored = int(import_meta.get("ignored_out_of_range", 0) or 0)
            if ignored:
                status_notes.append(f"{ignored} events ignored (time out of range)")

            dropped = int(import_meta.get("dropped_missing_time", 0) or 0)
            if dropped:
                status_notes.append(f"{dropped} events skipped (missing time/frame)")

            if import_meta.get("frame_fallback_used"):
                count = int(import_meta.get("frame_fallback_rows", 0) or 0)
                detail = f"{count} events" if count else "events"
                status_notes.append(f"Aligned {detail} by frame order (no timestamps)")

        self.compute_frame_trace_indices()
        self.update_scroll_slider()
        self.event_table.apply_theme()

        if status_notes:
            self.statusBar().showMessage(" · ".join(status_notes), 5000)

        log.info("Trace import complete with %d events", len(labels))

        if hasattr(self, "load_events_action") and self.load_events_action is not None:
            self.load_events_action.setEnabled(True)

        self._update_home_resume_button()

        return self.trace_data

    def load_trace_and_events(self, file_path=None, tiff_path=None):
        # --- Prep ---
        snapshots = None
        self._clear_canvas_and_table()
        # 1) Prompt for CSV if needed
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Trace File", "", "CSV Files (*.csv)"
            )
            if not file_path:
                return

        # 2) Load trace and events using helper
        try:
            self.load_trace_and_event_files(file_path)
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

        # 4) Helper already populated events & UI

        # 5) Ask if they want to load a TIFF
        if tiff_path is None:
            resp = QMessageBox.question(
                self,
                "Load TIFF?",
                "Would you like to load a Result TIFF file?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp == QMessageBox.Yes:
                tiff_path, _ = QFileDialog.getOpenFileName(
                    self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
                )

        if tiff_path:
            try:
                snapshots, _ = load_tiff(tiff_path, metadata=False)
                self.load_snapshots(snapshots)
                self.toggle_snapshot_viewer(True)
            except Exception as e:
                QMessageBox.warning(
                    self, "TIFF Load Error", f"Failed to load TIFF:\n{e}"
                )

        # 6) If a project and experiment are active, auto-add this dataset
        if self.current_project and self.current_experiment:
            sample_name = os.path.splitext(os.path.basename(file_path))[0]
            sample = SampleN(name=sample_name, trace_path=file_path)
            event_path = find_matching_event_file(file_path)
            if event_path and os.path.exists(event_path):
                sample.events_path = event_path
            if snapshots is not None:
                sample.snapshots = np.stack(snapshots)
            self.current_experiment.samples.append(sample)
            self.current_sample = sample
            self.refresh_project_tree()
            if self.current_project.path:
                save_project_file(self.current_project, self.current_project.path)
            self.statusBar().showMessage(
                f"\u2713 {sample_name} loaded into Experiment '{self.current_experiment.name}'",
                3000,
            )

    def _load_events_from_path(self, file_path: str) -> bool:
        try:
            labels, times, frames = load_events(file_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Events Load Error",
                f"Could not load events:\n{exc}",
            )
            return False

        if not labels:
            QMessageBox.information(
                self, "No Events Found", "The selected file contained no events."
            )
            return False

        if frames is None:
            frames = [0] * len(labels)

        self.load_project_events(labels, times, frames, None, None)
        self._last_event_import = {"event_file": file_path, "manual": True}
        self.statusBar().showMessage(f"{len(labels)} events loaded", 3000)
        self.mark_session_dirty()
        return True

    def populate_table(self):
        has_od = (
            self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        )
        self.event_table_controller.set_events(
            self.event_table_data, has_outer_diameter=has_od
        )
        self._update_excel_controls()

    def _update_excel_controls(self):
        """Enable or disable Excel mapping actions based on available data."""
        has_data = bool(getattr(self, "event_table_data", None))
        if hasattr(self, "excel_action") and self.excel_action is not None:
            self.excel_action.setEnabled(has_data)
        action_map = getattr(self, "action_map_excel", None)
        if action_map is not None:
            action_map.setEnabled(has_data)
        action_export = getattr(self, "action_export_excel", None)
        if action_export is not None:
            action_export.setEnabled(has_data)

    def _load_snapshot_from_path(self, file_path: str) -> bool:
        """Load a snapshot TIFF from ``file_path`` and update the viewer."""

        try:
            frames, frames_metadata = load_tiff(file_path)
            valid_frames = []
            valid_metadata = []

            for i, frame in enumerate(frames):
                if frame is not None and frame.size > 0:
                    valid_frames.append(frame)
                    if i < len(frames_metadata):
                        valid_metadata.append(frames_metadata[i])
                    else:
                        valid_metadata.append({})

            if len(valid_frames) < len(frames):
                QMessageBox.warning(
                    self, "TIFF Warning", "Skipped empty or corrupted TIFF frames."
                )

            if not valid_frames:
                QMessageBox.warning(
                    self,
                    "TIFF Load Error",
                    "No valid frames were found in the dropped TIFF file.",
                )
                return False

            self.snapshot_frames = valid_frames
            self.frames_metadata = valid_metadata

            if self.frames_metadata:
                first_meta = self.frames_metadata[0] or {}
                found = False
                for key in ("Rec_intvl", "FrameInterval", "FrameTime"):
                    if key in first_meta:
                        try:
                            val = float(str(first_meta[key]).replace("ms", "").strip())
                            if val > 1:
                                val /= 1000.0
                            if val > 0:
                                self.recording_interval = val
                                found = True
                        except (ValueError, TypeError):
                            pass
                        break
                if not found:
                    self.recording_interval = 0.14
            else:
                self.recording_interval = 0.14

            self.frame_times = []
            if self.frames_metadata:
                for idx, meta in enumerate(self.frames_metadata):
                    self.frame_times.append(
                        meta.get("FrameTime", idx * self.recording_interval)
                    )
            else:
                for idx in range(len(self.snapshot_frames)):
                    self.frame_times.append(idx * self.recording_interval)

            self.compute_frame_trace_indices()

            self.display_frame(0)
            self.slider.setMinimum(0)
            self.slider.setMaximum(len(self.snapshot_frames) - 1)
            self.slider.setValue(0)
            self.prev_frame_btn.setEnabled(True)
            self.next_frame_btn.setEnabled(True)
            self.play_pause_btn.setEnabled(True)
            self.snapshot_speed_label.setEnabled(True)
            self.snapshot_speed_combo.setEnabled(True)
            self._set_playback_state(False)
            self.update_snapshot_size()
            self._clear_slider_markers()
            self._configure_snapshot_timer()
            self._apply_frame_change(0)
            self.toggle_snapshot_viewer(True)

            if self.current_sample is not None:
                try:
                    self.current_sample.snapshots = np.stack(self.snapshot_frames)
                    self.current_sample.snapshot_path = os.path.abspath(file_path)
                except Exception:
                    pass
                self.mark_session_dirty()
                self.auto_save_project(reason="snapshot")

            return True

        except Exception as e:
            QMessageBox.critical(self, "TIFF Load Error", f"Failed to load TIFF:\n{e}")
            return False

    def load_snapshot(self):
        # 1) Prompt for TIFF
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if not file_path:
            return

        self._load_snapshot_from_path(file_path)

    def save_analysis(self):
        QMessageBox.information(
            self,
            "Save HDF5",
            "Legacy HDF5 files are no longer supported. Use Project > Save Project instead.",
        )

    def open_analysis(self, path=None):
        # QAction.triggered passes a boolean 'checked' argument. If this method
        # is connected directly to that signal, ``path`` may receive a bool
        # instead of the actual file path. Guard against that by treating a
        # boolean as ``None`` so the file dialog is shown.
        QMessageBox.information(
            self,
            "Import HDF5",
            "Legacy HDF5 files are no longer supported. Use Project > Open Project instead.",
        )

    def load_trace(self, t, d, od=None):
        import pandas as pd

        data = {"Time (s)": t, "Inner Diameter": d}
        if od is not None:
            data["Outer Diameter"] = od
        self.trace_data = self._prepare_trace_dataframe(pd.DataFrame(data))
        self.compute_frame_trace_indices()
        self.xlim_full = None
        self.ylim_full = None
        self.update_plot()
        self.update_scroll_slider()
        self.sampling_rate_hz = self._compute_sampling_rate(self.trace_data)
        self._update_status_chip()
        self._reset_session_dirty()

    def load_events(self, labels, diam_before, od_before=None):
        self.event_labels = list(labels)
        self.event_table_data = []
        has_od = od_before is not None
        if not has_od:
            for lbl, diam in zip(labels, diam_before):
                self.event_table_data.append((lbl, 0.0, diam, 0))
        else:
            for lbl, diam_i, diam_o in zip(labels, diam_before, od_before):
                self.event_table_data.append((lbl, 0.0, diam_i, diam_o, 0))
        self.populate_table()

    def load_project_events(self, labels, times, frames, diam_before, od_before=None):
        self.event_labels = list(labels)
        if times is not None:
            self.event_times = pd.to_numeric(times, errors="coerce").tolist()
        else:
            self.event_times = []

        if frames is not None:
            self.event_frames = (
                pd.to_numeric(pd.Series(frames), errors="coerce")
                .fillna(0)
                .astype(int)
                .tolist()
            )
        else:
            self.event_frames = [0] * len(self.event_times)
        self.event_table_data = []
        has_od = od_before is not None or "Outer Diameter" in self.trace_data.columns

        if self.trace_data is not None and self.event_times:
            arr_t = self.trace_data["Time (s)"].values
            arr_d = self.trace_data["Inner Diameter"].values
            arr_od = (
                self.trace_data["Outer Diameter"].values
                if "Outer Diameter" in self.trace_data.columns
                else None
            )
            for lbl, t, fr in zip(
                self.event_labels,
                self.event_times,
                self.event_frames,
            ):
                if pd.isna(t):
                    continue
                idx = int(np.argmin(np.abs(arr_t - t)))
                diam = float(arr_d[idx])
                if has_od and arr_od is not None:
                    od_val = float(arr_od[idx])
                    self.event_table_data.append((lbl, float(t), diam, od_val, int(fr)))
                else:
                    self.event_table_data.append((lbl, float(t), diam, int(fr)))
        else:
            if has_od:
                for lbl, t, fr, diam_i, diam_o in zip(
                    self.event_labels,
                    self.event_times,
                    self.event_frames,
                    diam_before,
                    od_before,
                ):
                    if pd.isna(t):
                        continue
                    self.event_table_data.append(
                        (lbl, float(t), float(diam_i), float(diam_o), int(fr))
                    )
            else:
                for lbl, t, fr, diam in zip(
                    self.event_labels,
                    self.event_times,
                    self.event_frames,
                    diam_before,
                ):
                    if pd.isna(t):
                        continue
                    self.event_table_data.append((lbl, float(t), float(diam), int(fr)))

        self.populate_table()
        self.xlim_full = None
        self.ylim_full = None
        self.update_plot()
        self._apply_event_label_mode()
        self._sync_event_controls()
        self._update_trace_controls_state()

    def load_snapshots(self, stack):
        self.snapshot_frames = [frame for frame in stack]
        if self.snapshot_frames:
            self.frame_times = [
                idx * self.recording_interval
                for idx in range(len(self.snapshot_frames))
            ]
            self.compute_frame_trace_indices()
            self.slider.setMinimum(0)
            self.slider.setMaximum(len(self.snapshot_frames) - 1)
            self.slider.setValue(0)
            self.display_frame(0)
            self.prev_frame_btn.setEnabled(True)
            self.next_frame_btn.setEnabled(True)
            self.play_pause_btn.setEnabled(True)
            self.snapshot_speed_label.setEnabled(True)
            self.snapshot_speed_combo.setEnabled(True)
            self._set_playback_state(False)
            self._configure_snapshot_timer()

    def compute_frame_trace_indices(self):
        """Map each frame time to the closest index in the loaded trace."""
        if self.trace_data is None or not self.frame_times:
            self.frame_trace_indices = []
            return

        t_trace = self.trace_data["Time (s)"].values
        frame_times = np.asarray(self.frame_times, dtype=float)

        if len(frame_times) > 1:
            dt_trace = float(t_trace[-1]) - float(t_trace[0])
            dt_frames = float(frame_times[-1]) - float(frame_times[0])
            scale = dt_trace / dt_frames if dt_frames != 0 else 1.0
        else:
            scale = 1.0

        adjusted = (frame_times - frame_times[0]) * scale + t_trace[0]

        idx = np.searchsorted(t_trace, adjusted, side="left")
        idx = np.clip(idx, 0, len(t_trace) - 1)
        self.frame_trace_indices = idx

    def apply_style(self, style):
        self._apply_time_window(style.get("xlim", self.ax.get_xlim()))
        self.ax.set_ylim(*style.get("ylim", self.ax.get_ylim()))
        self.ax.set_xscale(style.get("xscale", self.ax.get_xscale()))
        self.ax.set_yscale(style.get("yscale", self.ax.get_yscale()))
        font = self.event_table.font()
        font.setPointSize(style.get("table_fontsize", font.pointSize()))
        self.event_table.setFont(font)
        # Ensure the scroll slider visibility matches the restored limits
        self.update_scroll_slider()
        self.canvas.draw_idle()

    def set_current_frame(self, idx):
        if not self.snapshot_frames:
            return
        idx = max(0, min(int(idx), len(self.snapshot_frames) - 1))
        if self.slider.value() != idx:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
        self._apply_frame_change(idx)

    def display_frame(self, index):
        if not self.snapshot_frames:
            return

        # Clamp index to valid range
        if index < 0 or index >= len(self.snapshot_frames):
            log.warning("Frame index %s out of bounds.", index)
            return

        frame = self.snapshot_frames[index]

        # Skip if frame is empty or corrupted
        if frame is None or frame.size == 0:
            log.warning("Skipping empty or corrupted frame at index %s", index)
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

            target_width = self.event_table.viewport().width()
            if target_width <= 0:
                target_width = self.snapshot_label.width()
            pix = QPixmap.fromImage(q_img).scaledToWidth(
                target_width, Qt.SmoothTransformation
            )
            self.snapshot_label.setFixedSize(pix.width(), pix.height())
            self.snapshot_label.setPixmap(pix)
        except Exception as e:
            log.error("Error displaying frame %s: %s", index, e)

    def update_snapshot_size(self):
        if not self.snapshot_frames:
            return
        self.display_frame(self.current_frame)

    def eventFilter(self, source, event):
        event_table = getattr(self, "event_table", None)
        if (
            event_table is not None
            and source is event_table
            and event.type() == QEvent.Resize
        ):
            QTimer.singleShot(0, self.update_snapshot_size)
        elif source is self.trace_file_label and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._update_status_chip)
        return super().eventFilter(source, event)

    def change_frame(self):
        if not self.snapshot_frames:
            return

        idx = self.slider.value()
        self._apply_frame_change(idx)

    def _apply_frame_change(self, idx: int):
        self.current_frame = idx
        self.display_frame(idx)
        self.update_slider_marker()
        self._update_snapshot_status(idx)
        self._update_metadata_display(idx)

    def _update_snapshot_status(self, idx: int) -> None:
        total = len(self.snapshot_frames) if self.snapshot_frames else 0
        if total <= 0:
            self.snapshot_time_label.setText("Frame 0 / 0")
            return

        frame_number = idx + 1
        timestamp = None
        if self.frame_times and idx < len(self.frame_times):
            try:
                timestamp = float(self.frame_times[idx])
            except (TypeError, ValueError):
                timestamp = None
        if timestamp is None and self.recording_interval:
            try:
                timestamp = idx * float(self.recording_interval)
            except (TypeError, ValueError):
                timestamp = None

        if timestamp is None:
            self.snapshot_time_label.setText(f"Frame {frame_number} / {total}")
        else:
            self.snapshot_time_label.setText(
                f"Frame {frame_number} / {total} @ {timestamp:.2f} s"
            )

    def _update_metadata_display(self, idx: int) -> None:
        self._update_metadata_button_state()
        if not getattr(self, "frames_metadata", None):
            action = getattr(self, "action_snapshot_metadata", None)
            if action is not None:
                action.setText("Metadata…")
            return
        if idx >= len(self.frames_metadata):
            return

        metadata = self.frames_metadata[idx] or {}
        tag_count = len(metadata)
        tag_label = "tag" if tag_count == 1 else "tags"
        action = getattr(self, "action_snapshot_metadata", None)
        if action is not None:
            action.setText(f"Metadata ({tag_count} {tag_label})")

        if not metadata:
            self.metadata_details_label.setText("No metadata for this frame.")
            return

        lines = []
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, (list, tuple, np.ndarray)):
                arr = np.array(value)
                if arr.size > 16:
                    value_repr = f"Array shape {arr.shape}"
                else:
                    value_repr = np.array2string(arr, separator=", ")
            else:
                value_repr = value

            value_repr = str(value_repr).strip()
            escaped_value = html.escape(value_repr).replace("\n", "<br>")
            escaped_key = html.escape(str(key))
            lines.append(f"<b>{escaped_key}</b>: {escaped_value}")

        self.metadata_details_label.setText("<br>".join(lines))

    def _update_metadata_button_state(self) -> None:
        action = getattr(self, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(self, "frames_metadata", []))
        has_frames = bool(self.snapshot_frames)
        enabled = has_metadata and has_frames and self.snapshot_label.isVisible()

        if action is not None:
            action.setEnabled(enabled)
            if not enabled:
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
                action.setText("Metadata…")

        if not enabled:
            self.metadata_panel.hide()
            self.metadata_details_label.setText("No metadata available.")
            return

        is_visible = self.snapshot_label.isVisible()
        should_show = bool(action and action.isChecked() and enabled)
        self.metadata_panel.setVisible(should_show)
        if not should_show and not is_visible:
            # keep summary text in sync when hiding with the viewer
            self.metadata_details_label.setText("No metadata available.")

    def on_snapshot_speed_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "snapshot_speed_combo"):
            return

        data = self.snapshot_speed_combo.itemData(index)
        try:
            speed = float(data)
        except (TypeError, ValueError):
            speed = 1.0

        if speed <= 0:
            speed = 1.0

        self.snapshot_speed_multiplier = speed

        if not hasattr(self, "snapshot_timer"):
            return

        was_active = self.snapshot_timer.isActive()
        self._configure_snapshot_timer()

        if was_active and self.snapshot_frames:
            self.snapshot_timer.start()

    def _reset_snapshot_speed(self) -> None:
        self.snapshot_speed_multiplier = 1.0

        if hasattr(self, "snapshot_speed_combo"):
            self.snapshot_speed_combo.blockSignals(True)
            self.snapshot_speed_combo.setCurrentIndex(
                getattr(self, "snapshot_speed_default_index", 0)
            )
            self.snapshot_speed_combo.blockSignals(False)

            data = self.snapshot_speed_combo.itemData(
                getattr(self, "snapshot_speed_default_index", 0)
            )
            try:
                self.snapshot_speed_multiplier = float(data)
            except (TypeError, ValueError):
                self.snapshot_speed_multiplier = 1.0

        if hasattr(self, "snapshot_timer"):
            self._configure_snapshot_timer()

    def _configure_snapshot_timer(self) -> None:
        try:
            interval = float(self.recording_interval)
        except (TypeError, ValueError):
            interval = 0.14

        if not interval:
            interval = 0.14

        try:
            speed = float(self.snapshot_speed_multiplier)
        except (TypeError, ValueError):
            speed = 1.0

        if speed <= 0:
            speed = 1.0

        effective_interval = interval / speed if interval else 0.14
        interval_ms = max(20, int(round(effective_interval * 1000)))
        self.snapshot_timer.setInterval(interval_ms)

    def _set_playback_state(self, playing: bool) -> None:
        if not hasattr(self, "snapshot_timer"):
            return

        if not playing or not self.snapshot_frames:
            playing = False
            self.snapshot_timer.stop()
        else:
            self._configure_snapshot_timer()
            self.snapshot_timer.start()

        self.play_pause_btn.blockSignals(True)
        self.play_pause_btn.setChecked(playing)
        self.play_pause_btn.blockSignals(False)

        icon_role = QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay
        self.play_pause_btn.setIcon(self.style().standardIcon(icon_role))
        self.play_pause_btn.setText("Pause" if playing else "Play")
        tooltip = "Pause snapshot playback" if playing else "Play snapshot sequence"
        self.play_pause_btn.setToolTip(tooltip)

    def toggle_snapshot_playback(self, checked: bool) -> None:
        if checked and not self.snapshot_frames:
            self._set_playback_state(False)
            return
        self._set_playback_state(bool(checked))

    def advance_snapshot_frame(self) -> None:
        if not self.snapshot_frames:
            self._set_playback_state(False)
            return

        next_idx = (self.current_frame + 1) % len(self.snapshot_frames)
        self.set_current_frame(next_idx)

    def step_previous_frame(self) -> None:
        if not self.snapshot_frames:
            return
        if self.play_pause_btn.isChecked():
            self._set_playback_state(False)
        idx = (self.current_frame - 1) % len(self.snapshot_frames)
        self.set_current_frame(idx)

    def step_next_frame(self) -> None:
        if not self.snapshot_frames:
            return
        if self.play_pause_btn.isChecked():
            self._set_playback_state(False)
        idx = (self.current_frame + 1) % len(self.snapshot_frames)
        self.set_current_frame(idx)

    def set_snapshot_metadata_visible(self, visible: bool) -> None:
        action = getattr(self, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(self, "frames_metadata", []))
        can_show = (
            has_metadata
            and bool(self.snapshot_frames)
            and self.snapshot_label.isVisible()
        )
        should_show = bool(visible) and can_show

        if action is not None and action.isChecked() != should_show:
            action.blockSignals(True)
            action.setChecked(should_show)
            action.blockSignals(False)

        self.metadata_panel.setVisible(should_show)
        if should_show:
            self._update_metadata_display(self.current_frame)
        else:
            if not can_show:
                self.metadata_details_label.setText("No metadata available.")
            self._update_metadata_button_state()

    def _clear_slider_markers(self) -> None:
        """Remove existing slider markers from all axes."""
        self._time_cursor_time = None
        self._time_cursor_visible = True
        if hasattr(self, "plot_host"):
            try:
                self.plot_host.set_time_cursor(None, visible=False)
            except Exception:
                pass
        self._clear_event_highlight()
        markers = getattr(self, "slider_markers", None)
        if not markers:
            self.slider_markers = {}
            return
        for line in list(markers.values()):
            try:
                line.remove()
            except Exception:
                pass
        markers.clear()

    def update_slider_marker(self):
        # Make sure we have a trace and some TIFF frames
        if self.trace_data is None or not self.snapshot_frames:
            return

        # 1) Get the current slider index
        idx = self.slider.value()

        # 2) Lookup the timestamp for this frame
        if len(self.frame_trace_indices) > 0 and idx < len(self.frame_trace_indices):
            trace_idx = self.frame_trace_indices[idx]
            t_current = self.trace_data["Time (s)"].iat[trace_idx]
        elif idx < len(self.frame_times):
            t_current = self.frame_times[idx]
        else:
            t_current = idx * self.recording_interval

        # 3) Drive the shared time cursor overlay (fallback on legacy per-axis markers)
        self._time_cursor_time = float(t_current)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            try:
                plot_host.set_time_cursor(
                    self._time_cursor_time,
                    visible=self._time_cursor_visible,
                )
                return
            except Exception:
                log.debug(
                    "PlotHost time cursor update failed; falling back to legacy markers",
                    exc_info=True,
                )

        axes = [self.ax] if getattr(self, "ax", None) is not None else []
        if not axes:
            return
        for ax in axes:
            line = self.slider_markers.get(ax)
            if line is None or line.axes is None:
                line = ax.axvline(
                    x=t_current,
                    color="red",
                    linestyle="--",
                    linewidth=1.5,
                    label="TIFF Frame",
                    zorder=5,
                )
                self.slider_markers[ax] = line
            else:
                line.set_xdata([t_current, t_current])
        self.canvas.draw_idle()

    def populate_event_table_from_df(self, df):
        rows = []
        has_od = any(
            col.lower().startswith("od") or "outer" in col.lower() for col in df.columns
        )

        for _, item in df.iterrows():
            label = item.get("EventLabel", item.get("Event", ""))
            time_val = item.get("Time (s)", item.get("Time", 0.0))
            id_val = item.get("ID (µm)", item.get("Inner Diameter", 0.0))
            frame_val = item.get("Frame", 0)

            try:
                time_val = float(time_val)
            except (TypeError, ValueError):
                time_val = 0.0

            try:
                id_val = float(id_val)
            except (TypeError, ValueError):
                id_val = 0.0

            if has_od:
                od_val = item.get("OD (µm)", item.get("Outer Diameter", None))
                try:
                    od_val = float(od_val) if od_val is not None else None
                except (TypeError, ValueError):
                    od_val = None
                try:
                    frame_val = int(frame_val)
                except (TypeError, ValueError):
                    frame_val = 0
                rows.append((str(label), time_val, id_val, od_val, frame_val))
            else:
                try:
                    frame_val = int(frame_val)
                except (TypeError, ValueError):
                    frame_val = 0
                rows.append((str(label), time_val, id_val, frame_val))

        self.event_table_data = rows
        self.event_table_controller.set_events(rows, has_outer_diameter=has_od)
        self._update_excel_controls()

    def update_event_label_positions(self, event=None):
        """Legacy hook; annotation lane handles positioning automatically."""
        return

    def _init_hover_artists(self) -> None:
        """Create per-axis hover annotations and crosshair lines."""

        for line in getattr(self, "_hover_vlines", []) or []:
            if line is None:
                continue
            try:
                line.remove()
            except Exception:
                pass
        self._hover_vlines = []
        self._hover_vline_inner = None
        self._hover_vline_outer = None

        for annot in (
            getattr(self, "hover_annotation_id", None),
            getattr(self, "hover_annotation_od", None),
        ):
            if annot is None:
                continue
            try:
                annot.remove()
            except Exception:
                pass

        line_color = CURRENT_THEME.get(
            "cursor_line", CURRENT_THEME.get("grid_color", "#6e7687")
        )

        def _make_annotation(target_ax):
            return target_ax.annotate(
                text="",
                xy=(0.0, 0.0),
                xytext=(10, 10),
                textcoords="offset points",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                    ec=CURRENT_THEME["hover_label_border"],
                    lw=1,
                ),
                arrowprops=dict(arrowstyle="->"),
                fontsize=9,
                color=CURRENT_THEME["text"],
            )

        self.hover_annotation_id = None
        self.hover_annotation_od = None

        if self.ax is not None:
            self.hover_annotation_id = _make_annotation(self.ax)
            self.hover_annotation_id.set_visible(False)
            vline = self.ax.axvline(np.nan, color=line_color, linewidth=0.9, alpha=0.7)
            vline.set_visible(False)
            vline.set_zorder(55)
            self._hover_vline_inner = vline
            self._hover_vlines.append(vline)

        if self.ax2 is not None:
            self.hover_annotation_od = _make_annotation(self.ax2)
            self.hover_annotation_od.set_visible(False)
            vline = self.ax2.axvline(np.nan, color=line_color, linewidth=0.9, alpha=0.7)
            vline.set_visible(False)
            vline.set_zorder(55)
            self._hover_vline_outer = vline
            self._hover_vlines.append(vline)
        else:
            self.hover_annotation_od = None

    def _hide_hover_feedback(self) -> None:
        """Hide hover annotations and crosshair lines."""

        changed = False
        for annot in (
            getattr(self, "hover_annotation_id", None),
            getattr(self, "hover_annotation_od", None),
        ):
            if annot is not None and annot.get_visible():
                annot.set_visible(False)
                changed = True
        for line in getattr(self, "_hover_vlines", []) or []:
            if line is not None and line.get_visible():
                line.set_visible(False)
                changed = True
        if changed:
            self.canvas.draw_idle()

    def _handle_figure_leave(self, _event=None) -> None:
        self.canvas.setToolTip("")
        self._hide_hover_feedback()

    def _is_supported_drop_file(self, path: str) -> bool:
        if not path or not os.path.isfile(path):
            return False

        lower = path.lower()
        return lower.endswith(
            (
                ".vaso",
                ".h5",
                ".fig.json",
                ".csv",
                ".tif",
                ".tiff",
            )
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if self._is_supported_drop_file(url.toLocalFile()):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        files = [p for p in paths if self._is_supported_drop_file(p)]

        if not files:
            event.ignore()
            return

        # Prioritize VasoAnalyzer project archives
        vaso_path = next((p for p in files if p.lower().endswith(".vaso")), None)
        if vaso_path:
            event.acceptProposedAction()
            try:
                project = load_project(vaso_path)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Project Load Error",
                    f"Could not open project:\n{e}",
                )
                return
            self._replace_current_project(project)
            self.refresh_project_tree()
            self.statusBar().showMessage(
                f"\u2713 Project loaded: {self.current_project.name}", 3000
            )
            return

        h5_path = next((p for p in files if p.lower().endswith(".h5")), None)
        if h5_path:
            event.acceptProposedAction()
            self.open_analysis(h5_path)
            return

        csv_files = [p for p in files if p.lower().endswith(".csv")]
        tiff_files = [
            p
            for p in files
            if p.lower().endswith(".tif") or p.lower().endswith(".tiff")
        ]

        if csv_files:
            event.acceptProposedAction()
            tiff_path = tiff_files[0] if tiff_files else None
            self.load_trace_and_events(file_path=csv_files[0], tiff_path=tiff_path)
            return

        if tiff_files:
            event.acceptProposedAction()
            self._load_snapshot_from_path(tiff_files[0])
            return

        fig_sessions = [p for p in files if p.lower().endswith(".fig.json")]
        if fig_sessions:
            event.acceptProposedAction()
            for session_path in fig_sessions:
                self.load_pickle_session(session_path)
            return

        event.ignore()

    def load_pickle_session(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                state = json.load(f)

            # Restore basic session state
            td = state.get("trace_data", None)
            if td is not None:
                import pandas as pd

                self.trace_data = self._prepare_trace_dataframe(pd.DataFrame(td))
            else:
                self.trace_data = None
            self.event_labels = state.get("event_labels", [])
            self.event_times = state.get("event_times", [])
            self.event_table_data = state.get("event_table_data", [])

            # Temporarily store plot style before update_plot() wipes things
            plot_style = state.get("plot_style", None)
            if plot_style:
                self.apply_plot_style(plot_style, persist=False)
            self.canvas.draw_idle()

            # Redraw plot without overwriting full-view limits
            self.update_plot(track_limits=False)

            # Restore axis labels, limits, grid
            self._set_shared_xlabel(state.get("xlabel", "Time (s)"))
            self.ax.set_ylabel(state.get("ylabel", "Inner Diameter (µm)"))
            self._apply_time_window(state.get("xlim", self.ax.get_xlim()))
            self.ax.set_ylim(*state.get("ylim", self.ax.get_ylim()))
            self.grid_visible = state.get("grid_visible", True)
            axes = self.plot_host.axes() if hasattr(self, "plot_host") else [self.ax]
            axes = [axis for axis in axes if axis is not None]
            for axis in axes:
                if self.grid_visible:
                    axis.grid(True, color=CURRENT_THEME["grid_color"])
                else:
                    axis.grid(False)

            # Ensure full-view limits are available for Home/Zoom Out
            if self.xlim_full is None:
                self.xlim_full = self.ax.get_xlim()
            if self.ylim_full is None:
                self.ylim_full = self.ax.get_ylim()

            # Re-plot pinned points
            self.pinned_points.clear()
            for x, y in state.get("pinned_points", []):
                marker = self.ax.plot(x, y, "ro", markersize=6)[0]
                label = self.ax.annotate(
                    f"{x:.2f} s\n{y:.1f} µm",
                    xy=(x, y),
                    xytext=(6, 6),
                    textcoords="offset points",
                    bbox=dict(
                        boxstyle="round,pad=0.3",
                        fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                        ec=CURRENT_THEME["hover_label_border"],
                        lw=1,
                    ),
                    fontsize=8,
                )
                self.pinned_points.append((marker, label))

            # Apply saved style LAST so it overrides any plot resets
            if plot_style:
                self.apply_plot_style(plot_style, persist=False)

            # Final UI updates
            self.canvas.draw_idle()
            self.populate_table()
            self.sampling_rate_hz = self._compute_sampling_rate(self.trace_data)
            self._set_status_source(
                f"Restored from: {os.path.basename(file_path)}",
                file_path,
            )
            self._reset_session_dirty()
            self.statusBar().showMessage("Session restored successfully.")
            log.info("Session reloaded with full metadata.")

        except Exception as e:
            QMessageBox.critical(self, "Load Failed", f"Error loading session:\n{e}")

    def _handle_load_trace(self):
        # Prompt for the trace file
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        self.load_trace_and_events(file_path)

    def _handle_load_events(self):
        if self.trace_data is None:
            QMessageBox.warning(
                self,
                "No Trace Loaded",
                "Load a trace before importing events so they can be aligned.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Events File",
            "",
            "Table Files (*.csv *.tsv *.txt);;All Files (*)",
        )
        if not file_path:
            return
        self._load_events_from_path(file_path)

    # [E] ========================= PLOTTING AND EVENT SYNC ============================
    def update_plot(self, track_limits: bool = True):
        if self.trace_data is None:
            return

        has_outer = (
            "Outer Diameter" in self.trace_data.columns
            and not self.trace_data["Outer Diameter"].isna().all()
        )

        inner_requested = (
            self.id_toggle_act.isChecked() if self.id_toggle_act is not None else True
        )
        outer_requested = (
            self.od_toggle_act.isChecked() if self.od_toggle_act is not None else False
        )
        inner_visible, outer_visible = self._ensure_valid_channel_selection(
            inner_requested,
            outer_requested,
            toggled="inner",
            outer_supported=has_outer,
        )

        self._apply_toggle_state(
            inner_visible, outer_visible, outer_supported=has_outer
        )
        self._update_trace_controls_state()
        self._rebuild_channel_layout(inner_visible, outer_visible, redraw=False)
        self._apply_pending_plot_layout()

        inner_track = self.plot_host.track("inner") if inner_visible else None
        outer_track = self.plot_host.track("outer") if outer_visible else None
        primary_track = inner_track or outer_track
        if primary_track is None:
            log.error("No channels available after layout rebuild")
            return

        self.ax = primary_track.ax
        self.ax2 = outer_track.ax if inner_track and outer_track else None
        self._bind_primary_axis_callbacks()
        self._init_hover_artists()

        self.event_text_objects = []
        self.event_metadata = []

        prev_window = self.plot_host.current_window()
        try:
            self.trace_model = TraceModel.from_dataframe(self.trace_data)
        except Exception:
            log.exception("Failed to build trace model from dataframe")
            return

        self.plot_host.set_trace_model(self.trace_model)
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(self.trace_model)
        if self.scope_dock:
            self.scope_dock.set_trace_model(self.trace_model)
        if track_limits or prev_window is None:
            target_window = self.trace_model.full_range
        else:
            target_window = prev_window
        self.plot_host.set_time_window(*target_window)
        if track_limits or prev_window is None:
            self.plot_host.autoscale_all()
        self._refresh_zoom_window()

        self.trace_line = None
        self.inner_line = None
        if inner_track is not None:
            self.trace_line = inner_track.primary_line
            self.inner_line = self.trace_line
            if self.trace_line is not None:
                self.trace_line.set_visible(inner_visible)

        if outer_track is not None:
            self.od_line = outer_track.primary_line
            self.outer_line = self.od_line
            if self.od_line is not None:
                self.od_line.set_visible(outer_visible)
            if self.trace_line is None:
                self.trace_line = self.od_line
        else:
            self.od_line = None
            self.outer_line = None

        for axis in self.plot_host.axes():
            if self.grid_visible:
                axis.grid(True, color=CURRENT_THEME["grid_color"])
            else:
                axis.grid(False)

        time_full = self.trace_model.time_full
        if time_full.size:
            self.xlim_full = (float(time_full[0]), float(time_full[-1]))
        inner_full = self.trace_model.inner_full
        if inner_full.size:
            inner_min = float(np.nanmin(inner_full))
            inner_max = float(np.nanmax(inner_full))
            self.ylim_full = (inner_min, inner_max)

        # Plot events if available
        if self.event_labels and self.event_times:
            self.plot_host.set_events(self.event_times, labels=self.event_labels)
            self.event_table_data = []
            offset_sec = 2
            nEv = len(self.event_times)
            diam_trace = self.trace_data["Inner Diameter"]
            time_trace = self.trace_data["Time (s)"]
            od_trace = (
                self.trace_data["Outer Diameter"]
                if "Outer Diameter" in self.trace_data.columns
                else None
            )
            annotation_entries: list[AnnotationSpec] = []
            self.event_text_objects = []

            for i in range(nEv):
                evt_time = self.event_times[i]
                idx_ev = int(np.argmin(np.abs(time_trace - evt_time)))

                if i < nEv - 1:
                    t_sample = self.event_times[i + 1] - offset_sec
                else:
                    t_sample = time_trace.iloc[-1] - offset_sec
                idx_pre = np.argmin(np.abs(time_trace - t_sample))
                diam_val = diam_trace.iloc[idx_pre]
                od_val = od_trace.iloc[idx_pre] if od_trace is not None else None
                if self.event_frames and i < len(self.event_frames):
                    frame_number = self.event_frames[i]
                else:
                    frame_number = idx_ev

                full_label = self.event_labels[i]

                tooltip = f"{full_label} · {evt_time:.2f}s"
                tooltip += f" · ID {diam_val:.2f}µm"
                if od_val is not None:
                    tooltip += f" · OD {od_val:.2f}µm"
                self.event_metadata.append(
                    {
                        "time": evt_time,
                        "label": full_label,
                        "tooltip": tooltip,
                    }
                )

                if od_val is not None:
                    self.event_table_data.append(
                        (
                            self.event_labels[i],
                            round(evt_time, 2),
                            round(diam_val, 2),
                            round(od_val, 2),
                            frame_number,
                        )
                    )
                else:
                    self.event_table_data.append(
                        (
                            self.event_labels[i],
                            round(evt_time, 2),
                            round(diam_val, 2),
                            frame_number,
                        )
                    )
                annotation_entries.append(
                    AnnotationSpec(
                        time_s=float(evt_time),
                        label=full_label,
                    )
                )
            self.populate_table()
            self.auto_export_table()
            self.event_annotations = annotation_entries
            self._annotation_lane_visible = True
            self.plot_host.set_annotation_entries(annotation_entries)
            self._refresh_event_annotation_artists()
        else:
            self.plot_host.set_events([], labels=[])
            self.event_table_data = []
            self.event_metadata = []
            self.event_text_objects = []
            self.event_annotations = []
            self._annotation_lane_visible = True
            self.plot_host.set_annotation_entries([])
            self._refresh_event_annotation_artists()

        self._update_trace_controls_state()
        self._refresh_plot_legend()
        self.canvas.setToolTip("")

        # Apply plot style (defaults on first load)
        self.apply_plot_style(self.get_current_plot_style(), persist=False)
        self.canvas.draw_idle()

    def _refresh_plot_legend(self):
        if not hasattr(self, "ax"):
            return

        legend = getattr(self, "plot_legend", None)
        if legend is not None:
            try:
                legend.remove()
            except Exception:
                pass
        self.plot_legend = None
        self.canvas.draw_idle()

    def apply_legend_settings(self, settings=None, *, mark_dirty: bool = False) -> None:
        """Merge ``settings`` into the current legend options and refresh."""

        merged = copy.deepcopy(DEFAULT_LEGEND_SETTINGS)

        if isinstance(self.legend_settings, dict):
            existing = copy.deepcopy(self.legend_settings)
            labels = existing.pop("labels", {}) or {}
            merged.update(existing)
            merged["labels"] = labels

        if isinstance(settings, dict):
            incoming = settings.copy()
            labels_incoming = incoming.pop("labels", {}) or {}
            merged.update(incoming)
            merged.setdefault("labels", {})
            merged["labels"].update(labels_incoming)

        self.legend_settings = merged
        self._refresh_plot_legend()
        if mark_dirty:
            self.mark_session_dirty()

    def open_legend_settings_dialog(self):
        """Display the legend settings dialog and apply changes on accept."""

        current_settings = copy.deepcopy(self.legend_settings)
        labels_defaults = {}
        if getattr(self, "trace_line", None) is not None:
            labels_defaults["inner"] = LEGEND_LABEL_DEFAULTS.get("inner", "Inner")
        if getattr(self, "od_line", None) is not None:
            labels_defaults["outer"] = LEGEND_LABEL_DEFAULTS.get("outer", "Outer")

        labels_current = {}
        stored_labels = (
            (current_settings.get("labels") or {}) if current_settings else {}
        )
        for key, default_value in labels_defaults.items():
            value = stored_labels.get(key, default_value)
            labels_current[key] = value

        dialog = LegendSettingsDialog(
            self,
            settings=current_settings,
            labels=labels_current,
            defaults=labels_defaults,
        )

        if dialog.exec_():
            self.apply_legend_settings(dialog.get_settings(), mark_dirty=True)

    def _apply_time_window(self, xlim):
        """Apply an x-axis window to all tracks."""

        if xlim is None:
            return
        try:
            x0, x1 = float(xlim[0]), float(xlim[1])
        except (TypeError, ValueError, IndexError):
            return
        if getattr(self, "_syncing_time_window", False):
            return
        self._syncing_time_window = True
        try:
            if hasattr(self, "plot_host"):
                self.plot_host.set_time_window(x0, x1)
            elif self.ax is not None:
                self.ax.set_xlim(x0, x1)
                self.canvas.draw_idle()
        finally:
            self._syncing_time_window = False

    def _sync_time_window_from_axes(self) -> None:
        """Pull the current Matplotlib limits back into PlotHost."""

        if getattr(self, "_syncing_time_window", False):
            return

        primary_ax = (
            self.plot_host.primary_axis() if hasattr(self, "plot_host") else None
        )
        if primary_ax is None and self.ax is not None:
            primary_ax = self.ax
        if primary_ax is None:
            return

        x0, x1 = primary_ax.get_xlim()
        if hasattr(self, "plot_host"):
            current = self.plot_host.current_window()
            if current is not None:
                tol = max(abs(x1 - x0), 1.0) * 1e-6
                if abs(current[0] - x0) <= tol and abs(current[1] - x1) <= tol:
                    return
        self._apply_time_window((x0, x1))

    def _unbind_primary_axis_callbacks(self) -> None:
        """Detach x-limit callbacks from the current primary axis."""

        if getattr(self, "_axis_source_axis", None) is None:
            self._axis_xlim_cid = None
            return
        if self._axis_xlim_cid is not None:
            try:
                self._axis_source_axis.callbacks.disconnect(self._axis_xlim_cid)
            except Exception:
                pass
        self._axis_source_axis = None
        self._axis_xlim_cid = None

    def _bind_primary_axis_callbacks(self) -> None:
        """Attach x-limit callbacks to the current primary axis."""

        self._unbind_primary_axis_callbacks()
        self._axis_source_axis = self.ax
        if self.ax is None:
            return
        try:
            self._axis_xlim_cid = self.ax.callbacks.connect(
                "xlim_changed", self._handle_axis_xlim_changed
            )
        except Exception:
            self._axis_source_axis = None
            self._axis_xlim_cid = None

    def _handle_axis_xlim_changed(self, ax) -> None:
        if getattr(self, "_syncing_time_window", False):
            return
        if ax is None:
            return
        xlim = ax.get_xlim()
        self._apply_time_window(xlim)
        self.update_scroll_slider()

    def scroll_plot(self):
        if self.trace_data is None:
            return

        primary_ax = (
            self.plot_host.primary_axis() if hasattr(self, "plot_host") else None
        )
        if primary_ax is None and self.ax is not None:
            primary_ax = self.ax
        if primary_ax is None:
            return

        if self.trace_model is not None and self.trace_model.time_full.size:
            time_full = self.trace_model.time_full
            full_t_min = float(time_full[0])
            full_t_max = float(time_full[-1])
        else:
            time_series = self.trace_data["Time (s)"]
            full_t_min = float(time_series.min())
            full_t_max = float(time_series.max())

        xlim = primary_ax.get_xlim()
        window_width = xlim[1] - xlim[0]

        max_scroll = self.scroll_slider.maximum()
        slider_pos = self.scroll_slider.value()
        fraction = slider_pos / max_scroll

        new_left = full_t_min + (full_t_max - full_t_min - window_width) * fraction
        new_right = new_left + window_width

        self._apply_time_window((new_left, new_right))

    # [F] ========================= EVENT TABLE MANAGEMENT ================================

    def handle_table_edit(self, row: int, new_val: float, old_val: float):
        if row >= len(self.event_table_data):
            return

        rounded_val = round(float(new_val), 2)
        row_data = list(self.event_table_data[row])
        time = row_data[1]

        if len(row_data) == 5:
            od_val = row_data[3]
            frame = row_data[4]
            self.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                od_val,
                frame,
            )
        else:
            frame = row_data[3] if len(row_data) > 3 else 0
            self.event_table_data[row] = (
                row_data[0],
                time,
                rounded_val,
                frame,
            )

        self.last_replaced_event = (row, old_val)

        cmd = ReplaceEventCommand(self, row, old_val, rounded_val)
        self.undo_stack.push(cmd)
        log.info("ID updated at %.2fs → %.2f µm", time, rounded_val)
        self.mark_session_dirty()
        self._sync_event_data_from_table()

    def table_row_clicked(self, row, col):
        self._focus_event_row(row, source="table")

    def _focus_event_row(self, row: int, *, source: str) -> None:
        if not self.event_table_data or not (0 <= row < len(self.event_table_data)):
            return

        try:
            event_time = float(self.event_table_data[row][1])
        except (TypeError, ValueError):
            event_time = None

        if source != "table":
            model = self.event_table.model()
            if model is not None:
                index = model.index(row, 0)
                self.event_table.selectRow(row)
                self.event_table.scrollTo(index)

        if event_time is not None:
            self._highlight_selected_event(event_time)
        else:
            self._clear_event_highlight()

        frame_idx = self._frame_index_from_event_row(row)
        if frame_idx is None and event_time is not None:
            frame_idx = self._frame_index_for_time(event_time)

        if frame_idx is not None and self.snapshot_frames:
            self.set_current_frame(frame_idx)
        elif event_time is not None:
            self.update_slider_marker()

    def _highlight_selected_event(self, event_time: float) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return

        self._time_cursor_time = float(event_time)
        plot_host.set_time_cursor(
            self._time_cursor_time,
            visible=self._time_cursor_visible,
        )
        plot_host.set_event_highlight_style(
            color=self._event_highlight_color,
            alpha=self._event_highlight_base_alpha,
        )
        plot_host.highlight_event(self._time_cursor_time, visible=True)

        self._event_highlight_timer.stop()
        self._event_highlight_elapsed_ms = 0
        if self._event_highlight_duration_ms > 0:
            interval = max(16, min(100, self._event_highlight_duration_ms // 30 or 16))
            self._event_highlight_timer.setInterval(interval)
            self._event_highlight_timer.start()

    def _clear_event_highlight(self) -> None:
        timer = getattr(self, "_event_highlight_timer", None)
        if timer is not None:
            timer.stop()
        self._event_highlight_elapsed_ms = 0
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha)

    def _on_event_highlight_tick(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            self._event_highlight_timer.stop()
            return
        if self._event_highlight_duration_ms <= 0:
            self._event_highlight_timer.stop()
            return
        interval = self._event_highlight_timer.interval()
        self._event_highlight_elapsed_ms += interval
        progress = self._event_highlight_elapsed_ms / float(
            self._event_highlight_duration_ms
        )
        if progress >= 1.0:
            self._event_highlight_timer.stop()
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha)
            return
        remaining = max(0.0, 1.0 - progress)
        plot_host.set_event_highlight_alpha(
            self._event_highlight_base_alpha * remaining
        )

    def _frame_index_from_event_row(self, row: int) -> Optional[int]:
        if not (0 <= row < len(self.event_table_data)):
            return None

        data = self.event_table_data[row]
        frame_val = None
        if len(data) >= 5:
            frame_val = data[4]
        elif len(data) >= 4:
            frame_val = data[3]

        try:
            frame_idx = int(frame_val)
        except (TypeError, ValueError):
            return None
        if frame_idx < 0:
            return None
        return frame_idx

    def _frame_index_for_time(self, time_value: float) -> Optional[int]:
        if not self.frame_times:
            return None
        try:
            times = np.asarray(self.frame_times, dtype=float)
        except (TypeError, ValueError):
            return None
        if times.size == 0:
            return None
        idx = int(np.argmin(np.abs(times - time_value)))
        return idx

    def _nearest_event_index(self, time_value: float) -> Optional[int]:
        if not self.event_times:
            return None
        try:
            times = np.asarray(self.event_times, dtype=float)
        except (TypeError, ValueError):
            return None
        if times.size == 0:
            return None
        idx = int(np.argmin(np.abs(times - time_value)))
        return idx

    def _handle_plot_double_click(self, event) -> bool:
        if not getattr(event, "dblclick", False):
            return False
        if event.button not in (1,):
            return False
        if not hasattr(self, "ax") or self.ax is None:
            return False

        axis_candidates = [
            ("x", self.ax.xaxis.label),
            ("y", self.ax.yaxis.label),
        ]
        if self.ax2 is not None:
            axis_candidates.append(("y_right", self.ax2.yaxis.label))

        for _axis_id, label in axis_candidates:
            if label and label.get_visible():
                try:
                    contains = label.contains(event)[0]
                except Exception:
                    contains = False
                if contains:
                    self.open_unified_plot_settings_dialog("axis")
                    return True

        tick_labels = list(self.ax.get_xticklabels()) + list(self.ax.get_yticklabels())
        if self.ax2 is not None:
            tick_labels.extend(self.ax2.get_yticklabels())
        for tick in tick_labels:
            if tick and tick.get_visible():
                try:
                    contains = tick.contains(event)[0]
                except Exception:
                    contains = False
                if contains:
                    self.open_unified_plot_settings_dialog("axis")
                    return True

        for marker, label in self.pinned_points:
            marker_contains = False
            label_contains = False
            try:
                marker_contains = marker.contains(event)[0]
            except Exception:
                pass
            try:
                label_contains = label.contains(event)[0]
            except Exception:
                pass
            if marker_contains or label_contains:
                self.open_unified_plot_settings_dialog("style")
                return True

        for txt, *_ in self.event_text_objects:
            if not txt or not txt.get_visible():
                continue
            try:
                contains = txt.contains(event)[0]
            except Exception:
                contains = False
            if contains:
                self.open_unified_plot_settings_dialog("style")
                return True

        legend = getattr(self, "plot_legend", None)
        if legend is not None:
            try:
                renderer = getattr(self.canvas, "renderer", None)
                if renderer is None:
                    self.canvas.draw()
                    renderer = getattr(self.canvas, "renderer", None)
                bbox = legend.get_window_extent(renderer)
                if bbox.contains(event.x, event.y):
                    self.open_legend_settings_dialog()
                    return True
            except Exception:
                pass

        trace_targets = []
        if getattr(self, "trace_line", None) is not None:
            trace_targets.append(("inner", self.trace_line))
        if getattr(self, "od_line", None) is not None:
            trace_targets.append(("outer", self.od_line))

        for name, line in trace_targets:
            try:
                contains = line.contains(event)[0]
            except Exception:
                contains = False
            if contains:
                self.open_unified_plot_settings_dialog("style")
                return True

        if event.inaxes in (self.ax, getattr(self, "ax2", None)):
            visible = True
            if isinstance(self.legend_settings, dict):
                visible = self.legend_settings.get("visible", True)
            if not visible:
                self.open_legend_settings_dialog()
            else:
                self.open_unified_plot_settings_dialog("style")
            return True

        self.open_unified_plot_settings_dialog("frame")
        return True

    # [F2] ===================== TABLE B MANAGEMENT =========================

    # [G] ========================= PIN INTERACTION LOGIC ================================
    def handle_click_on_plot(self, event):
        if self._handle_plot_double_click(event):
            return
        if getattr(self, "_plot_drag_in_progress", False):
            return

        valid_axes = [self.ax]
        if self.ax2:
            valid_axes.append(self.ax2)
        if event.inaxes not in valid_axes:
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
                tr_type = getattr(marker, "trace_type", "inner")
                ax_ref = self.ax2 if tr_type == "outer" and self.ax2 else self.ax
                pixel_x, pixel_y = ax_ref.transData.transform((data_x, data_y))
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
                        self.mark_session_dirty()
                        return
                    elif action == replace_action:
                        self.handle_event_replacement(data_x, data_y)
                        return
                    elif action == undo_action:
                        self.undo_last_replacement()
                        return
                    elif action == add_new_action:
                        self.prompt_add_event(data_x, data_y, tr_type)
                        return
            return

        # 🟢 Left-click = add pin (unless toolbar zoom/pan is active)
        if event.button == 1:
            if self.event_times and event.xdata is not None:
                x_low, x_high = self.ax.get_xlim()
                tolerance = max((x_high - x_low) * 0.004, 0.05)
                idx = self._nearest_event_index(event.xdata)
                if (
                    idx is not None
                    and idx < len(self.event_times)
                    and abs(event.xdata - self.event_times[idx]) <= tolerance
                ):
                    self._focus_event_row(idx, source="plot")
                    return

        if event.button == 1 and not self.toolbar.mode:
            if self.trace_data is None:
                return
            t_arr = self.trace_data["Time (s)"].values
            idx = np.argmin(np.abs(t_arr - x))

            contains_id = self.trace_line.contains(event)[0]
            contains_od = False
            if self.ax2 and self.od_line:
                contains_od = self.od_line.contains(event)[0]

            tr_type = "inner"
            ax_ref = self.ax
            y_arr = self.trace_data["Inner Diameter"].values

            if contains_od and (not contains_id or event.inaxes is self.ax2):
                tr_type = "outer"
                ax_ref = self.ax2
                y_arr = self.trace_data["Outer Diameter"].values

            y = y_arr[idx]

            marker = ax_ref.plot(x, y, "ro", markersize=6)[0]
            marker.trace_type = tr_type
            label = ax_ref.annotate(
                f"{x:.2f} s\n{y:.1f} µm",
                xy=(x, y),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                    ec=CURRENT_THEME["hover_label_border"],
                    lw=1,
                ),
                fontsize=8,
            )
            label.trace_type = tr_type

            self.pinned_points.append((marker, label))
            self.canvas.draw_idle()
            self.mark_session_dirty()

    def handle_event_replacement(self, x, y):
        if not self.event_labels or not self.event_times:
            log.info("No events available to replace.")
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
                has_od = (
                    self.trace_data is not None
                    and "Outer Diameter" in self.trace_data.columns
                )
                old_value = self.event_table_data[index][2]
                self.last_replaced_event = (index, old_value)
                if has_od:
                    frame_num = self.event_table_data[index][4]
                    self.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        self.event_table_data[index][3],
                        frame_num,
                    )
                else:
                    frame_num = self.event_table_data[index][3]
                    self.event_table_data[index] = (
                        event_label,
                        round(event_time, 2),
                        round(y, 2),
                        frame_num,
                    )
                self.event_table_controller.update_row(
                    index, self.event_table_data[index]
                )
                self.auto_export_table()
                self.mark_session_dirty()

    def prompt_add_event(self, x, y, trace_type="inner"):
        if not self.event_table_data:
            QMessageBox.warning(
                self, "No Events", "You must load events before adding new ones."
            )
            return

        # Build label options and insertion points
        insert_labels = [
            f"{label} at {t:.2f}s" for label, t, *_ in self.event_table_data
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

        has_od = (
            self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        )

        arr_t = self.trace_data["Time (s)"].values
        idx = int(np.argmin(np.abs(arr_t - x)))
        id_val = self.trace_data["Inner Diameter"].values[idx]
        od_val = self.trace_data["Outer Diameter"].values[idx] if has_od else None

        if trace_type == "outer" and has_od:
            od_val = y
        else:
            id_val = y

        if has_od:
            new_entry = (
                new_label.strip(),
                round(x, 2),
                round(id_val, 2),
                round(od_val, 2),
                frame_number,
            )
        else:
            new_entry = (
                new_label.strip(),
                round(x, 2),
                round(id_val, 2),
                frame_number,
            )

        # Insert into data
        if insert_idx == len(self.event_table_data):  # Add to end
            self.event_labels.append(new_label.strip())
            self.event_times.append(x)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
        else:
            self.event_labels.insert(insert_idx, new_label.strip())
            self.event_times.insert(insert_idx, x)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)

        self.populate_table()
        self.auto_export_table()
        self.update_plot()
        log.info("Inserted new event: %s", new_entry)
        self.mark_session_dirty()

    def manual_add_event(self):
        if not self.trace_data:
            QMessageBox.warning(self, "No Trace", "Load a trace before adding events.")
            return

        has_od = "Outer Diameter" in self.trace_data.columns
        insert_labels = [f"{lbl} at {t:.2f}s" for lbl, t, *_ in self.event_table_data]
        insert_labels.append("↘️ Add to end")
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

        label, l_ok = QInputDialog.getText(
            self, "New Event Label", "Enter label for the new event:"
        )
        if not l_ok or not label.strip():
            return

        t_val, t_ok = QInputDialog.getDouble(
            self, "Event Time", "Time (s):", 0.0, 0, 1e6, 2
        )
        if not t_ok:
            return

        id_val, id_ok = QInputDialog.getDouble(
            self, "Inner Diameter", "ID (µm):", 0.0, 0, 1e6, 2
        )
        if not id_ok:
            return

        insert_idx = insert_labels.index(selected)
        frame_number = int(t_val / self.recording_interval)
        if has_od:
            od_val, ok = QInputDialog.getDouble(
                self, "Outer Diameter", "OD (µm):", 0.0, 0, 1e6, 2
            )
            if not ok:
                return
            new_entry = (
                label.strip(),
                round(t_val, 2),
                round(id_val, 2),
                round(od_val, 2),
                frame_number,
            )
        else:
            new_entry = (label.strip(), round(t_val, 2), round(id_val, 2), frame_number)

        if insert_idx == len(self.event_table_data):
            self.event_labels.append(label.strip())
            self.event_times.append(t_val)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
        else:
            self.event_labels.insert(insert_idx, label.strip())
            self.event_times.insert(insert_idx, t_val)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)

        self.populate_table()
        self.update_plot()
        self.auto_export_table()
        log.info("Manually inserted event: %s", new_entry)
        self.mark_session_dirty()

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
    def update_hover_label(self, event):
        valid_axes = [ax for ax in (self.ax, self.ax2) if ax is not None]
        if (
            event.inaxes not in valid_axes
            or self.trace_data is None
            or event.xdata is None
        ):
            self._last_hover_time = None
            self.canvas.setToolTip("")
            self._hide_hover_feedback()
            return

        times = self.trace_data["Time (s)"].to_numpy()
        if times.size == 0:
            self._hide_hover_feedback()
            return

        xdata = float(event.xdata)
        idx = int(np.clip(np.searchsorted(times, xdata), 0, len(times) - 1))
        time_val = float(times[idx])
        self._last_hover_time = time_val

        tooltip_shown = False
        if getattr(self, "event_metadata", None):
            x_low, x_high = self.ax.get_xlim() if self.ax is not None else (0.0, 0.0)
            tolerance = max((x_high - x_low) * 0.004, 0.05)
            for meta in self.event_metadata:
                if abs(time_val - meta["time"]) <= tolerance:
                    self.canvas.setToolTip(meta["tooltip"])
                    tooltip_shown = True
                    break
        if not tooltip_shown:
            self.canvas.setToolTip("")

        column = "Inner Diameter"
        label = "ID"
        annot = self.hover_annotation_id
        if event.inaxes is self.ax2 and "Outer Diameter" in self.trace_data.columns:
            column = "Outer Diameter"
            label = "OD"
            annot = self.hover_annotation_od or self.hover_annotation_id

        values = self.trace_data.get(column)
        value = float(values.to_numpy()[idx]) if values is not None else float("nan")
        value_text = f"{value:.2f} µm" if np.isfinite(value) else "—"

        if annot is not None:
            y_coord = value if np.isfinite(value) else (event.ydata or 0.0)
            annot.xy = (time_val, y_coord)
            annot.set_text(f"t={time_val:.2f} s\n{label}={value_text}")
            annot.set_visible(True)

        other = (
            self.hover_annotation_od
            if annot is self.hover_annotation_id
            else self.hover_annotation_id
        )
        if other is not None and other.get_visible():
            other.set_visible(False)

        for line in getattr(self, "_hover_vlines", []) or []:
            if line is not None:
                line.set_xdata([time_val, time_val])
                line.set_visible(True)

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

        self._sync_time_window_from_axes()
        self.update_scroll_slider()

    def update_scroll_slider(self):
        if self.trace_data is None:
            return

        primary_ax = (
            self.plot_host.primary_axis() if hasattr(self, "plot_host") else None
        )
        if primary_ax is None and self.ax is not None:
            primary_ax = self.ax
        if primary_ax is None:
            return

        if self.trace_model is not None and self.trace_model.time_full.size:
            time_full = self.trace_model.time_full
            full_t_min = float(time_full[0])
            full_t_max = float(time_full[-1])
        else:
            time_series = self.trace_data["Time (s)"]
            full_t_min = float(time_series.min())
            full_t_max = float(time_series.max())

        xlim = primary_ax.get_xlim()
        self.window_width = xlim[1] - xlim[0]

        if self.window_width < (full_t_max - full_t_min):
            self.scroll_slider.show()
        else:
            self.scroll_slider.hide()

    def open_subplot_layout_dialog(self, fig=None):
        """Open dialog to adjust subplot paddings and spacing."""
        fig = fig or self.fig
        dialog = SubplotLayoutDialog(self, fig)
        if dialog.exec_():
            params = dialog.get_values()
            fig.subplots_adjust(**params)
            fig.canvas.draw_idle()

    def open_axis_settings_dialog(self):
        """Open axis settings dialog for the main plot."""
        self.open_axis_settings_dialog_for(self.ax, self.canvas, self.ax2)

    def open_axis_settings_dialog_for(self, ax, canvas, ax2=None):
        dialog = AxisSettingsDialog(self, ax, canvas, ax2)
        dialog.exec_()

    def open_unified_plot_settings_dialog(self, tab_name=None):
        """Open combined dialog for layout, axis and style."""
        dialog = UnifiedPlotSettingsDialog(
            self,
            self.ax,
            self.canvas,
            self.ax2,
            self.event_text_objects,
            self.pinned_points,
        )
        if tab_name:
            mapping = {
                "frame": 0,
                "layout": 1,
                "axis": 2,
                "style": 3,
            }
            idx = mapping.get(str(tab_name).lower(), 0)
            try:
                dialog.tabs.setCurrentIndex(idx)
            except Exception:
                pass
        dialog.exec_()

    # [J] ========================= PLOT STYLE EDITOR ================================
    def open_plot_style_editor(self, tab_name=None):
        from PyQt5.QtWidgets import QDialog

        def capture_current_style():
            return self._snapshot_style()

        prev_style = capture_current_style()
        dialog = PlotStyleEditor(self, initial=prev_style)
        self.plot_style_dialog = dialog

        if tab_name:
            try:
                dialog.select_tab(tab_name)
            except AttributeError:
                pass

        if dialog.exec_() == QDialog.Accepted:
            style = dialog.get_style()
            self.apply_plot_style(style, persist=True)
        else:
            self.apply_plot_style(prev_style, persist=False)

    def apply_plot_style(self, style, persist: bool = False):
        manager = self._ensure_style_manager()
        effective_style = manager.update(style or {})
        x_axis = self._x_axis_for_style()
        manager.apply(
            ax=self.ax,
            ax_secondary=self.ax2,
            x_axis=x_axis,
            event_text_objects=self.event_text_objects,
            pinned_points=self.pinned_points,
            main_line=self.ax.lines[0] if self.ax.lines else None,
            od_line=self.od_line,
        )

        self.canvas.draw_idle()
        if hasattr(self, "plot_style_dialog") and self.plot_style_dialog:
            try:
                self.plot_style_dialog.set_style(effective_style)
            except AttributeError:
                pass

        if self._style_holder is None:
            self._style_holder = _StyleHolder(effective_style.copy())
        else:
            self._style_holder.set_style(effective_style.copy())

        if persist and self.current_sample:
            if not isinstance(self.current_sample.ui_state, dict):
                self.current_sample.ui_state = {}
            self.current_sample.ui_state["style_settings"] = effective_style
            self.mark_session_dirty()
            self.auto_save_project()

    def _x_axis_for_style(self):
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            axis = plot_host.bottom_axis()
            if axis is not None:
                return axis
        return self.ax

    def _set_shared_xlabel(self, text: str):
        self._shared_xlabel = text
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            if self.ax is not None:
                self.ax.set_xlabel(text)
            return
        plot_host.set_shared_xlabel(text)

    def _ensure_style_manager(self) -> PlotStyleManager:
        if getattr(self, "_style_manager", None) is None:
            base_style = (
                self._style_holder.get_style()
                if self._style_holder is not None
                else DEFAULT_STYLE.copy()
            )
            self._style_manager = PlotStyleManager(base_style)
        return self._style_manager

    def _snapshot_style(
        self,
        ax=None,
        ax2=None,
        event_text_objects=None,
        pinned_points=None,
        od_line=None,
    ):
        ax = ax or self.ax
        ax2 = self.ax2 if ax2 is None else ax2
        event_text_objects = (
            self.event_text_objects
            if event_text_objects is None
            else event_text_objects
        )
        pinned_points = self.pinned_points if pinned_points is None else pinned_points
        od_line = od_line if od_line is not None else getattr(self, "od_line", None)

        style = DEFAULT_STYLE.copy()
        if ax is None:
            return style
        x_axis = self._x_axis_for_style() or ax

        x_label = x_axis.xaxis.label
        y_label = ax.yaxis.label
        style["axis_font_size"] = x_label.get_fontsize()
        style["axis_font_family"] = x_label.get_fontname()
        style["axis_bold"] = str(x_label.get_fontweight()).lower() == "bold"
        style["axis_italic"] = x_label.get_fontstyle() == "italic"

        style["axis_color"] = x_label.get_color()
        style["x_axis_color"] = x_label.get_color()
        style["y_axis_color"] = y_label.get_color()

        x_tick_labels = x_axis.get_xticklabels()
        y_tick_labels = ax.get_yticklabels()
        tick_font_size = (
            x_tick_labels[0].get_fontsize()
            if x_tick_labels
            else (
                y_tick_labels[0].get_fontsize()
                if y_tick_labels
                else style["tick_font_size"]
            )
        )
        style["tick_font_size"] = tick_font_size

        x_tick_color = (
            x_tick_labels[0].get_color() if x_tick_labels else style["x_tick_color"]
        )
        y_tick_color = (
            y_tick_labels[0].get_color() if y_tick_labels else style["y_tick_color"]
        )
        style["tick_color"] = x_tick_color
        style["x_tick_color"] = x_tick_color
        style["y_tick_color"] = y_tick_color

        try:
            major_ticks = x_axis.xaxis.get_major_ticks()
            if major_ticks:
                style["tick_length"] = float(major_ticks[0].tick1line.get_markersize())
                style["tick_width"] = float(major_ticks[0].tick1line.get_linewidth())
        except Exception:
            pass

        if ax.lines:
            style["line_width"] = ax.lines[0].get_linewidth()
            style["line_color"] = ax.lines[0].get_color()
            style["line_style"] = ax.lines[0].get_linestyle()

        if event_text_objects:
            txt = event_text_objects[0][0]
            style["event_font_size"] = txt.get_fontsize()
            style["event_font_family"] = txt.get_fontname()
            style["event_bold"] = str(txt.get_fontweight()).lower() == "bold"
            style["event_italic"] = txt.get_fontstyle() == "italic"
            style["event_color"] = txt.get_color()

        if pinned_points:
            marker, label = pinned_points[0]
            style["pin_size"] = marker.get_markersize()
            style["pin_font_size"] = label.get_fontsize()
            style["pin_font_family"] = label.get_fontname()
            style["pin_bold"] = str(label.get_fontweight()).lower() == "bold"
            style["pin_italic"] = label.get_fontstyle() == "italic"
            style["pin_color"] = label.get_color()

        if od_line is not None:
            style["outer_line_width"] = od_line.get_linewidth()
            style["outer_line_color"] = od_line.get_color()
            style["outer_line_style"] = od_line.get_linestyle()
        elif ax2 and ax2.lines:
            style["outer_line_width"] = ax2.lines[0].get_linewidth()
            style["outer_line_color"] = ax2.lines[0].get_color()
            style["outer_line_style"] = ax2.lines[0].get_linestyle()

        if ax2:
            y2_label = ax2.yaxis.label
            style["right_axis_color"] = y2_label.get_color()
            y2_ticks = ax2.get_yticklabels()
            if y2_ticks:
                style["right_tick_color"] = y2_ticks[0].get_color()

        style["event_highlight_color"] = getattr(
            self,
            "_event_highlight_color",
            DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF"),
        )
        style["event_highlight_alpha"] = getattr(
            self,
            "_event_highlight_base_alpha",
            DEFAULT_STYLE.get("event_highlight_alpha", 0.95),
        )
        style["event_highlight_duration_ms"] = getattr(
            self,
            "_event_highlight_duration_ms",
            DEFAULT_STYLE.get("event_highlight_duration_ms", 2000),
        )

        return style

    def open_plot_style_editor_for(
        self, ax, canvas, event_text_objects=None, pinned_points=None
    ):
        def capture_current_style():
            secondary = self.ax2 if ax is self.ax else None
            od_line = self.od_line if ax is self.ax else None
            return self._snapshot_style(
                ax=ax,
                ax2=secondary,
                event_text_objects=event_text_objects,
                pinned_points=pinned_points,
                od_line=od_line,
            )

        prev_style = capture_current_style()
        dialog = PlotStyleEditor(self, initial=prev_style)

        def apply_local_style(style=None):
            style = style or dialog.get_style()
            merged = {**DEFAULT_STYLE, **style}

            axis_font_size = merged["axis_font_size"]
            axis_font_family = merged["axis_font_family"]
            axis_weight = "bold" if merged["axis_bold"] else "normal"
            axis_style = "italic" if merged["axis_italic"] else "normal"

            x_axis_color = merged.get("x_axis_color", merged.get("axis_color", "black"))
            y_axis_color = merged.get("y_axis_color", merged.get("axis_color", "black"))
            x_tick_color = merged.get("x_tick_color", merged.get("tick_color", "black"))
            y_tick_color = merged.get("y_tick_color", merged.get("tick_color", "black"))
            tick_length = merged.get("tick_length", DEFAULT_STYLE["tick_length"])
            tick_width = merged.get("tick_width", DEFAULT_STYLE["tick_width"])

            for label, color in (
                (ax.xaxis.label, x_axis_color),
                (ax.yaxis.label, y_axis_color),
            ):
                label.set_fontsize(axis_font_size)
                label.set_fontname(axis_font_family)
                label.set_fontstyle(axis_style)
                label.set_fontweight(axis_weight)
                label.set_color(color)

            for spine_name, color in (
                ("bottom", x_axis_color),
                ("top", x_axis_color),
                ("left", y_axis_color),
                ("right", y_axis_color),
            ):
                if spine_name in ax.spines:
                    ax.spines[spine_name].set_color(color)

            ax.tick_params(
                axis="x",
                labelsize=merged["tick_font_size"],
                colors=x_tick_color,
                length=tick_length,
                width=tick_width,
            )
            ax.tick_params(
                axis="y",
                labelsize=merged["tick_font_size"],
                colors=y_tick_color,
                length=tick_length,
                width=tick_width,
            )

            if event_text_objects:
                for txt, _, _ in event_text_objects:
                    txt.set_fontsize(merged["event_font_size"])
                    txt.set_fontname(merged["event_font_family"])
                    txt.set_fontstyle("italic" if merged["event_italic"] else "normal")
                    txt.set_fontweight("bold" if merged["event_bold"] else "normal")
                    txt.set_color(merged.get("event_color", "black"))

            if pinned_points:
                for marker, label in pinned_points:
                    marker.set_markersize(merged["pin_size"])
                    label.set_fontsize(merged["pin_font_size"])
                    label.set_fontname(merged["pin_font_family"])
                    label.set_fontstyle("italic" if merged["pin_italic"] else "normal")
                    label.set_fontweight("bold" if merged["pin_bold"] else "normal")
                    label.set_color(merged.get("pin_color", "black"))
                    marker.set_color(merged.get("pin_color", "red"))

            if ax.lines:
                ax.lines[0].set_linewidth(merged["line_width"])
                ax.lines[0].set_color(merged.get("line_color", "black"))
                ax.lines[0].set_linestyle(merged.get("line_style", "solid"))

            if self.od_line and ax is self.ax:
                self.od_line.set_linewidth(merged.get("outer_line_width", 2))
                self.od_line.set_color(merged.get("outer_line_color", "tab:orange"))
                self.od_line.set_linestyle(merged.get("outer_line_style", "solid"))

            self._event_highlight_color = merged.get(
                "event_highlight_color",
                self._event_highlight_color,
            )
            self._event_highlight_base_alpha = max(
                0.0,
                min(
                    float(
                        merged.get(
                            "event_highlight_alpha", self._event_highlight_base_alpha
                        )
                    ),
                    1.0,
                ),
            )
            self._event_highlight_duration_ms = max(
                0,
                int(
                    merged.get(
                        "event_highlight_duration_ms", self._event_highlight_duration_ms
                    )
                ),
            )
            self._event_highlight_elapsed_ms = 0
            if hasattr(self, "plot_host") and self.plot_host is not None:
                self.plot_host.set_event_highlight_style(
                    color=self._event_highlight_color,
                    alpha=self._event_highlight_base_alpha,
                )

            canvas.draw_idle()

        # Inject the apply method into the dialog
        dialog.apply_callback = apply_local_style

        if dialog.exec_():
            dialog.apply_callback()
        else:
            apply_local_style(prev_style)

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
        self.frames_metadata = []
        self.frame_times = []
        self.frame_trace_indices = []
        self.current_frame = 0
        self.event_labels = []
        self.event_times = []
        self.event_text_objects = []
        self.event_table_data = []
        self.event_metadata = []
        self.pinned_points = []
        self._clear_slider_markers()
        self._clear_event_highlight()
        self.trace_line = None
        self.inner_line = None
        self.od_line = None
        self.outer_line = None
        if hasattr(self, "plot_host"):
            self.plot_host.clear()
            initial_specs = [
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            ]
            self.plot_host.ensure_channels(initial_specs)
            inner_track = self.plot_host.track("inner")
            self.ax = inner_track.ax if inner_track else None
            self._bind_primary_axis_callbacks()
        self.ax2 = None
        self.hover_annotation_id = None
        self.hover_annotation_od = None
        self.canvas.draw()
        self.event_table_controller.clear()
        self.snapshot_label.clear()
        self.sampling_rate_hz = None
        self._set_status_source("No trace loaded", "")
        self._reset_session_dirty()
        self.toggle_snapshot_viewer(False)
        self.slider.hide()
        self.snapshot_controls.hide()
        self.prev_frame_btn.setEnabled(False)
        self.next_frame_btn.setEnabled(False)
        self.play_pause_btn.setEnabled(False)
        self.snapshot_speed_label.setEnabled(False)
        self.snapshot_speed_combo.setEnabled(False)
        self._reset_snapshot_speed()
        self._set_playback_state(False)
        self.snapshot_time_label.setText("Frame 0 / 0")
        self.snapshot_label.hide()
        self.set_snapshot_metadata_visible(False)
        self.metadata_details_label.setText("No metadata available.")
        self._update_metadata_button_state()
        self._update_excel_controls()
        log.info("Cleared session.")
        self.scroll_slider.setValue(0)
        self.scroll_slider.hide()
        self.show_home_screen()
        self.legend_settings = copy.deepcopy(DEFAULT_LEGEND_SETTINGS)
        if getattr(self, "plot_legend", None):
            try:
                self.plot_legend.remove()
            except Exception:
                pass
            self.plot_legend = None
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(None)
        if self.scope_dock:
            self.scope_dock.set_trace_model(None)
        self._apply_toggle_state(True, False, outer_supported=False)
        self._update_trace_controls_state()

    def _clear_canvas_and_table(self):
        """Wipe the current plot and event table."""
        self._clear_slider_markers()
        self.trace_data = None
        if hasattr(self, "plot_host"):
            self.plot_host.clear()
            initial_specs = [
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            ]
            self.plot_host.ensure_channels(initial_specs)
            inner_track = self.plot_host.track("inner")
            self.ax = inner_track.ax if inner_track else None
            self._bind_primary_axis_callbacks()
        self.ax2 = None
        self.outer_line = None
        self.trace_model = None
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(None)
        if self.scope_dock:
            self.scope_dock.set_trace_model(None)
        self.canvas.draw()
        if hasattr(self, "event_table_controller"):
            self.event_table_controller.clear()
        if hasattr(self, "load_events_action") and self.load_events_action is not None:
            self.load_events_action.setEnabled(False)
        self._event_lines_visible = True
        self._event_label_mode = "none"
        self._sync_event_controls()
        self._apply_toggle_state(True, False, outer_supported=False)
        self._update_trace_controls_state()

    def show_event_table_context_menu(self, position):
        index = self.event_table.indexAt(position)
        row = index.row() if index.isValid() else len(self.event_table_data)
        menu = QMenu()

        # Group 1: Edit & Delete
        if index.isValid():
            edit_action = menu.addAction("✏️ Edit ID (µm)…")
            delete_action = menu.addAction("🗑️ Delete Event")
        menu.addSeparator()

        # Group 2: Plot Navigation
        if index.isValid():
            jump_action = menu.addAction("🔍 Jump to Event on Plot")
            pin_action = menu.addAction("📌 Pin to Plot")
        menu.addSeparator()

        # Group 3: Pin Utilities
        if index.isValid():
            replace_with_pin_action = menu.addAction("🔄 Replace ID with Pinned Value")
        clear_pins_action = menu.addAction("❌ Clear All Pins")
        menu.addSeparator()

        add_event_action = menu.addAction("➕ Add Event…")

        # Show menu
        action = menu.exec_(self.event_table.viewport().mapToGlobal(position))

        # Group 1 actions
        if index.isValid() and action == edit_action:
            if row >= len(self.event_table_data):
                return
            old_val = self.event_table_data[row][2]
            new_val, ok = QInputDialog.getDouble(
                self,
                "Edit ID",
                "Enter new ID (µm):",
                float(old_val) if old_val is not None else 0.0,
                0,
                10000,
                2,
            )
            if ok:
                has_od = (
                    self.trace_data is not None
                    and "Outer Diameter" in self.trace_data.columns
                )
                rounded = round(new_val, 2)
                if has_od:
                    lbl, t, _, od_val, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, od_val, frame_val)
                else:
                    lbl, t, _, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, frame_val)
                self.event_table_controller.update_row(row, self.event_table_data[row])
                self.auto_export_table()

        elif index.isValid() and action == delete_action:
            confirm = QMessageBox.question(
                self,
                "Delete Event",
                f"Delete event: {self.event_table_data[row][0]}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                del self.event_labels[row]
                del self.event_times[row]
                if len(self.event_frames) > row:
                    del self.event_frames[row]
                self.event_table_data.pop(row)
                self.event_table_controller.remove_row(row)
                self.update_plot()
                self._update_excel_controls()

        # Group 2 actions
        elif index.isValid() and action == jump_action:
            self._focus_event_row(row, source="context")

        elif index.isValid() and action == pin_action:
            t = self.event_table_data[row][1]
            id_val = self.event_table_data[row][2]
            marker = self.ax.plot(t, id_val, "ro", markersize=6)[0]
            label = self.ax.annotate(
                f"{t:.2f} s\n{round(id_val,1)} µm",
                xy=(t, id_val),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc=css_rgba_to_mpl(CURRENT_THEME["hover_label_bg"]),
                    ec=CURRENT_THEME["hover_label_border"],
                    lw=1,
                ),
                fontsize=8,
            )
            self.pinned_points.append((marker, label))
            self.canvas.draw_idle()

        # Group 3 actions
        elif index.isValid() and action == replace_with_pin_action:
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
                has_od = (
                    self.trace_data is not None
                    and "Outer Diameter" in self.trace_data.columns
                )
                if has_od:
                    self.event_table_data[row] = (
                        self.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        self.event_table_data[row][3],
                        self.event_table_data[row][4],
                    )
                else:
                    self.event_table_data[row] = (
                        self.event_table_data[row][0],
                        t_event,
                        round(pin_id, 2),
                        self.event_table_data[row][3],
                    )
                self.event_table_controller.update_row(row, self.event_table_data[row])
                self.auto_export_table()
                log.info(
                    "Replaced ID at %.2fs with pinned value %.2f µm.",
                    t_event,
                    pin_id,
                )
                self.mark_session_dirty()

        elif action == clear_pins_action:
            if not self.pinned_points:
                QMessageBox.information(self, "No Pins", "There are no pins to clear.")
                return
            for marker, label in self.pinned_points:
                marker.remove()
                label.remove()
            self.pinned_points.clear()
            self.canvas.draw_idle()
            log.info("Cleared all pins.")
            self.mark_session_dirty()

        elif action == add_event_action:
            self.manual_add_event()

    def save_recent_files(self):
        self.settings.setValue("recentFiles", self.recent_files)

    def remove_recent_file(self, path: str) -> None:
        if path not in self.recent_files:
            return
        self.recent_files = [p for p in self.recent_files if p != path]
        self.save_recent_files()
        self.build_recent_files_menu()
        self._refresh_home_recent()

    def clear_recent_files(self):
        self.recent_files = []
        self.save_recent_files()
        self.build_recent_files_menu()
        self._refresh_home_recent()

    def get_current_plot_style(self):
        manager = self._ensure_style_manager()
        if hasattr(self, "plot_style_dialog") and self.plot_style_dialog:
            try:
                style = self.plot_style_dialog.get_style()
                if style:
                    manager.update(style)
                return manager.style()
            except AttributeError:
                pass

        if self._style_holder is not None:
            return self._style_holder.get_style()

        return manager.style()

    def sample_inner_diameter(self, time_value: float) -> Optional[float]:
        if self.trace_data is None:
            return None
        if "Time (s)" not in self.trace_data.columns:
            return None
        if "Inner Diameter" not in self.trace_data.columns:
            return None

        times = self.trace_data["Time (s)"].to_numpy()
        values = self.trace_data["Inner Diameter"].to_numpy()
        if times.size == 0:
            return None
        try:
            return float(np.interp(time_value, times, values))
        except Exception:
            return None

    def compute_interval_metrics(self) -> Optional[dict]:
        if self.trace_data is None:
            return None
        if "Time (s)" not in self.trace_data.columns:
            return None
        if "Inner Diameter" not in self.trace_data.columns:
            return None

        inner_pins = [
            marker.get_xdata()[0]
            for marker, _ in self.pinned_points
            if getattr(marker, "trace_type", "inner") == "inner"
        ]
        if len(inner_pins) < 2:
            return None

        start, end = sorted(inner_pins)[:2]
        if not np.isfinite(start) or not np.isfinite(end) or start == end:
            return None

        data = self.trace_data
        mask = (data["Time (s)"] >= start) & (data["Time (s)"] <= end)
        if mask.sum() < 2:
            return None

        times = data.loc[mask, "Time (s)"].to_numpy()
        values = data.loc[mask, "Inner Diameter"].to_numpy()
        if times.size < 2 or values.size < 2:
            return None

        baseline = float(values[0])
        peak = float(values.max())
        auc = float(np.trapz(values, times))

        return {
            "start": float(start),
            "end": float(end),
            "baseline": baseline,
            "peak": peak,
            "auc": auc,
        }

    def rebuild_default_main_layout(self):
        for widget in (
            self.canvas,
            self.scroll_slider,
            self.snapshot_label,
            self.slider,
            self.event_table,
        ):
            widget.setParent(None)

        plot_panel = QFrame()
        plot_panel.setObjectName("PlotPanel")
        plot_panel_layout = QVBoxLayout(plot_panel)
        plot_panel_layout.setContentsMargins(0, 0, 0, 0)
        plot_panel_layout.setSpacing(10)

        plot_container = QFrame()
        plot_container.setObjectName("PlotContainer")
        plot_container_layout = QVBoxLayout(plot_container)
        plot_container_layout.setContentsMargins(14, 14, 14, 14)
        plot_container_layout.setSpacing(6)
        plot_container_layout.addWidget(self.canvas)
        plot_container_layout.addWidget(self.scroll_slider)
        plot_panel_layout.addWidget(plot_container)

        side_panel = QFrame()
        side_panel.setObjectName("SidePanel")
        side_panel.setMinimumWidth(480)
        side_panel.setMaximumWidth(640)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(10)

        self.snapshot_card = QFrame()
        self.snapshot_card.setObjectName("SnapshotCard")
        snapshot_box = QVBoxLayout(self.snapshot_card)
        snapshot_box.setContentsMargins(12, 12, 12, 12)
        snapshot_box.setSpacing(12)
        snapshot_box.addWidget(self.snapshot_label, 0, Qt.AlignCenter)
        snapshot_box.addWidget(self.slider)
        snapshot_box.addWidget(self.snapshot_controls)
        snapshot_box.addWidget(self.metadata_panel)
        side_layout.addWidget(self.snapshot_card, 0, Qt.AlignTop)
        side_layout.addSpacing(12)
        table_card = QFrame()
        table_card.setObjectName("TableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.event_table, 1)
        side_layout.addWidget(table_card, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("DataSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(plot_panel)
        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)

        return splitter

    # [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
    def auto_export_table(self):
        if not self.trace_file_path:
            log.warning("No trace path set. Cannot export event table.")
            return

        try:
            trace_path = os.path.abspath(self.trace_file_path)
            if os.path.isfile(trace_path):
                output_dir = os.path.dirname(trace_path)
            else:
                output_dir = trace_path
            csv_path = os.path.join(output_dir, "eventDiameters_output.csv")
            has_od = (
                "Outer Diameter" in self.trace_data.columns
                if self.trace_data is not None
                else False
            )
            columns = ["Event", "Time (s)", "ID (µm)"]
            if has_od:
                columns.append("OD (µm)")
            columns.append("Frame")
            df = pd.DataFrame(self.event_table_data, columns=columns)
            df.to_csv(csv_path, index=False)
            log.info("Event table auto-exported to:\n%s", csv_path)
        except Exception as e:
            log.error("Failed to auto-export event table:\n%s", e)

        if self.excel_auto_path and self.excel_auto_column:
            update_excel_file(
                self.excel_auto_path,
                self.event_table_data,
                start_row=3,
                column_letter=self.excel_auto_column,
            )

    # ---------- UI State Persistence ----------
    def gather_ui_state(self):
        state = {
            "geometry": self.saveGeometry().data().hex(),
            "window_state": self.saveState().data().hex(),
            "axis_xlim": list(self.ax.get_xlim()),
            "axis_ylim": list(self.ax.get_ylim()),
        }
        layout_state = self._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        if self.current_experiment:
            state["last_experiment"] = self.current_experiment.name
        if self.current_sample:
            state["last_sample"] = self.current_sample.name
        if hasattr(self, "data_splitter") and self.data_splitter is not None:
            try:
                state["splitter_state"] = bytes(self.data_splitter.saveState()).hex()
            except Exception:
                pass
        return state

    def gather_sample_state(self):
        # preserve any previously saved style_settings
        prev = {}
        if self.current_sample and isinstance(self.current_sample.ui_state, dict):
            prev = self.current_sample.ui_state.get("style_settings", {}) or {}
        x_axis = self._x_axis_for_style()
        state = {
            "axis_xlim": list(self.ax.get_xlim()),
            "axis_ylim": list(self.ax.get_ylim()),
            "table_fontsize": self.event_table.font().pointSize(),
            "event_table_data": list(self.event_table_data),
            "pins": [
                (p.get_xdata()[0], p.get_ydata()[0]) for p, _ in self.pinned_points
            ],
            "plot_style": self.get_current_plot_style(),
            "grid_visible": self.grid_visible,
            "axis_settings": {
                "x": {"label": x_axis.get_xlabel() if x_axis else ""},
                "y": {"label": self.ax.get_ylabel()},
            },
        }
        if isinstance(self.legend_settings, dict):
            state["legend_settings"] = copy.deepcopy(self.legend_settings)
        # Always record whatever is in ui_state["style_settings"], even if empty
        state["style_settings"] = prev
        if self.ax2 is not None:
            state["axis_outer_ylim"] = list(self.ax2.get_ylim())
            state["axis_settings"]["y_outer"] = {"label": self.ax2.get_ylabel()}
        layout_state = self._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        return state

    def apply_ui_state(self, state):
        if not state:
            return
        geom = state.get("geometry")
        if geom:
            self.restoreGeometry(bytes.fromhex(geom))
        wstate = state.get("window_state")
        if wstate:
            self.restoreState(bytes.fromhex(wstate))
        if "axis_xlim" in state:
            self._apply_time_window(state["axis_xlim"])
        if "axis_ylim" in state:
            self.ax.set_ylim(state["axis_ylim"])
        splitter_state = state.get("splitter_state")
        if (
            splitter_state
            and hasattr(self, "data_splitter")
            and self.data_splitter is not None
        ):
            try:
                self.data_splitter.restoreState(bytes.fromhex(splitter_state))
            except Exception:
                pass
        plot_layout = state.get("plot_layout")
        if plot_layout:
            self._pending_plot_layout = plot_layout
        self.canvas.draw_idle()

    def apply_sample_state(self, state):
        if not state:
            return
        layout = state.get("plot_layout")
        if layout:
            self._pending_plot_layout = layout
        if "event_table_data" in state:
            self.event_table_data = state["event_table_data"]
            self.populate_table()
        if "axis_xlim" in state:
            self._apply_time_window(state["axis_xlim"])
        if "axis_ylim" in state:
            self.ax.set_ylim(state["axis_ylim"])
        if "axis_outer_ylim" in state and self.ax2 is not None:
            self.ax2.set_ylim(state["axis_outer_ylim"])
        if "table_fontsize" in state:
            font = self.event_table.font()
            font.setPointSize(state["table_fontsize"])
            self.event_table.setFont(font)
        if "pins" in state:
            for marker, label in self.pinned_points:
                marker.remove()
                label.remove()
            self.pinned_points.clear()
            for x, y in state.get("pins", []):
                marker = self.ax.plot(x, y, "ro", markersize=6)[0]
                label = self.ax.annotate(
                    f"{x:.2f} s\n{y:.1f} µm",
                    xy=(x, y),
                    xytext=(6, 6),
                    textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="black", lw=1),
                    fontsize=8,
                )
                self.pinned_points.append((marker, label))

        if "grid_visible" in state:
            self.grid_visible = state["grid_visible"]
            self.ax.grid(self.grid_visible)
            if self.grid_visible:
                self.ax.grid(color=CURRENT_THEME["grid_color"])

        legend_settings = state.get("legend_settings")
        if isinstance(legend_settings, dict):
            self.apply_legend_settings(legend_settings, mark_dirty=False)

        # ─── restore style settings ─────────────────────────────────────
        style = state.get("style_settings") or state.get("plot_style")
        if style:
            self.apply_plot_style(style, persist=False)
            if (
                state.get("plot_style")
                and hasattr(self, "plot_style_dialog")
                and self.plot_style_dialog
            ):
                try:
                    self.plot_style_dialog.set_style(state["plot_style"])
                except AttributeError:
                    pass
        if "axis_settings" in state:
            x_label = state["axis_settings"].get("x", {}).get("label")
            y_label = state["axis_settings"].get("y", {}).get("label")
            y_outer_label = state["axis_settings"].get("y_outer", {}).get("label")
            if x_label:
                self._set_shared_xlabel(x_label)
            if y_label:
                self.ax.set_ylabel(y_label)
            if y_outer_label and self.ax2 is not None:
                self.ax2.set_ylabel(y_outer_label)
        self.canvas.draw_idle()

    def restore_last_selection(self) -> bool:
        if not self.project_tree or not self.current_project:
            return False

        state = getattr(self.current_project, "ui_state", {}) or {}
        last_exp = state.get("last_experiment")
        if not last_exp:
            return False
        last_sample = state.get("last_sample")

        root = self.project_tree.topLevelItem(0)
        if root is None:
            return False

        exp_item = None
        sample_item = None

        for i in range(root.childCount()):
            child = root.child(i)
            obj = child.data(0, Qt.UserRole)
            if isinstance(obj, Experiment) and obj.name == last_exp:
                exp_item = child
                if last_sample:
                    for j in range(child.childCount()):
                        sample_child = child.child(j)
                        sample_obj = sample_child.data(0, Qt.UserRole)
                        if (
                            isinstance(sample_obj, SampleN)
                            and sample_obj.name == last_sample
                        ):
                            sample_item = sample_child
                            break
                break

        if sample_item is not None:
            self.project_tree.setCurrentItem(sample_item)
            self.on_tree_item_clicked(sample_item, 0)
            return True

        if exp_item is not None:
            self.project_tree.setCurrentItem(exp_item)
            self.on_tree_item_clicked(exp_item, 0)
            return True

        return False

    def closeEvent(self, event):
        if self.current_project and self.current_project.path:
            try:
                self.current_project.ui_state = self.gather_ui_state()
                if self.current_sample:
                    state = self.gather_sample_state()
                    self.current_sample.ui_state = state
                    self.project_state[id(self.current_sample)] = state
                save_project_file(self.current_project)
            except Exception as e:
                log.error("Failed to auto-save project:\n%s", e)
        self._replace_current_project(None)
        super().closeEvent(event)


# Bind mixin functions
VasoAnalyzerApp.auto_export_editable_plot = auto_export_editable_plot
VasoAnalyzerApp.export_high_res_plot = export_high_res_plot
VasoAnalyzerApp.toggle_grid = toggle_grid
VasoAnalyzerApp.save_data_as_n = save_data_as_n
VasoAnalyzerApp.show_save_menu = show_save_menu
VasoAnalyzerApp.open_excel_mapping_dialog = open_excel_mapping_dialog
