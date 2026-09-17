"""Materialize and analyze the real MR centre source through the accelerator exit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import (
    require_reviewed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_stage_2_ring_voltages,
    derive_two_zone_placement,
    load_contract,
    mirror_power_supply_limits,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    EVENT,
    FIELD,
    FLY_COMPLETED,
    parse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _single_center_source_fly2,
    _single_center_source_state,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be a finite number")
    return result


def materialize_source(
    *, contract_path: Path, reviewed_contract_path: Path, voltage_trial_path: Path,
    fly2_path: Path, receipt_path: Path,
) -> dict[str, Any]:
    """Freeze the selected +y slow-energy centre release for one real exit flight."""
    contract = load_contract(contract_path)
    detector_policy = contract["accelerator"]["detector_return_path"]
    supply_limits = mirror_power_supply_limits(contract)
    reviewed = load_contract(
        reviewed_contract_path,
        inherited_detector_return_path=detector_policy,
        inherited_mirror_power_supply_limits_v=supply_limits,
    )
    trial = load_contract(
        voltage_trial_path,
        inherited_detector_return_path=detector_policy,
        inherited_mirror_power_supply_limits_v=supply_limits,
    )
    require_reviewed_geometry(contract, reviewed)
    require_reviewed_geometry(trial, reviewed)
    derivation = trial.get("candidate_derivation")
    if (
        not isinstance(derivation, dict)
        or derivation.get("role") != "fixed_reviewed_geometry_accelerator_voltage_trial"
        or derivation.get("physical_placement_source") != "reviewed_contract_not_trial_focus"
    ):
        raise CandidateContractError("accelerator exit source requires a reviewed voltage trial")

    contract_species = contract.get("particle_source", {}).get("species")
    trial_species = trial.get("particle_source", {}).get("species")
    if not isinstance(contract_species, dict) or trial_species != contract_species:
        raise CandidateContractError("voltage trial species differs from the current source contract")
    mass = _finite(contract_species.get("mass_th"), "particle mass")
    charge = contract_species.get("charge_e")
    if mass <= 0.0 or charge != 1 or isinstance(charge, bool):
        raise CandidateContractError("accelerator exit diagnostic requires the current +1 source")
    partition = contract.get("prism_transport", {}).get("energy_partition")
    trial_partition = trial.get("prism_transport", {}).get("energy_partition")
    selected_energy = _finite(
        derivation.get(
            "target_axial_energy_per_charge_v",
            trial.get("nominal", {}).get("energy_per_charge_v"),
        ),
        "selected axial energy",
    )
    if selected_energy <= 0.0:
        raise CandidateContractError("selected axial energy must be positive")
    if not isinstance(partition, dict) or not isinstance(trial_partition, dict):
        raise CandidateContractError("current and voltage-trial energy partitions are required")
    slow_energy = _finite(
        trial_partition.get("drift_kinetic_energy_ev"), "selected source slow energy",
    )
    trial_fast_energy = _finite(
        trial_partition.get("fast_reflection_kinetic_energy_ev"),
        "voltage-trial fast energy",
    )
    trial_total_energy = _finite(
        trial_partition.get("total_kinetic_energy_ev"), "voltage-trial total energy",
    )
    if (
        slow_energy <= 0.0
        or trial_fast_energy != selected_energy
        or not math.isclose(
            trial_total_energy, slow_energy + selected_energy, rel_tol=0.0, abs_tol=1e-12,
        )
        or derivation.get("selected_slow_energy_per_charge_v") not in (None, slow_energy)
    ):
        raise CandidateContractError("voltage-trial orthogonal energy partition is inconsistent")

    placement = derive_two_zone_placement(reviewed)
    release = _finite(
        contract.get("accelerator", {}).get("release_position_in_gap_1_mm"),
        "accelerator release position",
    )
    trial_release = _finite(
        trial.get("accelerator", {}).get("release_position_in_gap_1_mm"),
        "voltage-trial release position",
    )
    if release != trial_release:
        raise CandidateContractError("voltage trial changed the source release position")
    release_z = placement.repeller_z_mm - release
    fly2 = _single_center_source_fly2(
        mass_th=mass,
        charge_state=charge,
        source_slow_energy_per_charge_v=slow_energy,
        focus_y_mm=placement.focus_y_mm,
        release_z_mm=release_z,
    )
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(fly2, encoding="utf-8", newline="\n")
    accelerator = trial["accelerator"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_accelerator_exit_center_source",
        "status": "materialized",
        "qualification": "source_to_accelerator_exit_diagnostic_input_only",
        "source_particle_count": 1,
        "particle_mass_th": mass,
        "charge_state": charge,
        "source_slow_kinetic_energy_per_charge_v": slow_energy,
        "source_position_project_mm": [0.0, placement.focus_y_mm, release_z],
        "source_direction_project": [0.0, 1.0, 0.0],
        "source_time_of_birth_us": 0.0,
        "selected_axial_energy_per_charge_v": selected_energy,
        "accelerator_endpoint_voltages_v": [
            _finite(accelerator.get(name), f"accelerator {name}")
            for name in ("repeller_v", "intermediate_grid_v", "exit_grid_v")
        ],
        "accelerator_ring_voltages_v": list(
            derive_stage_2_ring_voltages(trial, placement_contract=reviewed)
        ),
        "inputs": {
            "current_contract_sha256": _sha256(contract_path),
            "reviewed_geometry_contract_sha256": _sha256(reviewed_contract_path),
            "voltage_trial_sha256": _sha256(voltage_trial_path),
            "fly2_sha256": _sha256(fly2_path),
        },
    }
    # Exercise the shared state reconstruction now, so the receipt cannot publish
    # a source whose stated direction, species, or energy is internally inconsistent.
    _, source_state = _single_center_source_state(receipt)
    receipt["source_release_state"] = source_state
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _layout_source_and_event_text(text: str) -> tuple[int, dict[str, float], str]:
    layout_instances: list[int] = []
    source_events: list[dict[str, float]] = []
    retained: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = EVENT.match(line.strip())
        if match is None or match.group("kind") not in {
            "accelerator_layout", "accelerator_source",
        }:
            retained.append(line)
            continue
        fields: dict[str, str] = {}
        for token in match.group("fields").split():
            field = FIELD.fullmatch(token)
            if field is None or field.group("key") in fields:
                raise CandidateContractError(
                    f"malformed accelerator layout event at line {line_number}"
                )
            fields[field.group("key")] = field.group("value")
        if match.group("kind") == "accelerator_layout":
            if set(fields) != {"accelerator_instance"}:
                raise CandidateContractError("accelerator layout event has unexpected fields")
            try:
                numeric = float(fields["accelerator_instance"])
            except ValueError as error:
                raise CandidateContractError("accelerator layout instance must be an integer") from error
            if not math.isfinite(numeric) or numeric <= 0.0 or int(numeric) != numeric:
                raise CandidateContractError("accelerator layout instance must be a positive integer")
            layout_instances.append(int(numeric))
            continue
        required = {
            "ion", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us",
            "vz_mm_us", "mass_th", "charge_state", "kinetic_energy_ev_native",
        }
        if set(fields) != required:
            raise CandidateContractError("accelerator source event has unexpected fields")
        try:
            source_event = {name: float(value) for name, value in fields.items()}
        except ValueError as error:
            raise CandidateContractError("accelerator source event fields must be numeric") from error
        if not all(math.isfinite(value) for value in source_event.values()):
            raise CandidateContractError("accelerator source event fields must be finite")
        source_events.append(source_event)
    if len(layout_instances) != 1:
        raise CandidateContractError("flight must emit exactly one accelerator layout event")
    if len(source_events) != 1:
        raise CandidateContractError("flight must emit exactly one accelerator source event")
    return layout_instances[0], source_events[0], "\n".join(retained)


def analyze_exit(
    *, log_path: Path, source_receipt_path: Path, output_path: Path,
) -> dict[str, Any]:
    """Publish the one measured source-to-exit state using the discovered IOB role."""
    source = json.loads(source_receipt_path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(source, dict)
        or source.get("schema_version") != 1
        or source.get("role") != "mrtof_accelerator_exit_center_source"
        or source.get("status") != "materialized"
        or source.get("qualification") != "source_to_accelerator_exit_diagnostic_input_only"
    ):
        raise CandidateContractError("accelerator exit source receipt identity is invalid")
    _, source_state = _single_center_source_state(source)
    text = log_path.read_text(encoding="utf-8")
    accelerator_instance, measured_source, event_text = _layout_source_and_event_text(text)
    try:
        events = parse_events(event_text)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    exits = [event for event in events if event["kind"] == "accelerator_safe_exit"]
    if len(exits) != 1:
        raise CandidateContractError("flight must emit exactly one accelerator safe-exit event")
    completed = FLY_COMPLETED.search(text)
    if completed is None or int(completed.group("splats")) != 1:
        raise CandidateContractError("accelerator exit flight must complete with exactly one splat")
    terminals = [event for event in events if event["kind"] == "terminal"]
    if len(terminals) != 1:
        raise CandidateContractError("accelerator exit flight must emit exactly one terminal event")
    event = exits[0]
    ion = int(event["ion"])
    time_us = _finite(event["t_us"], "safe-exit time")
    from_instance = int(event["from_instance"])
    to_instance = int(event["to_instance"])
    position = [_finite(event[name], f"safe-exit {name}") for name in ("x_mm", "y_mm", "z_mm")]
    velocity = [
        _finite(event[name], f"safe-exit {name}")
        for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")
    ]
    if ion != 1:
        raise CandidateContractError("accelerator safe exit must belong to ion one")
    if time_us < _finite(source.get("source_time_of_birth_us"), "source birth time"):
        raise CandidateContractError("accelerator safe exit precedes source release")
    if from_instance != accelerator_instance or to_instance == accelerator_instance:
        raise CandidateContractError("safe-exit transition disagrees with the discovered accelerator instance")
    if velocity[2] >= 0.0:
        raise CandidateContractError("accelerator safe exit must travel toward negative project z")
    terminal = terminals[0]
    exit_index = events.index(event)
    terminal_index = events.index(terminal)
    if (
        int(terminal["ion"]) != 1
        or int(terminal["splat"]) != 1
        or terminal_index <= exit_index
    ):
        raise CandidateContractError("terminal event does not record successful post-exit termination")
    mass = _finite(source.get("particle_mass_th"), "particle mass")
    charge = source.get("charge_state")
    if mass <= 0.0 or charge != 1 or isinstance(charge, bool):
        raise CandidateContractError("accelerator exit diagnostic requires the current +1 source")
    expected_source = {
        "ion": 1.0,
        "t_us": _finite(source_state["time_us"], "source time"),
        "x_mm": _finite(source_state["position_mm"][0], "source x"),
        "y_mm": _finite(source_state["position_mm"][1], "source y"),
        "z_mm": _finite(source_state["position_mm"][2], "source z"),
        "mass_th": mass,
        "charge_state": 1.0,
    }
    if any(
        not math.isclose(measured_source[name], expected, rel_tol=1e-9, abs_tol=1e-9)
        for name, expected in expected_source.items()
    ):
        raise CandidateContractError("recorded accelerator source differs from the frozen source receipt")
    if (
        not math.isclose(measured_source["vx_mm_us"], 0.0, rel_tol=0.0, abs_tol=1e-9)
        or measured_source["vy_mm_us"] <= 0.0
        or not math.isclose(measured_source["vz_mm_us"], 0.0, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise CandidateContractError("recorded accelerator source is not directed along positive project y")
    frozen_source_energy = _finite(source_state["kinetic_energy_ev"], "source kinetic energy")
    if not math.isclose(
        measured_source["kinetic_energy_ev_native"],
        frozen_source_energy,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise CandidateContractError(
            "recorded native source kinetic energy differs from the frozen source receipt"
        )
    theoretical_velocity = [
        _finite(value, f"theoretical source velocity {axis}")
        for axis, value in zip("xyz", source_state["velocity_mm_per_us"], strict=True)
    ]
    native_velocity = [measured_source[f"v{axis}_mm_us"] for axis in "xyz"]
    components = [
        kinetic_energy_ev(
            mass, *(1000.0 * velocity[index] if index == axis else 0.0 for index in range(3))
        )
        for axis in range(3)
    ]
    result = {
        "schema_version": 1,
        "role": "mrtof_accelerator_exit_observation",
        "status": "observed",
        "qualification": "source_to_accelerator_exit_diagnostic_only",
        "coordinate_frame": "project",
        "accelerator_layout": {"accelerator_instance": accelerator_instance},
        "recorded_source_event": measured_source,
        "source_release_state": source_state,
        "source_velocity_conversion_diagnostic": {
            "energy_identity_authority": "SIMION native speed_to_ke(speed, ion_mass)",
            "theoretical_velocity_authority": "repository SI particle-physics constants",
            "frozen_source_kinetic_energy_ev": frozen_source_energy,
            "native_kinetic_energy_ev": measured_source["kinetic_energy_ev_native"],
            "theoretical_velocity_mm_per_us": theoretical_velocity,
            "recorded_native_velocity_mm_per_us": native_velocity,
            "native_minus_theoretical_velocity_mm_per_us": [
                measured - theoretical
                for measured, theoretical in zip(native_velocity, theoretical_velocity, strict=True)
            ],
        },
        "safe_exit_state": {
            "ion": ion,
            "time_us": time_us,
            "position_mm": position,
            "velocity_mm_per_us": velocity,
            "particle_mass_th": mass,
            "charge_state": charge,
            "kinetic_energy_ev": sum(components),
            "from_instance": from_instance,
            "to_instance": to_instance,
        },
        "recorded_kinetic_energy_components_ev": {
            "x": components[0], "y": components[1], "z": components[2],
            "total": sum(components),
        },
        "inputs": {
            "log_sha256": _sha256(log_path),
            "source_receipt_sha256": _sha256(source_receipt_path),
        },
        "limitations": [
            "This diagnostic ends at the first measured accelerator exit.",
            "The canonical exit state is the interpolated safe-exit event, not the later terminate callback state.",
            "It does not qualify P1, P2, Stripe transport, target K, detector arrival, or resolution.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize")
    materialize.add_argument("--contract", required=True, type=Path)
    materialize.add_argument("--reviewed-contract", required=True, type=Path)
    materialize.add_argument("--voltage-trial", required=True, type=Path)
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--source-receipt", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "materialize":
        materialize_source(
            contract_path=arguments.contract,
            reviewed_contract_path=arguments.reviewed_contract,
            voltage_trial_path=arguments.voltage_trial,
            fly2_path=arguments.fly2,
            receipt_path=arguments.receipt,
        )
    else:
        analyze_exit(
            log_path=arguments.log,
            source_receipt_path=arguments.source_receipt,
            output_path=arguments.output,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
