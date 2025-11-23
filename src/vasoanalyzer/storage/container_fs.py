"""
Single-file ZIP container format for VasoAnalyzer projects.

This module implements a container layer that wraps the existing .vasopack
bundle format into a single ZIP file, providing a user-friendly "single file"
project format similar to LabChart (.adicht) or Prism projects.

Container Structure:
    MyProject.vaso (ZIP file)
    └── bundle/
        ├── HEAD.json
        ├── snapshots/
        │   ├── 000001.sqlite
        │   └── 000002.sqlite
        └── project.meta.json

Design Principles:
- Container is a standard ZIP file (no compression for speed)
- On open: unpack to temp directory, use existing bundle logic
- On save: pack temp directory back to .vaso file atomically
- Staging and lock files are NOT included in the container (temp only)
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "is_vaso_container",
    "unpack_container_to_temp",
    "pack_temp_bundle_to_container",
    "cleanup_stale_temp_dirs",
    "get_container_metadata",
]

# Magic bytes for format detection
ZIP_MAGIC = b"PK\x03\x04"
SQLITE_MAGIC = b"SQLite format 3\x00"

# Temp directory prefix
TEMP_DIR_PREFIX = "VasoAnalyzer-container-"

# Maximum age for stale temp directories (24 hours)
TEMP_DIR_MAX_AGE = 86400


# =============================================================================
# Format Detection
# =============================================================================


def is_vaso_container(path: Path) -> bool:
    """
    Check if a file is a VasoAnalyzer ZIP container.

    Args:
        path: Path to file to check

    Returns:
        True if file is a ZIP-based container, False otherwise
    """
    if not path.exists() or not path.is_file():
        return False

    try:
        # Check file extension
        if path.suffix != ".vaso":
            return False

        # Check for ZIP magic bytes
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != ZIP_MAGIC:
                return False

        # Verify it's a valid ZIP and contains bundle structure
        with zipfile.ZipFile(path, "r") as zf:
            namelist = zf.namelist()
            # Check for required bundle files
            required = ["bundle/HEAD.json", "bundle/project.meta.json"]
            has_required = all(
                any(name.endswith(req) or name == req for name in namelist) for req in required
            )
            return has_required

    except (OSError, zipfile.BadZipFile) as e:
        log.debug(f"Not a valid container: {path} ({e})")
        return False


def is_legacy_vaso(path: Path) -> bool:
    """
    Check if a .vaso file is a legacy single-file SQLite database.

    Args:
        path: Path to file to check

    Returns:
        True if legacy SQLite .vaso file, False otherwise
    """
    if not path.exists() or not path.is_file():
        return False

    if path.suffix != ".vaso":
        return False

    try:
        with open(path, "rb") as f:
            magic = f.read(16)
            return magic == SQLITE_MAGIC
    except OSError:
        return False


def get_container_metadata(path: Path) -> dict[str, Any]:
    """
    Read metadata from container without unpacking.

    Args:
        path: Path to container file

    Returns:
        Dictionary with metadata, or empty dict if not found
    """
    if not is_vaso_container(path):
        return {}

    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Try to read project.meta.json
            for name in zf.namelist():
                if name.endswith("project.meta.json"):
                    import json

                    meta_bytes = zf.read(name)
                    loaded: Any = json.loads(meta_bytes.decode("utf-8"))
                    if isinstance(loaded, dict):
                        return loaded
                    log.warning("Container metadata is not a JSON object")
    except Exception as e:
        log.warning(f"Could not read container metadata: {e}")

    return {}


# =============================================================================
# Container Unpacking
# =============================================================================


def unpack_container_to_temp(path: Path, *, temp_dir: Path | None = None) -> Path:
    """
    Unpack a container file to a temporary directory.

    Creates a temp directory that looks exactly like a .vasopack bundle,
    so existing bundle code can work with it unchanged.

    Args:
        path: Path to container file (.vaso)
        temp_dir: Optional specific temp directory to use

    Returns:
        Path to unpacked bundle root (temp directory)

    Raises:
        ValueError: If not a valid container
        OSError: If unpacking fails
    """
    if not is_vaso_container(path):
        raise ValueError(f"Not a valid VasoAnalyzer container: {path}")

    log.info(f"Unpacking container to temp: {path}")

    # Create temp directory
    if temp_dir is None:
        temp_base = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
        temp_root = Path(temp_base)
    else:
        temp_root = temp_dir
        temp_root.mkdir(parents=True, exist_ok=True)

    bundle_root = temp_root / "bundle"

    try:
        # Extract ZIP to temp directory
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(temp_root)

        # Verify bundle structure exists
        if not bundle_root.exists():
            raise ValueError(f"Container does not contain bundle/ directory: {path}")

        # Create .staging directory (not stored in container)
        staging_dir = bundle_root / ".staging"
        staging_dir.mkdir(exist_ok=True)

        log.info(f"Unpacked container to: {bundle_root}")
        return bundle_root

    except Exception as e:
        # Clean up on error
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        log.error(f"Failed to unpack container: {e}")
        raise OSError(f"Failed to unpack container: {e}") from e


# =============================================================================
# Container Packing
# =============================================================================


def pack_temp_bundle_to_container(
    bundle_root: Path,
    target_path: Path,
    *,
    exclude_staging: bool = True,
    exclude_lock: bool = True,
) -> None:
    """
    Pack a bundle directory into a single-file container.

    Creates target_path.tmp first, then atomically renames to target_path.
    This ensures the container file is never left in a partial state.

    Args:
        bundle_root: Path to bundle directory (looks like .vasopack)
        target_path: Path to output container file (.vaso)
        exclude_staging: If True, don't include .staging/ directory
        exclude_lock: If True, don't include .lock file

    Raises:
        OSError: If packing fails
    """
    if not bundle_root.exists():
        raise ValueError(f"Bundle root does not exist: {bundle_root}")

    log.info(f"Packing bundle to container: {target_path}")

    # Create temp target path
    temp_target = target_path.with_suffix(target_path.suffix + ".tmp")

    try:
        # Create ZIP file with no compression (SQLite doesn't compress well)
        with zipfile.ZipFile(temp_target, "w", zipfile.ZIP_STORED) as zf:
            # Walk bundle directory and add files
            for root, dirs, files in os.walk(bundle_root):
                root_path = Path(root)

                # Skip .staging directory if requested
                if exclude_staging and root_path.name == ".staging":
                    dirs.clear()  # Don't recurse into .staging
                    continue

                # Add files
                for file in files:
                    file_path = root_path / file

                    # Skip .lock file if requested
                    if exclude_lock and file == ".lock":
                        continue

                    # Calculate archive name (relative to bundle_root parent)
                    # This preserves the "bundle/" prefix in the ZIP
                    archive_name = file_path.relative_to(bundle_root.parent)

                    # Add to ZIP
                    zf.write(file_path, archive_name)

        # Atomic replace: temp -> final
        os.replace(temp_target, target_path)
        log.info(f"Container created successfully: {target_path}")

    except Exception as e:
        # Clean up temp file on error
        if temp_target.exists():
            temp_target.unlink()
        log.error(f"Failed to pack container: {e}")
        raise OSError(f"Failed to pack container: {e}") from e


# =============================================================================
# Cleanup
# =============================================================================


def cleanup_stale_temp_dirs(max_age: int = TEMP_DIR_MAX_AGE) -> int:
    """
    Remove stale temporary bundle directories.

    This is called on app startup to clean up temp directories from
    crashed sessions.

    Args:
        max_age: Maximum age in seconds (default: 24 hours)

    Returns:
        Number of directories cleaned up
    """
    temp_base = Path(tempfile.gettempdir())
    cleaned = 0

    try:
        for temp_dir in temp_base.glob(f"{TEMP_DIR_PREFIX}*"):
            if not temp_dir.is_dir():
                continue

            try:
                # Check age
                age = time.time() - temp_dir.stat().st_mtime
                if age > max_age:
                    log.debug(f"Removing stale temp directory: {temp_dir}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    cleaned += 1
            except Exception as e:
                log.warning(f"Could not clean up {temp_dir}: {e}")

    except Exception as e:
        log.warning(f"Error during temp directory cleanup: {e}")

    if cleaned > 0:
        log.info(f"Cleaned up {cleaned} stale temp directories")

    return cleaned


def get_temp_root_for_bundle(bundle_path: Path) -> Path | None:
    """
    Get the temp root directory for a given bundle path.

    If the bundle is inside a temp container directory, returns the temp root.
    Otherwise returns None.

    Args:
        bundle_path: Path to bundle directory

    Returns:
        Path to temp root, or None if not in temp directory
    """
    # Check if bundle_path is inside a temp directory
    temp_base = Path(tempfile.gettempdir())

    try:
        # Check if bundle_path is relative to temp_base
        rel = bundle_path.relative_to(temp_base)

        # Check if the first component starts with our prefix
        parts = rel.parts
        if parts and parts[0].startswith(TEMP_DIR_PREFIX):
            return temp_base / parts[0]

    except ValueError:
        # Not relative to temp_base
        pass

    return None


# =============================================================================
# Conversion Utilities
# =============================================================================


def convert_vasopack_to_container(vasopack_path: Path, container_path: Path | None = None) -> Path:
    """
    Convert a .vasopack folder bundle to a .vaso container.

    Args:
        vasopack_path: Path to .vasopack directory
        container_path: Output path (default: vasopack_path.vaso)

    Returns:
        Path to created container file

    Raises:
        ValueError: If vasopack_path is not a valid bundle
        FileExistsError: If container_path already exists
    """
    if not vasopack_path.is_dir():
        raise ValueError(f"Not a directory: {vasopack_path}")

    # Verify it's a valid bundle
    required = ["HEAD.json", "project.meta.json", "snapshots"]
    missing = [name for name in required if not (vasopack_path / name).exists()]
    if missing:
        raise ValueError(f"Not a valid bundle (missing {', '.join(missing)}): {vasopack_path}")

    # Determine output path
    if container_path is None:
        container_path = vasopack_path.with_suffix(".vaso")

    if container_path.exists():
        raise FileExistsError(f"Container already exists: {container_path}")

    log.info(f"Converting .vasopack to container: {vasopack_path} → {container_path}")

    # Create temp structure that pack_temp_bundle_to_container expects
    # (bundle should be inside a parent directory called "bundle")
    with tempfile.TemporaryDirectory(prefix="vasopack-convert-") as temp_dir:
        temp_path = Path(temp_dir)
        temp_bundle = temp_path / "bundle"

        # Copy bundle to temp/bundle/
        shutil.copytree(vasopack_path, temp_bundle)

        # Pack to container
        pack_temp_bundle_to_container(temp_bundle, container_path)

    log.info(f"Conversion completed: {container_path}")
    return container_path
