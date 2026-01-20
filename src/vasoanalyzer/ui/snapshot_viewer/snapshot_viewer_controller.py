# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Canonical snapshot viewer controller skeleton."""

from __future__ import annotations

import logging
import os
import time
import weakref
from collections import deque

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
from .qimage_cache import qimage_cache_key
from .render_backends import coerce_qimage

log = logging.getLogger(__name__)

_DEFAULT_PREFETCH_FRAMES = 12
_DEFAULT_PREFETCH_INTERVAL_MS = 75
_DEFAULT_PLAYBACK_PPS = 30.0
_DEFAULT_PLAYBACK_TICK_HZ = 30.0


def _prefetch_window() -> int:
    value = os.environ.get("VA_SNAPSHOT_PREFETCH_FRAMES", "").strip()
    if not value:
        return _DEFAULT_PREFETCH_FRAMES
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return _DEFAULT_PREFETCH_FRAMES


def _prefetch_interval_ms() -> int:
    value = os.environ.get("VA_SNAPSHOT_PREFETCH_INTERVAL_MS", "").strip()
    if not value:
        return _DEFAULT_PREFETCH_INTERVAL_MS
    try:
        return max(50, int(value))
    except (TypeError, ValueError):
        return _DEFAULT_PREFETCH_INTERVAL_MS


def _resolve_default_playback_pps() -> float:
    value = os.environ.get("VA_SNAPSHOT_PPS", "").strip()
    if not value:
        return _DEFAULT_PLAYBACK_PPS
    try:
        pps = float(value)
    except (TypeError, ValueError):
        log.warning(
            "Invalid VA_SNAPSHOT_PPS=%s; using default %.1f PPS",
            value,
            _DEFAULT_PLAYBACK_PPS,
        )
        return _DEFAULT_PLAYBACK_PPS
    if not np.isfinite(pps) or pps <= 0:
        log.warning(
            "Invalid VA_SNAPSHOT_PPS=%s; using default %.1f PPS",
            value,
            _DEFAULT_PLAYBACK_PPS,
        )
        return _DEFAULT_PLAYBACK_PPS
    return pps


