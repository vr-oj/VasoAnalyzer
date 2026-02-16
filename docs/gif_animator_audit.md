# GIF Animator Audit

## Current pipeline overview (data -> timings -> frames -> save)
- Data inputs:
  - Vessel frames: `sample.snapshots` (TIFF stack already materialized in memory).
  - Trace data: `trace_model` for plotting and `sample.trace_data` for TIFF page -> trace time mapping.
  - Events: `events_df` for vertical markers.
- Timing extraction:
  - `_extract_frame_times()` attempts to build a TIFF frame time array aligned to trace time using the trace CSV TiffPage column (via `resolve_frame_times`). If that fails, it falls back to `sample.ui_state["snapshot_frame_times"]`, else estimates from a recording interval (`recording_interval`, default 0.14s). See `src/vasoanalyzer/ui/gif_animator/animator_window.py:245`.
- Timing -> keyframes:
  - `FrameSynchronizer` uses `frame_times`, `trace_model.time_full`, and the selected start/end to map animation time to the nearest TIFF frame index. Keyframes are either per TIFF frame (`use_tiff_frames=True`) or evenly spaced at target FPS (`use_tiff_frames=False`). See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:44` and `src/vasoanalyzer/ui/gif_animator/animator_window.py:1093`.
- Frame rendering:
  - `AnimationRenderer.render_frame()` draws a vessel panel and a trace panel, then composites them side-by-side or stacked. Vessel frames are cropped/rotated, normalized to uint8, resized with contain/cover behavior, and optionally annotated. Trace frames are rendered via Matplotlib or a cached "fast render". See `src/vasoanalyzer/ui/gif_animator/renderer.py:57`.
- Save/export:
  - Frames are saved as a GIF using a constant per-frame duration derived from FPS. See `src/vasoanalyzer/ui/gif_animator/renderer.py:851` and `src/vasoanalyzer/ui/gif_animator/animator_window.py:1300`.

## Timing sources and fallbacks (trace <-> TIFF)
- Primary (TiffPage -> trace time):
  - If `sample.trace_data` contains `tiff_page`/`TiffPage` and `t_seconds`/`Time (s)`, each TIFF page index maps to a trace row index, which maps to an absolute trace time. This uses `resolve_tiff_frame_times()` with `allow_fallback=False`, so any missing mapping aborts this path. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:257` and `src/vasoanalyzer/core/timebase.py:503`.
- Secondary (UI state):
  - Uses `sample.ui_state["snapshot_frame_times"]` if present and length matches `n_frames`. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:298`.
- Tertiary (estimation):
  - Uses a fixed `recording_interval` (default 0.14s), converted to FPS. This generates frame times starting at 0. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:313` and `src/vasoanalyzer/core/timebase.py:675`.
- Shared time mapping utilities:
  - `resolve_tiff_frame_times()` in `src/vasoanalyzer/core/timebase.py:503` handles TiffPage mapping, interpolation, TIFF metadata FrameTime, and FPS-based fallbacks.
  - `derive_tiff_page_times()` and trace import attach `tiff_page_to_trace_idx` in `src/vasoanalyzer/io/trace_events.py:263`.

### How sync is computed (trace <-> TIFF)
- `FrameSynchronizer.get_frame_for_time()` maps an animation time `t` to an absolute time `animation_start + t`, then uses `np.searchsorted` to select the nearest TIFF frame index. See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:99`.
- When `use_tiff_frames=True`, keyframes are the TIFF frames in the selected time range (optionally downsampled or repeated for `playback_speed`). `trace_time_s` is set to the TIFF frame's timestamp. See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:179`.
- When `use_tiff_frames=False`, keyframes are evenly spaced at `fps / playback_speed` and each keyframe's trace time is the animation time, with the vessel frame chosen by nearest timestamp. See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:145`.
- The trace panel uses `timing.trace_time_s` to plot the progressive window and to position the time indicator. See `src/vasoanalyzer/ui/gif_animator/renderer.py:257`.

