# Event Labels Analysis & Fixes

## Problem Summary

Based on your screenshots and code, there are three main issues with horizontal event labels:

### 1. **Labels Overlap When Horizontal** (Image 2)
All labels cluster at the top in a messy pile because they're all trying to occupy the same vertical space without proper lane assignment.

### 2. **Labels On Top of Dashed Line**
Labels are positioned directly at the x-position of the event line, making them overlap the dashed vertical lines instead of being offset to the right.

### 3. **Labels Extend Beyond Plot Boundaries**
Labels can get cut off at the edges of the plot area.

---

## Root Causes

### Issue 1: Overlapping Labels (Lane Assignment)

**In `event_labels.py` (original version):**

The lane assignment logic around line 608-642 has problems:

```python
# Line 608-642 in _draw_horizontal_inside
lane_right_px = [-float("inf")] * lanes  # Tracks rightmost pixel per lane

# For each cluster:
for idx_lane, right_edge in enumerate(lane_right_px):
    if text_left >= right_edge:  # <-- PROBLEM!
        lane_idx = idx_lane
        break
```

**The Problem:**
- The code checks if `text_left >= right_edge`, which means "can I fit in this lane?"
- But it only checks lanes sequentially and takes the *first* available lane
- This causes all labels to cluster in lane 0 if there's even a tiny gap
- The lane tracking (`lane_right_px`) may not account for all the space the label needs

**In `event_labels_v3.py`:**

The v3 version has similar logic around line 489:

```python
lane_index = self._select_lane(left_px, width, lane_end_px)
```

This calls a helper function that should be better, but may still have issues if labels are densely packed.

---

### Issue 2: Labels On The Line

**Both versions:** Labels are positioned at `cluster.x` (the exact event time) with a small offset:

```python
# event_labels.py line ~645
offset = total_pad if not align_right else -total_pad
# where total_pad is just horizontal_x_pad_px (default 6.0 pixels)

# The transform places the label at:
transform = base_transform + ScaledTranslation(offset / dpi, 0.0, ...)
```

**The Problem:**
- `offset` is too small (6px default)
- The label's horizontal alignment (`ha`) is set to "left" by default
- So the *start* of the text is only 6px from the line
- This makes it look like the label is on top of the line

**What We Want:**
- Labels should be clearly to the right of the dashed line
- Need a larger horizontal offset (e.g., 10-15px minimum)
- May want to position labels with their left edge at the offset, not their center

---

### Issue 3: Boundary Clipping

**Both versions** have logic to prevent clipping (lines 639-660 in original, 466-487 in v3):

```python
# Check if label extends beyond right edge
if text_right > axes_bbox.x1 - buffer_px:
    # Flip to left-aligned
    align_right = True
```

**The Problem:**
- This logic works, but it's reactive - it only flips alignment after detecting overflow
- It doesn't prevent the label from being placed in a bad position initially
- The buffer values may be too small
- No consideration for zoom level or very dense labels

---

## Recommended Solutions

### Fix 1: Improve Lane Assignment Algorithm

**Strategy:** Use a greedy "best-fit" approach instead of "first-fit"

```python
def _select_lane_improved(self, left_px: float, width_px: float, 
                          lane_end_px: list[float], buffer_px: float = 12.0) -> int:
    """
    Select the lane with the most leftward end position that can fit this label.
    This spreads labels across lanes more evenly.
    """
    right_px = left_px + width_px + buffer_px
    
    # Find all lanes where this label can fit
    candidates = []
    for lane_idx, lane_end in enumerate(lane_end_px):
        if left_px >= lane_end:  # Label can fit without overlap
            candidates.append((lane_idx, lane_end))
    
    if candidates:
        # Pick the lane with the earliest end (most room remaining)
        # This keeps labels as low as possible and spreads them out
        best_lane = min(candidates, key=lambda x: x[1])[0]
        return best_lane
    else:
        # No lane is free - pick the one that ends earliest
        # (will cause overlap, but minimizes it)
        return min(range(len(lane_end_px)), key=lambda i: lane_end_px[i])
```

**Key Changes:**
1. Consider *all* possible lanes, not just the first available
2. Choose the lane with the earliest end position (most room left)
3. This naturally spreads labels across lanes

---

### Fix 2: Increase Horizontal Offset from Dashed Line

**Strategy:** Make labels clearly offset from the vertical line

```python
# In LayoutOptions or similar config
horizontal_x_pad_px: float = 12.0  # Increase from 6.0 to 12.0+

# In rendering code, ensure minimum offset
min_offset_px = 12.0
offset_px = max(min_offset_px, horizontal_x_pad_px + user_override)

# Always use left alignment for horizontal labels
ha = "left"  # Don't use center or right by default
```

