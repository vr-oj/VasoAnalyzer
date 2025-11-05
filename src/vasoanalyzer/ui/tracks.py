"""Compatibility forwarders for channel track primitives."""

from __future__ import annotations

import warnings

from vasoanalyzer.ui.plots.channel_track import ChannelTrack, ChannelTrackSpec

__all__ = ["ChannelTrackSpec", "ChannelTrack"]

warnings.warn(
    "Importing from vasoanalyzer.ui.tracks is deprecated; use vasoanalyzer.ui.plots.channel_track",
    DeprecationWarning,
    stacklevel=2,
)
