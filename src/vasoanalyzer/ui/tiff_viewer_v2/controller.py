# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Playback controller for the TIFF viewer v2."""

from __future__ import annotations

import time
from typing import Optional

from PyQt5 import QtCore

from .page_time_map import PageTimeMap
from .stack_source import StackSource


class StackPlayerController(QtCore.QObject):
    """Owns playback, timing, and page selection state."""

    page_changed = QtCore.pyqtSignal(int, str)
    playing_changed = QtCore.pyqtSignal(bool)
    mapped_time_changed = QtCore.pyqtSignal(object)

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._source: StackSource | None = None
        self._page_time_map: PageTimeMap | None = None
        self._current_index: int | None = None
        self._pps = 30.0
        self._loop = True
        self._playing = False
        self._sync_enabled = True
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_playback_tick)
        self._last_tick: float | None = None
        self._tick_accum = 0.0

    @property
    def page_count(self) -> int:
        return len(self._source) if self._source is not None else 0

    @property
    def current_index(self) -> int | None:
        return self._current_index

    @property
    def pps(self) -> float:
        return self._pps

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def sync_enabled(self) -> bool:
        return self._sync_enabled

    @property
    def page_time_map(self) -> PageTimeMap | None:
        return self._page_time_map

    def set_source(
        self,
        source: StackSource | None,
        page_time_map: PageTimeMap | None = None,
    ) -> None:
        self._source = source
        self._page_time_map = page_time_map
        self._current_index = 0 if self.page_count > 0 else None
        self._sync_enabled = True
        if page_time_map is not None and not page_time_map.valid:
            self._sync_enabled = False
        self._tick_accum = 0.0
        if self.page_count <= 0:
            self.set_playing(False)
        if self._current_index is not None:
            self._emit_page_changed("source")

    def set_pps(self, pps: float) -> None:
        try:
            value = float(pps)
        except (TypeError, ValueError):
            return
        value = max(1.0, value)
        if abs(value - self._pps) < 0.01:
            return
        self._pps = value
        if self._playing:
            self._restart_timer()

    def set_loop(self, loop: bool) -> None:
        self._loop = bool(loop)

    def set_sync_enabled(self, enabled: bool) -> None:
        if self._page_time_map is not None and not self._page_time_map.valid:
            self._sync_enabled = False
            return
        self._sync_enabled = bool(enabled)
        if self._sync_enabled:
            self._emit_mapped_time()

    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if playing == self._playing:
            return
        if playing and self.page_count <= 0:
            return
        self._playing = playing
        if playing:
            if self._current_index is None:
                self._current_index = 0
            self._restart_timer()
        else:
            self._timer.stop()
            self._last_tick = None
            self._tick_accum = 0.0
        self.playing_changed.emit(self._playing)

    def jump_to_page(self, index: int, *, source: str = "user") -> bool:
        if self.page_count <= 0:
            return False
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return False
        idx = max(0, min(idx, self.page_count - 1))
        if self._current_index == idx:
            return True
        self._current_index = idx
        self._emit_page_changed(source)
        return True

    def jump_to_time(self, t_seconds: float, *, source: str = "time") -> bool:
        if self._page_time_map is None or not self._page_time_map.valid:
            return False
        target = self._page_time_map.page_for_time(t_seconds)
        if target is None:
            return False
        return self.jump_to_page(target, source=source)

    def _restart_timer(self) -> None:
        interval_ms = max(1, int(round(1000.0 / max(1.0, self._pps))))
        self._last_tick = time.monotonic()
        self._tick_accum = 0.0
        self._timer.start(interval_ms)

    def _on_playback_tick(self) -> None:
        if not self._playing:
            return
        if self.page_count <= 0:
            self.set_playing(False)
            return
        now = time.monotonic()
        last = self._last_tick if self._last_tick is not None else now
        dt = max(0.0, now - last)
        self._last_tick = now
        self._tick_accum += dt * self._pps
        steps = int(self._tick_accum)
        if steps <= 0:
            return
        self._tick_accum -= steps
        self._advance_by(steps)

    def _advance_by(self, steps: int) -> None:
        if self._current_index is None:
            self._current_index = 0
        new_index = self._current_index + steps
        if self._loop:
            new_index = new_index % max(1, self.page_count)
        else:
            if new_index >= self.page_count:
                new_index = self.page_count - 1
                self.set_playing(False)
        if new_index != self._current_index:
            self._current_index = new_index
            self._emit_page_changed("playback")

    def _emit_page_changed(self, source: str) -> None:
        if self._current_index is None:
            return
        self.page_changed.emit(self._current_index, source)
        self._emit_mapped_time()

    def _emit_mapped_time(self) -> None:
        if not self._sync_enabled:
            self.mapped_time_changed.emit(None)
            return
        if self._page_time_map is None or not self._page_time_map.valid:
            self.mapped_time_changed.emit(None)
            return
        if self._current_index is None:
            self.mapped_time_changed.emit(None)
            return
        mapped = self._page_time_map.time_for_page(self._current_index)
        self.mapped_time_changed.emit(mapped)


__all__ = ["StackPlayerController"]
