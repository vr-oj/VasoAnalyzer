# Development Guide

Developer reference for working on VasoAnalyzer.

---

## Prerequisites

- **Python 3.10+** (CI uses 3.11)
- **macOS** or **Windows** for running the GUI (Linux works headless with `QT_QPA_PLATFORM=offscreen`)
- On Ubuntu, PyQt5 needs system libraries — see `.github/workflows/tests.yml` for the list

---

## Setup

```bash
git clone https://github.com/vr-oj/VasoAnalyzer.git
cd VasoAnalyzer
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

---

## Running the App

```bash
python -m src.main
```

---

## Project Structure

```
src/
  main.py                          # Entry point
  utils/config.py                  # APP_VERSION and global config
  vasoanalyzer/
    app/                           # Application entry points and launchers
    cli/                           # `vaso` CLI interface
    ui/
      main_window.py               # Main window (~17,800 lines, mypy: ignore-errors)
      shell/init_ui.py             # UI initialization
      shell/toolbars.py            # Toolbar actions
      dialogs/                     # All dialog windows
      plots/
        pyqtgraph_channel_track.py # PyQtGraph multi-track renderer
        pyqtgraph_axes_compat.py   # Matplotlib-compatible axes wrapper
        canvas_compat.py           # Canvas compatibility layer
      point_editor_session.py      # Point editor logic
      point_editor_view.py         # Point editor UI
      panels/                      # Sidebar panels
      mixins/                      # Main window mixin classes
      gif_animator/                # GIF export
    core/                          # Project model, trace/event handling, audit
    storage/                       # SQLite / project I/O
    excel/                         # Excel template reading and flexible writer
    io/                            # Trace and event file importers
    services/                      # Project repository, cache, folder-import
    analysis/                      # Analysis utilities
    export/                        # Export utilities
tests/                             # Test suite (178 tests)
docs/                              # User guide, architecture docs, audit logs
icons/                             # 68 SVG icons for the UI
packaging/                         # macOS Info.plist and build configs
installer/                         # Platform-specific installer scripts
schemas/                           # Data/schema definitions and validation
scripts/                           # Maintenance and developer utilities
```

---

## Architecture Notes

### Renderer: PyQtGraph only

The live trace viewer uses **PyQtGraph exclusively**. Matplotlib is only used for offline high-res exports. This means:

- `self.ax` in `main_window.py` is a `PyQtGraphAxesCompat` wrapper, **not** a Matplotlib `Axes`
  - Has `get_xlim()`, `get_ylim()`, `set_xlim()`, `set_ylim()`
  - Does **NOT** have `relim()` or `autoscale_view()`
- `self.canvas` is a `PyQtGraphCanvasCompat` (has `draw_idle()`)
- For zoom-to-fit: use `self._zoom_all_x()` — the PyQtGraph-aware full-range zoom

### Important patterns

- **Single-key shortcuts**: `I`, `O`, `S` toggle Inner/Outer/Set-Pressure traces
- **Navigation**: `[`/`]` = prev/next event, `Left`/`Right` = pan, `Home`/`End` = jump, `0` = zoom all
- `_range_selection` stores the active time range tuple `(t0, t1)` when a range is selected
- `find_event_dialog()` is a no-op placeholder — Ctrl+F belongs to View > Fit to Data
- The main window file has `mypy: ignore-errors` due to its size and dynamic Qt patterns

---

## Tests

```bash
python -m pytest tests/ -q
```

Expected: **178 passed, 1 skipped** (the skipped test is a legacy scrollbar test).

For headless environments (CI, SSH):

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
```

---

## Linting and Type Checking

```bash
# Linting (ruff)
ruff check src/
ruff format --check src/

# Type checking (mypy)
mypy src/
```

Configuration lives in `pyproject.toml`:
- **ruff**: target Python 3.10, line length 100, double quotes, LF line endings
- **mypy**: `main_window.py` has `ignore_errors = true`; strict typing is enforced on `services/`, `storage/sqlite/`, `core/events/`, `core/traces/`, and `ui/plots/`

---

## Building

VasoAnalyzer is packaged with **PyInstaller** for distribution.

```bash
pip install pyinstaller
pyinstaller --noconfirm VasoAnalyzer.spec
```

- **Windows**: produces `dist/VasoAnalyzer/VasoAnalyzer.exe`
- **macOS**: produces `dist/VasoAnalyzer *.app`

For full installer instructions (DMG, Inno Setup, file associations), see [docs/distribution.md](docs/distribution.md).

---

## CI / CD

Two GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `tests.yml` | Push/PR to `main` | Runs pytest on Ubuntu (Python 3.11, offscreen Qt) |
| `build.yml` | Version tag (`v*.*.*`) | Builds macOS DMG (Intel + Apple Silicon) and Windows installer, creates GitHub Release |

---

## Code Style

- **Formatter**: ruff format (double quotes, 4-space indent, LF endings)
- **Line length**: 100 characters
- **Imports**: sorted by ruff (`isort` rules via `I` select)
- **Target**: Python 3.10+ syntax (`UP` rules enabled)
- Don't add docstrings, comments, or type annotations to code you didn't change
- Prefer simple, direct code over abstractions for one-off operations
