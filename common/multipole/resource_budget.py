"""Fail closed unless a requested multipole commercial-solver pilot is authorized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.multipole.runtime_profile import resolve_runtime_profile

_SCOPE_KEYS = {
    "project_id",
    "runtime_profile_id",
    "design_profile_id",
    "particle_source_profile_id",
    "particle_count",
    "solver_numerics_profile_ids",
    "allowed_solvers",
    "retention_class",
}
_LIMIT_KEYS = {
    "wall_clock_seconds_by_solver",
    "transient_run_directory_bytes",
    "process_tree_working_set_bytes",
    "minimum_system_available_memory_bytes",
    "compact_final_retained_bytes",
    "automatic_retry_count",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys differ: {sorted(value)}")


def _particle_count(path: Path) -> int:
    with path.open(encoding="utf-8-sig") as stream:
        return max(sum(1 for line in stream if line.strip()) - 1, 0)


def validate_pilot_budget(
    *,
    repo_root: Path,
    budget_path: Path,
    project_id: str,
    solver: str,
    runtime_profile_id: str,
    design_profile_id: str,
    particle_source_path: Path,
    retention_class: str,
) -> dict[str, Any]:
    """Resolve the runtime profile and validate the exact authorized pilot."""

    runtime = resolve_runtime_profile(repo_root.resolve(), project_id, runtime_profile_id)
    expected_budget = Path(runtime["engineering_budget"]["path"]).resolve()
    if budget_path.resolve() != expected_budget:
        raise ValueError("engineering-budget path differs from runtime profile")
    budget = _load(expected_budget)
    _require_keys(
        budget,
        {
            "schema_version",
            "role",
            "project_id",
            "contract_id",
            "preregistered_before_run",
            "pilot_authorization",
            "full_matrix_authorization",
            "budget_exhaustion_result",
            "claim_limit",
        },
        "engineering-budget contract",
    )
    if (
        budget["schema_version"] != 1
        or budget["role"] != "multipole_engineering_budget_contract"
        or budget["project_id"] != project_id
        or budget["preregistered_before_run"] is not True
    ):
        raise ValueError("engineering-budget identity differs")
    pilot = budget["pilot_authorization"]
    _require_keys(pilot, {"authorized", "scope", "limits"}, "pilot authorization")
    if pilot["authorized"] is not True:
        raise ValueError("multipole commercial solver pilot is not authorized")
    scope, limits = pilot["scope"], pilot["limits"]
    _require_keys(scope, _SCOPE_KEYS, "pilot scope")
    _require_keys(limits, _LIMIT_KEYS, "pilot limits")
    expected_scope = {
        "project_id": project_id,
        "runtime_profile_id": runtime_profile_id,
        "design_profile_id": design_profile_id,
        "particle_source_profile_id": runtime["particle_source"]["profile_id"],
        "particle_count": _particle_count(Path(runtime["particle_source"]["path"])),
        "solver_numerics_profile_ids": {
            name: runtime["solver_numerics"][name]["profile_id"]
            for name in ("comsol", "simion")
        },
        "allowed_solvers": ["comsol", "simion"],
        "retention_class": retention_class,
    }
    if scope != expected_scope:
        raise ValueError("requested pilot identity differs from authorized scope")
    if solver not in scope["allowed_solvers"]:
        raise ValueError(f"solver is not authorized: {solver}")
    if Path(runtime["particle_source"]["path"]).resolve() != particle_source_path.resolve():
        raise ValueError("particle source differs from authorized runtime profile")
    wall_clock = limits["wall_clock_seconds_by_solver"]
    if set(wall_clock) != {"comsol", "simion"}:
        raise ValueError("wall-clock solver keys differ")
    positive_limits = (
        list(wall_clock.values())
        + [
            limits[name]
            for name in (
                "transient_run_directory_bytes",
                "process_tree_working_set_bytes",
                "minimum_system_available_memory_bytes",
                "compact_final_retained_bytes",
            )
        ]
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in positive_limits):
        raise ValueError("resource limits must be positive integers")
    if limits["automatic_retry_count"] != 0:
        raise ValueError("automatic_retry_count must be zero")
    if budget["full_matrix_authorization"] != {
        "authorized": False,
        "reason": "pilot_measurements_required",
    }:
        raise ValueError("full matrix must remain unauthorized during pilot")
    return {
        "schema_version": 1,
        "role": "multipole_resolved_resource_budget",
        "project_id": project_id,
        "solver": solver,
        "runtime_profile_id": runtime_profile_id,
        "design_profile_id": design_profile_id,
        "particle_source_profile_id": runtime["particle_source"]["profile_id"],
        "solver_numerics_profile_id": runtime["solver_numerics"][solver]["profile_id"],
        "solver_numerics": runtime["solver_numerics"][solver]["values"],
        "retention_class": retention_class,
        "limits": {**limits, "wall_clock_seconds": wall_clock[solver]},
        "budget_path": str(expected_budget),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--solver", required=True, choices=("comsol", "simion"))
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--design-profile-id", required=True)
    parser.add_argument("--particle-source", required=True, type=Path)
    parser.add_argument("--retention-class", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = validate_pilot_budget(
        repo_root=args.repo_root,
        budget_path=args.budget,
        project_id=args.project_id,
        solver=args.solver,
        runtime_profile_id=args.runtime_profile_id,
        design_profile_id=args.design_profile_id,
        particle_source_path=args.particle_source,
        retention_class=args.retention_class,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MULTIPOLE_RESOURCE_BUDGET=PASS PROJECT={args.project_id} SOLVER={args.solver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
