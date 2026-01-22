# Snapshot Viewer Current State (UI + Internals)

This report documents how the snapshot viewer works today without proposing changes.
Snapshot viewing is Qt-only in normal operation; PyQtGraph is used for plots only, and the ImageView backend is quarantined for explicit opt-in.

## Component Map

### UI widgets
- SnapshotViewerWidget (canonical snapshot frame container; Qt-only by default) `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py#L28`
- SnapshotTimelineWidget (scrubber + frame/time readout) `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L15`
- QtFrameView + QtSnapshotRenderer (Qt paint backend + cache-aware rendering) `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py#L132` `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py#L276`
- Experimental PyQtGraph snapshot backend (ImageView; opt-in only) `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py#L23` `src/vasoanalyzer/ui/snapshot_viewer/experimental/pyqtgraph_renderer.py#L17`

### Controller(s)
- SnapshotViewerController (playback, sync, prefetch, signals) `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L86`

### Data source(s)
- SnapshotDataSource protocol + SnapshotStackDataSource adapter (time-to-page mapping via page_for_time) `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py#L18` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py#L32`
- Snapshot loading job (assets / TIFF path) `_SnapshotLoadJob` `src/vasoanalyzer/ui/main_window.py#L411`
- TIFF stack loader used by manual load and background job `load_tiff` `src/vasoanalyzer/io/tiffs.py#L69`

### Cache / prefetch
- QImage LRU cache + keying (frame index + rotation) `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L19` `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L57`
- Prefetch queue + timers (controller) `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L122` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L614`

### Theme / icon helpers
- Theme palette for snapshot background `snapshot_bg` `src/vasoanalyzer/ui/theme.py#L78`
- Snapshot UI stylesheet (SnapshotCard/Controls/Preview) `_apply_data_page_style` `src/vasoanalyzer/ui/shell/init_ui.py#L429`
- Timeline colors from CURRENT_THEME `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L65`
- Icon tinting via themed_svg_icon (palette-based) `src/vasoanalyzer/ui/icons.py#L8`

### MainWindow integration
- Snapshot widget/controller creation + binding `src/vasoanalyzer/ui/main_window.py#L899`
- Snapshot controls + timeline wiring in init UI `src/vasoanalyzer/ui/shell/init_ui.py#L207`
- Right panel layout with SnapshotCard + controls + metadata panel + event table `src/vasoanalyzer/ui/main_window.py#L16080`
- Snapshot viewer menu actions (View → Panels → Snapshot Viewer; Metadata…) `src/vasoanalyzer/ui/mixins/menu_mixin.py#L385`

### Mixins still touching snapshots (legacy / parallel paths)
- SnapshotMixin (legacy snapshot UI + loading) `src/vasoanalyzer/ui/mixins/snapshot_mixin.py#L40`
- SampleLoaderMixin snapshot loader (legacy) `src/vasoanalyzer/ui/mixins/sample_loader_mixin.py#L1048`
- MetadataMixin (uses snapshot_label visibility) `src/vasoanalyzer/ui/mixins/metadata_mixin.py#L177`

## Runtime Flow

### Dataset load → snapshot source set
- Sample load calls `_update_snapshot_viewer_state`; if `sample.snapshots` already materialized, `load_snapshots` runs immediately. `src/vasoanalyzer/ui/main_window.py#L4360` `src/vasoanalyzer/ui/main_window.py#L4401`
- If only asset/path exists, `_ensure_sample_snapshots_loaded` starts `_SnapshotLoadJob`; on completion, `_on_snapshot_load_finished` loads the stack and toggles the viewer. `src/vasoanalyzer/ui/main_window.py#L4415` `src/vasoanalyzer/ui/main_window.py#L4448`
- Manual TIFF load uses `_load_snapshot_from_path`, which probes the stack and can subsample before calling `load_tiff`. `src/vasoanalyzer/ui/main_window.py#L11095` `src/vasoanalyzer/io/tiffs.py#L69`
- Once frames are ready, `_set_snapshot_data_source` wraps them in `SnapshotStackDataSource` and calls `SnapshotViewerController.set_stack_source`. `src/vasoanalyzer/ui/main_window.py#L11673` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L298`

### page_times derived + stored
- MainWindow determines canonical per-frame times (`frame_trace_time` from trace/TiffPage mapping or `frame_times` from metadata fallback) and passes them into `_set_snapshot_data_source`. `src/vasoanalyzer/ui/main_window.py#L11238` `src/vasoanalyzer/ui/main_window.py#L11673`
- Controller extracts page times from the data source (`_extract_page_times`) and stores them in `_page_times` on `set_stack_source`. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L298` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L661`

