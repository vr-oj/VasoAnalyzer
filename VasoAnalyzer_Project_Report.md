# VasoAnalyzer — Project Technical Report
_Generated: 2025-11-04 16:39_

**Detected package:** `vasoanalyzer`  •  **App version:** `2.2`  


## 1) Repository Layout (Top Level)
```
CITATION.cff
LICENSE
LICENSES
NOTICE
README.md
VasoAnalyzer.spec
__MACOSX
dev.md
docs
horizontal_outside.png
icons
packaging
pyproject.toml
requirements.txt
resources
schemas
scripts
src
style.qss
test_project.vaso
test_project.vaso.bak
test_project2.vaso
test_project2.vaso.bak
tests
tmp_cli_project.vaso
tmp_cli_project.vaso.bak
tmp_cli_project.vaso.cache
tmp_trace.csv
vertical_inside.png
```
## 2) Key Entry Points
- src/main.py (desktop app)
- CLI: vaso (from pyproject.toml -> vasoanalyzer.cli:main)

## 3) Python Package Structure & Size
- Total Python LOC under `src/vasoanalyzer`: **31,204**
  - UI: **22,168**  •  Core: **3,525**  •  Storage: **2,010**  •  IO: **1,084**  •  Services: **982**  •  Package (`.vaso` ZIP): **776**

## 4) `.vaso` Format (ZIP-based) vs Legacy (SQLite)
- **ZIP-based package (new):** implemented in `vasoanalyzer/pkg/*`. Includes `manifest.json`, `project/project.json`, `events/events.jsonl`, `datasets/<id>/*`, `catalog.sqlite`, and optional embedded `blobs/` with SHA256 names. JSON Schemas in `schemas/vaso-package-v1/`.
- **Legacy SQLite (current samples):** the bundled sample files appear to start with `b'SQLite format 3\x00'`, indicating the original SQLite container. See `vasoanalyzer/storage/sqlite_*` for readers/writers.
  - Sample project files:
    - test_project.vaso — magic: b'SQLite format 3\x00'
    - test_project2.vaso — magic: b'SQLite format 3\x00'
    - tmp_cli_project.vaso — magic: b'SQLite format 3\x00'

## 5) CLI Surface
Declared in `pyproject.toml -> [project.scripts] vaso = 'vasoanalyzer.cli:main'`. Subcommands discovered:
```
- new
- add-dataset
- add-event
- pack
- verify
```

## 6) Desktop App Boot Path
- `src/main.py` ➜ `vasoanalyzer.app.launcher.VasoAnalyzerLauncher` ➜ `vasoanalyzer.ui.main_window.VasoAnalyzerApp`.
- HiDPI on by default, Fusion style + custom palette, splash screen, platform icons (ICNS/ICO/SVG).
- Update checker via `vasoanalyzer.services.version`.

## 7) Data Flow (High Level)
- **Trace CSV** ➜ `vasoanalyzer.io.traces.load_trace` (delimiter sniffing, column normalization).
- **Event CSV/TXT** ➜ `vasoanalyzer.io.events.load_events` (Time/Label/Lane mapping).
- **TIFF** ➜ `vasoanalyzer.services.project_service._load_tiff_stack` (memmap for large, optional compression).
- **Project model** ➜ `vasoanalyzer.core.project` (Project/Experiment/SampleN; autosave; export).
- **Packaging** ➜ `vasoanalyzer.pkg.exporter.export_project_to_package` (Project ➜ `.vaso` ZIP).

## 8) Tests Overview
- **api** (1):
  - `tests/api/test_public_imports.py`
- **events** (2):
  - `tests/events/test_cluster.py`
  - `tests/events/test_cluster_edges.py`
- **plots** (2):
  - `tests/plots/test_event_labels_v2.py`
  - `tests/plots/test_golden.py`
- **services** (1):
  - `tests/services/test_project_repository.py`
- **smoke** (1):
  - `tests/smoke/test_app_launch.py`
- **storage** (7):
  - `tests/storage/test_sqlite_assets.py`
  - `tests/storage/test_sqlite_conversion.py`
  - `tests/storage/test_sqlite_events.py`
  - `tests/storage/test_sqlite_projects.py`
  - `tests/storage/test_sqlite_save_pipeline.py`
  - `tests/storage/test_sqlite_traces.py`
  - `tests/storage/test_sqlite_utils_txn.py`
