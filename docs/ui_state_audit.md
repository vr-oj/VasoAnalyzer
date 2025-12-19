# UI State Persistence Audit

## Capture/restore flow (per-sample)
- Capture: `VasoAnalyzerApp.gather_sample_state` in `src/vasoanalyzer/ui/main_window.py` (called on sample switch, manual save, autosave, close).
- Restore: `VasoAnalyzerApp.apply_sample_state` in `src/vasoanalyzer/ui/main_window.py`, invoked from `SampleLoaderMixin._render_sample` with `state_to_apply = project_state.get(id(sample), sample.ui_state)` in `src/vasoanalyzer/ui/mixins/sample_loader_mixin.py`.
- Cache: `_cached_sample_state` gated by `_sample_state_dirty` (invalidated by `mark_session_dirty`, `_handle_axis_xlim_changed`, `_on_plot_host_time_window_changed`, `_apply_channel_toggle*`, `_on_autoscale_y_triggered`, and some explicit assignments).
- Disk: sample `ui_state` is stored in SQLite dataset `extra["ui_state"]` via `_build_sample_extra` and loaded via `_dataset_to_sample` in `src/vasoanalyzer/core/project.py`. Project-level UI uses `project_ui_state` in SQLite meta.
- Before save: `_sync_events_from_ui_state` in `src/vasoanalyzer/services/project_service.py` copies `event_table_data` into `sample.events_data` so edited events persist in both UI state and the stored events table.

## State map (per-sample)
| State key | Captured in | Restored in | Backend constraints |
| --- | --- | --- | --- |
| `data_quality` | `_set_samples_data_quality` in `src/vasoanalyzer/ui/main_window.py` | Not restored in `apply_sample_state` (used by tree icon logic) | N/A |
| `figure_slides` | `_on_figure_state_saved` / `_get_sample_figure_slides` in `src/vasoanalyzer/ui/main_window.py` | Used by figure composer open flow | N/A |
| `event_table_data` | `gather_sample_state` in `src/vasoanalyzer/ui/main_window.py` | `apply_sample_state` in same file | Restored even for embedded fast path |
| `event_label_meta` | `gather_sample_state` | `apply_sample_state` (with fallback and normalization) | Restored even for embedded fast path |
| `event_table_path` | `gather_sample_state` | `apply_sample_state` | N/A |
| `table_fontsize` | `gather_sample_state` | `apply_sample_state` | Skipped for embedded fast path |
| `pins` | `gather_sample_state` | `apply_sample_state` | Matplotlib: annotate on `ax`; PyQtGraph: `inner_track.add_pin`; skipped for embedded fast path |
| `plot_style` | `gather_sample_state` (`get_current_plot_style`) | `apply_sample_state` (`apply_plot_style`) | Works both backends; restored for embedded fast path |
| `style_settings` | `apply_plot_style(..., persist=True)` stores into `sample.ui_state` | `apply_sample_state` | Works both backends; restored for embedded fast path |
| `grid_visible` | `gather_sample_state` | `apply_sample_state` | Matplotlib: `ax.grid`; PyQtGraph: per-track grid; skipped for embedded fast path |
| `inner_trace_visible` | `gather_sample_state` | `apply_sample_state` | Matplotlib: layout/line visibility; PyQtGraph: `set_channel_visible`; restored for embedded fast path |
| `outer_trace_visible` | `gather_sample_state` | `apply_sample_state` | Same as above |
| `avg_pressure_visible` | `gather_sample_state` | `apply_sample_state` | Same as above |
| `set_pressure_visible` | `gather_sample_state` | `apply_sample_state` | Same as above |
| `axis_settings.x.label` | `gather_sample_state` | `apply_sample_state` | Skipped for embedded fast path |
| `axis_settings.y.label` | `gather_sample_state` | `apply_sample_state` | Skipped for embedded fast path |
| `axis_settings.y_outer.label` | `gather_sample_state` (when `ax2`) | `apply_sample_state` | Skipped for embedded fast path |
| `legend_settings` | `gather_sample_state` | `apply_sample_state` (`apply_legend_settings`) | Skipped for embedded fast path |
| `plot_layout` | `_serialize_plot_layout` in `src/vasoanalyzer/ui/main_window.py` | `_apply_pending_plot_layout` | PlotHost layout only; skipped for embedded fast path |
| `axis_xlim` | `_collect_plot_view_state` | `apply_sample_state` via `_apply_time_window` | Matplotlib uses `ax.get_xlim`; PyQtGraph uses `plot_host.current_window`; skipped for embedded fast path |
| `axis_ylim` | `_collect_plot_view_state` (Matplotlib only) | `apply_sample_state` | PyQtGraph uses `pyqtgraph_track_state` instead; skipped for embedded fast path |
| `axis_outer_ylim` | `_collect_plot_view_state` (Matplotlib only) | `apply_sample_state` | PyQtGraph uses `pyqtgraph_track_state` instead; skipped for embedded fast path |
| `pyqtgraph_track_state` | `_collect_plot_view_state` (PyQtGraph only) | `_apply_pyqtgraph_track_state` | PyQtGraph only; skipped for embedded fast path |

