"""Main window for GIF animation creation and preview.

This module provides the primary UI for the GIF Animator feature,
following the shared window layout pattern.
"""

import logging

import numpy as np
import pandas as pd
from PyQt5.QtCore import QPoint, QRect, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRubberBand,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.io.tiffs import resolve_frame_times

from .frame_synchronizer import FrameSynchronizer
from .poster_renderer import PosterFigureRenderer
from .preview_player import PreviewPlayerWidget
from .renderer import AnimationRenderer, EventSpec, RenderContext, estimate_gif_size_mb, save_gif
from .specs import AnimationSpec, FrameTimeExtractionResult, TracePanelSpec

logger = logging.getLogger(__name__)

TIFF_STRIP_HEIGHT_DEFAULT = 28
WIDE_CANVAS_HEIGHT_RATIO = 1 / 3


class RenderThread(QThread):
    """Background thread for rendering frames to avoid blocking UI with cancellation support."""

    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)  # rendered frames
    error = pyqtSignal(str)  # error message
    cancelled = pyqtSignal()  # emitted when rendering is cancelled

    def __init__(self, renderer, ctx, timings):
        super().__init__()
        self.renderer = renderer
        self.ctx = ctx
        self.timings = timings
        self._should_stop = False
        import threading

        self._lock = threading.Lock()

    def cancel(self):
        """Request cancellation of rendering."""
        with self._lock:
            self._should_stop = True
            logger.info("Render cancellation requested")

    def run(self):
        """Run rendering in background thread with cancellation checks."""
        try:
            frames = []
            total = len(self.timings)

            for i, timing in enumerate(self.timings):
                # Check cancellation before each frame
                with self._lock:
                    if self._should_stop:
                        logger.info(
                            "Render cancelled by user",
                            extra={"frames_completed": i, "total_frames": total},
                        )
                        self.cancelled.emit()
                        return

                # Render single frame
                frame = self.renderer.render_frame(self.ctx, timing)
                frames.append(frame)

                # Report progress
                self.progress.emit(i + 1, total)

            self.finished.emit(frames)
            logger.info("Render completed successfully", extra={"total_frames": len(frames)})

        except Exception as e:
            logger.error("Render failed with exception", extra={"error": str(e)}, exc_info=True)
            self.error.emit(str(e))


