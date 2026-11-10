"""Write solver-independent SIMION transport metrics from canonical outputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load_summary(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or not isinstance(document.get("transmission"), (int, float)):
        raise ValueError(f"SIMION summary has no numeric transmission: {path}")
    return document


def _handoff_transmission(path: Path, particles: int) -> float:
    if particles < 1:
        raise ValueError("SIMION summary particles must be positive")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if not rows.fieldnames or not {"event", "status"}.issubset(rows.fieldnames):
            raise ValueError(f"canonical state lacks event/status columns: {path}")
        transmitted = sum(
            row["event"] == "handoff" and row["status"] == "transmitted"
            for row in rows
        )
    return transmitted / particles


def _metric_case(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in summary.items() if key != "transmission"
    } | {"transmission_fraction": float(summary["transmission"])}


def evaluate(
    *,
    metric_kind: str,
    project_id: str,
    parent_resolved_design_sha256: str,
    case_set: str,
    primary_case_id: str,
    primary_summary: dict[str, Any],
    primary_state: Path | None,
    control_case_id: str | None = None,
    control_summary: dict[str, Any] | None = None,
    control_state: Path | None = None,
) -> dict[str, Any]:
    """Return the existing metric contract for a non-paired transport case."""
    primary_case = _metric_case(primary_summary)
    if metric_kind == "base_paired":
        if control_case_id is None or control_summary is None:
            raise ValueError("base paired metrics require a control summary")
        control_case = _metric_case(control_summary)
        return {
            "schema_version": 1,
            "role": "multipole_simion_finite_3d_transport_metrics",
            "status": "UNQUALIFIED",
            "project_id": project_id,
            "parent_resolved_design_sha256": parent_resolved_design_sha256,
            "model_level": "L3",
            "case_set": case_set,
            "primary_case_id": primary_case_id,
            "control_case_id": control_case_id,
            "cases": {"rf_on": primary_case, "zero_rf_control": control_case},
            "rf_minus_zero_transmission": (
                float(primary_summary["transmission"])
                - float(control_summary["transmission"])
            ),
            "claim_limit": "Resolved-design SIMION metrics only; no evidence claim.",
        }
    if metric_kind == "rf_off_energy_control":
        if control_case_id is None or control_summary is None or primary_state is None or control_state is None:
            raise ValueError("RF-off metrics require both canonical states and summaries")
        return {
            "schema_version": 1,
            "role": "multipole_simion_rf_off_energy_control_metrics",
            "status": "UNQUALIFIED",
            "project_id": project_id,
            "parent_resolved_design_sha256": parent_resolved_design_sha256,
            "model_level": "L3",
            "case_set": case_set,
            "primary_case_id": primary_case_id,
            "control_case_id": control_case_id,
            "cases": {"rf_on": primary_case, "rf_off": _metric_case(control_summary)},
            "primary_handoff_transmission": _handoff_transmission(
                primary_state, int(primary_summary["particles"])
            ),
            "control_handoff_transmission": _handoff_transmission(
                control_state, int(control_summary["particles"])
            ),
            "claim_limit": "RF-off energy-conservation diagnostic only; no evidence or qualification claim.",
        }
    if metric_kind == "primary":
        if primary_state is None:
            raise ValueError("primary metrics require a canonical state")
        return {
            "schema_version": 1,
            "role": "multipole_simion_primary_transport_metrics",
            "status": "UNQUALIFIED",
            "project_id": project_id,
            "parent_resolved_design_sha256": parent_resolved_design_sha256,
            "model_level": "L3",
            "case_set": case_set,
            "primary_case_id": primary_case_id,
            "primary_case": primary_case,
            "primary_handoff_transmission": _handoff_transmission(
                primary_state, int(primary_summary["particles"])
            ),
            "claim_limit": "Primary-case SIMION metrics only; no paired-control or evidence claim.",
        }
    if metric_kind == "base_primary":
        return {
            "schema_version": 1,
            "role": "multipole_simion_primary_transport_metrics",
            "status": "UNQUALIFIED",
            "project_id": project_id,
            "parent_resolved_design_sha256": parent_resolved_design_sha256,
            "model_level": "L3",
            "case_set": case_set,
            "primary_case_id": primary_case_id,
            "primary_case": primary_case,
            "claim_limit": "Primary-case SIMION metrics only; no zero-RF control or evidence claim.",
        }
    raise ValueError(f"unsupported transport metric kind: {metric_kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric-kind", choices=("base_paired", "base_primary", "rf_off_energy_control", "primary"), required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--parent-resolved-design-sha256", required=True)
    parser.add_argument("--case-set", required=True)
    parser.add_argument("--primary-case-id", required=True)
    parser.add_argument("--primary-summary", type=Path, required=True)
    parser.add_argument("--primary-state", type=Path)
    parser.add_argument("--control-case-id")
    parser.add_argument("--control-summary", type=Path)
    parser.add_argument("--control-state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(
        metric_kind=args.metric_kind, project_id=args.project_id,
        parent_resolved_design_sha256=args.parent_resolved_design_sha256,
        case_set=args.case_set, primary_case_id=args.primary_case_id,
        primary_summary=_load_summary(args.primary_summary), primary_state=args.primary_state,
        control_case_id=args.control_case_id,
        control_summary=None if args.control_summary is None else _load_summary(args.control_summary),
        control_state=args.control_state,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
