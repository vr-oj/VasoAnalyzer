# VasoAnalyzer Bundle Format (.vasopack)

## Overview

VasoAnalyzer now supports a **cloud-safe bundle format** (`.vasopack`) that solves corruption issues with cloud storage services and provides crash protection through immutable snapshots.

## Why Bundle Format?

### Problems with Legacy `.vaso` Format

The traditional single-file `.vaso` format has limitations:

- **Cloud sync corruption**: SQLite databases with WAL files don't sync properly with Dropbox, iCloud, Google Drive
- **Data loss on crashes**: Power failures or unexpected quits could corrupt the database
- **No version history**: Can't restore to earlier states if something goes wrong
- **Concurrent access issues**: Opening the same project on multiple machines risks corruption

### Benefits of `.vasopack` Bundle Format

✅ **Cloud-Safe**: Works reliably with Dropbox, iCloud, Google Drive, OneDrive
✅ **Crash-Proof**: If app crashes mid-save, your data is safe
✅ **Version History**: Automatic snapshots let you restore earlier states
✅ **Better Recovery**: Auto-detects corrupted snapshots and falls back to valid ones
✅ **Multi-Window Safe**: Can open read-only in second window while working in first

## How It Works

### Bundle Structure

A `.vasopack` project is a directory (bundle) that looks like a single file on macOS and appears as a folder on Windows/Linux:

```
MyProject.vasopack/
├── HEAD.json                  # Points to current snapshot
├── snapshots/
│   ├── 000001.sqlite         # First snapshot
│   ├── 000002.sqlite         # Second snapshot
│   └── 000042.sqlite         # Current snapshot
├── .staging/
│   └── abc123.sqlite         # Active session database (deleted on close)
├── project.meta.json          # Migration history and metadata
└── .lock                      # Prevents concurrent writes
```

### Append-Only Snapshots

Key principle: **Snapshots are never modified after creation.**

When you save:
1. Changes go to a local staging database (fast, with WAL journaling)
2. On save/autosave, staging DB is copied to a new snapshot (e.g., `000043.sqlite`)
3. `HEAD.json` is atomically updated to point to the new snapshot
4. Old snapshots remain intact (pruned after 50 by default)

If the app crashes during save:
- Staging DB might be lost, but...
- `HEAD.json` still points to the last good snapshot
- You lose at most a few seconds of work (since last autosave)

### Cloud Sync Behavior

With bundle format, cloud sync is **safe**:

1. **Immutable files**: Snapshots never change after creation, so partial uploads don't corrupt
2. **No WAL files**: WAL journaling only in local `.staging/` (not synced)
3. **Atomic HEAD updates**: Even if `HEAD.json` conflicts, app auto-resolves to newest valid snapshot
4. **Conflict resolution**: If multiple machines create snapshots, highest number wins

## Usage

### Creating New Projects

**Via Menu (New Project):**
1. File → New Project
2. Enter project name
3. Click Browse → Select save location
4. Choose "Vaso Bundles (*.vasopack)" from format dropdown
5. Create

**Default**: New projects use `.vasopack` format automatically (configurable in Preferences).

### Opening Projects

**Open .vasopack bundle:**
- File → Open → Select the `.vasopack` folder/bundle
- Or double-click the bundle in file browser (macOS)

**Auto-Migration:**
If you open an old `.vaso` file, VasoAnalyzer will:
1. Detect it's legacy format
2. Automatically migrate to `.vasopack`
3. Keep original as `.vaso.legacy` backup
4. Open the new bundle

### Saving Projects

**Autosave**: Creates new snapshot every ~30 seconds (configurable)

**Manual Save** (Cmd+S / Ctrl+S): Immediately creates snapshot

**Save As**: Can convert between formats
- Save `.vasopack` → `.vaso` (export to legacy)
- Save `.vaso` → `.vasopack` (upgrade to bundle)

### Preferences

File → Preferences → Project Format

- ☑ **Use cloud-safe bundle format (.vasopack) for new projects**
  - Recommended: ON (default)
  - Turn OFF if you need `.vaso` files by default

## Technical Details

### Snapshot Retention

- **Default**: Keep last 50 snapshots
- **Automatic pruning**: Old snapshots deleted when count exceeds 50
- **Current snapshot**: Never deleted (always safe)

### Snapshot Recovery

If `HEAD.json` points to a corrupted snapshot:
1. App validates snapshot with `PRAGMA quick_check`
2. If invalid, searches for newest valid snapshot
3. Updates `HEAD.json` to point to recovered snapshot
4. Opens recovered version

### Lock Files

`.lock` file prevents concurrent write access:
- First instance: Acquires lock, can write
- Second instance: Lock held → opens read-only
- Stale locks: Auto-removed after 1 hour

### Staging Database

