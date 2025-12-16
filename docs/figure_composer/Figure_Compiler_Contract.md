# Figure Compiler Contract (Matplotlib Figure Composer)

## 1. Purpose and scope
- Define a 5-layer “Figure Compiler” contract for the Matplotlib-based Single Figure Studio so preview and export always share one deterministic pipeline.
- Clarify what data is source of truth (specs), how UI edits propagate, and which decisions belong to VasoAnalyzer vs Matplotlib.
- Applies to the maintained composer only (`src/vasoanalyzer/ui/mpl_composer/*`); legacy code in `_archive` stays isolated.

## 2. Definitions
- **DataModel**: Runtime series + events delivered by the app (`TraceModel`, `series_map`, event metadata). Read-only inputs; no Matplotlib types.
- **SemanticGraphSpec**: “What to plot” meaning per graph (`GraphSpec` in `specs.py`): channel bindings, event bindings, semantic ranges (data domain), graph identity, references to reusable presets/templates.
- **PhysicalLayoutSpec**: Concrete geometry for a compiled figure: page size, dpi, axes rectangle, margins, sizing mode. Lives with FigureSpec’s `PageSpec`/`AxesSpec` (renderer-friendly).
- **StyleSpec**: Visual decisions independent of layout: colors, line/marker styles, fonts, legend visibility/location, annotation styling, line width scaling. Captured in `TraceSpec`, `EventSpec`, `AnnotationSpec`, legend settings, etc.
- **Renderer**: Pure functions in `src/vasoanalyzer/ui/mpl_composer/renderer.py` (`build_figure`, `export_figure`) that turn FigureSpec + RenderContext into a Matplotlib Figure (preview or export) without UI knowledge.

## 3. 5-layer pipeline (ASCII)
```
DataModel (TraceModel, series_map, events)
    ↓ bind/validate
SemanticGraphSpec (GraphSpec: channels/events/semantic ranges)
    ↓ compile_to_physical()
PhysicalLayoutSpec (PageSpec + AxesSpec geometry)
    ↓ apply_styles()
StyleSpec (TraceSpec/EventSpec/AnnotationSpec/legend/fonts)
    ↓ render()
Renderer (build_figure/export_figure in renderer.py)
```

## 4. Invariants (MUST / MUST NOT)
- MUST treat specs as source of truth; Matplotlib Figures are throwaway artifacts of `build_figure`/`export_figure`.
- MUST run preview and export through the same renderer entry points; no alternate render path for the canvas.
- MUST keep renderer pure: inputs are FigureSpec + RenderContext; no Qt widgets, dialogs, or global state.
- MUST keep DataModel read-only inside the compiler; all mutations happen in UI/controllers before compiling specs.
- MUST clamp/validate physical sizes before render (`PageSpec`/`AxesSpec`), never after export.
- MUST let Matplotlib decide only low-level glyph layout (text/legend packing); MUST NOT let Matplotlib auto-change semantic decisions (trace visibility, colors, label text, axis ranges when user fixed them).
- MUST NOT write back into specs from renderer except documented outputs (`effective_*` on PageSpec for sizing telemetry).
- MUST NOT mix legacy `_archive` composer classes into this pipeline.

## 5. Responsibilities by module (current files)
- `src/vasoanalyzer/ui/mpl_composer/specs.py`: Define `GraphSpec` (semantic graph), plus helpers to compile semantic → physical/style specs. Owns validation of bindings and defaults; no Matplotlib imports.
- `src/vasoanalyzer/ui/mpl_composer/renderer.py`: Own the render-ready dataclasses (`PageSpec`, `AxesSpec`, `TraceSpec`, `EventSpec`, `AnnotationSpec`, `FigureSpec`, `RenderContext`) and the only render entry points (`build_figure`, `export_figure`). Enforces size clamps and visibility guarantees.
- `src/vasoanalyzer/ui/mpl_composer/composer_window.py`: UI/controller that edits specs, syncs widgets ↔ specs, and calls renderer for preview/export. May cache `RenderContext` (data pointers) but must not alter Matplotlib axes directly.
- `src/vasoanalyzer/ui/mpl_composer/spec_serialization.py`: Persist/restore compiled specs (`FigureSpec`) to/from disk; no business logic beyond schema compatibility.
- Templates (`src/vasoanalyzer/ui/mpl_composer/templates`): Provide preset GraphSpecs/FigureSpecs; never reach into renderer internals.

## 6. Debugging rubric: If X is broken, check layer Y
- Wrong trace/event data plotted → DataModel binding or SemanticGraphSpec (wrong key mapping, visibility flags).
- Correct data but wrong ranges/shape → PhysicalLayoutSpec (page/axes sizing mode, margins, dpi clamp).
- Colors/fonts/legend wrong → StyleSpec (TraceSpec/EventSpec/AnnotationSpec, legend settings).
- Preview vs export mismatch → Renderer contract violation (preview bypassed `build_figure` or diverging context).
- Crashes from Qt in export/tests → ComposerWindow leaking Qt into renderer; renderer must stay headless.
- Serialized figure loads oddly → spec_serialization schema drift vs FigureSpec expectations.

## 7. Implementation roadmap (short)
- Establish `specs.py` with `GraphSpec` + compile functions to emit `FigureSpec` (PhysicalLayoutSpec + StyleSpec pieces).
- Refactor `composer_window.py` to mutate GraphSpec, then compile once per refresh and call `build_figure`.
- Ensure export button reuses the same compiled FigureSpec and `export_figure`.
- Add contract-level checks: validation on compile (bindings, ranges), renderer assertions on forbidden Qt/mutable inputs.
- Align templates and serialization with the compiled FigureSpec schema and versioning.
- Event markers/labels flow: specs carry `show_event_markers`/`show_event_labels`, UI toggles only mutate those fields, and `_render_events` (shared by preview/export) renders both paths identically.
- Templates: specs carry `template_id`; presets populate physical layout + style defaults via data-only `templates.py`, UI writes `template_id` and applies defaults, renderer consumes only the resulting `FigureSpec` (no template branching).
