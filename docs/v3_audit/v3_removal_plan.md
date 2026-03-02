# V3.0 Removal Plan (Deprecated Subsystems)

This plan stages removal to avoid breaking core analysis/export/GIF workflows.

## 1) Archived / duplicate UI screens

Stage A - Verify non-usage
- Confirm no runtime imports of `src/vasoanalyzer/ui/_archive/*`.

Stage B - Remove code
- Delete entire `src/vasoanalyzer/ui/_archive/` tree.

Data migration / compatibility
- None (archive code is not wired).

## 2) Matplotlib main-view renderer toggle

Stage A - Hide UI entry points
- Remove View > Renderer menu and any settings persistence for it.

Stage B - Remove internal usage
- Remove Matplotlib main-view paths; keep PyQtGraph as the only renderer.

Data migration / compatibility
- Ignore any stored renderer preference keys on load.

## 3) Protocol annotation tool (unused)

Stage A - Verify non-usage
- Confirm no references from UI/menu.

Stage B - Remove code
- Delete `src/vasoanalyzer/ui/protocol_annotation_tool.py` and related assets.

Data migration / compatibility
- None.

## 4) pkg.vaso sidecar export (feature-flagged)

Stage A - Disable by default
- Ensure feature flag remains off for V3.

Stage B - Remove export path
- Remove `pkg` export calls in `core.project` once no consumers remain.
- Optionally retain CLI support in a separate tooling repo.

Data migration / compatibility
- None required; sidecar files are optional artifacts.

## 5) Scope / triggered sweeps dock (if not merged)

Stage A - Validate usage
- Confirm whether sweep capture is part of the V3 analysis plan.

Stage B - Hide UI entry point
- Remove from View > Panels.

Stage C - Remove code
- Delete `src/vasoanalyzer/ui/scope_view.py` and `src/vasoanalyzer/core/sweeps.py` if unused.

Data migration / compatibility
- None (does not persist project data).
