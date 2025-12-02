## Append-Only Snapshot Bundles (`*.vaso`)

> Crash-safe, sync-friendly project storage that never mutates past snapshots.

### Why change?

The legacy “single sacred SQLite file” is fragile when laptops sleep mid-write or when Dropbox/iCloud syncs a half-written WAL file. The append-only bundle keeps each save immutable so readers always see a complete snapshot, regardless of crashes, power loss, or multi-machine sync races.

Key goals:
- Never rewrite a prior snapshot; every save is a brand-new SQLite file.
- Keep WAL files off synced volumes by staging writes in a local cache.
- Allow multiple processes to open a bundle where only one holds the write lock.
- Make recovery trivial: if `HEAD.json` or the latest snapshot disappears, fall back to the previous good file.

### Bundle layout

A `*.vaso` project becomes a directory bundle:

```
MyStudy.vaso/
  HEAD.json                 # atomic pointer to the active snapshot
  project.meta.json         # rarely changing project metadata
  snapshots/
    000001.sqlite           # immutable snapshot files
    000002.sqlite
  media/                    # TIFFs, overlays, exports (write-once)
  logs/
    activity.jsonl          # optional append-only history
```

**Rules**
1. `snapshots/*.sqlite` are immutable. Delete old ones only during retention pruning.
2. Publish a new snapshot by atomically renaming `00000N.sqlite.tmp → 00000N.sqlite`.
3. Change `HEAD.json` via `HEAD.json.tmp` + `os.replace` after the snapshot has been fsynced.
4. Media/log files follow the same “write tmp → fsync → rename” discipline.

### Session lifecycle

1. **Open**
   - Acquire a non-blocking lock file (`.lock`). Failure → open read-only.
   - Read `HEAD.json` and open its snapshot in read-only mode for the UI.
   - Create a **local staging DB** (`~/Library/Caches/VasoAnalyzer/staging/<uuid>.sqlite`) with `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `fullfsync=ON`. This DB never leaves the local disk.
2. **Edit**
   - All user edits go to the staging DB. No writes touch the bundle yet.
3. **Snapshot**
   - Copy staging → bundle using the SQLite backup API.
   - Run `VACUUM` / `PRAGMA optimize` on the temporary file if desired.
   - `fsync` the temp file, rename into `snapshots/00000N.sqlite`, then update `HEAD.json`.
   - Keep the staging DB open for further edits.

```python
from pathlib import Path
import os, json, sqlite3, time

def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)

def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def next_snapshot_name(snapshots_dir: Path) -> Path:
    nums = [int(p.stem) for p in snapshots_dir.glob("*.sqlite") if p.stem.isdigit()]
    n = (max(nums) + 1) if nums else 1
    return snapshots_dir / f"{n:06d}.sqlite"

def snapshot_from_staging(bundle: Path, staging_db: Path) -> Path:
    snaps = bundle / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    dest = next_snapshot_name(snaps)
    tmp = dest.with_suffix(".sqlite.tmp")
    with sqlite3.connect(f"file:{staging_db}?immutable=0", uri=True) as src, \
         sqlite3.connect(tmp) as dst:
        src.backup(dst)
        dst.execute("PRAGMA optimize")
    fsync_file(tmp)
    os.replace(tmp, dest)
    head_doc = {"current": dest.name, "ts": time.time()}
    atomic_write_text(bundle / "HEAD.json", json.dumps(head_doc))
    return dest
```

4. **Close**
   - Delete the staging DB. Readers never touch WAL files in the bundle.

### Recovery rules

- On open, validate the snapshot referenced by `HEAD.json` via `PRAGMA quick_check`. If corrupt or missing, walk backwards through `snapshots/*.sqlite` until the newest valid file is found, rewrite `HEAD.json`, and continue.
- If cloud sync duplicated `HEAD.json`, pick the highest snapshot id that passes validation and rewrite `HEAD.json` locally.
- For view-only fallback (no lock), the UI still loads the last good snapshot because it is immutable.

### Multi-window / multi-device safety

- The first writer owns `.lock`. Others open snapshots read-only and show a “view only” banner.
- Because snapshots are immutable, a second machine syncing mid-save only sees complete files. Partial uploads result in a truncated `.tmp` file that is ignored because `HEAD.json` still points to the prior snapshot.

### Retention & pruning

- Keep the latest N snapshots (default 50) plus tagged milestones.
- Run pruning in the background thread once the bundle grows beyond a quota, removing the oldest files that are not milestone-protected.

### Migration strategy

1. Detect legacy single-file `.vaso` (SQLite magic header).
2. Create `ProjectName.vaso/`.
3. Move the original DB to `snapshots/000001.sqlite`.
4. Write `HEAD.json = {"current": "000001.sqlite", "ts": ...}`.
5. Subsequent saves follow the snapshot routine.

### Optional hardening

- **HEAD conflict resolver:** show a toast when another machine publishes `000010` and you were on `000009`; offer to diff.
- **Disk-space guard:** pause snapshotting when <1 GiB free, prompt user to prune.
- **Health indicator:** green when quick_check passes and snapshots are recent; yellow when snapshotting paused; red if recovery was required.

### Implementation pointers

- New module: `vasoanalyzer/storage/snapshot_bundle.py` (lock, staging DB, snapshot writer, HEAD recovery).
- Update CLI/GUI `save` path to route through the snapshot writer.
- Tests:
  - `test_snapshot_recovery_latest_valid`.
  - `test_bundle_migration_from_legacy`.
  - `test_view_only_lock_conflict`.
  - `test_retention_prunes_oldest`.

For incremental rollout, gate the feature behind a flag (`bundle_snapshots`) and land migration + recovery before switching the default save pipeline.
