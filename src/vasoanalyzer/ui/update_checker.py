"""Background update-check orchestration for the VasoAnalyzer UI."""

from __future__ import annotations

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from vasoanalyzer.services.version import check_for_new_version


class _UpdateCheckSignals(QObject):
    """Signals emitted by a single update-check job."""

    finished = pyqtSignal(bool, object, object)


class _UpdateCheckJob(QRunnable):
    """QRunnable wrapper around :func:`check_for_new_version`."""

    def __init__(self, current_version: str, *, silent: bool) -> None:
        super().__init__()
        self._current_version = current_version
        self._silent = silent
        self.signals = _UpdateCheckSignals()

    def run(self) -> None:  # pragma: no cover - Qt runs this on a worker thread
        latest: str | None = None
        error: BaseException | None = None
        try:
            latest = check_for_new_version(self._current_version)
        except BaseException as exc:  # broad on purpose to avoid killing the thread
            error = exc
        try:
            self.signals.finished.emit(self._silent, latest, error)
        except RuntimeError:
            # Signals object may already be destroyed during app shutdown; ignore.
            pass


class UpdateChecker(QObject):
    """Dispatch update checks on a thread-pool and emit results via Qt signals."""

    completed = pyqtSignal(bool, object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._in_progress = False

    @property
    def is_running(self) -> bool:
        return self._in_progress

    def start(self, current_version: str, *, silent: bool = False) -> bool:
        if self._in_progress:
            return False

        job = _UpdateCheckJob(current_version, silent=silent)
        job.signals.finished.connect(self._handle_finished)
        self._pool.start(job)
        self._in_progress = True
        return True

    def _handle_finished(
        self, silent: bool, latest: str | None, error: BaseException | None
    ) -> None:
        self._in_progress = False
        self.completed.emit(silent, latest, error)
