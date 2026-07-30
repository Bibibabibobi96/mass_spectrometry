"""Evaluate L3 multipole convergence and converged cross-solver agreement."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev


COMSOL_PRIMARY_STATE_FILE = "particle_state__primary.csv"
SUPPORTED_SOLVERS = ("COMSOL", "SIMION")
PHYSICS_IDENTITY_FIELDS = (
    "model_level",
    "design_profile_id",
    "operating_mode_id",
    "operating_point_id",
)
PARTICLE_ENVELOPE_FIELDS = (
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "elapsed_time_us",
    "kinetic_energy_eV",
)
CANDIDATE_OBSERVABLE_FIELDS = (
    "rms_radius",
    "rms_divergence",
    "mean_energy",
    "mean_tof",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def physical_resolved_design_sha256(resolved: dict[str, Any]) -> str:
    """Hash compiled physics while excluding compiler and authority provenance."""
    payload = copy.deepcopy(resolved)
    for field in ("compiler", "governance", "sources", "resolved_sha256"):
        payload.pop(field, None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def solver_name(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item) for item in manifest.get("software", []))
    matches = [name for name in SUPPORTED_SOLVERS if name in software.upper()]
    if len(matches) != 1:
        raise ValueError("manifest must identify exactly one supported solver")
    return matches[0]


def manifest_record(manifest: dict[str, Any], filename: str) -> Path:
    matches = [
        Path(record["path"])
        for record in manifest.get("outputs", [])
        if Path(record["path"]).name == filename
    ]
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"manifest must contain exactly one existing {filename}")
    return matches[0]


def primary_case_id(manifest: dict[str, Any]) -> str:
    """Resolve the named primary case from retained machine-readable outputs."""
    case_ids: set[str] = set()
    for record in manifest.get("outputs", []):
        path = Path(record["path"])
        if path.suffix.lower() != ".json" or not path.is_file():
            continue
        try:
            value = load_json(path).get("primary_case_id")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if value:
            case_ids.add(str(value))
    if len(case_ids) != 1:
        raise ValueError("manifest outputs must identify exactly one primary_case_id")
    return case_ids.pop()


def primary_state_filename(manifest: dict[str, Any], solver: str) -> str:
    if solver == "COMSOL":
        return COMSOL_PRIMARY_STATE_FILE
    return f"particle_states__{primary_case_id(manifest)}.csv"


def mean_source_energy_from_particle_input(path: Path) -> float:
    """Calculate the normalization energy from the frozen solver-neutral source."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("particle source input is empty")
    particle_ids = [int(row["particle_id"]) for row in rows]
    if particle_ids != list(range(1, len(rows) + 1)):
        raise ValueError("particle source IDs must be contiguous, ordered, and one-based")
    energies = [
        kinetic_energy_ev(
            float(row["mass_amu"]),
            float(row["vx_m_s"]),
            float(row["vy_m_s"]),
            float(row["vz_m_s"]),
        )
        for row in rows
    ]
    return sum(energies) / len(energies)


