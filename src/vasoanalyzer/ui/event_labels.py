"""Utilities for positioning event labels within the plot gutter."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from matplotlib.axes import Axes
from matplotlib.text import Text


class EventLabelGutter:
    """Manage vertical event labels placed inside a shared gutter axis."""

    _LANE_Y = (0.25, 0.75, 0.5)

    def __init__(
        self,
        axis: Axes,
        event_times: Iterable[float],
        event_labels: Iterable[str],
        *,
        lanes_initial: int = 2,
        min_gap_px: int = 22,
        fontsize: int = 8,
    ) -> None:
        self.axis = axis
        self.figure = axis.figure
        self._lanes_initial = max(int(lanes_initial), 1)
        self._min_gap_px = max(int(min_gap_px), 1)
        self._fontsize = fontsize
        self._texts: List[Text] = []
        self._cid_xlim: Optional[int] = None
        self._cid_resize: Optional[int] = None
        self._event_times = np.asarray(list(event_times), dtype=float)
        self._event_labels = list(event_labels)
        self._attach_callbacks()
        self._ensure_text_pool()
        self.layout()

    # ------------------------------------------------------------------ lifecycle
    def dispose(self) -> None:
        """Disconnect callbacks and remove owned artists."""

        if self._cid_xlim is not None:
            self.axis.callbacks.disconnect(self._cid_xlim)
            self._cid_xlim = None
        if self._cid_resize is not None and self.figure.canvas is not None:
            try:
                self.figure.canvas.mpl_disconnect(self._cid_resize)
            except Exception:
                pass
            self._cid_resize = None
        for text in self._texts:
            try:
                text.remove()
            except Exception:
                pass
        self._texts.clear()

    # ------------------------------------------------------------------ updates
    def set_events(
        self,
        event_times: Iterable[float],
        event_labels: Iterable[str],
    ) -> None:
        self._event_times = np.asarray(list(event_times), dtype=float)
        self._event_labels = list(event_labels)
        self._ensure_text_pool()
        self.layout()

    def set_min_gap(self, pixels: int) -> None:
        pixels = max(int(pixels), 1)
        if pixels == self._min_gap_px:
            return
        self._min_gap_px = pixels
        self.layout()

    def layout(self) -> None:
        """Recompute label placement within the gutter."""

        canvas = getattr(self.figure, "canvas", None)
        if canvas is None:
            return
        if self._event_times.size == 0 or not self._event_labels:
            for text in self._texts:
                text.set_visible(False)
            return

        zeros = np.zeros_like(self._event_times)
        xpix = self.axis.transData.transform(np.column_stack([self._event_times, zeros]))[:, 0]
        order = np.argsort(xpix)
        xpix_sorted = xpix[order]

        lanes = max(self._lanes_initial, 1)
        lane_last_px = [-1e9] * lanes
        lane_assignment = [-1] * len(self._event_times)
        lanes_used = lanes

        for sorted_idx, x in zip(order, xpix_sorted):
            placed = False
            for lane in range(lanes_used):
                if x - lane_last_px[lane] >= self._min_gap_px:
                    lane_assignment[sorted_idx] = lane
                    lane_last_px[lane] = x
                    placed = True
                    break
            if not placed and lanes_used < len(self._LANE_Y):
                lane = lanes_used
                lanes_used += 1
                lane_last_px.append(-1e9)
                lane_assignment[sorted_idx] = lane
                lane_last_px[lane] = x

        lane_y = self._lane_positions(lanes_used)
        transform = self.axis.get_xaxis_transform()
        for idx, text in enumerate(self._texts):
            if idx >= len(self._event_times) or idx >= len(self._event_labels):
                text.set_visible(False)
                continue
            lane = lane_assignment[idx] if idx < len(lane_assignment) else -1
            if lane == -1:
                text.set_visible(False)
                continue
            text.set_visible(True)
            text.set_position((float(self._event_times[idx]), lane_y[lane]))
            text.set_text(str(self._event_labels[idx]))
            text.set_transform(transform)

        # Matplotlib already schedules a redraw for the triggering event (e.g., xlim change),
        # so we avoid calling draw_idle() here to prevent recursive repaint loops.

    # ------------------------------------------------------------------ internals
    def _attach_callbacks(self) -> None:
        self._cid_xlim = self.axis.callbacks.connect("xlim_changed", self._on_view_changed)
        canvas = getattr(self.figure, "canvas", None)
        if canvas is not None:
            self._cid_resize = canvas.mpl_connect("resize_event", self._on_resize_event)

    def _ensure_text_pool(self) -> None:
        needed = len(self._event_times)
        transform = self.axis.get_xaxis_transform()
        while len(self._texts) < needed:
            text = self.axis.text(
                0.0,
                0.0,
                "",
                rotation=90,
                ha="center",
                va="center",
                transform=transform,
                fontsize=self._fontsize,
                bbox=dict(
                    fc="white",
                    ec="none",
                    alpha=0.6,
                    pad=0.2,
                ),
                visible=False,
                zorder=3,
            )
            self._texts.append(text)
        for idx in range(needed, len(self._texts)):
            self._texts[idx].set_visible(False)

    def _lane_positions(self, lanes_used: int) -> Tuple[float, ...]:
        if lanes_used <= 0:
            return tuple()
        capped = min(lanes_used, len(self._LANE_Y))
        return tuple(self._LANE_Y[i] for i in range(capped))

    # ------------------------------------------------------------------ callbacks
    def _on_view_changed(self, _axes) -> None:
        self.layout()

    def _on_resize_event(self, _event) -> None:
        self.layout()
