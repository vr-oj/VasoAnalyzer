# VasoTracker Import Specification

## Overview

VasoAnalyzer provides full support for importing VasoTracker experimental data with automatic file discovery, high-precision time tracking, and comprehensive metadata preservation.

**Key Features:**
- ✅ Microsecond-precision time tracking (`Time_s_exact`)
- ✅ Automatic file discovery (trace, event table, TIFF)
- ✅ Full column preservation with schema normalization
- ✅ Provenance metadata tracking
- ✅ TIFF files external by default (optional embedding)
- ✅ Auto-migration from legacy formats

---

## VasoTracker File Format

A single VasoTracker experiment generates **three files**:

### 1. Trace CSV (`*_ExpXX.csv`)

The primary time-series data file containing continuous measurements.

**Required Columns:**
- `Time_s_exact` (float) - **Canonical** high-precision timestamp (microsecond accuracy)
- `Time (s)` (float) - Rounded time for display
- `Time (hh:mm:ss)` (string) - Human-readable timestamp
- `FrameNumber` (int) - Camera frame counter
- `Inner Diameter` (float) - Vessel inner diameter (µm)
- `Outer Diameter` (float) - Vessel outer diameter (µm)

**Optional VasoTracker Columns:**
- `TiffPage` (int) - Index into multi-page TIFF (0-based)
- `Saved` (int) - Whether frame was saved to TIFF (0/1)
- `Temperature (oC)` (float) - Temperature measurement
- `Pressure 1 (mmHg)` (float) - Pressure channel 1
- `Pressure 2 (mmHg)` (float) - Pressure channel 2
- `Avg Pressure (mmHg)` (float) - Average of pressure channels
- `Set Pressure (mmHg)` (float) - Target pressure setpoint
- `Table Marker` (int) - User-inserted event markers
- `Caliper length` (float) - Caliper measurement
- `Outer Profiles`, `Inner Profiles` - Profile detection data
- `Outer Profiles Valid`, `Inner Profiles Valid` - Quality flags

**Example:**
```csv
Time (s),Time (hh:mm:ss),Time_s_exact,FrameNumber,Saved,TiffPage,Outer Diameter,Inner Diameter,Temperature (oC),...
0.0,00:00:00,0.000014,1028,1,0,106.47,64.97,37.0,...
0.1,00:00:00,0.130134,1029,0,NaN,106.50,65.01,37.0,...
```

### 2. Event Table CSV (`*_ExpXX_table.csv`)

Discrete events marked during the experiment with snapshot measurements.

**Columns:**
- `#` (int) - Event index
- `Time` (string) - Timestamp (hh:mm:ss format)
- `Frame` (int) - Frame number (maps to trace `FrameNumber`)
- `Label` (string) - Event description
- `OD` (float) - Outer diameter at event time
- `%OD ref` (float) - Percent change from reference OD
- `ID` (float) - Inner diameter at event time
- `Caliper` (float) - Caliper measurement
- `Pavg` (float) - Average pressure
- `P1`, `P2` (float) - Pressure channels
- `Temp` (float) - Temperature

**Example:**
```csv
#,Time,Frame,Label,OD,%OD ref,ID,Caliper,Pavg,P1,P2,Temp
1,00:00:42,1373,20 mmHg,106.47,NaN,64.974,0.0,20.1,20.1,20.1,37.0
2,00:02:15,4521,tone + 1 uM CCh,98.32,-7.65,59.21,0.0,20.0,20.0,20.0,37.0
```

### 3. TIFF Stack (`*_ExpXX_Result.tiff`)

Multi-page TIFF containing saved video frames.

**Properties:**
- Multi-page TIFF format
- Frame indices match `TiffPage` column in trace CSV (0-based)
- Can be multi-GB in size
- Optional metadata in TIFF tags/descriptions

---

## How VasoAnalyzer Imports VasoTracker Data

### Canonical Time Column: `Time_s_exact`

VasoAnalyzer uses **`Time_s_exact`** as the single source of truth for all timing:

```
Time_s_exact → canonical "Time (s)" column
                    ↓
           All UI components use this:
           - PyQtGraph trace plots
           - Event markers
           - TIFF frame synchronization
           - Matplotlib figures
```

