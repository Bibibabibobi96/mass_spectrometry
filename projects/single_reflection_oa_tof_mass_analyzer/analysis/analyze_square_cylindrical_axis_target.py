"""Check a paired square/cylindrical real-PA axis export against one Candidate.

This is a post-run, solver-free receipt reader.  It proves neither transverse
field equivalence nor resolution: it checks that two realizations consumed the
same axial target and quantifies their separately exported on-axis fields.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.exported_axis_field_integrator import (
    integrate_axis_to_plane_us,
    load_total_axis_field,
)


_CANDIDATE = "inputs/three_zone_t5_candidate_resolved.json"
_GEOMETRY = "inputs/oatof_resolved_geometry.json"
_NUMERICS = "inputs/resolved_single_flight_execution_profile.json"
_PULSE = "inputs/resolved_single_flight_pulse_schedule.json"
_SOURCE = "inputs/resolved_source_contract.json"
_FIELD = "results/total_axis_field.csv"
_CHECKPOINTS = "results/single_flight_particle_checkpoints.csv"
_DT_US = (1.0e-4, 5.0e-5, 2.5e-5)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _required(run: Path, relative: str) -> Path:
    path = run / relative
    if not path.is_file():
        raise ValueError(f"{run.name} lacks required {relative}")
    return path


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _projection(run_directory: Path, *, require_axis_field: bool = True) -> dict[str, Any]:
    """Read the run-local identities that must be invariant across shapes."""
    run = Path(run_directory).resolve()
    summary = _load(_required(run, "summary.json"))
    manifest = _load(_required(run, "run_manifest.json"))
    if summary.get("status") != "success" or manifest.get("status") != "success":
        raise ValueError(f"{run.name} is not a successful immutable run")
    candidate_path = _required(run, _CANDIDATE)
    candidate = _load(candidate_path)
    geometry = _load(_required(run, _GEOMETRY))
    numerics = _load(_required(run, _NUMERICS))
    pulse = _load(_required(run, _PULSE))
    source = _load(_required(run, _SOURCE))
    try:
        candidate_planes = candidate["accelerator_topology"]["planes_global_z_mm"]
        candidate_potentials = candidate["accelerator_topology"]["potentials_v"]
        geometry_planes = geometry["accelerator_topology"]["planes_global_z_mm"]
        geometry_potentials = geometry["accelerator_topology"]["potentials_v"]
        candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest().upper()
        declared_sha = geometry["single_flight_layout_derivation"]["design_compilation"]["candidate"]["sha256"]
        if candidate_sha != str(declared_sha).upper():
            raise ValueError("geometry Candidate SHA does not bind the run-local Candidate")
        if _canonical(candidate_planes) != _canonical(geometry_planes) or _canonical(candidate_potentials) != _canonical(geometry_potentials):
            raise ValueError("geometry planes or potentials differ from the run-local Candidate")
        source_branch = source["source_branches"]["simion"]["source"]
        source_identity = {"state_sha256": source_branch["state"]["sha256"], "manifest_sha256": source_branch["manifest"]["sha256"], "particle_count": source_branch["particle_count"]}
        pulse_identity = {"policy": pulse["policy"], "rf_period_us": pulse["rf_period_us"], "pulse_base_time_us": pulse["pulse_base_time_us"], "pulse_offset_us": pulse["pulse_offset_us"], "pulse_effective_time_us": pulse["pulse_effective_time_us"], "source_state_sha256": pulse["source_state_sha256"], "selected_particle_ids": pulse["selected_particle_ids"]}
        rings = geometry["rings"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"{run.name} lacks a complete 300 mm realization identity") from error
    return {"run_directory": str(run), "candidate_sha256": candidate_sha, "candidate": candidate, "planes_global_z_mm": candidate_planes, "potentials_v": candidate_potentials, "rings": rings, "numerics": numerics, "pulse": pulse_identity, "source": source_identity, "realization_id": geometry.get("geometry_derivation", {}).get("accelerator", {}).get("realization_id"), "field_path": _required(run, _FIELD) if require_axis_field else run / _FIELD}


def _same(label: str, first: Any, second: Any) -> None:
    if _canonical(first) != _canonical(second):
        raise ValueError(f"square/cylindrical {label} differs; paired axis comparison is invalid")


def _integral(field_z: np.ndarray, field_ez: np.ndarray, start: float, stop: float) -> float:
    if not (field_z[0] <= start < stop <= field_z[-1]):
        raise ValueError("axis export does not cover the Candidate accelerator planes")
    inside = (field_z > start) & (field_z < stop)
    z = np.concatenate(([start], field_z[inside], [stop]))
    return float(np.trapezoid(np.interp(z, field_z, field_ez), z))


def _drop_report(field_path: Path, planes: Mapping[str, Any], potentials: Mapping[str, Any]) -> dict[str, Any]:
    field = load_total_axis_field(field_path)
    roles = (("zone1", "repeller", "intermediate1"), ("zone2", "intermediate1", "intermediate2"), ("zone3", "intermediate2", "exit"))
    rows = []
    for name, start_role, stop_role in roles:
        start, stop = float(planes[start_role]), float(planes[stop_role])
        intended = float(potentials[start_role]) - float(potentials[stop_role])
        observed = _integral(field.z_mm, field.ez_v_per_mm, start, stop)
        rows.append({"zone": name, "z_start_mm": start, "z_stop_mm": stop, "candidate_drop_v": intended, "exported_integral_ez_dz_v": observed, "difference_v": observed - intended})
    total = _integral(field.z_mm, field.ez_v_per_mm, float(planes["repeller"]), float(planes["exit"]))
    intended_total = float(potentials["repeller"]) - float(potentials["exit"])
    return {"axis_field_csv": str(field_path.resolve()), "zones": rows, "whole_accelerator": {"candidate_drop_v": intended_total, "exported_integral_ez_dz_v": total, "difference_v": total - intended_total}}


def _field_difference(square_path: Path, cylindrical_path: Path) -> dict[str, float]:
    square, cylindrical = load_total_axis_field(square_path), load_total_axis_field(cylindrical_path)
    start, stop = max(square.z_mm[0], cylindrical.z_mm[0]), min(square.z_mm[-1], cylindrical.z_mm[-1])
    if not start < stop:
        raise ValueError("square/cylindrical axis exports have no common interval")
    grid = np.unique(np.concatenate((square.z_mm[(square.z_mm >= start) & (square.z_mm <= stop)], cylindrical.z_mm[(cylindrical.z_mm >= start) & (cylindrical.z_mm <= stop)])))
    difference = np.interp(grid, square.z_mm, square.ez_v_per_mm) - np.interp(grid, cylindrical.z_mm, cylindrical.ez_v_per_mm)
    return {"common_z_min_mm": float(start), "common_z_max_mm": float(stop), "sample_count": int(grid.size), "ez_difference_rms_v_per_mm": float(np.sqrt(np.mean(difference ** 2))), "ez_difference_max_abs_v_per_mm": float(np.max(np.abs(difference)))}


def _checkpoint_states(path: Path) -> tuple[dict[int, tuple[float, float]], float]:
    states: dict[int, tuple[float, float]] = {}
    exits: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            particle_id = int(row["particle_id"])
            if row.get("event") == "pre_pulse_state":
                if particle_id in states:
                    raise ValueError("duplicate pre_pulse_state in trajectory receipt")
                states[particle_id] = (float(row["z_mm"]), float(row["vz_mm_per_us"]))
            elif row.get("event") == "local_accelerator_exit":
                exits[particle_id] = float(row["z_mm"])
    common = set(states).intersection(exits)
    if not common or set(states) != common or set(exits) != common:
        raise ValueError("trajectory receipt lacks one complete pre-pulse-to-local-exit cohort")
    planes = np.asarray([exits[item] for item in sorted(common)], dtype=float)
    if not np.all(np.isfinite(planes)) or np.ptp(planes) > 1.0e-9:
        raise ValueError("trajectory receipt local exit is not one shared plane")
    return states, float(planes[0])


def _integrator_report(axis_run: Mapping[str, Any], trajectory_run: Path | None) -> dict[str, Any]:
    """Use saved artifacts only; never run a solver or manufacture a state."""
    if trajectory_run is None:
        return {"status": "NOT_RUN", "reason": "No trajectory run was supplied.", "required_interface": {"trajectory_run": "successful paired full-flight run with results/single_flight_particle_checkpoints.csv", "required_events": ["pre_pulse_state", "local_accelerator_exit"]}}
    trajectory = _projection(trajectory_run, require_axis_field=False)
    for label in ("candidate_sha256", "planes_global_z_mm", "potentials_v", "numerics", "pulse", "source"):
        _same(f"trajectory attachment {label}", axis_run[label], trajectory[label])
    states, exit_plane = _checkpoint_states(_required(Path(trajectory["run_directory"]), _CHECKPOINTS))
    source = axis_run["candidate"]["source_identity"]["frozen_source"]
    field = load_total_axis_field(axis_run["field_path"])
    elapsed_by_dt: dict[str, float] = {}
    for dt_us in _DT_US:
        values = [integrate_axis_to_plane_us(field, z0_mm=z, vz0_mm_per_us=vz, z_stop_mm=exit_plane, mass_th=float(source["mass_to_charge_th"]), charge_state=int(source["charge_sign"]), dt_us=dt_us) for z, vz in states.values()]
        elapsed_by_dt[str(dt_us)] = float(np.mean(values) * 1000.0)
    fine, previous = elapsed_by_dt[str(_DT_US[-1])], elapsed_by_dt[str(_DT_US[-2])]
    return {"status": "RUN", "trajectory_run": trajectory["run_directory"], "particle_count": len(states), "local_exit_z_mm": exit_plane, "mean_pre_pulse_to_local_exit_ns_by_dt_us": elapsed_by_dt, "finest_pair_relative_difference": abs(fine - previous) / max(abs(fine), 1.0e-15)}


def analyze_square_cylindrical_axis_target(*, square_run: Path, cylindrical_run: Path, square_trajectory_run: Path | None = None, cylindrical_trajectory_run: Path | None = None) -> dict[str, Any]:
    """Validate paired identities and report exported axis-field diagnostics."""
    square, cylindrical = _projection(square_run), _projection(cylindrical_run)
    for label in ("candidate_sha256", "planes_global_z_mm", "potentials_v", "rings", "numerics", "pulse", "source"):
        _same(label, square[label], cylindrical[label])
    if square["realization_id"] == cylindrical["realization_id"]:
        raise ValueError("paired runs must declare distinct accelerator realizations")
    return {"schema_version": 1, "role": "square_cylindrical_accelerator_axis_target_report", "claim_limit": "Post-run on-axis real-PA comparison only. It does not establish transverse equivalence, collection, peak width, resolution, or a Formal result.", "conclusion": "PASS_CONTINUE", "identities": {key: square[key] for key in ("candidate_sha256", "planes_global_z_mm", "potentials_v", "rings", "numerics", "pulse", "source")}, "realizations": {"square": {"run_directory": square["run_directory"], "realization_id": square["realization_id"], "integrated_drops": _drop_report(square["field_path"], square["planes_global_z_mm"], square["potentials_v"])}, "cylindrical": {"run_directory": cylindrical["run_directory"], "realization_id": cylindrical["realization_id"], "integrated_drops": _drop_report(cylindrical["field_path"], cylindrical["planes_global_z_mm"], cylindrical["potentials_v"]) }}, "square_minus_cylindrical_axis_field_diagnostic": _field_difference(square["field_path"], cylindrical["field_path"]), "independent_axis_integrator": {"square": _integrator_report(square, square_trajectory_run), "cylindrical": _integrator_report(cylindrical, cylindrical_trajectory_run)}, "claims_supported": ["The two supplied successful runs consumed one Candidate, identical axial planes/potentials/rings/numerics/pulse/source identities, and exported comparable on-axis fields."], "claims_prohibited": ["The square and cylindrical three-dimensional fields are identical.", "Either realization has better collection, peak width, resolution, or transverse performance."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--square-run", required=True, type=Path)
    parser.add_argument("--cylindrical-run", required=True, type=Path)
    parser.add_argument("--square-trajectory-run", type=Path)
    parser.add_argument("--cylindrical-trajectory-run", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_square_cylindrical_axis_target(square_run=args.square_run, cylindrical_run=args.cylindrical_run, square_trajectory_run=args.square_trajectory_run, cylindrical_trajectory_run=args.cylindrical_trajectory_run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
