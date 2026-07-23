"""Evaluate paired SIMION axial-drop and zero-drop RF-on runs."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


def _handoff(path: Path) -> tuple[set[int], dict[int, float]]:
    sources: set[int] = set()
    transmitted: dict[int, float] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            particle_id = int(row["particle_id"])
            if row["event"] == "source":
                sources.add(particle_id)
            elif row["event"] in {"handoff", "terminal"} and row["status"] == "transmitted":
                transmitted[particle_id] = float(row["kinetic_energy_eV"])
    if not sources:
        raise ValueError(f"no source events in {path}")
    return sources, transmitted


def evaluate(
    accelerated_state: Path,
    control_state: Path,
    resolved_contract: dict[str, Any],
) -> dict[str, Any]:
    accelerated_sources, accelerated = _handoff(accelerated_state)
    control_sources, control = _handoff(control_state)
    if accelerated_sources != control_sources:
        raise ValueError("paired runs do not contain the same particle IDs")
    paired_ids = sorted(set(accelerated) & set(control))
    if not paired_ids:
        raise ValueError("paired runs have no common transmitted particles")
    count = len(accelerated_sources)
    accelerated_mean = statistics.fmean(accelerated[particle] for particle in paired_ids)
    control_mean = statistics.fmean(control[particle] for particle in paired_ids)
    mean_gain = accelerated_mean - control_mean
    predicted = float(resolved_contract["derived"]["predicted_output_energy_eV"])
    output_error = abs(accelerated_mean - predicted)
    acceptance = resolved_contract["functional_acceptance"]
    accelerated_transmission = len(accelerated) / count
    control_transmission = len(control) / count
    passed = (
        accelerated_transmission >= float(acceptance["minimum_transmission"])
        and mean_gain >= float(acceptance["minimum_mean_energy_gain_eV"])
        and output_error <= float(acceptance["maximum_mean_output_energy_error_eV"])
    )
    return {
        "schema_version": 1,
        "role": "multipole_simion_axial_acceleration_metrics",
        "status": "PASS" if passed else "FAIL",
        "particles": count,
        "paired_transmitted_particles": len(paired_ids),
        "accelerated_transmission": accelerated_transmission,
        "control_transmission": control_transmission,
        "mean_control_output_energy_eV": control_mean,
        "mean_accelerated_output_energy_eV": accelerated_mean,
        "mean_energy_gain_eV": mean_gain,
        "predicted_output_energy_eV": predicted,
        "absolute_mean_output_energy_error_eV": output_error,
        "claim_limit": resolved_contract["claim_limit"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerated-state", required=True, type=Path)
    parser.add_argument("--control-state", required=True, type=Path)
    parser.add_argument("--resolved-contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_contract.read_text(encoding="utf-8-sig"))
    result = evaluate(args.accelerated_state, args.control_state, resolved)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
