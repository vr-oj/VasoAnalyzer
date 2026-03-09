# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# Snapshot viewer notes:
# - Class: VasoAnalyzerApp hosts the TIFF viewer v2 widget and sync wiring.
# - Created in: initUI() → vasoanalyzer.ui.shell.init_ui.init_ui builds snapshot_widget and wires v2 controls.
# - Data source: Sample.snapshots numpy stack or snapshot asset/path resolved via _ensure_sample_snapshots_loaded/_SnapshotLoadJob (npz/npy or TIFF via vasoanalyzer.io.tiffs.load_tiff); manual _load_snapshot_from_path also uses load_tiff then np.stack.
# - Sync: trace["Time (s)"] is canonical. TIFF frames are aligned via trace["TiffPage"] → frame_trace_time, and jump_to_time(t) drives the v2 viewer.

# mypy: ignore-errors

# [A] ========================= IMPORTS AND GLOBAL CONFIG ============================
import contextlib
import copy
import csv
import html
import io
import json
import json as _json
import logging
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import webbrowser
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import tifffile
from PyQt5.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QRunnable,
    QSettings,
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QDesktopWidget,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QTreeWidgetItem,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

import vasoanalyzer.core.project as project_module
from utils.config import APP_VERSION
from vasoanalyzer.core.audit import serialize_edit_log
from vasoanalyzer.core.change_log_manager import ChangeLogManager
from vasoanalyzer.core.project import (
    Attachment,
    Experiment,
    Project,
    ProjectUpgradeRequired,
    SampleN,
    close_project_ctx,
    load_project,
    open_project_ctx,
    save_project,
)
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.core.timebase import derive_tiff_page_times, page_for_time
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.export.clipboard import render_tsv, write_csv
from vasoanalyzer.export.generator import build_export_table, events_from_rows
from vasoanalyzer.export.profiles import (
    EVENT_TABLE_ROW_PER_EVENT_ID,
    EVENT_VALUES_SINGLE_COLUMN_ID,
    PRESSURE_CURVE_STANDARD_ID,
    get_profile,
)
from vasoanalyzer.io.events import find_matching_event_file, load_events
from vasoanalyzer.io.importers import (
    event_rows_to_legacy_payload,
    guess_table_csv_for_trace as guess_vasotracker_table_csv_for_trace,
    import_vasotracker_v1,
    import_vasotracker_v2,
    trace_frames_to_dataframe,
)
from vasoanalyzer.io.tiffs import load_tiff, resolve_frame_times
from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.services.cache_service import DataCache, cache_dir_for_project
from vasoanalyzer.services.project_service import (
    events_dataframe_from_rows,
    export_project_bundle,
    export_project_single_file,
    import_project_bundle,
    is_valid_autosave_snapshot,
    normalize_event_table_rows,
    pending_autosave_path,
    quarantine_autosave_snapshot,
    restore_autosave,
    save_project_file,
)
from vasoanalyzer.services.types import ProjectRepository
from vasoanalyzer.storage.dataset_package import (
    DatasetPackageValidationError,
    export_dataset_package,
    import_dataset_package,
)
from vasoanalyzer.ui.commands import PointEditCommand, ReplaceEventCommand
from vasoanalyzer.ui.controllers.selection_sync import event_time_for_row, pick_event_row
from vasoanalyzer.ui.dialogs.event_review_wizard import EventReviewWizard
from vasoanalyzer.ui.dialogs.excel_mapping_dialog import update_excel_file
from vasoanalyzer.ui.dialogs.excel_template_export_dialog import ExcelTemplateExportDialog
from vasoanalyzer.ui.dialogs.legend_settings_dialog import LegendSettingsDialog
from vasoanalyzer.ui.dialogs.relink_dialog import MissingAsset, RelinkDialog
from vasoanalyzer.ui.dialogs.source_project_browser import (
    SourceProjectBrowserDialog,
    build_import_plan,
)
from vasoanalyzer.ui.dialogs.unified_settings_dialog import (
    UnifiedPlotSettingsDialog,
)
from vasoanalyzer.ui.event_table import build_event_table_column_contract
from vasoanalyzer.ui.formatting.time_format import TimeMode, coerce_time_mode
from vasoanalyzer.ui.icons import snapshot_icon
from vasoanalyzer.ui.panels.event_review_panel import EventReviewPanel
from vasoanalyzer.ui.panels.plot_empty_state import PlotEmptyState
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.overlays import AnnotationSpec
from vasoanalyzer.ui.point_editor_session import PointEditorSession, SessionSummary
from vasoanalyzer.ui.point_editor_view import PointEditorDialog
from vasoanalyzer.ui.review_mode_controller import ReviewModeController
from vasoanalyzer.ui.scope_view import ScopeDock
from vasoanalyzer.ui.theme import CURRENT_THEME, css_rgba_to_mpl, get_theme_manager
from vasoanalyzer.ui.tiff_viewer_v2 import TiffStackViewerWidget
from vasoanalyzer.ui.time_scrollbar import (
    TIME_SCROLLBAR_SCALE,
    compute_scrollbar_state,
    window_from_scroll_value,
)
from vasoanalyzer.ui.zoom_window import ZoomWindowDock

from .constants import DEFAULT_STYLE, PREVIOUS_PLOT_PATH
from .dialogs.new_project_dialog import NewProjectDialog
from .dialogs.welcome_dialog import WelcomeGuideDialog
from .metadata_panel import MetadataDock
from .plotting import auto_export_editable_plot, export_high_res_plot, toggle_grid
from .project_management import (
    open_excel_mapping_dialog,
    save_data_as_n,
)
from .style_manager import PlotStyleManager
from .update_checker import UpdateChecker

log = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.app.window_manager import WindowManager


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return False
    return value not in {"0", "false", "no", "off"}


_TIME_SYNC_DEBUG = bool(os.getenv("VA_TIME_SYNC_DEBUG"))
_TIFF_PROMPT_THRESHOLD = 1000
_TIFF_REDUCED_TARGET_FRAMES = 400
_CLIP_MIME = "application/x-vaso-datasets"
DEFAULT_INITIAL_VIEW_SECONDS = 1800.0


def _log_time_sync(label: str, **fields) -> None:
    """Conditional debug logger for time/frame sync flows."""

    if not (_TIME_SYNC_DEBUG or log.isEnabledFor(logging.DEBUG)):
        return
    clean = {k: v for k, v in fields.items() if v is not None}
    payload = ", ".join(f"{k}={v}" for k, v in clean.items())
    if _TIME_SYNC_DEBUG:
        log.info("[SYNC] %s %s", label, payload)
    else:
        log.debug("[SYNC] %s %s", label, payload)


REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_CONFIRMED = "CONFIRMED"
REVIEW_EDITED = "EDITED"
REVIEW_NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"


class _StyleHolder:
    def __init__(self, style):
        self._style = style

    def get_style(self):
        return self._style

    def set_style(self, style):
        self._style = style


class _SampleLoadSignals(QObject):
    progressChanged = pyqtSignal(int, str)
    finished = pyqtSignal(object, object, object, object, object)
    error = pyqtSignal(object, object, str)


class _SampleLoadJob(QRunnable):
    """Background job that materialises trace/events/results for a sample."""

    def __init__(
        self,
        repo: ProjectRepository | None,
        project_path: str | None,
        sample: SampleN,
        token: object,
        *,
        load_trace: bool,
        load_events: bool,
        load_results: bool,
        staging_db_path: str | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = _SampleLoadSignals()
        self._repo = repo
        self._project_path = project_path
        self._sample = sample
        self._token = token
        self._load_trace = load_trace
        self._load_events = load_events
        self._load_results = load_results
        self._dataset_id = sample.dataset_id
        self._staging_db_path = staging_db_path
        self._emit_progress(5, "Queued")

    def _emit_progress(self, percent: int, label: str) -> None:
        """Safely emit progress updates."""
        with contextlib.suppress(RuntimeError):
            self.signals.progressChanged.emit(percent, label)

    def run(self) -> None:  # type: ignore[override]
        trace_df = None
        events_df = None
        analysis_results = None

        if self._dataset_id is None:
            self.signals.finished.emit(self._token, self._sample, None, None, None)
            return

        repo = self._repo
        owned_ctx: ProjectContext | None = None
        thread_local_conn: sqlite3.Connection | None = None

        try:
            self._emit_progress(10, "Opening storage")
            # If we have a staging DB path, create a thread-local connection.
            # This fast path is used when project._store already has an open staging DB
            # (set by _save_project_bundle after any save), even when project_ctx is None.
            if self._staging_db_path:
                log.debug(
                    "Background job: creating thread-local connection to %s",
                    self._staging_db_path,
                )
                # Create connection in THIS thread (safe for SQLite)
                thread_local_conn = sqlite3.connect(self._staging_db_path)
                log.debug("Background job: thread-local connection created")

                # Create a temporary store wrapper with our thread-local connection
                from pathlib import Path

                from vasoanalyzer.storage.sqlite_store import ProjectStore

                temp_store = ProjectStore(path=Path(self._staging_db_path), conn=thread_local_conn)

                # Wrap in a temporary repository
                from vasoanalyzer.services.project_service import (
                    SQLiteProjectRepository,
                )

                repo = SQLiteProjectRepository(temp_store)
                log.debug("Background job: thread-safe repository created")

            elif repo is None:
                log.warning(
                    "Background job repo missing; creating new context for %s",
                    self._project_path,
                )
                if not self._project_path:
                    raise RuntimeError("Project path unavailable for sample load")
                log.debug("Opening new ProjectContext for %s", self._project_path)
                owned_ctx = open_project_ctx(self._project_path)
                repo = owned_ctx.repo
                log.debug("Created new context %s (repo=%s)", owned_ctx, repo)
            else:
                # Never reuse the main thread's SQLite connection from a background thread.
                # Extract the DB file path from the repo and open a thread-local connection.
                db_path: str | None = None
                try:
                    existing_store = getattr(repo, "_store", None)
                    if existing_store is not None:
                        p = getattr(existing_store, "path", None)
                        if p is not None:
                            db_path = str(p)
                except Exception:
                    log.debug("Failed to extract db path from existing store", exc_info=True)

                if db_path:
                    log.debug(
                        "Background job: creating thread-local connection to %s (from repo._store.path)",
                        db_path,
                    )
                    from pathlib import Path

                    from vasoanalyzer.services.project_service import (
                        SQLiteProjectRepository,
                    )
                    from vasoanalyzer.storage.sqlite_store import ProjectStore

                    thread_local_conn = sqlite3.connect(db_path)
                    temp_store = ProjectStore(path=Path(db_path), conn=thread_local_conn)
                    repo = SQLiteProjectRepository(temp_store)
                    log.debug("Background job: thread-safe repository created from repo store path")
                else:
                    log.warning(
                        "Background job: could not extract DB path from repo; using existing repo connection "
                        "(unsafe for cross-thread SQLite access) — repo=%s",
                        repo,
                    )

            if repo is None:
                raise RuntimeError("Unable to obtain project repository")

            if self._load_trace:
                self._emit_progress(40, "Loading trace")
                trace_raw = repo.get_trace(self._dataset_id)  # type: ignore[call-arg]
                self._emit_progress(55, "Formatting trace")
                trace_df = project_module._format_trace_df(
                    trace_raw,
                    getattr(self._sample, "trace_column_labels", None),
                    getattr(self._sample, "name", None),
                )
                history = getattr(self._sample, "edit_history", None)
                if trace_df is not None and history is not None:
                    trace_df.attrs["edit_log"] = history

            if self._load_events:
                self._emit_progress(70, "Loading events")
                log.debug("Background job: loading events for dataset_id=%s", self._dataset_id)
                events_raw = repo.get_events(self._dataset_id)  # type: ignore[call-arg]
                log.debug(
                    "Background job: loaded %d event rows",
                    len(events_raw) if events_raw is not None else 0,
                )
                self._emit_progress(80, "Formatting events")
                events_df = project_module._format_events_df(events_raw)

            if self._load_results:
                self._emit_progress(90, "Loading results")
                analysis_results = project_module._load_sample_results(repo, self._dataset_id)
            self._emit_progress(100, "Finalizing")
        except Exception as exc:  # pragma: no cover - defensive UI logging
            self.signals.error.emit(self._token, self._sample, str(exc))
            return
        finally:
            # Clean up thread-local connection
            if thread_local_conn is not None:
                try:
                    thread_local_conn.close()
                    log.debug("Background job: thread-local connection closed")
                except Exception as e:
                    log.warning("Error closing thread-local connection: %s", e)

            if owned_ctx is not None:
                close_project_ctx(owned_ctx)

        self.signals.finished.emit(self._token, self._sample, trace_df, events_df, analysis_results)


class _SnapshotLoadSignals(QObject):
    progressChanged = pyqtSignal(int, str)
    finished = pyqtSignal(object, object, object, object)


class _SnapshotLoadJob(QRunnable):
    """Background job that materialises snapshot stacks for a sample."""

    def __init__(
        self,
        sample: SampleN,
        token: object,
        project_path: str | None,
        asset_id: str | int | None,
        snapshot_path: str | None,
        snapshot_format: str | None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = _SnapshotLoadSignals()
        self._sample = sample
        self._token = token
        self._project_path = project_path
        self._asset_id = asset_id
        self._snapshot_path = snapshot_path
        self._snapshot_format = snapshot_format or ""

    def _emit_progress(self, percent: int, label: str) -> None:
        """Safely emit progress updates."""
        with contextlib.suppress(RuntimeError):
            self.signals.progressChanged.emit(percent, label)

    def run(self) -> None:  # type: ignore[override]
        stack = None
        error: str | None = None
        try:
            self._emit_progress(0, "Loading snapshot")
            stack = self._load_from_asset()
            if stack is None:
                stack = self._load_from_path()
            if stack is None:
                error = "Snapshots unavailable"
            self._emit_progress(100, "Complete")
        except Exception as exc:  # pragma: no cover - defensive logging
            error = str(exc)
            stack = None

        self.signals.finished.emit(self._token, self._sample, stack, error)

    def _load_from_asset(self) -> np.ndarray | None:
        if not self._project_path or not self._asset_id:
            return None

        ctx: ProjectContext | None = None
        try:
            self._emit_progress(20, "Opening project context")
            ctx = open_project_ctx(self._project_path)
            repo = ctx.repo
            if repo is None:
                return None
            self._emit_progress(40, "Reading snapshot data")
            data = repo.get_asset_bytes(self._asset_id)
            if not data:
                return None
            self._emit_progress(70, "Decoding snapshot")
            return self._stack_from_bytes(data)
        finally:
            if ctx is not None:
                close_project_ctx(ctx)

    def _load_from_path(self) -> np.ndarray | None:
        if not self._snapshot_path:
            return None
        path = Path(self._snapshot_path).expanduser()
        if not path.exists():
            return None
        self._emit_progress(40, "Reading TIFF file")
        frames, _, _ = load_tiff(path.as_posix(), metadata=False)
        if frames:
            self._emit_progress(80, "Building image stack")
            return np.stack(frames)
        return None

    def _stack_from_bytes(self, data: bytes) -> np.ndarray | None:
        buffer = io.BytesIO(data)
        fmt = self._snapshot_format.lower()
        if not fmt:
            fmt = "npz" if data.startswith(b"PK") else "npy"
        if fmt == "npz":
            with np.load(buffer, allow_pickle=False) as npz_file:
                stack = npz_file["stack"]
        else:
            stack = np.load(buffer, allow_pickle=False)
        if isinstance(stack, np.ndarray):
            return stack
        return np.stack(stack)


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


class _SaveJobSignals(QObject):
    progressChanged = pyqtSignal(int, str)
    finished = pyqtSignal(bool, float, str)
    error = pyqtSignal(str)


class _SaveJob(QRunnable):
    """Background job that writes the project to disk off the UI thread."""

    def __init__(
        self,
        project: Project,
        path: str | None,
        *,
        skip_optimize: bool,
        mode: str = "manual",
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = _SaveJobSignals()
        self._project = project
        self._path = path
        self._skip_optimize = skip_optimize
        self._mode = mode
        self._emit_progress(0, "Preparing project…")

    def _emit_progress(self, percent: int, label: str) -> None:
        """Safely emit progress updates."""
        with contextlib.suppress(RuntimeError):
            self.signals.progressChanged.emit(percent, label)

    def run(self) -> None:  # type: ignore[override]
        import time

        start = time.perf_counter()
        path = self._path
        log.debug("Background save job started path=%s mode=%s", path, self._mode)
        try:
            from vasoanalyzer.services.project_service import (
                autosave_project,
                save_project_file,
            )

            if self._mode == "autosave":
                self._emit_progress(20, "Autosaving project…")
                autosave_path = autosave_project(self._project)
                actual_path = autosave_path or path or getattr(self._project, "path", None)
                self._emit_progress(80, "Writing autosave…")
            else:
                self._emit_progress(20, "Serializing project…")
                save_project_file(self._project, path=path, skip_optimize=self._skip_optimize)
                actual_path = path or getattr(self._project, "path", None)
                self._emit_progress(80, "Writing project…")

            duration = time.perf_counter() - start
            self._emit_progress(100, "Finalizing…")
            self.signals.finished.emit(True, duration, actual_path or "")
        except Exception as exc:
            duration = time.perf_counter() - start
            self.signals.error.emit(str(exc))
            self.signals.finished.emit(False, duration, path or getattr(self._project, "path", ""))
        finally:
            # Ensure any store opened during the save is closed in the worker thread
            store = getattr(self._project, "_store", None)
            if store is not None:
                with contextlib.suppress(Exception):
                    store.close()
                self._project._store = None


def _collect_missing_assets(project: Project) -> tuple[list[MissingAsset], list[str]]:
    missing: list[MissingAsset] = []
    project_missing: list[str] = []

    base_dir = Path(project.path).resolve().parent if project.path else Path.cwd()

    def _resolve(candidate: str | None) -> Path | None:
        if not candidate:
            return None
        path_obj = Path(candidate)
        if not path_obj.is_absolute():
            path_obj = base_dir / path_obj
        return path_obj

    for experiment in project.experiments:
        for sample in experiment.samples:
            has_embedded_trace = (
                getattr(sample, "dataset_id", None) is not None
                or getattr(sample, "trace_data", None) is not None
            )
            has_embedded_events = (
                getattr(sample, "dataset_id", None) is not None
                or getattr(sample, "events_data", None) is not None
            )
            for kind, label in (("trace", "Trace"), ("events", "Events")):
                if kind == "trace" and has_embedded_trace:
                    continue
                if kind == "events" and has_embedded_events:
                    continue
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


def _copy_legend_settings(settings: dict) -> dict:
    """Fast copy of legend settings (avoids expensive deepcopy)."""
    result = dict(settings)
    # Only deep copy the labels dict if it exists and isn't empty
    if "labels" in result and result["labels"]:
        result["labels"] = dict(result["labels"])
    return result


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
    def __init__(
        self,
        check_updates: bool = True,
        window_manager: "WindowManager | None" = None,
    ):
        super().__init__()
        self.window_manager = window_manager

        self._active_theme_mode = "system"
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
        self.setWindowTitle(f"VasoAnalyzer {APP_VERSION}")
        self.setGeometry(100, 100, 1280, 720)
        screen_size = QDesktopWidget().availableGeometry()
        self.resize(screen_size.width(), screen_size.height())

        # ===== Initialize State =====
        self.trace_data = None
        self.trace_file_path = None
        self.trace_model: TraceModel | None = None
        self.trace_time: np.ndarray | None = None
        self.trace_time_exact: np.ndarray | None = None
        self.frame_numbers: np.ndarray | None = None
        self.frame_number_to_trace_idx: dict[int, int] = {}
        self.tiff_page_to_trace_idx: dict[int, int] = {}
        self.tiff_page_times: list[float] = []
        self.tiff_page_times_valid: bool = False
        self.snapshot_interval_median: float | None = None
        self.frame_trace_time: np.ndarray | None = None
        self.frame_trace_index: np.ndarray | None = None
        self.frame_trace_indices = []
        self.snapshot_frames = []
        self.frames_metadata = []
        self.frame_times = []
        self.snapshot_frame_indices: list[int] = []
        self.snapshot_loading_info: dict[str, Any] | None = None
        self.snapshot_frame_stride: int = 1
        self.snapshot_total_frames: int | None = None
        self.current_frame = 0
        self.current_page = 0
        self.page_float = 0.0
        self._snapshot_pps_default = self._resolve_snapshot_pps_default()
        self.snapshot_pps = float(self._snapshot_pps_default)
        self.snapshot_speed_multiplier = 1.0
        self.snapshot_sync_enabled = True
        self.snapshot_loop_enabled = True
        self._snapshot_play_start_wall_time: float | None = None
        self._snapshot_play_start_frame_index: int = 0
        self._snapshot_last_rendered_frame: int | None = None
        self._snapshot_ui_tick_hz: float | None = None
        self._snapshot_playback_last_tick_time: float | None = None
        self._snapshot_play_time_s: float | None = None
        self._snapshot_playback_last_log_time: float | None = None
        self.event_labels = []
        self.event_times = []
        self.event_frames = []
        self.event_label_meta: list[dict[str, Any]] = []
        self.event_annotations: list[AnnotationSpec] = []
        self._annotation_lane_visible = False
        self.event_text_objects = []
        self.event_table_data = []
        self._event_table_updating = False
        self._event_selection_syncing = False
        self._suppress_event_table_sync = False
        self._event_review_wizard = None
        self._suppress_review_prompt = False
        self._current_review_event_index = None
        self._review_notice_dismissed_key = None
        self.review_notice_banner = None
        self.review_notice_review_button = None
        self.review_notice_dismiss_button = None
        self._sample_summary_logged = False
        self.pinned_points = []
        self.slider_markers = {}
        self._time_cursor_time: float | None = None
        self._time_cursor_visible: bool = True
        self.trace_line = None
        self.od_line = None
        # Explicit references to the plotted lines
        self.inner_line = None
        self.outer_line = None
        self.plot_legend = None
        self.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)
        self.event_metadata = []
        self._last_event_import = {}
        self._event_table_path = None  # path to the current sample's event table, if known
        self.sampling_rate_hz: float | None = None
        self.session_dirty = False
        self.last_autosave_path: str | None = None
        self.autosave_interval_ms = 5 * 60 * 1000  # 5 minutes by default
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(self.autosave_interval_ms)
        self.autosave_timer.setSingleShot(False)
        self.autosave_timer.timeout.connect(self._autosave_tick)
        self.autosave_timer.start()
        self._save_in_progress = False  # Mutex to prevent concurrent saves
        self._active_save_reason: str | None = None
        self._active_save_path: str | None = None
        self._active_save_mode: str | None = None
        self._active_autosave_ctx: dict | None = None
        self._project_state_rev: int = 0
        self._autosave_in_progress: bool = False
        self._pending_autosave_ctx: dict | None = None
        self._last_save_error: str | None = None
        self._event_highlight_color = DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF")
        self._event_highlight_base_alpha = float(DEFAULT_STYLE.get("event_highlight_alpha", 0.95))
        self._event_highlight_duration_ms = int(
            DEFAULT_STYLE.get("event_highlight_duration_ms", 2000)
        )
        self._event_highlight_elapsed_ms = 0
        self._event_highlight_timer = QTimer(self)
        self._event_highlight_timer.setSingleShot(False)
        self._event_highlight_timer.setInterval(40)
        self._event_highlight_timer.timeout.connect(self._on_event_highlight_tick)
        # Performance: Cache expensive state gathering operations
        self._cached_sample_state: dict | None = None
        self._sample_state_dirty = True
        self._cached_snapshot_style: dict | None = None
        self._snapshot_style_dirty = True
        self._snapshot_load_token: object | None = None
        self._snapshot_loading_sample: SampleN | None = None
        self._snapshot_viewer_pending_open = False
        self._pending_snapshot_visibility: bool | None = None
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
        self._right_panel_layout = None
        self.snapshot_viewer_action = None
        self.recent_files = []
        self._event_label_mode: str = "names_on_hover"
        self._time_mode: str = "auto"
        self.settings = QSettings("TykockiLab", "VasoAnalyzer")
        self._time_mode = str(self.settings.value("plot/timeMode", self._time_mode, type=str) or "auto")
        self._event_label_mode = str(
            self.settings.value("plot/eventLabelMode", self._event_label_mode, type=str)
            or self._event_label_mode
        )
        self.onboarding_settings = QSettings(ONBOARDING_SETTINGS_ORG, ONBOARDING_SETTINGS_APP)
        self._syncing_time_window = False
        self._axis_source_axis = None
        self._axis_xlim_cid: int | None = None
        self._welcome_dialog = None
        self._update_check_in_progress = False
        self._updates_disabled_by_env = _env_flag("VASO_DISABLE_UPDATE_CHECK")
        self._snapshot_panel_disabled_by_env = _env_flag("VASO_DISABLE_SNAPSHOT_PANEL")
        self._update_checker = UpdateChecker(self)
        self._update_checker.completed.connect(self._on_update_check_completed)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_update_checker)
        self.load_recent_files()
        self.recent_projects = []
        self.load_recent_projects()
        self.setAcceptDrops(True)
        self.setStatusBar(QStatusBar(self))

        # Setup progress bar in status bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(240)
        self._progress_bar.setMaximumHeight(18)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()  # Hidden by default
        self.statusBar().addPermanentWidget(self._progress_bar)
        self._storage_mode_label = QLabel("")
        self._storage_mode_label.setVisible(False)
        self._storage_mode_label.setContentsMargins(8, 0, 8, 0)
        self.statusBar().addPermanentWidget(self._storage_mode_label, 0)
        self._storage_mode_path: str | None = None
        self._storage_mode_is_cloud: bool | None = None
        self._storage_mode_cloud_service: str | None = None
        self._apply_status_bar_theme()

        self.current_project = None
        self.project_tree = None
        self.metadata_dock = None
        self.zoom_dock = None
        self.scope_dock = None
        self.current_experiment = None
        self.current_sample = None
        self._last_track_layout_sample_id: int | None = None
        self.project_ctx: ProjectContext | None = None
        self.project_path: str | None = None
        self.project_meta: dict[str, Any] = {}
        self.data_cache: DataCache | None = None
        self._cache_root_hint: str | None = None
        self.snapshot_widget: TiffStackViewerWidget | None = None
        self.slider = None
        self._snapshot_sync_status_text: str | None = None
        self._snapshot_sync_partial_count: int | None = None
        self._last_tiff_page_time_warning_key: tuple | None = None
        if not self._snapshot_panel_disabled_by_env:
            self.snapshot_widget = TiffStackViewerWidget(self)
            self.snapshot_widget.hide()
        self._mirror_sources_enabled = False
        self._missing_assets: dict[tuple[int, str], MissingAsset] = {}
        self._relink_dialog: RelinkDialog | None = None
        self.action_relink_assets: QAction | None = None
        self.project_state = {}
        self._style_holder = _StyleHolder(DEFAULT_STYLE.copy())
        self._style_manager = PlotStyleManager(self._style_holder.get_style())
        self._data_quality_icons: dict[str | None, QIcon] = {}
        self.actGrid: QAction | None = None
        self.actStyle: QAction | None = None
        self.actOverviewStrip: QAction | None = None
        self._nav_mode_actions: list[QAction] = []
        self.actEventLines: QAction | None = None
        self.actEventLabelsOff: QAction | None = None
        self.actEventLabelsVertical: QAction | None = None
        self.actEventLabelsHorizontal: QAction | None = None
        self.actEventLabelsOutside: QAction | None = None
        self._event_lines_visible: bool = True
        self._event_label_gap_default: int = 22
        self._event_label_action_group: QActionGroup | None = None
        self.event_label_button: QToolButton | None = None
        self._overview_strip_enabled = False
        self._channel_event_labels_visible = False
        self._channel_event_label_font_size: float = 9.0
        self._trace_navigation_available = False
        self._space_pan_active: bool = False
        self._space_pan_prev_mode: str | None = None

        self._deferred_autosave_timer = QTimer(self)
        self._deferred_autosave_timer.setSingleShot(True)
        self._deferred_autosave_timer.timeout.connect(self._run_deferred_autosave)
        self._pending_autosave_reason: str | None = None
        self.menu_event_lines_action: QAction | None = None
        # ——— undo/redo ———
        self.undo_stack = QUndoStack(self)
        self._change_log = ChangeLogManager()
        self._thread_pool = QThreadPool.globalInstance()
        self._current_sample_token: object | None = None
        self._loading_dataset_ids: set[int] = set()  # Track in-flight dataset loads
        self._pending_asset_scan_token: object | None = None
        self._project_missing_messages: list[str] = []
        self._last_missing_assets_snapshot: tuple[int, int] | None = None
        self.event_table_action: QAction | None = None
        self._event_panel_has_data = False
        self._layout_log_ready = False
        self._next_step_hint_widget: QWidget | None = None
        self._next_step_hint_dismissed = False

        # ===== Axis + Slider State =====
        self.axis_dragging = False
        self.axis_drag_start = None
        self.drag_direction = None
        self.scroll_slider = None
        self._updating_time_scrollbar = False
        self._scrolling_from_scrollbar = False
        self._last_x_window_width_s: float | None = None
        self._xrange_source: str = ""
        self._xrange_expected: tuple[float, float] | None = None
        self._scrollbar_drag_width_s: float | None = None
        self.window_width = None
        self._plot_drag_in_progress = False
        self._last_hover_time: float | None = None
        self._pending_plot_layout: dict | None = None
        self._pending_pyqtgraph_track_state: dict | None = None
        self.trace_nav_bar = None
        self.overview_strip = None
        self.plot_stack_widget = None
        self.plot_stack_layout = None
        self.plot_content_page = None
        self.plot_empty_state_page = None
        self.plot_empty_state = None
        self._plot_host_window_listener = None
        self._pending_sample_loads: dict[int, SampleN] = {}
        self._processing_pending_sample_loads = False
        # Cache TraceModel per dataset_id to avoid rebuilding on every switch
        self._trace_model_cache: dict[int, TraceModel] = {}
        # Cache last view window per dataset_id to bypass heavy autoscale
        self._window_cache: dict[int, tuple[float, float]] = {}
        # Track background preload jobs
        self._preload_in_flight = 0

        # ===== Build UI =====
        self.create_menubar()
        self.initUI()
        self._wrap_views()
        self.setup_project_sidebar()
        self.setup_metadata_panel()
        self.setup_zoom_dock()
        self.setup_scope_dock()
        self.setup_review_panel_dock()
        self._update_excel_controls()

        self.modeStack.setMouseTracking(True)
        self.modeStack.widget(0).setMouseTracking(True)
        self.canvas.setMouseTracking(True)

        # Start in the workspace view (no embedded Home page in MainWindow).
        self.show_analysis_workspace()

        if (
            check_updates
            and not self._updates_disabled_by_env
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        ):
            self.check_for_updates_at_startup()

        theme_manager = get_theme_manager()
        theme_manager.themeChanged.connect(self.apply_theme)

        # ===== Instantiate Manager Delegates =====
        from vasoanalyzer.ui.managers.export_manager import ExportManager
        from vasoanalyzer.ui.managers.navigation_manager import NavigationManager
        from vasoanalyzer.ui.managers.project_manager import ProjectManager
        from vasoanalyzer.ui.managers.snapshot_manager import SnapshotManager

        self._export_mgr = ExportManager(self, parent=self)
        self._project_mgr = ProjectManager(self, parent=self)
        self._snapshot_mgr = SnapshotManager(self, parent=self)
        self._navigation_mgr = NavigationManager(self, parent=self)

        QTimer.singleShot(0, self._maybe_run_onboarding)

    def initUI(self):
        from vasoanalyzer.ui.shell.init_ui import init_ui as _init_ui_adapter

        return _init_ui_adapter(self)

    def setup_project_sidebar(self):
        from .project_explorer import ProjectExplorerWidget

        self.project_dock = ProjectExplorerWidget(self)
        self.project_tree = self.project_dock.tree
        self.project_tree.setHeaderHidden(True)
        self.project_tree.itemClicked.connect(self.on_tree_item_clicked)
        self.project_tree.itemChanged.connect(self.on_tree_item_changed)
        self.project_tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.project_tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        self.project_tree.itemExpanded.connect(self._on_tree_experiment_expand_changed)
        self.project_tree.itemCollapsed.connect(self._on_tree_experiment_expand_changed)
        self.project_dock.tree.experiment_reordered.connect(self._on_experiment_reordered)
        log.info("Connected project_tree.itemDoubleClicked to on_tree_item_double_clicked")
        # Single-click opens a sample; double-click is reserved for editing or opening figures
        self.project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(self.show_project_context_menu)
        self.project_tree.setAlternatingRowColors(True)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)
        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.project_dock.toggleViewAction())

        # Toggle button in toolbar
        self.project_toggle_btn = QToolButton()
        self.project_toggle_btn.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.project_toggle_btn.setCheckable(True)
        self.project_toggle_btn.setChecked(False)
        self.project_toggle_btn.setToolTip("Toggle project panel")
        self.project_toggle_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.project_toggle_btn.setProperty("isPanelToggle", True)
        if hasattr(self, "toolbar") and self.toolbar is not None:
            self.project_toggle_btn.setIconSize(self.toolbar.iconSize())
        self.project_toggle_btn.clicked.connect(lambda checked: self.project_dock.set_open(checked))
        self.project_dock.visibilityChanged.connect(self.project_toggle_btn.setChecked)
        self.project_toggle_action = self.toolbar.addWidget(self.project_toggle_btn)
        if hasattr(self.project_dock, "apply_theme"):
            self.project_dock.apply_theme()
        self.project_dock.hide()

    def _bold_font(self, size_delta: int = 0) -> QFont:
        font = QFont()
        font.setBold(True)
        if size_delta:
            with contextlib.suppress(Exception):
                font.setPointSize(font.pointSize() + int(size_delta))
        return font

    def _reveal_project_sidebar(self) -> None:
        """Ensure the project dock is visible when a project is active."""

        dock = getattr(self, "project_dock", None)
        if dock is None:
            return
        dock.setVisible(True)
        dock.show()
        raise_method = getattr(dock, "raise_", None)
        if callable(raise_method):
            raise_method()

    def setup_metadata_panel(self):
        self.metadata_dock = MetadataDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.metadata_dock)

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.metadata_dock.toggleViewAction())

        # Keep toggle button state in sync with dock visibility.
        self.metadata_dock.visibilityChanged.connect(self._on_metadata_visibility_changed)

        project_form = self.metadata_dock.project_form
        project_form.description_changed.connect(self.on_project_description_changed)
        project_form.tags_changed.connect(self.on_project_tags_changed)
        project_form.attachment_add_requested.connect(self.on_project_add_attachment)
        project_form.attachment_remove_requested.connect(self.on_project_remove_attachment)
        project_form.attachment_open_requested.connect(self.on_project_open_attachment)

        experiment_form = self.metadata_dock.experiment_form
        experiment_form.notes_changed.connect(self.on_experiment_notes_changed)
        experiment_form.tags_changed.connect(self.on_experiment_tags_changed)

        sample_form = self.metadata_dock.sample_form
        sample_form.notes_changed.connect(self.on_sample_notes_changed)
        sample_form.attachment_add_requested.connect(self.on_sample_add_attachment)
        sample_form.attachment_remove_requested.connect(self.on_sample_remove_attachment)
        sample_form.attachment_open_requested.connect(self.on_sample_open_attachment)

        self.metadata_toggle_btn = QToolButton()
        self.metadata_toggle_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.metadata_toggle_btn.setCheckable(True)
        self.metadata_toggle_btn.setChecked(False)
        self.metadata_toggle_btn.setToolTip("Toggle event and snapshot panel")
        self.metadata_toggle_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.metadata_toggle_btn.setProperty("isPanelToggle", True)
        if hasattr(self, "toolbar") and self.toolbar is not None:
            self.metadata_toggle_btn.setIconSize(self.toolbar.iconSize())
        self.metadata_toggle_btn.clicked.connect(
            lambda checked: self.metadata_dock.setVisible(checked)
        )
        self.metadata_toggle_action = self.toolbar.addWidget(self.metadata_toggle_btn)
        self.metadata_dock.hide()
        self._lock_plot_toolbar_row2_order()

    def setup_zoom_dock(self):
        self.zoom_dock = ZoomWindowDock(self)
        self.zoom_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.zoom_dock)
        self.zoom_dock.hide()

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.zoom_dock.toggleViewAction())

        self.zoom_dock.visibilityChanged.connect(self._on_zoom_visibility_changed)

    def setup_scope_dock(self):
        self.scope_dock = ScopeDock(self)
        self.scope_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.scope_dock)
        self.scope_dock.hide()

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.scope_dock.toggleViewAction())

        self.scope_dock.visibilityChanged.connect(self._on_scope_visibility_changed)

    def setup_review_panel_dock(self):
        """Setup event review panel as docked widget."""
        # Create review panel widget
        self.review_panel = EventReviewPanel(self)

        # Create dock widget
        self.review_dock = QDockWidget("Event Review", self)
        self.review_dock.setObjectName("ReviewDock")
        self.review_dock.setWidget(self.review_panel)
        self.review_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.review_dock)
        self.review_dock.hide()

        # Add to show/hide menu
        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.review_dock.toggleViewAction())

        # Create review mode controller
        plot_host = getattr(self, "plot_host", None)
        self.review_controller = ReviewModeController(self, self.review_panel, plot_host)

        # Register click handler for sampling mode
        if plot_host is not None:
            plot_host.on_click(self._handle_review_sampling_click)

        # Connect visibility changes
        self.review_dock.visibilityChanged.connect(self._on_review_dock_visibility_changed)

    def _on_review_dock_visibility_changed(self, visible: bool) -> None:
        """Handle review dock visibility changes.

        Args:
            visible: Whether dock is now visible
        """
        if visible and not self.review_controller.is_active():
            # Start review when dock opens
            self.review_controller.start_review()
        elif not visible and self.review_controller.is_active():
            # End review when dock closes
            self.review_controller.end_review()
        self._apply_event_table_column_contract()

    def _handle_review_sampling_click(self, ctx) -> None:
        """Handle plot clicks during review mode.

        Args:
            ctx: ClickContext from plot interaction
        """
        # Check if review mode is active
        if not hasattr(self, "review_controller"):
            return

        # If review is not active, don't interfere with normal clicks
        if not self.review_controller.is_active():
            return

        # During review mode, handle sampling clicks (press only, not release)
        if self.review_controller.sampling_mode:
            if getattr(ctx, "pressed", False) is not True:
                return
            if hasattr(ctx, "x_data") and ctx.x_data is not None:
                self.review_controller.handle_trace_click(ctx.x_data)
        # Otherwise, just consume the click to prevent accidental actions
        # (user can still pan/zoom with mouse drag, but single clicks are blocked)

    def _toggle_review_mode(self) -> None:
        """Toggle review mode (show/hide review panel)."""
        if not hasattr(self, "review_dock"):
            log.warning("Review dock not initialized")
            return

        if not self.event_table_data:
            QMessageBox.information(self, "No Events", "Load events before starting a review.")
            return

        # Toggle dock visibility
        self.review_dock.setVisible(not self.review_dock.isVisible())

        # Raise and activate if showing
        if self.review_dock.isVisible():
            with contextlib.suppress(Exception):
                self.review_dock.raise_()
                self.review_dock.activateWindow()

    # ---------- Project Menu Actions ----------
    def _replace_current_project(self, project):
        """Swap the active project, ensuring old resources are released."""

        if project is self.current_project:
            return

        # Close old project context before replacing
        old_ctx = getattr(self, "project_ctx", None)
        if old_ctx is not None:
            try:
                from vasoanalyzer.core.project import close_project_ctx

                close_project_ctx(old_ctx)
                log.debug("Closed previous ProjectContext")
            except Exception:
                log.debug("Failed to close previous ProjectContext", exc_info=True)
            self.project_ctx = None
            self.project_path = None
            self.project_meta = {}

        old_project = self.current_project
        self.current_project = project
        self.current_experiment = None
        self.current_sample = None
        self.project_state.clear()
        self._pending_sample_loads.clear()
        self._processing_pending_sample_loads = False
        self._cache_root_hint = project.path if project and getattr(project, "path", None) else None
        self.data_cache = None
        self._missing_assets.clear()
        if self.action_relink_assets:
            self.action_relink_assets.setEnabled(False)
        if self._relink_dialog:
            self._relink_dialog.hide()
        self._update_metadata_panel(project)
        self._update_window_title()
        self._update_storage_mode_indicator(
            getattr(project, "path", None) if project else None, show_message=False
        )

        if old_project is not None:
            try:
                old_project.close()
            except Exception:
                log.debug("Failed to close previous project resources", exc_info=True)

        self._next_step_hint_dismissed = False
        self._update_next_step_hint()
        self._update_plot_empty_state()
        # Kick off background preload of embedded datasets for fast switching
        self._start_project_preload()

    def _ensure_data_cache(self, hint_path: str | None = None) -> DataCache:
        """Return the active DataCache, creating it when necessary."""

        if self.current_project and getattr(self.current_project, "path", None):
            base_hint = self.current_project.path
        elif hint_path:
            try:
                base_hint = Path(hint_path).expanduser().resolve(strict=False).parent.as_posix()
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

    def _project_base_dir(self) -> Path | None:
        if self.current_project and self.current_project.path:
            try:
                return Path(self.current_project.path).expanduser().resolve(strict=False).parent
            except Exception:
                return Path(self.current_project.path).expanduser().parent
        return None

    @staticmethod
    def _compute_path_signature(path: Path) -> str | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return f"{stat.st_size}-{int(stat.st_mtime)}"

    def _update_sample_link_metadata(self, sample: SampleN, kind: str, path_obj: Path) -> None:
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

    def _resolve_sample_link(self, sample: SampleN, kind: str) -> str | None:
        path_attr = f"{kind}_path"
        hint_attr = f"{kind}_hint"
        relative_attr = f"{kind}_relative"

        # If the dataset is embedded (dataset_id present) we should not probe external files.
        if getattr(sample, "dataset_id", None) is not None:
            return getattr(sample, path_attr, None)

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

    def show_relink_dialog(self, checked: bool = False):
        """Show dialog to relink missing assets.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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

    def _apply_relinked_assets(self, assets: list[MissingAsset]) -> None:
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

    # ---------- Project preload ----------
    def _start_project_preload(self) -> None:
        """Preload embedded datasets (trace/events/TraceModel) in the background."""

        if not self.current_project or not isinstance(self.project_ctx, ProjectContext):
            return

        repo = getattr(self.project_ctx, "repo", None)
        project_path = getattr(self.project_ctx, "path", None)
        if repo is None or project_path is None:
            return

        samples: list[SampleN] = []
        for exp in self.current_project.experiments:
            for sample in exp.samples:
                if getattr(sample, "dataset_id", None) is not None:
                    samples.append(sample)

        if not samples:
            return

        # Extract staging DB path for thread-safe access
        staging_db_path: str | None = None
        try:
            store = getattr(repo, "_store", None)
            handle = getattr(store, "handle", None) if store is not None else None
            staging_path = getattr(handle, "staging_path", None) if handle is not None else None
            if staging_path is not None:
                staging_db_path = str(staging_path)
        except Exception:
            staging_db_path = None

        self._preload_in_flight = 0
        for sample in samples:
            dsid = getattr(sample, "dataset_id", None)
            if (
                dsid is not None
                and dsid in self._trace_model_cache
                and sample.events_data is not None
            ):
                continue
            job = _SampleLoadJob(
                repo,
                project_path,
                sample,
                object(),
                load_trace=True,
                load_events=True,
                load_results=False,
                staging_db_path=staging_db_path,
            )
            job.signals.finished.connect(self._on_preload_finished)
            job.signals.error.connect(self._on_preload_error)
            self._preload_in_flight += 1
            self._thread_pool.start(job)

        if self._preload_in_flight:
            self.statusBar().showMessage("Preparing datasets…", 0)

    def _on_preload_finished(
        self,
        _token: object,
        sample: SampleN,
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
        _analysis_results: dict[str, Any] | None,
    ) -> None:
        if trace_df is not None:
            sample.trace_data = trace_df
        if events_df is not None:
            sample.events_data = events_df

        dsid = getattr(sample, "dataset_id", None)
        if dsid is not None and sample.trace_data is not None:
            try:
                model = TraceModel.from_dataframe(sample.trace_data)
                self._trace_model_cache[dsid] = model
                self._window_cache.setdefault(dsid, model.full_range)
            except Exception:
                log.debug(
                    "Preload: failed to build TraceModel for %s",
                    sample.name,
                    exc_info=True,
                )

        self._preload_in_flight = max(0, self._preload_in_flight - 1)
        if self._preload_in_flight == 0 and self.statusBar() is not None:
            self.statusBar().clearMessage()

    def _on_preload_error(self, _token: object, sample: SampleN, message: str) -> None:
        log.debug("Preload error for %s: %s", getattr(sample, "name", "<unknown>"), message)
        self._preload_in_flight = max(0, self._preload_in_flight - 1)
        if self._preload_in_flight == 0 and self.statusBar() is not None:
            self.statusBar().clearMessage()

    def _handle_missing_asset(
        self,
        sample: SampleN,
        kind: str,
        path: str | None,
        error: str | None = None,
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

    def new_project(self, checked: bool = False):
        """Create a new project.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        manager = getattr(self, "window_manager", None)
        if manager is not None:
            manager.create_project_in_window_via_dialog(self)
            return
        dialog = NewProjectDialog(self, settings=self.settings)
        if dialog.exec_() != QDialog.Accepted:
            return

        self._create_project_from_inputs(
            dialog.project_name(),
            dialog.project_path(),
            dialog.experiment_name(),
        )

    def _create_project_from_inputs(self, name: str, path: str, exp_name: str | None) -> bool:
        if not name or not path:
            return False

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() not in [".vaso", ".vasopack"]:
            path_obj = path_obj.with_suffix(".vaso")
        normalised_path = str(path_obj.resolve(strict=False))

        log.info(
            "UI: Creating new project name=%r path=%s (initial experiment=%r)",
            name,
            normalised_path,
            exp_name or None,
        )

        # Check if user is trying to save to cloud storage
        from vasoanalyzer.core.project import _is_cloud_storage_path

        is_cloud, cloud_service = _is_cloud_storage_path(normalised_path)
        if is_cloud:
            reply = QMessageBox.warning(
                self,
                "Cloud Storage - Known Limitation",
                f"<b>You are creating a project in {cloud_service}</b>\n\n"
                f"<b>Technical Limitation:</b>\n"
                f"SQLite databases (like .vaso project files) can become corrupted when cloud sync services"
                f"upload the file mid-transaction. This happens because the sync daemon may interrupt "
                f"database writes, breaking integrity.\n\n"
                f"<b>Mitigations in place:</b>\n"
                f"• VasoAnalyzer uses WAL mode for better resilience\n"
                f"• Automatic recovery attempts if corruption occurs\n"
                f"• Risk is highest during active editing and autosaves\n\n"
                f"<b>Best practice:</b>\n"
                f"Store active projects locally (~/Documents, ~/Desktop), then copy .vaso "
                f"files to cloud storage for backup and sharing.\n\n"
                f"<b>Continue creating project in {cloud_service}?</b>",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False

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

        # Note: ProjectContext will be created when project is reopened via open_project_file()

        if self.project_tree and project.experiments:
            root_item = self.project_tree.topLevelItem(0)
            if root_item and root_item.childCount():
                first_exp_item = root_item.child(0)
                self.project_tree.setCurrentItem(first_exp_item)

        # Switch to analysis workspace so user can see project panel
        self.show_analysis_workspace()
        self._reveal_project_sidebar()

        self.statusBar().showMessage(
            "Project created. Use the Add Data actions to start populating your experiment.",
            6000,
        )
        self._update_storage_mode_indicator(normalised_path, force_message=True)
        return True

    def _open_project_file_legacy(self, path: str | None = None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Project",
                "",
                "Vaso Projects (*.vaso);;All Files (*)",
            )
            if not path:
                return

        path_obj = Path(path).expanduser().resolve(strict=False)
        path = str(path_obj)

        self.show_progress("Opening project…", maximum=0)
        self._clear_canvas_and_table()

        project: Project | None = None
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
                project_path = project.path or target_dir.joinpath(f"{stem}.vaso").as_posix()
                self.statusBar().showMessage(f"\u2713 Bundle unpacked to {target_dir}", 5000)
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Bundle Import Error",
                    f"Could not unpack bundle:\n{exc}",
                )
                self.hide_progress()
                return
        else:
            autosave_candidate = pending_autosave_path(path)
            if autosave_candidate:
                if not is_valid_autosave_snapshot(autosave_candidate):
                    quarantine_autosave_snapshot(autosave_candidate)
                    log.warning("Discarded corrupt autosave snapshot: %s", autosave_candidate)
                    QMessageBox.warning(
                        self,
                        "Autosave Discarded",
                        (
                            "The autosave snapshot for this project was corrupted and "
                            "has been discarded.\n\nThe original project will be opened instead."
                        ),
                    )
                    autosave_candidate = None
                else:
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
                                with contextlib.suppress(OSError):
                                    os.remove(autosave_candidate)
                            except Exception as exc:
                                QMessageBox.warning(
                                    self,
                                    "Autosave Recovery Failed",
                                    (
                                        "Could not restore autosave:\n"
                                        f"{exc}\n\nOpening original file instead."
                                    ),
                                )

            if project is None:
                try:
                    project = load_project(path)
                except ProjectUpgradeRequired:
                    choice = QMessageBox.question(
                        self,
                        "Convert Project",
                        (
                            "This project uses an older format.\n\n"
                            "Convert it to the new single-file .vaso format now?\n"
                            "A backup (.bak1) will be kept for safety."
                        ),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if choice != QMessageBox.Yes:
                        self.statusBar().showMessage("Conversion cancelled.", 5000)
                        self.hide_progress()
                        return
                    try:
                        from vasoanalyzer.core.project import convert_project

                        ctx = convert_project(path)
                        with contextlib.suppress(Exception):
                            ctx.close()
                        project = load_project(path)
                        self.statusBar().showMessage(
                            "\u2713 Project converted to single-file format.", 5000
                        )
                    except Exception as exc:
                        QMessageBox.critical(
                            self,
                            "Project Conversion Failed",
                            f"Could not convert project:\n{exc}",
                        )
                        self.hide_progress()
                        return
                except Exception as exc:
                    error_msg = str(exc)

                    # Check if this was a database corruption error
                    if "corrupted" in error_msg.lower() or "malformed" in error_msg.lower():
                        # Check if project is in cloud storage
                        from vasoanalyzer.core.project import _is_cloud_storage_path

                        is_cloud, cloud_service = _is_cloud_storage_path(path)

                        cloud_warning = ""
                        if is_cloud:
                            cloud_warning = (
                                f"\n\n⚠️ IMPORTANT: This project is stored in {cloud_service}.\n"
                                f"SQLite databases are INCOMPATIBLE with cloud storage and will become corrupted.\n\n"
                                f"To fix this:\n"
                                f"1. Move this project to a LOCAL folder (e.g., ~/Documents or ~/Desktop)\n"
                                f"2. Create a new project in the local folder\n"
                                f"3. Never store .vaso projects in iCloud, Dropbox, or other cloud storage\n\n"
                            )

                        if "backup was created" in error_msg:
                            # Recovery was attempted but failed
                            QMessageBox.critical(
                                self,
                                "Project Database Corrupted",
                                f"The project database is corrupted and automatic recovery failed.\n\n"
                                f"Error: {exc}"
                                f"{cloud_warning}\n"
                                f"A backup of your corrupted file has been created at:\n"
                                f"{path}.backup\n\n"
                                f"Recovery options:\n"
                                f"1. Try opening the backup file\n"
                                f"2. Contact support for manual recovery\n"
                                f"3. Create a new project and re-import your data",
                            )
                        else:
                            # Generic database error
                            QMessageBox.critical(
                                self,
                                "Project Database Error",
                                f"Could not open project due to database error:\n\n{exc}"
                                f"{cloud_warning}\n"
                                f"The database may be corrupted. Please check the file:\n{path}",
                            )
                    else:
                        # Other errors
                        QMessageBox.critical(
                            self,
                            "Project Load Error",
                            f"Could not open project:\n{exc}",
                        )
                    self.hide_progress()
                    return

        self.hide_progress()
        self._replace_current_project(project)
        self.apply_ui_state(getattr(self.current_project, "ui_state", None))
        self.refresh_project_tree()
        self.show_analysis_workspace()
        self._reveal_project_sidebar()

        status = f"\u2713 Project loaded: {self.current_project.name}"
        if restored_from_autosave:
            status += " (autosave recovered)"
        self.statusBar().showMessage(status, 5000)
        self._update_storage_mode_indicator(project_path, force_message=True)

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
            elif self.current_project.experiments and self.current_project.experiments[0].samples:
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

    def open_project_file(self, path: str | bool | None = None):
        """Open a project file.

        Args:
            path: Path to project file, or boolean from Qt signal (ignored), or None for file dialog
        """
        from vasoanalyzer.app.openers import open_project_file as _open_project_file

        # Ignore boolean argument from Qt signals (e.g., QAction.triggered)
        if isinstance(path, bool):
            path = None

        return _open_project_file(self, path)

    def _prepare_project_for_save(self) -> None:
        """Capture UI state into the project before dispatching a background save."""

        if not self.current_project:
            return

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        embed = settings.value("snapshots/embed_stacks", False, type=bool)
        self.current_project.embed_snapshots = bool(embed)

        self.current_project.ui_state = self.gather_ui_state()
        if self.current_sample:
            state = self.gather_sample_state()
            self.current_sample.ui_state = state
            self.project_state[id(self.current_sample)] = state
            # Persist change log so it survives across sessions
            change_log = getattr(self, "_change_log", None)
            if change_log is not None:
                self.current_sample.change_log = change_log.serialize()

    def _project_snapshot_for_save(self, project: Project) -> Project:
        """Create a lightweight snapshot of ``project`` suitable for background save."""

        snap = copy.copy(project)
        snap.resources = project_module.ProjectResources()
        snap._store = None  # Ensure thread-local store is opened inside the worker
        if hasattr(snap, "_store_cleanup_registered"):
            delattr(snap, "_store_cleanup_registered")
        return snap

    def _set_save_actions_enabled(self, enabled: bool) -> None:
        """Enable/disable save-related actions while a background save is running."""

        for action in (
            getattr(self, "action_save_project", None),
            getattr(self, "action_save_project_as", None),
            getattr(self, "save_session_action", None),
        ):
            if action is not None:
                action.setEnabled(enabled)

    def changeEvent(self, event):
        # Note: PaletteChange events are no longer handled since we don't follow OS theme.
        # Theme changes are controlled explicitly via View > Color Theme menu.
        super().changeEvent(event)

    def _status_bar_theme_colors(self) -> dict[str, str]:
        """Return palette-aware colors for status/progress widgets."""

        pal = self.palette()
        window = pal.color(QPalette.Window)
        text = pal.color(QPalette.WindowText)
        highlight = pal.color(QPalette.Highlight)

        is_dark = window.lightness() < 128
        status_bg = window.name()
        border = "#3a3a3a" if is_dark else "#c8c8c8"
        bar_bg = "#2a2a2a" if is_dark else "#e6e6e6"
        chunk = highlight.name() if highlight.isValid() else ("#4da3ff" if is_dark else "#2f7de1")
        text_color = text.name() if text.isValid() else ("#dcdcdc" if is_dark else "#202020")

        return {
            "status_bg": status_bg,
            "border": border,
            "bar_bg": bar_bg,
            "chunk": chunk,
            "text": text_color,
        }

    def _apply_status_bar_theme(self) -> None:
        """Apply palette-aware styling to status and progress bars."""

        colors = self._status_bar_theme_colors()
        status_style = (
            "QStatusBar {{ background: {status_bg}; border-top: 1px solid {border}; }} "
            "QStatusBar QLabel {{ color: {text}; }}"
        ).format(**colors)
        bar_style = (
            "QProgressBar {{ border: 1px solid {border}; border-radius: 3px; "
            "background: {bar_bg}; min-height: 16px; }} "
            "QProgressBar::chunk {{ background-color: {chunk}; }}"
        ).format(**colors)

        self.statusBar().setStyleSheet(status_style)
        self._progress_bar.setStyleSheet(bar_style)
        if hasattr(self, "_storage_mode_label"):
            self._storage_mode_label.setStyleSheet(
                f"color: {colors['text']}; padding: 0 8px; font-weight: 600;"
            )

    def _update_storage_mode_indicator(
        self, path: str | None, *, show_message: bool = True, force_message: bool = False
    ) -> None:
        """Update the status bar indicator showing storage mode."""

        if not hasattr(self, "_storage_mode_label"):
            return

        if not path:
            self._storage_mode_label.clear()
            self._storage_mode_label.setVisible(False)
            self._storage_mode_path = None
            self._storage_mode_is_cloud = None
            self._storage_mode_cloud_service = None
            return

        try:
            normalised = (
                Path(path).expanduser().resolve(strict=False).as_posix()
                if isinstance(path, str)
                else str(path)
            )
        except Exception:
            normalised = str(path)

        from vasoanalyzer.core.project import _is_cloud_storage_path

        is_cloud, cloud_service = _is_cloud_storage_path(normalised)
        mode_changed = (
            normalised != self._storage_mode_path
            or is_cloud != self._storage_mode_is_cloud
            or cloud_service != self._storage_mode_cloud_service
        )

        self._storage_mode_path = normalised
        self._storage_mode_is_cloud = is_cloud
        self._storage_mode_cloud_service = cloud_service

        if is_cloud:
            label = "Cloud-safe mode"
            if cloud_service:
                label += f" ({cloud_service})"
            tooltip = "DELETE journal + FULL sync for reliability on cloud storage."
            if show_message and (mode_changed or force_message):
                self.statusBar().showMessage("Using cloud-safe mode (slower but reliable)", 6000)
        else:
            label = "Fast mode (local)"
            tooltip = "WAL journal with NORMAL sync for local disks."
            # Avoid spamming the status bar for the common case

        self._storage_mode_label.setText(label)
        self._storage_mode_label.setToolTip(tooltip)
        self._storage_mode_label.setVisible(True)

    def _start_background_save(
        self,
        path: str | None,
        *,
        skip_optimize: bool,
        reason: str = "manual",
        mode: str = "manual",
        ctx: dict | None = None,
    ) -> None:
        """Dispatch a background save job using the thread pool."""

        project = self.current_project
        if project is None:
            return

        target_path = path or getattr(project, "path", None)
        if not target_path:
            self.statusBar().showMessage("No project path available to save.", 5000)
            return

        if self._save_in_progress:
            log.debug("Save already in progress, skipping concurrent save request")
            self.statusBar().showMessage("Save already in progress…", 3000)
            return

        if mode != "autosave":
            self._prepare_project_for_save()
        self._save_in_progress = True
        self._active_save_reason = reason
        self._active_save_path = target_path
        self._active_save_mode = mode
        self._last_save_error = None
        if mode != "autosave":
            self._set_save_actions_enabled(False)
        progress_label = "Autosaving project…" if mode == "autosave" else "Saving project…"
        self.show_progress(progress_label, maximum=100)

        if mode == "autosave":
            self._autosave_in_progress = True
            self._active_autosave_ctx = ctx or {}

        project_snapshot = self._project_snapshot_for_save(project)

        job = _SaveJob(
            project_snapshot,
            target_path,
            skip_optimize=skip_optimize,
            mode=mode,
        )
        job.signals.progressChanged.connect(self._on_save_progress_changed)
        job.signals.finished.connect(self._on_save_finished)
        job.signals.error.connect(self._on_save_error)
        self._thread_pool.start(job)
        log.info(
            "Background save started path=%s reason=%s mode=%s",
            target_path,
            reason,
            mode,
        )
        if mode == "autosave":
            log.debug(
                "Autosave scheduled ctx=%s current_sample_id=%s rev=%s",
                self._active_autosave_ctx,
                getattr(self.current_sample, "id", None),
                self._project_state_rev,
            )

    def _on_save_progress_changed(self, percent: int, message: str) -> None:
        """Update main progress bar from save worker signals."""
        if not self._progress_bar.isVisible():
            self.show_progress("", maximum=100)
        self._progress_bar.setValue(percent)
        self._progress_bar.setFormat(f"{message}... %p%")
        self.statusBar().showMessage(message)

    def _verify_saved_file(self, path: str, mode: str) -> None:
        """Check that a saved file exists and is non-empty. Show critical warning on failure."""
        if not path:
            return
        try:
            p = Path(path)
            if not p.exists():
                self._show_save_integrity_warning(path, "File does not exist after save")
                return
            size = p.stat().st_size
            if size == 0:
                self._show_save_integrity_warning(path, "File is empty (0 bytes) after save")
                return
            # For .vaso containers, verify ZIP structure
            if p.suffix.lower() == ".vaso" and p.is_file():
                import zipfile

                try:
                    with zipfile.ZipFile(p, "r") as zf:
                        if not zf.namelist():
                            self._show_save_integrity_warning(
                                path, "Project file contains no data"
                            )
                except zipfile.BadZipFile:
                    # Could be a legacy SQLite .vaso — not an error
                    pass
        except Exception as exc:
            log.warning("Post-save verification error: %s", exc, exc_info=True)

    def _show_save_integrity_warning(self, path: str, detail: str) -> None:
        """Show a critical dialog when saved file integrity check fails."""
        log.critical("SAVE INTEGRITY FAILURE: %s — %s", path, detail)
        QMessageBox.critical(
            self,
            "Save Verification Failed",
            f"<b>Your project may not have saved correctly.</b>\n\n"
            f"<b>Problem:</b> {detail}\n"
            f"<b>File:</b> {path}\n\n"
            f"<b>What to do:</b>\n"
            f"• Do NOT close the application — your data is still in memory\n"
            f"• Use <b>File → Save As</b> to save to a different location\n"
            f"• If this keeps happening, please report the issue",
        )

    def _on_save_error(self, details: str) -> None:
        self._last_save_error = details
        mode = self._active_save_mode or "manual"
        prefix = "Autosave" if mode == "autosave" else "Save"
        log.error("Error during project %s: %s", mode, details)
        if mode == "autosave":
            self._autosave_in_progress = False
            self._active_autosave_ctx = None
        else:
            # Show a blocking dialog for manual save failures so the user can't miss it
            QMessageBox.warning(
                self,
                f"{prefix} Failed",
                f"<b>Your project could not be saved.</b>\n\n"
                f"{details}\n\n"
                f"Your data is still in memory. Try <b>File → Save As</b> to "
                f"save to a different location.",
            )
        self.statusBar().showMessage(f"{prefix} failed: {details}", 5000)

    def _on_save_finished(self, ok: bool, duration_sec: float, path: str) -> None:
        resolved_path = (
            path or self._active_save_path or getattr(self.current_project, "path", None)
        )
        reason = self._active_save_reason or "manual"
        mode = self._active_save_mode or "manual"

        if ok:
            log.info(
                "Background save completed path=%s reason=%s mode=%s duration=%.2fs",
                resolved_path,
                reason,
                mode,
                duration_sec,
            )
            # Verify saved file integrity
            if resolved_path:
                self._verify_saved_file(resolved_path, mode)
            if self.current_project and reason == "save_as" and resolved_path:
                self.current_project.path = resolved_path
            if mode == "autosave":
                if resolved_path:
                    self.last_autosave_path = resolved_path
                message = (
                    f"Project saved: {Path(resolved_path).name} ({duration_sec:.2f}s)"
                    if resolved_path
                    else "Project saved"
                )
                self.statusBar().showMessage(message, 2500)
            else:
                if resolved_path:
                    self.update_recent_projects(resolved_path)
                    self._update_storage_mode_indicator(resolved_path)
                message = (
                    f"Project saved: {Path(resolved_path).name} ({duration_sec:.2f}s)"
                    if resolved_path
                    else "Project saved"
                )
                self.statusBar().showMessage(message, 2500)
                reset_reason = (
                    "manual save" if reason in ("manual", "save_as") else f"{reason} save"
                )
                self._reset_session_dirty(reason=reset_reason)
                self._update_window_title()
            self.hide_progress()
        else:
            log.error(
                "Background save failed path=%s reason=%s mode=%s duration=%.2fs",
                resolved_path,
                reason,
                mode,
                duration_sec,
            )
            message = f"Save failed: {Path(resolved_path).name}" if resolved_path else "Save failed"
            if self._last_save_error:
                message = f"{message} — {self._last_save_error}"
            message = f"{message} ({duration_sec:.2f}s)"
            self.statusBar().showMessage(message, 5000)
            self.hide_progress()

        if mode == "autosave":
            log.debug(
                "Autosave finished ok=%s ctx=%s live_sample_id=%s rev_now=%s",
                ok,
                self._active_autosave_ctx,
                getattr(self.current_sample, "id", None),
                self._project_state_rev,
            )
            self._autosave_in_progress = False
            self._active_autosave_ctx = None
        self._active_save_reason = None
        self._active_save_path = None
        self._active_save_mode = None
        self._last_save_error = None
        self._set_save_actions_enabled(True)
        self._save_in_progress = False

    def save_project_file(self, checked: bool = False):
        """Save the current project file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if self.current_project and self.current_project.path:
            project_path = self.current_project.path
            log.info("Manual save requested path=%s", project_path)
            self._start_background_save(project_path, skip_optimize=False, reason="manual")
        elif self.current_project:
            self.save_project_file_as()

    def save_project_file_as(self, checked: bool = False):
        """Save project to a new file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if not self.current_project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            self.current_project.path or "",
            "Vaso Projects (*.vaso)",
        )
        if not path:
            return

        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vaso":
            path_obj = path_obj.with_suffix(".vaso")
        path = str(path_obj.resolve(strict=False))

        # Check if user is trying to save to cloud storage
        from vasoanalyzer.core.project import _is_cloud_storage_path

        is_cloud, cloud_service = _is_cloud_storage_path(path)
        if is_cloud:
            reply = QMessageBox.warning(
                self,
                "Cloud Storage - Known Limitation",
                f"<b>You are saving to {cloud_service}</b>\n\n"
                f"<b>Technical Limitation:</b>\n"
                f"SQLite databases (like .vaso project files) can become corrupted when cloud sync services"
                f"upload the file mid-transaction. This happens because the sync daemon may interrupt "
                f"database writes, breaking integrity.\n\n"
                f"<b>Mitigations in place:</b>\n"
                f"• VasoAnalyzer uses WAL mode for better resilience\n"
                f"• Automatic recovery attempts if corruption occurs\n"
                f"• Risk is highest during active editing and autosaves\n\n"
                f"<b>Best practice:</b>\n"
                f"Store active projects locally (~/Documents, ~/Desktop), then copy .vaso "
                f"files to cloud storage for backup and sharing.\n\n"
                f"<b>Continue saving to {cloud_service}?</b>",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        log.info("Manual save (Save As) requested destination=%s", path)
        self._start_background_save(path, skip_optimize=False, reason="save_as")

    def export_project_bundle_action(self, checked: bool = False):
        """Export project as a shareable .vaso file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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
            Path(self.current_project.path).with_name(f"{default_stem}.vaso").as_posix()
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project Bundle",
            default_path,
            "Vaso Projects (*.vaso)",
        )
        if not path:
            return
        path_obj = Path(path).expanduser()
        if path_obj.suffix.lower() != ".vaso":
            path_obj = path_obj.with_suffix(".vaso")
        path = str(path_obj.resolve(strict=False))

        self.current_project.ui_state = self.gather_ui_state()
        if self.current_sample:
            state = self.gather_sample_state()
            self.current_sample.ui_state = state
            self.project_state[id(self.current_sample)] = state

        try:
            self.show_progress("Exporting bundle…", maximum=0)
            export_project_bundle(self.current_project, path)
            self.hide_progress()
            self.statusBar().showMessage(f"\u2713 Bundle saved: {path}", 5000)
        except Exception as exc:
            self.hide_progress()
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export bundle:\n{exc}",
            )

    def export_shareable_project(self, checked: bool = False):
        """Export a DELETE-mode single-file copy of the current project.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """

        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before exporting."
            )
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        # Ensure latest edits are flushed before exporting.
        self.save_project_file()
        if not self.current_project or not self.current_project.path:
            return

        stem = Path(self.current_project.path).with_suffix("").name
        default_path = (
            Path(self.current_project.path).with_name(f"{stem}.shareable.vaso").as_posix()
        )
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Shareable Project",
            default_path,
            "Vaso Projects (*.vaso)",
        )
        if not dest:
            return

        dest_path = Path(dest).expanduser()
        if dest_path.suffix.lower() != ".vaso":
            dest_path = dest_path.with_suffix(".vaso")
        dest_path = dest_path.resolve(strict=False)

        try:
            self.show_progress("Exporting shareable project…", maximum=0)
            exported = export_project_single_file(
                self.current_project,
                destination=dest_path.as_posix(),
                ensure_saved=False,
            )
        except Exception as exc:
            self.hide_progress()
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Could not export shareable project:\n{exc}",
            )
            return

        self.hide_progress()
        self.statusBar().showMessage(f"\u2713 Shareable project saved: {exported}", 5000)

    def export_dataset_package_action(self, checked: bool = False):
        """Export the currently selected dataset to a .vasods package."""

        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before exporting a dataset."
            )
            return

        if not self.current_sample:
            QMessageBox.information(self, "No Dataset Selected", "Select a dataset to export.")
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        dataset_id = getattr(self.current_sample, "dataset_id", None)
        if dataset_id is None:
            # Ensure dataset exists on disk
            self.save_project_file()
            dataset_id = getattr(self.current_sample, "dataset_id", None)

        if dataset_id is None:
            QMessageBox.warning(
                self,
                "Export Blocked",
                "Save the project once before exporting this dataset.",
            )
            return

        sample_name = self.current_sample.name or "Dataset"
        default_path = Path(self.current_project.path).with_name(f"{sample_name}.vasods").as_posix()
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Dataset Package",
            default_path,
            "Dataset Packages (*.vasods)",
        )
        if not dest:
            return

        dest_path = Path(dest).expanduser()
        if dest_path.suffix.lower() != ".vasods":
            dest_path = dest_path.with_suffix(".vasods")
        dest_path = dest_path.resolve(strict=False)

        try:
            export_dataset_package(self.current_project.path, dataset_id, dest_path)
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(self, "Export Failed", f"Dataset export failed:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", f"Could not export dataset:\n{exc}")
            return

        self.statusBar().showMessage(f"\u2713 Dataset exported: {dest_path}", 5000)

    def import_dataset_from_project_action(self, checked: bool = False):
        """Import dataset(s) from another project without leaving the current window."""

        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before importing."
            )
            return
        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        dest_experiments = [
            (exp.name, getattr(exp, "experiment_id", None))
            for exp in self.current_project.experiments
        ] or [("Default", None)]
        initial_preserve = settings.value(
            "import_from_project_preserve_experiments", False, type=bool
        )
        initial_dest_id = settings.value(
            "import_from_project_last_dest_experiment_id", None, type=str
        )
        dialog = SourceProjectBrowserDialog(
            self,
            current_project_path=self.current_project.path,
            current_experiments=dest_experiments,
            initial_preserve=initial_preserve,
            initial_dest_experiment_id=initial_dest_id,
        )
        source_path, dataset_entries, dest_exp, preserve, dest_exp_id = dialog.exec_with_source()
        if not source_path or not dataset_entries:
            return

        # Ensure destination is saved before mutation
        self.save_project_file()

        imported_ids: list[int] = []
        dest_expanded = set()
        plan = build_import_plan(dataset_entries, dest_exp, preserve)
        failures: list[tuple[str, str, str]] = []
        root_temp_dir = tempfile.mkdtemp(prefix="vasods_import_")
        try:
            for entry, target_exp in plan:
                pkg_path = Path(root_temp_dir) / f"dataset_{entry.dataset_id}.vasods"
                try:
                    export_dataset_package(source_path, entry.dataset_id, pkg_path)
                    new_id = import_dataset_package(
                        self.current_project.path,
                        pkg_path,
                        target_experiment_name=target_exp,
                    )
                    imported_ids.append(int(new_id))
                    if target_exp:
                        dest_expanded.add(target_exp)
                except Exception as exc:
                    failures.append((entry.dataset_name, entry.experiment_name, str(exc)))
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(self, "Import Failed", f"Dataset package is invalid:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not import dataset:\n{exc}")
            return
        finally:
            try:
                shutil.rmtree(root_temp_dir, ignore_errors=True)
            except Exception:
                log.debug("Failed to remove temp import dir %s", root_temp_dir, exc_info=True)

        if not imported_ids:
            if failures:
                details = "\n".join(f"- {name} ({exp}): {err}" for name, exp, err in failures)
                QMessageBox.critical(
                    self,
                    "Import Failed",
                    f"No datasets were imported.\n\nErrors:\n{details}",
                )
            return

        # Reload project to reflect new datasets and select the first imported one
        self.open_project_file(self.current_project.path)
        if dest_expanded:
            for name in dest_expanded:
                self._expand_experiment_in_tree(name)
        self._select_dataset_ids(imported_ids)
        self.statusBar().showMessage(
            f"\u2713 Imported {len(imported_ids)} dataset(s) from {Path(source_path).name}", 5000
        )
        # Persist user choices
        settings.setValue("import_from_project_preserve_experiments", bool(preserve))
        if dest_exp_id:
            settings.setValue("import_from_project_last_dest_experiment_id", dest_exp_id)
        elif dest_exp and not preserve:
            # Fall back to name if no id available
            settings.setValue("import_from_project_last_dest_experiment_id", dest_exp)

        if failures:
            detail = "\n".join(f"- {name} ({exp}): {err}" for name, exp, err in failures)
            msg = QMessageBox(self)
            msg.setWindowTitle("Import Partial")
            msg.setText(
                f"Imported {len(imported_ids)} dataset(s) from {Path(source_path).name}.\n"
                f"Failed {len(failures)} dataset(s)."
            )
            msg.setInformativeText("You can copy the details for support.")
            copy_btn = msg.addButton("Copy details", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.setDetailedText(detail)
            msg.exec_()
            if msg.clickedButton() is copy_btn:
                QApplication.clipboard().setText(detail)

    def _prompt_experiment_for_import(self, default_name: str | None) -> str | None:
        experiments = [
            exp.name for exp in getattr(self.current_project, "experiments", []) or [] if exp.name
        ]
        if default_name and default_name not in experiments:
            experiments.insert(0, default_name)
        if not experiments:
            experiments = ["Imported"]
        current_index = 0
        if default_name and default_name in experiments:
            current_index = experiments.index(default_name)
        selection, ok = QInputDialog.getItem(
            self,
            "Choose Experiment",
            "Import dataset into experiment:",
            experiments,
            current_index,
            True,
        )
        if not ok:
            return None
        selected = str(selection).strip()
        return selected or None

    def import_dataset_package_action(self, checked: bool = False):
        """Import a .vasods package into the current project."""

        if not self.current_project:
            QMessageBox.information(
                self, "No Project", "Open or create a project before importing."
            )
            return

        if not self.current_project.path:
            self.save_project_file_as()
            if not self.current_project or not self.current_project.path:
                return

        pkg_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Dataset Package",
            "",
            "Dataset Packages (*.vasods)",
        )
        if not pkg_path:
            return

        default_exp = None
        if getattr(self, "current_experiment", None):
            default_exp = self.current_experiment.name
        elif getattr(self.current_project, "experiments", None):
            default_exp = self.current_project.experiments[0].name

        target_exp = self._prompt_experiment_for_import(default_exp)
        if not target_exp:
            return

        # Flush current edits before mutating the project file
        self.save_project_file()

        try:
            import_dataset_package(
                self.current_project.path,
                pkg_path,
                target_experiment_name=target_exp,
            )
        except DatasetPackageValidationError as exc:
            QMessageBox.warning(self, "Import Failed", f"Dataset package is invalid:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not import dataset:\n{exc}")
            return

        # Reload project to reflect the new dataset
        self.open_project_file(self.current_project.path)
        self.statusBar().showMessage(f"\u2713 Dataset imported into '{target_exp}'", 5000)

    # Clipboard-based copy/paste of datasets --------------------------------
    def _gather_selected_samples_for_copy(self) -> list[SampleN]:
        samples = self._selected_samples_from_tree()
        if not samples and getattr(self, "current_sample", None):
            samples = [self.current_sample]
        return [s for s in samples if getattr(s, "dataset_id", None) is not None]

    def copy_selected_datasets(self) -> None:
        """Copy selected datasets to a temp .vasods set and place paths on clipboard."""

        if not self.current_project or not self.current_project.path:
            QMessageBox.information(
                self, "No Project", "Open or save a project before copying datasets."
            )
            return

        samples = self._gather_selected_samples_for_copy()
        if not samples:
            QMessageBox.information(self, "No Dataset", "Select a dataset to copy.")
            return

        # Ensure datasets are saved before exporting
        self.save_project_file()

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        preserve = settings.value("import_from_project_preserve_experiments", True, type=bool)

        root_temp_dir = tempfile.mkdtemp(prefix="vasods_clip_")
        payload_entries = []
        try:
            for sample in samples:
                ds_id = getattr(sample, "dataset_id", None)
                if ds_id is None:
                    continue
                pkg_path = Path(root_temp_dir) / f"dataset_{ds_id}.vasods"
                export_dataset_package(self.current_project.path, ds_id, pkg_path)
                payload_entries.append(
                    {
                        "path": pkg_path.as_posix(),
                        "dataset_id": ds_id,
                        "dataset_name": sample.name or f"Dataset {ds_id}",
                        "experiment": self._experiment_name_for_sample(sample),
                    }
                )
        except Exception:
            shutil.rmtree(root_temp_dir, ignore_errors=True)
            raise

        if not payload_entries:
            shutil.rmtree(root_temp_dir, ignore_errors=True)
            QMessageBox.warning(self, "Copy Failed", "No datasets were copied.")
            return

        payload = {
            "version": 1,
            "preserve": bool(preserve),
            "source_project": self.current_project.path,
            "temp_dir": root_temp_dir,
            "entries": payload_entries,
        }
        mime_data_json = _json.dumps(payload)
        mime = QMimeData()
        mime.setData(_CLIP_MIME, mime_data_json.encode("utf-8"))
        mime.setText(mime_data_json)
        QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage(
            f"\u2713 Copied {len(payload_entries)} dataset(s) to clipboard", 4000
        )

    def paste_datasets(self) -> None:
        """Paste datasets from clipboard into the current project."""

        if not self.current_project or not self.current_project.path:
            QMessageBox.information(
                self, "No Project", "Open or save a project before pasting datasets."
            )
            return

        mime = QApplication.clipboard().mimeData()
        raw = None
        if mime and mime.hasFormat(_CLIP_MIME):
            raw = bytes(mime.data(_CLIP_MIME)).decode("utf-8", errors="ignore")
        elif mime and mime.hasText():
            raw = mime.text()
        if not raw:
            QMessageBox.information(self, "Nothing to Paste", "Clipboard has no datasets.")
            return
        try:
            payload = _json.loads(raw)
        except Exception:
            QMessageBox.warning(self, "Paste Failed", "Clipboard data is not valid.")
            return

        entries = payload.get("entries") or []
        if not isinstance(entries, list) or not entries:
            QMessageBox.information(self, "Nothing to Paste", "Clipboard has no datasets.")
            return

        preserve = bool(payload.get("preserve", True))
        temp_dir = payload.get("temp_dir")
        imported_ids: list[int] = []
        dest_expanded = set()
        failures: list[tuple[str, str]] = []

        dest_exp = getattr(self, "current_experiment", None)
        dest_name = dest_exp.name if dest_exp else None

        self.save_project_file()

        try:
            for entry in entries:
                pkg_path = entry.get("path")
                if not pkg_path or not Path(pkg_path).exists():
                    failures.append((entry.get("dataset_name") or "Dataset", "Package missing"))
                    continue
                source_exp = entry.get("experiment")
                target_exp = source_exp if preserve else dest_name
                if not target_exp:
                    target_exp = source_exp or dest_name or "Imported"
                try:
                    new_id = import_dataset_package(
                        self.current_project.path,
                        pkg_path,
                        target_experiment_name=target_exp,
                    )
                    imported_ids.append(int(new_id))
                    if target_exp:
                        dest_expanded.add(target_exp)
                except Exception as exc:
                    failures.append((entry.get("dataset_name") or "Dataset", str(exc)))
        finally:
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    log.debug("Failed to remove clipboard temp dir %s", temp_dir, exc_info=True)

        if not imported_ids and failures:
            detail = "\n".join(f"- {name}: {err}" for name, err in failures)
            QMessageBox.critical(
                self,
                "Paste Failed",
                f"No datasets were pasted.\n\nErrors:\n{detail}",
            )
            return

        if imported_ids:
            self.open_project_file(self.current_project.path)
            if dest_expanded:
                for name in dest_expanded:
                    self._expand_experiment_in_tree(name)
            self._select_dataset_ids(imported_ids)
            self.statusBar().showMessage(
                f"\u2713 Pasted {len(imported_ids)} dataset(s) from clipboard", 4000
            )
        if failures:
            detail = "\n".join(f"- {name}: {err}" for name, err in failures)
            msg = QMessageBox(self)
            msg.setWindowTitle("Paste Partial")
            msg.setText(f"Pasted {len(imported_ids)} dataset(s); {len(failures)} failed.")
            msg.setInformativeText("You can copy the details for support.")
            copy_btn = msg.addButton("Copy details", QMessageBox.ActionRole)
            msg.addButton(QMessageBox.Ok)
            msg.setDetailedText(detail)
            msg.exec_()
            if msg.clickedButton() is copy_btn:
                QApplication.clipboard().setText(detail)

    def _run_deferred_autosave(self):
        reason = self._pending_autosave_reason or "deferred"
        self._pending_autosave_reason = None
        log.info(
            "Autosave: running deferred autosave reason=%s path=%s",
            reason,
            getattr(self.current_project, "path", None),
        )
        if self.current_project and self.current_project.path:
            ctx = self._pending_autosave_ctx or {}
            self.auto_save_project(reason=reason, ctx=ctx)

    def request_deferred_autosave(self, delay_ms: int = 2000, *, reason: str = "deferred") -> None:
        """Schedule an autosave after ``delay_ms`` to coalesce rapid edits."""

        if not self.current_project or not self.current_project.path:
            self._pending_autosave_reason = None
            self._deferred_autosave_timer.stop()
            return

        self._bump_project_state_rev(f"autosave scheduled ({reason})")
        ctx = {
            "rev": self._project_state_rev,
            "sample_id": getattr(self.current_sample, "id", None),
            "reason": reason,
            "utc": datetime.utcnow().isoformat() + "Z",
        }
        self._pending_autosave_ctx = ctx
        self._pending_autosave_reason = reason
        self._deferred_autosave_timer.start(max(0, int(delay_ms)))

    def auto_save_project(self, reason: str | None = None, ctx: dict | None = None):
        """Write an autosave snapshot when a project is available."""

        self._deferred_autosave_timer.stop()
        self._pending_autosave_reason = None
        if ctx is None and self._pending_autosave_ctx:
            ctx = self._pending_autosave_ctx

        if not self.current_project or not self.current_project.path:
            return

        project_path = self.current_project.path
        # Prevent concurrent saves (don't autosave if manual save is in progress)
        if self._save_in_progress:
            log.info(
                "Manual save in progress, deferring autosave path=%s reason=%s",
                project_path,
                reason or "auto",
            )
            # Reschedule autosave for later
            self.request_deferred_autosave(delay_ms=5000, reason=reason or "deferred")
            return

        log.info("Autosave started path=%s reason=%s", project_path, reason or "auto")
        self._start_background_save(
            path=None,
            skip_optimize=True,
            reason=reason or "auto",
            mode="autosave",
            ctx=ctx,
        )

    def _autosave_tick(self):
        if not self.current_project or not self.current_project.path:
            return
        if not self.session_dirty:
            return
        ctx = {
            "rev": self._project_state_rev,
            "sample_id": getattr(self.current_sample, "id", None),
            "reason": "timer",
            "utc": datetime.utcnow().isoformat() + "Z",
        }
        self._pending_autosave_ctx = ctx
        self.auto_save_project(reason="timer", ctx=ctx)

    def _bump_project_state_rev(self, reason: str) -> None:
        self._project_state_rev += 1
        log.debug("Project state rev bumped to %s (%s)", self._project_state_rev, reason)

    def _persist_sample_ui_state(self, sample: SampleN, state: dict) -> None:
        """Persist UI state for a specific sample without relying on current selection."""

        if sample is None:
            return
        sample.ui_state = state
        self.project_state[id(sample)] = state

    def _get_sample_data_quality(self, sample: SampleN) -> str | None:
        """Read the stored data-quality flag from a sample's UI state."""
        state = getattr(sample, "ui_state", None)
        if isinstance(state, dict):
            value = state.get("data_quality")
            if value in {"good", "questionable", "bad"}:
                return value
        return None

    def _data_quality_label(self, quality: str | None) -> str:
        labels = {
            "good": "Good data",
            "questionable": "Questionable data",
            "bad": "Bad data",
        }
        return labels.get(quality, "No decision")

    def _data_quality_icon(self, quality: str | None) -> QIcon:
        """Return a color-coded icon for dataset quality."""
        icon_map = {
            "good": "green.svg",
            "questionable": "yellow.svg",
            "bad": "red.svg",
        }
        if quality not in self._data_quality_icons:
            filename = icon_map.get(quality)
            if filename:
                self._data_quality_icons[quality] = QIcon(self.icon_path(filename))
            else:
                self._data_quality_icons[quality] = self.style().standardIcon(QStyle.SP_FileIcon)
        return self._data_quality_icons[quality]

    def _update_tree_icons_for_samples(self, samples: Sequence[SampleN]) -> None:
        if not self.project_tree:
            return
        for sample in samples:
            found = False
            for i in range(self.project_tree.topLevelItemCount()):
                project_item = self.project_tree.topLevelItem(i)
                if project_item is None:
                    continue
                for j in range(project_item.childCount()):
                    exp_item = project_item.child(j)
                    if exp_item is None:
                        continue
                    for k in range(exp_item.childCount()):
                        sample_item = exp_item.child(k)
                        if sample_item is None:
                            continue
                        if sample_item.data(0, Qt.UserRole) is sample:
                            quality = self._get_sample_data_quality(sample)
                            sample_item.setIcon(0, self._data_quality_icon(quality))
                            sample_item.setToolTip(
                                0,
                                f"Data quality: {self._data_quality_label(quality)}",
                            )
                            found = True
                            break
                    if found:
                        break
                if found:
                    break

    def refresh_project_tree(self):
        if not self.project_tree:
            return

        # Capture current expand/collapse state for each experiment before clearing
        expanded_state: dict[str, bool] = {}
        for i in range(self.project_tree.topLevelItemCount()):
            project_item = self.project_tree.topLevelItem(i)
            if project_item is None:
                continue
            for j in range(project_item.childCount()):
                exp_item = project_item.child(j)
                if exp_item is None:
                    continue
                obj = exp_item.data(0, Qt.UserRole)
                exp_name = getattr(obj, "name", None) or exp_item.text(0)
                expanded_state[exp_name] = exp_item.isExpanded()

        # Also seed from persisted project ui_state (for first load after a save)
        if self.current_project and isinstance(self.current_project.ui_state, dict):
            for exp_name, is_expanded in self.current_project.ui_state.get(
                "experiment_expanded", {}
            ).items():
                if exp_name not in expanded_state:
                    expanded_state[exp_name] = is_expanded

        self.project_tree.clear()
        if not self.current_project:
            return
        root = QTreeWidgetItem([self.current_project.name])
        root.setData(0, Qt.UserRole, self.current_project)
        root.setFlags(root.flags() | Qt.ItemIsEditable)
        root.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
        root.setData(0, Qt.FontRole, self._bold_font(size_delta=2))
        self.project_tree.addTopLevelItem(root)
        for exp in self.current_project.experiments:
            exp_item = QTreeWidgetItem([exp.name])
            exp_item.setData(0, Qt.UserRole, exp)
            exp_item.setFlags(exp_item.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
            exp_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileDialogListView))
            exp_item.setData(0, Qt.FontRole, self._bold_font(size_delta=1))
            root.addChild(exp_item)
            samples = sorted(
                exp.samples,
                key=lambda sample: (sample.name or "").lower(),
            )
            for s in samples:
                has_data = bool(
                    s.trace_path or s.trace_data is not None or s.dataset_id is not None
                )
                status = "✓" if has_data else "✗"
                quality = self._get_sample_data_quality(s)
                item = QTreeWidgetItem([f"{s.name} {status}"])
                item.setData(0, Qt.UserRole, s)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setIcon(0, self._data_quality_icon(quality))
                item.setToolTip(
                    0,
                    f"Data quality: {self._data_quality_label(quality)}",
                )
                exp_item.addChild(item)
            # Restore expand state; default to expanded for experiments seen for the first time
            exp_item.setExpanded(expanded_state.get(exp.name, True))
        root.setExpanded(True)
        self._update_metadata_panel(self.current_project)
        self._schedule_missing_asset_scan()
        if self.current_sample:
            self._select_tree_item_for_sample(self.current_sample)

    def _on_tree_experiment_expand_changed(self, item) -> None:
        """Persist experiment expand/collapse state to project.ui_state."""
        obj = item.data(0, Qt.UserRole)
        if not isinstance(obj, Experiment) or not self.current_project:
            return
        if not isinstance(self.current_project.ui_state, dict):
            self.current_project.ui_state = {}
        exp_expanded = self.current_project.ui_state.setdefault("experiment_expanded", {})
        exp_expanded[obj.name] = item.isExpanded()

    def _on_experiment_reordered(self) -> None:
        """Sync Project.experiments to the tree order after a drag-drop reorder."""
        if not self.current_project or not self.project_tree:
            return
        new_order: list[Experiment] = []
        for i in range(self.project_tree.topLevelItemCount()):
            root = self.project_tree.topLevelItem(i)
            for j in range(root.childCount()):
                exp_item = root.child(j)
                obj = exp_item.data(0, Qt.UserRole)
                if isinstance(obj, Experiment):
                    new_order.append(obj)
        if new_order:
            self.current_project.experiments = new_order
            self.mark_session_dirty("experiment_reordered")

    def _set_samples_data_quality(self, samples: Sequence[SampleN], quality: str | None) -> None:
        if not samples:
            return
        changed = False
        for sample in samples:
            if not isinstance(sample.ui_state, dict):
                sample.ui_state = {}
            previous = sample.ui_state.get("data_quality")
            if quality is None:
                if sample.ui_state.pop("data_quality", None) is not None:
                    changed = True
            elif previous != quality:
                sample.ui_state["data_quality"] = quality
                changed = True
            self.project_state[id(sample)] = sample.ui_state
        if changed:
            self._update_tree_icons_for_samples(samples)
            self.mark_session_dirty(reason="sample data quality updated")

    def _select_dataset_ids(self, dataset_ids: Sequence[int]) -> None:
        if not dataset_ids or not self.current_project:
            return
        target_set = {int(d) for d in dataset_ids if d is not None}
        for exp in self.current_project.experiments:
            for sample in exp.samples:
                if getattr(sample, "dataset_id", None) in target_set:
                    self.load_sample_into_view(sample)
                    self._select_tree_item_for_sample(sample)
                    return

    def _expand_experiment_in_tree(self, exp_name: str) -> None:
        if not self.project_tree:
            return
        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)
            if project_item is None:
                continue
            for j in range(project_item.childCount()):
                exp_item = project_item.child(j)
                if exp_item is None:
                    continue
                if exp_item.text(0) == exp_name:
                    tree.expandItem(project_item)
                    tree.expandItem(exp_item)
                    return

    def _select_tree_item_for_sample(self, sample: SampleN | None) -> None:
        if sample is None or not self.project_tree:
            return

        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            project_item = tree.topLevelItem(i)
            if project_item is None:
                continue
            for j in range(project_item.childCount()):
                exp_item = project_item.child(j)
                if exp_item is None:
                    continue
                for k in range(exp_item.childCount()):
                    sample_item = exp_item.child(k)
                    if sample_item is None:
                        continue
                    item_sample = sample_item.data(0, Qt.UserRole)
                    if item_sample is sample:
                        tree.blockSignals(True)
                        tree.setCurrentItem(sample_item)
                        tree.blockSignals(False)
                        tree.scrollToItem(sample_item)
                        return

    def _selected_samples_from_tree(self) -> list[SampleN]:
        if not self.project_tree:
            return []
        samples: list[SampleN] = []
        for item in self.project_tree.selectedItems() or []:
            obj = item.data(0, Qt.UserRole)
            if isinstance(obj, SampleN) and obj not in samples:
                samples.append(obj)
        return samples

    def _experiment_name_for_sample(self, sample: SampleN) -> str | None:
        if not self.current_project:
            return None
        for exp in self.current_project.experiments:
            if sample in exp.samples:
                return exp.name
        return None

    def _open_first_sample_if_none_active(self) -> None:
        if self.current_project is None:
            return
        if getattr(self, "current_sample", None) is not None:
            return

        first_sample: SampleN | None = None
        for exp in self.current_project.experiments:
            if not exp.samples:
                continue
            candidates = sorted(exp.samples, key=lambda s: (s.name or "").lower())
            if candidates:
                first_sample = candidates[0]
                break

        if first_sample is None:
            return

        self.load_sample_into_view(first_sample)
        self._select_tree_item_for_sample(first_sample)

    def _schedule_missing_asset_scan(self) -> None:
        if self.current_project is None or not getattr(self.current_project, "experiments", None):
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
        if snapshot != self._last_missing_assets_snapshot and (sample_assets or project_messages):
            self._report_missing_assets(sample_assets, project_messages)
            self._last_missing_assets_snapshot = snapshot

    def _on_missing_asset_scan_error(self, token: object, message: str) -> None:
        if token != self._pending_asset_scan_token:
            return
        self._pending_asset_scan_token = None
        log.debug("Missing asset scan failed: %s", message)

    def _report_missing_assets(
        self,
        sample_assets: list[MissingAsset],
        project_messages: list[str],
    ) -> None:
        entries: list[str] = []
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
        log.warning(
            "Some linked resources could not be found. Use Tools → Relink Missing Files… if needed.\n%s",
            summary,
        )
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(
                "Some linked files are missing (see Relink Missing Files…)",
                5000,
            )

    def on_tree_item_clicked(self, item, _):
        obj = item.data(0, Qt.UserRole)

        # Debug: Log all clicks
        if isinstance(obj, tuple) and len(obj) >= 1:
            log.info(f"Single-clicked tree item: {obj[0]} (tuple with {len(obj)} elements)")

        if isinstance(obj, SampleN):
            # When Ctrl or Shift is held the user is building a multi-selection.
            # Skip activation so the tree can accumulate selections without
            # refresh_project_tree clearing them.
            modifiers = QApplication.keyboardModifiers()
            if modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
                return

            experiment = None
            parent = item.parent()
            if parent:
                parent_obj = parent.data(0, Qt.UserRole)
                if isinstance(parent_obj, Experiment):
                    experiment = parent_obj
            self._activate_sample(obj, experiment)
            # Metadata panel is updated in _render_sample, no need to update here
            return
        if isinstance(obj, Experiment):
            self.current_experiment = obj
            self.current_sample = None
            if self.current_project is not None:
                if not isinstance(self.current_project.ui_state, dict):
                    self.current_project.ui_state = {}
                self.current_project.ui_state["last_experiment"] = obj.name
                self.current_project.ui_state.pop("last_sample", None)
                self.current_project.ui_state.pop("last_dataset_id", None)
            self._update_metadata_panel(obj)
            return
        self._update_metadata_panel(obj)

    def on_tree_item_double_clicked(self, item, column):
        """Handle double-click on tree items - open figures."""
        obj = item.data(0, Qt.UserRole)
        log.info(f"Double-clicked tree item, obj type: {type(obj)}, obj: {obj}")

    def _activate_sample(
        self,
        sample: SampleN,
        experiment: Experiment | None,
        *,
        ensure_loaded: bool = False,
    ) -> None:
        log.info(
            "UI: sample selected -> %s (dataset_id=%s) trace_data=%s events_data=%s",
            getattr(sample, "name", "<unknown>"),
            getattr(sample, "dataset_id", None),
            isinstance(getattr(sample, "trace_data", None), pd.DataFrame),
            isinstance(getattr(sample, "events_data", None), pd.DataFrame),
        )
        if self.current_sample and self.current_sample is not sample:
            state = self.gather_sample_state()
            if self._autosave_in_progress:
                log.debug(
                    "Autosave in progress; deferring persistence of sample state id=%s",
                    getattr(self.current_sample, "id", None),
                )
                self._cached_sample_state = state
            else:
                self._persist_sample_ui_state(self.current_sample, state)
        need_load = ensure_loaded or (self.current_sample is not sample)
        self.current_sample = sample
        self.current_experiment = experiment
        if need_load or self.trace_model is None:
            self.load_sample_into_view(sample)

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
                obj.trace_path or obj.trace_data is not None or obj.dataset_id is not None
            )
            status = "\u2713" if has_data else "\u2717"
            self.project_tree.blockSignals(True)
            item.setText(0, f"{name} {status}")
            self.project_tree.blockSignals(False)
        elif isinstance(obj, Experiment | Project):
            obj.name = name

    def on_tree_item_double_clicked(self, item, _):
        """Handle tree double-click (sample)."""
        obj = item.data(0, Qt.UserRole)
        if isinstance(obj, SampleN):
            self.load_sample_into_view(obj)
            return

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

    def _resolve_attachment_path(self, att: Attachment) -> str | None:
        for candidate in (att.data_path, att.source_path):
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _queue_sample_load_until_context(self, sample: SampleN) -> bool:
        """Defer sample loading until a ProjectContext is available."""
        if sample.dataset_id is None:
            return False
        self._pending_sample_loads[sample.dataset_id] = sample
        log.debug(
            "Deferring load for '%s' (dataset_id=%s) until ProjectContext is ready",
            sample.name,
            sample.dataset_id,
        )
        return True

    def _flush_pending_sample_loads(self) -> None:
        """Retry any deferred sample loads once the ProjectContext is ready."""
        if not self._pending_sample_loads or self._processing_pending_sample_loads:
            return
        self._processing_pending_sample_loads = True
        try:
            pending_samples = list(self._pending_sample_loads.values())
            self._pending_sample_loads.clear()
            for sample in pending_samples:
                try:
                    self.load_sample_into_view(sample)
                except Exception:
                    log.warning(
                        "Deferred load failed for sample '%s'",
                        sample.name,
                        exc_info=True,
                    )
        finally:
            self._processing_pending_sample_loads = False

    def _log_sample_data_summary(
        self,
        sample: SampleN,
        trace_df: pd.DataFrame | None = None,
        events_df: pd.DataFrame | None = None,
    ) -> None:
        """Emit a concise INFO log summarising the trace/events payload being shown."""

        if getattr(self, "_sample_summary_logged", False):
            return

        sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
        dataset_id = getattr(sample, "dataset_id", None)

        trace_source = (
            trace_df if isinstance(trace_df, pd.DataFrame) else getattr(sample, "trace_data", None)
        )
        if not isinstance(trace_source, pd.DataFrame):
            return

        events_source = events_df
        if events_source is None:
            events_source = getattr(sample, "events_data", None)

        if isinstance(events_source, pd.DataFrame):
            event_rows = len(events_source.index)
            first_event = (
                events_source.iloc[0]["Event"]
                if not events_source.empty and "Event" in events_source.columns
                else None
            )
            log.info(
                "DEBUG load: sample '%s' events_data rows=%s first_label=%r",
                sample_name,
                event_rows,
                first_event,
            )
        elif events_source is None:
            event_rows = 0
        else:
            try:
                event_rows = len(events_source)
            except TypeError:
                event_rows = 0
            log.info(
                "DEBUG load: sample '%s' events_source type=%s rows=%s",
                sample_name,
                type(events_source),
                event_rows,
            )

        self._sample_summary_logged = True

        log.info(
            "UI: Loading sample %s (dataset_id=%s) trace_rows=%d trace_columns=%s events_rows=%d",
            sample_name,
            dataset_id,
            len(trace_source.index),
            list(trace_source.columns),
            event_rows,
        )

    def load_sample_into_view(self, sample: SampleN):
        """Load a sample's trace and events into the main view."""
        t0 = time.perf_counter()
        try:
            log.debug("Loading sample %s", sample.name)

            if self.current_sample and self.current_sample is not sample:
                state = self.gather_sample_state()
                self.current_sample.ui_state = state
                self.project_state[id(self.current_sample)] = state
                # Persist change log before switching away
                self.current_sample.change_log = self._change_log.serialize()

            self.current_sample = sample
            self._sample_summary_logged = False
            self._last_track_layout_sample_id = None
            self._select_tree_item_for_sample(sample)

            token = object()
            self._current_sample_token = token

            # Validate cache - check if cached data belongs to current dataset_id
            # If a dataset was just loaded and the cache id never set, adopt the current dataset_id
            if (
                sample.trace_data is not None
                and getattr(sample, "_trace_cache_dataset_id", None) is None
            ):
                sample._trace_cache_dataset_id = sample.dataset_id
            if (
                sample.events_data is not None
                and getattr(sample, "_events_cache_dataset_id", None) is None
            ):
                sample._events_cache_dataset_id = sample.dataset_id

            trace_cache_valid = (
                sample.trace_data is not None
                and getattr(sample, "_trace_cache_dataset_id", None) == sample.dataset_id
            )
            events_cache_valid = (
                sample.events_data is not None
                and getattr(sample, "_events_cache_dataset_id", None) == sample.dataset_id
            )

            # Invalidate stale cache
            if sample.trace_data is not None and not trace_cache_valid:
                log.warning(
                    "CACHE_INVALID: trace cache for '%s' invalid (dataset_id=%s, cached_id=%s), clearing",
                    sample.name,
                    sample.dataset_id,
                    getattr(sample, "_trace_cache_dataset_id", None),
                )
                sample.trace_data = None
                sample._trace_cache_dataset_id = None

            if sample.events_data is not None and not events_cache_valid:
                log.warning(
                    "CACHE_INVALID: events cache for '%s' invalid (dataset_id=%s, cached_id=%s), clearing",
                    sample.name,
                    sample.dataset_id,
                    getattr(sample, "_events_cache_dataset_id", None),
                )
                sample.events_data = None
                sample._events_cache_dataset_id = None

            needs_trace = sample.trace_data is None and sample.dataset_id is not None
            needs_events = sample.events_data is None and sample.dataset_id is not None
            needs_results = (
                sample.analysis_results is None
                and sample.dataset_id is not None
                and (sample.analysis_result_keys is None or bool(sample.analysis_result_keys))
            )

            # Prevent duplicate loads for the same dataset
            if (
                sample.dataset_id is not None
                and sample.dataset_id in self._loading_dataset_ids
                and (needs_trace or needs_events or needs_results)
            ):
                log.info(
                    "DATASET_LOAD_SKIP: dataset_id=%s already loading, skipping duplicate load request",
                    sample.dataset_id,
                )
                return

            ctx = getattr(self, "project_ctx", None)
            log.debug("load_sample_into_view: ctx type=%s ctx=%s", type(ctx), ctx)

            project_path = (
                ctx.path
                if isinstance(ctx, ProjectContext)
                else getattr(self.current_project, "path", None)
            )
            repo = ctx.repo if isinstance(ctx, ProjectContext) else None

            # Extract staging DB path for thread-safe access
            staging_db_path: str | None = None
            if repo is not None:
                try:
                    # Try to get staging path from the store's handle
                    store = getattr(repo, "_store", None)
                    if store is not None:
                        handle = getattr(store, "handle", None)
                        if handle is not None:
                            staging_path = getattr(handle, "staging_path", None)
                            if staging_path is not None:
                                staging_db_path = str(staging_path)
                                log.debug(
                                    "Extracted staging DB path for thread-safe access: %s",
                                    staging_db_path,
                                )
                except Exception as e:
                    log.warning(f"Could not extract staging DB path: {e}")
            # Fallback: extract staging DB path directly from project._store when ctx is None.
            # This is the common case during an import session — project_ctx is not set but
            # _save_project_bundle already opened and attached a staging DB to the project.
            if staging_db_path is None and self.current_project is not None:
                try:
                    project_store = getattr(self.current_project, "_store", None)
                    if project_store is not None:
                        handle = getattr(project_store, "handle", None)
                        if handle is not None:
                            staging_path = getattr(handle, "staging_path", None)
                            if staging_path is not None:
                                staging_db_path = str(staging_path)
                                log.debug(
                                    "Extracted staging DB path from project._store: %s",
                                    staging_db_path,
                                )
                except Exception as e:
                    log.debug("Could not extract staging DB path from project._store: %s", e)

            log.debug(
                "load_sample_into_view: repo=%s project_path=%s needs_events=%s dataset_id=%s",
                repo,
                project_path,
                needs_events,
                sample.dataset_id,
            )

            # CRITICAL: If repo is None but we have a project context, something is wrong
            if repo is None and ctx is not None:
                log.warning("Repo is None but project context exists: %s", ctx)
            if repo is None and project_path and sample.dataset_id is not None:
                log.debug(
                    "No repo from project_ctx for '%s'; background job will open project context",
                    sample.name,
                )
            if repo is None and staging_db_path is None and project_path and needs_events:
                log.warning(
                    "Background job will create a NEW project context which means a NEW staging database; "
                    "events may not be found."
                )

            load_async = bool(
                (repo or project_path) and (needs_trace or needs_events or needs_results)
            )
            force_sync = os.environ.get("VA_FORCE_SYNC_LOAD", "0") == "1"
            if force_sync:
                if load_async:
                    log.info(
                        "VA_FORCE_SYNC_LOAD=1: forcing synchronous dataset load for sample '%s'",
                        sample.name,
                    )
                load_async = False

            log.info(
                "DATASET_LOAD: sample='%s' dataset_id=%s cached=(trace=%s, events=%s) "
                "needs=(trace=%s, events=%s, results=%s) load_async=%s",
                sample.name,
                sample.dataset_id,
                sample.trace_data is not None,
                sample.events_data is not None,
                needs_trace,
                needs_events,
                needs_results,
                load_async,
            )

            self._start_sample_load_progress(sample.name)
            self._prepare_sample_view(sample)

            if load_async:
                # Mark this dataset as loading
                if sample.dataset_id is not None:
                    self._loading_dataset_ids.add(sample.dataset_id)
                    log.debug(
                        "DATASET_LOAD_START: dataset_id=%s added to in-flight set",
                        sample.dataset_id,
                    )

                self.statusBar().showMessage(f"Loading {sample.name}…", 2000)
                self._begin_sample_load_job(
                    sample,
                    token,
                    repo,
                    project_path,
                    load_trace=needs_trace,
                    load_events=needs_events,
                    load_results=needs_results,
                    staging_db_path=staging_db_path,
                )
                return

            self._log_sample_data_summary(sample)
            self._render_sample(sample)
            self._finish_sample_load_progress()

        finally:
            log.debug("load_sample_into_view completed in %.3f s", time.perf_counter() - t0)

    def _prepare_sample_view(self, sample: SampleN) -> None:
        log.debug(
            "DATASET_PREPARE: sample='%s' clearing canvas + event table for load",
            sample.name,
        )
        self.show_analysis_workspace()
        self._reset_event_table_for_loading()
        # Clear the plot/canvas to avoid stale visuals while loading.
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
        self._refresh_trace_navigation_data()
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(None)
        if self.scope_dock:
            self.scope_dock.set_trace_model(None)
        self.canvas.draw_idle()

        # Clear snapshot UI
        self.snapshot_frames = []
        self.frames_metadata = []
        self._set_playback_state(False)
        self.toggle_snapshot_viewer(False, source="data")
        if self.snapshot_widget is not None:
            self.snapshot_widget.hide()
            self.snapshot_widget.clear()
        self._reset_snapshot_speed()
        self.metadata_details_label.setText("No metadata available.")
        self._clear_event_highlight()
        self._clear_pins()
        self._layout_log_ready = False
        self._last_tiff_page_time_warning_key = None
        self._update_plot_empty_state()

    def _reset_event_table_for_loading(self) -> None:
        """Clear event table state to avoid stale selections during dataset switches."""
        self._event_table_updating = True
        self._suppress_event_table_sync = True
        try:
            self._set_event_table_enabled(False)
            event_table = getattr(self, "event_table", None)
            selection = event_table.selectionModel() if event_table is not None else None
            if selection is not None:
                selection.blockSignals(True)
                selection.clearSelection()
                selection.blockSignals(False)

            controller = getattr(self, "event_table_controller", None)
            if controller is not None:
                controller.clear()
            else:
                self.event_table_data = []
                self._sync_event_data_from_table()
                self._update_event_table_presence_state(False)
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
                with contextlib.suppress(Exception):
                    plot_host.set_selected_event_index(None)
            self._clear_event_highlight()
        finally:
            self._event_table_updating = False
            self._suppress_event_table_sync = False

    def _set_event_table_enabled(self, enabled: bool) -> None:
        event_table = getattr(self, "event_table", None)
        if event_table is not None:
            event_table.setEnabled(bool(enabled))

    def _begin_sample_load_job(
        self,
        sample: SampleN,
        token: object,
        repo: ProjectRepository | None,
        project_path: str | None,
        *,
        load_trace: bool,
        load_events: bool,
        load_results: bool,
        staging_db_path: str | None = None,
    ) -> None:
        job = _SampleLoadJob(
            repo,
            project_path,
            sample,
            token,
            load_trace=load_trace,
            load_events=load_events,
            load_results=load_results,
            staging_db_path=staging_db_path,
        )
        job.signals.finished.connect(self._on_sample_load_finished)
        job.signals.error.connect(self._on_sample_load_error)
        job.signals.progressChanged.connect(self._update_sample_load_progress)
        self._thread_pool.start(job)

    def _on_sample_load_finished(
        self,
        token: object,
        sample: SampleN,
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
        analysis_results: dict[str, Any] | None,
    ) -> None:
        # Remove from in-flight tracking
        if sample.dataset_id is not None:
            self._loading_dataset_ids.discard(sample.dataset_id)
            log.debug(
                "DATASET_LOAD_FINISH: dataset_id=%s removed from in-flight set",
                sample.dataset_id,
            )

        if token != self._current_sample_token or sample is not self.current_sample:
            log.warning(
                "DATASET_LOAD_DISCARDED: sample='%s' dataset_id=%s reason=%s current_sample='%s'",
                sample.name,
                sample.dataset_id,
                ("token_mismatch" if token != self._current_sample_token else "sample_changed"),
                getattr(self.current_sample, "name", None),
            )
            # Clear any partial cache from this discarded load to prevent corruption
            # Only clear if this sample is NOT the current sample (we switched away)
            if sample is not self.current_sample:
                if trace_df is not None and sample.trace_data is None:
                    log.debug("DATASET_LOAD_DISCARDED: clearing partial trace cache")
                if events_df is not None and sample.events_data is None:
                    log.debug("DATASET_LOAD_DISCARDED: clearing partial events cache")
                # Note: We don't set sample.trace_data/events_data here because
                # the data might be useful if user switches back. Cache validation
                # will handle correctness on next load.
            return
        t0 = time.perf_counter()
        if trace_df is not None:
            sample.trace_data = trace_df
            sample._trace_cache_dataset_id = sample.dataset_id
        if events_df is not None:
            sample.events_data = events_df
            sample._events_cache_dataset_id = sample.dataset_id
        if analysis_results:
            sample.analysis_results = analysis_results
            sample.analysis_result_keys = list(analysis_results.keys())
        elif sample.analysis_result_keys is None:
            sample.analysis_result_keys = []

        trace_data = trace_df if trace_df is not None else sample.trace_data
        events_data = events_df if events_df is not None else sample.events_data

        if trace_data is None:
            log.warning(
                "Sample load finished without trace data for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )
            self._finish_sample_load_progress()
            return
        if events_data is None:
            log.info(
                "Sample load finished without events for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )

        self._log_sample_data_summary(sample, trace_data, events_data)
        log.info(
            "UI: _on_sample_load_finished resolved data for %s (dataset_id=%s); calling _render_sample",
            getattr(sample, "name", "<unknown>"),
            getattr(sample, "dataset_id", None),
        )
        self.statusBar().showMessage(f"{sample.name} ready", 2000)
        self._render_sample(sample)
        self._finish_sample_load_progress()
        log.info(
            "Timing: sample '%s' render pipeline finished in %.2f ms",
            getattr(sample, "name", "<unknown>"),
            (time.perf_counter() - t0) * 1000,
        )

    def _on_sample_load_error(self, token: object, sample: SampleN, message: str) -> None:
        # Remove from in-flight tracking
        if sample.dataset_id is not None:
            self._loading_dataset_ids.discard(sample.dataset_id)
            log.debug(
                "DATASET_LOAD_ERROR: dataset_id=%s removed from in-flight set",
                sample.dataset_id,
            )

        if token != self._current_sample_token or sample is not self.current_sample:
            return
        log.warning("Embedded data load failed for %s: %s", sample.name, message)
        self.statusBar().showMessage(
            f"Embedded data not available ({message})",
            6000,
        )
        self._render_sample(sample)
        self._finish_sample_load_progress()

    def _render_sample(self, sample: SampleN) -> None:
        # Restore change log for this sample
        self._change_log.clear()
        saved_log = getattr(sample, "change_log", None)
        if isinstance(saved_log, list):
            self._change_log.load(saved_log)
        # Also import any existing edit_history entries not yet in the change log
        self._change_log.merge_edit_history(getattr(sample, "edit_history", None))

        # Prevent review prompts from firing during intermediate sample rendering steps.
        self._suppress_review_prompt = True
        try:
            log.info(
                "UI: _render_sample called for %s (dataset_id=%s)",
                getattr(sample, "name", "<unknown>"),
                getattr(sample, "dataset_id", None),
            )
            style = None
            if isinstance(sample.ui_state, dict):
                style = sample.ui_state.get("style_settings") or sample.ui_state.get("plot_style")
            merged_style = {**DEFAULT_STYLE, **style} if style else DEFAULT_STYLE.copy()
            self._style_holder = _StyleHolder(merged_style.copy())
            self._style_manager.replace(merged_style)

            cache: DataCache | None = None
            try:
                trace_source = None
                if sample.trace_data is not None:
                    trace = sample.trace_data
                    # For embedded datasets, avoid touching external paths (may be on iCloud)
                    if getattr(sample, "dataset_id", None) is not None:
                        trace_source = sample.name
                    else:
                        trace_source = sample.trace_path or sample.name
                elif sample.trace_path and sample.dataset_id is None:
                    resolved_trace = self._resolve_sample_link(sample, "trace")
                    if not resolved_trace or not Path(resolved_trace).exists():
                        raise FileNotFoundError(str(sample.trace_path))
                    cache = self._ensure_data_cache(resolved_trace)
                    trace = load_trace(resolved_trace, cache=cache)
                    sample.trace_path = resolved_trace
                    self._clear_missing_asset(sample, "trace")
                    self.trace_file_path = resolved_trace
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
                display_name = (
                    os.path.basename(trace_source)
                    if isinstance(trace_source, str)
                    else str(trace_source)
                )
                prefix = "Sample"
                tooltip = (
                    sample.name if getattr(sample, "dataset_id", None) is not None else trace_source
                )
                # Only probe filesystem when not embedded
                if (
                    isinstance(trace_source, str)
                    and getattr(sample, "dataset_id", None) is None
                    and os.path.exists(trace_source)
                ):
                    prefix = "Trace"
                    self.trace_file_path = trace_source
                else:
                    self.trace_file_path = None
                self._set_status_source(f"{prefix} · {display_name}", tooltip)
            else:
                self._set_status_source(f"Sample · {sample.name}", sample.name)
                self.trace_file_path = None
            self._reset_session_dirty()

            labels, times, frames, diam, od = [], [], [], [], []
            try:
                # If events are embedded in the repo but not materialised on the sample, fetch them now.
                if sample.events_data is None and sample.dataset_id is not None:
                    repo_ctx = getattr(self, "project_ctx", None)
                    repo = repo_ctx.repo if isinstance(repo_ctx, ProjectContext) else None
                    get_events = getattr(repo, "get_events", None)
                    if callable(get_events):
                        with contextlib.suppress(Exception):
                            sample.events_data = project_module._format_events_df(
                                get_events(sample.dataset_id)  # type: ignore[arg-type]
                            )

                if sample.events_data is not None:
                    labels, times, frames = load_events(sample.events_data)
                    self._clear_missing_asset(sample, "events")
                elif sample.events_path and sample.dataset_id is None:
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
                    # Extract stored OD/ID from the events DataFrame as fallback
                    # when the trace has NaN at the event time (e.g. legacy files
                    # with sparse inner-diameter measurements).
                    stored_id: list[float | None] = []
                    stored_od: list[float | None] = []
                    ev_df = sample.events_data if sample.events_data is not None else None
                    if ev_df is not None and isinstance(ev_df, pd.DataFrame):
                        for col_name, out_list in (
                            ("id_diam", stored_id),
                            ("od", stored_od),
                        ):
                            if col_name in ev_df.columns:
                                for val in ev_df[col_name]:
                                    try:
                                        fv = float(val)
                                        out_list.append(fv if np.isfinite(fv) else None)
                                    except (TypeError, ValueError):
                                        out_list.append(None)
                            else:
                                out_list.extend([None] * len(times))
                    else:
                        stored_id = [None] * len(times)
                        stored_od = [None] * len(times)

                    for i, t in enumerate(times):
                        idx_evt = int(np.argmin(np.abs(arr_t - t)))
                        id_val = float(arr_d[idx_evt])
                        if not np.isfinite(id_val) and i < len(stored_id) and stored_id[i] is not None:
                            id_val = stored_id[i]
                        diam.append(id_val)
                        if arr_od is not None:
                            od_val = float(arr_od[idx_evt])
                            if not np.isfinite(od_val) and i < len(stored_od) and stored_od[i] is not None:
                                od_val = stored_od[i]
                            od.append(od_val)
                        elif i < len(stored_od) and stored_od[i] is not None:
                            od.append(stored_od[i])
            except FileNotFoundError as exc:
                missing = getattr(exc, "filename", None) or sample.events_path
                self._handle_missing_asset(sample, "events", missing, str(exc))
            except Exception as error:
                QMessageBox.warning(self, "Event Load Error", str(error))

            # Batch all plot updates to avoid multiple redraws during sample rendering
            plot_host = getattr(self, "plot_host", None)
            # Suspending/resuming updates can block in some render backends (e.g., pyqtgraph).
            # Only do it for backends that support fast suspend, and measure the resume cost.
            suspend_updates = False
            if plot_host is not None:
                try:
                    backend = plot_host.get_render_backend()
                    suspend_updates = backend != "pyqtgraph"
                except Exception:
                    suspend_updates = False
            if suspend_updates:
                plot_host.suspend_updates()

            try:
                self.trace_data = self._prepare_trace_dataframe(trace)
                self._update_trace_sync_state()
                self._layout_log_ready = True
                self._reset_channel_view_defaults()
                self.xlim_full = None
                self.ylim_full = None
                self.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)
                self.compute_frame_trace_indices()
                t_ev = time.perf_counter()
                self.load_project_events(
                    labels,
                    times,
                    frames,
                    diam,
                    od,
                    refresh_plot=False,
                    auto_export=True,
                )
                log.info(
                    "Timing: load_project_events for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_ev) * 1000,
                )
                t_plot = time.perf_counter()
                self.update_plot()
                self._apply_event_label_mode()
                self._sync_event_controls()
                self._update_trace_controls_state()
                log.info(
                    "Timing: update_plot for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_plot) * 1000,
                )
                state_to_apply = self.project_state.get(
                    id(sample), getattr(sample, "ui_state", None)
                )
                t_state = time.perf_counter()
                self.apply_sample_state(state_to_apply)
                log.info(
                    "Timing: apply_sample_state for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_state) * 1000,
                )
                if (
                    self._plot_host_is_pyqtgraph()
                    and plot_host is not None
                    and hasattr(plot_host, "log_data_and_view_ranges")
                ):
                    plot_host.log_data_and_view_ranges("after_sample_render")

                t_after = time.perf_counter()
                if self.current_project is not None:
                    if not isinstance(self.current_project.ui_state, dict):
                        self.current_project.ui_state = {}
                    if self.current_experiment:
                        self.current_project.ui_state["last_experiment"] = (
                            self.current_experiment.name
                        )
                    self.current_project.ui_state["last_sample"] = sample.name
                    if getattr(sample, "dataset_id", None) is not None:
                        self.current_project.ui_state["last_dataset_id"] = int(sample.dataset_id)

                self._sync_autoscale_y_action_from_host()
                self._update_snapshot_viewer_state(sample)
                self._update_gif_animator_state()
                self._update_home_resume_button()
                self._update_metadata_panel(sample)
                log.info(
                    "Timing: post-plot UI updates for '%s' took %.2f ms",
                    getattr(sample, "name", "<unknown>"),
                    (time.perf_counter() - t_after) * 1000,
                )
            finally:
                # Always resume updates even if there was an error
                if suspend_updates and plot_host is not None:
                    t_resume = time.perf_counter()
                    plot_host.resume_updates()
                    log.info(
                        "Timing: plot_host.resume_updates for '%s' took %.2f ms",
                        getattr(sample, "name", "<unknown>"),
                        (time.perf_counter() - t_resume) * 1000,
                    )
        finally:
            self._suppress_review_prompt = False
            self._update_review_notice_visibility()
            self._update_plot_empty_state()
            self._set_event_table_enabled(self.trace_data is not None)

    def _update_snapshot_viewer_state(self, sample: SampleN) -> None:
        if self._snapshot_panel_disabled_by_env:
            if self.snapshot_viewer_action:
                self.snapshot_viewer_action.setEnabled(False)
                self.snapshot_viewer_action.blockSignals(True)
                self.snapshot_viewer_action.setChecked(False)
                self.snapshot_viewer_action.blockSignals(False)
            return
        has_stack = isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
        asset_available = bool(
            sample.snapshot_role and sample.asset_roles.get(sample.snapshot_role)
        )
        path_available = bool(sample.snapshot_path)
        should_enable = has_stack or asset_available or path_available
        desired_visibility = self._pending_snapshot_visibility
        if desired_visibility is not None:
            self._pending_snapshot_visibility = None

        if self.snapshot_viewer_action:
            self.snapshot_viewer_action.setEnabled(should_enable)
            if not should_enable:
                self.snapshot_viewer_action.blockSignals(True)
                self.snapshot_viewer_action.setChecked(False)
                self.snapshot_viewer_action.blockSignals(False)
                self.snapshot_frames = []
                self.frames_metadata = []
                self.frame_times = []
                self._set_playback_state(False)
                if self.snapshot_widget is not None:
                    self.snapshot_widget.clear()
                self.toggle_snapshot_viewer(False, source="data")

        if has_stack:
            try:
                self.load_snapshots(sample.snapshots)
            except Exception:
                self.toggle_snapshot_viewer(False, source="data")
                return

        if desired_visibility is None:
            if has_stack:
                self.toggle_snapshot_viewer(True, source="data")
            return

        self.toggle_snapshot_viewer(bool(desired_visibility), source="restore")

    def _ensure_sample_snapshots_loaded(self, sample: SampleN) -> np.ndarray | None:
        if isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0:
            return sample.snapshots

        if self._snapshot_load_token is not None and self._snapshot_loading_sample is sample:
            return None

        project_path = getattr(self.current_project, "path", None)
        asset_id = None
        if sample.snapshot_role and sample.asset_roles:
            asset_id = sample.asset_roles.get(sample.snapshot_role)

        token = object()
        self._snapshot_load_token = token
        self._snapshot_loading_sample = sample

        job = _SnapshotLoadJob(
            sample=sample,
            token=token,
            project_path=project_path,
            asset_id=asset_id,
            snapshot_path=sample.snapshot_path,
            snapshot_format=sample.snapshot_format,
        )
        job.signals.progressChanged.connect(self._update_sample_load_progress)
        job.signals.finished.connect(self._on_snapshot_load_finished)
        self.statusBar().showMessage("Loading snapshots…", 0)
        self._thread_pool.start(job)
        return None

    def _on_snapshot_load_finished(
        self,
        token: object,
        sample: SampleN,
        stack: np.ndarray | None,
        error: str | None,
    ) -> None:
        if token != self._snapshot_load_token or sample is not self._snapshot_loading_sample:
            return

        self._snapshot_load_token = None
        self._snapshot_loading_sample = None
        if stack is not None:
            sample.snapshots = stack
            self.statusBar().showMessage("Snapshots ready", 2000)
            if sample is self.current_sample:
                should_show = bool(
                    self._snapshot_viewer_pending_open
                    or (self.snapshot_viewer_action and self.snapshot_viewer_action.isChecked())
                )
                if should_show:
                    try:
                        self.load_snapshots(stack)
                        self._snapshot_viewer_pending_open = False
                        self.toggle_snapshot_viewer(True, source="data")
                    except Exception:
                        log.error("Failed to initialise snapshot viewer", exc_info=True)
                        self.snapshot_frames = []
                        self.toggle_snapshot_viewer(False, source="data")
                # Update GIF Animator state after snapshots are loaded
                self._update_gif_animator_state()
        else:
            self._snapshot_viewer_pending_open = False
            message = error or "Snapshot load failed"
            self.statusBar().showMessage(message, 6000)
            self.toggle_snapshot_viewer(False, source="data")

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

    def _open_samples_in_dual_view_legacy(self, samples):
        """Display two samples stacked vertically in a single window."""
        if len(samples) != 2:
            QMessageBox.warning(self, "Dual View", "Please select exactly two datasets.")
            return

        class DualViewWindow(QMainWindow):
            def __init__(self, parent, pair):
                super().__init__(parent)
                self.setWindowTitle("Dual View")
                self.views = []
                self._syncing = False
                self._cursor_guides = []
                self._pin_signatures: list[tuple[float, ...]] = []

                splitter = QSplitter(Qt.Vertical, self)

                parent_style = (
                    parent.get_current_plot_style() if parent is not None else DEFAULT_STYLE.copy()
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
                self.delta_label = QLabel("Δ metrics: add ≥2 inner-diameter pins in each view")
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
                primary = view.ax.axvline(view.ax.get_xlim()[0], color=color, alpha=0.35)
                primary.set_linestyle("--")
                primary.set_visible(False)
                secondary = None
                if view.ax2 is not None:
                    secondary = view.ax2.axvline(view.ax2.get_xlim()[0], color=color, alpha=0.25)
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
                        with contextlib.suppress(Exception):
                            target.update_scroll_slider()
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
                for guides, target in zip(self._cursor_guides, self.views, strict=False):
                    guides["primary"].set_xdata((x, x))
                    guides["primary"].set_visible(True)
                    if guides["secondary"] is not None:
                        guides["secondary"].set_xdata((x, x))
                        guides["secondary"].set_visible(True)
                    target.canvas.draw_idle()

                self._update_cursor_label(x)

            def _hide_cursor(self) -> None:
                for guides, view in zip(self._cursor_guides, self.views, strict=False):
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

                def _pin_x(marker) -> float | None:
                    try:
                        if hasattr(marker, "get_xdata"):
                            return float(marker.get_xdata()[0])
                        getter = getattr(marker, "getData", None)
                        if callable(getter):
                            xdata, _ydata = getter()
                            if xdata is not None and len(xdata) > 0:
                                return float(xdata[0])
                    except Exception:
                        return None
                    return None

                for idx, view in enumerate(self.views):
                    pins = tuple(
                        sorted(
                            round(px, 4)
                            for marker, _ in view.pinned_points
                            for px in [_pin_x(marker)]
                            if px is not None and getattr(marker, "trace_type", "inner") == "inner"
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
                    self.delta_label.setText("Δ metrics: add ≥2 inner-diameter pins in each view")
                    return

                delta_baseline = metrics[0]["baseline"] - metrics[1]["baseline"]
                delta_peak = metrics[0]["peak"] - metrics[1]["peak"]
                delta_auc = metrics[0]["auc"] - metrics[1]["auc"]
                window = metrics[0]["start"], metrics[0]["end"]

                self.delta_label.setText(
                    f"Window {window[0]:.2f}–{window[1]:.2f} s · "
                    f"Δbaseline {delta_baseline:+.2f} µm | "
                    f"Δpeak {delta_peak:+.2f} µm | "
                    f"ΔAUC {delta_auc:+.2f} µm·s"
                )

        self.dual_window = DualViewWindow(self, samples)
        self.dual_window.show()

    def open_samples_in_dual_view(self, samples):
        from vasoanalyzer.app.openers import (
            open_samples_in_dual_view as _open_dual_view,
        )

        return _open_dual_view(self, samples)

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
            open_act = menu.addAction("Open Selected Datasets…")
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
            add_n = menu.addAction("Add Sample")
            import_folder = menu.addAction("Import Folder…")
            del_exp = menu.addAction("Delete Experiment")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == add_n:
                self.add_sample(obj)
            elif action == import_folder:
                self._handle_import_folder(target_experiment=obj)
            elif action == del_exp:
                self.delete_experiment(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, SampleN):
            load_data = menu.addAction("Load Data Into N…")
            save_n = menu.addAction("Save Data As…")
            _del_targets = selected_samples if len(selected_samples) > 1 else [obj]
            _del_label = (
                f"Delete {len(_del_targets)} Datasets"
                if len(_del_targets) > 1
                else "Delete Data"
            )
            del_n = menu.addAction(_del_label)
            quality_menu = menu.addMenu("Mark Data Quality")
            quality_clear = quality_menu.addAction(
                self._data_quality_icon(None), "No decision (white)"
            )
            quality_good = quality_menu.addAction(
                self._data_quality_icon("good"), "Good data (green)"
            )
            quality_questionable = quality_menu.addAction(
                self._data_quality_icon("questionable"), "Questionable data (yellow)"
            )
            quality_bad = quality_menu.addAction(self._data_quality_icon("bad"), "Bad data (red)")
            action = menu.exec_(self.project_tree.viewport().mapToGlobal(pos))
            if action == load_data:
                self.load_data_into_sample(obj)
            elif action == save_n:
                self.save_sample_as(obj)
            elif action == del_n:
                self.delete_samples(_del_targets)
            elif action in {
                quality_clear,
                quality_good,
                quality_questionable,
                quality_bad,
            }:
                target_samples = selected_samples or [obj]
                quality_value = {
                    quality_clear: None,
                    quality_good: "good",
                    quality_questionable: "questionable",
                    quality_bad: "bad",
                }.get(action)
                self._set_samples_data_quality(target_samples, quality_value)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)

    def add_experiment(self, checked: bool = False):
        """Add a new experiment to the current project.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if not self.current_project:
            return
        name, ok = QInputDialog.getText(self, "Experiment Name", "Name:")
        if ok and name:
            exp = Experiment(name=name)
            self.current_project.experiments.append(exp)
            self.current_experiment = exp
            self.refresh_project_tree()

    def delete_experiment(self, experiment: Experiment) -> None:
        if not self.current_project or experiment not in self.current_project.experiments:
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

    def add_sample_to_current_experiment(self, checked: bool = False):
        """Add a sample to the current experiment.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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
        log.debug("Loading data into sample: %s", sample.name)
        trace_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not trace_path:
            return

        log.debug("Reading trace file: %s", Path(trace_path).name)
        try:
            df = self.load_trace_and_event_files(trace_path)
            log.debug("Loaded %d trace samples for manual update", len(df))
        except Exception as e:
            log.error(f"  ✗ Failed to load trace data: {e}")
            return

        trace_obj = Path(trace_path).expanduser().resolve(strict=False)
        self._update_sample_link_metadata(sample, "trace", trace_obj)
        sample.trace_data = df
        event_path = find_matching_event_file(trace_path)
        if event_path and os.path.exists(event_path):
            event_obj = Path(event_path).expanduser().resolve(strict=False)
            self._update_sample_link_metadata(sample, "events", event_obj)
            log.debug("Found matching event file: %s", Path(event_path).name)

        self.refresh_project_tree()

        log.debug("Sample '%s' updated successfully", sample.name)

        if self.current_project and self.current_project.path:
            save_project(self.current_project, self.current_project.path)

    def _handle_import_folder(self, target_experiment=None):
        """Handle the Import Folder action.

        Args:
            target_experiment: Target experiment or boolean from Qt signal (ignored if boolean)
        """
        from vasoanalyzer.services.folder_import_service import scan_folder_with_status
        from vasoanalyzer.ui.dialogs.folder_import_dialog import FolderImportDialog

        # Ignore boolean argument from Qt signals
        if isinstance(target_experiment, bool):
            target_experiment = None

        log.info(
            "IMPORT: user triggered import folder into experiment target=%s",
            getattr(target_experiment, "name", None) if target_experiment else "<none>",
        )

        # Determine target experiment
        if target_experiment is None:
            target_experiment = self.current_experiment

        if target_experiment is None:
            QMessageBox.warning(
                self,
                "No Experiment Selected",
                "Please select an experiment before importing a folder.",
            )
            return

        # Prompt for folder selection
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Import",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )

        if not folder_path:
            return

        log.info(
            "IMPORT: folder chooser accepted path=%s target_experiment=%s",
            folder_path,
            getattr(target_experiment, "name", None),
        )

        # Scan folder for trace files
        try:
            log.info(
                "IMPORT: scanning folder for candidates path=%s experiment=%s",
                folder_path,
                getattr(target_experiment, "name", None),
            )
            candidates = scan_folder_with_status(folder_path, target_experiment)
            log.info(
                "IMPORT: scan complete path=%s candidates=%d",
                folder_path,
                len(candidates),
            )
            log.debug(
                "IMPORT: candidate preview entries=%s",
                [(c.subfolder, c.status) for c in candidates],
            )
            log.info(
                "IMPORT: Folder import found %d sample candidates in %s",
                len(candidates),
                folder_path,
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Scan Error",
                f"Failed to scan folder:\n{e}",
            )
            log.exception("Error scanning folder: %s", folder_path)
            return

        if not candidates:
            QMessageBox.information(
                self,
                "No Files Found",
                "No trace files were found in the selected folder or its subfolders.",
            )
            return

        # Show preview dialog
        dialog = FolderImportDialog(candidates, self)
        if dialog.exec_() != QDialog.Accepted:
            log.info("IMPORT: folder import dialog canceled path=%s", folder_path)
            return

        selected = dialog.selected_candidates
        if not selected:
            log.info(
                "IMPORT: folder import dialog accepted with no selections path=%s", folder_path
            )
            return
        log.info(
            "IMPORT: folder import dialog accepted path=%s selected=%d",
            folder_path,
            len(selected),
        )

        # Import selected files (merge or individual)
        if dialog.should_merge and len(selected) >= 2:
            self._import_as_merged(selected, target_experiment)
            return
        success_count, error_count, _ = self._import_candidates(selected, target_experiment)
        log.info(
            "UI: Folder import finished for %s (success=%d errors=%d)",
            folder_path,
            success_count,
            error_count,
        )

    def _import_candidates(self, candidates, target_experiment):
        """Import a list of candidates into an experiment."""
        from vasoanalyzer.services.folder_import_service import get_file_signature

        success_count = 0
        error_count = 0
        errors = []
        start_time = time.perf_counter()

        total = len(candidates)
        log.info(
            "IMPORT: begin importing %d candidate(s) into experiment=%s",
            total,
            getattr(target_experiment, "name", None),
        )

        for candidate in candidates:
            sample_start = time.perf_counter()
            try:
                log.info(
                    "IMPORT: [%d/%d] ingesting subfolder=%s trace=%s events=%s",
                    success_count + error_count + 1,
                    total,
                    candidate.subfolder,
                    candidate.trace_file,
                    candidate.events_file or "(auto / none)",
                )
                # Create sample
                sample = SampleN(name=candidate.subfolder)

                # Load trace data and events
                from vasoanalyzer.io.trace_events import load_trace_and_events

                df, labels, times, frames, diam, od_diam, import_meta = load_trace_and_events(
                    candidate.trace_file
                )
                sample.trace_data = df
                log.info(
                    "IMPORT: [%d/%d] loaded trace/events for %s (labels=%d frames=%s diameters=%s)",
                    success_count + error_count + 1,
                    total,
                    candidate.subfolder,
                    len(labels or []),
                    bool(frames),
                    bool(diam or od_diam),
                )

                # Update metadata for trace
                trace_obj = Path(candidate.trace_file).expanduser().resolve(strict=False)
                self._update_sample_link_metadata(sample, "trace", trace_obj)

                # Store file signature for change detection
                sample.trace_sig = get_file_signature(candidate.trace_file)

                # Embed events if found
                if labels and times:
                    # Create events DataFrame for embedding
                    events_data = {
                        "Time (s)": times,
                        "Event": labels,
                    }
                    if frames:
                        events_data["Frame"] = frames
                    if diam:
                        events_data["DiamBefore"] = diam
                    if od_diam:
                        events_data["OuterDiamBefore"] = od_diam

                    # Sample pressure values from trace at event times
                    if df is not None and not df.empty:
                        arr_t = df["Time (s)"].values
                        if "Avg Pressure (mmHg)" in df.columns:
                            arr_avg_p = df["Avg Pressure (mmHg)"].values
                            p_avg_vals = [
                                float(arr_avg_p[int(np.argmin(np.abs(arr_t - t)))]) for t in times
                            ]
                            events_data["p_avg"] = p_avg_vals

                        if "Set Pressure (mmHg)" in df.columns:
                            arr_set_p = df["Set Pressure (mmHg)"].values
                            p1_vals = [
                                float(arr_set_p[int(np.argmin(np.abs(arr_t - t)))]) for t in times
                            ]
                            events_data["p1"] = p1_vals

                    sample.events_data = pd.DataFrame(events_data)

                    # Also store the CSV path metadata if available
                    if candidate.events_file and os.path.exists(candidate.events_file):
                        event_obj = Path(candidate.events_file).expanduser().resolve(strict=False)
                        self._update_sample_link_metadata(sample, "events", event_obj)
                        sample.events_sig = get_file_signature(candidate.events_file)

                # Add to experiment
                target_experiment.samples.append(sample)
                success_count += 1
                trace_rows = len(df.index) if isinstance(df, pd.DataFrame) else 0
                event_rows = (
                    len(sample.events_data.index)
                    if hasattr(sample, "events_data") and sample.events_data is not None
                    else 0
                )
                log.debug(
                    "Embedded folder sample '%s' (trace rows=%d, events=%d)",
                    sample.name,
                    trace_rows,
                    event_rows,
                )
                log.info(
                    "IMPORT: [%d/%d] finished sample %s status=%s duration=%.2fs",
                    success_count + error_count,
                    total,
                    sample.name,
                    getattr(candidate, "status", None),
                    time.perf_counter() - sample_start,
                )

            except Exception as e:
                error_count += 1
                errors.append(f"{candidate.subfolder}: {str(e)}")
                log.exception("Error importing %s", candidate.trace_file)
                log.info(
                    "IMPORT: [%d/%d] failed sample %s duration=%.2fs",
                    success_count + error_count,
                    total,
                    candidate.subfolder,
                    time.perf_counter() - sample_start,
                )

        # Refresh UI
        log.info("IMPORT: refreshing project tree after folder import")
        self.refresh_project_tree()
        log.info("IMPORT: project tree refresh completed")
        self._open_first_sample_if_none_active()
        log.info("IMPORT: ensure first sample opened completed")

        # Save project
        if self.current_project and self.current_project.path:
            if os.environ.get("VA_DEBUG_SKIP_SAVE_AFTER_IMPORT") == "1":
                log.info(
                    "IMPORT: DEBUG skip save after folder import (VA_DEBUG_SKIP_SAVE_AFTER_IMPORT=1)"
                )
            else:
                log.info(
                    "IMPORT: starting save after folder import path=%s",
                    self.current_project.path,
                )
                log.info(
                    "SAVE: starting project save (reason=folder_import, path=%s)",
                    self.current_project.path,
                )
                save_project(self.current_project, self.current_project.path)
                log.info(
                    "SAVE: project save completed (reason=folder_import, path=%s)",
                    self.current_project.path,
                )
            log.info(
                "IMPORT: finished save after folder import path=%s",
                self.current_project.path,
            )

        # Show summary
        if error_count == 0:
            self.statusBar().showMessage(
                f"✓ Successfully imported {success_count} sample(s) into '{target_experiment.name}'",
                5000,
            )
        else:
            message = f"Imported {success_count} sample(s) with {error_count} error(s)."
            if errors:
                message += "\n\nErrors:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    message += f"\n... and {len(errors) - 5} more"
            QMessageBox.warning(self, "Import Complete with Errors", message)
        log.debug("Folder import summary: %d success, %d errors", success_count, error_count)
        log.info(
            "IMPORT: completed folder import into %s (success=%d errors=%d duration=%.2fs)",
            getattr(target_experiment, "name", None),
            success_count,
            error_count,
            time.perf_counter() - start_time,
        )
        return success_count, error_count, errors

    def _import_as_merged(self, candidates, target_experiment) -> None:
        """Merge multiple folder-import candidates into a single dataset."""
        from vasoanalyzer.io.trace_events import load_trace_and_events
        from vasoanalyzer.services.folder_import_service import get_file_signature

        # Sort by trace filename so segments join in chronological order
        sorted_cands = sorted(candidates, key=lambda c: Path(c.trace_file).name)
        trace_paths = [c.trace_file for c in sorted_cands]
        events_paths = [c.events_file for c in sorted_cands if c.events_file]

        # Ask user for dataset name
        default_name = Path(sorted_cands[0].subfolder_path).parent.name or "Merged Dataset"
        name, ok = QInputDialog.getText(
            self, "Merged Dataset Name", "Name for merged dataset:", text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        try:
            ev_arg = events_paths if len(events_paths) == len(trace_paths) else None
            df, labels, times, frames, diam, od_diam, import_meta = load_trace_and_events(
                trace_paths, ev_arg
            )
        except Exception as e:
            QMessageBox.critical(self, "Merge Error", f"Failed to merge trace files:\n{e}")
            log.exception("Error merging candidates: %s", trace_paths)
            return

        sample = SampleN(name=name)
        sample.trace_data = df
        self._update_sample_link_metadata(sample, "trace", Path(trace_paths[0]).resolve())
        sample.trace_sig = get_file_signature(trace_paths[0])

        if labels and times:
            events_data: dict[str, Any] = {"Time (s)": times, "Event": labels}
            if frames:
                events_data["Frame"] = frames
            if diam:
                events_data["DiamBefore"] = diam
            if od_diam:
                events_data["OuterDiamBefore"] = od_diam
            sample.events_data = pd.DataFrame(events_data)

        target_experiment.samples.append(sample)

        self.refresh_project_tree()
        self._open_first_sample_if_none_active()

        if self.current_project and self.current_project.path:
            save_project(self.current_project, self.current_project.path)

        self.statusBar().showMessage(
            f"✓ Merged {len(trace_paths)} segment(s) into '{name}'", 5000
        )
        log.info("IMPORT: merged %d segments into sample '%s'", len(trace_paths), name)

    def delete_samples(self, samples: list[SampleN]) -> None:
        """Delete one or more samples with a single confirmation and save."""
        if not self.current_project or not samples:
            return

        count = len(samples)
        if count == 1:
            msg = f"Delete dataset '{samples[0].name}'?\nThis cannot be undone."
            title = "Delete Dataset"
        else:
            names = "\n  • ".join(s.name for s in samples[:10])
            more = f"\n  … and {count - 10} more" if count > 10 else ""
            msg = f"Delete {count} datasets?\n  • {names}{more}\nThis cannot be undone."
            title = "Delete Datasets"

        if (
            QMessageBox.question(
                self, title, msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            != QMessageBox.Yes
        ):
            return

        for sample in samples:
            for exp in self.current_project.experiments:
                if sample in exp.samples:
                    exp.samples.remove(sample)
                    self.project_state.pop(id(sample), None)
                    if self.current_sample is sample:
                        self.current_sample = None
                    break

        self.refresh_project_tree()
        self.mark_session_dirty()
        if self.current_project.path:
            save_project_file(self.current_project, self.current_project.path)

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
            self.recent_menu.addAction("No recent imports").setEnabled(False)
        else:
            for path in self.recent_files:
                action = QAction(os.path.basename(path), self)
                action.setToolTip(path)
                action.triggered.connect(
                    lambda checked=False, p=path: self.load_trace_and_events(
                        p, source="recent_file"
                    )
                )
                self.recent_menu.addAction(action)

        self._refresh_home_recent()

    def icon_path(self, filename):
        """Return absolute path to an icon shipped with the application."""
        from utils import resource_path

        try:
            from vasoanalyzer.ui import theme as theme_module

            current_theme = getattr(theme_module, "CURRENT_THEME", None)
            is_dark = False
            if isinstance(current_theme, dict):
                is_dark = bool(current_theme.get("is_dark", False))
            dark_theme = getattr(theme_module, "DARK_THEME", None)
            if is_dark or (
                current_theme is not None and dark_theme is not None and current_theme is dark_theme
            ):
                name, ext = os.path.splitext(filename)
                dark_filename = f"{name}_Dark{ext}"
                candidate = resource_path("icons", dark_filename)
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            log.debug("Dark theme icon lookup failed for %s", dark_filename, exc_info=True)

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
        self.update_scroll_slider()

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
        self._build_window_menu(menubar)
        self._build_help_menu(menubar)

        try:
            mode = self.settings.value("appearance/themeMode", "system", type=str)
        except Exception:
            mode = "system"
        self._active_theme_mode = (mode or "system").lower()
        self._update_theme_action_checks(mode)

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

        self.action_add_sample = QAction("Add Sample", self)
        self.action_add_sample.triggered.connect(self.add_sample_to_current_experiment)
        project_menu.addAction(self.action_add_sample)

        file_menu.addSeparator()

        self.action_new = QAction("Start New Analysis…", self)
        self.action_new.setShortcut(QKeySequence.New)
        self.action_new.triggered.connect(self.start_new_analysis)
        file_menu.addAction(self.action_new)

        import_menu = file_menu.addMenu("Open Data")

        self.action_open_trace = QAction("Import Trace CSV…", self)
        self.action_open_trace.setShortcut(QKeySequence.Open)
        self.action_open_trace.triggered.connect(self._handle_load_trace)
        import_menu.addAction(self.action_open_trace)

        self.action_import_vasotracker_v1 = QAction("VasoTracker v1 (CSV + Table)…", self)
        self.action_import_vasotracker_v1.triggered.connect(self._handle_load_vasotracker_v1)
        import_menu.addAction(self.action_import_vasotracker_v1)

        self.action_import_vasotracker_v2 = QAction("VasoTracker v2 (CSV + table.csv)…", self)
        self.action_import_vasotracker_v2.triggered.connect(self._handle_load_vasotracker_v2)
        import_menu.addAction(self.action_import_vasotracker_v2)

        import_menu.addSeparator()

        self.action_import_events = QAction("Import Events CSV…", self)
        self.action_import_events.triggered.connect(self._handle_load_events)
        self.action_import_events.setEnabled(False)
        import_menu.addAction(self.action_import_events)

        self.action_open_tiff = QAction("Import Result TIFF…", self)
        self.action_open_tiff.setShortcut("Ctrl+Shift+T")
        self.action_open_tiff.triggered.connect(self.load_snapshot)
        import_menu.addAction(self.action_open_tiff)

        self.action_import_folder = QAction("Import Folder…", self)
        self.action_import_folder.setShortcut("Ctrl+Shift+I")
        self.action_import_folder.triggered.connect(self._handle_import_folder)
        import_menu.addAction(self.action_import_folder)

        self.action_import_dataset_pkg = QAction("Import Dataset Package…", self)
        self.action_import_dataset_pkg.triggered.connect(self.import_dataset_package_action)
        import_menu.addAction(self.action_import_dataset_pkg)

        self.action_import_dataset_from_project = QAction("Import from Project…", self)
        self.action_import_dataset_from_project.triggered.connect(
            self.import_dataset_from_project_action
        )
        import_menu.addAction(self.action_import_dataset_from_project)

        self.recent_menu = file_menu.addMenu("Recent Imports")
        self.update_recent_files_menu()

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("Export")

        copy_menu = export_menu.addMenu("Copy for Excel")
        self.action_copy_excel_row = QAction("Row-per-Event (Excel)", self)
        self.action_copy_excel_row.triggered.connect(
            lambda: self._copy_event_profile_to_clipboard(
                EVENT_TABLE_ROW_PER_EVENT_ID, include_header=True
            )
        )
        copy_menu.addAction(self.action_copy_excel_row)
        self.action_copy_excel_values = QAction("Values Only (Column Paste)", self)
        self.action_copy_excel_values.triggered.connect(
            lambda: self._copy_event_profile_to_clipboard(
                EVENT_VALUES_SINGLE_COLUMN_ID, include_header=False
            )
        )
        copy_menu.addAction(self.action_copy_excel_values)
        copy_menu.addSeparator()
        self.action_copy_excel_pressure = QAction("Pressure Curve (Standard)", self)
        self.action_copy_excel_pressure.triggered.connect(
            lambda: self._copy_event_profile_to_clipboard(
                PRESSURE_CURVE_STANDARD_ID, include_header=True
            )
        )
        copy_menu.addAction(self.action_copy_excel_pressure)

        export_csv_menu = export_menu.addMenu("Export CSV")
        self.action_export_csv = export_csv_menu.menuAction()
        self.action_export_csv_row = QAction("Row-per-Event (Excel)…", self)
        self.action_export_csv_row.triggered.connect(
            lambda: self._export_event_profile_csv_via_dialog(
                EVENT_TABLE_ROW_PER_EVENT_ID, include_header=True
            )
        )
        export_csv_menu.addAction(self.action_export_csv_row)
        self.action_export_csv_values = QAction("Values Only (Column Paste)…", self)
        self.action_export_csv_values.triggered.connect(
            lambda: self._export_event_profile_csv_via_dialog(
                EVENT_VALUES_SINGLE_COLUMN_ID, include_header=False
            )
        )
        export_csv_menu.addAction(self.action_export_csv_values)
        export_csv_menu.addSeparator()
        self.action_export_csv_pressure = QAction("Pressure Curve (Standard)…", self)
        self.action_export_csv_pressure.triggered.connect(
            lambda: self._export_event_profile_csv_via_dialog(
                PRESSURE_CURVE_STANDARD_ID, include_header=True
            )
        )
        export_csv_menu.addAction(self.action_export_csv_pressure)

        self.action_export_excel_template = QAction("Export to VasoAnalyzer Excel Template…", self)
        self.action_export_excel_template.triggered.connect(self.open_excel_template_export_dialog)
        export_menu.addAction(self.action_export_excel_template)

        self.action_export_excel = QAction("Export to Excel Template…", self)
        self.action_export_excel.triggered.connect(self.open_excel_mapping_dialog)
        export_menu.addAction(self.action_export_excel)

        self.action_gif_animator = QAction("Export GIF…", self)
        self.action_gif_animator.setToolTip("Create animated GIFs from traces and snapshots")
        self.action_gif_animator.triggered.connect(self.show_gif_animator)
        self.action_gif_animator.setEnabled(False)
        export_menu.addAction(self.action_gif_animator)

        export_menu.addSeparator()

        self.action_export_tiff = QAction("High-Res Plot…", self)
        self.action_export_tiff.triggered.connect(self.export_high_res_plot)
        export_menu.addAction(self.action_export_tiff)

        self.action_export_report = QAction("SciNote Report…", self)
        self.action_export_report.setToolTip(
            "Export a composite figure with trace, event table, and metadata"
        )
        self.action_export_report.triggered.connect(self._export_scinote_report)
        export_menu.addAction(self.action_export_report)

        self.action_export_bundle = QAction("Project Bundle (.vaso)…", self)
        self.action_export_bundle.triggered.connect(self.export_project_bundle_action)
        export_menu.addAction(self.action_export_bundle)

        self.action_export_shareable = QAction("Shareable Single File…", self)
        self.action_export_shareable.triggered.connect(self.export_shareable_project)
        export_menu.addAction(self.action_export_shareable)

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

        self.action_delete_event = QAction("Delete Event", self)
        self.action_delete_event.setShortcut(QKeySequence.Delete)
        self.action_delete_event.triggered.connect(self.delete_selected_events)
        edit_menu.addAction(self.action_delete_event)

        edit_menu.addSeparator()

        clear_pins = QAction("Clear All Pins", self)
        clear_pins.triggered.connect(self.clear_all_pins)
        edit_menu.addAction(clear_pins)

        clear_events = QAction("Clear All Events", self)
        clear_events.triggered.connect(self.clear_current_session)
        edit_menu.addAction(clear_events)

    def _build_view_menu(self, menubar):
        view_menu = menubar.addMenu("&View")

        home_act = QAction("Home Dashboard", self)
        home_act.setShortcut("Ctrl+Shift+H")
        home_act.triggered.connect(self.show_home_dashboard)
        view_menu.addAction(home_act)

        view_menu.addSeparator()

        # Color scheme selection
        theme_menu = view_menu.addMenu("Color Theme")
        self.action_theme_light = QAction("Light", self, checkable=True, checked=True)
        self.action_theme_dark = QAction("Dark", self, checkable=True)
        self.action_theme_light.triggered.connect(lambda: self.set_color_scheme("light"))
        self.action_theme_dark.triggered.connect(lambda: self.set_color_scheme("dark"))
        theme_menu.addAction(self.action_theme_light)
        theme_menu.addAction(self.action_theme_dark)

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

        goto_act = QAction("Go to Time…", self)
        goto_act.setShortcut("Ctrl+G")
        goto_act.triggered.connect(self.show_goto_time_dialog)
        view_menu.addAction(goto_act)
        self.action_goto_time = goto_act

        view_menu.addSeparator()

        anno_menu = view_menu.addMenu("Annotations")
        ev_lines = QAction("Event Lines", self, checkable=True, checked=True)
        ev_lbls = QAction("Event Labels", self)
        pin_lbls = QAction("Pinned Labels", self, checkable=True, checked=True)
        frame_mk = QAction("Frame Marker", self, checkable=True, checked=True)
        ev_lines.triggered.connect(lambda _: self.toggle_annotation("lines"))
        ev_lbls.triggered.connect(lambda _: self.toggle_annotation("evt_labels"))
        pin_lbls.triggered.connect(lambda _: self.toggle_annotation("pin_labels"))
        frame_mk.triggered.connect(lambda _: self.toggle_annotation("frame_marker"))
        for action in (ev_lines, ev_lbls, pin_lbls, frame_mk):
            anno_menu.addAction(action)
        self.menu_event_lines_action = ev_lines

        self._ensure_event_label_actions()
        label_modes_menu = anno_menu.addMenu("Label Mode")
        label_modes_menu.addAction(self.actEventLabelsOff)
        label_modes_menu.addAction(self.actEventLabelsVertical)
        label_modes_menu.addAction(self.actEventLabelsHorizontal)
        label_modes_menu.addAction(self.actEventLabelsOutside)

        view_menu.addSeparator()

        self.showhide_menu = view_menu.addMenu("Panels")
        evt_tbl = QAction("Event Table", self, checkable=True, checked=True)
        snap_vw = QAction("Snapshot Viewer", self, checkable=True, checked=False)
        evt_tbl.triggered.connect(self.toggle_event_table)
        if self._snapshot_panel_disabled_by_env:
            snap_vw.setEnabled(False)
            snap_vw.setToolTip("Disabled by VASO_DISABLE_SNAPSHOT_PANEL")
        else:
            snap_vw.triggered.connect(self.toggle_snapshot_viewer)
        self.showhide_menu.addAction(evt_tbl)
        self.showhide_menu.addAction(snap_vw)
        self.snapshot_viewer_action = snap_vw
        self.event_table_action = evt_tbl

        self._register_trace_nav_shortcuts()

        view_menu.addSeparator()

        shortcut = "Meta+M" if sys.platform == "darwin" else "Ctrl+M"
        self.action_snapshot_metadata = QAction("Metadata…", self)
        self.action_snapshot_metadata.setShortcut(shortcut)
        self.action_snapshot_metadata.setCheckable(True)
        self.action_snapshot_metadata.setEnabled(False)
        if not self._snapshot_panel_disabled_by_env:
            self.action_snapshot_metadata.triggered.connect(
                lambda checked: self.set_snapshot_metadata_visible(bool(checked))
            )
        view_menu.addAction(self.action_snapshot_metadata)

        self.id_toggle_act = QAction("Inner", self, checkable=True, checked=True)
        self.id_toggle_act.setStatusTip("Show inner diameter trace")
        self.id_toggle_act.setToolTip("Show inner diameter trace")
        self.od_toggle_act = QAction("Outer", self, checkable=True, checked=True)
        self.od_toggle_act.setStatusTip("Show outer diameter trace")
        self.od_toggle_act.setToolTip("Show outer diameter trace")
        self.avg_pressure_toggle_act = QAction("Pressure", self, checkable=True, checked=True)
        self.avg_pressure_toggle_act.setStatusTip("Show pressure trace")
        self.avg_pressure_toggle_act.setToolTip("Show pressure trace")
        self.set_pressure_toggle_act = QAction("Set Pressure", self, checkable=True, checked=False)
        self.set_pressure_toggle_act.setStatusTip("Show set pressure trace")
        self.set_pressure_toggle_act.setToolTip("Show set pressure trace")
        self.id_toggle_act.setShortcut("I")
        self.od_toggle_act.setShortcut("O")
        # Note: No shortcut for pressure to avoid conflict with PyQtGraph Autoscale (A)
        self.set_pressure_toggle_act.setShortcut("S")
        self.id_toggle_act.setIcon(QIcon(self.icon_path("ID.svg")))
        self.od_toggle_act.setIcon(QIcon(self.icon_path("OD.svg")))
        self.avg_pressure_toggle_act.setIcon(QIcon(self.icon_path("P.svg")))
        self.set_pressure_toggle_act.setIcon(QIcon(self.icon_path("SP.svg")))
        self.id_toggle_act.toggled.connect(self.toggle_inner_diameter)
        self.od_toggle_act.toggled.connect(self.toggle_outer_diameter)
        self.avg_pressure_toggle_act.toggled.connect(self.toggle_avg_pressure)
        self.set_pressure_toggle_act.toggled.connect(self.toggle_set_pressure)
        self.showhide_menu.addAction(self.id_toggle_act)
        self.showhide_menu.addAction(self.od_toggle_act)
        self.showhide_menu.addAction(self.avg_pressure_toggle_act)
        self.showhide_menu.addAction(self.set_pressure_toggle_act)

        view_menu.addSeparator()

        fs_act = QAction("Full Screen", self)
        fs_act.setShortcut("F11")
        fs_act.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fs_act)

    def _build_tools_menu(self, menubar):
        tools_menu = menubar.addMenu("&Tools")

        # Visualization tools
        self.action_plot_settings = QAction("Plot Settings…", self)
        self.action_plot_settings.triggered.connect(self.open_plot_settings_dialog)
        tools_menu.addAction(self.action_plot_settings)

        layout_act = QAction("Subplot Layout…", self)
        layout_act.triggered.connect(self.open_subplot_layout_dialog)
        tools_menu.addAction(layout_act)

        tools_menu.addSeparator()

        self.action_select_range = QAction("Select Range on Trace", self)
        self.action_select_range.setCheckable(True)
        self.action_select_range.toggled.connect(self._toggle_trace_range_selection)
        tools_menu.addAction(self.action_select_range)

        self.action_copy_selected_range = QAction("Copy Selected Range Data", self)
        self.action_copy_selected_range.triggered.connect(self._copy_selected_range_data)
        tools_menu.addAction(self.action_copy_selected_range)

        self.action_export_selected_range = QAction("Export Selected Range Data…", self)
        self.action_export_selected_range.triggered.connect(self._export_selected_range_data)
        tools_menu.addAction(self.action_export_selected_range)

        tools_menu.addSeparator()

        # Data management tools
        self.action_relink_assets = QAction("Relink Missing Files…", self)
        self.action_relink_assets.setEnabled(False)
        self.action_relink_assets.triggered.connect(self.show_relink_dialog)
        tools_menu.addAction(self.action_relink_assets)

        tools_menu.addSeparator()

        self.action_change_log = QAction("Change Log…", self)
        self.action_change_log.triggered.connect(self._show_change_log_dialog)
        tools_menu.addAction(self.action_change_log)

    def _build_window_menu(self, menubar):
        window_menu = menubar.addMenu("&Window")

        minimize_act = QAction("Minimize", self)
        minimize_act.setShortcut("Ctrl+M" if sys.platform != "darwin" else "Meta+M")
        minimize_act.triggered.connect(self.showMinimized)
        window_menu.addAction(minimize_act)

        zoom_act = QAction("Zoom", self)
        zoom_act.triggered.connect(self.toggle_maximize)
        window_menu.addAction(zoom_act)

        window_menu.addSeparator()

        if sys.platform == "darwin":
            bring_all_act = QAction("Bring All to Front", self)
            bring_all_act.triggered.connect(self.raise_all_windows)
            window_menu.addAction(bring_all_act)

    def _build_help_menu(self, menubar):
        help_menu = menubar.addMenu("&Help")

        self.action_about = QAction("About VasoAnalyzer", self)
        self.action_about.triggered.connect(self.show_about)
        self._assign_menu_role(self.action_about, "AboutRole")
        help_menu.addAction(self.action_about)

        act_about_project = QAction("About Project File…", self)
        act_about_project.triggered.connect(self.show_project_file_info)
        help_menu.addAction(act_about_project)

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
        if self._updates_disabled_by_env:
            act_update.setEnabled(False)
            act_update.setToolTip("Disabled by VASO_DISABLE_UPDATE_CHECK")
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

    def show_project_file_info(self, checked: bool = False) -> None:
        """Show information about project file format.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        message = (
            "<b>Single-File .vaso Projects</b><br><br>"
            "<ul>"
            "<li>SQLite v3 container that stores datasets, traces, UI state, and metadata together.</li>"
            "<li>All imported assets are embedded, deduplicated by SHA-256, and compressed for portability.</li>"
            "<li>Saves are atomic and crash-safe, with periodic autosave snapshots you can restore on reopen.</li>"
            "</ul>"
        )
        QMessageBox.information(self, "About Project File", message)

    def build_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
            return

        for path in self.recent_files:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(
                lambda checked=False, p=path: self.load_trace_and_events(p, source="recent_file")
            )
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def build_recent_projects_menu(self):
        if not hasattr(self, "recent_projects_menu") or self.recent_projects_menu is None:
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

    def open_preferences_dialog(self, checked: bool = False):
        """Open preferences dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        from vasoanalyzer.ui.dialogs.preferences_dialog import PreferencesDialog

        dialog = PreferencesDialog(self)
        dialog.exec_()

    def _safe_remove_artist(self, artist):
        """Remove the Matplotlib artist if it is still attached to a canvas."""
        if artist is None:
            return
        scene = getattr(artist, "scene", None)
        if callable(scene):
            sc = scene()
            if sc is not None:
                with contextlib.suppress(Exception):
                    sc.removeItem(artist)
                return
        if getattr(artist, "figure", None) is None and getattr(artist, "axes", None) is None:
            return
        try:
            artist.remove()
        except (NotImplementedError, ValueError):
            if hasattr(artist, "set_visible"):
                artist.set_visible(False)

    def _pin_coords(self, marker) -> tuple[float, float] | None:
        """Return (x,y) for a pin marker (Matplotlib or PyQtGraph)."""
        if marker is None:
            return None
        try:
            if hasattr(marker, "get_xdata") and hasattr(marker, "get_ydata"):
                return float(marker.get_xdata()[0]), float(marker.get_ydata()[0])
            get_data = getattr(marker, "getData", None)
            if callable(get_data):
                xdata, ydata = get_data()
                if xdata is not None and len(xdata) > 0 and ydata is not None and len(ydata) > 0:
                    return float(xdata[0]), float(ydata[0])
        except Exception:
            return None
        return None

    def _nearest_pin_index(self, x: float, y: float) -> int | None:
        best_idx = None
        best_dist = float("inf")
        for idx, (marker, _label) in enumerate(self.pinned_points):
            coords = self._pin_coords(marker)
            if coords is None:
                continue
            dx = coords[0] - x
            dy = coords[1] - y
            dist = abs(dx) + abs(dy)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is None or best_dist > 0.25:
            return None
        return best_idx

    def _add_pyqtgraph_pin(self, track_id: str, x: float, y: float, trace_type: str = "inner"):
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "track"):
            return
        track = plot_host.track(track_id)
        if track is None:
            return
        try:
            import pyqtgraph as pg
        except Exception:
            return

        plot_item = track.view.get_widget().getPlotItem()
        color = CURRENT_THEME.get("selection_bg", "#EF4444")
        brush = pg.mkBrush(color)
        pen = pg.mkPen(color)
        marker = pg.ScatterPlotItem([x], [y], symbol="o", size=8, brush=brush, pen=pen)
        marker.trace_type = trace_type
        plot_item.addItem(marker)

        label = pg.TextItem(f"{x:.2f} s\n{y:.1f} µm", anchor=(0, 1))
        label.trace_type = trace_type
        label.setPos(x, y)
        plot_item.addItem(label)

        self.pinned_points.append((marker, label))

    def clear_all_pins(self, checked: bool = False):
        """Clear all pinned annotations.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        for marker, label in self.pinned_points:
            self._safe_remove_artist(marker)
            self._safe_remove_artist(label)
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
                    coords
                    for marker, _ in self.pinned_points
                    if (coords := self._pin_coords(marker))
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
            QMessageBox.warning(self, "No Previous Plot", "No previously saved plot was found.")
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

    def clear_recent_projects(self, checked: bool = False):
        """Clear recent projects list.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self.recent_projects = []
        self.save_recent_projects()
        self.build_recent_projects_menu()
        self._refresh_home_recent()

    def open_recent_project(self, path):
        # Use the standard open flow which creates ProjectContext
        # This ensures repository is available for background jobs
        from vasoanalyzer.app.openers import open_project_file

        try:
            open_project_file(self, path)
        except Exception as e:
            error_msg = str(e)

            # Check if this was a database corruption error
            if "corrupted" in error_msg.lower() or "malformed" in error_msg.lower():
                # Check if project is in cloud storage
                from vasoanalyzer.core.project import _is_cloud_storage_path

                is_cloud, cloud_service = _is_cloud_storage_path(path)

                cloud_warning = ""
                if is_cloud:
                    cloud_warning = (
                        f"\n\n⚠️ IMPORTANT: This project is stored in {cloud_service}.\n"
                        f"SQLite databases are INCOMPATIBLE with cloud storage and will become corrupted.\n\n"
                        f"To fix this:\n"
                        f"1. Move this project to a LOCAL folder (e.g., ~/Documents or ~/Desktop)\n"
                        f"2. Create a new project in the local folder\n"
                        f"3. Never store .vaso projects in iCloud, Dropbox, or other cloud storage\n\n"
                    )

                if "backup was created" in error_msg:
                    QMessageBox.critical(
                        self,
                        "Project Database Corrupted",
                        f"The project database is corrupted and automatic recovery failed.\n\n"
                        f"Error: {e}"
                        f"{cloud_warning}\n"
                        f"A backup was created at: {path}.backup\n\n"
                        f"Recommendations:\n"
                        f"1. Check the backup file\n"
                        f"2. Contact support for manual recovery\n"
                        f"3. Create a new project and re-import your data",
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Project Database Error",
                        f"Could not open project due to database error:\n\n{e}"
                        f"{cloud_warning}\n"
                        f"The database may be corrupted.",
                    )
            else:
                QMessageBox.critical(
                    self,
                    "Project Load Error",
                    f"Could not open project:\n{e}",
                )
            return

    def _start_update_check(self, *, silent: bool = False) -> None:
        if self._updates_disabled_by_env:
            if not silent:
                self.statusBar().showMessage(
                    "Update checks disabled (VASO_DISABLE_UPDATE_CHECK)", 4000
                )
            return
        if self._update_check_in_progress or self._update_checker.is_running:
            return

        if not silent:
            self.statusBar().showMessage("Checking for updates…", 3000)
        started = self._update_checker.start(APP_VERSION, silent=silent)
        if started:
            self._update_check_in_progress = True

    def check_for_updates_at_startup(self) -> None:
        """Check for updates at startup if user hasn't disabled it or is not in snooze period."""
        import time

        if self._updates_disabled_by_env:
            return

        # Check if user disabled update notifications
        if self.settings.value("updates/dont_show_again", False, type=bool):
            return

        # Check if we're in the snooze period
        remind_later_timestamp = self.settings.value("updates/remind_later_until", 0, type=int)
        if remind_later_timestamp > 0:
            current_time = int(time.time())
            if current_time < remind_later_timestamp:
                # Still in snooze period
                return

        self._start_update_check(silent=True)

    def check_for_updates(self, checked: bool = False) -> None:
        """Check for application updates.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if self._updates_disabled_by_env:
            self.statusBar().showMessage("Update checks disabled (VASO_DISABLE_UPDATE_CHECK)", 4000)
            return
        self._start_update_check(silent=False)

    def _on_update_check_completed(self, silent: bool, latest: object, error: object) -> None:
        import time

        self._update_check_in_progress = False

        latest_str = latest if isinstance(latest, str) and latest else None
        manager = getattr(self, "window_manager", None)
        if manager is not None and getattr(manager, "_modal_in_progress", False):
            should_defer = bool(latest_str) or (error and not silent) or (not silent and not error)
            if should_defer:
                log.debug("Deferring update prompt while modal dialog is active")
                QTimer.singleShot(
                    2000,
                    lambda: self._on_update_check_completed(silent, latest, error),
                )
                return

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

        if latest_str:
            from .dialogs.update_dialog import UpdateDialog

            # Show custom update dialog with remind later and don't show options
            dlg = UpdateDialog(APP_VERSION, latest_str, self)
            self._update_checker.set_dialog(dlg)
            try:
                user_choice = dlg.exec_()
            finally:
                self._update_checker.set_dialog(None)

            if user_choice == UpdateDialog.DONT_SHOW:
                # User chose to never see update notifications again
                self.settings.setValue("updates/dont_show_again", True)
                self.statusBar().showMessage("Update notifications disabled", 3000)
            elif user_choice == UpdateDialog.REMIND_LATER:
                # User chose to be reminded in 7 days
                snooze_until = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days in seconds
                self.settings.setValue("updates/remind_later_until", snooze_until)
                self.statusBar().showMessage("Will remind you in 7 days", 3000)
            else:
                # User clicked OK
                self.statusBar().showMessage("Update available", 3000)
        elif not silent:
            QMessageBox.information(
                self,
                "Up to Date",
                f"You are running the latest release ({APP_VERSION}).",
            )
            self.statusBar().showMessage("Up to date", 3000)

    def _shutdown_update_checker(self) -> None:
        checker = getattr(self, "_update_checker", None)
        if checker is None:
            return
        try:
            checker.shutdown()
        except Exception:
            log.warning("Update checker shutdown failed", exc_info=True)

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
        self.canvas.draw_idle()

    def _register_trace_nav_shortcuts(self) -> None:
        if getattr(self, "_trace_nav_shortcuts", None):
            return
        self._trace_nav_shortcuts: list[QAction] = []

        def _add_action(label: str, shortcut: str, handler) -> None:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.WindowShortcut)
            action.triggered.connect(handler)
            self.addAction(action)
            self._trace_nav_shortcuts.append(action)

        zoom_all = QAction("Zoom to All (X)", self)
        zoom_all.setShortcuts([QKeySequence("0"), QKeySequence("Ctrl+0")])
        zoom_all.setShortcutContext(Qt.WindowShortcut)
        zoom_all.triggered.connect(self._zoom_all_x)
        self.addAction(zoom_all)
        self._trace_nav_shortcuts.append(zoom_all)
        self.actZoomAllX = zoom_all

        _add_action("Pan Left (10%)", "Left", lambda: self._pan_window_fraction(0.10, -1))
        _add_action("Pan Right (10%)", "Right", lambda: self._pan_window_fraction(0.10, 1))
        _add_action("Pan Left (50%)", "Shift+Left", lambda: self._pan_window_fraction(0.50, -1))
        _add_action("Pan Right (50%)", "Shift+Right", lambda: self._pan_window_fraction(0.50, 1))
        _add_action("Jump to Start", "Home", self._jump_to_start)
        _add_action("Jump to End", "End", self._jump_to_end)

        _add_action("Previous Event", "[", lambda: self._jump_to_event(-1))
        _add_action("Next Event", "]", lambda: self._jump_to_event(1))

    def show_goto_time_dialog(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return
        full_range = plot_host.full_range() if hasattr(plot_host, "full_range") else None
        current_window = (
            plot_host.current_window() if hasattr(plot_host, "current_window") else None
        )
        if full_range is None and current_window is None:
            return
        cursor_available = self._time_cursor_time is not None

        from vasoanalyzer.ui.dialogs.goto_time_dialog import GotoTimeDialog

        dialog = GotoTimeDialog(
            self,
            full_range=full_range,
            current_window=current_window,
            cursor_available=cursor_available,
        )
        if not dialog.exec_():
            return
        time_value = dialog.time_value()
        if time_value is None:
            return
        mode = dialog.mode()
        if mode == "cursor":
            self.jump_to_time(float(time_value), source="cursor")
        else:
            self.jump_to_time(float(time_value), source="manual")

    def _jump_to_start(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "full_range"):
            return
        full_range = plot_host.full_range()
        if full_range is None:
            return
        start, end = full_range
        span = None
        window = plot_host.current_window() if hasattr(plot_host, "current_window") else None
        if window is not None:
            span = window[1] - window[0]
        if span is None or span <= 0 or span >= (end - start):
            self._apply_time_window(full_range)
            return
        self._apply_time_window((start, start + span))

    def _jump_to_end(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "full_range"):
            return
        full_range = plot_host.full_range()
        if full_range is None:
            return
        start, end = full_range
        span = None
        window = plot_host.current_window() if hasattr(plot_host, "current_window") else None
        if window is not None:
            span = window[1] - window[0]
        if span is None or span <= 0 or span >= (end - start):
            self._apply_time_window(full_range)
            return
        self._apply_time_window((end - span, end))

    def _pan_window_fraction(self, fraction: float, direction: int) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "current_window"):
            return
        window = plot_host.current_window()
        if window is None:
            return
        span = float(window[1] - window[0])
        if span <= 0:
            return
        from vasoanalyzer.ui.plots.pyqtgraph_nav_math import pan_step

        delta = pan_step(span, fraction) * (1 if direction >= 0 else -1)
        plot_host.scroll_by(delta)

    def _jump_to_event(self, direction: int) -> None:
        times = sorted(self._overview_event_times())
        if not times:
            return
        plot_host = getattr(self, "plot_host", None)
        current = self._time_cursor_time
        if current is None:
            window = plot_host.current_window() if plot_host is not None else None
            if window is not None:
                current = 0.5 * (window[0] + window[1])
            else:
                current = times[0]
        idx = 0
        if direction > 0:
            for i, t in enumerate(times):
                if t > current:
                    idx = i
                    break
            else:
                return
        else:
            for i in range(len(times) - 1, -1, -1):
                if times[i] < current:
                    idx = i
                    break
            else:
                return
        self.jump_to_time(float(times[idx]), from_event=True, source="event")

    def _zoom_all_x(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "full_range"):
            if (
                hasattr(plot_host, "get_render_backend")
                and plot_host.get_render_backend() == "pyqtgraph"
                and hasattr(plot_host, "zoom_to_full_range")
            ):
                full = plot_host.full_range()
                if full is not None:
                    self._set_xrange_source("zoom.all", (float(full[0]), float(full[1])))
                else:
                    self._set_xrange_source("zoom.all", None)
                plot_host.zoom_to_full_range()
                return
            full = plot_host.full_range()
            if full is not None:
                self._set_xrange_source("zoom.all", (float(full[0]), float(full[1])))
                self._apply_time_window(full)
                return
        if self.xlim_full is not None:
            self._set_xrange_source(
                "zoom.all",
                (float(self.xlim_full[0]), float(self.xlim_full[1])),
            )
            self._apply_time_window(self.xlim_full)

    def reset_view(self, checked: bool = False):
        """Reset view to full extent.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self.reset_to_full_view()

    def fit_to_data(self, checked: bool = False):
        """Fit view to full data bounds (delegates to _zoom_all_x for PyQtGraph).

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self._zoom_all_x()

    def zoom_to_selection(self, checked: bool = False):
        """Zoom to current selection, or to full data range if no selection is active.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # Use the active range selection bounds if available; fall back to full range.
        range_sel = getattr(self, "_range_selection", None)
        if range_sel is not None:
            t0, t1 = range_sel
            self._apply_time_window((t0, t1))
        else:
            self._zoom_all_x()

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
            isinstance(mask, np.ndarray) and mask.dtype == bool and mask.size == values.size
        ) and mask.any():
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
            order = ["off", "indices", "names_on_hover", "names_always"]
            try:
                idx = order.index(self._event_label_mode)
            except ValueError:
                idx = 0
            next_mode = order[(idx + 1) % len(order)]
            self._set_event_label_mode(next_mode)
        elif kind == "pin_labels":
            for _marker, lbl in self.pinned_points:
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
        self._on_view_state_changed(reason="annotation toggle")

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
        self._update_event_table_presence_state(bool(self.event_table_data))
        if controller is not None:
            controller.set_review_states(self._current_review_states())
        self._update_excel_controls()

    def _ensure_event_meta_length(self, length: int | None = None) -> None:
        if length is None:
            length = len(self.event_labels)
        length = max(int(length), 0)
        self._normalize_event_label_meta(length)

    def _normalize_event_label_meta(self, length: int | None = None) -> None:
        target_len = len(self.event_table_data) if length is None else length
        current = list(getattr(self, "event_label_meta", []) or [])
        if len(current) < target_len:
            current.extend({} for _ in range(target_len - len(current)))
        elif len(current) > target_len:
            current = current[:target_len]
        normalized: list[dict[str, Any]] = []
        for meta in current:
            normalized.append(self._with_default_review_state(meta))
        self.event_label_meta = normalized

    @staticmethod
    def _with_default_review_state(meta: Mapping[str, Any] | None) -> dict[str, Any]:
        payload = dict(meta or {})
        state = payload.get("review_state")
        if isinstance(state, str) and state.strip():
            payload["review_state"] = state.strip().upper().replace(" ", "_").replace("-", "_")
        else:
            payload["review_state"] = REVIEW_UNREVIEWED
        return payload

    def _current_review_states(self) -> list[str]:
        self._normalize_event_label_meta(len(self.event_table_data))
        return [meta.get("review_state", REVIEW_UNREVIEWED) for meta in self.event_label_meta]

    def _review_notice_key(self) -> tuple:
        sample = getattr(self, "current_sample", None)
        if sample is None:
            return ("session",)
        dataset_id = getattr(sample, "dataset_id", None)
        sample_id = getattr(sample, "id", None)
        if sample_id is None:
            sample_id = id(sample)
        sample_name = getattr(sample, "name", None)
        return (dataset_id, sample_id, sample_name)

    def _configure_review_notice_banner(self) -> None:
        if not hasattr(self, "review_notice_review_button"):
            return
        tooltip = None
        if hasattr(self, "review_events_action") and self.review_events_action is not None:
            tooltip = self.review_events_action.toolTip() or None
        self.review_notice_review_button.setToolTip(
            tooltip or "Open the review panel to confirm or edit event values"
        )
        self.review_notice_dismiss_button.setToolTip("Hide this notice for the current dataset")

    def _dismiss_review_notice(self) -> None:
        self._review_notice_dismissed_key = self._review_notice_key()
        self._update_review_notice_visibility()

    def _update_review_notice_visibility(self) -> None:
        """Update the non-blocking review notice based on review state."""
        if getattr(self, "_suppress_review_prompt", False):
            return

        banner = getattr(self, "review_notice_banner", None)
        if banner is None:
            return

        if not getattr(self, "event_table_data", None):
            banner.setVisible(False)
            return

        review_states = (
            self._current_review_states() if hasattr(self, "_current_review_states") else []
        )
        if not review_states:
            banner.setVisible(False)
            return

        has_unreviewed = any(state == REVIEW_UNREVIEWED for state in review_states)
        if not has_unreviewed:
            banner.setVisible(False)
            return

        dismissed = self._review_notice_dismissed_key == self._review_notice_key()
        banner.setVisible(not dismissed)

    def _set_review_state_for_row(self, index: int, state: str) -> None:
        if not hasattr(self, "event_label_meta"):
            self.event_label_meta = []
        self._normalize_event_label_meta(len(self.event_table_data))
        if 0 <= index < len(self.event_label_meta):
            old_state = self.event_label_meta[index].get("review_state", "UNREVIEWED")
            self.event_label_meta[index]["review_state"] = state
            if old_state != state:
                event_label = ""
                if hasattr(self, "event_table_data") and index < len(self.event_table_data):
                    event_label = self.event_table_data[index][0] if self.event_table_data[index] else ""
                self._change_log.record_review_status_change(index, old_state, state, event_label)
            # CRITICAL FIX (Bug #2): Mark sample state dirty when review state changes
            self._sample_state_dirty = True
            self._update_review_notice_visibility()

    def _mark_row_edited(self, index: int) -> None:
        self._set_review_state_for_row(index, REVIEW_EDITED)
        controller = getattr(self, "event_table_controller", None)
        if controller is not None:
            controller.set_review_states(self._current_review_states())

    def _sample_values_at_time(
        self, time_sec: float
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Sample ID/OD/Avg P/Set P at a given time using current trace data."""
        if self.trace_data is None or "Time (s)" not in self.trace_data.columns:
            return (None, None, None, None)
        try:
            target_time = float(time_sec)
        except Exception:
            return (None, None, None, None)

        times = self.trace_data["Time (s)"].to_numpy()
        if times.size == 0:
            return (None, None, None, None)

        idx = int(np.argmin(np.abs(times - target_time)))

        def _sample_column(label: str | None) -> float | None:
            if not label or label not in self.trace_data.columns:
                return None
            try:
                value = self.trace_data[label].iloc[idx]
            except Exception:
                return None
            if pd.isna(value):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        id_val = _sample_column("Inner Diameter")
        od_val = _sample_column("Outer Diameter")
        avg_val = _sample_column(self._trace_label_for("p_avg"))
        set_val = _sample_column(self._trace_label_for("p2"))
        return (id_val, od_val, avg_val, set_val)

    def _insert_event_meta(self, index: int, meta: dict[str, Any] | None = None) -> None:
        payload = self._with_default_review_state(meta)
        if not hasattr(self, "event_label_meta"):
            self.event_label_meta = [payload]
            # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
            self._sample_state_dirty = True
            return
        index = max(0, min(int(index), len(self.event_label_meta)))
        self.event_label_meta.insert(index, payload)
        # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
        self._sample_state_dirty = True

    def _delete_event_meta(self, index: int) -> None:
        if not hasattr(self, "event_label_meta"):
            return
        if 0 <= index < len(self.event_label_meta):
            del self.event_label_meta[index]
            # CRITICAL FIX (Bug #2): Mark sample state dirty when event metadata changes
            self._sample_state_dirty = True

    def _fallback_restore_review_states(self, event_count: int) -> None:
        """
        CRITICAL FIX (Bug #3): Fallback method to restore review states when deserialization fails.

        Tries multiple strategies:
        1. Load review states from current sample's events DataFrame (if Bug #1 fix is in place)
        2. Preserve existing event_label_meta if available
        3. Default to UNREVIEWED as last resort

        Args:
            event_count: Number of events to create metadata for
        """
        review_states_restored = False

        # Strategy 1: Try to load from current sample's events DataFrame
        try:
            if (
                hasattr(self, "current_sample")
                and self.current_sample is not None
                and hasattr(self.current_sample, "events_data")
                and self.current_sample.events_data is not None
            ):
                events_df = self.current_sample.events_data
                if "review_state" in events_df.columns:
                    states = events_df["review_state"].tolist()
                    if len(states) == event_count:
                        self.event_label_meta = [{"review_state": str(state)} for state in states]
                        review_states_restored = True
                        log.info(f"Restored {len(states)} review states from events DataFrame")
        except Exception as e:
            log.debug(f"Could not restore review states from DataFrame: {e}")

        # Strategy 2: Preserve existing event_label_meta if it exists and has the right length
        if not review_states_restored and hasattr(self, "event_label_meta"):
            existing = getattr(self, "event_label_meta", [])
            if isinstance(existing, list) and len(existing) == event_count:
                # Keep existing - already has review states
                log.info(f"Preserved {len(existing)} existing review states from event_label_meta")
                review_states_restored = True

        # Strategy 3: Default to UNREVIEWED as last resort
        if not review_states_restored:
            self.event_label_meta = [
                self._with_default_review_state(None) for _ in range(event_count)
            ]
            log.warning(
                f"Could not restore review states - defaulted {event_count} events to UNREVIEWED"
            )

    def _sync_event_data_from_table(self) -> None:
        """Recompute cached event arrays, metadata, and annotation entries."""

        rows = list(getattr(self, "event_table_data", []) or [])
        self._normalize_event_label_meta(len(rows))
        if not getattr(self, "_suppress_event_table_sync", False):
            self._apply_event_rows_to_current_sample(rows)
        if not rows:
            self.event_labels = []
            self.event_times = []
            self.event_frames = []
            self.event_annotations = []
            self.event_metadata = []
            self.event_label_meta = []
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_annotation_entries([])
                plot_host.set_events([], labels=[], label_meta=[])
                self._refresh_event_annotation_artists()
        else:
            self.event_text_objects = []
            self._apply_current_style()
        self._refresh_overview_events()
        return

    def _apply_event_rows_to_current_sample(self, rows: list[tuple]) -> None:
        """Update the current sample's UI state and DataFrame to mirror ``rows``."""

        sample = getattr(self, "current_sample", None)
        if sample is None:
            return
        normalized = normalize_event_table_rows(rows)
        if normalized:
            df = events_dataframe_from_rows(normalized)
            sample.events_data = df
        else:
            sample.events_data = None
        state = getattr(sample, "ui_state", None)
        if not isinstance(state, dict):
            state = {}
            sample.ui_state = state
        state["event_table_data"] = list(normalized or [])
        self.project_state[id(sample)] = state

    def apply_event_label_overrides(
        self,
        labels: Sequence[str],
        metadata: Sequence[Mapping[str, Any]],
    ) -> None:
        """Apply per-event label overrides coming from the style editor."""

        if labels is None or metadata is None:
            return
        new_labels = list(labels)
        existing_states = self._current_review_states()
        new_meta = [self._with_default_review_state(entry) for entry in metadata]
        if not new_labels:
            # No events – clear helpers and bail.
            self.event_labels = []
            self.event_label_meta = []
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_events([], labels=[], label_meta=[])
                plot_host.set_annotation_entries([])
                self._refresh_event_annotation_artists()
            return

        if len(new_labels) != len(self.event_labels):
            log.warning(
                "Event label override count mismatch (%s vs %s); ignoring update.",
                len(new_labels),
                len(self.event_labels),
            )
            return

        self.event_labels = new_labels
        if len(new_meta) < len(new_labels):
            new_meta.extend(
                self._with_default_review_state(None)
                for _ in range(len(new_labels) - len(new_meta))
            )
        elif len(new_meta) > len(new_labels):
            new_meta = new_meta[: len(new_labels)]
        for idx, state in enumerate(existing_states):
            if idx < len(new_meta):
                new_meta[idx]["review_state"] = state
        self.event_label_meta = [self._with_default_review_state(entry) for entry in new_meta]
        self._normalize_event_label_meta(len(self.event_label_meta))

        # Update table rows in-place so the UI reflects any text edits.
        for idx, label in enumerate(new_labels):
            if idx >= len(self.event_table_data):
                continue
            row = list(self.event_table_data[idx])
            if not row:
                continue
            row[0] = label
            self.event_table_data[idx] = tuple(row)
            controller = getattr(self, "event_table_controller", None)
            if controller is not None:
                controller.update_row(idx, self.event_table_data[idx])
        controller = getattr(self, "event_table_controller", None)
        if controller is not None:
            controller.set_review_states(self._current_review_states())

        # Rebuild annotations and tooltips to reflect the new text.
        annotations: list[AnnotationSpec] = []
        metadata_entries: list[dict[str, Any]] = []
        has_outer = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        for idx, label in enumerate(new_labels):
            time_val = float(self.event_times[idx]) if idx < len(self.event_times) else 0.0
            annotations.append(AnnotationSpec(time_s=time_val, label=label))

            tooltip_parts = [label, f"{time_val:.2f} s"]
            if idx < len(self.event_table_data):
                row = self.event_table_data[idx]
                try:
                    id_val = float(row[2])
                    if np.isfinite(id_val):
                        tooltip_parts.append(f"ID {id_val:.2f} µm")
                except Exception:
                    log.debug("Failed to parse inner diameter value", exc_info=True)
                od_idx = 3 if has_outer and len(row) >= 5 else None
                if od_idx is not None:
                    try:
                        od_val = float(row[od_idx])
                        if np.isfinite(od_val):
                            tooltip_parts.append(f"OD {od_val:.2f} µm")
                    except Exception:
                        log.debug("Failed to parse outer diameter value", exc_info=True)
            metadata_entries.append(
                {
                    "time": time_val,
                    "label": label,
                    "tooltip": " · ".join(part for part in tooltip_parts if part),
                }
            )

        self.event_annotations = annotations
        self.event_metadata = metadata_entries

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_events(
                self.event_times,
                labels=self.event_labels,
                label_meta=self.event_label_meta,
            )
            visible_entries = self.event_annotations if self._annotation_lane_visible else []
            plot_host.set_annotation_entries(visible_entries)
            self._refresh_event_annotation_artists()
        self.mark_session_dirty()

    def _set_event_table_visible(self, visible: bool, *, source: str = "user") -> None:
        event_table = getattr(self, "event_table", None)
        event_table_action = getattr(self, "event_table_action", None)
        if event_table is None:
            return
        action = getattr(self, "event_table_action", None)
        if event_table.isVisible() != visible:
            event_table.setVisible(visible)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        log.debug("UI: Event table visibility updated to %s (source=%s)", visible, source)
        if source == "user":
            self._on_view_state_changed(reason="event table visibility")

    def toggle_event_table(self, checked: bool):
        self._set_event_table_visible(bool(checked), source="user")

    def _apply_snapshot_view_mode(self, should_show: bool) -> None:
        stack = getattr(self, "snapshot_stack", None)
        widget = getattr(self, "snapshot_widget", None)
        if stack is not None:
            if widget is not None:
                stack.setCurrentWidget(widget)
            stack.setVisible(bool(should_show))

        if widget is not None:
            widget.setVisible(bool(should_show))

        self._update_snapshot_panel_layout()
        self._update_snapshot_rotation_controls()

    def _snapshot_has_image(self) -> bool:
        widget = getattr(self, "snapshot_widget", None)
        if widget is not None and hasattr(widget, "has_image"):
            with contextlib.suppress(Exception):
                return bool(widget.has_image())
        return bool(self.snapshot_frames)

    def _update_snapshot_panel_layout(self) -> None:
        layout = getattr(self, "_right_panel_layout", None)
        snapshot_card = getattr(self, "snapshot_card", None)
        table_card = getattr(self, "event_table_card", None)
        if layout is None or snapshot_card is None or table_card is None:
            return

        has_image = self._snapshot_has_image()
        viewer_enabled = bool(
            getattr(self, "snapshot_viewer_action", None)
            and self.snapshot_viewer_action.isChecked()
        )
        show_snapshot = bool(has_image and viewer_enabled)
        snapshot_card.setVisible(show_snapshot)

    def _update_snapshot_rotation_controls(self) -> None:
        """Enable or disable rotation buttons based on viewer state."""

        buttons = (
            getattr(self, "rotate_ccw_btn", None),
            getattr(self, "rotate_cw_btn", None),
            getattr(self, "rotate_reset_btn", None),
        )
        can_rotate = (
            bool(self.snapshot_frames)
            and getattr(self, "snapshot_widget", None) is not None
            and self._snapshot_view_visible()
        )
        for btn in buttons:
            if btn is None:
                continue
            btn.setEnabled(can_rotate)

    def toggle_snapshot_viewer(self, checked: bool, *, source: str = "user"):
        if self._snapshot_panel_disabled_by_env:
            if self.snapshot_viewer_action and self.snapshot_viewer_action.isChecked():
                self.snapshot_viewer_action.blockSignals(True)
                self.snapshot_viewer_action.setChecked(False)
                self.snapshot_viewer_action.blockSignals(False)
            return
        if not checked:
            self._snapshot_viewer_pending_open = False
        if checked and not self.snapshot_frames and isinstance(self.current_sample, SampleN):
            stack = self._ensure_sample_snapshots_loaded(self.current_sample)
            if stack is not None:
                try:
                    self.load_snapshots(stack)
                except Exception:
                    log.debug("Failed to initialise snapshot viewer", exc_info=True)
                    self.snapshot_frames = []
                else:
                    self._snapshot_viewer_pending_open = False
            else:
                self._snapshot_viewer_pending_open = True
        has_snapshots = bool(self.snapshot_frames)
        should_show = bool(checked) and has_snapshots
        desired_action_state = bool(checked) and (
            has_snapshots or self._snapshot_viewer_pending_open
        )

        if (
            self.snapshot_viewer_action
            and self.snapshot_viewer_action.isChecked() != desired_action_state
        ):
            self.snapshot_viewer_action.blockSignals(True)
            self.snapshot_viewer_action.setChecked(desired_action_state)
            self.snapshot_viewer_action.blockSignals(False)

        self._apply_snapshot_view_mode(should_show)

        if not should_show:
            self.set_snapshot_metadata_visible(False)

        self._update_metadata_button_state()
        if source == "user":
            self._on_view_state_changed(reason="snapshot viewer visibility")

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

    def _avg_pressure_channel_available(self) -> bool:
        if self.trace_data is None:
            return False
        label = self._trace_label_for("p_avg")
        if label not in self.trace_data.columns:
            return False
        series = self.trace_data[label]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _set_pressure_channel_available(self) -> bool:
        if self.trace_data is None:
            return False
        label = self._trace_label_for("p2")
        sample = getattr(self, "current_sample", None)
        columns = list(self.trace_data.columns)
        in_columns = label in columns
        log.info(
            "UI: set-pressure availability check for %s -> label=%r in_columns=%s",
            getattr(sample, "name", "<unknown>") if sample is not None else "<none>",
            label,
            in_columns,
        )
        effective_label = label
        canonical_label = getattr(project_module, "P2_CANONICAL_LABEL", "Set Pressure (mmHg)")
        if not in_columns and canonical_label in self.trace_data.columns:
            log.info(
                "UI: set-pressure fallback -> using canonical %r even though label=%r",
                canonical_label,
                label,
            )
            effective_label = canonical_label
            in_columns = True

        if not in_columns:
            log.debug(
                "SET PRESSURE UNAVAILABLE: expected '%s' in %s",
                label,
                list(self.trace_data.columns),
            )
            return False
        series = self.trace_data[effective_label]
        try:
            return not series.isna().all()
        except Exception:
            return True

    def _trace_label_for(self, key: str) -> str:
        default_labels = {
            "p_avg": "Avg Pressure (mmHg)",
            "p2": "Set Pressure (mmHg)",
        }
        sample = getattr(self, "current_sample", None)
        if sample is not None:
            labels = getattr(sample, "trace_column_labels", None)
            if isinstance(labels, dict):
                candidate = labels.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    if key == "p2":
                        return project_module.normalize_p2_label(candidate)
                    return candidate
        if key == "p2":
            return project_module.normalize_p2_label(default_labels.get(key, "Set Pressure (mmHg)"))
        return default_labels.get(key, key)

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
        outer_supported: bool | None = None,
    ) -> None:
        if outer_supported is None:
            outer_supported = self._outer_channel_available()
        if self.id_toggle_act is not None and self.id_toggle_act.isChecked() != inner_on:
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

    def _reset_channel_view_defaults(self) -> None:
        """Ensure freshly loaded traces start with ID and OD visible when available."""

        has_outer = self._outer_channel_available()
        self._apply_toggle_state(True, True, outer_supported=has_outer)
        if self.avg_pressure_toggle_act is not None:
            self.avg_pressure_toggle_act.blockSignals(True)
            self.avg_pressure_toggle_act.setChecked(True)
            self.avg_pressure_toggle_act.blockSignals(False)
        if self.set_pressure_toggle_act is not None:
            self.set_pressure_toggle_act.blockSignals(True)
            self.set_pressure_toggle_act.setChecked(False)
            self.set_pressure_toggle_act.blockSignals(False)

    def _rebuild_channel_layout(
        self, inner_on: bool, outer_on: bool, *, redraw: bool = True
    ) -> None:
        # PyQtGraph: always build tracks for available data; show/hide via visibility flags
        render_backend = None
        if hasattr(self, "plot_host") and self.plot_host is not None:
            with contextlib.suppress(Exception):
                render_backend = self.plot_host.get_render_backend()

        if render_backend == "pyqtgraph":
            specs: list[ChannelTrackSpec] = []
            has_outer = self._outer_channel_available()
            has_avg = self._avg_pressure_channel_available()
            has_set = self._set_pressure_channel_available()

            specs.append(
                ChannelTrackSpec(
                    track_id="inner",
                    component="inner",
                    label="Inner Diameter (µm)",
                    height_ratio=1.0,
                )
            )

            if has_outer:
                specs.append(
                    ChannelTrackSpec(
                        track_id="outer",
                        component="outer",
                        label="Outer Diameter (µm)",
                        height_ratio=1.0,
                    )
                )

            if has_avg:
                specs.append(
                    ChannelTrackSpec(
                        track_id="avg_pressure",
                        component="avg_pressure",
                        label=self._trace_label_for("p_avg"),
                        height_ratio=1.0,
                    )
                )

            if has_set:
                specs.append(
                    ChannelTrackSpec(
                        track_id="set_pressure",
                        component="set_pressure",
                        label=self._trace_label_for("p2"),
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

            host = self.plot_host
            # Align host visibility flags with requested toggle states (or defaults)
            host.set_channel_visible("inner", bool(inner_on))
            host.set_channel_visible("outer", bool(outer_on and has_outer))
            if has_avg:
                desired_avg = (
                    self.avg_pressure_toggle_act.isChecked()
                    if hasattr(self, "avg_pressure_toggle_act") and self.avg_pressure_toggle_act
                    else True
                )
                host.set_channel_visible("avg_pressure", bool(desired_avg))
            else:
                host.set_channel_visible("avg_pressure", False)
            if has_set:
                desired_set = (
                    self.set_pressure_toggle_act.isChecked()
                    if hasattr(self, "set_pressure_toggle_act") and self.set_pressure_toggle_act
                    else False  # Default: hide Set Pressure track
                )
                host.set_channel_visible("set_pressure", bool(desired_set))
            else:
                host.set_channel_visible("set_pressure", False)

            sample = getattr(self, "current_sample", None)
            avg_track_added = has_avg
            set_track_added = has_set
            layout_ready = bool(getattr(self, "_layout_log_ready", False))
            if (
                sample is not None
                and layout_ready
                and getattr(self, "_last_track_layout_sample_id", None) != id(sample)
            ):
                sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
                log.info(
                    "UI: Track layout for sample %s -> inner=%s outer=%s avg_pressure=%s set_pressure=%s",
                    sample_name,
                    True,
                    has_outer,
                    avg_track_added,
                    set_track_added,
                )
                self._last_track_layout_sample_id = id(sample)

            self._unbind_primary_axis_callbacks()
            host.ensure_channels(specs)

            inner_track = host.track("inner")
            outer_track = host.track("outer") if has_outer else None
            avg_track = host.track("avg_pressure") if has_avg else None
            set_track = host.track("set_pressure") if has_set else None

            ordered_tracks = [t for t in (inner_track, outer_track, avg_track, set_track) if t]
            primary_track = next((t for t in ordered_tracks if t.is_visible()), None) or (
                ordered_tracks[0] if ordered_tracks else None
            )

            self.ax = primary_track.ax if primary_track else None
            self.ax2 = outer_track.ax if inner_track and outer_track else None
            self._bind_primary_axis_callbacks()
            self._init_hover_artists()

            self.trace_line = inner_track.primary_line if inner_track else None
            self.inner_line = self.trace_line
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
            self._sync_track_visibility_from_host()
            if redraw and hasattr(self, "canvas"):
                self.canvas.draw_idle()
            return

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

        # Add pressure tracks if available and toggled on
        avg_pressure_on = (
            self.avg_pressure_toggle_act.isChecked()
            if hasattr(self, "avg_pressure_toggle_act") and self.avg_pressure_toggle_act is not None
            else True
        )
        set_pressure_on = (
            self.set_pressure_toggle_act.isChecked()
            if hasattr(self, "set_pressure_toggle_act") and self.set_pressure_toggle_act is not None
            else False
        )

        if self._avg_pressure_channel_available() and avg_pressure_on:
            log.debug("Track layout: adding avg_pressure track spec")
            specs.append(
                ChannelTrackSpec(
                    track_id="avg_pressure",
                    component="avg_pressure",
                    label=self._trace_label_for("p_avg"),
                    height_ratio=1.0,
                )
            )
        if self._set_pressure_channel_available() and set_pressure_on:
            log.debug("Track layout: adding set_pressure track spec")
            specs.append(
                ChannelTrackSpec(
                    track_id="set_pressure",
                    component="set_pressure",
                    label=self._trace_label_for("p2"),
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

        sample = getattr(self, "current_sample", None)
        avg_track_added = any(spec.track_id == "avg_pressure" for spec in specs)
        set_track_added = any(spec.track_id == "set_pressure" for spec in specs)
        layout_ready = bool(getattr(self, "_layout_log_ready", False))
        if (
            sample is not None
            and layout_ready
            and getattr(self, "_last_track_layout_sample_id", None) != id(sample)
        ):
            sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
            log.info(
                "UI: Track layout for sample %s -> inner=%s outer=%s avg_pressure=%s set_pressure=%s",
                sample_name,
                inner_on,
                outer_on,
                avg_track_added,
                set_track_added,
            )
            self._last_track_layout_sample_id = id(sample)

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
        # PyQtGraph: drive host visibility without rebuilding tracks
        render_backend = None
        if hasattr(self, "plot_host") and self.plot_host is not None:
            with contextlib.suppress(Exception):
                render_backend = self.plot_host.get_render_backend()
        if render_backend == "pyqtgraph":
            self._apply_channel_toggle_pyqtgraph(channel, checked)
            return

        # For pressure channels, simply rebuild the layout
        if channel in ("avg_pressure", "set_pressure"):
            # Get current inner/outer state
            previous_inner, previous_outer = self._current_channel_presence()
            inner_on = (
                self.id_toggle_act.isChecked() if self.id_toggle_act is not None else previous_inner
            )
            outer_on = (
                self.od_toggle_act.isChecked() if self.od_toggle_act is not None else previous_outer
            )

            self._rebuild_channel_layout(inner_on, outer_on)
            self._refresh_zoom_window()
            self._invalidate_sample_state_cache()
            self._apply_event_table_column_contract()
            return

        # Original logic for inner/outer channels
        outer_supported = self._outer_channel_available()
        previous_inner, previous_outer = self._current_channel_presence()
        inner_on = (
            self.id_toggle_act.isChecked() if self.id_toggle_act is not None else previous_inner
        )
        outer_on = (
            self.od_toggle_act.isChecked() if self.od_toggle_act is not None else previous_outer
        )

        if channel == "inner":
            inner_on = bool(checked)
        else:
            if checked and not outer_supported:
                self._apply_toggle_state(inner_on, False, outer_supported=False)
                self._update_trace_controls_state()
                self._apply_event_table_column_contract()
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
        self._apply_event_table_column_contract()

        if inner_on == current_inner and outer_on == current_outer:
            return

        self._rebuild_channel_layout(inner_on, outer_on)
        self._refresh_zoom_window()
        self._on_view_state_changed(reason="channel toggle")

    def toggle_inner_diameter(self, checked: bool):
        self._apply_channel_toggle("inner", checked)

    def toggle_outer_diameter(self, checked: bool):
        self._apply_channel_toggle("outer", checked)

    def toggle_avg_pressure(self, checked: bool):
        self._apply_channel_toggle("avg_pressure", checked)

    def toggle_set_pressure(self, checked: bool):
        self._apply_channel_toggle("set_pressure", checked)

    def _apply_channel_toggle_pyqtgraph(self, channel: str, checked: bool) -> None:
        host = getattr(self, "plot_host", None)
        if host is None:
            return

        if channel in ("avg_pressure", "set_pressure"):
            host.set_channel_visible(channel, bool(checked))
        else:
            has_outer = self._outer_channel_available()
            inner_visible = host.is_channel_visible("inner")
            outer_visible = host.is_channel_visible("outer") if has_outer else False

            if channel == "inner":
                inner_visible = bool(checked)
            else:
                if checked and not has_outer:
                    self._apply_toggle_state(inner_visible, False, outer_supported=False)
                    self._update_trace_controls_state()
                    return
                outer_visible = bool(checked)

            inner_visible, outer_visible = self._ensure_valid_channel_selection(
                inner_visible,
                outer_visible,
                toggled=channel,
                outer_supported=has_outer,
            )

            self._apply_toggle_state(inner_visible, outer_visible, outer_supported=has_outer)
            host.set_channel_visible("inner", inner_visible)
            host.set_channel_visible("outer", outer_visible)

        self._sync_track_visibility_from_host()
        self._update_trace_controls_state()
        self._refresh_plot_legend()
        if hasattr(self, "canvas"):
            with contextlib.suppress(Exception):
                self.canvas.draw_idle()
        self._on_view_state_changed(reason="channel toggle")
        self._apply_event_table_column_contract()

    def toggle_fullscreen(self, checked: bool = False):
        """Toggle fullscreen mode.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self.statusBar().show()
        else:
            self.showFullScreen()
            self.menuBar().hide()
            self.statusBar().hide()

    def show_shortcuts(self, checked: bool = False):
        """Show keyboard shortcuts dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        from vasoanalyzer.ui.dialogs.keyboard_shortcuts_dialog import (
            KeyboardShortcutsDialog,
        )

        dialog = KeyboardShortcutsDialog(self)
        dialog.exec_()

    def open_user_manual(self, checked: bool = False):
        """Open user manual PDF.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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

    def show_release_notes(self, checked: bool = False):
        """Show release notes.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # You could load a local CHANGELOG.md and display it
        QMessageBox.information(
            self,
            "Release Notes",
            (
                f"Release {APP_VERSION}:\n"
                "- PyQtGraph renderer is now the primary backend for all trace views.\n"
                "- Multi-track stacked layout: Inner Diameter, Outer Diameter, Pressure, and Set Pressure synchronized in a single scrollable view.\n"
                "- Point Editor with undo/redo and audit history.\n"
                "- Excel Mapper with flexible template writer for any workbook layout.\n"
                "- VasoTracker v1 and v2 import with automatic sibling file discovery.\n"
                "- Dataset package import/export between .vaso projects.\n"
                "- Thread-safe background sample loading.\n"
                "- General stability and logging improvements.\n"
            ),
        )

    def show_about(self, checked: bool = False):
        """Show about dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        QMessageBox.information(
            self,
            "About VasoAnalyzer",
            f"VasoAnalyzer {APP_VERSION}\nhttps://github.com/vr-oj/VasoAnalyzer",
        )

    def show_tutorial(self, checked: bool = False):
        """Show tutorial dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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
        # Skip if launched via WindowManager (home dashboard handles onboarding)
        if self.window_manager is not None:
            return
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
        self.onboarding_settings.setValue("general/show_onboarding", "false" if hide else "true")

        if getattr(self, "_welcome_dialog", None) is dialog:
            self._welcome_dialog = None

    # ========================= NEW MENU ACTIONS ======================================

    def delete_selected_events(self, checked: bool = False, *, indices: list[int] | None = None):
        """Delete selected events."""
        if indices is None:
            selection = self.event_table.selectionModel()
            if selection is None:
                return
            indices = sorted({index.row() for index in selection.selectedRows()})
        if not indices:
            return

        events_desc = [
            self.event_table_data[idx][0]
            for idx in indices
            if 0 <= idx < len(self.event_table_data)
        ]
        if len(indices) == 1 and events_desc:
            prompt = f"Delete event: {events_desc[0]}?"
        else:
            prompt = f"Delete {len(indices)} selected events?"

        confirm = QMessageBox.question(
            self,
            "Delete Event" if len(indices) == 1 else "Delete Events",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._delete_events_by_indices(indices)

    def _delete_events_by_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        indices = sorted(
            set(idx for idx in indices if 0 <= idx < len(self.event_table_data)),
            reverse=True,
        )
        if not indices:
            return

        for idx in indices:
            del self.event_labels[idx]
            if idx < len(self.event_times):
                del self.event_times[idx]
            if idx < len(self.event_frames):
                del self.event_frames[idx]
            self._delete_event_meta(idx)
            self.event_table_data.pop(idx)
            self.event_table_controller.remove_row(idx)

        self.update_plot()
        self._update_excel_controls()
        self.mark_session_dirty()

    def _update_theme_action_checks(self, mode: str) -> None:
        """Sync Color Theme menu checkboxes with the active mode."""

        scheme = (mode or "light").lower()
        # Map old system/auto to light
        if scheme in ("system", "auto"):
            scheme = "light"

        action_map = {
            "light": getattr(self, "action_theme_light", None),
            "dark": getattr(self, "action_theme_dark", None),
        }

        for key, action in action_map.items():
            if isinstance(action, QAction):
                action.setChecked(scheme == key)

    def _update_action_icons(self) -> None:
        """Update action icons to match current theme (light/dark)."""
        # Update trace toggle button icons
        if hasattr(self, "id_toggle_act"):
            self.id_toggle_act.setIcon(QIcon(self.icon_path("ID.svg")))
        if hasattr(self, "od_toggle_act"):
            self.od_toggle_act.setIcon(QIcon(self.icon_path("OD.svg")))
        if hasattr(self, "avg_pressure_toggle_act"):
            self.avg_pressure_toggle_act.setIcon(QIcon(self.icon_path("P.svg")))
        if hasattr(self, "set_pressure_toggle_act"):
            self.set_pressure_toggle_act.setIcon(QIcon(self.icon_path("SP.svg")))

        # Update toolbar action icons
        if hasattr(self, "home_action"):
            self.home_action.setIcon(QIcon(self.icon_path("Home.svg")))
        if hasattr(self, "save_session_action"):
            self.save_session_action.setIcon(QIcon(self.icon_path("Save.svg")))
        if hasattr(self, "review_events_action"):
            self.review_events_action.setIcon(QIcon(self.icon_path("review-events.svg")))
        if hasattr(self, "excel_action"):
            self.excel_action.setIcon(QIcon(self.icon_path("excel-mapper.svg")))
        if hasattr(self, "sync_clip_action"):
            self.sync_clip_action.setIcon(QIcon(self.icon_path("play_arrow.svg")))

    def apply_theme(self, mode: str, *, persist: bool = False) -> None:
        """Apply light or dark theme at runtime and refresh all UI widgets."""
        log.debug(
            "[THEME-DEBUG] App.apply_theme called with mode=%r, persist=%s, id(self)=%s",
            mode,
            persist,
            id(self),
        )

        scheme = (mode or "light").lower()
        # Map old system/auto to light for backwards compatibility
        if scheme in ("system", "auto"):
            scheme = "light"

        if persist:
            try:
                from vasoanalyzer.ui import theme as theme_module

                theme_module.apply_theme(scheme, persist=True)
            except Exception:
                return
            return

        self._active_theme_mode = scheme
        current_name = (
            CURRENT_THEME.get("name") if isinstance(CURRENT_THEME, dict) else CURRENT_THEME
        )
        log.debug("[THEME-DEBUG] CURRENT_THEME=%r", current_name)

        self._update_theme_action_checks(self._active_theme_mode)
        self._update_action_icons()
        self._apply_status_bar_theme()
        apply_data_page_style = getattr(self, "_apply_data_page_style", None)
        if callable(apply_data_page_style):
            apply_data_page_style()

        if hasattr(self, "home_page") and self.home_page is not None:
            apply_theme = getattr(self.home_page, "apply_theme", None)
            if callable(apply_theme):
                apply_theme(scheme)
            else:
                self.home_page._apply_stylesheet()

        if hasattr(self, "event_table") and self.event_table is not None:
            apply_theme = getattr(self.event_table, "apply_theme", None)
            if callable(apply_theme):
                apply_theme()

        review_panel = getattr(self, "review_panel", None)
        apply_review_theme = getattr(review_panel, "apply_theme", None)
        if callable(apply_review_theme):
            with contextlib.suppress(Exception):
                apply_review_theme()

        if hasattr(self, "_apply_event_table_card_theme"):
            with contextlib.suppress(Exception):
                self._apply_event_table_card_theme()

        project_dock = getattr(self, "project_dock", None)
        apply_project_theme = getattr(project_dock, "apply_theme", None)
        if callable(apply_project_theme):
            apply_project_theme()

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "apply_theme"):
            with contextlib.suppress(Exception):
                plot_host.apply_theme()
        overview = getattr(self, "overview_strip", None)
        if overview is not None and hasattr(overview, "apply_theme"):
            with contextlib.suppress(Exception):
                overview.apply_theme()
        nav_bar = getattr(self, "trace_nav_bar", None)
        if nav_bar is not None and hasattr(nav_bar, "apply_theme"):
            with contextlib.suppress(Exception):
                nav_bar.apply_theme()

        for dock_name in (
            "layout_dock",
            "preset_library_dock",
            "advanced_style_dock",
            "export_queue_dock",
        ):
            dock = getattr(self, dock_name, None)
            apply_method = getattr(dock, "_apply_theme", None)
            if not callable(apply_method):
                apply_method = getattr(dock, "apply_theme", None)
            if callable(apply_method):
                apply_method()

        for dock_name in ("scope_dock", "zoom_dock"):
            dock = getattr(self, dock_name, None)
            apply_method = getattr(dock, "apply_theme", None)
            if callable(apply_method):
                apply_method()

        if hasattr(self, "_apply_snapshot_theme"):
            with contextlib.suppress(Exception):
                self._apply_snapshot_theme()

        toolbar = getattr(self, "toolbar", None)
        if toolbar is not None and hasattr(toolbar, "apply_theme"):
            with contextlib.suppress(Exception):
                toolbar.apply_theme()

        if hasattr(self, "_apply_primary_toolbar_theme"):
            with contextlib.suppress(Exception):
                self._apply_primary_toolbar_theme()

        # Force complete repaint to ensure all widgets pick up new colors
        self.update()
        QApplication.processEvents()
        log.debug("[THEME-DEBUG] Forced repaint after theme change")

    # View Menu Actions
    def set_color_scheme(self, scheme: str):
        """Set application color scheme (light or dark)."""
        # Apply immediately; no restart required
        self.apply_theme(scheme, persist=True)

    # Window Menu Actions
    def toggle_maximize(self, checked: bool = False):
        """Toggle window maximized state."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def raise_all_windows(self, checked: bool = False):
        """Bring all VasoAnalyzer windows to front (macOS)."""
        app = QApplication.instance()
        if app:
            for window in app.topLevelWidgets():
                if window.isWindow() and not window.isHidden():
                    window.raise_()
                    window.activateWindow()

    # [C] ========================= UI SETUP (initUI) ======================================
    def _initUI_legacy(self):
        from vasoanalyzer.ui.shell.init_ui import init_ui as _init_ui

        return _init_ui(self)

    def _create_primary_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Primary")
        toolbar.setObjectName("PrimaryToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setContextMenuPolicy(Qt.PreventContextMenu)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        self.home_action = QAction(QIcon(self.icon_path("Home.svg")), "Home", self)
        self.home_action.setToolTip("Home Dashboard")
        self.home_action.triggered.connect(self.show_home_dashboard)
        self.home_action.setVisible(False)
        toolbar.addAction(self.home_action)

        self.load_trace_action = QAction(
            QIcon(self.icon_path("folder-open.svg")), "Import Trace CSV…", self
        )
        self.load_trace_action.setToolTip("Import a CSV trace file and auto-detect matching events")
        self.load_trace_action.setShortcut(QKeySequence.Open)
        self.load_trace_action.triggered.connect(self._handle_load_trace)

        self.load_snapshot_action = QAction(
            QIcon(self.icon_path("empty-box.svg")), "Import Result TIFF…", self
        )
        self.load_snapshot_action.setToolTip("Import a _Result.tiff snapshot stack")
        self.load_snapshot_action.triggered.connect(self.load_snapshot)

        self.excel_action = QAction(
            QIcon(self.icon_path("excel-mapper.svg")), "Excel mapper…", self
        )
        self.excel_action.setToolTip("Excel mapper…")
        self.excel_action.setEnabled(False)
        self.excel_action.triggered.connect(self.open_excel_mapping_dialog)

        self.review_events_action = QAction(
            QIcon(self.icon_path("review-events.svg")), "Review Events", self
        )
        self.review_events_action.setToolTip("Review Events")
        self.review_events_action.setShortcut("Ctrl+Shift+R")
        self.review_events_action.setEnabled(False)
        self.review_events_action.triggered.connect(self._toggle_review_mode)

        edit_points_action = getattr(self, "actEditPoints", None)

        self.sync_clip_action = QAction(
            QIcon(self.icon_path("play_arrow.svg")), "Export Clip…", self
        )
        self.sync_clip_action.setToolTip("Export a synchronized trace + TIFF animation (GIF).")
        self.sync_clip_action.setEnabled(False)
        self.sync_clip_action.triggered.connect(self.open_sync_clip_exporter)

        self.load_events_action = QAction(
            QIcon(self.icon_path("folder-plus.svg")), "Import Events CSV…", self
        )
        self.load_events_action.setToolTip("Import an events table without reloading the trace")
        self.load_events_action.setEnabled(False)
        self.load_events_action.triggered.connect(self._handle_load_events)

        import_button = QToolButton(self)
        import_button.setObjectName("ImportDataButton")
        import_button.setText("Open Data…")
        import_button.setToolTip("Open Data…")
        import_button.setToolButtonStyle(toolbar.toolButtonStyle())
        import_button.setIconSize(toolbar.iconSize())
        if not self.load_trace_action.icon().isNull():
            import_button.setIcon(self.load_trace_action.icon())
        import_menu = QMenu(import_button)
        import_menu.addAction(self.load_trace_action)
        if hasattr(self, "action_import_vasotracker_v1"):
            import_menu.addAction(self.action_import_vasotracker_v1)
        if hasattr(self, "action_import_vasotracker_v2"):
            import_menu.addAction(self.action_import_vasotracker_v2)
        import_menu.addSeparator()
        import_menu.addAction(self.load_events_action)
        import_menu.addAction(self.load_snapshot_action)
        import_menu.addAction(self.action_import_folder)
        if hasattr(self, "action_import_dataset_pkg"):
            import_menu.addAction(self.action_import_dataset_pkg)
        if hasattr(self, "action_import_dataset_from_project"):
            import_menu.addAction(self.action_import_dataset_from_project)
        import_button.setMenu(import_menu)
        import_button.setPopupMode(QToolButton.InstantPopup)
        self.save_session_action = QAction(QIcon(self.icon_path("Save.svg")), "Save Project", self)
        self.save_session_action.setToolTip("Save Project")
        self.save_session_action.setShortcut(QKeySequence.Save)
        self.save_session_action.triggered.connect(self.save_project_file)

        self.welcome_action = QAction(
            QIcon(self.icon_path("info-circle.svg")), "Welcome guide", self
        )
        self.welcome_action.setToolTip("Open the welcome guide")
        self.welcome_action.triggered.connect(lambda: self.show_welcome_guide(modal=False))

        toolbar.addWidget(import_button)
        toolbar.addAction(self.save_session_action)
        toolbar.addSeparator()
        toolbar.addAction(self.review_events_action)
        if edit_points_action is not None:
            toolbar.addAction(edit_points_action)
        toolbar.addAction(self.excel_action)
        toolbar.addAction(self.sync_clip_action)
        for action in (
            self.review_events_action,
            edit_points_action,
            self.excel_action,
            self.sync_clip_action,
        ):
            if action is None:
                continue
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setProperty("isWorkflowAction", True)

        toolbar.addWidget(self.trace_file_label)

        return toolbar

    def _update_toolbar_compact_mode(self, width: int | None = None) -> None:
        if width is None:
            width = self.width()
        compact = width < 1152
        style = Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextUnderIcon
        for toolbar in (
            getattr(self, "primary_toolbar", None),
            getattr(self, "toolbar", None),
        ):
            if toolbar is None:
                continue
            toolbar.setToolButtonStyle(style)
        plot_toolbar = getattr(self, "toolbar", None)
        if plot_toolbar is not None:
            view_button = getattr(plot_toolbar, "_view_menu_button", None)
            if isinstance(view_button, QToolButton):
                view_button.setToolButtonStyle(style)
                view_button.setIconSize(plot_toolbar.iconSize())
        self._update_primary_toolbar_button_widths(compact)
        self._update_plot_toolbar_signal_button_widths(compact)
        self._normalize_plot_toolbar_button_geometry()

    def _primary_toolbar_buttons(self) -> list[QToolButton]:
        toolbar = getattr(self, "primary_toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        seen: set[int] = set()
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if isinstance(widget, QToolButton) and id(widget) not in seen:
                buttons.append(widget)
                seen.add(id(widget))
        for widget in toolbar.findChildren(QToolButton):
            if id(widget) in seen:
                continue
            buttons.append(widget)
            seen.add(id(widget))
        return buttons

    def _plot_toolbar_signal_buttons(self) -> list[QToolButton]:
        toolbar = getattr(self, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        for action in (
            getattr(self, "id_toggle_act", None),
            getattr(self, "od_toggle_act", None),
            getattr(self, "avg_pressure_toggle_act", None),
            getattr(self, "set_pressure_toggle_act", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            if isinstance(widget, QToolButton):
                widget.setProperty("isSignalToggle", True)
                buttons.append(widget)
        return buttons

    def _plot_toolbar_row2_buttons(self) -> list[QToolButton]:
        toolbar = getattr(self, "toolbar", None)
        if toolbar is None:
            return []
        buttons: list[QToolButton] = []
        seen: set[int] = set()

        def add_button(button: QToolButton | None) -> None:
            if not isinstance(button, QToolButton):
                return
            if id(button) in seen:
                return
            buttons.append(button)
            seen.add(id(button))

        for action in (
            getattr(self, "actPgPan", None),
            getattr(self, "actBoxZoom", None),
            getattr(self, "actPan", None),
            getattr(self, "actZoom", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            add_button(widget)

        for action in (
            getattr(toolbar, "_quick_zoom_all_action", None),
            getattr(toolbar, "_quick_zoom_back_action", None),
            getattr(toolbar, "_quick_zoom_in_action", None),
            getattr(toolbar, "_quick_zoom_out_action", None),
            getattr(toolbar, "_quick_autoscale_action", None),
        ):
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            add_button(widget)

        add_button(getattr(toolbar, "_view_menu_button", None))

        for button in self._plot_toolbar_signal_buttons():
            add_button(button)

        add_button(getattr(self, "project_toggle_btn", None))
        add_button(getattr(self, "metadata_toggle_btn", None))

        return buttons

    def _normalize_plot_toolbar_button_geometry(self) -> None:
        buttons = self._plot_toolbar_row2_buttons()
        if not buttons:
            return
        for button in buttons:
            button.setMinimumHeight(0)
            button.setMaximumHeight(16777215)

        heights = []
        for button in buttons:
            hint = button.sizeHint()
            if hint.isValid():
                heights.append(hint.height())
        if not heights:
            return

        target_height = max(heights)
        for button in buttons:
            button.setMinimumHeight(target_height)
            button.setMaximumHeight(target_height)
            button.updateGeometry()

    def _lock_plot_toolbar_row2_order(self) -> None:
        toolbar = getattr(self, "toolbar", None)
        if toolbar is None:
            return

        nav_pan = getattr(self, "actPgPan", None) or getattr(self, "actPan", None)
        nav_select = getattr(self, "actBoxZoom", None) or getattr(self, "actZoom", None)
        view_action = getattr(toolbar, "_view_menu_action", None)
        quick_actions = [
            getattr(toolbar, "_quick_zoom_all_action", None),
            getattr(toolbar, "_quick_zoom_back_action", None),
            getattr(toolbar, "_quick_zoom_in_action", None),
            getattr(toolbar, "_quick_zoom_out_action", None),
            getattr(toolbar, "_quick_autoscale_action", None),
        ]

        signal_actions = [
            getattr(self, "id_toggle_act", None),
            getattr(self, "od_toggle_act", None),
            getattr(self, "avg_pressure_toggle_act", None),
            getattr(self, "set_pressure_toggle_act", None),
        ]

        panel_actions = [
            getattr(self, "project_toggle_action", None),
            getattr(self, "metadata_toggle_action", None),
        ]

        separators = [action for action in toolbar.actions() if action.isSeparator()]
        sep_nav_signals = separators[0] if len(separators) > 0 else toolbar.addSeparator()
        sep_signals_panels = separators[1] if len(separators) > 1 else toolbar.addSeparator()

        # Row 2 canonical order:
        # Pan, Select, Zoom All, Zoom Back, Zoom In, Zoom Out, Autoscale, More...
        # | Inner, Outer, Pressure, Set Pressure | Project, Details.
        ordered_actions = [
            nav_pan,
            nav_select,
            *quick_actions,
            view_action,
            sep_nav_signals,
            *signal_actions,
            sep_signals_panels,
            *panel_actions,
        ]

        before_action = None
        for action in reversed([act for act in ordered_actions if act is not None]):
            toolbar.insertAction(before_action, action)
            before_action = action

    def _update_plot_toolbar_signal_button_widths(self, compact: bool) -> None:
        buttons = self._plot_toolbar_signal_buttons()
        if not buttons:
            return
        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        if compact:
            return

        widths = []
        for button in buttons:
            hint = button.sizeHint()
            if hint.isValid():
                widths.append(hint.width())
        if not widths:
            return

        target_width = min(max(widths), 140)
        for button in buttons:
            button.setMinimumWidth(target_width)
            button.setMaximumWidth(target_width)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            button.updateGeometry()

    def _update_primary_toolbar_button_widths(self, compact: bool) -> None:
        buttons = self._primary_toolbar_buttons()
        if not buttons:
            return

        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextUnderIcon
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

        target_width = min(max(widths), 140)
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
        if visible:
            self._refresh_zoom_window()

    def _on_scope_visibility_changed(self, visible: bool) -> None:
        if visible and self.scope_dock and self.trace_model is not None:
            self.scope_dock.set_trace_model(self.trace_model)

    def _serialize_plot_layout(self) -> dict | None:
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
        # Fast path: if the pending layout matches the current layout, skip work.
        try:
            current = self._serialize_plot_layout()
            if (
                isinstance(layout, dict)
                and isinstance(current, dict)
                and layout.get("order") == current.get("order")
                and dict(layout.get("height_ratios", {})) == dict(current.get("height_ratios", {}))
                and dict(layout.get("visibility", {})) == dict(current.get("visibility", {}))
            ):
                self._pending_plot_layout = None
                return
        except Exception:
            log.debug("Plot layout update check failed", exc_info=True)
        specs_map = {spec.track_id: spec for spec in self.plot_host.channel_specs()}
        order = None
        height_ratios = None
        visibility = None
        if isinstance(layout, dict):
            order = layout.get("order")
            height_ratios = layout.get("height_ratios", {}) or {}
            visibility = layout.get("visibility")
        else:
            order = getattr(layout, "order", None)
            height_ratios = getattr(layout, "height_ratios", {}) or {}
            visibility = getattr(layout, "visibility", None)
        if not order:
            order = list(specs_map.keys())
        if height_ratios is None:
            height_ratios = {}
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
        if visibility and isinstance(visibility, Mapping):
            for track_id, visible in visibility.items():
                applied = False
                with contextlib.suppress(Exception):
                    self.plot_host.set_channel_visible(track_id, bool(visible))
                    applied = True
                if applied:
                    continue
                if hasattr(self.plot_host, "track"):
                    track = None
                    with contextlib.suppress(Exception):
                        track = self.plot_host.track(track_id)
                    if track is not None:
                        with contextlib.suppress(Exception):
                            track.set_visible(bool(visible))
            self._sync_track_visibility_from_host()
        self._pending_plot_layout = None

    def _build_data_header(self):
        header = QFrame()
        header.setObjectName("DataHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        return header

    def _create_next_step_hint_widget(self, parent: QWidget) -> QWidget:
        container = QFrame(parent)
        container.setObjectName("NextStepHint")
        container.setFrameShape(QFrame.StyledPanel)
        container.setFrameShadow(QFrame.Raised)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        label = QLabel("Next step: Add data to this project", container)
        label.setObjectName("NextStepHintLabel")

        btn_import_folder = QPushButton("Import folder…", container)
        btn_import_folder.setCursor(Qt.PointingHandCursor)
        btn_import_folder.clicked.connect(self._handle_import_folder)

        btn_import_trace = QPushButton("Import trace/events file…", container)
        btn_import_trace.setCursor(Qt.PointingHandCursor)
        btn_import_trace.clicked.connect(self._handle_load_trace)

        dismiss_btn = QToolButton(container)
        dismiss_btn.setText("Dismiss")
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.setAutoRaise(True)
        dismiss_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        dismiss_btn.clicked.connect(self._dismiss_next_step_hint)

        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(btn_import_folder)
        layout.addWidget(btn_import_trace)
        layout.addWidget(dismiss_btn)

        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
        bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("window_bg", "#ffffff"))
        text = CURRENT_THEME.get("text", "#000000")
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        status = CURRENT_THEME.get("text_disabled", text)
        container.setStyleSheet(
            f"#NextStepHint {{"
            f"background: {bg};"
            f"border: 1px dashed {border};"
            "border-radius: 12px;"
            "}"
            "#NextStepHint QLabel#NextStepHintLabel {"
            f"color: {text};"
            "font-weight: 600;"
            "}"
        )
        container.hide()
        return container

    def _project_has_imported_data(self, project: Project | None) -> bool:
        if self._next_step_hint_widget is None:
            return False
        if project is None or not getattr(project, "experiments", None):
            return False
        for experiment in project.experiments:
            for sample in getattr(experiment, "samples", []) or []:
                if getattr(sample, "trace_path", None):
                    return True
                if getattr(sample, "trace_data", None) is not None:
                    return True
                if getattr(sample, "dataset_id", None) is not None:
                    return True
        return False

    def _update_next_step_hint(self) -> None:
        if self._next_step_hint_widget is None:
            return
        widget = getattr(self, "_next_step_hint_widget", None)
        if widget is None:
            return
        project = getattr(self, "current_project", None)
        if project is None or self._next_step_hint_dismissed:
            widget.hide()
            return
        if self._project_has_imported_data(project):
            widget.hide()
            return
        widget.show()

    def _dismiss_next_step_hint(self) -> None:
        if self._next_step_hint_widget is None:
            return
        self._next_step_hint_dismissed = True
        if self._next_step_hint_widget is not None:
            self._next_step_hint_widget.hide()

    def _build_home_page_legacy(self, target_widget: QWidget | None = None):
        from vasoanalyzer.ui.panels.home_page import HomePage

        return HomePage(self)

    def home_open_data(self) -> None:
        from PyQt5.QtCore import QTimer

        action = getattr(self, "load_trace_action", None)
        if action is not None:
            QTimer.singleShot(0, action.trigger)
        else:
            QTimer.singleShot(0, self._handle_load_trace)

    def home_open_project(self) -> None:
        from PyQt5.QtCore import QTimer

        action = getattr(self, "action_open_project", None)
        if action is not None:
            QTimer.singleShot(0, action.trigger)
        else:
            QTimer.singleShot(0, self.open_project_file)

    def show_import_data_menu(self, checked: bool = False, anchor: QWidget | None = None) -> None:
        if anchor is None:
            sender = self.sender()
            if isinstance(sender, QWidget):
                anchor = sender
            else:
                anchor = self

        menu = QMenu(anchor)
        for action in (
            getattr(self, "action_open_trace", None),
            getattr(self, "action_import_events", None),
            getattr(self, "action_open_tiff", None),
            getattr(self, "action_import_folder", None),
            getattr(self, "action_import_dataset_pkg", None),
            getattr(self, "action_import_dataset_from_project", None),
        ):
            if action is not None:
                menu.addAction(action)

        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

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
        button.clicked.connect(lambda _checked=False: callback())
        self._apply_button_style(button)
        return button

    def _set_toolbars_visible(self, visible: bool) -> None:
        for name in ("primary_toolbar", "toolbar"):
            toolbar = getattr(self, name, None)
            if isinstance(toolbar, QToolBar):
                toolbar.setVisible(visible)

    def show_home_screen(self, checked: bool = False):
        """Open the Home dashboard window.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self.show_home_dashboard()

    def show_analysis_workspace(self):
        self.stack.setCurrentWidget(self.data_page)
        if hasattr(self, "home_action") and self.home_action is not None:
            self.home_action.setVisible(True)
        self._update_home_resume_button()
        self._set_toolbars_visible(True)
        self._update_plot_empty_state()

    def show_home_dashboard(self) -> None:
        manager = getattr(self, "window_manager", None)
        if manager is None:
            log.debug("Home dashboard unavailable (no WindowManager)")
            return
        manager.show_dashboard()

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
            tooltip = f"Return to workspace · {status}" if status else "Return to workspace"
            self.home_resume_btn.setToolTip(tooltip)
        else:
            self.home_resume_btn.setToolTip("Return to workspace")

        if hasattr(self, "home_page") and self.home_page is not None:
            self.home_page._update_responsive_layout()

    @staticmethod
    def _apply_button_style(button: QPushButton) -> None:
        button.style().unpolish(button)
        button.style().polish(button)

    def _shared_button_css(self) -> str:
        border = CURRENT_THEME["grid_color"]
        text = CURRENT_THEME["text"]
        button_bg = CURRENT_THEME.get("button_bg", CURRENT_THEME["window_bg"])
        button_hover_bg = CURRENT_THEME.get(
            "button_hover_bg", CURRENT_THEME.get("selection_bg", button_bg)
        )
        button_active_bg = CURRENT_THEME.get("button_active_bg", button_hover_bg)
        accent = CURRENT_THEME.get("accent", button_active_bg)
        accent_hover = CURRENT_THEME.get("accent_fill", accent)
        button_bg = CURRENT_THEME.get("button_bg", CURRENT_THEME["window_bg"])
        primary_bg = accent
        primary_hover = accent_hover
        primary_text = "#ffffff"
        secondary_bg = button_bg
        secondary_hover = button_hover_bg
        return f"""
QPushButton[isPrimary="true"] {{
    background-color: {primary_bg};
    color: {primary_text};
    border: 2px solid {primary_bg};
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 600;
}}
QPushButton[isPrimary="true"]:hover {{
    background-color: {primary_hover};
    border: 2px solid {primary_hover};
}}
QPushButton[isPrimary="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {button_active_bg};
    padding: 9px 20px 7px 20px;
}}
QPushButton[isSecondary="true"] {{
    background-color: {secondary_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 500;
}}
QPushButton[isSecondary="true"]:hover {{
    background-color: {secondary_hover};
    border: 2px solid {border};
    padding: 7px 19px;
}}
QPushButton[isSecondary="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {border};
    padding: 8px 19px 6px 19px;
}}
QPushButton[isGhost="true"] {{
    background-color: transparent;
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 20px;
}}
QPushButton[isGhost="true"]:hover {{
    background-color: {button_hover_bg};
    border: 2px solid {border};
    padding: 7px 19px;
}}
QPushButton[isGhost="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {border};
    padding: 8px 19px 6px 19px;
}}
"""

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
        button_text: str | None = None,
        callback=None,
        icon_name: str = "folder-open.svg",
    ) -> None:
        placeholder = QLabel(message)
        placeholder.setObjectName("CardPlaceholder")
        placeholder.setWordWrap(True)
        layout.addWidget(placeholder)
        if button_text and callback:
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
        row.setToolTip(path)
        row.setCursor(Qt.PointingHandCursor)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        def _row_click(event):
            if event.button() == Qt.LeftButton:
                open_callback()
            event.accept()

        row.mousePressEvent = _row_click

        open_btn = QPushButton(label)
        open_btn.setProperty("isGhost", True)
        open_btn.setMinimumHeight(32)
        open_btn.setToolTip(path)
        open_btn.clicked.connect(lambda _checked=False: open_callback())
        self._apply_button_style(open_btn)
        row_layout.addWidget(open_btn, 1)

        remove_btn = QToolButton()
        remove_btn.setObjectName("HomeRemoveButton")
        remove_btn.setAutoRaise(True)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        remove_btn.setText("Remove")
        remove_btn.setToolTip(f"Remove {path}")
        remove_btn.clicked.connect(lambda _checked=False: remove_callback())
        row_layout.addWidget(remove_btn, 0, Qt.AlignRight)

        return row

    def _set_status_source(self, label: str, tooltip: str = "") -> None:
        self._status_base_label = label
        self.trace_file_label.setToolTip(tooltip)
        self._update_status_chip()

    def _update_status_chip(self, label: str | None = None, tooltip: str | None = None) -> None:
        if label is not None:
            self._status_base_label = label
        if tooltip is not None:
            self.trace_file_label.setToolTip(tooltip)

        full_text = getattr(self, "_status_base_label", "No trace loaded")
        if self.session_dirty:
            full_text = f"● {full_text}"

        if self.trace_file_label.width() > 0:
            metrics = QFontMetrics(self.trace_file_label.font())
            display = metrics.elidedText(full_text, Qt.ElideMiddle, self.trace_file_label.width())
        else:
            display = full_text
        self.trace_file_label.setText(display)
        self.trace_file_label.setProperty("_full_status_text", full_text)

    def _reset_session_dirty(self, *, reason: str | None = None) -> None:
        if self.session_dirty:
            log.info(
                "Project dirty state changed: False (reason=%s, path=%s)",
                reason or "reset",
                getattr(self.current_project, "path", None) or "<unsaved>",
            )
        self.session_dirty = False
        self._update_status_chip()

    def mark_session_dirty(self, reason: str | None = None) -> None:
        if not self.session_dirty:
            self.session_dirty = True
            log.info(
                "Project dirty state changed: True (reason=%s, path=%s)",
                reason or "unspecified",
                getattr(self.current_project, "path", None) or "<unsaved>",
            )
            self._update_status_chip()
        # Invalidate cached state since something changed
        self._invalidate_sample_state_cache()

    # ------------------------------------------------------------------ progress bar helpers
    def show_progress(self, message: str = "", maximum: int = 100) -> None:
        """Show progress bar in status bar with optional message."""
        self._progress_bar.setMaximum(maximum)
        self._progress_bar.setValue(0)
        (
            self._progress_bar.setFormat(f"{message} %p%")
            if message
            else self._progress_bar.setFormat("%p%")
        )
        self._progress_bar.show()
        if message:
            self.statusBar().showMessage(message)

    def update_progress(self, value: int) -> None:
        """Update progress bar value."""
        if self._progress_bar.isVisible():
            self._progress_bar.setValue(value)
            # Progress bar updates automatically - no need to force event processing

    def hide_progress(self) -> None:
        """Hide progress bar."""
        self._progress_bar.hide()
        self._progress_bar.setValue(0)

    def _start_sample_load_progress(self, sample_name: str) -> None:
        """Begin status-bar progress indication for sample load."""
        if self._progress_bar is None:
            return
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(True)
        self._progress_bar.setFormat(f"Loading {sample_name}…")
        if self.statusBar() is not None:
            self.statusBar().showMessage(f"Loading {sample_name}…")

    def _update_sample_load_progress(self, percent: int, label: str) -> None:
        """Update status-bar sample load progress."""
        if self._progress_bar is None:
            return
        if self._progress_bar.minimum() == 0 and self._progress_bar.maximum() == 0:
            self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(max(0, min(percent, 100)))
        self._progress_bar.setFormat(f"{label}… %p%")

    def _finish_sample_load_progress(self) -> None:
        """Hide status-bar sample load progress."""
        if self._progress_bar is None:
            return
        self._progress_bar.setVisible(False)
        if self.statusBar() is not None:
            self.statusBar().clearMessage()

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
                insert_at = (
                    trace.columns.get_loc(inner_raw_name) + 1
                    if inner_raw_name in trace.columns
                    else trace.columns.get_loc("Inner Diameter") + 1
                )
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
                insert_at = (
                    trace.columns.get_loc(outer_raw_name) + 1
                    if outer_raw_name in trace.columns
                    else trace.columns.get_loc("Outer Diameter") + 1
                )
                trace.insert(insert_at, outer_clean_name, outer_values.copy())

        trace.attrs.setdefault("edit_log", [])
        return trace

    def _update_trace_sync_state(self) -> None:
        """Cache canonical trace time + frame mappings for sync."""

        self.trace_time = None
        self.frame_numbers = None
        self.frame_number_to_trace_idx = {}
        self.tiff_page_to_trace_idx = {}
        self.tiff_page_times = []
        self.tiff_page_times_valid = False
        self.snapshot_interval_median = None
        self.frame_trace_time = None
        self.frame_trace_index = None
        self.trace_time_exact = None
        self.frame_times = []

        if self.trace_data is None:
            return

        if "Time (s)" in self.trace_data.columns:
            with contextlib.suppress(Exception):
                self.trace_time = self.trace_data["Time (s)"].to_numpy(dtype=float)
        if "Time_s_exact" in self.trace_data.columns:
            with contextlib.suppress(Exception):
                self.trace_time_exact = self.trace_data["Time_s_exact"].to_numpy(dtype=float)

        if "FrameNumber" in self.trace_data.columns:
            try:
                series = pd.to_numeric(self.trace_data["FrameNumber"], errors="coerce")
                self.frame_numbers = series.to_numpy()
                self.frame_number_to_trace_idx = {
                    int(fn): int(i) for i, fn in enumerate(self.frame_numbers) if pd.notna(fn)
                }
            except Exception:
                log.debug("Unable to build frame→trace mapping", exc_info=True)
        if "TiffPage" in self.trace_data.columns:
            try:
                tiff_series = pd.to_numeric(self.trace_data["TiffPage"], errors="coerce")
                if "Saved" in self.trace_data.columns:
                    saved_mask = (
                        pd.to_numeric(self.trace_data["Saved"], errors="coerce")
                        .fillna(0)
                        .to_numpy()
                        > 0
                    )
                    tiff_series = tiff_series.where(saved_mask)
                self.tiff_page_to_trace_idx = {
                    int(tp): int(i) for i, tp in enumerate(tiff_series.to_numpy()) if pd.notna(tp)
                }
            except Exception:
                log.debug("Unable to build TIFF page→trace mapping", exc_info=True)

        self._refresh_tiff_page_times()

    def _refresh_tiff_page_times(self, *, expected_page_count: int | None = None) -> None:
        """Derive canonical TIFF page times from trace data when available."""

        self.tiff_page_times = []
        self.tiff_page_times_valid = False
        self.snapshot_interval_median = None

        if self.trace_data is None:
            return

        sample = getattr(self, "current_sample", None)
        page_count_hint = expected_page_count
        if page_count_hint is None and self.snapshot_total_frames:
            page_count_hint = int(self.snapshot_total_frames)
        result = derive_tiff_page_times(self.trace_data, expected_page_count=page_count_hint)
        self.tiff_page_times = result.tiff_page_times
        self.tiff_page_times_valid = bool(result.valid)
        self.snapshot_interval_median = result.median_interval_s

        if not result.tiff_page_times and sample is not None:
            meta = dict(sample.import_metadata or {})
            timebase_block = dict(meta.get("timebase") or {})
            tiff_block = dict(timebase_block.get("tiff") or {})
            stored_times = tiff_block.get("tiff_page_times")
            if isinstance(stored_times, list) and stored_times:
                self.tiff_page_times = stored_times
                self.tiff_page_times_valid = bool(tiff_block.get("tiff_page_times_valid", False))
                stored_median = tiff_block.get("snapshot_interval_median_s")
                if stored_median is not None:
                    self.snapshot_interval_median = float(stored_median)

        warning_key = None
        if page_count_hint is not None and result.warnings:
            warning_key = (
                tuple(result.warnings),
                result.page_count,
                result.time_column,
            )
        if warning_key and warning_key != self._last_tiff_page_time_warning_key:
            for warning in result.warnings:
                log.warning("TIFF page time mapping: %s", warning)
            self._last_tiff_page_time_warning_key = warning_key
        elif page_count_hint is not None and not result.warnings:
            self._last_tiff_page_time_warning_key = None

        self._update_snapshot_sync_toggle()

        if sample is None:
            return

        meta = dict(sample.import_metadata or {})
        timebase_block = dict(meta.get("timebase") or {})
        tiff_block = dict(timebase_block.get("tiff") or {})
        if result.tiff_page_times:
            tiff_block["tiff_page_times"] = result.tiff_page_times
            tiff_block["tiff_page_times_valid"] = bool(result.valid)
            tiff_block["tiff_page_time_warnings"] = list(result.warnings)
            tiff_block["snapshot_interval_median_s"] = (
                float(result.median_interval_s) if result.median_interval_s is not None else None
            )
            tiff_block["tiff_page_time_column"] = result.time_column
        elif "tiff_page_times" not in tiff_block:
            tiff_block["tiff_page_times"] = None
        timebase_block["tiff"] = tiff_block
        meta["timebase"] = timebase_block
        sample.import_metadata = meta

    def _get_trace_model_for_sample(self, sample: SampleN | None) -> TraceModel:
        """Return a TraceModel for the current trace_data, using a per-dataset cache."""

        if self.trace_data is None:
            raise ValueError("trace_data is not available")

        dsid = getattr(sample, "dataset_id", None) if sample is not None else None
        if dsid is not None:
            cached = self._trace_model_cache.get(dsid)
            if cached is not None:
                return cached

        model = TraceModel.from_dataframe(self.trace_data)
        if dsid is not None:
            self._trace_model_cache[dsid] = model
        return model

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
                    self.trace_data.loc[:, "Outer Diameter (raw)"] = (
                        self.trace_model.outer_raw.copy()
                    )
                else:
                    self.trace_data["Outer Diameter (raw)"] = self.trace_model.outer_raw.copy()

        serialized_log = serialize_edit_log(self.trace_model.edit_log)
        self.trace_data.attrs["edit_log"] = serialized_log

        if self.current_sample is not None:
            self.current_sample.edit_history = serialized_log
            self.current_sample.change_log = self._change_log.serialize()
            synchronized = self.trace_data.copy()
            synchronized.attrs = dict(self.trace_data.attrs)
            self.current_sample.trace_data = synchronized

    def _refresh_views_after_edit(self) -> None:
        if self.trace_model is None:
            return
        current_window: tuple[float, float] | None = None
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
            with contextlib.suppress(Exception):
                self._refresh_zoom_window()
        self._update_trace_controls_state()
        if hasattr(self, "canvas"):
            with contextlib.suppress(Exception):
                self.canvas.draw_idle()

    def _apply_point_editor_actions(
        self, actions: Sequence, summary: SessionSummary | None
    ) -> None:
        if self.trace_model is None or not actions:
            return
        self.trace_model.apply_actions(actions)
        self._change_log.record_point_edits(actions)
        self._sync_trace_dataframe_from_model()
        self._refresh_views_after_edit()
        self.mark_session_dirty()

        if summary is None:
            point_count = sum(getattr(action, "count", 0) for action in actions)
            total_samples = max(len(self.trace_model.inner_full), 1)
            percent = (point_count / total_samples) * 100.0
            channel_label = ", ".join(
                sorted(
                    {
                        "ID" if getattr(action, "channel", "inner") == "inner" else "OD"
                        for action in actions
                    }
                )
            )
            message = (
                f"Edited {point_count} points ({percent:.3f}%) [{channel_label}] — Undo available"
            )
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
        channels = ", ".join(
            sorted({"ID" if action.channel == "inner" else "OD" for action in removed})
        )
        self.statusBar().showMessage(f"Point edits undone ({point_count} pts) [{channels}]", 6000)

    def _on_edit_points_triggered(self) -> None:
        if self.trace_model is None:
            return

        # Only offer channels that are currently visible
        channels: list[tuple[str, str]] = []
        has_outer = self.trace_model.outer_full is not None
        inner_visible = self.id_toggle_act is None or self.id_toggle_act.isChecked()
        outer_visible = has_outer and (self.od_toggle_act is None or self.od_toggle_act.isChecked())

        if inner_visible:
            channels.append(("inner", "Inner Diameter (ID)"))
        if outer_visible:
            channels.append(("outer", "Outer Diameter (OD)"))

        if not channels:
            QMessageBox.information(
                self,
                "Edit Points",
                "No visible channels to edit.\nTurn on a trace in the plot, then try again.",
            )
            return

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
        if window is not None and not self._channel_has_data_in_window(channel, window):
            QMessageBox.information(
                self,
                "No data in current window",
                "There are no points in the currently visible time window.\n"
                "Zoom into a region with data, or reset the view, then try again.",
            )
            return
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

    def _channel_has_data_in_window(self, channel: str, window: tuple[float, float]) -> bool:
        """Return True if the channel has any samples inside the window."""
        if self.trace_model is None:
            return False
        time_full = getattr(self.trace_model, "time_full", None)
        if time_full is None:
            return False

        series = None
        channel_key = str(channel).strip().lower()
        if channel_key == "inner":
            series = getattr(self.trace_model, "inner_full", None)
        elif channel_key == "outer":
            series = getattr(self.trace_model, "outer_full", None)
        if series is None:
            return False

        x0, x1 = float(window[0]), float(window[1])
        xmin, xmax = (x0, x1) if x0 <= x1 else (x1, x0)
        mask = (time_full >= xmin) & (time_full <= xmax)
        if not np.any(mask):
            return False

        window_values = series[mask]
        return bool(np.any(np.isfinite(window_values)))

    def _update_window_title(self) -> None:
        base = f"VasoAnalyzer {APP_VERSION}"
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

    def _compute_sampling_rate(self, trace_df: pd.DataFrame | None) -> float | None:
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
                    "No recent imports yet. Import data to see them listed here.",
                )
            else:
                for path in paths[:3]:
                    name = os.path.basename(path) or path
                    row = self._make_home_recent_row(
                        name,
                        path,
                        lambda checked=False, p=path: self.load_trace_and_events(
                            p, source="recent_session"
                        ),
                        partial(self.remove_recent_file, path),
                    )
                    layout.addWidget(row)
            layout.addStretch()

        if hasattr(self, "home_recent_projects_layout"):
            layout = self.home_recent_projects_layout
            self._clear_layout(layout)
            projects = [p for p in (self.recent_projects or []) if isinstance(p, str) and p]
            has_projects = bool(projects)
            if hasattr(self, "home_clear_projects_button"):
                self.home_clear_projects_button.setVisible(has_projects)
                self.home_clear_projects_button.setEnabled(has_projects)
            if not has_projects:
                self._add_home_placeholder(
                    layout,
                    "No recent projects yet. Open or create a project to see it here.",
                    "Open project…",
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

    def _build_toolbar_for_canvas_legacy(self, canvas):
        from vasoanalyzer.ui.shell.toolbars import (
            build_canvas_toolbar as _build_canvas_toolbar,
        )

        return _build_canvas_toolbar(self, canvas)

    def build_toolbar_for_canvas(self, *args, **kwargs):
        from vasoanalyzer.ui.shell.toolbars import (
            build_canvas_toolbar as _build_toolbar_adapter,
        )

        return _build_toolbar_adapter(self, *args, **kwargs)

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
        mode = "pan"
        if sender is getattr(self, "actBoxZoom", None) or sender is getattr(self, "actZoom", None):
            mode = "rect"
        self._update_nav_mode_indicator(mode)

    def _set_plot_cursor_for_mode(self, mode: str) -> None:
        target = None
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "widget"):
            with contextlib.suppress(Exception):
                target = plot_host.widget()
        if target is None:
            target = getattr(self, "canvas", None)
        if target is None:
            return
        cursor = Qt.OpenHandCursor if mode == "pan" else Qt.CrossCursor
        with contextlib.suppress(Exception):
            target.setCursor(QCursor(cursor))

    def _update_nav_mode_indicator(self, mode: str) -> None:
        normalized = "rect" if str(mode).lower() == "rect" else "pan"
        label = "Select" if normalized == "rect" else "Pan"
        review_controller = getattr(self, "review_controller", None)
        review_active = bool(
            review_controller is not None
            and hasattr(review_controller, "is_active")
            and review_controller.is_active()
        )
        if review_active:
            label = f"{label} · Review"
        with contextlib.suppress(Exception):
            self.statusBar().showMessage(f"Mode: {label}", 2500)
        self._set_plot_cursor_for_mode(normalized)

    def _set_nav_actions_for_mode(self, mode: str) -> None:
        normalized = "rect" if str(mode).lower() == "rect" else "pan"
        pan_action = getattr(self, "actPgPan", None) or getattr(self, "actPan", None)
        select_action = getattr(self, "actBoxZoom", None) or getattr(self, "actZoom", None)
        if pan_action is not None:
            pan_action.blockSignals(True)
            pan_action.setChecked(normalized == "pan")
            pan_action.blockSignals(False)
        if select_action is not None:
            select_action.blockSignals(True)
            select_action.setChecked(normalized == "rect")
            select_action.blockSignals(False)

    def _focus_is_plot_widget(self) -> bool:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "widget"):
            return False
        with contextlib.suppress(Exception):
            host_widget = plot_host.widget()
            focus_widget = QApplication.focusWidget()
            if focus_widget is None:
                return True
            if focus_widget is host_widget:
                return True
            return bool(host_widget.isAncestorOf(focus_widget))
        return False

    def _on_grid_action_triggered(self) -> None:
        self.toggle_grid()
        self._sync_grid_action()

    def _on_zoom_in_triggered(self) -> None:
        """Handle zoom in button click - zoom in around the current cursor."""
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return

        is_pyqtgraph = bool(
            hasattr(plot_host, "get_render_backend")
            and plot_host.get_render_backend() == "pyqtgraph"
        )

        if is_pyqtgraph:
            from vasoanalyzer.ui.plots.pyqtgraph_nav_math import ZOOM_STEP_IN

            if hasattr(plot_host, "zoom_x_at"):
                self._set_xrange_source("zoom.in", None)
                plot_host.zoom_x_at(None, factor=ZOOM_STEP_IN)
                return
            if hasattr(plot_host, "zoom_at"):
                self._set_xrange_source("zoom.in", None)
                plot_host.zoom_at(None, factor=ZOOM_STEP_IN)
                return

        window = plot_host.current_window()
        full_range = plot_host.full_range()
        if window is None or full_range is None:
            return

        start, end = float(window[0]), float(window[1])
        full_start, full_end = float(full_range[0]), float(full_range[1])
        span = end - start
        full_span = full_end - full_start
        if span <= 0 or full_span <= 0:
            return

        center = (start + end) / 2.0
        min_span = full_span / 1000.0
        new_span = max(span * 0.5, min_span)
        new_span = min(new_span, full_span)

        half_span = new_span / 2.0
        new_start = center - half_span
        new_end = center + half_span

        if new_start < full_start:
            new_start = full_start
            new_end = full_start + new_span
        if new_end > full_end:
            new_end = full_end
            new_start = full_end - new_span

        if new_end <= new_start or new_span <= 0:
            new_start, new_end = full_start, full_end

        self._set_xrange_source("zoom.in", (new_start, new_end))
        self._apply_time_window((new_start, new_end))

    def _on_zoom_out_triggered(self) -> None:
        """Handle zoom out button click - zoom out around the current cursor."""
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return

        is_pyqtgraph = bool(
            hasattr(plot_host, "get_render_backend")
            and plot_host.get_render_backend() == "pyqtgraph"
        )

        if is_pyqtgraph:
            from vasoanalyzer.ui.plots.pyqtgraph_nav_math import ZOOM_STEP_OUT

            if hasattr(plot_host, "zoom_x_at"):
                self._set_xrange_source("zoom.out", None)
                plot_host.zoom_x_at(None, factor=ZOOM_STEP_OUT)
                return
            if hasattr(plot_host, "zoom_at"):
                self._set_xrange_source("zoom.out", None)
                plot_host.zoom_at(None, factor=ZOOM_STEP_OUT)
                return

        window = plot_host.current_window()
        full_range = plot_host.full_range()
        if window is None or full_range is None:
            return

        start, end = float(window[0]), float(window[1])
        full_start, full_end = float(full_range[0]), float(full_range[1])
        span = end - start
        full_span = full_end - full_start
        if full_span <= 0:
            return

        center = (start + end) / 2.0
        new_span = full_span if span <= 0 else min(span * 2.0, full_span)

        half_span = new_span / 2.0
        new_start = center - half_span
        new_end = center + half_span

        if new_start < full_start:
            new_start = full_start
            new_end = full_start + new_span
        if new_end > full_end:
            new_end = full_end
            new_start = full_end - new_span

        if new_end <= new_start or new_span <= 0:
            new_start, new_end = full_start, full_end

        self._set_xrange_source("zoom.out", (new_start, new_end))
        self._apply_time_window((new_start, new_end))

    def _apply_time_span_preset(self, span_seconds: float) -> None:
        full_range = self._trace_full_range()
        if full_range is None:
            return
        plot_host = getattr(self, "plot_host", None)
        window = None
        if plot_host is not None and hasattr(plot_host, "current_window"):
            with contextlib.suppress(Exception):
                window = plot_host.current_window()
        if window is None and self.ax is not None:
            with contextlib.suppress(Exception):
                window = self.ax.get_xlim()
        if window is None:
            return

        try:
            center = 0.5 * (float(window[0]) + float(window[1]))
        except (TypeError, ValueError, IndexError):
            return

        span = max(float(span_seconds), 1e-9)
        fr0, fr1 = float(full_range[0]), float(full_range[1])
        max_span = fr1 - fr0
        if max_span <= 0:
            return
        if span >= max_span:
            self._last_x_window_width_s = max_span
            self._scrollbar_drag_width_s = None
            self._set_xrange_source("time_preset.full", (fr0, fr1))
            self._apply_time_window((fr0, fr1))
            return

        start = center - span * 0.5
        end = center + span * 0.5
        if start < fr0:
            start = fr0
            end = fr0 + span
        if end > fr1:
            end = fr1
            start = fr1 - span
        self._last_x_window_width_s = span
        self._scrollbar_drag_width_s = None
        self._set_xrange_source(
            f"time_preset.{span_seconds:.0f}s",
            (start, end),
        )
        self._apply_time_window((start, end))

    def _on_zoom_back_triggered(self) -> None:
        """Handle zoom back button - step back through zoom history using scaleHistory(-1)."""
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            return

        is_pyqtgraph = bool(
            hasattr(plot_host, "get_render_backend")
            and plot_host.get_render_backend() == "pyqtgraph"
        )

        if not is_pyqtgraph:
            # Matplotlib backend doesn't have scaleHistory, fallback to reset
            if hasattr(plot_host, "full_range"):
                full_range = plot_host.full_range()
                if full_range is not None:
                    self._set_xrange_source(
                        "zoom.back",
                        (float(full_range[0]), float(full_range[1])),
                    )
                    self._apply_time_window(full_range)
            return

        # PyQtGraph: use ViewBox.scaleHistory(-1) to step back in zoom history
        # Get the primary (first visible) track's ViewBox
        tracks = list(plot_host.iter_tracks()) if hasattr(plot_host, "iter_tracks") else []
        if not tracks:
            return

        # Find first visible track
        primary_track = None
        for track in tracks:
            if hasattr(track, "is_visible") and track.is_visible():
                primary_track = track
                break
        if primary_track is None:
            primary_track = tracks[0]  # Fallback to first track

        # Get ViewBox from track
        view_box = None
        if hasattr(primary_track, "view") and hasattr(primary_track.view, "view_box"):
            view_box = primary_track.view.view_box()
        elif hasattr(primary_track, "view_box"):
            view_box = primary_track.view_box()

        if view_box is None:
            return

        # Step back in zoom history (per PyQtGraph docs)
        try:
            self._set_xrange_source("zoom.back", None)
            view_box.scaleHistory(-1)
        except Exception:
            # No history available - fallback to full range with auto-range
            if hasattr(plot_host, "full_range"):
                full_range = plot_host.full_range()
                if full_range is not None:
                    self._set_xrange_source(
                        "zoom.back",
                        (float(full_range[0]), float(full_range[1])),
                    )
                    self._apply_time_window(full_range)

    def _on_box_zoom_toggled(self, checked: bool) -> None:
        """Enable rectangle zoom mode for PyQtGraph traces; otherwise keep pan-only."""
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "get_render_backend"):
            return
        if plot_host.get_render_backend() != "pyqtgraph":
            return
        if hasattr(plot_host, "set_mouse_mode"):
            mode = "rect" if checked else "pan"
            plot_host.set_mouse_mode(mode)
            self._update_nav_mode_indicator(mode)

    def _on_autoscale_triggered(self) -> None:
        """Handle autoscale button click - one-shot Y autoscale."""
        if hasattr(self, "_logger"):
            self._logger.debug("Toolbar autoscale: one-shot Y autoscale")
        if not hasattr(self, "plot_host"):
            return

        plot_host = self.plot_host
        is_pyqtgraph = (
            hasattr(plot_host, "get_render_backend")
            and plot_host.get_render_backend() == "pyqtgraph"
        )
        if is_pyqtgraph:
            autoscale_once_all = getattr(plot_host, "autoscale_all_y_once", None)
            if callable(autoscale_once_all):
                autoscale_once_all()
            else:
                plot_host.autoscale_all()
            return

        # Legacy backend: reset to full range + autoscale Y
        full = plot_host.full_range()
        if full is not None:
            plot_host.set_time_window(*full)
        plot_host.autoscale_all()

    def _on_autoscale_y_triggered(self, checked: bool) -> None:
        """Handle Y-axis autoscale toggle."""
        if hasattr(self, "_logger"):
            self._logger.debug("Toolbar Y-autoscale toggle: %s", checked)
        if not hasattr(self, "plot_host"):
            return

        plot_host = self.plot_host
        if plot_host is not None and hasattr(plot_host, "debug_dump_state"):
            plot_host.debug_dump_state("autoscale_y_toolbar (before)")

        # Enable/disable Y-axis autoscaling for all tracks
        self.plot_host.set_autoscale_y_enabled(checked)
        self._invalidate_sample_state_cache()
        self.mark_session_dirty(reason="autoscale y toggled")

        if plot_host is not None and hasattr(plot_host, "debug_dump_state"):
            plot_host.debug_dump_state("autoscale_y_toolbar (after)")
        if (
            self._plot_host_is_pyqtgraph()
            and plot_host is not None
            and hasattr(plot_host, "log_data_and_view_ranges")
        ):
            plot_host.log_data_and_view_ranges("autoscale_y_toolbar")
        self._sync_autoscale_y_action_from_host()

    def _on_pan_mode_toggled(self, checked: bool) -> None:
        """Enable PyQtGraph pan mode when the Pan action is activated."""
        if not checked:
            return
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "get_render_backend"):
            return
        if plot_host.get_render_backend() != "pyqtgraph":
            return
        if hasattr(plot_host, "set_mouse_mode"):
            plot_host.set_mouse_mode("pan")
            self._update_nav_mode_indicator("pan")

    def _sync_autoscale_y_action_from_host(self) -> None:
        """Align the Y-autoscale toggle with the current renderer state."""
        act = getattr(self, "actAutoscaleY", None)
        if act is None:
            return
        plot_host = getattr(self, "plot_host", None)
        enabled = False
        if plot_host is not None and hasattr(plot_host, "is_autoscale_y_enabled"):
            with contextlib.suppress(Exception):
                enabled = bool(plot_host.is_autoscale_y_enabled())
        act.blockSignals(True)
        act.setChecked(enabled)
        act.blockSignals(False)

    def _ensure_event_label_actions(self) -> None:
        if getattr(self, "_event_label_action_group", None) is not None:
            return

        self._event_label_action_group = QActionGroup(self)
        self._event_label_action_group.setExclusive(True)

        def make_action(text: str, mode: str) -> QAction:
            action = QAction(text, self)
            action.setCheckable(True)
            self._event_label_action_group.addAction(action)

            def _on_toggled(checked: bool, *, value: str = mode) -> None:
                if checked:
                    self._set_event_label_mode(value)

            action.toggled.connect(_on_toggled)
            return action

        self.actEventLabelsOff = make_action("Off", "off")
        self.actEventLabelsVertical = make_action("Indices", "indices")
        self.actEventLabelsHorizontal = make_action("Names on Hover", "names_on_hover")
        self.actEventLabelsOutside = make_action("Names Always", "names_always")

        self._sync_event_controls()

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
        self._on_view_state_changed(reason="event lines toggled")

    def _on_event_label_mode_auto(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("indices")

    def _on_event_label_mode_all(self, checked: bool) -> None:
        if checked:
            self._set_event_label_mode("names_always")

    def _set_event_label_mode(self, mode: str) -> None:
        normalized = mode.lower()
        alias = {
            "auto": "indices",
            "all": "names_always",
            "vertical": "indices",
            "horizontal_outside": "indices",
            "horizontal": "names_always",
            "none": "off",
        }
        normalized = alias.get(normalized, normalized)
        if normalized not in {"off", "indices", "names_on_hover", "names_always"}:
            normalized = "indices"
        if normalized == self._event_label_mode:
            return
        self._apply_event_label_mode(normalized)

    def _apply_event_label_mode(self, mode: str | None = None) -> None:
        """Central switch for event labels.

        Ensures legacy lane is disabled when helper is active.
        """
        incoming = mode if mode is not None else self._event_label_mode
        mapped = {
            "auto": "indices",
            "all": "names_always",
            "vertical": "indices",
            "horizontal_outside": "indices",
            "horizontal": "names_always",
        }.get(incoming, incoming)
        self._event_label_mode = mapped
        with contextlib.suppress(Exception):
            self.settings.setValue("plot/eventLabelMode", self._event_label_mode)

        # Always tear down the legacy annotation lane FIRST
        self._annotation_lane_visible = False
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            plot_host.set_annotation_entries([])
        else:
            self._refresh_event_annotation_artists()

        if plot_host is None:
            self.canvas.draw_idle()
            self._sync_event_controls()
            self._on_view_state_changed(reason="event label mode")
            return

        set_display_mode = getattr(plot_host, "set_event_display_mode", None)
        if callable(set_display_mode):
            set_display_mode(self._event_label_mode)
        else:
            plot_host.set_event_label_mode(self._event_label_mode)  # fallback
        self._refresh_event_annotation_artists()
        self.canvas.draw_idle()
        self._sync_event_controls()
        self._on_view_state_changed(reason="event label mode")

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
            "off": self.actEventLabelsOff,
            "indices": self.actEventLabelsVertical,
            "names_on_hover": self.actEventLabelsHorizontal,
            "names_always": self.actEventLabelsOutside,
        }
        for key, action in mapping.items():
            if action is None:
                continue
            should_check = mode == key
            if action.isChecked() != should_check:
                action.blockSignals(True)
                action.setChecked(should_check)
                action.blockSignals(False)

        if self.event_label_button is not None:
            labels = {
                "off": "Labels: Off",
                "indices": "Labels: Indices",
                "names_on_hover": "Labels: Hover",
                "names_always": "Labels: Always",
            }
            self.event_label_button.setText(labels.get(mode, "Labels"))

    def _apply_time_mode(self, mode: TimeMode | str, *, persist: bool = True) -> None:
        resolved = coerce_time_mode(mode)
        self._time_mode = str(resolved.value)

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_time_mode"):
            with contextlib.suppress(Exception):
                plot_host.set_time_mode(self._time_mode)

        controller = getattr(self, "event_table_controller", None)
        if controller is not None and hasattr(controller, "set_time_mode"):
            with contextlib.suppress(Exception):
                controller.set_time_mode(self._time_mode)

        nav_bar = getattr(self, "trace_nav_bar", None)
        if nav_bar is not None and hasattr(nav_bar, "set_time_mode"):
            with contextlib.suppress(Exception):
                nav_bar.set_time_mode(self._time_mode, emit_signal=False)

        self._set_shared_xlabel("Time (s)" if resolved == TimeMode.SECONDS else "Time")
        if persist:
            with contextlib.suppress(Exception):
                self.settings.setValue("plot/timeMode", self._time_mode)
                self.settings.sync()

    def _on_time_mode_changed(self, mode: str) -> None:
        self._apply_time_mode(mode, persist=True)

    def _update_trace_controls_state(self) -> None:
        has_trace = (
            self.trace_data is not None and getattr(self.trace_data, "empty", False) is False
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

    def _sync_track_visibility_from_host(self) -> None:
        """Align toolbar actions with PyQtGraph host visibility state."""

        host = getattr(self, "plot_host", None)
        if host is None:
            return
        with contextlib.suppress(Exception):
            backend = host.get_render_backend()
        if host is None or backend != "pyqtgraph":
            return

        mapping = {
            "inner": getattr(self, "id_toggle_act", None),
            "outer": getattr(self, "od_toggle_act", None),
            "avg_pressure": getattr(self, "avg_pressure_toggle_act", None),
            "set_pressure": getattr(self, "set_pressure_toggle_act", None),
        }

        for key, action in mapping.items():
            if action is None:
                continue
            desired = host.is_channel_visible(key)
            if action.isChecked() != desired:
                action.blockSignals(True)
                action.setChecked(desired)
                action.blockSignals(False)

        self._update_trace_controls_state()

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

        widget = getattr(self, "snapshot_widget", None)
        if widget is None:
            return
        chosen = menu.exec_(widget.mapToGlobal(pos))
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
            if isinstance(value, list | tuple | np.ndarray):
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
    @staticmethod
    def _utc_iso_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _basename(value: Any) -> str | None:
        if isinstance(value, os.PathLike):
            value = os.fspath(value)
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return os.path.basename(stripped)

    @classmethod
    def _basename_list(cls, values: Any) -> list[str]:
        if not isinstance(values, list | tuple):
            return []
        names: list[str] = []
        for value in values:
            name = cls._basename(value)
            if name:
                names.append(name)
        return names

    @classmethod
    def _sanitize_import_metadata(cls, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
        clean = dict(metadata or {})

        trace_name = cls._basename(clean.get("trace_original_filename"))
        if trace_name:
            clean["trace_original_filename"] = trace_name

        trace_names = cls._basename_list(clean.get("trace_original_filenames"))
        if trace_names:
            clean["trace_original_filenames"] = trace_names
        else:
            clean.pop("trace_original_filenames", None)

        events_name = cls._basename(clean.get("events_original_filename"))
        if events_name:
            clean["events_original_filename"] = events_name

        tiff_name = cls._basename(clean.get("tiff_original_filename"))
        if tiff_name:
            clean["tiff_original_filename"] = tiff_name

        event_file_name = cls._basename(clean.pop("event_file", None))
        if event_file_name and not clean.get("events_original_filename"):
            clean["events_original_filename"] = event_file_name

        for key in ("event_files", "merged_traces", "merged_from_paths", "merged_requested_paths"):
            names = cls._basename_list(clean.get(key))
            if names:
                clean[key] = names
            else:
                clean.pop(key, None)

        for key in ("merged_skipped_paths", "event_skipped_paths"):
            entries = clean.get(key)
            if not isinstance(entries, list):
                continue
            normalised: list[Any] = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    normalised.append(entry)
                    continue
                entry_copy = dict(entry)
                path_name = cls._basename(entry_copy.get("path"))
                if path_name:
                    entry_copy["path"] = path_name
                normalised.append(entry_copy)
            clean[key] = normalised

        segments = clean.get("merged_segments")
        if isinstance(segments, list):
            normalised_segments: list[Any] = []
            for segment in segments:
                if not isinstance(segment, Mapping):
                    normalised_segments.append(segment)
                    continue
                segment_copy = dict(segment)
                path_name = cls._basename(segment_copy.get("path"))
                if path_name:
                    segment_copy["path"] = path_name
                normalised_segments.append(segment_copy)
            clean["merged_segments"] = normalised_segments

        clean.pop("trace_original_directory", None)
        return clean

    def _apply_loaded_trace_event_payload(
        self,
        *,
        df: pd.DataFrame,
        labels: Sequence[str] | None,
        times: Sequence[float] | None,
        frames: Sequence[int | None] | None,
        diam: Sequence[float | None] | None,
        od_diam: Sequence[float | None] | None,
        import_meta: Mapping[str, Any] | None,
        primary_trace: str,
        trace_paths: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        labels_list = list(labels or [])
        times_list = list(times or [])
        frames_list = list(frames or [])
        diam_list = list(diam or []) if diam is not None else None
        od_diam_list = list(od_diam or []) if od_diam is not None else None
        trace_path_list = list(trace_paths or [primary_trace])

        self.trace_data = self._prepare_trace_dataframe(df)
        self._update_trace_sync_state()
        self._reset_channel_view_defaults()
        self._last_event_import = self._sanitize_import_metadata(import_meta or {})
        self.trace_file_path = primary_trace
        trace_filename = os.path.basename(primary_trace)
        if len(trace_path_list) > 1:
            trace_filename = f"{trace_filename} (+{len(trace_path_list) - 1})"
        self.sampling_rate_hz = self._compute_sampling_rate(self.trace_data)
        self._set_status_source(f"Trace · {trace_filename}", primary_trace)
        self._reset_session_dirty()
        self.show_analysis_workspace()

        if labels_list:
            self.load_project_events(
                labels_list,
                times_list,
                frames_list,
                diam_list,
                od_diam_list,
                auto_export=True,
            )
            event_file = import_meta.get("event_file") if import_meta else None
            if event_file:
                self._event_table_path = str(event_file)
        else:
            self.event_labels = []
            self.event_times = []
            self.event_frames = []
            self.event_table_data = []
            self.event_label_meta = []
            self._event_table_path = None
            self.populate_table()
            self.xlim_full = None
            self.ylim_full = None
            self.update_plot()

        status_notes: list[str] = []
        if import_meta and import_meta.get("merged_traces"):
            merged_count = len(import_meta.get("merged_traces") or [])
            if merged_count > 1:
                status_notes.append(f"Merged {merged_count} trace files")
            merge_warnings = import_meta.get("merge_warnings") or []
            skipped = import_meta.get("merged_skipped_paths") or []
            for warn in merge_warnings:
                status_notes.append(str(warn))
            for skip in skipped:
                path = os.path.basename(skip.get("path", "unknown"))
                reason = skip.get("reason", "missing required columns")
                status_notes.append(f"Skipped {path}: {reason}")
        neg_inner = int(self.trace_data.attrs.get("negative_inner_diameters", 0) or 0)
        neg_outer = int(self.trace_data.attrs.get("negative_outer_diameters", 0) or 0)
        neg_sanitized = bool(self.trace_data.attrs.get("negative_diameters_sanitized", True))
        neg_verb = "Ignored" if neg_sanitized else "Detected"
        if neg_inner:
            status_notes.append(f"{neg_verb} {neg_inner} negative inner-diameter samples")
        if neg_outer:
            status_notes.append(f"{neg_verb} {neg_outer} negative outer-diameter samples")

        if import_meta:
            event_file = import_meta.get("event_file")
            if import_meta.get("auto_detected") and event_file:
                event_name = os.path.basename(str(event_file))
                if "_table" in event_name.lower():
                    status_notes.append(f"Matched events: {event_name}")
            for warn in import_meta.get("event_merge_warnings") or []:
                status_notes.append(str(warn))
            for skip in import_meta.get("event_skipped_paths") or []:
                path = os.path.basename(skip.get("path", "events.csv"))
                reason = skip.get("reason", "invalid")
                status_notes.append(f"Skipped events {path}: {reason}")
            for warn in import_meta.get("import_warnings") or []:
                status_notes.append(str(warn))
            for err in import_meta.get("import_errors") or []:
                status_notes.append(str(err))

            stats_payload = import_meta.get("import_stats")
            if isinstance(stats_payload, Mapping):
                unplaced = int(stats_payload.get("unplaced_event_count", 0) or 0)
                if unplaced:
                    status_notes.append(f"{unplaced} event(s) could not be placed")

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

        log.debug("Trace import complete with %d events", len(labels_list))

        if hasattr(self, "load_events_action") and self.load_events_action is not None:
            self.load_events_action.setEnabled(True)
        if hasattr(self, "action_import_events") and self.action_import_events is not None:
            self.action_import_events.setEnabled(True)

        self._update_home_resume_button()
        return self.trace_data

    def load_trace_and_event_files(self, trace_path):
        """Load a trace file (or multiple) and matching events if available."""
        if isinstance(trace_path, (list, tuple)):
            trace_paths = list(dict.fromkeys(trace_path))  # dedupe, keep order
            primary_trace = trace_paths[0]
        else:
            trace_paths = [trace_path]
            primary_trace = trace_path

        events_hint = find_matching_event_file(primary_trace)
        log.info(
            "UI: Importing single dataset: trace=%s events=%s",
            trace_path,
            events_hint or "(auto / none)",
        )
        cache = self._ensure_data_cache(primary_trace)
        (
            df,
            labels,
            times,
            frames,
            diam,
            od_diam,
            import_meta,
        ) = load_trace_and_events(
            trace_paths if len(trace_paths) > 1 else primary_trace, cache=cache
        )
        return self._apply_loaded_trace_event_payload(
            df=df,
            labels=labels,
            times=times,
            frames=frames,
            diam=diam,
            od_diam=od_diam,
            import_meta=import_meta,
            primary_trace=primary_trace,
            trace_paths=trace_paths,
        )

    def load_trace_and_events(
        self,
        file_path=None,
        tiff_path=None,
        *,
        source: str = "manual",
        prefetched_payload: tuple[
            pd.DataFrame,
            list[str],
            list[float],
            list[int | None] | None,
            list[float | None] | None,
            list[float | None] | None,
            Mapping[str, Any] | None,
        ]
        | None = None,
    ):
        # --- Prep ---
        snapshots = None
        self._clear_canvas_and_table()
        # 1) Prompt for CSV if needed
        if file_path is None:
            selected, _ = QFileDialog.getOpenFileNames(
                self, "Select Trace File(s)", "", "CSV Files (*.csv)"
            )
            if not selected:
                return
            if len(selected) > 1:
                choice = self._prompt_merge_traces(selected)
                if choice == "cancel":
                    return
                file_path = selected if choice == "merge" else selected[0]
            else:
                file_path = selected[0]
        primary_trace_path = file_path[0] if isinstance(file_path, list) else file_path

        # 2) Load trace and events using helper
        try:
            if prefetched_payload is None:
                self.load_trace_and_event_files(file_path)
            else:
                (
                    df,
                    labels,
                    times,
                    frames,
                    diam,
                    od_diam,
                    import_meta,
                ) = prefetched_payload
                trace_paths = (
                    list(dict.fromkeys(file_path))
                    if isinstance(file_path, list | tuple)
                    else [primary_trace_path]
                )
                self._apply_loaded_trace_event_payload(
                    df=df,
                    labels=labels,
                    times=times,
                    frames=frames,
                    diam=diam,
                    od_diam=od_diam,
                    import_meta=import_meta,
                    primary_trace=primary_trace_path,
                    trace_paths=trace_paths,
                )
        except Exception as e:
            QMessageBox.critical(self, "Trace Load Error", f"Failed to load trace file:\n{e}")
            return

        # 3) Remember in Recent Files
        if primary_trace_path not in self.recent_files:
            self.recent_files = [primary_trace_path] + self.recent_files[:4]
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
                snapshots, _, _ = load_tiff(tiff_path, metadata=False)
                self.load_snapshots(snapshots)
                self.toggle_snapshot_viewer(True)
            except Exception as e:
                QMessageBox.warning(self, "TIFF Load Error", f"Failed to load TIFF:\n{e}")

        # 6) If a project and experiment are active, auto-add this dataset
        target_experiment: Experiment | None = None
        if self.current_project:
            if (
                self.current_experiment
                and self.current_experiment in self.current_project.experiments
            ):
                target_experiment = self.current_experiment
            elif self.current_project.experiments:
                target_experiment = self.current_project.experiments[0]
            else:
                target_experiment = Experiment(name="Experiment 1")
                self.current_project.experiments.append(target_experiment)

        if self.current_project and target_experiment:
            trace_obj = Path(primary_trace_path).expanduser().resolve(strict=False)
            sample_name = os.path.splitext(os.path.basename(primary_trace_path))[0]
            if isinstance(file_path, list) and len(file_path) > 1:
                sample_name = f"{sample_name} (+{len(file_path) - 1})"
            sample = SampleN(name=sample_name)
            self._update_sample_link_metadata(sample, "trace", trace_obj)
            if isinstance(self.trace_data, pd.DataFrame) and not self.trace_data.empty:
                with contextlib.suppress(Exception):
                    sample.trace_data = self.trace_data.copy(deep=True)
            meta = dict(sample.import_metadata or {})
            if isinstance(self._last_event_import, dict) and self._last_event_import:
                meta.update(self._sanitize_import_metadata(self._last_event_import))
            trace_paths = (
                list(dict.fromkeys(file_path))
                if isinstance(file_path, list | tuple)
                else [primary_trace_path]
            )
            trace_names = [name for name in (self._basename(path) for path in trace_paths) if name]
            if trace_names:
                meta["trace_original_filename"] = trace_names[0]
                if len(trace_names) > 1:
                    meta["trace_original_filenames"] = trace_names
                else:
                    meta.pop("trace_original_filenames", None)

            event_path = find_matching_event_file(primary_trace_path)
            if event_path and os.path.exists(event_path):
                event_obj = Path(event_path).expanduser().resolve(strict=False)
                self._update_sample_link_metadata(sample, "events", event_obj)
                meta["events_original_filename"] = os.path.basename(event_path)

            if tiff_path:
                meta["tiff_original_filename"] = os.path.basename(tiff_path)
            meta["import_timestamp"] = self._utc_iso_timestamp()
            meta["import_source"] = source
            sample.import_metadata = self._sanitize_import_metadata(meta)

            if snapshots is not None:
                try:
                    sample.snapshots = np.stack(snapshots)
                except Exception:
                    log.debug(
                        "Failed to materialise snapshot stack for %s",
                        sample_name,
                        exc_info=True,
                    )

            target_experiment.samples.append(sample)
            self.current_experiment = target_experiment
            self.current_sample = sample
            self.refresh_project_tree()
            if self.current_project.path:
                save_project_file(self.current_project, self.current_project.path)
            self.statusBar().showMessage(
                f"\u2713 {sample_name} loaded into Experiment '{self.current_experiment.name}'",
                3000,
            )
            embedded_rows = (
                len(self.trace_data.index) if isinstance(self.trace_data, pd.DataFrame) else 0
            )
            event_count = len(self.event_labels or [])
            log.debug(
                "Embedded sample '%s' via %s (trace rows=%d, events=%d)",
                sample_name,
                source,
                embedded_rows,
                event_count,
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

        self.load_project_events(labels, times, frames, None, None, auto_export=True)
        self._last_event_import = self._sanitize_import_metadata(
            {
                "events_original_filename": os.path.basename(file_path),
                "manual": True,
                "import_timestamp": self._utc_iso_timestamp(),
                "import_source": "file_dialog",
            }
        )
        if self.current_sample is not None:
            meta = dict(self.current_sample.import_metadata or {})
            meta.update(self._last_event_import)
            self.current_sample.import_metadata = self._sanitize_import_metadata(meta)
        self._event_table_path = str(file_path)
        self.statusBar().showMessage(f"{len(labels)} events loaded", 3000)
        self.mark_session_dirty()
        return True

    def _event_table_signal_availability(self) -> tuple[bool, bool, bool]:
        trace = self.trace_data
        has_od = trace is not None and "Outer Diameter" in trace.columns
        avg_label = self._trace_label_for("p_avg")
        set_label = self._trace_label_for("p2")
        has_avg_p = trace is not None and avg_label in trace.columns
        has_set_p = trace is not None and set_label in trace.columns
        return has_od, has_avg_p, has_set_p

    def _event_table_review_mode_active(self) -> bool:
        controller = getattr(self, "review_controller", None)
        if controller is not None and controller.is_active():
            return True
        wizard = getattr(self, "_event_review_wizard", None)
        return bool(wizard is not None and wizard.isVisible())

    def _apply_event_table_column_contract(self) -> None:
        controller = getattr(self, "event_table_controller", None)
        if controller is None:
            return
        has_od, has_avg_p, has_set_p = self._event_table_signal_availability()
        show_id = True if self.id_toggle_act is None else self.id_toggle_act.isChecked()
        show_od = bool(self.od_toggle_act.isChecked()) if self.od_toggle_act is not None else False
        show_avg_p = (
            bool(self.avg_pressure_toggle_act.isChecked())
            if self.avg_pressure_toggle_act is not None
            else False
        )
        show_set_p = (
            bool(self.set_pressure_toggle_act.isChecked())
            if self.set_pressure_toggle_act is not None
            else False
        )
        column_keys = build_event_table_column_contract(
            review_mode=self._event_table_review_mode_active(),
            show_id=show_id,
            show_od=show_od,
            show_avg_p=show_avg_p,
            show_set_p=show_set_p,
            has_id=True,
            has_od=has_od,
            has_avg_p=has_avg_p,
            has_set_p=has_set_p,
        )
        controller.apply_column_contract(column_keys)

    def populate_table(self):
        has_data = bool(self.event_table_data)
        has_od, has_avg_p, has_set_p = self._event_table_signal_availability()
        review_states = self._current_review_states()
        self._event_table_updating = True
        try:
            self.event_table_controller.set_events(
                self.event_table_data,
                has_outer_diameter=has_od,
                has_avg_pressure=has_avg_p,
                has_set_pressure=has_set_p,
                review_states=review_states,
            )
        finally:
            self._event_table_updating = False
        self._apply_event_table_column_contract()
        self._update_excel_controls()
        self._update_event_table_presence_state(has_data)

    def _launch_event_review_wizard(self) -> None:
        if self._event_review_wizard is not None and self._event_review_wizard.isVisible():
            with contextlib.suppress(Exception):
                self._event_review_wizard.raise_()
                self._event_review_wizard.activateWindow()
            return

        if not self.event_table_data:
            QMessageBox.information(self, "No Events", "Load events before starting a review.")
            return

        events = [tuple(row) for row in self.event_table_data]
        review_states = self._current_review_states()

        def _focus(idx: int, event_data: tuple | None = None) -> None:
            self._current_review_event_index = idx
            try:
                self._focus_event_row(int(idx), source="wizard")
            except Exception:
                log.debug("Unable to focus event row %s from wizard", idx, exc_info=True)

        dialog = EventReviewWizard(
            self,
            events=events,
            review_states=review_states,
            focus_event_callback=_focus,
            sample_values_callback=self._sample_values_at_time,
        )
        self._event_review_wizard = dialog
        flags = dialog.windowFlags()
        dialog.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        dialog.setWindowModality(Qt.NonModal)
        dialog.accepted.connect(self._apply_event_review_changes)
        dialog.rejected.connect(self._cleanup_event_review_wizard)
        dialog.finished.connect(self._cleanup_event_review_wizard)
        dialog.show()
        with contextlib.suppress(Exception):
            dialog.raise_()
            dialog.activateWindow()
        self._apply_event_table_column_contract()

    def _apply_event_review_changes(self) -> None:
        wizard = getattr(self, "_event_review_wizard", None)
        if wizard is None:
            return

        updated_events = wizard.updated_events()
        updated_states = wizard.updated_review_states()
        if updated_events:
            self.event_table_data = [tuple(row) for row in updated_events]
        if updated_states:
            self._normalize_event_label_meta(len(self.event_table_data))
            for idx, state in enumerate(updated_states):
                self._set_review_state_for_row(idx, state)

        # CRITICAL FIX (Bug #2): Mark sample state dirty after review changes applied
        # (Note: _set_review_state_for_row also sets this, but setting here ensures it's set
        # even if only event data changed without state changes)
        self._sample_state_dirty = True

        self.populate_table()
        self._sync_event_data_from_table()
        self.mark_session_dirty()
        self._prompt_export_event_table_after_review()

    def _cleanup_event_review_wizard(self, *args) -> None:
        self._event_review_wizard = None
        self._current_review_event_index = None
        self._apply_event_table_column_contract()

    def _update_event_table_presence_state(self, has_events: bool) -> None:
        self._event_panel_has_data = bool(has_events)
        if has_events:
            self._set_event_table_visible(True, source="data")
        self._update_review_notice_visibility()

    def _reset_snapshot_loading_info(self) -> None:
        """Clear any cached snapshot loading metadata."""

        self.snapshot_loading_info = None
        self.snapshot_frame_indices = []
        self.snapshot_total_frames = None
        self.snapshot_frame_stride = 1
        self._update_snapshot_sampling_badge()

    @staticmethod
    def _format_stride_label(stride: int) -> str:
        """Return a human-friendly label like 'every 3rd'."""

        suffix = "th"
        if stride % 100 not in {11, 12, 13}:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(stride % 10, "th")
        return f"every {stride}{suffix}"

    def _probe_tiff_frame_count(self, file_path: str) -> int | None:
        """Return the total number of pages in a TIFF without loading frames."""

        try:
            with tifffile.TiffFile(file_path) as tif:
                return len(tif.pages)
        except Exception:
            log.debug("Failed to probe TIFF frame count for %s", file_path, exc_info=True)
            return None

    def _prompt_tiff_load_strategy(self, total_frames: int) -> tuple[str, int | None]:
        """Ask the user whether to load all frames or a reduced subset."""

        stride = max(2, int(math.ceil(total_frames / _TIFF_REDUCED_TARGET_FRAMES)))
        approx_frames = int(math.ceil(total_frames / stride))
        stride_label = self._format_stride_label(stride)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Large TIFF detected")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(f"This TIFF contains {total_frames} frames. Loading all frames may be slow.")
        dialog.setInformativeText(
            f"Load all frames, or load a reduced set ({stride_label}, ~{approx_frames} frames)?"
        )
        all_btn = dialog.addButton("Load all frames", QMessageBox.AcceptRole)
        reduced_btn = dialog.addButton("Load reduced set", QMessageBox.ActionRole)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.setDefaultButton(all_btn)
        dialog.exec_()

        clicked = dialog.clickedButton()
        if clicked == cancel_btn:
            return "cancel", None
        if clicked == reduced_btn:
            return "reduced", stride
        return "full", None

    def _update_excel_controls(self):
        """Enable or disable Excel mapping actions based on available data."""
        has_data = bool(getattr(self, "event_table_data", None))
        if hasattr(self, "excel_action") and self.excel_action is not None:
            self.excel_action.setEnabled(has_data)
        if hasattr(self, "review_events_action") and self.review_events_action is not None:
            self.review_events_action.setEnabled(has_data)
        action_export = getattr(self, "action_export_excel", None)
        if action_export is not None:
            action_export.setEnabled(has_data)
        action_template = getattr(self, "action_export_excel_template", None)
        if action_template is not None:
            action_template.setEnabled(has_data)
        for name in (
            "action_export_csv_row",
            "action_export_csv_values",
            "action_export_csv_pressure",
            "action_copy_excel_row",
            "action_copy_excel_values",
            "action_copy_excel_pressure",
        ):
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(has_data)

    def _derive_frame_trace_time(
        self, n_frames: int
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """
        Use trace_df["TiffPage"] to produce canonical frame→time mapping.

        Returns (frame_trace_index, frame_trace_time) or (None, None) when unavailable.
        """

        self.frame_trace_index = None
        self.frame_trace_time = None
        self.frame_times = []
        self._snapshot_sync_status_text = None
        self._snapshot_sync_partial_count = None

        if self.trace_data is None or "TiffPage" not in self.trace_data.columns:
            return None, None

        frame_indices = []
        info_indices = None
        if isinstance(self.snapshot_loading_info, Mapping):
            info_indices = self.snapshot_loading_info.get("frame_indices")
        if info_indices and len(info_indices) == n_frames:
            frame_indices = list(info_indices)
        elif self.snapshot_frame_indices and len(self.snapshot_frame_indices) == n_frames:
            frame_indices = list(self.snapshot_frame_indices)
        else:
            frame_indices = list(range(n_frames))

        try:
            mapping = dict(self.tiff_page_to_trace_idx)
            if not mapping:
                tiff_rows = self.trace_data[self.trace_data["TiffPage"].notna()].copy()
                if tiff_rows.empty:
                    return None, None
                tiff_rows.loc[:, "TiffPage"] = pd.to_numeric(tiff_rows["TiffPage"], errors="coerce")
                if "Saved" in tiff_rows.columns:
                    saved_mask = (
                        pd.to_numeric(tiff_rows["Saved"], errors="coerce").fillna(0).to_numpy() > 0
                    )
                    tiff_rows = tiff_rows.loc[saved_mask]
                tiff_rows = tiff_rows[tiff_rows["TiffPage"].notna()]
                mapping = {int(row["TiffPage"]): int(idx) for idx, row in tiff_rows.iterrows()}

            if not mapping:
                return None, None

            expected_pages = self.snapshot_total_frames
            if expected_pages is None and frame_indices:
                try:
                    expected_pages = int(max(frame_indices) + 1)
                except Exception:
                    expected_pages = None
            if expected_pages is not None:
                self._refresh_tiff_page_times(expected_page_count=int(expected_pages))

            if self.tiff_page_times_valid and self.tiff_page_times:
                times = []
                frame_trace_index = np.full(n_frames, -1, dtype=int)
                invalid = False
                for idx, page in enumerate(frame_indices):
                    try:
                        page_int = int(page)
                    except Exception:
                        invalid = True
                        break
                    if page_int < 0 or page_int >= len(self.tiff_page_times):
                        invalid = True
                        break
                    time_val = self.tiff_page_times[page_int]
                    if not math.isfinite(time_val):
                        invalid = True
                        break
                    times.append(float(time_val))
                    trace_idx = mapping.get(page_int)
                    if trace_idx is not None:
                        frame_trace_index[idx] = int(trace_idx)
                if not invalid:
                    frame_trace_time = np.asarray(times, dtype=float)
                    self.frame_trace_index = frame_trace_index
                    self.frame_trace_time = frame_trace_time
                    self.frame_times = frame_trace_time.tolist()
                    self.snapshot_frame_indices = frame_indices
                    self._snapshot_sync_status_text = None
                    self._snapshot_sync_partial_count = 0
                    return frame_trace_index, frame_trace_time

            trace_times = pd.to_numeric(self.trace_data["Time (s)"], errors="coerce").to_numpy(
                dtype=float
            )
            result = resolve_frame_times(
                self.frames_metadata,
                n_frames=n_frames,
                frame_indices=frame_indices,
                trace_time_s=trace_times,
                tiff_page_to_trace_idx=mapping,
                allow_fallback=True,
            )
            frame_trace_index = result.frame_to_trace_idx
            frame_trace_time = result.frame_times_s
            if frame_trace_time is None or np.isnan(frame_trace_time).any():
                log.error("TIFF sync mismatch: NaN times when mapping TiffPage to trace")
                return None, None

            if result.warnings:
                for warning in result.warnings:
                    log.warning("TIFF sync warning: %s", warning)

            if frame_trace_index is None or (frame_trace_index < 0).any():
                if trace_times is None or trace_times.size == 0:
                    return None, None
                idx = np.searchsorted(trace_times, frame_trace_time, side="left")
                idx = np.clip(idx, 0, len(trace_times) - 1)
                frame_trace_index = idx

            if result.interpolated_pages:
                count = int(result.interpolated_pages)
                self._snapshot_sync_partial_count = count
                self._snapshot_sync_status_text = f"Sync: Partial ({count} pages interpolated)"
            else:
                self._snapshot_sync_status_text = None
                self._snapshot_sync_partial_count = 0

            self.frame_trace_index = frame_trace_index
            self.frame_trace_time = frame_trace_time
            self.frame_times = frame_trace_time.tolist()
            self.snapshot_frame_indices = frame_indices

            try:
                span = (min(frame_indices), max(frame_indices)) if frame_indices else (None, None)
            except Exception:
                span = (None, None)
            info = (
                self.snapshot_loading_info
                if isinstance(self.snapshot_loading_info, Mapping)
                else {}
            )
            total_frames = info.get("total_frames", self.snapshot_total_frames)
            stride = info.get("frame_stride", self.snapshot_frame_stride)
            log.debug(
                "Frame/trace sync established: loaded_frames=%d total_frames=%s stride=%s span=%s",
                n_frames,
                total_frames,
                stride,
                span,
            )
            return frame_trace_index, frame_trace_time
        except Exception:
            log.exception("Failed to derive frame_trace_time from trace metadata")
            return None, None

    def _load_snapshot_from_path(self, file_path: str) -> bool:
        """Load a snapshot TIFF from ``file_path`` and update the viewer."""

        self._reset_snapshot_loading_info()
        try:
            total_frames = self._probe_tiff_frame_count(file_path)
            max_frames = None
            chosen_stride = None
            if total_frames is not None:
                self.snapshot_total_frames = int(total_frames)
                if total_frames >= _TIFF_PROMPT_THRESHOLD:
                    choice, stride = self._prompt_tiff_load_strategy(total_frames)
                    if choice == "cancel":
                        return False
                    if choice == "reduced" and stride:
                        chosen_stride = stride
                        max_frames = int(math.ceil(total_frames / stride))

            frames, frames_metadata, loading_info = load_tiff(file_path, max_frames=max_frames)
            loading_info = loading_info or {}
            valid_frames = []
            valid_metadata = []
            raw_indices = loading_info.get("frame_indices") or list(range(len(frames)))
            valid_indices: list[int] = []

            for i, frame in enumerate(frames):
                if frame is not None and frame.size > 0:
                    valid_frames.append(frame)
                    if i < len(frames_metadata):
                        valid_metadata.append(frames_metadata[i])
                    else:
                        valid_metadata.append({})
                    if i < len(raw_indices):
                        try:
                            valid_indices.append(int(raw_indices[i]))
                        except Exception:
                            valid_indices.append(raw_indices[i])
                    else:
                        valid_indices.append(i)

            if len(valid_frames) < len(frames):
                QMessageBox.warning(self, "TIFF Warning", "Skipped empty or corrupted TIFF frames.")

            if not valid_frames:
                QMessageBox.warning(
                    self,
                    "TIFF Load Error",
                    "No valid frames were found in the dropped TIFF file.",
                )
                return False

            frame_stride = int(loading_info.get("frame_stride", chosen_stride or 1))
            total_frames_value = loading_info.get(
                "total_frames", self.snapshot_total_frames or len(valid_frames)
            )
            try:
                total_frames_value = int(total_frames_value)
            except Exception:
                total_frames_value = self.snapshot_total_frames or len(valid_frames)

            loading_info.update(
                {
                    "loaded_frames": len(valid_frames),
                    "frame_indices": valid_indices,
                    "frame_stride": frame_stride,
                    "total_frames": total_frames_value,
                }
            )
            loading_info["is_subsampled"] = bool(
                frame_stride > 1 or len(valid_frames) < int(total_frames_value or 0)
            )

            self.snapshot_frames = valid_frames
            self.frames_metadata = valid_metadata
            self.snapshot_loading_info = loading_info
            self.snapshot_frame_indices = valid_indices
            self.snapshot_frame_stride = frame_stride
            self.snapshot_total_frames = total_frames_value

            first_meta: dict[str, Any] = (
                self.frames_metadata[0] or {} if self.frames_metadata else {}
            )
            frame_trace_index, frame_trace_time = self._derive_frame_trace_time(
                len(self.snapshot_frames)
            )

            # Canonical path: use trace["TiffPage"] to align frames to Time (s)
            if frame_trace_time is not None:
                self.recording_interval = None
                _log_time_sync(
                    "VIDEO_LOAD",
                    sample=getattr(self.current_sample, "name", None),
                    path=os.path.basename(file_path),
                    frames=len(self.snapshot_frames),
                    frame_time_0=frame_trace_time[0] if len(frame_trace_time) else None,
                    frame_time_last=frame_trace_time[-1] if len(frame_trace_time) else None,
                    meta_keys=",".join(sorted((first_meta or {}).keys())),
                )
            else:
                fallback_interval = 0.14
                try:
                    fallback_result = resolve_frame_times(
                        self.frames_metadata,
                        n_frames=len(self.snapshot_frames),
                        frame_indices=valid_indices,
                        fps=None,
                        allow_fallback=True,
                    )
                except ValueError:
                    fallback_result = resolve_frame_times(
                        self.frames_metadata,
                        n_frames=len(self.snapshot_frames),
                        frame_indices=valid_indices,
                        fps=1.0 / fallback_interval,
                        allow_fallback=True,
                    )
                    fallback_result.warnings.append(
                        f"Frame times estimated using default interval {fallback_interval:.2f}s (no metadata)."
                    )

                self.frame_times = fallback_result.frame_times_s.tolist()
                if len(self.frame_times) >= 2:
                    diffs = np.diff(np.asarray(self.frame_times, dtype=float))
                    diffs = diffs[diffs > 0]
                    self.recording_interval = (
                        float(np.median(diffs)) if diffs.size else fallback_interval
                    )
                else:
                    self.recording_interval = fallback_interval

                _log_time_sync(
                    "VIDEO_LOAD_LEGACY",
                    sample=getattr(self.current_sample, "name", None),
                    path=os.path.basename(file_path),
                    frames=len(self.snapshot_frames),
                    interval=f"{self.recording_interval:.4f}"
                    if self.recording_interval
                    else "unknown",
                    frame_time_0=self.frame_times[0] if self.frame_times else None,
                    frame_time_1=self.frame_times[1] if len(self.frame_times) > 1 else None,
                    meta_keys=",".join(sorted((first_meta or {}).keys())),
                )

            self.compute_frame_trace_indices()
            canonical_times = (
                frame_trace_time
                if frame_trace_time is not None
                else np.asarray(self.frame_times, dtype=float)
            )
            timebase_meta = {
                "source": "tiff_page" if frame_trace_time is not None else "legacy",
                "warnings": [],
                "fps": None,
            }
            if frame_trace_time is None:
                timebase_meta["warnings"] = (
                    list(getattr(fallback_result, "warnings", []) or [])
                    if "fallback_result" in locals()
                    else []
                )
                timebase_meta["source"] = (
                    getattr(fallback_result, "source", None).value
                    if "fallback_result" in locals()
                    and getattr(fallback_result, "source", None) is not None
                    else "legacy"
                )
                timebase_meta["fps"] = (
                    float(getattr(fallback_result, "fps", 0.0) or 0.0)
                    if "fallback_result" in locals()
                    else None
                )
            timebase_meta["recording_interval_s"] = (
                float(self.recording_interval) if self.recording_interval is not None else None
            )
            timebase_meta["frame_count"] = int(len(canonical_times))
            if self.current_sample is not None:
                meta = dict(self.current_sample.import_metadata or {})
                timebase_block = dict(meta.get("timebase") or {})
                tiff_block = dict(timebase_block.get("tiff") or {})
                tiff_block.update(timebase_meta)
                timebase_block["tiff"] = tiff_block
                meta["timebase"] = timebase_block
                self.current_sample.import_metadata = meta
            self._set_snapshot_data_source(self.snapshot_frames, canonical_times)

            if self.slider is not None:
                self.slider.blockSignals(True)
                self.slider.setRange(0, len(self.snapshot_frames) - 1)
                self.slider.setValue(0)
                self.slider.blockSignals(False)

            prev_btn = getattr(self, "prev_frame_btn", None)
            next_btn = getattr(self, "next_frame_btn", None)
            play_btn = getattr(self, "play_pause_btn", None)
            speed_label = getattr(self, "snapshot_speed_label", None)
            speed_combo = getattr(self, "snapshot_speed_combo", None)
            if prev_btn is not None:
                prev_btn.setEnabled(True)
            if next_btn is not None:
                next_btn.setEnabled(True)
            if play_btn is not None:
                play_btn.setEnabled(True)
            if speed_label is not None:
                speed_label.setEnabled(True)
            if speed_combo is not None:
                speed_combo.setEnabled(True)
            self._set_playback_state(False)
            self.update_snapshot_size()
            self._clear_slider_markers()
            self.toggle_snapshot_viewer(True)
            self._update_snapshot_sampling_badge()

            if self.current_sample is not None:
                try:
                    self.current_sample.snapshots = np.stack(self.snapshot_frames)
                    self.current_sample.snapshot_path = os.path.abspath(file_path)
                except Exception:
                    log.warning("Failed to stack snapshot frames", exc_info=True)
                self.mark_session_dirty()
                self.auto_save_project(reason="snapshot")

            status_note = None
            if self.snapshot_loading_info.get("is_subsampled"):
                stride_text = self._format_stride_label(
                    int(self.snapshot_loading_info.get("frame_stride", 1))
                )
                status_note = (
                    f"Reduced snapshot set loaded: {len(self.snapshot_frames)}/"
                    f"{self.snapshot_loading_info.get('total_frames')} frames "
                    f"({stride_text})"
                )
            elif self.snapshot_total_frames:
                status_note = (
                    f"Loaded {len(self.snapshot_frames)} frame(s)"
                    f" (original stack: {self.snapshot_total_frames})"
                )
            if status_note:
                self.statusBar().showMessage(status_note, 6000)

            # Update GIF Animator state after snapshots are loaded
            self._update_gif_animator_state()

            return True

        except Exception as e:
            QMessageBox.critical(self, "TIFF Load Error", f"Failed to load TIFF:\n{e}")
            return False

    def load_snapshot(self, checked: bool = False):
        """Load a snapshot from TIFF file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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
        self._update_trace_sync_state()
        self._reset_channel_view_defaults()
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
        self.event_label_meta = [self._with_default_review_state(None) for _ in self.event_labels]
        self.event_table_data = []
        has_od = od_before is not None
        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        for lbl, diam, od in zip(
            labels,
            diam_before,
            od_before if has_od else [None] * len(labels),
            strict=False,
        ):
            self.event_table_data.append((lbl, 0.0, diam, od, None, None, 0))
        self.populate_table()

    def _trace_time_for_frame_number(self, frame: int | float | None) -> float | None:
        """Return canonical trace time for a given camera frame number."""

        if frame is None or pd.isna(frame):
            return None
        frame_int = int(frame)
        idx = self.frame_number_to_trace_idx.get(frame_int)
        if idx is None or self.trace_time is None:
            return None
        if idx < 0 or idx >= len(self.trace_time):
            return None
        # Events derive their canonical time from the trace row that matches FrameNumber.
        return float(self.trace_time[idx])

    def load_project_events(
        self,
        labels,
        times,
        frames,
        diam_before,
        od_before=None,
        *,
        refresh_plot: bool = True,
        auto_export: bool = False,
    ):
        log.debug(
            "DATASET_EVENTS_POPULATE: sample='%s' event_count=%d",
            getattr(self.current_sample, "name", "<unknown>"),
            len(labels) if labels else 0,
        )
        self.event_labels = list(labels)
        self.event_label_meta = [self._with_default_review_state(None) for _ in self.event_labels]
        raw_times = pd.to_numeric(times, errors="coerce").tolist() if times is not None else []
        raw_frame_series = (
            pd.to_numeric(pd.Series(frames), errors="coerce") if frames is not None else None
        )
        if raw_frame_series is not None:
            raw_frame_values = raw_frame_series.tolist()
        else:
            raw_frame_values = [None] * len(self.event_labels)
        raw_frame_list: list[int | None] = [
            int(val) if pd.notna(val) else None for val in raw_frame_values
        ]

        trace_time_series = None
        if self.trace_data is not None and "Time (s)" in self.trace_data.columns:
            trace_time_series = pd.to_numeric(self.trace_data["Time (s)"], errors="coerce")

        resolved_times: list[float] = []
        resolved_frames: list[int | None] = []
        event_trace_indices: list[int | None] = []
        unsynced_events = 0
        for idx_ev, lbl in enumerate(self.event_labels):
            frame_val = raw_frame_list[idx_ev] if idx_ev < len(raw_frame_list) else None
            time_val = raw_times[idx_ev] if idx_ev < len(raw_times) else np.nan
            resolved_frames.append(frame_val)

            trace_idx = None
            if frame_val is not None:
                trace_idx = self.frame_number_to_trace_idx.get(int(frame_val))
            event_trace_indices.append(trace_idx)

            mapped_time = None
            if trace_idx is not None and trace_time_series is not None:
                with contextlib.suppress(Exception):
                    mapped_time = float(trace_time_series.iloc[trace_idx])
            if mapped_time is None or pd.isna(mapped_time):
                try:
                    mapped_time = float(time_val)
                except (TypeError, ValueError):
                    mapped_time = np.nan
                    if frame_val is not None:
                        unsynced_events += 1
            resolved_times.append(mapped_time)

        if unsynced_events:
            log.warning("Events: %d rows had frame numbers with no trace match", unsynced_events)

        # --- Event time range validation ---
        if resolved_times and trace_time_series is not None and not trace_time_series.empty:
            trace_min = float(trace_time_series.min())
            trace_max = float(trace_time_series.max())
            valid_event_times = [t for t in resolved_times if not pd.isna(t)]
            if valid_event_times:
                ev_min = min(valid_event_times)
                ev_max = max(valid_event_times)
                out_of_range = [
                    t for t in valid_event_times if t < trace_min or t > trace_max
                ]
                if out_of_range:
                    pct = len(out_of_range) / len(valid_event_times) * 100
                    log.warning(
                        "Event validation: %d of %d events (%.0f%%) are outside "
                        "trace time range [%.1f, %.1f] s",
                        len(out_of_range), len(valid_event_times), pct,
                        trace_min, trace_max,
                    )
                    if pct > 50:
                        ratio = ev_max / trace_max if trace_max > 0 else 0
                        hint = ""
                        if 55 < ratio < 65:
                            hint = (
                                "\n\nHint: Event times appear to be in minutes "
                                "while the trace is in seconds."
                            )
                        elif 900 < ratio < 1100:
                            hint = (
                                "\n\nHint: Event times appear to be in "
                                "milliseconds while the trace is in seconds."
                            )
                        QMessageBox.warning(
                            self,
                            "Event Time Mismatch",
                            f"{len(out_of_range)} of {len(valid_event_times)} events "
                            f"fall outside the trace time range "
                            f"({trace_min:.1f}\u2013{trace_max:.1f} s).\n\n"
                            f"Event time range: {ev_min:.1f}\u2013{ev_max:.1f} s.\n"
                            f"Events may be in different time units or reference "
                            f"a different recording.{hint}",
                        )

        # Canonical event times prefer trace["Time (s)"] mapped via FrameNumber; event CSV strings are fallback only.
        self.event_times = resolved_times
        self.event_frames = [int(fr) if fr is not None else 0 for fr in resolved_frames]

        self.event_table_data = []
        annotation_entries: list[AnnotationSpec] = []
        event_meta: list[dict[str, Any]] = []

        has_od = od_before is not None or (
            self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        )
        avg_label = self._trace_label_for("p_avg")
        set_label = self._trace_label_for("p2")
        has_avg_pressure = self.trace_data is not None and avg_label in self.trace_data.columns
        has_set_pressure = self.trace_data is not None and set_label in self.trace_data.columns

        if self.trace_data is not None and self.event_times:
            arr_t = self.trace_data["Time (s)"].values
            arr_d = self.trace_data["Inner Diameter"].values
            arr_od = (
                self.trace_data["Outer Diameter"]
                if "Outer Diameter" in self.trace_data.columns
                else None
            )
            arr_avg_p = self.trace_data[avg_label].values if has_avg_pressure else None
            arr_set_p = self.trace_data[set_label].values if has_set_pressure else None
            default_offset_sec = 2.0
            time_trace = self.trace_data["Time (s)"]

            # Event times should come from trace["Time (s)"] via FrameNumber mapping, not parsed event CSV strings.
            for idx_ev, (lbl, t, fr) in enumerate(
                zip(
                    self.event_labels,
                    self.event_times,
                    resolved_frames,
                    strict=False,
                )
            ):
                if pd.isna(t):
                    continue
                trace_idx = (
                    event_trace_indices[idx_ev] if idx_ev < len(event_trace_indices) else None
                )
                if trace_idx is None:
                    trace_idx = int(np.argmin(np.abs(arr_t - t)))
                frame_number = int(fr) if fr is not None else trace_idx

                # Sample a value before the *next* event (or before trace end)
                if len(self.event_times) > 1 and idx_ev < len(self.event_times) - 1:
                    next_t = self.event_times[idx_ev + 1]
                    gap = max(0.0, float(next_t) - float(t))
                    if gap <= 0.5:
                        t_sample = float(t) + gap * 0.5
                    elif gap <= 1.0:
                        t_sample = float(t) + gap * 0.6
                    else:
                        lookback = min(5.0, max(1.0, gap / 2.0, default_offset_sec))
                        lookback = min(lookback, gap - 0.05) if gap > 0.05 else gap * 0.5
                        t_sample = float(next_t) - lookback
                else:
                    t_sample = float(time_trace.iloc[-1]) - default_offset_sec
                # Clamp sample time within trace range
                t_sample = max(float(time_trace.iloc[0]), min(t_sample, float(time_trace.iloc[-1])))

                idx_pre = int(np.argmin(np.abs(arr_t - t_sample)))

                diam_val = float(arr_d[idx_pre])
                # Fallback to stored diam_before when the trace has NaN at the sample point
                # (common for legacy VasoTracker files with sparse ID measurements)
                if not np.isfinite(diam_val) and diam_before is not None and idx_ev < len(diam_before):
                    fb = diam_before[idx_ev]
                    if fb is not None:
                        try:
                            fb_f = float(fb)
                            if np.isfinite(fb_f):
                                diam_val = fb_f
                        except (TypeError, ValueError):
                            pass

                od_val_sample = float(arr_od[idx_pre]) if arr_od is not None else None
                # Fallback to stored od_before when the trace has NaN at the sample point
                if (
                    od_val_sample is None or not np.isfinite(od_val_sample)
                ) and od_before is not None and idx_ev < len(od_before):
                    fb_od = od_before[idx_ev]
                    if fb_od is not None:
                        try:
                            fb_od_f = float(fb_od)
                            if np.isfinite(fb_od_f):
                                od_val_sample = fb_od_f
                        except (TypeError, ValueError):
                            pass
                avg_p_val_sample = None
                if arr_avg_p is not None:
                    val = arr_avg_p[idx_pre]
                    if val is not None and not pd.isna(val):
                        avg_p_val_sample = float(val)
                set_p_val_sample = None
                if arr_set_p is not None:
                    val = arr_set_p[idx_pre]
                    if val is not None and not pd.isna(val):
                        set_p_val_sample = float(val)

                # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
                # Use the sampled value *before the next event* to keep continuity with legacy behavior.
                self.event_table_data.append(
                    (
                        lbl,
                        float(t),
                        diam_val,
                        od_val_sample,
                        avg_p_val_sample,
                        set_p_val_sample,
                        int(fr) if fr is not None else frame_number,
                    )
                )

                tooltip = f"{lbl} · {float(t):.2f}s · ID {diam_val:.2f}µm"
                if od_val_sample is not None:
                    tooltip += f" · OD {od_val_sample:.2f}µm"
                event_meta.append(
                    {
                        "time": float(t),
                        "label": lbl,
                        "tooltip": tooltip,
                        "frame": frame_number,
                        "avg_pressure": avg_p_val_sample,
                        "set_pressure": set_p_val_sample,
                    }
                )
                annotation_entries.append(
                    AnnotationSpec(
                        time_s=float(t),
                        label=lbl,
                    )
                )
        else:
            # When loading from saved data (diam_before, od_before exist)
            # Pressure data would come from trace_data, not saved event data
            for lbl, t, fr, diam_i in zip(
                self.event_labels,
                self.event_times,
                self.event_frames,
                diam_before,
                strict=False,
            ):
                if pd.isna(t):
                    continue
                od_val = (
                    float(od_before[self.event_labels.index(lbl)]) if has_od and od_before else None
                )
                # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
                self.event_table_data.append(
                    (lbl, float(t), float(diam_i), od_val, None, None, int(fr))
                )

        self.event_annotations = annotation_entries
        self.event_metadata = event_meta

        if self.event_table_data:
            log.info(
                "DEBUG load: event_table_data rows=%s first_label=%r",
                len(self.event_table_data),
                self.event_table_data[0][0],
            )
        else:
            log.info("DEBUG load: event_table_data rows=0")
        self._normalize_event_label_meta(len(self.event_table_data))
        self.populate_table()
        if auto_export and _env_flag("VASO_ENABLE_EVENT_TABLE_AUTOEXPORT"):
            self.auto_export_table()
        if refresh_plot:
            self.xlim_full = None
            self.ylim_full = None
            self.update_plot()
            self._apply_event_label_mode()
            self._sync_event_controls()
            self._update_trace_controls_state()
        self._update_review_notice_visibility()
        self._refresh_overview_events()

        sample = getattr(self, "current_sample", None)
        sample_name = getattr(sample, "name", getattr(sample, "label", "N/A"))
        log.info(
            "UI: Event table populated for sample %s with %d rows",
            sample_name,
            len(self.event_table_data),
        )

    def _set_snapshot_data_source(
        self, stack: Sequence[np.ndarray] | np.ndarray, frame_times: Sequence[float] | None
    ) -> None:
        """Bind a canonical snapshot data source for controller-driven viewing."""

        viewer = getattr(self, "snapshot_widget", None)
        if viewer is None:
            return
        try:
            frames = list(stack) if not isinstance(stack, np.ndarray) else list(stack)
        except Exception:
            log.debug("Failed to coerce snapshot stack for v2 viewer", exc_info=True)
            return
        from vasoanalyzer.ui.tiff_viewer_v2.page_time_map import (
            PageTimeMap,
            derive_page_time_map_from_trace,
        )

        page_time_map: PageTimeMap
        if frame_times is not None and len(frame_times):
            status = getattr(self, "_snapshot_sync_status_text", None)
            if status:
                page_time_map = PageTimeMap(
                    tuple(float(v) for v in frame_times),
                    True,
                    status,
                )
            else:
                page_time_map = PageTimeMap.from_times(frame_times)
        else:
            page_time_map = derive_page_time_map_from_trace(
                getattr(self, "trace_data", None),
                expected_page_count=len(frames),
            )
            if not page_time_map.valid:
                page_time_map = PageTimeMap.invalid(page_time_map.status)
        if page_time_map.valid:
            log.info("V2 sync status: %s", page_time_map.status or "Sync available")
        else:
            log.warning("V2 sync status: %s", page_time_map.status or "Sync unavailable")
        with contextlib.suppress(Exception):
            viewer.set_stack_source(frames, page_time_map=page_time_map)

    def load_snapshots(self, stack):
        self.snapshot_frames = [frame for frame in stack]
        if self.snapshot_frames:
            self.snapshot_frame_indices = list(range(len(self.snapshot_frames)))
            self.snapshot_frame_stride = 1
            self.snapshot_total_frames = len(self.snapshot_frames)
            self.snapshot_loading_info = {
                "total_frames": self.snapshot_total_frames,
                "loaded_frames": len(self.snapshot_frames),
                "frame_stride": 1,
                "frame_indices": self.snapshot_frame_indices,
                "is_subsampled": False,
            }
        else:
            self._reset_snapshot_loading_info()
            self._set_playback_state(False)
            if self.snapshot_widget is not None:
                self.snapshot_widget.clear()
        if self.snapshot_frames:
            canonical_times = None
            frame_trace_index, frame_trace_time = self._derive_frame_trace_time(
                len(self.snapshot_frames)
            )
            if frame_trace_time is not None:
                canonical_times = frame_trace_time
                self.recording_interval = None
            else:
                self.frame_times = [
                    idx * self.recording_interval for idx in range(len(self.snapshot_frames))
                ]
                canonical_times = np.asarray(self.frame_times, dtype=float)

            self.compute_frame_trace_indices()
            self.reset_snapshot_rotation()
            self._set_snapshot_data_source(self.snapshot_frames, canonical_times)
            if self.slider is not None:
                self.slider.blockSignals(True)
                self.slider.setRange(0, len(self.snapshot_frames) - 1)
                self.slider.setValue(0)
                self.slider.blockSignals(False)
            prev_btn = getattr(self, "prev_frame_btn", None)
            next_btn = getattr(self, "next_frame_btn", None)
            play_btn = getattr(self, "play_pause_btn", None)
            speed_label = getattr(self, "snapshot_speed_label", None)
            speed_combo = getattr(self, "snapshot_speed_combo", None)
            if prev_btn is not None:
                prev_btn.setEnabled(True)
            if next_btn is not None:
                next_btn.setEnabled(True)
            if play_btn is not None:
                play_btn.setEnabled(True)
            if speed_label is not None:
                speed_label.setEnabled(True)
            if speed_combo is not None:
                speed_combo.setEnabled(True)
            self._set_playback_state(False)
            self._update_snapshot_sampling_badge()
            self._update_snapshot_rotation_controls()

    def compute_frame_trace_indices(self):
        """Map each frame to the nearest trace index using canonical times."""

        self.frame_trace_indices = []
        self.frame_trace_index = None

        if self.trace_time is None:
            return

        if self.frame_trace_time is not None and len(self.frame_trace_time):
            times = np.asarray(self.frame_trace_time, dtype=float)
        elif self.frame_times:
            times = np.asarray(self.frame_times, dtype=float)
        else:
            return

        idx = np.searchsorted(self.trace_time, times, side="left")
        idx = np.clip(idx, 0, len(self.trace_time) - 1)
        self.frame_trace_index = idx
        self.frame_trace_indices = idx

    def _time_for_frame(self, idx: int) -> float | None:
        """Return canonical seconds for the given frame index."""

        if self.frame_trace_time is not None and idx < len(self.frame_trace_time):
            try:
                return float(self.frame_trace_time[idx])
            except (TypeError, ValueError):
                return None

        if self.frame_times and idx < len(self.frame_times):
            try:
                return float(self.frame_times[idx])
            except (TypeError, ValueError):
                return None
        return None

    def _frame_index_for_time_canonical(self, time_value: float) -> int | None:
        """Nearest frame index for a canonical time (seconds)."""

        if not self.snapshot_frames:
            return None

        try:
            t_val = float(time_value)
        except (TypeError, ValueError):
            return None

        times = None
        if self.frame_trace_time is not None and len(self.frame_trace_time):
            times = np.asarray(self.frame_trace_time, dtype=float)
        elif self.frame_times:
            with contextlib.suppress(Exception):
                times = np.asarray(self.frame_times, dtype=float)

        if times is None or times.size == 0:
            return None

        return page_for_time(t_val, times, mode="nearest")

    def jump_to_time(
        self,
        t: float,
        *,
        from_event: bool = False,
        from_playback: bool = False,
        from_frame_change: bool = False,
        source: str | None = None,
        snap_to_trace: bool = True,
    ) -> None:
        """
        Canonical time jump (seconds) that updates trace and video consistently.
        """

        try:
            t_val = float(t)
        except (TypeError, ValueError):
            return

        src_label = source or ("event" if from_event else "video" if from_playback else "manual")

        _log_time_sync(
            "JUMP_TO_TIME",
            t=t_val,
            source=src_label,
        )

        resolved_time = t_val
        if snap_to_trace and self.trace_time is not None and len(self.trace_time):
            idx_trace = int(np.searchsorted(self.trace_time, t_val))
            idx_trace = max(0, min(idx_trace, len(self.trace_time) - 1))
            resolved_time = float(self.trace_time[idx_trace])
        self._time_cursor_time = resolved_time
        self._snapshot_play_time_s = float(resolved_time)

        # Update trace cursor + highlight.
        self._highlight_selected_event(resolved_time)
        is_playing_video = bool(
            getattr(self, "play_pause_btn", None) and self.play_pause_btn.isChecked()
        )
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            if hasattr(plot_host, "set_time_cursor"):
                with contextlib.suppress(Exception):
                    plot_host.set_time_cursor(resolved_time, visible=True)
            # Avoid snapping back to full range during playback; keep user zoom stable.
            should_center = not is_playing_video and src_label in {"manual", "event"}
            if should_center and hasattr(plot_host, "center_on_time"):
                with contextlib.suppress(Exception):
                    plot_host.center_on_time(resolved_time)

        frame_idx = self._frame_index_for_time_canonical(resolved_time)
        if frame_idx is not None:
            self.current_frame = frame_idx
            self.current_page = frame_idx
            self.page_float = float(frame_idx)
            if self.slider is not None and self.slider.value() != frame_idx:
                self.slider.blockSignals(True)
                self.slider.setValue(frame_idx)
                self.slider.blockSignals(False)
            if log.isEnabledFor(logging.DEBUG):
                tiff_page = self._tiff_page_for_frame(frame_idx)
                time_exact = self._trace_time_exact_for_page(tiff_page)
                log.debug(
                    "Trace→Frame sync: time=%s frame=%s tiff_page=%s time_exact=%s",
                    resolved_time,
                    frame_idx,
                    tiff_page,
                    time_exact,
                )

        if self.snapshot_frames:
            viewer = getattr(self, "snapshot_widget", None)
            if viewer is not None and getattr(viewer, "sync_enabled", True):
                with contextlib.suppress(Exception):
                    viewer.jump_to_time(resolved_time, source=src_label or "trace")
        self._on_view_state_changed(reason="time cursor moved")

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

    def set_current_frame(self, idx, *, from_jump: bool = False, from_playback: bool = False):
        if not self.snapshot_frames:
            return
        idx = max(0, min(int(idx), len(self.snapshot_frames) - 1))
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.jump_to_page(idx, source="external")
            return
        if self.slider is not None and self.slider.value() != idx:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
        self._apply_frame_change(idx, from_playback=from_playback)

    def update_snapshot_size(self):
        widget = getattr(self, "snapshot_widget", None)
        if widget is not None:
            widget.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if (
            event.key() == Qt.Key_Space
            and not event.isAutoRepeat()
            and self._plot_host_is_pyqtgraph()
            and self._focus_is_plot_widget()
        ):
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "mouse_mode"):
                current_mode = "pan"
                with contextlib.suppress(Exception):
                    current_mode = str(plot_host.mouse_mode()).lower()
                current_mode = "rect" if current_mode == "rect" else "pan"
                if not self._space_pan_active:
                    self._space_pan_active = True
                    self._space_pan_prev_mode = current_mode
                    if current_mode != "pan":
                        if hasattr(plot_host, "set_mouse_mode"):
                            with contextlib.suppress(Exception):
                                plot_host.set_mouse_mode("pan")
                        self._set_nav_actions_for_mode("pan")
                        self._update_nav_mode_indicator("pan")
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and self._space_pan_active:
            previous_mode = self._space_pan_prev_mode or "pan"
            self._space_pan_active = False
            self._space_pan_prev_mode = None
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "set_mouse_mode"):
                with contextlib.suppress(Exception):
                    plot_host.set_mouse_mode(previous_mode)
            self._set_nav_actions_for_mode(previous_mode)
            self._update_nav_mode_indicator(previous_mode)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def eventFilter(self, source, event):
        event_table = getattr(self, "event_table", None)
        if event_table is not None and source is event_table and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self.update_snapshot_size)
        elif source is self.trace_file_label and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._update_status_chip)
        return super().eventFilter(source, event)

    def _update_snapshot_sampling_badge(self) -> None:
        """Show or hide the reduced-load badge near the snapshot controls."""

        label = getattr(self, "snapshot_subsample_label", None)
        if label is None:
            return
        info = self.snapshot_loading_info or {}
        if not isinstance(info, Mapping):
            info = {}
        loaded = info.get("loaded_frames") or (
            len(self.snapshot_frames) if self.snapshot_frames else None
        )
        total = info.get("total_frames")
        stride = info.get("frame_stride")
        is_subsampled = bool(info.get("is_subsampled"))
        if (
            is_subsampled
            and loaded
            and total
            and stride
            and int(total) >= int(loaded)
            and int(stride) >= 1
        ):
            stride_text = self._format_stride_label(int(stride))
            label.setText(f"Reduced: {int(loaded)}/{int(total)} frames ({stride_text})")
            label.setVisible(True)
            label.setToolTip(
                f"Loaded {int(loaded)} of {int(total)} frames ({stride_text}) from the TIFF stack"
            )
        else:
            label.clear()
            label.setVisible(False)

    def _tiff_page_for_frame(self, frame_idx: int) -> int | None:
        """Return the original TIFF page index for the given loaded frame."""

        indices = self.snapshot_frame_indices or []
        if frame_idx < 0 or frame_idx >= len(indices):
            return None
        try:
            return int(indices[frame_idx])
        except Exception:
            return indices[frame_idx]

    def _trace_time_exact_for_page(self, tiff_page: int | None) -> float | None:
        """Return Time_s_exact for the trace row mapped to the given TIFF page."""

        if tiff_page is None or self.trace_time_exact is None:
            return None
        try:
            trace_idx = self.tiff_page_to_trace_idx.get(int(tiff_page))
        except Exception:
            trace_idx = None
        if trace_idx is None:
            return None
        if trace_idx < 0 or trace_idx >= len(self.trace_time_exact):
            return None
        with contextlib.suppress(Exception):
            return float(self.trace_time_exact[int(trace_idx)])
        return None

    def _apply_frame_change(self, idx: int, *, from_playback: bool = False):
        self.current_frame = idx
        self.current_page = idx
        if not from_playback:
            self.page_float = float(idx)
        frame_time = self._time_for_frame(idx)

        trace_idx = None
        trace_time = None
        tiff_page = self._tiff_page_for_frame(idx)
        time_exact = self._trace_time_exact_for_page(tiff_page)
        if self.frame_trace_index is not None and idx < len(self.frame_trace_index):
            trace_idx = int(self.frame_trace_index[idx])
            if self.trace_time is not None and trace_idx < len(self.trace_time):
                trace_time = float(self.trace_time[trace_idx])
        elif self.trace_time is not None and frame_time is not None:
            with contextlib.suppress(Exception):
                trace_idx = int(np.searchsorted(self.trace_time, frame_time))
                trace_idx = max(0, min(trace_idx, len(self.trace_time) - 1))
                trace_time = float(self.trace_time[trace_idx])

        _log_time_sync(
            "PLAYBACK_FRAME",
            idx=idx,
            frame_time=frame_time,
            trace_idx=trace_idx,
            trace_time=trace_time,
            tiff_page=tiff_page,
            time_exact=time_exact,
        )
        if log.isEnabledFor(logging.DEBUG):
            log.debug(
                "Frame→Trace sync: frame=%d tiff_page=%s trace_idx=%s time=%s time_exact=%s",
                idx,
                tiff_page,
                trace_idx,
                trace_time,
                time_exact,
            )
        if frame_time is not None and not from_playback:
            self.jump_to_time(
                float(frame_time),
                from_playback=True,
                from_frame_change=True,
                source="video",
            )

        self.update_slider_marker()
        self._update_snapshot_status(idx)
        self._update_metadata_display(idx)

    def _update_snapshot_status(self, idx: int) -> None:
        self._update_snapshot_sampling_badge()
        total = len(self.snapshot_frames) if self.snapshot_frames else 0
        label = getattr(self, "snapshot_time_label", None)
        if label is None:
            return
        if total <= 0:
            label.setText("No TIFF loaded")
            return

        frame_number = idx + 1
        timestamp = None
        if self.frame_trace_time is not None and idx < len(self.frame_trace_time):
            try:
                timestamp = float(self.frame_trace_time[idx])
            except (TypeError, ValueError):
                timestamp = None
        elif self.frame_times and idx < len(self.frame_times):
            try:
                timestamp = float(self.frame_times[idx])
            except (TypeError, ValueError):
                timestamp = None
        if timestamp is None and self.recording_interval:
            try:
                timestamp = idx * float(self.recording_interval)
            except (TypeError, ValueError):
                timestamp = None
        total_time = None
        if self.frame_trace_time is not None and len(self.frame_trace_time):
            try:
                total_time = float(self.frame_trace_time[-1])
            except (TypeError, ValueError):
                total_time = None
        elif self.frame_times:
            try:
                total_time = float(self.frame_times[-1])
            except (TypeError, ValueError):
                total_time = None
        elif self.recording_interval:
            try:
                total_time = float(total - 1) * float(self.recording_interval)
            except (TypeError, ValueError):
                total_time = None
        info = self.snapshot_loading_info or {}
        if not isinstance(info, Mapping):
            info = {}
        original_total = info.get("total_frames")
        stride = info.get("frame_stride", 1)
        is_subsampled = bool(info.get("is_subsampled"))
        suffix = ""
        if is_subsampled and original_total and int(original_total) >= total and int(stride) >= 1:
            stride_text = self._format_stride_label(int(stride))
            suffix = f" (from original {int(original_total)} frames, {stride_text})"

        frame_text = f"Frame {frame_number} / {total}{suffix}"
        if timestamp is None:
            text = frame_text
        else:
            if total_time is not None and math.isfinite(total_time):
                text = f"{frame_text}   {timestamp:.2f} s / {total_time:.2f} s"
            else:
                text = f"{frame_text}   {timestamp:.2f} s"
        label.setText(text)

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
            if isinstance(value, list | tuple | np.ndarray):
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

    def _snapshot_view_visible(self) -> bool:
        widget = getattr(self, "snapshot_widget", None)
        return bool(widget and widget.isVisible())

    def _update_metadata_button_state(self) -> None:
        action = getattr(self, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(self, "frames_metadata", []))
        has_frames = bool(self.snapshot_frames)
        enabled = has_metadata and has_frames and self._snapshot_view_visible()

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

        is_visible = self._snapshot_view_visible()
        should_show = bool(action and action.isChecked() and enabled)
        self.metadata_panel.setVisible(should_show)
        if not should_show and not is_visible:
            # keep summary text in sync when hiding with the viewer
            self.metadata_details_label.setText("No metadata available.")

    def on_snapshot_speed_changed(self, value: float) -> None:
        try:
            multiplier = float(value)
        except (TypeError, ValueError):
            multiplier = 1.0

        if not math.isfinite(multiplier) or multiplier <= 0:
            multiplier = 1.0

        self.snapshot_speed_multiplier = multiplier
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_speed_multiplier(multiplier)

    def on_snapshot_sync_toggled(self, checked: bool) -> None:
        self.snapshot_sync_enabled = bool(checked)
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_sync_enabled(self.snapshot_sync_enabled)
        with contextlib.suppress(Exception):
            self._refresh_snapshot_sync_label()

    def on_snapshot_loop_toggled(self, checked: bool) -> None:
        """Handle loop playback checkbox toggle."""
        self.snapshot_loop_enabled = bool(checked)
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_loop(bool(checked))

    def _reset_snapshot_speed(self) -> None:
        self.snapshot_pps = float(getattr(self, "_snapshot_pps_default", 30.0))
        self.snapshot_speed_multiplier = 1.0

        if hasattr(self, "snapshot_speed_combo"):
            combo = getattr(self, "snapshot_speed_combo", None)
            if combo is not None:
                combo.blockSignals(True)
                for idx in range(combo.count()):
                    data = combo.itemData(idx)
                    if isinstance(data, (int, float)) and abs(float(data) - 1.0) < 0.01:
                        combo.setCurrentIndex(idx)
                        break
                combo.blockSignals(False)

        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_pps(self.snapshot_pps)
            with contextlib.suppress(Exception):
                viewer.set_speed_multiplier(self.snapshot_speed_multiplier)

    def _resolve_snapshot_pps_default(self) -> float:
        default_pps = 30.0
        raw_pps = os.environ.get("VA_SNAPSHOT_PPS", "").strip()
        if raw_pps:
            try:
                value = float(raw_pps)
            except (TypeError, ValueError):
                log.warning(
                    "Invalid VA_SNAPSHOT_PPS=%s; using default %.1f PPS",
                    raw_pps,
                    default_pps,
                )
                return default_pps
            if not math.isfinite(value) or value <= 0:
                log.warning(
                    "Invalid VA_SNAPSHOT_PPS=%s; using default %.1f PPS",
                    raw_pps,
                    default_pps,
                )
                return default_pps
            return value
        return default_pps

    def _sync_time_cursor_to_snapshot(self) -> None:
        frame_time = self._time_for_frame(self.current_frame)
        if frame_time is None:
            return
        self.jump_to_time(
            float(frame_time),
            from_playback=True,
            from_frame_change=True,
            source="video",
        )

    # Playback controller lives in the TIFF viewer v2 widget.
    def _update_playback_button_state(self, playing: bool) -> None:
        play_btn = getattr(self, "play_pause_btn", None)
        if play_btn is None:
            return
        play_btn.blockSignals(True)
        play_btn.setChecked(playing)
        play_btn.blockSignals(False)

        with contextlib.suppress(Exception):
            self._update_snapshot_playback_icons()
        # Button is icon-only, no text to update
        tooltip = "Pause snapshot playback" if playing else "Play snapshot sequence"
        play_btn.setToolTip(tooltip)

    def _set_playback_state(self, playing: bool) -> None:
        """Control playback using the v2 viewer controller."""
        if not self.snapshot_frames:
            playing = False
        play_btn = getattr(self, "play_pause_btn", None)
        was_playing = bool(play_btn.isChecked()) if play_btn is not None else False
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_playing(playing)
        if not playing and was_playing and self.snapshot_frames and self.snapshot_sync_enabled:
            self._sync_time_cursor_to_snapshot()

        self._update_playback_button_state(playing)

    def _on_snapshot_page_changed_v2(self, page_index: int, source: str) -> None:
        if not self.snapshot_frames:
            return
        try:
            idx = int(page_index)
        except (TypeError, ValueError):
            return
        idx = max(0, min(idx, len(self.snapshot_frames) - 1))
        self.current_frame = idx
        self.current_page = idx
        self.page_float = float(idx)
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
        self.update_slider_marker()
        self._update_snapshot_status(idx)
        self._update_metadata_display(idx)

    def _on_snapshot_playback_time_changed(self, trace_time: float) -> None:
        try:
            time_val = float(trace_time)
        except (TypeError, ValueError):
            return
        if math.isfinite(time_val):
            self._sync_trace_cursor_to_time(time_val)
            self._set_snapshot_sync_time(time_val)

    def _on_snapshot_playing_changed(self, playing: bool) -> None:
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_playing(bool(playing))
        self._update_playback_button_state(bool(playing))

    def toggle_snapshot_playback(self, checked: bool) -> None:
        if checked and not self.snapshot_frames:
            self._set_playback_state(False)
            return
        self._set_playback_state(bool(checked))

    def _mapped_trace_time_for_page(self, page_index: int) -> float | None:
        tiff_page = self._tiff_page_for_frame(page_index)
        if (
            tiff_page is not None
            and self.tiff_page_times_valid
            and 0 <= int(tiff_page) < len(self.tiff_page_times)
        ):
            return float(self.tiff_page_times[int(tiff_page)])
        if self.frame_trace_time is not None and page_index < len(self.frame_trace_time):
            with contextlib.suppress(Exception):
                return float(self.frame_trace_time[page_index])
        if self.frame_times and page_index < len(self.frame_times):
            with contextlib.suppress(Exception):
                return float(self.frame_times[page_index])
        return None

    def _sync_trace_cursor_to_time(self, trace_time: float) -> None:
        self._time_cursor_time = float(trace_time)
        self._highlight_selected_event(float(trace_time))
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "set_time_cursor"):
            return
        with contextlib.suppress(Exception):
            plot_host.set_time_cursor(float(trace_time), visible=True)
        # Keep the cursor visible during playback (page-scroll mode): when the cursor
        # exits the current window, jump so it lands at 20% from the left edge.
        with contextlib.suppress(Exception):
            if hasattr(plot_host, "current_window") and hasattr(plot_host, "set_time_window"):
                window = plot_host.current_window()
                if window is not None:
                    x0, x1 = window
                    span = x1 - x0
                    if span > 0 and not (x0 <= trace_time <= x1):
                        new_x0 = trace_time - span * 0.20
                        plot_host.set_time_window(new_x0, new_x0 + span)

    def step_previous_frame(self) -> None:
        if not self.snapshot_frames:
            return
        play_btn = getattr(self, "play_pause_btn", None)
        if play_btn is not None and play_btn.isChecked():
            self._set_playback_state(False)
        idx = (self.current_frame - 1) % len(self.snapshot_frames)
        self.set_current_frame(idx)

    def step_next_frame(self) -> None:
        if not self.snapshot_frames:
            return
        play_btn = getattr(self, "play_pause_btn", None)
        if play_btn is not None and play_btn.isChecked():
            self._set_playback_state(False)
        idx = (self.current_frame + 1) % len(self.snapshot_frames)
        self.set_current_frame(idx)

    def rotate_snapshot_ccw(self) -> None:
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is None:
            return
        rotate = getattr(viewer, "rotate_ccw_90", None)
        if callable(rotate):
            with contextlib.suppress(Exception):
                rotate()

    def rotate_snapshot_cw(self) -> None:
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is None:
            return
        rotate = getattr(viewer, "rotate_cw_90", None)
        if callable(rotate):
            with contextlib.suppress(Exception):
                rotate()

    def reset_snapshot_rotation(self) -> None:
        viewer = getattr(self, "snapshot_widget", None)
        if viewer is None:
            return
        reset = getattr(viewer, "reset_rotation", None)
        if callable(reset):
            with contextlib.suppress(Exception):
                reset()
        self._update_snapshot_rotation_controls()

    def set_snapshot_metadata_visible(self, visible: bool) -> None:
        action = getattr(self, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(self, "frames_metadata", []))
        can_show = has_metadata and bool(self.snapshot_frames) and self._snapshot_view_visible()
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
            with contextlib.suppress(Exception):
                self.plot_host.set_time_cursor(None, visible=False)
        self._clear_event_highlight()
        markers = getattr(self, "slider_markers", None)
        if not markers:
            self.slider_markers = {}
            self._on_view_state_changed(reason="time cursor cleared")
            return
        for line in list(markers.values()):
            with contextlib.suppress(Exception):
                line.remove()
        markers.clear()
        self._on_view_state_changed(reason="time cursor cleared")

    def _clear_pins(self) -> None:
        """Remove all pinned point markers/labels from the axes."""
        if not getattr(self, "pinned_points", None):
            self.pinned_points = []
            return
        for marker, label in list(self.pinned_points):
            self._safe_remove_artist(marker)
            self._safe_remove_artist(label)
        self.pinned_points.clear()

    def update_slider_marker(self):
        # Make sure we have a trace and some TIFF frames
        if self.trace_data is None or not self.snapshot_frames:
            return
        if self.slider is None:
            return

        # 1) Get the current slider index
        idx = self.slider.value()

        # 2) Lookup the timestamp for this frame
        t_current = None
        if self.frame_trace_index is not None and idx < len(self.frame_trace_index):
            trace_idx = int(self.frame_trace_index[idx])
            if self.trace_time is not None and trace_idx < len(self.trace_time):
                t_current = float(self.trace_time[trace_idx])
            elif self.trace_data is not None:
                with contextlib.suppress(Exception):
                    t_current = float(self.trace_data["Time (s)"].iat[trace_idx])
        elif self.frame_trace_time is not None and idx < len(self.frame_trace_time):
            t_current = float(self.frame_trace_time[idx])
        elif idx < len(self.frame_times):
            t_current = float(self.frame_times[idx])
        elif self.recording_interval:
            t_current = idx * self.recording_interval

        if t_current is None:
            return

        # 3) Drive the shared time cursor overlay (fallback on legacy per-axis markers)
        self._time_cursor_time = float(t_current)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            try:
                plot_host.set_time_cursor(
                    self._time_cursor_time,
                    visible=self._time_cursor_visible,
                )
                self._on_view_state_changed(reason="time cursor moved")
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
        self._on_view_state_changed(reason="time cursor moved")

    def populate_event_table_from_df(self, df):
        rows = []
        has_od = any(col.lower().startswith("od") or "outer" in col.lower() for col in df.columns)
        has_avg_p = any("avg" in col.lower() and "pressure" in col.lower() for col in df.columns)
        has_set_p = any("set" in col.lower() and "pressure" in col.lower() for col in df.columns)

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

            od_val = None
            if has_od:
                od_val = item.get("OD (µm)", item.get("Outer Diameter", None))
                try:
                    od_val = float(od_val) if od_val is not None else None
                except (TypeError, ValueError):
                    od_val = None

            avg_p_val = None
            if has_avg_p:
                avg_p_val = item.get("Avg P (mmHg)", item.get("Avg Pressure (mmHg)", None))
                try:
                    avg_p_val = float(avg_p_val) if avg_p_val is not None else None
                except (TypeError, ValueError):
                    avg_p_val = None

            set_p_val = None
            if has_set_p:
                set_p_val = item.get("Set P (mmHg)", item.get("Set Pressure (mmHg)", None))
                try:
                    set_p_val = float(set_p_val) if set_p_val is not None else None
                except (TypeError, ValueError):
                    set_p_val = None

            try:
                frame_val = int(frame_val)
            except (TypeError, ValueError):
                frame_val = 0

            # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
            rows.append((str(label), time_val, id_val, od_val, avg_p_val, set_p_val, frame_val))

        self.event_table_data = rows
        self.event_label_meta = [self._with_default_review_state(None) for _ in rows]
        self.event_table_controller.set_events(
            rows,
            has_outer_diameter=has_od,
            has_avg_pressure=has_avg_p,
            has_set_pressure=has_set_p,
            review_states=self._current_review_states(),
        )
        self._apply_event_table_column_contract()
        self._update_excel_controls()

    def update_event_label_positions(self, event=None):
        """Legacy hook; annotation lane handles positioning automatically."""
        return

    def _init_hover_artists(self) -> None:
        """Create per-axis hover annotations and crosshair lines."""

        for line in getattr(self, "_hover_vlines", []) or []:
            if line is None:
                continue
            with contextlib.suppress(Exception):
                line.remove()
        self._hover_vlines = []
        self._hover_vline_inner = None
        self._hover_vline_outer = None

        for annot in (
            getattr(self, "hover_annotation_id", None),
            getattr(self, "hover_annotation_od", None),
        ):
            if annot is None:
                continue
            with contextlib.suppress(Exception):
                annot.remove()

        # Check if we're using PyQtGraph renderer
        plot_host = getattr(self, "plot_host", None)
        is_pyqtgraph = plot_host is not None and plot_host.get_render_backend() == "pyqtgraph"

        # PyQtGraph doesn't support matplotlib-style annotations
        # For now, disable hover annotations when using PyQtGraph
        # TODO: Implement PyQtGraph-specific hover feedback using TextItem
        # NOTE: This hover/pin path is Matplotlib-only; Phase 3 should replace
        # it with a PyQtGraph-native implementation or remove the legacy branch.
        if is_pyqtgraph:
            self.hover_annotation_id = None
            self.hover_annotation_od = None
            return

        # Matplotlib-specific hover annotations
        line_color = CURRENT_THEME.get("cursor_line", CURRENT_THEME.get("grid_color", "#6e7687"))

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
                self.open_project_file(vaso_path)
            except Exception as e:
                error_msg = str(e)

                # Check if this was a database corruption error
                if "corrupted" in error_msg.lower() or "malformed" in error_msg.lower():
                    # Check if project is in cloud storage
                    from vasoanalyzer.core.project import _is_cloud_storage_path

                    is_cloud, cloud_service = _is_cloud_storage_path(vaso_path)

                    cloud_warning = ""
                    if is_cloud:
                        cloud_warning = (
                            f"\n\n⚠️ IMPORTANT: This project is stored in {cloud_service}.\n"
                            f"SQLite databases are INCOMPATIBLE with cloud storage and will become corrupted.\n\n"
                            f"To fix this:\n"
                            f"1. Move this project to a LOCAL folder (e.g., ~/Documents or ~/Desktop)\n"
                            f"2. Create a new project in the local folder\n"
                            f"3. Never store .vaso projects in iCloud, Dropbox, or other cloud storage\n\n"
                        )

                    if "backup was created" in error_msg:
                        QMessageBox.critical(
                            self,
                            "Project Database Corrupted",
                            f"The project database is corrupted and automatic recovery failed."
                            f"{cloud_warning}\n"
                            f"A backup was created at: {vaso_path}.backup\n\n"
                            f"Please check the backup or create a new project.",
                        )
                    else:
                        QMessageBox.critical(
                            self,
                            "Project Database Error",
                            f"Could not open project due to database error."
                            f"{cloud_warning}\n"
                            f"The database may be corrupted.",
                        )
                else:
                    QMessageBox.critical(
                        self,
                        "Project Load Error",
                        f"Could not open project:\n{e}",
                    )
                return
            return

        h5_path = next((p for p in files if p.lower().endswith(".h5")), None)
        if h5_path:
            event.acceptProposedAction()
            self.open_analysis(h5_path)
            return

        csv_files = [p for p in files if p.lower().endswith(".csv")]
        tiff_files = [p for p in files if p.lower().endswith(".tif") or p.lower().endswith(".tiff")]

        if csv_files:
            event.acceptProposedAction()
            tiff_path = tiff_files[0] if tiff_files else None
            self._import_trace_events_from_paths(
                csv_files[0],
                tiff_path=tiff_path,
                source="drag_and_drop",
            )
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
            with open(file_path, encoding="utf-8") as f:
                state = json.load(f)

            # Restore basic session state
            td = state.get("trace_data", None)
            if td is not None:
                import pandas as pd

                self.trace_data = self._prepare_trace_dataframe(pd.DataFrame(td))
                self._update_trace_sync_state()
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
            is_pg = self._plot_host_is_pyqtgraph()
            self._set_shared_xlabel(state.get("xlabel", "Time (s)"))
            if not is_pg and self.ax is not None:
                self.ax.set_ylabel(state.get("ylabel", "Inner Diameter (µm)"))
            self._apply_time_window(state.get("xlim", self.ax.get_xlim() if self.ax else None))
            if is_pg:
                inner_track = self.plot_host.track("inner") if hasattr(self, "plot_host") else None
                if inner_track is not None:
                    ylim = state.get("ylim")
                    if ylim:
                        inner_track.set_ylim(*ylim)
            elif self.ax is not None:
                self.ax.set_ylim(*state.get("ylim", self.ax.get_ylim()))
            self.grid_visible = state.get("grid_visible", True)
            if is_pg:
                for track in getattr(self.plot_host, "tracks", lambda: [])():
                    track.set_grid_visible(self.grid_visible)
            else:
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

            # Re-plot pinned points for the active renderer
            self.pinned_points.clear()
            if is_pg:
                inner_track = self.plot_host.track("inner") if hasattr(self, "plot_host") else None
                if inner_track is not None:
                    inner_track.clear_pins()
                    for x, y in state.get("pinned_points", []):
                        marker, label = inner_track.add_pin(x, y, f"{x:.2f} s\n{y:.1f} µm")
                        self.pinned_points.append((marker, label))
            else:
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

    def _handle_load_trace(self, checked: bool = False):
        """Handle loading a trace file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Trace File(s)", "", "CSV Files (*.csv)"
        )
        if not file_paths:
            return

        trace_source: str | list[str]
        if len(file_paths) > 1:
            choice = self._prompt_merge_traces(file_paths)
            if choice == "cancel":
                return
            trace_source = file_paths if choice == "merge" else file_paths[0]
        else:
            trace_source = file_paths[0]
        self._import_trace_events_from_paths(trace_source, source="file_dialog")

    def _build_vasotracker_prefetched_payload(
        self,
        trace_path: str,
        *,
        source_format: str,
    ) -> tuple[
        pd.DataFrame,
        list[str],
        list[float],
        list[int | None],
        list[float | None],
        list[float | None],
        dict[str, Any],
    ]:
        trace_path_obj = Path(trace_path)
        table_path = guess_vasotracker_table_csv_for_trace(trace_path_obj)

        if source_format == "vasotracker_v1":
            frames, events, report = import_vasotracker_v1(
                trace_path_obj,
                table_csv_path=table_path,
                normalize_time_to_zero=True,
                generate_frame_numbers="row_index",
                set_table_markers=True,
            )
        elif source_format == "vasotracker_v2":
            frames, events, report = import_vasotracker_v2(
                trace_path_obj,
                table_csv_path=table_path,
                normalize_time_to_zero=False,
            )
        else:
            raise ValueError(f"Unsupported source format: {source_format}")

        trace_df = trace_frames_to_dataframe(frames)
        trace_df.attrs["negative_inner_diameters"] = int(
            report.stats.get("negative_inner_diameter_count", 0) or 0
        )
        trace_df.attrs["negative_outer_diameters"] = int(
            report.stats.get("negative_outer_diameter_count", 0) or 0
        )
        trace_df.attrs["negative_diameters_sanitized"] = False

        labels, times, frame_numbers, diam, od_diam = event_rows_to_legacy_payload(events)
        import_meta: dict[str, Any] = {
            "trace_original_filename": trace_path_obj.name,
            "event_file": str(table_path) if table_path is not None else None,
            "auto_detected": table_path is not None,
            "import_source_format": report.source_format,
            "import_warnings": list(report.warnings),
            "import_errors": list(report.errors),
            "import_stats": dict(report.stats),
            "import_timestamp": self._utc_iso_timestamp(),
        }
        if table_path is not None:
            import_meta["events_original_filename"] = table_path.name
        if report.errors:
            import_meta["event_merge_warnings"] = list(report.errors)

        return (
            trace_df,
            labels,
            times,
            frame_numbers,
            diam,
            od_diam,
            import_meta,
        )

    def _handle_load_vasotracker_v1(self, checked: bool = False) -> None:
        """Import a VasoTracker v1 trace/table pair through the normalized pipeline."""

        trace_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select VasoTracker v1 trace CSV",
            "",
            "CSV Files (*.csv)",
        )
        if not trace_path:
            return
        try:
            payload = self._build_vasotracker_prefetched_payload(
                trace_path,
                source_format="vasotracker_v1",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "VasoTracker v1 Import Error",
                f"Could not import VasoTracker v1 files:\n{exc}",
            )
            return
        self._import_trace_events_from_paths(
            trace_path,
            source="vasotracker_v1",
            prefetched_payload=payload,
        )

    def _handle_load_vasotracker_v2(self, checked: bool = False) -> None:
        """Import a VasoTracker v2 trace/table pair through the normalized pipeline."""

        trace_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select VasoTracker v2 trace CSV",
            "",
            "CSV Files (*.csv)",
        )
        if not trace_path:
            return
        try:
            payload = self._build_vasotracker_prefetched_payload(
                trace_path,
                source_format="vasotracker_v2",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "VasoTracker v2 Import Error",
                f"Could not import VasoTracker v2 files:\n{exc}",
            )
            return
        self._import_trace_events_from_paths(
            trace_path,
            source="vasotracker_v2",
            prefetched_payload=payload,
        )

    def _prompt_merge_traces(self, paths: list[str]) -> str:
        """Ask the user whether to merge multiple trace CSVs."""
        box = QMessageBox(self)
        box.setWindowTitle("Merge trace CSVs?")
        box.setText(
            f"{len(paths)} trace CSV files selected.\nMerge them into one continuous dataset?"
        )
        merge_btn = box.addButton("Merge into one trace", QMessageBox.AcceptRole)
        single_btn = box.addButton("Load first only", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(merge_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == merge_btn:
            return "merge"
        if clicked == single_btn:
            return "single"
        return "cancel"

    def _import_trace_events_from_paths(
        self,
        trace_path: str | list[str],
        *,
        tiff_path: str | None = None,
        source: str = "manual",
        prefetched_payload: tuple[
            pd.DataFrame,
            list[str],
            list[float],
            list[int | None] | None,
            list[float | None] | None,
            list[float | None] | None,
            Mapping[str, Any] | None,
        ]
        | None = None,
    ) -> None:
        """Shared entry point for importing trace/events data from any UI path."""
        if not trace_path:
            return
        log.debug(
            "Import request via %s: trace=%s tiff=%s",
            source,
            trace_path,
            tiff_path or "auto-prompt",
        )

        # Show data preview for user-initiated imports (file dialog or drag-drop)
        if source in ("file_dialog", "manual", "drag_drop") and not prefetched_payload:
            single_path = trace_path if isinstance(trace_path, str) else trace_path[0]
            try:
                preview_df = pd.read_csv(single_path, nrows=100)
                from vasoanalyzer.ui.dialogs.data_preview_dialog import DataPreviewDialog

                events_path = find_matching_event_file(single_path)
                events_df = None
                if events_path:
                    try:
                        events_df = pd.read_csv(events_path, nrows=100)
                    except Exception:
                        log.warning("Failed to load events CSV preview from %s", events_path, exc_info=True)

                dlg = DataPreviewDialog(
                    self,
                    trace_path=single_path,
                    trace_df=preview_df,
                    events_df=events_df,
                    source_format=source,
                )
                if dlg.exec_() != QDialog.Accepted:
                    return
            except Exception:
                log.debug("Could not show data preview, proceeding with import", exc_info=True)

        self.load_trace_and_events(
            file_path=trace_path,
            tiff_path=tiff_path,
            source=source,
            prefetched_payload=prefetched_payload,
        )

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

    def _initial_time_window(self) -> tuple[float, float] | None:
        full_range = self._trace_full_range()
        if full_range is None:
            return None

        t0 = None
        t1 = None
        if isinstance(self.trace_time, np.ndarray) and self.trace_time.size:
            t0 = float(self.trace_time[0])
            t1 = float(self.trace_time[-1])
        elif self.trace_model is not None:
            time_full = getattr(self.trace_model, "time_full", None)
            if isinstance(time_full, np.ndarray) and time_full.size:
                t0 = float(time_full[0])
                t1 = float(time_full[-1])

        if t0 is None or t1 is None or not (math.isfinite(t0) and math.isfinite(t1)):
            t0 = float(full_range[0])
            t1 = float(full_range[1])
        if not (math.isfinite(t0) and math.isfinite(t1)):
            return None
        if t1 < t0:
            t0, t1 = t1, t0

        span = t1 - t0
        if span <= 0:
            return (t0, t1)

        window_end = t0 + DEFAULT_INITIAL_VIEW_SECONDS
        if window_end > t1:
            window_end = t1
        return (t0, window_end)

    def _reset_time_scrollbar_to_start(self) -> None:
        slider = self.scroll_slider
        if slider is None:
            return
        self.update_scroll_slider()
        self._updating_time_scrollbar = True
        blocker = QSignalBlocker(slider)
        try:
            slider.setValue(slider.minimum())
        finally:
            self._updating_time_scrollbar = False
            del blocker

    def _force_trace_start_view(self, window: tuple[float, float]) -> None:
        if window is None:
            return
        t0, t1 = float(window[0]), float(window[1])
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_time_window"):
            self._set_xrange_source("load.start", (t0, t1))
            plot_host.set_time_window(t0, t1)
            if hasattr(plot_host, "force_primary_xrange"):
                plot_host.force_primary_xrange()
        elif plot_host is not None and hasattr(plot_host, "force_primary_xrange"):
            self._set_xrange_source("load.start", (t0, t1))
            try:
                plot_host.force_primary_xrange()
            except TypeError:
                plot_host.force_primary_xrange(t0, t1)
        elif self.ax is not None:
            self.ax.set_xlim(t0, t1)
            self.canvas.draw_idle()
        self._last_x_window_width_s = float(t1 - t0)
        self._reset_time_scrollbar_to_start()

    # [E] ========================= PLOTTING AND EVENT SYNC ============================
    def update_plot(self, track_limits: bool = True):
        t0 = time.perf_counter()
        try:
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

            self._apply_toggle_state(inner_visible, outer_visible, outer_supported=has_outer)
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
            sample = getattr(self, "current_sample", None)
            dataset_id = getattr(sample, "dataset_id", None)
            cached_window = None
            if dataset_id is not None:
                cached_window = self._window_cache.get(dataset_id)
            prev_window = cached_window or self.plot_host.current_window()
            try:
                self.trace_model = self._get_trace_model_for_sample(self.current_sample)
            except Exception:
                log.exception("Failed to build trace model from dataframe")
                return

            self.plot_host.set_trace_model(self.trace_model)
            if self.zoom_dock:
                self.zoom_dock.set_trace_model(self.trace_model)
            if self.scope_dock:
                self.scope_dock.set_trace_model(self.trace_model)
            initial_window = None
            if track_limits or prev_window is None:
                # Default initial view: first slice of the recording (start-aligned).
                initial_window = self._initial_time_window()
                if initial_window is not None:
                    target_window = initial_window
                    full_range = self.trace_model.full_range
                    if full_range[1] - full_range[0] > DEFAULT_INITIAL_VIEW_SECONDS:
                        log.info(
                            "Initial load: showing first %.0f seconds of %.0f second trace",
                            DEFAULT_INITIAL_VIEW_SECONDS,
                            full_range[1] - full_range[0],
                        )
                else:
                    target_window = self.trace_model.full_range
            else:
                target_window = prev_window
            self.plot_host.set_time_window(*target_window)
            self._last_x_window_width_s = float(target_window[1] - target_window[0])
            # NOTE: Removed redundant autoscale_all() call here - set_time_window() already
            # performs autoscaling internally via _apply_window(). Calling autoscale_all()
            # again causes double rendering of all tracks, which is especially slow for
            # datasets with multiple pressure channels (4 tracks × 2 = 8 expensive updates).
            # This was causing 9+ second load times for multi-track datasets.
            # if track_limits and prev_window is None:
            #     self.plot_host.autoscale_all()
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
                self._ensure_event_meta_length(len(self.event_labels))
                self.plot_host.set_events(
                    self.event_times,
                    labels=self.event_labels,
                    label_meta=self.event_label_meta,
                )
                # Enable event label rendering for matplotlib; PyQtGraph defaults to off.
                if not self._plot_host_is_pyqtgraph():
                    self.plot_host.set_event_labels_visible(True)
                annotations = self.event_annotations or []
                self._annotation_lane_visible = True
                self.plot_host.set_annotation_entries(annotations)
                self._refresh_event_annotation_artists()
            else:
                self.plot_host.set_events([], labels=[], label_meta=[])
                # Disable event label rendering when no events
                self.plot_host.set_event_labels_visible(False)
                self.event_table_data = []
                self.event_metadata = []
                self.event_text_objects = []
                self.event_annotations = []
                self.event_label_meta = []
                self._annotation_lane_visible = True
                self.plot_host.set_annotation_entries([])
                self._refresh_event_annotation_artists()

            self._update_trace_controls_state()
            self._refresh_plot_legend()
            self.canvas.setToolTip("")

            # Apply plot style (defaults on first load) - defer draw to avoid redundant redraws
            self.apply_plot_style(self.get_current_plot_style(), persist=False, draw=False)
            self._apply_pending_pyqtgraph_track_state()
            self._refresh_trace_navigation_data()
            self.canvas.draw_idle()

            if initial_window is not None:
                self._force_trace_start_view(initial_window)
            self._refresh_zoom_window()

            # Cache the current window for this dataset to avoid re-autoscaling on next load
            sample = getattr(self, "current_sample", None)
            dsid = getattr(sample, "dataset_id", None)
            if dsid is not None:
                window = self.plot_host.current_window() if hasattr(self, "plot_host") else None
                if window is not None:
                    self._window_cache[dsid] = window

            # Force the shared X-axis to be visible even on initial load (pyqtgraph)
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                try:
                    updater = getattr(plot_host, "_update_bottom_axis_assignments", None)
                    if callable(updater):
                        updater()
                    bottom_axis = getattr(plot_host, "bottom_axis", lambda: None)()
                    if bottom_axis is not None:
                        with contextlib.suppress(Exception):
                            bottom_axis.setVisible(True)
                            bottom_axis.setStyle(showValues=True, tickLength=5)
                            bottom_axis.setLabel(self._shared_xlabel or "Time (s)")
                            bottom_axis.showLabel(True)
                except Exception:
                    log.debug("Failed to force bottom axis visibility", exc_info=True)

        finally:
            log.debug("update_plot completed in %.3f s", time.perf_counter() - t0)

    def _refresh_plot_legend(self):
        if not hasattr(self, "ax"):
            return

        legend = getattr(self, "plot_legend", None)
        if legend is not None:
            with contextlib.suppress(Exception):
                legend.remove()
        self.plot_legend = None
        # Canvas draw is handled by caller - no need to draw here

    def apply_legend_settings(self, settings=None, *, mark_dirty: bool = False) -> None:
        """Merge ``settings`` into the current legend options and refresh."""

        merged = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)

        if isinstance(self.legend_settings, dict):
            existing = _copy_legend_settings(self.legend_settings)
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
        stored_labels = (current_settings.get("labels") or {}) if current_settings else {}
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

    def _on_trace_nav_window_requested(self, x0: float, x1: float) -> None:
        self._apply_time_window((x0, x1))
        self.mark_session_dirty(reason="view range changed")

    def _trace_full_range(self) -> tuple[float, float] | None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "full_range"):
            with contextlib.suppress(Exception):
                full = plot_host.full_range()
                if full is not None:
                    return float(full[0]), float(full[1])
        if self.trace_model is not None:
            try:
                return self.trace_model.full_range
            except Exception:
                log.debug("Failed to get trace model full range", exc_info=True)
        if self.trace_data is not None and "Time (s)" in self.trace_data.columns:
            series = self.trace_data["Time (s)"]
            with contextlib.suppress(Exception):
                return float(series.min()), float(series.max())
        return None

    def _set_trace_navigation_visible(self, visible: bool) -> None:
        self._trace_navigation_available = bool(visible)
        self._apply_overview_strip_visibility()
        nav_bar = getattr(self, "trace_nav_bar", None)
        if nav_bar is not None:
            nav_bar.setVisible(bool(visible))
            nav_bar.setEnabled(bool(visible))

    def _apply_overview_strip_visibility(self) -> None:
        overview = getattr(self, "overview_strip", None)
        if overview is None:
            return
        is_available = bool(getattr(self, "_trace_navigation_available", False))
        overview_visible = is_available and bool(self._overview_strip_enabled)
        overview.setVisible(overview_visible)
        overview.setEnabled(overview_visible)

    def toggle_overview_strip(self, checked: bool) -> None:
        self._overview_strip_enabled = bool(checked)
        self._apply_overview_strip_visibility()

    def toggle_channel_event_labels(self, checked: bool) -> None:
        """Show or hide vertical event text labels inside channel tracks."""
        self._channel_event_labels_visible = bool(checked)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_channel_event_labels_visible"):
            plot_host.set_channel_event_labels_visible(self._channel_event_labels_visible)

    def set_channel_event_label_font_size(self, size_pt: float) -> None:
        """Set the event label font size and update checked state in the size menu."""
        self._channel_event_label_font_size = float(size_pt)
        # Sync checkmarks in the font-size submenu.
        size_group = getattr(self, "_event_label_font_size_group", None)
        if size_group is not None:
            for action in size_group.actions():
                with contextlib.suppress(Exception):
                    action.setChecked(float(action.data()) == self._channel_event_label_font_size)
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_channel_event_label_font_size"):
            plot_host.set_channel_event_label_font_size(self._channel_event_label_font_size)

    def _overview_event_times(self) -> list[float]:
        rows = list(getattr(self, "event_table_data", []) or [])
        times: list[float] = []
        if rows:
            for row in rows:
                if len(row) < 2:
                    continue
                try:
                    t_val = float(row[1])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(t_val):
                    times.append(t_val)
            return times
        times = [float(t) for t in getattr(self, "event_times", []) or [] if t is not None]
        return [t for t in times if math.isfinite(t)]

    def _refresh_overview_events(self) -> None:
        overview = getattr(self, "overview_strip", None)
        if overview is None:
            return
        overview.set_events(self._overview_event_times())

    def _refresh_trace_navigation_data(self) -> None:
        overview = getattr(self, "overview_strip", None)
        if overview is None:
            return

        full_range = self._trace_full_range()
        if self.trace_model is None or full_range is None:
            overview.clear()
            self._set_trace_navigation_visible(False)
            return

        overview.set_trace_model(self.trace_model)
        overview.set_full_range(*full_range)
        plot_host = getattr(self, "plot_host", None)
        window = plot_host.current_window() if plot_host is not None else None
        if window is not None:
            overview.set_time_window(window[0], window[1])
        self._refresh_overview_events()
        self._set_trace_navigation_visible(True)

    def _plot_host_is_pyqtgraph(self) -> bool:
        plot_host = getattr(self, "plot_host", None)
        is_pg = bool(plot_host is not None and plot_host.get_render_backend() == "pyqtgraph")
        if (
            not is_pg
            and hasattr(self, "action_select_range")
            and self.action_select_range is not None
        ):
            with contextlib.suppress(Exception):
                self.action_select_range.blockSignals(True)
                self.action_select_range.setChecked(False)
                self.action_select_range.blockSignals(False)
        return is_pg

    def _attach_plot_host_window_listener(self) -> None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "add_time_window_listener"):
            return
        listener = getattr(self, "_plot_host_window_listener", None)
        if listener is not None and hasattr(plot_host, "remove_time_window_listener"):
            plot_host.remove_time_window_listener(listener)
        self._plot_host_window_listener = self._on_plot_host_time_window_changed
        plot_host.add_time_window_listener(self._plot_host_window_listener)
        if (
            os.getenv("VASO_DEBUG_XRANGE") == "1"
            and hasattr(plot_host, "attach_xrange_debug")
            and not getattr(self, "_xrange_debug_attached", False)
        ):
            attached = plot_host.attach_xrange_debug(
                lambda: (
                    self._xrange_source,
                    self._xrange_expected,
                    bool(getattr(self, "_scrolling_from_scrollbar", False)),
                ),
                set_source_callable=self._set_xrange_source,
            )
            if attached:
                self._xrange_debug_attached = True

    def _on_plot_host_time_window_changed(self, x0: float, x1: float) -> None:
        if getattr(self, "_syncing_time_window", False):
            return
        if os.getenv("VASO_DEBUG_XRANGE") == "1" and not getattr(
            self, "_xrange_debug_attached", False
        ):
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "attach_xrange_debug"):
                attached = plot_host.attach_xrange_debug(
                    lambda: (
                        self._xrange_source,
                        self._xrange_expected,
                        bool(getattr(self, "_scrolling_from_scrollbar", False)),
                    ),
                    set_source_callable=self._set_xrange_source,
                )
                if attached:
                    self._xrange_debug_attached = True
        self._update_last_x_window_width(x0, x1)
        try:
            self.update_scroll_slider()
        except Exception:
            log.exception("Failed to synchronize time scrollbar with plot window")
        overview = getattr(self, "overview_strip", None)
        if overview is not None:
            overview.set_time_window(x0, x1)
        self._invalidate_sample_state_cache()
        plot_host = getattr(self, "plot_host", None)
        is_user_range = bool(
            plot_host
            and hasattr(plot_host, "is_user_range_change_active")
            and plot_host.is_user_range_change_active()
        )
        if is_user_range:
            self.mark_session_dirty(reason="view range changed")

    def _collect_plot_view_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and plot_host.get_render_backend() == "pyqtgraph":
            window = plot_host.current_window()
            if window is not None:
                state["axis_xlim"] = [float(window[0]), float(window[1])]
            track_state: dict[str, Any] = {}
            tracks = []
            with contextlib.suppress(Exception):
                tracks = plot_host.tracks()
            for track in tracks or []:
                view = getattr(track, "view", None)
                if view is None:
                    continue
                try:
                    ymin, ymax = view.get_ylim()
                except Exception:
                    continue
                track_state[track.id] = {
                    "ylim": [float(ymin), float(ymax)],
                    "autoscale": view.is_autoscale_enabled(),
                }
            if track_state:
                state["pyqtgraph_track_state"] = track_state
            state["event_text_labels_on_trace"] = bool(plot_host.event_labels_visible())
            return state

        if self.ax is not None:
            state["axis_xlim"] = list(self.ax.get_xlim())
            state["axis_ylim"] = list(self.ax.get_ylim())
        if self.ax2 is not None:
            state["axis_outer_ylim"] = list(self.ax2.get_ylim())
        return state

    def _apply_pyqtgraph_track_state(self, track_state: dict | None) -> None:
        if not track_state:
            self._pending_pyqtgraph_track_state = None
            return
        plot_host = getattr(self, "plot_host", None)
        if (
            plot_host is None
            or plot_host.get_render_backend() != "pyqtgraph"
            or not hasattr(plot_host, "track")
        ):
            self._pending_pyqtgraph_track_state = track_state
            return

        for track_id, payload in track_state.items():
            track = plot_host.track(track_id)
            if track is None:
                continue
            autoscale = bool(payload.get("autoscale"))
            if autoscale:
                track.view.set_autoscale_y(True)
                with contextlib.suppress(Exception):
                    track.autoscale()
                continue
            ylim = payload.get("ylim")
            if isinstance(ylim, list | tuple) and len(ylim) == 2:
                try:
                    y0 = float(ylim[0])
                    y1 = float(ylim[1])
                except (TypeError, ValueError):
                    continue
                track.set_ylim(y0, y1)
        self._pending_pyqtgraph_track_state = None
        self._sync_autoscale_y_action_from_host()

    def _apply_pending_pyqtgraph_track_state(self) -> None:
        if self._pending_pyqtgraph_track_state:
            self._apply_pyqtgraph_track_state(self._pending_pyqtgraph_track_state)

    def _sync_time_window_from_axes(self) -> None:
        """Pull the current Matplotlib limits back into PlotHost."""

        if getattr(self, "_syncing_time_window", False):
            return

        primary_ax = self.plot_host.primary_axis() if hasattr(self, "plot_host") else None
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
            with contextlib.suppress(Exception):
                self._axis_source_axis.callbacks.disconnect(self._axis_xlim_cid)
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
        self._set_xrange_source("axis_xlim_changed", (float(xlim[0]), float(xlim[1])))
        self._update_last_x_window_width(xlim[0], xlim[1])
        self._apply_time_window(xlim)
        self.update_scroll_slider()
        self._invalidate_sample_state_cache()

    def scroll_plot(self) -> None:
        if self.scroll_slider is None:
            return
        self.scroll_plot_user(self.scroll_slider.value(), source="valueChanged")

    def scroll_plot_user(self, value: int, *, source: str | None = None) -> None:
        if self.trace_data is None or self.scroll_slider is None:
            return
        if getattr(self, "_updating_time_scrollbar", False):
            return

        full_range = self._trace_full_range()
        if full_range is None:
            return
        window = self._current_time_window()
        full_t_min, full_t_max = full_range

        width = self._scrollbar_drag_width_s
        if width is None or width <= 0:
            width = self._last_x_window_width_s
        if width is None or width <= 0:
            if window is not None:
                width = window[1] - window[0]
            else:
                width = full_t_max - full_t_min
        if width <= 0:
            return

        max_scroll = max(1, self.scroll_slider.maximum())
        new_left, new_right = window_from_scroll_value(
            value,
            t0=full_t_min,
            t1=full_t_max,
            current_width=width,
            max_value=max_scroll,
        )

        source_label = source or "scrollbar"
        self._set_xrange_source(f"scrollbar.{source_label}", (new_left, new_right))
        self._apply_time_window((new_left, new_right))
        self.mark_session_dirty(reason="view range changed")

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
        event_label = row_data[0] if row_data else ""
        self._change_log.record_event_value_edit(row, old_val, rounded_val, event_label)
        self._mark_row_edited(row)
        self.mark_session_dirty()
        self._sync_event_data_from_table()

    def handle_event_label_edit(self, row: int, new_label: str, old_label: str) -> None:
        if not (0 <= row < len(self.event_table_data)):
            return

        label_text = "" if new_label is None else str(new_label)
        row_data = list(self.event_table_data[row])
        if not row_data or row_data[0] == label_text:
            return

        row_data[0] = label_text
        self.event_table_data[row] = tuple(row_data)
        self._change_log.record_event_label_edit(row, old_label, label_text)

        if not hasattr(self, "event_labels") or self.event_labels is None:
            self.event_labels = []
        if len(self.event_labels) < len(self.event_table_data):
            self.event_labels.extend(
                "" for _ in range(len(self.event_table_data) - len(self.event_labels))
            )
        if row < len(self.event_labels):
            self.event_labels[row] = label_text
        else:
            self.event_labels.append(label_text)

        self._ensure_event_meta_length(len(self.event_table_data))
        self._mark_row_edited(row)
        self.apply_event_label_overrides(self.event_labels, self.event_label_meta)

    def _selected_event_rows(self) -> list[int]:
        event_table = getattr(self, "event_table", None)
        if event_table is None:
            return []
        selection = event_table.selectionModel()
        if selection is None:
            return []
        return sorted({index.row() for index in selection.selectedIndexes() if index.isValid()})

    def _on_event_table_selection_changed(self, *_args) -> None:
        if self._event_table_updating or self._event_selection_syncing:
            return
        event_table = getattr(self, "event_table", None)
        if event_table is None or not event_table.isEnabled():
            return
        rows = self._selected_event_rows()
        if not rows:
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
                with contextlib.suppress(Exception):
                    plot_host.set_selected_event_index(None)
            return
        target_row = pick_event_row(rows, self.event_table_data)
        if target_row is None:
            return
        self._focus_event_row(target_row, source="selection")

    def _warn_event_sync(self, message: str) -> None:
        log.warning("Event sync: %s", message)
        status = getattr(self, "statusBar", None)
        if callable(status):
            status().showMessage(message, 4000)

    def _event_time_in_range(self, event_time: float) -> bool:
        if self.trace_time is None or len(self.trace_time) == 0:
            return False
        t_min = float(np.nanmin(self.trace_time))
        t_max = float(np.nanmax(self.trace_time))
        if not (np.isfinite(t_min) and np.isfinite(t_max)):
            return False
        eps = 1e-6
        return (t_min - eps) <= event_time <= (t_max + eps)

    def table_row_clicked(self, row, col):
        self._focus_event_row(row, source="table")

    def _focus_event_row(self, row: int, *, source: str) -> None:
        if not self.event_table_data or not (0 <= row < len(self.event_table_data)):
            return
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "set_selected_event_index"):
            with contextlib.suppress(Exception):
                plot_host.set_selected_event_index(int(row))

        # Sync review panel if active (unless source is already review_controller)
        if hasattr(self, "review_controller") and source != "review_controller":
            if self.review_controller.is_active():
                self.review_controller.sync_to_event(row)

        event_time = event_time_for_row(self.event_table_data[row])
        if event_time is None:
            self._warn_event_sync("Event time missing for selected row; selection ignored.")
            return
        if self.trace_time is None or len(self.trace_time) == 0:
            self._warn_event_sync("Trace timebase unavailable; selection ignored.")
            return
        if not self._event_time_in_range(event_time):
            self._warn_event_sync(
                f"Event time {event_time:.3f}s outside trace range; selection ignored."
            )
            return
        label_value = ""
        with contextlib.suppress(Exception):
            label_value = str(self.event_table_data[row][0] or "").strip()
        status_text = (
            f"Event {row + 1}: {label_value} @ {event_time:.3f}s"
            if label_value
            else f"Event {row + 1} @ {event_time:.3f}s"
        )
        with contextlib.suppress(Exception):
            self.statusBar().showMessage(status_text, 4000)

        if source not in {"table", "selection"}:
            model = self.event_table.model()
            if model is not None:
                index = model.index(row, 0)
                selection = self.event_table.selectionModel()
                self._event_selection_syncing = True
                try:
                    if selection is not None:
                        selection.blockSignals(True)
                    self.event_table.selectRow(row)
                finally:
                    if selection is not None:
                        selection.blockSignals(False)
                    self._event_selection_syncing = False
                self.event_table.scrollTo(index)

        frame_idx_raw = self._frame_index_from_event_row(row)
        frame_idx = frame_idx_raw
        frame_idx_from_time = None
        if frame_idx is None and event_time is not None:
            frame_idx_from_time = self._frame_index_for_time_canonical(event_time)
            frame_idx = frame_idx_from_time

        _log_time_sync(
            "EVENT_FOCUS",
            source=source,
            row=row,
            event_time=event_time,
            frame_from_row=frame_idx_raw,
            frame_from_time=frame_idx_from_time,
            target_frame=frame_idx,
        )

        self.jump_to_time(event_time, from_event=True, source="event")
        self._on_view_state_changed(reason="event focus")

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
        self._on_view_state_changed(reason="event highlight")

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
        progress = self._event_highlight_elapsed_ms / float(self._event_highlight_duration_ms)
        if progress >= 1.0:
            self._event_highlight_timer.stop()
            plot_host.highlight_event(None, visible=False)
            plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha)
            return
        remaining = max(0.0, 1.0 - progress)
        plot_host.set_event_highlight_alpha(self._event_highlight_base_alpha * remaining)

    def _frame_index_from_event_row(self, row: int) -> int | None:
        """
        Return the legacy trace/frame hint from the event table, if present.

        This value comes from imported event tables and is not the canonical
        video frame. Event sync is driven by event time.
        """

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

    def _frame_index_for_time(self, time_value: float) -> int | None:
        return self._frame_index_for_time_canonical(time_value)

    def _nearest_event_index(self, time_value: float) -> int | None:
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
            with contextlib.suppress(Exception):
                marker_contains = marker.contains(event)[0]
            with contextlib.suppress(Exception):
                label_contains = label.contains(event)[0]
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
                    self.canvas.draw_idle()
                    renderer = getattr(self.canvas, "renderer", None)
                bbox = legend.get_window_extent(renderer)
                if bbox.contains(event.x, event.y):
                    self.open_legend_settings_dialog()
                    return True
            except Exception:
                log.debug("Legend click detection failed", exc_info=True)

        trace_targets = []
        if getattr(self, "trace_line", None) is not None:
            trace_targets.append(("inner", self.trace_line))
        if getattr(self, "od_line", None) is not None:
            trace_targets.append(("outer", self.od_line))

        for _name, line in trace_targets:
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
                coords = self._pin_coords(marker)
                if coords is None:
                    continue
                data_x, data_y = coords
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
                        self._safe_remove_artist(marker)
                        self._safe_remove_artist(label)
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
        if event.button == 1 and self.event_times and event.xdata is not None:
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

            # PyQtGraph doesn't support matplotlib-style pinned points yet
            plot_host = getattr(self, "plot_host", None)
            is_pyqtgraph = plot_host is not None and plot_host.get_render_backend() == "pyqtgraph"
            if is_pyqtgraph:
                # TODO: Implement PyQtGraph-compatible pinned points
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

    def _handle_pyqtgraph_click(self, track_id: str, x: float, y: float, button: int, event=None):
        """Handle clicks from PyQtGraph tracks for pin interactions."""
        if self.trace_data is None:
            return
        is_left = button == 1
        is_right = button == 3

        wizard = getattr(self, "_event_review_wizard", None)
        if wizard is not None and wizard.isVisible() and (button == 1 or button == Qt.LeftButton):
            try:
                wizard.handle_trace_click(x)
            except Exception:
                log.debug("Wizard trace click handling failed", exc_info=True)

        # Skip normal click handling when review sampling mode is active —
        # sampling clicks are handled separately by _handle_review_sampling_click
        review_ctrl = getattr(self, "review_controller", None)
        if review_ctrl is not None and review_ctrl.is_active() and review_ctrl.sampling_mode:
            return

        # Focus nearest event if click is close
        if is_left and self.event_times:
            current_window = None
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "current_window"):
                current_window = plot_host.current_window()
            x_low, x_high = (
                current_window
                if current_window
                else (
                    min(self.event_times, default=x),
                    max(self.event_times, default=x),
                )
            )
            tolerance = max((x_high - x_low) * 0.004, 0.05)
            idx = self._nearest_event_index(x)
            if (
                idx is not None
                and idx < len(self.event_times)
                and abs(x - float(self.event_times[idx])) <= tolerance
            ):
                self._focus_event_row(idx, source="plot")
                return

        # Right-click menu
        if is_right:
            # Check if clicking on an existing pin
            idx = self._nearest_pin_index(x, y) if self.pinned_points else None

            if idx is not None:
                # Context menu for existing pin
                marker, label = self.pinned_points[idx]
                coords = self._pin_coords(marker)
                if coords is None:
                    return
                data_x, data_y = coords
                menu = QMenu(self)
                replace_action = menu.addAction("Replace Event Value…")
                delete_action = menu.addAction("Delete Pin")
                undo_action = menu.addAction("Undo Last Replacement")
                add_new_action = menu.addAction("➕ Add as New Event")
                action = menu.exec_(QCursor.pos())
                if action == delete_action:
                    self._safe_remove_artist(marker)
                    self._safe_remove_artist(label)
                    self.pinned_points.pop(idx)
                    self.mark_session_dirty()
                    return
                if action == replace_action:
                    self.handle_event_replacement(data_x, data_y)
                    return
                if action == undo_action:
                    self.undo_last_replacement()
                    return
                if action == add_new_action:
                    tr_type = getattr(marker, "trace_type", "inner")
                    self.prompt_add_event(data_x, data_y, tr_type)
                    return
            else:
                # Context menu for empty trace area (add new pin)
                tr_type = "inner"
                track = getattr(self, "plot_host", None)
                if track is not None and hasattr(track, "track"):
                    spec_track = track.track(track_id)
                    if spec_track and getattr(spec_track.spec, "component", "") == "outer":
                        tr_type = "outer"
                menu = QMenu(self)
                add_pin_action = menu.addAction("📍 Add Pin Here")
                add_event_action = menu.addAction("➕ Add Event Marker Here…")
                action = menu.exec_(QCursor.pos())

                if action == add_pin_action:
                    self._add_pyqtgraph_pin(track_id, x, y, tr_type)
                    self.mark_session_dirty()
                    return
                if action == add_event_action:
                    self.quick_add_event_at_trace_point(x, y, tr_type)
                    return

    def handle_event_replacement(self, x, y):
        if not self.event_labels or not self.event_times:
            log.info("No events available to replace.")
            return

        options = [
            f"{label} at {time:.2f}s"
            for label, time in zip(self.event_labels, self.event_times, strict=False)
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
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
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
                self.event_table_controller.update_row(index, self.event_table_data[index])
                self._mark_row_edited(index)
                self.auto_export_table()
                self.mark_session_dirty()

    def quick_add_event_at_trace_point(self, x: float, y: float, trace_type: str = "inner") -> None:
        """Quick-add an event marker at the clicked trace position."""
        if self.trace_data is None or "Time (s)" not in self.trace_data.columns:
            QMessageBox.warning(self, "No Trace", "Load a trace before adding event markers.")
            return

        try:
            click_time = float(x)
        except (TypeError, ValueError):
            return

        times = self.trace_data["Time (s)"].to_numpy(dtype=float)
        if times.size == 0:
            QMessageBox.warning(self, "No Trace", "Trace timebase is empty.")
            return

        nearest_idx = int(np.argmin(np.abs(times - click_time)))
        event_time = float(times[nearest_idx])

        default_label = f"Event {len(self.event_table_data) + 1}"
        label_text, label_ok = QInputDialog.getText(
            self,
            "Add Event Marker",
            "Event label:",
            text=default_label,
        )
        if not label_ok:
            return

        label_value = str(label_text or "").strip()
        if not label_value:
            return

        def _round_optional(value: float | None) -> float | None:
            if value is None:
                return None
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if not np.isfinite(numeric):
                return None
            return round(numeric, 2)

        id_val, od_val, avg_p_val, set_p_val = self._sample_values_at_time(event_time)
        if str(trace_type).lower() == "outer" and od_val is not None:
            od_val = float(y)
        else:
            id_val = float(y)

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        new_entry = (
            label_value,
            round(event_time, 2),
            _round_optional(id_val),
            _round_optional(od_val),
            _round_optional(avg_p_val),
            _round_optional(set_p_val),
            int(nearest_idx),
        )

        insert_idx = len(self.event_table_data)
        for idx, row in enumerate(self.event_table_data):
            row_time = event_time_for_row(row)
            if row_time is None:
                continue
            with contextlib.suppress(Exception):
                if float(event_time) < float(row_time):
                    insert_idx = idx
                    break

        if not isinstance(self.event_labels, list):
            self.event_labels = []
        if not isinstance(self.event_times, list):
            self.event_times = []
        if not isinstance(self.event_frames, list):
            self.event_frames = []
        if not isinstance(self.event_label_meta, list):
            self.event_label_meta = []

        if insert_idx >= len(self.event_table_data):
            self.event_table_data.append(new_entry)
            self.event_labels.append(label_value)
            self.event_times.append(event_time)
            self.event_frames.append(int(nearest_idx))
            self.event_label_meta.append(self._with_default_review_state(None))
        else:
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_labels.insert(insert_idx, label_value)
            self.event_times.insert(insert_idx, event_time)
            self.event_frames.insert(insert_idx, int(nearest_idx))
            self._insert_event_meta(insert_idx)

        self._ensure_event_meta_length(len(self.event_table_data))
        self.populate_table()
        self.update_plot()
        self.auto_export_table()
        self._focus_event_row(insert_idx, source="manual")
        log.info("Quick-added event marker: %s", new_entry)
        self.mark_session_dirty()

    def prompt_add_event(self, x, y, trace_type="inner"):
        if not self.event_table_data:
            QMessageBox.warning(self, "No Events", "You must load events before adding new ones.")
            return

        # Build label options and insertion points
        insert_labels = [f"{label} at {t:.2f}s" for label, t, *_ in self.event_table_data]
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

        has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        avg_label = self._trace_label_for("p_avg")
        set_label = self._trace_label_for("p2")
        has_avg_p = self.trace_data is not None and avg_label in self.trace_data.columns
        has_set_p = self.trace_data is not None and set_label in self.trace_data.columns

        arr_t = self.trace_data["Time (s)"].values
        idx = int(np.argmin(np.abs(arr_t - x)))
        id_val = self.trace_data["Inner Diameter"].values[idx]
        od_val = self.trace_data["Outer Diameter"].values[idx] if has_od else None
        avg_p_val = self.trace_data[avg_label].values[idx] if has_avg_p else None
        set_p_val = self.trace_data[set_label].values[idx] if has_set_p else None

        if trace_type == "outer" and has_od:
            od_val = y
        else:
            id_val = y

        frame_number = idx  # store nearest trace index as frame hint

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        new_entry = (
            new_label.strip(),
            round(x, 2),
            round(id_val, 2),
            round(od_val, 2) if od_val is not None else None,
            round(avg_p_val, 2) if avg_p_val is not None else None,
            round(set_p_val, 2) if set_p_val is not None else None,
            frame_number,
        )

        # Insert into data
        if insert_idx == len(self.event_table_data):  # Add to end
            self.event_labels.append(new_label.strip())
            self.event_times.append(x)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
            self.event_label_meta.append(self._with_default_review_state(None))
        else:
            self.event_labels.insert(insert_idx, new_label.strip())
            self.event_times.insert(insert_idx, x)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)
            self._insert_event_meta(insert_idx)

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

        t_val, t_ok = QInputDialog.getDouble(self, "Event Time", "Time (s):", 0.0, 0, 1e6, 2)
        if not t_ok:
            return

        id_val, id_ok = QInputDialog.getDouble(self, "Inner Diameter", "ID (µm):", 0.0, 0, 1e6, 2)
        if not id_ok:
            return

        insert_idx = insert_labels.index(selected)
        arr_t = self.trace_data["Time (s)"].values
        frame_number = int(np.argmin(np.abs(arr_t - t_val)))
        od_val = None
        if has_od:
            od_val, ok = QInputDialog.getDouble(self, "Outer Diameter", "OD (µm):", 0.0, 0, 1e6, 2)
            if not ok:
                return

        # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
        # Pressure values set to None for manually entered events
        new_entry = (
            label.strip(),
            round(t_val, 2),
            round(id_val, 2),
            round(od_val, 2) if od_val is not None else None,
            None,  # avg_p - not available for manual entry
            None,  # set_p - not available for manual entry
            frame_number,
        )

        if insert_idx == len(self.event_table_data):
            self.event_labels.append(label.strip())
            self.event_times.append(t_val)
            self.event_table_data.append(new_entry)
            self.event_frames.append(frame_number)
            self.event_label_meta.append(self._with_default_review_state(None))
        else:
            self.event_labels.insert(insert_idx, label.strip())
            self.event_times.insert(insert_idx, t_val)
            self.event_table_data.insert(insert_idx, new_entry)
            self.event_frames.insert(insert_idx, frame_number)
            self._insert_event_meta(insert_idx)

        self.populate_table()
        self.update_plot()
        self.auto_export_table()
        log.info("Manually inserted event: %s", new_entry)
        self.mark_session_dirty()

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
    def update_hover_label(self, event):
        valid_axes = [ax for ax in (self.ax, self.ax2) if ax is not None]
        if event.inaxes not in valid_axes or self.trace_data is None or event.xdata is None:
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

    def _current_time_window(self) -> tuple[float, float] | None:
        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None and hasattr(plot_host, "current_window"):
            with contextlib.suppress(Exception):
                window = plot_host.current_window()
                if window is not None:
                    return float(window[0]), float(window[1])
        if self.ax is not None:
            with contextlib.suppress(Exception):
                xlim = self.ax.get_xlim()
                return float(xlim[0]), float(xlim[1])
        return None

    def _update_last_x_window_width(self, x0: float, x1: float) -> None:
        if getattr(self, "_scrolling_from_scrollbar", False):
            return
        try:
            width = float(x1) - float(x0)
        except (TypeError, ValueError):
            return
        if width <= 0:
            return
        self._last_x_window_width_s = width

    def _set_xrange_source(self, source: str, expected: tuple[float, float] | None = None) -> None:
        self._xrange_source = str(source or "")
        self._xrange_expected = expected

    def update_scroll_slider(self):
        if self.scroll_slider is None:
            return
        if getattr(self, "trace_nav_bar", None) is not None and self._plot_host_is_pyqtgraph():
            self.scroll_slider.hide()
            return
        if getattr(self, "_scrolling_from_scrollbar", False):
            return
        has_trace = (
            self.trace_data is not None and getattr(self.trace_data, "empty", False) is False
        )
        if not has_trace:
            self.scroll_slider.hide()
            return

        full_range = self._trace_full_range()
        window = self._current_time_window()
        if full_range is None or window is None:
            self.scroll_slider.hide()
            return
        full_t_min, full_t_max = full_range
        win_start, win_end = window
        self.window_width = win_end - win_start
        value, page_step = compute_scrollbar_state(
            full_t_min,
            full_t_max,
            win_start,
            win_end,
            scale=TIME_SCROLLBAR_SCALE,
        )

        if os.getenv("VASO_DEBUG_SCROLLBAR") == "1":
            log.debug(
                "[SCROLLBAR SYNC] window=(%s, %s) value=%s page_step=%s",
                win_start,
                win_end,
                value,
                page_step,
            )
        self._updating_time_scrollbar = True
        blocker = QSignalBlocker(self.scroll_slider)
        try:
            self.scroll_slider.setRange(0, TIME_SCROLLBAR_SCALE)
            self.scroll_slider.setPageStep(page_step)
            self.scroll_slider.setSingleStep(max(1, page_step // 10))
            self.scroll_slider.setValue(value)
        finally:
            self._updating_time_scrollbar = False
            del blocker

        self.scroll_slider.setEnabled(full_t_max > full_t_min)
        self.scroll_slider.show()

    def _on_scrollbar_pressed(self) -> None:
        self._scrolling_from_scrollbar = True
        window = self._current_time_window()
        width = None
        if window is not None:
            width = float(window[1]) - float(window[0])
        if width is None or width <= 0:
            full = self._trace_full_range()
            if full is not None:
                width = float(full[1]) - float(full[0])
        if width is not None and width > 0:
            self._scrollbar_drag_width_s = width
            log.debug("[SCROLLBAR DRAG] drag_width_s=%.6f source=sliderPressed", width)

    def _on_scrollbar_released(self) -> None:
        self._scrolling_from_scrollbar = False
        if self.scroll_slider is None:
            return
        self.scroll_plot_user(self.scroll_slider.value(), source="sliderReleased")
        self._scrollbar_drag_width_s = None

    def _on_scrollbar_value_changed(self, value: int) -> None:
        if getattr(self, "_updating_time_scrollbar", False):
            return
        if getattr(self, "_scrolling_from_scrollbar", False):
            return
        self.scroll_plot_user(value, source="valueChanged")

    def _on_scrollbar_moved(self, value: int) -> None:
        self.scroll_plot_user(value, source="sliderMoved")

    def open_subplot_layout_dialog(self, fig=None):
        """Open dialog to adjust subplot paddings and spacing.

        Args:
            fig: Figure object or boolean from Qt signal (ignored if boolean)
        """
        # Ignore boolean argument from Qt signals
        if isinstance(fig, bool):
            fig = None

        # Redirect to unified dialog, open Layout tab
        self.open_unified_plot_settings_dialog(tab_name="layout")

    def open_axis_settings_dialog(self):
        """Open axis settings dialog for the main plot."""
        # Redirect to unified dialog, open Axis tab
        self.open_unified_plot_settings_dialog(tab_name="axis")

    def open_axis_settings_dialog_for(self, ax, canvas, ax2=None):
        """Open axis settings dialog - redirects to unified dialog."""
        # Redirect to unified dialog, open Axis tab
        self.open_unified_plot_settings_dialog(tab_name="axis")

    def _show_change_log_dialog(self) -> None:
        from vasoanalyzer.ui.dialogs.change_log_dialog import ChangeLogDialog

        sample_name = ""
        if hasattr(self, "current_sample") and self.current_sample is not None:
            sample_name = getattr(self.current_sample, "name", "")
        dialog = ChangeLogDialog(
            self._change_log.entries,
            sample_name=sample_name,
            parent=self,
        )
        dialog.exec_()

    def _export_scinote_report(self) -> None:
        import matplotlib.pyplot as plt

        from vasoanalyzer.export.report_figure import render_report_figure
        from vasoanalyzer.ui.dialogs.report_export_dialog import ReportExportDialog

        if self.trace_model is None:
            QMessageBox.warning(self, "Export Error", "No trace data loaded.")
            return

        # Detect what data is available
        has_snapshot = bool(getattr(self, "snapshot_frames", None))
        has_events = bool(getattr(self, "event_table_data", None))

        # Show settings dialog
        dlg = ReportExportDialog(
            self,
            has_snapshot=has_snapshot,
            has_events=has_events,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        settings = dlg.get_settings()
        if settings is None:
            return

        # ---- Gather data ----

        # View range
        plot_host = getattr(self, "plot_host", None)
        xlim = self.trace_model.full_range
        if plot_host is not None and hasattr(plot_host, "current_window"):
            window = plot_host.current_window()
            if window:
                xlim = window

        # Visible traces — query with the channel_kind keys used by set_channel_visible
        _channel_keys = ["inner", "outer", "avg_pressure", "set_pressure"]
        visible_traces = None
        if plot_host is not None:
            visible_traces = [
                key for key in _channel_keys
                if plot_host.is_channel_visible(key)
            ]
            if not visible_traces:
                visible_traces = None  # fall back to auto-detect
            log.info("Report export visible_traces=%s", visible_traces)

        # Event data
        event_times = []
        event_labels_list = []
        events_df = None
        if settings["include_table"] and self.event_table_data:
            for row in self.event_table_data:
                if len(row) >= 2:
                    event_labels_list.append(str(row[0]) if row[0] else "")
                    try:
                        event_times.append(float(row[1]))
                    except (ValueError, TypeError):
                        event_times.append(0.0)
            controller = getattr(self, "event_table_controller", None)
            if controller is not None:
                events_df = controller.to_dataframe()
        elif self.event_table_data:
            # Still show event markers even if table panel is off
            for row in self.event_table_data:
                if len(row) >= 2:
                    event_labels_list.append(str(row[0]) if row[0] else "")
                    try:
                        event_times.append(float(row[1]))
                    except (ValueError, TypeError):
                        event_times.append(0.0)

        # Snapshot frame
        snapshot_image = None
        if settings["include_frame"] and has_snapshot:
            frames = self.snapshot_frames
            frame_idx = getattr(self, "current_frame", 0)
            # Use current frame, or middle frame as fallback
            if 0 <= frame_idx < len(frames):
                snapshot_image = frames[frame_idx]
            elif frames:
                snapshot_image = frames[len(frames) // 2]

        # Metadata
        sample_name = ""
        experiment_name = ""
        if self.current_sample is not None:
            sample_name = getattr(self.current_sample, "name", "")
        if hasattr(self, "current_experiment") and self.current_experiment is not None:
            experiment_name = getattr(self.current_experiment, "name", "")

        metadata = {
            "sample_name": sample_name,
            "experiment": experiment_name,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        # ---- Render ----
        figsize = (settings["width"], settings["height"])
        dpi = settings["dpi"]
        try:
            fig = render_report_figure(
                trace_model=self.trace_model,
                xlim=xlim,
                visible_traces=visible_traces,
                events_df=events_df if settings["include_table"] else None,
                event_times=event_times or None,
                event_labels=event_labels_list or None,
                snapshot_image=snapshot_image,
                metadata=metadata,
                figsize=figsize,
                dpi=dpi,
                include_frame=settings["include_frame"],
                include_table=settings["include_table"],
            )
        except Exception as exc:
            log.exception("Failed to render experiment report")
            QMessageBox.critical(
                self, "Export Error", f"Failed to render report:\n{exc}"
            )
            return

        # ---- Save ----
        fmt = settings["format"]
        ext_map = {"png": "png", "tiff": "tiff", "pdf": "pdf"}
        ext = ext_map.get(fmt, "png")
        filter_map = {
            "png": "PNG Image (*.png)",
            "tiff": "TIFF Image (*.tiff *.tif)",
            "pdf": "PDF Document (*.pdf)",
        }
        default_name = f"{sample_name or 'report'}_report.{ext}"
        base_dir = os.path.dirname(self.trace_file_path) if self.trace_file_path else ""
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Experiment Report",
            os.path.join(base_dir, default_name),
            filter_map.get(fmt, f"*.{ext}"),
        )
        if not save_path:
            plt.close(fig)
            return

        try:
            fig.savefig(save_path, dpi=dpi, bbox_inches="tight", facecolor="white")
            self.statusBar().showMessage(f"Report saved: {save_path}", 5000)
        except Exception as exc:
            log.exception("Failed to save experiment report")
            QMessageBox.critical(
                self, "Save Error", f"Failed to save report:\n{exc}"
            )
        finally:
            plt.close(fig)

    def open_plot_settings_dialog(self, tab_name=None):
        """Open plot settings dialog - automatically routes to correct backend dialog.

        Args:
            tab_name: Name of tab to open (if supported by the backend dialog)
        """
        if self._plot_host_is_pyqtgraph():
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None and hasattr(plot_host, "debug_dump_state"):
                plot_host.debug_dump_state("open_plot_settings_dialog (before)")
            # Use PyQtGraph-specific settings dialog
            self.open_pyqtgraph_settings_dialog()
        else:
            # Use matplotlib-based unified dialog
            self.open_unified_plot_settings_dialog(tab_name=tab_name)

    def open_unified_plot_settings_dialog(self, tab_name=None):
        """Open combined dialog for layout, axis and style.

        Args:
            tab_name: Name of tab to open, or boolean from Qt signal (ignored if boolean)
        """
        # Ignore boolean argument from Qt signals
        if isinstance(tab_name, bool):
            tab_name = None

        dialog = UnifiedPlotSettingsDialog(
            self,
            self.ax,
            self.canvas,
            self.ax2,
            self.event_text_objects,
            self.pinned_points,
        )
        if hasattr(dialog, "set_event_update_callback"):
            dialog.set_event_update_callback(self.apply_event_label_overrides)
        if tab_name:
            mapping = {
                "frame": 0,
                "layout": 1,
                "axis": 2,
                "style": 3,
                "event_labels": 4,
            }
            idx = mapping.get(str(tab_name).lower(), 0)
            with contextlib.suppress(Exception):
                dialog.tabs.setCurrentIndex(idx)
        dialog.exec_()

    def open_pyqtgraph_settings_dialog(self):
        """Open PyQtGraph plot settings dialog.

        This dialog provides settings for PyQtGraph renderer without depending on
        matplotlib Figure objects. It focuses on commonly used settings like:
        - Track/channel appearance (colors, line width, y-axis)
        - Event labels (mode, clustering, font)
        - General plot settings (grid, background)
        """
        from vasoanalyzer.ui.dialogs.pyqtgraph_settings_dialog import (
            PyQtGraphSettingsDialog,
        )

        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            QMessageBox.warning(self, "No Plot Available", "No PyQtGraph plot is currently loaded.")
            return

        dialog = PyQtGraphSettingsDialog(self, plot_host)
        dialog.resize(200, 1000)
        dialog.exec_()

    def _update_gif_animator_state(self) -> None:
        """Enable GIF Animator menu action when sample has required data."""
        if not self.current_sample:
            self.action_gif_animator.setEnabled(False)
            if hasattr(self, "sync_clip_action") and self.sync_clip_action is not None:
                self.sync_clip_action.setEnabled(False)
            prev_enabled = getattr(self, "_sync_clip_enabled", None)
            if prev_enabled is None or prev_enabled:
                log.info(
                    "Export Clip enabled=%s (trace=%s, tiff=%s, events=%s)",
                    False,
                    False,
                    False,
                    False,
                )
            self._sync_clip_enabled = False
            return

        sample = self.current_sample

        # Check for required data
        has_trace = sample.trace_data is not None or sample.dataset_id is not None
        has_snapshots = isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
        has_events = sample.events_data is not None and len(sample.events_data) >= 2

        # Enable only if all requirements are met
        should_enable = has_trace and has_snapshots and has_events
        self.action_gif_animator.setEnabled(should_enable)
        if hasattr(self, "sync_clip_action") and self.sync_clip_action is not None:
            self.sync_clip_action.setEnabled(should_enable)
        prev_enabled = getattr(self, "_sync_clip_enabled", None)
        if prev_enabled is None or prev_enabled != should_enable:
            log.info(
                "Export Clip enabled=%s (trace=%s, tiff=%s, events=%s)",
                should_enable,
                has_trace,
                has_snapshots,
                has_events,
            )
        self._sync_clip_enabled = should_enable

    def show_gif_animator(self, checked: bool = False) -> None:
        """Launch GIF Animator window."""
        self.open_sync_clip_exporter(checked)

    def open_sync_clip_exporter(self, checked: bool = False) -> None:
        """Launch GIF Animator window.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        log.info(
            "UI: Export Clip clicked (enabled=%s)",
            (
                getattr(self, "sync_clip_action", None).isEnabled()
                if isinstance(getattr(self, "sync_clip_action", None), QAction)
                else None
            ),
        )

        def _ensure_window_on_screen(window: QWidget) -> None:
            try:
                frame = window.frameGeometry()
            except Exception:
                return
            screens = QApplication.screens()
            if not screens:
                return
            if any(frame.intersects(screen.availableGeometry()) for screen in screens):
                return
            parent_geom = self.geometry()
            frame.moveCenter(parent_geom.center())
            window.move(frame.topLeft())

        if not self.current_sample:
            QMessageBox.information(
                self,
                "Export Clip",
                "Load a trace and TIFF to export a synchronized clip.",
            )
            return

        # Validate requirements
        has_snapshots = (
            isinstance(self.current_sample.snapshots, np.ndarray)
            and self.current_sample.snapshots.size > 0
        )
        has_events = (
            self.current_sample.events_data is not None
            and len(self.current_sample.events_data) >= 2
        )

        if not has_snapshots or not has_events:
            QMessageBox.information(
                self,
                "Export Clip",
                "Load a trace and TIFF and define at least two events to export a synchronized clip.",
            )
            log.info(
                "Export Clip blocked (snapshots=%s, events=%s)",
                has_snapshots,
                has_events,
            )
            return

        # Get trace model (use existing or build)
        if self.trace_model is None:
            try:
                trace_model = self._get_trace_model_for_sample(self.current_sample)
            except Exception:
                trace_model = None
        else:
            trace_model = self.trace_model

        if trace_model is None:
            QMessageBox.information(
                self,
                "Export Clip",
                "Load a trace and TIFF to export a synchronized clip.",
            )
            log.info("Export Clip blocked (trace_model missing)")
            return

        try:
            existing = getattr(self, "_sync_clip_window", None)
            if existing is not None:
                if (
                    getattr(existing, "sample", None) is not self.current_sample
                    or getattr(existing, "trace_model", None) is not trace_model
                ):
                    with contextlib.suppress(Exception):
                        existing.close()
                    self._sync_clip_window = None

            if getattr(self, "_sync_clip_window", None) is None:
                from vasoanalyzer.ui.gif_animator import GifAnimatorWindow

                self._sync_clip_window = GifAnimatorWindow(
                    parent=self,
                    project_ctx=self.project_ctx,
                    sample=self.current_sample,
                    trace_model=trace_model,
                    events_df=self.current_sample.events_data,
                )
                self._sync_clip_window.destroyed.connect(
                    lambda *_: setattr(self, "_sync_clip_window", None)
                )

                from vasoanalyzer.ui.theme import get_theme_manager

                theme_manager = get_theme_manager()
                with contextlib.suppress(Exception):
                    theme_manager.themeChanged.connect(self._sync_clip_window.apply_theme)
                with contextlib.suppress(Exception):
                    self._sync_clip_window.apply_theme(getattr(self, "_active_theme_mode", "light"))

            window = self._sync_clip_window
            window.setWindowFlag(Qt.Window, True)
            window.show()
            if window.isMinimized():
                window.showNormal()
            _ensure_window_on_screen(window)
            window.raise_()
            window.activateWindow()

            n_frames = len(self.current_sample.snapshots) if has_snapshots else 0
            log.info(
                "Export Clip: context set (trace=%s, tiff=%s, frames=%s)",
                trace_model is not None,
                has_snapshots,
                n_frames,
            )
        except Exception:
            log.exception("Export Clip failed to open")
            QMessageBox.information(
                self,
                "Export Clip",
                "Unable to open the exporter window. Check logs for details.",
            )
            return

        log.info("GIF Animator launched")

    def _toggle_trace_range_selection(self, checked: bool) -> None:
        plot_host = getattr(self, "plot_host", None)
        if (
            plot_host is None
            or not hasattr(plot_host, "get_render_backend")
            or plot_host.get_render_backend() != "pyqtgraph"
        ):
            QMessageBox.information(
                self,
                "Range Selection",
                "Range selection is available only when using the PyQtGraph backend.",
            )
            if hasattr(self, "action_select_range") and self.action_select_range is not None:
                with contextlib.suppress(Exception):
                    self.action_select_range.blockSignals(True)
                    self.action_select_range.setChecked(False)
                    self.action_select_range.blockSignals(False)
            return
        setter = getattr(plot_host, "set_range_selection_visible", None)
        if callable(setter):
            setter(bool(checked))

    def _get_selected_range_from_plot_host(self) -> tuple[float, float] | None:
        plot_host = getattr(self, "plot_host", None)
        if (
            plot_host is None
            or not hasattr(plot_host, "get_render_backend")
            or plot_host.get_render_backend() != "pyqtgraph"
        ):
            return None
        if hasattr(plot_host, "selected_range"):
            rng = plot_host.selected_range()
            if rng is not None:
                return rng
        if hasattr(plot_host, "current_window"):
            return plot_host.current_window()
        return None

    def _slice_trace_model_for_range(
        self, x_range: tuple[float, float], visible_channels: dict[str, bool]
    ) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[str, np.ndarray]] | None:
        if self.trace_model is None:
            return None
        time = getattr(self.trace_model, "time_full", None)
        if time is None:
            return None
        time = np.asarray(time)
        x0, x1 = x_range
        mask = (time >= x0) & (time <= x1)
        if not mask.any():
            return None
        time_slice = time[mask]
        series_map: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        data_columns: dict[str, np.ndarray] = {"time": time_slice}
        for key in ["inner", "outer", "avg_pressure", "set_pressure"]:
            arr = getattr(self.trace_model, f"{key}_full", None)
            if arr is None or not visible_channels.get(key, True):
                continue
            y = np.asarray(arr)[mask]
            series_map[key] = (time_slice, y)
            data_columns[key] = y
        if not series_map:
            return None
        return series_map, data_columns

    def _visible_channels_from_toggles(self) -> dict[str, bool]:
        visible_channels = {
            "inner": bool(getattr(self, "id_toggle_act", None) and self.id_toggle_act.isChecked()),
            "outer": bool(getattr(self, "od_toggle_act", None) and self.od_toggle_act.isChecked()),
            "avg_pressure": bool(
                getattr(self, "avg_pressure_toggle_act", None)
                and self.avg_pressure_toggle_act.isChecked()
            ),
            "set_pressure": bool(
                getattr(self, "set_pressure_toggle_act", None)
                and self.set_pressure_toggle_act.isChecked()
            ),
        }
        if not any(visible_channels.values()):
            visible_channels["inner"] = True
        return visible_channels

    def _build_selected_range_table(
        self, *, use_visible_channels: bool = True
    ) -> tuple[list[str], list[list[float]]] | None:
        x_range = self._get_selected_range_from_plot_host()
        if x_range is None and hasattr(self, "plot_host") and self.plot_host is not None:
            if hasattr(self.plot_host, "current_window"):
                x_range = self.plot_host.current_window()
        if x_range is None:
            return None
        channels = (
            self._visible_channels_from_toggles()
            if use_visible_channels
            else {
                "inner": True,
                "outer": True,
                "avg_pressure": True,
                "set_pressure": True,
            }
        )
        sliced = self._slice_trace_model_for_range(x_range, channels)
        if sliced is None:
            return None
        _, data_columns = sliced
        headers = list(data_columns.keys())
        rows: list[list[float]] = []
        length = len(next(iter(data_columns.values())))
        for idx in range(length):
            row = [float(data_columns[h][idx]) for h in headers]
            rows.append(row)
        return headers, rows

    def _copy_selected_range_data(self) -> None:
        payload = self._build_selected_range_table()
        if payload is None:
            QMessageBox.information(
                self,
                "Copy Selected Range",
                "No selection available to copy. Use 'Select Range on Trace' first.",
            )
            return
        headers, rows = payload
        lines = ["\t".join(headers)]
        for row in rows:
            lines.append("\t".join(f"{val:.6g}" for val in row))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)

    def _export_selected_range_data(self) -> None:
        payload = self._build_selected_range_table()
        if payload is None:
            QMessageBox.information(
                self,
                "Export Selected Range",
                "No selection available to export. Use 'Select Range on Trace' first.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Selected Range",
            "selected_range.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        headers, rows = payload
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
        except Exception:
            log.exception("Failed to export selected range data")

    # [J] ========================= PLOT STYLE EDITOR ================================
    def apply_plot_style(self, style, persist: bool = False, draw: bool = True):
        manager = self._ensure_style_manager()
        effective_style = manager.update(style or {})
        x_axis = self._x_axis_for_style()

        # Don't pass v3 event text objects to StyleManager - v3 handles its own styling
        plot_host = getattr(self, "plot_host", None)
        v3_enabled = False
        if plot_host is not None:
            with contextlib.suppress(Exception):
                v3_enabled = effective_style.get("event_labels_v3_enabled", False)
        event_texts = [] if v3_enabled else self.event_text_objects

        manager.apply(
            ax=self.ax,
            ax_secondary=self.ax2,
            x_axis=x_axis,
            event_text_objects=event_texts,
            pinned_points=self.pinned_points,
            main_line=self.ax.lines[0] if self.ax.lines else None,
            od_line=self.od_line,
        )

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            defaults = DEFAULT_STYLE
            try:
                # Batch all setter calls to avoid cascading redraws
                plot_host.suspend_updates()
                # Always use v3 - force upgrade from old saved settings
                plot_host.set_event_labels_v3_enabled(True)
                plot_host.set_event_label_mode(
                    effective_style.get(
                        "event_label_mode",
                        defaults.get("event_label_mode", "vertical"),
                    )
                )
                plot_host.set_max_labels_per_cluster(
                    effective_style.get(
                        "event_label_max_per_cluster",
                        defaults.get("event_label_max_per_cluster", 1),
                    )
                )
                plot_host.set_cluster_style_policy(
                    effective_style.get(
                        "event_label_style_policy",
                        defaults.get("event_label_style_policy", "first"),
                    )
                )
                plot_host.set_label_lanes(
                    effective_style.get(
                        "event_label_lanes",
                        defaults.get("event_label_lanes", 3),
                    )
                )
                plot_host.set_belt_baseline(
                    effective_style.get(
                        "event_label_belt_baseline",
                        defaults.get("event_label_belt_baseline", True),
                    )
                )
                plot_host.set_event_label_span_siblings(
                    effective_style.get(
                        "event_label_span_siblings",
                        defaults.get("event_label_span_siblings", True),
                    )
                )
                plot_host.set_auto_event_label_mode(
                    effective_style.get(
                        "event_label_auto_mode",
                        defaults.get("event_label_auto_mode", True),
                    )
                )
                plot_host.set_label_density_thresholds(
                    compact=effective_style.get(
                        "event_label_density_compact",
                        defaults.get("event_label_density_compact", 0.8),
                    ),
                    belt=effective_style.get(
                        "event_label_density_belt",
                        defaults.get("event_label_density_belt", 0.25),
                    ),
                )
                plot_host.set_label_outline_enabled(
                    effective_style.get(
                        "event_label_outline_enabled",
                        defaults.get("event_label_outline_enabled", True),
                    )
                )
                plot_host.set_label_outline(
                    effective_style.get(
                        "event_label_outline_width",
                        defaults.get("event_label_outline_width", 2.0),
                    ),
                    effective_style.get(
                        "event_label_outline_color",
                        defaults.get("event_label_outline_color", (1.0, 1.0, 1.0, 0.9)),
                    ),
                )
                plot_host.set_label_tooltips_enabled(
                    effective_style.get(
                        "event_label_tooltips_enabled",
                        defaults.get("event_label_tooltips_enabled", True),
                    )
                )
                plot_host.set_tooltip_proximity(
                    effective_style.get(
                        "event_label_tooltip_proximity",
                        defaults.get("event_label_tooltip_proximity", 10),
                    )
                )
                plot_host.set_compact_legend_enabled(
                    effective_style.get(
                        "event_label_legend_enabled",
                        defaults.get("event_label_legend_enabled", True),
                    )
                )
                plot_host.set_compact_legend_location(
                    effective_style.get(
                        "event_label_legend_loc",
                        defaults.get("event_label_legend_loc", "upper right"),
                    )
                )
                if hasattr(plot_host, "set_axis_font"):
                    plot_host.set_axis_font(
                        family=effective_style.get(
                            "axis_font_family",
                            defaults.get("axis_font_family", "Arial"),
                        ),
                        size=effective_style.get(
                            "axis_font_size",
                            defaults.get("axis_font_size", 12),
                        ),
                    )
                    plot_host.set_tick_font_size(
                        effective_style.get(
                            "tick_font_size",
                            defaults.get("tick_font_size", 12),
                        )
                    )
                    plot_host.set_default_line_width(
                        effective_style.get(
                            "line_width",
                            defaults.get("line_width", 2.0),
                        )
                    )
                plot_host.set_event_base_style(
                    font_family=effective_style.get(
                        "event_font_family",
                        defaults.get("event_font_family", "Arial"),
                    ),
                    font_size=effective_style.get(
                        "event_font_size",
                        defaults.get("event_font_size", 15),
                    ),
                    bold=effective_style.get(
                        "event_bold",
                        defaults.get("event_bold", False),
                    ),
                    italic=effective_style.get(
                        "event_italic",
                        defaults.get("event_italic", False),
                    ),
                    color=effective_style.get(
                        "event_color",
                        defaults.get("event_color", "#000000"),
                    ),
                )
            except Exception:
                log.exception("Failed to apply event label style to PlotHost")
            finally:
                # Always resume updates, even if there was an error
                plot_host.resume_updates()

        if draw:
            self.canvas.draw_idle()
        if hasattr(self, "plot_style_dialog") and self.plot_style_dialog:
            with contextlib.suppress(AttributeError):
                self.plot_style_dialog.set_style(effective_style)

        if self._style_holder is None:
            self._style_holder = _StyleHolder(effective_style.copy())
        else:
            self._style_holder.set_style(effective_style.copy())

        if persist and self.current_sample:
            if not isinstance(self.current_sample.ui_state, dict):
                self.current_sample.ui_state = {}
            self.current_sample.ui_state["style_settings"] = effective_style
            self.mark_session_dirty()
            self.request_deferred_autosave(delay_ms=2000, reason="style")

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
        # Use cache only when called with default parameters (most common case)
        use_cache = all(p is None for p in [ax, ax2, event_text_objects, pinned_points, od_line])
        if use_cache and not self._snapshot_style_dirty and self._cached_snapshot_style is not None:
            return self._cached_snapshot_style.copy()

        ax = ax or self.ax
        ax2 = self.ax2 if ax2 is None else ax2
        event_text_objects = (
            self.event_text_objects if event_text_objects is None else event_text_objects
        )
        pinned_points = self.pinned_points if pinned_points is None else pinned_points
        od_line = od_line if od_line is not None else getattr(self, "od_line", None)

        style = DEFAULT_STYLE.copy()
        if ax is None:
            return style
        x_axis = self._x_axis_for_style() or ax

        # Detect PyQtGraph backend - return default style since PyQtGraph styling
        # is handled differently and doesn't use matplotlib artist properties
        is_pyqtgraph = not hasattr(x_axis, "xaxis")
        if is_pyqtgraph:
            return style

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
            else (y_tick_labels[0].get_fontsize() if y_tick_labels else style["tick_font_size"])
        )
        style["tick_font_size"] = tick_font_size

        x_tick_color = x_tick_labels[0].get_color() if x_tick_labels else style["x_tick_color"]
        y_tick_color = y_tick_labels[0].get_color() if y_tick_labels else style["y_tick_color"]
        style["tick_color"] = x_tick_color
        style["x_tick_color"] = x_tick_color
        style["y_tick_color"] = y_tick_color

        try:
            major_ticks = x_axis.xaxis.get_major_ticks()
            if major_ticks:
                style["tick_length"] = float(major_ticks[0].tick1line.get_markersize())
                style["tick_width"] = float(major_ticks[0].tick1line.get_linewidth())
        except Exception:
            log.debug("Failed to extract tick style from axes", exc_info=True)

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

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            style["event_labels_v3_enabled"] = plot_host.event_labels_v3_enabled()
            style["event_label_max_per_cluster"] = plot_host.max_labels_per_cluster()
            style["event_label_style_policy"] = plot_host.cluster_style_policy()
            style["event_label_lanes"] = plot_host.event_label_lanes()
            style["event_label_belt_baseline"] = plot_host.belt_baseline_enabled()
            style["event_label_span_siblings"] = plot_host.span_event_lines_across_siblings()
            style["event_label_auto_mode"] = plot_host.auto_event_label_mode()
            compact_thr, belt_thr = plot_host.label_density_thresholds()
            style["event_label_density_compact"] = compact_thr
            style["event_label_density_belt"] = belt_thr
            outline_enabled, outline_width, outline_color = plot_host.label_outline_settings()
            style["event_label_outline_enabled"] = outline_enabled
            style["event_label_outline_width"] = outline_width
            style["event_label_outline_color"] = outline_color or DEFAULT_STYLE.get(
                "event_label_outline_color", "#FFFFFFFF"
            )
            style["event_label_tooltips_enabled"] = plot_host.label_tooltips_enabled()
            style["event_label_tooltip_proximity"] = plot_host.tooltip_proximity()
            style["event_label_legend_enabled"] = plot_host.compact_legend_enabled()
            style["event_label_legend_loc"] = plot_host.compact_legend_location()
        else:
            style.setdefault(
                "event_labels_v3_enabled",
                DEFAULT_STYLE.get("event_labels_v3_enabled", True),
            )
            style.setdefault(
                "event_label_max_per_cluster",
                DEFAULT_STYLE.get("event_label_max_per_cluster", 1),
            )
            style.setdefault(
                "event_label_style_policy",
                DEFAULT_STYLE.get("event_label_style_policy", "first"),
            )
            style.setdefault(
                "event_label_lanes",
                DEFAULT_STYLE.get("event_label_lanes", 3),
            )
            style.setdefault(
                "event_label_belt_baseline",
                DEFAULT_STYLE.get("event_label_belt_baseline", True),
            )
            style.setdefault(
                "event_label_span_siblings",
                DEFAULT_STYLE.get("event_label_span_siblings", True),
            )
            style.setdefault(
                "event_label_auto_mode",
                DEFAULT_STYLE.get("event_label_auto_mode", False),
            )
            style.setdefault(
                "event_label_density_compact",
                DEFAULT_STYLE.get("event_label_density_compact", 0.8),
            )
            style.setdefault(
                "event_label_density_belt",
                DEFAULT_STYLE.get("event_label_density_belt", 0.25),
            )
            style.setdefault(
                "event_label_outline_enabled",
                DEFAULT_STYLE.get("event_label_outline_enabled", False),
            )
            style.setdefault(
                "event_label_outline_width",
                DEFAULT_STYLE.get("event_label_outline_width", 0.0),
            )
            style.setdefault(
                "event_label_outline_color",
                DEFAULT_STYLE.get("event_label_outline_color", "#FFFFFFFF"),
            )

        # Cache the result if using default parameters
        if use_cache:
            self._cached_snapshot_style = style.copy()
            self._snapshot_style_dirty = False

        return style

    def open_customize_dialog(self):
        # Check visibility of any existing grid line
        is_grid_visible = any(line.get_visible() for line in self.ax.get_xgridlines())
        self.ax.grid(not is_grid_visible)
        self.toolbar.edit_parameters()
        self.canvas.draw_idle()

    def start_new_analysis(self, checked: bool = False):
        """Start a new analysis session.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        confirm = QMessageBox.question(
            self,
            "Start New Analysis",
            "Clear current session and start fresh?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.clear_current_session()

    def clear_current_session(self, checked: bool = False):
        """Clear the current analysis session.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self.trace_data = None
        self.trace_file_path = None
        self.trace_time = None
        self.trace_time_exact = None
        self.frame_numbers = None
        self.frame_number_to_trace_idx = {}
        self.frame_trace_time = None
        self.frame_trace_index = None
        self.snapshot_frames = []
        self.frames_metadata = []
        self.frame_times = []
        self.frame_trace_indices = []
        self.snapshot_frame_indices = []
        self.snapshot_frame_stride = 1
        self.snapshot_total_frames = None
        self.snapshot_loading_info = None
        self.current_frame = 0
        self.current_page = 0
        self.page_float = 0.0
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
        self.canvas.draw_idle()
        self.event_table_controller.clear()
        self._set_playback_state(False)
        if self.snapshot_widget is not None:
            self.snapshot_widget.clear()
        self.sampling_rate_hz = None
        self._set_status_source("No trace loaded", "")
        self._reset_session_dirty()
        self.toggle_snapshot_viewer(False, source="data")
        if hasattr(self, "rotate_ccw_btn"):
            self.rotate_ccw_btn.setEnabled(False)
        if hasattr(self, "rotate_cw_btn"):
            self.rotate_cw_btn.setEnabled(False)
        if hasattr(self, "rotate_reset_btn"):
            self.rotate_reset_btn.setEnabled(False)
        self._reset_snapshot_speed()
        self.reset_snapshot_rotation()
        label = getattr(self, "snapshot_time_label", None)
        if label is not None:
            label.setText("Frame 0 / 0")
        if self.snapshot_widget is not None:
            self.snapshot_widget.hide()
        self._reset_snapshot_loading_info()
        self.set_snapshot_metadata_visible(False)
        self.metadata_details_label.setText("No metadata available.")
        self._update_metadata_button_state()
        self._update_excel_controls()
        log.info("Cleared session.")
        self.scroll_slider.setValue(0)
        self.scroll_slider.hide()
        self.show_analysis_workspace()
        self.legend_settings = _copy_legend_settings(DEFAULT_LEGEND_SETTINGS)
        if getattr(self, "plot_legend", None):
            with contextlib.suppress(Exception):
                self.plot_legend.remove()
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
        self.event_label_meta = []
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
        self._refresh_trace_navigation_data()
        if self.zoom_dock:
            self.zoom_dock.set_trace_model(None)
        if self.scope_dock:
            self.scope_dock.set_trace_model(None)
        self.canvas.draw_idle()
        if hasattr(self, "event_table_controller"):
            self.event_table_controller.clear()
        if hasattr(self, "load_events_action") and self.load_events_action is not None:
            self.load_events_action.setEnabled(False)
        if hasattr(self, "action_import_events") and self.action_import_events is not None:
            self.action_import_events.setEnabled(False)
        self._event_lines_visible = True
        self._event_label_mode = "indices"
        self._sync_event_controls()
        self._apply_toggle_state(True, False, outer_supported=False)
        self._update_trace_controls_state()
        self._update_event_table_presence_state(False)
        self._update_plot_empty_state()

    def show_event_table_context_menu(self, position):
        index = self.event_table.indexAt(position)
        if index.isValid():
            selection = self.event_table.selectionModel()
            if selection is not None and not selection.isSelected(index):
                self.event_table.selectRow(index.row())
        row = index.row() if index.isValid() else len(self.event_table_data)
        menu = QMenu()
        has_events = bool(getattr(self, "event_table_data", None))

        if index.isValid():
            edit_action = menu.addAction("✏️ Edit ID (µm)…")
            delete_action = menu.addAction("🗑️ Delete Event")
            menu.addSeparator()
            jump_action = menu.addAction("🔍 Jump to Event on Plot")
            pin_action = menu.addAction("📌 Pin to Plot")
            menu.addSeparator()
            replace_with_pin_action = menu.addAction("🔄 Replace ID with Pinned Value")
        else:
            edit_action = delete_action = jump_action = pin_action = replace_with_pin_action = None

        copy_menu = menu.addMenu("Copy")
        copy_row_action = copy_menu.addAction("Row-per-Event (Excel)")
        copy_values_action = copy_menu.addAction("Values Only (Column Paste)")
        copy_profile_menu = copy_menu.addMenu("Profile")
        copy_pressure_action = copy_profile_menu.addAction("Pressure Curve (Standard)")
        for action in (copy_row_action, copy_values_action, copy_pressure_action):
            action.setEnabled(has_events)

        menu.addSeparator()
        clear_pins_action = menu.addAction("❌ Clear All Pins")
        menu.addSeparator()
        add_event_action = menu.addAction("➕ Add Event…")

        action = menu.exec_(self.event_table.viewport().mapToGlobal(position))

        if action == copy_row_action:
            self._copy_event_profile_to_clipboard(EVENT_TABLE_ROW_PER_EVENT_ID, include_header=True)
            return
        if action == copy_values_action:
            self._copy_event_profile_to_clipboard(
                EVENT_VALUES_SINGLE_COLUMN_ID, include_header=False
            )
            return
        if action == copy_pressure_action:
            self._copy_event_profile_to_clipboard(PRESSURE_CURVE_STANDARD_ID, include_header=True)
            return

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
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
                rounded = round(new_val, 2)
                if has_od:
                    lbl, t, _, od_val, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, od_val, frame_val)
                else:
                    lbl, t, _, frame_val = self.event_table_data[row]
                    self.event_table_data[row] = (lbl, t, rounded, frame_val)
                self.event_table_controller.update_row(row, self.event_table_data[row])
                self._mark_row_edited(row)
                self.auto_export_table()

        elif index.isValid() and action == delete_action:
            self.delete_selected_events(indices=[row])

        elif index.isValid() and action == jump_action:
            self._focus_event_row(row, source="context")

        elif index.isValid() and action == pin_action:
            plot_host = getattr(self, "plot_host", None)
            is_pyqtgraph = plot_host is not None and plot_host.get_render_backend() == "pyqtgraph"
            if is_pyqtgraph:
                return
            t = self.event_table_data[row][1]
            id_val = self.event_table_data[row][2]
            marker = self.ax.plot(t, id_val, "ro", markersize=6)[0]
            label = self.ax.annotate(
                f"{t:.2f} s\n{round(id_val, 1)} µm",
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

        elif index.isValid() and action == replace_with_pin_action:
            t_event = self.event_table_data[row][1]
            if not self.pinned_points:
                QMessageBox.information(self, "No Pins", "There are no pinned points to use.")
                return

            def _pin_time(pin) -> float:
                coords = self._pin_coords(pin[0])
                return coords[0] if coords is not None else float("inf")

            closest_pin = min(self.pinned_points, key=lambda p: abs(_pin_time(p) - t_event))
            coords = self._pin_coords(closest_pin[0])
            if coords is None:
                return
            pin_id = coords[1]
            confirm = QMessageBox.question(
                self,
                "Confirm Replacement",
                f"Replace ID at {t_event:.2f}s with pinned value: {pin_id:.2f} µm?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self.last_replaced_event = (row, self.event_table_data[row][2])
                has_od = self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
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
                self._mark_row_edited(row)
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
                self._safe_remove_artist(marker)
                self._safe_remove_artist(label)
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

    def clear_recent_files(self, checked: bool = False):
        """Clear recent files list.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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

    def sample_inner_diameter(self, time_value: float) -> float | None:
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

    def compute_interval_metrics(self) -> dict | None:
        if self.trace_data is None:
            return None
        if "Time (s)" not in self.trace_data.columns:
            return None
        if "Inner Diameter" not in self.trace_data.columns:
            return None

        inner_pins = []
        for marker, _ in self.pinned_points:
            if getattr(marker, "trace_type", "inner") != "inner":
                continue
            coords = self._pin_coords(marker)
            if coords is not None:
                inner_pins.append(coords[0])
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
            getattr(self, "trace_widget", None),
            getattr(self, "overview_strip", None),
            getattr(self, "trace_nav_bar", None),
            getattr(self, "plot_stack_widget", None),
            self.scroll_slider,
            getattr(self, "snapshot_widget", None),
            self.event_table,
        ):
            if widget is not None:
                widget.setParent(None)

        plot_panel = QFrame()
        plot_panel.setObjectName("PlotPanel")
        plot_panel_layout = QVBoxLayout(plot_panel)
        plot_panel_layout.setContentsMargins(0, 0, 0, 0)
        plot_panel_layout.setSpacing(0)

        plot_container = QFrame()
        plot_container.setObjectName("PlotContainer")
        plot_container_layout = QVBoxLayout(plot_container)
        plot_container_layout.setContentsMargins(0, 0, 0, 0)
        plot_container_layout.setSpacing(0)
        if getattr(self, "overview_strip", None) is not None:
            plot_container_layout.addWidget(self.overview_strip)
        self.plot_stack_widget = QWidget()
        self.plot_stack_layout = QStackedLayout(self.plot_stack_widget)
        self.plot_stack_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_stack_layout.setSpacing(0)

        self.plot_content_page = QWidget()
        plot_content_layout = QVBoxLayout(self.plot_content_page)
        plot_content_layout.setContentsMargins(0, 0, 0, 0)
        plot_content_layout.setSpacing(4)
        plot_content_layout.addWidget(self.trace_widget, 1)
        if getattr(self, "trace_nav_bar", None) is not None:
            plot_content_layout.addWidget(self.trace_nav_bar)
        plot_content_layout.addWidget(self.scroll_slider)
        self.plot_stack_layout.addWidget(self.plot_content_page)

        self.plot_empty_state_page = QWidget()
        empty_state_layout = QVBoxLayout(self.plot_empty_state_page)
        empty_state_layout.setContentsMargins(0, 0, 0, 0)
        empty_state_layout.setSpacing(0)
        empty_state_layout.addStretch()
        self.plot_empty_state = PlotEmptyState(self.plot_empty_state_page)
        empty_state_layout.addWidget(self.plot_empty_state, 0, Qt.AlignHCenter)
        empty_state_layout.addStretch()
        self.plot_stack_layout.addWidget(self.plot_empty_state_page)

        plot_container_layout.addWidget(self.plot_stack_widget)
        self._configure_plot_empty_state_actions()
        self._update_plot_empty_state()
        plot_panel_layout.addWidget(plot_container)

        side_panel = QFrame()
        side_panel.setObjectName("SidePanel")
        side_panel.setMinimumWidth(420)
        side_panel.setMaximumWidth(560)
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)

        right_panel_card = QFrame()
        right_panel_card.setObjectName("RightPanelCard")
        self.right_panel_card = right_panel_card
        right_panel_layout = QVBoxLayout(right_panel_card)
        self._right_panel_layout = right_panel_layout
        right_panel_layout.setContentsMargins(0, 0, 0, 0)
        right_panel_layout.setSpacing(0)
        side_layout.addWidget(right_panel_card)

        # Snapshot + event layout:
        #   data_page (QWidget) -> main_layout (QVBoxLayout)
        #     -> data_splitter (QSplitter, Horizontal)
        #         [0] plot_panel (QFrame)
        #         [1] side_panel (QFrame)
        #             -> right_panel_card (QFrame) / QVBoxLayout (stretched 3:2 vs table)
        #                 [0] snapshot_card (QFrame) / QVBoxLayout
        #                     [0] snapshot_stack (QStackedWidget)
        #                         - snapshot_widget (TIFF viewer v2 with controls)
        #                     [1] metadata_panel
        #                 [1] event_table_card (QFrame) / QVBoxLayout
        #                     [0] event_table
        self.snapshot_card = None
        self.snapshot_stack = None
        if not self._snapshot_panel_disabled_by_env:
            self.snapshot_card = QFrame()
            self.snapshot_card.setObjectName("SnapshotCard")
            self.snapshot_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            snapshot_box = QVBoxLayout(self.snapshot_card)
            snapshot_box.setContentsMargins(0, 0, 0, 0)
            snapshot_box.setSpacing(0)
            snapshot_title = QLabel("Snapshot Viewer", self.snapshot_card)
            snapshot_title.setObjectName("PanelSectionTitle")
            snapshot_box.addWidget(snapshot_title, 0, Qt.AlignLeft)
            self.snapshot_stack = QStackedWidget(self.snapshot_card)
            self.snapshot_stack.setObjectName("SnapshotStack")
            self.snapshot_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.snapshot_stack.setMinimumHeight(160)
            if self.snapshot_widget is not None:
                self.snapshot_stack.addWidget(self.snapshot_widget)
            snapshot_box.addWidget(self.snapshot_stack, 1)
            snapshot_box.addWidget(self.metadata_panel)
            right_panel_layout.addWidget(self.snapshot_card)
        self.event_table_card = QFrame()
        self.event_table_card.setObjectName("TableCard")
        self.event_table_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table_layout = QVBoxLayout(self.event_table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_title = QLabel("Event Table", self.event_table_card)
        table_title.setObjectName("PanelSectionTitle")
        table_layout.addWidget(table_title)
        self.review_notice_banner = QFrame(self.event_table_card)
        self.review_notice_banner.setObjectName("ReviewNoticeBanner")
        notice_layout = QHBoxLayout(self.review_notice_banner)
        notice_layout.setContentsMargins(10, 6, 10, 6)
        notice_layout.setSpacing(8)
        notice_label = QLabel("Some events need review.", self.review_notice_banner)
        notice_label.setObjectName("ReviewNoticeText")
        notice_layout.addWidget(notice_label)
        notice_layout.addStretch()
        self.review_notice_review_button = QPushButton("Review Events", self.review_notice_banner)
        self.review_notice_review_button.clicked.connect(self._toggle_review_mode)
        self.review_notice_dismiss_button = QPushButton("Dismiss", self.review_notice_banner)
        self.review_notice_dismiss_button.clicked.connect(self._dismiss_review_notice)
        notice_layout.addWidget(self.review_notice_review_button)
        notice_layout.addWidget(self.review_notice_dismiss_button)
        self.review_notice_banner.setVisible(False)
        self._configure_review_notice_banner()
        table_layout.addWidget(self.review_notice_banner)
        table_layout.addWidget(self.event_table, 1)
        right_panel_layout.addWidget(self.event_table_card, 1)
        # Snapshot card uses Preferred policy (aspect-ratio-aware); event table expands.
        if self.snapshot_card is not None:
            right_panel_layout.setStretch(0, 0)
            right_panel_layout.setStretch(1, 1)
        self._update_snapshot_panel_layout()
        self._update_review_notice_visibility()

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("DataSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(plot_panel)
        splitter.addWidget(side_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        if hasattr(splitter, "stretchFactor"):
            try:
                stretch_factors = [splitter.stretchFactor(i) for i in range(splitter.count())]
            except Exception:
                stretch_factors = "error"
        else:
            stretch_factors = "unavailable (PyQt5 QSplitter has no stretchFactor())"
        log.info(
            "Snapshot splitter sizes: %s stretchFactors: %s",
            splitter.sizes(),
            stretch_factors,
        )
        with contextlib.suppress(Exception):
            splitter.splitterMoved.connect(lambda *_: self._log_snapshot_column_geometries())
        QTimer.singleShot(0, self._log_snapshot_column_geometries)

        return splitter

    def _configure_plot_empty_state_actions(self) -> None:
        panel = getattr(self, "plot_empty_state", None)
        if panel is None:
            return

        primary_action = getattr(self, "load_trace_action", None) or getattr(
            self, "action_open_trace", None
        )
        primary_tooltip = None
        if primary_action is not None:
            primary_tooltip = primary_action.toolTip() or None
        panel.primary_button.setText("Open Data\u2026")
        panel.set_primary_action(
            primary_action,
            tooltip=primary_tooltip or "Open a trace CSV file and auto-detect matching events",
        )

        secondary_action = getattr(self, "action_import_folder", None)
        secondary_tooltip = None
        if secondary_action is not None:
            secondary_tooltip = secondary_action.toolTip() or None
        panel.set_secondary_action(
            secondary_action,
            text="Import Folder\u2026",
            tooltip=secondary_tooltip or "Import a folder of datasets into the current project",
        )

    def _update_plot_empty_state(self) -> None:
        stack = getattr(self, "plot_stack_layout", None)
        empty_page = getattr(self, "plot_empty_state_page", None)
        content_page = getattr(self, "plot_content_page", None)
        if stack is None or empty_page is None or content_page is None:
            return
        show_empty = self.trace_data is None and self.current_sample is None
        target = empty_page if show_empty else content_page
        if stack.currentWidget() is not target:
            stack.setCurrentWidget(target)

    def _log_snapshot_column_geometries(self) -> None:
        """Debug helper to log sizes of snapshot/event column to diagnose gaps."""
        snap_card = getattr(self, "snapshot_card", None)
        table_card = getattr(self, "event_table_card", None)
        right_card = getattr(self, "right_panel_card", None)
        if snap_card is None or table_card is None or right_card is None:
            return
        log.info(
            "Snapshot column geom: right_panel_card=%s snapshot_card=%s event_table_card=%s",
            right_card.size(),
            snap_card.size(),
            table_card.size(),
        )

    def _apply_event_table_card_theme(self) -> None:
        """Apply theme styling to the event table container card."""
        log.debug(
            "[THEME-DEBUG] _apply_event_table_card_theme called, card_exists=%s",
            hasattr(self, "event_table_card") and self.event_table_card is not None,
        )

        card = getattr(self, "event_table_card", None)
        if card is None:
            return

        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
        bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("window_bg", "#ffffff"))
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        text = CURRENT_THEME.get("text", "#000000")
        card.setStyleSheet(
            f"""
            QFrame#TableCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QFrame#TableCard QWidget {{
                color: {text};
            }}
        """
        )
        style = card.styleSheet() if card is not None else ""
        log.debug("[THEME-DEBUG] EventTableCard styleSheet length=%s", len(style))

    def _apply_snapshot_theme(self) -> None:
        """Apply theme styling to the snapshot card and controls."""

        card = getattr(self, "snapshot_card", None)
        if card is None:
            return

        border = CURRENT_THEME.get("panel_border", CURRENT_THEME.get("grid_color", "#d0d0d0"))
        bg = CURRENT_THEME.get("panel_bg", CURRENT_THEME.get("window_bg", "#ffffff"))
        text = CURRENT_THEME.get("text", "#000000")
        status = CURRENT_THEME.get("text_disabled", text)
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        panel_bg = CURRENT_THEME.get("panel_bg", bg)
        panel_border = CURRENT_THEME.get("panel_border", border)
        button_bg = CURRENT_THEME.get("button_bg", bg)
        button_hover = CURRENT_THEME.get("button_hover_bg", button_bg)
        button_active = CURRENT_THEME.get(
            "button_active_bg", CURRENT_THEME.get("selection_bg", button_hover)
        )

        card.setStyleSheet(
            f"""
            QFrame#SnapshotCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QFrame#SnapshotCard QLabel {{
                color: {text};
            }}
            QFrame#SnapshotCard QFrame#TiffViewerHeader {{
                background: transparent;
                border: none;
            }}
            QFrame#SnapshotCard QWidget#TiffTransportBar {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: {radius}px;
            }}
            QLabel#SnapshotSpeedLabel,
            QLabel#SnapshotTimeLabel {{
                color: {text};
                font-size: 10px;
            }}
            QLabel#SnapshotTimeLabel {{
                font-family: Menlo, Consolas, "Courier New", monospace;
            }}
            QLabel#SnapshotStatusLabel {{
                color: {status};
                font-size: 10px;
            }}
            QLabel#SnapshotSubsampleLabel {{
                background: {button_hover};
                color: {text};
                border-radius: {radius}px;
                padding: 2px 8px;
                font-size: 11px;
            }}
            QFrame#SnapshotCard QToolButton {{
                background: {button_bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: 0px;
                min-height: 30px;
                min-width: 30px;
                font-size: 12px;
            }}
            QFrame#SnapshotCard QToolButton:hover {{
                background: {button_hover};
            }}
            QFrame#SnapshotCard QToolButton:pressed,
            QFrame#SnapshotCard QToolButton:checked {{
                background: {button_active};
            }}
            QFrame#SnapshotCard QToolButton:disabled {{
                background: {panel_bg};
                border-color: {panel_border};
                color: {status};
            }}
            QFrame#SnapshotCard QComboBox#SnapshotSpeedCombo {{
                background: transparent;
                border: none;
                padding: 2px 4px;
                min-height: 22px;
                font-size: 11px;
                color: {text};
            }}
        """
        )

        with contextlib.suppress(Exception):
            self._update_snapshot_playback_icons()

    def _update_snapshot_sync_label(self, mode: str) -> None:
        mode_key = (mode or "").lower()
        self._snapshot_sync_mode = mode_key
        self._refresh_snapshot_sync_label()

    def _set_snapshot_sync_time(self, time_value: float | None) -> None:
        if time_value is None or not math.isfinite(time_value):
            self._snapshot_sync_time = None
        else:
            self._snapshot_sync_time = float(time_value)
        self._refresh_snapshot_sync_label()

    def _refresh_snapshot_sync_label(self) -> None:
        label = getattr(self, "snapshot_sync_label", None)
        if label is None:
            return
        if not bool(getattr(self, "snapshot_sync_enabled", True)):
            label.setText("Synced: —")
            return
        time_value = getattr(self, "_snapshot_sync_time", None)
        if isinstance(time_value, (int, float)) and math.isfinite(time_value):
            label.setText(f"Synced: {time_value:.3f} s")
            return

        mode_key = (getattr(self, "_snapshot_sync_mode", "") or "").lower()
        if mode_key == "event":
            label.setText("Synced: Event")
        elif mode_key == "cursor":
            label.setText("Synced: Cursor")
        else:
            label.setText("Synced: —")

    def _update_snapshot_sync_toggle(self) -> None:
        checkbox = getattr(self, "snapshot_sync_checkbox", None)
        if checkbox is None:
            return
        viewer = getattr(self, "snapshot_widget", None)
        page_map = getattr(getattr(viewer, "controller", None), "page_time_map", None)
        available = bool(page_map and page_map.valid)
        desired = bool(self.snapshot_sync_enabled) if available else False
        checkbox.blockSignals(True)
        checkbox.setEnabled(available)
        checkbox.setChecked(desired)
        checkbox.blockSignals(False)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_sync_enabled(desired)

    def _update_snapshot_playback_icons(self) -> None:
        prev_btn = getattr(self, "prev_frame_btn", None)
        next_btn = getattr(self, "next_frame_btn", None)
        play_btn = getattr(self, "play_pause_btn", None)

        def apply_icon(button: QToolButton | None, icon_name: str) -> None:
            if button is None:
                return
            button.setIcon(snapshot_icon(icon_name))

        apply_icon(prev_btn, "prev")
        apply_icon(next_btn, "next")
        if play_btn is not None:
            icon_name = "pause" if play_btn.isChecked() else "play"
            apply_icon(play_btn, icon_name)

    def _apply_primary_toolbar_theme(self) -> None:
        """Refresh primary toolbar styles and icons from the current theme."""

        toolbar = getattr(self, "primary_toolbar", None)
        if toolbar is None:
            return

        # Reassign icons for known actions
        icon_actions = {
            "home_action": "Home.svg",
            "load_trace_action": "folder-open.svg",
            "load_snapshot_action": "empty-box.svg",
            "excel_action": "excel-mapper.svg",
            "review_events_action": None,
            "load_events_action": "folder-plus.svg",
            "save_session_action": "Save.svg",
            "welcome_action": "info-circle.svg",
        }
        for attr, icon_name in icon_actions.items():
            action = getattr(self, attr, None)
            if not isinstance(action, QAction) or not icon_name:
                continue
            try:
                action.setIcon(QIcon(self.icon_path(icon_name)))
            except Exception:
                continue

        # Refresh import button icon (shares load_trace icon)
        try:
            import_button = toolbar.findChild(QToolButton, "ImportDataButton")
            if import_button and hasattr(self, "load_trace_action"):
                import_button.setIcon(self.load_trace_action.icon())
        except Exception:
            log.debug("Failed to assign icon to import button", exc_info=True)

        # Reapply shared button styles
        if hasattr(self, "_shared_button_css"):
            toolbar.setStyleSheet(self._shared_button_css())
            for action in toolbar.actions():
                widget = toolbar.widgetForAction(action)
                if isinstance(widget, QPushButton):
                    self._apply_button_style(widget)

    # [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
    def auto_export_table(self, checked: bool = False, path: str | None = None):
        """Auto-export event table to CSV.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        try:
            sample = getattr(self, "current_sample", None)

            # Resolve the best trace path (prefer the live file on disk)
            candidate_paths: list[str] = []
            if self.trace_file_path:
                candidate_paths.append(os.path.abspath(self.trace_file_path))
            if sample is not None and getattr(sample, "trace_path", None):
                candidate_paths.append(os.path.abspath(sample.trace_path))
                # Try resolving stored links if present
                with contextlib.suppress(Exception):
                    resolved = self._resolve_sample_link(sample, "trace")
                    if resolved:
                        candidate_paths.append(os.path.abspath(resolved))

            trace_path = next((p for p in candidate_paths if p and os.path.isfile(p)), None)

            # Name and output directory
            base_name = None
            if sample is not None and getattr(sample, "name", None):
                base_name = str(sample.name).strip()
            if base_name is None and trace_path:
                base_name = os.path.splitext(os.path.basename(trace_path))[0]
            if not base_name:
                base_name = "event"

            if path:
                csv_path = path
                output_dir = os.path.dirname(csv_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
            else:
                if trace_path:
                    output_dir = os.path.dirname(trace_path)
                elif getattr(self.current_project, "path", None):
                    output_dir = os.path.dirname(self.current_project.path)
                else:
                    output_dir = os.getcwd()

                os.makedirs(output_dir, exist_ok=True)
                filename = f"{base_name}_eventDiameters_output.csv"
                csv_path = os.path.join(output_dir, filename)
            has_od = (
                "Outer Diameter" in self.trace_data.columns
                if self.trace_data is not None
                else False
            )
            avg_label = self._trace_label_for("p_avg")
            set_label = self._trace_label_for("p2")
            has_avg_p = self.trace_data is not None and avg_label in self.trace_data.columns
            has_set_p = self.trace_data is not None and set_label in self.trace_data.columns
            # EventRow: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)
            columns = [
                "Event",
                "Time (s)",
                "ID (µm)",
                "OD (µm)",
                "Avg P (mmHg)",
                "Set P (mmHg)",
                "Frame",
            ]
            df = pd.DataFrame(self.event_table_data, columns=columns)

            numeric_cols = [
                "Time (s)",
                "ID (µm)",
                "OD (µm)",
                "Avg P (mmHg)",
                "Set P (mmHg)",
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            # Round numeric columns to 2 decimal places
            if "ID (µm)" in df.columns:
                df["ID (µm)"] = df["ID (µm)"].round(2)
            if "OD (µm)" in df.columns:
                df["OD (µm)"] = df["OD (µm)"].round(2)
            if "Time (s)" in df.columns:
                df["Time (s)"] = df["Time (s)"].round(2)
            if "Avg P (mmHg)" in df.columns:
                df["Avg P (mmHg)"] = df["Avg P (mmHg)"].round(2)
            if "Set P (mmHg)" in df.columns:
                df["Set P (mmHg)"] = df["Set P (mmHg)"].round(2)

            # Drop columns that don't have data
            if not has_od:
                df = df.drop(columns=["OD (µm)"])
            if not has_avg_p:
                df = df.drop(columns=["Avg P (mmHg)"])
            if not has_set_p:
                df = df.drop(columns=["Set P (mmHg)"])

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

    def _export_event_table_to_path(self, path: str) -> bool:
        """
        Export the current event table to the given path using auto_export_table.

        Returns True on success, False on error.
        """
        try:
            self.auto_export_table(checked=False, path=path)
        except Exception as exc:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Failed to export events")
            msg.setText(f"Could not export event table to:\n{path}\n\n{exc}")
            msg.exec_()
            return False

        self._event_table_path = path
        self._invalidate_sample_state_cache()
        return True

    def _export_event_table_via_dialog(self) -> None:
        """
        Ask the user where to save the event table, then export if a path was chosen.
        """
        initial_dir = ""
        initial_name = "event_table.csv"

        if self._event_table_path:
            initial_dir = os.path.dirname(self._event_table_path)
            initial_name = os.path.basename(self._event_table_path)
        else:
            trace_path = getattr(self, "trace_file_path", None)
            if trace_path:
                initial_dir = os.path.dirname(trace_path)
                base = os.path.splitext(os.path.basename(trace_path))[0]
                initial_name = f"{base}_eventDiameters_output.csv"
            elif getattr(self.current_project, "path", None):
                initial_dir = os.path.dirname(self.current_project.path)

        start_path = os.path.join(initial_dir, initial_name) if initial_dir else initial_name

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export event table",
            start_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        self._export_event_table_to_path(path)

    def _event_rows_for_export(self) -> list[tuple]:
        rows = list(getattr(self, "event_table_data", []) or [])
        if not rows or not hasattr(self, "event_table"):
            return rows

        selection = self.event_table.selectionModel()
        if selection is None:
            return rows

        selected_rows = {index.row() for index in selection.selectedRows()}
        if not selected_rows:
            selected_rows = {index.row() for index in selection.selectedIndexes()}

        if not selected_rows:
            return rows

        return [rows[i] for i in sorted(selected_rows) if 0 <= i < len(rows)]

    def _build_export_table_for_profile(self, profile_id: str):
        profile = get_profile(profile_id)
        rows = self._event_rows_for_export()
        events = events_from_rows(rows)
        return profile, build_export_table(profile, events)

    def _show_export_warnings(self, profile_name: str, warnings: Sequence[str]) -> None:
        if not warnings:
            return
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(f"{profile_name} warnings")
        msg.setText("\n".join(warnings))
        msg.setStandardButtons(QMessageBox.Ok)
        msg.open()

    def _copy_event_profile_to_clipboard(self, profile_id: str, *, include_header: bool) -> None:
        profile, table = self._build_export_table_for_profile(profile_id)
        if not table.headers and not table.rows:
            return
        text = render_tsv(table, include_header=include_header)
        QApplication.clipboard().setText(text)
        self._show_export_warnings(profile.display_name, table.warnings)

    def _default_event_export_filename(self, profile_id: str) -> str:
        base_name = None
        sample = getattr(self, "current_sample", None)
        if sample is not None and getattr(sample, "name", None):
            base_name = str(sample.name).strip()
        if base_name is None and self.trace_file_path:
            base_name = os.path.splitext(os.path.basename(self.trace_file_path))[0]
        if not base_name:
            base_name = "event"
        return f"{base_name}_{profile_id}.csv"

    def _export_event_profile_csv_via_dialog(
        self, profile_id: str, *, include_header: bool
    ) -> None:
        profile, table = self._build_export_table_for_profile(profile_id)
        if not table.headers and not table.rows:
            return

        initial_dir = ""
        if self._event_table_path:
            initial_dir = os.path.dirname(self._event_table_path)
        elif getattr(self.current_project, "path", None):
            initial_dir = os.path.dirname(self.current_project.path)

        filename = self._default_event_export_filename(profile_id)
        start_path = os.path.join(initial_dir, filename) if initial_dir else filename

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {profile.display_name}",
            start_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        write_csv(path, table, include_header=include_header)
        self._show_export_warnings(profile.display_name, table.warnings)

    def open_excel_template_export_dialog(self, checked: bool = False) -> None:
        if not getattr(self, "event_table_data", None):
            QMessageBox.warning(self, "No Data", "No event data available to export.")
            return
        dialog = ExcelTemplateExportDialog(self, event_rows=self.event_table_data)
        dialog.exec_()

    def _prompt_export_event_table_after_review(self) -> None:
        """
        Offer to export the updated event table after a review session completes.
        """
        if not getattr(self, "event_table_data", None):
            return

        path = self._event_table_path

        if path:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Export updated event table?")
            msg.setText(
                "You reviewed and updated the event table.\n\n"
                f"Do you want to save these changes to:\n{path}"
            )
            overwrite_btn = msg.addButton("Export", QMessageBox.AcceptRole)
            choose_btn = msg.addButton("Choose different path…", QMessageBox.ActionRole)
            later_btn = msg.addButton("Not now", QMessageBox.RejectRole)
            msg.setDefaultButton(overwrite_btn)
            msg.exec_()
            clicked = msg.clickedButton()

            if clicked is overwrite_btn:
                if not self._export_event_table_to_path(path):
                    self._export_event_table_via_dialog()
            elif clicked is choose_btn:
                self._export_event_table_via_dialog()
        else:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Export updated event table?")
            msg.setText(
                "You reviewed and updated the event table.\n\n"
                "Do you want to export these values to a file?"
            )
            export_btn = msg.addButton("Export…", QMessageBox.AcceptRole)
            later_btn = msg.addButton("Not now", QMessageBox.RejectRole)
            msg.setDefaultButton(export_btn)
            msg.exec_()

            if msg.clickedButton() is export_btn:
                self._export_event_table_via_dialog()

    # ---------- UI State Persistence ----------
    def gather_ui_state(self):
        # Close review dock before capturing state so it doesn't reopen on restart
        review_dock = getattr(self, "review_dock", None)
        if review_dock is not None and review_dock.isVisible():
            review_dock.hide()

        state = {
            "geometry": self.saveGeometry().data().hex(),
            "window_state": self.saveState().data().hex(),
        }
        self._sync_track_visibility_from_host()
        state.update(self._collect_plot_view_state())
        layout_state = self._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        if self.current_experiment:
            state["last_experiment"] = self.current_experiment.name
            log.debug(
                "SAVE_STATE: Saving last_experiment='%s'",
                self.current_experiment.name,
            )
        if self.current_sample:
            state["last_sample"] = self.current_sample.name
            if getattr(self.current_sample, "dataset_id", None) is not None:
                state["last_dataset_id"] = int(self.current_sample.dataset_id)
            log.debug(
                "SAVE_STATE: Saving last_sample='%s'",
                self.current_sample.name,
            )
        if hasattr(self, "data_splitter") and self.data_splitter is not None:
            with contextlib.suppress(Exception):
                state["splitter_state"] = bytes(self.data_splitter.saveState()).hex()
        # Save trace visibility state
        if hasattr(self, "id_toggle_act") and self.id_toggle_act is not None:
            state["inner_trace_visible"] = self.id_toggle_act.isChecked()
        if hasattr(self, "od_toggle_act") and self.od_toggle_act is not None:
            state["outer_trace_visible"] = self.od_toggle_act.isChecked()
        host = getattr(self, "plot_host", None)
        if hasattr(self, "avg_pressure_toggle_act") and self.avg_pressure_toggle_act is not None:
            state["avg_pressure_visible"] = self.avg_pressure_toggle_act.isChecked()
        elif host is not None:
            with contextlib.suppress(Exception):
                state["avg_pressure_visible"] = host.is_channel_visible("avg_pressure")
        if hasattr(self, "set_pressure_toggle_act") and self.set_pressure_toggle_act is not None:
            state["set_pressure_visible"] = self.set_pressure_toggle_act.isChecked()
        elif host is not None:
            with contextlib.suppress(Exception):
                state["set_pressure_visible"] = host.is_channel_visible("set_pressure")
        # Capture experiment expand/collapse states from the tree at save-time.
        # Must be here because gather_ui_state() completely overwrites project.ui_state,
        # discarding whatever _on_tree_experiment_expand_changed had stored in memory.
        if getattr(self, "project_tree", None):
            experiment_expanded: dict[str, bool] = {}
            for _i in range(self.project_tree.topLevelItemCount()):
                _root = self.project_tree.topLevelItem(_i)
                for _j in range(_root.childCount()):
                    _exp_item = _root.child(_j)
                    _obj = _exp_item.data(0, Qt.UserRole)
                    if isinstance(_obj, Experiment):
                        experiment_expanded[_obj.name] = _exp_item.isExpanded()
            if experiment_expanded:
                state["experiment_expanded"] = experiment_expanded
        return state

    def _invalidate_sample_state_cache(self):
        """Invalidate the cached sample state to force recomputation on next gather."""
        self._sample_state_dirty = True
        self._cached_sample_state = None
        # Also invalidate snapshot style since it's part of the state
        self._snapshot_style_dirty = True
        self._cached_snapshot_style = None

    def _on_view_state_changed(self, reason: str = "") -> None:
        """Mark UI view state as changed (invalidate cache + dirty)."""
        if getattr(self, "_restoring_sample_state", False):
            return
        self._invalidate_sample_state_cache()
        if reason:
            self.mark_session_dirty(reason=reason)
        else:
            self.mark_session_dirty()

    def _sync_sample_events_dataframe(self, sample_state: dict) -> None:
        """Ensure the current sample's events_data mirrors the table rows in sample_state."""
        sample = getattr(self, "current_sample", None)
        if sample is None:
            return
        rows = list(sample_state.get("event_table_data") or [])
        normalized_rows = normalize_event_table_rows(rows)
        if normalized_rows:
            df = events_dataframe_from_rows(normalized_rows)
            sample.events_data = df
        else:
            sample.events_data = None

    def gather_sample_state(self):
        """Gather current sample state (cached for performance)."""
        # Return cached version if still valid
        if not self._sample_state_dirty and self._cached_sample_state is not None:
            self._sync_sample_events_dataframe(self._cached_sample_state)
            return self._cached_sample_state

        self._normalize_event_label_meta(len(self.event_table_data))
        # Start from existing UI state so we don't drop custom keys (e.g., data_quality)
        base_state: dict[str, Any] = {}
        if self.current_sample and isinstance(self.current_sample.ui_state, dict):
            base_state = copy.deepcopy(self.current_sample.ui_state)
        # preserve any previously saved style_settings
        prev = base_state.get("style_settings", {}) or {}
        x_axis = self._x_axis_for_style()
        focused_row = None
        event_table = getattr(self, "event_table", None)
        event_table_action = getattr(self, "event_table_action", None)
        if event_table is not None:
            with contextlib.suppress(Exception):
                idx = event_table.currentIndex()
                if idx.isValid():
                    focused_row = int(idx.row())
        state = {**base_state}
        state.update(
            {
                "table_fontsize": self.event_table.font().pointSize(),
                "event_table_data": list(self.event_table_data),
                "event_label_meta": copy.deepcopy(self.event_label_meta),
                "event_table_path": (
                    str(self._event_table_path) if self._event_table_path else None
                ),
                "event_table_visible": (
                    bool(event_table_action.isChecked())
                    if event_table_action is not None
                    else (bool(event_table.isVisible()) if event_table is not None else None)
                ),
                "pins": [
                    coords
                    for marker, _ in self.pinned_points
                    if (coords := self._pin_coords(marker))
                ],
                "plot_style": self.get_current_plot_style(),
                "grid_visible": self.grid_visible,
                "inner_trace_visible": (
                    self.id_toggle_act.isChecked() if self.id_toggle_act is not None else True
                ),
                "outer_trace_visible": (
                    self.od_toggle_act.isChecked() if self.od_toggle_act is not None else False
                ),
                "avg_pressure_visible": (
                    self.avg_pressure_toggle_act.isChecked()
                    if self.avg_pressure_toggle_act is not None
                    else (
                        getattr(self.plot_host, "is_channel_visible", lambda *_: True)(
                            "avg_pressure"
                        )
                        if hasattr(self, "plot_host")
                        else True
                    )
                ),
                "set_pressure_visible": (
                    self.set_pressure_toggle_act.isChecked()
                    if self.set_pressure_toggle_act is not None
                    else (
                        getattr(self.plot_host, "is_channel_visible", lambda *_: False)(
                            "set_pressure"
                        )
                        if hasattr(self, "plot_host")
                        else False  # Default: hide Set Pressure track
                    )
                ),
                "axis_settings": {
                    "x": {"label": x_axis.get_xlabel() if x_axis else ""},
                    "y": {"label": self.ax.get_ylabel()},
                },
                "time_cursor": {
                    "t": float(self._time_cursor_time)
                    if self._time_cursor_time is not None
                    else None,
                    "visible": bool(self._time_cursor_visible),
                },
                "focused_event_row": focused_row,
                "event_lines_visible": bool(self._event_lines_visible),
                "event_label_mode": str(self._event_label_mode or "indices"),
                "snapshot_viewer_visible": (
                    bool(self.snapshot_viewer_action.isChecked())
                    if getattr(self, "snapshot_viewer_action", None) is not None
                    else bool(self._snapshot_view_visible())
                ),
            }
        )
        if isinstance(self.legend_settings, dict):
            state["legend_settings"] = copy.deepcopy(self.legend_settings)
        # Always record whatever is in ui_state["style_settings"], even if empty
        state["style_settings"] = prev
        if self.ax2 is not None:
            state["axis_settings"]["y_outer"] = {"label": self.ax2.get_ylabel()}
        self._sync_track_visibility_from_host()
        layout_state = self._serialize_plot_layout()
        if layout_state:
            state["plot_layout"] = layout_state
        state.update(self._collect_plot_view_state())

        self._sync_sample_events_dataframe(state)
        # Cache the result
        self._cached_sample_state = state
        self._sample_state_dirty = False
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
        is_pg = self._plot_host_is_pyqtgraph()
        if "axis_xlim" in state:
            self._apply_time_window(state["axis_xlim"])
        if "axis_ylim" in state:
            if is_pg:
                inner_track = self.plot_host.track("inner") if hasattr(self, "plot_host") else None
                if inner_track is not None:
                    inner_track.set_ylim(*state["axis_ylim"])
            elif self.ax is not None:
                self.ax.set_ylim(state["axis_ylim"])
        splitter_state = state.get("splitter_state")
        if splitter_state and hasattr(self, "data_splitter") and self.data_splitter is not None:
            with contextlib.suppress(Exception):
                self.data_splitter.restoreState(bytes.fromhex(splitter_state))
        plot_layout = state.get("plot_layout")
        if plot_layout:
            self._pending_plot_layout = plot_layout
        pyqtgraph_tracks = state.get("pyqtgraph_track_state")
        if pyqtgraph_tracks:
            self._apply_pyqtgraph_track_state(pyqtgraph_tracks)
        if is_pg and "event_text_labels_on_trace" in state:
            plot_host = getattr(self, "plot_host", None)
            if plot_host is not None:
                plot_host.set_event_labels_visible(bool(state["event_text_labels_on_trace"]))
        # Restore trace visibility state
        if (
            "inner_trace_visible" in state
            and hasattr(self, "id_toggle_act")
            and self.id_toggle_act is not None
        ):
            self.id_toggle_act.blockSignals(True)
            self.id_toggle_act.setChecked(state["inner_trace_visible"])
            self.id_toggle_act.blockSignals(False)
        if (
            "outer_trace_visible" in state
            and hasattr(self, "od_toggle_act")
            and self.od_toggle_act is not None
        ):
            self.od_toggle_act.blockSignals(True)
            self.od_toggle_act.setChecked(state["outer_trace_visible"])
            self.od_toggle_act.blockSignals(False)
        if (
            "avg_pressure_visible" in state
            and hasattr(self, "avg_pressure_toggle_act")
            and self.avg_pressure_toggle_act is not None
        ):
            self.avg_pressure_toggle_act.blockSignals(True)
            self.avg_pressure_toggle_act.setChecked(state["avg_pressure_visible"])
            self.avg_pressure_toggle_act.blockSignals(False)
            self._apply_channel_toggle("avg_pressure", state["avg_pressure_visible"])
        if (
            "set_pressure_visible" in state
            and hasattr(self, "set_pressure_toggle_act")
            and self.set_pressure_toggle_act is not None
        ):
            self.set_pressure_toggle_act.blockSignals(True)
            self.set_pressure_toggle_act.setChecked(state["set_pressure_visible"])
            self.set_pressure_toggle_act.blockSignals(False)
            self._apply_channel_toggle("set_pressure", state["set_pressure_visible"])
        # Apply the visibility changes after restoring state
        if "inner_trace_visible" in state or "outer_trace_visible" in state:
            inner_on = state.get("inner_trace_visible", True)
            outer_on = state.get("outer_trace_visible", False)
            self._rebuild_channel_layout(inner_on, outer_on, redraw=False)
        self.canvas.draw_idle()

    def _sample_is_embedded(self, sample: SampleN | None) -> bool:
        if sample is None or getattr(sample, "dataset_id", None) is None:
            return False
        has_external = bool(
            getattr(sample, "trace_path", None)
            or getattr(sample, "events_path", None)
            or getattr(sample, "trace_relative", None)
            or getattr(sample, "events_relative", None)
        )
        return not has_external

    def apply_sample_state(self, state):
        t0 = time.perf_counter()
        self._restoring_sample_state = True
        try:
            if not state:
                return
            sample = getattr(self, "current_sample", None)
            is_embedded = self._sample_is_embedded(sample)
            self._event_table_path = state.get("event_table_path")
            self._pending_snapshot_visibility = None

            # ── minimal restore for embedded datasets to avoid pyqtgraph stalls
            if is_embedded:
                # Restore inner/outer toggles
                for key, act_name, channel in (
                    ("inner_trace_visible", "id_toggle_act", "inner"),
                    ("outer_trace_visible", "od_toggle_act", "outer"),
                ):
                    if key in state and hasattr(self, act_name):
                        act = getattr(self, act_name)
                        if act is not None:
                            act.blockSignals(True)
                            act.setChecked(bool(state[key]))
                            act.blockSignals(False)
                            self._apply_channel_toggle(channel, bool(state[key]))
                # Restore channel toggles for pressure tracks
                for key, act_name, channel in (
                    ("avg_pressure_visible", "avg_pressure_toggle_act", "avg_pressure"),
                    ("set_pressure_visible", "set_pressure_toggle_act", "set_pressure"),
                ):
                    if key in state and hasattr(self, act_name):
                        act = getattr(self, act_name)
                        if act is not None:
                            act.blockSignals(True)
                            act.setChecked(bool(state[key]))
                            act.blockSignals(False)
                            self._apply_channel_toggle(channel, bool(state[key]))
                if "axis_xlim" in state:
                    self._apply_time_window(state["axis_xlim"])
                self.canvas.draw_idle()
                log.info(
                    "Timing: apply_sample_state (embedded fast path) total=%.2f ms",
                    (time.perf_counter() - t0) * 1000,
                )
                return

            layout = state.get("plot_layout")
            # Applying stored plot layouts on embedded datasets is expensive on pyqtgraph;
            # skip restoring layout/track state on load when we have embedded data.
            if layout and not is_embedded:
                self._pending_plot_layout = layout
            pyqtgraph_tracks = state.get("pyqtgraph_track_state")
            if pyqtgraph_tracks and not is_embedded:
                self._apply_pyqtgraph_track_state(pyqtgraph_tracks)
            t_events = time.perf_counter()
            event_rows = state.get("event_table_data")
            # Only restore saved event rows when the state actually contains data; otherwise
            # keep the freshly populated events from storage.
            if isinstance(event_rows, list) and event_rows:
                self.event_table_data = event_rows
                meta_payload = state.get("event_label_meta")

                # CRITICAL FIX (Bug #3): Improved deserialization with fallback
                if isinstance(meta_payload, list):
                    try:
                        self.event_label_meta = [
                            (
                                self._with_default_review_state(item)
                                if isinstance(item, Mapping)
                                else self._with_default_review_state(None)
                            )
                            for item in meta_payload
                        ]
                    except Exception as e:
                        # If deserialization fails, try to preserve existing states
                        log.error(
                            f"Failed to deserialize event_label_meta for sample "
                            f"{getattr(sample, 'name', 'unknown')}: {e}. "
                            f"Attempting fallback to preserve review states."
                        )
                        # Fallback: try to get review states from events DataFrame
                        self._fallback_restore_review_states(len(event_rows))
                else:
                    # meta_payload is None or not a list - try fallback
                    if meta_payload is not None:
                        log.warning(
                            f"event_label_meta is not a list for sample "
                            f"{getattr(sample, 'name', 'unknown')} "
                            f"(got {type(meta_payload).__name__}). Using fallback."
                        )
                    self._fallback_restore_review_states(len(event_rows))

                self.populate_table()
                self._update_review_notice_visibility()
            event_table_visible = state.get("event_table_visible")
            if event_table_visible is not None:
                self._set_event_table_visible(
                    bool(event_table_visible),
                    source="restore",
                )
            event_lines_visible = state.get("event_lines_visible")
            if event_lines_visible is not None:
                self._event_lines_visible = bool(event_lines_visible)
                plot_host = getattr(self, "plot_host", None)
                if plot_host is not None:
                    plot_host.set_event_lines_visible(self._event_lines_visible)
                else:
                    self._toggle_event_lines_legacy(self._event_lines_visible)
            event_label_mode = state.get("event_label_mode")
            if event_label_mode:
                self._set_event_label_mode(str(event_label_mode))
            self._sync_event_controls()
            snapshot_visible = state.get("snapshot_viewer_visible")
            if snapshot_visible is not None:
                self._pending_snapshot_visibility = bool(snapshot_visible)
            cursor_payload = state.get("time_cursor")
            if isinstance(cursor_payload, Mapping):
                cursor_time = cursor_payload.get("t")
                cursor_visible = cursor_payload.get("visible", True)
            else:
                cursor_time = None
                cursor_visible = True
            try:
                cursor_time = float(cursor_time) if cursor_time is not None else None
            except (TypeError, ValueError):
                cursor_time = None
            self._time_cursor_visible = bool(cursor_visible)
            focused_row = state.get("focused_event_row")
            applied_focus = False
            if focused_row is not None and self.event_table_data:
                try:
                    row = int(focused_row)
                except (TypeError, ValueError):
                    row = None
                if row is not None:
                    row = max(0, min(row, len(self.event_table_data) - 1))
                    event_table = getattr(self, "event_table", None)
                    if event_table is not None:
                        event_table.blockSignals(True)
                    try:
                        self._focus_event_row(row, source="restore")
                        applied_focus = True
                    finally:
                        if event_table is not None:
                            event_table.blockSignals(False)
            if not applied_focus:
                self._time_cursor_time = cursor_time
                plot_host = getattr(self, "plot_host", None)
                if plot_host is not None and hasattr(plot_host, "set_time_cursor"):
                    with contextlib.suppress(Exception):
                        if cursor_time is None:
                            plot_host.set_time_cursor(None, visible=False)
                        else:
                            plot_host.set_time_cursor(
                                cursor_time,
                                visible=self._time_cursor_visible,
                            )
            t_axes = time.perf_counter()
            is_pg = self._plot_host_is_pyqtgraph()
            if "axis_xlim" in state:
                self._apply_time_window(state["axis_xlim"])
            if "axis_ylim" in state:
                if is_pg:
                    inner_track = (
                        self.plot_host.track("inner") if hasattr(self, "plot_host") else None
                    )
                    if inner_track is not None:
                        inner_track.set_ylim(*state["axis_ylim"])
                elif self.ax is not None:
                    self.ax.set_ylim(state["axis_ylim"])
            if "axis_outer_ylim" in state:
                if is_pg:
                    outer_track = (
                        self.plot_host.track("outer") if hasattr(self, "plot_host") else None
                    )
                    if outer_track is not None:
                        outer_track.set_ylim(*state["axis_outer_ylim"])
                elif self.ax2 is not None:
                    self.ax2.set_ylim(state["axis_outer_ylim"])
            t_font = time.perf_counter()
            if "table_fontsize" in state:
                font = self.event_table.font()
                font.setPointSize(state["table_fontsize"])
                self.event_table.setFont(font)
            t_pins = time.perf_counter()
            if "pins" in state:
                for marker, label in self.pinned_points:
                    self._safe_remove_artist(marker)
                    self._safe_remove_artist(label)
                self.pinned_points.clear()
                if is_pg:
                    inner_track = (
                        self.plot_host.track("inner") if hasattr(self, "plot_host") else None
                    )
                    if inner_track is not None:
                        inner_track.clear_pins()
                        for x, y in state.get("pins", []):
                            label_text = f"{x:.2f} s\n{y:.1f} µm"
                            marker, text_item = inner_track.add_pin(x, y, label_text)
                            self.pinned_points.append((marker, text_item))
                else:
                    for x, y in state.get("pins", []):
                        marker = self.ax.plot(x, y, "ro", markersize=6)[0]
                        label = self.ax.annotate(
                            f"{x:.2f} s\n{y:.1f} µm",
                            xy=(x, y),
                            xytext=(6, 6),
                            textcoords="offset points",
                            bbox=dict(boxstyle="round,pad=0.3", fc="#F8F8F8", ec="#CCCCCC", lw=1),
                            fontsize=8,
                        )
                        self.pinned_points.append((marker, label))

            if "grid_visible" in state:
                self.grid_visible = state["grid_visible"]
                if is_pg:
                    for track in getattr(self.plot_host, "tracks", lambda: [])():
                        track.set_grid_visible(self.grid_visible)
                elif self.ax is not None:
                    self.ax.grid(self.grid_visible)
                    if self.grid_visible:
                        self.ax.grid(color=CURRENT_THEME["grid_color"])
            if (
                ("inner_trace_visible" in state or "outer_trace_visible" in state)
                and hasattr(self, "id_toggle_act")
                and self.id_toggle_act is not None
            ):
                inner_on = state.get(
                    "inner_trace_visible",
                    self.id_toggle_act.isChecked(),
                )
                outer_on = state.get(
                    "outer_trace_visible",
                    (self.od_toggle_act.isChecked() if self.od_toggle_act is not None else False),
                )
                outer_supported = self._outer_channel_available()
                self._apply_toggle_state(inner_on, outer_on, outer_supported=outer_supported)
                self._rebuild_channel_layout(inner_on, outer_on, redraw=False)
            # Apply avg/set visibility after layout so ancillary tracks stay in sync
            if (
                "avg_pressure_visible" in state
                and hasattr(self, "avg_pressure_toggle_act")
                and self.avg_pressure_toggle_act is not None
            ):
                self.avg_pressure_toggle_act.blockSignals(True)
                self.avg_pressure_toggle_act.setChecked(state["avg_pressure_visible"])
                self.avg_pressure_toggle_act.blockSignals(False)
                self._apply_channel_toggle("avg_pressure", state["avg_pressure_visible"])
            if (
                "set_pressure_visible" in state
                and hasattr(self, "set_pressure_toggle_act")
                and self.set_pressure_toggle_act is not None
            ):
                self.set_pressure_toggle_act.blockSignals(True)
                self.set_pressure_toggle_act.setChecked(state["set_pressure_visible"])
                self.set_pressure_toggle_act.blockSignals(False)
                self._apply_channel_toggle("set_pressure", state["set_pressure_visible"])

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
                    with contextlib.suppress(AttributeError):
                        self.plot_style_dialog.set_style(state["plot_style"])
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
            self._apply_time_mode(self._time_mode, persist=False)
            t_layout = time.perf_counter()
            self._apply_pending_plot_layout()
            t_pyqtgraph = time.perf_counter()
            self._apply_pending_pyqtgraph_track_state()
            t_draw = time.perf_counter()
            self.canvas.draw_idle()
            t_end = time.perf_counter()
            log.info(
                "Timing: apply_sample_state breakdown (ms) events=%.2f axes=%.2f font=%.2f pins=%.2f layout=%.2f pyqtgraph=%.2f draw=%.2f total=%.2f",
                (t_events - t0) * 1000,
                (t_font - t_events) * 1000,
                (t_pins - t_font) * 1000,
                (t_layout - t_pins) * 1000,
                (t_pyqtgraph - t_layout) * 1000,
                (t_draw - t_pyqtgraph) * 1000,
                (t_end - t_draw) * 1000,
                (t_end - t0) * 1000,
            )

        finally:
            self._restoring_sample_state = False
            log.debug("apply_sample_state completed in %.3f s", time.perf_counter() - t0)

    def restore_last_selection(self) -> bool:
        if not self.project_tree or not self.current_project:
            return False

        state = getattr(self.current_project, "ui_state", {}) or {}
        last_dataset_id = state.get("last_dataset_id")
        last_exp = state.get("last_experiment")
        last_sample = state.get("last_sample")
        log.info(
            "RESTORE_SELECTION: last_experiment='%s' last_sample='%s'",
            last_exp,
            last_sample,
        )
        if last_dataset_id is not None:
            try:
                target_id = int(last_dataset_id)
            except (TypeError, ValueError):
                target_id = None
            if target_id is not None:
                root = self.project_tree.topLevelItem(0)
                if root is not None:
                    for i in range(root.childCount()):
                        child = root.child(i)
                        for j in range(child.childCount()):
                            sample_child = child.child(j)
                            sample_obj = sample_child.data(0, Qt.UserRole)
                            if (
                                isinstance(sample_obj, SampleN)
                                and sample_obj.dataset_id == target_id
                            ):
                                log.info(
                                    "RESTORE_SELECTION: Restored dataset_id=%s",
                                    target_id,
                                )
                                self.project_tree.setCurrentItem(sample_child)
                                self.on_tree_item_clicked(sample_child, 0)
                                return True
        if not last_exp:
            log.warning("RESTORE_SELECTION: No last_experiment saved, falling back to first sample")
            return False

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
                        if isinstance(sample_obj, SampleN) and sample_obj.name == last_sample:
                            sample_item = sample_child
                            break
                break

        if sample_item is not None:
            log.info("RESTORE_SELECTION: Successfully restored sample '%s'", last_sample)
            self.project_tree.setCurrentItem(sample_item)
            self.on_tree_item_clicked(sample_item, 0)
            return True

        if exp_item is not None:
            log.info(
                "RESTORE_SELECTION: Restored experiment '%s' (sample not found)",
                last_exp,
            )
            self.project_tree.setCurrentItem(exp_item)
            self.on_tree_item_clicked(exp_item, 0)
            return True

        log.warning("RESTORE_SELECTION: Failed to find experiment '%s' in tree", last_exp)
        return False

    def closeEvent(self, event):
        self._shutdown_update_checker()
        if self.current_project and self.current_project.path:
            # Stop autosave timers to prevent concurrent saves during shutdown
            self.autosave_timer.stop()
            self._deferred_autosave_timer.stop()

            project_path = self.current_project.path
            try:
                # Wait for any in-progress save to complete (with timeout)
                max_wait_iterations = 50  # 5 seconds max (50 * 100ms)
                wait_iteration = 0
                while self._save_in_progress and wait_iteration < max_wait_iterations:
                    from PyQt5.QtCore import QCoreApplication

                    QCoreApplication.processEvents()
                    import time

                    time.sleep(0.1)
                    wait_iteration += 1

                if self._save_in_progress:
                    log.warning("Timed out waiting for save to complete, forcing save anyway")

                if not self.session_dirty:
                    log.info("Close-event save skipped (not dirty) path=%s", project_path)
                else:
                    log.info(
                        "Close-event save requested path=%s (skip_optimize=True)",
                        project_path,
                    )
                    self._save_in_progress = True
                    self.current_project.ui_state = self.gather_ui_state()
                    if self.current_sample:
                        state = self.gather_sample_state()
                        self.current_sample.ui_state = state
                        self.project_state[id(self.current_sample)] = state
                    # Data integrity takes precedence; use full save path to ensure event edits persist.
                    save_project_file(self.current_project)
                    log.info("Close-event save completed path=%s", project_path)
                    self._reset_session_dirty(reason="close-event save")
            except Exception as e:
                log.error("Failed to auto-save project:\n%s", e)
            finally:
                self._save_in_progress = False
        self._replace_current_project(None)
        super().closeEvent(event)


# Bind mixin functions
VasoAnalyzerApp.auto_export_editable_plot = auto_export_editable_plot
VasoAnalyzerApp.export_high_res_plot = export_high_res_plot
VasoAnalyzerApp.toggle_grid = toggle_grid
VasoAnalyzerApp.save_data_as_n = save_data_as_n
VasoAnalyzerApp.open_excel_mapping_dialog = open_excel_mapping_dialog