class CropImageLabel(QLabel):
    """Image label with rubber-band ROI selection."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._source_pixmap = pixmap
        self._scaled_pixmap: QPixmap | None = None
        self._offset = QPoint(0, 0)
        self._scale = 1.0
        self._origin = QPoint(0, 0)
        self._selection_rect = QRect()
        self._rubber_band = QRubberBand(QRubberBand.Rectangle, self)

        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(400, 300)
        self._update_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()
        self._rubber_band.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._scaled_pixmap is not None:
            self._origin = event.pos()
            self._rubber_band.setGeometry(QRect(self._origin, self._origin))
            self._rubber_band.show()

    def mouseMoveEvent(self, event):
        if self._rubber_band.isVisible():
            self._rubber_band.setGeometry(QRect(self._origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._rubber_band.isVisible():
            self._selection_rect = self._rubber_band.geometry().normalized()

    def _update_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._scaled_pixmap = scaled
        self.setPixmap(scaled)
        offset_x = max(0, (self.width() - scaled.width()) // 2)
        offset_y = max(0, (self.height() - scaled.height()) // 2)
        self._offset = QPoint(offset_x, offset_y)
        if self._source_pixmap.width() > 0:
            self._scale = scaled.width() / self._source_pixmap.width()

    def get_crop_rect(self) -> tuple[int, int, int, int] | None:
        if self._scaled_pixmap is None or self._selection_rect.isNull():
            return None
        pixmap_rect = QRect(self._offset, self._scaled_pixmap.size())
        selected = self._selection_rect.intersected(pixmap_rect)
        if selected.isEmpty() or self._scale <= 0:
            return None
        x = int(round((selected.x() - self._offset.x()) / self._scale))
        y = int(round((selected.y() - self._offset.y()) / self._scale))
        w = int(round(selected.width() / self._scale))
        h = int(round(selected.height() / self._scale))

        x = max(0, min(x, self._source_pixmap.width() - 1))
        y = max(0, min(y, self._source_pixmap.height() - 1))
        w = max(1, min(w, self._source_pixmap.width() - x))
        h = max(1, min(h, self._source_pixmap.height() - y))
        return (x, y, w, h)


class CropSelectionDialog(QDialog):
    """Dialog to select a crop ROI from a TIFF frame."""

    def __init__(self, frame: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Crop ROI")
        self._crop_label = CropImageLabel(self._frame_to_pixmap(frame), self)

        layout = QVBoxLayout(self)
        layout.addWidget(self._crop_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _frame_to_pixmap(frame: np.ndarray) -> QPixmap:
        arr = frame
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=2)
        elif arr.ndim == 3 and arr.shape[2] == 1:
            arr = np.repeat(arr, 3, axis=2)
        if arr.dtype != np.uint8:
            vmax = float(arr.max()) if arr.size else 0.0
            if vmax > 0:
                arr = (arr / vmax * 255).astype(np.uint8)
            else:
                arr = np.zeros_like(arr, dtype=np.uint8)

        h, w, c = arr.shape
        bytes_per_line = c * w
        qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)

    def get_crop_rect(self) -> tuple[int, int, int, int] | None:
        return self._crop_label.get_crop_rect()


class GifAnimatorWindow(QMainWindow):
    """Main window for GIF animation creation and preview."""

    def __init__(self, parent, project_ctx, sample, trace_model, events_df):
        """Initialize GIF Animator window.

        Args:
            parent: Parent widget
            project_ctx: Project context (can be None)
            sample: SampleN instance with snapshots and data
            trace_model: TraceModel instance
            events_df: Pandas DataFrame with event data
        """
        super().__init__(parent)

        self.project_ctx = project_ctx
        self.sample = sample
        self.trace_model = trace_model
        self.events_df = events_df

        self._tiff_aspect_ratio = self._compute_tiff_aspect_ratio()

        # State
        self.current_spec = self._create_default_spec()
        self.current_spec.vessel_crop_rect = self._load_crop_rect()
        self.rendered_frames: list[np.ndarray] = []
        self.rendered_frame_durations_ms: list[int] | None = None
        self.is_rendering = False
        self.render_thread: RenderThread | None = None
        self._status_tone: str = "neutral"

        # Extract frame times with metadata
        frame_time_result = self._extract_frame_times()
        self.frame_times = frame_time_result.frame_times
        self.frame_time_metadata = frame_time_result  # Store metadata for auditability

        # Setup UI
        self.setWindowTitle(f"GIF Animator - {sample.name}")
        self.setGeometry(100, 100, 1200, 700)

        self._init_ui()
        self._sync_trace_width_controls()
        self._sync_y_range_controls()
        self._seed_y_range_controls()
        self.apply_theme()

    def _extract_frame_times(self) -> FrameTimeExtractionResult:
        """Extract frame timestamps using TiffPage synchronization logic with full auditability.

        This follows the same logic as the main window's _derive_frame_trace_time()
        to properly sync TIFF frames with trace data using the TiffPage column.

        Returns:
            FrameTimeExtractionResult with frame times and metadata about the extraction
        """
        n_frames = len(self.sample.snapshots)
        warnings: list[str] = []
        trace_start_s = self._trace_start_time_s()

        trace_data = self.sample.trace_data
        if trace_data is not None:
            tiff_col = "tiff_page" if "tiff_page" in trace_data.columns else None
            if tiff_col is None and "TiffPage" in trace_data.columns:
                tiff_col = "TiffPage"
            time_col_name = "t_seconds" if "t_seconds" in trace_data.columns else None
            if time_col_name is None and "Time (s)" in trace_data.columns:
                time_col_name = "Time (s)"

            if tiff_col is not None and time_col_name is not None:
                try:
                    tiff_series = pd.to_numeric(trace_data[tiff_col], errors="coerce")
                    mapping = {
                        int(tp): int(i)
                        for i, tp in enumerate(tiff_series.to_numpy())
                        if pd.notna(tp)
                    }
                    trace_times = pd.to_numeric(
                        trace_data[time_col_name], errors="coerce"
                    ).to_numpy(dtype=float)
                    result = resolve_frame_times(
                        [],
                        n_frames=n_frames,
                        trace_time_s=trace_times,
                        tiff_page_to_trace_idx=mapping,
                        allow_fallback=False,
                    )
                    frame_times, repair_applied, repair_note = (
                        self._validate_and_repair_frame_times(
                            result.frame_times_s.tolist(), n_frames
                        )
                    )
                    if repair_note:
                        warnings.append(repair_note)
                    if repair_applied:
                        logger.warning(
                            "Frame times repaired to enforce monotonicity",
                            extra={"source": "tiff_page", "n_frames": n_frames},
                        )
                    if frame_times is not None:
                        warnings.extend(result.warnings)
                        return self._finalize_frame_time_result(
                            frame_times=frame_times,
                            source="tiff_page",
                            confidence="high",
                            warnings=warnings,
                            mapping_coverage=1.0,
                        )
                    warnings.append(
                        "Frame times invalid after TiffPage sync; attempting fallback sources."
                    )
                    logger.warning(
                        "Frame times invalid after TiffPage sync; attempting fallback sources",
                        extra={"source": "tiff_page", "n_frames": n_frames},
                    )
                except Exception as exc:
                    warnings.append(f"TiffPage sync failed: {exc}")
                    logger.warning(
                        "Frame time extraction from TiffPage failed",
                        extra={"error": str(exc), "fallback_to": "ui_state"},
                    )

        if self.sample.ui_state:
            frame_times = self.sample.ui_state.get("snapshot_frame_times")
            if frame_times and len(frame_times) == n_frames:
                logger.info(
                    "Frame times loaded from ui_state",
                    extra={"source": "ui_state", "n_frames": len(frame_times)},
                )
                frame_times, repair_applied, repair_note = self._validate_and_repair_frame_times(
                    frame_times, n_frames
                )
                if repair_note:
                    warnings.append(repair_note)
                if repair_applied:
                    logger.warning(
                        "Frame times repaired to enforce monotonicity",
                        extra={"source": "ui_state", "n_frames": n_frames},
                    )
                if frame_times is not None:
                    warnings.append("Frame times loaded from saved ui_state")
                    return self._finalize_frame_time_result(
                        frame_times=frame_times,
                        source="ui_state",
                        confidence="medium",
                        warnings=warnings,
                        mapping_coverage=1.0,
                    )
                warnings.append("Frame times invalid from ui_state; falling back to estimation.")
                logger.warning(
                    "Frame times invalid from ui_state; using estimation fallback",
                    extra={"source": "ui_state", "n_frames": n_frames},
                )

        recording_interval = 0.14
        if self.sample.ui_state:
            recording_interval = self.sample.ui_state.get("recording_interval", 0.14)
        try:
            recording_interval = float(recording_interval)
        except Exception:
            recording_interval = 0.14
        if not np.isfinite(recording_interval) or recording_interval <= 0:
            logger.warning(
                "Invalid recording_interval; using default",
                extra={"recording_interval": recording_interval},
            )
            recording_interval = 0.14

        frame_times, estimate_warnings = self._estimate_frame_times(
            n_frames,
            recording_interval,
            trace_start_s,
        )
        warnings.extend(estimate_warnings)
        warnings.append(
            f"Frame times estimated using {recording_interval}s interval (no TiffPage or ui_state data)"
        )
        logger.warning(
            "Frame times estimated (no data source available)",
            extra={"source": "estimation", "interval": recording_interval, "n_frames": n_frames},
        )

        frame_times, repair_applied, repair_note = self._validate_and_repair_frame_times(
            frame_times, n_frames
        )
        if repair_note:
            warnings.append(repair_note)
        if repair_applied:
            logger.warning(
                "Frame times repaired to enforce monotonicity",
                extra={"source": "estimation", "n_frames": n_frames},
            )
        if frame_times is None:
            logger.warning(
                "Frame times invalid after estimation; using fallback baseline",
                extra={"n_frames": n_frames},
            )
            frame_times = list(
                trace_start_s + np.arange(n_frames, dtype=float) * float(recording_interval)
            )

        return self._finalize_frame_time_result(
            frame_times=frame_times,
            source="estimation",
            confidence="low",
            warnings=warnings,
            mapping_coverage=0.0,
        )

    def _estimate_frame_times(
        self,
        n_frames: int,
        recording_interval: float,
        trace_start_s: float,
    ) -> tuple[list[float], list[str]]:
        fps = None
        if recording_interval:
            try:
                fps = 1.0 / float(recording_interval)
            except Exception:
                fps = None
        result = resolve_frame_times(
            [],
            n_frames=n_frames,
            fps=fps,
            time_offset_s=trace_start_s,
        )
        return result.frame_times_s.tolist(), list(result.warnings)

    def _validate_and_repair_frame_times(
        self,
        frame_times: list[float] | np.ndarray | None,
        n_frames: int,
    ) -> tuple[list[float] | None, bool, str | None]:
        if frame_times is None:
            return None, False, "Frame times unavailable; falling back to estimation."
        arr = np.asarray(frame_times, dtype=float)
        if arr.size != n_frames:
            return None, False, f"Frame times length mismatch ({arr.size} vs {n_frames})."
        if arr.size == 0:
            return arr.tolist(), False, None
        if not np.isfinite(arr).all():
            return None, False, "Frame times contain non-finite values."
        diffs = np.diff(arr)
        if np.any(diffs < 0):
            repaired = np.maximum.accumulate(arr)
            return repaired.tolist(), True, "Frame times were not monotonic; repaired by clipping."
        return arr.tolist(), False, None

    def _finalize_frame_time_result(
        self,
        *,
        frame_times: list[float],
        source: str,
        confidence: str,
        warnings: list[str],
        mapping_coverage: float,
    ) -> FrameTimeExtractionResult:
        monotonic_ok = True
        start_time = None
        end_time = None
        if frame_times:
            arr = np.asarray(frame_times, dtype=float)
            if arr.size >= 2:
                monotonic_ok = bool(np.all(np.diff(arr) >= 0))
            start_time = float(arr[0])
            end_time = float(arr[-1])
        logger.info(
            "Frame times resolved",
            extra={
                "n_frames": len(frame_times),
                "source": source,
                "monotonic_ok": monotonic_ok,
                "coverage": mapping_coverage,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return FrameTimeExtractionResult(
            frame_times=frame_times,
            source=source,
            confidence=confidence,
            warnings=warnings,
            mapping_coverage=mapping_coverage,
        )

    def _trace_start_time_s(self) -> float:
        try:
            times = np.asarray(self.trace_model.time_full, dtype=float)
        except Exception:
            return 0.0
        finite = np.isfinite(times)
        if finite.any():
            return float(times[finite][0])
        return 0.0

    def _create_default_spec(self) -> AnimationSpec:
        """Create default animation specification."""
        # Get time range from trace model
        t_min, t_max = self.trace_model.full_range

        spec = AnimationSpec(
            start_time_s=t_min,
            end_time_s=t_max,
            fps=10,
            playback_speed=1.0,
            loop_count=0,
            output_width_px=800,
            output_height_px=400,
            layout_mode="side_by_side",
            vessel_width_ratio=0.4,
            use_tiff_frames=True,
            auto_vessel_width=True,
            trace_spec=TracePanelSpec(),
        )
        spec.vessel_show_timestamp = False
        self._apply_tiff_aspect_ratio(spec)
        return spec

    def _compute_tiff_aspect_ratio(self) -> float | None:
        """Return TIFF frame aspect ratio (width / height) if available."""
        if not isinstance(self.sample.snapshots, np.ndarray) or self.sample.snapshots.size == 0:
            return None
        rect = self._load_crop_rect()
        if rect is not None:
            _, _, w, h = rect
        else:
            frame = self.sample.snapshots[0]
            if frame.ndim == 2:
                h, w = frame.shape
            elif frame.ndim >= 3:
                h, w = frame.shape[0], frame.shape[1]
            else:
                return None
        if h <= 0 or w <= 0:
            return None
        return float(w) / float(h)

    def _apply_tiff_aspect_ratio(self, spec: AnimationSpec) -> None:
        """Adjust vessel width ratio to match TIFF aspect ratio."""
        if spec.layout_mode != "side_by_side":
            return
        if not getattr(spec, "auto_vessel_width", True):
            return
        ratio = self._tiff_aspect_ratio
        if ratio is None:
            return
        # Prefer a wider trace panel for presentation readability.
        max_vessel_ratio = 0.4
        total_w = max(1, spec.output_width_px)
        total_h = max(1, spec.output_height_px)
        vessel_ratio = (ratio * total_h) / total_w
        vessel_ratio = min(max_vessel_ratio, max(0.1, vessel_ratio))
        spec.vessel_width_ratio = vessel_ratio

    def _update_vessel_ratio_for_aspect(self) -> None:
        """Keep vessel width ratio aligned with TIFF aspect ratio."""
        if self.current_spec is None:
            return
        self._apply_tiff_aspect_ratio(self.current_spec)

    def _load_crop_rect(self) -> tuple[int, int, int, int] | None:
        """Return saved crop rect from sample ui_state if present."""
        state = self.sample.ui_state if isinstance(self.sample.ui_state, dict) else {}
        rect = state.get("gif_animator_crop_rect")
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            try:
                x, y, w, h = [int(v) for v in rect]
            except Exception:
                return None
            if w > 0 and h > 0:
                return (x, y, w, h)
        return None

    def _save_crop_rect(self, rect: tuple[int, int, int, int] | None) -> None:
        state = self.sample.ui_state if isinstance(self.sample.ui_state, dict) else {}
        if rect:
            state["gif_animator_crop_rect"] = list(rect)
        else:
            state.pop("gif_animator_crop_rect", None)
        self.sample.ui_state = state
        if hasattr(self.parent(), "mark_session_dirty"):
            try:
                self.parent().mark_session_dirty(reason="gif_crop")
            except Exception:
                pass

    def _set_crop_roi(self) -> None:
        if not isinstance(self.sample.snapshots, np.ndarray) or self.sample.snapshots.size == 0:
            QMessageBox.warning(self, "No TIFF Frames", "No TIFF frames available to crop.")
            return
        frame = self.sample.snapshots[0]
        dialog = CropSelectionDialog(frame, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        rect = dialog.get_crop_rect()
        if rect is None:
            QMessageBox.information(self, "Crop ROI", "No crop region selected.")
            return
        self.current_spec.vessel_crop_rect = rect
        self._save_crop_rect(rect)
        self._tiff_aspect_ratio = self._compute_tiff_aspect_ratio()
        self._apply_tiff_aspect_ratio(self.current_spec)
        self._refresh_preview()

    def _clear_crop_roi(self) -> None:
        self.current_spec.vessel_crop_rect = None
        self._save_crop_rect(None)
        self._tiff_aspect_ratio = self._compute_tiff_aspect_ratio()
        self._apply_tiff_aspect_ratio(self.current_spec)
        self._refresh_preview()

    def _init_ui(self):
        """Initialize UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)

        # Splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Preview player
        self.preview_player = PreviewPlayerWidget()
        self.preview_player.setMinimumWidth(400)
        splitter.addWidget(self.preview_player)

        # Right panel: Controls (in scroll area)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(350)
        scroll_area.setMaximumWidth(500)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.addWidget(self._create_event_selection_group())
        controls_layout.addWidget(self._create_animation_settings_group())
        controls_layout.addWidget(self._create_size_settings_group())
        controls_layout.addWidget(self._create_trace_settings_group())
        controls_layout.addWidget(self._create_actions_group())
        controls_layout.addStretch()

        scroll_area.setWidget(controls_widget)
        splitter.addWidget(scroll_area)

        # Set splitter proportions
        splitter.setStretchFactor(0, 3)  # Preview gets more space
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    def _create_event_selection_group(self) -> QGroupBox:
        """Create event selection controls."""
        group = QGroupBox("Event Selection")
        layout = QVBoxLayout()

        # Start event
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start Event:"))
        self.start_event_combo = QComboBox()
        self._populate_event_combo(self.start_event_combo)
        self.start_event_combo.currentIndexChanged.connect(self._on_event_selection_changed)
        start_layout.addWidget(self.start_event_combo, 1)
        layout.addLayout(start_layout)

        # End event
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("End Event:"))
        self.end_event_combo = QComboBox()
        self._populate_event_combo(self.end_event_combo)
        # Select last event by default (before adding trace end option)
        if self.end_event_combo.count() > 0:
            self.end_event_combo.setCurrentIndex(self.end_event_combo.count() - 1)
        # Add end-of-trace option
        self.end_event_combo.insertSeparator(self.end_event_combo.count())
        _, t_max = self.trace_model.full_range
        self.end_event_combo.addItem(
            f"End of trace ({t_max:.2f}s)",
            userData={"time": float(t_max), "label": "End of trace"},
        )
        self.end_event_combo.currentIndexChanged.connect(self._on_event_selection_changed)
        end_layout.addWidget(self.end_event_combo, 1)
        layout.addLayout(end_layout)

        # Time range display
        self.time_range_label = QLabel("Time range: -")
        layout.addWidget(self.time_range_label)

        group.setLayout(layout)
        return group

    def _populate_event_combo(self, combo: QComboBox):
        """Populate event combo box with events from dataframe."""
        if self.events_df is None or len(self.events_df) == 0:
            return

        # Check for time column - support both CSV and database column names
        time_col = None
        for col in ["t_seconds", "Time (s)", "Time(s)", "Time", "time"]:
            if col in self.events_df.columns:
                time_col = col
                break

        if time_col is None:
            return

        # Convert time column to numeric (handles hh:mm:ss format)
        time_series = self.events_df[time_col].copy()
        time_numeric = pd.to_numeric(time_series, errors="coerce")

        # If conversion failed (all NaN), try parsing as hh:mm:ss timedelta
        if time_numeric.isna().all():
            try:
                time_td = pd.to_timedelta(time_series.astype(str), errors="coerce")
                if not time_td.isna().all():
                    time_numeric = time_td.dt.total_seconds()
            except Exception:
                pass

        # Get TIFF time range for annotation
        tiff_start = self.frame_times[0] if self.frame_times else 0
        tiff_end = self.frame_times[-1] if self.frame_times else float("inf")

        events = []
        for pos, (_, row) in enumerate(self.events_df.iterrows()):
            event_time = time_numeric.iloc[pos] if not pd.isna(time_numeric.iloc[pos]) else 0.0
            event_label = row.get("Label", row.get("Event", f"Event {pos + 1}"))
            out_of_range = event_time < tiff_start or event_time > tiff_end
            suffix = " [out of TIFF range]" if out_of_range else ""
            events.append((event_time, event_label, f"{event_label} ({event_time:.2f}s){suffix}"))

        for event_time, event_label, display_label in events:
            combo.addItem(display_label, userData={"time": event_time, "label": event_label})

    def _create_animation_settings_group(self) -> QGroupBox:
        """Create animation settings controls."""
        group = QGroupBox("Animation Settings")
        layout = QVBoxLayout()

        # FPS
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(10)
        self.fps_spin.valueChanged.connect(self._on_settings_changed)
        fps_layout.addWidget(self.fps_spin)
        fps_layout.addStretch()
        layout.addLayout(fps_layout)

        # Playback speed
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Speed:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 20.0)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(1.0)
        self.speed_spin.valueChanged.connect(self._on_settings_changed)
        speed_layout.addWidget(self.speed_spin)
        speed_layout.addWidget(QLabel("x"))
        speed_layout.addStretch()
        layout.addLayout(speed_layout)

        # Frame sampling
        self.use_tiff_frames_checkbox = QCheckBox("Use TIFF frames (fast)")
        self.use_tiff_frames_checkbox.setChecked(True)
        self.use_tiff_frames_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.use_tiff_frames_checkbox)

        # Loop
        self.loop_checkbox = QCheckBox("Loop forever")
        self.loop_checkbox.setChecked(True)
        self.loop_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.loop_checkbox)

        # Time indicator
        self.time_indicator_checkbox = QCheckBox("Show time indicator")
        self.time_indicator_checkbox.setChecked(True)
        self.time_indicator_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.time_indicator_checkbox)

        group.setLayout(layout)
        return group

    def _create_size_settings_group(self) -> QGroupBox:
        """Create size settings controls."""
        group = QGroupBox("Size Settings")
        layout = QVBoxLayout()

        # Size preset
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.size_preset_combo = QComboBox()
        self.size_preset_combo.addItem("640x480 (SD)", userData=(640, 480))
        self.size_preset_combo.addItem("800x600 (SVGA)", userData=(800, 600))
        self.size_preset_combo.addItem("1024x768 (XGA)", userData=(1024, 768))
        self.size_preset_combo.addItem("1280x720 (HD)", userData=(1280, 720))
        self.size_preset_combo.addItem("Custom", userData=None)
        self.size_preset_combo.setCurrentIndex(1)  # 800x600 default
        self.size_preset_combo.currentIndexChanged.connect(self._on_size_preset_changed)
        preset_layout.addWidget(self.size_preset_combo, 1)
        layout.addLayout(preset_layout)

        # TIFF position
        position_layout = QHBoxLayout()
        position_layout.addWidget(QLabel("TIFF position:"))
        self.trace_position_combo = QComboBox()
        self.trace_position_combo.addItem("Left", userData="left")
        self.trace_position_combo.addItem("Right", userData="right")
        self.trace_position_combo.addItem("Top", userData="top")
        self.trace_position_combo.currentIndexChanged.connect(self._on_trace_position_changed)
        position_layout.addWidget(self.trace_position_combo, 1)
        layout.addLayout(position_layout)

        # Trace width
        trace_width_layout = QHBoxLayout()
        trace_width_layout.addWidget(QLabel("Trace width:"))
        self.trace_width_spin = QSpinBox()
        self.trace_width_spin.setRange(20, 80)
        self.trace_width_spin.setValue(60)
        self.trace_width_spin.setSingleStep(5)
        self.trace_width_spin.valueChanged.connect(self._on_settings_changed)
        trace_width_layout.addWidget(self.trace_width_spin)
        trace_width_layout.addWidget(QLabel("%"))
        trace_width_layout.addStretch()
        layout.addLayout(trace_width_layout)

        self.auto_vessel_width_checkbox = QCheckBox("Auto-fit vessel width")
        self.auto_vessel_width_checkbox.setChecked(True)
        self.auto_vessel_width_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.auto_vessel_width_checkbox)

        strip_layout = QHBoxLayout()
        strip_layout.addWidget(QLabel("TIFF strip height:"))
        self.vessel_height_spin = QSpinBox()
        self.vessel_height_spin.setRange(20, 40)
        self.vessel_height_spin.setValue(TIFF_STRIP_HEIGHT_DEFAULT)
        self.vessel_height_spin.setSingleStep(1)
        self.vessel_height_spin.valueChanged.connect(self._on_settings_changed)
        strip_layout.addWidget(self.vessel_height_spin)
        strip_layout.addWidget(QLabel("%"))
        strip_layout.addStretch()
        layout.addLayout(strip_layout)
        # Width
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(100, 4000)
        self.width_spin.setValue(800)
        self.width_spin.setSingleStep(10)
        self.width_spin.valueChanged.connect(self._on_settings_changed)
        width_layout.addWidget(self.width_spin)
        width_layout.addWidget(QLabel("px"))
        width_layout.addStretch()
        layout.addLayout(width_layout)

        # Height
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(100, 4000)
        self.height_spin.setValue(400)
        self.height_spin.setSingleStep(10)
        self.height_spin.valueChanged.connect(self._on_settings_changed)
        height_layout.addWidget(self.height_spin)
        height_layout.addWidget(QLabel("px"))
        height_layout.addStretch()
        layout.addLayout(height_layout)

        group.setLayout(layout)
        return group

    def _create_trace_settings_group(self) -> QGroupBox:
        """Create trace visualization settings."""
        group = QGroupBox("Trace Settings")
        layout = QVBoxLayout()

        # Channel visibility
        self.show_inner_checkbox = QCheckBox("Show inner diameter")
        self.show_inner_checkbox.setChecked(True)
        self.show_inner_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.show_inner_checkbox)

        self.show_outer_checkbox = QCheckBox("Show outer diameter")
        self.show_outer_checkbox.setChecked(True)
        self.show_outer_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.show_outer_checkbox)

        self.show_events_checkbox = QCheckBox("Show events")
        self.show_events_checkbox.setChecked(True)
        self.show_events_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.show_events_checkbox)

        self.zero_time_checkbox = QCheckBox("Time axis starts at 0")
        self.zero_time_checkbox.setChecked(False)
        self.zero_time_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.zero_time_checkbox)

        self.fast_trace_checkbox = QCheckBox("Fast trace (static)")
        self.fast_trace_checkbox.setChecked(True)
        self.fast_trace_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.fast_trace_checkbox)

        shape_layout = QHBoxLayout()
        shape_layout.addWidget(QLabel("Trace shape:"))
        self.trace_shape_combo = QComboBox()
        self.trace_shape_combo.addItem("Balanced", userData="balanced")
        self.trace_shape_combo.addItem("Wide", userData="wide")
        self.trace_shape_combo.currentIndexChanged.connect(self._on_settings_changed)
        shape_layout.addWidget(self.trace_shape_combo, 1)
        layout.addLayout(shape_layout)

        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Axis font:"))
        self.axis_font_spin = QSpinBox()
        self.axis_font_spin.setRange(8, 32)
        self.axis_font_spin.setValue(int(round(self.current_spec.trace_spec.label_fontsize)))
        self.axis_font_spin.setSingleStep(1)
        self.axis_font_spin.valueChanged.connect(self._on_settings_changed)
        font_layout.addWidget(self.axis_font_spin)
        font_layout.addWidget(QLabel("Tick font:"))
        self.tick_font_spin = QSpinBox()
        self.tick_font_spin.setRange(6, 28)
        self.tick_font_spin.setValue(int(round(self.current_spec.trace_spec.tick_fontsize)))
        self.tick_font_spin.setSingleStep(1)
        self.tick_font_spin.valueChanged.connect(self._on_settings_changed)
        font_layout.addWidget(self.tick_font_spin)
        font_layout.addStretch()
        layout.addLayout(font_layout)

        self.manual_y_range_checkbox = QCheckBox("Manual y-axis range")
        self.manual_y_range_checkbox.setChecked(False)
        self.manual_y_range_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.manual_y_range_checkbox)

        y_range_layout = QHBoxLayout()
        y_range_layout.addWidget(QLabel("Y min:"))
        self.y_min_spin = QDoubleSpinBox()
        self.y_min_spin.setRange(-10000.0, 10000.0)
        self.y_min_spin.setDecimals(2)
        self.y_min_spin.setSingleStep(1.0)
        self.y_min_spin.valueChanged.connect(self._on_settings_changed)
        y_range_layout.addWidget(self.y_min_spin)
        y_range_layout.addWidget(QLabel("Y max:"))
        self.y_max_spin = QDoubleSpinBox()
        self.y_max_spin.setRange(-10000.0, 10000.0)
        self.y_max_spin.setDecimals(2)
        self.y_max_spin.setSingleStep(1.0)
        self.y_max_spin.valueChanged.connect(self._on_settings_changed)
        y_range_layout.addWidget(self.y_max_spin)
        layout.addLayout(y_range_layout)

        group.setLayout(layout)
        return group

    def _create_actions_group(self) -> QGroupBox:
        """Create action buttons."""
        group = QGroupBox("Actions")
        layout = QVBoxLayout()

        # Crop controls
        self.crop_btn = QPushButton("Set Crop ROI...")
        self.crop_btn.clicked.connect(self._set_crop_roi)
        layout.addWidget(self.crop_btn)

        self.clear_crop_btn = QPushButton("Clear Crop")
        self.clear_crop_btn.clicked.connect(self._clear_crop_roi)
        layout.addWidget(self.clear_crop_btn)

        # Refresh Preview button
        self.refresh_btn = QPushButton("Refresh Preview")
        self.refresh_btn.clicked.connect(self._refresh_preview)
        layout.addWidget(self.refresh_btn)

        # Cancel button (hidden by default, shown during rendering)
        self.cancel_render_btn = QPushButton("Cancel")
        self.cancel_render_btn.clicked.connect(self._cancel_render)
        self.cancel_render_btn.setVisible(False)
        layout.addWidget(self.cancel_render_btn)

        # Export button
        self.export_btn = QPushButton("Export GIF...")
        self.export_btn.clicked.connect(self._export_gif)
        layout.addWidget(self.export_btn)

        # Export static frame
        self.export_frame_btn = QPushButton("Export Static Frame...")
        self.export_frame_btn.clicked.connect(self._export_static_frame)
        layout.addWidget(self.export_frame_btn)

        # Export poster figure
        self.export_poster_btn = QPushButton("Export Poster Figure...")
        self.export_poster_btn.clicked.connect(self._export_poster_figure)
        layout.addWidget(self.export_poster_btn)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Sync status label (shows frame time source)
        self.sync_status_label = QLabel()
        layout.addWidget(self.sync_status_label)
        self._set_status_message("", tone="neutral")
        self._update_sync_status()  # Initialize with current metadata

        group.setLayout(layout)
        return group

    def _theme_colors(self) -> dict[str, str]:
        from vasoanalyzer.ui.theme import CURRENT_THEME

        theme = CURRENT_THEME if isinstance(CURRENT_THEME, dict) else {}
        return {
            "info": theme.get("accent_fill", theme.get("accent", "#4a9eff")),
            "success": theme.get("success_text", theme.get("accent", "#51cf66")),
            "error": theme.get("error_text", theme.get("warning_border", "#ff6b6b")),
            "warning": theme.get("warning_text", theme.get("warning_border", "#f59e0b")),
            "muted": theme.get("text_disabled", "#666666"),
            "highlighted_text": theme.get("highlighted_text", "#ffffff"),
            "panel_border": theme.get("panel_border", "#666666"),
        }

    def _set_status_message(self, text: str, *, tone: str = "neutral") -> None:
        colors = self._theme_colors()
        tone_map = {
            "info": colors["info"],
            "success": colors["success"],
            "error": colors["error"],
            "warning": colors["warning"],
            "neutral": colors["muted"],
        }
        color = tone_map.get(tone, colors["muted"])
        self._status_tone = tone
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 10px; }}")

    def _apply_cancel_button_style(self) -> None:
        colors = self._theme_colors()
        cancel_color = colors["error"]
        self.cancel_render_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {cancel_color};
                color: {colors["highlighted_text"]};
                border: 1px solid {cancel_color};
            }}
            QPushButton:disabled {{
                color: {colors["muted"]};
                border: 1px solid {colors["panel_border"]};
            }}
            """
        )

    def _update_sync_status(self):
        """Update the sync status label to show frame time source and confidence."""
        if not hasattr(self, "frame_time_metadata") or not hasattr(self, "sync_status_label"):
            return

        result = self.frame_time_metadata
        colors = self._theme_colors()
        color_map = {"high": colors["info"], "medium": colors["warning"], "low": colors["error"]}
        color = color_map.get(result.confidence, colors["muted"])

        # Create tooltip with detailed information
        tooltip = "Frame Time Synchronization\n\n"
        tooltip += f"Source: {result.source}\n"
        tooltip += f"Confidence: {result.confidence}\n"
        tooltip += f"Coverage: {result.mapping_coverage:.1%}\n"

        if result.warnings:
            tooltip += "\nWarnings:\n"
            for warning in result.warnings:
                tooltip += f"  • {warning}\n"

        # Create display text
        display_text = (
            f'<span style="color: {color};">'
            f"● Sync: {result.source} ({result.confidence} confidence)"
            "</span>"
        )

        self.sync_status_label.setText(display_text)
        self.sync_status_label.setToolTip(tooltip)

    def apply_theme(self, mode: str | None = None) -> None:
        """Apply the current theme to this window."""
        from vasoanalyzer.ui.theme import CURRENT_THEME

        theme = CURRENT_THEME if isinstance(CURRENT_THEME, dict) else {}
        bg = theme.get("window_bg", "#FFFFFF")
        text = theme.get("text", "#000000")
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(bg))
        palette.setColor(QPalette.WindowText, QColor(text))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self._apply_cancel_button_style()
        current_text = self.status_label.text() if hasattr(self, "status_label") else ""
        self._set_status_message(current_text, tone=self._status_tone)
        self._update_sync_status()

    def _on_event_selection_changed(self):
        """Handle event selection change."""
        # Update spec with new time range
        start_data = self.start_event_combo.currentData()
        end_data = self.end_event_combo.currentData()

        if start_data and end_data:
            self.current_spec.start_time_s = start_data["time"]
            self.current_spec.end_time_s = end_data["time"]
            self.current_spec.start_event_label = start_data["label"]
            self.current_spec.end_event_label = end_data["label"]

            # Update time range display
            duration = self.current_spec.duration_s
            self.time_range_label.setText(
                f"Time range: {self.current_spec.start_time_s:.2f}s - "
                f"{self.current_spec.end_time_s:.2f}s (duration: {duration:.2f}s)"
            )

            # Validate time range
            if self.current_spec.start_time_s >= self.current_spec.end_time_s:
                self._set_status_message("⚠ Start time must be before end time", tone="error")
            else:
                self._set_status_message("", tone="neutral")
            self._update_trace_y_range()

    def _on_settings_changed(self):
        """Handle settings change (update spec)."""
        # Update spec from UI controls
        self.current_spec.fps = self.fps_spin.value()
        self.current_spec.playback_speed = self.speed_spin.value()
        self.current_spec.loop_count = 0 if self.loop_checkbox.isChecked() else 1
        self.current_spec.output_width_px = self.width_spin.value()
        self.current_spec.output_height_px = self.height_spin.value()
        self.current_spec.use_tiff_frames = self.use_tiff_frames_checkbox.isChecked()
        tiff_position = self.trace_position_combo.currentData()
        side_layout = tiff_position in ("left", "right")
        self.current_spec.layout_mode = "side_by_side" if side_layout else "stacked"
        self.current_spec.vessel_position = tiff_position if side_layout else "left"
        self.current_spec.auto_vessel_width = self.auto_vessel_width_checkbox.isChecked()
        if side_layout:
            if not self.current_spec.auto_vessel_width:
                trace_ratio = self.trace_width_spin.value() / 100.0
                self.current_spec.vessel_width_ratio = max(0.1, min(0.9, 1.0 - trace_ratio))
            self._update_vessel_ratio_for_aspect()
        else:
            self.current_spec.vessel_width_ratio = self.vessel_height_spin.value() / 100.0
        self.current_spec.vessel_fit = "contain"
        self.current_spec.vessel_crop_rect = self._load_crop_rect()

        # Trace settings
        self.current_spec.trace_spec.show_inner = self.show_inner_checkbox.isChecked()
        self.current_spec.trace_spec.show_outer = self.show_outer_checkbox.isChecked()
        self.current_spec.trace_spec.show_events = self.show_events_checkbox.isChecked()
        self.current_spec.display_time_zero = self.zero_time_checkbox.isChecked()
        show_time_indicator = self.time_indicator_checkbox.isChecked()
        self.current_spec.trace_spec.show_time_indicator = show_time_indicator
        self.current_spec.vessel_show_timestamp = False
        self.current_spec.trace_spec.fast_render = self.fast_trace_checkbox.isChecked()
        self.current_spec.trace_spec.shape = self.trace_shape_combo.currentData()
        self.current_spec.trace_spec.label_fontsize = float(self.axis_font_spin.value())
        self.current_spec.trace_spec.tick_fontsize = float(self.tick_font_spin.value())
        self._apply_trace_shape_width()
        self._apply_trace_shape_height()
        self._sync_y_range_controls()
        self._maybe_seed_manual_y_range()
        self._update_trace_y_range()
        self._sync_trace_width_controls()

    def _on_size_preset_changed(self, index):
        """Handle size preset change."""
        preset_data = self.size_preset_combo.currentData()
        if preset_data:
            width, height = preset_data
            self.width_spin.blockSignals(True)
            self.height_spin.blockSignals(True)
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
            self.width_spin.blockSignals(False)
            self.height_spin.blockSignals(False)
            self._on_settings_changed()

    def _on_trace_position_changed(self, index: int) -> None:
        position = self.trace_position_combo.currentData()
        if position in ("left", "right"):
            self.current_spec.vessel_position = position
        else:
            self.current_spec.vessel_position = "left"
        self._sync_trace_width_controls()

    def _sync_trace_width_controls(self) -> None:
        tiff_position = self.trace_position_combo.currentData()
        side_layout = tiff_position in ("left", "right")
        self.auto_vessel_width_checkbox.setEnabled(side_layout)
        auto = self.auto_vessel_width_checkbox.isChecked()
        self.trace_width_spin.setEnabled(side_layout and not auto)
        self.vessel_height_spin.setEnabled(not side_layout)

    def _apply_trace_shape_width(self) -> None:
        if self.current_spec.layout_mode != "side_by_side":
            return
        if self.current_spec.trace_spec.shape != "wide":
            return

        if self.current_spec.auto_vessel_width:
            self.current_spec.vessel_width_ratio = min(self.current_spec.vessel_width_ratio, 0.3)
            return

        min_trace_ratio = 70
        trace_ratio = self.trace_width_spin.value()
        if trace_ratio < min_trace_ratio:
            self.trace_width_spin.blockSignals(True)
            self.trace_width_spin.setValue(min_trace_ratio)
            self.trace_width_spin.blockSignals(False)
            trace_ratio = min_trace_ratio
        self.current_spec.vessel_width_ratio = max(0.1, min(0.9, 1.0 - trace_ratio / 100.0))

    def _apply_trace_shape_height(self) -> None:
        if self.current_spec.layout_mode != "side_by_side":
            self.height_spin.setEnabled(True)
            return
        if self.current_spec.trace_spec.shape != "wide":
            self.height_spin.setEnabled(True)
            return

        target_height = int(round(self.current_spec.output_width_px * WIDE_CANVAS_HEIGHT_RATIO))
        target_height = max(
            self.height_spin.minimum(), min(self.height_spin.maximum(), target_height)
        )
        if self.current_spec.output_height_px != target_height:
            self.current_spec.output_height_px = target_height
            self.height_spin.blockSignals(True)
            self.height_spin.setValue(target_height)
            self.height_spin.blockSignals(False)
        self.height_spin.setEnabled(False)

    def _sync_y_range_controls(self) -> None:
        manual = self.manual_y_range_checkbox.isChecked()
        self.y_min_spin.setEnabled(manual)
        self.y_max_spin.setEnabled(manual)

    def _seed_y_range_controls(self) -> None:
        y_range = self._compute_trace_y_range()
        if y_range is not None:
            self._set_manual_y_range(*y_range)

    def _maybe_seed_manual_y_range(self) -> None:
        if not self.manual_y_range_checkbox.isChecked():
            return
        y_min = self.y_min_spin.value()
        y_max = self.y_max_spin.value()
        if y_min < y_max:
            return
        y_range = self._compute_trace_y_range()
        if y_range is not None:
            self._set_manual_y_range(*y_range)

    def _set_manual_y_range(self, y_min: float, y_max: float) -> None:
        self.y_min_spin.blockSignals(True)
        self.y_max_spin.blockSignals(True)
        self.y_min_spin.setValue(y_min)
        self.y_max_spin.setValue(y_max)
        self.y_min_spin.blockSignals(False)
        self.y_max_spin.blockSignals(False)

    def _update_trace_y_range(self) -> None:
        spec = self.current_spec.trace_spec
        if self.manual_y_range_checkbox.isChecked():
            y_min = float(self.y_min_spin.value())
            y_max = float(self.y_max_spin.value())
            if y_min < y_max:
                spec.y_range = (y_min, y_max)
            return
        if spec.fast_render:
            spec.y_range = None
            return

        spec.y_range = self._compute_trace_y_range()

    def _compute_trace_y_range(self) -> tuple[float, float] | None:
        time = self.trace_model.time_full
        start = self.current_spec.start_time_s
        end = self.current_spec.end_time_s
        if start >= end:
            return None

        mask = (time >= start) & (time <= end)
        if not np.any(mask):
            return None

        series = []
        spec = self.current_spec.trace_spec
        if spec.show_inner:
            series.append(self.trace_model.inner_full[mask])
        if spec.show_outer and self.trace_model.outer_full is not None:
            series.append(self.trace_model.outer_full[mask])

        if not series:
            return None

        data = np.concatenate(series)
        if data.size == 0 or not np.isfinite(data).any():
            return None

        y_min = float(np.nanmin(data))
        y_max = float(np.nanmax(data))
        if not np.isfinite(y_min) or not np.isfinite(y_max):
            return None

        if y_min == y_max:
            pad = max(abs(y_min) * 0.05, 1.0)
        else:
            pad = (y_max - y_min) * 0.05
        return (y_min - pad, y_max + pad)

    def _refresh_preview(self):
        """Refresh preview by rendering animation frames."""
        # Update spec from UI
        self._on_event_selection_changed()
        self._on_settings_changed()

        # Validate spec
        errors = self.current_spec.validate()
        if errors:
            QMessageBox.warning(self, "Invalid Settings", "\n".join(errors))
            return

        # Validate with frame synchronizer
        try:
            synchronizer = FrameSynchronizer(
                self.frame_times,
                self.trace_model.time_full,
                self.current_spec.start_time_s,
                self.current_spec.end_time_s,
            )
            valid, error_msg = synchronizer.validate_time_range()
            if not valid:
                QMessageBox.warning(self, "Time Range Error", error_msg)
                return
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        # Estimate frame count and file size
        if self.current_spec.use_tiff_frames:
            timings = synchronizer.get_tiff_keyframes(
                playback_speed=self.current_spec.playback_speed
            )
        else:
            timings = synchronizer.get_animation_keyframes(
                self.current_spec.fps,
                self.current_spec.playback_speed,
            )
        n_frames = len(timings)
        self.rendered_frame_durations_ms = None
        if self.current_spec.use_tiff_frames and timings:
            self.rendered_frame_durations_ms = synchronizer.get_tiff_keyframe_durations_ms(
                timings,
                playback_speed=self.current_spec.playback_speed,
            )
            if (
                self.rendered_frame_durations_ms
                and len(self.rendered_frame_durations_ms) != n_frames
            ):
                logger.warning(
                    "Frame duration count mismatch; falling back to constant duration",
                    extra={
                        "n_frames": n_frames,
                        "duration_count": len(self.rendered_frame_durations_ms),
                    },
                )
                self.rendered_frame_durations_ms = None
        estimated_size_mb = estimate_gif_size_mb(
            self.current_spec.output_width_px,
            self.current_spec.output_height_px,
            n_frames,
        )

        # Estimate memory usage
        memory_mb = self._estimate_memory_mb(
            n_frames, self.current_spec.output_width_px, self.current_spec.output_height_px
        )

        logger.info(
            "Render initiated",
            extra={
                "n_frames": n_frames,
                "estimated_size_mb": estimated_size_mb,
                "estimated_memory_mb": memory_mb,
                "resolution": f"{self.current_spec.output_width_px}x{self.current_spec.output_height_px}",
            },
        )

        # Warn if memory usage is high
        if memory_mb > 500:  # Warn if >500MB
            reply = QMessageBox.warning(
                self,
                "Large Animation",
                f"This animation will use approximately {memory_mb:.0f} MB of memory.\n\n"
                f"Frame count: {n_frames}\n"
                f"Resolution: {self.current_spec.output_width_px}x{self.current_spec.output_height_px}\n\n"
                "Consider reducing frame count (shorter duration or lower FPS), "
                "resolution, or using faster playback speed.\n\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                logger.info("User cancelled render due to high memory warning")
                return

        # Clear old frames before rendering to free memory
        self.rendered_frames.clear()

        self._set_status_message(
            f"Rendering {n_frames} frames... (estimated size: {estimated_size_mb:.1f} MB)",
            tone="info",
        )

        # Create render context
        ctx = self._create_render_context()

        # Render in background thread
        renderer = AnimationRenderer(self.current_spec)

        self.render_thread = RenderThread(renderer, ctx, timings)
        self.render_thread.progress.connect(self._on_render_progress)
        self.render_thread.finished.connect(self._on_render_finished)
        self.render_thread.error.connect(self._on_render_error)
        self.render_thread.cancelled.connect(self._on_render_cancelled)

        # Update UI for rendering state
        self.refresh_btn.setVisible(False)
        self.cancel_render_btn.setVisible(True)
        self.export_btn.setEnabled(False)
        self.is_rendering = True

        self.render_thread.start()

    def _create_render_context(self) -> RenderContext:
        """Create render context with current data."""
        # Extract events
        events = []
        if self.events_df is not None:
            time_col = None
            for col in ["t_seconds", "Time (s)", "Time(s)", "Time", "time"]:
                if col in self.events_df.columns:
                    time_col = col
                    break

            if time_col:
                time_series = self.events_df[time_col]
                time_numeric = pd.to_numeric(time_series, errors="coerce")
                if time_numeric.isna().any():
                    time_td = pd.to_timedelta(time_series.astype(str), errors="coerce")
                    time_numeric = time_numeric.where(
                        time_numeric.notna(), time_td.dt.total_seconds()
                    )
                dropped = 0
                for idx, row in self.events_df.iterrows():
                    event_time = time_numeric.loc[idx]
                    if pd.isna(event_time) or not np.isfinite(event_time):
                        dropped += 1
                        continue
                    event_label = row.get("Label", f"Event {idx + 1}")
                    event_color = row.get("Color", "#888888")
                    events.append(EventSpec(float(event_time), event_label, event_color))
                log_fn = logger.warning if dropped else logger.info
                log_fn(
                    "Event time coercion complete",
                    extra={
                        "time_col": time_col,
                        "events_kept": len(events),
                        "events_dropped": dropped,
                    },
                )

        return RenderContext(
            trace_model=self.trace_model,
            vessel_frames=self.sample.snapshots,
            events=events,
            sample_name=self.sample.name,
        )

    def _on_render_progress(self, current: int, total: int):
        """Handle render progress update."""
        self._set_status_message(f"Rendering frame {current} / {total}...", tone="info")

    def _on_render_finished(self, frames: list[np.ndarray]):
        """Handle render completion."""
        self.rendered_frames = frames
        self.preview_player.load_frames(frames, self.current_spec.fps)

        self._set_status_message(f"✓ Rendered {len(frames)} frames successfully", tone="success")

        # Restore UI state
        self._restore_ui_after_render()

    def _on_render_error(self, error_msg: str):
        """Handle render error."""
        QMessageBox.critical(self, "Render Error", f"Failed to render animation:\n\n{error_msg}")

        self._set_status_message("✗ Render failed", tone="error")

        # Restore UI state
        self._restore_ui_after_render()

    def _on_render_cancelled(self):
        """Handle render cancellation."""
        self._set_status_message("⊗ Render cancelled by user", tone="error")

        logger.info("Render cancelled, UI restored")

        # Restore UI state
        self._restore_ui_after_render()

    def _cancel_render(self):
        """Cancel the current rendering operation."""
        if self.render_thread and self.render_thread.isRunning():
            self.render_thread.cancel()
            self.cancel_render_btn.setEnabled(False)  # Prevent multiple clicks
            self._set_status_message("Cancelling render...", tone="info")

    def _restore_ui_after_render(self):
        """Restore UI controls to normal state after rendering completes/fails/cancels."""
        self.refresh_btn.setVisible(True)
        self.cancel_render_btn.setVisible(False)
        self.cancel_render_btn.setEnabled(True)  # Re-enable for next render
        self.export_btn.setEnabled(True)
        self.is_rendering = False

    def _estimate_memory_mb(self, n_frames: int, width: int, height: int) -> float:
        """Estimate memory needed for rendered frames in MB.

        Args:
            n_frames: Number of frames to render
            width: Frame width in pixels
            height: Frame height in pixels

        Returns:
            Estimated memory usage in megabytes
        """
        # RGB frames: width * height * 3 bytes per pixel (uint8)
        bytes_per_frame = width * height * 3
        total_bytes = bytes_per_frame * n_frames
        memory_mb = total_bytes / (1024 * 1024)  # Convert to MB

        logger.debug(
            "Memory estimation",
            extra={
                "n_frames": n_frames,
                "resolution": f"{width}x{height}",
                "bytes_per_frame": bytes_per_frame,
                "total_mb": memory_mb,
            },
        )

        return memory_mb

    def _export_gif(self):
        """Export animation as GIF file."""
        if not self.rendered_frames:
            QMessageBox.information(
                self,
                "No Preview",
                "Please refresh the preview before exporting.",
            )
            return

        # Get export path
        default_name = f"{self.sample.name}_animation.gif"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GIF Animation",
            default_name,
            "GIF Files (*.gif)",
        )

        if not file_path:
            return

        # Show progress dialog
        progress = QProgressDialog("Exporting GIF...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        try:
            # Save GIF
            durations_ms = self.rendered_frame_durations_ms
            if durations_ms and len(durations_ms) != len(self.rendered_frames):
                logger.warning(
                    "Export duration count mismatch; using constant duration",
                    extra={
                        "frames": len(self.rendered_frames),
                        "durations": len(durations_ms),
                    },
                )
                durations_ms = None
            save_gif(
                self.rendered_frames,
                file_path,
                self.current_spec.fps,
                self.current_spec.loop_count,
                optimize=self.current_spec.optimize,
                quality=self.current_spec.quality,
                durations_ms=durations_ms,
            )

            progress.setValue(100)
            progress.close()

            QMessageBox.information(
                self,
                "Export Complete",
                f"GIF saved successfully:\n{file_path}",
            )

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to save GIF:\n\n{str(e)}",
            )

    def _export_static_frame(self):
        """Export a single rendered frame as PNG."""
        self._on_event_selection_changed()
        self._on_settings_changed()

        if self.current_spec.start_time_s >= self.current_spec.end_time_s:
            QMessageBox.warning(self, "Time Range Error", "Start time must be before end time.")
            return

        default_name = f"{self.sample.name}_frame.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Static Frame",
            default_name,
            "PNG Files (*.png)",
        )
        if not file_path:
            return

        frame = None
        if self.rendered_frames:
            idx = self.preview_player.get_current_frame_index()
            if idx < 0 or idx >= len(self.rendered_frames):
                idx = 0
            if 0 <= idx < len(self.rendered_frames):
                frame = self.rendered_frames[idx]

        if frame is None:
            try:
                synchronizer = FrameSynchronizer(
                    self.frame_times,
                    self.trace_model.time_full,
                    self.current_spec.start_time_s,
                    self.current_spec.end_time_s,
                )
                valid, error_msg = synchronizer.validate_time_range()
                if not valid:
                    QMessageBox.warning(self, "Time Range Error", error_msg)
                    return

                duration = self.current_spec.duration_s
                anim_t = max(0.0, min(duration, duration * 0.5))
                timing = synchronizer.get_frame_for_time(anim_t)
                ctx = self._create_render_context()
                renderer = AnimationRenderer(self.current_spec)
                frame = renderer.render_frame(ctx, timing)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"Failed to render static frame:\n\n{str(e)}",
                )
                return

        if frame is None:
            QMessageBox.critical(self, "Export Error", "Unable to render static frame.")
            return

        from PIL import Image

        try:
            Image.fromarray(frame).save(file_path, format="PNG")
            QMessageBox.information(
                self,
                "Export Complete",
                f"Static frame saved successfully:\n{file_path}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to save static frame:\n\n{str(e)}",
            )

    def _export_poster_figure(self):
        """Export a trace-dominant poster figure as PNG."""
        self._on_event_selection_changed()
        self._on_settings_changed()

        if self.current_spec.start_time_s >= self.current_spec.end_time_s:
            QMessageBox.warning(self, "Time Range Error", "Start time must be before end time.")
            return

        default_name = f"{self.sample.name}_poster.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Poster Figure",
            default_name,
            "PNG Files (*.png)",
        )
        if not file_path:
            return

        frame = self._select_poster_frame()
        renderer = PosterFigureRenderer(
            self.current_spec.output_width_px,
            self.current_spec.output_height_px,
        )
        image = renderer.render(
            trace_model=self.trace_model,
            start_time_s=self.current_spec.start_time_s,
            end_time_s=self.current_spec.end_time_s,
            show_inner=self.current_spec.trace_spec.show_inner,
            show_outer=self.current_spec.trace_spec.show_outer,
            y_range=self.current_spec.trace_spec.y_range,
            vessel_frame=frame,
            time_offset_s=self.current_spec.start_time_s
            if self.current_spec.display_time_zero
            else 0.0,
        )

        from PIL import Image

        try:
            Image.fromarray(image).save(file_path, format="PNG")
            QMessageBox.information(
                self,
                "Export Complete",
                f"Poster figure saved successfully:\n{file_path}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to save poster figure:\n\n{str(e)}",
            )

    def _select_poster_frame(self) -> np.ndarray | None:
        if not isinstance(self.sample.snapshots, np.ndarray) or self.sample.snapshots.size == 0:
            return None

        n_frames = len(self.sample.snapshots)
        if not self.frame_times or len(self.frame_times) != n_frames:
            return self.sample.snapshots[n_frames // 2]

        mid_time = (self.current_spec.start_time_s + self.current_spec.end_time_s) / 2.0
        times = np.asarray(self.frame_times, dtype=float)
        idx = int(np.argmin(np.abs(times - mid_time)))
        idx = max(0, min(n_frames - 1, idx))
        return self.sample.snapshots[idx]

    def closeEvent(self, event):
        """Handle window close event with proper thread cleanup.

        Ensures render thread is properly cancelled and cleaned up before
        the window closes to prevent crashes and zombie threads.
        """
        if self.render_thread and self.render_thread.isRunning():
            logger.info("Window closing during active render, cancelling thread")

            # Cancel the render thread
            self.render_thread.cancel()

            # Wait up to 5 seconds for thread to finish gracefully
            if not self.render_thread.wait(5000):
                logger.warning("Render thread did not finish within timeout, forcing termination")
                # Force termination as last resort
                self.render_thread.terminate()
                # Wait for termination to complete
                self.render_thread.wait()

            logger.info("Render thread cleaned up successfully")

        # Call parent closeEvent
        super().closeEvent(event)
