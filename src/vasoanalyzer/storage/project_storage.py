"""
Unified project storage interface supporting both legacy and bundle formats.

This module provides backward-compatible wrappers around the existing ProjectStore
that automatically handle bundle format projects transparently.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .bundle_adapter import (
    ProjectHandle,
    close_project_handle,
    create_project_handle,
    is_bundle_format,
    open_project_handle,
    save_project_handle,
)
from .migration import detect_project_format
from .sqlite_store import SCHEMA_VERSION

log = logging.getLogger(__name__)

__all__ = [
    "UnifiedProjectStore",
    "create_unified_project",
    "open_unified_project",
    "USE_BUNDLE_FORMAT_BY_DEFAULT",
]


# =============================================================================
# Configuration
# =============================================================================


def get_use_bundle_format_by_default() -> bool:
    """
    Get user preference for default project format.

    Checks QSettings for user preference, falls back to True (bundle format).
    Bundle format is the default because it's cloud-safe and crash-proof.
    """
    try:
        from PyQt5.QtCore import QSettings

        settings = QSettings("TykockiLab", "VasoAnalyzer")
        # Default to True (bundle format) if not set
        value = settings.value("project/use_bundle_format", True, type=bool)
        return bool(value)
    except Exception:
        # If Qt not available or settings fail, default to bundle format
        return True


# Global flag: if True, new projects use bundle format by default
# Can be overridden by user preference or command-line flag
USE_BUNDLE_FORMAT_BY_DEFAULT = get_use_bundle_format_by_default()


def _detect_cloud_storage(path: Path) -> tuple[bool, str | None]:
    """
    Determine whether ``path`` resides in a known cloud storage location.

    The import is local to avoid circular dependencies during module import.
    """
    try:
        from vasoanalyzer.core.project import _is_cloud_storage_path

        return _is_cloud_storage_path(path.as_posix())
    except Exception:
        return False, None


# =============================================================================
# Unified Project Store
# =============================================================================


@dataclass
class UnifiedProjectStore:
    """
    Unified wrapper for both legacy and bundle format projects.

    Provides the same interface as ProjectStore but works transparently with
    both formats. Legacy code using ProjectStore.conn will work unchanged.

    Attributes:
        path: Path to project (bundle dir or legacy file)
        conn: Database connection (staging DB for bundles, direct for legacy)
        dirty: Whether project has unsaved changes
        handle: ProjectHandle (bundle only)
        is_bundle: True if bundle format
        readonly: True if opened read-only
    """

    path: Path
    conn: sqlite3.Connection
    dirty: bool = False
    handle: ProjectHandle | None = None
    is_bundle: bool = False
    readonly: bool = False
    is_cloud_path: bool = False
    cloud_service: str | None = None
    journal_mode: str | None = None
    _closed: bool = field(default=False, init=False, repr=False)

    def mark_dirty(self) -> None:
        """Mark project as having unsaved changes."""
        self.dirty = True

    def commit(self) -> None:
        """Commit pending changes to database."""
        if self._closed:
            log.warning("Attempt to commit closed project")
            return

        if self.conn:
            self.conn.commit()
        self.dirty = False

    def save(self, *, skip_snapshot: bool = False) -> None:
        """
        Save project (creates snapshot for bundles).

        Args:
            skip_snapshot: If True, skip snapshot creation (commit only)
        """
        if self._closed:
            log.warning("Attempt to save closed project")
            return

        if self.readonly:
            log.warning("Cannot save read-only project")
            return

        # Commit first
        self.commit()

        # Create snapshot for bundles
        if self.is_bundle and self.handle:
            save_project_handle(self.handle, skip_snapshot=skip_snapshot)

        log.debug(f"Project saved: {self.path}")

    def close(self) -> None:
        """Close project and clean up resources."""
        if self._closed:
            return

        try:
            # Save if dirty
            if self.dirty and not self.readonly:
                self.save()

            # Close via handle if bundle
            if self.is_bundle and self.handle:
                close_project_handle(self.handle, save_before_close=False)
            else:
                # Close connection directly for legacy
                if self.conn:
                    self.conn.close()

        finally:
            self._closed = True
            log.debug(f"Project closed: {self.path}")

    def __enter__(self) -> UnifiedProjectStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):
        """Ensure cleanup on garbage collection."""
        # DISABLED: __del__ was causing premature closure during object transfer
        # The Repository wrapper (SQLiteProjectRepository) handles cleanup properly
        # This defensive cleanup was closing the database before it could be used
        pass


# =============================================================================
# Create / Open
# =============================================================================


def create_unified_project(
    path: str | os.PathLike[str],
    *,
    app_version: str,
    timezone: str,
    use_bundle_format: bool | None = None,
    use_container_format: bool | None = None,
) -> UnifiedProjectStore:
    """
    Create a new project (container, bundle, or legacy format).

    Args:
        path: Path for new project
        app_version: Application version string
        timezone: Timezone string (e.g., "UTC", "America/New_York")
        use_bundle_format: If True, create bundle; if False, create legacy;
                          if None, use USE_BUNDLE_FORMAT_BY_DEFAULT
        use_container_format: If True, create single-file container (.vaso);
            if False, create folder bundle (.vasopack); if None, defaults to
            True (container format)

    Returns:
        UnifiedProjectStore

    Raises:
        FileExistsError: If project already exists
    """
    path = Path(path)

    # Determine format
    if use_bundle_format is None:
        use_bundle_format = USE_BUNDLE_FORMAT_BY_DEFAULT

    if use_container_format is None:
        use_container_format = True  # Default to container format

    format_name = (
        "container"
        if (use_bundle_format and use_container_format)
        else ("bundle" if use_bundle_format else "legacy")
    )
    log.info(f"Creating new project ({format_name}): {path}")

    if use_bundle_format:
        if use_container_format:
            # Ensure .vaso extension
            if path.suffix != ".vaso":
                path = path.with_suffix(".vaso")
        else:
            # Ensure .vasopack extension
            if path.suffix != ".vasopack":
                path = path.with_suffix(".vasopack")

        is_cloud, cloud_service = _detect_cloud_storage(path)

        # Create bundle/container project
        handle, conn = create_project_handle(
            path, use_bundle_format=True, use_container_format=use_container_format
        )

        # CRITICAL FIX: Ensure connection is synchronized with handle
        # For bundles/containers, the connection should always match handle.staging_conn
        if handle and handle.staging_conn and handle.staging_conn != conn:
            log.warning("Connection mismatch detected after project creation, using handle's connection")
            conn = handle.staging_conn

        # Initialize schema
        from .sqlite import projects as _projects

        _projects.ensure_schema(
            conn,
            schema_version=SCHEMA_VERSION,
            now=_utc_now(),
            app_version=app_version,
            timezone=timezone,
        )

        # Commit initial schema
        conn.commit()

        return UnifiedProjectStore(
            path=path,
            conn=conn,
            dirty=False,
            handle=handle,
            is_bundle=True,
            readonly=False,
            is_cloud_path=getattr(handle, "is_cloud_path", is_cloud),
            cloud_service=getattr(handle, "cloud_service", cloud_service),
            journal_mode=getattr(handle, "journal_mode", None),
        )

    else:
        # Ensure .vaso extension
        if path.suffix != ".vaso":
            path = path.with_suffix(".vaso")

        is_cloud, cloud_service = _detect_cloud_storage(path)

        # Create legacy project (use existing create_project from sqlite_store)
        from .sqlite_store import create_project as _create_legacy_project

        legacy_store = _create_legacy_project(path, app_version=app_version, timezone=timezone)

        return UnifiedProjectStore(
            path=legacy_store.path,
            conn=legacy_store.conn,
            dirty=legacy_store.dirty,
            handle=None,
            is_bundle=False,
            readonly=False,
            is_cloud_path=getattr(legacy_store, "is_cloud_path", is_cloud),
            cloud_service=getattr(legacy_store, "cloud_service", cloud_service),
            journal_mode=getattr(legacy_store, "journal_mode", None),
        )


def open_unified_project(
    path: str | os.PathLike[str],
    *,
    readonly: bool = False,
    auto_migrate: bool = True,
) -> UnifiedProjectStore:
    """
    Open existing project (automatically handles both formats).

    Automatically:
    - Detects format (legacy or bundle)
    - Migrates legacy to bundle if auto_migrate=True
    - Handles version upgrades
    - Recovers from corruption

    Args:
        path: Path to project file or bundle
        readonly: If True, open read-only
        auto_migrate: If True, auto-migrate legacy projects to bundle

    Returns:
        UnifiedProjectStore

    Raises:
        FileNotFoundError: If project doesn't exist
        ValueError: If project is invalid or corrupted
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Project not found: {path}")

    is_cloud, cloud_service = _detect_cloud_storage(path)

    # Detect format
    fmt = detect_project_format(path)
    log.info(f"Opening project ({fmt}): {path}")

    # Check if bundle or container format
    if fmt in ("bundle-v1", "zip-bundle-v1") or (auto_migrate and is_bundle_format(path)):
        # Open as bundle or container
        handle, conn = open_project_handle(path, readonly=readonly, auto_migrate=auto_migrate)

        return UnifiedProjectStore(
            path=handle.path,
            conn=conn,
            dirty=False,
            handle=handle,
            is_bundle=True,
            readonly=readonly,
            is_cloud_path=getattr(handle, "is_cloud_path", is_cloud),
            cloud_service=getattr(handle, "cloud_service", cloud_service),
            journal_mode=getattr(handle, "journal_mode", None),
        )

    else:
        # Open as legacy (use existing open_project from sqlite_store)
        from .sqlite_store import open_project as _open_legacy_project

        try:
            legacy_store = _open_legacy_project(path)

            return UnifiedProjectStore(
                path=legacy_store.path,
                conn=legacy_store.conn,
                dirty=legacy_store.dirty,
                handle=None,
                is_bundle=False,
                readonly=readonly,
                is_cloud_path=getattr(legacy_store, "is_cloud_path", is_cloud),
                cloud_service=getattr(legacy_store, "cloud_service", cloud_service),
                journal_mode=getattr(legacy_store, "journal_mode", None),
            )

        except Exception as e:
            # If auto_migrate is enabled and this is a supported legacy version,
            # try migrating to bundle
            if auto_migrate and fmt in ("sqlite-v1", "sqlite-v2", "sqlite-v3"):
                log.info(f"Attempting auto-migration to bundle format: {path}")
                try:
                    from .migration import migrate_to_bundle

                    bundle_path = migrate_to_bundle(path, keep_legacy=True)

                    # Open the newly created bundle
                    return open_unified_project(bundle_path, readonly=readonly, auto_migrate=False)

                except Exception as migrate_err:
                    log.error(f"Migration failed: {migrate_err}")
                    # Fall back to original error
                    raise e from migrate_err
            else:
                raise


