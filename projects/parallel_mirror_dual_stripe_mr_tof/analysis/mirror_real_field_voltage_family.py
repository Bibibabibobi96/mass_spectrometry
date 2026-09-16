"""Solve the mirror L0 voltage family from sampled finite-3-D PA responses.

The manufactured geometry and its refined response PAs are immutable inputs.
Only the four symmetric mirror coordinates B--E are recombined.  The axial
model is a fast search surrogate; every selected member still requires a
native SIMION trajectory and transverse L1 validation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.integrate import IntegrationWarning, quad
from scipy.interpolate import CubicSpline
from scipy.optimize import brentq, least_squares

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period import (
    load_exact_k_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")
REGION_LIMITS = {
    "mirror_turn_negative": (-319.0, -131.0),
    "stripe_mirror_bridge_negative": (-131.0, -72.0),
    "central_transport": (-72.0, 72.0),
    "stripe_mirror_bridge_positive": (72.0, 131.0),
    "mirror_turn_positive": (131.0, 319.0),
}


def load_numerical_profile(contract_path: Path) -> dict[str, Any]:
    """Load the sole authority for finite-3-D L0 family numerics."""
    contract = _object(contract_path, "MR-TOF baseline contract")
    try:
        source = contract["mirror"]["theory_requirements"][
            "real_3d_l0_voltage_family_profile"
        ]
    except (KeyError, TypeError) as exc:
        raise CandidateContractError(
            "baseline contract lacks the real-3-D L0 voltage-family profile"
        ) from exc
    if not isinstance(source, Mapping):
        raise CandidateContractError("real-3-D L0 voltage-family profile must be an object")
    scheme = str(source.get("voltage_jacobian_scheme", ""))
    if scheme != "three_point_central":
        raise CandidateContractError("real-3-D L0 voltage Jacobian scheme is unsupported")
    try:
        profile = {
            "response_grid_spacing_mm": float(source["response_grid_spacing_mm"]),
            "axis_probe_y_mm": float(source["axis_probe_y_mm"]),
            "e_voltage_slice_count": int(source["e_voltage_slice_count"]),
            "voltage_jacobian_scheme": scheme,
            "voltage_jacobian_relative_step": float(
                source["voltage_jacobian_relative_step"]
            ),
            "maximum_function_evaluations_per_e_slice": int(
                source["maximum_function_evaluations_per_e_slice"]
            ),
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CandidateContractError(
            "real-3-D L0 voltage-family profile is incomplete"
        ) from exc
    finite_positive = (
        "response_grid_spacing_mm",
        "voltage_jacobian_relative_step",
    )
    if any(
        not math.isfinite(profile[key]) or profile[key] <= 0.0
        for key in finite_positive
    ):
        raise CandidateContractError("real-3-D L0 profile contains a non-positive value")
    if not math.isfinite(profile["axis_probe_y_mm"]):
        raise CandidateContractError("real-3-D L0 axis probe must be finite")
    if (
        profile["e_voltage_slice_count"] < 3
        or profile["maximum_function_evaluations_per_e_slice"] < 1
    ):
        raise CandidateContractError("real-3-D L0 profile contains an invalid count")
    return profile


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def _cache_generation(
    family_run: Path, cache_root: Path,
) -> tuple[dict[str, Any], Path, str, str]:
    contract = _object(
        family_run / "results" / "analyzer_local_pa_family_contract.json",
        "local-family contract",
    )
    identity = _object(
        family_run / "results" / "pa_family_cache_identity.json",
        "local-family identity",
    )
    publication = _object(
        family_run / "results" / "pa_family_cache_publication.json",
        "local-family publication",
    )
    cache_key = str(publication.get("cache_key", ""))
    if canonical_pa_family_cache_key(identity) != cache_key:
        raise CandidateContractError("local-family identity and publication differ")
    pointer = _object(cache_root / cache_key / "current_generation.json", "cache pointer")
    generation_sha = str(pointer.get("generation_sha256", ""))
    generation = cache_root / cache_key / "generations" / generation_sha
    manifest = _object(generation / "cache_manifest.json", "cache manifest")
    if (
        pointer.get("cache_key") != cache_key
        or manifest.get("cache_key") != cache_key
        or manifest.get("generation_sha256") != generation_sha
        or manifest.get("identity") != identity
    ):
        raise CandidateContractError("local-family current generation is inconsistent")
    return contract, generation, cache_key, generation_sha


def prepare_sampling_plan(
    local_workbench_run: Path,
    exact_k_run: Path,
    cache_root: Path,
    contract_path: Path,
    output_directory: Path,
) -> dict[str, Any]:
    """Resolve verified B--E standalone responses and deterministic samples."""
    workbench = local_workbench_run.resolve()
    config = _object(workbench / "run_config.json", "local workbench config")
    manifest = _object(workbench / "run_manifest.json", "local workbench manifest")
    if (
        config.get("mode") != "analyzer_local_replacement_workbench"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("response sampling needs a successful local workbench")
    numerical_profile = load_numerical_profile(contract_path)
    step = float(numerical_profile["response_grid_spacing_mm"])
    probe_y_mm = float(numerical_profile["axis_probe_y_mm"])
    subdivisions = 0.5 / step if step > 0.0 else math.nan
    if (
        not math.isfinite(step)
        or step <= 0.0
        or not math.isclose(subdivisions, round(subdivisions), abs_tol=1e-12)
    ):
        raise CandidateContractError("sample step must divide the 0.5-mm response grid")
    loaded = load_exact_k_point(exact_k_run)
    l0 = loaded["l0"]
    energies = [float(value) for value in l0["three_point"]["energies_v"]]
    derivative_step = float(l0["period_slope_derivative_step_v"])
    base_voltages = [float(value) for value in loaded["point"]["mirror_voltages_v"]]
    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        raise CandidateContractError("local workbench parameters are missing")
    normalization = float(parameters.get("basis_voltage_v"))
    if normalization <= 0.0:
        raise CandidateContractError("response basis normalization must be positive")
    family_manifests = config.get("inputs", {}).get("local_family_manifests")
    if not isinstance(family_manifests, list) or len(family_manifests) != 5:
        raise CandidateContractError("local workbench must bind five local families")
    output_directory.mkdir(parents=True, exist_ok=True)
    regions = []
    seen: set[str] = set()
    for manifest_path in family_manifests:
        family_run = Path(str(manifest_path)).resolve().parent
        family_manifest = _object(family_run / "run_manifest.json", "local-family run manifest")
        if family_manifest.get("status") != "success":
            raise CandidateContractError("local-family input is not successful")
        contract, generation, cache_key, generation_sha = _cache_generation(
            family_run, cache_root.resolve(),
        )
        region = str(contract.get("region", ""))
        if region not in REGION_LIMITS or region in seen:
            raise CandidateContractError("local-family regions are missing or duplicated")
        seen.add(region)
        lower, upper = REGION_LIMITS[region]
        count = int(round((upper - lower) / step))
        values = [lower + index * step for index in range(count + 1)]
        # The workbench uses lower-inclusive, upper-exclusive intervals except
        # for the final positive mirror.  Avoid duplicate seam ownership.
        if region != "mirror_turn_positive":
            values = values[:-1]
        sample_path = output_directory / f"samples_{region}.csv"
        with sample_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("name", "x_mm", "y_mm", "z_mm"))
            for index, z_mm in enumerate(values):
                writer.writerow((f"n{index}", "0", f"{probe_y_mm:.17g}", f"{z_mm:.17g}"))
        recipes = contract.get("response_recipes")
        if not isinstance(recipes, list):
            raise CandidateContractError("local-family response recipes are missing")
        responses = []
        for group in GROUPS:
            matches = [item for item in recipes if isinstance(item, Mapping) and item.get("group") == group]
            if len(matches) != 1:
                raise CandidateContractError(f"local-family response is not unique: {group}")
            filename = str(matches[0].get("standalone_response_filename", ""))
            source = generation / filename
            if source.suffix.lower() != ".pa" or not source.is_file():
                raise CandidateContractError(f"standalone response is missing: {source}")
            responses.append({
                "group": group,
                "source_pa": str(source),
                "comparison_csv": str(output_directory / f"response_{region}_{group}.csv"),
            })
        regions.append({
            "region": region,
            "origin_project_mm": contract["patch_origin_project_mm"],
            "sample_csv": str(sample_path),
            "sample_count": len(values),
            "cache_key": cache_key,
            "generation_sha256": generation_sha,
            "responses": responses,
        })
    if seen != set(REGION_LIMITS):
        raise CandidateContractError("five-region response plan is incomplete")
    regions.sort(key=lambda item: REGION_LIMITS[item["region"]][0])
    plan = {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_axis_response_sampling_plan",
        "status": "prepared",
        "qualification": "0p5mm_axis_surrogate__native_flight_validation_required",
        "probe_x_mm": 0.0,
        "probe_y_mm": float(probe_y_mm),
        "sample_step_mm": step,
        "basis_normalization_v": normalization,
        "energy_centers_ev": energies,
        "period_slope_derivative_step_ev": derivative_step,
        "maximum_abs_normalized_period_slope_per_v": float(
            l0["maximum_abs_normalized_period_slope_per_v"]
        ),
        "base_mirror_voltages_v": base_voltages,
        "numerical_profile": numerical_profile,
        "source_contract_sha256": file_sha256(contract_path),
        "voltage_bounds_v": {
            "mirror_B": [-10000.0, energies[0]],
            "mirror_C": [-5000.0, energies[0]],
            "mirror_D": [-5000.0, energies[0]],
            "mirror_E": [energies[-1] + 1e-6, 10000.0],
        },
        "source_exact_k_run_id": loaded["manifest"]["run_id"],
        "regions": regions,
    }
    (output_directory / "mirror_response_sampling_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8",
    )
    return plan


@dataclass(frozen=True)
class AxisResponseBasis:
    z_mm: np.ndarray
    response_v: np.ndarray
    normalization_v: float

    def potential(self, voltages_v: Sequence[float]) -> CubicSpline:
        values = np.asarray(tuple(float(value) for value in voltages_v), dtype=float)
        if values.shape != (4,) or not np.all(np.isfinite(values)):
            raise CandidateContractError("real-field mirror model needs finite B--E voltages")
        samples = self.response_v @ (values / self.normalization_v)
        interpolator = CubicSpline(self.z_mm, samples, extrapolate=False)
        zero = float(interpolator(0.0))
        return CubicSpline(self.z_mm, samples - zero, extrapolate=False)


def _first_turn(interpolator: CubicSpline, energy: float, direction: int, z_limit: float) -> float:
    grid = np.linspace(0.0, z_limit, 2049) if direction > 0 else np.linspace(0.0, z_limit, 2049)
    values = np.asarray(interpolator(grid), dtype=float) - energy
    for index in range(len(grid) - 1):
        if values[index] <= 0.0 <= values[index + 1]:
            return float(brentq(lambda z: float(interpolator(z)) - energy, grid[index], grid[index + 1]))
    raise CandidateContractError("real-field voltage trial has no retained first mirror turn")


def reduced_period_from_basis(
    basis: AxisResponseBasis, energy_ev: float, voltages_v: Sequence[float],
) -> tuple[float, tuple[float, float]]:
    energy = float(energy_ev)
    if not math.isfinite(energy) or energy <= 0.0:
        raise CandidateContractError("real-field mirror energy must be positive")
    potential = basis.potential(voltages_v)
    left = _first_turn(potential, energy, -1, float(basis.z_mm[0]))
    right = _first_turn(potential, energy, 1, float(basis.z_mm[-1]))

    def side(turn: float) -> float:
        length = abs(turn)
        sign = 1.0 if turn > 0.0 else -1.0
        derivative = abs(float(potential.derivative()(turn)))
        if derivative <= 0.0:
            raise CandidateContractError("real-field mirror turn is not a simple crossing")

        def integrand(t: float) -> float:
            if t <= 1e-10:
                return 2.0 * math.sqrt(length / derivative)
            z = turn - sign * length * t * t
            kinetic = energy - float(potential(z))
            return 2.0 * length * t / math.sqrt(max(kinetic, 1e-14))

        try:
            return float(quad(integrand, 0.0, 1.0, epsabs=1e-7, epsrel=1e-8, limit=200)[0])
        except IntegrationWarning as exc:
            raise CandidateContractError("real-field period quadrature did not converge") from exc

    return side(left) + side(right), (left, right)


def normalized_slopes(
    basis: AxisResponseBasis,
    voltages_v: Sequence[float],
    energies_ev: Sequence[float],
    derivative_step_ev: float,
) -> tuple[float, float, float]:
    if len(energies_ev) != 3:
        raise CandidateContractError("real-field mirror solve needs three energy nodes")
    slopes = []
    for energy in energies_ev:
        low = reduced_period_from_basis(basis, energy - derivative_step_ev, voltages_v)[0]
        mid = reduced_period_from_basis(basis, energy, voltages_v)[0]
        high = reduced_period_from_basis(basis, energy + derivative_step_ev, voltages_v)[0]
        slopes.append((high - low) / (2.0 * derivative_step_ev * mid))
    return tuple(slopes)  # type: ignore[return-value]


def solve_l0_family(
    basis: AxisResponseBasis,
    energies_ev: Sequence[float],
    derivative_step_ev: float,
    base_voltages_v: Sequence[float],
    voltage_bounds_v: Mapping[str, Sequence[float]],
    maximum_abs_normalized_period_slope_per_v: float,
    numerical_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Solve B--D on deterministic E slices, preserving the L0 nullity."""
    slope_tolerance = float(maximum_abs_normalized_period_slope_per_v)
    if not math.isfinite(slope_tolerance) or slope_tolerance <= 0.0:
        raise CandidateContractError("real-field mirror slope tolerance must be positive")
    lower = np.array([float(voltage_bounds_v[group][0]) for group in GROUPS])
    upper = np.array([float(voltage_bounds_v[group][1]) for group in GROUPS])
    base = np.clip(np.asarray(tuple(base_voltages_v), dtype=float), lower, upper)
    e_slice_count = int(numerical_profile["e_voltage_slice_count"])
    jacobian_relative_step = float(numerical_profile["voltage_jacobian_relative_step"])
    maximum_evaluations = int(
        numerical_profile["maximum_function_evaluations_per_e_slice"]
    )
    if (
        base.shape != (4,)
        or e_slice_count < 3
        or jacobian_relative_step <= 0.0
        or maximum_evaluations < 1
        or numerical_profile.get("voltage_jacobian_scheme") != "three_point_central"
    ):
        raise CandidateContractError("real-field family input dimensions are invalid")
    e_values = np.linspace(lower[3], upper[3], e_slice_count)
    e_values = np.unique(np.append(e_values, base[3]))
    base_slopes = normalized_slopes(
        basis, base, energies_ev, derivative_step_ev,
    )
    base_periods_and_turns = [
        reduced_period_from_basis(basis, energy, base) for energy in energies_ev
    ]

    def solve_slice(e_voltage: float, start: np.ndarray) -> tuple[dict[str, Any], np.ndarray]:
        def residual(values: np.ndarray) -> np.ndarray:
            try:
                return 1e7 * np.asarray(normalized_slopes(
                    basis, (*values, float(e_voltage)), energies_ev, derivative_step_ev,
                ))
            except CandidateContractError:
                return np.full(3, 1e6)

        solution = least_squares(
            residual, start, bounds=(lower[:3], upper[:3]),
            x_scale=np.maximum(upper[:3] - lower[:3], 1.0),
            jac="3-point",
            diff_step=jacobian_relative_step,
            max_nfev=maximum_evaluations,
        )
        voltages = [*map(float, solution.x), float(e_voltage)]
        try:
            slopes = normalized_slopes(basis, voltages, energies_ev, derivative_step_ev)
            periods_and_turns = [reduced_period_from_basis(basis, energy, voltages) for energy in energies_ev]
            feasible = bool(solution.success and max(abs(value) for value in slopes) <= slope_tolerance)
        except CandidateContractError:
            slopes = (None, None, None)
            periods_and_turns = []
            feasible = False
        member = {
            "mirror_voltages_v": [0.0, *voltages],
            "normalized_period_slopes_per_v": list(slopes),
            "reduced_periods_mm_per_sqrt_v": [item[0] for item in periods_and_turns],
            "turning_points_mm": [list(item[1]) for item in periods_and_turns],
            "optimizer_success": bool(solution.success),
            "optimizer_message": str(solution.message),
            "function_evaluations": int(solution.nfev),
            "l0_feasible": feasible,
        }
        next_start = solution.x if solution.success and np.all(np.isfinite(solution.x)) else start
        return member, np.asarray(next_start, dtype=float)

    members = []
    base_member, center_start = solve_slice(float(base[3]), base[:3])
    members.append(base_member)
    below = sorted((value for value in e_values if value < base[3]), reverse=True)
    above = sorted(value for value in e_values if value > base[3])
    for direction in (below, above):
        start = center_start.copy()
        for e_voltage in direction:
            member, start = solve_slice(float(e_voltage), start)
            members.append(member)
    members.sort(key=lambda item: item["mirror_voltages_v"][-1])
    feasible_members = [item for item in members if item["l0_feasible"]]
    return {
        "schema_version": 1,
        "role": "mrtof_real_3d_mirror_l0_voltage_family",
        "status": "l0_family_found__l1_and_native_flight_pending" if feasible_members else "no_l0_family_member_found",
        "qualification": "sampled_0p5mm_axis_surrogate__not_a_simion_operating_point",
        "energy_centers_ev": list(map(float, energies_ev)),
        "period_slope_derivative_step_ev": float(derivative_step_ev),
        "maximum_abs_normalized_period_slope_per_v": slope_tolerance,
        "voltage_bounds_v": {key: list(map(float, value)) for key, value in voltage_bounds_v.items()},
        "family_nullity": 1,
        "numerics": {
            "voltage_jacobian_scheme": "three_point_central",
            "voltage_jacobian_relative_step": jacobian_relative_step,
            "maximum_function_evaluations_per_e_slice": maximum_evaluations,
            "requested_e_slice_count": int(e_slice_count),
            "continuation": "independent_lower_and_upper_e_sweeps_from_optimized_base_slice",
        },
        "base_point": {
            "mirror_voltages_v": [0.0, *map(float, base)],
            "normalized_period_slopes_per_v": list(base_slopes),
            "reduced_periods_mm_per_sqrt_v": [item[0] for item in base_periods_and_turns],
            "turning_points_mm": [list(item[1]) for item in base_periods_and_turns],
        },
        "member_count": len(members),
        "feasible_member_count": len(feasible_members),
        "members": members,
        "limitations": [
            "The axial surrogate does not evaluate gamma, transverse stability, Tbar_xx, or peak field.",
            "Every selected member requires native SIMION period and transverse-map validation.",
        ],
    }


