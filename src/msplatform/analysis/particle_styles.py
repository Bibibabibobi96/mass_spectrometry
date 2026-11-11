"""Shared deterministic visual styles for particle comparisons."""

from __future__ import annotations

from typing import Sequence


COLORS = (
    "#000000",
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#7F3C8D",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#6B6B6B",
    "#7A3E9D",
)
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "<", ">", "*")
COMPARISON_COLORS = COLORS
LINESTYLES = ("-", "--", "-.", ":")
MAX_AUTO_STYLE_SERIES = min(len(COMPARISON_COLORS), len(MARKERS))


def prepare_visual_style_map(labels: Sequence[str]) -> dict[str, dict[str, str]]:
    """Return deterministic, non-repeating styles for a readable combined figure."""

    ordered = sorted(labels)
    if any(not label for label in ordered) or len(set(ordered)) != len(ordered):
        raise ValueError("Plot series labels must be non-empty and unique.")
    if len(ordered) > MAX_AUTO_STYLE_SERIES:
        raise ValueError(
            "Combined figure exceeds the non-repeating automatic style capacity; "
            "split the comparison into smaller figure groups."
        )
    return {
        label: {
            "color": COMPARISON_COLORS[index],
            "marker": MARKERS[index],
            "linestyle": LINESTYLES[index % len(LINESTYLES)],
        }
        for index, label in enumerate(ordered)
    }