**Improvements:**
- Double the default horizontal padding (6px → 12px)
- Add a configurable minimum offset
- Always start labels to the right of the line (left-aligned text)

---

### Fix 3: Better Boundary Awareness

**Strategy:** Calculate safe positioning zones upfront

```python
def _calculate_safe_label_zone(self, ax: Axes, renderer, margin_px: float = 8.0):
    """
    Calculate the safe rendering zone for labels, accounting for axes boundaries.
    Returns (left_px, right_px) bounds.
    """
    bbox = ax.get_window_extent(renderer=renderer)
    
    left_boundary_px = bbox.x0 + margin_px
    right_boundary_px = bbox.x1 - margin_px
    
    return left_boundary_px, right_boundary_px

# Then in label placement:
left_safe, right_safe = self._calculate_safe_label_zone(ax, renderer)

# Clamp label position
if left_px < left_safe:
    left_px = left_safe
if right_px > right_safe:
    # Either truncate or flip to left-aligned from line
    if can_fit_left_of_line:
        # Place label to left of line instead
        left_px = max(event_x_px - width_px - offset_px, left_safe)
    else:
        # Truncate text or reduce font size
        pass
```

---

### Fix 4: Density-Based Font Scaling

**Strategy:** Automatically reduce font size when many labels are present

```python
def _adaptive_fontsize(self, base_size: float, num_visible_labels: int, 
                       plot_width_px: float) -> float:
    """
    Scale down font size based on label density.
    """
    # Calculate approximate labels per 100 pixels
    density = (num_visible_labels * 100.0) / max(plot_width_px, 100.0)
    
    if density < 0.5:  # Sparse
        return base_size
    elif density < 1.0:  # Moderate
        return base_size * 0.9
    elif density < 2.0:  # Dense
        return base_size * 0.8
    else:  # Very dense
        return max(base_size * 0.7, 7.0)  # Don't go below 7pt
```

---

## Priority System Enhancement

Your editor has a "priority" field - this should influence lane assignment:

```python
# Sort clusters by priority before lane assignment
clusters_sorted = sorted(clusters, key=lambda c: (-c.max_priority, c.px))

# High priority labels get first pick of lanes (stay lower/more visible)
# Low priority labels get pushed to upper lanes
```

---

## Implementation Checklist

### Quick Wins (Minimal Code Changes)
- [ ] Increase `horizontal_x_pad_px` from 6.0 to 12.0 in LayoutOptions
- [ ] Change default `ha` to always be "left" for horizontal mode
- [ ] Add minimum offset check before placing labels

### Medium Effort (Better Lane Logic)
- [ ] Replace first-fit lane algorithm with best-fit
- [ ] Sort clusters by priority before lane assignment
- [ ] Improve lane_right_px tracking to include buffer space

### Advanced (Optimal Solution)
- [ ] Implement safe zone calculation upfront
- [ ] Add adaptive font scaling based on density
- [ ] Add label truncation or ellipsis for very long labels
- [ ] Consider two-pass layout: place high-priority first, then fill in

---

## Code Locations to Modify

### In `event_labels.py`:

1. **LayoutOptions** (line 36-69):
   - Change `horizontal_x_pad_px: float = 6.0` to `12.0`

2. **_draw_horizontal_inside** (line 586-720):
   - Modify lane selection logic (lines 608-642)
   - Update offset calculation (line 645)
   - Improve boundary checking (lines 639-660)

3. **_draw_horizontal_outside** (similar changes needed)

### In `event_labels_v3.py`:

1. **LayoutOptionsV3** (line 65-83):
   - Add min_offset_px parameter

2. **_draw_horizontal_inside** (line 429-517):
   - Improve `_select_lane` method
   - Update offset_px calculation (line 462)

3. **_select_lane** method (needs to be added or improved)

---

## Testing Recommendations

1. **Test with your current data** (12 events as shown)
2. **Test with more events** (20, 50, 100)
3. **Test with zoom** (zoomed in vs zoomed out)
4. **Test with long labels** vs short labels
5. **Test priority system** - ensure high-priority labels stay visible

---

## Summary

The core issues are:
1. **Lane assignment is first-fit instead of best-fit** → labels pile up
2. **Horizontal offset is too small** → labels overlap lines
3. **Boundary checking is reactive** → labels still get clipped

The fixes are relatively straightforward:
- Better lane algorithm
- Larger default offsets
- Priority-based sorting
- Optional: density-aware font sizing

Would you like me to create a patched version of one of your files with these fixes implemented?
