# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Canonical snapshot viewer controller skeleton."""

from __future__ import annotations

import logging
import time
import weakref

import numpy as np
from PyQt5 import QtCore

try:
    _QPointer = QtCore.QPointer
except AttributeError:  # pragma: no cover - fallback for older PyQt builds
    _QPointer = None

try:  # pragma: no cover - best-effort guard
    import sip
except Exception:  # pragma: no cover
    sip = None

from .snapshot_data_source import SnapshotDataSource
from .snapshot_perf import log_perf, perf_enabled

log = logging.getLogger(__name__)


class SnapshotViewerController(QtCore.QObject):
    """Logic-only controller for snapshot viewing."""

    frame_changed = QtCore.pyqtSignal(object)
    enabled_changed = QtCore.pyqtSignal(bool)
    sync_mode_changed = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._trace_time_s: float | None = None
        self._event_time_s: float | None = None
        self._source: SnapshotDataSource | None = None
        self._widget_ref: object | None = None
        self._enabled = True
        self._sync_mode = "none"
        self._perf_last_update: float | None = None
        self._pending_time_s: float | None = None
        self._pending_source: str = ""
        self._flush_scheduled: bool = False
        self._scheduled_generation: int | None = None
        self._last_frame_index: int | None = None
        self._last_mode: str = "cursor"
        self._generation: int = 0
        self._flush_timer = QtCore.QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)

    def bind_widget(self, widget: QtCore.QObject | None) -> None:
        if widget is None:
            self._widget_ref = None
            return
        if _QPointer is not None:
            self._widget_ref = _QPointer(widget)
        else:
            self._widget_ref = weakref.ref(widget)

    def _widget_is_null(self) -> bool:
        widget = self._widget_ref
        if widget is None:
            return True
        if _QPointer is not None:
            return bool(widget.isNull())
        ref = widget()
        if ref is None:
            return True
        if sip is None:
            return False
        try:
            return bool(sip.isdeleted(ref))
        except Exception:
            return False

    def reset(self) -> None:
        self._bump_generation()
        self._pending_time_s = None
        self._pending_source = ""
        self._flush_scheduled = False
        self._scheduled_generation = None
        self._flush_timer.stop()
        self._last_frame_index = None

    def _bump_generation(self) -> None:
        self._generation += 1
        self._scheduled_generation = None
        self._flush_scheduled = False
        self._flush_timer.stop()

    def set_trace_time(self, t_seconds: float | None, *, source: str = "cursor") -> None:
        if t_seconds is None:
            self._trace_time_s = None
            self._update_sync_mode()
            return
        self._trace_time_s = float(t_seconds)
        self._update_sync_mode()
        if self._event_time_s is not None:
            return
        self._queue_pending(self._trace_time_s, source)

    def set_event_time(self, t_seconds: float | None, *, source: str = "event") -> None:
        if t_seconds is None:
            self._event_time_s = None
            self._update_sync_mode()
            if self._trace_time_s is not None:
                self._queue_pending(self._trace_time_s, "cursor")
            return
        self._event_time_s = float(t_seconds)
        # Keep trace time aligned to event selection for cursor fallback.
        self._trace_time_s = self._event_time_s
        self._update_sync_mode()
        self._queue_pending(self._event_time_s, source)

    def set_stack_source(self, source: SnapshotDataSource | None) -> None:
        self._source = source
        self._bump_generation()
        self._last_frame_index = None
        self._pending_time_s = None
        self._pending_source = ""
        if perf_enabled():
            if source is None:
                log_perf("source_set", source="none")
            else:
                source_kind = getattr(source, "source_kind", "unknown")
                frame_count = len(source) if hasattr(source, "__len__") else None
                log_perf(
                    "source_set",
                    source=type(source).__name__,
                    kind=source_kind,
                    frames=frame_count,
                )
        self._refresh_frame()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.enabled_changed.emit(enabled)
        if not enabled:
            self._pending_time_s = None
            self._pending_source = ""
            self._flush_scheduled = False
            self._last_frame_index = None
            self.frame_changed.emit(None)

    def _refresh_frame(self) -> None:
        if not self._enabled:
            return
        source = self._source
        if source is None:
            self.frame_changed.emit(None)
            return

        time_s = self._event_time_s if self._event_time_s is not None else self._trace_time_s
        if time_s is None:
            return
        mode = "event" if self._event_time_s is not None else "cursor"
        self._queue_pending(time_s, mode)

    def _queue_pending(self, time_s: float, source: str) -> None:
        self._pending_time_s = float(time_s)
        self._pending_source = str(source or "")
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        self._scheduled_generation = self._generation
        self._flush_timer.start(0)

    def _flush_pending(self, generation: int | None = None) -> None:
        self._flush_scheduled = False
        self._flush_timer.stop()
        if generation is None:
            generation = self._scheduled_generation or self._generation
        if generation != self._generation:
            return
        if not self._enabled:
            return
        source = self._source
        if source is None:
            self.frame_changed.emit(None)
            return

        pending_time = self._pending_time_s
        pending_source = self._pending_source
        self._pending_time_s = None
        self._pending_source = ""
        if pending_time is None:
            return

        total_start = time.perf_counter() if perf_enabled() else None
        get_start = time.perf_counter() if perf_enabled() else None
        frame_index = self._index_for_time(source, pending_time)
        if frame_index is not None and frame_index == self._last_frame_index:
            if self._pending_time_s is not None and not self._flush_scheduled:
                self._flush_scheduled = True
                QtCore.QTimer.singleShot(0, self._flush_pending)
            return

        frame = None
        if frame_index is not None:
            frame = self._frame_for_index(source, frame_index)
        if frame is None:
            frame = self._frame_for_time(source, pending_time)
        get_ms = None
        if get_start is not None:
            get_ms = (time.perf_counter() - get_start) * 1000.0

        if frame is not None:
            if not self._widget_is_null():
                widget_ref = self._widget_ref
                widget = widget_ref if _QPointer is not None else widget_ref()
                if widget is not None:
                    widget.set_frame(frame, frame_index=frame_index)
            self.frame_changed.emit(frame)
            if frame_index is not None:
                self._last_frame_index = frame_index

        if total_start is not None:
            total_ms = (time.perf_counter() - total_start) * 1000.0
            frame_shape = getattr(frame, "shape", None)
            frame_dtype = None
            if isinstance(frame, np.ndarray):
                frame_dtype = str(frame.dtype)
                if frame_shape is not None:
                    frame_shape = tuple(frame_shape)
            source_kind = getattr(source, "source_kind", "unknown")
            now = time.perf_counter()
            fps = None
            if self._perf_last_update is not None:
                delta = now - self._perf_last_update
                if delta > 0:
                    fps = round(1.0 / delta, 2)
            self._perf_last_update = now
            log_perf(
                "frame_update",
                get_ms=round(get_ms, 3) if get_ms is not None else None,
                total_ms=round(total_ms, 3),
                frame_shape=frame_shape,
                frame_dtype=frame_dtype,
                source_kind=source_kind,
                source=pending_source or None,
                frame_index=frame_index,
                fps=fps,
            )

        if self._pending_time_s is not None and not self._flush_scheduled:
            self._flush_scheduled = True
            self._scheduled_generation = self._generation
            self._flush_timer.start(0)

    def _frame_for_time(self, source: SnapshotDataSource, time_s: float):
        getter = getattr(source, "get_frame_at_time", None)
        if callable(getter):
            try:
                return getter(float(time_s))
            except Exception:
                log.debug(
                    "Snapshot data source get_frame_at_time failed", exc_info=True
                )
                return None

        # TODO: map time to frame index when only get_frame_at_index is available.
        return None

    def _frame_for_index(self, source: SnapshotDataSource, index: int):
        getter = getattr(source, "get_frame_at_index", None)
        if callable(getter):
            try:
                return getter(int(index))
            except Exception:
                log.debug(
                    "Snapshot data source get_frame_at_index failed", exc_info=True
                )
                return None
        return None

    def _index_for_time(self, source: SnapshotDataSource, time_s: float) -> int | None:
        getter = getattr(source, "index_for_time", None)
        if callable(getter):
            try:
                return getter(float(time_s))
            except Exception:
                log.debug(
                    "Snapshot data source index_for_time failed", exc_info=True
                )
                return None
        return None

    def _update_sync_mode(self) -> None:
        mode = "event" if self._event_time_s is not None else "cursor"
        if self._event_time_s is None and self._trace_time_s is None:
            mode = "none"
        if mode == self._sync_mode:
            return
        self._sync_mode = mode
        self._last_mode = mode
        self.sync_mode_changed.emit(mode)
