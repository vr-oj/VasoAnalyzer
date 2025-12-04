# Main-window trace/event/video sync – Phase 1 notes

## Phase 2 implementation hooks (current branch)
- Added `jump_to_time(t, *, from_event=False, from_playback=False, from_frame_change=False)` to drive trace cursor + video via one path. Playback (`_apply_frame_change`), PG timeline (`_on_snapshot_time_changed`), and event clicks now call this instead of bespoke mappings.
- `frame_times` are normalized to seconds on TIFF load (ms heuristics + unit stripping); `_frame_index_for_time_canonical` / `_time_for_frame` are the single helpers for frame↔time.
- Event-table focus uses `event_time` → `jump_to_time` (Frame column is no longer used to drive TIFF); manual/plot-added events stop inventing `time/recording_interval` frames and instead store the nearest trace index.

## Event table column semantics (plan)
- Current headers (from `EventTableModel.set_events`): `["Event", "Time (s)", "ID (µm)", [optional OD/pressure], "Trace idx (legacy)"]`; tooltip “Imported from the events table; legacy trace/frame hint. Trace/video sync is driven by event time (Time (s)).”
- The column holds legacy/imported values (often nearest trace index), not the canonical video frame. Event clicks route through `event_time → jump_to_time`; the trace idx is a hint only.
- Remaining frame uses: `_frame_index_from_event_row` still parses the Frame column, but `_focus_event_row` only uses it as a fallback; `_frame_index_for_time` now delegates to `_frame_index_for_time_canonical`. No other paths treat Frame as authoritative for video.

## Snapshot viewer defaults (plan)
- Viewers: legacy QLabel/slider stack vs `SnapshotViewPG` (PyQtGraph). Both are created and added to `snapshot_stack`; `_apply_snapshot_view_mode` chooses which widget is shown.
- Control: View → “Use PyQtGraph snapshot viewer” (`action_use_pg_snapshot`, now checked by default). `_use_pg_snapshot_viewer` consults this flag; PG shows when enabled.
- Current default: PG viewer is now the default for fresh sessions; legacy remains available via the same toggle.

## Components and current time state
- `VasoAnalyzerApp` holds the shared state: `trace_data["Time (s)"]` is the main timeline, `event_times`/`event_table_data` store event rows, and snapshot state is tracked via `snapshot_frames`, `frame_times`, `recording_interval` (default 0.14 s), and `frame_trace_indices`.
- Snapshot viewer: legacy QLabel + slider/timer plus the PyQtGraph `SnapshotViewPG`. `SnapshotViewPG.currentTimeChanged` feeds back into the main window via `_on_snapshot_time_changed` (`src/vasoanalyzer/ui/main_window.py:9320`).
- Time cursor state lives in `_time_cursor_time` and is driven by `plot_host.set_time_cursor` plus `_highlight_selected_event`.

## Event-table click flow (event → trace/video)
- Signal path: `EventTableWidget.cellClicked` → `table_row_clicked` → `_focus_event_row` (`src/vasoanalyzer/ui/main_window.py:10809`).
- Row lookup: `event_time = event_table_data[row][1]` (seconds). Raw frame column is read via `_frame_index_from_event_row` (prefers col 5 then 4).
- If no usable frame, `_frame_index_for_time(event_time)` picks `argmin(|frame_times - event_time|)` using raw `frame_times` (no scaling) (`src/vasoanalyzer/ui/main_window.py:10923`).
- With a frame index present and snapshots loaded, `set_current_frame(frame_idx)` is called; otherwise just highlights the event on the trace.
- Event frame values originate from `load_project_events` (frames forwarded from the CSV if present, otherwise nearest trace index) or from manual/plot-added events where `frame_number = time / recording_interval` (defaults to 0.14 s), so the Frame column often encodes trace indices, not video frames.

## Playback → trace cursor flow
- Legacy playback: slider/timer → `change_frame` → `_apply_frame_change` (`src/vasoanalyzer/ui/main_window.py:9458`). PG playback: `SnapshotViewPG` emits `currentTimeChanged(t)` → `_on_snapshot_time_changed` (`src/vasoanalyzer/ui/main_window.py:9320`) → `_frame_index_for_time(t)` → `set_current_frame`.
- `_apply_frame_change` sets `current_frame`, forwards to the active viewer, derives `frame_time` from `frame_times[idx]` or `idx * recording_interval`, logs, highlights the event cursor at `frame_time`, then calls `update_slider_marker`.
- `update_slider_marker` uses `frame_trace_indices` (if available) to map frame → trace index → `trace_data["Time (s)"]`, otherwise falls back to raw `frame_times` or `idx * recording_interval`, then updates `_time_cursor_time` and the plot cursor (`src/vasoanalyzer/ui/main_window.py:9759`).
- `SnapshotViewPG` computes `t` for signals as `frame_times[idx]` if provided, else the index (`src/vasoanalyzer/ui/panels/snapshot_view_pg.py:437`), so the playback path stays consistent with whatever `frame_times` were seeded.

