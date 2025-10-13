"""Golden image regression tests for key plot configurations."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np
import pytest

from vasoanalyzer.ui.event_labels import EventLabeler, LayoutOptions

from tests._sample_data import event_tuples, snapshot_array, synthetic_time_series

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "golden_plots"


def _ensure_golden(name: str) -> Path:
    path = GOLDEN_DIR / name
    if not path.exists():
        pytest.skip(f"Golden image missing: {path}")
    return path


def _fig_to_array(fig) -> np.ndarray:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    array = plt.imread(buffer)
    if array.dtype != np.uint8:
        array = np.round(array * 255.0).astype(np.uint8)
    return array


def _load_golden(name: str) -> np.ndarray:
    golden = plt.imread(_ensure_golden(name))
    if golden.dtype != np.uint8:
        golden = np.round(golden * 255.0).astype(np.uint8)
    return golden


def _assert_images_close(actual: np.ndarray, expected: np.ndarray, tolerance: int = 4) -> Tuple[int, float]:
    if actual.shape != expected.shape:
        raise AssertionError(f"Image shapes differ: {actual.shape} vs {expected.shape}")
    diff = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
    max_diff = int(diff.max())
    mean_diff = float(diff.mean())
    assert max_diff <= tolerance, f"max pixel diff {max_diff} exceeds tolerance {tolerance}"
    return max_diff, mean_diff


def _render_full_trace():
    times, inner, outer = synthetic_time_series()
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=200)
    ax.plot(times, inner, label="Inner", color="#1D5CFF", linewidth=1.5)
    ax.plot(times, outer, label="Outer", color="#FF7C43", linewidth=1.1)
    ax.set_xlim(0, 60)
    ax.set_ylim(30, 55)
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Diameter [µm]")
    ax.grid(linewidth=0.3, alpha=0.4)
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig


def _render_zoom_event_labels():
    events = event_tuples()
    times, inner, _ = synthetic_time_series()
    gradient = np.gradient(inner)
    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(7.8, 4.4),
        dpi=200,
        gridspec_kw={"height_ratios": [2.0, 1.3], "hspace": 0.18},
    )
    ax_top.plot(times, inner, color="#008B8B", linewidth=1.35)
    ax_bottom.plot(times, gradient, color="#C75146", linewidth=1.1)
    ax_top.set_xlim(0, 35)
    ax_top.set_ylabel("Inner [µm]")
    ax_bottom.set_xlabel("Time [s]")
    ax_bottom.set_ylabel("Δ Inner")
    options = LayoutOptions(min_px=20, max_labels_per_cluster=1, top_pad_axes=0.04)
    EventLabeler(ax_bottom, events, mode="vertical", options=options).draw()
    fig.align_ylabels((ax_top, ax_bottom))
    return fig


def _render_snapshot_overlay():
    data = snapshot_array()
    fig, ax = plt.subplots(figsize=(4.2, 4.2), dpi=200)
    image = ax.imshow(data, cmap="magma", origin="lower")
    ax.contour(data, levels=6, colors="white", linewidths=0.6, alpha=0.6)
    positions = np.linspace(0.15, 0.85, len(event_tuples()))
    height = data.shape[0]
    for pos, (_, label) in zip(positions, event_tuples()):
        x = pos * data.shape[1]
        y = height * 0.85
        ax.scatter([x], [y], s=20, color="white", edgecolors="black", linewidths=0.3)
        ax.text(x, y - 6, label, color="white", ha="center", va="top", fontsize=7)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    return fig


@pytest.mark.parametrize(
    ("render", "golden_name"),
    [
        (_render_full_trace, "full_trace.png"),
        (_render_zoom_event_labels, "zoom_event_labels.png"),
        (_render_snapshot_overlay, "snapshot_overlay.png"),
    ],
)
def test_plot_matches_golden(render, golden_name):
    fig = render()
    actual = _fig_to_array(fig)
    expected = _load_golden(golden_name)
    max_diff, mean_diff = _assert_images_close(actual, expected)
    assert max_diff <= 4, f"{golden_name}: max diff {max_diff}, mean diff {mean_diff:.2f}"
