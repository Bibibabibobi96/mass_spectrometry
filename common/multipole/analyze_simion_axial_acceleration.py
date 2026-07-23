"""Evaluate paired SIMION axial-drop and zero-drop RF-on runs."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema


PAIRED_POPULATION_POLICY = "intersection_of_transmitted_particle_ids"


def _terminal_transmission(
    path: Path,
) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, float]]]:
    sources: dict[int, dict[str, float]] = {}
    transmitted: dict[int, dict[str, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            particle_id = int(row["particle_id"])
            if row["event"] == "source":
                sources[particle_id] = {
                    "kinetic_energy_eV": float(row["kinetic_energy_eV"]),
                    "divergence_angle_deg": float(row["divergence_angle_deg"]),
                    "radial_position_mm": float(row["radial_position_mm"]),
                }
            elif row["event"] == "terminal" and row["status"] == "transmitted":
                transmitted[particle_id] = {
                    "kinetic_energy_eV": float(row["kinetic_energy_eV"]),
                    "divergence_angle_deg": float(row["divergence_angle_deg"]),
                    "radial_position_mm": float(row["radial_position_mm"]),
                }
    if not sources:
        raise ValueError(f"no source events in {path}")
    return sources, transmitted


def evaluate(
    accelerated_state: Path,
    control_state: Path,
    resolved_contract: dict[str, Any],
) -> dict[str, Any]:
    if resolved_contract.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("paired axial evidence requires a governed resolved design")
    parent_hash = resolved_contract["resolved_sha256"]
    project_id = resolved_contract["identity"]["project_id"]
    axial_drive = resolved_contract["axial_drive"]
    topology = axial_drive["topology"]
    if topology == "none":
        raise ValueError("resolved design has no axial-drive topology")
    nominal_predicted_output_energy_eV = axial_drive["predicted_output_energy_eV"]
    expected_energy_gain_eV = axial_drive["predicted_energy_gain_eV"]
    primary_case_id = (
        "endplate_acceleration_rf_on"
        if topology == "endplate_potential_step"
        else "axial_acceleration_rf_on"
    )
    control_case_id = (
        "zero_endplate_drop_rf_on"
        if topology == "endplate_potential_step"
        else "zero_axial_drop_rf_on"
    )
    claim_limit = (
        "N=100 functional endplate-acceleration reference only; acceleration "
        "is localized near the exit and does not establish continuous in-rod "
        "acceleration, convergence, cross-solver numerical equivalence, "
        "mechanical or Formal qualification."
        if topology == "endplate_potential_step"
        else "Resolved-design axial-drive metrics only; no formal claim."
    )
    accelerated_sources, accelerated = _terminal_transmission(accelerated_state)
    control_sources, control = _terminal_transmission(control_state)
    if accelerated_sources != control_sources:
        raise ValueError("paired runs do not contain the same particle IDs")
    paired_ids = sorted(set(accelerated) & set(control))
    if not paired_ids:
        raise ValueError("paired runs have no common transmitted particles")
    count = len(accelerated_sources)
    def values(rows: dict[int, dict[str, float]], field: str) -> list[float]:
        return [rows[particle][field] for particle in paired_ids]

    for particle in paired_ids:
        if accelerated_sources[particle] != control_sources[particle]:
            raise ValueError("paired runs do not preserve identical source states")
    sample_source_mean = statistics.fmean(
        values(control_sources, "kinetic_energy_eV")
    )
    source_model = resolved_contract["particle_source"]["energy_model"]
    if source_model["kind"] == "monoenergetic":
        nominal_source = float(source_model["kinetic_energy_eV"])
        model_predicted_mean: float | None = nominal_source
    else:
        nominal_source = float(source_model["nominal_energy_eV"])
        model_predicted_mean = None
    accelerated_mean = statistics.fmean(values(accelerated, "kinetic_energy_eV"))
    control_mean = statistics.fmean(values(control, "kinetic_energy_eV"))
    accelerated_divergence = statistics.fmean(
        values(accelerated, "divergence_angle_deg")
    )
    control_divergence = statistics.fmean(values(control, "divergence_angle_deg"))
    accelerated_radius_rms = statistics.fmean(
        value**2 for value in values(accelerated, "radial_position_mm")
    ) ** 0.5
    control_radius_rms = statistics.fmean(
        value**2 for value in values(control, "radial_position_mm")
    ) ** 0.5
    mean_gain = accelerated_mean - control_mean
    nominal_predicted = float(nominal_predicted_output_energy_eV)
    expected_gain = float(expected_energy_gain_eV)
    paired_expected_output = control_mean + expected_gain
    output_error = abs(accelerated_mean - paired_expected_output)
    accelerated_transmission = len(accelerated) / count
    control_transmission = len(control) / count
    result = {
        "schema_version": 1,
        "role": "multipole_paired_axial_drive_metrics",
        "status": "UNQUALIFIED",
        "project_id": project_id,
        "parent_resolved_design_sha256": parent_hash,
        "axial_drive_topology": topology,
        "primary_case_id": primary_case_id,
        "control_case_id": control_case_id,
        "paired_population_policy": PAIRED_POPULATION_POLICY,
        "particles": count,
        "accelerated_transmitted_particles": len(accelerated),
        "control_transmitted_particles": len(control),
        "paired_transmitted_particles": len(paired_ids),
        "accelerated_transmission": accelerated_transmission,
        "control_transmission": control_transmission,
        "mean_control_output_energy_eV": control_mean,
        "mean_accelerated_output_energy_eV": accelerated_mean,
        "mean_energy_gain_eV": mean_gain,
        "expected_axial_energy_gain_eV": expected_gain,
        "paired_expected_mean_output_energy_eV": paired_expected_output,
        "nominal_source_energy_eV": nominal_source,
        "sample_source_mean_energy_eV": sample_source_mean,
        "source_model_predicted_mean_energy_eV": model_predicted_mean,
        "nominal_predicted_output_energy_eV": nominal_predicted,
        "absolute_mean_output_energy_error_eV": output_error,
        "mean_control_divergence_angle_deg": control_divergence,
        "mean_accelerated_divergence_angle_deg": accelerated_divergence,
        "mean_divergence_change_deg": accelerated_divergence - control_divergence,
        "control_rms_radial_position_mm": control_radius_rms,
        "accelerated_rms_radial_position_mm": accelerated_radius_rms,
        "rms_radial_position_change_mm": accelerated_radius_rms - control_radius_rms,
        "claim_limit": claim_limit,
    }
    validate_schema(result, "multipole_paired_metrics.schema.json")
    return result


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
