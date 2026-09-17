"""Managed preparation and analysis helpers for the sampled real-3-D mirror L1 screen.

The workflow reads the already refined five-region PA families.  It never
refines a PA and never changes the manufactured geometry.  Region ownership
comes from the frozen local-refinement plan; the outer z extent comes from the
retained L0 axis-response basis, so no analyser boundary is duplicated here.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    GROUPS,
    RealFieldL1Error,
    load_response_basis_csv,
    screen_feasible_family,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
    _cache_generation,
)


ROLE = "mrtof_real_3d_mirror_l1_response_sampling_plan"
REGION_ORDER = (
    "mirror_turn_negative",
    "stripe_mirror_bridge_negative",
    "central_transport",
    "stripe_mirror_bridge_positive",
    "mirror_turn_positive",
)
SHORT_GROUPS = ("B", "C", "D", "E")


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealFieldL1Error(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RealFieldL1Error(f"{label} must be an object")
    return value


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RealFieldL1Error(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise RealFieldL1Error(f"{label} must be finite")
    return number


def _axis_extent(path: Path, expected_step_mm: float) -> tuple[float, float]:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or "z_mm" not in reader.fieldnames:
                raise RealFieldL1Error("L0 axis basis lacks z_mm")
            values = sorted({_finite(row["z_mm"], "axis z_mm") for row in reader})
    except OSError as exc:
        raise RealFieldL1Error(f"L0 axis basis is unreadable: {path}") from exc
    if len(values) < 3:
        raise RealFieldL1Error("L0 axis basis has too few z nodes")
    if any(
        not math.isclose(right - left, expected_step_mm, abs_tol=1e-10)
        for left, right in zip(values, values[1:], strict=False)
    ):
        raise RealFieldL1Error("L0 axis basis z nodes do not use the declared response spacing")
    return values[0], values[-1]


def _responsibility_ranges(
    local_plan: Mapping[str, Any], outer_z: tuple[float, float], step_mm: float,
) -> dict[str, tuple[float, float]]:
    handoff = local_plan.get("handoff_planes_project_mm")
    if not isinstance(handoff, Mapping):
        raise RealFieldL1Error("local refinement plan lacks handoff planes")
    seams = (
        _finite(handoff.get("negative_bridge_to_mirror"), "negative mirror handoff"),
        _finite(handoff.get("negative_central_to_bridge"), "negative central handoff"),
        _finite(handoff.get("positive_central_to_bridge"), "positive central handoff"),
        _finite(handoff.get("positive_bridge_to_mirror"), "positive mirror handoff"),
    )
    boundaries = (outer_z[0], *seams, outer_z[1] + step_mm)
    if any(not left < right for left, right in zip(boundaries, boundaries[1:], strict=False)):
        raise RealFieldL1Error("local responsibility boundaries are not strictly ordered")
    ranges = {}
    for index, region in enumerate(REGION_ORDER):
        lower = boundaries[index]
        upper = boundaries[index + 1] - step_mm
        count = (upper - lower) / step_mm
        if upper < lower or not math.isclose(count, round(count), abs_tol=1e-10):
            raise RealFieldL1Error(f"region responsibility is not native-node aligned: {region}")
        ranges[region] = (lower, upper)
    return ranges


def prepare_plan(
    *, local_workbench_run: Path, l0_response_basis_run: Path, cache_root: Path,
    contract_path: Path, output_path: Path,
) -> dict[str, Any]:
    workbench = local_workbench_run.resolve()
    basis_run = l0_response_basis_run.resolve()
    config = _object(workbench / "run_config.json", "local workbench config")
    manifest = _object(workbench / "run_manifest.json", "local workbench manifest")
    basis_manifest = _object(basis_run / "run_manifest.json", "L0 response-basis manifest")
    basis_receipt = _object(
        basis_run / "results" / "mirror_response_sampling_receipt.json",
        "L0 response-basis receipt",
    )
    contract = _object(contract_path, "MR-TOF contract")
    if (
        config.get("mode") != "analyzer_local_replacement_workbench"
        or manifest.get("status") != "success"
        or basis_manifest.get("status") != "success"
        or basis_receipt.get("status") != "sampled"
    ):
        raise RealFieldL1Error("L1 preparation requires successful workbench and L0 basis runs")
    try:
        l0_profile = contract["mirror"]["theory_requirements"]["real_3d_l0_voltage_family_profile"]
        l1_profile = contract["mirror"]["theory_requirements"]["real_3d_l1_screen_profile"]
        beam_width = _finite(contract["mirror"]["beam_slot_width_mm"], "mirror beam-slot width")
    except (KeyError, TypeError) as exc:
        raise RealFieldL1Error("contract lacks the real-3-D L1 geometry sources") from exc
    step = _finite(l0_profile["response_grid_spacing_mm"], "response grid spacing")
    probe_y = _finite(l0_profile["axis_probe_y_mm"], "response slice y")
    if step <= 0.0 or beam_width <= 0.0:
        raise RealFieldL1Error("response spacing and beam-slot width must be positive")
    if (
        _finite(basis_receipt.get("sample_step_mm"), "basis sample step") != step
        or _finite(basis_receipt.get("probe_y_mm"), "basis probe y") != probe_y
    ):
        raise RealFieldL1Error("L0 basis and active L1 source contract differ")
    axis_path = basis_run / "results" / "real_3d_mirror_axis_response_basis.csv"
    outer_z = _axis_extent(axis_path, step)
    plan_path_value = config.get("inputs", {}).get("current_local_refinement_plan")
    if not isinstance(plan_path_value, str):
        raise RealFieldL1Error("workbench does not bind its current local-refinement plan")
    local_plan_path = Path(plan_path_value)
    local_plan = _object(local_plan_path, "current local-refinement plan")
    ranges = _responsibility_ranges(local_plan, outer_z, step)
    family_manifests = config.get("inputs", {}).get("local_family_manifests")
    if not isinstance(family_manifests, list) or len(family_manifests) != len(REGION_ORDER):
        raise RealFieldL1Error("workbench must bind exactly five local PA families")
    normalization = _finite(config.get("parameters", {}).get("basis_voltage_v"), "basis voltage")
    if normalization <= 0.0 or normalization != _finite(
        basis_receipt.get("basis_normalization_v"), "L0 basis normalization",
    ):
        raise RealFieldL1Error("workbench and L0 basis normalizations differ")
    by_region: dict[str, dict[str, Any]] = {}
    for manifest_value in family_manifests:
        family_run = Path(str(manifest_value)).resolve().parent
        family_contract, generation, cache_key, generation_sha = _cache_generation(
            family_run, cache_root.resolve(),
        )
        region = str(family_contract.get("region", ""))
        if region not in REGION_ORDER or region in by_region:
            raise RealFieldL1Error("local PA-family regions are unknown or duplicated")
        recipes = family_contract.get("response_recipes")
        if not isinstance(recipes, list):
            raise RealFieldL1Error(f"local family has no response recipes: {region}")
        responses = []
        for full_group, short_group in zip(GROUPS, SHORT_GROUPS, strict=True):
            matches = [
                item for item in recipes
                if isinstance(item, Mapping) and item.get("group") == full_group
            ]
            if len(matches) != 1:
                raise RealFieldL1Error(f"local response is not unique: {region}/{full_group}")
            source = generation / str(matches[0].get("standalone_response_filename", ""))
            if source.suffix.lower() != ".pa" or not source.is_file():
                raise RealFieldL1Error(f"local response PA is missing: {source}")
            responses.append({
                "group": short_group,
                "full_group": full_group,
                "source_pa": str(source),
                "source_pa_bytes": source.stat().st_size,
            })
        origin = family_contract.get("patch_origin_project_mm")
        if not isinstance(origin, list) or len(origin) != 3:
            raise RealFieldL1Error(f"local family origin is invalid: {region}")
        by_region[region] = {
            "region_id": region,
            "region_origin_project_mm": [_finite(value, f"{region} origin") for value in origin],
            "x_range_mm": [-beam_width / 2.0, beam_width / 2.0],
            "z_range_mm": list(ranges[region]),
            "cache_key": cache_key,
            "generation_sha256": generation_sha,
            "responses": responses,
        }
    if set(by_region) != set(REGION_ORDER):
        raise RealFieldL1Error("five-region response inventory is incomplete")
    plan = {
        "schema_version": 1,
        "role": ROLE,
        "status": "prepared",
        "qualification": "read_only_sampled_0p5mm_response_screen__native_validation_required",
        "project_frame": "project_xyz__x_transverse_y_drift_z_fast_reflection",
        "slice_y_mm": probe_y,
        "sample_step_mm": step,
        "basis_normalization_v": normalization,
        "x_range_mm": [-beam_width / 2.0, beam_width / 2.0],
        "z_range_mm": list(outer_z),
        "region_order": list(REGION_ORDER),
        "regions": [by_region[region] for region in REGION_ORDER],
        "sources": {
            "local_workbench_run_id": manifest.get("run_id"),
            "local_workbench_manifest_sha256": file_sha256(workbench / "run_manifest.json"),
            "l0_response_basis_run_id": basis_manifest.get("run_id"),
            "l0_response_basis_manifest_sha256": file_sha256(basis_run / "run_manifest.json"),
            "l0_axis_basis_sha256": file_sha256(axis_path),
            "local_refinement_plan_sha256": file_sha256(local_plan_path),
            "contract_sha256": file_sha256(contract_path),
        },
        "contract_profile": l1_profile,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan


def _lua_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_sampler_spec(
    *, plan_path: Path, region_id: str, response_paths: Sequence[Path], output_path: Path,
) -> None:
    plan = _object(plan_path, "L1 sampling plan")
    if plan.get("role") != ROLE or plan.get("status") != "prepared":
        raise RealFieldL1Error("sampler spec requires a prepared L1 plan")
    matches = [item for item in plan["regions"] if item.get("region_id") == region_id]
    if len(matches) != 1 or len(response_paths) != 4:
        raise RealFieldL1Error("sampler spec region or response paths are invalid")
    region = matches[0]
    normalization = _finite(plan["basis_normalization_v"], "basis normalization")
    origin = ", ".join(f"{float(value):.17g}" for value in region["region_origin_project_mm"])
    responses = ",\n".join(
        "    {group=%s, standalone_pa_path=%s, normalization_v=%.17g}"
        % (_lua_string(group), _lua_string(str(path.resolve())), normalization)
        for group, path in zip(SHORT_GROUPS, response_paths, strict=True)
    )
    text = (
        "return {\n"
        "  schema_version=1,\n"
        "  role=\"mrtof_real_3d_mirror_l1_response_slice\",\n"
        f"  project_frame={_lua_string(str(plan['project_frame']))},\n"
        f"  region_id={_lua_string(region_id)},\n"
        f"  region_origin_project_mm={{x={origin.split(', ')[0]}, y={origin.split(', ')[1]}, z={origin.split(', ')[2]}}},\n"
        f"  slice_y_mm={float(plan['slice_y_mm']):.17g},\n"
        f"  x_range_mm={{min_mm={float(region['x_range_mm'][0]):.17g}, max_mm={float(region['x_range_mm'][1]):.17g}}},\n"
        f"  z_range_mm={{min_mm={float(region['z_range_mm'][0]):.17g}, max_mm={float(region['z_range_mm'][1]):.17g}}},\n"
        "  responses={\n" + responses + "\n  },\n}\n"
    )
    output_path.write_text(text, encoding="utf-8")


def merge_region_csvs(*, plan_path: Path, region_csvs: Sequence[Path], output_path: Path) -> None:
    plan = _object(plan_path, "L1 sampling plan")
    if plan.get("role") != ROLE or len(region_csvs) != len(REGION_ORDER):
        raise RealFieldL1Error("merge requires one canonical CSV per responsibility region")
    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    for expected_region, path in zip(REGION_ORDER, region_csvs, strict=True):
        region = next(item for item in plan["regions"] if item["region_id"] == expected_region)
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise RealFieldL1Error(f"region CSV has no header: {path}")
            if fieldnames is None:
                fieldnames = reader.fieldnames
            elif reader.fieldnames != fieldnames:
                raise RealFieldL1Error("regional response CSV schemas differ")
            local = list(reader)
        if not local:
            raise RealFieldL1Error(f"region CSV is empty: {expected_region}")
        z_values = sorted({_finite(row["z_mm"], "regional z") for row in local})
        if not (
            math.isclose(z_values[0], float(region["z_range_mm"][0]), abs_tol=1e-10)
            and math.isclose(z_values[-1], float(region["z_range_mm"][1]), abs_tol=1e-10)
        ):
            raise RealFieldL1Error(f"regional CSV does not cover its responsibility: {expected_region}")
        rows.extend(local)
    assert fieldnames is not None
    rows.sort(key=lambda row: (_finite(row["z_mm"], "z_mm"), _finite(row["x_mm"], "x_mm")))
    seen: set[tuple[float, float]] = set()
    for row in rows:
        key = (_finite(row["x_mm"], "x_mm"), _finite(row["z_mm"], "z_mm"))
        if key in seen:
            raise RealFieldL1Error(f"regional ownership overlaps at {key}")
        seen.add(key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    # The canonical loader proves that all x-z Cartesian nodes exist exactly once.
    load_response_basis_csv(
        output_path,
        normalization_v=float(plan["basis_normalization_v"]),
        probe_y_mm=float(plan["slice_y_mm"]),
    )


def analyze_screen(
    *, plan_path: Path, basis_path: Path, family_path: Path, contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    plan = _object(plan_path, "L1 sampling plan")
    family = _object(family_path, "real-3-D L0 family")
    contract = _object(contract_path, "MR-TOF contract")
    basis = load_response_basis_csv(
        basis_path,
        normalization_v=float(plan["basis_normalization_v"]),
        probe_y_mm=float(plan["slice_y_mm"]),
    )
    try:
        requirements = contract["mirror"]["theory_requirements"]
        l0 = requirements["l0_acceptance_budget"]
        l1 = requirements["l1_screen_profile"]
        real = requirements["real_3d_l1_screen_profile"]
        trajectory = contract["simion"]["trajectory_profiles"][real["screen_trajectory_profile_id"]]
        species = contract["particle_source"]["species"]
    except (KeyError, TypeError) as exc:
        raise RealFieldL1Error("contract lacks an L1 numerical source") from exc
    if (
        real.get("axis_period_authority_source")
        != "mirror.theory_requirements.real_3d_l0_voltage_family_profile.axis_period_authority"
        or family.get("axis_period_authority") != "integrated_piecewise_linear_sampled_Ez"
        or int(family.get("axis_basis_schema_version", 0)) != 2
    ):
        raise RealFieldL1Error("L1 screening requires the field-consistent L0 family")
    energy_points = tuple(float(value) for value in family["energy_centers_ev"])
    half_window = (energy_points[-1] - energy_points[0]) / 2.0
    slope_gate = float(l0["mirror_time_width_fraction"]) / (
        2.0 * float(l0["minimum_mass_resolution"]) * half_window
    )
    tolerances = real["ranking_metric_tolerances"]
    result = screen_feasible_family(
        family,
        basis,
        evaluation_arguments={
            "energy_points_v": energy_points,
            "period_slope_derivative_step_v": float(family["period_slope_derivative_step_ev"]),
            "probe_scale_factors": tuple(float(value) for value in l1["probe_convergence_scale_factors"]),
            "position_probe_mm": float(l1["position_probe_mm"]),
            "angle_probe_rad": float(l1["angle_probe_rad"]),
            "trace_controls": {
                "particle_mass_th": float(species["mass_th"]),
                "particle_charge_e": float(species["charge_e"]),
                "relative_tolerance": float(real["surrogate_relative_tolerance"]),
                "absolute_tolerance": float(real["surrogate_absolute_tolerance"]),
                "maximum_step_us": float(trajectory["maximum_step_us"]),
                "maximum_leg_time_us": float(real["maximum_leg_time_us"]),
                "central_plane_offset_mm": float(real["central_plane_offset_mm"]),
            },
            "target_gamma_degrees": float(l1["target_gamma_degrees"]),
            "maximum_gamma_target_residual_degrees": float(l1["maximum_gamma_target_residual_degrees"]),
            "maximum_adjacent_gamma_change_degrees": float(l1["maximum_adjacent_gamma_change_degrees"]),
            "maximum_adjacent_relative_tbar_change": float(l1["maximum_adjacent_relative_Tbar_change"]),
            "tbar_relative_change_absolute_floor_us_per_mm2": float(
                real["tbar_relative_change_absolute_floor_us_per_mm2"]
            ),
            "minimum_stability_margin": float(real["minimum_stability_margin"]),
            "maximum_abs_normalized_period_slope_per_v": slope_gate,
        },
        ranking_metric_tolerances=(
            float(tolerances["absolute_Tbar_xx_us_per_mm2"]),
            float(tolerances["minimum_stability_margin"]),
            float(tolerances["sampled_peak_field_v_per_mm"]),
            float(tolerances["maximum_absolute_mirror_voltage_v"]),
        ),
        maximum_parallel_workers=int(l1["maximum_parallel_workers"]),
    )
    result["inputs"] = {
        "sampling_plan_sha256": file_sha256(plan_path),
        "response_basis_sha256": file_sha256(basis_path),
        "l0_family_sha256": file_sha256(family_path),
        "contract_sha256": file_sha256(contract_path),
    }
    result["derived_maximum_abs_normalized_period_slope_per_v"] = slope_gate
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--local-workbench-run", type=Path, required=True)
    prepare.add_argument("--l0-response-basis-run", type=Path, required=True)
    prepare.add_argument("--cache-root", type=Path, required=True)
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    spec = commands.add_parser("spec")
    spec.add_argument("--plan", type=Path, required=True)
    spec.add_argument("--region", required=True)
    spec.add_argument("--response-pa", type=Path, action="append", required=True)
    spec.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--plan", type=Path, required=True)
    merge.add_argument("--region-csv", type=Path, action="append", required=True)
    merge.add_argument("--output", type=Path, required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--plan", type=Path, required=True)
    analyze.add_argument("--basis", type=Path, required=True)
    analyze.add_argument("--family", type=Path, required=True)
    analyze.add_argument("--contract", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "prepare":
        prepare_plan(
            local_workbench_run=arguments.local_workbench_run,
            l0_response_basis_run=arguments.l0_response_basis_run,
            cache_root=arguments.cache_root,
            contract_path=arguments.contract,
            output_path=arguments.output,
        )
    elif arguments.command == "spec":
        write_sampler_spec(
            plan_path=arguments.plan, region_id=arguments.region,
            response_paths=arguments.response_pa, output_path=arguments.output,
        )
    elif arguments.command == "merge":
        merge_region_csvs(
            plan_path=arguments.plan, region_csvs=arguments.region_csv, output_path=arguments.output,
        )
    else:
        analyze_screen(
            plan_path=arguments.plan, basis_path=arguments.basis,
            family_path=arguments.family, contract_path=arguments.contract,
            output_path=arguments.output,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
