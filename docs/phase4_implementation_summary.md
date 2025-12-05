# Phase 4 Implementation Summary

**Date:** 2025-12-04
**Status:** ✅ Complete - Ready for Testing

---

## Changes Made

### 1. Data Structure Improvements ✅

#### Changed `event_times` from list to np.ndarray
- **File:** [main_window.py:660](../src/vasoanalyzer/ui/main_window.py#L660)
- **Before:** `self.event_times = []`
- **After:** `self.event_times: np.ndarray | None = None  # Canonical Time (s) for each event`
- **Benefit:** Consistent with `trace_time` and `frame_trace_time`, faster numpy operations

#### Removed redundant `frame_times` list
- **Files Modified:**
  - `main_window.py:657` - Removed from initialization
  - `main_window.py:7793` - Removed from `_update_trace_sync_state()`
  - `main_window.py:8935` - Removed from `_derive_frame_trace_time()`
  - `main_window.py:12858` - Removed from cleanup code
- **Benefit:** `frame_trace_time` (ndarray) is sufficient, no need for duplicate list

#### Updated event loading to use np.ndarray
- **File:** [main_window.py:9262](../src/vasoanalyzer/ui/main_window.py#L9262)
- **Before:** `self.event_times = resolved_times` (list)
- **After:** `self.event_times = np.array(resolved_times, dtype=float)  # Canonical Time (s)`
- **Benefit:** Enables fast vectorized operations like `argmin(|event_times - t|)`

### 2. Simplified Time Mapping Helpers ✅

#### Cleaned up `_time_for_frame()`
- **File:** [main_window.py:9544-9552](../src/vasoanalyzer/ui/main_window.py#L9544-L9552)
- **Removed:** Fallback to `self.frame_times` (redundant)
- **Now:** Only uses `self.frame_trace_time` (canonical)

#### Cleaned up `_frame_index_for_time_canonical()`
- **File:** [main_window.py:9554-9569](../src/vasoanalyzer/ui/main_window.py#L9554-L9569)
- **Removed:** Fallback to `self.frame_times` and unnecessary array conversion
- **Now:** Direct numpy operation on `frame_trace_time`

### 3. Simplified `jump_to_time()` Function ✅

#### Removed redundant boolean flags
- **File:** [main_window.py:9571-9626](../src/vasoanalyzer/ui/main_window.py#L9571-L9626)
- **Before:**
  ```python
  def jump_to_time(
      self, t: float, *,
      from_event: bool = False,
      from_playback: bool = False,
      from_frame_change: bool = False,
      source: str | None = None,
  )
  ```
- **After:**
  ```python
  def jump_to_time(
      self, t: float, *,
      source: str = "manual",
  )
  ```

#### Improved feedback loop prevention
- **Before:** Used `from_frame_change` flag
- **After:** Check `source != "video"` before updating video
- **Logic:** If the source is "video", we're already coming from a video change, so don't update video again

#### Updated all callers
- [main_window.py:9535](../src/vasoanalyzer/ui/main_window.py#L9535) - `_on_snapshot_time_changed()`
- [main_window.py:9761](../src/vasoanalyzer/ui/main_window.py#L9761) - `_apply_frame_change()`
- [main_window.py:11152](../src/vasoanalyzer/ui/main_window.py#L11152) - `_focus_event_row()`
- All now use simple `source="video"` or `source="event"` parameter

---

## What Was Already Correct ✅

1. **`frame_number_to_trace_idx` mapping** - Already being built in [main_window.py:7806-7811](../src/vasoanalyzer/ui/main_window.py#L7806-L7811)
2. **Event time derivation** - Already using `_trace_time_for_frame_number()` in [main_window.py:9252](../src/vasoanalyzer/ui/main_window.py#L9252)
3. **Frame time derivation** - Already using `TiffPage` column in [main_window.py:8925-8977](../src/vasoanalyzer/ui/main_window.py#L8925-L8977)
4. **PyQtGraph viewer** - Already passing `xvals=frame_trace_time` in [snapshot_view_pg.py:123](../src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L123)
5. **Video→trace sync** - Already correct via `sigTimeChanged` in [snapshot_view_pg.py:68](../src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L68)

---

## Architecture Summary

### Canonical Data Flow

```
VasoTracker Files
  ├─ Trace CSV
  │   ├─ Time (s)         → trace_time (ndarray)
  │   ├─ FrameNumber      → frame_number_to_trace_idx (dict)
  │   └─ TiffPage         → frame_trace_time (ndarray)
  │
  ├─ Events CSV
  │   └─ Frame            → event_times (ndarray) via frame_number_to_trace_idx
  │
  └─ TIFF Stack
      └─ Frame index      → frame_trace_time via TiffPage

All use trace["Time (s)"] as canonical time
```

### Single Sync Entry Point

```python
jump_to_time(time_s, source="event"|"video"|"manual")
  ├─ Snaps to nearest trace_time
  ├─ Updates trace cursor & viewport
  ├─ Highlights event (if near one)
  └─ Updates video (unless source == "video")
```

### Sync Flows

```
Event Click:
  event_table.cellClicked(row)
  → _focus_event_row(row)
  → event_time = event_times[row]
  → jump_to_time(event_time, source="event")

Video Scrub/Play:
  PyQtGraph sigTimeChanged(time_s)
  → _on_snapshot_time_changed(time_s)
  → jump_to_time(time_s, source="video")
  (video not updated due to source check)
```

---

## What to Test Now (Phase 5)

### Test 1: Load Trace + Events (No TIFF)

```bash
# 1. Launch VasoAnalyzer
# 2. Load trace CSV
# 3. Load events CSV
```

**Expected:**
- ✅ Events appear in table
- ✅ Click each event → red marker moves to correct position
- ✅ Event markers on trace are correctly positioned

### Test 2: Add TIFF Video

```bash
# 4. Load TIFF file
```

**Expected:**
- ✅ PyQtGraph timeline shows full experiment duration (e.g., 0-3000s, not 0-40s)
- ✅ Video plays smoothly
- ✅ Red marker sweeps across full trace as video plays

### Test 3: Event → Video Sync

```bash
# 5. Click "20 mmHg" event
```

**Expected:**
- ✅ Trace red marker jumps to event
- ✅ Trace viewport centers on event
- ✅ Video frame updates to show frame at that time
- ✅ Video timeline cursor at correct position

### Test 4: Video → Trace Sync

```bash
# 6. Scrub video timeline
# 7. Press play button
```

**Expected:**
- ✅ Scrubbing: Trace red marker follows video position
- ✅ Playing: Red marker smoothly advances across trace
- ✅ When playhead crosses an event, marker aligns with event position

### Test 5: Edge Cases

```bash
# 8. Click event at start of trace
# 9. Click event at end of trace
# 10. Scrub video to beginning/end
```

**Expected:**
- ✅ No errors or crashes
- ✅ Sync remains accurate at boundaries

---

## Debugging Tips

If sync issues occur, check these:

1. **Verify data verification script**:
   ```bash
   python verify_data_relationships.py /path/to/your/dataset
   ```
   This confirms the trace→event and trace→TIFF mappings are valid.

2. **Enable time sync logging** (optional):
   Look for `_log_time_sync()` calls in the code. These log:
   - `JUMP_TO_TIME` events with source
   - `EVENT_FOCUS` events
   - Frame and time values

3. **Check PyQtGraph timeline scale**:
   - Hover over video timeline - should show experiment seconds
   - Min value ≈ first frame's `Time (s)`
   - Max value ≈ last frame's `Time (s)`

4. **Inspect data structures** (in debugger):
   ```python
   # Should all be ndarrays with matching lengths
   len(self.trace_time)          # e.g., 180000
   len(self.frame_trace_time)    # e.g., 2000 (TIFF frames)
   len(self.event_times)         # e.g., 8 (events)
   ```

---

## Known Limitations

1. **Event times must have matching frames**: If an event's `Frame` value doesn't exist in `trace["FrameNumber"]`, it falls back to the parsed time string (less reliable).

2. **TIFF sync requires TiffPage column**: If trace CSV doesn't have `TiffPage` column, video sync is unavailable.

3. **No backwards compatibility for old sessions**: Sessions saved with the old `frame_times` list structure will need to reload data.

---

## Next Steps After Testing

1. **If sync works correctly**: Archive old helper functions, update user documentation
2. **If issues found**: Use data verification script to diagnose, report specific issue
3. **Performance optimization** (optional): Consider caching event→trace lookups if event count is very large (>1000)

---

**End of Summary**
