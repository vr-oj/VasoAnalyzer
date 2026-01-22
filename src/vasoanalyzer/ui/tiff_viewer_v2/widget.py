# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Main widget for the TIFF viewer v2."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .controller import StackPlayerController
from .controls import ControlsStrip
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

        self.controller = StackPlayerController(self)

        self.status_label = QtWidgets.QLabel("Sync unavailable: no data", self)
        self.status_label.setObjectName("SnapshotStatusLabel")
        self.status_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.status_label.setContentsMargins(2, 0, 2, 0)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )

        self.frame_view = FrameView(self)
        self.frame_view.setObjectName("SnapshotPreview")
        self.frame_view.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        self.controls = ControlsStrip(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.status_label)
        layout.addWidget(self.frame_view, 1)
        layout.addWidget(self.controls)

        self.controls.prev_clicked.connect(self._on_prev_clicked)
        self.controls.next_clicked.connect(self._on_next_clicked)
        self.controls.play_toggled.connect(self.controller.set_playing)
        self.controls.page_changed.connect(self._on_slider_changed)
        self.controls.pps_changed.connect(self.controller.set_pps)
        self.controls.loop_toggled.connect(self.controller.set_loop)
        self.controls.sync_toggled.connect(self._on_sync_toggled)

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
        self.controls.speed_input.blockSignals(True)
        self.controls.speed_input.setValue(float(pps))
        self.controls.speed_input.blockSignals(False)
        self.controller.set_pps(pps)

    def set_loop(self, loop: bool) -> None:
        self.controls.loop_checkbox.blockSignals(True)
        self.controls.loop_checkbox.setChecked(bool(loop))
        self.controls.loop_checkbox.blockSignals(False)
        self.controller.set_loop(loop)

    def set_playing(self, playing: bool) -> None:
        self.controller.set_playing(playing)

    def set_sync_enabled(self, enabled: bool) -> None:
        self._on_sync_toggled(enabled)

    def jump_to_page(self, page_index: int, *, source: str = "external") -> bool:
        return self.controller.jump_to_page(page_index, source=source)

    def jump_to_time(self, t_seconds: float, *, source: str = "external") -> bool:
        return self.controller.jump_to_time(t_seconds, source=source)

    def _on_prev_clicked(self) -> None:
        self._stop_playback_for_manual_action()
        current = self.controller.current_index or 0
        self.controller.jump_to_page(current - 1, source="step")

    def _on_next_clicked(self) -> None:
        self._stop_playback_for_manual_action()
        current = self.controller.current_index or 0
        self.controller.jump_to_page(current + 1, source="step")

    def _on_slider_changed(self, index: int) -> None:
        self._stop_playback_for_manual_action()
        self.controller.jump_to_page(index, source="slider")

    def _on_sync_toggled(self, enabled: bool) -> None:
        self.controller.set_sync_enabled(enabled)
        self._update_sync_availability()

    def _on_page_changed(self, index: int, source: str) -> None:
        self.controls.set_page_index(index)
        self._render_page(index)

    def _on_mapped_time_changed(self, mapped_time) -> None:
        if mapped_time is None:
            self.controls.set_mapped_time_text("Synced: —")
            return
        try:
            value = float(mapped_time)
        except (TypeError, ValueError):
            self.controls.set_mapped_time_text("Synced: —")
            return
        self.controls.set_mapped_time_text(f"Synced: {value:.3f} s")

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
        if self._page_time_map is None:
            self.status_label.setText("Sync unavailable: no mapping")
            return
        status = (self._page_time_map.status or "").strip()
        if not status:
            if self._page_time_map.valid:
                status = f"Sync available ({self._page_time_map.page_count} pages mapped)"
            else:
                status = "Sync unavailable"
        self.status_label.setText(status)

    def _update_sync_availability(self) -> None:
        if self._page_time_map is None or not self._page_time_map.valid:
            self.controls.set_sync_checked(False)
            self.controls.set_sync_available(False)
            return
        self.controls.set_sync_available(True)
        self.controls.set_sync_checked(self.controller.sync_enabled)


__all__ = ["TiffStackViewerWidget"]
