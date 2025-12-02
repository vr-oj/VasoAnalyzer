"""
Advanced recovery utilities for VasoAnalyzer projects.

Provides tools to recover data from:
- Corrupted .vaso files (using existing 3-stage recovery)
- Corrupted .vasopack bundles (using snapshot fallback)
- Orphaned autosave files
- Manual extraction from bundle snapshots
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

__all__ = [
    "recover_project",
    "list_recovery_options",
    "extract_from_snapshot",
    "find_autosave_files",
]


# =============================================================================
# High-Level Recovery API
# =============================================================================


def recover_project(project_path: str | Path) -> tuple[bool, str, list[Path]]:
    """
    Attempt to recover a corrupted project using all available methods.

    This is the main entry point for project recovery. It automatically
    detects the project format and tries appropriate recovery strategies.

    Args:
        project_path: Path to corrupted project (.vaso or .vasopack)

    Returns:
        Tuple of (success, message, recovered_files):
        - success: True if recovery succeeded
        - message: Human-readable description of what happened
        - recovered_files: List of recovered file paths

    Example:
        >>> success, msg, files = recover_project("MyProject.vasopack")
        >>> if success:
        >>>     print(f"Recovered: {msg}")
        >>>     print(f"Files: {files}")
    """
    path = Path(project_path)

    if not path.exists():
        return False, f"Project not found: {path}", []

    # Detect format
    from vasoanalyzer.storage.migration import detect_project_format

    fmt = detect_project_format(path)

    if fmt == "bundle-v1":
        return _recover_bundle(path)
    elif fmt in ("sqlite-v1", "sqlite-v2", "sqlite-v3"):
        return _recover_legacy_vaso(path)
    else:
        return False, f"Unknown project format: {fmt}", []


def list_recovery_options(project_path: str | Path) -> dict:
    """
    List all available recovery options for a project without modifying it.

    Useful for showing users what recovery methods are available before
    they decide which one to use.

    Args:
        project_path: Path to project

    Returns:
        Dictionary with recovery options:
        {
            "format": "bundle-v1" or "sqlite-v3",
            "options": [
                {
                    "method": "snapshot_fallback",
                    "description": "Use older snapshot",
                    "available": True,
                    "snapshots": [1, 2, 3, 4, 5]
                },
                ...
            ]
        }
    """
    path = Path(project_path)
    from vasoanalyzer.storage.migration import detect_project_format

    fmt = detect_project_format(path)
    options = []

    if fmt == "bundle-v1":
        # List bundle recovery options
        from vasoanalyzer.storage.snapshots import list_snapshots, validate_snapshot

        try:
            snapshots = list_snapshots(path)
            valid_snapshots = [s for s in snapshots if validate_snapshot(s.path)]

            if valid_snapshots:
                options.append(
                    {
                        "method": "snapshot_fallback",
                        "description": f"Use older snapshot ({len(valid_snapshots)} available)",
                        "available": True,
                        "snapshots": [s.number for s in valid_snapshots],
                    }
                )

            # Check for autosave in bundle
            autosave_candidates = list((path / ".staging").glob("*.sqlite")) if (
                path / ".staging"
            ).exists() else []
            if autosave_candidates:
                options.append(
                    {
                        "method": "staging_recovery",
                        "description": f"Recover from staging DB ({len(autosave_candidates)} found)",
                        "available": True,
                        "files": [str(f) for f in autosave_candidates],
                    }
                )

        except Exception as e:
            log.error(f"Error listing bundle options: {e}")

    elif fmt in ("sqlite-v1", "sqlite-v2", "sqlite-v3"):
        # List legacy recovery options
        backup_path = path.with_suffix(path.suffix + ".bak")
        if backup_path.exists():
            options.append(
                {
                    "method": "backup_restore",
                    "description": "Restore from .bak file",
                    "available": True,
                    "file": str(backup_path),
                }
            )

        autosave_path = path.with_suffix(path.suffix + ".autosave")
        if autosave_path.exists():
            options.append(
                {
                    "method": "autosave_restore",
                    "description": "Restore from autosave",
                    "available": True,
                    "file": str(autosave_path),
                }
            )

        # 3-stage SQLite recovery always available
        options.append(
            {
                "method": "sqlite_recovery",
                "description": "3-stage SQLite recovery (CLI dump, iterdump, PRAGMA)",
                "available": True,
            }
        )

    return {"format": fmt, "options": options}


# =============================================================================
# Bundle Recovery
# =============================================================================


def _recover_bundle(bundle_path: Path) -> tuple[bool, str, list[Path]]:
    """
    Recover corrupted bundle by falling back to older snapshots.

    Strategy:
    1. Validate current snapshot
    2. If corrupted, try previous snapshots (newest first)
    3. Update HEAD to point to recovered snapshot
    """
    from vasoanalyzer.storage.snapshots import (
        get_current_snapshot,
        list_snapshots,
        validate_snapshot,
    )

    log.info(f"Attempting bundle recovery: {bundle_path}")

    try:
        # Get all snapshots
        snapshots = list_snapshots(bundle_path)

        if not snapshots:
            return False, "No snapshots found in bundle", []

        # Check current snapshot
        try:
            current = get_current_snapshot(bundle_path)
            if current and validate_snapshot(current.path):
                return (
                    True,
                    f"Current snapshot is valid (snapshot {current.number})",
                    [current.path],
                )
        except Exception as e:
            log.warning(f"Could not validate current snapshot: {e}")

        # Current is corrupted, try others (newest first)
        valid_snapshots = []
        for snapshot in reversed(snapshots):
            if validate_snapshot(snapshot.path):
                valid_snapshots.append(snapshot)

        if not valid_snapshots:
            return False, "All snapshots are corrupted", []

        # Use newest valid snapshot
        best_snapshot = valid_snapshots[0]

        # Update HEAD to point to it
        from vasoanalyzer.storage.snapshots import atomic_write_text
        import json
        import time

        head_doc = {
            "current": best_snapshot.path.name,
            "timestamp": time.time(),
            "recovered": True,
            "recovered_from": best_snapshot.number,
        }
        atomic_write_text(bundle_path / "HEAD.json", json.dumps(head_doc, indent=2))

        message = (
            f"Recovered from snapshot {best_snapshot.number} "
            f"({len(valid_snapshots)} valid snapshots found)"
        )

        return True, message, [best_snapshot.path]

    except Exception as e:
        log.error(f"Bundle recovery failed: {e}", exc_info=True)
        return False, f"Bundle recovery error: {e}", []


def _recover_legacy_vaso(vaso_path: Path) -> tuple[bool, str, list[Path]]:
    """
    Recover corrupted .vaso file using existing 3-stage recovery.

    Tries in order:
    1. .bak file (if exists)
    2. .autosave file (if exists)
    3. 3-stage SQLite recovery (CLI dump, iterdump, PRAGMA)
    """
    log.info(f"Attempting legacy .vaso recovery: {vaso_path}")

    recovered_files = []

    # Method 1: Try .bak file
    backup_path = vaso_path.with_suffix(vaso_path.suffix + ".bak")
    if backup_path.exists():
        try:
            if _validate_sqlite_file(backup_path):
                shutil.copy2(backup_path, vaso_path)
                log.info(f"Restored from .bak file: {backup_path}")
                return True, f"Recovered from backup: {backup_path.name}", [backup_path]
        except Exception as e:
            log.warning(f"Could not restore from .bak: {e}")

    # Method 2: Try .autosave file
    autosave_path = vaso_path.with_suffix(vaso_path.suffix + ".autosave")
    if autosave_path.exists():
        try:
            if _validate_sqlite_file(autosave_path):
                shutil.copy2(autosave_path, vaso_path)
                log.info(f"Restored from autosave: {autosave_path}")
                return (
                    True,
                    f"Recovered from autosave: {autosave_path.name}",
                    [autosave_path],
                )
        except Exception as e:
            log.warning(f"Could not restore from autosave: {e}")

    # Method 3: Use existing 3-stage recovery
    try:
        from vasoanalyzer.core.project import _attempt_database_recovery

        success = _attempt_database_recovery(str(vaso_path))

        if success:
            # Check what backup was created
            backup_created = vaso_path.with_suffix(vaso_path.suffix + ".backup")
            if backup_created.exists():
                recovered_files.append(backup_created)

            return True, "Recovered using 3-stage SQLite recovery", recovered_files
        else:
            return False, "All recovery methods failed", []

    except Exception as e:
        log.error(f"3-stage recovery failed: {e}", exc_info=True)
        return False, f"Recovery error: {e}", []


# =============================================================================
# Manual Extraction
# =============================================================================


def extract_from_snapshot(
    bundle_path: str | Path, snapshot_number: int, output_path: str | Path
) -> bool:
    """
    Extract a specific snapshot from a bundle as a standalone .vaso file.

    Useful for:
    - Manually inspecting old snapshots
    - Creating backups of specific states
    - Exporting snapshot for analysis

    Args:
        bundle_path: Path to .vasopack bundle
        snapshot_number: Snapshot number to extract (e.g., 42 for 000042.sqlite)
        output_path: Where to save extracted .vaso file

    Returns:
        True if extraction succeeded

    Example:
        >>> extract_from_snapshot("MyProject.vasopack", 35, "recovered.vaso")
        True
    """
    bundle_path = Path(bundle_path)
    output_path = Path(output_path)

    snapshot_path = bundle_path / "snapshots" / f"{snapshot_number:06d}.sqlite"

    if not snapshot_path.exists():
        log.error(f"Snapshot {snapshot_number} not found")
        return False

    try:
        # Copy snapshot to output
        shutil.copy2(snapshot_path, output_path)
        log.info(f"Extracted snapshot {snapshot_number} to {output_path}")
        return True

    except Exception as e:
        log.error(f"Extraction failed: {e}")
        return False


def find_autosave_files(directory: str | Path) -> list[Path]:
    """
    Find all autosave files in a directory tree.

    Searches for:
    - .vaso.autosave files (legacy)
    - .staging/*.sqlite files (bundle format)

    Args:
        directory: Directory to search

    Returns:
        List of paths to autosave files

    Example:
        >>> autosaves = find_autosave_files("/Users/me/Projects")
        >>> for autosave in autosaves:
        >>>     print(autosave)
    """
    directory = Path(directory)
    autosaves = []

    # Find legacy autosaves
    for autosave in directory.rglob("*.autosave"):
        if autosave.is_file():
            autosaves.append(autosave)

    # Find bundle staging DBs
    for staging in directory.rglob(".staging/*.sqlite"):
        if staging.is_file():
            autosaves.append(staging)

    return sorted(autosaves)


# =============================================================================
# Utilities
# =============================================================================


def _validate_sqlite_file(path: Path) -> bool:
    """Check if SQLite file is valid and not corrupted."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        (status,) = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
        return status == "ok"
    except Exception:
        return False