Active session uses a local staging DB:
- **Location**: `bundle/.staging/<uuid>.sqlite`
- **Journaling**: WAL mode (fast, safe)
- **Cleanup**: Deleted on clean close
- **Orphan cleanup**: Stale staging DBs removed after 1 hour

## Migration Guide

### Automatic Migration

When you open a `.vaso` file:
```
1. App detects legacy format
2. Creates MyProject.vasopack/ directory
3. Copies .vaso as snapshots/000001.sqlite
4. Renames original to MyProject.vaso.legacy
5. Opens bundle
```

**You don't need to do anything** - it happens automatically.

### Manual Migration

To explicitly migrate:
1. Open legacy `.vaso` project
2. File → Save As
3. Choose "Vaso Bundles (*.vasopack)"
4. Select new location
5. Save

Original `.vaso` file is preserved.

### Backward Compatibility

To share with users on older VasoAnalyzer:
1. Open `.vasopack` bundle
2. File → Save As
3. Choose "Vaso Files (*.vaso)"
4. Share the `.vaso` file

Note: Bundle benefits (snapshots, cloud-safety) are lost in `.vaso` export.

## Troubleshooting

### "Bundle is locked by another process"

**Cause**: Another VasoAnalyzer instance has the bundle open.

**Solution**:
- Close other instances, or
- Open as read-only (automatic fallback)

### "No valid snapshot found"

**Cause**: All snapshots are corrupted (extremely rare).

**Solution**:
- Check if `.vaso.legacy` backup exists
- Open backup and re-save as bundle
- Contact support with bundle for recovery assistance

### Cloud Sync Conflicts

**Symptom**: Multiple `HEAD.json` files appear after sync.

**Solution**:
- VasoAnalyzer auto-resolves to newest valid snapshot
- Verify recovery: File → Open → Check data is correct
- Conflicted files can be manually deleted

### Disk Space

**Symptom**: Bundle grows large over time.

**Solution**:
- Automatic: Old snapshots pruned after 50
- Manual: Can reduce retention count (coming in future update)
- Each snapshot ~= full database size (compressed)

## Advanced Recovery

### When Both .vaso and .vaso.backup Are Corrupted

If you have a corrupted **legacy .vaso** file and the `.vaso.backup` is also corrupted, VasoAnalyzer has **three recovery methods** that run automatically:

#### Method 1: CLI sqlite3 Dump (Most Robust)
Uses the command-line `sqlite3` tool to dump the database to SQL, then reconstructs it:
```bash
sqlite3 corrupted.vaso .dump > dump.sql
sqlite3 recovered.vaso < dump.sql
```
This works even when the database is partially corrupted.

#### Method 2: Python iterdump (Fallback)
Python's SQLite library attempts to recover row-by-row, skipping corrupted data:
- Recovers readable tables
- Skips corrupted rows
- May lose some data but saves what's recoverable

#### Method 3: PRAGMA Recovery (Last Resort)
Uses SQLite's recovery mode to salvage data:
```sql
PRAGMA writable_schema=ON;
-- Attempts to copy readable tables
```

### Command-Line Recovery Tool

VasoAnalyzer includes a powerful command-line recovery tool for advanced scenarios:

#### Automatic Recovery
```bash
# Try all recovery methods automatically
python -m vasoanalyzer.cli.recover MyProject.vasopack
```

#### List Available Options
```bash
# See what recovery options are available
python -m vasoanalyzer.cli.recover MyProject.vasopack --list
```

**Example output:**
```
Recovery options for: MyProject.vasopack
Format: bundle-v1

Available recovery methods:

1. [✓] snapshot_fallback
   Use older snapshot (15 available)
   Snapshots: 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 42, 43, 44

2. [✓] staging_recovery
   Recover from staging DB (1 found)
   Files: 1
```

#### Extract Specific Snapshot
```bash
# Extract snapshot #35 from bundle
python -m vasoanalyzer.cli.recover MyProject.vasopack --extract 35 --output snapshot35.vaso

# Open the extracted snapshot to verify it has your data
```

#### Find Autosave Files
```bash
# Search entire Documents folder for autosaves
python -m vasoanalyzer.cli.recover --find-autosaves ~/Documents
```

**Example output:**
```
Found 3 autosave file(s):

  /Users/me/Documents/ProjectA.vaso.autosave
  /Users/me/Documents/ProjectB.vasopack/.staging/abc123.sqlite
  /Users/me/Dropbox/Research/Study.vaso.autosave
```

### Bundle Format Recovery Advantages

With `.vasopack` bundles, you have **many more recovery options** than legacy files:

| Scenario | Legacy .vaso | Bundle .vasopack |
|----------|--------------|------------------|
| Current file corrupted | Try .backup or autosave | Use any of 50 snapshots |
| Autosave exists | 1 autosave file | Multiple staging DBs possible |
| Cloud sync conflict | Must manually resolve | Auto-resolves to newest valid |
| Partial corruption | All-or-nothing recovery | Can extract specific snapshots |
| Time-travel needed | Impossible | Extract any snapshot |

