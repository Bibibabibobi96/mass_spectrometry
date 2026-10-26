"""Evaluate solver metrics against an explicit versioned evidence contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema


def evaluate(
    metrics: dict[str, Any],
    evidence: dict[str, Any],
    *,
    project_id: str,
    design_profile_id: str,
) -> dict[str, Any]:
    """Return a PASS/FAIL evidence decision without changing physical inputs."""
    validate_schema(evidence, "multipole_evidence_contract.schema.json")
    if evidence["project_id"] != project_id or evidence["design_profile_id"] != design_profile_id:
        raise ValueError("evidence contract identity differs from the run")
    thresholds = evidence["thresholds"]
    if evidence["evaluation"] == "rf_vs_zero_rf":
        primary = metrics["cases"][metrics["primary_case_id"]]
        control = metrics["cases"][metrics["control_case_id"]]
        checks = {
            "minimum_primary_transmission": primary["transmission_fraction"]
            >= thresholds["minimum_primary_transmission"],
            "minimum_transmission_improvement": (
                primary["transmission_fraction"] - control["transmission_fraction"]
            )
            >= thresholds["minimum_transmission_improvement"],
        }
    else:
        validate_schema(metrics, "multipole_paired_metrics.schema.json")
        if metrics["project_id"] != project_id:
            raise ValueError("paired metrics project identity differs from the run")
        checks = {
            "minimum_primary_transmission": metrics["accelerated_transmission"]
            >= thresholds["minimum_primary_transmission"],
            "minimum_mean_energy_gain_eV": metrics["mean_energy_gain_eV"]
            >= thresholds["minimum_mean_energy_gain_eV"],
            "maximum_mean_output_energy_error_eV": metrics[
                "absolute_mean_output_energy_error_eV"
            ]
            <= thresholds["maximum_mean_output_energy_error_eV"],
        }
    result = {
        "schema_version": 1,
        "role": "multipole_transport_evidence_evaluation",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "project_id": project_id,
        "design_profile_id": design_profile_id,
        "evaluation": evidence["evaluation"],
        "checks": checks,
    }
    validate_schema(result, "multipole_evidence_evaluation.schema.json")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--design-profile-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.metrics.read_text(encoding="utf-8-sig")),
        json.loads(args.evidence.read_text(encoding="utf-8-sig")),
        project_id=args.project_id,
        design_profile_id=args.design_profile_id,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