def run_data(manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("status") != "success":
        raise ValueError(f"source run is not successful: {manifest_path}")
    solver = solver_name(manifest)
    config = load_json(Path(manifest["run_config"]["path"]))
    numerics = load_json(Path(manifest["inputs"]["solver_numerics"]["path"]))
    resolved = load_json(Path(manifest["inputs"]["multipole_resolved_design"]["path"]))
    state_path = manifest_record(manifest, primary_state_filename(manifest, solver))
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    handoff = {
        int(row["particle_id"]): row
        for row in rows
        if row["event"] == "handoff" and row["status"] == "transmitted"
    }
    if not handoff:
        raise ValueError("run has no transmitted handoff states")
    source = {
        int(row["particle_id"]): row
        for row in rows
        if row["event"] == "source"
    }
    if set(source) != set(range(1, len(source) + 1)):
        raise ValueError("source particle IDs must be contiguous and one-based")
    values = list(handoff.values())
    mean = lambda field: sum(float(row[field]) for row in values) / len(values)
    rms = lambda field: math.sqrt(
        sum(float(row[field]) ** 2 for row in values) / len(values)
    )
    exit_interface = resolved["interfaces_mm"]["exit"]
    aperture_radius = float(exit_interface["aperture_radius_mm"])
    projection_distance = float(exit_interface["census_plane_z_mm"]) - float(
        exit_interface["handoff_plane_z_mm"]
    )
    if aperture_radius <= 0 or projection_distance < 0:
        raise ValueError("exit aperture or handoff-to-census distance is invalid")
    rf_period_us = 1e6 / float(resolved["drive"]["frequency_Hz"])
    particle_source_path = Path(manifest["inputs"]["particle_source"]["path"])
    if not particle_source_path.is_file():
        raise ValueError("manifest particle_source input does not exist")
    mean_source_energy = mean_source_energy_from_particle_input(particle_source_path)
    rms_radius = rms("radial_position_mm")
    rms_divergence = rms("divergence_angle_deg")
    mean_tof = mean("elapsed_time_us")
    mean_energy = mean("kinetic_energy_eV")
    maximum_rod_radius = max(float(row["max_rod_radius_mm"]) for row in rows)
    working_radius = float(resolved["geometry_mm"]["enclosure"]["working_region_radius_mm"])
    margin_fraction = (working_radius - maximum_rod_radius) / working_radius
    return {
        "manifest": manifest,
        "config": config,
        "numerics": numerics,
        "solver": solver,
        "run_id": manifest["run_id"],
        "project": manifest["project"],
        "resolved_design_sha256": config["provenance"]["parent_resolved_design_sha256"],
        "physical_resolved_design_sha256": physical_resolved_design_sha256(
            resolved
        ),
        "particle_source_sha256": config["provenance"]["particle_source_sha256"],
        "scales": {
            "exit_aperture_radius_mm": aperture_radius,
            "handoff_to_census_distance_mm": projection_distance,
            "rf_period_us": rf_period_us,
            "mean_source_energy_eV": mean_source_energy,
        },
        "handoff_particle_ids": sorted(handoff),
        "source_particle_ids": sorted(source),
        "lost_particle_ids": sorted(set(source) - set(handoff)),
        "_handoff": handoff,
        "observables": {
            "transmission": len(handoff) / len(source),
            "transmitted_particle_count": len(handoff),
            "mean_tof": mean_tof,
            "rms_radius": rms_radius,
            "rms_divergence": rms_divergence,
            "mean_energy": mean_energy,
            "maximum_rod_radius": maximum_rod_radius,
            "minimum_working_radius_margin_fraction": margin_fraction,
            "rms_radius_exit_aperture_fraction": rms_radius / aperture_radius,
            "projected_divergence_exit_aperture_fraction": (
                projection_distance
                * math.tan(math.radians(rms_divergence))
                / aperture_radius
            ),
            "mean_tof_rf_periods": mean_tof / rf_period_us,
            "mean_energy_source_fraction": mean_energy / mean_source_energy,
        },
    }


def symmetric_relative(a: float, b: float) -> float:
    scale = (abs(a) + abs(b)) / 2
    return abs(a - b) / scale if scale else 0.0


def observable_differences(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    ao = a["observables"]
    bo = b["observables"]
    differences = {
        "transmitted_particle_count_difference": abs(
            ao["transmitted_particle_count"] - bo["transmitted_particle_count"]
        ),
        "rms_radius_exit_aperture_fraction_difference": abs(
            ao["rms_radius_exit_aperture_fraction"]
            - bo["rms_radius_exit_aperture_fraction"]
        ),
        "projected_divergence_exit_aperture_fraction_difference": abs(
            ao["projected_divergence_exit_aperture_fraction"]
            - bo["projected_divergence_exit_aperture_fraction"]
        ),
        "mean_tof_rf_period_difference": abs(
            ao["mean_tof_rf_periods"] - bo["mean_tof_rf_periods"]
        ),
        "mean_energy_source_fraction_difference": abs(
            ao["mean_energy_source_fraction"]
            - bo["mean_energy_source_fraction"]
        ),
        "transmission_absolute_difference": abs(
            ao["transmission"] - bo["transmission"]
        ),
        "mean_tof_relative_difference": symmetric_relative(ao["mean_tof"], bo["mean_tof"]),
        "rms_radius_relative_difference": symmetric_relative(ao["rms_radius"], bo["rms_radius"]),
        "rms_divergence_relative_difference": symmetric_relative(
            ao["rms_divergence"], bo["rms_divergence"]
        ),
        "mean_energy_relative_difference": symmetric_relative(
            ao["mean_energy"], bo["mean_energy"]
        ),
    }
    common_ids = sorted(set(a["_handoff"]) & set(b["_handoff"]))
    if common_ids:
        def paired_rms(fields: tuple[str, ...]) -> float:
            return math.sqrt(
                sum(
                    sum(
                        (
                            float(a["_handoff"][particle_id][field])
                            - float(b["_handoff"][particle_id][field])
                        )
                        ** 2
                        for field in fields
                    )
                    for particle_id in common_ids
                )
                / len(common_ids)
            )

        differences.update(
            paired_transverse_position_rms_difference_mm=paired_rms(
                ("transverse_x_mm", "transverse_y_mm")
            ),
            paired_transverse_velocity_rms_difference_m_s=paired_rms(
                ("velocity_x_m_s", "velocity_y_m_s")
            ),
            paired_elapsed_time_rms_difference_us=paired_rms(("elapsed_time_us",)),
            paired_energy_rms_difference_eV=paired_rms(("kinetic_energy_eV",)),
        )
    return differences


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
    elif axis == "spatial":
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        if solver == "COMSOL":
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
        else:
            path = ("cell_mm",)
        if without_path(coarse, path) != without_path(fine, path):
            errors.append("non-spatial solver numerics differ")
        coarse_value = coarse
        fine_value = fine
        for key in path:
            coarse_value = coarse_value[key]
            fine_value = fine_value[key]
        if not float(fine_value) < float(coarse_value):
            errors.append("refined spatial discretization is not smaller")
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
    checks = {}
    if axis != "mesh_strategy":
        checks.update(
            {
                name: differences[name] <= float(limit)
                for name, limit in maximum.items()
            }
        )
    elif maximum:
        checks.update(
            {
                name: differences[name] <= float(limit)
                for name, limit in maximum.items()
            }
        )
    for name, minimum in acceptance.get("minimum_each_run", {}).items():
        checks[f"baseline_{name}_minimum"] = (
            baseline["observables"][name] >= float(minimum)
        )
        checks[f"refined_or_peer_{name}_minimum"] = (
            refined["observables"][name] >= float(minimum)
        )
    for name in acceptance.get("positive_each_run", []):
        checks[f"baseline_{name}_positive"] = baseline["observables"][name] > 0
        checks[f"refined_or_peer_{name}_positive"] = (
            refined["observables"][name] > 0
        )
    checks["handoff_particle_id_sets"] = (
        baseline["handoff_particle_ids"] == refined["handoff_particle_ids"]
    )
    status = "PASS" if not errors and all(checks.values()) else "FAIL"
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
        choices=("spatial", "temporal", "cross_solver", "mesh_strategy"),
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
