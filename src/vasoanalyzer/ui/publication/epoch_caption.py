"""Caption builder utilities for epoch timeline overlays."""

from __future__ import annotations

from collections import defaultdict

from vasoanalyzer.ui.publication.epoch_model import Epoch

__all__ = ["build_epoch_legend"]


def build_epoch_legend(epochs: list[Epoch], *, greyscale: bool = False) -> str:
    """Generate figure legend text describing epoch overlays.

    Args:
        epochs: List of epochs to describe
        greyscale: Whether export is in greyscale mode (use pattern descriptions)

    Returns:
        Legend text describing the epochs

    Examples:
        >>> epochs = [
        ...     Epoch(id="1", channel="Drug", label="U-46619 25 nM", ...),
        ...     Epoch(id="2", channel="Blocker", label="BaCl₂ 100 μM", ...),
        ... ]
        >>> build_epoch_legend(epochs)
        "Horizontal bars denote drug application (blue, U-46619 25 nM) and BaCl₂ (red, 100 μM)."
    """
    if not epochs:
        return ""

    # Group epochs by channel
    channel_groups: dict[str, list[Epoch]] = defaultdict(list)
    for epoch in epochs:
        channel_groups[epoch.channel].append(epoch)

    # Build legend parts
    parts: list[str] = []

    # Pressure setpoints
    if "Pressure" in channel_groups:
        pressure_epochs = channel_groups["Pressure"]
        values = sorted(set(e.label for e in pressure_epochs))
        if greyscale:
            parts.append(f"Step boxes denote pressure levels ({', '.join(values)})")
        else:
            parts.append(f"Step boxes denote pressure levels ({', '.join(values)})")

    # Drugs
    if "Drug" in channel_groups:
        drug_epochs = channel_groups["Drug"]
        drug_names = ", ".join(set(e.label for e in drug_epochs))
        if greyscale:
            parts.append(f"Solid bars denote drug application ({drug_names})")
        else:
            parts.append(f"Horizontal bars denote drug application (blue, {drug_names})")

    # Blockers
    if "Blocker" in channel_groups:
        blocker_epochs = channel_groups["Blocker"]
        blocker_names = ", ".join(set(e.label for e in blocker_epochs))
        if greyscale:
            parts.append(f"Dashed bars denote blockers ({blocker_names})")
        else:
            parts.append(f"Horizontal bars denote blockers (red, {blocker_names})")

    # Perfusate
    if "Perfusate" in channel_groups:
        perfusate_epochs = channel_groups["Perfusate"]
        perfusate_names = ", ".join(set(e.label for e in perfusate_epochs))
        if greyscale:
            parts.append(f"Shaded regions denote perfusate changes ({perfusate_names})")
        else:
            parts.append(f"Shaded regions denote perfusate changes ({perfusate_names})")

    # Custom channels
    if "Custom" in channel_groups:
        custom_epochs = channel_groups["Custom"]
        custom_names = ", ".join(set(e.label for e in custom_epochs))
        parts.append(f"Custom markers: {custom_names}")

    # Combine parts
    if len(parts) == 1:
        return parts[0] + "."
    elif len(parts) == 2:
        return f"{parts[0]} and {parts[1]}."
    else:
        return "; ".join(parts[:-1]) + f"; and {parts[-1]}."


def build_compact_legend(epochs: list[Epoch]) -> str:
    """Generate compact legend for space-constrained figures.

    Args:
        epochs: List of epochs to describe

    Returns:
        Compact legend text

    Examples:
        >>> build_compact_legend(epochs)
        "Bars: U-46619 (blue), BaCl₂ (red). Shaded: Ca²⁺-free PSS."
    """
    if not epochs:
        return ""

    # Group by style
    bars = [e for e in epochs if e.style == "bar"]
    boxes = [e for e in epochs if e.style == "box"]
    shades = [e for e in epochs if e.style == "shade"]

    parts: list[str] = []

    if bars:
        bar_names = ", ".join(set(e.label for e in bars))
        parts.append(f"Bars: {bar_names}")

    if boxes:
        box_names = ", ".join(set(e.label for e in boxes))
        parts.append(f"Boxes: {box_names}")

    if shades:
        shade_names = ", ".join(set(e.label for e in shades))
        parts.append(f"Shaded: {shade_names}")

    return ". ".join(parts) + "." if parts else ""


def format_epoch_summary(epochs: list[Epoch]) -> str:
    """Generate a summary line for epoch count and types.

    Args:
        epochs: List of epochs to summarize

    Returns:
        Summary text

    Examples:
        >>> format_epoch_summary(epochs)
        "5 epochs: 2 pressure steps, 1 drug, 1 blocker, 1 perfusate"
    """
    if not epochs:
        return "No epochs"

    # Count by channel
    channel_counts: dict[str, int] = defaultdict(int)
    for epoch in epochs:
        channel_counts[epoch.channel] += 1

    # Build summary
    parts = []
    channel_labels = {
        "Pressure": "pressure steps",
        "Drug": "drugs" if channel_counts.get("Drug", 0) > 1 else "drug",
        "Blocker": "blockers" if channel_counts.get("Blocker", 0) > 1 else "blocker",
        "Perfusate": "perfusate changes" if channel_counts.get("Perfusate", 0) > 1 else "perfusate",
        "Custom": "custom",
    }

    for channel in ["Pressure", "Drug", "Blocker", "Perfusate", "Custom"]:
        count = channel_counts.get(channel, 0)
        if count > 0:
            parts.append(f"{count} {channel_labels[channel]}")

    summary = ", ".join(parts)
    total = len(epochs)

    return f"{total} epoch{'s' if total != 1 else ''}: {summary}"
