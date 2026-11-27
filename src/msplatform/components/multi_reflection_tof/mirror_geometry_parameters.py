"""Derive analytic mirror boundaries from the frozen mechanical contract."""

from __future__ import annotations

from typing import Any

def derive_mirror_boundaries(mirror: dict[str, Any]) -> dict[str, list[float] | float]:
    """Return mechanical and analytic boundaries derived from one mirror contract.

    No axial coordinate is independently stored: all values come from the
    Stripe-facing shield, five CAD electrode thicknesses and four CAD gaps.
    """
    try:
        cursor = float(mirror["inner_face_z_mm"]) + float(mirror["grounded_inner_shield"]["thickness_z_mm"])
        thicknesses = [float(value) for value in mirror["electrode_thicknesses_mm"]]
        gaps = [float(value) for value in mirror["inter_electrode_gaps_mm"]]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("mirror mechanical parameters are incomplete") from error
    if len(thicknesses) != 5 or len(gaps) != 4 or min(thicknesses) <= 0.0 or min(gaps) <= 0.0:
        raise ValueError("mirror needs five positive thicknesses and four positive gaps")
    starts: list[float] = []
    for index, thickness in enumerate(thicknesses):
        starts.append(cursor)
        cursor += thickness
        if index < len(gaps):
            cursor += gaps[index]
    # Berdnikov's ideal planar model has neither the physical 4-mm-slot A
    # cover nor a finite outer E cover.  It starts its grounded A segment at
    # z=0; the first 0-V step is therefore a no-op.  The later step locations
    # retain the measured axial stack, referenced to that central plane.
    transitions = [0.0] + [starts[index] - gaps[index - 1] / 2.0 for index in range(1, 5)]
    e_active_end = starts[-1] + thicknesses[-1]
    return {
        "active_start_z_mm": starts,
        "active_end_z_mm": [start + thickness for start, thickness in zip(starts, thicknesses)],
        "analytic_transition_z_mm": transitions,
        "physical_E_active_end_z_mm": e_active_end,
        # The physical E cover starts at this plane and continues into metal.
        # Its inner face, not its external face, bounds the mirror vacuum and
        # is therefore Berdnikov's terminal-electrode plane L_e.
        "terminal_electrode_plane_z_mm": e_active_end,
        "E_midpoint_z_mm": (starts[-1] + e_active_end) / 2.0,
    }
