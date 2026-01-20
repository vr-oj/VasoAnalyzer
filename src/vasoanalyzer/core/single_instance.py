"""Single-instance coordination and file-open helpers for VasoAnalyzer."""

from __future__ import annotations

import json
import logging
import os
import sys
import weakref
from pathlib import Path
from typing import Iterable, Sequence

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QMessageBox

if sys.platform == "win32":
    DEFAULT_SERVER_NAME = "vasoanalyzer_single_instance"
else:
    DEFAULT_SERVER_NAME = "com.vasoanalyzer.single_instance"

log = logging.getLogger(__name__)

_pending_paths: list[str] = []
_window_ref: weakref.ReferenceType | None = None
_manager_ref: weakref.ReferenceType | None = None
_ipc_warning: bool = False


def _normalize_vaso_path(path: str | os.PathLike[str] | None) -> str | None:
    """Normalize and validate candidate project paths."""
    if not path:
        return None

    candidate = Path(path).expanduser()
    if candidate.suffix.lower() != ".vaso":
        return None

    try:
        normalized = str(candidate.resolve())
    except Exception:
        normalized = str(candidate)
    return normalized


def _unique_pending_append(path: str) -> None:
    if path not in _pending_paths:
        _pending_paths.append(path)


def collect_vaso_paths(argv: Sequence[str]) -> list[str]:
    """
    Return existing .vaso paths from argv (ignoring argv[0]).

    Only existing files are returned to avoid spurious opens.
    """
    paths: list[str] = []
    for raw in list(argv)[1:]:
        normalized = _normalize_vaso_path(raw)
        if not normalized:
            continue

        if Path(normalized).exists():
            paths.append(normalized)
    return paths


def parse_ipc_message(payload: str) -> list[str]:
    """Parse a JSON IPC payload into normalized .vaso paths."""
    try:
        message = json.loads(payload)
    except json.JSONDecodeError:
        return []

    if not isinstance(message, dict):
        return []

    candidates = message.get("open", [])
    if not isinstance(candidates, list):
        return []

    parsed: list[str] = []
    for item in candidates:
        normalized = _normalize_vaso_path(str(item))
        if normalized:
            parsed.append(normalized)
    return parsed


def queue_open_requests(paths: Iterable[str]) -> None:
    """Queue .vaso paths to open once a window is available."""
    for path in paths:
        normalized = _normalize_vaso_path(path)
        if normalized:
            _unique_pending_append(normalized)


def _get_window():
    return _window_ref() if _window_ref else None


def _get_manager():
    return _manager_ref() if _manager_ref else None


def register_main_window(window) -> None:
    """Register the main window so queued opens can be dispatched."""
    global _window_ref
    _window_ref = weakref.ref(window)

    if _pending_paths:
        QTimer.singleShot(100, dispatch_pending_open_requests)


def register_window_manager(manager) -> None:
    """Register the window manager so queued opens can be dispatched."""
    global _manager_ref
    _manager_ref = weakref.ref(manager)

    if _pending_paths:
        QTimer.singleShot(100, dispatch_pending_open_requests)


def _open_on_window(window, path: str) -> None:
    if not Path(path).exists():
        QMessageBox.warning(
            window,
            "Project Not Found",
            f"The project file could not be found:\n{path}",
        )
        return

    try:
        window.open_recent_project(path)
    except Exception:
        log.exception("Failed to open project %s", path)
        QMessageBox.critical(
            window,
            "Project Load Error",
            f"Could not open project:\n{path}",
        )


def open_project_from_path(path: str) -> None:
    """
    Open a .vaso project or queue it until the main window is ready.

    This function centralizes the file-open pathway for CLI, IPC, and
    platform file-open events.
    """
    normalized = _normalize_vaso_path(path)
    if not normalized:
        log.debug("Ignoring non-.vaso path: %s", path)
        return

    manager = _get_manager()
    if manager is not None:
        manager.open_project(normalized)
        return

    window = _get_window()
    if window is None:
        _unique_pending_append(normalized)
        return

    _open_on_window(window, normalized)


def has_pending_open_requests() -> bool:
    return bool(_pending_paths)


def dispatch_pending_open_requests() -> None:
    """Flush queued opens once the main window is available."""
    manager = _get_manager()
    window = _get_window()
    if manager is None and window is None:
        return
    if not _pending_paths:
        return

    to_open = list(_pending_paths)
    _pending_paths.clear()
    for path in to_open:
        if manager is not None:
            manager.open_project(path)
        elif window is not None:
            _open_on_window(window, path)


class SingleInstanceManager(QObject):
    """Coordinate single-instance routing via QLocalServer/QLocalSocket."""

    def __init__(self, server_name: str | None = None) -> None:
        super().__init__()
        self.server_name = server_name or DEFAULT_SERVER_NAME
        self.server: QLocalServer | None = None

    def forward_to_primary(self, paths: Sequence[str]) -> bool:
        """
        If another instance is running, forward the open request and exit.

        Returns True when a primary instance was found and the current
        process should terminate.
        """
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(500):
            if paths:
                global _ipc_warning
                _ipc_warning = True
                log.warning(
                    "Could not reach running VasoAnalyzer instance; continuing as primary "
                    "to open requested projects"
                )
            return False

        payload = json.dumps({"open": list(paths or [])})
        socket.write(payload.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        log.info("Forwarded open request to existing VasoAnalyzer instance")
        return True

    def start_listening(self) -> None:
        """Start the IPC server to receive open requests."""
        QLocalServer.removeServer(self.server_name)
        server = QLocalServer(self)
        if not server.listen(self.server_name):
            log.warning("Could not start single-instance server: %s", server.errorString())
            return

        server.newConnection.connect(self._handle_new_connection)
        self.server = server
        log.debug("Single-instance server listening as %s", self.server_name)

    def _handle_new_connection(self) -> None:
        if not self.server:
            return

        socket = self.server.nextPendingConnection()
        if not socket:
            return

        socket.readyRead.connect(lambda s=socket: self._process_socket(s))
        socket.disconnected.connect(socket.deleteLater)

    def _process_socket(self, socket: QLocalSocket) -> None:
        try:
            raw = bytes(socket.readAll()).decode("utf-8", errors="ignore")
            paths = parse_ipc_message(raw)
            if paths:
                queue_open_requests(paths)
                dispatch_pending_open_requests()
        except Exception:
            log.exception("Failed to process single-instance message")
        finally:
            socket.disconnectFromServer()


def consume_ipc_warning() -> bool:
    """Return True once if IPC failed when forwarding to a primary instance."""
    global _ipc_warning
    flag = _ipc_warning
    _ipc_warning = False
    return flag
