"""Fail closed unless a requested multipole commercial-solver pilot is authorized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from projects.rf_multipole_ion_optics.core.compile_design_request import resolved_design_sha256

from projects.rf_multipole_ion_optics.runtime.runtime_profile import (
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


def validate_resource_limits(limits: dict[str, Any], full_matrix: dict[str, Any]) -> None:
    """Existing pilot numeric/no-retry/no-matrix policy for all consumers."""
    _require_limit_keys(limits)
    wall_clock = limits["wall_clock_seconds_by_solver"]
    if set(wall_clock) != {"comsol", "simion"}:
        raise ValueError("wall-clock solver keys differ")
    positive_limits = list(wall_clock.values()) + [
        limits[name]
        for name in (
            "transient_run_directory_bytes",
            "process_tree_working_set_bytes",
            "minimum_system_available_memory_bytes",
            "compact_final_retained_bytes",
        )
    ]
    if "maximum_mesh_cells" in limits:
        positive_limits.append(limits["maximum_mesh_cells"])
    if "maximum_pa_grid_points" in limits:
        positive_limits.append(limits["maximum_pa_grid_points"])
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in positive_limits):
        raise ValueError("resource limits must be positive integers")
    if limits["automatic_retry_count"] != 0:
        raise ValueError("automatic_retry_count must be zero")
    if (
        not isinstance(full_matrix, dict)
        or set(full_matrix) != {"authorized", "reason"}
        or full_matrix["authorized"] is not False
        or not isinstance(full_matrix["reason"], str)
        or not full_matrix["reason"]
    ):
        raise ValueError("full matrix must remain unauthorized during pilot")


def validate_budget_authorization(budget: dict[str, Any], project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the existing engineering contract without resolving scientific profiles."""
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
    allowed_solvers = scope["allowed_solvers"]
    if (
        not isinstance(allowed_solvers, list)
        or not allowed_solvers
        or len(set(allowed_solvers)) != len(allowed_solvers)
        or not set(allowed_solvers).issubset({"comsol", "simion"})
    ):
        raise ValueError("allowed_solvers must be a nonempty unique supported subset")
    return scope, limits