- **test_pkg_mvp.py** (1):
  - `tests/test_pkg_mvp.py`
- **test_single_file_export.py** (1):
  - `tests/test_single_file_export.py`
- **traces** (1):
  - `tests/traces/test_checksum.py`
- **ui** (2):
  - `tests/ui/test_event_labels_no_doubleconnect.py`
  - `tests/ui/test_settings_dialog_smoke.py`

Key highlights: PyQt5 offscreen smoke (`tests/smoke/test_app_launch.py`), event-label wiring (`tests/ui/test_event_labels_no_doubleconnect.py`), SQLite store (create/open/convert/save), package MVP roundtrip, and checksum utilities.

## 9) Schemas
Shipped JSON Schemas:
```
dataset.schema.json
event.schema.json
manifest.schema.json
```

## 10) Packaging (PyInstaller)
- Root `VasoAnalyzer.spec` builds the desktop app; collects platform icons, toolbar SVGs, and Qt platform plugins; supplies Info.plist for macOS; includes `requests` and `openpyxl` submodules.

## 11) Notable Strengths
- Clear separation between **core**, **IO**, **storage**, **UI**, and **package** layers.
- Realistic test suite covering UI smoke, event labeling, SQLite store ops, and package export.
- ZIP `.vaso` architecture is well specified; linkmap for path repair; embedded blob strategy with SHA256 for deterministic dedup.
- Sensible defaults: HiDPI, Fusion theme, palette, offscreen test fixture, CSV delimiter sniffing, TIFF memmap threshold, autosave pipeline.

## 12) Improvements & Recommendations
- **Update checker:** Use the GitHub API endpoint `https://api.github.com/repos/vr-oj/VasoAnalyzer/releases/latest` instead of the HTML releases page, and handle errors. Cache etag; fallback gracefully when offline.
- **Continuous Integration:** Add a GitHub Actions workflow to run Ruff, mypy, and pytest (with `QT_QPA_PLATFORM=offscreen` and `MPLBACKEND=Agg`) on Ubuntu/macOS/Windows. Cache pip; upload artifacts on failure.
- **Pre-commit hooks:** Add `.pre-commit-config.yaml` (ruff, ruff-format/black, end-of-file-fixer, trailing-whitespace, check-yaml, check-merge-conflict).
- **Type coverage:** UI has some `type: ignore` and one `# mypy: ignore-errors`. Gradually type the `ui.*` layer using `typing.cast` and precise signal/slot annotations (`pyqtSignal[Type]`).
- **Exception hygiene:** Found ~142 occurrences of `except Exception`. Narrow where possible (e.g., `ValueError`, `IOError`), and always log context with `exc_info=True`.
- **File format clarity:** Samples are SQLite `.vaso` while the new `.vaso` is ZIP. Consider using different extensions (`.vaso` vs `.vaso.zip`) or a manifest-first magic (`manifest.json`) to avoid ambiguity; add automatic migration on open when SQLite magic is detected.
- **CLI polish:** Add `vaso list`, `vaso show <dataset-id>`, `vaso unpack --to DIR`, and `vaso validate` to run schema checks against `schemas/vaso-package-v1/*`. Enforce `role` choices for `pack` (e.g., `trace`, `tiff`, `events`, `snapshot`).
- **Docs:** Link the `WELCOME_TOUR.md` and `USER_MANUAL.md` from the README; add a short GIF of the workflow; include a minimal CSV/Events sample in `docs/samples/` and reference it in the Quick Start.
- **Performance:** For very large traces, consider optional on-disk chunked stores (parquet/feather) and downsampled preview via Level-of-Detail (already present in `core.lod` — expose it more broadly).
- **Reproducible builds:** Pin wheels in `requirements.txt` or move deps to `pyproject.toml` entirely; document code signing / notarization steps for macOS; include an automated `pyinstaller` step in CI for tagged releases.
- **Event labels polish:** Ensure event overlays draw on a dedicated Matplotlib artist layer with high `zorder`, collision‑avoid text layout, and consistent font scaling; add a toggle to keep labels above dashed separators and avoid clipping in exports.

## 13) Quick Sanity Checklist (Dev)
- `python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
- `pytest -q`  (offscreen fixtures are set in `tests/conftest.py`)
- `python -m vasoanalyzer.cli --help` and exercise `new/add-dataset/add-event/pack/verify`.
- `pyinstaller -y VasoAnalyzer.spec` and launch the app headless to verify resource loading.
