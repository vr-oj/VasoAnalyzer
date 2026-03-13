# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""LRU cache for QImage frames (v2)."""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Hashable

from PyQt6 import QtGui

DEFAULT_QIMAGE_CACHE_MB = 512


def qimage_cache_key(page_index: int, rotation_key: int = 0) -> tuple[int, int]:
    return (int(page_index), int(rotation_key))


def _parse_cache_budget_mb() -> float:
    value = os.environ.get("VA_SNAPSHOT_QIMAGE_CACHE_MB", "").strip()
    if not value:
        return float(DEFAULT_QIMAGE_CACHE_MB)
    try:
        mb = float(value)
    except (TypeError, ValueError):
        return float(DEFAULT_QIMAGE_CACHE_MB)
    return max(0.0, mb)


def qimage_cache_budget_bytes() -> int:
    return int(round(_parse_cache_budget_mb() * 1024 * 1024))


def estimate_qimage_bytes(image: QtGui.QImage) -> int:
    if image is None or image.isNull():
        return 0
    try:
        size = int(image.byteCount())
    except Exception:
        size = 0
    if size <= 0:
        try:
            size = int(image.bytesPerLine()) * int(image.height())
        except Exception:
            size = 0
    if size <= 0:
        size = int(image.width()) * int(image.height()) * 4
    return max(0, size)


class FrameCache:
    """Simple byte-budgeted LRU cache for QImages."""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max(0, int(max_bytes))
        self._current_bytes = 0
        self._items: OrderedDict[Hashable, tuple[QtGui.QImage, int]] = OrderedDict()

    @classmethod
    def from_env(cls) -> FrameCache | None:
        budget = qimage_cache_budget_bytes()
        if budget <= 0:
            return None
        return cls(budget)

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def current_bytes(self) -> int:
        return self._current_bytes

    @property
    def item_count(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
        self._current_bytes = 0

    def get(self, key: Hashable) -> QtGui.QImage | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        image, _size = entry
        self._items.move_to_end(key)
        return image

    def set(self, key: Hashable, image: QtGui.QImage) -> bool:
        if self._max_bytes <= 0:
            return False
        size = estimate_qimage_bytes(image)
        if size <= 0 or size > self._max_bytes:
            return False
        existing = self._items.pop(key, None)
        if existing is not None:
            _, old_size = existing
            self._current_bytes = max(0, self._current_bytes - old_size)
        self._items[key] = (image, size)
        self._current_bytes += size
        self._evict()
        return True

    def _evict(self) -> None:
        while self._items and self._current_bytes > self._max_bytes:
            _, (_, size) = self._items.popitem(last=False)
            self._current_bytes = max(0, self._current_bytes - size)


__all__ = [
    "DEFAULT_QIMAGE_CACHE_MB",
    "FrameCache",
    "estimate_qimage_bytes",
    "qimage_cache_budget_bytes",
    "qimage_cache_key",
]
