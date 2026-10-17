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
        ])
        if "direction" in beam:
            direction = beam["direction"]
            if not isinstance(direction, (list, tuple)) or len(direction) != 3:
                raise ValueError("standard beam direction must contain three components")
            lines.extend([
                f"    position = vector({beam['x']},{beam['y']},{beam['z']}),",
                f"    direction = vector({direction[0]},{direction[1]},{direction[2]}),",
                f"    ke = {beam['ke']},",
            ])
        else:
            lines.extend([
                f"    x = {beam['x']},", f"    y = {beam['y']},", f"    z = {beam['z']},",
                f"    ke = {beam['ke']},", f"    az = {beam['az']},", f"    el = {beam['el']},",
            ])
        lines.extend([
            f"    cwf = {beam['cwf']},", f"    color = {beam['color']}", f"  }}{comma}",
        ])
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_source_states(states: list[dict[str, Any]], *, significant_digits: int = 15) -> str:
    """Render workbench states; 17 digits preserve binary64, default 15 is legacy."""
    if isinstance(significant_digits, bool) or not isinstance(significant_digits, int) or significant_digits not in (15, 17):
        raise ValueError("source-state significant_digits must be 15 or 17")
    precision = f".{significant_digits}g"
    lines = ["return {"]
    for state in states:
        lines.append(
            f"  [{int(state['particle_id'])}]={{t={state['t']:{precision}},x={state['x']:{precision}},"
            f"y={state['y']:{precision}},z={state['z']:{precision}},vx={state['vx']:{precision}},"
            f"vy={state['vy']:{precision}},vz={state['vz']:{precision}},ke={state['ke']:{precision}}" + "},"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"
