# Remove Legacy Snapshot Viewer (v1) Inventory

This report captures the v1 snapshot viewer surface area before deletion.

## Files/directories to delete
- `src/vasoanalyzer/ui/snapshot_viewer/` (entire directory)
- `src/vasoanalyzer/ui/snapshot_viewer/experimental/` (experimental snapshot viewer)
- `src/vasoanalyzer/ui/mixins/snapshot_mixin.py`
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_widget.py`
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_viewer_controller.py`
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_timeline.py`
- `src/vasoanalyzer/ui/snapshot_viewer/render_backends.py`
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_perf.py`
- `src/vasoanalyzer/ui/snapshot_viewer/snapshot_data_source.py`
- `src/vasoanalyzer/ui/snapshot_viewer/factory.py`
- `src/vasoanalyzer/ui/snapshot_viewer/__init__.py`

## Imports/call sites to update
- `src/vasoanalyzer/ui/main_window.py`
  - imports from `vasoanalyzer.ui.snapshot_viewer`
  - snapshot controller wiring, timeline handling, and pg snapshot toggles
- `src/vasoanalyzer/ui/shell/init_ui.py`
  - legacy timeline import and snapshot controls
- `src/vasoanalyzer/ui/mixins/menu_mixin.py`
  - snapshot viewer toggle wiring (keep if v2 still uses, remove v1 specifics)
- `src/vasoanalyzer/ui/mixins/sample_loader_mixin.py`
  - snapshot viewer toggles and v1-only paths
- `src/vasoanalyzer/ui/__init__.py`
  - if snapshot viewer exports are re-exported here

## Tests referencing v1 to remove/update
- `tests/test_snapshot_controller_routing.py`
- `tests/test_snapshot_sync_mode.py`
- `tests/test_snapshot_coalescing.py`
- snapshot cache tests (removed)

## Docs referencing legacy snapshot viewer to remove/update
- `docs/snapshot_viewer_audit.md`
- `docs/snapshot_sync_fixes.md`
- `docs/time_sync_canonical_architecture.md`
- `docs/main_window_sync_investigation.md`
- `docs/phase4_implementation_summary.md`
- `docs/ui_audit/snapshot_viewer_inventory.md`
- `docs/ui_audit/snapshot_viewer_canonical_plan.md`
- `docs/ui_audit/snapshot_viewer_current_state.md`
- `docs/ui_audit/snapshot_tiff_pipeline.md`
- `docs/ui_audit/snapshot_tiff_perf_plan.md`
- `docs/v3_audit/v3_keep_map.md`
