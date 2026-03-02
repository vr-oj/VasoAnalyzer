# V3.0 Dependency Map

This map is intended to support safe deprecation and hardening. It highlights allowed dependency directions and areas that must stay UI-free.

## High-level graph (Mermaid)

```mermaid
graph TD
  subgraph App
    main[src/main.py]
    launcher[src/vasoanalyzer/app/launcher.py]
    openers[src/vasoanalyzer/app/openers.py]
  end

  subgraph UI
    main_window[src/vasoanalyzer/ui/main_window.py]
    ui_mixins[src/vasoanalyzer/ui/mixins/*]
    ui_plots[src/vasoanalyzer/ui/plots/*]
    ui_gif[src/vasoanalyzer/ui/gif_animator/*]
    ui_dialogs[src/vasoanalyzer/ui/dialogs/*]
  end

  subgraph Services
    project_service[src/vasoanalyzer/services/project_service.py]
    folder_import[src/vasoanalyzer/services/folder_import_service.py]
    cache_service[src/vasoanalyzer/services/cache_service.py]
  end

  subgraph Core
    project[src/vasoanalyzer/core/project.py]
    trace_model[src/vasoanalyzer/core/trace_model.py]
    audit[src/vasoanalyzer/core/audit.py]
    events_core[src/vasoanalyzer/core/events/*]
  end

  subgraph Storage_IO
    storage[src/vasoanalyzer/storage/*]
    io_csv[src/vasoanalyzer/io/*]
  end

  subgraph Analysis
    analysis[src/vasoanalyzer/analysis/*]
  end

  subgraph Packaging
    pkg[src/vasoanalyzer/pkg/*]
  end

  subgraph Legacy
    archive[src/vasoanalyzer/ui/_archive/*]
  end

  main --> launcher
  launcher --> main_window
  openers --> main_window

  main_window --> ui_mixins
  main_window --> ui_plots
  main_window --> ui_dialogs
  main_window --> ui_gif
  main_window --> project_service
  main_window --> project
  main_window --> trace_model
  main_window --> io_csv
  main_window --> storage
  main_window --> analysis

  project_service --> project
  project_service --> storage
  project_service --> io_csv

  project --> storage
  project --> io_csv
  storage --> project
  storage --> audit
  storage --> events_core

  analysis --> project
  pkg --> project
  pkg --> storage

  archive -. not wired .- main_window
```

## Rules / constraints

- Core, storage, io, analysis MUST NOT import UI modules.
- Avoid import-time side effects in core/storage/analysis (no filesystem writes or config mutations on import).
- UI may depend on core/storage/io/analysis/services; services may depend on core/storage/io.
- Packaging (`pkg/*`) is feature-flagged and should remain isolated from UI.

## Safe removal targets once deprecated

- `src/vasoanalyzer/ui/_archive/*`
- `src/vasoanalyzer/ui/protocol_annotation_tool.py`
- Matplotlib main-view renderer toggle (UI only)

## Risky edges to watch

- `core.project` <-> `storage.*` have bidirectional imports (some are local to avoid cycles).
- `ui.main_window` is a nexus of dependencies; changes ripple across most subsystems.
