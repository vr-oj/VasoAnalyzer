# VasoAnalyzer Time Synchronization: Canonical Architecture

**Created:** 2025-12-04
**Status:** Design Document
**Purpose:** Define the canonical time synchronization model for VasoAnalyzer

---

## Executive Summary

This document establishes `trace["Time (s)"]` as the **single source of truth** for all time synchronization in VasoAnalyzer. All other time representations (event times, TIFF frame times, video playback times) are **views** of this canonical axis.

### Key Principles

1. **One Truth:** `trace["Time (s)"]` is the only ground-truth experiment time
2. **Mappings, Not Conversions:** Events and frames map to trace time via indices, not time arithmetic
3. **Single Entry Point:** All sync flows go through `jump_to_time(time_s)`
4. **PyQtGraph Native:** Use `ImageView.setImage(..., xvals=frame_trace_time)` for video timeline

---

## Phase 1: Data Reality Check (Canonical Mappings from VasoTracker Files)

### 1.1 VasoTracker File Format

VasoTracker exports three synchronized data streams:

1. **Trace CSV** (`*_trace.csv`):
   - `Time (s)`: Float seconds (canonical time axis)
   - `Time (hh:mm:ss)`: String timestamp
   - `FrameNumber`: Integer frame counter (may have gaps)
   - `TiffPage`: Integer 0-based TIFF frame index (sparse, only for captured frames)
   - `Inner Diameter`: Float micrometers
   - Other columns: `Outer Diameter`, `Avg Pressure (mmHg)`, `Set Pressure (mmHg)`, etc.

2. **Events CSV** (`*_events.csv` or `*_table.csv`):
   - `EventLabel`: String event name
   - `Time`: String timestamp (hh:mm:ss format)
   - `Frame`: Integer matching `FrameNumber` in trace
   - Optional: `DiamBefore`, `OuterDiamBefore`, `Pavg`, etc.

3. **TIFF Stack** (`*.tif`):
   - Multi-frame TIFF with `n_frames` images
   - Frame timing is **not** derived from TIFF metadata
   - Timing comes exclusively from trace CSV `TiffPage` column

### 1.2 Verified Relationships

#### Event Mapping: `events["Frame"]` → `trace["FrameNumber"]` → `trace["Time (s)"]`

```python
# For each event j:
event_frame = events["Frame"][j]
# Find trace row where FrameNumber == event_frame
trace_idx = frame_number_to_trace_idx[event_frame]
# Get canonical time
event_time[j] = trace["Time (s)"][trace_idx]

# Verification: events["Time"][j] == trace["Time (hh:mm:ss)"][trace_idx]
```

**Invariants:**
- Each `events["Frame"]` appears **exactly once** in `trace["FrameNumber"]`
- Time string in events CSV matches trace CSV exactly
- `event_times` is derived, not assumed from time arithmetic

#### TIFF Frame Mapping: `tiff_frame_index` → `trace["TiffPage"]` → `trace["Time (s)"]`

```python
# For each TIFF frame f (0-based):
# Find trace row where TiffPage == f
trace_idx = tiff_page_to_trace_idx[f]
# Get canonical time and trace position
frame_trace_index[f] = trace_idx
frame_trace_time[f] = trace["Time (s)"][trace_idx]
```

**Invariants:**
- Number of non-null `TiffPage` values equals TIFF frame count
- `TiffPage` values are sequential integers 0..n_frames-1, each appearing once
- `frame_trace_time` length exactly equals TIFF frame count

### 1.3 Canonical Data Structures

After loading VasoTracker data, we maintain these mappings:

```python
# Trace (always present)
trace_time: np.ndarray              # shape (n_trace_rows,), Time (s) column
trace_df: pd.DataFrame              # Full trace data

# Events (if loaded)
event_times: np.ndarray             # shape (n_events,), canonical time for each event
event_labels: list[str]             # Event names
event_table_data: list[tuple]       # (label, time, id, od, avg_p, set_p, frame)

# TIFF frames (if loaded)
frame_trace_index: np.ndarray       # shape (n_frames,), trace row index for each frame
frame_trace_time: np.ndarray        # shape (n_frames,), Time (s) for each frame
snapshot_frames: list[np.ndarray]   # Actual image data
```

### 1.4 What We DON'T Use

