"""Load and analyze a five-region fixed-operating-PA field slice.

The canonical CSV is produced by ``sample_fixed_operating_field_slice.lua``.
This module adapts its already-combined potential and field to the existing
``CombinedField`` and ``l1_probe_at_energy`` numerical physics.  It does not
compose responses, choose voltages, or call SIMION.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    CombinedField,
    RealFieldL1Error,
    ResponseBasis,
    l1_probe_at_energy,
)


REGION_ORDER = (
    "mirror_turn_negative",
    "stripe_mirror_bridge_negative",
    "central_transport",
    "stripe_mirror_bridge_positive",
    "mirror_turn_positive",
)
CSV_COLUMNS = {
    "region_id",
    "source_mesh_x_mm",
    "source_mesh_y_mm",
    "source_mesh_z_mm",
    "x_mm",
    "z_mm",
    "is_electrode",
    "potential_v",
    "ex_v_per_mm",
    "ey_v_per_mm",
    "ez_v_per_mm",
}

_FIXED_L1_WORKER_FIELD: CombinedField | None = None
_FIXED_L1_WORKER_POSITION_PROBE_MM: float | None = None
_FIXED_L1_WORKER_ANGLE_PROBE_RAD: float | None = None
_FIXED_L1_WORKER_TRACE_CONTROLS: Mapping[str, Any] | None = None


def _initialize_fixed_l1_worker(
    field: CombinedField,
    position_probe_mm: float,
    angle_probe_rad: float,
    trace_controls: Mapping[str, Any],
) -> None:
    global _FIXED_L1_WORKER_FIELD
    global _FIXED_L1_WORKER_POSITION_PROBE_MM, _FIXED_L1_WORKER_ANGLE_PROBE_RAD
    global _FIXED_L1_WORKER_TRACE_CONTROLS
    _FIXED_L1_WORKER_FIELD = field
    _FIXED_L1_WORKER_POSITION_PROBE_MM = position_probe_mm
    _FIXED_L1_WORKER_ANGLE_PROBE_RAD = angle_probe_rad
    _FIXED_L1_WORKER_TRACE_CONTROLS = trace_controls


def _fixed_l1_probe_job(
    job: tuple[int, float, int, float],
) -> tuple[int, float, int, dict[str, Any]]:
    direction, energy, scale_index, scale = job
    if (
        _FIXED_L1_WORKER_FIELD is None
        or _FIXED_L1_WORKER_POSITION_PROBE_MM is None
        or _FIXED_L1_WORKER_ANGLE_PROBE_RAD is None
        or _FIXED_L1_WORKER_TRACE_CONTROLS is None
    ):
        raise RealFieldL1Error("fixed L1 probe worker was not initialized")
    record = l1_probe_at_energy(
        _FIXED_L1_WORKER_FIELD,
        energy_per_charge_v=energy,
        launch_direction=direction,
        position_probe_mm=_FIXED_L1_WORKER_POSITION_PROBE_MM * scale,
        angle_probe_rad=_FIXED_L1_WORKER_ANGLE_PROBE_RAD * scale,
        trace_controls=_FIXED_L1_WORKER_TRACE_CONTROLS,
    )
    return direction, energy, scale_index, record


def _lua_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_sampler_spec(*, plan_path: Path, output_path: Path) -> None:
    """Validate a fixed-field sampling plan and render its SIMION Lua spec."""

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealFieldL1Error(f"fixed operating field plan is unreadable: {plan_path}") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise RealFieldL1Error("fixed operating field plan schema_version must be 1")
    if plan.get("role") != "mrtof_fixed_operating_field_slice":
        raise RealFieldL1Error("fixed operating field plan role is invalid")
    regions = plan.get("regions")
    if not isinstance(regions, list) or len(regions) != len(REGION_ORDER):
        raise RealFieldL1Error("fixed operating field plan requires five regions")
    rendered_regions = []
    for expected, region in zip(REGION_ORDER, regions, strict=True):
        if not isinstance(region, dict) or region.get("region_id") != expected:
            raise RealFieldL1Error("fixed operating field regions are not in canonical order")
        path = Path(str(region.get("standalone_pa_path", ""))).resolve()
        if path.suffix.lower() not in {".pa", ".pa0"} or not path.is_file():
            raise RealFieldL1Error(f"fixed operating standalone PA is missing: {path}")
        try:
            origin = tuple(float(value) for value in region["region_origin_project_mm"])
            mesh = tuple(float(value) for value in region["mesh_mm_per_gu"])
            z_range = tuple(float(value) for value in region["z_range_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RealFieldL1Error(f"fixed operating region geometry is invalid: {expected}") from exc
        if (
            len(origin) != 3
            or len(mesh) != 3
            or len(z_range) != 2
            or not all(math.isfinite(value) for value in origin + mesh + z_range)
            or any(value <= 0.0 for value in mesh)
            or z_range[0] > z_range[1]
        ):
            raise RealFieldL1Error(f"fixed operating region geometry is invalid: {expected}")
        rendered_regions.append(
            "    {region_id=%s, standalone_pa_path=%s, "
            "region_origin_project_mm={x=%.17g,y=%.17g,z=%.17g}, "
            "mesh_mm_per_gu={x=%.17g,y=%.17g,z=%.17g}, "
            "z_range_mm={min_mm=%.17g,max_mm=%.17g}}"
            % ((_lua_string(expected), _lua_string(str(path))) + origin + mesh + z_range)
        )
    try:
        x_range = tuple(float(value) for value in plan["x_range_mm"])
        slice_y = float(plan["slice_y_mm"])
        sample_step = float(plan["sample_step_mm"])
        project_frame = str(plan["project_frame"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RealFieldL1Error("fixed operating field global sampling geometry is invalid") from exc
    if (
        len(x_range) != 2
        or x_range[0] > x_range[1]
        or not all(math.isfinite(value) for value in x_range + (slice_y, sample_step))
        or sample_step <= 0.0
        or not project_frame
    ):
        raise RealFieldL1Error("fixed operating field global sampling geometry is invalid")
    text = (
        "return {\n"
        "  schema_version=1,\n"
        '  role="mrtof_fixed_operating_field_slice",\n'
        f"  project_frame={_lua_string(project_frame)},\n"
        f"  slice_y_mm={slice_y:.17g},\n"
        f"  sample_step_mm={sample_step:.17g},\n"
        f"  x_range_mm={{min_mm={x_range[0]:.17g},max_mm={x_range[1]:.17g}}},\n"
        "  regions={\n" + ",\n".join(rendered_regions) + "\n  },\n}\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class OperatingFieldSlice:
    """One stitched fixed operating field and its per-region source mesh."""

    basis: ResponseBasis
    mesh_by_region_mm_per_gu: Mapping[str, tuple[float, float, float]]
    z_range_by_region_mm: Mapping[str, tuple[float, float]]

    def combined_field(self) -> CombinedField:
        """Return the existing field interpolator over the fixed field."""

        return CombinedField(self.basis, (1.0, 0.0, 0.0, 0.0))


def _finite(text: Any, label: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise RealFieldL1Error(f"{label} is not numeric") from exc
    if not math.isfinite(value):
        raise RealFieldL1Error(f"{label} is non-finite")
    return value


def load_operating_field_csv(path: Path, *, probe_y_mm: float) -> OperatingFieldSlice:
    """Load a complete regular x-z slice with one geometry mask.

    Region ownership must be contiguous in canonical order.  Mesh metadata is
    constant inside a region and may differ between regions; this is how the
    0.25-mm mirror PAs and 0.5-mm bridge/central PAs remain explicit after
    stitching onto the common output grid.
    """

    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or set(reader.fieldnames) != CSV_COLUMNS:
                raise RealFieldL1Error("operating field CSV columns differ from the canonical schema")
            rows = list(reader)
    except OSError as exc:
        raise RealFieldL1Error(f"operating field CSV is unreadable: {path}") from exc
    if not rows:
        raise RealFieldL1Error("operating field CSV is empty")
    if not math.isfinite(float(probe_y_mm)):
        raise RealFieldL1Error("operating field probe y must be finite")

    parsed: dict[tuple[float, float], tuple[str, tuple[float, float, float], bool, list[float]]] = {}
    for row in rows:
        x_mm = _finite(row["x_mm"], "x_mm")
        z_mm = _finite(row["z_mm"], "z_mm")
        key = (x_mm, z_mm)
        if key in parsed:
            raise RealFieldL1Error(f"duplicate operating field grid point: {key}")
        region = row["region_id"]
        if region not in REGION_ORDER:
            raise RealFieldL1Error(f"unknown operating field region: {region}")
        mesh = tuple(_finite(row[f"source_mesh_{axis}_mm"], f"{region} mesh {axis}") for axis in "xyz")
        if any(value <= 0.0 for value in mesh):
            raise RealFieldL1Error(f"operating field region mesh must be positive: {region}")
        mask = row["is_electrode"].strip().lower()
        if mask not in {"0", "1", "false", "true"}:
            raise RealFieldL1Error("is_electrode must be 0/1 or false/true")
        values = [_finite(row["potential_v"], "potential_v")]
        values.extend(_finite(row[f"e{axis}_v_per_mm"], f"E{axis}") for axis in "xyz")
        parsed[key] = (region, mesh, mask in {"1", "true"}, values)

    x_values = np.asarray(sorted({key[0] for key in parsed}), dtype=float)
    z_values = np.asarray(sorted({key[1] for key in parsed}), dtype=float)
    if len(x_values) < 2 or len(z_values) < 3 or len(parsed) != len(x_values) * len(z_values):
        raise RealFieldL1Error("operating field CSV is not a complete nontrivial Cartesian grid")
    x_steps = np.diff(x_values)
    z_steps = np.diff(z_values)
    if not np.allclose(x_steps, x_steps[0], rtol=0.0, atol=1e-12) or not np.allclose(
        z_steps, z_steps[0], rtol=0.0, atol=1e-12
    ):
        raise RealFieldL1Error("operating field output axes must use one regular common grid")

    region_by_z: dict[float, str] = {}
    mesh_by_region: dict[str, tuple[float, float, float]] = {}
    z_by_region: dict[str, list[float]] = {region: [] for region in REGION_ORDER}
    for z_mm in z_values:
        records = [parsed[(float(x_mm), float(z_mm))] for x_mm in x_values]
        regions = {record[0] for record in records}
        meshes = {record[1] for record in records}
        if len(regions) != 1 or len(meshes) != 1:
            raise RealFieldL1Error("one z row must have one source region and source mesh")
        region = next(iter(regions))
        mesh = next(iter(meshes))
        if region in mesh_by_region and mesh_by_region[region] != mesh:
            raise RealFieldL1Error(f"source mesh changes inside operating field region: {region}")
        region_by_z[float(z_mm)] = region
        mesh_by_region[region] = mesh
        z_by_region[region].append(float(z_mm))
    active_regions = [region_by_z[float(z_mm)] for z_mm in z_values]
    collapsed = [active_regions[0]]
    for region in active_regions[1:]:
        if region != collapsed[-1]:
            collapsed.append(region)
    if tuple(collapsed) != REGION_ORDER or set(mesh_by_region) != set(REGION_ORDER):
        raise RealFieldL1Error("operating field regions are missing, repeated, or out of order")

    potential = np.zeros((len(x_values), len(z_values), 4), dtype=float)
    field = np.zeros((len(x_values), len(z_values), 4, 3), dtype=float)
    mask = np.empty((len(x_values), len(z_values)), dtype=bool)
    for ix, x_mm in enumerate(x_values):
        for iz, z_mm in enumerate(z_values):
            _region, _mesh, electrode, values = parsed[(float(x_mm), float(z_mm))]
            mask[ix, iz] = electrode
            potential[ix, iz, 0] = values[0]
            field[ix, iz, 0, :] = values[1:]
    basis = ResponseBasis(
        x_values,
        z_values,
        potential,
        field,
        mask,
        normalization_v=1.0,
        probe_y_mm=float(probe_y_mm),
    )
    return OperatingFieldSlice(
        basis=basis,
        mesh_by_region_mm_per_gu=mesh_by_region,
        z_range_by_region_mm={
            region: (min(z_by_region[region]), max(z_by_region[region])) for region in REGION_ORDER
        },
    )


def _relative_change(left: float, right: float, absolute_floor: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), absolute_floor)


def analyze_operating_field_l1(
    operating_slice: OperatingFieldSlice,
    *,
    energy_points_v: Sequence[float],
    probe_scale_factors: Sequence[float],
    position_probe_mm: float,
    angle_probe_rad: float,
    trace_controls: Mapping[str, float],
    target_gamma_degrees: float,
    maximum_gamma_target_residual_degrees: float,
    maximum_adjacent_gamma_change_degrees: float,
    maximum_adjacent_relative_tbar_change: float,
    tbar_relative_change_absolute_floor_us_per_mm2: float,
    minimum_stability_margin: float,
    maximum_parallel_workers: int = 1,
) -> dict[str, Any]:
    """Report gamma/Tbar and frozen adjacent-scale convergence gates."""

    energies = tuple(float(value) for value in energy_points_v)
    scales = tuple(float(value) for value in probe_scale_factors)
    controls = (
        position_probe_mm,
        angle_probe_rad,
        target_gamma_degrees,
        maximum_gamma_target_residual_degrees,
        maximum_adjacent_gamma_change_degrees,
        maximum_adjacent_relative_tbar_change,
        tbar_relative_change_absolute_floor_us_per_mm2,
        minimum_stability_margin,
    )
    if (
        len(energies) != 3
        or tuple(sorted(energies)) != energies
        or len(scales) < 2
        or tuple(sorted(scales)) != scales
        or any(not math.isfinite(value) or value <= 0.0 for value in energies + scales)
        or any(not math.isfinite(float(value)) or float(value) < 0.0 for value in controls)
        or position_probe_mm <= 0.0
        or angle_probe_rad <= 0.0
        or maximum_gamma_target_residual_degrees <= 0.0
        or maximum_adjacent_gamma_change_degrees <= 0.0
        or maximum_adjacent_relative_tbar_change <= 0.0
        or tbar_relative_change_absolute_floor_us_per_mm2 <= 0.0
        or not 0.0 < target_gamma_degrees < 180.0
        or isinstance(maximum_parallel_workers, bool)
        or not isinstance(maximum_parallel_workers, int)
        or maximum_parallel_workers < 1
    ):
        raise RealFieldL1Error("operating-field L1 energies, probes, or gates are invalid")

    field = operating_slice.combined_field()
    nominal_energy = energies[1]
    jobs = []
    for direction in (-1, 1):
        for energy in energies:
            active_scale_indices = range(len(scales)) if energy == nominal_energy else (len(scales) - 1,)
            jobs.extend(
                (direction, energy, scale_index, scales[scale_index])
                for scale_index in active_scale_indices
            )
    worker_count = min(len(jobs), maximum_parallel_workers, os.cpu_count() or 1)
    worker_arguments = (
        field, position_probe_mm, angle_probe_rad, dict(trace_controls),
    )
    if worker_count > 1:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_fixed_l1_worker,
            initargs=worker_arguments,
        ) as executor:
            evaluated_jobs = list(executor.map(_fixed_l1_probe_job, jobs))
    else:
        _initialize_fixed_l1_worker(*worker_arguments)
        evaluated_jobs = [_fixed_l1_probe_job(job) for job in jobs]
    evaluated = {
        (direction, energy, scale_index): record
        for direction, energy, scale_index, record in evaluated_jobs
    }
    if len(evaluated) != len(jobs):
        raise RealFieldL1Error("fixed L1 parallel probe jobs changed identity")

    directions: dict[str, Any] = {}
    failures: list[str] = []
    minimum_margin = math.inf
    maximum_gamma_residual = 0.0
    maximum_abs_tbar = 0.0
    for direction in (-1, 1):
        energy_records: dict[str, Any] = {}
        for energy in energies:
            active_scale_indices = range(len(scales)) if energy == nominal_energy else (len(scales) - 1,)
            records = [evaluated[(direction, energy, scale_index)] for scale_index in active_scale_indices]
            for record in records:
                if not record["stable"] or record["gamma_degrees"] is None or record["Tbar_xx_us_per_mm2"] is None:
                    failures.append(f"unstable_or_undefined:direction={direction}:energy={energy}")
            last = records[-1]
            if last["stable"]:
                minimum_margin = min(minimum_margin, float(last["stability_margin"]))
            gamma_change = None
            tbar_change = None
            if energy == nominal_energy and len(records) >= 2:
                previous = records[-2]
                if previous["gamma_degrees"] is not None and last["gamma_degrees"] is not None:
                    gamma_change = abs(float(last["gamma_degrees"]) - float(previous["gamma_degrees"]))
                if previous["Tbar_xx_us_per_mm2"] is not None and last["Tbar_xx_us_per_mm2"] is not None:
                    tbar_change = _relative_change(
                        float(last["Tbar_xx_us_per_mm2"]),
                        float(previous["Tbar_xx_us_per_mm2"]),
                        tbar_relative_change_absolute_floor_us_per_mm2,
                    )
                if gamma_change is None or gamma_change > maximum_adjacent_gamma_change_degrees:
                    failures.append(f"gamma_probe_not_converged:direction={direction}")
                if tbar_change is None or tbar_change > maximum_adjacent_relative_tbar_change:
                    failures.append(f"tbar_probe_not_converged:direction={direction}")
                if last["gamma_degrees"] is not None:
                    gamma_residual = abs(float(last["gamma_degrees"]) - target_gamma_degrees)
                    maximum_gamma_residual = max(maximum_gamma_residual, gamma_residual)
                    if gamma_residual > maximum_gamma_target_residual_degrees:
                        failures.append(f"gamma_target_failed:direction={direction}")
                if last["Tbar_xx_us_per_mm2"] is not None:
                    maximum_abs_tbar = max(maximum_abs_tbar, abs(float(last["Tbar_xx_us_per_mm2"])))
            energy_records[f"{energy:.17g}"] = {
                "scales": records,
                "last_adjacent_gamma_change_degrees": gamma_change,
                "last_adjacent_relative_Tbar_change": tbar_change,
            }
        directions[str(direction)] = energy_records
    if minimum_margin < minimum_stability_margin:
        failures.append("minimum_stability_margin_failed")

    return {
        "schema_version": 1,
        "role": "mrtof_fixed_operating_field_l1_analysis",
        "status": "screen_pass_diagnostic_only" if not failures else "screen_fail_diagnostic_only",
        "qualification": (
            "solver_neutral_fixed_operating_0p25mm_mirrors_0p5mm_other_regions_diagnostic__"
            "native_simion_validation_required"
        ),
        "probe_y_mm": float(operating_slice.basis.probe_y_mm),
        "mesh_by_region_mm_per_gu": {
            region: list(operating_slice.mesh_by_region_mm_per_gu[region]) for region in REGION_ORDER
        },
        "z_range_by_region_mm": {
            region: list(operating_slice.z_range_by_region_mm[region]) for region in REGION_ORDER
        },
        "energy_points_v": list(energies),
        "probe_scale_factors": list(scales),
        "probe_parallelism": {
            "requested_maximum_workers": maximum_parallel_workers,
            "actual_workers": worker_count,
            "job_count": len(jobs),
            "job_identity": "one_direction_energy_probe_scale_tuple",
        },
        "directions": directions,
        "selection_metrics": {
            "maximum_absolute_Tbar_xx_us_per_mm2": maximum_abs_tbar,
            "minimum_transverse_stability_margin": minimum_margin,
            "maximum_gamma_target_residual_degrees": maximum_gamma_residual,
        },
        "numerical_convergence_gates": {
            "maximum_adjacent_gamma_change_degrees": maximum_adjacent_gamma_change_degrees,
            "maximum_adjacent_relative_Tbar_change": maximum_adjacent_relative_tbar_change,
            "minimum_stability_margin": minimum_stability_margin,
        },
        "hard_gate_failures": sorted(set(failures)),
    }


def analyze_from_contract(
    *, basis_path: Path, probe_contract_path: Path, project_contract_path: Path, output_path: Path,
) -> dict[str, Any]:
    """Load frozen project controls and publish one fixed-field L1 report."""

    try:
        probe = json.loads(probe_contract_path.read_text(encoding="utf-8"))
        contract = json.loads(project_contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealFieldL1Error("fixed-field L1 input contract is unreadable") from exc
    if (
        not isinstance(probe, dict)
        or probe.get("role") != "mrtof_bare_mirror_real_field_period_probe"
        or probe.get("status") != "prepared"
    ):
        raise RealFieldL1Error("fixed-field L1 requires a prepared real-field period probe")
    try:
        requirements = contract["mirror"]["theory_requirements"]
        l1 = requirements["l1_screen_profile"]
        real = requirements["real_3d_l1_screen_profile"]
        trajectory_profile_id = str(real["fixed_grid_l1_trajectory_profile_id"])
        trajectory = contract["simion"]["trajectory_profiles"][trajectory_profile_id]
        species = contract["particle_source"]["species"]
        energies = tuple(float(value) for value in probe["energy_centers_ev"])
        probe_y = float(probe["probe_y_mm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RealFieldL1Error("project or period-probe contract lacks fixed-field L1 controls") from exc
    operating_slice = load_operating_field_csv(basis_path, probe_y_mm=probe_y)
    result = analyze_operating_field_l1(
        operating_slice,
        energy_points_v=energies,
        probe_scale_factors=tuple(float(value) for value in l1["probe_convergence_scale_factors"]),
        position_probe_mm=float(l1["position_probe_mm"]),
        angle_probe_rad=float(l1["angle_probe_rad"]),
        trace_controls={
            "particle_mass_th": float(species["mass_th"]),
            "particle_charge_e": float(species["charge_e"]),
            "relative_tolerance": float(real["surrogate_relative_tolerance"]),
            "absolute_tolerance": float(real["surrogate_absolute_tolerance"]),
            "maximum_step_us": float(trajectory["maximum_step_us"]),
            "maximum_leg_time_us": float(real["maximum_leg_time_us"]),
            "central_plane_offset_mm": float(real["central_plane_offset_mm"]),
        },
        target_gamma_degrees=float(l1["target_gamma_degrees"]),
        maximum_gamma_target_residual_degrees=float(l1["maximum_gamma_target_residual_degrees"]),
        maximum_adjacent_gamma_change_degrees=float(l1["maximum_adjacent_gamma_change_degrees"]),
        maximum_adjacent_relative_tbar_change=float(l1["maximum_adjacent_relative_Tbar_change"]),
        tbar_relative_change_absolute_floor_us_per_mm2=float(
            real["tbar_relative_change_absolute_floor_us_per_mm2"]
        ),
        minimum_stability_margin=float(real["minimum_stability_margin"]),
        maximum_parallel_workers=int(l1["maximum_parallel_workers"]),
    )
    result["inputs"] = {
        "fixed_operating_field_csv_sha256": file_sha256(basis_path),
        "period_probe_contract_sha256": file_sha256(probe_contract_path),
        "project_contract_sha256": file_sha256(project_contract_path),
    }
    result["trajectory_profile"] = {
        "profile_id": trajectory_profile_id,
        "maximum_step_us": float(trajectory["maximum_step_us"]),
        "relative_tolerance": float(real["surrogate_relative_tolerance"]),
        "absolute_tolerance": float(real["surrogate_absolute_tolerance"]),
        "maximum_leg_time_us": float(real["maximum_leg_time_us"]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    spec = commands.add_parser("spec")
    spec.add_argument("--plan", type=Path, required=True)
    spec.add_argument("--output", type=Path, required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--basis", type=Path, required=True)
    analyze.add_argument("--probe-contract", type=Path, required=True)
    analyze.add_argument("--project-contract", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "spec":
        write_sampler_spec(plan_path=arguments.plan, output_path=arguments.output)
        print("MRTOF_FIXED_OPERATING_FIELD_SPEC=PASS")
    else:
        from common.host_resource_python import ensure_heavy_entry

        ensure_heavy_entry(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "mirror_fixed_operating_field_l1",
            list(argv) if argv is not None else None,
            role="GATE",
            stage="theory_compute",
        )
        analyze_from_contract(
            basis_path=arguments.basis,
            probe_contract_path=arguments.probe_contract,
            project_contract_path=arguments.project_contract,
            output_path=arguments.output,
        )
        print("MRTOF_FIXED_OPERATING_FIELD_L1=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
