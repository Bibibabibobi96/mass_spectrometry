"""Audit the S1 COMSOL-to-SIMION state seam without rerunning either solver.

The canonical CSV remains the physical authority.  SIMION ION rows and row
indices are treated only as derived adapter data and are decoded back into the
canonical global frame for an independent comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re

from common.contracts.particle_physics import kinetic_energy_ev

try:
    from rf_handoff_adapter import (
        decode_simion_accelerator_velocity,
    )
except ModuleNotFoundError:
    from projects.oa_tof.analysis.rf_handoff_adapter import (
        decode_simion_accelerator_velocity,
    )
PULSE_CONTRACT = re.compile(
    r"handoff_pulse_contract mode=(\d+) time_us=([-+0-9.eE]+) "
    r"width_us=([-+0-9.eE]+)"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_ion(path: Path) -> list[list[float]]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            values = [float(value) for value in line.split(",")]
            if len(values) != 11:
                raise ValueError("S1 SIMION ION row must contain exactly 11 values")
            rows.append(values)
    return rows


def relative_residual(left: float, right: float, scale: float = 1.0) -> float:
    return abs(left - right) / max(abs(left), abs(right), scale)


decode_simion_instance3_velocity = decode_simion_accelerator_velocity


def audit(
    entry_path: Path,
    local_events_path: Path,
    canonical_path: Path,
    ion_path: Path,
    row_map_path: Path,
    downstream_path: Path,
    handoff_metadata_path: Path,
    run_config_path: Path,
    source_run_config_path: Path,
    simion_stdout_path: Path,
) -> dict[str, object]:
    entries = {int(row["particle_id"]): row for row in read_csv(entry_path)}
    exits = {
        int(row["particle_id"]): row for row in read_csv(local_events_path)
        if row["event"] == "local_joint_exit" and row["status"] == "transmitted"
    }
    canonical = read_csv(canonical_path)
    ion = read_ion(ion_path)
    mapping = read_csv(row_map_path)
    downstream = read_csv(downstream_path)
    handoff = json.loads(handoff_metadata_path.read_text(encoding="utf-8"))
    run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    source_config = json.loads(source_run_config_path.read_text(encoding="utf-8"))

    counts = {len(exits), len(canonical), len(ion), len(mapping), len(downstream)}
    if len(counts) != 1 or not counts or next(iter(counts)) == 0:
        raise ValueError("S1 state-chain row counts are empty or inconsistent")
    particles = len(canonical)
    frames = {row["frame_id"] for row in entries.values()}
    epochs = {row["clock_epoch_id"] for row in entries.values()}
    if len(frames) != 1 or len(epochs) != 1:
        raise ValueError("S1 entry states must use one explicit frame and clock epoch")
    frame_id = next(iter(frames))
    epoch_id = next(iter(epochs))

    canonical_ids: list[int] = []
    maximum_position_residual_mm = 0.0
    maximum_velocity_residual_m_s = 0.0
    maximum_ion_velocity_relative_residual = 0.0
    maximum_energy_relative_residual = 0.0
    maximum_birth_time_residual_us = 0.0
    maximum_elapsed_time_residual_us = 0.0
    maximum_downstream_initial_position_residual_mm = 0.0
    maximum_downstream_initial_energy_residual_ev = 0.0
    maximum_detector_clock_residual_us = 0.0

    for offset, (state, map_row, ion_row, result_row) in enumerate(
        zip(canonical, mapping, ion, downstream), start=1
    ):
        particle_id = int(state["particle_id"])
        canonical_ids.append(particle_id)
        if particle_id not in exits or particle_id not in entries:
            raise ValueError("canonical S1 particle has no matching entry or local exit")
        event = exits[particle_id]
        entry = entries[particle_id]
        solver_index = int(map_row["solver_row_index"])
        if solver_index != offset or int(map_row["particle_id"]) != particle_id:
            raise ValueError("row_map is not the unique ordered solver-index adapter")
        if int(result_row["Ion"]) != solver_index:
            raise ValueError("downstream SIMION row does not match row_map")
        if state["frame_id"] != frame_id or state["clock_epoch_id"] != epoch_id:
            raise ValueError("canonical handoff silently changed frame or clock epoch")

        position = [float(state[f"position_{axis}_mm"]) for axis in "xyz"]
        event_position = [float(event[f"{axis}_mm"]) for axis in "xyz"]
        velocity = [float(state[f"velocity_{axis}_m_s"]) for axis in "xyz"]
        event_velocity = [float(event[f"v{axis}_m_s"]) for axis in "xyz"]
        maximum_position_residual_mm = max(
            maximum_position_residual_mm,
            *(abs(left - right) for left, right in zip(position, event_position)),
        )
        maximum_velocity_residual_m_s = max(
            maximum_velocity_residual_m_s,
            *(abs(left - right) for left, right in zip(velocity, event_velocity)),
        )

        mass_amu = float(state["mass_amu"])
        charge_state = int(float(state["charge_state"]))
        energy_ev = float(state["kinetic_energy_eV"])
        velocity_energy = kinetic_energy_ev(mass_amu, *velocity)
        maximum_energy_relative_residual = max(
            maximum_energy_relative_residual,
            relative_residual(velocity_energy, energy_ev, 1e-30),
        )

        birth_time, ion_mass, ion_charge, ion_x, ion_y, ion_z, azimuth, elevation, ion_energy, cwf, color = ion_row
        expected_adapter_values = (
            float(state["instrument_time_us"]), mass_amu, charge_state,
            *position, energy_ev,
        )
        actual_adapter_values = (
            birth_time, ion_mass, ion_charge, ion_x, ion_y, ion_z, ion_energy,
        )
        if any(relative_residual(left, right, 1.0) > 1e-12
               for left, right in zip(expected_adapter_values, actual_adapter_values)):
            raise ValueError("SIMION ION adapter changed canonical time, species, position or energy")
        if int(cwf) != 1 or int(color) != 3:
            raise ValueError("SIMION ION adapter uses an unexpected CWF or accelerator instance")
        decoded_velocity = decode_simion_instance3_velocity(
            ion_mass, ion_energy, azimuth, elevation)
        maximum_ion_velocity_relative_residual = max(
            maximum_ion_velocity_relative_residual,
            *(relative_residual(left, right, 1.0)
              for left, right in zip(velocity, decoded_velocity)),
        )

        mapped_birth = float(map_row["solver_birth_time_us"])
        maximum_birth_time_residual_us = max(
            maximum_birth_time_residual_us,
            abs(mapped_birth - birth_time),
            abs(float(map_row["instrument_time_us"]) - birth_time),
        )
        elapsed = float(state["instrument_time_us"]) - float(entry["instrument_time_us"])
        maximum_elapsed_time_residual_us = max(
            maximum_elapsed_time_residual_us,
            abs(float(state["last_component_elapsed_time_us"]) - elapsed),
            abs(float(state["lineage_age_us"]) - (float(entry["lineage_age_us"]) + elapsed)),
            abs(float(state["particle_age_us"]) - (float(entry["particle_age_us"]) + elapsed)),
        )

        initial_position = [float(result_row[name]) for name in ("X0Mm", "Y0Mm", "Z0Mm")]
        maximum_downstream_initial_position_residual_mm = max(
            maximum_downstream_initial_position_residual_mm,
            *(abs(left - right) for left, right in zip(position, initial_position)),
        )
        maximum_downstream_initial_energy_residual_ev = max(
            maximum_downstream_initial_energy_residual_ev,
            abs(float(result_row["EnergyEv"]) - energy_ev),
        )
        instrument_arrival = float(result_row["InstrumentTimeUs"])
        solver_elapsed = float(result_row["TofUs"])
        maximum_detector_clock_residual_us = max(
            maximum_detector_clock_residual_us,
            abs(instrument_arrival - (birth_time + solver_elapsed)),
        )

    pulse_start = float(run_config["parameters"]["pulse_time_us"])
    pulse_width = float(run_config["parameters"]["pulse_width_us"])
    pulse_end = pulse_start + pulse_width
    source_parameters = source_config["parameters"]
    source_pulse_matches = (
        math.isclose(float(source_parameters["pulse_time_us"]), pulse_start, abs_tol=1e-12)
        and math.isclose(float(source_parameters["pulse_width_us"]), pulse_width, abs_tol=1e-12)
    )
    matches = PULSE_CONTRACT.findall(simion_stdout_path.read_text(encoding="utf-8-sig"))
    actual_pulse_matches = len(matches) == 1 and int(matches[0][0]) == 1 and (
        math.isclose(float(matches[0][1]), pulse_start, abs_tol=1e-9)
        and math.isclose(float(matches[0][2]), pulse_width, abs_tol=1e-12)
    )
    exit_times = [float(state["instrument_time_us"]) for state in canonical]
    exits_during_pulse = sum(pulse_start <= value < pulse_end for value in exit_times)

    checks = {
        "one_frame_and_clock_epoch": True,
        "unique_original_particle_ids": len(set(canonical_ids)) == particles,
        "local_exit_to_canonical_state_exact": (
            maximum_position_residual_mm <= 1e-12 and maximum_velocity_residual_m_s <= 1e-9
        ),
        "canonical_energy_matches_velocity": maximum_energy_relative_residual <= 1e-9,
        "ion_adapter_preserves_position_species_energy_and_birth_time": True,
        "ion_direction_decodes_to_global_velocity": maximum_ion_velocity_relative_residual <= 1e-12,
        "row_map_preserves_original_identity_and_absolute_birth_time": maximum_birth_time_residual_us <= 1e-12,
        "chain_ages_advance_once": maximum_elapsed_time_residual_us <= 1e-12,
        "downstream_initial_state_matches_ion_adapter": (
            maximum_downstream_initial_position_residual_mm <= 1e-12
            and maximum_downstream_initial_energy_residual_ev <= 1e-9
        ),
        "detector_instrument_time_equals_birth_plus_solver_elapsed": maximum_detector_clock_residual_us <= 1e-9,
        "source_and_downstream_use_same_pulse": source_pulse_matches and actual_pulse_matches,
        "handoff_is_identity_without_projection": (
            handoff["transform"]["kind"] == "identity"
            and handoff["transform"]["position_projection_applied"] is False
        ),
        "same_absolute_clock_continues_downstream": (
            run_config["parameters"]["solver_clock"] == "instrument_time"
            and handoff["pulse"]["downstream_waveform_must_continue_on_shared_clock"] is True
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_state_chain_physics_audit",
        "status": status,
        "scope": "functional state, coordinate and clock continuity; no numerical convergence or Formal performance claim",
        "particles": particles,
        "coordinate_chain": {
            "authoritative_frame_id": frame_id,
            "rule": "S1 uses the oaTOF global frame directly; ION positions remain global while direction angles are the derived instance-3 adapter",
            "maximum_local_exit_to_canonical_position_residual_mm": maximum_position_residual_mm,
            "maximum_local_exit_to_canonical_velocity_residual_m_s": maximum_velocity_residual_m_s,
            "maximum_ion_decoded_velocity_relative_residual": maximum_ion_velocity_relative_residual,
            "maximum_downstream_initial_position_residual_mm": maximum_downstream_initial_position_residual_mm,
            "position_projection_applied": False,
        },
        "identity_and_time": {
            "clock_epoch_id": epoch_id,
            "unique_original_particle_ids": len(set(canonical_ids)),
            "maximum_birth_time_residual_us": maximum_birth_time_residual_us,
            "maximum_chain_age_residual_us": maximum_elapsed_time_residual_us,
            "maximum_detector_clock_residual_us": maximum_detector_clock_residual_us,
        },
        "pulse_continuation": {
            "pulse_start_us": pulse_start,
            "pulse_end_us": pulse_end,
            "exits_during_same_pulse": exits_during_pulse,
            "exits_total": particles,
            "source_and_runtime_pulse_contract_match": source_pulse_matches and actual_pulse_matches,
        },
        "state_diagnostics": {
            "maximum_energy_velocity_relative_residual": maximum_energy_relative_residual,
            "maximum_downstream_initial_energy_residual_eV": maximum_downstream_initial_energy_residual_ev,
        },
        "field_ownership": {
            "upstream": "COMSOL S1 joint field owns integration through the local_joint_exit event",
            "downstream": "SIMION oaTOF owns integration beginning from the identical state and absolute birth time",
            "seam_policy": "one state event, no spatial projection, no time rebase and no repeated pulse",
            "field_value_continuity_claimed": False,
        },
        "checks": checks,
        "physical_link_claim_allowed": False,
        "numerical_convergence_claim_allowed": False,
        "resolution_claim_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "entry", "local-events", "canonical", "ion", "row-map", "downstream",
        "handoff-metadata", "run-config", "source-run-config", "simion-stdout", "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.entry, args.local_events, args.canonical, args.ion, args.row_map,
        args.downstream, args.handoff_metadata, args.run_config,
        args.source_run_config, args.simion_stdout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"S1_STATE_CHAIN_AUDIT={result['status']} PARTICLES={result['particles']}")
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
