# Single Figure Studio – Phase 1 alignment

- Composer and renderer are locked to one axes/one canvas. The spec model now lives in `src/vasoanalyzer/ui/mpl_composer/renderer.py` as `PageSpec`, `AxesSpec`, `TraceSpec`, `EventSpec`, `AnnotationSpec`, and `FigureSpec`.
- Preview and export both call `build_figure(FigureSpec, RenderContext)`; export uses `export_figure` which only honors page size + DPI (no Qt canvas sizing, no zoom scaling). Dimensions are clamped at 8k px for safety.
- Data binding is keyed by `TraceSpec.key` (`inner`, `outer`, `avg_pressure`, `set_pressure`) and resolved through the `RenderContext.trace_model`. Missing series are skipped gracefully.
- Zoom is view-only: `QScrollArea` hosts the Matplotlib canvas; zoom adjusts widget size, not the spec.
- Events/annotations are now explicit spec lists; UI wiring for edits will follow in later phases.
- Legacy multi-panel layout/grid code is retired; neutral layout/spec I/O will be revisited after the single-axes flow is stable.
