"""
Migration utilities for converting legacy .vaso files to bundle format.

Handles automatic migration from single-file SQLite databases to the new
append-only snapshot bundle format (.vasopack).
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path

from .snapshots import (
    atomic_write_text,
    create_bundle,
    fsync_file,
)

log = logging.getLogger(__name__)

__all__ = [
    "is_legacy_project",
    "migrate_to_bundle",
    "detect_project_format",
]


# =============================================================================
# Format Detection
# =============================================================================


def detect_project_format(path: Path) -> str:
    """
    Detect project file format.

    Args:
        path: Path to project file or bundle

    Returns:
        Format string: "zip-bundle-v1", "bundle-v1", "sqlite-v3", "sqlite-v2",
        "sqlite-v1", or "unknown"
    """
    if not path.exists():
        return "unknown"

    # Check if ZIP container (new single-file format)
    if path.is_file() and path.suffix == ".vaso":
        from .container_fs import is_vaso_container

        if is_vaso_container(path):
            return "zip-bundle-v1"

    # Check if bundle
    if path.is_dir():
        if (path / "HEAD.json").exists() and (path / "snapshots").exists():
            return "bundle-v1"
        return "unknown"

    # Check if SQLite file
    if path.is_file():
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
                # Check schema version
                (version,) = conn.execute("PRAGMA user_version").fetchone()

                # Check for meta table (v3 feature)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
                )
                has_meta = cursor.fetchone() is not None

                if has_meta:
                    # Try to get format from meta table
                    try:
                        cursor = conn.execute("SELECT value FROM meta WHERE key='format'")
                        row = cursor.fetchone()
                        if row:
                            fmt = row[0]
                            if fmt == "sqlite-v3":
                                return "sqlite-v3"
                    except Exception:
                        pass

                # Fallback to user_version
                version_map = {3: "sqlite-v3", 2: "sqlite-v2", 1: "sqlite-v1"}
                return version_map.get(version, "unknown")

        except Exception as e:
            log.debug(f"Could not detect format for {path}: {e}")
            return "unknown"

    return "unknown"


def is_legacy_project(path: Path) -> bool:
    """
    Check if path is a legacy single-file project.

    Args:
        path: Path to check

    Returns:
        True if legacy format, False if bundle or unknown
    """
    fmt = detect_project_format(path)
    return fmt in ("sqlite-v1", "sqlite-v2", "sqlite-v3")


# =============================================================================
# Migration
# =============================================================================


def migrate_to_bundle(
    legacy_path: Path,
    *,
    bundle_path: Path | None = None,
    keep_legacy: bool = True,
    validate: bool = True,
) -> Path:
    """
    Migrate legacy .vaso file to bundle format.

    Creates a new .vasopack bundle with the legacy database as the first snapshot.
    Preserves all data, metadata, and timestamps.

    Args:
        legacy_path: Path to legacy .vaso file
        bundle_path: Path for new bundle (default: legacy_path.vasopack)
        keep_legacy: If True, rename legacy file to .vaso.legacy (default: True)
        validate: If True, validate legacy DB before migration (default: True)

    Returns:
        Path to new bundle directory

    Raises:
        FileNotFoundError: If legacy file doesn't exist
        ValueError: If legacy file is invalid or corrupted
        FileExistsError: If bundle already exists
    """
    if not legacy_path.exists():
        raise FileNotFoundError(f"Legacy project not found: {legacy_path}")

    if not legacy_path.is_file():
        raise ValueError(f"Legacy project path is not a file: {legacy_path}")

    # Detect format
    fmt = detect_project_format(legacy_path)
    if not is_legacy_project(legacy_path):
        raise ValueError(f"Not a legacy project (format: {fmt}): {legacy_path}")

    log.info(f"Migrating legacy project ({fmt}): {legacy_path}")

    # Determine bundle path
    if bundle_path is None:
        bundle_path = legacy_path.with_suffix(".vasopack")

    if bundle_path.exists():
        raise FileExistsError(f"Bundle already exists: {bundle_path}")

    # Validate legacy database if requested
    if validate:
        log.debug("Validating legacy database")
        try:
            with sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True, timeout=10) as conn:
                (status,) = conn.execute("PRAGMA integrity_check").fetchone()
                if status != "ok":
                    raise ValueError(f"Legacy database failed integrity check: {status}")
        except sqlite3.Error as e:
            raise ValueError(f"Legacy database validation failed: {e}") from e

    # Read legacy metadata
    legacy_meta = _read_legacy_metadata(legacy_path)

    # Create bundle structure
    log.debug(f"Creating bundle at {bundle_path}")
    create_bundle(bundle_path)

    # Copy legacy database as first snapshot
    snapshot_path = bundle_path / "snapshots" / "000001.sqlite"
    log.debug(f"Copying legacy database to {snapshot_path}")
    shutil.copy2(legacy_path, snapshot_path)

    # Ensure snapshot is readable
    snapshot_path.chmod(0o644)

    # Fsync snapshot
    fsync_file(snapshot_path)

    # Update HEAD to point to first snapshot
    head_doc = {
        "current": "000001.sqlite",
        "timestamp": time.time(),
    }
    atomic_write_text(bundle_path / "HEAD.json", json.dumps(head_doc, indent=2))

    # Create project metadata
    project_meta = {
        "format": "bundle-v1",
        "created_at": time.time(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "migrated_from": str(legacy_path),
        "migrated_from_format": fmt,
        "migrated_at": time.time(),
        "migrated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "original_created_at": legacy_meta.get("created_at"),
        "original_modified_at": legacy_meta.get("modified_at"),
    }
    atomic_write_text(bundle_path / "project.meta.json", json.dumps(project_meta, indent=2))

    # Handle legacy file
    if keep_legacy:
        legacy_backup = legacy_path.with_suffix(legacy_path.suffix + ".legacy")
        log.info(f"Renaming legacy file to {legacy_backup}")
        legacy_path.rename(legacy_backup)
    else:
        log.info("Removing legacy file")
        legacy_path.unlink()

    log.info(f"Migration completed successfully: {bundle_path}")
    return bundle_path


def _read_legacy_metadata(legacy_path: Path) -> dict:
    """
    Read metadata from legacy database.

    Args:
        legacy_path: Path to legacy .vaso file

    Returns:
        Dictionary of metadata key-value pairs
    """
    meta = {}

    try:
        with sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True, timeout=5) as conn:
            # Check if meta table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            )
            if cursor.fetchone():
                # Read all meta entries
                cursor = conn.execute("SELECT key, value FROM meta")
                for key, value in cursor:
                    meta[key] = value

            # Get file timestamps as fallback
            stat = legacy_path.stat()
            if "created_at" not in meta:
                meta["created_at"] = stat.st_ctime
            if "modified_at" not in meta:
                meta["modified_at"] = stat.st_mtime

    except Exception as e:
        log.warning(f"Could not read legacy metadata: {e}")

    return meta


# =============================================================================
# Automatic Migration on Open
# =============================================================================


def auto_migrate_if_needed(path: Path, *, keep_legacy: bool = True) -> tuple[Path, bool]:
    """
    Automatically migrate legacy project if needed.

    If path is a legacy .vaso file, migrates to bundle and returns bundle path.
    If path is already a bundle or .vasopack exists, returns as-is.

    Args:
        path: Path to project (legacy or bundle)
        keep_legacy: If migrating, keep legacy file as .vaso.legacy

    Returns:
        Tuple of (final_path, was_migrated)
    """
    # Check if already a bundle
    if path.is_dir():
        fmt = detect_project_format(path)
        if fmt == "bundle-v1":
            return path, False

    # Check if it's already a ZIP container (new format)
    fmt = detect_project_format(path)
    if fmt == "zip-bundle-v1":
        # Already in container format, no migration needed
        return path, False

    # Check if bundle already exists
    bundle_path = path.with_suffix(".vasopack")
    if bundle_path.exists():
        log.info(f"Found existing bundle: {bundle_path}")
        return bundle_path, False

    # Check if legacy format
    if is_legacy_project(path):
        log.info(f"Legacy project detected, migrating to bundle format: {path}")
        try:
            bundle_path = migrate_to_bundle(path, keep_legacy=keep_legacy)
            return bundle_path, True
        except Exception as e:
            log.error(f"Migration failed: {e}")
            # Fall back to opening legacy file
            log.warning("Migration failed, falling back to legacy format")
            return path, False

    # Unknown format or not a project
    return path, False


# =============================================================================
# Rollback / Export to Legacy
# =============================================================================


def export_to_legacy(bundle_path: Path, output_path: Path | None = None) -> Path:
    """
    Export current bundle snapshot to legacy single-file format.

    Useful for:
    - Sharing with users on older VasoAnalyzer versions
    - Creating portable single-file backups
    - Rollback to legacy format if needed

    Args:
        bundle_path: Path to bundle directory
        output_path: Output path for .vaso file (default: bundle_path.vaso)

    Returns:
        Path to exported .vaso file

    Raises:
        FileNotFoundError: If bundle doesn't exist
        ValueError: If bundle has no snapshots
    """
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    if output_path is None:
        output_path = bundle_path.with_suffix(".vaso")

    # Get current snapshot
    from .snapshots import get_current_snapshot

    snapshot_info = get_current_snapshot(bundle_path)
    if snapshot_info is None:
        raise ValueError(f"Bundle has no snapshots: {bundle_path}")

    log.info(f"Exporting snapshot {snapshot_info.number} to legacy format: {output_path}")

    # Copy snapshot to output
    shutil.copy2(snapshot_info.path, output_path)

    # Update metadata to indicate it's an export
    try:
        with sqlite3.connect(output_path, timeout=10) as conn:
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'exported_from'",
                (str(bundle_path),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("exported_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            conn.commit()
    except Exception as e:
        log.warning(f"Could not update export metadata: {e}")

    log.info(f"Export completed: {output_path}")
    return output_path
