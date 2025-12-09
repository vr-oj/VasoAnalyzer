"""
Timeout wrapper for long-running database operations.

Provides a context manager that raises TimeoutError if an operation
takes longer than a specified duration. This prevents infinite hangs
during save operations, especially on cloud storage.
"""

from __future__ import annotations

import contextlib
import logging
import platform
import signal
import threading
from typing import Generator

log = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when operation exceeds timeout."""

    pass


@contextlib.contextmanager
def timeout(seconds: int) -> Generator[None, None, None]:
    """
    Context manager that raises TimeoutError after specified seconds.

    Uses signal.SIGALRM on Unix-like systems (macOS, Linux) when running in
    the main thread, and threading.Timer elsewhere (including Windows).

    Args:
        seconds: Maximum duration in seconds

    Raises:
        TimeoutError: If operation takes longer than specified seconds

    Example:
        ```python
        try:
            with timeout(60):
                # Long-running operation
                slow_function()
        except TimeoutError:
            print("Operation timed out!")
        ```

    Note:
        - Signal-based timeouts only work in the main thread on Unix
        - Thread-based timeouts work on all platforms but are less precise
        - Timeout does not forcefully kill threads, just raises exception
    """
    is_windows = platform.system() == "Windows"
    in_main_thread = threading.current_thread() is threading.main_thread()

    def _thread_timer_timeout() -> Generator[None, None, None]:
        """Timer-based fallback for worker threads or Windows."""

        timer = None
        timed_out = threading.Event()

        def timeout_handler() -> None:
            timed_out.set()

        timer = threading.Timer(seconds, timeout_handler)
        timer.daemon = True
        timer.start()

        try:
            yield
            if timed_out.is_set():
                raise TimeoutError(f"Operation timed out after {seconds} seconds")
        finally:
            if timer is not None:
                timer.cancel()

    if is_windows or not in_main_thread:
        # Windows or worker threads: use timer-based timeout
        yield from _thread_timer_timeout()

    else:
        # Use signal-based timeout for Unix-like systems
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")

        # Save old handler
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)

        try:
            yield
        finally:
            # Restore old handler and cancel alarm
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


@contextlib.contextmanager
def optional_timeout(seconds: int | None) -> Generator[None, None, None]:
    """
    Context manager with optional timeout (for backward compatibility).

    Args:
        seconds: Maximum duration in seconds, or None to disable timeout

    Example:
        ```python
        with optional_timeout(60):  # 60 second timeout
            slow_function()

        with optional_timeout(None):  # No timeout
            slow_function()
        ```
    """
    if seconds is None or seconds <= 0:
        # No timeout - just yield
        yield
    else:
        with timeout(seconds):
            yield