## Top issues blocking "exactly how I left it"
1. Several UI changes never mark the session dirty, so close/autosave can skip persistence entirely (channel toggles, grid toggle, annotation toggles, Matplotlib axis dialog changes). This loses per-sample state even though it exists in memory.
2. Some state updates do not invalidate the sample-state cache, so `gather_sample_state` can return stale data: `toggle_grid` in `src/vasoanalyzer/ui/plotting.py`, `toggle_annotation` in `src/vasoanalyzer/ui/main_window.py`, and Matplotlib axis dialog changes in `src/vasoanalyzer/ui/dialogs/unified_settings_dialog.py`.
3. Matplotlib y-limit changes are never observed (no `ylim_changed` callbacks), so `axis_ylim` and `axis_outer_ylim` are often stale in cached state. This affects toolbar zoom/pan and axis dialog edits.
4. Cursor/trace position is not persisted at all: `_time_cursor_time`, `_time_cursor_visible`, and focused event row are runtime-only. Reload always resets cursor and selection.
5. Embedded dataset fast path intentionally skips restoring axis limits, grid, pins, plot layout, legend settings, and PyQtGraph track state. This is a performance optimization but breaks "exactly how I left it" for embedded datasets.
6. Event-line visibility and label-mode toggles are runtime only (not in `sample.ui_state`), so they reset on reload unless changed through the style dialog.

## Minimal change plan (smallest diff)
1. Add a lightweight helper to mark view-state changes: call `_invalidate_sample_state_cache()` and `mark_session_dirty()` from `toggle_grid`, `toggle_annotation`, and channel toggle handlers.
2. For Matplotlib, connect `ylim_changed` callbacks in `_bind_primary_axis_callbacks` and invalidate/mark dirty on y-axis changes (include `ax2` when present).
3. Persist cursor focus state under `SampleN.ui_state` (example: `ui_state["time_cursor"] = {"t": float, "visible": bool}` and `ui_state["focused_event_row"] = int | None`) and restore in `apply_sample_state` after event rows are populated.
4. Persist event-line visibility and label mode under `SampleN.ui_state` (example: `ui_state["event_lines_visible"]`, `ui_state["event_label_mode"]`) and restore in `apply_sample_state`.
5. Keep embedded fast path lightweight: consider restoring only `axis_xlim` and toggles; continue skipping plot layout, track state, pins, and legend changes to avoid PyQtGraph stalls.

## Performance notes (embedded datasets)
- Do not apply full plot layouts or track-state restores during load; `ensure_channels` and repeated autoscale calls are the main slow paths.
- Avoid recreating pins/annotations on load; these trigger multiple expensive redraws in PyQtGraph.
- Prefer restoring minimal view state (time window + channel toggles + plot style) and defer any heavy operations until explicit user action.

## Validation plan
- Manual test (Matplotlib backend, non-embedded):
  1. Open a project and sample.
  2. Toggle inner/outer/avg/set, toggle grid, change x and y ranges via toolbar, edit axis labels in the settings dialog.
  3. Toggle event lines and label mode, add a pin, select an event row (cursor moves).
  4. Save, close, reopen. Verify all above states restore.
- Manual test (PyQtGraph backend, non-embedded):
  1. Adjust time window, toggle autoscale Y, reorder tracks/visibility via layout controls.
  2. Toggle channels and grid, set event label options via style dialog.
  3. Save, reopen, verify `axis_xlim` + `pyqtgraph_track_state` + layout visibility.
- Manual test (embedded dataset):
  1. Repeat toggle and time-window steps; ensure load time stays acceptable.
  2. Confirm intentionally skipped restores (layout, pins, legend) remain skipped.
- Smoke check (no tests): `python -m compileall src/vasoanalyzer`.