- ❌ TIFF metadata timestamps
- ❌ `recording_interval` or `Rec_intvl` parsed from strings
- ❌ Frame index arithmetic (e.g., `frame_idx * interval`)
- ❌ Separate "video time" domain (0 to video_duration)

---

## Phase 2: Current Implementation Audit

### 2.1 Trace & Event Loading

#### Trace Loading ([traces.py](../src/vasoanalyzer/io/traces.py))

✅ **GOOD:**
- Loads `Time (s)` as canonical float column
- Preserves `FrameNumber` and `TiffPage` columns
- No time manipulation, just loads raw data

❌ **ISSUES:**
- No explicit `frame_number_to_trace_idx` mapping built
- No validation that `FrameNumber` or `TiffPage` are unique

#### Event Loading ([events.py](../src/vasoanalyzer/io/events.py))

✅ **GOOD:**
- Loads event times and frames correctly
- Flexible header matching

⚠️ **ISSUES:**
- Returns `(labels, times, frames)` but times are parsed from event CSV, not derived from trace
- No explicit `Frame` → `FrameNumber` → `Time (s)` mapping enforced
- Caller must manually join events to trace to get canonical times

### 2.2 Video Viewer ([snapshot_view_pg.py](../src/vasoanalyzer/ui/panels/snapshot_view_pg.py))

✅ **GOOD (already implements canonical model!):**
- `set_stack(stack, frame_trace_time)` accepts canonical time array
- Passes `xvals=frame_trace_time` to PyQtGraph `ImageView.setImage(...)`
- `sigTimeChanged` emits experiment time (seconds) directly
- `set_current_time(t_s)` finds nearest frame using `argmin(|frame_trace_time - t_s|)`

✅ **This viewer is already correct!** No changes needed.

### 2.3 Main Window Sync ([main_window.py](../src/vasoanalyzer/ui/main_window.py))

#### Data Structures

```python
# Line 653-661
self.trace_time: np.ndarray | None = None         # ✅ Canonical
self.frame_trace_time: np.ndarray | None = None   # ✅ Canonical
self.frame_times: list = []                        # ⚠️ Duplicate of frame_trace_time
self.event_times: list = []                        # ⚠️ Not np.ndarray, inconsistent with pattern
self.event_table_data: list[tuple] = []            # ✅ Stores (label, time, ...)
```

⚠️ **ISSUES:**
- `frame_times` is redundant with `frame_trace_time`
- `event_times` should be `np.ndarray` for consistency and performance

#### Frame Time Derivation ([main_window.py:8927-8981](../src/vasoanalyzer/ui/main_window.py#L8927-L8981))

✅ **GOOD:**
- `_derive_frame_trace_time()` correctly builds `frame_trace_time` from `TiffPage` column
- Validates that frame count matches and indices are sequential
- Sets `self.frame_trace_time` and `self.frame_times` (redundant)

```python
def _derive_frame_trace_time(self, n_frames: int):
    tiff_rows = self.trace_data[self.trace_data["TiffPage"].notna()]
    frame_trace_index = tiff_rows.index.to_numpy(dtype=int)
    frame_trace_time = tiff_rows["Time (s)"].to_numpy(dtype=float)
    # ... validation ...
    self.frame_trace_time = frame_trace_time
    self.frame_times = frame_trace_time.tolist()  # ⚠️ Redundant
```

#### Event Focus ([main_window.py:11151-11193](../src/vasoanalyzer/ui/main_window.py#L11151-L11193))

✅ **GOOD:**
- `_focus_event_row()` extracts `event_time` from `event_table_data[row][1]`
- Calls `jump_to_time(event_time, from_event=True, source="event")`

⚠️ **ISSUE:**
- Falls back to `_frame_index_from_event_row()` which may use legacy frame indices
- Should always use `event_time` derived from canonical mapping

#### Jump to Time ([main_window.py:9588-9650](../src/vasoanalyzer/ui/main_window.py#L9588-L9650))

✅ **GOOD:**
- Single entry point `jump_to_time(t, source="...")` exists
- Updates trace cursor and plot via `plot_host.center_on_time(resolved_time)`
- Calls `_propagate_time_to_snapshot_pg(resolved_time)` for PyQtGraph viewer