def validate_analysis_budget(
    budget: dict[str, Any], *, parent_config: dict[str, Any],
    parent_budget: dict[str, Any], source_metadata: dict[str, Any],
    retention_class: str, run_id: str,
) -> dict[str, Any]:
    """Authorize only new analysis payload against original frozen science.

    Existing input/output CSVs and native models remain protected references.
    This function does not resolve profiles, generate a source or authorize a solve.
    """
    project = parent_config["project"]
    scope, limits = validate_budget_authorization(budget, project)
    parameters = parent_config["parameters"]
    if parent_budget.get("role") == "multipole_engineering_budget_contract":
        expected = dict(parent_budget["pilot_authorization"]["scope"])
    elif parent_budget.get("role") == "multipole_transport_experiment_campaign":
        rows = [row for row in parent_budget["experiments"]
                if row["experiment_id"] == parameters["runtime_profile_id"]]
        if len(rows) != 1:
            raise ValueError("parent frozen campaign budget is not unique")
        row = rows[0]
        simion = row["simion_solver_numerics"]
        simion_id = simion["profile_id"] if simion["kind"] == "profile" else simion["numerics_id"]
        expected = dict(project_id=row["project_id"], runtime_profile_id=row["experiment_id"],
                        stop_stage=row["stop_stage"], design_profile_id=row["design_profile_id"],
                        particle_source_profile_id=row["particle_source_profile_id"],
                        particle_count=source_metadata["particle_count"],
                        solver_numerics_profile_ids=dict(comsol=row["comsol_solver_numerics_profile_id"], simion=simion_id),
                        allowed_solvers=[row["solver"]], retention_class=row["retention_class"])
    else:
        raise ValueError("parent has no supported frozen engineering scope; analysis will not resolve current defaults")
    if (expected["project_id"] != project or expected["runtime_profile_id"] != parameters["runtime_profile_id"]
            or expected["design_profile_id"] != parameters["design_profile_id"]
            or expected["stop_stage"] != "transport" or expected["particle_count"] != source_metadata["particle_count"]):
        raise ValueError("parent frozen budget scope differs from its science/source authority")
    count = source_metadata["particle_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("parent frozen mother count must be a positive integer")
    # These two fields belong to this new execution, not the parent's identity.
    expected.pop("authorized_run_id", None)
    expected["retention_class"] = retention_class
    if "authorized_run_id" in scope:
        if not isinstance(scope["authorized_run_id"], str) or scope["authorized_run_id"] != run_id:
            raise ValueError("analysis authorized_run_id differs from its new run")
        expected["authorized_run_id"] = run_id
    if "expected_run_parent_resolved_design_sha256" in scope:
        original = parent_config["provenance"]["parent_resolved_design_sha256"]
        if scope["expected_run_parent_resolved_design_sha256"] != original:
            raise ValueError("analysis budget logical design differs from frozen parent")
        expected["expected_run_parent_resolved_design_sha256"] = original
    if scope != expected:
        raise ValueError("analysis budget scope differs from original frozen science")
    validate_resource_limits(limits, budget["full_matrix_authorization"])
    return dict(schema_version=1, role="multipole_resolved_resource_budget", project_id=project,
                runtime_profile_id=scope["runtime_profile_id"], design_profile_id=scope["design_profile_id"],
                stop_stage="transport", solver="comsol", retention_class=retention_class,
                limits={**limits, "wall_clock_seconds": limits["wall_clock_seconds_by_solver"]["comsol"]})


def validate_pilot_budget(
    *,
    repo_root: Path,
    budget_path: Path,
    project_id: str,
    solver: str,
    runtime_profile_id: str,
    design_profile_id: str,
    particle_source_path: Path | None = None,
    retention_class: str,
    run_id: str | None = None,
    resolved_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the runtime profile and validate the exact authorized pilot."""

    if resolved_runtime is not None:
        runtime = resolved_runtime
        if (runtime.get("role") != "multipole_resolved_runtime_profile"
                or runtime.get("project_id") != project_id
                or runtime.get("runtime_profile_id") != runtime_profile_id
                or runtime.get("design_profile_id") != design_profile_id):
            raise ValueError("resolved runtime identity differs from the budget request")
        design = runtime["design_profile_resolution"]["resolved_design"]
        if design.get("resolved_sha256") != resolved_design_sha256(design):
            raise ValueError("resolved runtime contains a stale logical design identity")
        budget = runtime["engineering_budget"]["inline_contract"]
        authority = _load(budget_path.resolve())
        if authority.get("role") == "multipole_engineering_budget_contract":
            if authority != budget:
                raise ValueError("frozen engineering-budget definition differs from its authority")
        elif authority.get("role") == "multipole_transport_experiment_campaign":
            rows = [row for row in authority["experiments"] if row["experiment_id"] == runtime_profile_id]
            if len(rows) != 1:
                raise ValueError("frozen campaign budget experiment is not unique")
            authorization = rows[0]["resource_authorization"]
            if (budget["pilot_authorization"]["authorized"] != authorization["authorized"]
                    or budget["pilot_authorization"]["limits"] != authorization["limits"]
                    or budget["full_matrix_authorization"] != authorization["full_matrix_authorization"]):
                raise ValueError("frozen campaign budget differs from its authorization")
        else:
            raise ValueError("resolved runtime budget authority is unsupported")
    else:
        budget_source = _load(budget_path.resolve())
        if budget_source.get("role") == "multipole_transport_experiment_campaign":
            runtime = resolve_runtime_selection(
                repo_root.resolve(), project_id, campaign_path=budget_path.resolve(),
                experiment_id=runtime_profile_id,
            )
            budget = runtime["engineering_budget"]["inline_contract"]
        else:
            runtime = resolve_runtime_profile(repo_root.resolve(), project_id, runtime_profile_id)
            budget = budget_source
    stop_stage = runtime.get("stop_stage")
    if stop_stage not in {"transport", "mesh_build", "field_solve"}:
        raise ValueError("resolved runtime profile stop stage is missing or unsupported")
    expected_budget = Path(runtime["engineering_budget"]["path"]).resolve()
    if budget_path.resolve() != expected_budget:
        raise ValueError("engineering-budget path differs from runtime profile")
    scope, limits = validate_budget_authorization(budget, project_id)
    allowed_solvers = scope["allowed_solvers"]
    expected_scope = {
        "project_id": project_id,
        "runtime_profile_id": runtime_profile_id,
        "stop_stage": stop_stage,
        "design_profile_id": design_profile_id,
        "particle_source_profile_id": runtime["particle_source"]["profile_id"],
        "particle_count": (
            runtime["particle_source"]["particle_count"]
            if "release_spec" in runtime["particle_source"]
            else _particle_count(Path(runtime["particle_source"]["path"]))
        ),
        "solver_numerics_profile_ids": {
            name: runtime["solver_numerics"][name]["profile_id"] for name in ("comsol", "simion")
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
            raise ValueError("expected_run_parent_resolved_design_sha256 must be uppercase SHA-256")
        expected_scope["expected_run_parent_resolved_design_sha256"] = expected_run_hash
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
    if "release_spec" in runtime["particle_source"]:
        if particle_source_path is not None:
            raise ValueError("release-spec runtime does not accept an external particle source")
        if solver != "simion":
            raise ValueError("release-spec materialization is currently implemented for SIMION only")
    elif (
        particle_source_path is None
        or Path(runtime["particle_source"]["path"]).resolve() != particle_source_path.resolve()
    ):
        raise ValueError("particle source differs from authorized runtime profile")
    if "maximum_mesh_cells" in limits:
        mesh = runtime["solver_numerics"][solver]["values"].get("mesh", {})
        if solver != "comsol" or mesh.get("strategy") != "physical_segment_hybrid_swept_tetra_v1":
            raise ValueError("maximum_mesh_cells requires a COMSOL physical-segment hybrid mesh profile")
    if "maximum_pa_grid_points" in limits and solver != "simion":
        raise ValueError("maximum_pa_grid_points is only valid for SIMION")
    validate_resource_limits(limits, budget["full_matrix_authorization"])
    wall_clock = limits["wall_clock_seconds_by_solver"]
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
        **({"particle_source": runtime["particle_source"]} if "release_spec" in runtime["particle_source"] else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--solver", required=True, choices=("comsol", "simion"))
    parser.add_argument("--runtime-profile-id", required=True)
    parser.add_argument("--design-profile-id", required=True)
    parser.add_argument("--particle-source", type=Path)
    parser.add_argument("--retention-class", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resolved-runtime-profile", type=Path)
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
        resolved_runtime=(_load(args.resolved_runtime_profile) if args.resolved_runtime_profile else None),
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MULTIPOLE_RESOURCE_BUDGET=PASS PROJECT={args.project_id} SOLVER={args.solver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
