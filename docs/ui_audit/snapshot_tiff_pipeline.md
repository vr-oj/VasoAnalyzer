# Snapshot/TIFF Pipeline Audit (Facts)

## Pipeline summary (facts only)

1) Snapshot TIFF is fully materialized in memory when loaded.

- Loading from project assets or external TIFF resolves into a numpy stack:
  - `src/vasoanalyzer/ui/main_window.py:_SnapshotLoadJob._load_from_path()` -> `load_tiff()` -> list of frames -> `np.stack`.
  - `src/vasoanalyzer/ui/main_window.py:_load_snapshot_from_path()` -> `load_tiff()` -> list of frames -> stored as `self.snapshot_frames` list; optionally `np.stack` into `sample.snapshots`.
- `src/vasoanalyzer/io/tiffs.py:load_tiff()` explicitly loads all requested pages into a list of `np.ndarray` frames.

2) Frame data passed to the viewer is a numpy ndarray (per-frame).

- `src/vasoanalyzer/ui/main_window.py:_set_snapshot_data_source()` wraps a list of numpy frames in `SnapshotStackDataSource`.
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py:SnapshotStackDataSource.get_frame_at_time()` returns a single frame (numpy ndarray).
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py:_refresh_frame()` emits that frame.
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py:set_frame()` receives a numpy array and routes to `QtSnapshotRenderer`.

3) Time -> frame mapping occurs in two places:

- Canonical mapping (trace time to frame index):
  - `src/vasoanalyzer/ui/main_window.py:_derive_frame_trace_time()` uses trace `TiffPage` and `Time (s)` via `resolve_frame_times()`.
  - `src/vasoanalyzer/io/tiffs.py:resolve_frame_times()` delegates to `src/vasoanalyzer/core/timebase.py:resolve_tiff_frame_times()`.
- Runtime mapping for cursor/event scrub:
  - `src/vasoanalyzer/ui/main_window.py:_frame_index_for_time_canonical()` uses `np.argmin` against `frame_trace_time` or `frame_times`.
  - `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py:SnapshotStackDataSource.get_frame_at_time()` uses `np.argmin` on `frame_times`.

4) Frame conversion for rendering happens in the Qt snapshot renderer.

- `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py:numpy_to_qimage()` normalizes grayscale/RGB to `uint8` and builds a QImage.
- `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py:QtSnapshotRenderer.set_frame()` uses the cache and passes the QImage to `QtFrameView`.

5) Playback is PPS-based and runs on the UI thread.

- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py:SnapshotViewerController` manages flipbook-style playback at configurable pages/second (default 30 PPS).
- Controller timer: `_playback_timer.timeout` → `_on_playback_tick()` → `page_float += pps * dt_s` → `set_frame_index(source="playback")`.
- Trace synchronization uses canonical page→time mapping: `_page_times[page_index]` emitted via `playback_time_changed` signal.
- All of the above run synchronously on the UI thread (no worker threads during playback).

6) Playback architecture (controller-based).

- **Controller:** `SnapshotViewerController` owns all playback state (`_playing`, `_playback_pps`, `_page_float`).
- **Flipbook model:** Advances `page_float` at fixed PPS rate, independent of experiment time.
- **Trace sync:** Page→time mapping via `_page_times` array (extracted from data source `frame_times`).
- **Signals:**
  - `page_changed(index, source)` for UI updates
  - `playback_time_changed(trace_time)` for trace cursor sync
  - `playing_changed(bool)` for playback state
- **Legacy code removed:** Time-based timer (`snapshot_timer`) and `advance_snapshot_frame()` removed in cleanup.

## Diagram

```
[TIF stack on disk]
   |
   | load_tiff (tifffile) -> list[np.ndarray]
   v
[np.stack] -> sample.snapshots (ndarray) or snapshot_frames (list)
   |
   | _set_snapshot_data_source -> SnapshotStackDataSource(list, frame_times)
   v
SnapshotViewerController.set_trace_time(t)
   |
   | get_frame_at_time (np.argmin)
   v
SnapshotViewerWidget.set_frame(np.ndarray)
   |
   | QtSnapshotRenderer.set_frame -> numpy_to_qimage -> QtFrameView.paintEvent
   v
Qt render (no ImageView)
```

## Notes

- Snapshot viewing is Qt-only; PyQtGraph is used for plots only.

## Conclusion (in-memory vs file-backed)

Frames are loaded fully into memory (list of numpy arrays and often a stacked numpy array). Playback uses in-memory frames only; no on-demand disk-backed TIFF reads occur during playback.