### Recovery Workflow for Bundles

If you suspect corruption in a bundle:

1. **Try opening normally** - Auto-recovery runs automatically
   ```
   File → Open → MyProject.vasopack
   ```

2. **If that fails, list options**:
   ```bash
   python -m vasoanalyzer.cli.recover MyProject.vasopack --list
   ```

3. **Extract older snapshot**:
   ```bash
   # Try snapshot before corruption (e.g., #40 if #42 is corrupted)
   python -m vasoanalyzer.cli.recover MyProject.vasopack --extract 40 --output recovered.vaso
   ```

4. **Open extracted snapshot**:
   ```
   File → Open → recovered.vaso
   ```

5. **Save as new bundle** (if recovered successfully):
   ```
   File → Save As → MyRecoveredProject.vasopack
   ```

### Recovery Workflow for Legacy .vaso

If both `.vaso` and `.vaso.backup` are corrupted:

1. **Check for autosave**:
   ```bash
   ls -lh MyProject.vaso.autosave
   ```
   If newer than main file, try opening it directly.

2. **Try automatic recovery**:
   ```bash
   python -m vasoanalyzer.cli.recover MyProject.vaso
   ```
   This runs 3-stage recovery automatically.

3. **Check the backup created during recovery**:
   ```bash
   ls -lh MyProject.vaso.backup
   ```
   The recovery process creates a `.backup` before attempting repair.

4. **If all else fails, check for**:
   - Exported Excel files (can manually recreate project)
   - CSV exports (trace and event tables)
   - Screenshots or figure exports
   - Time Machine backups (macOS)
   - Windows File History
   - Cloud service version history

### Prevention is Better Than Recovery

To minimize risk of data loss:

✅ **Use bundle format** - More recovery options
✅ **Enable autosave** - Creates recovery points
✅ **Back up to Time Machine/File History** - OS-level backup
✅ **Export data periodically** - Excel templates, CSV files
✅ **Keep project in cloud storage** - Built-in versioning (Dropbox, etc.)
✅ **Don't force-quit during saves** - Let autosave complete

### Getting Help with Recovery

If you can't recover your project:

1. **Preserve the corrupted files** - Don't delete anything!
2. **Note what you tried** - List recovery methods attempted
3. **Gather information**:
   - Project format (.vaso or .vasopack)
   - When corruption occurred
   - Recent operations (cloud sync, crash, etc.)
4. **Contact support** with:
   - Corrupted project files (if small enough)
   - Recovery tool output (with `--verbose`)
   - Description of what happened

## FAQ

**Q: Can I delete old snapshots manually?**
A: Yes, but leave the current snapshot (highest number) and a few recent ones. Delete from `snapshots/` folder.

**Q: Can I use both `.vaso` and `.vasopack`?**
A: Yes. Use Save As to convert between formats as needed.

**Q: Will old VasoAnalyzer versions open `.vasopack`?**
A: No. Export to `.vaso` for backward compatibility.

**Q: What if I run out of disk space?**
A: Automatic pruning keeps only 50 snapshots. For large projects, consider external drive or reduce snapshot retention (future feature).

**Q: Can I see/browse snapshot history?**
A: Not yet in UI. Coming in future update. Advanced users can open snapshots directly in `snapshots/` folder.

**Q: Is `.vasopack` the default now?**
A: Yes for new projects. Legacy `.vaso` files still work and can be used via Preferences or Save As.

**Q: Can I share bundles with collaborators?**
A: Yes! Place `.vasopack` in shared Dropbox/iCloud folder. Each user will work on their own staging DB, creating sequential snapshots safely.

## Best Practices

### ✅ DO

- Use `.vasopack` for projects in cloud storage
- Enable autosave for automatic snapshot protection
- Keep bundle format as default (File → Preferences)
- Verify data after cloud sync conflicts (rare, but possible)

### ❌ DON'T

- Don't manually edit files inside bundle (except with care)
- Don't disable autosave if working on cloud-synced bundle
- Don't force-quit app during save (defeats crash protection)
- Don't share same bundle across Windows/Mac without cloud sync (direct copy OK)

## Version History

- **v3.0** (2025-01): Initial bundle format implementation
  - Append-only snapshots
  - Automatic migration
  - Cloud-safe architecture
  - Crash recovery

## Support

If you encounter issues with bundle format:
1. Check this documentation
2. Try exporting to `.vaso` as temporary workaround
3. Report issue with bundle attached (if possible)
4. Contact: [support email or GitHub issues]

---

**Recommended**: Enable bundle format for all new projects via File → Preferences.
