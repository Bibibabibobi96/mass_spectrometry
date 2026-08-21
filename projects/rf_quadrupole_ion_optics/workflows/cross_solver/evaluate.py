"""Contract-driven cross-solver comparison for quadrupole transport modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256 as _sha256
from projects.rf_quadrupole_ion_optics.analysis.particle_state_comparison_core import (
    aggregate_comparison, aggregate_handoff, load_event_table, pair_event_census,
    source_id_evidence, write_census,
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _within(value: float | None, maximum: float) -> bool:
    return value is not None and value <= maximum


def _no_collision_gates(
    *, mode: dict[str, Any], resolved: dict[str, Any], policy: dict[str, Any],
    particle_count: int, paired: int, comsol: dict[str, Any], simion: dict[str, Any],
    comparison: dict[str, Any], eligible: bool,
) -> tuple[int, dict[str, bool]]:
    if policy.get("role") != "repository_particle_count_policy":
        raise ValueError("particle-count policy identity differs")
    minimum = int(policy["functional_check_count"])
    if not eligible:
        return minimum, {}
    numerics = mode["numerics"]
    maximum_radius = max(
        float(comsol["max_rod_radius_mm"]), float(simion["max_rod_radius_mm"])
    ) if comsol["max_rod_radius_mm"] is not None and simion["max_rod_radius_mm"] is not None else None
    return minimum, {
        "full_handoff_pairing": paired == particle_count,
        "minimum_transmission_comsol": float(comsol["transmission"]) >= numerics["minimum_expected_transmission"],
        "minimum_transmission_simion": float(simion["transmission"]) >= numerics["minimum_expected_transmission"],
        "transmission": comparison["transmission_absolute_difference"] <= numerics["cross_solver_transmission_absolute_tolerance"],
        "mean_tof": _within(comparison["mean_tof_relative_difference"], numerics["cross_solver_relative_mean_tof_tolerance"]),
        "confinement": maximum_radius is not None and maximum_radius < resolved["geometry_mm"]["inscribed_radius_r0"],
    }


def _interface_gates(
    *, mode: dict[str, Any], particle_count: int, comsol: dict[str, Any],
    simion: dict[str, Any], comparison: dict[str, Any], eligible: bool,
) -> tuple[int, dict[str, bool]]:
    minimum = int(mode["numerics"]["minimum_diagnostic_particles"])
    if not eligible:
        return minimum, {}
    targets = mode["candidate_acceptance_targets"]
    return minimum, {
        "minimum_transmission_comsol": float(comsol["transmission"]) >= targets["minimum_transmission"],
        "minimum_transmission_simion": float(simion["transmission"]) >= targets["minimum_transmission"],
        "transmission": _within(comparison["transmission_absolute_difference"], targets["cross_solver_transmission_absolute_difference"]),
        "mean_tof": _within(comparison["mean_tof_relative_difference"], targets["cross_solver_relative_mean_tof_difference"]),
        "rms_radius": _within(comparison["rms_radius_relative_difference"], targets["cross_solver_relative_rms_output_radius_difference"]),
        "rms_divergence": _within(comparison["rms_divergence_relative_difference"], targets["cross_solver_relative_rms_divergence_difference"]),
        "mean_energy": _within(comparison["mean_energy_relative_difference"], targets["cross_solver_relative_mean_energy_difference"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol", type=Path, required=True)
    parser.add_argument("--simion", type=Path, required=True)
    parser.add_argument("--mode-contract", type=Path, required=True)
    parser.add_argument("--particles", type=Path, required=True)
    parser.add_argument("--particle-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--census-output", type=Path, required=True)
    parser.add_argument("--resolved", type=Path)
    parser.add_argument("--particle-count-policy", type=Path)
    args = parser.parse_args()
    mode = _json(args.mode_contract)
    workflow = mode.get("mode")
    if workflow not in {"transport_no_collision", "transport_interface_readiness"}:
        raise ValueError("unsupported cross-solver mode contract")
    if args.particle_count <= 0:
        raise ValueError("particle source is empty")
    if workflow == "transport_no_collision":
        if args.resolved is None or args.particle_count_policy is None:
            raise ValueError("no-collision comparison requires resolved design and count policy")
        resolved = _json(args.resolved)
        if resolved.get("role") != "multipole_resolved_design_do_not_edit":
            raise ValueError("resolved physical authority role differs")
        policy = _json(args.particle_count_policy)
    else:
        resolved = policy = None
    left, right = load_event_table(args.comsol), load_event_table(args.simion)
    source = source_id_evidence(left, right, args.particle_count)
    census, residuals = pair_event_census(left, right, set(range(1, args.particle_count + 1)))
    comsol, simion = aggregate_handoff(left, args.particle_count), aggregate_handoff(right, args.particle_count)
    comparison = aggregate_comparison(comsol, simion, residuals)
    # The two modes intentionally have distinct, contract-owned acceptance gates.
    if workflow == "transport_no_collision":
        minimum = int(policy["functional_check_count"])
        eligible = bool(source["valid"]) and args.particle_count >= minimum
        minimum, gates = _no_collision_gates(mode=mode, resolved=resolved, policy=policy, particle_count=args.particle_count, paired=len(residuals), comsol=comsol, simion=simion, comparison=comparison, eligible=eligible)
        role = "rf_quadrupole_no_collision_cross_solver_result"
        extra: dict[str, Any] = {"minimum_functional_particles": minimum}
    else:
        minimum = int(mode["numerics"]["minimum_diagnostic_particles"])
        eligible = bool(source["valid"]) and args.particle_count >= minimum
        minimum, gates = _interface_gates(mode=mode, particle_count=args.particle_count, comsol=comsol, simion=simion, comparison=comparison, eligible=eligible)
        role = "rf_quadrupole_interface_readiness_cross_solver_result"
        extra = {"minimum_diagnostic_particles": minimum, "target_policy": mode["candidate_acceptance_targets"].get("policy")}
    status = "NOT_EVALUATED" if not eligible else "PASS" if all(gates.values()) else "FAIL"
    inputs = {"comsol_particle_state_sha256": _sha256(args.comsol), "simion_particle_state_sha256": _sha256(args.simion), "mode_contract_sha256": _sha256(args.mode_contract), "particle_source_sha256": _sha256(args.particles)}
    if args.resolved is not None: inputs["resolved_physical_authority_sha256"] = _sha256(args.resolved)
    if args.particle_count_policy is not None: inputs["particle_count_policy_sha256"] = _sha256(args.particle_count_policy)
    result = {"schema_version": 2, "role": role, "workflow": workflow, "status": status, "execution_status": "success", "claim_status": mode.get("status"), "particles": args.particle_count, **extra, "sample_size_eligible": eligible, "source_evidence": source, "paired_handoff_particles": len(residuals), "inputs": inputs, "solvers": {"COMSOL": comsol, "SIMION": simion}, "comparison": comparison, "gates": gates}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_census(args.census_output, census, left_label="comsol", right_label="simion")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
