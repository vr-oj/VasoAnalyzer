"""Main window for GIF animation creation and preview.

This module provides the primary UI for the GIF Animator feature,
following the Figure Composer window pattern.
"""

import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QScrollArea, QFileDialog, QMessageBox, QProgressDialog, QColorDialog,
    QSizePolicy, QDialog, QDialogButtonBox, QRubberBand,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect
from PyQt5.QtGui import QColor, QImage, QPixmap

from .specs import AnimationSpec, TracePanelSpec
from .frame_synchronizer import FrameSynchronizer, FrameTimingInfo
from .renderer import AnimationRenderer, RenderContext, EventSpec, save_gif, estimate_gif_size_mb
from .preview_player import PreviewPlayerWidget


class RenderThread(QThread):
    """Background thread for rendering frames to avoid blocking UI."""

    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list)  # rendered frames
    error = pyqtSignal(str)  # error message

    def __init__(self, renderer, ctx, timings):
        super().__init__()
        self.renderer = renderer
        self.ctx = ctx
        self.timings = timings

    def run(self):
        """Run rendering in background thread."""
        try:
            frames = self.renderer.render_all_frames(
                self.ctx,
                self.timings,
                progress_callback=lambda curr, total: self.progress.emit(curr, total),
            )
            self.finished.emit(frames)
        except Exception as e:
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
        self.is_rendering = False
        self.render_thread: RenderThread | None = None

        # Extract frame times
        self.frame_times = self._extract_frame_times()

        # Setup UI
        self.setWindowTitle(f"GIF Animator - {sample.name}")
        self.setGeometry(100, 100, 1200, 700)

        self._init_ui()

    def _extract_frame_times(self) -> list[float]:
        """Extract frame timestamps using TiffPage synchronization logic.

        This follows the same logic as the main window's _derive_frame_trace_time()
        to properly sync TIFF frames with trace data using the TiffPage column.
        """
        n_frames = len(self.sample.snapshots)

        # Try to use TiffPage column for proper synchronization
        # Check for both CSV column names (TiffPage, Time (s)) and database column names (tiff_page, t_seconds)
        trace_data = self.sample.trace_data
        if trace_data is not None:
            # Determine which column names to use
            tiff_col = None
            time_col_name = None

            if "tiff_page" in trace_data.columns:
                tiff_col = "tiff_page"
            elif "TiffPage" in trace_data.columns:
                tiff_col = "TiffPage"

            if "t_seconds" in trace_data.columns:
                time_col_name = "t_seconds"
            elif "Time (s)" in trace_data.columns:
                time_col_name = "Time (s)"

            if tiff_col is not None and time_col_name is not None:
                try:
                    # Build mapping from TiffPage to trace row index
                    tiff_rows = trace_data[trace_data[tiff_col].notna()].copy()
                    if not tiff_rows.empty:
                        tiff_rows.loc[:, tiff_col] = pd.to_numeric(
                            tiff_rows[tiff_col], errors="coerce"
                        )
                        tiff_rows = tiff_rows[tiff_rows[tiff_col].notna()]
                        mapping = {
                            int(row[tiff_col]): int(idx)
                            for idx, row in tiff_rows.iterrows()
                        }

                        if mapping:
                            # Map each TIFF frame to its trace time
                            frame_times = []
                            time_col = pd.to_numeric(trace_data[time_col_name], errors="coerce")

                            for frame_idx in range(n_frames):
                                trace_idx = mapping.get(frame_idx)
                                if trace_idx is not None and 0 <= trace_idx < len(time_col):
                                    frame_time = float(time_col.iloc[trace_idx])
                                    frame_times.append(frame_time)
                                else:
                                    # Frame not in mapping - estimate
                                    if frame_times:
                                        # Use last known time + interval
                                        interval = 0.14
                                        frame_times.append(frame_times[-1] + interval)
                                    else:
                                        frame_times.append(frame_idx * 0.14)

                            return frame_times
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Failed to derive frame times from TiffPage: {e}"
                    )

        # Fallback: Try to get from ui_state
        if self.sample.ui_state:
            frame_times = self.sample.ui_state.get('snapshot_frame_times', None)
            if frame_times:
                return frame_times

        # Final fallback: Estimated uniform spacing
        recording_interval = 0.14  # Default
        if self.sample.ui_state:
            recording_interval = self.sample.ui_state.get('recording_interval', 0.14)

        return [i * recording_interval for i in range(n_frames)]

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
            vessel_width_ratio=0.5,
            use_tiff_frames=True,
            trace_spec=TracePanelSpec(),
        )
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
        # Select last event by default
        if self.end_event_combo.count() > 0:
            self.end_event_combo.setCurrentIndex(self.end_event_combo.count() - 1)
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
        for col in ['t_seconds', 'Time (s)', 'Time(s)', 'Time', 'time']:
            if col in self.events_df.columns:
                time_col = col
                break

        if time_col is None:
            return

        # Convert time column to numeric (handles hh:mm:ss format)
        time_series = self.events_df[time_col].copy()
        time_numeric = pd.to_numeric(time_series, errors='coerce')

        # If conversion failed (all NaN), try parsing as hh:mm:ss timedelta
        if time_numeric.isna().all():
            try:
                time_td = pd.to_timedelta(time_series.astype(str), errors='coerce')
                if not time_td.isna().all():
                    time_numeric = time_td.dt.total_seconds()
            except Exception:
                pass

        # Get TIFF time range for filtering
        tiff_start = self.frame_times[0] if self.frame_times else 0
        tiff_end = self.frame_times[-1] if self.frame_times else float('inf')

        # Only show events within TIFF range
        valid_events = []
        for idx, row in self.events_df.iterrows():
            event_time = time_numeric.iloc[idx] if not pd.isna(time_numeric.iloc[idx]) else 0.0
            # Include events within TIFF range
            if tiff_start <= event_time <= tiff_end:
                event_label = row.get('Label', row.get('Event', f'Event {idx + 1}'))
                valid_events.append((event_time, event_label))

        # If no events in range, show all with warning
        if not valid_events:
            combo.addItem(f"⚠ No events in TIFF range (0-{tiff_end:.1f}s)", userData=None)
            # Fall back to showing all events anyway
            for idx, row in self.events_df.iterrows():
                event_time = time_numeric.iloc[idx] if not pd.isna(time_numeric.iloc[idx]) else 0.0
                event_label = row.get('Label', row.get('Event', f'Event {idx + 1}'))
                combo.addItem(f"{event_label} ({event_time:.2f}s)", userData={'time': event_time, 'label': event_label})
        else:
            # Show only valid events
            for event_time, event_label in valid_events:
                combo.addItem(f"{event_label} ({event_time:.2f}s)", userData={'time': event_time, 'label': event_label})

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

        self.fast_trace_checkbox = QCheckBox("Fast trace (static)")
        self.fast_trace_checkbox.setChecked(True)
        self.fast_trace_checkbox.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.fast_trace_checkbox)

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

        # Export button
        self.export_btn = QPushButton("Export GIF...")
        self.export_btn.clicked.connect(self._export_gif)
        layout.addWidget(self.export_btn)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("QLabel { color: #666; font-size: 10px; }")
        layout.addWidget(self.status_label)

        group.setLayout(layout)
        return group

    def _on_event_selection_changed(self):
        """Handle event selection change."""
        # Update spec with new time range
        start_data = self.start_event_combo.currentData()
        end_data = self.end_event_combo.currentData()

        if start_data and end_data:
            self.current_spec.start_time_s = start_data['time']
            self.current_spec.end_time_s = end_data['time']
            self.current_spec.start_event_label = start_data['label']
            self.current_spec.end_event_label = end_data['label']

            # Update time range display
            duration = self.current_spec.duration_s
            self.time_range_label.setText(
                f"Time range: {self.current_spec.start_time_s:.2f}s - "
                f"{self.current_spec.end_time_s:.2f}s (duration: {duration:.2f}s)"
            )

            # Validate time range
            if self.current_spec.start_time_s >= self.current_spec.end_time_s:
                self.status_label.setText("⚠ Start time must be before end time")
                self.status_label.setStyleSheet("QLabel { color: #ff6b6b; }")
            else:
                self.status_label.setText("")

    def _on_settings_changed(self):
        """Handle settings change (update spec)."""
        # Update spec from UI controls
        self.current_spec.fps = self.fps_spin.value()
        self.current_spec.playback_speed = self.speed_spin.value()
        self.current_spec.loop_count = 0 if self.loop_checkbox.isChecked() else 1
        self.current_spec.output_width_px = self.width_spin.value()
        self.current_spec.output_height_px = self.height_spin.value()
        self.current_spec.use_tiff_frames = self.use_tiff_frames_checkbox.isChecked()
        self._update_vessel_ratio_for_aspect()
        self.current_spec.vessel_crop_rect = self._load_crop_rect()

        # Trace settings
        self.current_spec.trace_spec.show_inner = self.show_inner_checkbox.isChecked()
        self.current_spec.trace_spec.show_outer = self.show_outer_checkbox.isChecked()
        self.current_spec.trace_spec.show_events = self.show_events_checkbox.isChecked()
        self.current_spec.trace_spec.show_time_indicator = self.time_indicator_checkbox.isChecked()
        self.current_spec.trace_spec.fast_render = self.fast_trace_checkbox.isChecked()

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
        estimated_size_mb = estimate_gif_size_mb(
            self.current_spec.output_width_px,
            self.current_spec.output_height_px,
            n_frames,
        )

        self.status_label.setText(
            f"Rendering {n_frames} frames... (estimated size: {estimated_size_mb:.1f} MB)"
        )
        self.status_label.setStyleSheet("QLabel { color: #4a9eff; }")

        # Create render context
        ctx = self._create_render_context()

        # Render in background thread
        renderer = AnimationRenderer(self.current_spec)

        self.render_thread = RenderThread(renderer, ctx, timings)
        self.render_thread.progress.connect(self._on_render_progress)
        self.render_thread.finished.connect(self._on_render_finished)
        self.render_thread.error.connect(self._on_render_error)

        # Disable controls during rendering
        self.refresh_btn.setEnabled(False)
        self.export_btn.setEnabled(False)

        self.render_thread.start()

    def _create_render_context(self) -> RenderContext:
        """Create render context with current data."""
        # Extract events
        events = []
        if self.events_df is not None:
            time_col = None
            for col in ['Time (s)', 'Time(s)', 'Time', 'time']:
                if col in self.events_df.columns:
                    time_col = col
                    break

            if time_col:
                for idx, row in self.events_df.iterrows():
                    event_time = row[time_col]
                    event_label = row.get('Label', f'Event {idx + 1}')
                    event_color = row.get('Color', '#888888')
                    events.append(EventSpec(event_time, event_label, event_color))

        return RenderContext(
            trace_model=self.trace_model,
            vessel_frames=self.sample.snapshots,
            events=events,
            sample_name=self.sample.name,
        )

    def _on_render_progress(self, current: int, total: int):
        """Handle render progress update."""
        self.status_label.setText(f"Rendering frame {current} / {total}...")

    def _on_render_finished(self, frames: list[np.ndarray]):
        """Handle render completion."""
        self.rendered_frames = frames
        self.preview_player.load_frames(frames, self.current_spec.fps)

        self.status_label.setText(f"✓ Rendered {len(frames)} frames successfully")
        self.status_label.setStyleSheet("QLabel { color: #51cf66; }")

        # Re-enable controls
        self.refresh_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def _on_render_error(self, error_msg: str):
        """Handle render error."""
        QMessageBox.critical(self, "Render Error", f"Failed to render animation:\n\n{error_msg}")

        self.status_label.setText(f"✗ Render failed")
        self.status_label.setStyleSheet("QLabel { color: #ff6b6b; }")

        # Re-enable controls
        self.refresh_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

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
            save_gif(
                self.rendered_frames,
                file_path,
                self.current_spec.fps,
                self.current_spec.loop_count,
                optimize=self.current_spec.optimize,
                quality=self.current_spec.quality,
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
