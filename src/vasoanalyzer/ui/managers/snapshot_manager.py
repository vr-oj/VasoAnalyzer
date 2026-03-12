# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""
SnapshotManager -- extracted snapshot/TIFF management logic.

All host state (snapshot_frames, snapshot_widget, trace_data, etc.) is accessed
via ``self._host`` which is expected to be the VasoAnalyzerApp main window.
"""

from __future__ import annotations

import contextlib
import html
import logging
import math
import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import tifffile
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from vasoanalyzer.core.timebase import page_for_time
from vasoanalyzer.io.tiffs import load_tiff, resolve_frame_times

if TYPE_CHECKING:
    from vasoanalyzer.core.project import SampleN

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (mirrored from main_window)
# ---------------------------------------------------------------------------
_TIME_SYNC_DEBUG = bool(os.getenv("VA_TIME_SYNC_DEBUG"))
_TIFF_PROMPT_THRESHOLD = 1000
_TIFF_REDUCED_TARGET_FRAMES = 400


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


class SnapshotManager(QObject):
    """Manages TIFF snapshot loading, display, playback, and synchronization."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):  # type: ignore[name-defined]  # noqa: F821
        super().__init__(parent)
        self._host = host

    # ------------------------------------------------------------------
    # Snapshot view mode
    # ------------------------------------------------------------------

    def _apply_snapshot_view_mode(self, should_show: bool) -> None:
        h = self._host
        stack = getattr(h, "snapshot_stack", None)
        widget = getattr(h, "snapshot_widget", None)
        if stack is not None:
            if widget is not None:
                stack.setCurrentWidget(widget)
            stack.setVisible(bool(should_show))

        if widget is not None:
            widget.setVisible(bool(should_show))

        self._update_snapshot_panel_layout()
        self._update_snapshot_rotation_controls()

    def _snapshot_has_image(self) -> bool:
        h = self._host
        widget = getattr(h, "snapshot_widget", None)
        if widget is not None and hasattr(widget, "has_image"):
            with contextlib.suppress(Exception):
                return bool(widget.has_image())
        return bool(h.snapshot_frames)

    def _update_snapshot_panel_layout(self) -> None:
        h = self._host
        layout = getattr(h, "_right_panel_layout", None)
        snapshot_card = getattr(h, "snapshot_card", None)
        table_card = getattr(h, "event_table_card", None)
        if layout is None or snapshot_card is None or table_card is None:
            return

        has_image = self._snapshot_has_image()
        viewer_enabled = bool(
            getattr(h, "snapshot_viewer_action", None)
            and h.snapshot_viewer_action.isChecked()
        )
        show_snapshot = bool(has_image and viewer_enabled)
        snapshot_card.setVisible(show_snapshot)

    def _update_snapshot_rotation_controls(self) -> None:
        """Enable or disable rotation buttons based on viewer state."""
        h = self._host
        buttons = (
            getattr(h, "rotate_ccw_btn", None),
            getattr(h, "rotate_cw_btn", None),
            getattr(h, "rotate_reset_btn", None),
        )
        can_rotate = (
            bool(h.snapshot_frames)
            and getattr(h, "snapshot_widget", None) is not None
            and self._snapshot_view_visible()
        )
        for btn in buttons:
            if btn is None:
                continue
            btn.setEnabled(can_rotate)

    def toggle_snapshot_viewer(self, checked: bool, *, source: str = "user") -> None:
        h = self._host
        if h._snapshot_panel_disabled_by_env:
            if h.snapshot_viewer_action and h.snapshot_viewer_action.isChecked():
                h.snapshot_viewer_action.blockSignals(True)
                h.snapshot_viewer_action.setChecked(False)
                h.snapshot_viewer_action.blockSignals(False)
            return
        if not checked:
            h._snapshot_viewer_pending_open = False

        from vasoanalyzer.core.project import SampleN

        if checked and not h.snapshot_frames and isinstance(h.current_sample, SampleN):
            stack = self._ensure_sample_snapshots_loaded(h.current_sample)
            if stack is not None:
                try:
                    self.load_snapshots(stack)
                except Exception:
                    log.debug("Failed to initialise snapshot viewer", exc_info=True)
                    h.snapshot_frames = []
                else:
                    h._snapshot_viewer_pending_open = False
            else:
                h._snapshot_viewer_pending_open = True
        has_snapshots = bool(h.snapshot_frames)
        should_show = bool(checked) and has_snapshots
        desired_action_state = bool(checked) and (
            has_snapshots or h._snapshot_viewer_pending_open
        )

        if (
            h.snapshot_viewer_action
            and h.snapshot_viewer_action.isChecked() != desired_action_state
        ):
            h.snapshot_viewer_action.blockSignals(True)
            h.snapshot_viewer_action.setChecked(desired_action_state)
            h.snapshot_viewer_action.blockSignals(False)

        self._apply_snapshot_view_mode(should_show)

        if not should_show:
            self.set_snapshot_metadata_visible(False)

        self._update_metadata_button_state()
        if source == "user":
            h._on_view_state_changed(reason="snapshot viewer visibility")

    # ------------------------------------------------------------------
    # TIFF probing and load strategy
    # ------------------------------------------------------------------

    def _reset_snapshot_loading_info(self) -> None:
        """Clear any cached snapshot loading metadata."""
        h = self._host
        h.snapshot_loading_info = None
        h.snapshot_frame_indices = []
        h.snapshot_total_frames = None
        h.snapshot_frame_stride = 1
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
        h = self._host
        stride = max(2, int(math.ceil(total_frames / _TIFF_REDUCED_TARGET_FRAMES)))
        approx_frames = int(math.ceil(total_frames / stride))
        stride_label = self._format_stride_label(stride)
        dialog = QMessageBox(h)
        dialog.setWindowTitle("Large TIFF detected")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"This TIFF contains {total_frames} frames. Loading all frames may be slow.")
        dialog.setInformativeText(
            f"Load all frames, or load a reduced set ({stride_label}, ~{approx_frames} frames)?"
        )
        all_btn = dialog.addButton("Load all frames", QMessageBox.ButtonRole.AcceptRole)
        reduced_btn = dialog.addButton("Load reduced set", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(all_btn)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == cancel_btn:
            return "cancel", None
        if clicked == reduced_btn:
            return "reduced", stride
        return "full", None

    # ------------------------------------------------------------------
    # Frame / trace time derivation
    # ------------------------------------------------------------------

    def _derive_frame_trace_time(
        self, n_frames: int
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """
        Use trace_df["TiffPage"] to produce canonical frame->time mapping.

        Returns (frame_trace_index, frame_trace_time) or (None, None) when unavailable.
        """
        h = self._host
        h.frame_trace_index = None
        h.frame_trace_time = None
        h.frame_times = []
        h._snapshot_sync_status_text = None
        h._snapshot_sync_partial_count = None

        if h.trace_data is None or "TiffPage" not in h.trace_data.columns:
            return None, None

        frame_indices = []
        info_indices = None
        if isinstance(h.snapshot_loading_info, Mapping):
            info_indices = h.snapshot_loading_info.get("frame_indices")
        if info_indices and len(info_indices) == n_frames:
            frame_indices = list(info_indices)
        elif h.snapshot_frame_indices and len(h.snapshot_frame_indices) == n_frames:
            frame_indices = list(h.snapshot_frame_indices)
        else:
            frame_indices = list(range(n_frames))

        try:
            mapping = dict(h.tiff_page_to_trace_idx)
            if not mapping:
                tiff_rows = h.trace_data[h.trace_data["TiffPage"].notna()].copy()
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

            expected_pages = h.snapshot_total_frames
            if expected_pages is None and frame_indices:
                try:
                    expected_pages = int(max(frame_indices) + 1)
                except Exception:
                    expected_pages = None
            if expected_pages is not None:
                h._refresh_tiff_page_times(expected_page_count=int(expected_pages))

            if h.tiff_page_times_valid and h.tiff_page_times:
                times = []
                frame_trace_index = np.full(n_frames, -1, dtype=int)
                invalid = False
                for idx, page in enumerate(frame_indices):
                    try:
                        page_int = int(page)
                    except Exception:
                        invalid = True
                        break
                    if page_int < 0 or page_int >= len(h.tiff_page_times):
                        invalid = True
                        break
                    time_val = h.tiff_page_times[page_int]
                    if not math.isfinite(time_val):
                        invalid = True
                        break
                    times.append(float(time_val))
                    trace_idx = mapping.get(page_int)
                    if trace_idx is not None:
                        frame_trace_index[idx] = int(trace_idx)
                if not invalid:
                    frame_trace_time = np.asarray(times, dtype=float)
                    h.frame_trace_index = frame_trace_index
                    h.frame_trace_time = frame_trace_time
                    h.frame_times = frame_trace_time.tolist()
                    h.snapshot_frame_indices = frame_indices
                    h._snapshot_sync_status_text = None
                    h._snapshot_sync_partial_count = 0
                    return frame_trace_index, frame_trace_time

            trace_times = pd.to_numeric(h.trace_data["Time (s)"], errors="coerce").to_numpy(
                dtype=float
            )
            result = resolve_frame_times(
                h.frames_metadata,
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
                h._snapshot_sync_partial_count = count
                h._snapshot_sync_status_text = f"Sync: Partial ({count} pages interpolated)"
            else:
                h._snapshot_sync_status_text = None
                h._snapshot_sync_partial_count = 0

            h.frame_trace_index = frame_trace_index
            h.frame_trace_time = frame_trace_time
            h.frame_times = frame_trace_time.tolist()
            h.snapshot_frame_indices = frame_indices

            try:
                span = (min(frame_indices), max(frame_indices)) if frame_indices else (None, None)
            except Exception:
                span = (None, None)
            info = (
                h.snapshot_loading_info
                if isinstance(h.snapshot_loading_info, Mapping)
                else {}
            )
            total_frames = info.get("total_frames", h.snapshot_total_frames)
            stride = info.get("frame_stride", h.snapshot_frame_stride)
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

    # ------------------------------------------------------------------
    # Loading snapshots from path / dialog
    # ------------------------------------------------------------------

    def _load_snapshot_from_path(self, file_path: str) -> bool:
        """Load a snapshot TIFF from ``file_path`` and update the viewer."""
        h = self._host

        self._reset_snapshot_loading_info()
        try:
            total_frames = self._probe_tiff_frame_count(file_path)
            max_frames = None
            chosen_stride = None
            if total_frames is not None:
                h.snapshot_total_frames = int(total_frames)
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
                QMessageBox.warning(h, "TIFF Warning", "Skipped empty or corrupted TIFF frames.")

            if not valid_frames:
                QMessageBox.warning(
                    h,
                    "TIFF Load Error",
                    "No valid frames were found in the dropped TIFF file.",
                )
                return False

            frame_stride = int(loading_info.get("frame_stride", chosen_stride or 1))
            total_frames_value = loading_info.get(
                "total_frames", h.snapshot_total_frames or len(valid_frames)
            )
            try:
                total_frames_value = int(total_frames_value)
            except Exception:
                total_frames_value = h.snapshot_total_frames or len(valid_frames)

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

            h.snapshot_frames = valid_frames
            h.frames_metadata = valid_metadata
            h.snapshot_loading_info = loading_info
            h.snapshot_frame_indices = valid_indices
            h.snapshot_frame_stride = frame_stride
            h.snapshot_total_frames = total_frames_value

            first_meta: dict[str, Any] = (
                h.frames_metadata[0] or {} if h.frames_metadata else {}
            )
            frame_trace_index, frame_trace_time = self._derive_frame_trace_time(
                len(h.snapshot_frames)
            )

            # Canonical path: use trace["TiffPage"] to align frames to Time (s)
            if frame_trace_time is not None:
                h.recording_interval = None
                _log_time_sync(
                    "VIDEO_LOAD",
                    sample=getattr(h.current_sample, "name", None),
                    path=os.path.basename(file_path),
                    frames=len(h.snapshot_frames),
                    frame_time_0=frame_trace_time[0] if len(frame_trace_time) else None,
                    frame_time_last=frame_trace_time[-1] if len(frame_trace_time) else None,
                    meta_keys=",".join(sorted((first_meta or {}).keys())),
                )
            else:
                fallback_interval = 0.14
                try:
                    fallback_result = resolve_frame_times(
                        h.frames_metadata,
                        n_frames=len(h.snapshot_frames),
                        frame_indices=valid_indices,
                        fps=None,
                        allow_fallback=True,
                    )
                except ValueError:
                    fallback_result = resolve_frame_times(
                        h.frames_metadata,
                        n_frames=len(h.snapshot_frames),
                        frame_indices=valid_indices,
                        fps=1.0 / fallback_interval,
                        allow_fallback=True,
                    )
                    fallback_result.warnings.append(
                        f"Frame times estimated using default interval {fallback_interval:.2f}s (no metadata)."
                    )

                h.frame_times = fallback_result.frame_times_s.tolist()
                if len(h.frame_times) >= 2:
                    diffs = np.diff(np.asarray(h.frame_times, dtype=float))
                    diffs = diffs[diffs > 0]
                    h.recording_interval = (
                        float(np.median(diffs)) if diffs.size else fallback_interval
                    )
                else:
                    h.recording_interval = fallback_interval

                _log_time_sync(
                    "VIDEO_LOAD_LEGACY",
                    sample=getattr(h.current_sample, "name", None),
                    path=os.path.basename(file_path),
                    frames=len(h.snapshot_frames),
                    interval=f"{h.recording_interval:.4f}"
                    if h.recording_interval
                    else "unknown",
                    frame_time_0=h.frame_times[0] if h.frame_times else None,
                    frame_time_1=h.frame_times[1] if len(h.frame_times) > 1 else None,
                    meta_keys=",".join(sorted((first_meta or {}).keys())),
                )

            self.compute_frame_trace_indices()
            canonical_times = (
                frame_trace_time
                if frame_trace_time is not None
                else np.asarray(h.frame_times, dtype=float)
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
                float(h.recording_interval) if h.recording_interval is not None else None
            )
            timebase_meta["frame_count"] = int(len(canonical_times))
            if h.current_sample is not None:
                meta = dict(h.current_sample.import_metadata or {})
                timebase_block = dict(meta.get("timebase") or {})
                tiff_block = dict(timebase_block.get("tiff") or {})
                tiff_block.update(timebase_meta)
                timebase_block["tiff"] = tiff_block
                meta["timebase"] = timebase_block
                h.current_sample.import_metadata = meta
            self._set_snapshot_data_source(h.snapshot_frames, canonical_times)

            if h.slider is not None:
                h.slider.blockSignals(True)
                h.slider.setRange(0, len(h.snapshot_frames) - 1)
                h.slider.setValue(0)
                h.slider.blockSignals(False)

            prev_btn = getattr(h, "prev_frame_btn", None)
            next_btn = getattr(h, "next_frame_btn", None)
            play_btn = getattr(h, "play_pause_btn", None)
            speed_label = getattr(h, "snapshot_speed_label", None)
            speed_combo = getattr(h, "snapshot_speed_combo", None)
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

            if h.current_sample is not None:
                try:
                    h.current_sample.snapshots = np.stack(h.snapshot_frames)
                    h.current_sample.snapshot_path = os.path.abspath(file_path)
                except Exception:
                    log.warning("Failed to stack snapshot frames", exc_info=True)
                h.mark_session_dirty()
                h.auto_save_project(reason="snapshot")

            status_note = None
            if h.snapshot_loading_info.get("is_subsampled"):
                stride_text = self._format_stride_label(
                    int(h.snapshot_loading_info.get("frame_stride", 1))
                )
                status_note = (
                    f"Reduced snapshot set loaded: {len(h.snapshot_frames)}/"
                    f"{h.snapshot_loading_info.get('total_frames')} frames "
                    f"({stride_text})"
                )
            elif h.snapshot_total_frames:
                status_note = (
                    f"Loaded {len(h.snapshot_frames)} frame(s)"
                    f" (original stack: {h.snapshot_total_frames})"
                )
            if status_note:
                h.statusBar().showMessage(status_note, 6000)

            # Update GIF Animator state after snapshots are loaded
            h._update_gif_animator_state()

            return True

        except Exception as e:
            QMessageBox.critical(h, "TIFF Load Error", f"Failed to load TIFF:\n{e}")
            return False

    def load_snapshot(self, checked: bool = False) -> None:
        """Load a snapshot from TIFF file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        h = self._host
        file_path, _ = QFileDialog.getOpenFileName(
            h, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if not file_path:
            return

        self._load_snapshot_from_path(file_path)

    def save_analysis(self) -> None:
        QMessageBox.information(
            self._host,
            "Save HDF5",
            "Legacy HDF5 files are no longer supported. Use Project > Save Project instead.",
        )

    def open_analysis(self, path=None) -> None:
        QMessageBox.information(
            self._host,
            "Import HDF5",
            "Legacy HDF5 files are no longer supported. Use Project > Open Project instead.",
        )

    # ------------------------------------------------------------------
    # Trace time helpers
    # ------------------------------------------------------------------

    def _trace_time_for_frame_number(self, frame: int | float | None) -> float | None:
        """Return canonical trace time for a given camera frame number."""
        h = self._host
        if frame is None or pd.isna(frame):
            return None
        frame_int = int(frame)
        idx = h.frame_number_to_trace_idx.get(frame_int)
        if idx is None or h.trace_time is None:
            return None
        if idx < 0 or idx >= len(h.trace_time):
            return None
        return float(h.trace_time[idx])

    # ------------------------------------------------------------------
    # Snapshot data source (v2 viewer binding)
    # ------------------------------------------------------------------

    def _set_snapshot_data_source(
        self, stack: Sequence[np.ndarray] | np.ndarray, frame_times: Sequence[float] | None
    ) -> None:
        """Bind a canonical snapshot data source for controller-driven viewing."""
        h = self._host
        viewer = getattr(h, "snapshot_widget", None)
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
            status = getattr(h, "_snapshot_sync_status_text", None)
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
                getattr(h, "trace_data", None),
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

    # ------------------------------------------------------------------
    # Load snapshots from numpy stack
    # ------------------------------------------------------------------

    def load_snapshots(self, stack) -> None:
        h = self._host
        h.snapshot_frames = [frame for frame in stack]
        if h.snapshot_frames:
            h.snapshot_frame_indices = list(range(len(h.snapshot_frames)))
            h.snapshot_frame_stride = 1
            h.snapshot_total_frames = len(h.snapshot_frames)
            h.snapshot_loading_info = {
                "total_frames": h.snapshot_total_frames,
                "loaded_frames": len(h.snapshot_frames),
                "frame_stride": 1,
                "frame_indices": h.snapshot_frame_indices,
                "is_subsampled": False,
            }
        else:
            self._reset_snapshot_loading_info()
            self._set_playback_state(False)
            if h.snapshot_widget is not None:
                h.snapshot_widget.clear()
        if h.snapshot_frames:
            canonical_times = None
            frame_trace_index, frame_trace_time = self._derive_frame_trace_time(
                len(h.snapshot_frames)
            )
            if frame_trace_time is not None:
                canonical_times = frame_trace_time
                h.recording_interval = None
            else:
                h.frame_times = [
                    idx * h.recording_interval for idx in range(len(h.snapshot_frames))
                ]
                canonical_times = np.asarray(h.frame_times, dtype=float)

            self.compute_frame_trace_indices()
            self.reset_snapshot_rotation()
            self._set_snapshot_data_source(h.snapshot_frames, canonical_times)
            if h.slider is not None:
                h.slider.blockSignals(True)
                h.slider.setRange(0, len(h.snapshot_frames) - 1)
                h.slider.setValue(0)
                h.slider.blockSignals(False)
            prev_btn = getattr(h, "prev_frame_btn", None)
            next_btn = getattr(h, "next_frame_btn", None)
            play_btn = getattr(h, "play_pause_btn", None)
            speed_label = getattr(h, "snapshot_speed_label", None)
            speed_combo = getattr(h, "snapshot_speed_combo", None)
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

    # ------------------------------------------------------------------
    # Frame <-> trace index mapping
    # ------------------------------------------------------------------

    def compute_frame_trace_indices(self) -> None:
        """Map each frame to the nearest trace index using canonical times."""
        h = self._host
        h.frame_trace_indices = []
        h.frame_trace_index = None

        if h.trace_time is None:
            return

        if h.frame_trace_time is not None and len(h.frame_trace_time):
            times = np.asarray(h.frame_trace_time, dtype=float)
        elif h.frame_times:
            times = np.asarray(h.frame_times, dtype=float)
        else:
            return

        idx = np.searchsorted(h.trace_time, times, side="left")
        idx = np.clip(idx, 0, len(h.trace_time) - 1)
        h.frame_trace_index = idx
        h.frame_trace_indices = idx

    def _time_for_frame(self, idx: int) -> float | None:
        """Return canonical seconds for the given frame index."""
        h = self._host
        if h.frame_trace_time is not None and idx < len(h.frame_trace_time):
            try:
                return float(h.frame_trace_time[idx])
            except (TypeError, ValueError):
                return None

        if h.frame_times and idx < len(h.frame_times):
            try:
                return float(h.frame_times[idx])
            except (TypeError, ValueError):
                return None
        return None

    def _frame_index_for_time_canonical(self, time_value: float) -> int | None:
        """Nearest frame index for a canonical time (seconds)."""
        h = self._host
        if not h.snapshot_frames:
            return None

        try:
            t_val = float(time_value)
        except (TypeError, ValueError):
            return None

        times = None
        if h.frame_trace_time is not None and len(h.frame_trace_time):
            times = np.asarray(h.frame_trace_time, dtype=float)
        elif h.frame_times:
            with contextlib.suppress(Exception):
                times = np.asarray(h.frame_times, dtype=float)

        if times is None or times.size == 0:
            return None

        return page_for_time(t_val, times, mode="nearest")

    # ------------------------------------------------------------------
    # Time jump (canonical)
    # ------------------------------------------------------------------

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
        h = self._host

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
        if snap_to_trace and h.trace_time is not None and len(h.trace_time):
            idx_trace = int(np.searchsorted(h.trace_time, t_val))
            idx_trace = max(0, min(idx_trace, len(h.trace_time) - 1))
            resolved_time = float(h.trace_time[idx_trace])
        h._time_cursor_time = resolved_time
        h._snapshot_play_time_s = float(resolved_time)

        # Update trace cursor + highlight.
        h._highlight_selected_event(resolved_time)
        is_playing_video = bool(
            getattr(h, "play_pause_btn", None) and h.play_pause_btn.isChecked()
        )
        plot_host = getattr(h, "plot_host", None)
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
            h.current_frame = frame_idx
            h.current_page = frame_idx
            h.page_float = float(frame_idx)
            if h.slider is not None and h.slider.value() != frame_idx:
                h.slider.blockSignals(True)
                h.slider.setValue(frame_idx)
                h.slider.blockSignals(False)
            if log.isEnabledFor(logging.DEBUG):
                tiff_page = self._tiff_page_for_frame(frame_idx)
                time_exact = self._trace_time_exact_for_page(tiff_page)
                log.debug(
                    "Trace->Frame sync: time=%s frame=%s tiff_page=%s time_exact=%s",
                    resolved_time,
                    frame_idx,
                    tiff_page,
                    time_exact,
                )

        if h.snapshot_frames:
            viewer = getattr(h, "snapshot_widget", None)
            if viewer is not None and getattr(viewer, "sync_enabled", True):
                with contextlib.suppress(Exception):
                    viewer.jump_to_time(resolved_time, source=src_label or "trace")
        h._on_view_state_changed(reason="time cursor moved")

    # ------------------------------------------------------------------
    # Frame display / navigation
    # ------------------------------------------------------------------

    def set_current_frame(self, idx, *, from_jump: bool = False, from_playback: bool = False) -> None:
        h = self._host
        if not h.snapshot_frames:
            return
        idx = max(0, min(int(idx), len(h.snapshot_frames) - 1))
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.jump_to_page(idx, source="external")
            return
        if h.slider is not None and h.slider.value() != idx:
            h.slider.blockSignals(True)
            h.slider.setValue(idx)
            h.slider.blockSignals(False)
        self._apply_frame_change(idx, from_playback=from_playback)

    def update_snapshot_size(self) -> None:
        widget = getattr(self._host, "snapshot_widget", None)
        if widget is not None:
            widget.update()

    # ------------------------------------------------------------------
    # Snapshot sampling badge
    # ------------------------------------------------------------------

    def _update_snapshot_sampling_badge(self) -> None:
        """Show or hide the reduced-load badge near the snapshot controls."""
        h = self._host
        label = getattr(h, "snapshot_subsample_label", None)
        if label is None:
            return
        info = h.snapshot_loading_info or {}
        if not isinstance(info, Mapping):
            info = {}
        loaded = info.get("loaded_frames") or (
            len(h.snapshot_frames) if h.snapshot_frames else None
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

    # ------------------------------------------------------------------
    # TIFF page mapping helpers
    # ------------------------------------------------------------------

    def _tiff_page_for_frame(self, frame_idx: int) -> int | None:
        """Return the original TIFF page index for the given loaded frame."""
        indices = self._host.snapshot_frame_indices or []
        if frame_idx < 0 or frame_idx >= len(indices):
            return None
        try:
            return int(indices[frame_idx])
        except Exception:
            return indices[frame_idx]

    def _trace_time_exact_for_page(self, tiff_page: int | None) -> float | None:
        """Return Time_s_exact for the trace row mapped to the given TIFF page."""
        h = self._host
        if tiff_page is None or h.trace_time_exact is None:
            return None
        try:
            trace_idx = h.tiff_page_to_trace_idx.get(int(tiff_page))
        except Exception:
            trace_idx = None
        if trace_idx is None:
            return None
        if trace_idx < 0 or trace_idx >= len(h.trace_time_exact):
            return None
        with contextlib.suppress(Exception):
            return float(h.trace_time_exact[int(trace_idx)])
        return None

    # ------------------------------------------------------------------
    # Frame change application
    # ------------------------------------------------------------------

    def _apply_frame_change(self, idx: int, *, from_playback: bool = False) -> None:
        h = self._host
        h.current_frame = idx
        h.current_page = idx
        if not from_playback:
            h.page_float = float(idx)
        frame_time = self._time_for_frame(idx)

        trace_idx = None
        trace_time = None
        tiff_page = self._tiff_page_for_frame(idx)
        time_exact = self._trace_time_exact_for_page(tiff_page)
        if h.frame_trace_index is not None and idx < len(h.frame_trace_index):
            trace_idx = int(h.frame_trace_index[idx])
            if h.trace_time is not None and trace_idx < len(h.trace_time):
                trace_time = float(h.trace_time[trace_idx])
        elif h.trace_time is not None and frame_time is not None:
            with contextlib.suppress(Exception):
                trace_idx = int(np.searchsorted(h.trace_time, frame_time))
                trace_idx = max(0, min(trace_idx, len(h.trace_time) - 1))
                trace_time = float(h.trace_time[trace_idx])

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
                "Frame->Trace sync: frame=%d tiff_page=%s trace_idx=%s time=%s time_exact=%s",
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

        h.update_slider_marker()
        self._update_snapshot_status(idx)
        self._update_metadata_display(idx)

    # ------------------------------------------------------------------
    # Snapshot status / metadata display
    # ------------------------------------------------------------------

    def _update_snapshot_status(self, idx: int) -> None:
        h = self._host
        self._update_snapshot_sampling_badge()
        total = len(h.snapshot_frames) if h.snapshot_frames else 0
        label = getattr(h, "snapshot_time_label", None)
        if label is None:
            return
        if total <= 0:
            label.setText("No TIFF loaded")
            return

        frame_number = idx + 1
        timestamp = None
        if h.frame_trace_time is not None and idx < len(h.frame_trace_time):
            try:
                timestamp = float(h.frame_trace_time[idx])
            except (TypeError, ValueError):
                timestamp = None
        elif h.frame_times and idx < len(h.frame_times):
            try:
                timestamp = float(h.frame_times[idx])
            except (TypeError, ValueError):
                timestamp = None
        if timestamp is None and h.recording_interval:
            try:
                timestamp = idx * float(h.recording_interval)
            except (TypeError, ValueError):
                timestamp = None
        total_time = None
        if h.frame_trace_time is not None and len(h.frame_trace_time):
            try:
                total_time = float(h.frame_trace_time[-1])
            except (TypeError, ValueError):
                total_time = None
        elif h.frame_times:
            try:
                total_time = float(h.frame_times[-1])
            except (TypeError, ValueError):
                total_time = None
        elif h.recording_interval:
            try:
                total_time = float(total - 1) * float(h.recording_interval)
            except (TypeError, ValueError):
                total_time = None
        info = h.snapshot_loading_info or {}
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
        h = self._host
        self._update_metadata_button_state()
        if not getattr(h, "frames_metadata", None):
            action = getattr(h, "action_snapshot_metadata", None)
            if action is not None:
                action.setText("Metadata\u2026")
            return
        if idx >= len(h.frames_metadata):
            return

        metadata = h.frames_metadata[idx] or {}
        tag_count = len(metadata)
        tag_label = "tag" if tag_count == 1 else "tags"
        action = getattr(h, "action_snapshot_metadata", None)
        if action is not None:
            action.setText(f"Metadata ({tag_count} {tag_label})")

        if not metadata:
            h.metadata_details_label.setText("No metadata for this frame.")
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

        h.metadata_details_label.setText("<br>".join(lines))

    def _snapshot_view_visible(self) -> bool:
        widget = getattr(self._host, "snapshot_widget", None)
        return bool(widget and widget.isVisible())

    def _update_metadata_button_state(self) -> None:
        h = self._host
        action = getattr(h, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(h, "frames_metadata", []))
        has_frames = bool(h.snapshot_frames)
        enabled = has_metadata and has_frames and self._snapshot_view_visible()

        if action is not None:
            action.setEnabled(enabled)
            if not enabled:
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
            action.setText("Metadata\u2026")

        if not enabled:
            h.metadata_panel.hide()
            h.metadata_details_label.setText("No metadata available.")
            return

        is_visible = self._snapshot_view_visible()
        should_show = bool(action and action.isChecked() and enabled)
        h.metadata_panel.setVisible(should_show)
        if not should_show and not is_visible:
            h.metadata_details_label.setText("No metadata available.")

    # ------------------------------------------------------------------
    # Speed / sync / loop toggles
    # ------------------------------------------------------------------

    def on_snapshot_speed_changed(self, value: float) -> None:
        h = self._host
        try:
            multiplier = float(value)
        except (TypeError, ValueError):
            multiplier = 1.0

        if not math.isfinite(multiplier) or multiplier <= 0:
            multiplier = 1.0

        h.snapshot_speed_multiplier = multiplier
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_speed_multiplier(multiplier)

    def on_snapshot_sync_toggled(self, checked: bool) -> None:
        h = self._host
        h.snapshot_sync_enabled = bool(checked)
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_sync_enabled(h.snapshot_sync_enabled)
        with contextlib.suppress(Exception):
            self._refresh_snapshot_sync_label()

    def on_snapshot_loop_toggled(self, checked: bool) -> None:
        """Handle loop playback checkbox toggle."""
        h = self._host
        h.snapshot_loop_enabled = bool(checked)
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_loop(bool(checked))

    def _reset_snapshot_speed(self) -> None:
        h = self._host
        h.snapshot_pps = float(getattr(h, "_snapshot_pps_default", 30.0))
        h.snapshot_speed_multiplier = 1.0

        if hasattr(h, "snapshot_speed_combo"):
            combo = getattr(h, "snapshot_speed_combo", None)
            if combo is not None:
                combo.blockSignals(True)
                for idx in range(combo.count()):
                    data = combo.itemData(idx)
                    if isinstance(data, (int, float)) and abs(float(data) - 1.0) < 0.01:
                        combo.setCurrentIndex(idx)
                        break
                combo.blockSignals(False)

        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_pps(h.snapshot_pps)
            with contextlib.suppress(Exception):
                viewer.set_speed_multiplier(h.snapshot_speed_multiplier)

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

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def _sync_time_cursor_to_snapshot(self) -> None:
        h = self._host
        frame_time = self._time_for_frame(h.current_frame)
        if frame_time is None:
            return
        self.jump_to_time(
            float(frame_time),
            from_playback=True,
            from_frame_change=True,
            source="video",
        )

    def _update_playback_button_state(self, playing: bool) -> None:
        h = self._host
        play_btn = getattr(h, "play_pause_btn", None)
        if play_btn is None:
            return
        play_btn.blockSignals(True)
        play_btn.setChecked(playing)
        play_btn.blockSignals(False)

        with contextlib.suppress(Exception):
            h._update_snapshot_playback_icons()
        tooltip = "Pause snapshot playback" if playing else "Play snapshot sequence"
        play_btn.setToolTip(tooltip)

    def _set_playback_state(self, playing: bool) -> None:
        """Control playback using the v2 viewer controller."""
        h = self._host
        if not h.snapshot_frames:
            playing = False
        play_btn = getattr(h, "play_pause_btn", None)
        was_playing = bool(play_btn.isChecked()) if play_btn is not None else False
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_playing(playing)
        if not playing and was_playing and h.snapshot_frames and h.snapshot_sync_enabled:
            self._sync_time_cursor_to_snapshot()

        self._update_playback_button_state(playing)

    def _on_snapshot_page_changed_v2(self, page_index: int, source: str) -> None:
        h = self._host
        if not h.snapshot_frames:
            return
        try:
            idx = int(page_index)
        except (TypeError, ValueError):
            return
        idx = max(0, min(idx, len(h.snapshot_frames) - 1))
        h.current_frame = idx
        h.current_page = idx
        h.page_float = float(idx)
        if h.slider is not None:
            h.slider.blockSignals(True)
            h.slider.setValue(idx)
            h.slider.blockSignals(False)
        h.update_slider_marker()
        self._update_snapshot_status(idx)
        self._update_metadata_display(idx)

    def _on_snapshot_playback_time_changed(self, trace_time: float) -> None:
        h = self._host
        try:
            time_val = float(trace_time)
        except (TypeError, ValueError):
            return
        if math.isfinite(time_val):
            self._sync_trace_cursor_to_time(time_val)
            self._set_snapshot_sync_time(time_val)

    def _on_snapshot_playing_changed(self, playing: bool) -> None:
        h = self._host
        viewer = getattr(h, "snapshot_widget", None)
        if viewer is not None:
            with contextlib.suppress(Exception):
                viewer.set_playing(bool(playing))
        self._update_playback_button_state(bool(playing))

    def toggle_snapshot_playback(self, checked: bool) -> None:
        h = self._host
        if checked and not h.snapshot_frames:
            self._set_playback_state(False)
            return
        self._set_playback_state(bool(checked))

    def _mapped_trace_time_for_page(self, page_index: int) -> float | None:
        h = self._host
        tiff_page = self._tiff_page_for_frame(page_index)
        if (
            tiff_page is not None
            and h.tiff_page_times_valid
            and 0 <= int(tiff_page) < len(h.tiff_page_times)
        ):
            return float(h.tiff_page_times[int(tiff_page)])
        if h.frame_trace_time is not None and page_index < len(h.frame_trace_time):
            with contextlib.suppress(Exception):
                return float(h.frame_trace_time[page_index])
        if h.frame_times and page_index < len(h.frame_times):
            with contextlib.suppress(Exception):
                return float(h.frame_times[page_index])
        return None

    def _sync_trace_cursor_to_time(self, trace_time: float) -> None:
        h = self._host
        h._time_cursor_time = float(trace_time)
        h._highlight_selected_event(float(trace_time))
        plot_host = getattr(h, "plot_host", None)
        if plot_host is None or not hasattr(plot_host, "set_time_cursor"):
            return
        with contextlib.suppress(Exception):
            plot_host.set_time_cursor(float(trace_time), visible=True)
        with contextlib.suppress(Exception):
            if hasattr(plot_host, "current_window") and hasattr(plot_host, "set_time_window"):
                window = plot_host.current_window()
                if window is not None:
                    x0, x1 = window
                    span = x1 - x0
                    if span > 0 and not (x0 <= trace_time <= x1):
                        new_x0 = trace_time - span * 0.20
                        plot_host.set_time_window(new_x0, new_x0 + span)

    # ------------------------------------------------------------------
    # Step / rotate / metadata visibility
    # ------------------------------------------------------------------

    def step_previous_frame(self) -> None:
        h = self._host
        if not h.snapshot_frames:
            return
        play_btn = getattr(h, "play_pause_btn", None)
        if play_btn is not None and play_btn.isChecked():
            self._set_playback_state(False)
        idx = (h.current_frame - 1) % len(h.snapshot_frames)
        self.set_current_frame(idx)

    def step_next_frame(self) -> None:
        h = self._host
        if not h.snapshot_frames:
            return
        play_btn = getattr(h, "play_pause_btn", None)
        if play_btn is not None and play_btn.isChecked():
            self._set_playback_state(False)
        idx = (h.current_frame + 1) % len(h.snapshot_frames)
        self.set_current_frame(idx)

    def rotate_snapshot_ccw(self) -> None:
        viewer = getattr(self._host, "snapshot_widget", None)
        if viewer is None:
            return
        rotate = getattr(viewer, "rotate_ccw_90", None)
        if callable(rotate):
            with contextlib.suppress(Exception):
                rotate()

    def rotate_snapshot_cw(self) -> None:
        viewer = getattr(self._host, "snapshot_widget", None)
        if viewer is None:
            return
        rotate = getattr(viewer, "rotate_cw_90", None)
        if callable(rotate):
            with contextlib.suppress(Exception):
                rotate()

    def reset_snapshot_rotation(self) -> None:
        viewer = getattr(self._host, "snapshot_widget", None)
        if viewer is None:
            return
        reset = getattr(viewer, "reset_rotation", None)
        if callable(reset):
            with contextlib.suppress(Exception):
                reset()
        self._update_snapshot_rotation_controls()

    def set_snapshot_metadata_visible(self, visible: bool) -> None:
        h = self._host
        action = getattr(h, "action_snapshot_metadata", None)
        has_metadata = bool(getattr(h, "frames_metadata", []))
        can_show = has_metadata and bool(h.snapshot_frames) and self._snapshot_view_visible()
        should_show = bool(visible) and can_show

        if action is not None and action.isChecked() != should_show:
            action.blockSignals(True)
            action.setChecked(should_show)
            action.blockSignals(False)

        h.metadata_panel.setVisible(should_show)
        if should_show:
            self._update_metadata_display(h.current_frame)
        else:
            if not can_show:
                h.metadata_details_label.setText("No metadata available.")
            self._update_metadata_button_state()

    # ------------------------------------------------------------------
    # Slider marker helpers
    # ------------------------------------------------------------------

    def _clear_slider_markers(self) -> None:
        """Remove existing slider markers from all axes."""
        h = self._host
        h._time_cursor_time = None
        h._time_cursor_visible = True
        if hasattr(h, "plot_host"):
            with contextlib.suppress(Exception):
                h.plot_host.set_time_cursor(None, visible=False)
        h._clear_event_highlight()
        markers = getattr(h, "slider_markers", None)
        if not markers:
            h.slider_markers = {}
            h._on_view_state_changed(reason="time cursor cleared")
            return
        for line in list(markers.values()):
            with contextlib.suppress(Exception):
                line.remove()
        markers.clear()
        h._on_view_state_changed(reason="time cursor cleared")

    # ------------------------------------------------------------------
    # Sync label / time
    # ------------------------------------------------------------------

    def _set_snapshot_sync_time(self, time_value: float | None) -> None:
        h = self._host
        if time_value is None or not math.isfinite(time_value):
            h._snapshot_sync_time = None
        else:
            h._snapshot_sync_time = float(time_value)
        self._refresh_snapshot_sync_label()

    def _refresh_snapshot_sync_label(self) -> None:
        h = self._host
        label = getattr(h, "snapshot_sync_label", None)
        if label is None:
            return
        if not bool(getattr(h, "snapshot_sync_enabled", True)):
            label.setText("Synced: \u2014")
            return
        time_value = getattr(h, "_snapshot_sync_time", None)
        if isinstance(time_value, (int, float)) and math.isfinite(time_value):
            label.setText(f"Synced: {time_value:.3f} s")
            return

        mode_key = (getattr(h, "_snapshot_sync_mode", "") or "").lower()
        if mode_key == "event":
            label.setText("Synced: Event")
        elif mode_key == "cursor":
            label.setText("Synced: Cursor")
        else:
            label.setText("Synced: \u2014")

    # ------------------------------------------------------------------
    # Sample-level snapshot viewer state
    # ------------------------------------------------------------------

    def _update_snapshot_viewer_state(self, sample: "SampleN") -> None:
        h = self._host
        if h._snapshot_panel_disabled_by_env:
            if h.snapshot_viewer_action:
                h.snapshot_viewer_action.setEnabled(False)
                h.snapshot_viewer_action.blockSignals(True)
                h.snapshot_viewer_action.setChecked(False)
                h.snapshot_viewer_action.blockSignals(False)
            return
        has_stack = isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0
        asset_available = bool(
            sample.snapshot_role and sample.asset_roles.get(sample.snapshot_role)
        )
        path_available = bool(sample.snapshot_path)
        should_enable = has_stack or asset_available or path_available
        desired_visibility = h._pending_snapshot_visibility
        if desired_visibility is not None:
            h._pending_snapshot_visibility = None

        if h.snapshot_viewer_action:
            h.snapshot_viewer_action.setEnabled(should_enable)
            if not should_enable:
                h.snapshot_viewer_action.blockSignals(True)
                h.snapshot_viewer_action.setChecked(False)
                h.snapshot_viewer_action.blockSignals(False)
                h.snapshot_frames = []
                h.frames_metadata = []
                h.frame_times = []
                self._set_playback_state(False)
                if h.snapshot_widget is not None:
                    h.snapshot_widget.clear()
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

    def _ensure_sample_snapshots_loaded(self, sample: "SampleN") -> np.ndarray | None:
        h = self._host
        if isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0:
            return sample.snapshots

        if h._snapshot_load_token is not None and h._snapshot_loading_sample is sample:
            return None

        project_path = getattr(h.current_project, "path", None)
        asset_id = None
        if sample.snapshot_role and sample.asset_roles:
            asset_id = sample.asset_roles.get(sample.snapshot_role)

        token = object()
        h._snapshot_load_token = token
        h._snapshot_loading_sample = sample

        from vasoanalyzer.ui.main_window import _SnapshotLoadJob

        job = _SnapshotLoadJob(
            sample=sample,
            token=token,
            project_path=project_path,
            asset_id=asset_id,
            snapshot_path=sample.snapshot_path,
            snapshot_format=sample.snapshot_format,
        )
        job.signals.progressChanged.connect(h._update_sample_load_progress)
        job.signals.finished.connect(self._on_snapshot_load_finished)
        h.statusBar().showMessage("Loading snapshots\u2026", 0)
        h._thread_pool.start(job)
        return None

    def _on_snapshot_load_finished(
        self,
        token: object,
        sample: "SampleN",
        stack: np.ndarray | None,
        error: str | None,
    ) -> None:
        h = self._host
        if token != h._snapshot_load_token or sample is not h._snapshot_loading_sample:
            return

        h._snapshot_load_token = None
        h._snapshot_loading_sample = None
        if stack is not None:
            sample.snapshots = stack
            h.statusBar().showMessage("Snapshots ready", 2000)
            if sample is h.current_sample:
                should_show = bool(
                    h._snapshot_viewer_pending_open
                    or (h.snapshot_viewer_action and h.snapshot_viewer_action.isChecked())
                )
                if should_show:
                    try:
                        self.load_snapshots(stack)
                        h._snapshot_viewer_pending_open = False
                        self.toggle_snapshot_viewer(True, source="data")
                    except Exception:
                        log.error("Failed to initialise snapshot viewer", exc_info=True)
                        h.snapshot_frames = []
                        self.toggle_snapshot_viewer(False, source="data")
                # Update GIF Animator state after snapshots are loaded
                h._update_gif_animator_state()
        else:
            h._snapshot_viewer_pending_open = False
            message = error or "Snapshot load failed"
            h.statusBar().showMessage(message, 6000)
            self.toggle_snapshot_viewer(False, source="data")
