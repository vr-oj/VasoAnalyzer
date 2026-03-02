from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "tests", "docs")
TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".pyi",
    ".qss",
    ".rst",
    ".svg",
    ".toml",
    ".tsv",
    ".txt",
    ".ui",
    ".yaml",
    ".yml",
}

# Keep the list explicit; add terms here as policy evolves.
BANNED_TERMS = ("vasotracker",)

# Legacy compatibility/import docs that still contain the term.
ALLOWED_BY_TERM = {
    "vasotracker": {
        "docs/v3_audit/v3_keep_map.md",
        "docs/vasotracker_import.md",
        "src/vasoanalyzer/core/project.py",
        "src/vasoanalyzer/io/events.py",
        "src/vasoanalyzer/io/importers/__init__.py",
        "src/vasoanalyzer/io/importers/vasotracker_normalize.py",
        "src/vasoanalyzer/io/importers/vasotracker_v1_importer.py",
        "src/vasoanalyzer/io/importers/vasotracker_v2_contract.py",
        "src/vasoanalyzer/io/importers/vasotracker_v2_importer.py",
        "src/vasoanalyzer/io/trace_events.py",
        "src/vasoanalyzer/services/folder_import_service.py",
        "src/vasoanalyzer/storage/sqlite/events.py",
        "src/vasoanalyzer/storage/sqlite/projects.py",
        "src/vasoanalyzer/storage/sqlite/traces.py",
        "src/vasoanalyzer/ui/dialogs/welcome_dialog.py",
        "src/vasoanalyzer/ui/main_window.py",
        "src/vasoanalyzer/ui/tiff_viewer_v2/page_time_map.py",
        "tests/test_vasotracker_importers.py",
        "tests/verify_data_relationships.py",
    }
}


def _iter_text_files():
    for directory in SCAN_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            # Skip generated package metadata directories (e.g. *.egg-info)
            if any(part.endswith(".egg-info") for part in path.parts):
                continue
            yield path


def test_no_banned_terms() -> None:
    offenders: list[str] = []
    for term in BANNED_TERMS:
        pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
        allowed = set(ALLOWED_BY_TERM.get(term, set()))
        for path in _iter_text_files():
            rel = path.relative_to(ROOT).as_posix()
            if rel == "tests/test_no_banned_terms.py":
                continue
            if rel in allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(f"{rel}: {term}")
    assert not offenders, "Banned terms found:\n" + "\n".join(sorted(offenders))