### Syncing
- **page → trace time**: controller emits `playback_time_changed` using `_page_times`; MainWindow consumes this in `_on_snapshot_playback_time_changed` to move the trace cursor. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L697` `src/vasoanalyzer/ui/main_window.py#L12453`
- **trace cursor → page jump**: `jump_to_time` is the canonical time setter; it resolves a frame index with `_frame_index_for_time_canonical` and updates the slider/timeline. `src/vasoanalyzer/ui/main_window.py#L11851` `src/vasoanalyzer/ui/main_window.py#L11828`
- **event → page jump**: event selection flows through `_focus_event_row` → `jump_to_time(from_event=True)`, which then calls `controller.set_event_time` to drive the viewer. `src/vasoanalyzer/ui/main_window.py#L13886` `src/vasoanalyzer/ui/main_window.py#L11931`
- **time→index mapping**: `SnapshotStackDataSource.index_for_time` uses `page_for_time` for deterministic nearest matching. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py#L66` `src/vasoanalyzer/core/timebase.py#L721`

### Playback
- Controller owns the playback timer (`QTimer` with `PreciseTimer`); playback step logic lives in `_on_playback_tick`, including loop/stop behavior. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L130` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L728`
- MainWindow toggles playback via `_set_playback_state`, which calls `controller.set_playing` and updates button state. `src/vasoanalyzer/ui/main_window.py#L12420` `src/vasoanalyzer/ui/main_window.py#L12468`
- PPS (pages/sec) is driven by the speed input and propagated to `controller.set_playback_pps`. `src/vasoanalyzer/ui/main_window.py#L12330` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L156`

### Scrubber / timeline
- SnapshotTimelineWidget is created in `init_ui`, wired to `change_frame_from_timeline`, and aliased to `window.slider`. `src/vasoanalyzer/ui/shell/init_ui.py#L219`
- Manual scrub calls `change_frame_from_timeline`, which stops playback and sets the current frame. `src/vasoanalyzer/ui/main_window.py#L12065`

## UI Layout Description

### Right-panel widget hierarchy
- `data_page → data_splitter → side_panel → right_panel_card` creates the snapshot/event column. `src/vasoanalyzer/ui/main_window.py#L16080`
- Snapshot card stack:
  - `SnapshotCard` (QFrame)
  - `SnapshotStack` (QStackedWidget)
  - `SnapshotViewerWidget` (SnapshotPreview)
  - `SnapshotControls` (two-row transport + timeline + settings)
  - `MetadataPanel` (collapsed by default)
  - Event table card below `SnapshotCard` `src/vasoanalyzer/ui/main_window.py#L16117`

### Timeline / scrubber
- The timeline is a custom widget embedded in row 1 of `SnapshotControls`, not a floating window. `src/vasoanalyzer/ui/shell/init_ui.py#L219` `src/vasoanalyzer/ui/main_window.py#L16080`
- Experimental PyQtGraph backend collapses the native ImageView timeline/ROI plot in `SnapshotViewPG`. `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py#L340`

### Two-row control strip
- Row 1: `prev_frame_btn`, `play_pause_btn`, `next_frame_btn`, `snapshot_timeline`. `src/vasoanalyzer/ui/shell/init_ui.py#L248`
- Row 2: `snapshot_speed_label`, `snapshot_speed_input`, `snapshot_speed_units_label`, `snapshot_loop_checkbox`, `snapshot_sync_checkbox`, `snapshot_sync_label`, `snapshot_subsample_label`, `snapshot_time_label`. `src/vasoanalyzer/ui/shell/init_ui.py#L287`