## Layout modes and edge cases
- Side-by-side (`layout_mode="side_by_side"`):
  - Vessel and trace panels are padded to equal height and concatenated. Padding uses white (255) even if the vessel background color is not white. See `src/vasoanalyzer/ui/gif_animator/renderer.py:77` and `src/vasoanalyzer/ui/gif_animator/renderer.py:824`.
  - Auto vessel width clamps to ~40% of total width to favor trace readability. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:382`.
- Stacked (`layout_mode="stacked"`):
  - Vessel frames are rotated 90 degrees before resize to match the strip layout. If a crop ROI was chosen in the unrotated view, it may not correspond to the post-rotation layout. See `src/vasoanalyzer/ui/gif_animator/renderer.py:121`.
- Fit mode:
  - `contain` scales to fit within the panel and pads with background color. `cover` scales to fill and crops center. See `src/vasoanalyzer/ui/gif_animator/renderer.py:157`.
- Wide trace shape:
  - `shape="wide"` reduces the trace height and implicitly shrinks the vessel content height, which can introduce extra top/bottom padding when side-by-side. See `src/vasoanalyzer/ui/gif_animator/renderer.py:154` and `src/vasoanalyzer/ui/gif_animator/renderer.py:745`.

## Rendering quality concerns
- Per-frame intensity normalization for vessel frames (`vmax = frame.max()` each frame) can cause brightness flicker across frames when the max changes over time. See `src/vasoanalyzer/ui/gif_animator/renderer.py:131`.
- GIF palette quantization is left to Pillow defaults; no shared palette is enforced, so per-frame palette differences can cause color flicker and banding. See `src/vasoanalyzer/ui/gif_animator/renderer.py:851`.
- Matplotlib line antialiasing is disabled, which can make thin traces look jagged in smaller output sizes. See `src/vasoanalyzer/ui/gif_animator/renderer.py:298`.
- Text overlays (timestamps/event labels) rely on default fonts if Arial is missing, which can change sizing and clarity across platforms. See `src/vasoanalyzer/ui/gif_animator/renderer.py:205`.

## Performance + memory profile risks
- Frames are rendered and stored in memory before export. Memory scales as `n_frames * width * height * 3`, which can exceed hundreds of MB quickly. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:1273`.
- Non-fast trace rendering redraws a full Matplotlib plot per frame, which is CPU-heavy and can be slow for long durations. See `src/vasoanalyzer/ui/gif_animator/renderer.py:230`.
- `use_tiff_frames=True` can generate very large frame counts for long recordings, even when the final GIF duration is short, because GIF uses constant duration per frame. See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:179`.

## Failure modes that cause bad GIFs
- Incorrect timing/sync:
  - Non-monotonic `frame_times` break `np.searchsorted` assumptions and can misalign vessel and trace frames. See `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:115` and `src/vasoanalyzer/core/timebase.py:703`.
  - `use_tiff_frames=True` ignores irregular inter-frame spacing; all GIF frames use a uniform duration, so the exported animation can run too fast/slow relative to the trace. See `src/vasoanalyzer/ui/gif_animator/renderer.py:874`.
  - Fallback estimation starts at 0 seconds; if the trace timebase does not start at 0, the trace window and vessel frames can drift. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:313`.
- Unreadable output:
  - Per-frame intensity normalization can cause flicker and low contrast if one frame has a bright outlier. See `src/vasoanalyzer/ui/gif_animator/renderer.py:131`.
  - Line antialiasing disabled + low resolution can make traces jagged. See `src/vasoanalyzer/ui/gif_animator/renderer.py:298`.
- Distortion/clipping:
  - `cover` fit mode crops content; if users switch to cover (or if defaults change later), vessel edges can be clipped. See `src/vasoanalyzer/ui/gif_animator/renderer.py:176`.
  - Stacked mode rotates frames; pre-rotation crops can clip the wrong area after rotation. See `src/vasoanalyzer/ui/gif_animator/renderer.py:121`.
