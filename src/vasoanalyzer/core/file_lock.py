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

STALE_LOCK_AGE_SECONDS = 2 * 60 * 60  # 2 hours

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
        self.lock_file: int | None = None
        self._acquired = False
        self._owns_lockfile = False

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
        logged_waiting = False

        while True:
            try:
                # Try to create lock file exclusively (atomic operation)
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)

                # Write lock metadata (PID and timestamp for debugging)
                lock_info = f"{os.getpid()}\n{time.time()}\n"
                os.write(fd, lock_info.encode("utf-8"))

                self.lock_file = fd
                self._acquired = True
                self._owns_lockfile = True
                log.info(f"Acquired project lock: {self.lock_path}")
                return True

            except FileExistsError as exc:
                if self._is_held_by_current_process():
                    self._acquired = True
                    self._owns_lockfile = False
                    log.info(
                        "Reusing project lock for current process path=%s lock=%s pid=%s",
                        self.project_path,
                        self.lock_path,
                        os.getpid(),
                    )
                    return True
                # Lock file exists - check if it's stale
                if self._is_stale_lock():
                    log.warning(f"Removing stale lock file: {self.lock_path}")
                    try:
                        self.lock_path.unlink(missing_ok=True)
                        continue  # Try to acquire again
                    except Exception as e:
                        log.error(f"Failed to remove stale lock: {e}")
                        raise RuntimeError(f"Failed to clean up stale lock: {e}") from e

                if not logged_waiting:
                    holder_info = self._get_lock_holder_info()
                    log.info(
                        "Project lock busy path=%s lock=%s holder=%s",
                        self.project_path,
                        self.lock_path,
                        holder_info,
                    )
                    logged_waiting = True

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    lock_holder = self._get_lock_holder_info()
                    log.error(
                        "Timeout acquiring project lock path=%s lock=%s holder=%s",
                        self.project_path,
                        self.lock_path,
                        lock_holder,
                    )
                    raise RuntimeError(
                        f"Project is already open in another instance.\n\n"
                        f"Lock file: {self.lock_path}\n"
                        f"{lock_holder}\n\n"
                        f"If you're certain no other instance is running, "
                        f"delete the lock file manually."
                    ) from exc

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
            if self._owns_lockfile:
                try:
                    self.lock_path.unlink(missing_ok=True)
                    log.info(f"Released project lock: {self.lock_path}")
                except Exception as e:
                    log.error(f"Failed to remove lock file: {e}")

        finally:
            self._acquired = False
            self._owns_lockfile = False

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
            metadata = self._read_lock_metadata()
            if metadata is None:
                return False

            pid, timestamp = metadata
            if pid is not None:
                if not self._process_exists(pid):
                    log.warning(
                        "Lock pid %s is not running; treating %s as stale", pid, self.lock_path
                    )
                    return True
                return False

            if timestamp is not None:
                age = time.time() - timestamp
                if age >= STALE_LOCK_AGE_SECONDS:
                    log.warning(
                        "Lock has no PID and is %ds old; treating %s as stale",
                        int(age),
                        self.lock_path,
                    )
                    return True
                return False

            log.warning("Lock metadata missing for %s; treating as stale", self.lock_path)
            return True
        except Exception as e:
            log.debug(f"Error checking stale lock: {e}")
            # If we can't read it, assume it might be valid to be safe
            return False

    def _is_held_by_current_process(self) -> bool:
        """Return True when the lock metadata references this PID."""
        metadata = self._read_lock_metadata()
        if metadata is None:
            return False
        pid, _ = metadata
        return pid == os.getpid()

    def _read_lock_metadata(self) -> tuple[int | None, float | None] | None:
        """Return (pid, timestamp) tuple from lock file when available."""
        try:
            with open(self.lock_path, encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.debug("Unable to read lock metadata for %s: %s", self.lock_path, exc)
            return None

        if not lines:
            return None

        pid: int | None = None
        timestamp: float | None = None

        pid_str = lines[0].strip()
        if pid_str:
            try:
                pid = int(pid_str)
            except ValueError:
                log.debug("Invalid PID entry in %s: %r", self.lock_path, pid_str)
                pid = None

        if len(lines) >= 2:
            ts_str = lines[1].strip()
            try:
                timestamp = float(ts_str)
            except ValueError:
                log.debug("Invalid timestamp entry in %s: %r", self.lock_path, ts_str)
                timestamp = None

        return pid, timestamp

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
        metadata = self._read_lock_metadata()
        if metadata is None:
            return "Lock holder information unavailable"

        pid, timestamp = metadata
        if pid is not None and timestamp is not None:
            lock_age = time.time() - timestamp
            return f"Locked by PID {pid} (lock age: {lock_age:.0f}s)"
        if pid is not None:
            return f"Locked by PID {pid}"
        if timestamp is not None:
            lock_age = time.time() - timestamp
            return f"Lock age {lock_age:.0f}s (no PID recorded)"
        return "Lock metadata missing"

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
