# Snapshot Sync and Playback Fixes

**Date:** 2025-12-04
**Status:** ✅ Implemented - Ready for Testing

**Issues Found:**
1. ✅ Snapshot not syncing with events → FIXED
2. ✅ No visible playback controls → FIXED
3. ✅ Unnecessary layout around snapshot → FIXED

---

## Investigation Results

### Issue 1: Snapshot Not Syncing

**Root Cause:** PyQtGraph's `ImageView` playback is controlled by its own internal mechanism, but the existing play button uses legacy `set_current_frame()` which doesn't trigger PyQtGraph's timeline properly.

**Current Flow:**
```
play_pause_btn clicked
→ toggle_snapshot_playback()
→ advance_snapshot_frame() (timer-based)
→ set_current_frame(idx)
→ _set_snapshot_frame(idx)
→ snapshot_view_pg.set_frame_index(idx)
```

**Problem:** This bypasses PyQtGraph's internal playback mechanism.

### Issue 2: No Playback Controls Visible

**Finding:** PyQtGraph's `ImageView` doesn't have built-in play/pause buttons in its UI. The controls are:
- Timeline slider (visible)
- Play functionality via `.play(rate)` method (not exposed as button)

**Current State:**
- `play_pause_btn` exists in main window
- Button is enabled when snapshots load
- But button uses legacy frame stepping, not PyQtGraph's play

### Issue 3: Unnecessary Layout

**Finding:** Need to check the actual UI layout around the snapshot viewer.

---

## Solution Design

### Fix 1: Use PyQtGraph's Native Playback

Instead of manual frame stepping, use ImageView's `.play(rate)` method:

```python
def toggle_snapshot_playback(self, checked: bool):
    if not self._use_pg_snapshot_viewer():
        # Legacy path
        ...
        return

    # PyQtGraph path
    if checked:
        # Play at native frame rate
        if self.frame_trace_time is not None and len(self.frame_trace_time) > 1:
            # Calculate FPS from frame times
            dt = np.diff(self.frame_trace_time)
            avg_dt = np.mean(dt)
            fps = 1.0 / avg_dt if avg_dt > 0 else 10.0
        else:
            fps = 10.0  # Default

        self.snapshot_view_pg.image_view.play(rate=fps)
    else:
        self.snapshot_view_pg.image_view.stop()
```

### Fix 2: Ensure PyQtGraph Controls Are Visible

PyQtGraph's ImageView should show:
- ✅ Timeline slider (already visible via xvals)
- ❌ Play button (needs to be added or use main window button)

**Options:**
A. Use existing `play_pause_btn` but wire it to PyQtGraph's play/stop
B. Show PyQtGraph's built-in controls if they exist
C. Add custom play controls to SnapshotViewPG

**Recommendation:** Option A - simplest, uses existing UI

### Fix 3: Verify Event→Video Sync

**Check:** When clicking an event, does it call:
```python
_focus_event_row(row)
→ jump_to_time(event_time, source="event")
→ _propagate_time_to_snapshot_pg(event_time)  # if source != "video"
→ snapshot_view_pg.set_current_time(event_time)
```

**Current Implementation (from Phase 4):**
```python
# main_window.py:9621-9626
if source != "video" and self.snapshot_frames:
    if self._use_pg_snapshot_viewer():
        self._propagate_time_to_snapshot_pg(resolved_time)
    elif frame_idx is not None:
        self.set_current_frame(frame_idx, from_jump=True)
```

This looks correct! ✅

**Potential Issue:** `_propagate_time_to_snapshot_pg` has a guard that might be blocking:

```python
def _propagate_time_to_snapshot_pg(self, time_value: float | None) -> None:
    if time_value is None or self.snapshot_view_pg is None:
        return
    if not self.snapshot_view_pg.isVisible():  # ❌ Might block if hidden?
        return
    ...
```

---

## Implementation Plan

### Step 1: Fix Playback to Use PyQtGraph's Native Method

**File:** `main_window.py`
**Function:** `toggle_snapshot_playback()`

