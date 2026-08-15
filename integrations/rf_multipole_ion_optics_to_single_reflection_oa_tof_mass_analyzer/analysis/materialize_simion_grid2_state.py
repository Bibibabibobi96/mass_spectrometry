"""Materialize a canonical grid2 state from a SIMION interface trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
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


def materialize(
    template_path: Path,
    trace_path: Path,
    output_path: Path,
    receipt_path: Path | None = None,
) -> int:
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
    maximum_energy_error_ev = 0.0
    for trace in trace_rows:
        state = dict(template[int(trace["particle_id"])])
        instrument_time = float(trace["instrument_time_us"])
        mass_amu = float(state["mass_amu"])
        velocity = tuple(float(trace[key]) for key in ("vx", "vy", "vz"))
        derived_energy = kinetic_energy_ev(mass_amu, *velocity)
        trace_energy = float(trace["energy"])
        if not math.isfinite(trace_energy) or not math.isclose(
            trace_energy, derived_energy, rel_tol=5e-8, abs_tol=5e-9
        ):
            raise ValueError(
                "SIMION grid2 trace energy differs from mass and velocity"
            )
        maximum_energy_error_ev = max(
            maximum_energy_error_ev, abs(trace_energy - derived_energy)
        )
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
            "kinetic_energy_eV": format(derived_energy, ".17g"),
        })
        rows.append(state)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    validate_component_particle_state_csv(output_path)
    if receipt_path is not None:
        receipt = {
            "schema_version": 1,
            "role": "rf_oatof_legacy_simion_grid2_materialization_receipt",
            "particle_count": len(rows),
            "trace_energy_validation": {
                "authority": "mass_and_velocity_derived_kinetic_energy",
                "relative_tolerance": 5e-8,
                "absolute_tolerance_eV": 5e-9,
                "maximum_absolute_error_eV": maximum_energy_error_ev,
                "status": "PASS",
            },
            "trace_field_authority": {
                "position_and_time": "grid2_crossing_linear_interpolation",
                "velocity": "current_solver_step_not_crossing_interpolated",
                "acceleration_x_y": "non_authoritative_legacy_trace_fields",
                "energy": "validated_only_then_recomputed_from_mass_and_velocity",
            },
            "limitations": [
                "legacy_grid2_velocity_is_current_step_not_crossing_interpolated"
            ],
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    count = materialize(args.template, args.trace, args.output, args.receipt)
    print(f"SIMION_GRID2_CANONICAL=PASS PARTICLES={count}")


if __name__ == "__main__":
    main()
