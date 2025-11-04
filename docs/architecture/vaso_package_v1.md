## VasoAnalyzer “.vaso Package v1” Architecture

### Overview
VasoAnalyzer is migrating from the SQLite-project container to a portable, schema-driven package called `.vaso Package v1`. The goal is to let researchers capture every aspect of an experiment in a single distributable file that can reopen identically on any machine without bespoke tooling.

Key goals:
- Collapse the legacy folder/SQLite layout into one ZIP-based `.vaso` file.
- Preserve datasets, events, UI layouts, analysis DAGs, and exports.
- Support both referenced assets (default) and embedded “pack” mode for large binaries.
- Keep the format human-readable, versioned, auditable, and forward compatible.

### Package Layout
The `.vaso` file is a ZIP container with a deterministic directory tree:

```
/manifest.json                  # root metadata, schema + semver, package id
/README.md, /LICENSE.txt, /CITATION.cff
/catalog.sqlite                 # catalog/index of datasets + blobs
/audit/log.jsonl                # append-only audit trail
/project/project.json           # project metadata + timezone
/project/tags.json
/datasets/<uuid>/               # one directory per dataset
  dataset.json
  timebase.json
  channels.parquet
  rois.json
  qc.json
  refs.json                     # external URIs and checksums
  blobs/<sha256>                # embedded binaries when “pack” mode is used
/events/events.jsonl            # semantic event stream
/views/<name>.yaml              # default + named view configurations
/analysis/graph.json            # operation DAG
/analysis/results/*.parquet     # persisted outputs (CSV mirrors optional)
/analysis/caches/               # transient intermediates (safe to delete)
/figures/<slug>/                # figure JSON + SVG/PNG renderings
/exports/...                    # exported reports/tables
/links/linkmap.json             # path remapping cache
/env/environment.lock           # resolved dependency versions
```

All JSON/YAML documents include a `$schema` URI and `version` field. Tables persist as Parquet with optional CSV companions. Embedded binary blobs are stored under `datasets/.../blobs/<sha256>` using ZIP_STORED to avoid recompressing TIFFs.

### Storage Modes
**Referenced (default):** `refs.json` records absolute + relative paths plus SHA-256 checksums. When reopening, the application searches in priority order:
1. Exact recorded path.
2. Sibling directory relative to the `.vaso` file.
3. Previously resolved aliases in `links/linkmap.json`.
4. SHA-256 scan below a user-provided root.

Successful resolutions update the link map for future sessions.

**Embedded (“Pack”):** Large files are copied into `datasets/.../blobs/<sha256>` and `refs.json` switches URIs to `vaso://blobs/<sha256>`. Duplicate blobs deduplicate automatically because the path is keyed by the digest.

### Core Modules (`src/vasoanalyzer/pkg/`)
- `package.py`: `VasoPackage` façade implementing `create/open/save/pack/unpack/relink/verify`.
- `catalog.py`: catalog utilities (dataset registry, blob index, link tracking).
- `models.py`: Pydantic models bound to JSON Schemas (manifest, datasets, events, views).
- `paths.py`: helper constants and typed wrappers for package-relative paths.
- `blobs.py`: blob hashing, deduplication, streaming IO helpers.
- `io_zip.py`: low-level ZIP read/write helpers with atomic `.tmp → rename` commits.
- `migrate.py`: schema migration hooks plus legacy converter entry points.

### Reliability & Audit
- Atomic saves through temporary files and rename.
- Lock file to prevent concurrent writes.
- Rolling backups (`.vaso~1`, `.vaso~2`).
- Append-only `/audit/log.jsonl` capturing action, timestamp (UTC ISO-8601), app version, git commit, and platform.
- Verification routine checks checksums, schema compatibility, and embedded blob integrity.

### CLI & GUI Integration
Expose new commands (`vaso new/open/pack/unpack/relink/verify/migrate`) via `vasoanalyzer/__main__.py` or a dedicated CLI module. The Qt GUI receives menu entries for saving `.vaso`, saving as, embedding data, and relinking missing files. Both surfaces share the `VasoPackage` implementation.

### Testing Focus
- Round-trip save/open parity.
- Pack/unpack idempotency (checksum stable).
- Referenced asset relinking across platforms (Windows vs POSIX paths).
- Schema validation errors produce actionable messages.
- Migration tests (legacy project → `.vaso Package v1`).

### Deliverables Snapshot
- `src/vasoanalyzer/pkg/` scaffolding (core module set above).
- `schemas/vaso-package-v1/` JSON Schemas checked in and bundled for PyInstaller.
- `tests/test_pkg_*.py` covering new behaviors.
- `scripts/migrate_to_v1.py` for bulk conversion.
- README + developer log updates describing the new format.

This document should guide incremental implementation while keeping compatibility with existing releases. Start by scaffolding the package module, codifying schemas, and wiring tests before swapping the GUI/service layer to the new backend.

