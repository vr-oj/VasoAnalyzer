# VasoAnalyzer v2.0

**Companion app for VasoTracker — Pressure Myography Analysis Toolkit**

VasoAnalyzer is a **desktop** app (Windows/macOS) that streamlines analysis of pressure myography experiments. It pairs fast trace visualization with event editing, optional TIFF snapshots, and export‑ready figures/tables.

---

## 🚀 Quick Start (End Users)

**1) Download the app**
- Go to the project’s *Releases* page and download the latest build for your OS.
- Windows: unzip, then run `VasoAnalyzer.exe`.
- macOS: unzip, drag the app into **Applications**, then right‑click → Open (first run).

**2) Start a project**
- Launch VasoAnalyzer → **Create Project / Experiment** (or **Open Project**).
- A project saves to a single `*.vaso` file (a standard ZIP under the hood) with:
  - `manifest.json` – experiment metadata & file signatures
  - `state.json` – your window/plot state and layout

**3) Import your data**
- **Trace CSV** with columns like **`Time (s)`**, **`Inner Diameter (µm)`** and optional **`Outer Diameter (µm)`** (header names are case‑insensitive; common synonyms are auto‑recognized). Negative diameters are treated as missing.
- **Event file** (CSV/TXT) with **`Time`** and **`Label`**; optional contextual columns such as **`Temp`**, **`P1`**, **`P2`**, **`Caliper`**, etc.
- **TIFF snapshot** (optional). Large stacks are automatically sub‑sampled for preview to keep the UI responsive.

**4) Analyze & export**
- Pin/edit events, tweak plot style & axes, and export:
  - **`eventDiameters_output.csv`** (event table) — saved next to your trace file
  - **Figure (TIFF/SVG)** — publication‑ready
  - **Session state** → `tracePlot_output.fig.json` — reopens your exact view later
  - **Excel Mapper** — push table data into your lab’s Excel template

**5) Save**
- Use **Save** to write/update your `.vaso` project. You can associate `.vaso` with the app to open projects by double‑clicking.

---

## 🧰 Supported Inputs (summary)

- **Trace:** CSV with **Time** + **Inner Diameter** (µm); **Outer Diameter** optional.
- **Events:** CSV/TXT with **Time** + **Label**; optional columns include **Temp**, **P1**, **P2**, **Caliper**.
- **Images:** TIFF stacks for snapshots/previews (frames auto‑sampled by default).

> Tip: The app is tolerant to common header variants and whitespace/case differences.

---

## 📦 Projects & Files

- **Project format:** `*.vaso` (ZIP) containing `manifest.json` + `state.json`.
- **Snapshots:** Not embedded inside the project by default; link to external TIFFs.
- **Where exports go:** The event CSV and session JSON are written **alongside your trace file**.

---

## 🖼️ Styling & Layout

Use **Plot Settings** to set titles, fonts, grids, axes, and subplot layout. A factory style with sensible defaults ships with the app; you can revert to defaults at any time.

---

## 🔄 Updates & Privacy

- On startup the app may **check GitHub Releases** to notify you of a newer version (short timeout; no telemetry or data upload).
- All analysis happens **locally** on your machine.

---

## 🧪 Run from source (advanced)

1. Install Python 3.10+ and a virtual environment.
2. `pip install -r requirements.txt`
3. `python -m src.main` (or run `src/main.py`)

> Windows packaging uses PyInstaller; macOS uses a standard app bundle (see `packaging/`).

---

## ❓Troubleshooting

- **macOS “unidentified developer”**: Right‑click the app → **Open**.
- **Windows SmartScreen**: Click **More info** → **Run anyway** (if you trust the source).
- **Large TIFFs feel slow**: The app loads a capped number of frames for preview; consider trimming or down‑sampling for smoother navigation.
- **CSV didn’t load**: Ensure headers include *Time* and *Inner Diameter*; see the User Guide for accepted variants.

---

## 🙌 Citation & License

If you use VasoAnalyzer, please cite it (see `CITATION.cff`).  
License: **CC BY‑NC‑SA 4.0**. For details, see `LICENSE` and `LICENSES/` in this repository.
