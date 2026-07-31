"""Fail closed unless a requested multipole commercial-solver pilot is authorized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.multipole.runtime_profile import (
    resolve_runtime_profile,
    resolve_runtime_selection,
)

_SCOPE_KEYS = {
    "project_id",
    "runtime_profile_id",
    "stop_stage",
    "design_profile_id",
    "particle_source_profile_id",
    "particle_count",
    "solver_numerics_profile_ids",
    "allowed_solvers",
    "retention_class",
}
_OPTIONAL_SCOPE_KEYS = {
    "authorized_run_id",
    "expected_run_parent_resolved_design_sha256",
}
_REQUIRED_LIMIT_KEYS = {
    "wall_clock_seconds_by_solver",
    "transient_run_directory_bytes",
    "process_tree_working_set_bytes",
    "minimum_system_available_memory_bytes",
    "compact_final_retained_bytes",
    "automatic_retry_count",
}
_OPTIONAL_LIMIT_KEYS = {
    "maximum_mesh_cells",
    "maximum_pa_grid_points",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys differ: {sorted(value)}")


def _require_limit_keys(limits: dict[str, Any]) -> None:
    actual = set(limits)
    allowed = _REQUIRED_LIMIT_KEYS | _OPTIONAL_LIMIT_KEYS
    if not _REQUIRED_LIMIT_KEYS.issubset(actual) or not actual.issubset(allowed):
        raise ValueError(f"pilot limits keys differ: {sorted(limits)}")


def _require_scope_keys(scope: dict[str, Any]) -> None:
    actual = set(scope)
    allowed = _SCOPE_KEYS | _OPTIONAL_SCOPE_KEYS
    if not _SCOPE_KEYS.issubset(actual) or not actual.issubset(allowed):
        raise ValueError(f"pilot scope keys differ: {sorted(scope)}")


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
    run_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the runtime profile and validate the exact authorized pilot."""

    budget_source = _load(budget_path.resolve())
    if budget_source.get("role") == "multipole_transport_experiment_campaign":
        runtime = resolve_runtime_selection(
            repo_root.resolve(),
            project_id,
            campaign_path=budget_path.resolve(),
            experiment_id=runtime_profile_id,
        )
        budget = runtime["engineering_budget"]["inline_contract"]
    else:
        runtime = resolve_runtime_profile(
            repo_root.resolve(), project_id, runtime_profile_id
        )
        budget = budget_source
    stop_stage = runtime.get("stop_stage")
    if stop_stage not in {"transport", "mesh_build", "field_solve"}:
        raise ValueError("resolved runtime profile stop stage is missing or unsupported")
    expected_budget = Path(runtime["engineering_budget"]["path"]).resolve()
    if budget_path.resolve() != expected_budget:
        raise ValueError("engineering-budget path differs from runtime profile")
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
    _require_scope_keys(scope)
    _require_limit_keys(limits)
    allowed_solvers = scope["allowed_solvers"]
    if (
        not isinstance(allowed_solvers, list)
        or not allowed_solvers
        or len(set(allowed_solvers)) != len(allowed_solvers)
        or not set(allowed_solvers).issubset({"comsol", "simion"})
    ):
        raise ValueError("allowed_solvers must be a nonempty unique supported subset")
    expected_scope = {
        "project_id": project_id,
        "runtime_profile_id": runtime_profile_id,
        "stop_stage": stop_stage,
        "design_profile_id": design_profile_id,
        "particle_source_profile_id": runtime["particle_source"]["profile_id"],
        "particle_count": _particle_count(Path(runtime["particle_source"]["path"])),
        "solver_numerics_profile_ids": {
            name: runtime["solver_numerics"][name]["profile_id"]
            for name in ("comsol", "simion")
        },
        "allowed_solvers": allowed_solvers,
        "retention_class": retention_class,
    }
    expected_run_hash = scope.get("expected_run_parent_resolved_design_sha256")
    if expected_run_hash is not None:
        if (
            not isinstance(expected_run_hash, str)
            or len(expected_run_hash) != 64
            or any(character not in "0123456789ABCDEF" for character in expected_run_hash)
        ):
            raise ValueError(
                "expected_run_parent_resolved_design_sha256 must be uppercase SHA-256"
            )
        expected_scope["expected_run_parent_resolved_design_sha256"] = (
            expected_run_hash
        )
    authorized_run_id = scope.get("authorized_run_id")
    if authorized_run_id is not None:
        if (
            not isinstance(authorized_run_id, str)
            or not authorized_run_id
            or authorized_run_id != authorized_run_id.strip()
        ):
            raise ValueError("authorized_run_id must be a nonempty trimmed string")
        expected_scope["authorized_run_id"] = authorized_run_id
    if scope != expected_scope:
        raise ValueError("requested pilot identity differs from authorized scope")
    if run_id is not None and authorized_run_id is not None and run_id != authorized_run_id:
        raise ValueError("explicit run ID differs from authorized_run_id")
    if solver not in scope["allowed_solvers"]:
        raise ValueError(f"solver is not authorized: {solver}")
    if Path(runtime["particle_source"]["path"]).resolve() != particle_source_path.resolve():
        raise ValueError("particle source differs from authorized runtime profile")
    if "maximum_mesh_cells" in limits:
        mesh = runtime["solver_numerics"][solver]["values"].get("mesh", {})
        if (
            solver != "comsol"
            or mesh.get("strategy") != "physical_segment_hybrid_swept_tetra_v1"
        ):
            raise ValueError(
                "maximum_mesh_cells requires a COMSOL physical-segment hybrid mesh profile"
            )
    if "maximum_pa_grid_points" in limits and solver != "simion":
        raise ValueError("maximum_pa_grid_points is only valid for SIMION")
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
    if "maximum_mesh_cells" in limits:
        positive_limits.append(limits["maximum_mesh_cells"])
    if "maximum_pa_grid_points" in limits:
        positive_limits.append(limits["maximum_pa_grid_points"])
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in positive_limits):
        raise ValueError("resource limits must be positive integers")
    if limits["automatic_retry_count"] != 0:
        raise ValueError("automatic_retry_count must be zero")
    full_matrix = budget["full_matrix_authorization"]
    if (
        not isinstance(full_matrix, dict)
        or set(full_matrix) != {"authorized", "reason"}
        or full_matrix["authorized"] is not False
        or not isinstance(full_matrix["reason"], str)
        or not full_matrix["reason"]
    ):
        raise ValueError("full matrix must remain unauthorized during pilot")
    return {
        "schema_version": 1,
        "role": "multipole_resolved_resource_budget",
        "project_id": project_id,
        "solver": solver,
        "runtime_profile_id": runtime_profile_id,
        "stop_stage": stop_stage,
        "design_profile_id": design_profile_id,
        "particle_source_profile_id": runtime["particle_source"]["profile_id"],
        "solver_numerics_profile_id": runtime["solver_numerics"][solver]["profile_id"],
        "solver_numerics": runtime["solver_numerics"][solver]["values"],
        "retention_class": retention_class,
        "authorized_run_id": authorized_run_id,
        "expected_run_parent_resolved_design_sha256": expected_run_hash,
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
    parser.add_argument("--run-id")
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
        run_id=args.run_id,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MULTIPOLE_RESOURCE_BUDGET=PASS PROJECT={args.project_id} SOLVER={args.solver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
