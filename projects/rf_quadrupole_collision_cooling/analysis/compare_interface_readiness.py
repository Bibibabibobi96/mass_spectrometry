"""Decide the interface-readiness cross-solver comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from projects.rf_quadrupole_collision_cooling.analysis.particle_state_comparison_core import (
        aggregate_comparison,
        aggregate_handoff,
        load_event_table,
        pair_event_census,
        source_id_evidence,
        write_census,
    )
else:
    from particle_state_comparison_core import (
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
    parser.add_argument("--mode-contract", type=Path, required=True)
    parser.add_argument("--particles", type=Path, required=True)
    parser.add_argument("--particle-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--census-output", type=Path, required=True)
    args = parser.parse_args()

    mode = _load_json(args.mode_contract)
    if mode.get("mode") != "transport_interface_readiness":
        raise ValueError("mode contract is not transport_interface_readiness")
    particle_count = args.particle_count
    if particle_count <= 0:
        raise ValueError("particle source is empty")

    comsol = load_event_table(args.comsol)
    simion = load_event_table(args.simion)
    source_evidence = source_id_evidence(comsol, simion, particle_count)
    minimum_particles = int(mode["numerics"]["minimum_diagnostic_particles"])
    sample_size_eligible = particle_count >= minimum_particles
    expected_ids = set(range(1, particle_count + 1))
    census, residuals = pair_event_census(comsol, simion, expected_ids)
    comsol_aggregate = aggregate_handoff(comsol, particle_count)
    simion_aggregate = aggregate_handoff(simion, particle_count)
    comparison = aggregate_comparison(
        comsol_aggregate, simion_aggregate, residuals
    )

    gates: dict[str, bool] = {}
    eligible = bool(source_evidence["valid"]) and sample_size_eligible
    if eligible:
        targets = mode["candidate_acceptance_targets"]
        gates = {
            "minimum_transmission_comsol": (
                float(comsol_aggregate["transmission"])
                >= targets["minimum_transmission"]
            ),
            "minimum_transmission_simion": (
                float(simion_aggregate["transmission"])
                >= targets["minimum_transmission"]
            ),
            "transmission": _within(
                comparison["transmission_absolute_difference"],
                targets["cross_solver_transmission_absolute_difference"],
            ),
            "mean_tof": _within(
                comparison["mean_tof_relative_difference"],
                targets["cross_solver_relative_mean_tof_difference"],
            ),
            "rms_radius": _within(
                comparison["rms_radius_relative_difference"],
                targets[
                    "cross_solver_relative_rms_output_radius_difference"
                ],
            ),
            "rms_divergence": _within(
                comparison["rms_divergence_relative_difference"],
                targets["cross_solver_relative_rms_divergence_difference"],
            ),
            "mean_energy": _within(
                comparison["mean_energy_relative_difference"],
                targets["cross_solver_relative_mean_energy_difference"],
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
        "role": "rf_quadrupole_interface_readiness_cross_solver_result",
        "workflow": "transport_interface_readiness",
        "status": status,
        "execution_status": "success",
        "claim_status": mode.get("status"),
        "target_policy": mode["candidate_acceptance_targets"].get("policy"),
        "particles": particle_count,
        "minimum_diagnostic_particles": minimum_particles,
        "sample_size_eligible": sample_size_eligible,
        "source_evidence": source_evidence,
        "paired_handoff_particles": len(residuals),
        "inputs": {
            "comsol_particle_state_sha256": _sha256(args.comsol),
            "simion_particle_state_sha256": _sha256(args.simion),
            "mode_contract_sha256": _sha256(args.mode_contract),
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
