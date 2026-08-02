"""Evaluate L3 multipole convergence and converged cross-solver agreement."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.numerical_observables import (
    CANDIDATE_OBSERVABLE_FIELDS,
    CELL_AXES,
    PARTICLE_ENVELOPE_FIELDS,
    PHYSICS_IDENTITY_FIELDS,
    SPATIAL_COMPARISON_AXES,
    SUPPORTED_SOLVERS,
    _load_hashed_json,
    load_json,
    normalize_simion_solver_numerics,
    observable_differences,
    run_data,
)

def compose_engineering_progression_contract(
    policy: dict[str, Any],
    functional_contract: dict[str, Any],
    *,
    functional_contract_sha256: str,
) -> dict[str, Any]:
    """Bind functional acceptance to the decomposed engineering capability."""
    supported_statuses = {
        "DRAFT_PENDING_ENERGY_THRESHOLDS",
        "ACTIVE_ENGINEERING_PROGRESSION_POLICY",
    }
    policy_status = policy.get("status")
    if (
        policy.get("role")
        != "multipole_engineering_progression_acceptance_contract"
        or policy_status not in supported_statuses
    ):
        raise ValueError("engineering progression policy identity differs")
    functional_binding = policy.get("functional_acceptance")
    if not isinstance(functional_binding, dict):
        raise ValueError("engineering progression functional binding is missing")
    if (
        functional_binding.get("required_result") != "PASS"
        or str(functional_binding.get("sha256", "")).upper()
        != functional_contract_sha256.upper()
    ):
        raise ValueError("engineering progression functional binding is stale")
    if functional_contract.get("claim_profile") != "functional_transport":
        raise ValueError("functional acceptance claim profile differs")

    comparison_kinds = policy.get("scope", {}).get("comparison_kinds")
    if comparison_kinds != ["same_solver_discretization", "cross_solver"]:
        raise ValueError("engineering progression comparison kinds differ")
    continuous = policy.get("continuous_engineering_acceptance")
    if not isinstance(continuous, dict):
        raise ValueError("continuous engineering acceptance is missing")
    if (
        continuous.get("comparison_operator")
        != "absolute_difference_less_than_or_equal"
        or continuous.get("all_approved_thresholds_required") is not True
        or continuous.get("energy_thresholds_required_before_activation")
        is not True
    ):
        raise ValueError("engineering progression observable contract differs")
    missing_result = continuous.get("missing_metric_result")
    if missing_result != "NOT_EVALUATED_DO_NOT_PROGRESS":
        raise ValueError("engineering progression missing-metric policy differs")

    policy_metrics = {
        ("spatial_observables", "centroid_position_difference_mm"): (
            "transverse_centroid_vector_difference_mm",
            False,
        ),
        ("spatial_observables", "centered_spatial_spread_difference_mm"): (
            "centered_spatial_rms_spread_absolute_difference_mm",
            False,
        ),
        ("angular_observables", "mean_direction_difference_deg"): (
            "mean_beam_direction_separation_deg",
            False,
        ),
        ("angular_observables", "centered_angular_spread_difference_deg"): (
            "centered_angular_rms_spread_absolute_difference_deg",
            False,
        ),
        ("energy_observables", "mean_energy_difference_eV"): (
            "mean_energy_absolute_difference_eV",
            True,
        ),
        ("energy_observables", "centered_energy_spread_difference_eV"): (
            "centered_rms_energy_spread_absolute_difference_eV",
            True,
        ),
    }
    maximum_limits = {}
    pending_metrics = []
    for (section_name, policy_name), (
        metric,
        may_be_pending,
    ) in policy_metrics.items():
        section = continuous.get(section_name)
        entry = section.get(policy_name) if isinstance(section, dict) else None
        if not isinstance(entry, dict):
            raise ValueError(
                f"engineering progression policy lacks {section_name}.{policy_name}"
            )
        value = entry.get("maximum")
        if value is None:
            if not may_be_pending:
                raise ValueError(
                    "approved spatial and angular limits must be present"
                )
            pending_metrics.append(metric)
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(
                "engineering progression limits must be finite and nonnegative"
            )
        maximum_limits[metric] = float(value)
    if policy_status == "ACTIVE_ENGINEERING_PROGRESSION_POLICY" and pending_metrics:
        raise ValueError("active engineering policy lacks required energy thresholds")

    result = copy.deepcopy(functional_contract)
    for acceptance_name in (
        "same_solver_acceptance",
        "cross_solver_acceptance",
    ):
        acceptance = result.get(acceptance_name)
        if not isinstance(acceptance, dict):
            raise ValueError(
                f"functional contract lacks {acceptance_name}"
            )
        maximum = acceptance.get("maximum")
        if not isinstance(maximum, dict):
            raise ValueError(f"{acceptance_name}.maximum must be an object")
        maximum.update(maximum_limits)
    result["claim_profile"] = "engineering_progression"
    result["claim_limit"] = policy["claim_limit"]
    result["missing_metric_result"] = missing_result
    result["engineering_required_difference_metrics"] = [
        *maximum_limits,
        *pending_metrics,
    ]
    result["pending_required_threshold_metrics"] = pending_metrics
    result["engineering_progression_policy"] = {
        "contract_id": policy["contract_id"],
        "functional_contract_sha256": functional_contract_sha256.upper(),
        "status": policy_status,
    }
    return result


def load_engineering_progression_contract(
    policy_path: Path,
    functional_contract_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load, hash, bind, and compose the shared engineering contract."""
    policy_path = policy_path.resolve()
    functional_contract_path = functional_contract_path.resolve()
    policy, policy_sha256 = _load_hashed_json(policy_path)
    functional_contract, functional_sha256 = _load_hashed_json(
        functional_contract_path
    )
    binding = policy.get("functional_acceptance")
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise ValueError("engineering progression functional path is missing")
    declared_path = binding["path"].replace("\\", "/").strip("/")
    actual_path = functional_contract_path.as_posix()
    if not declared_path or not (
        actual_path == declared_path
        or actual_path.endswith("/" + declared_path)
    ):
        raise ValueError("engineering progression functional path differs")
    contract = compose_engineering_progression_contract(
        policy,
        functional_contract,
        functional_contract_sha256=functional_sha256,
    )
    provenance = {
        "policy": {
            "path": str(policy_path),
            "sha256": policy_sha256,
            "contract_id": policy["contract_id"],
            "status": policy["status"],
        },
        "functional_contract": {
            "path": str(functional_contract_path),
            "sha256": functional_sha256,
            "contract_id": functional_contract["contract_id"],
        },
    }
    return contract, provenance


