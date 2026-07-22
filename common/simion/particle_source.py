"""Serialize prepared SIMION beams and exact source states without device assumptions."""

from __future__ import annotations

from typing import Any


def render_standard_beams(beams: list[dict[str, Any]]) -> str:
    """Render standard_beam records whose values are already in SIMION coordinates."""
    lines = ["particles {", "  coordinates = 0,"]
    for index, beam in enumerate(beams):
        comma = "," if index < len(beams) - 1 else ""
        lines.extend([
            "  standard_beam {", "    n = 1,", f"    tob = {beam['tob']},",
            f"    mass = {beam['mass']},", f"    charge = {beam['charge']},",
            f"    x = {beam['x']},", f"    y = {beam['y']},", f"    z = {beam['z']},",
            f"    ke = {beam['ke']},", f"    az = {beam['az']},", f"    el = {beam['el']},",
            f"    cwf = {beam['cwf']},", f"    color = {beam['color']}", f"  }}{comma}",
        ])
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_source_states(states: list[dict[str, Any]]) -> str:
    """Render source states after a device adapter has supplied workbench coordinates."""
    lines = ["return {"]
    for state in states:
        lines.append(
            f"  [{int(state['particle_id'])}]={{t={state['t']:.15g},x={state['x']:.15g},"
            f"y={state['y']:.15g},z={state['z']:.15g},vx={state['vx']:.15g},"
            f"vy={state['vy']:.15g},vz={state['vz']:.15g},ke={state['ke']:.15g}}},"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"
