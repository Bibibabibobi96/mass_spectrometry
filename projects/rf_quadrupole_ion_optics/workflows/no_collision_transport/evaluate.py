"""Decide the collision-free component-regression comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from projects.rf_quadrupole_ion_optics.analysis.particle_state_comparison_core import (
    aggregate_comparison,
    aggregate_handoff,
    load_event_table,
    pair_event_census,
    source_id_evidence,
    write_census,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _within(value: float | None, maximum: float) -> bool:
    return value is not None and value <= maximum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comsol", type=Path, required=True)
    parser.add_argument("--simion", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--mode-contract", type=Path, required=True)
    parser.add_argument("--particle-count-policy", type=Path, required=True)
    parser.add_argument("--particles", type=Path, required=True)
    parser.add_argument("--particle-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--census-output", type=Path, required=True)
    args = parser.parse_args()

    mode = _load_json(args.mode_contract)
    resolved = _load_json(args.resolved)
    policy = _load_json(args.particle_count_policy)
    if mode.get("mode") != "transport_no_collision":
        raise ValueError("mode contract is not transport_no_collision")
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("resolved physical authority role differs")
    if policy.get("role") != "repository_particle_count_policy":
        raise ValueError("particle-count policy identity differs")
    particle_count = args.particle_count
    if particle_count <= 0:
        raise ValueError("particle source is empty")

    comsol = load_event_table(args.comsol)
    simion = load_event_table(args.simion)
    source_evidence = source_id_evidence(comsol, simion, particle_count)
    expected_ids = set(range(1, particle_count + 1))
    census, residuals = pair_event_census(comsol, simion, expected_ids)
    comsol_aggregate = aggregate_handoff(comsol, particle_count)
    simion_aggregate = aggregate_handoff(simion, particle_count)
    comparison = aggregate_comparison(
        comsol_aggregate, simion_aggregate, residuals
    )

    minimum_particles = int(policy["functional_check_count"])
    sample_size_eligible = particle_count >= minimum_particles
    eligible = bool(source_evidence["valid"]) and sample_size_eligible
    gates: dict[str, bool] = {}
    if eligible:
        numerics = mode["numerics"]
        maximum_radius = (
            max(
                float(comsol_aggregate["max_rod_radius_mm"]),
                float(simion_aggregate["max_rod_radius_mm"]),
            )
            if comsol_aggregate["max_rod_radius_mm"] is not None
            and simion_aggregate["max_rod_radius_mm"] is not None
            else None
        )
        gates = {
            "full_handoff_pairing": len(residuals) == particle_count,
            "minimum_transmission_comsol": (
                float(comsol_aggregate["transmission"])
                >= numerics["minimum_expected_transmission"]
            ),
            "minimum_transmission_simion": (
                float(simion_aggregate["transmission"])
                >= numerics["minimum_expected_transmission"]
            ),
            "transmission": (
                comparison["transmission_absolute_difference"]
                <= numerics["cross_solver_transmission_absolute_tolerance"]
            ),
            "mean_tof": _within(
                comparison["mean_tof_relative_difference"],
                numerics["cross_solver_relative_mean_tof_tolerance"],
            ),
            "confinement": (
                maximum_radius is not None
                and maximum_radius
                < resolved["geometry_mm"]["inscribed_radius_r0"]
            ),
        }
    status = (
        "NOT_EVALUATED"
        if not eligible
        else "PASS"
        if all(gates.values())
        else "FAIL"
    )
    result = {
        "schema_version": 2,
        "role": "rf_quadrupole_no_collision_cross_solver_result",
        "workflow": "transport_no_collision",
        "status": status,
        "execution_status": "success",
        "claim_status": mode.get("status"),
        "particles": particle_count,
        "minimum_functional_particles": minimum_particles,
        "sample_size_eligible": sample_size_eligible,
        "source_evidence": source_evidence,
        "paired_handoff_particles": len(residuals),
        "inputs": {
            "comsol_particle_state_sha256": _sha256(args.comsol),
            "simion_particle_state_sha256": _sha256(args.simion),
            "resolved_physical_authority_sha256": _sha256(args.resolved),
            "mode_contract_sha256": _sha256(args.mode_contract),
            "particle_count_policy_sha256": _sha256(
                args.particle_count_policy
            ),
            "particle_source_sha256": _sha256(args.particles),
        },
        "solvers": {
            "COMSOL": comsol_aggregate,
            "SIMION": simion_aggregate,
        },
        "comparison": comparison,
        "gates": gates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_census(
        args.census_output,
        census,
        left_label="comsol",
        right_label="simion",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