### Actions/buttons and connected slots
- `prev_frame_btn.clicked` → `step_previous_frame` `src/vasoanalyzer/ui/shell/init_ui.py#L248`
- `play_pause_btn.clicked` → `toggle_snapshot_playback` `src/vasoanalyzer/ui/shell/init_ui.py#L259`
- `next_frame_btn.clicked` → `step_next_frame` `src/vasoanalyzer/ui/shell/init_ui.py#L273`
- `snapshot_timeline.seek_requested` → `change_frame_from_timeline` `src/vasoanalyzer/ui/shell/init_ui.py#L219`
- `snapshot_speed_input.valueChanged` → `on_snapshot_speed_changed` `src/vasoanalyzer/ui/shell/init_ui.py#L292`
- `snapshot_sync_checkbox.toggled` → `on_snapshot_sync_toggled` `src/vasoanalyzer/ui/shell/init_ui.py#L315`
- `snapshot_loop_checkbox.toggled` → `on_snapshot_loop_toggled` `src/vasoanalyzer/ui/shell/init_ui.py#L321`
- `SnapshotViewerWidget` context menu → `show_snapshot_context_menu` `src/vasoanalyzer/ui/shell/init_ui.py#L208`
- `action_snapshot_metadata.triggered` → `set_snapshot_metadata_visible` `src/vasoanalyzer/ui/mixins/menu_mixin.py#L395`
- `snapshot_viewer_action.triggered` → `toggle_snapshot_viewer` `src/vasoanalyzer/ui/mixins/menu_mixin.py#L385`
- Controller signals wired in init UI:
  - `sync_mode_changed` → `_update_snapshot_sync_label` `src/vasoanalyzer/ui/shell/init_ui.py#L356`
  - `page_changed` → `_on_snapshot_page_changed` `src/vasoanalyzer/ui/shell/init_ui.py#L360`
  - `playback_time_changed` → `_on_snapshot_playback_time_changed` `src/vasoanalyzer/ui/shell/init_ui.py#L363`
  - `playing_changed` → `_on_snapshot_playing_changed` `src/vasoanalyzer/ui/shell/init_ui.py#L366`

## Theming & Icons
- Snapshot card + controls styling is injected via `_apply_data_page_style` using CURRENT_THEME values. `src/vasoanalyzer/ui/shell/init_ui.py#L429`
- Snapshot preview background uses `snapshot_bg` from the theme. `src/vasoanalyzer/ui/shell/init_ui.py#L528` `src/vasoanalyzer/ui/theme.py#L78`
- QtFrameView paints the viewer background using `snapshot_bg`. `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py#L199`
- SnapshotTimelineWidget uses `plot_bg`, `text`, `accent`, `grid_color` from CURRENT_THEME. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L65`
- Experimental PyQtGraph backend sets ImageView background from `snapshot_bg`. `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py#L68`
- Icons are palette-tinted using `themed_svg_icon` (normal/disabled/active states). `src/vasoanalyzer/ui/icons.py#L8`

Light vs dark theme notes:
- No explicit theme-branching bugs are visible in snapshot-specific code; most styling is derived from CURRENT_THEME. `src/vasoanalyzer/ui/shell/init_ui.py#L429`
- Potential visual mismatch: the timeline uses `plot_bg` (plot palette) while the snapshot preview uses `snapshot_bg`, so in light mode the timeline may read as “plot” rather than “card.” `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L65` `src/vasoanalyzer/ui/shell/init_ui.py#L528`
- Icon tinting depends on widget palettes; if palettes aren’t refreshed on theme change, icons can drift in contrast. `src/vasoanalyzer/ui/icons.py#L8`

## Performance Architecture

### Renderer backend selection
- Snapshot viewer is Qt-only by default; `VA_SNAPSHOT_RENDER_BACKEND=pyqtgraph` is honored only when `VA_ALLOW_EXPERIMENTAL_SNAPSHOT_BACKENDS=1`, and uses the experimental ImageView backend. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py#L141`

### QImage cache
- QImage cache budget `VA_SNAPSHOT_QIMAGE_CACHE_MB` (default 512 MB), key `(frame_index, rotation)`, LRU eviction by byte budget. `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L16` `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L19` `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L111`
- QtSnapshotRenderer checks the cache on every frame, records hit/miss, and stores converted QImages. `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py#L338`

### Prefetch logic
- Prefetch window size and interval are env-controlled (`VA_SNAPSHOT_PREFETCH_FRAMES`, `VA_SNAPSHOT_PREFETCH_INTERVAL_MS`), backed by a `VeryCoarseTimer`. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L43` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L134`
- Prefetch pauses if cache is near capacity (>90%) or if playback is late/pending; it converts frames to QImage and inserts into the cache. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L568` `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L614`

### Risk areas for stutter
- Frame conversion + scaling happen on the UI thread in QtFrameView/QtSnapshotRenderer; large frames or rotations can spike `paintEvent`/scaling time. `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py#L199`
- Prefetch uses a coarse timer and can be cleared when cache is near cap, so sustained high PPS playback can outpace prefetch. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L614`
- Experimental PyQtGraph backend re-sets the stack on each `set_frame` call (via `set_stack`), which can be heavier than Qt path for rapid frame changes. `src/vasoanalyzer/ui/snapshot_viewer/experimental/pyqtgraph_renderer.py#L39` `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py#L111`
- Large TIFFs are fully materialized in memory (optionally subsampled), which can spike RAM and GC during load. `src/vasoanalyzer/io/tiffs.py#L69`

