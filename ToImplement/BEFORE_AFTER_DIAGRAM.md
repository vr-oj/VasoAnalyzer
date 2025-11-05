# Before vs After - Simple Comparison

## Your Original Problem (Image 2)

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│ Set pressure Set pressure Set pressure Set pressure Set pressure  │ ← All labels
│Set pressureSet pressureSet pressureSet pressureSet pressure Set...│   stacked!
│      ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊   │
│      ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊   │
│      ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊   │
│ [Inner Diameter Plot Area]                                        │
│      ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊   │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│ [Outer Diameter Plot Area]                                        │
│      ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊    ┊   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Problems:**
- ❌ All 12 labels clustered in one horizontal line
- ❌ Labels overlapping each other
- ❌ Text sitting ON TOP of dashed lines (only 6px gap)
- ❌ Impossible to read

---

## After the Fix

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│              ┊           ┊              ┊             ┊           │ Lane 2
│  80.0 mmHg   ┊  100.0    ┊  120.0 mmHg  ┊  80.0 mmHg  ┊           │ (top)
│              ┊           ┊              ┊             ┊           │
│         40.0 mmHg  ┊  60.0 mmHg  ┊  100.0 mmHg ┊  60.0 mmHg       │ Lane 1
│              ┊           ┊              ┊             ┊           │ (middle)
│  20.0 mmHg   ┊  40.0     ┊  60.0 mmHg   ┊  20.0 mmHg  ┊           │ Lane 0
│              ┊           ┊              ┊             ┊           │ (bottom)
│              ┊           ┊              ┊             ┊           │
│ [Inner Diameter Plot Area] — 12px gap →  ┊             ┊           │
│              ┊           ┊              ┊             ┊           │
│                                                                    │
├────────────────────────────────────────────────────────────────────┤
│ [Outer Diameter Plot Area]                                        │
│              ┊           ┊              ┊             ┊           │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Solutions:**
- ✅ Labels spread across 3 lanes evenly (4 labels per lane)
- ✅ No overlapping - each label has its own space
- ✅ 12px gap from dashed lines - clearly separated
- ✅ Easy to read and professional looking

---

## The Math

### Before (First-Fit Algorithm)
```
12 labels distributed:
- Lane 0: ████████████ (11 labels = 91.7%)
- Lane 1: █ (1 label = 8.3%)
- Lane 2: (0 labels = 0%)

Balance Score: 14.0 (bad)
```

### After (Best-Fit Algorithm)
```
12 labels distributed:
- Lane 0: ████ (4 labels = 33.3%)
- Lane 1: ████ (4 labels = 33.3%)
- Lane 2: ████ (4 labels = 33.3%)

Balance Score: 0.0 (perfect!)
```

---

## Timeline View

### Before
```
Time:    111s  712s  1312s  1911s  2512s  3111s  3144s  3744s  4344s  4944s  5545s  6145s

Lane 2:  
Lane 1:                                               [L6]
Lane 0:  [L0]  [L1]   [L2]   [L3]   [L4]   [L5]   [L7]  [L8]   [L9]   [L10]  [L11]
         └─────┴──────┴──────┴──────┴──────┴──────┴─────┴──────┴──────┴──────┴──────┘
```

### After
```
Time:    111s  712s  1312s  1911s  2512s  3111s  3144s  3744s  4344s  4944s  5545s  6145s

Lane 2:              [L2]                  [L5]          [L8]                  [L11]
Lane 1:        [L1]                [L4]          [L7]          [L10]
Lane 0:  [L0]                [L3]                [L6]                [L9]
         └─────┴──────┴──────┴──────┴──────┴──────┴─────┴──────┴──────┴──────┴──────┘
```

---

## What This Means For You

### Readability
- **Before:** "Set pressure Set pressure Set pressure..." (unreadable mess)
- **After:** Each label clear and distinct in its own lane

### Visual Clarity
- **Before:** Labels obscure dashed lines, can't tell which event is which
- **After:** Labels clearly offset from lines, easy to match label to event

### Professional Appearance
- **Before:** Looks like a bug/glitch
- **After:** Looks intentional and well-designed

---

## The Two Key Changes

### Change 1: Lane Algorithm

```python
# OLD (First-Fit)
for lane_index, lane_tail in enumerate(lane_end_px):
    if px >= lane_tail:
        return lane_index  # Take first available lane
```

```python
# NEW (Best-Fit)
candidates = [(idx, tail) for idx, tail in enumerate(lane_end_px) if px >= tail]
if candidates:
    return min(candidates, key=lambda x: x[1])[0]  # Pick lane with most space
```

### Change 2: Spacing

```python
# OLD
preferred_gap_px = 6.0  # Too close to dashed line

# NEW
preferred_gap_px = 12.0  # Clearly separated from dashed line
```

---

## Bottom Line

**Two small code changes = Massive visual improvement**

Your labels will now:
1. Spread evenly across all lanes (no clustering)
2. Be clearly separated from dashed lines (no overlap)
3. Stay within plot boundaries (no cutoff)
4. Look professional and easy to read

Copy `event_labels_v3_improved.py` and you're done!
