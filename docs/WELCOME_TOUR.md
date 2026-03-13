# Welcome Tour — VasoAnalyzer v3.1.0

Reference text for the in-app Welcome Guide (5 pages). The dialog can be reopened anytime with `Cmd/Ctrl + /`.

---

## Page 1 — Overview

**What is VasoAnalyzer?**

VasoAnalyzer is a desktop toolkit for analyzing pressure myography experiments. Load your VasoTracker recordings, clean the data, annotate events, fill your lab's Excel template, and export publication-ready figures — all inside a single `.vaso` project file you can share with collaborators.

**Highlights:**
- **Multi-track trace viewer** — ID, OD, pressure, and set-pressure in a synchronized view with event markers and level-of-detail rendering.
- **Point Editor with audit trail** — clean artefacts interactively; every edit is recorded.
- **Events + Excel Mapper** — import events, view them as plot markers and table rows, then map results into your lab's Excel template with intelligent label matching.
- **Figures, GIFs + dataset sharing** — export PNG/TIFF/SVG, GIF animations, and `.vasods` dataset packages.
- **Full VasoTracker integration** — microsecond timing, automatic file discovery, frame-based TIFF sync, complete data preservation.

---

## Page 2 — Workflow

**Your workflow in 5 steps:**

1. **Create or open a project** — start fresh or open an existing `.vaso` file.
2. **Import your data** — load trace CSVs, event files, and optional TIFF stacks. VasoTracker sibling files are discovered automatically.
3. **Explore and clean** — pan/zoom through the trace (`P` for pan, `Z` for zoom). Use the Point Editor to remove spikes.
4. **Annotate and map** — adjust events in the table, then use the Excel Mapper to fill your lab's template.
5. **Export and save** — export figures, GIFs, event tables, or filled templates. Save the project to capture everything.

---

## Page 3 — Data

**Data you can load:**

- **Trace CSVs** — time + inner diameter (required); outer diameter, pressure, set-pressure optional. Common header variants auto-detected.
- **Event files (CSV/TXT)** — Time + Label; optional metadata (Temp, P1, P2, Caliper). Events appear as plot markers, table rows, and inline labels.
- **TIFF stacks** — vessel image frames for visual context. Large stacks auto-sampled; frame-based TIFF sync for image alignment.
- **Project files (.vaso)** — ZIP-based bundle with all data, edits, settings, and exports.
- **Dataset packages (.vasods)** — lightweight single-dataset archives for sharing.

---

## Page 4 — Navigation

**Toolbar modes:**
- **Pan mode (P)** — drag to pan through time with momentum scrolling.
- **Select mode (Z)** — draw a rectangle to zoom into that time range.

**Scroll wheel / trackpad:**
- `Scroll` — pan left/right through time
- `Cmd/Ctrl + Scroll` — zoom in/out at cursor position
- `Shift + Scroll` — pan Y-axis up/down
- `Alt/Option + Scroll` — zoom Y-axis

**Y-axis interactions:**
- Drag the Y-axis to scale (Pan mode)
- `Shift + Scroll` to pan the Y-axis
- Double-click to auto-scale
- Right-click for context menu

**Quick zoom:**
- `+` / `=` — zoom in
- `-` — zoom out
- `Backspace` — undo last zoom
- `A` — auto-scale Y (one-shot)
- `Shift + A` — toggle persistent auto-scale
- `0` — zoom to full range

---

## Page 5 — Shortcuts

**File:**
- `Cmd/Ctrl + O` — import trace CSV
- `Cmd/Ctrl + Shift + O` — open project
- `Cmd/Ctrl + Shift + S` — save project

**Navigation:**
- `P` — pan mode
- `Z` — select/zoom mode
- `0` — zoom to full range
- `A` — auto-scale Y-axis
- `Backspace` — undo last zoom
- `[ / ]` — previous/next event
- `Left / Right` — pan left/right

**Editing:**
- `Cmd/Ctrl + Z` — undo
- `Cmd/Ctrl + Y` — redo
- `Cmd/Ctrl + F` — fit data to window
- `Cmd/Ctrl + /` — reopen this guide

> For the complete list, see Help → Keyboard Shortcuts in the menu bar.
