"""
Adapter for integrating snapshot-based bundle format with existing VasoAnalyzer code.

This module provides a transparent interface that works with both:
- Legacy single-file .vaso projects (backward compatibility)
- New bundle format .vasopack projects (cloud-safe, snapshot-based)

The adapter automatically handles:
- Format detection
- Auto-migration from legacy to bundle
- Staging database management for active sessions
- Snapshot creation on save
- Recovery from crashes and corruption
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .migration import auto_migrate_if_needed, detect_project_format, is_legacy_project
from .snapshots import (
    BundleInfo,
    cleanup_staging_dbs,
    create_bundle,
    create_snapshot,
    get_current_snapshot,
    open_bundle,
    open_staging_db,
    prune_old_snapshots,
    release_lock,
)

log = logging.getLogger(__name__)

__all__ = [
    "ProjectHandle",
    "open_project_handle",
    "create_project_handle",
    "save_project_handle",
    "close_project_handle",
]


# =============================================================================
# Project Handle
# =============================================================================


@dataclass
class ProjectHandle:
    """
    Handle to an open project (bundle or legacy).

    Manages staging database for bundle projects and provides unified interface
    for both legacy and bundle formats.

    Attributes:
        path: Path to project (bundle dir or legacy file)
        format: Project format ("bundle-v1" or "sqlite-v3", etc.)
        is_bundle: True if bundle format
        readonly: True if opened read-only
        bundle_info: BundleInfo if bundle format
        staging_path: Path to staging database (bundle only)
        staging_conn: Connection to staging database
        snapshot_on_save: If True, create snapshot on each save
    """

    path: Path
    format: str
    is_bundle: bool
    readonly: bool
    bundle_info: BundleInfo | None
    staging_path: Path | None
    staging_conn: sqlite3.Connection | None
    snapshot_on_save: bool = True

    def __post_init__(self):
        # Register cleanup on process exit
        weakref.finalize(self, _cleanup_handle, self.path, self.staging_path)


# Global registry of open handles for cleanup
_open_handles: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


def _cleanup_handle(bundle_path: Path, staging_path: Path | None):
    """Cleanup function called on handle destruction or process exit."""
    try:
        if staging_path and staging_path.exists():
            log.debug(f"Cleaning up staging database: {staging_path}")
            # Close any open connections (best effort)
            try:
                # The connection should already be closed, but just in case
                pass
            except Exception:
                pass

        # Release lock on bundle
        if bundle_path and bundle_path.is_dir():
            release_lock(bundle_path)

    except Exception as e:
        log.warning(f"Error during handle cleanup: {e}")


@atexit.register
def _cleanup_all_handles():
    """Cleanup all open handles on process exit."""
    for handle in list(_open_handles.values()):
        try:
            close_project_handle(handle)
        except Exception as e:
            log.warning(f"Error closing handle during shutdown: {e}")


# =============================================================================
# Open / Create Project
# =============================================================================


def open_project_handle(
    path: str | Path,
    *,
    readonly: bool = False,
    auto_migrate: bool = True,
    create_if_missing: bool = False,
) -> tuple[ProjectHandle, sqlite3.Connection]:
    """
    Open a project and return handle + database connection.

    Automatically handles:
    - Format detection (legacy .vaso or bundle .vasopack)
    - Migration from legacy to bundle (if auto_migrate=True)
    - Staging database creation for bundles
    - Lock acquisition for write access
    - Recovery from corrupted snapshots

    Args:
        path: Path to project file or bundle
        readonly: If True, open read-only (no staging DB, no lock)
        auto_migrate: If True, auto-migrate legacy projects to bundle
        create_if_missing: If True, create new project if doesn't exist

    Returns:
        Tuple of (ProjectHandle, sqlite3.Connection)
        - For bundles: connection is to staging database
        - For legacy: connection is direct to .vaso file

    Raises:
        FileNotFoundError: If project doesn't exist and create_if_missing=False
        ValueError: If project format is invalid or corrupted
    """
    path = Path(path)

    # Handle creation
    if not path.exists():
        if create_if_missing:
            log.info(f"Creating new project: {path}")
            return create_project_handle(path)
        else:
            raise FileNotFoundError(f"Project not found: {path}")

    # Auto-migrate if needed
    was_migrated = False
    if auto_migrate:
        path, was_migrated = auto_migrate_if_needed(path, keep_legacy=True)
        if was_migrated:
            log.info(f"Project auto-migrated to bundle format: {path}")

    # Detect format
    fmt = detect_project_format(path)
    is_bundle = fmt == "bundle-v1"

    log.info(f"Opening project ({fmt}): {path}")

    if is_bundle:
        return _open_bundle_handle(path, readonly=readonly)
    else:
        return _open_legacy_handle(path, readonly=readonly, fmt=fmt)


def create_project_handle(
    path: str | Path,
    *,
    use_bundle_format: bool = True,
) -> tuple[ProjectHandle, sqlite3.Connection]:
    """
    Create a new project.

    Args:
        path: Path for new project
        use_bundle_format: If True, create bundle; if False, create legacy file

    Returns:
        Tuple of (ProjectHandle, sqlite3.Connection)

    Raises:
        FileExistsError: If project already exists
    """
    path = Path(path)

    if path.exists():
        raise FileExistsError(f"Project already exists: {path}")

    log.info(f"Creating new project ({'bundle' if use_bundle_format else 'legacy'}): {path}")

    if use_bundle_format:
        # Ensure path has .vasopack extension
        if path.suffix != ".vasopack":
            path = path.with_suffix(".vasopack")

        # Create bundle
        create_bundle(path)

        # Open the bundle (will create staging DB)
        return _open_bundle_handle(path, readonly=False)
    else:
        # Create legacy single-file project
        # Ensure path has .vaso extension
        if path.suffix != ".vaso":
            path = path.with_suffix(".vaso")

        # Create empty database
        conn = sqlite3.connect(path, timeout=30.0)

        # Initialize schema (this is normally done by the ProjectRepository)
        from ..storage.sqlite import projects as _projects

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _projects.ensure_schema(conn, schema_version=3, now=now)

        handle = ProjectHandle(
            path=path,
            format="sqlite-v3",
            is_bundle=False,
            readonly=False,
            bundle_info=None,
            staging_path=None,
            staging_conn=conn,
            snapshot_on_save=False,
        )

        _open_handles[id(handle)] = handle
        return handle, conn


def _open_bundle_handle(
    bundle_path: Path, *, readonly: bool = False
) -> tuple[ProjectHandle, sqlite3.Connection]:
    """Open bundle project and create staging database."""

    # Open bundle (validates structure, acquires lock)
    bundle_info = open_bundle(bundle_path, readonly=readonly)

    # Clean up any orphaned staging databases
    cleanup_staging_dbs(bundle_path)

    # Get current snapshot
    current_snapshot = get_current_snapshot(bundle_path)

    if readonly:
        # Read-only mode: open snapshot directly
        if current_snapshot is None:
            raise ValueError(f"Bundle has no snapshots: {bundle_path}")

        conn = sqlite3.connect(f"file:{current_snapshot.path}?mode=ro", uri=True, timeout=10.0)

        handle = ProjectHandle(
            path=bundle_path,
            format="bundle-v1",
            is_bundle=True,
            readonly=True,
            bundle_info=bundle_info,
            staging_path=None,
            staging_conn=conn,
            snapshot_on_save=False,
        )

    else:
        # Write mode: create staging database from current snapshot (or empty if new)
        init_from = current_snapshot.path if current_snapshot is not None else None
        staging_path, staging_conn = open_staging_db(bundle_path, initialize_from=init_from)

        # If this is a brand new bundle (no snapshots), initialize the schema
        if current_snapshot is None:
            log.info(f"Initializing schema for new bundle: {bundle_path}")
            from ..storage.sqlite import projects as _projects

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _projects.ensure_schema(staging_conn, schema_version=3, now=now)

        handle = ProjectHandle(
            path=bundle_path,
            format="bundle-v1",
            is_bundle=True,
            readonly=False,
            bundle_info=bundle_info,
            staging_path=staging_path,
            staging_conn=staging_conn,
            snapshot_on_save=True,
        )

    _open_handles[id(handle)] = handle
    return handle, handle.staging_conn


def _open_legacy_handle(
    vaso_path: Path, *, readonly: bool = False, fmt: str = "sqlite-v3"
) -> tuple[ProjectHandle, sqlite3.Connection]:
    """Open legacy .vaso file directly."""

    if readonly:
        conn = sqlite3.connect(f"file:{vaso_path}?mode=ro", uri=True, timeout=10.0)
    else:
        conn = sqlite3.connect(vaso_path, timeout=30.0)
        # Set up optimal settings
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")

    handle = ProjectHandle(
        path=vaso_path,
        format=fmt,
        is_bundle=False,
        readonly=readonly,
        bundle_info=None,
        staging_path=None,
        staging_conn=conn,
        snapshot_on_save=False,
    )

    _open_handles[id(handle)] = handle
    return handle, conn


# =============================================================================
# Save / Close
# =============================================================================


def save_project_handle(handle: ProjectHandle, *, skip_snapshot: bool = False) -> None:
    """
    Save project to disk.

    For bundle projects:
    - Creates new snapshot from staging database
    - Updates HEAD to point to new snapshot
    - Optionally prunes old snapshots

    For legacy projects:
    - Commits any pending transactions

    Args:
        handle: ProjectHandle to save
        skip_snapshot: If True, skip snapshot creation (bundle only)

    Raises:
        RuntimeError: If save fails
    """
    if handle.readonly:
        log.warning("Cannot save read-only project")
        return

    if handle.is_bundle:
        if not skip_snapshot and handle.snapshot_on_save:
            log.info(f"Creating snapshot for bundle: {handle.path}")

            # Ensure staging connection is committed
            if handle.staging_conn:
                handle.staging_conn.commit()
            else:
                log.error("No staging connection available for bundle save")
                raise RuntimeError("Cannot save bundle: no staging connection")

            # Verify staging path exists
            if not handle.staging_path:
                log.error("No staging database path available for bundle save")
                raise RuntimeError("Cannot save bundle: no staging database path")

            if not handle.staging_path.exists():
                log.error(f"Staging database does not exist: {handle.staging_path}")
                raise RuntimeError(
                    f"Cannot save bundle: staging database not found at {handle.staging_path}"
                )

            # Create snapshot from staging database
            log.debug(f"Creating snapshot from staging DB: {handle.staging_path}")
            snapshot_info = create_snapshot(handle.path, handle.staging_path)
            log.info(
                f"Snapshot created: {snapshot_info.number} "
                f"({snapshot_info.size_bytes / 1024 / 1024:.1f} MB)"
            )

            # Prune old snapshots (keep last 50)
            pruned = prune_old_snapshots(handle.path, keep_count=50)
            if pruned > 0:
                log.info(f"Pruned {pruned} old snapshots")

        else:
            # Just commit staging database
            if handle.staging_conn:
                handle.staging_conn.commit()
            else:
                log.warning("No staging connection to commit for bundle")

    else:
        # Legacy format: just commit
        if handle.staging_conn:
            handle.staging_conn.commit()


def close_project_handle(handle: ProjectHandle, *, save_before_close: bool = True) -> None:
    """
    Close project handle and clean up resources.

    Args:
        handle: ProjectHandle to close
        save_before_close: If True, save before closing

    Raises:
        RuntimeError: If close fails
    """
    import traceback

    log.debug(f"Closing project handle: {handle.path}")

    # DIAGNOSTIC: Log stack trace to understand who's calling close
    stack_trace = "".join(traceback.format_stack())
    log.info(f"🔍 DIAGNOSTIC - Project close called from:\n{stack_trace}")

    try:
        # Save if requested
        if save_before_close and not handle.readonly:
            save_project_handle(handle)

        # Close database connection
        if handle.staging_conn:
            handle.staging_conn.close()
            handle.staging_conn = None

        # Clean up staging database (bundle only)
        if handle.is_bundle and handle.staging_path:
            if handle.staging_path.exists():
                try:
                    # Remove staging DB and WAL files
                    handle.staging_path.unlink()
                    log.debug(f"Removed staging database: {handle.staging_path}")

                    # Remove WAL and SHM files if they exist
                    wal_file = handle.staging_path.with_suffix(".sqlite-wal")
                    shm_file = handle.staging_path.with_suffix(".sqlite-shm")
                    if wal_file.exists():
                        wal_file.unlink()
                    if shm_file.exists():
                        shm_file.unlink()

                except Exception as e:
                    log.warning(f"Could not remove staging files: {e}")

        # Release bundle lock
        if handle.is_bundle:
            release_lock(handle.path)

        # Remove from registry
        if id(handle) in _open_handles:
            del _open_handles[id(handle)]

        log.info(f"Project closed successfully: {handle.path}")

    except Exception as e:
        log.error(f"Error closing project handle: {e}")
        raise RuntimeError(f"Failed to close project: {e}") from e


# =============================================================================
# Utilities
# =============================================================================


def get_database_path(handle: ProjectHandle) -> Path:
    """
    Get path to active database file.

    For bundles: returns staging database path
    For legacy: returns .vaso file path

    Args:
        handle: ProjectHandle

    Returns:
        Path to database file
    """
    if handle.is_bundle:
        if handle.staging_path:
            return handle.staging_path
        elif handle.bundle_info and handle.bundle_info.current_snapshot:
            return handle.bundle_info.current_snapshot.path
        else:
            raise ValueError("Bundle has no active database")
    else:
        return handle.path


def is_bundle_format(path: str | Path) -> bool:
    """
    Check if path is a bundle format project.

    Args:
        path: Path to check

    Returns:
        True if bundle format, False otherwise
    """
    fmt = detect_project_format(Path(path))
    return fmt == "bundle-v1"


def force_snapshot_now(handle: ProjectHandle) -> int | None:
    """
    Force creation of snapshot immediately (manual snapshot).

    Args:
        handle: ProjectHandle

    Returns:
        Snapshot number, or None if not applicable

    Raises:
        ValueError: If handle is read-only or not a bundle
    """
    if handle.readonly:
        raise ValueError("Cannot create snapshot for read-only handle")

    if not handle.is_bundle:
        raise ValueError("Cannot create snapshot for legacy format")

    if not handle.staging_path:
        raise ValueError("No staging database available")

    log.info("Creating manual snapshot")
    save_project_handle(handle, skip_snapshot=False)

    # Get current snapshot number
    snapshot_info = get_current_snapshot(handle.path)
    if snapshot_info:
        return snapshot_info.number

    return None
