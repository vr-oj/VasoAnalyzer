# VasoAnalyzer 1.7

🧪 *Bladder Vasculature Analysis Toolkit — Python Edition*  
Built by **Osvaldo J. Vega Rodríguez** | Tykocki Lab | Michigan State University

[![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v1.7/VasoAnalyzer.1.7_macOS.zip)
[![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v1.7/VasoAnalyzer.1.7_Windows.zip)

---

## 🌟 What is VasoAnalyzer?

**VasoAnalyzer** is a standalone desktop app built to make pressure myography data analysis clean, fast, and intuitive. It visualizes diameter traces, and auto-extracts event-based inner diameter data. **1.7** brings a host of new UX improvements, analysis‑ready exports.

Designed for researchers. Powered by Python. Zero coding required.

---
## 🔍 View Modes

### Single View  
– Focus on one trace + event table + snapshot.  
– Ideal for quick QC, event editing, exporting.

## 🧰 Key Features in v1.7

- **📊 Load & visualize trace data** from `.csv`
- **⬅️ Legacy file support** automatically detects old VasoTracker columns and event filenames
- **📍 Import & display event tables** (CSV/TXT)  
- **🖼️ Synchronized TIFF snapshots** with red trace‑time markers  
- **🧠 Interactive plotting**: zoom, pan, hover‑to‑read, and pin points  
- **📏 Auto‑populated event table** with editable inner‑diameter values  
 - **🎨 Plot Style Editor**
  - Consistent fonts and spacing across tabs with helpful descriptions
  - **Apply** & **Reset** on every tab
- **🆕 New Toolbar Buttons**  
  - **Aa** → Open font & style editor  
  - **Grid** → Light‑grid toggle  
- **📌 Pin & Edit Tools**  
  - Left‑click to pin; right‑click to replace or remove  
  - Insert new events with custom labels  
  - Undo last diameter change via Edit → Undo  
- **🔄 One‑click export**  
  - `eventDiameters_output.csv` (data table)  
  - `tracePlot_output.fig.pickle` (editable Python state)  
  - `tracePlot_output_pubready.tiff` / `.svg` (600 dpi publication‑ready)  
- **🧾 Excel Mapper Integration**
  - Map table into existing `.xlsx` templates
  - Preserves formulas & formatting
- **⚡ UI & Performance**
  - Responsive layout, light theme, compact toolbar
  - Fast TIFF loading, slider sync, smooth tooltips


---
## Projects & Ns

Organize related experiments together in a single `.vaso` file. Each project can contain multiple experiments and each experiment holds your N‑samples.

![Sidebar demo](docs/projects_demo.png)

### 📁 Quick Project Workflow

1. **Project → New Project** to start a fresh project file.
2. **Project → Add Experiment** and **Project → Add N** build your experiment tree.
3. Right‑click an N and choose **Load Data Into N…** to import trace and events.
4. Save progress with **Project → Save Project** and reopen using **Project → Open Project…**.
5. **Save N As…** exports a single sample to its own `.vaso` file for quick sharing.
6. Use the **Save As** toolbar button to export a high‑res plot or choose **Save Data to Project** to embed the current trace and events as a new N in the selected experiment.
7. Select two Ns, right‑click, and choose **Open Dual View…** to compare them side by side in one window.

---
## 🚀 Download & Install

### ✅ Option 1: No Python Needed — Use the App!

- [![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v1.7/VasoAnalyzer.1.7_macOS.zip)
- [![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v1.7/VasoAnalyzer.1.7_Windows.zip)

After downloading:

- **macOS**:  
  1. Unzip the download.  
  2. Move the app to your **Applications** folder.  
  3. **Right-click → Open** (you only need to do this the first time).  
  4. If macOS still blocks the app, see the Gatekeeper fix below.

- **Windows**:  
  1. Unzip the folder.  
  2. Double-click `VasoAnalyzer_1.7.exe` to launch the app.

---

### ⚠️ macOS Gatekeeper Warning

If macOS says:

> **“VasoAnalyzer can’t be opened because it is from an unidentified developer”**  
> or  
> **“VasoAnalyzer is damaged and can’t be opened”**

This is a common issue for unsigned apps on macOS — it does **not** mean the app is unsafe. You can safely bypass this using Terminal.

#### One-Time Fix

Open the **Terminal** app and run:

```bash
xattr -rd com.apple.quarantine /path/to/VasoAnalyzer 1.7.app
```
Replace /path/to/VasoAnalyzer.app with the actual path where you placed the app
(e.g., ~/Applications/VasoAnalyzer 1.7.app).

Then try launching the app again.  
> You only need to do this once per computer or per download.
---

### 🧪 Option 2: Run From Source (Python 3.10+)

```bash
git clone https://github.com/vr-oj/VasoAnalyzer.git
cd VasoAnalyzer
pip install -r requirements.txt
python src/main.py
```

---

## 👟 How to Use

1. **Load Trace File** (.csv from VasoTracker)
2. **Load Event File** (.csv or .txt with time labels)
3. *(Optional)* Load TIFF file (`_Result.tif`) to view snapshots
   - Frames load in fast preview mode; click **📋 View Metadata** to parse tags
4. **Zoom** into regions and drag timeline using slider
5. **Pin points** on trace to annotate or edit events
6. **Export** results with one click:
   - `eventDiameters_output.csv`
   - `tracePlot_output.fig.pickle`
   - `tracePlot_output_pubready.tiff` or `.svg`
7. *(Optional)* Click **📊 Excel** to:
   - Map diameters into an Excel template
   - Select column for insertion
   - Preserve all original formulas and formatting

---

## 🛠️ Folder Structure

```
VasoAnalyzer/
├── src/
│   ├── main.py                     # App entry point
│   ├── utils/                      # Configuration helpers
│   ├── icons/                      # Toolbar and UI icons
│   └── vasoanalyzer/               # Application modules
│       ├── ui/                     # Qt widgets and dialogs
│       ├── trace_loader.py         # Load trace CSV
│       ├── event_loader.py         # Load event tables
│       ├── tiff_loader.py          # Load TIFF snapshots
│       ├── project.py              # Project data structures
│       ├── project_controller.py   # Logic for saving/loading projects
│       └── version_checker.py      # GitHub update checker
├── tests/                          # Unit tests
├── docs/                           # Documentation and license
├── icons/                          # Standalone icons
└── requirements.txt
```

---

## 🧪 Requirements for Developers

# core plotting + data
- matplotlib>=3.0
- numpy>=1.18
- pandas>=1.0
- tifffile>=2020.7
- imagecodecs>=2021.3   # optional, for TIFF compression support

# GUI
- PyQt5>=5.15

# Excel export
- openpyxl>=3.0

# for GitHub‑API version checks
- requests>=2.25

# packaging
- pyinstaller>=5.0

Compatible with macOS and Windows

---

## 🛡️ License

VasoAnalyzer is released under the terms of the MIT License. See
[`docs/LICENSE.txt`](docs/LICENSE.txt) for the full license text.

---

## 👨‍🔬 Credits

**Osvaldo J. Vega Rodríguez**  
Developed at the **Tykocki Lab**, Michigan State University

---