**Precision Comparison:**
```
Time (s):      0.0,    0.1,    0.3,    0.4      (100ms resolution)
Time_s_exact:  0.000014, 0.130134, 0.255535, 0.381367  (µs resolution)
                  ↑ 14 microseconds precision!
```

**Legacy Files:**
- If `Time_s_exact` is missing, VasoAnalyzer falls back to `Time (s)`
- A warning is logged: *"Using legacy time column (Time_s_exact not found)"*

### File Auto-Discovery

VasoAnalyzer can import from **any** of the three file types and automatically finds siblings:

**Starting from Trace CSV:**
```
User drops: 20251202_Exp01.csv
App finds:  20251202_Exp01_table.csv  ✓
            20251202_Exp01_Result.tiff ✓
```

**Starting from Event Table:**
```
User drops: 20251202_Exp01_table.csv
App finds:  20251202_Exp01.csv         ✓  (reverse discovery)
            20251202_Exp01_Result.tiff ✓
```

**Starting from TIFF:**
```
User drops: 20251202_Exp01_Result.tiff
App finds:  20251202_Exp01.csv         ✓  (reverse discovery)
            20251202_Exp01_table.csv   ✓
```

**Patterns Recognized:**
- Trace: `{base}.csv`
- Events: `{base}_table.csv`, `{base}_Table.csv`, `{base}-table.csv`, `{base} table.csv`
- TIFF: `{base}_Result.tiff`, `{base}_Result.tif`, `{base}_Raw.tiff`, `{base}.tiff`

### Column Normalization

VasoAnalyzer normalizes raw column names to a canonical internal schema:

| Raw Column Name         | Canonical Name   | Database Column    |
|------------------------|------------------|--------------------|
| `Time_s_exact`         | `Time (s)`       | `t_seconds`        |
| `FrameNumber`          | `FrameNumber`    | `frame_number`     |
| `TiffPage`             | `TiffPage`       | `tiff_page`        |
| `Temperature (oC)`     | `Temperature`    | `temp`             |
| `Table Marker`         | `Table Marker`   | `table_marker`     |
| `Caliper length`       | `Caliper Length` | `caliper_length`   |
| `Pressure 1 (mmHg)`    | *stored as-is*   | `p1`               |
| `Pressure 2 (mmHg)`    | *stored as-is*   | `p2`               |
| `Avg Pressure (mmHg)`  | `Avg Pressure`   | `p_avg`            |

### Event-to-Trace Linking

Events are linked to the trace using **frame numbers as the primary key**:

**Priority 1: Frame-Based Mapping (Most Accurate)**
```
Event Frame → trace.FrameNumber → trace.Time_s_exact
1373        → row with FrameNumber=1373 → 43.144919 seconds
```

**Priority 2: Time Lookup (Fallback)**
```
Event Time string → parse to seconds → find nearest trace row
"00:00:42"        → 42.0 seconds    → closest row at 43.144919
```

**Priority 3: Frame Order Approximation (Legacy)**
- Used only when frame mapping and time parsing both fail
- Approximates time based on event order

### TIFF Frame Synchronization

TIFF frames are synchronized via the `TiffPage` column:

```
Trace Row: FrameNumber=1373, TiffPage=0, Time_s_exact=43.144919
                                  ↓
TIFF: Page 0 → display this frame at time 43.144919 seconds
```

**Frame-to-Time Mapping:**
1. Build mapping: `{TiffPage → trace_row_index → Time_s_exact}`
2. When user clicks time `T` in plot:
   - Find nearest trace row
   - Get its `TiffPage` value
   - Display that TIFF page

---

## .vaso Project Storage

### What Gets Stored

**Inside .vaso file:**
- ✅ Normalized trace data (all columns, high-precision time)
- ✅ Event data with canonical times
- ✅ Frame-to-time mappings
- ✅ Provenance metadata (see below)
- ✅ Analysis results, regions of interest, annotations
- ✅ Matplotlib figure configurations

**External (Linked):**
- 🔗 TIFF files (by default) - stored as external path reference
- 🔗 Original CSV files (optional, for debugging)

