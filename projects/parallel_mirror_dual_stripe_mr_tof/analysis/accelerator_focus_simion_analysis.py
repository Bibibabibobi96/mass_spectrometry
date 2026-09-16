"""Analyze the independent SIMION two-zone first-time-focus flight."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_focus_voltage_trial import (
    require_reviewed_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    derive_two_zone_focus,
    derive_two_zone_placement,
    load_contract,
)

_EVENT = re.compile(r"MRTOF_ACCELERATOR_FOCUS_EVENT\s+(?P<kind>\w+)\s+(?P<fields>.*)")
_FIELD = re.compile(r"(?P<name>[A-Za-z_]+)=(?P<value>[^\s]+)")


def _events(path: Path) -> dict[int, dict[str, dict[str, float]]]:
    result: dict[int, dict[str, dict[str, float]]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _EVENT.search(line)
        if not match:
            continue
        fields = {item.group("name"): float(item.group("value")) for item in _FIELD.finditer(match.group("fields"))}
        ion = int(fields.pop("ion"))
        kind = match.group("kind")
        if kind in result.setdefault(ion, {}):
            raise ValueError(f"duplicate accelerator-focus {kind} event for ion {ion}")
        result[ion][kind] = fields
    return result


def _single_center_focus_state(
    records: dict[int, dict[str, dict[str, float]]],
    *,
    expected_count: int,
    contract: dict[str, Any],
    contract_path: Path,
    reviewed_contract_path: Path,
    log_path: Path,
    selected_energy_per_charge_v: float,
    target_focus_z_mm: float,
) -> dict[str, Any] | None:
    """Publish only a fully recorded one-ion focus crossing, never a nominal substitute."""
    if expected_count != 1 or "focus" not in records.get(1, {}):
        return None
    focus = records[1]["focus"]
    required = ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
    if any(name not in focus for name in required):
        raise ValueError("single-center focus event lacks complete recorded position or velocity")
    values = {name: float(focus[name]) for name in required}
    if not all(np.isfinite(value) for value in values.values()):
        raise ValueError("single-center focus event position and velocity must be finite")
    if values["vz_mm_us"] >= 0.0:
        raise ValueError("single-center focus event must cross toward negative project z")
    # Reuse the established project-frame interface-location tolerance used by
    # the adjacent P1/focus hand-off checks; this is not a physics acceptance
    # threshold or a replacement for the recorded event coordinate.
    if abs(values["z_mm"] - target_focus_z_mm) > 1.0e-9:
        raise ValueError("single-center focus event is not on the declared focus plane")
    species = contract.get("particle_source", {}).get("species")
    if not isinstance(species, dict):
        raise ValueError("single-center accelerator output requires source species identity")
    try:
        mass_th = float(species["mass_th"])
        charge_e = float(species["charge_e"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("single-center accelerator output has invalid species identity") from error
    if not np.isfinite(mass_th) or not np.isfinite(charge_e) or mass_th <= 0.0 or charge_e == 0.0:
        raise ValueError("single-center accelerator output has invalid species identity")
    velocity = [values[name] for name in ("vx_mm_us", "vy_mm_us", "vz_mm_us")]
    component_energy_ev = [
        kinetic_energy_ev(
            mass_th,
            *(1000.0 * velocity[index] if index == axis else 0.0 for index in range(3)),
        )
        for axis in range(3)
    ]
    return {
        "schema_version": 1,
        "status": "published_from_recorded_single_center_focus_event",
        "qualification": "accelerator_focus_diagnostic_state_only__not_full_mr_source",
        "event": "negative_going_project_z_focus_plane_crossing",
        "ion_number": 1,
        "time_us": values["t_us"],
        "position_project_mm": [values[name] for name in ("x_mm", "y_mm", "z_mm")],
        "velocity_project_mm_per_us": velocity,
        "recorded_kinetic_energy_components_ev": {
            "x": component_energy_ev[0],
            "y": component_energy_ev[1],
            "z": component_energy_ev[2],
            "total": sum(component_energy_ev),
        },
        "species": {"mass_th": mass_th, "charge_e": charge_e},
        "selected_net_gain_center_per_charge_v": float(selected_energy_per_charge_v),
        "input_identity": {
            "focus_log_sha256": file_sha256(log_path),
            "contract_sha256": file_sha256(contract_path),
            "reviewed_geometry_contract_sha256": file_sha256(reviewed_contract_path),
        },
        "semantics": (
            "All position and velocity components come from the recorded SIMION focus event. "
            "This zero-initial-KE accelerator diagnostic does not fabricate the separate 5-eV "
            "slow component required by the future complete MR source."
        ),
    }


def analyze(
    log_path: Path, contract_path: Path, expected_count: int,
    reviewed_contract_path: Path | None = None,
) -> dict[str, Any]:
    if expected_count <= 0:
        raise ValueError("expected particle count must be positive")
    contract = load_contract(contract_path)
    reviewed = contract if reviewed_contract_path is None else load_contract(
        reviewed_contract_path,
        inherited_detector_return_path=contract["accelerator"]["detector_return_path"],
    )
    require_reviewed_geometry(contract, reviewed)
    records = _events(log_path)
    expected_ids = list(range(1, expected_count + 1))
    if sorted(records) != expected_ids:
        raise ValueError("accelerator-focus log particle identities do not match the contract")
    if any("source" not in records[ion] or "terminal" not in records[ion] for ion in expected_ids):
        raise ValueError("every accelerator-focus particle needs source and terminal events")
    reached = [ion for ion in expected_ids if "focus" in records[ion]]
    placement = derive_two_zone_placement(reviewed)
    trial_focus = derive_two_zone_focus(contract, require_downstream_focus=False)
    accelerator = contract["accelerator"]
    species = contract["particle_source"]["species"]
    z0 = np.asarray([records[ion]["source"]["z_mm"] for ion in reached], dtype=float)
    time_us = np.asarray([records[ion]["focus"]["t_us"] for ion in reached], dtype=float)
    speed_mm_us = np.asarray([-records[ion]["focus"]["vz_mm_us"] for ion in reached], dtype=float)
    if np.any(speed_mm_us <= 0.0):
        raise ValueError("every accelerator-focus crossing must travel along negative project z")
    release = placement.repeller_z_mm - z0
    analytic_us = np.asarray([
        1.0e6 * time_to_fixed_plane_s(
            float(accelerator["repeller_v"]),
            float(accelerator["intermediate_grid_v"]),
            float(accelerator["gap_1_mm"]),
            float(accelerator["gap_2_mm"]),
            float(value),
            0.0,
            placement.exit_grid_z_mm - placement.focus_z_mm,
            float(species["mass_th"]),
            exit_v=float(accelerator["exit_grid_v"]),
        )
        for value in release
    ])
    if reached:
        coefficients = None
        focus_shift_mm = None
        if len(reached) >= 3:
            centered = release - float(accelerator["release_position_in_gap_1_mm"])
            design = np.column_stack((np.ones(len(centered)), centered, centered * centered))
            coefficients, *_ = np.linalg.lstsq(design, time_us, rcond=None)
            inverse_speed_coefficients, *_ = np.linalg.lstsq(design, 1.0 / speed_mm_us, rcond=None)
            if abs(inverse_speed_coefficients[1]) > 1.0e-15:
                focus_shift_mm = float(-coefficients[1] / inverse_speed_coefficients[1])
        timing = {
            "mean_time_us": float(np.mean(time_us)),
            "peak_to_peak_time_ns": float(np.ptp(time_us) * 1000.0),
            "linear_slope_ps_per_mm": None if coefficients is None else float(coefficients[1] * 1.0e6),
            "quadratic_coefficient_ps_per_mm2": None if coefficients is None else float(coefficients[2] * 1.0e6),
            "analytic_max_abs_time_error_ns": float(np.max(np.abs(time_us - analytic_us)) * 1000.0),
            "derived_focus_shift_along_negative_z_mm": focus_shift_mm,
            "derived_first_order_focus_project_z_mm": None if focus_shift_mm is None else placement.focus_z_mm - focus_shift_mm,
            "first_order_focus_plane_residual_z_mm": None if focus_shift_mm is None else -focus_shift_mm,
        }
    else:
        timing = None
    analytic_focus_project_z_mm = placement.exit_grid_z_mm - trial_focus.focus_after_exit_mm
    reviewed_path = contract_path if reviewed_contract_path is None else reviewed_contract_path
    single_center_state = _single_center_focus_state(
        records,
        expected_count=expected_count,
        contract=contract,
        contract_path=contract_path,
        reviewed_contract_path=reviewed_path,
        log_path=log_path,
        selected_energy_per_charge_v=trial_focus.energy_per_charge_v,
        target_focus_z_mm=placement.focus_z_mm,
    )
    return {
        "schema_version": 1,
        "role": "mrtof_two_zone_accelerator_first_time_focus_simion",
        "status": "complete" if len(reached) == expected_count else "incomplete",
        "qualification": "candidate_prototype_numeric_focus_only",
        "expected_particle_count": expected_count,
        "focus_particle_count": len(reached),
        "detection_fraction": len(reached) / expected_count,
        "source_release_interval_mm": [float(np.min(release)), float(np.max(release))] if reached else None,
        "target_plane_project_z_mm": placement.focus_z_mm,
        "analytic_trial_focus_project_z_mm": analytic_focus_project_z_mm,
        "analytic_trial_focus_plane_residual_z_mm": analytic_focus_project_z_mm - placement.focus_z_mm,
        "single_center_focus_state": single_center_state,
        "timing": timing,
        "limitations": [
            "This isolates the static two-zone accelerator and stops particles at z=0.",
            "The recorded single-center state belongs to the zero-initial-KE focus diagnostic; it does not include the complete MR source's separate slow-energy component.",
            "It does not qualify prism transport, MR oscillations, detector arrival, or mass resolution.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--reviewed-contract", type=Path)
    args = parser.parse_args()
    result = analyze(args.log, args.contract, args.expected_count, args.reviewed_contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result["status"] != "complete":
        raise SystemExit("accelerator focus flight did not reach z=0 for every particle")
    print(f"MRTOF_ACCELERATOR_FOCUS_ANALYSIS=PASS particles={result['focus_particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
