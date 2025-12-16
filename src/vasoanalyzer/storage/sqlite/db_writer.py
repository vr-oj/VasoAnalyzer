"""Serialized SQLite writer service used for staging/snapshot consistency.

The writer owns a single ``sqlite3.Connection`` (``check_same_thread=False``)
and executes all submitted callables on a dedicated worker thread.  This
provides two guarantees needed by autosave/snapshot logic:

* Only one write transaction runs at a time (single-writer).
* Callers can wait for a barrier before creating a snapshot to ensure that
  no pending writes remain in the queue.

Usage:
    writer = DbWriter(db_path)
    writer.run(lambda conn: conn.execute("INSERT ..."))
    writer.barrier()  # Wait until the queue is empty
    writer.close()
"""

from __future__ import annotations

import queue
import sqlite3
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

__all__ = ["DbWriter", "WriterClosed"]


class WriterClosed(RuntimeError):
    """Raised when a submission is attempted after the writer is closed."""


class DbWriter:
    """Single-writer queue for SQLite connections."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        pragmas: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._queue: "queue.Queue[tuple[Future, Callable[[sqlite3.Connection], Any]]]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="DbWriter", daemon=True)
        self._lock = threading.RLock()
        self._owns_conn = connection is None

        if connection is not None:
            self.conn = connection
        else:
            self.conn = sqlite3.connect(self.db_path.as_posix(), check_same_thread=False)

        # Enforce deterministic pragmas for all connections the writer owns.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        if pragmas:
            for key, value in pragmas.items():
                try:
                    self.conn.execute(f"PRAGMA {key}={value}")
                except sqlite3.DatabaseError:
                    # Pragmas are best-effort; don't crash if unsupported.
                    continue

        self._closed = False
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def run(self, func: Callable[[sqlite3.Connection], Any]) -> Any:
        """Submit ``func`` to run on the writer thread and return its result."""

        future: Future = Future()
        if self._closed:
            future.set_exception(WriterClosed("Writer is closed"))
            raise WriterClosed("Writer is closed")

        self._queue.put((future, func))
        return future.result()

    def submit(self, func: Callable[[sqlite3.Connection], Any]) -> Future:
        """Submit ``func`` asynchronously and return the future."""

        future: Future = Future()
        if self._closed:
            future.set_exception(WriterClosed("Writer is closed"))
            return future

        self._queue.put((future, func))
        return future

    def barrier(self) -> None:
        """Block until all queued work has been processed."""

        self.run(lambda _conn: None)

    def write_lock(self):
        """Expose the lock so existing synchronous code can serialize writes."""

        return self._lock

    def close(self) -> None:
        """Shut down the worker thread and close the connection."""

        if self._closed:
            return
        self._closed = True
        sentinel: Future = Future()
        sentinel.set_result(None)
        self._queue.put((sentinel, lambda _conn: None))
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._owns_conn:
            try:
                self.conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Internal worker                                                    #
    # ------------------------------------------------------------------ #
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                future, func = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if future.done():
                # Sentinel or cancelled submission.
                continue

            try:
                with self._lock:
                    result = func(self.conn)
                future.set_result(result)
            except Exception as exc:  # pragma: no cover - tested indirectly
                future.set_exception(exc)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------ #
    # Context manager helpers                                            #
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "DbWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