**Provenance Metadata Captured:**
```json
{
  "trace_original_filename": "20251202_Exp01.csv",
  "events_original_filename": "20251202_Exp01_table.csv",
  "trace_original_directory": "/Users/you/Data/RawFiles",
  "import_timestamp": "2025-12-05T00:21:00.545158+00:00",
  "canonical_time_source": "Time_s_exact",
  "schema_version": 3
}
```

### TIFF Embedding (Optional)

By default, TIFF files are **NOT embedded** to keep .vaso files lightweight.

**To embed a TIFF:**
1. Set `experiment.embed_tiff_snapshots = True` (requires explicit opt-in)
2. Save the project
3. VasoAnalyzer will:
   - Log a warning with file size
   - Read the entire TIFF into memory
   - Store it as a project asset
   - Significantly increase .vaso file size

**Example warning:**
```
WARNING: Embedding TIFF snapshot for sample=Exp01 (size=3810.7 MB).
         This will increase .vaso file size significantly.
```

**When to embed:**
- Archiving for long-term storage
- Sharing complete datasets
- When external TIFF will be deleted

**When NOT to embed:**
- Working with data actively (keeps saves fast)
- TIFF is backed up elsewhere
- File size is a concern

---

## Schema Version 3

VasoAnalyzer uses **Schema v3** for full VasoTracker support.

### Database Tables

**Trace Table:**
```sql
CREATE TABLE trace (
    dataset_id INTEGER NOT NULL,
    t_seconds REAL NOT NULL,        -- From Time_s_exact (canonical)
    inner_diam REAL,
    outer_diam REAL,
    p_avg REAL,
    p1 REAL,
    p2 REAL,
    frame_number INTEGER,            -- NEW in v3
    tiff_page INTEGER,               -- NEW in v3
    temp REAL,                       -- NEW in v3
    table_marker INTEGER,            -- NEW in v3
    caliper_length REAL,             -- NEW in v3
    PRIMARY KEY (dataset_id, t_seconds)
);
```

**Event Table:**
```sql
CREATE TABLE event (
    id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    t_seconds REAL NOT NULL,
    label TEXT NOT NULL,
    frame INTEGER,
    p_avg REAL,
    p1 REAL,
    p2 REAL,
    temp REAL,
    od REAL,                         -- NEW in v3
    id_diam REAL,                    -- NEW in v3
    caliper REAL,                    -- NEW in v3
    od_ref_pct REAL,                 -- NEW in v3
    extra_json TEXT
);
```

### Auto-Migration from v2

When opening a v2 .vaso file:
1. **Backup created:** `filename.v2.backup.vaso`
2. **Schema upgraded:** ALTER TABLE adds new columns
3. **Old data preserved:** Existing rows get NULL for new columns
4. **Version updated:** PRAGMA user_version = 3

**Migration log:**
```
INFO: Auto-migrating project from v2 to v3
INFO: Created backup: /path/to/project.v2.backup.vaso
INFO: Migrating schema from v2 to v3 (VasoTracker full support)
INFO: Migration complete: v2 → v3
```

---

## UI Synchronization

All UI components stay synchronized through the canonical `Time_s_exact` timeline:

### PyQtGraph Trace View
- X-axis: `Time (s)` column (sourced from `Time_s_exact`)
- Plots: Inner/outer diameter, pressure, temperature
- Event markers: Vertical lines at event times

### Event Table
- Displays: Event index, label, time, frame, diameters, pressures
- Click event → Jump to that time in plot + show TIFF frame

### TIFF Snapshot Viewer
- Synchronized via `TiffPage` → `Time_s_exact` mapping
- Scrubbing timeline updates TIFF frame
- Click in plot → TIFF jumps to corresponding frame

### Matplotlib Figure Composer
- Uses same canonical data
- Event lines placed at exact `t_seconds` values
- Guarantees consistency with PyQtGraph plots

---

## Best Practices

### For VasoTracker Users

1. **Keep all three files together** in the same folder
   - `20251202_Exp01.csv`
   - `20251202_Exp01_table.csv`
   - `20251202_Exp01_Result.tiff`

2. **Don't rename files** (breaks auto-discovery)
   - Keep the `_table` and `_Result` suffixes
   - Maintain the common base name