class SnapshotViewerController(QtCore.QObject):
    """Logic-only controller for snapshot viewing."""

    frame_changed = QtCore.pyqtSignal(object)
    page_changed = QtCore.pyqtSignal(int, str)
    enabled_changed = QtCore.pyqtSignal(bool)
    sync_mode_changed = QtCore.pyqtSignal(str)
    playing_changed = QtCore.pyqtSignal(bool)
    playback_time_changed = QtCore.pyqtSignal(float)

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
        self._playing = False
        self._playback_pps = _resolve_default_playback_pps()
        self._page_float = 0.0
        self._current_page = 0
        self._sync_enabled = True
        self._loop_enabled = False
        self._page_times: list[float] | None = None
        self._playback_last_log_time: float | None = None
        self._playback_elapsed_ms: int | None = None
        self._prefetch_window = _prefetch_window()
        self._prefetch_queue: deque[int] = deque()
        self._prefetch_pending: set[int] = set()
        self._prefetch_generation: int | None = None
        self._prefetch_interval_ms = _prefetch_interval_ms()
        self._playback_expected_ms: float | None = None
        self._playback_last_tick_ms: float | None = None
        self._playback_pending = False
        self._playback_clock = QtCore.QElapsedTimer()
        self._playback_timer = QtCore.QTimer(self)
        self._playback_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._playback_timer.setInterval(self._playback_interval_ms())
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._prefetch_timer = QtCore.QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setTimerType(QtCore.Qt.VeryCoarseTimer)
        self._prefetch_timer.setInterval(self._prefetch_interval_ms)
        self._prefetch_timer.timeout.connect(self._prefetch_next)
        self._flush_timer = QtCore.QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)

    def _playback_tick_hz(self) -> float:
        try:
            pps = float(self._playback_pps)
        except (TypeError, ValueError):
            pps = _DEFAULT_PLAYBACK_PPS
        if not np.isfinite(pps) or pps <= 0:
            pps = _DEFAULT_PLAYBACK_PPS
        return max(_DEFAULT_PLAYBACK_TICK_HZ, min(pps, 120.0))

    def _playback_interval_ms(self) -> int:
        tick_hz = self._playback_tick_hz()
        return max(1, int(round(1000.0 / tick_hz))) if tick_hz > 0 else 33

    def set_playback_pps(self, pps: float) -> None:
        try:
            value = float(pps)
        except (TypeError, ValueError):
            value = _DEFAULT_PLAYBACK_PPS
        if not np.isfinite(value) or value <= 0:
            value = _DEFAULT_PLAYBACK_PPS
        if self._playback_pps == value:
            return
        self._playback_pps = value
        self._playback_timer.setInterval(self._playback_interval_ms())

    def playback_pps(self) -> float:
        return float(self._playback_pps)

    def set_sync_enabled(self, enabled: bool) -> None:
        self._sync_enabled = bool(enabled)

    def sync_enabled(self) -> bool:
        return bool(self._sync_enabled)

    def set_loop_enabled(self, enabled: bool) -> None:
        """Enable or disable loop playback."""
        self._loop_enabled = bool(enabled)

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
        self._clear_prefetch()
        self.set_playing(False)
        self._playback_pending = False
        self._playback_last_tick_ms = None
        self._playback_expected_ms = None
        self._playback_elapsed_ms = None
        self._playback_last_log_time = None
        self._pending_time_s = None
        self._pending_source = ""
        self._flush_scheduled = False
        self._scheduled_generation = None
        self._flush_timer.stop()
        self._last_frame_index = None

    def _bump_generation(self) -> None:
        self._generation += 1
        self._clear_prefetch()
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

    def set_frame_index(self, index: int, *, source: str = "manual") -> None:
        """Render a specific frame index without time-based lookup."""
        if not self._enabled:
            return
        src = self._source
        if src is None:
            self.frame_changed.emit(None)
            return
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return
        if hasattr(src, "__len__"):
            try:
                total = len(src)
            except Exception:
                total = None
            if idx < 0 or (total is not None and idx >= total):
                return
        if source == "playback":
            self._playback_pending = True
        try:
            frame = self._frame_for_index(src, idx)
            if frame is None:
                return

            if not self._widget_is_null():
                widget = self._get_widget()
                if widget is not None:
                    widget.set_frame(frame, frame_index=idx)
            self.frame_changed.emit(frame)
            self._last_frame_index = idx
            self._current_page = int(idx)
            if source != "playback":
                self._page_float = float(idx)
            self.page_changed.emit(int(idx), str(source or ""))
            if self._playing:
                self._queue_prefetch(idx)
        finally:
            if source == "playback":
                self._playback_pending = False

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
        self.set_playing(False)
        self._source = source
        self._bump_generation()
        self._clear_prefetch()
        self._last_frame_index = None
        self._pending_time_s = None
        self._pending_source = ""
        self._page_times = self._extract_page_times(source)
        self._current_page = 0
        self._page_float = 0.0
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
            self.set_playing(False)
            self._clear_prefetch()
            self._playback_pending = False
            self._playback_last_tick_ms = None
            self._playback_expected_ms = None
            self._pending_time_s = None
            self._pending_source = ""
            self._flush_scheduled = False
            self._last_frame_index = None
            self.frame_changed.emit(None)

    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if self._playing == playing:
            return
        self._playing = playing
        if not playing:
            self._clear_prefetch()
            self._playback_pending = False
            self._playback_last_tick_ms = None
            self._playback_expected_ms = None
            self._playback_elapsed_ms = None
            self._playback_last_log_time = None
            if self._playback_timer.isActive():
                self._playback_timer.stop()
        else:
            self._playback_last_tick_ms = None
            self._playback_expected_ms = None
            if self._last_frame_index is not None:
                self._queue_prefetch(self._last_frame_index)
            self._page_float = float(self._current_page)
            self._playback_clock.start()
            self._playback_elapsed_ms = 0
            self._playback_timer.start()
        self.playing_changed.emit(bool(self._playing))

    def note_playback_tick(
        self,
        tick_ms: float | None,
        target_fps: float | None,
    ) -> None:
        if tick_ms is not None:
            self._playback_last_tick_ms = float(tick_ms)
        if target_fps is None:
            return
        try:
            fps = float(target_fps)
        except (TypeError, ValueError):
            return
        if fps > 0:
            self._playback_expected_ms = 1000.0 / fps

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
        if self._pending_source == "playback":
            self._playback_pending = True
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
            if pending_source == "playback":
                self._playback_pending = False
            return

        total_start = time.perf_counter() if perf_enabled() else None
        get_start = time.perf_counter() if perf_enabled() else None
        frame_index = self._index_for_time(source, pending_time)
        if frame_index is not None and frame_index == self._last_frame_index:
            if pending_source == "playback":
                self._playback_pending = False
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
                self._current_page = int(frame_index)
                self._page_float = float(frame_index)
                self.page_changed.emit(int(frame_index), str(pending_source or ""))
                if self._playing:
                    self._queue_prefetch(frame_index)
        if pending_source == "playback":
            self._playback_pending = False

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

    def _get_widget(self):
        if self._widget_is_null():
            return None
        widget_ref = self._widget_ref
        if widget_ref is None:
            return None
        return widget_ref if _QPointer is not None else widget_ref()

    def _prefetch_cache(self):
        widget = self._get_widget()
        if widget is None:
            return None
        getter = getattr(widget, "get_qimage_cache", None)
        if callable(getter):
            return getter()
        return getattr(widget, "cache", None)

    def _cache_key_for(self, frame_index: int) -> tuple[int, int] | None:
        widget = self._get_widget()
        rotation = getattr(widget, "rotation_deg", 0) if widget is not None else 0
        try:
            return qimage_cache_key(frame_index, rotation)
        except Exception:
            return None

    def _clear_prefetch(self) -> None:
        self._prefetch_queue.clear()
        self._prefetch_pending.clear()
        self._prefetch_generation = None
        if self._prefetch_timer.isActive():
            self._prefetch_timer.stop()

    def _queue_prefetch(self, frame_index: int) -> None:
        if not self._playing or self._prefetch_window <= 0:
            return
        source = self._source
        if source is None:
            return
        cache = self._prefetch_cache()
        if cache is None:
            return
        try:
            total = len(source)
        except Exception:
            total = None
        start = int(frame_index) + 1
        end = int(frame_index) + int(self._prefetch_window)
        if total is not None:
            end = min(end, total - 1)
        if start > end:
            return

        for idx in range(start, end + 1):
            if idx in self._prefetch_pending:
                continue
            key = self._cache_key_for(idx)
            if cache is not None and key is not None and cache.get(key) is not None:
                continue
            self._prefetch_pending.add(idx)
            self._prefetch_queue.append(idx)

        if self._prefetch_queue and not self._prefetch_timer.isActive():
            self._prefetch_generation = self._generation
            self._prefetch_timer.start(self._prefetch_interval_ms)

    def _playback_tick_late(self) -> bool:
        if self._playback_last_tick_ms is None or self._playback_expected_ms is None:
            return False
        return self._playback_last_tick_ms > (1.5 * self._playback_expected_ms)

    def _prefetch_next(self) -> None:
        if not self._playing:
            self._clear_prefetch()
            return
        if self._prefetch_generation is not None and self._prefetch_generation != self._generation:
            self._clear_prefetch()
            return
        source = self._source
        cache = self._prefetch_cache()
        if source is None or cache is None:
            self._clear_prefetch()
            return
        if self._playing and (self._playback_pending or self._playback_tick_late()):
            if self._prefetch_queue:
                self._prefetch_timer.start(self._prefetch_interval_ms)
            return

        while self._prefetch_queue:
            idx = self._prefetch_queue.popleft()
            self._prefetch_pending.discard(idx)
            key = self._cache_key_for(idx)
            if key is None:
                continue
            if cache.get(key) is not None:
                continue
            frame = self._frame_for_index(source, idx)
            if frame is None:
                break
            qimage = coerce_qimage(frame)
            if qimage is None:
                break
            cache.set(key, qimage)
            if perf_enabled():
                log_perf(
                    "prefetch",
                    frame_index=idx,
                    cache_bytes=cache.current_bytes,
                    cache_max=cache.max_bytes,
                )
            break

        if self._prefetch_queue:
            self._prefetch_timer.start(self._prefetch_interval_ms)

    def _extract_page_times(
        self, source: SnapshotDataSource | None
    ) -> list[float] | None:
        if source is None:
            return None
        frame_times = getattr(source, "frame_times", None)
        if frame_times is None:
            return None
        try:
            times = [float(v) for v in frame_times]
        except Exception:
            return None
        try:
            total = len(source)
        except Exception:
            total = None
        if total is not None and len(times) != total:
            return None
        if not times:
            return None
        if not all(np.isfinite(val) for val in times):
            return None
        for idx in range(1, len(times)):
            if times[idx] <= times[idx - 1]:
                return None
        return times

    def _page_count(self) -> int:
        source = self._source
        if source is None:
            return 0
        try:
            return len(source)
        except Exception:
            return 0

    def _emit_playback_sync(self, page_index: int) -> float | None:
        if not self._sync_enabled:
            return None
        if self._page_times is None:
            return None
        if page_index < 0 or page_index >= len(self._page_times):
            return None
        trace_time = float(self._page_times[page_index])
        self.playback_time_changed.emit(trace_time)
        return trace_time

    def _log_playback_tick(
        self, page_index: int, tick_ms: float | None, mapped_trace_time: float | None
    ) -> None:
        if not perf_enabled():
            return
        now = time.perf_counter()
        last_log = self._playback_last_log_time
        if last_log is not None and now - last_log < 1.0:
            return
        log_perf(
            "playback_tick",
            snapshot_pps=round(float(self._playback_pps), 3),
            current_page=int(page_index),
            mapped_trace_time=round(mapped_trace_time, 3)
            if mapped_trace_time is not None
            else None,
            tick_ms=round(float(tick_ms), 3) if tick_ms is not None else None,
        )
        self._playback_last_log_time = now

    def _on_playback_tick(self) -> None:
        if not self._playing:
            return
        total = self._page_count()
        if total <= 0:
            self.set_playing(False)
            return
        elapsed_ms = int(self._playback_clock.elapsed())
        if self._playback_elapsed_ms is None:
            self._playback_elapsed_ms = elapsed_ms
            return
        dt_ms = elapsed_ms - self._playback_elapsed_ms
        self._playback_elapsed_ms = elapsed_ms
        dt_s = max(0.0, float(dt_ms) / 1000.0)
        tick_hz = self._playback_tick_hz()
        self.note_playback_tick(dt_ms, tick_hz)

        try:
            page_float = float(self._page_float)
        except (TypeError, ValueError):
            page_float = float(self._current_page)
        page_float += float(self._playback_pps) * dt_s
        max_page = total - 1
        next_page = int(page_float)
        mapped_trace_time = None
        if next_page >= max_page:
            if self._loop_enabled:
                # Loop mode: reset to frame 0 and continue
                self._page_float = 0.0
                self.set_frame_index(0, source="playback")
                mapped_trace_time = self._emit_playback_sync(0)
                self._log_playback_tick(0, dt_ms, mapped_trace_time)
                # Do not stop - playback continues
            else:
                # Original behavior: stop at last frame
                page_float = float(max_page)
                self._page_float = page_float
                if max_page != self._current_page:
                    self.set_frame_index(max_page, source="playback")
                    mapped_trace_time = self._emit_playback_sync(max_page)
                else:
                    mapped_trace_time = (
                        float(self._page_times[max_page])
                        if self._page_times is not None
                        and self._sync_enabled
                        and 0 <= max_page < len(self._page_times)
                        else None
                    )
                self._log_playback_tick(max_page, dt_ms, mapped_trace_time)
                self.set_playing(False)
                return

        self._page_float = page_float
        if next_page != self._current_page:
            self.set_frame_index(next_page, source="playback")
            mapped_trace_time = self._emit_playback_sync(next_page)
        else:
            if (
                self._page_times is not None
                and self._sync_enabled
                and 0 <= self._current_page < len(self._page_times)
            ):
                mapped_trace_time = float(self._page_times[self._current_page])
        self._log_playback_tick(self._current_page, dt_ms, mapped_trace_time)

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
