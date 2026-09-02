"""Parse MR-TOF Candidate SIMION event receipts without filtering losses."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Any


EVENT = re.compile(r"^MRTOF_EVENT\s+(?P<kind>\w+)\s+(?P<fields>.*)$")
FIELD = re.compile(r"(?P<key>[A-Za-z_]+)=(?P<value>[^\s]+)")


def parse_events(text: str) -> list[dict[str, Any]]:
    """Read only explicitly emitted Candidate events from a SIMION log."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = EVENT.match(line.strip())
        if not match:
            continue
        event: dict[str, Any] = {"kind": match.group("kind")}
        for field in FIELD.finditer(match.group("fields")):
            value = field.group("value")
            try:
                event[field.group("key")] = float(value)
            except ValueError:
                event[field.group("key")] = value
        events.append(event)
    return events


def _fwhm(times_us: list[float]) -> float | None:
    if len(times_us) < 8:
        return None
    low, high = min(times_us), max(times_us)
    if not high > low:
        return 0.0
    bin_count = max(8, min(128, int(math.sqrt(len(times_us)))))
    width = (high - low) / bin_count
    counts = [0] * bin_count
    for value in times_us:
        counts[min(bin_count - 1, int((value - low) / width))] += 1
    half = max(counts) / 2.0
    occupied = [index for index, count in enumerate(counts) if count >= half]
    return width * (occupied[-1] - occupied[0] + 1) if occupied else None


def summarize_events(events: list[dict[str, Any]], target_k: int = 25) -> dict[str, Any]:
    """Return an all-particle Candidate summary; no aperture or tail selection."""
    terminal = [event for event in events if event["kind"] == "terminal"]
    detector = [
        event
        for event in terminal
        if abs(float(event.get("y_mm", math.inf)) - 285.0) <= 5.0
    ]
    turns = [int(round(float(event.get("turns", 0)))) for event in terminal]
    oscillations = [value // 2 for value in turns]
    detected_times = [float(event["t_us"]) for event in detector if "t_us" in event]
    fwhm = _fwhm(detected_times)
    center_time = median(detected_times) if detected_times else None
    resolution = (
        center_time / (2.0 * fwhm)
        if center_time is not None and fwhm is not None and fwhm > 0.0
        else None
    )
    return {
        "schema_version": 1,
        "status": "candidate_not_formal",
        "particle_terminal_count": len(terminal),
        "detector_hit_count": len(detector),
        "detection_rate": len(detector) / len(terminal) if terminal else None,
        "target_k": target_k,
        "target_k_count": sum(value == target_k for value in oscillations),
        "target_k_fraction": (
            sum(value == target_k for value in oscillations) / len(terminal)
            if terminal
            else None
        ),
        "overtone_histogram": {
            str(value): oscillations.count(value) for value in sorted(set(oscillations))
        },
        "central_plane_crossing_count": sum(
            event["kind"] == "central_plane" for event in events
        ),
        "detector_tof_us": detected_times,
        "detector_tof_fwhm_us": fwhm,
        "detector_tof_median_us": center_time,
        "mass_resolution_t_over_2fwhm": resolution,
        "all_losses_retained": True,
    }


def analyze_log(log_path: Path, output_path: Path, target_k: int = 25) -> dict[str, Any]:
    """Parse a run log and write a stable JSON Candidate result receipt."""
    summary = summarize_events(parse_events(log_path.read_text(encoding="utf-8")), target_k)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