def _closed_interval(center: float, half_width: float) -> list[float]:
    if not math.isfinite(center) or not math.isfinite(half_width) or half_width < 0:
        raise ValueError("interval center and half-width must be finite and nonnegative")
    return [center - half_width, center + half_width]


def _same_particle_ids(runs: list[dict[str, Any]]) -> bool:
    return all(
        run["handoff_particle_ids"] == runs[0]["handoff_particle_ids"]
        for run in runs[1:]
    )


def standalone_candidate_envelope(
    solver_runs: dict[str, dict[str, dict[str, Any]]],
    minimum_transmission: float = 0.8,
) -> dict[str, Any]:
    """Build a conservative union of converged COMSOL and SIMION intervals.

    Each solver contributes a nominal run and its adjacent spatial and temporal
    refinements.  The numerical half-width is the larger absolute change from
    nominal along those two axes.  Solver intervals are then unioned; their
    center-to-center difference is therefore never treated as a separately
    invented percentage tolerance.
    """

    if set(solver_runs) != set(SUPPORTED_SOLVERS):
        raise ValueError("candidate envelope requires COMSOL and SIMION")
    required_levels = {"nominal", "spatial_refined", "temporal_refined"}
    all_runs: list[dict[str, Any]] = []
    per_solver: dict[str, Any] = {}
    identity_errors: list[str] = []
    for solver in SUPPORTED_SOLVERS:
        levels = solver_runs[solver]
        if set(levels) != required_levels:
            raise ValueError(
                f"{solver} candidate runs must be nominal, spatial_refined, "
                "and temporal_refined"
            )
        nominal = levels["nominal"]
        spatial = levels["spatial_refined"]
        temporal = levels["temporal_refined"]
        runs = [nominal, spatial, temporal]
        all_runs.extend(runs)
        if any(run["solver"] != solver for run in runs):
            identity_errors.append(f"{solver} run labels differ from solver")
        identity_errors.extend(
            f"{solver} spatial: {error}"
            for error in validate_identity(nominal, spatial, "spatial")
        )
        identity_errors.extend(
            f"{solver} temporal: {error}"
            for error in validate_identity(nominal, temporal, "temporal")
        )
        if not _same_particle_ids(runs):
            identity_errors.append(f"{solver} adjacent numerical particle IDs differ")

        particle_intervals: dict[str, Any] = {}
        if _same_particle_ids(runs):
            for particle_id in nominal["handoff_particle_ids"]:
                fields = {}
                for field in PARTICLE_ENVELOPE_FIELDS:
                    center = float(nominal["_handoff"][particle_id][field])
                    spatial_change = abs(
                        center - float(spatial["_handoff"][particle_id][field])
                    )
                    temporal_change = abs(
                        center - float(temporal["_handoff"][particle_id][field])
                    )
                    half_width = max(spatial_change, temporal_change)
                    fields[field] = {
                        "nominal": center,
                        "numerical_half_width": half_width,
                        "interval": _closed_interval(center, half_width),
                    }
                particle_intervals[str(particle_id)] = fields

        observable_intervals = {}
        for field in CANDIDATE_OBSERVABLE_FIELDS:
            center = float(nominal["observables"][field])
            half_width = max(
                abs(center - float(spatial["observables"][field])),
                abs(center - float(temporal["observables"][field])),
            )
            observable_intervals[field] = {
                "nominal": center,
                "numerical_half_width": half_width,
                "interval": _closed_interval(center, half_width),
            }
        per_solver[solver] = {
            "run_ids": {level: levels[level]["run_id"] for level in sorted(levels)},
            "handoff_particle_ids": nominal["handoff_particle_ids"],
            "lost_particle_ids": nominal.get("lost_particle_ids", []),
            "particle_intervals": particle_intervals,
            "observable_intervals": observable_intervals,
        }

    nominal_runs = [solver_runs[solver]["nominal"] for solver in SUPPORTED_SOLVERS]
    if not _same_particle_ids(nominal_runs):
        identity_errors.append("cross-solver nominal particle IDs differ")
    for solver in SUPPORTED_SOLVERS[1:]:
        identity_errors.extend(
            f"cross-solver: {error}"
            for error in validate_identity(
                solver_runs[SUPPORTED_SOLVERS[0]]["nominal"],
                solver_runs[solver]["nominal"],
                "cross_solver",
            )
        )

    union_observables = {}
    for field in CANDIDATE_OBSERVABLE_FIELDS:
        intervals = [
            per_solver[solver]["observable_intervals"][field]["interval"]
            for solver in SUPPORTED_SOLVERS
        ]
        union_observables[field] = [
            min(interval[0] for interval in intervals),
            max(interval[1] for interval in intervals),
        ]

    union_particles: dict[str, Any] = {}
    common_ids = set(per_solver[SUPPORTED_SOLVERS[0]]["particle_intervals"])
    common_ids &= set(per_solver[SUPPORTED_SOLVERS[1]]["particle_intervals"])
    for particle_id in sorted(common_ids, key=int):
        fields = {}
        for field in PARTICLE_ENVELOPE_FIELDS:
            intervals = [
                per_solver[solver]["particle_intervals"][particle_id][field][
                    "interval"
                ]
                for solver in SUPPORTED_SOLVERS
            ]
            fields[field] = [
                min(interval[0] for interval in intervals),
                max(interval[1] for interval in intervals),
            ]
        x_interval = fields["transverse_x_mm"]
        y_interval = fields["transverse_y_mm"]
        radial_upper = math.hypot(
            max(abs(value) for value in x_interval),
            max(abs(value) for value in y_interval),
        )
        union_particles[particle_id] = {
            "fields": fields,
            "worst_transverse_radius_mm": radial_upper,
        }

    aperture_radius = min(
        float(run["scales"]["exit_aperture_radius_mm"]) for run in all_runs
    )
    worst_radius = max(
        (
            particle["worst_transverse_radius_mm"]
            for particle in union_particles.values()
        ),
        default=math.inf,
    )
    checks = {
        "identity": not identity_errors,
        "minimum_transmission": all(
            float(run["observables"]["transmission"]) >= minimum_transmission
            for run in all_runs
        ),
        "exact_handoff_particle_ids": _same_particle_ids(all_runs),
        "positive_rod_margin": all(
            float(run["observables"]["minimum_working_radius_margin_fraction"]) > 0
            for run in all_runs
        ),
        "positive_aperture_margin": worst_radius < aperture_radius,
    }
    return {
        "schema_version": 1,
        "role": "multipole_standalone_candidate_envelope",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "method": (
            "per-solver max(spatial adjacent change, temporal adjacent change), "
            "followed by closed-interval union across solvers"
        ),
        "minimum_transmission": minimum_transmission,
        "identity_errors": identity_errors,
        "checks": checks,
        "per_solver": per_solver,
        "union": {
            "observable_intervals": union_observables,
            "particle_intervals": union_particles,
            "exit_aperture_radius_mm": aperture_radius,
            "worst_transverse_radius_mm": worst_radius,
            "minimum_aperture_margin_mm": aperture_radius - worst_radius,
        },
        "claim_limit": (
            "Numerical Candidate envelope only; no mode superiority or Formal "
            "mechanical claim."
        ),
    }


