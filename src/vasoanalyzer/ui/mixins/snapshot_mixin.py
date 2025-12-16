# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Snapshot viewer functionality for VasoAnalyzer main window."""

import html
import io
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QStyle, QWidget

from vasoanalyzer.core.project import SampleN, close_project_ctx, open_project_ctx
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.io.tiffs import load_tiff

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PyQt5.QtWidgets import (
        QAction,
        QComboBox,
        QLabel,
        QSlider,
        QStatusBar,
        QToolButton,
        QWidget,
    )


class SnapshotMixin:
    """Mixin class providing snapshot viewer and playback functionality."""

    if TYPE_CHECKING:
        snapshot_viewer_action: QAction | None
        current_project: ProjectContext | None
        current_sample: SampleN | None
        project_ctx: ProjectContext | None
        snapshot_card: QWidget | None
        snapshot_label: QLabel
        slider: QSlider
        snapshot_controls: QWidget
        snapshot_frames: list[np.ndarray]
        frames_metadata: list[dict[str, Any]]
        frame_times: list[float]
        current_frame: int
        recording_interval: float
        snapshot_speed_multiplier: float
        snapshot_speed_default_index: int
        snapshot_speed_combo: QComboBox
        snapshot_speed_label: QLabel
        prev_frame_btn: QToolButton
        next_frame_btn: QToolButton
        play_pause_btn: QToolButton
        snapshot_timer: QTimer
        metadata_panel: QWidget
        metadata_details_label: QLabel
        snapshot_time_label: QLabel
        action_snapshot_metadata: QAction | None
        snapshot_speed_presets: list[tuple[str, float]]

        def statusBar(self) -> QStatusBar: ...

        def compute_frame_trace_indices(self) -> None: ...

        def mark_session_dirty(self, reason: str | None = None) -> None: ...

        def auto_save_project(self, reason: str | None = None) -> None: ...

        def _clear_slider_markers(self) -> None: ...

        def update_slider_marker(self) -> None: ...

        def style(self) -> QStyle: ...

    def _message_parent(self) -> QWidget | None:
        """Return QWidget parent for message boxes when available."""

        if isinstance(self, QWidget):
            return cast(QWidget, self)
        return None

    def _update_snapshot_viewer_state(self, sample: SampleN) -> None:
        has_stack = isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
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

    def _ensure_sample_snapshots_loaded(self, sample: SampleN) -> np.ndarray | None:
        snapshots = sample.snapshots
        if isinstance(snapshots, np.ndarray) and snapshots.size > 0:
            return snapshots

        project_path = getattr(self.current_project, "path", None)
        asset_id = None
        if sample.snapshot_role and sample.asset_roles:
            asset_id = sample.asset_roles.get(sample.snapshot_role)

        ctx = getattr(self, "project_ctx", None)
        repo = ctx.repo if isinstance(ctx, ProjectContext) else None
        owned_ctx = None
        data = None

        if repo is None and project_path:
            try:
                owned_ctx = open_project_ctx(project_path)
                repo = owned_ctx.repo
            except Exception:
                repo = None

        if repo is not None and asset_id:
            try:
                data = repo.get_asset_bytes(asset_id)
            except Exception:
                data = None

        if owned_ctx is not None:
            close_project_ctx(owned_ctx)

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
                result = stack if isinstance(stack, np.ndarray) else np.stack(stack)
                sample.snapshots = result
                return result
            except Exception:
                log.debug(
                    "Failed to decode snapshot stack for %s",
                    sample.name,
                    exc_info=True,
                )

        if sample.snapshot_path and Path(sample.snapshot_path).exists():
            try:
                frames, _, _ = load_tiff(sample.snapshot_path, metadata=False)
                if frames:
                    result = np.stack(frames)
                    sample.snapshots = result
                    return result
            except Exception:
                log.debug("Failed to load snapshot TIFF for %s", sample.name, exc_info=True)

        return None

    def toggle_snapshot_viewer(self, checked: bool):
        if checked and not self.snapshot_frames and isinstance(self.current_sample, SampleN):
            stack = self._ensure_sample_snapshots_loaded(self.current_sample)
            if stack is not None:
                try:
                    self.load_snapshots(stack)
                except Exception:
                    log.debug("Failed to initialise snapshot viewer", exc_info=True)
                    self.snapshot_frames = []
        has_snapshots = bool(self.snapshot_frames)
        should_show = bool(checked) and has_snapshots

        if self.snapshot_viewer_action and self.snapshot_viewer_action.isChecked() != should_show:
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

    def _load_snapshot_from_path(self, file_path: str) -> bool:
        """Load a snapshot TIFF from ``file_path`` and update the viewer."""

        try:
            frames, frames_metadata, _ = load_tiff(file_path)
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
                    self._message_parent(),
                    "TIFF Warning",
                    "Skipped empty or corrupted TIFF frames.",
                )

            if not valid_frames:
                QMessageBox.warning(
                    self._message_parent(),
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
                    self.frame_times.append(meta.get("FrameTime", idx * self.recording_interval))
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
            QMessageBox.critical(
                self._message_parent(),
                "TIFF Load Error",
                f"Failed to load TIFF:\n{e}",
            )
            return False

    def load_snapshot(self):
        # 1) Prompt for TIFF
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if not file_path:
            return

        self._load_snapshot_from_path(file_path)

    def load_snapshots(self, stack):
        self.snapshot_frames = [frame for frame in stack]
        if self.snapshot_frames:
            self.frame_times = [
                idx * self.recording_interval for idx in range(len(self.snapshot_frames))
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
                    q_img = QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888)
                else:
                    raise ValueError(f"Unsupported TIFF frame format: {frame.shape}")
            else:
                raise ValueError(f"Unknown TIFF frame dimensions: {frame.shape}")

            target_width = self.event_table.viewport().width()
            if target_width <= 0:
                target_width = self.snapshot_label.width()
            pix = QPixmap.fromImage(q_img).scaledToWidth(target_width, Qt.SmoothTransformation)
            self.snapshot_label.setFixedSize(pix.width(), pix.height())
            self.snapshot_label.setPixmap(pix)
        except Exception as e:
            log.error("Error displaying frame %s: %s", index, e)

    def update_snapshot_size(self):
        if not self.snapshot_frames:
            return
        self.display_frame(self.current_frame)

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
            self.snapshot_time_label.setText(f"Frame {frame_number} / {total} @ {timestamp:.2f} s")

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
        can_show = has_metadata and bool(self.snapshot_frames) and self.snapshot_label.isVisible()
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

    def _snapshot_style(
        self,
        ax=None,
        ax2=None,
        event_text_objects=None,
        pinned_points=None,
        od_line=None,
    ):
        from .constants import DEFAULT_STYLE

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

        return style