## TIFF load path and frame-time derivation
- `_load_snapshot_from_path` (`src/vasoanalyzer/ui/main_window.py:8880`): loads TIFF via `vasoanalyzer.io.tiffs.load_tiff`, extracts `recording_interval` from the first metadata entry using `Rec_intvl`/`FrameInterval`/`FrameTime` (divides by 1000 if >1), otherwise defaults to 0.14 s.
- `frame_times` are built as `meta.get("FrameTime", idx * recording_interval)` per frame; **FrameTime is not unit-normalized** (left as-is from metadata). When metadata is absent, `idx * recording_interval` is used.
- `compute_frame_trace_indices` scales `frame_times` onto the trace span: `scale = (t_trace[-1]-t_trace[0]) / (frame_times[-1]-frame_times[0])`, `adjusted = (frame_times - frame_times[0]) * scale + t_trace[0]`, then `searchsorted` into `trace_data["Time (s)"]` to map each frame to a trace index (`src/vasoanalyzer/ui/main_window.py:9285`).
- `frame_times` themselves remain unscaled and are reused by `_frame_index_for_time` and `SnapshotViewPG` for event jumps and playback signals.

## Suspected divergence points / hacks
- Event clicks prefer the Frame column even when it encodes trace indices (from `load_trace_and_events` or manual additions) rather than video frames; once a TIFF is loaded, those raw frame numbers drive `set_current_frame`, causing mismatches.
- Event → frame fallback uses `_frame_index_for_time` against **raw** `frame_times` (potentially in ms or on a different span) instead of the scaled mapping in `frame_trace_indices`. Playback stays self-consistent because it uses `frame_times` throughout, so the event path is the odd one out.
- Metadata handling normalizes `Rec_intvl`/`FrameInterval` but leaves `FrameTime` untouched, so `frame_times` can be in ms while event times are in seconds.
- The fixed default `recording_interval = 0.14` is reused for manual event frame numbers and for snapshot stacks without metadata, even if the actual video fps differs.
- Two playback controllers exist (legacy timer vs `SnapshotViewPG`’s timer); they converge in `set_current_frame`, but there is no central `jump_to_time` API—each path performs its own conversions.

## Diagnostics added (enable with `VA_TIME_SYNC_DEBUG=1` or logger DEBUG)
- `[SYNC] VIDEO_LOAD`: after TIFF load with sample, path, frames, interval, first frame times.
- `[SYNC] PLAYBACK_FRAME`: each `set_current_frame` application with frame_time, mapped trace_idx/trace_time.
- `[SYNC] EVENT_FOCUS`: event-table activation showing source, event_time, frame from row vs frame from time fallback, chosen target frame.
- `[SYNC] PG_TIME`: PG timeline changes with emitted time and mapped frame.

## Phase 2 target model (sketch)
- **Canonical axis:** `t` in seconds from experiment start. Trace (`trace_data["Time (s)"]`) is the source of truth for span and offsets.
- **Mappings:**  
  - Trace: index → `t = trace_time[idx]`.  
  - Events: store/load in canonical seconds; if legacy Frame present, convert once using known video fps/offset.  
  - Video/TIFF: frame → `t = video_t0 + frame_idx / fps` (derive fps/interval from metadata with explicit unit normalization).
- **Unified API:** add `jump_to_time(t)` (or `seek_time(t)`) on `VasoAnalyzerApp` that sets `_time_cursor_time`, drives `plot_host`, chooses nearest snapshot frame via a single mapping (scaled `frame_trace_indices`), updates snapshot viewer, and (optionally) re-focuses the nearest event row.
- **Single conversion path:** event-table click → compute `t_event` once → `jump_to_time(t_event)`; playback tick → derive `t` from frame index using normalized fps/offset → same `jump_to_time` (without altering selection). Avoid per-path +1/-1 hacks; express any offsets (`trace_t0`, `video_t0`) explicitly and reuse them everywhere.