3. **Import via VasoAnalyzer folder scanner**
   - Drop any one file, app finds the others
   - Clear messages if files are missing

4. **Check for `Time_s_exact` column**
   - Modern VasoTracker versions include it
   - If missing, you'll get a warning but import still works

### For Data Management

1. **Default .vaso saving** (recommended)
   - TIFFs stay external
   - Fast saves
   - Small .vaso files

2. **Archival .vaso** (for long-term storage)
   - Set `embed_tiff_snapshots = True`
   - Creates self-contained archive
   - Large file size (GB+)

3. **Version control**
   - Only commit .vaso files (not TIFFs)
   - Use git-lfs for large .vaso files
   - Keep original VasoTracker files in separate data repo

---

## Troubleshooting

### "Using legacy time column" warning

**Cause:** VasoTracker CSV missing `Time_s_exact` column

**Solution:**
- Update VasoTracker to latest version
- If not possible, import still works with `Time (s)` (100ms precision)

### Missing event table or TIFF

**Symptoms:**
- "Found trace + TIFF (no event table found)"
- "Found trace + events (no TIFF found)"

**Solutions:**
1. Check file naming matches patterns (`*_table.csv`, `*_Result.tiff`)
2. Ensure files are in same folder
3. Import continues with available files

### TIFF frames not synchronized

**Debug:**
1. Check trace CSV has `TiffPage` column
2. Verify `FrameNumber` values match between trace and events
3. Check `TiffPage` indices are 0-based and match TIFF page count

### Schema version mismatch

**Error:** "Project uses legacy schema version 1"

**Solution:**
- Schema v1 requires manual conversion (not auto-upgradeable)
- Contact support or use legacy VasoAnalyzer version

---

## API Reference

### Import Functions

```python
from vasoanalyzer.io.trace_events import load_trace_and_events
from vasoanalyzer.io.events import (
    find_matching_event_file,
    find_matching_tiff_file,
    find_matching_trace_file
)

# Load trace + events with auto-discovery
df, labels, times, frames, diam, od_diam, metadata = load_trace_and_events(
    trace_path="20251202_Exp01.csv"
)

# Metadata includes provenance
print(metadata["canonical_time_source"])  # "Time_s_exact"
print(metadata["import_timestamp"])
```

### File Discovery

```python
# Find siblings from trace
events_path = find_matching_event_file("20251202_Exp01.csv")
tiff_path = find_matching_tiff_file("20251202_Exp01.csv")

# Reverse discovery from event or TIFF
trace_path = find_matching_trace_file("20251202_Exp01_table.csv")
trace_path = find_matching_trace_file("20251202_Exp01_Result.tiff")
```

### TIFF Embedding

```python
# Enable TIFF embedding (use with caution - large file sizes!)
project.embed_tiff_snapshots = True
save_project(project, path="archive.vaso")
```

### File Size Check

```python
from vasoanalyzer.core.project import get_file_size_mb

size_mb = get_file_size_mb("20251202_Exp01_Result.tiff")
print(f"TIFF size: {size_mb:.1f} MB")

# Warn user before embedding
if size_mb > 1000:
    print(f"⚠️  This will add {size_mb:.1f} MB to your .vaso file!")
```

---

## Version History

### Schema v3 (Current)
- **Added:** Full VasoTracker column support
- **Added:** `Time_s_exact` as canonical time
- **Added:** Provenance metadata tracking
- **Added:** Auto-migration from v2 with backup
- **Added:** Optional TIFF embedding with size warnings

### Schema v2 (Legacy)
- Basic trace + events support
- `Time (s)` as canonical (100ms precision)
- Auto-upgrades to v3 on open

### Schema v1 (Deprecated)
- Requires manual conversion
- Not supported by auto-migration

---

## See Also

- [User Manual](USER_MANUAL.md) - General VasoAnalyzer usage
- [Time Synchronization Architecture](time_sync_canonical_architecture.md) - Technical details
- [Snapshot Sync Fixes](snapshot_sync_fixes.md) - Frame synchronization implementation

---

*Last updated: December 5, 2025*
*VasoAnalyzer Schema Version: 3*
