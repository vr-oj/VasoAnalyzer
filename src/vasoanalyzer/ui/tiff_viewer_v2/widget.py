# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Main widget for the TIFF viewer v2."""

from __future__ import annotations

from typing import Sequence

import math

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .controller import StackPlayerController
from .transport_bar import TiffTransportBar
from .frame_cache import FrameCache, qimage_cache_key
from .frame_view import FrameView, coerce_qimage
from .page_time_map import PageTimeMap
from .stack_source import InMemoryStackSource, StackSource


class TiffStackViewerWidget(QtWidgets.QWidget):
    """Qt-only TIFF stack viewer widget (v2)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TiffStackViewerV2")
        self._source: StackSource | None = None
        self._page_time_map: PageTimeMap | None = None
        self._cache = FrameCache.from_env()
        self._rotation_key = 0
        self._base_pps = 30.0
        self._speed_multiplier = 1.0

        self.controller = StackPlayerController(self)

        self.status_label = QtWidgets.QLabel("Sync unavailable: no data", self)
        self.status_label.setObjectName("SnapshotStatusLabel")
        self.status_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.status_label.setContentsMargins(0, 0, 0, 0)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )

        self.frame_view = FrameView(self)
        self.frame_view.setObjectName("SnapshotPreview")
        self.frame_view.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        self.controls = TiffTransportBar(self)

        header = QtWidgets.QFrame(self)
        header.setObjectName("TiffViewerHeader")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(6, 2, 6, 2)
        header_layout.setSpacing(4)
        header_layout.addWidget(self.status_label, 1)
        header_layout.addStretch(1)
        self.controls.speed_pill.setParent(header)
        header_layout.addWidget(self.controls.speed_pill, 0)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(header)
        layout.addWidget(self.frame_view, 1)
        layout.addWidget(self.controls)

        self.controls.frameRequested.connect(self._on_frame_requested)
        self.controls.playToggled.connect(self.controller.set_playing)
        self.controls.speedChanged.connect(self._on_speed_multiplier_changed)

        self.controller.page_changed.connect(self._on_page_changed)
        self.controller.playing_changed.connect(self.controls.set_playing)
        self.controller.mapped_time_changed.connect(self._on_mapped_time_changed)

        self.controls.set_controls_enabled(False)

    def set_source(
        self,
        source: StackSource | Sequence | np.ndarray | None,
        page_time_map: PageTimeMap | None = None,
    ) -> None:
        if source is None:
            self._source = None
        elif isinstance(source, StackSource):
            self._source = source
        elif isinstance(source, np.ndarray):
            if source.ndim <= 2:
                frames = [source]
            else:
                frames = list(source)
            self._source = InMemoryStackSource(frames)
        else:
            self._source = InMemoryStackSource(source)

        if page_time_map is None:
            page_time_map = PageTimeMap.invalid("Sync unavailable: no mapping")
        self._page_time_map = page_time_map

        if self._cache is not None:
            self._cache.clear()
        self.controller.set_source(self._source, self._page_time_map)
        self.controls.set_page_count(self.controller.page_count)
        self._update_status_label()
        self._update_sync_availability()
        self._update_time_readout(self.controller.current_index or 0)

        if self.controller.page_count == 0:
            self.frame_view.clear()

    def clear(self) -> None:
        empty_map = PageTimeMap.invalid("Sync unavailable: no data")
        self.set_source(None, page_time_map=empty_map)

    @property
    def sync_enabled(self) -> bool:
        return bool(self.controller.sync_enabled)

    def set_stack_source(
        self,
        source: StackSource | Sequence | np.ndarray | None,
        page_time_map: PageTimeMap | None = None,
    ) -> None:
        self.set_source(source, page_time_map=page_time_map)

    def set_pps(self, pps: float) -> None:
        try:
            base_pps = float(pps)
        except (TypeError, ValueError):
            return
        base_pps = max(1.0, base_pps)
        self._base_pps = base_pps
        self._apply_playback_rate()

    def set_speed_multiplier(self, multiplier: float) -> None:
        try:
            value = float(multiplier)
        except (TypeError, ValueError):
            value = 1.0
        if value <= 0:
            value = 1.0
        self._speed_multiplier = value
        self.controls.set_speed_multiplier(value)
        self._apply_playback_rate()

    def set_loop(self, loop: bool) -> None:
        self.controller.set_loop(loop)

    def set_playing(self, playing: bool) -> None:
        self.controller.set_playing(playing)

    def set_sync_enabled(self, enabled: bool) -> None:
        self.controller.set_sync_enabled(enabled)
        self._update_sync_availability()

    def jump_to_page(self, page_index: int, *, source: str = "external") -> bool:
        return self.controller.jump_to_page(page_index, source=source)

    def jump_to_time(self, t_seconds: float, *, source: str = "external") -> bool:
        return self.controller.jump_to_time(t_seconds, source=source)

    def _on_frame_requested(self, index: int) -> None:
        self._stop_playback_for_manual_action()
        self.controller.jump_to_page(index, source="transport")

    def _on_speed_multiplier_changed(self, multiplier: float) -> None:
        try:
            value = float(multiplier)
        except (TypeError, ValueError):
            value = 1.0
        if value <= 0:
            value = 1.0
        self._speed_multiplier = value
        self._apply_playback_rate()

    def _on_page_changed(self, index: int, source: str) -> None:
        self.controls.set_page_index(index)
        self._render_page(index)
        self._update_time_readout(index)

    def _on_mapped_time_changed(self, mapped_time) -> None:
        self._update_time_readout(self.controller.current_index or 0, mapped_time)

    def _stop_playback_for_manual_action(self) -> None:
        if self.controller.playing:
            self.controller.set_playing(False)

    def _render_page(self, index: int) -> None:
        if self._source is None:
            self.frame_view.clear()
            return
        key = qimage_cache_key(index, self._rotation_key)
        qimage = self._cache.get(key) if self._cache is not None else None
        if qimage is None:
            frame = self._source.get_frame(index)
            qimage = coerce_qimage(frame) if frame is not None else None
            if qimage is not None and self._cache is not None:
                self._cache.set(key, qimage)
        self.frame_view.set_frame(qimage)

    def _update_status_label(self) -> None:
        if self.controller.page_count <= 0:
            self.status_label.setText("No TIFF loaded")
            return
        if self._page_time_map is None:
            self.status_label.setText("Sync unavailable: no mapping")
            return
        status = (self._page_time_map.status or "").strip()
        if not status:
            if self._page_time_map.valid:
                status = f"TIFF mapped: {self._page_time_map.page_count} frames"
            else:
                status = "Sync unavailable"
        elif self._page_time_map.valid:
            status = f"TIFF mapped: {self._page_time_map.page_count} frames"
        self.status_label.setText(status)

    def _update_sync_availability(self) -> None:
        if self._page_time_map is None or not self._page_time_map.valid:
            self.controller.set_sync_enabled(False)
            return
        if not self.controller.sync_enabled:
            self.controller.set_sync_enabled(True)

    def _apply_playback_rate(self) -> None:
        self.controller.set_pps(self._base_pps * self._speed_multiplier)

    def _update_time_readout(self, index: int, mapped_time: float | None = None) -> None:
        count = self.controller.page_count
        if count <= 0:
            self.controls.set_time_readout("No TIFF loaded")
            return
        current = None
        if isinstance(mapped_time, (int, float)):
            current = float(mapped_time)
        elif self._page_time_map is not None and self._page_time_map.valid:
            current = self._page_time_map.time_for_page(index)
        total = None
        if self._page_time_map is not None and self._page_time_map.valid:
            times = self._page_time_map.page_times
            if times:
                total = float(times[-1])
        text = _format_time_readout(index, count, current, total)
        self.controls.set_time_readout(text)


__all__ = ["TiffStackViewerWidget"]


def _format_time_readout(
    index: int, total_frames: int, current: float | None, total: float | None
) -> str:
    frame_text = f"Frame {index + 1} / {total_frames}"
    if current is None or not math.isfinite(float(current)):
        return frame_text
    if total is None or not math.isfinite(float(total)):
        return f"{frame_text}   {float(current):.2f} s"
    return f"{frame_text}   {float(current):.2f} s / {float(total):.2f} s"
