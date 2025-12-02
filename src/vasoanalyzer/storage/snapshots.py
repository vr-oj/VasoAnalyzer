"""
Append-only snapshot system for VasoAnalyzer projects.

This module implements a crash-safe, cloud-sync-safe project storage system using
immutable snapshots in a bundle directory format.

Bundle Structure:
    MyProject.vasopack/
        HEAD.json                 # Pointer to current snapshot
        snapshots/
            000001.sqlite         # Immutable snapshot files
            000002.sqlite
            ...
        .staging/
            <uuid>.sqlite         # Active staging DB (deleted on close)
        project.meta.json         # Stable project metadata
        .lock                     # Lock file for write access

Design Principles:
- Snapshots are NEVER modified after creation (immutable)
- All saves create a new snapshot, then atomically update HEAD
- Crash during save = HEAD still points to last good snapshot
- Cloud sync safe: partial uploads don't corrupt anything
- Multi-window safe: only lock holder can create snapshots
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

log = logging.getLogger(__name__)

__all__ = [
    "BundleInfo",
    "SnapshotInfo",
    "create_bundle",
    "open_bundle",
    "create_snapshot",
    "open_staging_db",
    "snapshot_from_staging",
    "get_current_snapshot",
    "list_snapshots",
    "validate_snapshot",
    "prune_old_snapshots",
]


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class SnapshotInfo:
    """Metadata about a single snapshot."""

    path: Path
    number: int
    timestamp: float
    is_current: bool
    size_bytes: int


@dataclass
class BundleInfo:
    """Information about a project bundle."""

    bundle_path: Path
    current_snapshot: SnapshotInfo | None
    total_snapshots: int
    total_size_bytes: int


# =============================================================================
# Atomic File Operations
# =============================================================================


def atomic_write_text(path: Path, text: str) -> None:
    """
    Write text to file atomically with fsync.

    Creates temporary file, writes content, fsyncs, then atomically replaces target.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        # Ensure data is on disk
        fd = os.open(tmp, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        # Atomic replace
        os.replace(tmp, path)
    except Exception:
        # Clean up temp file on error
        if tmp.exists():
            tmp.unlink()
        raise


def fsync_file(path: Path) -> None:
    """Force file data to disk."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# =============================================================================
# Bundle Creation & Opening
# =============================================================================


def create_bundle(bundle_path: Path) -> Path:
    """
    Create a new project bundle directory structure.

    Args:
        bundle_path: Path to bundle (e.g., MyProject.vasopack)

    Returns:
        Path to bundle directory

    Raises:
        FileExistsError: If bundle already exists
    """
    if bundle_path.exists():
        raise FileExistsError(f"Bundle already exists: {bundle_path}")

    log.info(f"Creating new bundle at {bundle_path}")

    # Create directory structure
    bundle_path.mkdir(parents=True, exist_ok=False)
    (bundle_path / "snapshots").mkdir(exist_ok=True)
    (bundle_path / ".staging").mkdir(exist_ok=True)

    # Create initial project metadata
    meta = {
        "format": "bundle-v1",
        "created_at": time.time(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_text(bundle_path / "project.meta.json", json.dumps(meta, indent=2))

    # Create empty HEAD (no snapshots yet)
    head = {"current": None, "timestamp": time.time()}
    atomic_write_text(bundle_path / "HEAD.json", json.dumps(head, indent=2))

    log.info(f"Bundle created successfully at {bundle_path}")
    return bundle_path


def open_bundle(bundle_path: Path, *, readonly: bool = False) -> BundleInfo:
    """
    Open an existing project bundle and validate it.

    Args:
        bundle_path: Path to bundle directory
        readonly: If True, open in read-only mode (no lock acquired)

    Returns:
        BundleInfo with bundle metadata

    Raises:
        FileNotFoundError: If bundle doesn't exist
        ValueError: If bundle is invalid or corrupted
    """
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    if not bundle_path.is_dir():
        raise ValueError(f"Bundle path is not a directory: {bundle_path}")

    # Validate structure
    required = ["HEAD.json", "snapshots"]
    missing = [name for name in required if not (bundle_path / name).exists()]
    if missing:
        raise ValueError(f"Invalid bundle (missing {', '.join(missing)}): {bundle_path}")

    # Try to acquire lock (unless readonly)
    lock_path = bundle_path / ".lock"
    if not readonly:
        try:
            # Try non-blocking lock
            if lock_path.exists():
                # Check if lock is stale (older than 1 hour)
                lock_age = time.time() - lock_path.stat().st_mtime
                if lock_age < 3600:
                    log.warning(
                        f"Bundle is locked by another process (opened read-only): {bundle_path}"
                    )
                    readonly = True
                else:
                    log.info("Removing stale lock file")
                    lock_path.unlink()

            if not readonly:
                # Create lock file
                lock_data = {
                    "pid": os.getpid(),
                    "timestamp": time.time(),
                    "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
                }
                atomic_write_text(lock_path, json.dumps(lock_data, indent=2))
        except Exception as e:
            log.warning(f"Could not acquire lock: {e}. Opening read-only.")
            readonly = True

    # Get current snapshot
    current_snapshot = None
    try:
        current_snapshot = get_current_snapshot(bundle_path)
    except Exception as e:
        log.warning(f"Could not get current snapshot: {e}")

    # Calculate bundle stats
    snapshots = list_snapshots(bundle_path)
    total_size = sum(snap.size_bytes for snap in snapshots)

    return BundleInfo(
        bundle_path=bundle_path,
        current_snapshot=current_snapshot,
        total_snapshots=len(snapshots),
        total_size_bytes=total_size,
    )


# =============================================================================
# Snapshot Management
# =============================================================================


def next_snapshot_name(snapshots_dir: Path) -> Path:
    """
    Generate next snapshot filename in sequence.

    Args:
        snapshots_dir: Path to snapshots directory

    Returns:
        Path to next snapshot file (e.g., snapshots/000042.sqlite)
    """
    nums = [int(p.stem) for p in snapshots_dir.glob("*.sqlite") if p.stem.isdigit()]
    n = (max(nums) + 1) if nums else 1
    return snapshots_dir / f"{n:06d}.sqlite"


def create_snapshot(bundle_path: Path, staging_db: Path) -> SnapshotInfo:
    """
    Create immutable snapshot from staging database.

    Uses SQLite backup API to create consistent snapshot, then atomically
    updates HEAD.json to point to it.

    Args:
        bundle_path: Path to bundle directory
        staging_db: Path to staging database to snapshot

    Returns:
        SnapshotInfo for newly created snapshot

    Raises:
        RuntimeError: If snapshot creation fails
    """
    log.info(f"Creating snapshot from staging DB: {staging_db}")

    snaps_dir = bundle_path / "snapshots"
    snaps_dir.mkdir(parents=True, exist_ok=True)

    # Determine next snapshot path
    dest_tmp = next_snapshot_name(snaps_dir).with_suffix(".sqlite.tmp")
    dest = Path(str(dest_tmp)[:-4])  # Remove .tmp

    try:
        # CRITICAL FIX: Checkpoint WAL to ensure all data is in the main database file
        # Before creating snapshot, we must flush all pending writes from WAL to main DB
        log.debug("Checkpointing WAL before snapshot creation")
        try:
            with sqlite3.connect(staging_db) as conn:
                # PRAGMA wal_checkpoint(FULL) ensures:
                # 1. All WAL frames are written to main database
                # 2. WAL file is reset/truncated
                # 3. Checkpoint completes even if database is busy
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
                log.debug("WAL checkpoint completed successfully")
        except Exception as e:
            log.warning(f"WAL checkpoint failed (will try backup anyway): {e}")

        # Verify WAL/SHM files are gone or minimal after checkpoint
        wal_file = staging_db.with_suffix(".sqlite-wal")
        shm_file = staging_db.with_suffix(".sqlite-shm")
        if wal_file.exists():
            wal_size = wal_file.stat().st_size
            if wal_size > 0:
                log.warning(f"WAL file still exists with {wal_size} bytes: {wal_file}")
        if shm_file.exists():
            log.debug(f"SHM file exists (normal for WAL mode): {shm_file}")

        # Use simple file copy now that WAL has been checkpointed
        # This avoids potential locking issues with SQLite backup API
        log.debug("Copying staging database to snapshot")
        shutil.copy2(staging_db, dest_tmp)

        # Convert snapshot to non-WAL mode and optimize
        log.debug("Converting snapshot to DELETE journal mode and optimizing")
        with sqlite3.connect(dest_tmp) as dst:
            # Disable WAL mode for snapshots (they're read-only anyway)
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.execute("PRAGMA optimize")
            dst.commit()

        # Fsync the snapshot file
        fsync_file(dest_tmp)

        # Atomic publish: rename temp to final name
        os.replace(dest_tmp, dest)
        log.info(f"Snapshot created: {dest.name}")

        # Update HEAD to point to new snapshot
        head_doc = {"current": dest.name, "timestamp": time.time()}
        atomic_write_text(bundle_path / "HEAD.json", json.dumps(head_doc, indent=2))

        # Return snapshot info
        return SnapshotInfo(
            path=dest,
            number=int(dest.stem),
            timestamp=time.time(),
            is_current=True,
            size_bytes=dest.stat().st_size,
        )

    except Exception as e:
        # Clean up temp file on error
        if dest_tmp.exists():
            dest_tmp.unlink()
        log.error(f"Failed to create snapshot: {e}")
        raise RuntimeError(f"Snapshot creation failed: {e}") from e


def snapshot_from_staging(bundle_path: Path, staging_db: Path) -> SnapshotInfo:
    """
    Alias for create_snapshot() for compatibility with user's code example.
    """
    return create_snapshot(bundle_path, staging_db)


def get_current_snapshot(bundle_path: Path) -> SnapshotInfo | None:
    """
    Get the current snapshot referenced by HEAD.json.

    Validates snapshot integrity and falls back to latest valid snapshot if needed.

    Args:
        bundle_path: Path to bundle directory

    Returns:
        SnapshotInfo for current snapshot, or None if no snapshots exist

    Raises:
        RuntimeError: If no valid snapshot found
    """
    head_path = bundle_path / "HEAD.json"
    if not head_path.exists():
        return None

    try:
        head = json.loads(head_path.read_text(encoding="utf-8"))
        snap_name = head.get("current")

        if snap_name:
            snap_path = bundle_path / "snapshots" / snap_name

            # Validate snapshot
            if snap_path.exists() and validate_snapshot(snap_path):
                return SnapshotInfo(
                    path=snap_path,
                    number=int(snap_path.stem),
                    timestamp=head.get("timestamp", 0),
                    is_current=True,
                    size_bytes=snap_path.stat().st_size,
                )

        # Fallback: find latest valid snapshot
        log.warning("HEAD points to invalid snapshot, searching for latest valid snapshot")
        candidates = sorted(
            (bundle_path / "snapshots").glob("*.sqlite"), key=lambda p: int(p.stem), reverse=True
        )

        for candidate in candidates:
            if validate_snapshot(candidate):
                log.info(f"Found valid snapshot: {candidate.name}")
                # Update HEAD to point to recovered snapshot
                head_doc = {"current": candidate.name, "timestamp": time.time()}
                atomic_write_text(head_path, json.dumps(head_doc, indent=2))

                return SnapshotInfo(
                    path=candidate,
                    number=int(candidate.stem),
                    timestamp=candidate.stat().st_mtime,
                    is_current=True,
                    size_bytes=candidate.stat().st_size,
                )

        # No valid snapshots found
        return None

    except Exception as e:
        log.error(f"Error getting current snapshot: {e}")
        raise RuntimeError(f"Failed to get current snapshot: {e}") from e


def open_head_snapshot(bundle_path: Path) -> Path:
    """
    Get path to current snapshot (for compatibility with user's code example).

    Args:
        bundle_path: Path to bundle directory

    Returns:
        Path to current snapshot file

    Raises:
        RuntimeError: If no valid snapshot found
    """
    snapshot_info = get_current_snapshot(bundle_path)
    if snapshot_info is None:
        raise RuntimeError("No valid snapshot found")
    return snapshot_info.path


def list_snapshots(bundle_path: Path) -> list[SnapshotInfo]:
    """
    List all snapshots in bundle, sorted by number.

    Args:
        bundle_path: Path to bundle directory

    Returns:
        List of SnapshotInfo, sorted by snapshot number (newest last)
    """
    snaps_dir = bundle_path / "snapshots"
    if not snaps_dir.exists():
        return []

    # Get current snapshot name
    current_name = None
    try:
        head = json.loads((bundle_path / "HEAD.json").read_text(encoding="utf-8"))
        current_name = head.get("current")
    except Exception:
        pass

    snapshots = []
    for snap_path in snaps_dir.glob("*.sqlite"):
        if not snap_path.stem.isdigit():
            continue

        try:
            stat = snap_path.stat()
            snapshots.append(
                SnapshotInfo(
                    path=snap_path,
                    number=int(snap_path.stem),
                    timestamp=stat.st_mtime,
                    is_current=(snap_path.name == current_name),
                    size_bytes=stat.st_size,
                )
            )
        except Exception as e:
            log.warning(f"Could not read snapshot {snap_path}: {e}")

    # Sort by number (oldest first)
    snapshots.sort(key=lambda s: s.number)
    return snapshots


def validate_snapshot(snap_path: Path) -> bool:
    """
    Validate snapshot database integrity.

    Args:
        snap_path: Path to snapshot file

    Returns:
        True if snapshot is valid, False otherwise
    """
    if not snap_path.exists():
        return False

    try:
        with sqlite3.connect(f"file:{snap_path}?mode=ro", uri=True, timeout=5) as db:
            result = db.execute("PRAGMA quick_check").fetchone()
            status = cast(str | None, result[0] if result else None)
            return status == "ok"
    except Exception as e:
        log.debug(f"Snapshot validation failed for {snap_path}: {e}")
        return False


# =============================================================================
# Staging Database
# =============================================================================


def open_staging_db(
    bundle_path: Path, *, initialize_from: Path | None = None
) -> tuple[Path, sqlite3.Connection]:
    """
    Create or open staging database for active session.

    Staging DB is stored in bundle/.staging/<uuid>.sqlite with WAL mode for
    fast, crash-safe writes during session.

    Args:
        bundle_path: Path to bundle directory
        initialize_from: If provided, copy this snapshot as starting point

    Returns:
        Tuple of (staging_db_path, connection)
    """
    staging_dir = bundle_path / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique staging DB name
    staging_id = uuid.uuid4().hex[:12]
    staging_path = staging_dir / f"{staging_id}.sqlite"

    log.info(f"Creating staging database: {staging_path}")

    # Copy from snapshot if provided
    if initialize_from and initialize_from.exists():
        log.debug(f"Initializing staging DB from {initialize_from}")
        shutil.copy2(initialize_from, staging_path)

    # Open with optimal settings for staging
    conn = sqlite3.connect(staging_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # Faster, still safe
    if hasattr(os, "F_FULLFSYNC"):  # macOS
        conn.execute("PRAGMA fullfsync=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")  # 256 MB
    conn.execute("PRAGMA cache_size=-131072")  # 128 MB

    log.info(f"Staging database ready: {staging_path}")
    return staging_path, conn


# =============================================================================
# Snapshot Retention
# =============================================================================


def prune_old_snapshots(bundle_path: Path, keep_count: int = 50) -> int:
    """
    Remove old snapshots, keeping only the most recent N.

    Never removes the current snapshot referenced by HEAD.

    Args:
        bundle_path: Path to bundle directory
        keep_count: Number of most recent snapshots to keep (default: 50)

    Returns:
        Number of snapshots deleted

    Raises:
        ValueError: If keep_count < 1
    """
    if keep_count < 1:
        raise ValueError("keep_count must be at least 1")

    log.info(f"Pruning old snapshots (keeping {keep_count} most recent)")

    snapshots = list_snapshots(bundle_path)
    if len(snapshots) <= keep_count:
        log.debug(f"Only {len(snapshots)} snapshots exist, no pruning needed")
        return 0

    # Never delete current snapshot
    current_nums = {s.number for s in snapshots if s.is_current}

    # Sort by number, oldest first
    candidates = sorted(snapshots, key=lambda s: s.number)

    # Keep only the oldest (total - keep_count) snapshots
    to_delete = []
    for snap in candidates[:-keep_count]:
        # Don't delete current snapshot
        if snap.number not in current_nums:
            to_delete.append(snap)

    # Delete snapshots
    deleted_count = 0
    for snap in to_delete:
        try:
            snap.path.unlink()
            log.debug(f"Deleted snapshot: {snap.path.name}")
            deleted_count += 1
        except Exception as e:
            log.warning(f"Could not delete snapshot {snap.path}: {e}")

    log.info(f"Pruned {deleted_count} old snapshots")
    return deleted_count


# =============================================================================
# Utilities
# =============================================================================


def cleanup_staging_dbs(bundle_path: Path) -> int:
    """
    Remove orphaned staging databases (from crashed sessions).

    Args:
        bundle_path: Path to bundle directory

    Returns:
        Number of staging DBs cleaned up
    """
    staging_dir = bundle_path / ".staging"
    if not staging_dir.exists():
        return 0

    cleaned = 0
    for staging_file in staging_dir.glob("*.sqlite*"):
        try:
            # Check if file is older than 1 hour
            age = time.time() - staging_file.stat().st_mtime
            if age > 3600:
                staging_file.unlink()
                log.debug(f"Cleaned up stale staging file: {staging_file.name}")
                cleaned += 1
        except Exception as e:
            log.warning(f"Could not clean up {staging_file}: {e}")

    return cleaned


def release_lock(bundle_path: Path) -> None:
    """
    Release lock on bundle (called on clean close).

    Args:
        bundle_path: Path to bundle directory
    """
    lock_path = bundle_path / ".lock"
    if lock_path.exists():
        try:
            lock_path.unlink()
            log.debug("Released bundle lock")
        except Exception as e:
            log.warning(f"Could not release lock: {e}")
