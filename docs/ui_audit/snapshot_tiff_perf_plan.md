# Snapshot/TIFF Performance Plan

## Bottleneck class (primary)

Primary: UI thread blocking due to synchronous updates.

Supporting observations (code locations):
- `src/vasoanalyzer/ui/main_window.py:_SnapshotLoadJob._load_from_path()` loads all TIFF frames into memory; playback does not hit disk I/O per frame.
- `src/vasoanalyzer/ui/main_window.py:advance_snapshot_frame()` is driven by a `QTimer` on the UI thread, then calls `_apply_frame_change()` and `jump_to_time()` synchronously.
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py:_refresh_frame()` emits `frame_changed` directly; the slot executes on the UI thread.
- Qt backend: `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py:set_frame()` calls `QtSnapshotRenderer.set_frame()` for each frame update (QImage conversion + paint).
- Experimental PyQtGraph backend: `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py:SnapshotViewPG._normalize_stack()` performs dtype conversions (float32/uint8) on every update.
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py:SnapshotStackDataSource.get_frame_at_time()` uses `np.argmin` (O(n)) for each update; cost grows with frame count.
- `src/vasoanalyzer/ui/main_window.py:_apply_frame_change()` also drives plot updates; heavy plotting work competes with frame rendering on the same thread.

## Tiered plan

### Tier 1 (must-have, minimal risk)

1) Latest-wins coalescing for frame updates
- Modules: `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py`, `src/vasoanalyzer/ui/main_window.py`
- Idea: queue only the newest requested time/index and drop intermediate updates during scrubbing/playback (singleShot + pending time).
- Acceptance: scrubbing never freezes UI >100 ms; no backlog of pending updates during rapid slider drags.

2) Skip redundant updates when frame index/time is unchanged
- Modules: `src/vasoanalyzer/ui/main_window.py` (guard in `_apply_frame_change()` or `jump_to_time()`), `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py`
- Acceptance: repeated slider signals at the same index produce zero extra render work (confirmed by perf logs).

3) Playback decimation when render cost exceeds timer interval
- Modules: `src/vasoanalyzer/ui/main_window.py` (`advance_snapshot_frame()` / `_configure_snapshot_timer()`)
- Idea: if render time > interval, skip frames by stride during playback.
- Acceptance: sustained playback >=10 fps on typical datasets without UI stalls.

### Tier 2 (nice-to-have)

1) LRU cache of converted frames (16-32 frames)
- Modules: `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py` (cache QImage/QPixmap or normalized arrays)
- Acceptance: repeat scrubs over recent frames reduce render time by >=30%.

2) Worker-thread normalization/convert
- Modules: `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py`, new worker in `src/vasoanalyzer/ui/snapshot_viewer/`
- Idea: normalize frames off the UI thread and emit ready-to-render frames via signals.
- Acceptance: UI thread frame update stays <50 ms even on large frames.

### Tier 3 (optional)

1) Adaptive FPS based on rolling render time
- Modules: `src/vasoanalyzer/ui/main_window.py` (snapshot timer), `src/vasoanalyzer/ui/snapshot_viewer/snapshot_perf.py`
- Acceptance: FPS auto-adjusts to stay within 80-90% of render capacity with no visible stutter.

## Instrumentation

Opt-in performance logging is available via `VASO_DEBUG_SNAPSHOT_PERF=1` and logs:
- get_frame_at_time duration and total frame update duration.
- render/conversion duration.
- frame shape/dtype, source kind, and effective FPS.
