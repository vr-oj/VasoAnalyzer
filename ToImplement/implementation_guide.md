# Quick Implementation Guide

## What I Fixed

I've created an improved version of your `event_labels_v3.py` file with two key changes:

### 1. **Better Lane Algorithm** (Best-Fit Instead of First-Fit)

**Before:**
```python
def _select_lane(...):
    # Uses first-fit: takes the first available lane
    for lane_index, lane_tail in enumerate(lane_end_px):
        if px >= lane_tail:
            return lane_index  # Returns immediately
```

**After:**
```python
def _select_lane(...):
    # Uses best-fit: finds all available lanes, picks the one with most room
    candidates = []
    for lane_index, lane_tail in enumerate(lane_end_px):
        if px >= lane_tail:
            candidates.append((lane_index, lane_tail))
    
    if candidates:
        # Pick lane with earliest end (most room remaining)
        best_lane = min(candidates, key=lambda x: x[1])[0]
        return best_lane
```

**Why This Helps:**
- Labels spread across lanes more evenly
- Prevents all labels from clustering in lane 0
- Keeps lower lanes (more visible) available for later labels

---

### 2. **Increased Horizontal Spacing** (6px → 12px)

**Before:**
```python
preferred_gap_px = 6.0
```

**After:**
```python
preferred_gap_px = 12.0  # Increased for better separation from dashed line
```

**Why This Helps:**
- Labels are clearly separated from the dashed event lines
- Easier to read
- Less visual clutter

---

## How to Use the Improved File

1. **Backup your current file:**
   ```bash
   cp event_labels_v3.py event_labels_v3_backup.py
   ```

2. **Replace with improved version:**
   ```bash
   cp event_labels_v3_improved.py event_labels_v3.py
   ```

3. **Test with your data:**
   - Run your application
   - Check that labels now spread across lanes
   - Verify labels don't overlap dashed lines

---

## Expected Improvements

Based on your screenshots:

### Before (Image 2):
```
All labels piled at top: "Set pressure Set pressure Set pressure..."
```

### After:
```
Lane 1: "Set pressure = 20.0 mmHg"  "Set pressure = 80.0 mmHg"
Lane 2: "Set pressure = 40.0 mmHg"  "Set pressure = 100.0 mmHg"
Lane 3: "Set pressure = 60.0 mmHg"  "Set pressure = 120.0 mmHg"
```

Labels will:
- ✅ Spread across 3 lanes instead of clustering
- ✅ Be clearly to the right of dashed lines (not overlapping)
- ✅ Not extend beyond plot boundaries (existing logic preserved)

---

## Additional Tuning (Optional)

If you want to fine-tune further, you can adjust these parameters in the code:

### In `_draw_horizontal_inside` method (line ~450):

```python
margin_px = 4.0           # Space from plot edge
preferred_gap_px = 12.0   # Space from dashed line (you can increase this)
min_gap_px = 2.0          # Minimum space if squeezing is needed
buffer_px = 12.0          # Space between labels in same lane
```

### In `LayoutOptionsV3` class (line ~64):

```python
lanes: int = 3            # Number of horizontal lanes (increase for more)
```

---

## What Didn't Change

The improved version preserves all existing features:
- Priority system
- Pinning
- Color overrides
- Font customization
- Clustering logic
- Boundary checking
- All three modes (vertical, h_inside, h_belt)

---

## If You Still See Issues

If labels still overlap after this fix, it may be because:

1. **Too many events in small space** → Increase `min_px` in clustering
2. **Font size too large** → Reduce base font size or enable adaptive sizing
3. **Too few lanes** → Increase `lanes` parameter from 3 to 4 or 5

Let me know if you need further adjustments!

---

## Changes Summary

| What | Before | After | Why |
|------|--------|-------|-----|
| Lane Algorithm | First-fit | Best-fit | Better distribution |
| Horizontal Gap | 6px | 12px | Clearer from lines |
| Distribution | Clusters in lane 0 | Spreads evenly | More readable |
