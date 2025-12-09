# Pure Matplotlib Figure Composer – Phase 1 alignment notes

- Reported mismatch: preview vs PNG/PDF disagree for event verticals/dashed lines, event rectangles/pressure boxes, and the top-left “mmHg / 80” box (other overlays suspected). Scientific data/timings stay correct; issue appears to be annotation rendering.
- Preview path: persistent `FigureCanvasQTAgg` at `preview_dpi` (100) in `PureMplFigureComposer._update_preview` → `render_into_axes` embeds a GridSpec inside a page-sized axes; annotations are drawn onto an overlay axes (`transAxes`).
- Export path: `export_figure` rebuilds a fresh Matplotlib Figure per output via `render_figure` (Agg/PDF backends) with export DPI; the preview Figure instance is not reused.
- Annotated audit notes live inline in `renderer.py` (event lines/labels, panel labels, annotation transforms) and `composer_window.py` (preview overlay transforms, TODOs).

## Debug export helper (for visual diffs)
- Call `PureMplFigureComposer._debug_export_all_backends("composer_alignment_test")` from a REPL/dev hook after loading a sample project and placing event boxes/lines similar to the repro.
- Outputs land in `./_debug_exports/`: `_screen_like.png` (preview DPI), `_highdpi.png` (300 dpi), `.pdf`. Compare these with a preview screenshot to spot shifts.

## Planned unified coordinate & sizing strategy (Phase 2 design)
- Time-based objects (event lines/boxes) remain in data space for x; if lines must span full height, use `ax.get_xaxis_transform()` with documented rationale. Avoid mixed figure/axes transforms unless explicitly needed.
- Line widths/dash patterns: set explicit linewidths in points and explicit dash arrays so backend defaults cannot diverge between screen vs Agg/PDF.
- Text/bounding boxes: prefer `ax.text(..., transform=ax.transData, clip_on=True)` with fixed fontsize (points) and explicit bbox dict; avoid mixed annotate/textcoords combos that blend transforms implicitly.
- Figure construction: converge on a single `build_figure_from_spec(spec, *, dpi)` entry that does layout, traces, and all annotations. Preview uses it at `preview_dpi`; export uses it at target DPI/backends. (Not implemented yet—tracked with TODOs.)

## Regression checklist for later verification
- Single-panel with event boxes + vertical lines: preview screenshot vs PNG vs PDF must match.
- Two-panel layout (1×2 or 2×1) with differing y-ranges: event markers align to the correct times in both panels.
- Different DPI exports: 120, 300, 600 dpi PNG all align identically (no rectangle/line drift).
- macOS + Retina: no additional preview offset relative to exports.
- Legacy .vaso: load an existing layout; positions of events/boxes/labels remain correct.
