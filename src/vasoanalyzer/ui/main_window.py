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
from PyQt6.QtCore import (
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
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QUndoStack,
)
from PyQt6.QtWidgets import (
    QApplication,
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
from .project_explorer import SubfolderRef
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


class _ProgressAnimator(QObject):
    """Animates a QProgressBar with an asymptotic crawl toward a cap, then snaps to 100% on finish.

    While a job is running the bar smoothly moves from 0 toward _CAP (never quite reaching it),
    giving users honest "something is happening" feedback without fake percentages.
    Calling finish() stops the crawl, jumps to 100%, and auto-hides after a short delay.
    """

    _CAP = 85          # asymptote: bar naturally approaches but never reaches this %
    _EASING = 0.07     # fraction of remaining gap closed each tick (higher = faster start)
    _INTERVAL_MS = 50  # tick rate in ms (50ms ≈ 20 fps, smooth without thrashing)

    def __init__(self, bar: "QProgressBar", parent: "QObject | None" = None) -> None:
        super().__init__(parent)
        self._bar = bar
        self._current = 0.0
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self._INTERVAL_MS)
        self._tick_timer.timeout.connect(self._tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._bar.hide)

    def start(self, message: str = "") -> None:
        """Show the bar and begin crawling toward the cap."""
        self._hide_timer.stop()
        self._tick_timer.stop()
        self._current = 0.0
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._set_format(message)
        self._bar.show()
        self._tick_timer.start()

    def update_label(self, label: str) -> None:
        """Update the text label without touching the animated value."""
        if self._bar.isVisible():
            self._set_format(label)

    def finish(self) -> None:
        """Stop crawling, snap to 100%, then auto-hide after a short pause."""
        self._tick_timer.stop()
        self._bar.setValue(100)
        self._hide_timer.start(400)

    def stop(self) -> None:
        """Immediately hide without completing the animation (e.g. on error)."""
        self._tick_timer.stop()
        self._hide_timer.stop()
        self._bar.hide()

    def _tick(self) -> None:
        remaining = self._CAP - self._current
        self._current += remaining * self._EASING
        self._bar.setValue(int(self._current))

    def _set_format(self, message: str) -> None:
        self._bar.setFormat(f"{message} %p%" if message else "%p%")


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
        screen_size = QGuiApplication.primaryScreen().availableGeometry()
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
        self._progress_animator = _ProgressAnimator(self._progress_bar, self)
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

        # ===== Instantiate Manager Delegates =====
        from vasoanalyzer.ui.managers.export_manager import ExportManager
        from vasoanalyzer.ui.managers.navigation_manager import NavigationManager
        from vasoanalyzer.ui.managers.project_manager import ProjectManager
        from vasoanalyzer.ui.managers.snapshot_manager import SnapshotManager
        from vasoanalyzer.ui.managers.theme_manager import ThemeManager
        from vasoanalyzer.ui.managers.event_manager import EventManager
        from vasoanalyzer.ui.managers.sample_manager import SampleManager
        from vasoanalyzer.ui.managers.plot_manager import PlotManager

        self._export_mgr = ExportManager(self, parent=self)
        self._project_mgr = ProjectManager(self, parent=self)
        self._snapshot_mgr = SnapshotManager(self, parent=self)
        self._navigation_mgr = NavigationManager(self, parent=self)
        self._theme_mgr = ThemeManager(self, parent=self)
        self._event_mgr = EventManager(self, parent=self)
        self._sample_mgr = SampleManager(self, parent=self)
        self._plot_mgr = PlotManager(self, parent=self)
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
        self.project_dock.tree.sample_moved.connect(self._on_sample_moved_in_tree)
        log.info("Connected project_tree.itemDoubleClicked to on_tree_item_double_clicked")
        # Single-click opens a sample; double-click is reserved for editing or opening figures
        self.project_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(self.show_project_context_menu)
        self.project_tree.setAlternatingRowColors(True)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)
        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.project_dock.toggleViewAction())

        # Toggle button in toolbar
        self.project_toggle_btn = QToolButton()
        self.project_toggle_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.project_toggle_btn.setCheckable(True)
        self.project_toggle_btn.setChecked(False)
        self.project_toggle_btn.setToolTip("Toggle project panel")
        self.project_toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
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
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.metadata_dock)

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
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.metadata_toggle_btn.setCheckable(True)
        self.metadata_toggle_btn.setChecked(False)
        self.metadata_toggle_btn.setToolTip("Toggle event and snapshot panel")
        self.metadata_toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
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
        self.zoom_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.zoom_dock)
        self.zoom_dock.hide()

        if hasattr(self, "showhide_menu"):
            self.showhide_menu.addAction(self.zoom_dock.toggleViewAction())

        self.zoom_dock.visibilityChanged.connect(self._on_zoom_visibility_changed)

    def setup_scope_dock(self):
        self.scope_dock = ScopeDock(self)
        self.scope_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.scope_dock)
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
        self.review_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.review_dock)
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
        self._project_mgr._replace_current_project(project)

    def _ensure_data_cache(self, hint_path: str | None = None) -> DataCache:
        return self._sample_mgr._ensure_data_cache(hint_path)

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
        self._sample_mgr._update_sample_link_metadata(sample, kind, path_obj)

    def _resolve_sample_link(self, sample: SampleN, kind: str) -> str | None:
        return self._sample_mgr._resolve_sample_link(sample, kind)

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
        self._project_mgr.new_project(checked)

    def _create_project_from_inputs(self, name: str, path: str, exp_name: str | None) -> bool:
        return self._project_mgr._create_project_from_inputs(name, path, exp_name)

    def _open_project_file_legacy(self, path: str | None = None):
        self._project_mgr._open_project_file_legacy(path)

    def open_project_file(self, path: str | bool | None = None):
        return self._project_mgr.open_project_file(path)

    def _prepare_project_for_save(self) -> None:
        self._project_mgr._prepare_project_for_save()

    def _project_snapshot_for_save(self, project: Project) -> Project:
        return self._project_mgr._project_snapshot_for_save(project)

    def _set_save_actions_enabled(self, enabled: bool) -> None:
        self._project_mgr._set_save_actions_enabled(enabled)

    def changeEvent(self, event):
        # Note: PaletteChange events are no longer handled since we don't follow OS theme.
        # Theme changes are controlled explicitly via View > Color Theme menu.
        super().changeEvent(event)

    def _status_bar_theme_colors(self) -> dict[str, str]:
        """Return palette-aware colors for status/progress widgets."""

        pal = self.palette()
        window = pal.color(QPalette.ColorRole.Window)
        text = pal.color(QPalette.ColorRole.WindowText)
        highlight = pal.color(QPalette.ColorRole.Highlight)

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
        self._project_mgr._start_background_save(path, skip_optimize=skip_optimize, reason=reason, mode=mode, ctx=ctx)

    def _on_save_progress_changed(self, percent: int, message: str) -> None:
        self._project_mgr._on_save_progress_changed(percent, message)

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
        self._project_mgr._on_save_error(details)

    def _on_save_finished(self, ok: bool, duration_sec: float, path: str) -> None:
        self._project_mgr._on_save_finished(ok, duration_sec, path)

    def save_project_file(self, checked: bool = False):
        self._project_mgr.save_project_file(checked)

    def save_project_file_as(self, checked: bool = False):
        self._project_mgr.save_project_file_as(checked)

    def export_project_bundle_action(self, checked: bool = False):
        self._export_mgr.export_project_bundle_action(checked)

    def export_shareable_project(self, checked: bool = False):
        self._export_mgr.export_shareable_project(checked)

    def export_dataset_package_action(self, checked: bool = False):
        self._export_mgr.export_dataset_package_action(checked)

    def import_dataset_from_project_action(self, checked: bool = False):
        self._sample_mgr.import_dataset_from_project_action(checked)

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
        self._sample_mgr.import_dataset_package_action(checked)

    # Clipboard-based copy/paste of datasets --------------------------------
    def _gather_selected_samples_for_copy(self) -> list[SampleN]:
        return self._sample_mgr._gather_selected_samples_for_copy()

    def copy_selected_datasets(self) -> None:
        self._sample_mgr.copy_selected_datasets()

    def paste_datasets(self) -> None:
        self._sample_mgr.paste_datasets()

    def _run_deferred_autosave(self):
        self._project_mgr._run_deferred_autosave()

    def request_deferred_autosave(self, delay_ms: int = 2000, *, reason: str = "deferred") -> None:
        self._project_mgr.request_deferred_autosave(delay_ms, reason=reason)

    def auto_save_project(self, reason: str | None = None, ctx: dict | None = None):
        self._project_mgr.auto_save_project(reason, ctx)

    def _autosave_tick(self):
        self._project_mgr._autosave_tick()

    def _bump_project_state_rev(self, reason: str) -> None:
        self._project_mgr._bump_project_state_rev(reason)

    def _persist_sample_ui_state(self, sample: SampleN, state: dict) -> None:
        self._sample_mgr._persist_sample_ui_state(sample, state)

    def _get_sample_data_quality(self, sample: SampleN) -> str | None:
        return self._sample_mgr._get_sample_data_quality(sample)

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
                self._data_quality_icons[quality] = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return self._data_quality_icons[quality]

    def _update_tree_icons_for_samples(self, samples: Sequence[SampleN]) -> None:
        self._sample_mgr._update_tree_icons_for_samples(samples)

    def refresh_project_tree(self):
        if not self.project_tree:
            return

        # Capture current expand/collapse state for each experiment before clearing
        expanded_state: dict[str, bool] = {}
        for i in range(self.project_tree.topLevelItemCount()):
            exp_item = self.project_tree.topLevelItem(i)
            if exp_item is None:
                continue
            obj = exp_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(obj, Experiment):
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
        # Update the dock header label with the project name
        if hasattr(self.project_dock, "header_label"):
            self.project_dock.header_label.setText(self.current_project.name)
        _sf_color = QColor(CURRENT_THEME.get("text_disabled", "#6B7280"))

        for exp in self.current_project.experiments:
            exp_item = QTreeWidgetItem([exp.name])
            exp_item.setData(0, Qt.ItemDataRole.UserRole, exp)
            exp_item.setFlags(exp_item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
            exp_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirClosedIcon))
            exp_item.setData(0, Qt.ItemDataRole.FontRole, self._bold_font(size_delta=1))
            self.project_tree.addTopLevelItem(exp_item)
            all_samples = sorted(
                exp.samples,
                key=lambda sample: (sample.name or "").lower(),
            )
            ungrouped = [s for s in all_samples if not getattr(s, "subfolder", None)]
            # Canonical subfolder order: declared names first, then any extra from sample data
            declared = list(exp.subfolder_names) if exp.subfolder_names else []
            extra = [
                sf for sf in dict.fromkeys(
                    getattr(s, "subfolder", None) for s in all_samples
                    if getattr(s, "subfolder", None)
                )
                if sf not in declared
            ]
            ordered_subfolders = declared + extra
            subfolder_map: dict[str, list[SampleN]] = {}
            for s in all_samples:
                sf = getattr(s, "subfolder", None)
                if sf:
                    subfolder_map.setdefault(sf, []).append(s)

            for s in ungrouped:
                exp_item.addChild(self._make_tree_sample_item(s))

            sf_font = self._bold_font(size_delta=0)
            sf_font.setItalic(True)
            sf_font.setBold(False)
            for sf_name in ordered_subfolders:
                sf_item = QTreeWidgetItem([sf_name])
                sf_item.setData(0, Qt.ItemDataRole.UserRole, SubfolderRef(name=sf_name, experiment=exp))
                sf_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                sf_item.setData(0, Qt.ItemDataRole.FontRole, sf_font)
                sf_item.setForeground(0, QBrush(_sf_color))
                sf_item.setFlags(
                    (sf_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    & ~Qt.ItemFlag.ItemIsDragEnabled
                )
                exp_item.addChild(sf_item)
                for s in subfolder_map.get(sf_name, []):
                    sf_item.addChild(self._make_tree_sample_item(s))
                sf_item.setExpanded(True)

            # Restore expand state; default to expanded for experiments seen for the first time
            exp_item.setExpanded(expanded_state.get(exp.name, True))
        self._update_metadata_panel(self.current_project)
        self._schedule_missing_asset_scan()
        if self.current_sample:
            self._select_tree_item_for_sample(self.current_sample)

    def _make_tree_sample_item(self, s: SampleN) -> QTreeWidgetItem:
        """Create a QTreeWidgetItem for a sample node."""
        has_data = bool(s.trace_path or s.trace_data is not None or s.dataset_id is not None)
        status = "✓" if has_data else "✗"
        quality = self._get_sample_data_quality(s)
        item = QTreeWidgetItem([f"{s.name} {status}"])
        item.setData(0, Qt.ItemDataRole.UserRole, s)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setIcon(0, self._data_quality_icon(quality))
        item.setToolTip(0, f"Data quality: {self._data_quality_label(quality)}")
        return item

    def _on_tree_experiment_expand_changed(self, item) -> None:
        """Persist experiment expand/collapse state to project.ui_state."""
        obj = item.data(0, Qt.ItemDataRole.UserRole)
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
            exp_item = self.project_tree.topLevelItem(i)
            obj = exp_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(obj, Experiment):
                new_order.append(obj)
        if new_order:
            self.current_project.experiments = new_order
            self.mark_session_dirty("experiment_reordered")

    def _on_sample_moved_in_tree(self, samples, target_exp: Experiment, target_sf) -> None:
        """Handle one or more samples drag-dropped within the project tree."""
        if not self.current_project:
            return
        for sample in samples:
            source_exp = None
            for exp in self.current_project.experiments:
                if sample in exp.samples:
                    source_exp = exp
                    break
            if source_exp is None:
                continue
            if source_exp is not target_exp:
                source_exp.samples.remove(sample)
                target_exp.samples.append(sample)
            sample.subfolder = target_sf
        if target_sf and target_sf not in target_exp.subfolder_names:
            target_exp.subfolder_names.append(target_sf)
        self.refresh_project_tree()
        self.mark_session_dirty()

    def _set_samples_data_quality(self, samples: Sequence[SampleN], quality: str | None) -> None:
        self._sample_mgr._set_samples_data_quality(samples, quality)

    def _select_dataset_ids(self, dataset_ids: Sequence[int]) -> None:
        self._sample_mgr._select_dataset_ids(dataset_ids)

    def _expand_experiment_in_tree(self, exp_name: str) -> None:
        if not self.project_tree:
            return
        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            exp_item = tree.topLevelItem(i)
            if exp_item is None:
                continue
            if exp_item.text(0) == exp_name:
                tree.expandItem(exp_item)
                return

    def _select_tree_item_for_sample(self, sample: SampleN | None) -> None:
        self._sample_mgr._select_tree_item_for_sample(sample)

    def _selected_samples_from_tree(self) -> list[SampleN]:
        return self._sample_mgr._selected_samples_from_tree()

    def _experiment_name_for_sample(self, sample: SampleN) -> str | None:
        return self._sample_mgr._experiment_name_for_sample(sample)

    def _open_first_sample_if_none_active(self) -> None:
        self._sample_mgr._open_first_sample_if_none_active()

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
        obj = item.data(0, Qt.ItemDataRole.UserRole)

        # Debug: Log all clicks
        if isinstance(obj, tuple) and len(obj) >= 1:
            log.info(f"Single-clicked tree item: {obj[0]} (tuple with {len(obj)} elements)")

        if isinstance(obj, SampleN):
            # When Ctrl or Shift is held the user is building a multi-selection.
            # Skip activation so the tree can accumulate selections without
            # refresh_project_tree clearing them.
            modifiers = QApplication.keyboardModifiers()
            if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                return

            # Resolve parent experiment: parent may be an Experiment or a SubfolderRef
            experiment = None
            parent = item.parent()
            if parent:
                parent_obj = parent.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_obj, Experiment):
                    experiment = parent_obj
                elif isinstance(parent_obj, SubfolderRef):
                    experiment = parent_obj.experiment
            self._activate_sample(obj, experiment)
            # Metadata panel is updated in _render_sample, no need to update here
            return
        if isinstance(obj, SubfolderRef):
            # Toggle expand/collapse on single click
            item.setExpanded(not item.isExpanded())
            return
        if isinstance(obj, Experiment):
            item.setExpanded(not item.isExpanded())
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
        obj = item.data(0, Qt.ItemDataRole.UserRole)
        log.info(f"Double-clicked tree item, obj type: {type(obj)}, obj: {obj}")

    def _activate_sample(
        self,
        sample: SampleN,
        experiment: Experiment | None,
        *,
        ensure_loaded: bool = False,
    ) -> None:
        self._sample_mgr._activate_sample(sample, experiment, ensure_loaded=ensure_loaded)

    def on_tree_item_changed(self, item, _):
        obj = item.data(0, Qt.ItemDataRole.UserRole)
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
        elif isinstance(obj, SubfolderRef):
            old_name = obj.name
            if name and name != old_name:
                for s in obj.experiment.samples:
                    if getattr(s, "subfolder", None) == old_name:
                        s.subfolder = name
                sf_names = obj.experiment.subfolder_names
                if old_name in sf_names:
                    sf_names[sf_names.index(old_name)] = name
                obj.name = name
                self.mark_session_dirty()
        elif isinstance(obj, Experiment):
            obj.name = name
        elif isinstance(obj, Project):
            obj.name = name
            if hasattr(self.project_dock, "header_label"):
                self.project_dock.header_label.setText(name)

    def on_tree_item_double_clicked(self, item, _):
        """Handle tree double-click (sample)."""
        obj = item.data(0, Qt.ItemDataRole.UserRole)
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
        obj = selection[0].data(0, Qt.ItemDataRole.UserRole)
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
        self._sample_mgr.on_sample_notes_changed(text)

    def on_sample_add_attachment(self) -> None:
        self._sample_mgr.on_sample_add_attachment()

    def on_sample_remove_attachment(self, index: int) -> None:
        self._sample_mgr.on_sample_remove_attachment(index)

    def on_sample_open_attachment(self, index: int) -> None:
        self._sample_mgr.on_sample_open_attachment(index)

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
        return self._sample_mgr._queue_sample_load_until_context(sample)

    def _flush_pending_sample_loads(self) -> None:
        self._sample_mgr._flush_pending_sample_loads()

    def _log_sample_data_summary(
        self,
        sample: SampleN,
        trace_df: pd.DataFrame | None = None,
        events_df: pd.DataFrame | None = None,
    ) -> None:
        self._sample_mgr._log_sample_data_summary(sample, trace_df, events_df)

    def load_sample_into_view(self, sample: SampleN):
        self._sample_mgr.load_sample_into_view(sample)

    def _prepare_sample_view(self, sample: SampleN) -> None:
        self._sample_mgr._prepare_sample_view(sample)

    def _reset_event_table_for_loading(self) -> None:
        self._event_mgr._reset_event_table_for_loading()

    def _set_event_table_enabled(self, enabled: bool) -> None:
        self._event_mgr._set_event_table_enabled(enabled)

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
        self._sample_mgr._begin_sample_load_job(sample, token, repo, project_path, load_trace=load_trace, load_events=load_events, load_results=load_results, staging_db_path=staging_db_path)

    def _on_sample_load_finished(
        self,
        token: object,
        sample: SampleN,
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
        analysis_results: dict[str, Any] | None,
    ) -> None:
        self._sample_mgr._on_sample_load_finished(token, sample, trace_df, events_df, analysis_results)

    def _on_sample_load_error(self, token: object, sample: SampleN, message: str) -> None:
        self._sample_mgr._on_sample_load_error(token, sample, message)

    def _render_sample(self, sample: SampleN) -> None:
        self._sample_mgr._render_sample(sample)

    def _update_snapshot_viewer_state(self, sample: SampleN) -> None:
        self._snapshot_mgr._update_snapshot_viewer_state(sample)

    def _ensure_sample_snapshots_loaded(self, sample: SampleN) -> np.ndarray | None:
        return self._snapshot_mgr._ensure_sample_snapshots_loaded(sample)

    def _on_snapshot_load_finished(
        self,
        token: object,
        sample: SampleN,
        stack: np.ndarray | None,
        error: str | None,
    ) -> None:
        self._snapshot_mgr._on_snapshot_load_finished(token, sample, stack, error)

    def open_comparison_window(self) -> None:
        """Open (or raise) the floating dataset comparison window."""
        if not hasattr(self, "_comparison_window") or self._comparison_window is None:
            from vasoanalyzer.ui.comparison_window import ComparisonWindow
            self._comparison_window = ComparisonWindow(self)
        self._comparison_window.show()
        self._comparison_window.raise_()
        self._comparison_window.activateWindow()

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

                splitter = QSplitter(Qt.Orientation.Vertical, self)

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
        global_pos = self.project_tree.viewport().mapToGlobal(pos)

        selected_samples = [
            it.data(0, Qt.ItemDataRole.UserRole)
            for it in self.project_tree.selectedItems()
            if isinstance(it.data(0, Qt.ItemDataRole.UserRole), SampleN)
        ]
        open_act = None
        dual_act = None
        if selected_samples:
            open_act = menu.addAction("Open Selected Datasets…")
            if len(selected_samples) == 2:
                dual_act = menu.addAction("Open Dual View…")

        if item is None:
            add_exp = menu.addAction("Add Experiment")
            action = menu.exec(global_pos)
            if action == add_exp:
                self.add_experiment()
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
            return

        obj = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(obj, Experiment):
            add_n = menu.addAction("Add Sample")
            import_folder = menu.addAction("Import Folder…")
            menu.addSeparator()
            add_sf = menu.addAction("Add Subfolder…")
            menu.addSeparator()
            del_exp = menu.addAction("Delete Experiment")
            action = menu.exec(global_pos)
            if action == add_n:
                self.add_sample(obj)
            elif action == import_folder:
                self._handle_import_folder(target_experiment=obj)
            elif action == add_sf:
                self._add_subfolder_to_experiment(obj)
            elif action == del_exp:
                self.delete_experiment(obj)
            elif action == open_act:
                self.open_samples_in_new_windows(selected_samples)
            elif action == dual_act:
                self.open_samples_in_dual_view(selected_samples)
        elif isinstance(obj, SubfolderRef):
            del_sf = menu.addAction("Delete Subfolder")
            del_sf.setToolTip("Remove subfolder — datasets are moved back to the experiment")
            action = menu.exec(global_pos)
            if action == del_sf:
                self._delete_subfolder(obj)
        elif isinstance(obj, SampleN):
            load_data = menu.addAction("Load Data Into N…")
            save_n = menu.addAction("Save Data As…")
            menu.addSeparator()
            # Subfolder assignment
            _current_sf = getattr(obj, "subfolder", None)
            move_to_sf = menu.addAction(
                "Move to Subfolder…" if not _current_sf else f'Move from "{_current_sf}"…'
            )
            if _current_sf:
                remove_from_sf = menu.addAction("Remove from Subfolder")
            else:
                remove_from_sf = None
            menu.addSeparator()
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
            action = menu.exec(global_pos)
            if action == load_data:
                self.load_data_into_sample(obj)
            elif action == save_n:
                self.save_sample_as(obj)
            elif action == move_to_sf:
                _targets = selected_samples if len(selected_samples) > 1 else [obj]
                self._move_samples_to_subfolder(_targets)
            elif action == remove_from_sf and remove_from_sf is not None:
                _targets = selected_samples if len(selected_samples) > 1 else [obj]
                for s in _targets:
                    s.subfolder = None
                self.refresh_project_tree()
                self.mark_session_dirty()
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
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

    def _add_subfolder_to_experiment(self, experiment: Experiment) -> None:
        """Create a new subfolder in the experiment and start inline rename."""
        base = "New Subfolder"
        name = base
        existing = set(experiment.subfolder_names)
        counter = 1
        while name in existing:
            name = f"{base} {counter}"
            counter += 1
        experiment.subfolder_names.append(name)
        self.refresh_project_tree()
        # Find the new subfolder item and start inline editing
        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            exp_item = tree.topLevelItem(i)
            if exp_item.data(0, Qt.ItemDataRole.UserRole) is experiment:
                for k in range(exp_item.childCount()):
                    child = exp_item.child(k)
                    obj = child.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(obj, SubfolderRef) and obj.name == name:
                        exp_item.setExpanded(True)
                        tree.scrollToItem(child)
                        tree.setCurrentItem(child)
                        tree.editItem(child, 0)
                        return
        self.mark_session_dirty()

    def _delete_subfolder(self, sf_ref: SubfolderRef) -> None:
        """Remove a subfolder and move its samples back to the experiment level."""
        for s in sf_ref.experiment.samples:
            if getattr(s, "subfolder", None) == sf_ref.name:
                s.subfolder = None
        if sf_ref.name in sf_ref.experiment.subfolder_names:
            sf_ref.experiment.subfolder_names.remove(sf_ref.name)
        self.refresh_project_tree()
        self.mark_session_dirty()

    def _move_samples_to_subfolder(self, samples: list[SampleN]) -> None:
        """Prompt for a subfolder name and assign it to the given samples."""
        if not samples:
            return
        # Find the experiment for the first sample to suggest existing subfolders
        experiment = None
        if self.current_project:
            for exp in self.current_project.experiments:
                if samples[0] in exp.samples:
                    experiment = exp
                    break
        existing_sfs = sorted({
            getattr(s, "subfolder", None)
            for s in (experiment.samples if experiment else [])
            if getattr(s, "subfolder", None)
        })
        prompt = "Subfolder name:"
        if existing_sfs:
            prompt += f"\n(Existing: {', '.join(existing_sfs)})"
        name, ok = QInputDialog.getText(self, "Move to Subfolder", prompt)
        name = name.strip()
        if not ok or not name:
            return
        for s in samples:
            s.subfolder = name
        # Ensure the name is registered in the experiment's subfolder_names
        if experiment and name not in experiment.subfolder_names:
            experiment.subfolder_names.append(name)
        self.refresh_project_tree()
        self.mark_session_dirty()

    def add_sample(self, experiment):
        self._sample_mgr.add_sample(experiment)

    def add_sample_to_current_experiment(self, checked: bool = False):
        self._sample_mgr.add_sample_to_current_experiment(checked)

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
        self._sample_mgr.load_data_into_sample(sample)

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
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
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
        if dialog.exec() != QDialog.DialogCode.Accepted:
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
                self, title, msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
            )
            != QMessageBox.StandardButton.Yes
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
                candidate = resource_path("resources", "icons", dark_filename)
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            log.debug("Dark theme icon lookup failed for %s", dark_filename, exc_info=True)

        return resource_path("resources", "icons", filename)

    def _brand_icon_path(self, extension: str) -> str:
        """Return the absolute path to the main VasoAnalyzer app icon."""
        from utils import resource_path

        if not extension:
            return ""

        filename = f"VasoAnalyzerIcon.{extension}"
        search_roots = [
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
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setPen(QColor(0, 0, 0))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return QIcon(pix)

    def sync_slider_with_plot(self, event=None):
        self._plot_mgr.sync_slider_with_plot(event)

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
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        self.action_new.triggered.connect(self.start_new_analysis)
        file_menu.addAction(self.action_new)

        import_menu = file_menu.addMenu("Open Data")

        self.action_open_trace = QAction("Import Trace CSV…", self)
        self.action_open_trace.setShortcut(QKeySequence.StandardKey.Open)
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

        self.action_export_dataset_pkg = QAction("Export Dataset Package…", self)
        self.action_export_dataset_pkg.triggered.connect(self.export_dataset_package_action)
        export_menu.addAction(self.action_export_dataset_pkg)

        export_menu.addSeparator()

        self.action_export_tiff = QAction("High-Res Plot…", self)
        self.action_export_tiff.triggered.connect(self.export_high_res_plot)
        export_menu.addAction(self.action_export_tiff)

        self.action_export_report = QAction("Data Report…", self)
        self.action_export_report.setToolTip(
            "Export a composite figure with trace, event table, and metadata"
        )
        self.action_export_report.triggered.connect(self._export_data_report)
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
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)
        self._assign_menu_role(self.action_exit, "QuitRole")
        file_menu.addAction(self.action_exit)

    def _build_edit_menu(self, menubar):
        edit_menu = menubar.addMenu("&Edit")

        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        edit_menu.addAction(undo)

        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        edit_menu.addAction(redo)

        edit_menu.addSeparator()

        self.action_delete_event = QAction("Delete Event", self)
        self.action_delete_event.setShortcut(QKeySequence.StandardKey.Delete)
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

        self.action_compare_datasets = QAction("Compare Datasets…", self)
        self.action_compare_datasets.setToolTip(
            "Open the comparison window and drag datasets from the project tree to compare them"
        )
        self.action_compare_datasets.triggered.connect(self.open_comparison_window)
        tools_menu.addAction(self.action_compare_datasets)

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
        dialog.exec()

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
                user_choice = dlg.exec()
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
        self._navigation_mgr.reset_to_full_view()

    def _register_trace_nav_shortcuts(self) -> None:
        self._navigation_mgr._register_trace_nav_shortcuts()

    def show_goto_time_dialog(self) -> None:
        self._navigation_mgr.show_goto_time_dialog()

    def _jump_to_start(self) -> None:
        self._navigation_mgr._jump_to_start()

    def _jump_to_end(self) -> None:
        self._navigation_mgr._jump_to_end()

    def _pan_window_fraction(self, fraction: float, direction: int) -> None:
        self._navigation_mgr._pan_window_fraction(fraction, direction)

    def _jump_to_event(self, direction: int) -> None:
        self._navigation_mgr._jump_to_event(direction)

    def _zoom_all_x(self) -> None:
        self._navigation_mgr._zoom_all_x()

    def reset_view(self, checked: bool = False):
        self._navigation_mgr.reset_view(checked)

    def fit_to_data(self, checked: bool = False):
        self._navigation_mgr.fit_to_data(checked)

    def zoom_to_selection(self, checked: bool = False):
        self._navigation_mgr.zoom_to_selection(checked)

    def zoom_out(self, factor: float = 1.5, x_only: bool = True):
        self._navigation_mgr.zoom_out(factor, x_only)

    def fit_x_full(self):
        self._navigation_mgr.fit_x_full()

    def fit_y_in_current_x(self):
        self._navigation_mgr.fit_y_in_current_x()

    def _value_range(self, values: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
        return self._navigation_mgr._value_range(values, mask)

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
        self._event_mgr._refresh_event_annotation_artists()

    def _apply_current_style(self, *, redraw: bool = False) -> None:
        self._plot_mgr._apply_current_style(redraw=redraw)

    def _on_event_rows_changed(self) -> None:
        self._event_mgr._on_event_rows_changed()
        self._update_event_count_label()

    def _update_event_count_label(self) -> None:
        label = getattr(self, "event_count_label", None)
        if label is None:
            return
        ctrl = getattr(self, "event_table_controller", None)
        count = len(ctrl.rows) if ctrl is not None else 0
        label.setText(f"{count} event{'s' if count != 1 else ''}" if count else "")

    def _ensure_event_meta_length(self, length: int | None = None) -> None:
        self._event_mgr._ensure_event_meta_length(length)

    def _normalize_event_label_meta(self, length: int | None = None) -> None:
        self._event_mgr._normalize_event_label_meta(length)

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
        return self._event_mgr._current_review_states()

    def _review_notice_key(self) -> tuple:
        return self._event_mgr._review_notice_key()

    def _configure_review_notice_banner(self) -> None:
        self._event_mgr._configure_review_notice_banner()

    def _dismiss_review_notice(self) -> None:
        self._event_mgr._dismiss_review_notice()

    def _update_review_notice_visibility(self) -> None:
        self._event_mgr._update_review_notice_visibility()

    def _set_review_state_for_row(self, index: int, state: str) -> None:
        self._event_mgr._set_review_state_for_row(index, state)

    def _mark_row_edited(self, index: int) -> None:
        self._set_review_state_for_row(index, REVIEW_EDITED)
        controller = getattr(self, "event_table_controller", None)
        if controller is not None:
            controller.set_review_states(self._current_review_states())

    def _sample_values_at_time(
        self, time_sec: float
    ) -> tuple[float | None, float | None, float | None, float | None]:
        return self._sample_mgr._sample_values_at_time(time_sec)

    def _insert_event_meta(self, index: int, meta: dict[str, Any] | None = None) -> None:
        self._event_mgr._insert_event_meta(index, meta)

    def _delete_event_meta(self, index: int) -> None:
        self._event_mgr._delete_event_meta(index)

    def _fallback_restore_review_states(self, event_count: int) -> None:
        self._event_mgr._fallback_restore_review_states(event_count)

    def _sync_event_data_from_table(self) -> None:
        self._event_mgr._sync_event_data_from_table()

    def _apply_event_rows_to_current_sample(self, rows: list[tuple]) -> None:
        self._event_mgr._apply_event_rows_to_current_sample(rows)

    def apply_event_label_overrides(
        self,
        labels: Sequence[str],
        metadata: Sequence[Mapping[str, Any]],
    ) -> None:
        self._event_mgr.apply_event_label_overrides(labels, metadata)

    def _set_event_table_visible(self, visible: bool, *, source: str = "user") -> None:
        self._event_mgr._set_event_table_visible(visible, source=source)

    def toggle_event_table(self, checked: bool):
        self._event_mgr.toggle_event_table(checked)

    def _apply_snapshot_view_mode(self, should_show: bool) -> None:
        self._snapshot_mgr._apply_snapshot_view_mode(should_show)

    def _snapshot_has_image(self) -> bool:
        return self._snapshot_mgr._snapshot_has_image()

    def _update_snapshot_panel_layout(self) -> None:
        self._snapshot_mgr._update_snapshot_panel_layout()

    def _update_snapshot_rotation_controls(self) -> None:
        self._snapshot_mgr._update_snapshot_rotation_controls()

    def toggle_snapshot_viewer(self, checked: bool, *, source: str = "user"):
        self._snapshot_mgr.toggle_snapshot_viewer(checked, source=source)

    def _outer_channel_available(self) -> bool:
        return self._plot_mgr._outer_channel_available()

    def _avg_pressure_channel_available(self) -> bool:
        return self._plot_mgr._avg_pressure_channel_available()

    def _set_pressure_channel_available(self) -> bool:
        return self._plot_mgr._set_pressure_channel_available()

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
        return self._plot_mgr._current_channel_presence()

    def _ensure_valid_channel_selection(
        self,
        inner_on: bool,
        outer_on: bool,
        *,
        toggled: str,
        outer_supported: bool,
    ) -> tuple[bool, bool]:
        return self._plot_mgr._ensure_valid_channel_selection(inner_on, outer_on, toggled=toggled, outer_supported=outer_supported)

    def _apply_toggle_state(
        self,
        inner_on: bool,
        outer_on: bool,
        *,
        outer_supported: bool | None = None,
        avg_pressure_supported: bool | None = None,
        set_pressure_supported: bool | None = None,
    ) -> None:
        if outer_supported is None:
            outer_supported = self._outer_channel_available()
        if avg_pressure_supported is None:
            avg_pressure_supported = self._avg_pressure_channel_available()
        if set_pressure_supported is None:
            set_pressure_supported = self._set_pressure_channel_available()
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
        if self.avg_pressure_toggle_act is not None:
            self.avg_pressure_toggle_act.setEnabled(avg_pressure_supported)
            if not avg_pressure_supported and self.avg_pressure_toggle_act.isChecked():
                self.avg_pressure_toggle_act.blockSignals(True)
                self.avg_pressure_toggle_act.setChecked(False)
                self.avg_pressure_toggle_act.blockSignals(False)
        if self.set_pressure_toggle_act is not None:
            self.set_pressure_toggle_act.setEnabled(set_pressure_supported)
            if not set_pressure_supported and self.set_pressure_toggle_act.isChecked():
                self.set_pressure_toggle_act.blockSignals(True)
                self.set_pressure_toggle_act.setChecked(False)
                self.set_pressure_toggle_act.blockSignals(False)

    def _reset_channel_view_defaults(self) -> None:
        self._plot_mgr._reset_channel_view_defaults()

    def _rebuild_channel_layout(
        self, inner_on: bool, outer_on: bool, *, redraw: bool = True
    ) -> None:
        self._plot_mgr._rebuild_channel_layout(inner_on, outer_on, redraw=redraw)

    def _apply_channel_toggle(self, channel: str, checked: bool) -> None:
        self._plot_mgr._apply_channel_toggle(channel, checked)

    def toggle_inner_diameter(self, checked: bool):
        self._apply_channel_toggle("inner", checked)

    def toggle_outer_diameter(self, checked: bool):
        self._apply_channel_toggle("outer", checked)

    def toggle_avg_pressure(self, checked: bool):
        self._apply_channel_toggle("avg_pressure", checked)

    def toggle_set_pressure(self, checked: bool):
        self._apply_channel_toggle("set_pressure", checked)

    def _apply_channel_toggle_pyqtgraph(self, channel: str, checked: bool) -> None:
        self._plot_mgr._apply_channel_toggle_pyqtgraph(channel, checked)

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
        dialog.exec()

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
        dont_show = dlg.exec()
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
            dont_show = dlg.exec()
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
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            dlg.finished.connect(lambda _: self._handle_welcome_guide_closed(dlg))
            dlg.exec()
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
        self._event_mgr.delete_selected_events(checked, indices=indices)

    def _delete_events_by_indices(self, indices: list[int]) -> None:
        self._event_mgr._delete_events_by_indices(indices)

    def _update_theme_action_checks(self, mode: str) -> None:
        self._theme_mgr._update_theme_action_checks(mode)

    def _update_action_icons(self) -> None:
        self._theme_mgr._update_action_icons()

    def apply_theme(self, mode: str, *, persist: bool = False) -> None:
        self._theme_mgr.apply_theme(mode, persist=persist)

    # View Menu Actions
    def set_color_scheme(self, scheme: str):
        self._theme_mgr.set_color_scheme(scheme)

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
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        self.home_action = QAction(QIcon(self.icon_path("Home.svg")), "Home", self)
        self.home_action.setToolTip("Home Dashboard")
        self.home_action.triggered.connect(self.show_home_dashboard)
        self.home_action.setVisible(False)
        toolbar.addAction(self.home_action)
        home_btn = toolbar.widgetForAction(self.home_action)
        if isinstance(home_btn, QToolButton):
            home_btn.setObjectName("HomeButton")

        self.load_trace_action = QAction(
            QIcon(self.icon_path("folder-open.svg")), "Import Trace CSV…", self
        )
        self.load_trace_action.setToolTip("Import a CSV trace file and auto-detect matching events")
        self.load_trace_action.setShortcut(QKeySequence.StandardKey.Open)
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
        import_button.setText("Open Data")
        import_button.setToolTip("Open Data")
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
        import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.save_session_action = QAction(QIcon(self.icon_path("Save.svg")), "Save Project", self)
        self.save_session_action.setToolTip("Save Project")
        self.save_session_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_session_action.triggered.connect(self.save_project_file)

        self.welcome_action = QAction(
            QIcon(self.icon_path("info-circle.svg")), "Welcome guide", self
        )
        self.welcome_action.setToolTip("Open the welcome guide")
        self.welcome_action.triggered.connect(lambda: self.show_welcome_guide(modal=False))

        toolbar.addWidget(import_button)
        toolbar.addAction(self.save_session_action)
        save_btn = toolbar.widgetForAction(self.save_session_action)
        if isinstance(save_btn, QToolButton):
            save_btn.setObjectName("SaveProjectButton")
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

        toolbar.setStyleSheet(self._primary_toolbar_css())
        return toolbar

    def _update_toolbar_compact_mode(self, width: int | None = None) -> None:
        if width is None:
            width = self.width()
        compact = width < 1152
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        for toolbar in (
            getattr(self, "primary_toolbar", None),
            getattr(self, "toolbar", None),
        ):
            if toolbar is None:
                continue
            toolbar.setToolButtonStyle(style)
        self._update_primary_toolbar_button_widths(compact)
        self._normalize_plot_toolbar_group_widths(compact)
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
        return self._plot_mgr._plot_toolbar_signal_buttons()

    def _plot_toolbar_row2_buttons(self) -> list[QToolButton]:
        return self._plot_mgr._plot_toolbar_row2_buttons()

    def _normalize_plot_toolbar_button_geometry(self) -> None:
        self._plot_mgr._normalize_plot_toolbar_button_geometry()

    def _lock_plot_toolbar_row2_order(self) -> None:
        self._plot_mgr._lock_plot_toolbar_row2_order()

    def _update_plot_toolbar_signal_button_widths(self, compact: bool) -> None:
        self._plot_mgr._update_plot_toolbar_signal_button_widths(compact)

    def _normalize_plot_toolbar_group_widths(self, compact: bool) -> None:
        self._plot_mgr._normalize_plot_toolbar_group_widths(compact)

    def _update_primary_toolbar_button_widths(self, compact: bool) -> None:
        buttons = self._primary_toolbar_buttons()
        if not buttons:
            return

        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
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
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            button.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_toolbar_compact_mode(event.size().width())

    def _set_plot_drag_state(self, active: bool) -> None:
        self._plot_drag_in_progress = bool(active)

    def _refresh_zoom_window(self) -> None:
        self._plot_mgr._refresh_zoom_window()

    def _on_zoom_visibility_changed(self, visible: bool) -> None:
        if visible:
            self._refresh_zoom_window()

    def _on_scope_visibility_changed(self, visible: bool) -> None:
        if visible and self.scope_dock and self.trace_model is not None:
            self.scope_dock.set_trace_model(self.trace_model)

    def _serialize_plot_layout(self) -> dict | None:
        return self._plot_mgr._serialize_plot_layout()

    def _apply_pending_plot_layout(self) -> None:
        self._plot_mgr._apply_pending_plot_layout()

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
        container.setFrameShape(QFrame.Shape.StyledPanel)
        container.setFrameShadow(QFrame.Shadow.Raised)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        label = QLabel("Next step: Add data to this project", container)
        label.setObjectName("NextStepHintLabel")

        btn_import_folder = QPushButton("Import folder…", container)
        btn_import_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import_folder.clicked.connect(self._handle_import_folder)

        btn_import_trace = QPushButton("Import trace/events file…", container)
        btn_import_trace.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import_trace.clicked.connect(self._handle_load_trace)

        dismiss_btn = QToolButton(container)
        dismiss_btn.setText("Dismiss")
        dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss_btn.setAutoRaise(True)
        dismiss_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
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
        from PyQt6.QtCore import QTimer

        action = getattr(self, "load_trace_action", None)
        if action is not None:
            QTimer.singleShot(0, action.trigger)
        else:
            QTimer.singleShot(0, self._handle_load_trace)

    def home_open_project(self) -> None:
        from PyQt6.QtCore import QTimer

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

        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

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
        button.setCursor(Qt.CursorShape.PointingHandCursor)
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

    def _primary_toolbar_css(self) -> str:
        bg = CURRENT_THEME.get("toolbar_bg", CURRENT_THEME.get("window_bg", "#FFFFFF"))
        border_color = CURRENT_THEME.get("panel_border", CURRENT_THEME["grid_color"])
        separator_color = CURRENT_THEME.get("grid_color", border_color)
        button_bg = CURRENT_THEME.get("button_bg", bg)
        hover_bg = CURRENT_THEME.get("button_hover_bg", CURRENT_THEME.get("selection_bg", bg))
        pressed_bg = CURRENT_THEME.get("button_active_bg", hover_bg)
        text_color = CURRENT_THEME["text"]
        disabled_text = CURRENT_THEME.get("text_disabled", text_color)
        radius = int(CURRENT_THEME.get("panel_radius", 6))
        chevron_path = self.icon_path("chevron-down.svg").replace("\\", "/")
        return f"""
QToolBar#PrimaryToolbar {{
    background: {bg};
    border: none;
    spacing: 2px;
    padding: 2px 4px;
}}
QToolBar#PrimaryToolbar::separator {{
    background: {border_color};
    width: 2px;
    border-radius: 1px;
    margin: 3px 8px;
}}
QToolBar#PrimaryToolbar QToolButton {{
    background: {button_bg};
    border: 1px solid {border_color};
    border-radius: {radius}px;
    padding: 2px 10px 6px 10px;
    color: {text_color};
    min-width: 52px;
}}
QToolBar#PrimaryToolbar QToolButton:hover {{
    background: {hover_bg};
}}
QToolBar#PrimaryToolbar QToolButton:pressed {{
    background: {pressed_bg};
}}
QToolBar#PrimaryToolbar QToolButton:disabled {{
    background: {bg};
    border-color: {separator_color};
    color: {disabled_text};
}}
QToolBar#PrimaryToolbar QToolButton#HomeButton,
QToolBar#PrimaryToolbar QToolButton#ImportDataButton,
QToolBar#PrimaryToolbar QToolButton#SaveProjectButton {{
    font-weight: 600;
}}
QToolBar#PrimaryToolbar QToolButton::menu-indicator {{
    width: 0;
    height: 0;
    image: none;
}}
QToolBar#PrimaryToolbar QToolButton#ImportDataButton::menu-indicator {{
    image: url("{chevron_path}");
    subcontrol-position: bottom center;
    subcontrol-origin: padding;
    bottom: 1px;
    width: 10px;
    height: 6px;
}}
"""

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
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        def _row_click(event):
            if event.button() == Qt.MouseButton.LeftButton:
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
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        remove_btn.setText("Remove")
        remove_btn.setToolTip(f"Remove {path}")
        remove_btn.clicked.connect(lambda _checked=False: remove_callback())
        row_layout.addWidget(remove_btn, 0, Qt.AlignmentFlag.AlignRight)

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
            display = metrics.elidedText(full_text, Qt.TextElideMode.ElideMiddle, self.trace_file_label.width())
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
        """Show an animated progress bar. The bar crawls smoothly toward ~85% while work runs."""
        self._progress_animator.start(message)
        if message:
            self.statusBar().showMessage(message)

    def update_progress(self, value: int) -> None:
        """No-op: the animator owns the visual value. Use show_progress/hide_progress."""

    def hide_progress(self) -> None:
        """Snap bar to 100% and auto-hide after a short pause."""
        self._progress_animator.finish()

    def _start_sample_load_progress(self, sample_name: str) -> None:
        self._sample_mgr._start_sample_load_progress(sample_name)

    def _update_sample_load_progress(self, percent: int, label: str) -> None:
        self._sample_mgr._update_sample_load_progress(percent, label)

    def _finish_sample_load_progress(self) -> None:
        self._sample_mgr._finish_sample_load_progress()

    # ------------------------------------------------------------------ trace editing helpers
    def _prepare_trace_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._plot_mgr._prepare_trace_dataframe(df)

    def _update_trace_sync_state(self) -> None:
        self._plot_mgr._update_trace_sync_state()

    def _refresh_tiff_page_times(self, *, expected_page_count: int | None = None) -> None:
        self._plot_mgr._refresh_tiff_page_times(expected_page_count=expected_page_count)

    def _get_trace_model_for_sample(self, sample: SampleN | None) -> TraceModel:
        return self._sample_mgr._get_trace_model_for_sample(sample)

    def _sync_trace_dataframe_from_model(self) -> None:
        self._plot_mgr._sync_trace_dataframe_from_model()

    def _refresh_views_after_edit(self) -> None:
        self._plot_mgr._refresh_views_after_edit()

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
        menu.exec(QCursor.pos())

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
        if dialog.exec() != QDialog.DialogCode.Accepted:
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
        return self._plot_mgr._channel_has_data_in_window(channel, window)

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
        self._plot_mgr._set_plot_cursor_for_mode(mode)

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
        self._plot_mgr._sync_autoscale_y_action_from_host()

    def _ensure_event_label_actions(self) -> None:
        return self._event_mgr._ensure_event_label_actions()

    def _sync_grid_action(self) -> None:
        self._plot_mgr._sync_grid_action()

    def _on_event_lines_toggled(self, checked: bool) -> None:
        self._event_mgr._on_event_lines_toggled(checked)

    def _on_event_label_mode_auto(self, checked: bool) -> None:
        self._event_mgr._on_event_label_mode_auto(checked)

    def _on_event_label_mode_all(self, checked: bool) -> None:
        self._event_mgr._on_event_label_mode_all(checked)

    def _set_event_label_mode(self, mode: str) -> None:
        self._event_mgr._set_event_label_mode(mode)

    def _apply_event_label_mode(self, mode: str | None = None) -> None:
        self._event_mgr._apply_event_label_mode(mode)

    def _sync_event_controls(self) -> None:
        self._event_mgr._sync_event_controls()

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
        self._plot_mgr._update_trace_controls_state()

    def _sync_track_visibility_from_host(self) -> None:
        self._plot_mgr._sync_track_visibility_from_host()

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
        chosen = menu.exec(widget.mapToGlobal(pos))
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
        # Always move to front (most-recently-used ordering)
        filtered = [p for p in self.recent_files if p != primary_trace_path]
        self.recent_files = [primary_trace_path] + filtered[:9]
        self.settings.setValue("recentFiles", self.recent_files)
        self.update_recent_files_menu()

        # 4) Helper already populated events & UI

        # 5) Ask if they want to load a TIFF
        if tiff_path is None:
            resp = QMessageBox.question(
                self,
                "Load TIFF?",
                "Would you like to load a Result TIFF file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp == QMessageBox.StandardButton.Yes:
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
        return self._event_mgr._load_events_from_path(file_path)

    def _event_table_signal_availability(self) -> tuple[bool, bool, bool]:
        return self._event_mgr._event_table_signal_availability()

    def _event_table_review_mode_active(self) -> bool:
        return self._event_mgr._event_table_review_mode_active()

    def _apply_event_table_column_contract(self) -> None:
        self._event_mgr._apply_event_table_column_contract()

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
        self._event_mgr._launch_event_review_wizard()

    def _apply_event_review_changes(self) -> None:
        self._event_mgr._apply_event_review_changes()

    def _cleanup_event_review_wizard(self, *args) -> None:
        self._event_mgr._cleanup_event_review_wizard(*args)

    def _update_event_table_presence_state(self, has_events: bool) -> None:
        self._event_mgr._update_event_table_presence_state(has_events)

    def _reset_snapshot_loading_info(self) -> None:
        self._snapshot_mgr._reset_snapshot_loading_info()

    @staticmethod
    def _format_stride_label(stride: int) -> str:
        """Return a human-friendly label like 'every 3rd'."""

        suffix = "th"
        if stride % 100 not in {11, 12, 13}:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(stride % 10, "th")
        return f"every {stride}{suffix}"

    def _probe_tiff_frame_count(self, file_path: str) -> int | None:
        return self._snapshot_mgr._probe_tiff_frame_count(file_path)

    def _prompt_tiff_load_strategy(self, total_frames: int) -> tuple[str, int | None]:
        return self._snapshot_mgr._prompt_tiff_load_strategy(total_frames)

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
        return self._snapshot_mgr._derive_frame_trace_time(n_frames)

    def _load_snapshot_from_path(self, file_path: str) -> bool:
        return self._snapshot_mgr._load_snapshot_from_path(file_path)

    def load_snapshot(self, checked: bool = False):
        self._snapshot_mgr.load_snapshot(checked)

    def save_analysis(self):
        self._snapshot_mgr.save_analysis()

    def open_analysis(self, path=None):
        self._snapshot_mgr.open_analysis(path)

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
        self._event_mgr.load_events(labels, diam_before, od_before)

    def _trace_time_for_frame_number(self, frame: int | float | None) -> float | None:
        return self._snapshot_mgr._trace_time_for_frame_number(frame)

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
        self._snapshot_mgr._set_snapshot_data_source(stack, frame_times)

    def load_snapshots(self, stack):
        self._snapshot_mgr.load_snapshots(stack)

    def compute_frame_trace_indices(self):
        self._snapshot_mgr.compute_frame_trace_indices()

    def _time_for_frame(self, idx: int) -> float | None:
        return self._snapshot_mgr._time_for_frame(idx)

    def _frame_index_for_time_canonical(self, time_value: float) -> int | None:
        return self._snapshot_mgr._frame_index_for_time_canonical(time_value)

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
        self._snapshot_mgr.jump_to_time(t, from_event=from_event, from_playback=from_playback, from_frame_change=from_frame_change, source=source, snap_to_trace=snap_to_trace)

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
        self._snapshot_mgr.set_current_frame(idx, from_jump=from_jump, from_playback=from_playback)

    def update_snapshot_size(self):
        self._snapshot_mgr.update_snapshot_size()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if (
            event.key() == Qt.Key.Key_Space
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
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and self._space_pan_active:
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
        if event_table is not None and source is event_table and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.update_snapshot_size)
        elif source is self.trace_file_label and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._update_status_chip)
        return super().eventFilter(source, event)

    def _update_snapshot_sampling_badge(self) -> None:
        self._snapshot_mgr._update_snapshot_sampling_badge()

    def _tiff_page_for_frame(self, frame_idx: int) -> int | None:
        return self._snapshot_mgr._tiff_page_for_frame(frame_idx)

    def _trace_time_exact_for_page(self, tiff_page: int | None) -> float | None:
        return self._snapshot_mgr._trace_time_exact_for_page(tiff_page)

    def _apply_frame_change(self, idx: int, *, from_playback: bool = False):
        self._snapshot_mgr._apply_frame_change(idx, from_playback=from_playback)

    def _update_snapshot_status(self, idx: int) -> None:
        self._snapshot_mgr._update_snapshot_status(idx)

    def _update_metadata_display(self, idx: int) -> None:
        self._snapshot_mgr._update_metadata_display(idx)

    def _snapshot_view_visible(self) -> bool:
        return self._snapshot_mgr._snapshot_view_visible()

    def _update_metadata_button_state(self) -> None:
        self._snapshot_mgr._update_metadata_button_state()

    def on_snapshot_speed_changed(self, value: float) -> None:
        self._snapshot_mgr.on_snapshot_speed_changed(value)

    def on_snapshot_sync_toggled(self, checked: bool) -> None:
        self._snapshot_mgr.on_snapshot_sync_toggled(checked)

    def on_snapshot_loop_toggled(self, checked: bool) -> None:
        self._snapshot_mgr.on_snapshot_loop_toggled(checked)

    def _reset_snapshot_speed(self) -> None:
        self._snapshot_mgr._reset_snapshot_speed()

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
        self._snapshot_mgr._sync_time_cursor_to_snapshot()

    # Playback controller lives in the TIFF viewer v2 widget.
    def _update_playback_button_state(self, playing: bool) -> None:
        self._snapshot_mgr._update_playback_button_state(playing)

    def _set_playback_state(self, playing: bool) -> None:
        self._snapshot_mgr._set_playback_state(playing)

    def _on_snapshot_page_changed_v2(self, page_index: int, source: str) -> None:
        self._snapshot_mgr._on_snapshot_page_changed_v2(page_index, source)

    def _on_snapshot_playback_time_changed(self, trace_time: float) -> None:
        self._snapshot_mgr._on_snapshot_playback_time_changed(trace_time)

    def _on_snapshot_playing_changed(self, playing: bool) -> None:
        self._snapshot_mgr._on_snapshot_playing_changed(playing)

    def toggle_snapshot_playback(self, checked: bool) -> None:
        self._snapshot_mgr.toggle_snapshot_playback(checked)

    def _mapped_trace_time_for_page(self, page_index: int) -> float | None:
        return self._snapshot_mgr._mapped_trace_time_for_page(page_index)

    def _sync_trace_cursor_to_time(self, trace_time: float) -> None:
        self._snapshot_mgr._sync_trace_cursor_to_time(trace_time)

    def step_previous_frame(self) -> None:
        self._snapshot_mgr.step_previous_frame()

    def step_next_frame(self) -> None:
        self._snapshot_mgr.step_next_frame()

    def rotate_snapshot_ccw(self) -> None:
        self._snapshot_mgr.rotate_snapshot_ccw()

    def rotate_snapshot_cw(self) -> None:
        self._snapshot_mgr.rotate_snapshot_cw()

    def reset_snapshot_rotation(self) -> None:
        self._snapshot_mgr.reset_snapshot_rotation()

    def set_snapshot_metadata_visible(self, visible: bool) -> None:
        self._snapshot_mgr.set_snapshot_metadata_visible(visible)

    def _clear_slider_markers(self) -> None:
        self._snapshot_mgr._clear_slider_markers()

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
        self._plot_mgr.update_slider_marker()

    def populate_event_table_from_df(self, df):
        self._event_mgr.populate_event_table_from_df(df)

    def update_event_label_positions(self, event=None):
        self._event_mgr.update_event_label_positions(event)

    def _init_hover_artists(self) -> None:
        return self._plot_mgr._init_hover_artists()

    def _hide_hover_feedback(self) -> None:
        self._plot_mgr._hide_hover_feedback()

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
        merge_btn = box.addButton("Merge into one trace", QMessageBox.ButtonRole.AcceptRole)
        single_btn = box.addButton("Load first only", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(merge_btn)
        box.exec()
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
                if dlg.exec() != QDialog.DialogCode.Accepted:
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
        self._event_mgr._handle_load_events()

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
        self._plot_mgr._reset_time_scrollbar_to_start()

    def _force_trace_start_view(self, window: tuple[float, float]) -> None:
        self._plot_mgr._force_trace_start_view(window)

    # [E] ========================= PLOTTING AND EVENT SYNC ============================
    def update_plot(self, track_limits: bool = True):
        self._plot_mgr.update_plot(track_limits)

    def _refresh_plot_legend(self):
        self._plot_mgr._refresh_plot_legend()
        # Canvas draw is handled by caller - no need to draw here

    def apply_legend_settings(self, settings=None, *, mark_dirty: bool = False) -> None:
        self._plot_mgr.apply_legend_settings(settings, mark_dirty=mark_dirty)

    def open_legend_settings_dialog(self):
        self._plot_mgr.open_legend_settings_dialog()

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
        self._plot_mgr._on_trace_nav_window_requested(x0, x1)

    def _trace_full_range(self) -> tuple[float, float] | None:
        return self._plot_mgr._trace_full_range()

    def _set_trace_navigation_visible(self, visible: bool) -> None:
        self._plot_mgr._set_trace_navigation_visible(visible)

    def _apply_overview_strip_visibility(self) -> None:
        self._plot_mgr._apply_overview_strip_visibility()

    def toggle_overview_strip(self, checked: bool) -> None:
        self._plot_mgr.toggle_overview_strip(checked)

    def toggle_channel_event_labels(self, checked: bool) -> None:
        self._event_mgr.toggle_channel_event_labels(checked)

    def set_channel_event_label_font_size(self, size_pt: float) -> None:
        self._event_mgr.set_channel_event_label_font_size(size_pt)

    def _overview_event_times(self) -> list[float]:
        return self._event_mgr._overview_event_times()

    def _refresh_overview_events(self) -> None:
        self._event_mgr._refresh_overview_events()

    def _refresh_trace_navigation_data(self) -> None:
        self._plot_mgr._refresh_trace_navigation_data()

    def _plot_host_is_pyqtgraph(self) -> bool:
        return self._plot_mgr._plot_host_is_pyqtgraph()

    def _attach_plot_host_window_listener(self) -> None:
        self._plot_mgr._attach_plot_host_window_listener()

    def _on_plot_host_time_window_changed(self, x0: float, x1: float) -> None:
        self._plot_mgr._on_plot_host_time_window_changed(x0, x1)

    def _collect_plot_view_state(self) -> dict[str, Any]:
        return self._plot_mgr._collect_plot_view_state()

    def _apply_pyqtgraph_track_state(self, track_state: dict | None) -> None:
        self._plot_mgr._apply_pyqtgraph_track_state(track_state)

    def _apply_pending_pyqtgraph_track_state(self) -> None:
        self._plot_mgr._apply_pending_pyqtgraph_track_state()

    def _sync_time_window_from_axes(self) -> None:
        self._plot_mgr._sync_time_window_from_axes()

    def _unbind_primary_axis_callbacks(self) -> None:
        self._plot_mgr._unbind_primary_axis_callbacks()

    def _bind_primary_axis_callbacks(self) -> None:
        self._plot_mgr._bind_primary_axis_callbacks()

    def _handle_axis_xlim_changed(self, ax) -> None:
        self._plot_mgr._handle_axis_xlim_changed(ax)

    def scroll_plot(self) -> None:
        self._plot_mgr.scroll_plot()

    def scroll_plot_user(self, value: int, *, source: str | None = None) -> None:
        self._plot_mgr.scroll_plot_user(value, source=source)

    # [F] ========================= EVENT TABLE MANAGEMENT ================================

    def handle_table_edit(self, row: int, new_val: float, old_val: float):
        self._event_mgr.handle_table_edit(row, new_val, old_val)

    def handle_event_label_edit(self, row: int, new_label: str, old_label: str) -> None:
        self._event_mgr.handle_event_label_edit(row, new_label, old_label)

    def _selected_event_rows(self) -> list[int]:
        return self._event_mgr._selected_event_rows()

    def _on_event_table_selection_changed(self, *_args) -> None:
        self._event_mgr._on_event_table_selection_changed(*_args)

    def _warn_event_sync(self, message: str) -> None:
        self._event_mgr._warn_event_sync(message)

    def _event_time_in_range(self, event_time: float) -> bool:
        return self._event_mgr._event_time_in_range(event_time)

    def table_row_clicked(self, row, col):
        self._focus_event_row(row, source="table")

    def _focus_event_row(self, row: int, *, source: str) -> None:
        self._event_mgr._focus_event_row(row, source=source)

    def _highlight_selected_event(self, event_time: float) -> None:
        self._event_mgr._highlight_selected_event(event_time)

    def _clear_event_highlight(self) -> None:
        self._event_mgr._clear_event_highlight()

    def _on_event_highlight_tick(self) -> None:
        self._event_mgr._on_event_highlight_tick()

    def _frame_index_from_event_row(self, row: int) -> int | None:
        return self._event_mgr._frame_index_from_event_row(row)

    def _frame_index_for_time(self, time_value: float) -> int | None:
        return self._frame_index_for_time_canonical(time_value)

    def _nearest_event_index(self, time_value: float) -> int | None:
        return self._event_mgr._nearest_event_index(time_value)

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

                    action = menu.exec(self.canvas.mapToGlobal(event.guiEvent.pos()))
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
        if wizard is not None and wizard.isVisible() and (button == 1 or button == Qt.MouseButton.LeftButton):
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
                action = menu.exec(QCursor.pos())
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
                action = menu.exec(QCursor.pos())

                if action == add_pin_action:
                    self._add_pyqtgraph_pin(track_id, x, y, tr_type)
                    self.mark_session_dirty()
                    return
                if action == add_event_action:
                    self.quick_add_event_at_trace_point(x, y, tr_type)
                    return

    def handle_event_replacement(self, x, y):
        self._event_mgr.handle_event_replacement(x, y)

    def quick_add_event_at_trace_point(self, x: float, y: float, trace_type: str = "inner") -> None:
        return self._event_mgr.quick_add_event_at_trace_point(x, y, trace_type)

    def prompt_add_event(self, x, y, trace_type="inner"):
        self._event_mgr.prompt_add_event(x, y, trace_type)

    def manual_add_event(self):
        self._event_mgr.manual_add_event()

    # [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
    def update_hover_label(self, event):
        self._plot_mgr.update_hover_label(event)

    # [I] ========================= ZOOM + SLIDER LOGIC ================================
    def on_mouse_release(self, event):
        self.update_event_label_positions(event)

        # Deselect zoom after box zoom
        if self.toolbar.mode == "zoom":
            self.toolbar.zoom()  # toggles off
            self.toolbar.mode = ""
            self.toolbar._active = None
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

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
        self._plot_mgr.update_scroll_slider()

    def _on_scrollbar_pressed(self) -> None:
        self._plot_mgr._on_scrollbar_pressed()

    def _on_scrollbar_released(self) -> None:
        self._plot_mgr._on_scrollbar_released()

    def _on_scrollbar_value_changed(self, value: int) -> None:
        self._plot_mgr._on_scrollbar_value_changed(value)

    def _on_scrollbar_moved(self, value: int) -> None:
        self._plot_mgr._on_scrollbar_moved(value)

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
        dialog.exec()

    def _export_data_report(self) -> None:
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
        if dlg.exec() != QDialog.DialogCode.Accepted:
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
        dialog.exec()

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
        dialog.exec()

    def _update_gif_animator_state(self) -> None:
        self._export_mgr._update_gif_animator_state()

    def show_gif_animator(self, checked: bool = False) -> None:
        self._export_mgr.show_gif_animator(checked)

    def open_sync_clip_exporter(self, checked: bool = False) -> None:
        self._export_mgr.open_sync_clip_exporter(checked)

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
        return self._plot_mgr._get_selected_range_from_plot_host()

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
        return self._plot_mgr._visible_channels_from_toggles()

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
        self._plot_mgr.apply_plot_style(style, persist, draw)

    def _x_axis_for_style(self):
        return self._plot_mgr._x_axis_for_style()

    def _set_shared_xlabel(self, text: str):
        self._shared_xlabel = text
        plot_host = getattr(self, "plot_host", None)
        if plot_host is None:
            if self.ax is not None:
                self.ax.set_xlabel(text)
            return
        plot_host.set_shared_xlabel(text)

    def _ensure_style_manager(self) -> PlotStyleManager:
        return self._plot_mgr._ensure_style_manager()

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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
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
        self._plot_mgr._clear_canvas_and_table()

    def show_event_table_context_menu(self, position):
        return self._event_mgr.show_event_table_context_menu(position)

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
        return self._plot_mgr.get_current_plot_style()

    def sample_inner_diameter(self, time_value: float) -> float | None:
        return self._sample_mgr.sample_inner_diameter(time_value)

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
        empty_state_layout.addWidget(self.plot_empty_state, 0, Qt.AlignmentFlag.AlignHCenter)
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
            self.snapshot_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            snapshot_box = QVBoxLayout(self.snapshot_card)
            snapshot_box.setContentsMargins(0, 0, 0, 0)
            snapshot_box.setSpacing(0)
            self.snapshot_stack = QStackedWidget(self.snapshot_card)
            self.snapshot_stack.setObjectName("SnapshotStack")
            self.snapshot_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.snapshot_stack.setMinimumHeight(160)
            if self.snapshot_widget is not None:
                self.snapshot_stack.addWidget(self.snapshot_widget)
            snapshot_box.addWidget(self.snapshot_stack, 1)
            snapshot_box.addWidget(self.metadata_panel)
            right_panel_layout.addWidget(self.snapshot_card)
        self.event_table_card = QFrame()
        self.event_table_card.setObjectName("TableCard")
        self.event_table_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table_layout = QVBoxLayout(self.event_table_card)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
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
        self.event_count_label = QLabel("", self.event_table_card)
        self.event_count_label.setObjectName("EventCountLabel")
        self.event_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table_layout.addWidget(self.event_count_label)
        right_panel_layout.addWidget(self.event_table_card, 1)
        # Snapshot card uses Preferred policy (aspect-ratio-aware); event table expands.
        if self.snapshot_card is not None:
            right_panel_layout.setStretch(0, 0)
            right_panel_layout.setStretch(1, 1)
        self._update_snapshot_panel_layout()
        self._update_review_notice_visibility()

        splitter = QSplitter(Qt.Orientation.Horizontal)
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
            stretch_factors = "unavailable"
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
        self._plot_mgr._configure_plot_empty_state_actions()

    def _update_plot_empty_state(self) -> None:
        self._plot_mgr._update_plot_empty_state()

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
        self._theme_mgr._apply_event_table_card_theme()

    def _apply_snapshot_theme(self) -> None:
        self._theme_mgr._apply_snapshot_theme()

    def _update_snapshot_sync_label(self, mode: str) -> None:
        mode_key = (mode or "").lower()
        self._snapshot_sync_mode = mode_key
        self._refresh_snapshot_sync_label()

    def _set_snapshot_sync_time(self, time_value: float | None) -> None:
        self._snapshot_mgr._set_snapshot_sync_time(time_value)

    def _refresh_snapshot_sync_label(self) -> None:
        self._snapshot_mgr._refresh_snapshot_sync_label()

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
        self._theme_mgr._apply_primary_toolbar_theme()

    # [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
    def auto_export_table(self, checked: bool = False, path: str | None = None):
        self._export_mgr.auto_export_table(checked, path)

    def _export_event_table_to_path(self, path: str) -> bool:
        return self._export_mgr._export_event_table_to_path(path)

    def _export_event_table_via_dialog(self) -> None:
        self._export_mgr._export_event_table_via_dialog()

    def _event_rows_for_export(self) -> list[tuple]:
        return self._export_mgr._event_rows_for_export()

    def _build_export_table_for_profile(self, profile_id: str):
        return self._export_mgr._build_export_table_for_profile(profile_id)

    def _show_export_warnings(self, profile_name: str, warnings: Sequence[str]) -> None:
        self._export_mgr._show_export_warnings(profile_name, warnings)

    def _copy_event_profile_to_clipboard(self, profile_id: str, *, include_header: bool) -> None:
        self._export_mgr._copy_event_profile_to_clipboard(profile_id, include_header=include_header)

    def _default_event_export_filename(self, profile_id: str) -> str:
        return self._export_mgr._default_event_export_filename(profile_id)

    def _export_event_profile_csv_via_dialog(
        self, profile_id: str, *, include_header: bool
    ) -> None:
        self._export_mgr._export_event_profile_csv_via_dialog(profile_id, include_header=include_header)

    def open_excel_template_export_dialog(self, checked: bool = False) -> None:
        self._export_mgr.open_excel_template_export_dialog(checked)

    def _prompt_export_event_table_after_review(self) -> None:
        self._event_mgr._prompt_export_event_table_after_review()

    # ---------- UI State Persistence ----------
    def gather_ui_state(self):
        return self._sample_mgr.gather_ui_state()

    def _invalidate_sample_state_cache(self):
        self._sample_mgr._invalidate_sample_state_cache()

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
        self._event_mgr._sync_sample_events_dataframe(sample_state)

    def gather_sample_state(self):
        return self._sample_mgr.gather_sample_state()

    def apply_ui_state(self, state):
        self._sample_mgr.apply_ui_state(state)

    def _sample_is_embedded(self, sample: SampleN | None) -> bool:
        return self._sample_mgr._sample_is_embedded(sample)

    def apply_sample_state(self, state):
        self._sample_mgr.apply_sample_state(state)

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
                for i in range(self.project_tree.topLevelItemCount()):
                    exp_child = self.project_tree.topLevelItem(i)
                    if exp_child is not None:
                        for sample_child in self._sample_mgr._iter_sample_items(exp_child):
                            sample_obj = sample_child.data(0, Qt.ItemDataRole.UserRole)
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

        exp_item = None
        sample_item = None

        for i in range(self.project_tree.topLevelItemCount()):
            child = self.project_tree.topLevelItem(i)
            obj = child.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(obj, Experiment) and obj.name == last_exp:
                exp_item = child
                if last_sample:
                    for sc in self._sample_mgr._iter_sample_items(child):
                        sample_obj = sc.data(0, Qt.ItemDataRole.UserRole)
                        if isinstance(sample_obj, SampleN) and sample_obj.name == last_sample:
                            sample_item = sc
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
                    from PyQt6.QtCore import QCoreApplication

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