✅ **Uses canonical time:**
```python
def jump_to_time(self, t: float, *, source: str | None = None):
    t_val = float(t)  # Always experiment seconds
    # Snap to nearest trace time
    idx_trace = np.searchsorted(self.trace_time, t_val)
    resolved_time = self.trace_time[idx_trace]
    # Update trace
    plot_host.center_on_time(resolved_time)
    plot_host.set_time_cursor(resolved_time)
    # Update video
    frame_idx = self._frame_index_for_time_canonical(resolved_time)
    if not from_frame_change:
        self._propagate_time_to_snapshot_pg(resolved_time)
```

⚠️ **MINOR ISSUES:**
- Still has `from_event`, `from_playback`, `from_frame_change` flags; `source` should be sufficient
- Calls `_frame_index_for_time_canonical` but also has legacy `set_current_frame` path

#### Video Time Changed ([main_window.py:9530-9546](../src/vasoanalyzer/ui/main_window.py#L9530-L9546))

✅ **GOOD:**
- `_on_snapshot_time_changed(time_s)` receives experiment seconds from PyQtGraph
- Calls `jump_to_time(time_s, source="video")`
- Has `_pg_time_sync_block` guard to prevent feedback loops

✅ **This is already correct!**

### 2.4 Event Table ([event_table.py](../src/vasoanalyzer/ui/event_table.py))

✅ **GOOD:**
- Displays event data as tuples: `(label, time, id, od, avg_p, set_p, frame)`
- `time` is canonical `Time (s)` value
- Clicking a row emits `cellClicked(row, col)` which triggers `_focus_event_row(row)`

⚠️ **MINOR:**
- Header tooltip for "Trace idx (legacy)" acknowledges frame column is legacy
- Should be renamed to "Frame" and treated as informational only

### 2.5 Summary of Current State

#### What's Working ✅

1. **PyQtGraph viewer** (`SnapshotViewPG`) is already fully canonical
2. **Frame derivation** (`_derive_frame_trace_time`) correctly maps TIFF→trace time
3. **Jump to time** exists and uses canonical seconds
4. **Video→trace sync** works correctly (PyQtGraph `sigTimeChanged` → `jump_to_time`)

#### What Needs Fixing ⚠️

1. **Event time mapping** not explicitly validated against trace on load
2. **Redundant data** (`frame_times` list vs `frame_trace_time` array)
3. **Legacy frame paths** still exist (e.g., `set_current_frame` bypassing canonical sync)
4. **Event data structure** (`event_times` should be `np.ndarray`, not list)
5. **Event loading** should enforce `Frame` → `FrameNumber` → `Time (s)` mapping

---

## Phase 3: Target Architecture

### 3.1 Canonical Data Structures

After loading, maintain these structures in `MainWindow`:

```python
class MainWindow:
    # Trace (required)
    trace_df: pd.DataFrame              # Full trace data
    trace_time: np.ndarray              # Time (s) column, shape (n_trace_rows,)
    frame_number_to_trace_idx: dict[int, int]  # FrameNumber → trace row index

    # Events (optional)
    event_times: np.ndarray             # shape (n_events,), canonical Time (s)
    event_labels: list[str]             # Event names
    event_table_data: list[tuple]       # (label, time, id, od, avg_p, set_p, frame)

    # TIFF frames (optional)
    snapshot_frames: list[np.ndarray]   # Image data
    frame_trace_index: np.ndarray       # shape (n_frames,), trace row for each frame
    frame_trace_time: np.ndarray        # shape (n_frames,), Time (s) for each frame
```

### 3.2 Single Sync Entry Point

```python
def jump_to_time(self, time_s: float, *, source: str) -> None:
    """
    Canonical time jump (seconds) that updates trace and video consistently.

    Args:
        time_s: Experiment time in seconds (canonical Time (s))
        source: "event" | "video" | "manual" | "slider"

    Updates:
        - Trace red cursor position
        - Trace viewport (center on time)
        - Video frame (via set_current_time)
        - Event table highlight (optional)
    """
    # Snap to nearest trace time
    idx = np.argmin(np.abs(self.trace_time - time_s))
    resolved_time = float(self.trace_time[idx])

    # Update trace cursor
    self.plot_host.set_time_cursor(resolved_time, visible=True)
    self.plot_host.center_on_time(resolved_time)

    # Update video (if loaded)
    if self.snapshot_view_pg is not None and self.frame_trace_time is not None:
        self.snapshot_view_pg.set_current_time(resolved_time)

    # Update event highlight (optional)
    self._highlight_nearest_event(resolved_time)
```