def analyze_sampled_responses(
    plan_path: Path,
    output_path: Path,
    native_period_run: Path | None = None,
) -> dict[str, Any]:
    plan = _object(plan_path, "response sampling plan")
    rows: list[tuple[float, list[float]]] = []
    for region in plan["regions"]:
        columns: dict[str, dict[float, float]] = {}
        for response in region["responses"]:
            values: dict[float, float] = {}
            with Path(response["comparison_csv"]).open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    values[float(row["z_mm"])] = float(row["potential_a_V"])
            columns[response["group"]] = values
        z_values = sorted(columns[GROUPS[0]])
        if any(sorted(columns[group]) != z_values for group in GROUPS):
            raise CandidateContractError("sampled response coordinates differ")
        rows.extend((z, [columns[group][z] for group in GROUPS]) for z in z_values)
    rows.sort(key=lambda item: item[0])
    z = np.asarray([item[0] for item in rows], dtype=float)
    response = np.asarray([item[1] for item in rows], dtype=float)
    if len(np.unique(z)) != len(z) or not np.all(np.diff(z) > 0.0):
        raise CandidateContractError("sampled response axis is not strictly ordered")
    basis = AxisResponseBasis(z, response, float(plan["basis_normalization_v"]))
    basis_path = output_path.with_name("real_3d_mirror_axis_response_basis.csv")
    with basis_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("z_mm", *GROUPS))
        for coordinate, values in rows:
            writer.writerow((f"{coordinate:.17g}", *(f"{value:.17g}" for value in values)))
    report = solve_l0_family(
        basis,
        plan["energy_centers_ev"],
        float(plan["period_slope_derivative_step_ev"]),
        plan["base_mirror_voltages_v"][1:],
        plan["voltage_bounds_v"],
        float(plan["maximum_abs_normalized_period_slope_per_v"]),
        plan["numerical_profile"],
    )
    report["probe_y_mm"] = float(plan["probe_y_mm"])
    report["sample_step_mm"] = float(plan["sample_step_mm"])
    report["source_exact_k_run_id"] = plan["source_exact_k_run_id"]
    report["basis_cache_generations"] = [
        {"region": item["region"], "cache_key": item["cache_key"], "generation_sha256": item["generation_sha256"]}
        for item in plan["regions"]
    ]
    report["axis_response_basis_filename"] = basis_path.name
    if native_period_run is not None:
        native_root = native_period_run.resolve()
        native_manifest = _object(native_root / "run_manifest.json", "native period manifest")
        native = _object(
            native_root / "results" / "mirror_real_field_period_comparison.json",
            "native period comparison",
        )
        if (
            native_manifest.get("status") != "success"
            or native.get("energy_centers_ev") != plan["energy_centers_ev"]
            or not math.isclose(float(native.get("probe_y_mm")), float(plan["probe_y_mm"]), abs_tol=1e-12)
            or native.get("particles") is None
        ):
            raise CandidateContractError("native period comparison differs from the sampled basis contract")
        native_voltages = _object(
            native_root / "results" / "mirror_period_probe_contract.json",
            "native period probe contract",
        ).get("mirror_voltages_v")
        if native_voltages != plan["base_mirror_voltages_v"]:
            raise CandidateContractError("native period voltages differ from the sampled basis baseline")
        surrogate = report["base_point"]["normalized_period_slopes_per_v"]
        native_slopes = [float(value) for value in native["simion_normalized_period_slopes_per_v"]]
        difference = [float(left) - right for left, right in zip(surrogate, native_slopes, strict=True)]
        report["native_period_cross_check"] = {
            "run_id": native_manifest["run_id"],
            "native_simion_normalized_period_slopes_per_v": native_slopes,
            "axis_surrogate_normalized_period_slopes_per_v": surrogate,
            "difference_per_v": difference,
            "maximum_abs_difference_per_v": max(abs(value) for value in difference),
            "acceptance_threshold_assigned": False,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def analyze_preserved_basis(
    basis_run: Path,
    exact_k_run: Path,
    contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Re-solve an immutable sampled response basis without reopening SIMION PAs."""
    root = basis_run.resolve()
    manifest = _object(root / "run_manifest.json", "response-basis run manifest")
    if (
        manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "real_3d_mirror_l0_voltage_family"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("response basis must come from one successful managed run")

    def manifest_output(name: str) -> Path:
        path = (root / "results" / name).resolve()
        matches = [
            item for item in manifest.get("outputs", [])
            if isinstance(item, Mapping) and Path(str(item.get("path", ""))).resolve() == path
        ]
        if len(matches) != 1 or not path.is_file():
            raise CandidateContractError(f"response-basis output is not uniquely manifest-bound: {name}")
        if str(matches[0].get("sha256", "")).upper() != file_sha256(path):
            raise CandidateContractError(f"response-basis output hash differs: {name}")
        return path

    basis_path = manifest_output("real_3d_mirror_axis_response_basis.csv")
    receipt = _object(
        manifest_output("mirror_response_sampling_receipt.json"), "response sampling receipt",
    )
    numerical_profile = load_numerical_profile(contract_path)
    if (
        receipt.get("role") != "mrtof_real_3d_mirror_axis_response_sampling_plan"
        or receipt.get("status") != "sampled"
        or float(receipt.get("sample_step_mm"))
        != float(numerical_profile["response_grid_spacing_mm"])
    ):
        raise CandidateContractError(
            "response basis grid differs from the baseline numerical profile"
        )
    with basis_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    expected_columns = {"z_mm", *GROUPS}
    if not rows or set(rows[0]) != expected_columns:
        raise CandidateContractError("response basis columns differ from the B--E contract")
    z = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    response = np.asarray([[float(row[group]) for group in GROUPS] for row in rows], dtype=float)
    if not np.all(np.isfinite(z)) or not np.all(np.isfinite(response)) or not np.all(np.diff(z) > 0.0):
        raise CandidateContractError("response basis contains invalid or unordered samples")
    basis = AxisResponseBasis(z, response, float(receipt["basis_normalization_v"]))

    loaded = load_exact_k_point(exact_k_run)
    l0 = loaded["l0"]
    energies = [float(value) for value in l0["three_point"]["energies_v"]]
    base_voltages = [float(value) for value in loaded["point"]["mirror_voltages_v"]]
    bounds = {
        "mirror_B": [-10000.0, energies[0]],
        "mirror_C": [-5000.0, energies[0]],
        "mirror_D": [-5000.0, energies[0]],
        "mirror_E": [energies[-1] + 1e-6, 10000.0],
    }
    report = solve_l0_family(
        basis,
        energies,
        float(l0["period_slope_derivative_step_v"]),
        base_voltages[1:],
        bounds,
        float(l0["maximum_abs_normalized_period_slope_per_v"]),
        numerical_profile,
    )
    report.update({
        "probe_y_mm": float(receipt["probe_y_mm"]),
        "sample_step_mm": float(receipt["sample_step_mm"]),
        "source_exact_k_run_id": loaded["manifest"]["run_id"],
        "source_response_basis_run_id": manifest["run_id"],
        "source_response_basis_sha256": file_sha256(basis_path),
        "source_contract_sha256": file_sha256(contract_path),
        "basis_cache_generations": receipt["cache_generations"],
        "axis_response_basis_filename": basis_path.name,
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--local-workbench-run", type=Path, required=True)
    prepare.add_argument("--exact-k-run", type=Path, required=True)
    prepare.add_argument("--cache-root", type=Path, required=True)
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--output-directory", type=Path, required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--plan", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--native-period-run", type=Path)
    reuse = subparsers.add_parser("reuse")
    reuse.add_argument("--basis-run", type=Path, required=True)
    reuse.add_argument("--exact-k-run", type=Path, required=True)
    reuse.add_argument("--contract", type=Path, required=True)
    reuse.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare_sampling_plan(
            args.local_workbench_run, args.exact_k_run, args.cache_root,
            args.contract, args.output_directory,
        )
        print("MRTOF_REAL_FIELD_MIRROR_RESPONSE_PREPARE=PASS")
    elif args.action == "analyze":
        report = analyze_sampled_responses(args.plan, args.output, args.native_period_run)
        print(
            "MRTOF_REAL_FIELD_MIRROR_L0="
            f"{report['status']} FEASIBLE={report['feasible_member_count']}"
        )
    else:
        report = analyze_preserved_basis(
            args.basis_run, args.exact_k_run, args.contract, args.output,
        )
        print(
            "MRTOF_REAL_FIELD_MIRROR_L0_REUSE="
            f"{report['status']} FEASIBLE={report['feasible_member_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
