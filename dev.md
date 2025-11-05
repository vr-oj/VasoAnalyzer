### 2025-11-04 — Project File System Overhaul

**Change summary**
- Landed `.vaso Package v1` MVP with functional create/open/save, dataset/event authoring, blob packing, link-map relinking, and catalog index persistence.
- Added JSON Schemas + Pydantic models for manifest, datasets, and events while updating to Pydantic v2 idioms.
- Shipped CLI (`vaso ...`) for quick project creation, dataset/event injection, blob packing, verification, and exercised round-trip/pack/relink smoke tests.
- Introduced sidecar exporter that mirrors GUI saves into `.pkg.vaso` packages behind the `pkg_save` feature flag.

**Rationale**
Replace the SQLite-centric project format with a single durable package that is shareable, auditable, and schema-driven.

**Next steps**
- Replace append-in-zip rewrites with atomic entry replacement to drop duplicate-name warnings.
- Move GUI/project loading onto `VasoPackage` and expand dataset serialization (Parquet defaults, ROI metadata, figures).
- Build full relink UI + checksum scanner and legacy migration workflow.
