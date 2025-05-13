# VasoAnalyzer 1.6

🧪 *Bladder Vasculature Analysis Toolkit — Python Edition*  
Built by **Osvaldo J. Vega Rodríguez** | Tykocki Lab | Michigan State University

[![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.6/VasoAnalyzer.2.6.macOS.zip)
[![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)]()

---

## 🌟 What is VasoAnalyzer?

**VasoAnalyzer** is a standalone desktop app built to make pressure myography data analysis clean, fast, and intuitive. It visualizes diameter traces, and auto-extracts event-based inner diameter data. **1.6** brings a host of new UX improvements, analysis‑ready exports, and a full dual‑view mode for side‑by‑side comparisons.

Designed for researchers. Powered by Python. Zero coding required.

---
## 🔍 View Modes

### Single View  
– Focus on one trace + event table + snapshot.  
– Ideal for quick QC, event editing, exporting.

### Dual View  
– Compare two datasets side‑by‑side.  
– Independent styling, zoom & pan in each panel.  
– Sync or swap pickles via drag‑and‑drop.
  - Improved TIFF loading, slider syncing, tooltip display

## 🧰 Key Features in v1.6

- **📊 Load & visualize trace data** from `.csv`  
- **📍 Import & display event tables** (CSV/TXT)  
- **🖼️ Synchronized TIFF snapshots** with red trace‑time markers  
- **🧠 Interactive plotting**: zoom, pan, hover‑to‑read, and pin points  
- **📏 Auto‑populated event table** with editable inner‑diameter values  
- **🎨 Plot Style Editor**  
  - Tabbed interface for axis titles, tick labels, event labels, pinned labels, trace style  
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
## 🚀 Download & Install

### ✅ Option 1: No Python Needed — Use the App!

- [![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.6/VasoAnalyzer.2.6.macOS.zip)
- [![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)]()

After downloading:

- **macOS**:  
  1. Unzip the download.  
  2. Move the app to your **Applications** folder.  
  3. **Right-click → Open** (you only need to do this the first time).  
  4. If macOS still blocks the app, see the Gatekeeper fix below.

- **Windows**:  
  1. Unzip the folder.  
  2. Double-click `VasoAnalyzer_1.6.exe` to launch the app.

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
xattr -rd com.apple.quarantine /path/to/VasoAnalyzer 1.6.app
```
Replace /path/to/VasoAnalyzer.app with the actual path where you placed the app
(e.g., ~/Applications/VasoAnalyzer 1.6.app).

Then try launching the app again.  
> You only need to do this once per computer or per download.
---

### 🧪 Option 2: Run From Source (Python 3.10+)

```bash
git clone https://github.com/vr-oj/VasoAnalyzer.git
cd VasoAnalyzer/src
pip install -r requirements.txt
python main.py
```

---

## 👟 How to Use

1. **Load Trace File** (.csv from VasoTracker)
2. **Load Event File** (.csv or .txt with time labels)
3. *(Optional)* Load TIFF file (`_Result.tif`) to view snapshots
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
│   ├── main.py                 # App launcher
│   └── vasoanalyzer/           # App modules and logic
│       ├── gui.py              # UI logic (PyQt5)
│       ├── trace_loader.py     # Load trace CSV
│       ├── event_loader.py     # Load event files
│       ├── tiff_loader.py      # Load TIFFs
│       └── VasoAnalyzerIcon.icns
└── requirements.txt
```

---

## 🧪 Requirements for Developers

- PyQt5>=5.15.4
- matplotlib>=3.5.0
- numpy>=1.21.0
- pandas>=1.3.0
- tifffile>=2021.7.2
- openpyxl>=3.0.0
- Compatible with macOS and Windows

---

## 🛡️ License

Non-commercial academic use only.  
To collaborate, adapt, or extend, please contact the **Tykocki Lab**.

---

## 👨‍🔬 Credits

**Osvaldo J. Vega Rodríguez**  
Developed at the **Tykocki Lab**, Michigan State University

**VasoTracker Group** for TIFF‑trace synchronization logic with VasoTracker software

---
