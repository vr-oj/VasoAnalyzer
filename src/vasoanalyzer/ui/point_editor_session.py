"""Session state for the manual point editor."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from vasoanalyzer.core.audit import EditAction
from vasoanalyzer.core.trace_model import TraceModel, bridge_segment, find_neighbor


def _normalize_channel(channel: str) -> str:
    key = channel.strip().lower()
    if key in {"inner", "id"}:
        return "inner"
    if key in {"outer", "od"}:
        return "outer"
    raise ValueError(f"Unsupported channel: {channel}")


def _channel_label(channel: str) -> str:
    return "ID" if channel == "inner" else "OD"


@dataclass
class SessionSummary:
    channel: str
    point_count: int
    percent_of_trace: float
    action_count: int
    time_bounds: tuple[float, float]


class PointEditorSession(QObject):
    """Manage undoable point edits for a selected trace segment."""

    data_changed = pyqtSignal()
    selection_changed = pyqtSignal()
    undo_redo_changed = pyqtSignal(bool, bool)
    warning_emitted = pyqtSignal(str)

    def __init__(
        self,
        model: TraceModel,
        channel: str,
        time_window: tuple[float, float],
    ) -> None:
        super().__init__()
        self._model = model
        self._channel = _normalize_channel(channel)
        self._time: np.ndarray = model.time_full
        raw_full = model.inner_raw if self._channel == "inner" else model.outer_raw
        clean_base = (
            model.inner_full.copy()
            if self._channel == "inner"
            else (model.outer_full.copy() if model.outer_full is not None else None)
        )
        if raw_full is None or clean_base is None:
            raise ValueError(f"Channel {channel} not available for editing")
        self._raw_full: np.ndarray = raw_full
        self._clean_base: np.ndarray = clean_base

        self._connect_method = "linear"
        self._time_window = (
            min(float(time_window[0]), float(time_window[1])),
            max(float(time_window[0]), float(time_window[1])),
        )
        mask = (self._time >= self._time_window[0]) & (self._time <= self._time_window[1])
        indices = np.nonzero(mask)[0]
        self._visible_indices: np.ndarray = (
            indices if indices.size else np.arange(self._time.size, dtype=int)
        )
        self._selection: set[int] = set()

        self._base_clean: np.ndarray = self._clean_base.copy()
        self._working_clean: np.ndarray = self._clean_base.copy()
        self._pending_actions: list[EditAction] = []
        self._redo_stack: list[EditAction] = []

    # ------------------------------------------------------------------ properties
    @property
    def channel(self) -> str:
        return self._channel

    @property
    def channel_label(self) -> str:
        return _channel_label(self._channel)

    @property
    def connect_method(self) -> str:
        return self._connect_method

    @connect_method.setter
    def connect_method(self, value: str) -> None:
        method = str(value or "linear").lower()
        if method not in {"linear", "cubic"}:
            method = "linear"
        self._connect_method = method

    @property
    def time_window(self) -> tuple[float, float]:
        return self._time_window

    def selection(self) -> tuple[int, ...]:
        return tuple(sorted(self._selection))

    def has_selection(self) -> bool:
        return bool(self._selection)

    def selection_bounds(self) -> tuple[float, float] | None:
        if not self._selection:
            return None
        indices = self.selection()
        return float(self._time[indices[0]]), float(self._time[indices[-1]])

    def action_count(self) -> int:
        return len(self._pending_actions)

    def can_undo(self) -> bool:
        return bool(self._pending_actions)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def visible_indices(self) -> np.ndarray:
        return self._visible_indices.copy()

    def visible_times(self) -> np.ndarray:
        return cast(np.ndarray, self._time[self._visible_indices])

    def visible_raw(self) -> np.ndarray:
        return cast(np.ndarray, self._raw_full[self._visible_indices])

    def visible_clean(self) -> np.ndarray:
        return cast(np.ndarray, self._working_clean[self._visible_indices])

    def working_clean(self) -> np.ndarray:
        return self._working_clean

    # ------------------------------------------------------------------ selection helpers
    def clear_selection(self) -> None:
        if not self._selection:
            return
        self._selection.clear()
        self.selection_changed.emit()

    def set_selection(
        self, indices: Iterable[int], *, additive: bool = False, toggle: bool = False
    ) -> None:
        normalized = {int(idx) for idx in indices}
        if not normalized:
            return
        if toggle:
            for idx in normalized:
                if idx in self._selection:
                    self._selection.remove(idx)
                else:
                    self._selection.add(idx)
        elif additive:
            self._selection.update(normalized)
        else:
            self._selection = normalized
        self.selection_changed.emit()

    # ------------------------------------------------------------------ operations
    def delete_selection(self) -> EditAction | None:
        if not self._selection:
            return None
        return self._apply_operation("delete_points", self.selection())

    def restore_selection(self) -> EditAction | None:
        if not self._selection:
            return None
        return self._apply_operation("restore_points", self.selection())

    def connect_selection(self, *, method: str | None = None) -> EditAction | None:
        if not self._selection:
            return None
        chosen = (method or self._connect_method or "linear").lower()
        if chosen not in {"linear", "cubic"}:
            chosen = "linear"
        return self._apply_operation("connect_across", self.selection(), method=chosen)

    def _apply_operation(
        self,
        op: str,
        indices: Sequence[int],
        *,
        method: str | None = None,
    ) -> EditAction | None:
        unique_indices = sorted(dict.fromkeys(int(i) for i in indices))
        if not unique_indices:
            return None

        first = unique_indices[0]
        last = unique_indices[-1]
        params: dict[str, str] = {}

        span_seconds = float(self._time[last] - self._time[first])
        total_samples = max(len(self._time), 1)
        selection_fraction = len(unique_indices) / total_samples

        if span_seconds > 5.0:
            self.warning_emitted.emit(
                "You are editing a segment longer than 5 s. Consider leaving a gap."
            )
        if op == "delete_points" and selection_fraction > 0.01:
            self.warning_emitted.emit("Large deletion: more than 1% of the trace is selected.")

        if op == "connect_across":
            params["method"] = method or self._connect_method
            forbidden = set(unique_indices)
            left_idx = find_neighbor(
                self._working_clean, start=first - 1, step=-1, forbidden=forbidden
            )
            right_idx = find_neighbor(
                self._working_clean, start=last + 1, step=+1, forbidden=forbidden
            )
            if left_idx is None or right_idx is None:
                params["fallback"] = "nan"
        action = EditAction(
            channel=self._channel,
            op=op,
            indices=tuple(unique_indices),
            t_bounds=(float(self._time[first]), float(self._time[last])),
            params=params,
        )
        self._pending_actions.append(action)
        self._apply_to_working(action)
        self._redo_stack.clear()
        self.data_changed.emit()
        self.undo_redo_changed.emit(self.can_undo(), self.can_redo())
        return action

    def _apply_to_working(self, action: EditAction) -> None:
        indices = np.fromiter(action.indices, dtype=int)
        if action.op == "delete_points":
            self._working_clean[indices] = np.nan
            return
        if action.op == "restore_points":
            self._working_clean[indices] = self._raw_full[indices]
            return
        if action.op != "connect_across":
            return

        fallback = str(action.params.get("fallback", "")).lower()
        if fallback == "nan":
            self._working_clean[indices] = np.nan
            return

        forbidden = {int(i) for i in indices.tolist()}
        left_idx = find_neighbor(
            self._working_clean, start=int(indices[0]) - 1, step=-1, forbidden=forbidden
        )
        right_idx = find_neighbor(
            self._working_clean, start=int(indices[-1]) + 1, step=+1, forbidden=forbidden
        )
        if left_idx is None or right_idx is None:
            self._working_clean[indices] = np.nan
            self.warning_emitted.emit("Connect fallback: segment touches trace edge.")
            return

        bridged = bridge_segment(
            self._time,
            self._working_clean,
            self._raw_full,
            indices,
            left_idx=left_idx,
            right_idx=right_idx,
            method=str(action.params.get("method", "linear")),
            forbidden=forbidden,
        )
        self._working_clean[indices] = bridged

    # ------------------------------------------------------------------ undo/redo
    def undo(self) -> EditAction | None:
        if not self._pending_actions:
            return None
        action = self._pending_actions.pop()
        self._redo_stack.append(action)
        self._rebuild_working()
        self.data_changed.emit()
        self.undo_redo_changed.emit(self.can_undo(), self.can_redo())
        return action

    def redo(self) -> EditAction | None:
        if not self._redo_stack:
            return None
        action = self._redo_stack.pop()
        self._pending_actions.append(action)
        self._apply_to_working(action)
        self.data_changed.emit()
        self.undo_redo_changed.emit(self.can_undo(), self.can_redo())
        return action

    def _rebuild_working(self) -> None:
        self._working_clean = self._base_clean.copy()
        for action in self._pending_actions:
            self._apply_to_working(action)

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        self._pending_actions.clear()
        self._redo_stack.clear()
        self._working_clean = self._base_clean.copy()
        self.data_changed.emit()
        self.undo_redo_changed.emit(False, False)

    def commit(self) -> tuple[EditAction, ...]:
        actions = tuple(self._pending_actions)
        if actions:
            self._base_clean = self._working_clean.copy()
        self._pending_actions = []
        self._redo_stack = []
        self.undo_redo_changed.emit(False, False)
        return actions

    def summary(self) -> SessionSummary:
        total_points = sum(action.count for action in self._pending_actions)
        total_samples = max(len(self._time), 1)
        percent = float(total_points) / float(total_samples)
        if self._pending_actions:
            first_time = min(action.t_bounds[0] for action in self._pending_actions)
            last_time = max(action.t_bounds[1] for action in self._pending_actions)
        else:
            first_time, last_time = self._time_window
        return SessionSummary(
            channel=self.channel_label,
            point_count=total_points,
            percent_of_trace=percent,
            action_count=len(self._pending_actions),
            time_bounds=(first_time, last_time),
        )