## Known Issues List

- **TIFF page time mapping warnings**: emitted when TiffPage/time pairs are missing, out of range, duplicated, or non-monotonic (also when time/TiffPage columns are missing). These warnings are logged in `_refresh_tiff_page_times`. `src/vasoanalyzer/core/timebase.py#L592` `src/vasoanalyzer/ui/main_window.py#L9437`
- **Floating scrubber window**: no explicit floating window is created in current code; the only scrubber is `SnapshotTimelineWidget`. The PyQtGraph ImageView backend is quarantined and opt-in only, so no native ImageView timeline should appear in normal runs. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L15` `src/vasoanalyzer/ui/snapshot_viewer/experimental/snapshot_view_pg.py#L340`
- **Legacy code paths still present**:
  - `_use_pg_snapshot_viewer` / `_on_toggle_pg_snapshot_viewer` are no-ops (legacy toggle). `src/vasoanalyzer/ui/main_window.py#L7228`
  - `display_frame` references `snapshot_label`, which is not built in current UI. `src/vasoanalyzer/ui/main_window.py#L11974`
  - SnapshotMixin and SampleLoaderMixin retain older snapshot loading/UI logic (parallel to main_window). `src/vasoanalyzer/ui/mixins/snapshot_mixin.py#L40` `src/vasoanalyzer/ui/mixins/sample_loader_mixin.py#L1048`
  - MetadataMixin still keys on `snapshot_label.isVisible()` instead of snapshot_widget. `src/vasoanalyzer/ui/mixins/metadata_mixin.py#L177`

## Diagram (Data Flow + UI Flow)

```
DATA FLOW
┌───────────────┐  load_sample()       ┌───────────────────────┐
│ SampleN       │ ───────────────►     │ _update_snapshot_viewer│
│ (snapshots or │                      │ _state (enable UI)    │
│ snapshot_path)│                      └───────────┬───────────┘
└───────┬───────┘                                  │
        │ if snapshots missing                     │
        │                                          ▼
        │                           _SnapshotLoadJob (asset/TTF)
        │                                  │
        ▼                                  ▼
  _load_snapshot_from_path()         load_tiff() → frames
        │                                  │
        └───────────────┬──────────────────┘
                        ▼
         snapshot_frames + canonical_times
                        ▼
          SnapshotStackDataSource
                        ▼
          SnapshotViewerController
                        ▼
          SnapshotViewerWidget
                    │
                    ▼
            QtSnapshotRenderer
             (QImageLruCache)

SYNC FLOW
Trace cursor/event → jump_to_time() → controller.set_trace_time/event_time
Controller playback → playback_time_changed → trace cursor update

UI FLOW
SnapshotCard
  ├─ SnapshotStack → SnapshotViewerWidget
  ├─ SnapshotControls → [Prev][Play][Next][Timeline]
  └─ MetadataPanel
EventTableCard below
```

## Do Not Touch Invariants (Step 2)

- Keep `SnapshotViewerController` public signals and setters stable (`frame_changed`, `page_changed`, `playing_changed`, `playback_time_changed`, `set_trace_time`, `set_event_time`, `set_stack_source`, `set_playing`). `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py#L86`
- `jump_to_time` remains the single canonical entry point for sync between trace, events, and snapshots. `src/vasoanalyzer/ui/main_window.py#L11851`
- `SnapshotStackDataSource.index_for_time` continues to use `page_for_time` semantics (nearest, monotonic-safe). `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py#L66` `src/vasoanalyzer/core/timebase.py#L721`
- Timeline widget must preserve QSlider compatibility (`setValue`, `setMaximum`) because `window.slider` aliases it. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L200` `src/vasoanalyzer/ui/shell/init_ui.py#L225`
- Cache keying must remain `(frame_index, rotation)` for stable hits across rotations. `src/vasoanalyzer/ui/snapshot_viewer/qimage_cache.py#L19`
- `VA_SNAPSHOT_RENDER_BACKEND=pyqtgraph` is honored only when `VA_ALLOW_EXPERIMENTAL_SNAPSHOT_BACKENDS=1` (debug-only); default must remain Qt. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py#L141`
- `SnapshotTimelineWidget.seek_requested` is the only scrubber signal and must remain connected to `change_frame_from_timeline`. `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py#L25` `src/vasoanalyzer/ui/shell/init_ui.py#L219`
