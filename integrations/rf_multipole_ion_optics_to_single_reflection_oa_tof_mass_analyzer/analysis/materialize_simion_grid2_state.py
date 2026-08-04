"""Materialize a canonical grid2 state from a SIMION interface trace."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common.contracts.component_particle_state import (
    csv_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev


TRACE_COLUMNS = [
    "particle_id", "instrument_time_us", "x", "y", "z",
    "vx", "vy", "vz", "ax", "ay", "energy",
]


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def materialize(template_path: Path, trace_path: Path, output_path: Path) -> int:
    """Join the reduced trace to its canonical source by particle identity."""
    validate_component_particle_state_csv(template_path)
    template_columns, template_rows = _read(template_path)
    trace_columns, trace_rows = _read(trace_path)
    if template_columns != csv_columns():
        raise ValueError("SIMION grid2 template columns differ")
    if trace_columns != TRACE_COLUMNS or not trace_rows:
        raise ValueError("SIMION grid2 trace columns differ or the trace is empty")
    template = {int(row["particle_id"]): row for row in template_rows}
    trace_ids = [int(row["particle_id"]) for row in trace_rows]
    if len(trace_ids) != len(set(trace_ids)) or not set(trace_ids) <= set(template):
        raise ValueError("SIMION grid2 trace identity is duplicate or unmapped")

    rows: list[dict[str, str]] = []
    for trace in trace_rows:
        state = dict(template[int(trace["particle_id"])])
        instrument_time = float(trace["instrument_time_us"])
        mass_amu = float(state["mass_amu"])
        velocity = tuple(float(trace[key]) for key in ("vx", "vy", "vz"))
        state.update({
            "source_component_id": (
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            ),
            "target_component_id": "single_reflection_oa_tof_mass_analyzer",
            "state_event": "local_accelerator_exit",
            "instrument_time_us": format(instrument_time, ".17g"),
            "lineage_age_us": format(
                instrument_time - float(state["lineage_birth_time_us"]), ".17g"
            ),
            "particle_age_us": format(
                instrument_time - float(state["particle_birth_time_us"]), ".17g"
            ),
            "last_component_elapsed_time_us": format(
                instrument_time - float(state["instrument_time_us"]), ".17g"
            ),
            "position_x_mm": trace["x"],
            "position_y_mm": trace["y"],
            "position_z_mm": trace["z"],
            "velocity_x_m_s": trace["vx"],
            "velocity_y_m_s": trace["vy"],
            "velocity_z_m_s": trace["vz"],
            "kinetic_energy_eV": format(
                kinetic_energy_ev(mass_amu, *velocity), ".17g"
            ),
        })
        rows.append(state)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    validate_component_particle_state_csv(output_path)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = materialize(args.template, args.trace, args.output)
    print(f"SIMION_GRID2_CANONICAL=PASS PARTICLES={count}")


if __name__ == "__main__":
    main()
