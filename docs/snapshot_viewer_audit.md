# Snapshot Viewer Audit Report

**Audit Date:** December 4, 2025
**Scope:** VasoAnalyzer Snapshot Viewer - TIFF display, frame playback, and UI polish assessment
**Status:** No code changes recommended at this time - audit findings only

---

## Executive Summary

The VasoAnalyzer snapshot viewer has a **solid architectural foundation** with dual viewer support (legacy QLabel + experimental PyQtGraph) and implemented time synchronization infrastructure. However, **critical limitations exist**: the viewer cannot display full TIFF stacks, playback-trace synchronization accuracy needs investigation and fixes, and the experimental status of the PyQtGraph viewer indicates incomplete production readiness. While the core functionality works well for typical use cases, several issues impact professional polish and user experience.

### Critical Findings
1. **The snapshot viewer CANNOT display full TIFF stacks.** TIFFs with more than 300 frames are automatically subsampled, with frames evenly skipped to reduce the stack to 300 frames. This is a hard-coded limitation in the TIFF loading logic ([tiffs.py:67-93](src/vasoanalyzer/io/tiffs.py#L67-L93)) with no UI option to override.

2. **Playback-trace synchronization requires investigation.** While sync infrastructure is implemented, the accuracy of timing synchronization between video playback and trace data needs verification and potential fixes.

---

## 1. Architecture Overview

### Dual Viewer System

**File Locations:**
- **Legacy Viewer**: [main_window.py:9733-9794](src/vasoanalyzer/ui/main_window.py#L9733-L9794) (QLabel with QPixmap scaling)
- **PyQtGraph Viewer**: [snapshot_view_pg.py](src/vasoanalyzer/ui/panels/snapshot_view_pg.py) (254 lines, ImageView wrapper)
- **TIFF Loader**: [tiffs.py](src/vasoanalyzer/io/tiffs.py) (137 lines)
- **UI Layout**: [init_ui.py:194-277](src/vasoanalyzer/ui/shell/init_ui.py#L194-L277)
- **Playback Control**: [main_window.py:10010-10093](src/vasoanalyzer/ui/main_window.py#L10010-L10093)

**Layout Hierarchy:**
```
snapshot_card (QFrame)
├── snapshot_stack (QStackedWidget) ─── switches between viewers
│   ├── snapshot_label (legacy QLabel)
│   └── snapshot_view_pg (SnapshotViewPG with PyQtGraph ImageView)
├── slider (QSlider) ─── frame navigation
├── snapshot_controls (QWidget) ─── playback buttons + speed control
│   ├── prev_frame_btn (Skip Backward)
│   ├── play_pause_btn (Play/Pause toggle)
│   ├── next_frame_btn (Skip Forward)
│   ├── snapshot_speed_combo (0.25x to 4x)
│   └── snapshot_time_label (status: "Frame 42 / 300 @ 5.88 s")
└── metadata_panel (QFrame with scroll area)
```

**Viewer Selection:**
- Menu: View → "Use PyQtGraph snapshot viewer (experimental)"
- Default: Legacy QLabel viewer (checkbox unchecked)
- PyQtGraph viewer explicitly labeled as **"experimental"**

---

## 2. TIFF Display Assessment

### ❌ Does NOT Always Show Full TIFF

**Critical Limitation: 300 Frame Cap**

Location: [tiffs.py:67-93](src/vasoanalyzer/io/tiffs.py#L67-L93)

```python
def load_tiff(file_path, max_frames=300, metadata=True):
    # ...
    with tifffile.TiffFile(file_path) as tif:
        total_frames = len(tif.pages)
        skip = max(1, round(total_frames / max_frames))  # ← Subsampling here

        for i in range(0, total_frames, skip):  # ← Frames are skipped
            # ...
```

**Impact:**
- TIFFs with >300 frames are **automatically downsampled** to ~300 frames
- Subsampling is **uniform** (every Nth frame) - not intelligent selection
- **No UI warning** that frames are being skipped
- **No user option** to load full TIFF or adjust the limit
- Users analyzing temporal dynamics may miss critical frames

**Example:** A 1000-frame TIFF would skip every 3rd frame (skip=3), loading only 333 frames.

### Image Scaling & Aspect Ratio

**Legacy Viewer** ([main_window.py:9769-9781](src/vasoanalyzer/ui/main_window.py#L9769-L9781)):
- Uses `QPixmap.scaledToWidth()` with `Qt.SmoothTransformation`
- Maintains aspect ratio automatically
- Target width calculated with fallback chain: `snapshot_stack.width()` → `snapshot_label.width()` → `event_table.viewport().width()`
- **Issue**: Complex width calculation may cause unpredictable scaling on resize

**PyQtGraph Viewer** ([snapshot_view_pg.py:50-58](src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L50-L58)):
- Uses `view_box.setAspectLocked(True)` - guarantees correct aspect ratio
- `setDefaultPadding(0.0)` - removes padding for maximum image area
- `setMouseEnabled(x=False, y=False)` - disables mouse pan/zoom for stability
- **Superior approach** - more robust than legacy viewer

**Color Handling:**
- Both viewers convert **RGB to grayscale** using luminance weights (0.299R + 0.587G + 0.114B)
- [snapshot_view_pg.py:198-207](src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L198-L207)
- **Lossy conversion** - color information is discarded
- No option for native RGB/color display

---

## 3. Frame Playback Assessment

### ✅ Playback Works (But Only for Loaded Frames)

**Controls:**
- ✅ Previous/Next buttons step through frames
- ✅ Play/Pause toggle with looping at end
- ✅ Speed control: 0.25x, 0.5x, 1x, 1.5x, 2x, 3x, 4x presets
- ✅ Slider for direct frame navigation
- ✅ Frame status display: "Frame 42 / 300 @ 5.88 s"

**Playback Implementation** ([main_window.py:10010-10093](src/vasoanalyzer/ui/main_window.py#L10010-L10093)):
- Uses `QTimer` with dynamic interval based on frame timing
- Interval calculated from median frame time differences or fallback `recording_interval` (0.14s)
- Minimum interval: 20ms (max 50 fps)
- Effective interval = `base_interval / speed_multiplier`
- **Loops at end** - `next_idx = (current_frame + 1) % len(snapshot_frames)`

**Time Synchronization** (Implemented but Needs Verification):
- Bidirectional sync with main trace plot implemented
- Canonical time source: `trace["Time (s)"]` column
- Frame mapping via `trace["TiffPage"]` column
- Clicking video updates plot cursor; clicking plot updates video frame
- [main_window.py:8938-9013](src/vasoanalyzer/ui/main_window.py#L8938-L9013) - `_derive_frame_trace_time()`
- **Issue:** Synchronization accuracy requires investigation and potential fixes

### ❌ Cannot Play All Frames (Due to 300 Frame Limit)

Since TIFFs are subsampled at load time, playback **only plays the loaded subset** (max ~300 frames), not the full stack. Users working with high-speed imaging or long recordings will experience:
- Skipped temporal events
- Discontinuous motion
- Loss of analytical fidelity

---

## 4. Polish & Professionalism Assessment

### Strengths ✅

**Architecture:**
- Clean signal/slot architecture ([snapshot_view_pg.py:35-36](src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L35-L36))
- Well-documented API (`set_stack`, `set_frame_index`, `set_current_time`)
- Proper separation of concerns (TIFF loading, display, playback)
- Graceful fallbacks (PyQtGraph → legacy viewer switching)

**User Experience:**
- Rotation context menu (right-click → rotate 90° left/right/reset)
- Metadata extraction and display with copy-to-clipboard
- Theme integration (`CURRENT_THEME.get("snapshot_bg")`)
- Responsive layout with `QSizePolicy.Expanding`
- Status feedback ("Frame X / Y @ Z.ZZ s")

**Time Synchronization:**
- Sync infrastructure implemented with trace data integration
- Handles edge cases (missing trace columns, fallback timing)
- **Sync accuracy requires investigation and potential fixes**

### Weaknesses ❌

**1. Experimental Status**
- PyQtGraph viewer menu label: **"Use PyQtGraph snapshot viewer (experimental)"**
- Indicates incomplete production readiness despite superior architecture
- Default viewer is legacy QLabel implementation

**2. Debug Logging in Production Code**

[main_window.py:9763-9791](src/vasoanalyzer/ui/main_window.py#L9763-L9791):
```python
log.info("LegacySnapshotView: frame shape=%s bytesPerLine=%s", ...)
log.info("LegacySnapshotView.default_rect: frame=%d rect=%s ...", ...)
```

- Multiple `log.info()` calls on every frame display (hot path)
- Should be `log.debug()` or removed in production builds
- Performance impact on high-frame-rate playback

**3. Layout Instability Indicators**

Evidence from code:
- Method `_log_snapshot_column_geometries()` suggests ongoing sizing issues
- Resize event handling deferred with `QTimer.singleShot` ([main_window.py](src/vasoanalyzer/ui/main_window.py))
- Complex target width calculation with multiple fallbacks

**4. No User Feedback on Frame Limit**
- Silent subsampling - users don't know frames are being skipped
- No warning dialog or status bar message
- No tooltip explaining the 300-frame limitation

**5. Basic Metadata Display**
- Arrays truncated at 16 elements in metadata panel
- Raw tag values shown (not user-friendly formatting)
- No persistent storage for manually loaded TIFF metadata

**6. No Full-Resolution Optimization**
- All frames materialized in memory simultaneously
- No lazy loading or streaming for large stacks
- No caching or performance optimization

**7. Status Feedback Brevity**
- Status bar messages dismissed after 2 seconds
- May be too brief for users to read

---

## 5. Detailed Issue Inventory

| # | Severity | Category | Issue | Location |
|---|----------|----------|-------|----------|
| 1 | **CRITICAL** | Functionality | 300 frame hard limit with silent subsampling | [tiffs.py:67-93](src/vasoanalyzer/io/tiffs.py#L67-L93) |
| 2 | High | Completeness | PyQtGraph viewer marked "experimental" | [main_window.py](src/vasoanalyzer/ui/main_window.py) (menu action) |
| 3 | High | Performance | RGB→grayscale conversion lossy (no color display option) | [snapshot_view_pg.py:198-207](src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L198-L207) |
| 4 | Medium | Polish | Debug `log.info()` in display hot path | [main_window.py:9763-9791](src/vasoanalyzer/ui/main_window.py#L9763-L9791) |
| 5 | Medium | UX | No warning when frames are subsampled | [tiffs.py](src/vasoanalyzer/io/tiffs.py) |
| 6 | Medium | UX | No UI option to adjust max_frames limit | [tiffs.py](src/vasoanalyzer/io/tiffs.py) |
| 7 | Medium | Layout | Complex width calculation with fallback chain | [main_window.py:9769-9777](src/vasoanalyzer/ui/main_window.py#L9769-L9777) |
| 8 | Low | Performance | All frames materialized in memory (no lazy loading) | [tiffs.py:88-129](src/vasoanalyzer/io/tiffs.py#L88-L129) |
| 9 | Low | Polish | Metadata display basic (arrays truncated at 16 elements) | [main_window.py](src/vasoanalyzer/ui/main_window.py) |
| 10 | Low | UX | Status messages dismissed after 2 seconds | [main_window.py](src/vasoanalyzer/ui/main_window.py) |
| 11 | **High** | Functionality | Playback-trace sync accuracy needs investigation/fixes | [main_window.py:8938-9013](src/vasoanalyzer/ui/main_window.py#L8938-L9013) |

---

## 6. Comparison: Legacy vs PyQtGraph Viewer

| Feature | Legacy (QLabel) | PyQtGraph (SnapshotViewPG) | Winner |
|---------|----------------|---------------------------|--------|
| **Aspect ratio** | `scaledToWidth()` (good) | `setAspectLocked(True)` (better) | **PG** |
| **Performance** | QPixmap operations can be slow | Hardware-accelerated rendering | **PG** |
| **Scaling robustness** | Complex width fallback chain | Built-in responsive scaling | **PG** |
| **Features** | Basic display only | Context menu rotation | **PG** |
| **Code quality** | Debug logging in hot path | Clean API, proper signals | **PG** |
| **Production status** | Default (production) | Experimental | **Legacy** |
| **User trust** | Established | Experimental label undermines confidence | **Legacy** |

**Recommendation:** The PyQtGraph viewer is architecturally superior but needs **experimental label removed** and **thorough testing** to become the default.

---

## 7. Code Quality Observations

### Excellent Patterns ✅
- Signal/slot architecture ([snapshot_view_pg.py:35-36](src/vasoanalyzer/ui/panels/snapshot_view_pg.py#L35-L36))
- Context manager usage (`contextlib.suppress`, `with tifffile.TiffFile(...)`)
- Graceful error handling with logging
- Type hints in PyQtGraph viewer (`_t.Optional[...]`)
- Defensive programming (clipping indices, fallback values)

### Needs Improvement ❌
- Debug logging in production hot paths
- Magic numbers (`max_frames=300`, `min_interval=20ms`, `min_height=220px`)
- Complex conditional chains for width calculation
- Silent failures (frame subsampling, metadata truncation)
- Incomplete migration (dual viewer system suggests transition in progress)

---

## 8. User Experience Flow Analysis

### Typical User Journey:

1. **Load TIFF** → Silent subsampling if >300 frames ❌
2. **View snapshot** → Displays correctly with aspect ratio ✅
3. **Play video** → Smooth playback with speed control ✅
4. **Navigate frames** → Slider + buttons work well ✅
5. **Sync with traces** → Sync implemented but accuracy needs verification ⚠️
6. **Rotate image** → Context menu rotation works ✅

### Pain Points:
- **No feedback on frame limit** - users unaware of data loss
- **Experimental label** - undermines confidence in PG viewer
- **No color display** - may be important for certain experiments
- **Brief status messages** - easy to miss

---

## 9. Summary Assessment

### Does it always show the full TIFF?
**❌ NO** - Hard-coded 300 frame limit with silent subsampling. TIFFs with >300 frames are automatically reduced, with no user warning or option to override.

### Can it play all frames of the TIFF stack?
**❌ NO** - Only plays the loaded subset (max ~300 frames). Full playback requires removing the frame limit.

### Does it look polished and professional?
**⚠️ PARTIALLY** - Core functionality is solid with excellent time synchronization and good UI design, but:
- "Experimental" label undermines professionalism
- Debug logging in production code
- Silent frame subsampling (data integrity concern)
- Layout instability indicators
- No user control over critical parameters

### Overall Grade: **B-** (Good architecture, critical functionality gaps)

**Strengths:**
- Dual viewer system shows forward planning
- Clean PyQtGraph implementation
- Professional playback controls
- Time sync infrastructure implemented

**Critical Gaps:**
- Cannot display full TIFFs (300 frame limit)
- Experimental status not production-ready
- Silent data loss (subsampling)
- Missing user controls
- Playback-trace synchronization accuracy needs investigation/fixes

---

## 10. Recommendations (For Future Implementation)

### Priority 1: Critical Functionality
1. **Investigate and fix playback-trace synchronization** - verify timing accuracy between video frames and trace data
2. **Remove 300 frame limit** or make it user-configurable
3. **Add warning dialog** when TIFFs are subsampled: "This TIFF contains 1000 frames. Loading 300 frames (every 3rd frame). Load all frames? [Yes] [No]"
4. **Promote PyQtGraph viewer** to production status (remove "experimental" label)
5. **Switch default** to PyQtGraph viewer after thorough testing

### Priority 2: Polish & Professionalism
6. **Remove debug logging** from display hot paths (change `log.info` → `log.debug`)
7. **Add progress indicator** for large TIFF loading
8. **Simplify width calculation** - remove fallback chain complexity
9. **Add tooltips** explaining frame limit and controls

### Priority 3: Feature Enhancements
10. **Support color display** - option to preserve RGB TIFFs
11. **Add frame export** - save current frame or frame range as images
12. **Lazy loading** - stream frames on demand for very large stacks
13. **Metadata improvements** - better formatting, persistent storage
14. **Frame interpolation** - smooth playback for subsampled stacks

---

## Conclusion

The VasoAnalyzer snapshot viewer has a **solid technical foundation** with thoughtful architecture and implemented sync infrastructure. The PyQtGraph implementation demonstrates professional design patterns. However, **critical gaps exist**: the 300 frame limitation prevents displaying full TIFF stacks, playback-trace synchronization accuracy needs investigation and fixes, and the "experimental" status of the superior viewer undermines user confidence.

**Primary recommendation:** Address playback-trace sync accuracy (Priority 1.1), remove the frame limit (Priority 1.2-1.3), and promote the PyQtGraph viewer to production status (Priority 1.4-1.5) to achieve professional-grade snapshot viewing.

**Key Files to Review:**
- [tiffs.py](src/vasoanalyzer/io/tiffs.py) - Frame limit removal
- [snapshot_view_pg.py](src/vasoanalyzer/ui/panels/snapshot_view_pg.py) - Production readiness
- [main_window.py](src/vasoanalyzer/ui/main_window.py) - Debug logging cleanup
- [init_ui.py](src/vasoanalyzer/ui/shell/init_ui.py) - UI polish

---

**End of Audit Report**