### 3.3 Data Loading Workflow

#### Trace Load

```python
def _load_trace(self, file_path: str):
    self.trace_df = load_trace(file_path)
    self.trace_time = self.trace_df["Time (s)"].to_numpy(dtype=float)

    # Build FrameNumber → trace index mapping
    self.frame_number_to_trace_idx = {}
    for idx, row in self.trace_df.iterrows():
        frame_num = row.get("FrameNumber")
        if pd.notna(frame_num):
            self.frame_number_to_trace_idx[int(frame_num)] = int(idx)
```

#### Event Load

```python
def _load_events(self, file_path: str):
    labels, time_strings, frames = load_events(file_path)

    # Map events to canonical trace time
    event_times = []
    for j, (time_str, frame_num) in enumerate(zip(time_strings, frames)):
        if frame_num is not None and frame_num in self.frame_number_to_trace_idx:
            trace_idx = self.frame_number_to_trace_idx[frame_num]
            event_time = self.trace_df.loc[trace_idx, "Time (s)"]
            event_times.append(float(event_time))
        else:
            # Fall back to parsed time (less reliable)
            log.warning(f"Event {j} frame {frame_num} not in trace, using parsed time")
            event_times.append(parse_time_to_seconds(time_str))

    self.event_times = np.array(event_times, dtype=float)
    self.event_labels = labels
    # Build event_table_data tuples...
```

#### TIFF Load

```python
def _load_tiff(self, file_path: str):
    stack = load_tiff_stack(file_path)
    n_frames = len(stack)

    # Derive canonical frame times from trace TiffPage column
    frame_trace_index, frame_trace_time = self._derive_frame_trace_time(n_frames)

    if frame_trace_time is None:
        log.error("Cannot sync TIFF without TiffPage column in trace")
        return False

    # Set in PyQtGraph viewer with canonical xvals
    self.snapshot_view_pg.set_stack(stack, frame_trace_time)
    self.frame_trace_index = frame_trace_index
    self.frame_trace_time = frame_trace_time
    self.snapshot_frames = stack
```

### 3.4 PyQtGraph Integration

**SnapshotViewPG** (no changes needed):

```python
# Already correct!
def set_stack(self, stack: np.ndarray, frame_trace_time: np.ndarray):
    self.image_view.setImage(
        stack,
        axes={'t': 0, 'y': 1, 'x': 2},
        xvals=frame_trace_time,  # Canonical Time (s)
        autoRange=True,
        autoLevels=True,
    )
    self.image_view.sigTimeChanged.connect(self._on_pg_time_changed)

def _on_pg_time_changed(self, index: int, time_s: float):
    # time_s is already canonical Time (s) from PyQtGraph
    self.currentTimeChanged.emit(float(time_s))

def set_current_time(self, t_s: float):
    idx = int(np.argmin(np.abs(self.frame_trace_time - t_s)))
    self.image_view.setCurrentIndex(idx)
```

**MainWindow wiring:**

```python
self.snapshot_view_pg.currentTimeChanged.connect(self._on_snapshot_time_changed)

def _on_snapshot_time_changed(self, time_s: float):
    # Prevent feedback loop
    if self._pg_time_sync_block:
        return
    self._pg_time_sync_block = True
    try:
        self.jump_to_time(time_s, source="video")
    finally:
        self._pg_time_sync_block = False
```

### 3.5 Sync Flows

All sync flows route through `jump_to_time`:

```
Event Click:
    event_table.cellClicked(row)
    → _focus_event_row(row)
    → event_time = event_times[row]
    → jump_to_time(event_time, source="event")

Video Scrub/Play:
    PyQtGraph sigTimeChanged(index, time_s)
    → _on_snapshot_time_changed(time_s)
    → jump_to_time(time_s, source="video")

Manual Jump (slider, keyboard):
    user_action
    → jump_to_time(time_s, source="manual")
```

### 3.6 Rules for Implementation

1. **Time Units:** Anything called `time_s`, `time`, or passed to `jump_to_time` is **always** in canonical `Time (s)` units.

