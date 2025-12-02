# VasoAnalyzer v2.2.5

**Companion app for VasoTracker — Pressure Myography Analysis Toolkit**

VasoAnalyzer is a cross-platform **desktop app** (Windows / macOS) for analyzing
pressure myography experiments. It focuses on:

- fast, responsive trace visualization  
- rich event annotation  
- careful point editing with an audit trail  
- export-ready figures and tables

Everything for an experiment lives in a single project file (`.vaso`) so you
can send a whole analysis to a collaborator as one file.

---

## ✨ Key Features

- **Single-file projects (`.vaso`)**
  - All datasets, analysis state, and configuration are stored inside one file.
  - Designed to be portable between machines and OSes.

- **Multi-track trace viewer**
  - Inner diameter, outer diameter, pressure, and set-pressure stacked in a
    synchronized view.
  - Level-of-detail rendering keeps navigation smooth even for long recordings.
  - Event strip above the trace shows numbered event markers aligned in time.

- **Point Editor with audit history**
  - Interactive editor for cleaning artefacts and spikes in diameter traces.
  - Connect-across / delete-with-NaN operations.
  - Edits are recorded as structured actions and summarized in the dataset
    “Edit History” panel.

- **Event management**
  - CSV-based event import (time + label, plus optional metadata).
  - Events are tied to the trace and shown in both the event table and plots.
  - Default plot labels use event indices (1, 2, 3, …) that match the table.

- **Excel Mapper**
  - Map event- and trace-level data into your lab’s Excel templates.
  - Reuse mappings so you don’t have to redo column wiring every time.

- **Figure Composer**
  - Build publication-ready multi-panel figures from your plots.
  - Share figure layouts inside the `.vaso` project for reproducibility.

- **Cross-platform**
  - Runs on recent Windows and macOS versions.
  - Pure Python + Qt + PyQtGraph, no cloud dependencies.

---

## 🧬 Project Files (`.vaso`)

VasoAnalyzer stores entire experiments as a single `*.vaso` file.

A `.vaso` project is a **ZIP container** that typically includes:

- **HEAD.json** — top-level metadata for the experiment.
- **Embedded staging database** — SQLite file with traces, events, and
  derived tables.
- **Snapshots** — optional TIFF snapshots or down-sampled frames for preview.
- **Views & settings** — plot styles, axis settings, event label options.
- **Edit history** — audit entries for point edits made in the Point Editor.
- **Figures & exports** — saved figure configurations and exported tables.

You can safely back up, version, and share a project by copying the `.vaso`
file. For advanced debugging, the file can be unzipped with any ZIP tool.

---

## 🚀 Quick Start (End-Users)

### 1. Install

- **Binary build (recommended)**
  - Download the latest Windows/macOS build from the project’s Releases page.
  - Windows: unzip, then run `VasoAnalyzer.exe`.
  - macOS: unzip, drag the app to **Applications**, then right-click → **Open**
    on first run to bypass Gatekeeper.

- **From source (advanced)**
  - See [Run from source](#-%EF%B8%8F-run-from-source-advanced) below.

### 2. Create or open a project

1. Launch **VasoAnalyzer**.
2. From the Home screen choose:
   - **New project / experiment** to start from scratch, or  
   - **Open project** to load an existing `*.vaso` file.
3. The left sidebar shows your project tree (cohorts → samples → traces).

### 3. Import data

For each sample / trace:

1. Click **Import data…** in the toolbar.
2. Choose:
   - **Trace CSV**: must contain a time column and at least an inner diameter
     column. Common header variants are recognized automatically.
   - **Events CSV/TXT**: at minimum, `Time` and `Label`; optional metadata
     columns (e.g. `Temp`, `P1`, `P2`, `Caliper`) are preserved.
   - **TIFF snapshot** (optional): a representative stack; frames are
     down-sampled for fast preview.

After import, the trace viewer will show stacked ID/OD/pressure tracks plus an
event table.

### 4. Clean and annotate

- Use **Edit Points** to open the Point Editor:
  - Clean spikes and artefacts by deleting or connecting points.
  - Apply changes to update the main trace.
  - The “Edit History” section in the Details panel records what you did.

- Use the **Events** table to adjust event times and labels:
  - These are reflected in the plot and the event strip.

- Use **Plot Settings** to adjust:
  - Grid, axes, fonts, and tick styling.
  - Event label appearance.

### 5. Export

VasoAnalyzer supports several export paths:

- **Event tables** (CSV) — one row per event with associated diameters /
  pressures and metadata.
- **Excel Mapper** — map data into a lab-specific Excel template.
- **Figures** — export plots and composed figures as PNG/TIFF/SVG (depending on
  platform and configuration).

All exports are reproducible: VasoAnalyzer stores enough state inside the
project to regenerate views.

### 6. Save and reopen

- Use **Save Project** in the toolbar to persist your work to the `.vaso` file.
- Later, double-click a `.vaso` or open from within the app to resume exactly
  where you left off (including plots, events, edit history, and figures).

---

## 🧰 Supported Inputs (summary)

- **Trace CSV**
  - Required columns:
    - `Time (s)` or similar
    - `Inner Diameter (µm)` (header variants allowed)
  - Optional columns:
    - `Outer Diameter (µm)`
    - one or more pressure channels
    - any extra numeric or categorical columns

- **Event CSV/TXT**
  - Required: `Time`, `Label`
  - Optional: `Temp`, `P1`, `P2`, `Caliper`, and other metadata columns.

- **Images**
  - TIFF stacks for snapshot/preview.
  - Large stacks are auto-sampled for responsiveness.

---

## 🗂️ Repository Layout (high-level)

- `src/vasoanalyzer/`
  - `app/` — application entry points and launchers
  - `ui/` — Qt dialogs, main window, point editor, Excel Mapper, Figure Composer
  - `core/` — project model, trace/event handling, audit, logging
  - `storage/` — SQLite / project I/O
  - `resources/` — icons, QSS styles, etc.
- `packaging/` — PyInstaller / macOS bundle configs (if present)
- `README.md` — this file
- `LICENSE`, `CITATION.cff` — licensing and citation info

(Details may vary slightly by version.)

---

## 🧪 Run from source (advanced)

1. Install **Python 3.10+**.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
````

4. Run the app:

   ```bash
   python -m src.main
   # or, depending on layout:
   python src/main.py
   ```

On first run you may see debug logging in the console; packaged builds typically
suppress most of this.

---

## 🔐 Privacy

* All processing happens **locally** on your machine.
* The app may optionally check for updates (GitHub Releases) on startup using a
  short HTTP request.
* No data, traces, or images are uploaded by default.

---

## 🙌 Citation & License

If VasoAnalyzer contributed to your work, please cite it using the metadata in
`CITATION.cff`.

This project is released under the **CC BY-NC-SA 4.0** license. See `LICENSE`
and `LICENSES/` in this repository for details.
