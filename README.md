# VasoAnalyzer v3.1.0

**Desktop analysis toolkit for pressure myography — built for VasoTracker users**

<!-- TODO: Add screenshot/banner image here -->

VasoAnalyzer turns raw VasoTracker recordings into clean, export-ready results without leaving your desktop. Load a trace CSV, annotate events, clean artefacts, fill your lab's Excel template, and export publication-quality figures — all inside a single `.vaso` project file you can share with collaborators or archive for reproducibility.

> **Privacy first** — all processing happens locally. No cloud, no account, no data leaves your machine.

---

## Who is this for?

VasoAnalyzer is designed for researchers and lab members who run **pressure myography experiments** with [VasoTracker](https://vasotracker.com) and need a fast, reliable way to:

- Visualize multi-channel diameter and pressure traces
- Annotate protocol events (drug additions, pressure steps, washes)
- Clean artefacts and spikes before analysis
- Compare datasets side by side
- Export figures and tables for papers and presentations
- Keep an organized, reproducible record of every experiment

If you currently copy-paste VasoTracker CSVs into Excel by hand, VasoAnalyzer replaces that entire workflow.

---

## Key capabilities

### Single-file projects (`.vaso`)
Every dataset, event annotation, edit, figure setting, and export configuration lives in one portable SQLite file. Back it up, email it, or drop it on a shared drive — your collaborator opens the exact same view.

### Multi-track trace viewer
Inner diameter, outer diameter, pressure, and set-pressure channels stacked in a synchronized view with smooth pan and zoom. Event markers sit above the trace and inline on each channel so you always know where you are in the protocol.

### Dataset comparison
Open the comparison tool to view multiple datasets side by side. Drag samples from the project tree, compare traces across experiments, and see event markers overlaid on each panel.

### Point Editor with audit trail
Interactively clean spikes and artefacts by deleting or connecting points. Every edit is recorded as a structured action and visible in the Edit History panel — nothing is silently discarded.

### Event management
Import event files (CSV/TXT with Time + Label + optional metadata like temperature and caliper readings). Events appear as plot markers, table rows, and strip annotations. Adjust timing and labels in place.

### Excel Mapper
Map event-level and trace-level data into your lab's existing Excel templates. The mapper uses intelligent label matching (exact, normalized, and fuzzy) and remembers your corrections across sessions. Formulas and formatting in the template are preserved.

### Exports
- **Figures** — PNG, TIFF, or SVG at publication resolution
- **GIF animations** — synchronized vessel image + trace playback
- **Event tables** — CSV with diameters, pressures, and metadata per event
- **Dataset packages** (`.vasods`) — share individual datasets between projects
- **Reports** — composite figures with trace, event table, and metadata

### Full VasoTracker integration
- Microsecond-precision timing via `Time_s_exact`
- Automatic sibling file discovery (drop any file and VasoAnalyzer finds the rest)
- Frame-based TIFF synchronization for perfect image alignment
- All VasoTracker columns preserved (frame numbers, TIFF pages, temperature, markers, caliper)
- Provenance tracking — original filenames, timestamps, and data sources recorded

---

## Quick start

### Install

Download the latest release for your platform from the [Releases page](https://github.com/vr-oj/VasoAnalyzer/releases).

| Platform | Download | Steps |
|----------|----------|-------|
| **Windows** | `VasoAnalyzer-Setup-x.x.x.exe` | Run the installer and follow the prompts. A desktop shortcut is created automatically. |
| **macOS** | `VasoAnalyzer-x.x.x.zip` | Extract, drag `VasoAnalyzer.app` to **Applications**, then right-click → **Open** on first launch to bypass Gatekeeper. |

VasoAnalyzer checks for updates automatically (configurable in *Help → Check for Updates*).

### Typical workflow

1. **Create a project** — launch VasoAnalyzer and click *Create New Project* on the Home screen.
2. **Import data** — go to *File → Import* in the menu bar. Load a trace CSV (time + diameter), an event file (time + label), and optionally a TIFF stack.
3. **Explore** — pan and zoom through the trace. Use `P` for pan mode, `Z` for select/zoom mode, scroll to navigate.
4. **Clean** — open the Point Editor to remove spikes and artefacts. All edits are tracked.
5. **Annotate** — adjust event labels and timing in the Events table. Changes are reflected on the plot immediately.
6. **Export** — export figures (PNG/TIFF/SVG), event tables as CSV, or dataset packages for sharing.
7. **Save** — press `Cmd/Ctrl + Shift + S` to save. The `.vaso` file captures everything — reopen it tomorrow to the exact same view.

---

## Supported data formats

### Trace CSV
- **Required**: a time column (`Time (s)` or similar) and an inner diameter column (`Inner Diameter (µm)`)
- **Optional**: outer diameter, pressure, set-pressure, and any additional numeric or categorical columns
- Common header variants are recognized automatically

### Event CSV / TXT
- **Required**: `Time` and `Label`
- **Optional**: `Temp`, `P1`, `P2`, `Caliper`, and other metadata columns
- If an event file sits next to a trace file, VasoAnalyzer auto-detects it

### Images
- TIFF stacks for snapshot/preview (large stacks are auto-sampled for performance)

### Project files
- `.vaso` — single-file SQLite project containing all datasets, annotations, and settings
- `.vasods` — single-dataset package for sharing between projects

---

## Run from source

```bash
# 1. Python 3.10+ required
python --version

# 2. Create a virtual environment
python -m venv .venv && source .venv/bin/activate  # macOS/Linux
python -m venv .venv && .venv\Scripts\activate      # Windows

# 3. Install
pip install -r requirements.txt
pip install -e .

# 4. Launch
python -m src.main
```

---

## macOS tips

- Move the `.app` to `/Applications` so Launch Services registers file type associations.
- Right-click any `.vaso` file → *Open With* → *VasoAnalyzer*, then check *Always Open With* to bind `.vaso` files permanently.
- If icons look wrong after moving the app, run it once from `/Applications` or refresh with `lsregister -f /Applications/VasoAnalyzer*.app`.

---

## Keyboard shortcuts (highlights)

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + O` | Import trace CSV |
| `Cmd/Ctrl + Shift + O` | Open project |
| `Cmd/Ctrl + Shift + S` | Save project |
| `P` | Pan mode |
| `Z` | Select / rectangle zoom |
| `0` | Zoom to full range |
| `A` | Auto-scale Y-axis |
| `Backspace` | Undo last zoom |
| `[ / ]` | Previous / next event |
| `Cmd/Ctrl + Z / Y` | Undo / Redo |
| `Cmd/Ctrl + /` | Open Welcome Guide |

See *Help → Keyboard Shortcuts* in the app for the complete list.

---

## Project layout

```
src/vasoanalyzer/
  app/        — application entry points and launchers
  ui/         — Qt dialogs, main window, point editor, Excel Mapper
  core/       — project model, trace/event handling, audit trail
  storage/    — SQLite project I/O and .vaso bundle format
  excel/      — Excel template reading, flexible writer, label matching
  io/         — trace and event file importers, TIFF loader
  services/   — project repository, cache, version checking
  analysis/   — analysis and metrics modules
  export/     — export generators, reports, clipboard
  cli/        — command-line interface
docs/         — user manual, welcome tour, architecture docs
tests/        — test suite
packaging/    — PyInstaller specs, installer scripts
resources/    — icons, SVGs, stylesheets
```

---

## Documentation

- [User Manual](docs/USER_MANUAL.md) — comprehensive guide covering every feature in depth
- [VasoTracker Import Guide](docs/vasotracker_import.md) — detailed VasoTracker data integration
- [Welcome Tour](docs/WELCOME_TOUR.md) — in-app onboarding reference
- [Bundle Format](docs/BUNDLE_FORMAT.md) — `.vaso` file format specification

---

## Privacy

- All processing happens **locally** on your machine.
- Optional update check on startup (one HTTPS request to GitHub Releases).
- No data, traces, or images are uploaded.

---

## How to cite this software

If VasoAnalyzer contributed to your research, please cite it as:

> Vega Rodríguez, O. J. (2025). *VasoAnalyzer* (v3.1.0) [Computer software]. https://github.com/vr-oj/VasoAnalyzer

BibTeX:

```bibtex
@software{VasoAnalyzer,
  author    = {Vega Rodríguez, Osvaldo J.},
  title     = {VasoAnalyzer},
  version   = {3.1.0},
  year      = {2025},
  url       = {https://github.com/vr-oj/VasoAnalyzer},
  license   = {CC-BY-NC-SA-4.0}
}
```

Machine-readable citation metadata is also available in [`CITATION.cff`](CITATION.cff).

You can also find this citation from within the app via *Help → How to Cite*.

---

## License

This project is released under the **CC BY-NC-SA 4.0** license. See [`LICENSE`](LICENSE) for details.