- Palette/quantization issues:
  - No fixed palette or dithering control leads to banding and per-frame palette shifts, especially with gradients or overlays. See `src/vasoanalyzer/ui/gif_animator/renderer.py:851`.
- Render failures:
  - Event times are not coerced to numeric in `_create_render_context`. If they are strings (for example hh:mm:ss), rendering can throw comparison errors. See `src/vasoanalyzer/ui/gif_animator/animator_window.py:1199`.

## Concrete prioritized fixes (P0/P1/P2)

### P0 (correctness)
- Enforce numeric event times before rendering (coerce or skip invalid rows) to prevent render crashes. `src/vasoanalyzer/ui/gif_animator/animator_window.py:1199`.
- Add monotonicity validation for `frame_times` and abort or normalize when invalid to protect `np.searchsorted` logic. `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:115` and `src/vasoanalyzer/ui/gif_animator/animator_window.py:245`.
- Encode variable per-frame durations when `use_tiff_frames=True` and frame intervals are irregular. Use `FrameTimingInfo` to compute `duration_ms` per frame and pass `duration=[...]` to Pillow. `src/vasoanalyzer/ui/gif_animator/frame_synchronizer.py:179` and `src/vasoanalyzer/ui/gif_animator/renderer.py:851`.
- Preserve trace time alignment when using estimation by offsetting estimated frame times to the trace start time (or by capturing time_offset in `resolve_frame_times`). `src/vasoanalyzer/ui/gif_animator/animator_window.py:313` and `src/vasoanalyzer/core/timebase.py:703`.

### P1 (readability defaults)
- Stabilize vessel intensity scaling across frames (use a global percentile or fixed min/max, not per-frame max) to avoid flicker. `src/vasoanalyzer/ui/gif_animator/renderer.py:131`.
- Use a shared palette for GIF export (quantize once on a representative frame, then apply to all frames) to reduce palette flicker and banding. `src/vasoanalyzer/ui/gif_animator/renderer.py:851`.
- Make padding color match `vessel_bg_color` for side-by-side padding to avoid white seams. `src/vasoanalyzer/ui/gif_animator/renderer.py:824`.

### P2 (quality/optimization)
- Allow optional antialiasing for trace lines and text when output size is large enough to benefit. `src/vasoanalyzer/ui/gif_animator/renderer.py:298`.
- Add a max-frame guard or streaming export mode to avoid high memory usage on long recordings. `src/vasoanalyzer/ui/gif_animator/animator_window.py:1093` and `src/vasoanalyzer/ui/gif_animator/renderer.py:851`.
- Precompute a cached trace window even for non-fast render when `n_frames` is large (adaptive fallback). `src/vasoanalyzer/ui/gif_animator/renderer.py:230`.

## Proposed safe defaults in `AnimationSpec`
These defaults prioritize predictable output, manageable memory usage, and readable traces for most datasets:
- `fps=10` and `playback_speed=1.0` (balanced smoothness vs size).
- `use_tiff_frames=False` by default for GIF export (prevents huge frame counts and avoids irregular TIFF timing being flattened into constant duration frames).
- `output_width_px=800`, `output_height_px=400`, `layout_mode="side_by_side"`, `auto_vessel_width=True` (consistent footprint, trace readability).
- `vessel_fit="contain"`, `vessel_interpolation="bilinear"`, `vessel_show_timestamp=False` (avoid cropping and reduce aliasing).
- `trace_spec.fast_render=True`, `trace_spec.shape="balanced"`, `trace_spec.show_events=True`, `trace_spec.show_event_labels=False`, `trace_spec.show_time_indicator=True` (readable and performant).
- `optimize=True`, `quality` ignored for GIF (document this to avoid confusion).

If a dataset has a uniform, trustworthy TIFF frame interval and limited frame count, enabling `use_tiff_frames=True` can be appropriate, but should be paired with per-frame duration export.
