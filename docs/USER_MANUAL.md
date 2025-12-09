# VasoAnalyzer User Guide (v2.3.0)

This guide covers the typical end‑user workflow from first run to export.

---

## 1) Install & Launch

- **Download** the latest Windows/macOS build from the Releases page.
- **Windows**: unzip and run `VasoAnalyzer.exe`.
- **macOS**: unzip, drag to **Applications**, right‑click → **Open** the first time.

> Optional: associate `.vaso` files with VasoAnalyzer so you can double‑click projects.

---

## 2) Create a Project & Your First Experiment

1. Open VasoAnalyzer → **Create Project / Experiment**.
2. Name your **Project** and the first **Experiment** (e.g., *ACh Dose Response*).
3. Add a **Sample N** if you track replicates.

A VasoAnalyzer project is a single `.vaso` file that keeps your metadata and window/plot state together.

---

## 3) Import Data

### 3.1 Trace CSV
- Required columns:
  - **`Time (s)`**
  - **`Inner Diameter (µm)`**
- Optional column:
  - **`Outer Diameter (µm)`**
- Header names are matched case‑insensitively. Common variants are automatically normalized. Negative diameter values are treated as missing.

### 3.2 Event Annotations (CSV/TXT)
- Minimal headers:
  - **`Time`** – in seconds
  - **`Label`** – event name (e.g., *KCl 60 mM*)
- Optional context columns: **`Temp`**, **`P1`**, **`P2`**, **`Caliper`**, etc.
- If an event file is in the same folder as the trace, VasoAnalyzer attempts to auto‑detect it by name.

### 3.3 TIFF Snapshot (optional)
- Load a TIFF stack to capture a representative image. Very large stacks are previewed via sub‑sampling (default cap ≈ 300 frames).

---

## 4) Explore, Annotate & Edit

- **Zoom / Pan**: use the toolbar or trackpad/mouse; focus is cursor‑centric.
- **Add/Edit Events**: insert pins, rename labels, or adjust timings in place.
- **Point Editor**: correct outliers or adjust diameter points if needed.
- **Dual View**: compare two *N*’s side by side.
- **Style & Axes**: open **Plot Settings** to set fonts, titles, grids, and axis ranges; revert to factory defaults anytime.

---

## 5) Saving & Reopening

- **Save** writes/updates the `.vaso` file (manifest + state).
- **Reopen** a project from the Welcome screen or **File → Open**; your exact view (zoom/selection) restores automatically.

---

## 6) Export

- **Event table CSV** → `eventDiameters_output.csv` (next to your trace file).
- **Figure export** → TIFF/SVG with your current style and layout.
- **Session state** → `tracePlot_output.fig.json` to reproduce the on‑screen view.
- **Excel Mapper** → send your event table into an existing Excel template while preserving formulas/formatting.

---

## 7) Tips & Gotchas

- Keep your **trace, events, and snapshots** in a tidy folder per experiment.
- Prefer **UTF‑8** CSVs with a header row.
- If you rename/move source files, use the **Relink** dialog when prompted.
- For very large TIFFs, load a smaller subset for smoother navigation.

---

## 8) Shortcuts

- **Save**: `Ctrl/Cmd + S`
- **Undo/Redo**: standard OS shortcuts (where available)
- **Zoom/Pan**: toolbar + common mouse/trackpad gestures

---

## 9) Support, License & Citation

- License: **CC BY‑NC‑SA 4.0**
- Please cite VasoAnalyzer if it contributes to your work (see `CITATION.cff`).