def without_path(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    parent: Any = result
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    return result


def physics_identity(config: dict[str, Any]) -> dict[str, Any]:
    """Return the run-config fields that bind one multipole physics case."""
    parameters = config.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("run config parameters must be an object")
    missing = [name for name in PHYSICS_IDENTITY_FIELDS if name not in parameters]
    if "mode" not in config:
        missing.append("mode")
    if missing:
        raise ValueError(
            "run config is missing physics identity fields: " + ", ".join(missing)
        )
    return {
        "mode": config["mode"],
        **{name: parameters[name] for name in PHYSICS_IDENTITY_FIELDS},
    }


def validate_identity(
    baseline: dict[str, Any], refined: dict[str, Any], axis: str
) -> list[str]:
    errors = []
    identity_fields = ["project", "particle_source_sha256"]
    identity_fields.append(
        "physical_resolved_design_sha256"
        if axis == "mesh_strategy"
        else "resolved_design_sha256"
    )
    for field in identity_fields:
        if baseline[field] != refined[field]:
            errors.append(f"{field} differs")
    if baseline["scales"] != refined["scales"]:
        errors.append("normalization scales differ")
    if axis == "cross_solver":
        if baseline["solver"] == refined["solver"]:
            errors.append("cross-solver comparison requires different solvers")
        return errors
    if baseline["solver"] != refined["solver"]:
        errors.append("same-solver comparison requires one solver")
        return errors
    solver = baseline["solver"]
    if axis == "mesh_strategy":
        try:
            if physics_identity(baseline["config"]) != physics_identity(
                refined["config"]
            ):
                errors.append("physics identity differs")
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        coarse_mesh = coarse.get("mesh")
        fine_mesh = fine.get("mesh")
        if not isinstance(coarse_mesh, dict) or not isinstance(fine_mesh, dict):
            errors.append("mesh-strategy comparison requires mesh objects")
        else:
            if without_path(coarse, ("mesh",)) != without_path(fine, ("mesh",)):
                errors.append("non-mesh solver numerics differ")
            if coarse_mesh == fine_mesh:
                errors.append("mesh objects do not differ")
            if coarse_mesh.get("strategy") == fine_mesh.get("strategy"):
                errors.append("mesh strategies do not differ")
    elif axis in SPATIAL_COMPARISON_AXES:
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        if solver == "COMSOL":
            if axis != "spatial":
                errors.append(
                    "COMSOL supports only the generic spatial comparison axis"
                )
                return errors
            candidate_paths = (
                ("mesh", "working_region_maximum_element_size_mm"),
                (
                    "mesh",
                    "hybrid",
                    "sensitive_region",
                    "maximum_element_size_mm",
                ),
                (
                    "mesh",
                    "hybrid",
                    "sensitive_region",
                    "exit_interface_refinement",
                    "maximum_element_size_mm",
                ),
            )
            changed_paths = []
            for candidate_path in candidate_paths:
                coarse_value: Any = coarse
                fine_value: Any = fine
                try:
                    for key in candidate_path:
                        coarse_value = coarse_value[key]
                        fine_value = fine_value[key]
                except (KeyError, TypeError):
                    continue
                if coarse_value != fine_value:
                    changed_paths.append(candidate_path)
            if len(changed_paths) != 1:
                errors.append(
                    "COMSOL spatial comparison must change exactly one supported "
                    "mesh-size axis"
                )
                return errors
            path = changed_paths[0]
            if without_path(coarse, path) != without_path(fine, path):
                errors.append("non-spatial solver numerics differ")
            coarse_value = coarse
            fine_value = fine
            for key in path:
                coarse_value = coarse_value[key]
                fine_value = fine_value[key]
            if not float(fine_value) < float(coarse_value):
                errors.append("refined spatial discretization is not smaller")
        else:
            try:
                coarse = normalize_simion_solver_numerics(coarse)
                fine = normalize_simion_solver_numerics(fine)
            except ValueError as exc:
                errors.append(str(exc))
                return errors
            coarse_cell = coarse["cell_mm_xyz"]
            fine_cell = fine["cell_mm_xyz"]
            coarse_without_cell = dict(coarse)
            fine_without_cell = dict(fine)
            del coarse_without_cell["cell_mm_xyz"]
            del fine_without_cell["cell_mm_xyz"]
            if coarse_without_cell != fine_without_cell:
                errors.append("non-spatial solver numerics differ")
            refined_axes = {
                "spatial": set(CELL_AXES),
                "spatial_radial": {"x", "y"},
                "spatial_axial": {"z"},
                "spatial_isotropic": set(CELL_AXES),
            }[axis]
            for cell_axis in CELL_AXES:
                coarse_value = float(coarse_cell[cell_axis])
                fine_value = float(fine_cell[cell_axis])
                if cell_axis in refined_axes:
                    if not fine_value < coarse_value:
                        errors.append(
                            f"refined SIMION {cell_axis}-cell spacing is not smaller"
                        )
                elif fine_value != coarse_value:
                    errors.append(
                        f"non-target SIMION {cell_axis}-cell spacing differs"
                    )
    elif axis == "temporal":
        path = ("trajectory", "rf_steps_per_period")
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        if without_path(coarse, path) != without_path(fine, path):
            errors.append("non-temporal solver numerics differ")
        if not int(fine["trajectory"]["rf_steps_per_period"]) > int(
            coarse["trajectory"]["rf_steps_per_period"]
        ):
            errors.append("refined RF steps per period is not larger")
    else:
        errors.append(f"unsupported comparison axis: {axis}")
    return errors


def evaluate(
    baseline: dict[str, Any],
    refined: dict[str, Any],
    axis: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    required_acceptance = (
        ("same_solver_acceptance",)
        if axis == "mesh_strategy"
        else ("same_solver_acceptance", "cross_solver_acceptance")
    )
    for name in required_acceptance:
        if name not in contract:
            raise ValueError(
                "method-only contract cannot qualify results; supply a preregistered "
                f"applicable contract containing {name}"
            )
    errors = validate_identity(baseline, refined, axis)
    differences = observable_differences(baseline, refined)
    acceptance_name = (
        "cross_solver_acceptance" if axis == "cross_solver"
        else "same_solver_acceptance"
    )
    acceptance = contract[acceptance_name]
    maximum = acceptance.get("maximum")
    if axis == "mesh_strategy" and maximum is not None and not isinstance(
        maximum, dict
    ):
        raise ValueError(
            "mesh-strategy same_solver_acceptance.maximum must be an object"
        )
    if axis == "mesh_strategy" and set(maximum or {}) - {
        "transmitted_particle_count_difference"
    }:
        raise ValueError(
            "mesh-strategy functional screening cannot apply continuous "
            "difference limits"
        )
    if axis != "mesh_strategy" and (
        not isinstance(maximum, dict) or not maximum
    ):
        raise ValueError(f"{acceptance_name}.maximum must define accepted differences")
    checks: dict[str, bool] = {}
    missing_metric_checks: set[str] = set()
    for name, limit in (maximum or {}).items():
        if name not in differences:
            raise ValueError(f"{acceptance_name}.maximum has unknown metric {name}")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(float(limit))
            or float(limit) < 0
        ):
            raise ValueError(f"{acceptance_name}.maximum.{name} must be finite")
        value = differences[name]
        if value is None or not math.isfinite(float(value)):
            checks[name] = False
            missing_metric_checks.add(name)
        else:
            checks[name] = float(value) <= float(limit)
    for name, minimum in acceptance.get("minimum_each_run", {}).items():
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, (int, float))
            or not math.isfinite(float(minimum))
        ):
            raise ValueError(f"{acceptance_name}.minimum_each_run.{name} is invalid")
        baseline_value = baseline["observables"].get(name)
        refined_value = refined["observables"].get(name)
        checks[f"baseline_{name}_minimum"] = (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and math.isfinite(float(baseline_value))
            and float(baseline_value) >= float(minimum)
        )
        checks[f"refined_or_peer_{name}_minimum"] = (
            isinstance(refined_value, (int, float))
            and not isinstance(refined_value, bool)
            and math.isfinite(float(refined_value))
            and float(refined_value) >= float(minimum)
        )
    for name in acceptance.get("positive_each_run", []):
        baseline_value = baseline["observables"].get(name)
        refined_value = refined["observables"].get(name)
        checks[f"baseline_{name}_positive"] = (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and math.isfinite(float(baseline_value))
            and float(baseline_value) > 0
        )
        checks[f"refined_or_peer_{name}_positive"] = (
            isinstance(refined_value, (int, float))
            and not isinstance(refined_value, bool)
            and math.isfinite(float(refined_value))
            and float(refined_value) > 0
        )
    baseline_ids = baseline.get("handoff_particle_ids")
    refined_ids = refined.get("handoff_particle_ids")
    baseline_handoff = baseline.get("_handoff")
    refined_handoff = refined.get("_handoff")
    exact_handoff_ids = (
        isinstance(baseline_ids, list)
        and isinstance(refined_ids, list)
        and len(baseline_ids) == len(set(baseline_ids))
        and len(refined_ids) == len(set(refined_ids))
        and isinstance(baseline_handoff, dict)
        and isinstance(refined_handoff, dict)
        and baseline_ids == sorted(baseline_handoff)
        and refined_ids == sorted(refined_handoff)
        and baseline_ids == refined_ids
    )
    checks["handoff_particle_id_sets"] = exact_handoff_ids
    nonmissing_failure = any(
        not passed and name not in missing_metric_checks
        for name, passed in checks.items()
    )
    engineering = contract.get("claim_profile") == "engineering_progression"
    policy_status = contract.get("engineering_progression_policy", {}).get(
        "status"
    )
    pending_thresholds = contract.get("pending_required_threshold_metrics", [])
    if errors or nonmissing_failure:
        status = "FAIL"
    elif missing_metric_checks or (
        engineering
        and (
            policy_status != "ACTIVE_ENGINEERING_PROGRESSION_POLICY"
            or pending_thresholds
        )
    ):
        status = contract.get(
            "missing_metric_result", "NOT_EVALUATED_DO_NOT_PROGRESS"
        )
    else:
        status = "PASS"
    result = {
        "schema_version": 1,
        "role": "multipole_l3_numerical_qualification_result",
        "status": status,
        "comparison_axis": axis,
        "claim_profile": contract.get("claim_profile"),
        "baseline": {
            key: baseline[key]
            for key in ("run_id", "project", "solver", "scales", "observables")
        },
        "refined_or_peer": {
            key: refined[key]
            for key in ("run_id", "project", "solver", "scales", "observables")
        },
        "identity_errors": errors,
        "differences": differences,
        "acceptance": acceptance,
        "checks": checks,
        "claim_limit": contract["claim_limit"],
    }
    if engineering:
        result["engineering_progression_status"] = status
        result["numerical_convergence_status"] = "DEFERRED_NOT_WAIVED"
        result["missing_required_metrics"] = sorted(missing_metric_checks)
        result["pending_required_threshold_metrics"] = list(pending_thresholds)
    if axis == "mesh_strategy":
        result["functional_status"] = status
        result["continuous_status"] = "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--refined-manifest", required=True, type=Path)
    parser.add_argument(
        "--axis",
        required=True,
        choices=(
            "spatial",
            "spatial_radial",
            "spatial_axial",
            "spatial_isotropic",
            "temporal",
            "cross_solver",
            "mesh_strategy",
        ),
    )
    parser.add_argument(
        "--contract",
        required=True,
        type=Path,
        help="Preregistered project or explicitly applicable shared acceptance contract.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        run_data(args.baseline_manifest),
        run_data(args.refined_manifest),
        args.axis,
        load_json(args.contract),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    status_line = (
        f"MULTIPOLE_NUMERICAL_QUALIFICATION={result['status']} "
        f"AXIS={args.axis} OUTPUT={args.output.resolve()}"
    )
    if args.axis == "mesh_strategy":
        status_line += (
            f" FUNCTIONAL={result['functional_status']} "
            f"CONTINUOUS={result['continuous_status']}"
        )
    print(status_line)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
