"""Validate and execute one design-plan-bound oa-TOF candidate workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
COMMON_CONTRACTS = REPO_ROOT / "common" / "contracts"
if str(COMMON_CONTRACTS) not in sys.path:
    sys.path.insert(0, str(COMMON_CONTRACTS))

from machine_contracts import load_json, sha256
from run_candidate_workflow import run_candidate_workflow


def _verified_record(record: dict[str, Any], label: str) -> Path:
    path = Path(record.get("path", "")).resolve()
    expected = record.get("sha256", "")
    if not path.is_file() or not expected or sha256(path).lower() != expected.lower():
        raise ValueError(f"{label} is missing or changed")
    return path


def validate_bound_candidate(design_plan_path: Path, candidate_plan_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    design_plan_path = design_plan_path.resolve()
    candidate_plan_path = candidate_plan_path.resolve()
    design = load_json(design_plan_path)
    candidate = load_json(candidate_plan_path)
    if design.get("role") != "solver_neutral_design_plan":
        raise ValueError("input is not a solver-neutral design plan")
    if candidate.get("role") != "oa_tof_candidate_run_plan":
        raise ValueError("input is not an oa-TOF candidate run plan")
    if design.get("project_id") != "oa_tof" or design.get("mode") != "design_candidate":
        raise ValueError("design plan is not an oa-TOF design_candidate plan")
    if design.get("request_status") != "approved":
        raise ValueError("bound candidate execution requires an approved design request")
    if design.get("run_id") != candidate.get("run_id"):
        raise ValueError("design plan and candidate workflow run_id differ")

    source_request = _verified_record(design.get("provenance", {}).get("request", {}), "design-plan request")
    frozen_request = _verified_record(
        candidate.get("candidate_inputs", {}).get("design_request.json", {}), "frozen candidate request"
    )
    if sha256(source_request).lower() != sha256(frozen_request).lower():
        raise ValueError("design plan and candidate workflow use different design requests")
    request = load_json(frozen_request)
    if (request.get("request_id") != design.get("request_id") or
            request.get("target", {}).get("mode") != design.get("mode")):
        raise ValueError("frozen request identity/mode differs from the design plan")
    if request.get("status") != "approved":
        raise ValueError("frozen candidate request is not approved")

    diff_path = _verified_record(
        candidate.get("candidate_inputs", {}).get("candidate_diff.json", {}), "frozen candidate diff"
    )
    diff = load_json(diff_path)
    if diff.get("request_id") != design.get("request_id"):
        raise ValueError("candidate diff belongs to another design request")
    allowed_variables = {"reflectron_midgrid_voltage"}
    requested_variables = set(request.get("design_variables", []))
    unsupported_requested = requested_variables - allowed_variables
    if unsupported_requested:
        raise ValueError(
            "approved request contains variables without runtime coverage: "
            + ", ".join(sorted(unsupported_requested))
        )
    changed_variables = diff.get("changed_variables", [])
    proposed_variables = {
        item.get("variable") for item in changed_variables
        if item.get("change_origin") == "proposed"
    }
    unsupported = proposed_variables - allowed_variables
    if unsupported:
        raise ValueError(
            "bound candidate contains variables without runtime coverage: "
            + ", ".join(sorted(unsupported))
        )
    unrequested = proposed_variables - requested_variables
    if unrequested:
        raise ValueError(
            "candidate diff contains variables absent from the approved request: "
            + ", ".join(sorted(unrequested))
        )
    if any(item.get("change_origin") != "proposed" for item in changed_variables):
        raise ValueError("changed_variables must contain only explicitly proposed variables")
    return design, candidate


def run_bound_candidate_workflow(
    design_plan_path: Path,
    candidate_plan_path: Path,
    simion_exe: str = r"C:\Program Files\SIMION-2020\simion.exe",
) -> tuple[Path, dict[str, Any]]:
    validate_bound_candidate(design_plan_path, candidate_plan_path)
    return run_candidate_workflow(candidate_plan_path, simion_exe)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_plan", type=Path)
    parser.add_argument("candidate_workflow_plan", type=Path)
    parser.add_argument("--simion-exe", default=r"C:\Program Files\SIMION-2020\simion.exe")
    args = parser.parse_args()
    try:
        run_root, summary = run_bound_candidate_workflow(
            args.design_plan, args.candidate_workflow_plan, args.simion_exe
        )
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"BOUND_CANDIDATE_WORKFLOW=FAIL {exc}") from exc
    print(f"BOUND_CANDIDATE_WORKFLOW=PASS RUN_ROOT={run_root} DECISION={summary['candidate_decision']}")


if __name__ == "__main__":
    main()