# =============================================================================
# Utilities
# =============================================================================


def _utc_now() -> str:
    """Get current UTC timestamp as ISO string."""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_project_format(path: str | os.PathLike[str]) -> str:
    """
    Get format of project at path.

    Args:
        path: Path to project

    Returns:
        Format string: "bundle-v1", "sqlite-v3", etc.
    """
    return detect_project_format(Path(path))


def convert_to_bundle(
    legacy_path: str | os.PathLike[str],
    *,
    bundle_path: str | os.PathLike[str] | None = None,
    keep_legacy: bool = True,
) -> Path:
    """
    Convert legacy .vaso to bundle format.

    Args:
        legacy_path: Path to legacy .vaso file
        bundle_path: Output path (default: legacy_path.vasopack)
        keep_legacy: If True, keep legacy file as .vaso.legacy

    Returns:
        Path to new bundle

    Raises:
        ValueError: If not a legacy project
        FileExistsError: If bundle already exists
    """
    from .migration import migrate_to_bundle

    legacy_path = Path(legacy_path)
    bundle_path_obj: Path | None = Path(bundle_path) if bundle_path is not None else None

    return migrate_to_bundle(legacy_path, bundle_path=bundle_path_obj, keep_legacy=keep_legacy)


def export_bundle_to_legacy(
    bundle_path: str | os.PathLike[str],
    *,
    output_path: str | os.PathLike[str] | None = None,
) -> Path:
    """
    Export bundle to legacy single-file format.

    Useful for sharing with users on older VasoAnalyzer versions.

    Args:
        bundle_path: Path to bundle
        output_path: Output path (default: bundle_path.vaso)

    Returns:
        Path to exported .vaso file

    Raises:
        ValueError: If not a bundle
    """
    from .migration import export_to_legacy

    bundle_path_path = Path(bundle_path)
    output_path_obj: Path | None = Path(output_path) if output_path is not None else None

    return export_to_legacy(bundle_path_path, output_path=output_path_obj)
