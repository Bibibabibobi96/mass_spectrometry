"""Compile the Ion Processor native electrode schedule on the instrument clock."""
from __future__ import annotations

import math
from typing import Any


def derive_native_timing(baseline: dict[str, Any]) -> dict[str, Any]:
    """Compile author-selected LP switch alignment on the instrument clock.

    Eight ULPs of the computed half-cycle index cover phase arithmetic roundoff
    at an already-zero request; this is not a physical switching tolerance.
    Other consumers read the frozen result and never recompute alignment.
    """
    electric, clock, schedule = (baseline[key] for key in ("electric", "clock", "schedule"))
    frequency = electric["rf_frequency_hz"] * 1e-6
    phase_cycles = clock["rf_phase_rad"] / (2 * math.pi)
    requested = schedule["extraction_start_us"]
    delay = electric["rf_quench_delay_cycles"]
    alignment = electric["rf_quench_alignment"]
    if not isinstance(alignment, str) or alignment not in {"requested_time", "next_cosine_zero"}:
        raise ValueError("unsupported electric.rf_quench_alignment")
    if not all(math.isfinite(value) for value in (frequency, phase_cycles, requested, delay, clock["epoch_us"])) or frequency <= 0 or delay <= 0:
        raise ValueError("invalid native RF timing inputs")
    if alignment == "requested_time":
        primary = requested
        roundoff_us = 0
        policy = "requested_instrument_time_v1"
    else:
        if 2 * delay != round(2 * delay):
            raise ValueError("side RF zero switching requires a positive integer number of half-cycles")
        index = 2 * (frequency * (clock["epoch_us"] + requested) + phase_cycles) - .5
        if not math.isfinite(index):
            raise ValueError("native RF timing phase overflows its finite clock")
        roundoff = 8 * math.ulp(index)
        nearest = round(index)
        if abs(index - nearest) <= roundoff:
            primary = requested
        else:
            primary = (.25 + .5 * math.ceil(index) - phase_cycles) / frequency - clock["epoch_us"]
            if primary < requested:
                raise ValueError("derived primary RF quench precedes its requested time")
        roundoff_us = roundoff/(2*frequency)
        policy = "cosine_zero_at_or_after_requested_v1"
    pulse = primary + delay / frequency
    if not schedule["lift_end_us"] <= primary < pulse < schedule["terminal_us"]:
        raise ValueError("derived RF quench/pulse must follow lift and precede terminal time")
    return dict(schema_version=1, role="native_electrode_timing",
                policy=policy, requested_quench_us=requested,
                primary_quench_us=primary, side_quench_us=pulse, pulse_start_us=pulse,
                alignment_roundoff_us=roundoff_us)
