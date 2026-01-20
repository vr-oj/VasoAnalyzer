# Snapshot Viewer Canonical Plan

## One True Form
**Chosen canonical form:** `SnapshotViewPG` (PyQtGraph ImageView) as the base implementation, re-homed behind the new canonical widget/controller interface.

**Why:**
- Already supports `xvals` time alignment to canonical trace time.
- Robust aspect locking + consistent scaling without manual QLabel width hacks.
- Clean API (`set_stack`, `set_current_time`, `set_frame_index`) and signal `currentTimeChanged`.
- Existing integration in `VasoAnalyzerApp` shows it is stable enough to serve as the target implementation.

## Canonical architecture

### SnapshotViewerWidget (UI only)
Responsibilities:
- Render the current frame (image display + aspect ratio handling).
- Provide zoom/pan if the underlying viewer supports it (no data logic).
- Display frame metadata (optional UI-only presentation).
- Emit user interactions (click -> time jump request).

Must not:
- Own trace-time mapping logic.
- Perform file I/O or TIFF loading.

### SnapshotViewerController (logic)
Responsibilities:
- Accept trace cursor time / event time and compute the target frame.
- Load a frame from the data source and publish it to the widget.
- Maintain caching strategy (future, not in Phase 1/2).
- Coordinate event selection -> frame mapping.

Must not:
- Own UI layout or widget rendering details.

### SnapshotDataSource (protocol)
Interface for frame retrieval (backed by sample snapshots, TIFF stack, or cached frames):
- `get_frame_at_time(t_seconds) -> Frame` **or**
- `get_frame_at_index(i) -> Frame`

## Minimal API (controller contract)
- `set_trace_time(t_seconds: float)`
- `set_event_time(t_seconds: float)`
- `set_stack_source(source: SnapshotDataSource)`
- `set_enabled(enabled: bool)`

## MainWindow integration points
- Trace cursor movement (`jump_to_time`, plot host cursor updates) -> `controller.set_trace_time(...)`.
- Event selection (event table selection sync) -> `controller.set_event_time(...)`.
- Dataset switch (`load_sample_into_view`, `load_trace_and_events`) -> reset controller state and call `controller.set_stack_source(...)` for the new sample.
- Snapshot availability: when no TIFF stack exists, call `controller.set_enabled(False)` and hide the widget; enable again after snapshot load.

## Migration plan (phased)
- **Phase 3:** Route all snapshot entry points to the canonical controller + widget.
  - Wrap existing `SnapshotViewPG` inside `SnapshotViewerWidget` or adapt `SnapshotViewerWidget` to delegate to `SnapshotViewPG`.
  - MainWindow uses controller instead of direct calls to `display_frame` / `set_current_time`.
  - Keep legacy QLabel viewer and SnapshotMixin in place (quarantined) while routing new flows through the controller.
- **Phase 4:** Remove legacy implementations once parity is confirmed.
  - Delete legacy QLabel rendering path and SnapshotMixin logic.
  - Remove the dual-viewer toggle and legacy-only code paths.

## Canonical component location
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py` (`SnapshotViewerWidget`)
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py` (`SnapshotViewerController` + `SnapshotDataSource`)
