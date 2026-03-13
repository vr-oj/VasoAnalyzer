# VasoAnalyzer User Manual (v3.1.0)

Comprehensive guide to every feature in VasoAnalyzer — from first launch to advanced exports.

---

## Table of contents

1. [Installation](#1-installation)
2. [First launch and the Home screen](#2-first-launch-and-the-home-screen)
3. [Projects and the project tree](#3-projects-and-the-project-tree)
4. [Importing data](#4-importing-data)
5. [The trace viewer](#5-the-trace-viewer)
6. [Navigation and interaction](#6-navigation-and-interaction)
7. [Event management](#7-event-management)
8. [Point Editor](#8-point-editor)
9. [Snapshot / TIFF viewer](#9-snapshot--tiff-viewer)
10. [Plot settings and styling](#10-plot-settings-and-styling)
11. [Exporting results](#11-exporting-results)
12. [Excel Mapper](#12-excel-mapper)
13. [GIF Animator](#13-gif-animator)
14. [Dataset packages (.vasods)](#14-dataset-packages-vasods)
15. [Saving, autosave, and recovery](#15-saving-autosave-and-recovery)
16. [Preferences](#16-preferences)
17. [Relinking missing files](#17-relinking-missing-files)
18. [Command-line interface (CLI)](#18-command-line-interface-cli)
19. [Keyboard shortcuts](#19-keyboard-shortcuts)
20. [Menu reference](#20-menu-reference)
21. [Privacy and updates](#21-privacy-and-updates)
22. [Tips and troubleshooting](#22-tips-and-troubleshooting)

---

## 1. Installation

### Binary builds (recommended)

| Platform | Steps |
|----------|-------|
| **Windows** | Download the latest `.zip` from the [Releases page](https://github.com/vr-oj/VasoAnalyzer/releases). Extract and run `VasoAnalyzer.exe`. |
| **macOS** | Download the `.zip`, extract, drag the `.app` to **Applications**. On first launch, right-click → **Open** to bypass Gatekeeper. |

**macOS tips:**
- Keep the app in `/Applications` so Launch Services registers `.vaso` file associations.
- To bind `.vaso` files: right-click any `.vaso` file → *Open With* → *VasoAnalyzer* → check *Always Open With*.
- If icons look stale, run `lsregister -f /Applications/VasoAnalyzer*.app` or relaunch.

### From source

```bash
# Python 3.10+ required
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
python -m src.main
```

---

## 2. First launch and the Home screen

On first launch (or after a version upgrade) VasoAnalyzer shows the **Welcome Guide** — a 5-page tour covering the app's capabilities, typical workflow, data formats, navigation, and shortcuts. You can dismiss it and reopen anytime with `Cmd/Ctrl + /`.

The **Home screen** is the landing page shown whenever no project is open:

- **Create New Project** — start a blank project with a name and first experiment.
- **Open Project** — browse for an existing `.vaso` file.
- **Open Data** — quick-view mode: open a trace CSV without creating a project first (you can save as a project later).
- **Return to workspace** — reopen the last active project if one was loaded.
- **Recent Imports** — files and folders you've recently brought into projects.
- **Recent Projects** — projects you've worked on recently (double-click to open).
- **Welcome Guide** — reopen the onboarding tour.

A **storage recommendation banner** may appear on first launch reminding you to keep active `.vaso` projects on local storage (not directly in a cloud-synced folder) for best reliability. Dismiss it once you've read it.

---

## 3. Projects and the project tree

### Hierarchy

VasoAnalyzer organizes data in a four-level hierarchy:

```
Project
  └── Experiment (e.g., "ACh Dose Response")
        └── Sample (e.g., "N1", "N2")
              └── Dataset (trace + events + results)
```

An optional **Subfolder** layer lets you group samples within an experiment.

### The project tree (left sidebar)

The sidebar shows this hierarchy as a collapsible tree. Right-click any node for context actions:

| Node | Actions |
|------|---------|
| **Project** | Add Experiment |
| **Experiment** | Add Sample, Add Subfolder, Delete |
| **Sample** | Open, Dual View, Load Data, Save Data As, Move to Subfolder, Mark Data Quality, Delete |
| **Subfolder** | Add Sample, Delete |
| **Dataset** | Open, Delete |

**Data quality markers** — right-click a sample and choose *Mark Data Quality* to flag it as Good, Questionable, or Bad. This is a visual indicator for your own reference.

**Dual View** — open two datasets side-by-side for comparison.

### The `.vaso` file

A project is stored as a single `.vaso` file — a ZIP container holding:

- `HEAD.json` — project metadata
- Embedded SQLite database — traces, events, results, derived tables
- Edit history — audit entries from the Point Editor
- View settings — plot styles, axis settings, event label preferences
- TIFF snapshots (optional) — embedded or referenced externally

You can inspect a `.vaso` file with any ZIP tool for debugging.

---

## 4. Importing data

### From the toolbar

Click **Open Data** in the toolbar or use the **File → Open Data** submenu:

| Action | Description |
|--------|-------------|
| **Load Trace** | Import a trace CSV (time + diameter columns) |
| **Load Events** | Import an event CSV/TXT (time + label) |
| **Open TIFF** | Load a TIFF stack for snapshot/preview |
| **Import VasoTracker v1/v2** | Auto-detect VasoTracker format and import |
| **Import Folder** | Batch-import all compatible files from a folder |
| **Import Dataset Package** | Load a `.vasods` archive |
| **Import Dataset from Project** | Browse another `.vaso` file and cherry-pick datasets |

### Trace CSV format

- **Required columns:** a time column (e.g., `Time (s)`, `Time_s`, `Time_s_exact`) and an inner diameter column (e.g., `Inner Diameter (µm)`, `ID (um)`)
- **Optional columns:** outer diameter, pressure, set-pressure, and any additional numeric or categorical columns
- Common header variants are recognized automatically. Negative diameter values are treated as missing.

### Event CSV / TXT format

- **Required columns:** `Time` and `Label`
- **Optional columns:** `Temp`, `P1`, `P2`, `Caliper`, `Marker`, and other metadata
- Events appear as: plot markers above the trace, inline labels on each channel, and rows in the Event Table

### TIFF stacks

- Load a representative image stack for visual context
- Large stacks are auto-sampled (default cap ~300 frames) for smooth preview
- Frame-based synchronization keeps the image aligned with the trace timeline

### VasoTracker integration

When you drop any VasoTracker file (trace CSV, event table, or TIFF), VasoAnalyzer automatically discovers sibling files in the same folder. Additional VasoTracker features:

- **Microsecond-precision timing** — uses `Time_s_exact` for 14 µs accuracy
- **Complete column preservation** — frame numbers, TIFF pages, temperature, markers, caliper
- **Provenance tracking** — original filenames, timestamps, and data sources are recorded

---

## 5. The trace viewer

The main workspace is a multi-track trace viewer showing up to four synchronized channels:

1. **Inner Diameter (ID)** — primary trace
2. **Outer Diameter (OD)** — if available
3. **Average Pressure** — if available
4. **Set Pressure** — if available

Each channel is stacked vertically with a shared time axis. An **event strip** above the traces shows numbered event markers aligned in time. Per-channel **inline event labels** are drawn directly on each track for at-a-glance protocol context.

### Channel visibility

Toggle individual channels from the **View → Panels** submenu or the toolbar. Only channels with data are available.

### Level-of-detail rendering

Long recordings are rendered using level-of-detail decimation — you see a downsampled overview when zoomed out, and full-resolution data when zoomed in. This keeps navigation smooth regardless of recording length.

---

## 6. Navigation and interaction

### Toolbar modes

| Mode | Key | Behavior |
|------|-----|----------|
| **Pan** | `P` | Drag left/right to pan through time with momentum scrolling. Cursor shows an open hand. |
| **Select** | `Z` | Draw a rectangle to zoom into that time range. Cursor shows a crosshair. |

### Mouse and trackpad

| Gesture | Action |
|---------|--------|
| Scroll | Pan left/right through time |
| `Cmd/Ctrl` + Scroll | Zoom in/out at cursor position |
| `Shift` + Scroll | Pan the Y-axis up/down |
| `Alt/Option` + Scroll | Zoom the Y-axis in/out |

### Y-axis interactions

- **Drag the Y-axis** (Pan mode only) — hover over the Y-axis labels on the left edge until the cursor changes to a vertical resize arrow, then drag to scale the amplitude range.
- **Shift + Scroll** — slide the Y-axis range up/down without changing scale (works in both modes).
- **Double-click the Y-axis** — auto-scale to fit visible data.
- **Right-click the Y-axis** — context menu with autoscale and range options.

### Quick zoom shortcuts

| Key | Action |
|-----|--------|
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `Backspace` | Undo last zoom (zoom back) |
| `A` | Auto-scale Y-axis (one-shot) |
| `Shift + A` | Toggle persistent Y auto-scale |
| `0` | Zoom to full range |

### Event navigation

| Key | Action |
|-----|--------|
| `[` | Jump to previous event |
| `]` | Jump to next event |

---

## 7. Event management

### Event Table

The Event Table (visible in the main workspace) shows one row per event with columns for index, time, label, and associated measurements (ID, OD, pressure at event time).

- **Edit labels and times** directly in the table
- **Delete events** via right-click or `Edit → Delete Event`
- **Clear all events** via `Edit → Clear All Events`

### Event annotations on the plot

Events are shown in three places simultaneously:
1. **Event strip** — numbered markers above the trace
2. **Inline labels** — text drawn on each channel track
3. **Event Table** — tabular view with editable fields

Changes in any view are reflected in the others immediately.

### Event Review Wizard

Step through events one at a time to verify measurements:
- Review ID, OD, pressure, and set-pressure values at each event
- Mark review state: Unreviewed, Confirmed, Edited, or Needs Follow-up
- Navigate with Previous / Next / Confirm & Next buttons
- The plot automatically scrolls to show the current event

---

## 8. Point Editor

The Point Editor is an interactive tool for cleaning artefacts, spikes, and noise in diameter traces.

### Opening the Point Editor

Click **Edit Points** in the toolbar or use the context menu on a trace channel.

### Interface

- **Left panel** — matplotlib plot showing the raw trace (gray) and your edited preview (blue). Selected points are highlighted in orange.
- **Right panel** — data table with columns: Index, Time (s), Raw value, Preview value.

### Operations

| Operation | Description |
|-----------|-------------|
| **Delete (NaN)** | Replace selected points with NaN, creating a gap in the trace |
| **Connect Across** | Interpolate over deleted points using Linear or Slope-preserving cubic interpolation |
| **Restore** | Revert selected points to original values |
| **Undo / Redo** | Full editing history |

### Selection

- **Click** on the plot to select a single point
- **Shift + Click** to extend the selection
- **Cmd/Ctrl + Click** to toggle individual points
- **Drag** to move selected points vertically
- Table row selection syncs with the plot and vice versa

### Applying changes

- **Apply & Close** — commits all edits to the main trace and closes the editor
- **Cancel** — discards all edits

All applied edits are recorded in the **Edit History** panel (Details sidebar) as structured actions with timestamps, so you always have a record of what was changed and when.

---

## 9. Snapshot / TIFF viewer

The integrated TIFF viewer shows vessel image frames synchronized to the trace timeline.

- **Frame synchronization** — the displayed frame updates as you navigate the trace
- **Playback controls** — play/pause, frames-per-second control, speed multiplier
- **Loop and sync toggles** — loop playback, lock to trace cursor
- **Frame stride** — skip frames for reduced memory usage on very large stacks

Toggle the viewer from **View → Panels → Snapshot Viewer**.

---

## 10. Plot settings and styling

Open plot settings from **Tools → Plot Settings** or the toolbar. The dialog has four tabs:

### Layout tab
Control subplot margins and spacing:
- Left, Right, Top, Bottom margins (0–1 scale)
- Width gap (wspace) and Height gap (hspace) between subplots
- Live preview canvas shows changes in real time

### Axis tab
Configure axis ranges and scales:
- **X axis** — auto range, min/max, scale (Linear/Log), major tick count
- **Top plot Y-axis** — auto range, min/max, scale, ticks, units suffix
- **Bottom plot Y-axis** — same controls
- **Grid & ticks** — show/hide grid, tick length, tick width

### Style tab
Customize titles, fonts, and colors:
- **Titles** — plot title, X-axis title, Y-axis titles (top and bottom)
- **Font** — family, size (6–48 pt), bold/italic
- **Colors** — separate color pickers for each axis title
- **Tick labels** — font size and color per axis

### Event Labels tab
Fine-tune how event annotations appear on the plot:
- **Display mode** — Vertical, Horizontal, Belt, or Auto (switches based on density)
- **Font** — family, size, bold/italic, color
- **Clustering** — group nearby events, max events per cluster, number of lanes
- **Belt mode** — baseline position, span siblings
- **Density thresholds** — when to switch between compact and belt modes
- **Outlines** — enable/disable, width, color
- **Tooltips** — proximity-based hover tooltips
- **Legend** — show/hide, location (11 presets including "Best"), column count, border
- **Per-event overrides** — customize individual event labels beyond the global defaults

---

## 11. Exporting results

VasoAnalyzer supports multiple export paths, all accessible from **File → Export**:

### Clipboard (copy for Excel)
- **Copy as Excel row** — one row with all metrics, ready to paste
- **Copy as Excel values only** — values without headers
- **Copy pressure curve** — pressure-specific data

### CSV export
- **Export as CSV (row format)** — one row per event with associated diameters and pressures
- **Export as CSV values only** — values without header metadata
- **Export pressure curve as CSV** — pressure curve data

### Figure export
Export the current plot as a high-resolution image:

| Setting | Options |
|---------|---------|
| **Format** | TIFF (raster) or SVG (vector) |
| **DPI** | 72–2400 (default 600) |
| **Width** | Single column (85 mm), 1.5 column (120 mm), double column (180 mm), presentation (260 mm), or custom (40–400 mm) |
| **Padding** | 0–1.0 inches (default 0.03) |
| **SVG fonts** | Flatten to outlines (optional) |

Height is calculated automatically to preserve the current aspect ratio.

### Experiment report
Generate a composed report page combining trace plot, TIFF snapshot, and event table:

| Setting | Options |
|---------|---------|
| **Template** | Standard Landscape, Wide Trace, Trace Focus, Poster Panel, Custom |
| **Page size** | Width 6–24 in, Height 5–18 in |
| **Panels** | Include TIFF snapshot, Include event table |
| **Format** | PNG, TIFF, or PDF |
| **DPI** | 72–1200 (default 300) |

### Excel template export
See [Excel Mapper](#12-excel-mapper) below.

### Other exports
- **Export TIFF** — save snapshot frames as TIFF
- **Export Bundle** — package project for archival
- **Export Shareable** — create a shareable project format

---

## 12. Excel Mapper

The Excel Mapper lets you fill your lab's existing Excel templates with VasoAnalyzer data while preserving formulas and formatting.

### Two modes

**Standard mode** — auto-detects VasoAnalyzer Standard Template format:
- Select a block (for replicate columns) and replicate number
- Choose a profile (e.g., Pressure Curve Standard)
- Option to skip missing metrics
- Preview table shows metric names, values, and target cells

**Flexible mode** — for any custom Excel template:
- Select the target sheet and column
- Map template rows to your session events using the mapping table
- The mapper uses intelligent label matching (4-pass cascade):
  1. **Saved history** — reuses your corrections from previous sessions
  2. **Existing sheet values** — matches against values already in the template
  3. **Exact match** — case-insensitive label comparison
  4. **Normalized match** — handles µ→u conversion, punctuation, digit-letter splits
  5. **Fuzzy match** — substring and Jaccard token overlap for partial matches
- Green/amber row tinting provides visual feedback on match quality
- Validation before export detects unmapped rows and duplicates

### Template fingerprinting

The mapper remembers your column wiring per template. When you reopen the same template (identified by a structural fingerprint), your previous mappings are restored automatically.

---

## 13. GIF Animator

Create synchronized vessel image + trace animations:

1. Open from **File → Export → GIF Animator**
2. Configure:
   - **Frame rate (FPS)** and speed multiplier
   - **Loop** enable/disable
   - **TIFF cropping** — select a region of interest with a rubber-band tool
   - **Trace panel** — show/hide, styling options
   - **Event annotations** — overlay event markers on the animation
3. Preview the animation before exporting
4. Export — the renderer runs in the background with progress tracking and cancellation support
5. Size estimation is shown before you commit to the export

You can also generate a **poster frame** — a single static image from the animation.

---

## 14. Dataset packages (.vasods)

Dataset packages are lightweight ZIP archives containing a single dataset, useful for sharing specific experiments between projects or with collaborators.

### Exporting

1. Select a dataset in the project tree
2. Go to **File → Export → Export Dataset Package**
3. Choose a destination and save

### Contents of a `.vasods` file

- `data/trace.csv` — time series data
- `data/events.csv` — event markers with labels, times, values, and review states
- `data/dataset.json` — metadata (ID, name, notes, FPS, pixel size, creation date)
- `data/results.json` — analysis results (optional)
- `manifest.json` — format version, app version, source project UUID, SHA256 checksums

### Importing

- **From a `.vasods` file:** File → Open Data → Import Dataset Package
- **From another project:** File → Open Data → Import Dataset from Project (browse in read-only mode and cherry-pick)

Imported datasets preserve their original metadata. Name collisions are handled automatically.

---

## 15. Saving, autosave, and recovery

### Manual save

- `Cmd/Ctrl + Shift + S` — save the project to its `.vaso` file
- **Save As** — save a copy under a new name or location

### Autosave

VasoAnalyzer can automatically save snapshots of your work at regular intervals:

| Setting | Options |
|---------|---------|
| **Enable/disable** | Toggle in Preferences → Autosave & Snapshots |
| **Interval** | 30 seconds, 1 minute, 2 minutes, 5 minutes, or 10 minutes |
| **Retention** | Keep 1–500 snapshots (default: 3) |
| **Embed snapshots** | Store snapshots inside the project file (larger but fully portable) |

### Crash recovery

If VasoAnalyzer detects an unfinished session from a previous crash, it offers to recover your work automatically. Recovery snapshots are stored alongside your project.

### Temporary file cleanup

Stale temporary files older than a configurable threshold (1–168 hours) are cleaned up automatically. You can also trigger a manual cleanup from Preferences → Advanced.

---

## 16. Preferences

Open from **File → Preferences** (or `VasoAnalyzer → Preferences` on macOS).

### General
- Default save location (project directory)
- Default data location (import directory)
- Color theme: Light or Dark
- Show welcome dialog on startup
- Restore last session on startup

### Projects
- Use single-file project format (`.vaso`) for new projects
- Automatic migration of legacy projects
- Keep legacy backup files after migration

### Autosave & Snapshots
- See [Autosave](#autosave) section above

### Advanced
- Enable/disable automatic recovery
- Temporary file cleanup age threshold
- Compress container files (reduces size 10–20%, slower saves)
- Manual temp file cleanup button

---

## 17. Relinking missing files

If you move or rename source files (trace CSVs, event files, TIFFs) after importing them, VasoAnalyzer will prompt you to relink.

Open the Relink dialog from **Tools → Relink Missing Assets** or when prompted:

1. The dialog shows a tree of all missing assets with columns: Item Name, Current Path, Relative Path, Status
2. **Select Root Folder** — point to the folder containing your files and VasoAnalyzer will auto-match by filename
3. **Relink Selected** — manually choose a replacement file for a specific item
4. Status indicators: green "Ready" (found) or red "Missing" (not found)
5. Click **Apply** to commit all changes at once

---

## 18. Command-line interface (CLI)

VasoAnalyzer includes a `vaso` CLI for scripted workflows:

```bash
# Create a new empty project
vaso new project.vaso --title "My Study"

# Add a dataset
vaso add-dataset project.vaso --name "Vessel1" --rate 50 --channels inner:µm outer:µm

# Add an event
vaso add-event project.vaso --id evt1 --dataset-id ds1 --t 120.5 --label "KCl 60mM"

# Embed a file (e.g., TIFF)
vaso pack project.vaso --dataset-id ds1 --file snapshot.tiff --role tiff

# Verify project integrity
vaso verify project.vaso

# Recovery tools
vaso recover project.vaso --list               # List available recovery snapshots
vaso recover project.vaso --extract 2 --output recovered.vaso  # Extract snapshot
vaso recover --find-autosaves ~/Documents      # Find autosave files
```

---

## 19. Keyboard shortcuts

### File

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + O` | Import trace CSV |
| `Cmd/Ctrl + Shift + O` | Open project |
| `Cmd/Ctrl + Shift + S` | Save project |

### Navigation

| Shortcut | Action |
|----------|--------|
| `P` | Pan mode |
| `Z` | Select / rectangle zoom |
| `0` | Zoom to full range |
| `A` | Auto-scale Y-axis (one-shot) |
| `Shift + A` | Toggle persistent Y auto-scale |
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `Backspace` | Undo last zoom |
| `[` | Previous event |
| `]` | Next event |
| `Left` / `Right` | Pan left / right |

### Editing

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + Z` | Undo |
| `Cmd/Ctrl + Y` | Redo |
| `Cmd/Ctrl + F` | Fit data to window |
| `Cmd/Ctrl + /` | Open Welcome Guide |

For the complete list, see **Help → Keyboard Shortcuts** in the app.

---

## 20. Menu reference

### File
- **Project** — New, Open, Recent, Save, Save As, Add Experiment, Add Sample
- **Open Data** — Load Trace, Import VasoTracker, Load Events, Open TIFF, Import Folder, Import Dataset Package, Import from Project
- **Recent Imports** — recently opened files
- **Export** — Copy for Excel, Export CSV, Excel Template, Excel Mapper, GIF Animator, Dataset Package, TIFF, Experiment Report, Bundle, Shareable
- **Preferences** / **Exit**

### Edit
- Undo / Redo
- Delete Event
- Clear Pinned Points
- Clear All Events

### View
- Home (zoom to fit)
- Color Theme (Light / Dark)
- Reset Zoom / Fit / Zoom to Selection
- Go to Time
- **Annotations** — label mode (Off / Vertical / Horizontal / Outside)
- **Panels** — Event Table, Snapshot Viewer, Zoom Window, Scope View, Metadata, Channel toggles (ID, OD, Avg Pressure, Set Pressure)
- Fullscreen

### Tools
- Plot Settings
- Layout Adjustment
- Select Range / Copy Range / Export Range
- Relink Missing Assets
- Compare Datasets
- Change Log

### Window
- Minimize / Zoom / Bring All to Front

### Help
- About VasoAnalyzer / About Project
- User Manual / Welcome Guide / Tutorial
- Check for Updates
- Keyboard Shortcuts
- Report Bug / Release Notes

---

## 21. Privacy and updates

- All processing happens **locally** on your machine.
- No data, traces, or images are uploaded anywhere.
- An optional update check on startup sends a single HTTPS request to the GitHub Releases API. You can disable this in Preferences.

---

## 22. Tips and troubleshooting

- **Keep source files organized** — store trace, event, and TIFF files in a tidy folder per experiment. This makes relinking easy if you move things.
- **Use UTF-8 CSVs** with a header row for best compatibility.
- **Store active projects locally** — cloud storage sync (iCloud, OneDrive, Dropbox) can interrupt SQLite writes. Copy `.vaso` files to cloud storage for backup, but work on a local copy.
- **Large TIFF stacks** — VasoAnalyzer auto-samples for preview. For smoother interaction, consider loading a subset.
- **Negative diameter values** — treated as missing data and excluded from calculations.
- **File associations** — on macOS, move the app to `/Applications` and use "Open With" to bind `.vaso` files. On Windows, the installer registers associations automatically.
- **Recovery** — if the app closes unexpectedly, it will offer to recover your last session on next launch. You can also use `vaso recover` from the command line.
- **Inspect `.vaso` files** — they're standard ZIP archives. Rename to `.zip` and unzip with any tool for debugging.

---

*VasoAnalyzer is released under the CC BY-NC-SA 4.0 license. If it contributed to your research, please cite it using the metadata in `CITATION.cff`.*