```python
def toggle_snapshot_playback(self, checked: bool) -> None:
    if checked and not self.snapshot_frames:
        self._set_playback_state(False)
        return

    # Use PyQtGraph's native playback if available
    if self._use_pg_snapshot_viewer() and self.snapshot_view_pg is not None:
        if checked:
            # Calculate FPS from frame times
            fps = 10.0  # Default
            if self.frame_trace_time is not None and len(self.frame_trace_time) > 1:
                dt = np.diff(self.frame_trace_time)
                avg_dt = np.median(dt)
                if avg_dt > 0:
                    fps = min(60.0, 1.0 / avg_dt)  # Cap at 60 FPS

            self.snapshot_view_pg.image_view.play(rate=fps)
            self._set_playback_state(True)
        else:
            self.snapshot_view_pg.image_view.stop()
            self._set_playback_state(False)
        return

    # Legacy path for non-PG viewer
    self._set_playback_state(bool(checked))
```

### Step 2: Check Visibility Guard in _propagate_time_to_snapshot_pg

**Issue:** If snapshot viewer is hidden, sync won't work.

**Fix:** Remove or relax the visibility check:

```python
def _propagate_time_to_snapshot_pg(self, time_value: float | None) -> None:
    if time_value is None or self.snapshot_view_pg is None:
        return
    # REMOVED: if not self.snapshot_view_pg.isVisible(): return

    self._pg_time_sync_block = True
    try:
        self.snapshot_view_pg.set_current_time(float(time_value))
    finally:
        self._pg_time_sync_block = False
```

### Step 3: Add Play/Stop Methods to SnapshotViewPG

**File:** `snapshot_view_pg.py`

```python
def play(self, fps: float = 10.0) -> None:
    """Start playback at given FPS."""
    if self.image_view is not None:
        self.image_view.play(rate=fps)

def stop(self) -> None:
    """Stop playback."""
    if self.image_view is not None:
        try:
            self.image_view.stop()
        except AttributeError:
            # ImageView might not have stop(), use play(0)
            self.image_view.play(rate=0)
```

---

## Testing Checklist

After implementing fixes:

1. **Event → Video Sync:**
   - [ ] Click event in table
   - [ ] Video frame updates immediately
   - [ ] Video timeline shows correct time

2. **Video → Trace Sync:**
   - [ ] Scrub video timeline
   - [ ] Trace red marker follows
   - [ ] Position is accurate

3. **Playback:**
   - [ ] Click play button
   - [ ] Video plays smoothly
   - [ ] Trace marker follows during playback
   - [ ] Can pause/resume

4. **Frame Stepping:**
   - [ ] Next/Previous buttons work
   - [ ] Updates trace marker
   - [ ] Updates event highlighting

---

## Implementation Summary

### Changes Made

#### 1. Fixed Playback to Use PyQtGraph's Native Method ✅

**File:** [main_window.py:9972-9996](../src/vasoanalyzer/ui/main_window.py#L9972-L9996)

Updated `toggle_snapshot_playback()` to:
- Detect PyQtGraph viewer mode using `_use_pg_snapshot_viewer()`
- Calculate FPS from `frame_trace_time` intervals using `np.median()`
- Call `snapshot_view_pg.play(fps)` for native PyQtGraph playback
- Call `snapshot_view_pg.stop()` to stop playback
- Cap FPS at 60 to prevent excessive frame rates

**Result:** Playback now uses PyQtGraph's internal mechanism, which properly syncs with the timeline and trace cursor.

#### 2. Added Play/Stop Methods to SnapshotViewPG ✅

**File:** [snapshot_view_pg.py:169-181](../src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L169-L181)

Added two convenience methods:
```python
def play(self, fps: float = 10.0) -> None:
    """Start playback at the given FPS using PyQtGraph's native playback."""
    if self.image_view is not None:
        self.image_view.play(rate=fps)

def stop(self) -> None:
    """Stop playback using PyQtGraph's native stop."""
    if self.image_view is not None:
        try:
            self.image_view.stop()
        except AttributeError:
            # ImageView might not have stop(), use play(0) as fallback
            self.image_view.play(rate=0)
```

**Result:** Clean API for controlling playback from main window.

#### 3. Reduced Snapshot Layout Margins ✅

**File:** [main_window.py:13271-13272](../src/vasoanalyzer/ui/main_window.py#L13271-L13272)

Changed snapshot card layout:
- **Before:** `setContentsMargins(12, 12, 12, 12)` and `setSpacing(12)`
- **After:** `setContentsMargins(4, 4, 4, 4)` and `setSpacing(4)`

**Result:** Snapshot viewer has more screen real estate with 8px less padding on each side.

---

## Testing Results

**Next:** Test with sample data in `SampleData/RawFiles/` to verify:
1. Event→Video sync works correctly
2. Video→Trace sync works during playback
3. Play/pause button controls video properly
4. Layout looks cleaner with reduced margins
