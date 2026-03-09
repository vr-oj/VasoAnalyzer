# VasoAnalyzer v3.0.2

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

## 🔬 VasoTracker Integration

**Full support for VasoTracker experimental data with:**

- **Microsecond-precision time tracking** — Uses `Time_s_exact` for 14 µs accuracy (vs 100 ms)
- **Automatic file discovery** — Drop any file (trace CSV, event table, or TIFF) and VasoAnalyzer finds siblings
- **Complete data preservation** — All VasoTracker columns saved (frame numbers, TIFF pages, temperature, markers, caliper)
- **Smart event linking** — Frame-based synchronization for perfect TIFF alignment
- **Provenance tracking** — Original filenames, timestamps, and data sources preserved
- **External TIFF by default** — Small `.vaso` files; optional embedding for archival

👉 See [**VasoTracker Import Guide**](docs/vasotracker_import.md) for complete documentation.

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
  - Per-channel event labels drawn inline on each track for at-a-glance
    protocol context.

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
  - Flexible template writer supports non-standard lab workbooks: pick a sheet
    and column, preview the result, and write without overwriting formulas.

- **Exports + GIFs**
  - Export to clipboard, CSV, and Excel templates with consistent formatting.
  - Generate high-res plot images (PNG/TIFF/SVG) and synchronized vessel +
    trace GIF animations from the same data.

- **Cross-platform**
  - Runs on recent Windows and macOS versions.
  - Pure Python + Qt + PyQtGraph + Matplotlib, no cloud dependencies.

---

## 🧬 Project Files (`.vaso`)

VasoAnalyzer stores entire experiments as a single project file.

- **`.vaso`** — a ZIP container you can open with any ZIP tool for debugging
  and share freely between machines.

A `.vaso` project typically includes:

- **HEAD.json** — top-level metadata for the experiment.
- **Embedded staging database** — SQLite file with traces, events, and
  derived tables.
- **Snapshots** — optional TIFF snapshots or down-sampled frames for preview.
- **Views & settings** — plot styles, axis settings, event label options.
- **Edit history** — audit entries for point edits made in the Point Editor.
- **Exports** — exported tables, plot images, and GIF settings.

You can safely back up, version, and share a project by copying the `.vaso`
file. For advanced debugging, unzip it with any ZIP tool.

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

1. Click **Open Data…** in the toolbar.
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

### 7. Share datasets between projects

Individual datasets can be shared between projects using **dataset packages**
(`.vasods`) — lightweight ZIP archives containing a single dataset's trace,
events, results, and metadata.

**Export a dataset:**

1. Select the dataset you want to share in the project tree.
2. Go to **File → Export → Export Dataset Package…**
3. Choose a destination and save the `.vasods` file.

**Import a dataset:**

- **From a `.vasods` file:** Go to **File → Open Data → Import Dataset
  Package…**, select the `.vasods` file, and choose which experiment to import
  it into.
- **From another project:** Go to **File → Open Data → Import from Project…**
  to browse another `.vaso` project in read-only mode, select one or more
  datasets, and import them into your current project.

Imported datasets preserve their original metadata and optionally keep the
source experiment grouping. Name collisions are handled automatically.

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
  - `cli/` — `vaso` command-line interface
  - `ui/` — Qt dialogs, main window, point editor, Excel Mapper, export dialogs
  - `core/` — project model, trace/event handling, audit, logging
  - `storage/` — SQLite / project I/O
  - `excel/` — Excel template reading and flexible writer
  - `io/` — trace and event file importers
  - `services/` — project repository, cache, and folder-import services
  - `analysis/` — analysis and metrics modules
  - `export/` — export generators and reports
  - `utils/` — utility modules
- `docs/` — user guide, welcome tour, and import documentation
- `resources/` — application assets (icons, art, stylesheet)
- `schemas/` — data/schema definitions and validation helpers
- `scripts/` — maintenance and developer utilities
- `tests/` — test suite
- `packaging/` — PyInstaller spec, installer scripts, platform configs
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
   pip install -e .
   ```

4. Run the app:

   ```bash
   python -m src.main
   ```

On first run you may see debug logging in the console; packaged builds typically
suppress most of this.

---

## 💻 Installing on macOS (packaged build)

- Build or download the `.app`, then move it into `/Applications` (helps Launch Services register file types).
- In Finder, right-click a `.vaso` file → `Open With` → `VasoAnalyzer`, and enable **Always Open With**. This binds `.vaso` files to VasoAnalyzer so double-click opens the app instead of unzipping.
- If icons/association still look wrong, run the app once from `/Applications` or refresh Launch Services (`lsregister -f /Applications/VasoAnalyzer*.app`).

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
