# Distribution

## Windows (PyInstaller + Inno Setup)
- Build the onedir bundle: `pyinstaller --noconfirm VasoAnalyzer.spec` (outputs `dist/VasoAnalyzer/` with `VasoAnalyzer.exe`, icons, and `VasoDocument.ico`).
- Document icon sources live in `assets/icons/`; the PyInstaller spec copies both `.ico` and `.icns` into the dist root for installer consumption.
- Create the installer with `installer/windows/build_installer.ps1` (requires `iscc` in `PATH`). Output lands in `installer/windows/output/VasoAnalyzer-Setup.exe`.
- File association: ProgID `VasoAnalyzer.Project`, default icon `{app}\VasoDocument.ico,0`, open command `"{app}\VasoAnalyzer.exe" "%1"`. The installer also adds a Start Menu shortcut and optional desktop icon.

## macOS (.app bundle)
- Build the app bundle with `pyinstaller --noconfirm VasoAnalyzer.spec` (produces `dist/VasoAnalyzer */VasoAnalyzer ... .app`).
- Document registration and icon mapping are defined in `packaging/macos/Info.plist` (`UTType com.vasoanalyzer.vaso`, `CFBundleTypeIconFile` `VasoDocument`). PyInstaller pulls `assets/icons/VasoDocument.icns` into the app's `Contents/Resources`.
- App icon comes from `src/vasoanalyzer/VasoAnalyzerIcon.icns` via the spec; document icon from `assets/icons/VasoDocument.icns`.
- Finder double-clicks surface as `FileOpen` events handled by the Qt event filter plus the single-instance IPC bridge, so projects open in the existing instance when running.

## Dataset exchange (.vasods)
- A portable dataset package (`.vasods`) is a ZIP with `manifest.json`, `data/dataset.json`, and trace/events payloads (CSV) plus optional results (`data/results.json`).
- Export uses the same read path as project saves; import feeds through `sqlite_store.add_dataset(...)` so integrity signatures and thumbnails stay consistent.
- Use `export_dataset_package(project_path, dataset_id, out_path)` to write a package and `import_dataset_package(dest_project_path, package_path, target_experiment_name=...)` to insert it into another project/experiment.
