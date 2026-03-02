# V3.0 Hardening Backlog (KEEP subsystems)

Prioritized items to make KEEP subsystems deterministic, testable, and stable before new features.

## 1) Deterministic UI state persistence
- Subsystem: Dataset UI-state persistence
- Symptom / risk: Saved projects reopen with missing plot state, toggles, pins, and label modes.
- Fix strategy: Implement items from `docs/ui_state_audit.md` (mark dirty, invalidate cache, persist cursor/label modes, restore minimal state on embedded loads).
- Tests to add: Integration test that saves and reopens a project and asserts restored axis limits, channel toggles, and event label mode.
- Acceptance criteria: Reopen reproduces view state for non-embedded datasets with no manual steps; embedded datasets restore time window and channel toggles only.
- Estimated risk: High

## 2) Trace / events / TIFF timebase alignment
- Subsystem: Import + sync
- Symptom / risk: Events or TIFF frames drift from trace time, producing incorrect analysis/export.
- Fix strategy: Enforce canonical time mapping (Time_s_exact > Time (s) > fallback) and validate event/frame mappings during import.
- Tests to add: Add a fixture with trace CSV + events CSV + TIFF metadata and verify frame->time mapping and event alignment.
- Acceptance criteria: Import logs any mismatch; aligned datasets reproduce expected event times within tolerance.
- Estimated risk: High

## 3) Autosave snapshot integrity in .vasopack
- Subsystem: Project I/O
- Symptom / risk: Interrupted save leaves HEAD pointing to invalid snapshot.
- Fix strategy: Strengthen snapshot validation and recovery path, add explicit tests around interrupted writes and lock contention.
- Tests to add: Simulate save interruption, verify fallback to previous snapshot (extend `tests/test_vaso_format.py`).
- Acceptance criteria: No corrupted project on interrupted save; HEAD always points to a valid snapshot.
- Estimated risk: High

## 4) Event edit persistence
- Subsystem: Events system
- Symptom / risk: Edited events in UI do not consistently persist to storage.
- Fix strategy: Ensure UI edits always flow through `project_service._sync_events_from_ui_state` and are saved on autosave/close.
- Tests to add: UI-state integration test that edits events, saves, reloads, and verifies event table rows.
- Acceptance criteria: Event edits persist across save/reopen and are reflected in export.
- Estimated risk: Medium

## 5) PyQtGraph trace viewer determinism and performance
- Subsystem: Main trace viewer
- Symptom / risk: LOD rendering or navigation causes inconsistent display vs export.
- Fix strategy: Audit LOD thresholds and time window updates; ensure deterministic transforms for visible channels.
- Tests to add: Unit tests for LOD output ranges given fixed input; time window change should not alter data values.
- Acceptance criteria: Same input trace yields same visible points for a given window; no regression in navigation responsiveness.
- Estimated risk: Medium

## 6) CSV export schema stability
- Subsystem: CSV + clipboard exports
- Symptom / risk: Column order or naming drift breaks downstream pipelines.
- Fix strategy: Centralize schema definitions and validate export columns before write.
- Tests to add: Snapshot tests for CSV header order and content from a synthetic dataset.
- Acceptance criteria: Export headers remain stable and match documented schema.
- Estimated risk: Medium

## 7) GIF animator frame sync + memory bounds
- Subsystem: GIF generator
- Symptom / risk: Frame sync drifts or render fails on large stacks.
- Fix strategy: Validate frame timing extraction results and limit memory usage with streaming render paths.
- Tests to add: Unit tests for `FrameSynchronizer` with fixed inputs; smoke test for render with small stack.
- Acceptance criteria: Frame sync matches expected indices; render completes without OOM for typical datasets.
- Estimated risk: Medium

## 8) Excel mapper validation
- Subsystem: Excel export
- Symptom / risk: Template mismatches yield silent errors or corrupt outputs.
- Fix strategy: Add strict validation for required columns and destination sheets with clear error messages.
- Tests to add: Unit tests for mapping failures (missing Event column, missing ID/OD fields).
- Acceptance criteria: Invalid templates fail fast with actionable errors; valid templates export deterministically.
- Estimated risk: Medium

## 9) Point editor audit integrity
- Subsystem: Point editor + audit
- Symptom / risk: Edit actions not serialized or replayed deterministically.
- Fix strategy: Verify `serialize_edit_log` / `deserialize_edit_log` and audit replay paths.
- Tests to add: Round-trip audit log test and replay test verifying edited trace values.
- Acceptance criteria: Audit logs replay to identical trace output; undo/redo stable across sessions.
- Estimated risk: Medium

## 10) Analysis pipeline integration
- Subsystem: Analysis metrics/segmentation/provenance
- Symptom / risk: Analysis results not reproducible if events or metadata change.
- Fix strategy: Freeze analysis inputs (params hash, event payloads) at compute time and store provenance.
- Tests to add: End-to-end test that recompute yields same results for same inputs.
- Acceptance criteria: Same dataset + params produces same results and provenance hash.
- Estimated risk: Low

## 11) Dataset package import robustness
- Subsystem: Dataset package (.vasods)
- Symptom / risk: Partial imports or metadata collisions cause silent data loss.
- Fix strategy: Strengthen validation and surface partial-failure reports in UI.
- Tests to add: Extend `tests/test_dataset_package.py` with corrupted manifest and collision scenarios.
- Acceptance criteria: Import reports failures explicitly; no silent data loss on collision.
- Estimated risk: Medium

## 12) Project recovery CLI coverage
- Subsystem: Recovery tooling
- Symptom / risk: CLI paths untested and may regress.
- Fix strategy: Add minimal smoke tests for list/extract modes.
- Tests to add: CLI tests against a small fixture bundle.
- Acceptance criteria: CLI reports options and extraction works on known bundle.
- Estimated risk: Low
