# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Cross-platform file locking to prevent concurrent project access."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


class ProjectFileLock:
    """
    Cross-platform file locking for SQLite project files.

    Prevents multiple instances from opening the same project simultaneously,
    which could cause database corruption.

    Usage:
        lock = ProjectFileLock(project_path)
        try:
            lock.acquire(timeout=5)
            # ... work with project ...
        finally:
            lock.release()

    Or use as context manager:
        with ProjectFileLock(project_path):
            # ... work with project ...
    """

    def __init__(self, project_path: str | Path):
        """
        Initialize file lock for a project.

        Args:
            project_path: Path to the .vaso project file
        """
        self.project_path = Path(project_path)
        self.lock_path = self.project_path.with_suffix(self.project_path.suffix + ".lock")
        self.lock_file = None
        self._acquired = False

    def acquire(self, timeout: float = 5.0) -> bool:
        """
        Attempt to acquire the lock.

        Args:
            timeout: Maximum seconds to wait for lock acquisition

        Returns:
            True if lock was acquired

        Raises:
            RuntimeError: If lock cannot be acquired within timeout
        """
        start_time = time.time()

        while True:
            try:
                # Try to create lock file exclusively (atomic operation)
                fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644
                )

                # Write lock metadata (PID and timestamp for debugging)
                lock_info = f"{os.getpid()}\n{time.time()}\n"
                os.write(fd, lock_info.encode('utf-8'))

                self.lock_file = fd
                self._acquired = True
                log.info(f"Acquired project lock: {self.lock_path}")
                return True

            except FileExistsError:
                # Lock file exists - check if it's stale
                if self._is_stale_lock():
                    log.warning(f"Removing stale lock file: {self.lock_path}")
                    try:
                        self.lock_path.unlink(missing_ok=True)
                        continue  # Try to acquire again
                    except Exception as e:
                        log.error(f"Failed to remove stale lock: {e}")

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    lock_holder = self._get_lock_holder_info()
                    raise RuntimeError(
                        f"Project is already open in another instance.\n\n"
                        f"Lock file: {self.lock_path}\n"
                        f"{lock_holder}\n\n"
                        f"If you're certain no other instance is running, delete the lock file manually."
                    )

                # Wait a bit before retrying
                time.sleep(0.1)

            except Exception as e:
                log.error(f"Unexpected error acquiring lock: {e}", exc_info=True)
                raise RuntimeError(f"Failed to acquire project lock: {e}") from e

    def release(self) -> None:
        """Release the lock if held."""
        if not self._acquired:
            return

        try:
            # Close file descriptor
            if self.lock_file is not None:
                try:
                    os.close(self.lock_file)
                except OSError as e:
                    log.debug(f"Error closing lock file descriptor: {e}")
                finally:
                    self.lock_file = None

            # Remove lock file
            try:
                self.lock_path.unlink(missing_ok=True)
                log.info(f"Released project lock: {self.lock_path}")
            except Exception as e:
                log.error(f"Failed to remove lock file: {e}")

        finally:
            self._acquired = False

    def is_locked(self) -> bool:
        """Check if a lock file exists (doesn't verify if it's stale)."""
        return self.lock_path.exists()

    def _is_stale_lock(self) -> bool:
        """
        Check if the lock file belongs to a dead/non-existent process.

        Returns:
            True if lock is stale and should be removed
        """
        try:
            # Read PID from lock file
            with open(self.lock_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if not lines:
                    return True  # Empty lock file is stale

                pid_str = lines[0].strip()
                try:
                    pid = int(pid_str)
                except ValueError:
                    log.warning(f"Invalid PID in lock file: {pid_str}")
                    return True  # Malformed lock file

            # Check if process exists
            return not self._process_exists(pid)

        except Exception as e:
            log.debug(f"Error checking stale lock: {e}")
            # If we can't read it, assume it might be valid to be safe
            return False

    def _process_exists(self, pid: int) -> bool:
        """
        Check if a process with the given PID exists.

        Args:
            pid: Process ID to check

        Returns:
            True if process exists, False otherwise
        """
        try:
            if sys.platform == "win32":
                # Windows: Use ctypes to check process existence
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

                # Try to open the process
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False

            else:
                # Unix/Linux/macOS: Send signal 0 (doesn't actually send signal)
                # If process exists, no exception. If not, raises ProcessLookupError
                os.kill(pid, 0)
                return True

        except (OSError, ProcessLookupError):
            # Process doesn't exist
            return False
        except Exception as e:
            log.debug(f"Error checking process existence: {e}")
            # If unsure, assume process exists to be safe
            return True

    def _get_lock_holder_info(self) -> str:
        """Get information about the process holding the lock."""
        try:
            with open(self.lock_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) >= 2:
                    pid = lines[0].strip()
                    timestamp = float(lines[1].strip())
                    lock_age = time.time() - timestamp
                    return f"Locked by PID {pid} (lock age: {lock_age:.0f}s)"
                elif len(lines) == 1:
                    return f"Locked by PID {lines[0].strip()}"
        except Exception:
            pass
        return "Lock holder information unavailable"

    def __enter__(self) -> ProjectFileLock:
        """Context manager entry: acquire lock."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit: release lock."""
        self.release()

    def __del__(self) -> None:
        """Destructor: ensure lock is released."""
        if self._acquired:
            log.warning(f"Lock not explicitly released, cleaning up: {self.lock_path}")
            self.release()
