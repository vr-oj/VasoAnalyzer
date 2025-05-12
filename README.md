# VasoAnalyzer 2.6

🧪 *Bladder Vasculature Analysis Toolkit — Python Edition*  
Built by **Osvaldo J. Vega Rodríguez** | Tykocki Lab | Michigan State University

[![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.5/VasoAnalyzer.2.5.macOS.zip)
[![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.5/VasoAnalyzer.2.5.Windows.zip)

---

## 🌟 What is VasoAnalyzer?

**VasoAnalyzer** is a standalone desktop app built to make pressure myography data analysis clean, fast, and intuitive. It visualizes diameter traces, and auto-extracts event-based inner diameter data.

Designed for researchers. Powered by Python. Zero coding required.

---

## 🧰 Key Features in v2.6

- **📊 Load and visualize trace data** from `.csv` files
- **📍 Import and display events** from `.csv` or `.txt` files
- **🖼️ View synchronized TIFF snapshots** with red trace markers
- **🧠 Interactive plotting**: zoom, pan, hover, and pin points
- **📏 Auto-populated event table** with editable inner diameter values
- **🎨 Plot Style Editor** (Tabbed)
  - Customize fonts and line widths
  - Separate tabs for: axis titles, tick labels, event labels, pinned labels, trace style
  - Each tab has **Apply** and **Reset** buttons
- **🆕 New Toolbar Buttons**:
  - "Aa" = Open font + style editor
  - "Grid" = Toggle grid visibility (light grid on/off)
- **📌 Pin and Edit Tools**:
  - Right-click any pin to replace or remove
  - Insert new events with custom labels
  - Undo last diameter change
- **🔄 One-click export**:
  - `eventDiameters_output.csv` (for Excel or analysis)
  - `tracePlot_output.fig.pickle` (editable in Python)
  - `tracePlot_output_pubready.tiff` or `.svg` (publication-ready)
- **🧾 Excel Mapper Integration**:
  - Map events to a custom Excel file
  - Preserves formulas and formatting
- **⚡ UI + Performance Improvements**
  - Responsive design, light theme, compact toolbar spacing
  - Improved TIFF loading, slider syncing, tooltip display

---
## 🚀 Download & Install

### ✅ Option 1: No Python Needed — Use the App!

- [![Download macOS App](https://img.shields.io/badge/Download-macOS-blue?logo=apple&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.5/VasoAnalyzer.2.5.macOS.zip)
- [![Download Windows App](https://img.shields.io/badge/Download-Windows-blue?logo=windows&style=for-the-badge)](https://github.com/vr-oj/VasoAnalyzer/releases/download/v2.5/VasoAnalyzer.2.5.Windows.zip)

After downloading:

- **macOS**:  
  1. Unzip the download.  
  2. Move the app to your **Applications** folder.  
  3. **Right-click → Open** (you only need to do this the first time).  
  4. If macOS still blocks the app, see the Gatekeeper fix below.

- **Windows**:  
  1. Unzip the folder.  
  2. Double-click `VasoAnalyzer_2.5.exe` to launch the app.

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
xattr -rd com.apple.quarantine /path/to/VasoAnalyzer 2.5.app
```
Replace /path/to/VasoAnalyzer.app with the actual path where you placed the app
(e.g., ~/Applications/VasoAnalyzer 2.5.app).

Then try launching the app again.  
> You only need to do this once per computer or per download.
---

### 🧪 Option 2: Run From Source (Python 3.10+)

```bash
git clone https://github.com/vr-oj/VasoAnalyzer_2.0.git
cd VasoAnalyzer_2.0/src
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
VasoAnalyzer_2.0/
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

---
