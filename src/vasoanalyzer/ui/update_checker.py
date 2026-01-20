"""Background update-check orchestration for the VasoAnalyzer UI."""

from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PyQt5.QtWidgets import QDialog

log = logging.getLogger(__name__)

_API_URL = "https://api.github.com/repos/vr-oj/VasoAnalyzer/releases/latest"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "VasoAnalyzer Update Checker",
}
_TIMEOUT_MS = 5000


class UpdateChecker(QObject):
    """Dispatch update checks via QNetworkAccessManager and emit results via Qt signals."""

    completed = pyqtSignal(bool, object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: Optional[QNetworkReply] = None
        self._timer: Optional[QTimer] = None
        self._dialog: Optional[QDialog] = None
        self._in_progress = False
        self._current_version: str | None = None
        self._current_silent = False
        self._init_timeout_timer()

    def _init_timeout_timer(self) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_timeout)
        self._timer = timer

    @property
    def is_running(self) -> bool:
        return self._in_progress

    def set_dialog(self, dialog: QDialog | None) -> None:
        self._dialog = dialog

    def start(self, current_version: str, *, silent: bool = False) -> bool:
        if self._in_progress:
            return False

        self._current_version = current_version
        self._current_silent = silent

        self._cleanup_reply()

        request = QNetworkRequest(QUrl(_API_URL))
        for key, value in _HEADERS.items():
            request.setRawHeader(key.encode("ascii"), value.encode("ascii"))

        self._reply = self._nam.get(request)
        self._reply.finished.connect(self._on_reply_finished, Qt.QueuedConnection)
        self._in_progress = True
        if self._timer is not None:
            self._timer.start(_TIMEOUT_MS)
        return True

    def _cleanup_reply(self) -> None:
        if self._reply is None:
            return
        if self._timer is not None:
            self._timer.stop()
        try:
            self._reply.finished.disconnect(self._on_reply_finished)
        except TypeError:
            pass
        try:
            self._reply.abort()
        except Exception:
            log.debug("Update reply abort failed", exc_info=True)
        self._reply.deleteLater()
        self._reply = None
        self._in_progress = False

    def _on_timeout(self) -> None:
        if self._reply is None:
            return
        try:
            self._reply.abort()
        except Exception:
            log.debug("Update reply abort failed on timeout", exc_info=True)

    def _on_reply_finished(self) -> None:
        reply = self._reply
        self._reply = None
        self._in_progress = False
        if self._timer is not None:
            self._timer.stop()

        if reply is None:
            return

        latest: str | None = None
        error: BaseException | None = None

        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        status_code = int(status) if status is not None else None
        if reply.error() != QNetworkReply.NoError:
            log.info("Update check failed: %s", reply.errorString())
        elif status_code == 200:
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                latest_version = payload.get("tag_name")
                if (
                    isinstance(latest_version, str)
                    and latest_version
                    and latest_version != self._current_version
                ):
                    latest = latest_version
            except (ValueError, TypeError) as exc:
                log.info("Update check returned invalid JSON: %s", exc)
        elif status_code == 304:
            pass
        else:
            log.info("Update check skipped (status=%s)", status_code)

        reply.deleteLater()
        self.completed.emit(self._current_silent, latest, error)

    def shutdown(self) -> None:
        self._in_progress = False
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        self._cleanup_reply()

        if self._dialog is not None:
            self._dialog.close()
            self._dialog.deleteLater()
            self._dialog = None

        try:
            self.completed.disconnect()
        except TypeError:
            pass
