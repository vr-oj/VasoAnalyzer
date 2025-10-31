#!/usr/bin/env python3
"""Demonstration script for the event_labels module."""

from __future__ import annotations

import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for entry in (SRC, ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

def _make_events():
    return [
        (2.5, "System check"),
        (5.00, "Valve open"),
        (5.05, "Valve verify"),
        (8.2, "Operator note"),
        (10.0, "Pressure spike"),
        (12.00, "Sensor A trip"),
        (12.02, "Sensor B trip"),
        (12.08, "Sensor reset"),
        (15.6, "Cooldown start"),
        (18.4, "Maintenance note"),
        (22.3, "Flow adjusted"),
        (25.0, "Valve close"),
        (27.1, "Warning issued"),
        (32.0, "Operator note"),
        (35.5, "Calibration start"),
        (41.2, "Inspection"),
        (45.5, "Calibration done"),
        (48.0, "Alarm acknowledged"),
        (52.3, "Resume ops"),
        (55.0, "Shutdown sequence"),
    ]


def _make_signal():
    rng = np.random.default_rng(42)
    times = np.linspace(0, 60, 600)
    signal = (
        0.8 * np.sin(times / 3.0)
        + 0.2 * np.cos(times / 5.0)
        + 0.15 * rng.normal(size=times.size)
    )
    return times, signal


def plot_vertical(events, times, signal, event_labeler_cls, layout_options_cls):
    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(8, 4),
        gridspec_kw={"height_ratios": [2.0, 1.0], "hspace": 0.15},
    )
    ax_top.plot(times, signal, color="C0", linewidth=1.2)
    ax_bottom.plot(times, np.gradient(signal), color="C1", linewidth=1.0)

    ax_top.set_xlim(0, 60)
    ax_top.set_ylabel("Amplitude")
    ax_bottom.set_ylabel("d/dt")
    ax_bottom.set_xlabel("Time [s]")
    ax_top.set_title("Vertical (inside) event labels on shared X")

    options = layout_options_cls(min_px=22, max_labels_per_cluster=1, top_pad_axes=0.04)
    event_labeler_cls(ax_bottom, events, mode="vertical", options=options).draw()

    fig.align_ylabels((ax_top, ax_bottom))
    fig.savefig("vertical_inside.png", dpi=200)
    plt.close(fig)


def plot_horizontal(events, times, signal, event_labeler_cls, layout_options_cls):
    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(8, 4.2),
        gridspec_kw={"height_ratios": [2.0, 1.0], "hspace": 0.18},
    )
    ax_top.plot(times, signal, color="C0", linewidth=1.2)
    ax_bottom.plot(times, np.cos(times / 4.0), color="C2", linewidth=1.0)

    ax_top.set_xlim(0, 60)
    ax_top.set_ylabel("Amplitude")
    ax_bottom.set_ylabel("Reference")
    ax_bottom.set_xlabel("Time [s]")
    ax_top.set_title("Horizontal outside belt anchored to top axes")

    options = layout_options_cls(
        min_px=22,
        max_labels_per_cluster=1,
        max_lanes=3,
        outside_height_pct=14,
        outside_pad_in=0.18,
        outside_show_baseline=True,
        top_pad_axes=0.04,
    )
    event_labeler_cls(ax_bottom, events, mode="horizontal_outside", options=options).draw()

    fig.align_ylabels((ax_top, ax_bottom))
    fig.savefig("horizontal_outside.png", dpi=200)
    plt.close(fig)


def main():
    from vasoanalyzer.ui.event_labels import EventLabeler, LayoutOptions

    events = _make_events()
    times, signal = _make_signal()
    plot_vertical(events, times, signal, EventLabeler, LayoutOptions)
    plot_horizontal(events, times, signal, EventLabeler, LayoutOptions)


if __name__ == "__main__":
    main()
