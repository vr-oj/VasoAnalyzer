# VasoAnalyzer Project History

---

## 2026-03-11 — Data Safety Hardening (Continued from prior session)

### Background
A silent data loss bug was discovered and fixed in a prior session. The root cause: `_populate_store_from_project()` cleared the staging DB (via `DELETE FROM dataset`, cascading to all trace rows), then used `source_ctx` — opened from the same `.vaso` file's last snapshot — as the trace source. Datasets added since the last snapshot had no entry in the source, so the JOIN in `_bulk_copy_traces_attach` silently produced 0 rows. No error was raised; save appeared to succeed but trace data was gone.

**The immediate fix (applied in prior session):** Before clearing the staging DB, create a `sqlite3.Connection.backup()` copy of it. Use this backup as the primary source for the bulk trace copy, so all current datasets (including unsaved ones) are preserved.

This session focused on comprehensive data safety hardening across the entire save pipeline.

---

### Changes Made

#### `src/vasoanalyzer/core/project.py`

**Risk 1 — Hard errors instead of silent data drops**
- `_bulk_copy_traces_attach` path: if `src_sqlite_path is None` (no trace source available), now raises `RuntimeError` instead of logging a warning. A missing source guarantees data loss; the save is aborted.
- Per-dataset fast-copy path in `_save_sample_to_store`: `_copy_trace_rows_sql` failure now re-raises instead of warning. Silent failure here left samples with no trace data.

**Risk 2 — Staging backup failure is fatal when unsaved data exists**
- Added `_staging_has_datasets_beyond_source(staging_conn, source_ctx) -> bool`: compares dataset IDs in staging DB vs source snapshot. Returns `True` if staging has IDs not present in source (i.e., unsaved data would be lost). Conservatively returns `True` when `source_ctx is None`.
- In `_populate_store_from_project`: if the pre-save staging backup fails (exception in the backup try-block) AND `_staging_has_datasets_beyond_source` returns `True`, raises `RuntimeError` to abort the save rather than proceeding with guaranteed data loss.
- Fixed a bug: `source_ctx` was referenced before assignment in the exception handler. Added `source_ctx: ProjectContext | None = None` early in the function so it's always defined.

**Risk 3 — Post-save verification manifest**
- Added `_build_save_manifest(project) -> dict[int, int]`: returns `{dataset_id: expected_trace_row_count}` from the in-memory project. Samples using the deferred fast-copy path (trace_data is None) get sentinel value `-1` (skipped in verification).
- Added `_verify_save_manifest(store_conn, manifest)`: queries the actual saved store and raises `RuntimeError` if any dataset's actual row count doesn't match the expected count.
- Wired into `_save_project_bundle`: manifest is built before `_populate_store_from_project`, verified after it completes but before the snapshot is created. Mismatch aborts the save with a detailed error message.

**Risk 4 — Autosave durability for container format**
- The autosave path (`skip_optimize=True`) only calls `store.commit()` — no snapshot, no repack. For container format, the staging DB lives in a temp dir that is lost on app crash.
- After `store.commit()`, if `store.container_path` is set, now writes a durable sidecar backup at `{container_path}.autosave.sqlite` using `sqlite3.Connection.backup()`.
- On the next full save, the sidecar is deleted after successful container repacking.

#### `src/vasoanalyzer/storage/bundle_adapter.py`

**Risk 4 (continued) — Autosave sidecar recovery on open**
- In `open_project_handle` for container format: after unpacking and opening the staging DB, checks for `{container_path}.autosave.sqlite`.
- If the sidecar exists and is newer than the container file (indicating an autosave happened after the last full save), copies the sidecar data into the staging DB via `sqlite3.Connection.backup()` and logs a recovery warning.
- Sidecar is deleted after recovery (whether recovered or stale).
- In `save_project_handle`: after successful container repacking, deletes the sidecar (data is now durably in the snapshot).

#### `tests/test_save_persistence.py` (new file)

Five new tests covering each risk scenario:

1. **`test_new_dataset_survives_full_save`** — Creates a project with trace data, saves, reopens, verifies trace row count in the snapshot directly via ZIP extraction.
2. **`test_new_dataset_survives_second_save`** — Loads an existing project, adds a new sample, saves again, reopens, verifies both original and new samples have correct trace counts.
3. **`test_bulk_copy_failure_raises`** — Patches `_bulk_copy_traces_attach` to raise, verifies `RuntimeError` propagates (no silent drop).
4. **`test_staging_backup_failure_aborts_save_with_unsaved_data`** — Patches `Path.is_file` to raise for presave_bak files (simulating disk full) and `_staging_has_datasets_beyond_source` to return True, verifies `RuntimeError` is raised with "staging backup failed" message.
5. **`test_autosave_recovery_after_crash`** — Inserts a new dataset directly into the staging DB, writes the autosave sidecar manually, simulates a crash, reopens the container, verifies the dataset is recovered and the sidecar is cleaned up.

---

### Test Results
- All 5 new tests pass.
- All 7 pre-existing integrity/format tests pass (`test_integrity.py`, `test_vaso_format.py`).

---

### Key Architecture Notes

- **Staging DB**: Temporary SQLite file in a temp dir (for containers), initialized from last snapshot on open, writable during session.
- **Snapshot architecture**: Each full save creates an immutable snapshot; HEAD.json atomically updated.
- **`_populate_store_from_project`**: Clears staging DB, then repopulates from in-memory Project + trace source. The pre-save backup ensures all current staging data is available as trace source.
- **Autosave sidecar**: Lives next to the `.vaso` file; survives crashes. Recovered on next open if newer than the container.
- **`sqlite3.Connection.backup()`**: C-level SQLite backup API used for both pre-save staging backup and autosave sidecar — consistent point-in-time copy including WAL data.
