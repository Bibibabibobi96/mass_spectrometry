"""Audit identity, aperture, clock and state continuity for one S2 particle run."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev



def _read_rows(path: Path) -> dict[int, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    indexed = {int(row["particle_id"]): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate particle_id in {path}")
    return indexed


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"unsupported boolean value: {value}")


def audit(source_path: Path, event_path: Path, contract_path: Path) -> dict:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    candidate = contract["functional_candidate"]
    source = _read_rows(source_path)
    events = _read_rows(event_path)
    expected_count = int(candidate["source_particles"])
    if len(source) != expected_count or set(source) != set(events):
        raise ValueError("S2 source and output particle identity sets differ")

    registration = contract["nominal_registration"]
    source_center = [float(value) for value in registration["source_exit_center_instrument_mm"]]
    target_center = [float(value) for value in registration["target_entry_center_instrument_mm"]]
    aperture = contract["passive_connector_geometry"]["downstream_entry_aperture"]
    half_y = float(aperture["full_width_y_mm"]) / 2
    half_z = float(aperture["full_height_z_mm"]) / 2
    tolerances = candidate["audit_tolerances"]
    plane_tolerance = float(tolerances["plane_residual_mm"])
    clock_tolerance = float(tolerances["clock_residual_us"])
    energy_tolerance = float(tolerances["energy_velocity_relative_residual"])

    maximum_source_plane_residual = 0.0
    maximum_target_plane_residual = 0.0
    maximum_clock_residual = 0.0
    maximum_energy_residual = 0.0
    maximum_transmitted_abs_y = 0.0
    maximum_transmitted_abs_z_offset = 0.0
    minimum_lost_aperture_excess = math.inf
    minimum_elapsed = math.inf
    maximum_elapsed = 0.0
    transmitted = 0
    lost = 0

    for particle_id, source_row in source.items():
        event = events[particle_id]
        if event["frame_id"] != source_row["frame_id"]:
            raise ValueError("S2 frame_id changed across the connector")
        if event["clock_epoch_id"] != source_row["clock_epoch_id"]:
            raise ValueError("S2 clock_epoch_id changed across the connector")
        if float(event["mass_amu"]) != float(source_row["mass_amu"]):
            raise ValueError("S2 particle mass changed without a reaction")
        if int(float(event["charge_state"])) != int(float(source_row["charge_state"])):
            raise ValueError("S2 particle charge changed without a reaction")

        source_residual = abs(float(source_row["position_x_mm"]) - source_center[0])
        target_residual = abs(float(event["position_x_mm"]) - target_center[0])
        maximum_source_plane_residual = max(maximum_source_plane_residual, source_residual)
        maximum_target_plane_residual = max(maximum_target_plane_residual, target_residual)

        elapsed = float(event["last_component_elapsed_time_us"])
        minimum_elapsed = min(minimum_elapsed, elapsed)
        maximum_elapsed = max(maximum_elapsed, elapsed)
        for output_name, source_name in (
            ("instrument_time_us", "instrument_time_us"),
            ("lineage_age_us", "lineage_age_us"),
            ("particle_age_us", "particle_age_us"),
        ):
            residual = abs(
                float(event[output_name]) - float(source_row[source_name]) - elapsed
            )
            maximum_clock_residual = max(maximum_clock_residual, residual)

        energy = kinetic_energy_ev(
            float(event["mass_amu"]),
            *(float(event[name]) for name in (
                "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"
            )),
        )
        recorded_energy = float(event["kinetic_energy_eV"])
        relative_energy_residual = abs(energy - recorded_energy) / recorded_energy
        maximum_energy_residual = max(maximum_energy_residual, relative_energy_residual)

        abs_y = abs(float(event["position_y_mm"]) - target_center[1])
        abs_z = abs(float(event["position_z_mm"]) - target_center[2])
        inside = abs_y <= half_y + plane_tolerance and abs_z <= half_z + plane_tolerance
        if event["status"] == "transmitted":
            transmitted += 1
            if (
                event["event"] != "oatof_entry"
                or not inside
                or not _parse_bool(event["first_forward_oatof_entry"])
            ):
                raise ValueError("transmitted S2 particle is not inside the oa entry aperture")
            maximum_transmitted_abs_y = max(maximum_transmitted_abs_y, abs_y)
            maximum_transmitted_abs_z_offset = max(maximum_transmitted_abs_z_offset, abs_z)
        elif event["status"] == "lost":
            lost += 1
            if (
                event["event"] != "downstream_entry_wall"
                or inside
                or _parse_bool(event["first_forward_oatof_entry"])
            ):
                raise ValueError("lost S2 particle does not identify the downstream entry wall")
            minimum_lost_aperture_excess = min(
                minimum_lost_aperture_excess, max(abs_y - half_y, abs_z - half_z)
            )
        else:
            raise ValueError("unsupported S2 particle status")

    if maximum_source_plane_residual > plane_tolerance:
        raise ValueError("S2 source plane residual exceeds the contract")
    if maximum_target_plane_residual > plane_tolerance:
        raise ValueError("S2 target plane residual exceeds the contract")
    if maximum_clock_residual > clock_tolerance:
        raise ValueError("S2 clock continuity residual exceeds the contract")
    if maximum_energy_residual > energy_tolerance:
        raise ValueError("S2 velocity and kinetic energy are inconsistent")
    if transmitted < int(candidate["minimum_oatof_entry_crossings"]):
        raise ValueError("S2 transmitted count is below the functional minimum")

    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s2_particle_chain_audit",
        "status": "PASS",
        "particles": expected_count,
        "oatof_entry_crossings": transmitted,
        "downstream_entry_wall_losses": lost,
        "maximum_source_plane_residual_mm": maximum_source_plane_residual,
        "maximum_target_plane_residual_mm": maximum_target_plane_residual,
        "maximum_clock_residual_us": maximum_clock_residual,
        "maximum_energy_velocity_relative_residual": maximum_energy_residual,
        "maximum_transmitted_abs_y_mm": maximum_transmitted_abs_y,
        "maximum_transmitted_abs_z_offset_mm": maximum_transmitted_abs_z_offset,
        "minimum_lost_aperture_excess_mm": (
            minimum_lost_aperture_excess if lost else None
        ),
        "minimum_component_elapsed_time_us": minimum_elapsed,
        "maximum_component_elapsed_time_us": maximum_elapsed,
        "claim_limit": "Nominal RF-exit to oa-entry connector continuity only; no S2 qualification, pulse, downstream detector or Formal claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source, args.events, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "S2_PARTICLE_CHAIN_AUDIT=PASS "
        f"INPUT={result['particles']} ENTRY={result['oatof_entry_crossings']} "
        f"WALL_LOSS={result['downstream_entry_wall_losses']}"
    )


if __name__ == "__main__":
    main()
