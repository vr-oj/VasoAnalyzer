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
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py:set_frame()` receives a numpy array and routes to `SnapshotViewPG`.

3) Time -> frame mapping occurs in two places:

- Canonical mapping (trace time to frame index):
  - `src/vasoanalyzer/ui/main_window.py:_derive_frame_trace_time()` uses trace `TiffPage` and `Time (s)` via `resolve_frame_times()`.
  - `src/vasoanalyzer/io/tiffs.py:resolve_frame_times()` delegates to `src/vasoanalyzer/core/timebase.py:resolve_tiff_frame_times()`.
- Runtime mapping for playback/scrub:
  - `src/vasoanalyzer/ui/main_window.py:_frame_index_for_time_canonical()` uses `np.argmin` against `frame_trace_time` or `frame_times`.
  - `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py:SnapshotStackDataSource.get_frame_at_time()` uses `np.argmin` on `frame_times`.

4) Frame conversion for rendering happens in SnapshotViewPG.

- `src/vasoanalyzer/ui/panels/snapshot_view_pg.py:SnapshotViewPG._normalize_stack()` converts grayscale to `float32` and RGB/RGBA to `uint8`.
- `src/vasoanalyzer/ui/panels/snapshot_view_pg.py:SnapshotViewPG.set_stack()` calls `ImageView.setImage()` with `autoRange/autoLevels`.
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py:_coerce_pixmap()` (QImage/QPixmap path) is used only if the frame is not an ndarray.

5) Playback timer runs on the UI thread.

- `src/vasoanalyzer/ui/shell/init_ui.py` connects `snapshot_timer.timeout` to `advance_snapshot_frame`.
- `src/vasoanalyzer/ui/main_window.py:advance_snapshot_frame()` -> `set_current_frame()` -> `_apply_frame_change()` -> `jump_to_time()` -> controller update.
- All of the above run synchronously on the UI thread (no worker threads during playback).

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
   | SnapshotViewPG.set_stack -> _normalize_stack -> ImageView.setImage
   v
Qt/pyqtgraph render
```

## Conclusion (in-memory vs file-backed)

Frames are loaded fully into memory (list of numpy arrays and often a stacked numpy array). Playback uses in-memory frames only; no on-demand disk-backed TIFF reads occur during playback.
