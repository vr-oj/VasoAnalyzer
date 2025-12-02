# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# mypy: ignore-errors

"""Sample loading mixin for VasoAnalyzer main window.

This mixin contains all methods related to loading samples, traces, events,
and snapshots into the application.
"""

import contextlib
import copy
import io
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
)

from vasoanalyzer.core.project import (
    Experiment,
    SampleN,
    close_project_ctx,
    open_project_ctx,
    save_project_file,
)
from vasoanalyzer.core.project_context import ProjectContext
from vasoanalyzer.io.events import find_matching_event_file, load_events
from vasoanalyzer.io.tiffs import load_tiff
from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.io.traces import load_trace
from vasoanalyzer.services.cache_service import DataCache, cache_dir_for_project
from vasoanalyzer.services.types import ProjectRepository
from vasoanalyzer.ui.dialogs.relink_dialog import MissingAsset, RelinkDialog

from ..constants import DEFAULT_LEGEND_SETTINGS, DEFAULT_STYLE

log = logging.getLogger(__name__)


class SampleLoaderMixin:
    """Mixin class containing all sample loading functionality."""

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
            and (sample.analysis_result_keys is None or bool(sample.analysis_result_keys))
        )

        ctx = getattr(self, "project_ctx", None)
        project_path = (
            ctx.path
            if isinstance(ctx, ProjectContext)
            else getattr(self.current_project, "path", None)
        )
        repo = ctx.repo if isinstance(ctx, ProjectContext) else None
        load_async = bool((repo or project_path) and (needs_trace or needs_events or needs_results))

        self._prepare_sample_view(sample)

        if load_async:
            self.statusBar().showMessage(f"Loading {sample.name}…", 2000)
            self._begin_sample_load_job(
                sample,
                token,
                repo,
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
        self.event_label_meta = []

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
    ) -> None:
        job = _SampleLoadJob(
            repo,
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
        trace_df: pd.DataFrame | None,
        events_df: pd.DataFrame | None,
        analysis_results: dict[str, Any] | None,
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

    def _on_sample_load_error(self, token: object, sample: SampleN, message: str) -> None:
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
            style = sample.ui_state.get("style_settings") or sample.ui_state.get("plot_style")
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
                first_label = labels[0] if labels else None
                log.info(
                    "Project load: sample '%s' using %d events from project data (first=%r)",
                    sample.name,
                    len(labels),
                    first_label,
                )
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
                    trace["Outer Diameter"].values if "Outer Diameter" in trace.columns else None
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
        self._reset_channel_view_defaults()
        self.xlim_full = None
        self.ylim_full = None
        self.legend_settings = copy.deepcopy(DEFAULT_LEGEND_SETTINGS)
        self.update_plot()
        self.compute_frame_trace_indices()
        self.load_project_events(labels, times, frames, diam, od)
        state_to_apply = self.project_state.get(id(sample), getattr(sample, "ui_state", None))
        self.apply_sample_state(state_to_apply)
        log.info("Sample loaded with %d events", len(labels))

        if self.current_project is not None:
            if not isinstance(self.current_project.ui_state, dict):
                self.current_project.ui_state = {}
            if self.current_experiment:
                self.current_project.ui_state["last_experiment"] = self.current_experiment.name
            self.current_project.ui_state["last_sample"] = sample.name

        self._update_snapshot_viewer_state(sample)
        self._update_home_resume_button()
        self._update_metadata_panel(sample)

    def _ensure_sample_snapshots_loaded(self, sample: SampleN) -> np.ndarray | None:
        if isinstance(sample.snapshots, np.ndarray) and sample.snapshots.size > 0:
            return sample.snapshots

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
                log.debug("Failed to load snapshot TIFF for %s", sample.name, exc_info=True)

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
        from vasoanalyzer.app.openers import open_samples_in_dual_view as _open_dual_view

        return _open_dual_view(self, samples)

    def trace_loader(self):
        from vasoanalyzer.io.traces import load_trace

        return load_trace

    @property
    def event_loader(self):
        from vasoanalyzer.io.events import load_events

        return load_events

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
        self._reset_channel_view_defaults()
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
            self.event_label_meta = []
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
            QMessageBox.critical(self, "Trace Load Error", f"Failed to load trace file:\n{e}")
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
            trace_obj = Path(file_path).expanduser().resolve(strict=False)
            sample_name = os.path.splitext(os.path.basename(file_path))[0]
            sample = SampleN(name=sample_name)
            self._update_sample_link_metadata(sample, "trace", trace_obj)
            if isinstance(self.trace_data, pd.DataFrame) and not self.trace_data.empty:
                with contextlib.suppress(Exception):
                    sample.trace_data = self.trace_data.copy(deep=True)

            event_path = find_matching_event_file(file_path)
            if event_path and os.path.exists(event_path):
                event_obj = Path(event_path).expanduser().resolve(strict=False)
                self._update_sample_link_metadata(sample, "events", event_obj)

            if snapshots is not None:
                try:
                    sample.snapshots = np.stack(snapshots)
                except Exception:
                    log.debug(
                        "Failed to materialise snapshot stack for %s", sample_name, exc_info=True
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
                QMessageBox.warning(self, "TIFF Warning", "Skipped empty or corrupted TIFF frames.")

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

    def load_trace(self, t, d, od=None):
        import pandas as pd

        data = {"Time (s)": t, "Inner Diameter": d}
        if od is not None:
            data["Outer Diameter"] = od
        self.trace_data = self._prepare_trace_dataframe(pd.DataFrame(data))
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
        self.event_label_meta = [dict() for _ in self.event_labels]
        self.event_table_data = []
        has_od = od_before is not None
        if not has_od:
            for lbl, diam in zip(labels, diam_before, strict=False):
                self.event_table_data.append((lbl, 0.0, diam, 0))
        else:
            for lbl, diam_i, diam_o in zip(labels, diam_before, od_before, strict=False):
                self.event_table_data.append((lbl, 0.0, diam_i, diam_o, 0))
        self.populate_table()

    def load_project_events(self, labels, times, frames, diam_before, od_before=None):
        self.event_labels = list(labels)
        self.event_label_meta = [dict() for _ in self.event_labels]
        if times is not None:
            self.event_times = pd.to_numeric(times, errors="coerce").tolist()
        else:
            self.event_times = []

        if frames is not None:
            self.event_frames = (
                pd.to_numeric(pd.Series(frames), errors="coerce").fillna(0).astype(int).tolist()
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
                strict=False,
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
                    strict=False,
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
                    strict=False,
                ):
                    if pd.isna(t):
                        continue
                    self.event_table_data.append((lbl, float(t), float(diam), int(fr)))

        if self.event_table_data:
            log.info(
                "DEBUG load: event_table_data rows=%s first_label=%r",
                len(self.event_table_data),
                self.event_table_data[0][0],
            )
        else:
            log.info("DEBUG load: event_table_data rows=0")

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