2. **Mappings:** Use `frame_trace_time[idx]` or `event_times[j]`, never arithmetic like `idx * interval`.

3. **Single Source:** `jump_to_time(time_s, source)` is the only function that updates:
   - Trace cursor
   - Trace viewport
   - Video frame
   - Event highlights

4. **No Legacy Paths:** Remove or mark as unused:
   - `_frame_index_for_video_time` (if it exists)
   - `set_current_frame` calls that bypass `jump_to_time`
   - Any code that assumes "video time" is different from experiment time

5. **PyQtGraph Native:** Trust `ImageView.setImage(..., xvals=...)` and `sigTimeChanged`. No manual time conversions.

---

## Phase 4: Implementation Checklist

### 4.1 Data Loading

- [ ] **Trace:** Build `frame_number_to_trace_idx` mapping on load
- [ ] **Events:** Compute `event_times` from `Frame` → `FrameNumber` → `Time (s)`
- [ ] **TIFF:** Assert `len(frame_trace_time) == n_frames`
- [ ] Remove `frame_times` list (redundant with `frame_trace_time`)
- [ ] Change `event_times` from `list` to `np.ndarray`

### 4.2 Sync Paths

- [ ] **Event click:** Get `event_times[row]`, call `jump_to_time(event_time, source="event")`
- [ ] **Video time change:** Already correct (`_on_snapshot_time_changed` → `jump_to_time`)
- [ ] Remove legacy frame index logic in `_focus_event_row`
- [ ] Remove or isolate `_frame_index_from_event_row`

### 4.3 Clean Up

- [ ] Remove `from_event`, `from_playback`, `from_frame_change` flags from `jump_to_time`
- [ ] Keep only `source: str` parameter
- [ ] Remove `set_current_frame` if it bypasses `jump_to_time`
- [ ] Remove `_time_for_frame` and `_frame_index_for_time_canonical` (use `frame_trace_time` directly)

### 4.4 Documentation

- [ ] Add docstring to `jump_to_time` explaining canonical time model
- [ ] Comment `frame_trace_time` and `event_times` as "canonical Time (s) mappings"
- [ ] Update event table header tooltip to clarify "Frame (legacy)"

---

## Phase 5: Testing

Run with real VasoTracker dataset (e.g., 20251201 sample):

1. **Trace + Events (no TIFF):**
   - Click each event → trace red marker moves to correct labeled position
   - Event markers on trace are unchanged and correct

2. **Add TIFF:**
   - PyQtGraph slider time scale matches `Time (s)` range (not 0–40 seconds!)
   - Press play → red line sweeps across full trace duration
   - When playhead crosses event, trace marker aligns with event position

3. **Event → Video:**
   - Click "20 mmHg" → trace jumps, video shows expected frame

4. **Video → Trace:**
   - Scrub video → trace red marker follows, matches expected time

---

## Appendix: PyQtGraph ImageView Time Handling

From [PyQtGraph documentation](https://pyqtgraph.readthedocs.io/en/latest/api_reference/imageview.html):

```python
ImageView.setImage(
    image,
    axes={'t': 0, 'y': 1, 'x': 2},
    xvals=None,  # <-- Array of time values for each frame
    ...
)
```

**xvals:** Array of values to use as x-axis labels for the time axis. If not specified, frames are labeled 0, 1, 2, ...

**sigTimeChanged(index, time):** Emitted when the user moves the timeline slider. `time` is the xvals value for the current frame, or frame index if xvals not provided.

**This means:** If we pass `xvals=frame_trace_time`, PyQtGraph will:
- Label the timeline with canonical experiment seconds
- Emit `time_s` in canonical units when the user scrubs
- Handle frame→time mapping internally

**We don't need to write any time conversion code!** PyQtGraph already does exactly what we need.

---

## Glossary

- **Canonical time:** `trace["Time (s)"]`, the single source of truth for experiment time
- **Frame trace time:** `frame_trace_time[i]` = canonical time for TIFF frame `i`
- **Event time:** `event_times[j]` = canonical time for event `j`
- **Jump to time:** The single sync function that updates trace and video to show a given experiment time
- **Video time:** ❌ **Does not exist.** Video uses experiment time via `frame_trace_time`.

---

**End of Document**
