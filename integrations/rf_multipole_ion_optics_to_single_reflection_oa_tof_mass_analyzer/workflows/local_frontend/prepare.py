"""Compile a manifest-bound IP guide/OA frontend without a downstream analyzer.

This preparation boundary performs no source generation, particle selection,
native discovery, field solving, capacity admission, or run publication.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.rigid_transform import FramedPosition, RigidTransform
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.ion_release.release import validate_release_spec
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import render_pa_plus_solution_model
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import compile_frontend
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import GLOBAL_COLUMNS, SOURCE_COLUMNS, materialize, render_restart_fly2
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.orthogonal_accelerator.analysis.three_zone_ideal_theory import (
    AffineSource, OuterGeometry, derive_three_zone_state, exact_accelerator_normalized_time,
)

ROLE = "rf_oatof_local_frontend_request"
SOURCE_NAMES = ("producer_manifest", "resolved_model", "source_spec", "release_csv")
SOURCE_CLOCK = {"policy_id": "zero_local_launch_clock__program_restores_frozen_birth_time_v1",
                "source_clock": "instrument_time_us", "native_fly2_tob_us": 0,
                "program_birth_time_restore_required": True}


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _keys(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} fields differ: expected {sorted(keys)}")


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def _input_path(workspace: Path, identity: dict, label: str) -> Path:
    _keys(identity, {"path", "bytes", "sha256"}, label)
    text = identity["path"]
    if not isinstance(text, str) or not text.startswith("artifacts/"):
        raise ValueError(f"{label} must be an explicit workspace artifacts/ path")
    path = (workspace / text).resolve(strict=True)
    if not path.is_relative_to((workspace / "artifacts").resolve()):
        raise ValueError(f"{label} escapes workspace artifacts")
    if type(identity["bytes"]) is not int or identity["bytes"] <= 0:
        raise ValueError(f"{label} byte identity invalid")
    verify_record(label, {**identity, "path": str(path)})
    return path


def _source_inputs(request: dict, workspace: Path) -> tuple[dict, dict, dict, dict]:
    _keys(request, set(SOURCE_NAMES), "source")
    paths = {name: _input_path(workspace, request[name], name) for name in SOURCE_NAMES}
    manifest_path = paths["producer_manifest"]
    require_completed_terminal_publication(manifest_path)
    manifest = _load(manifest_path)
    if (manifest.get("status") != "success" or manifest.get("project") != "dual_pressure_rectilinear_ion_processor"
            or manifest.get("role") != "simulation_run_manifest"):
        raise ValueError("source producer must be a successful IP run manifest")
    verify_record("producer run_config", manifest["run_config"], base_dir=manifest_path.parent)
    records = manifest.get("inputs")
    if not isinstance(records, dict):
        raise ValueError("producer input records missing")
    for name in SOURCE_NAMES[1:]:
        matches = [r for r in records.values() if record_path(r, base_dir=manifest_path.parent) == paths[name]]
        if len(matches) != 1:
            raise ValueError(f"{name} must be one exact producer manifest input")
        verify_record(name, matches[0], base_dir=manifest_path.parent)
    model, spec = _load(paths["resolved_model"]), _load(paths["source_spec"])
    validate_release_spec(spec)
    if model.get("source") != spec:
        raise ValueError("resolved model and frozen source spec differ")
    with paths["release_csv"].open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise ValueError("release CSV canonical columns differ")
        rows = list(reader)
    count = spec["particle_count"]
    if type(count) is not int or count <= 0 or spec["mother_particle_count"] != count or len(rows) != count:
        raise ValueError("release must contain the complete declared mother population")
    validate_standard_particle_count(count)
    if [int(r["particle_id"]) for r in rows] != list(range(1, count + 1)):
        raise ValueError("complete ordered source IDs required")
    for row in rows:
        values = {key: float(row[key]) for key in SOURCE_COLUMNS}
        if not all(math.isfinite(v) for v in values.values()) or values["mass_amu"] <= 0:
            raise ValueError("release contains invalid canonical numeric values")
        charge = values["charge_state"]
        if charge == 0 or not charge.is_integer():
            raise ValueError("release charge must be a nonzero integer")
    return paths, model, spec, rows


def _registration(request: dict, guide: dict, component: dict, frontend: dict) -> tuple[dict, dict]:
    _keys(request, {"source_to_common", "guide_to_solver"}, "registration")
    source = RigidTransform.from_contract(request["source_to_common"])
    common = RigidTransform.from_contract(request["guide_to_solver"])
    if source.to_contract() != guide["coordinate_transform"] or common.from_frame_id != source.to_frame_id:
        raise ValueError("source/common guide transform differs from provider")
    if common.to_frame_id != "mrtof_global_cartesian":
        raise ValueError("guide destination must be mrtof_global_cartesian")
    # Compose the two authoritative rigid transforms; no propagation or clock shift.
    rotation = [[sum(common.rotation[a][k] * source.rotation[k][b] for k in range(3)) for b in range(3)] for a in range(3)]
    translation = common.transform_position(FramedPosition(common.from_frame_id, source.translation_mm)).coordinates_mm
    combined = RigidTransform(source.from_frame_id, common.to_frame_id, rotation, translation)
    pose = (frontend["accelerator_local_region"]["axis_center_mm"] if component["variant_id"] == "three_zone"
            else component["transform"]["translation_mm"])
    exit_center = [pose[0], pose[1], frontend["accelerator_local_region"]["planes"]["exit"]]
    mr = RigidTransform.identity(common.to_frame_id)
    return dict(source_to_common=source.to_contract(), guide_to_solver=common.to_contract(),
                source_to_solver=combined.to_contract(), observer_to_mr=mr.to_contract(),
                oa_exit_center_solver_mm=exit_center, target_exit_center_mr_mm=exit_center), {
                    "spatial_registration": {"rotation_upstream_to_downstream": rotation, "translation_mm": list(translation)}}


def _nominal_extraction_duration(frontend: dict, source_row: dict) -> float:
    """Use the provider's ideal timing oracle solely for display scheduling."""
    local = frontend["accelerator_local_region"]
    planes, ids = local["planes"], frontend["electrodes"]
    on = local["operating_voltages_v"]
    repeller, grid1, exit_v = (on[str(ids[name])] for name in
                             ("accelerator_repeller_id", "accelerator_grid1_id", "accelerator_grid2_id"))
    d1 = planes["repeller"]-planes["grid1"]
    release = planes["repeller"]-local["port"]["center_mm"][2]
    mass_to_charge = float(source_row["mass_amu"])/float(source_row["charge_state"])
    if local["accelerator_component"]["variant_id"] == "two_zone":
        return 1e6*time_to_fixed_plane_s(repeller, grid1, d1, planes["grid1"]-planes["exit"],
                                         release, 0, 0, mass_to_charge, exit_v=exit_v)
    if local["accelerator_component"]["variant_id"] != "three_zone":
        raise ValueError("unsupported provider extraction-time oracle")
    if exit_v != 0:
        raise ValueError("three-zone timing oracle requires the declared zero exit voltage")
    intermediate = on[str(ids["accelerator_intermediate2_id"])]
    d2 = planes["grid1"]-planes["intermediate2"]
    d3 = planes["intermediate2"]-planes["exit"]
    source = AffineSource.from_velocity(mass_to_charge_th=mass_to_charge, center_x_mm=release,
                                        center_velocity_m_per_s=0, velocity_slope_m_per_s_per_mm=0)
    outer = OuterGeometry(zone1_length_mm=d1, downstream_length_mm=d2+d3, split_fraction=d2/(d2+d3),
                          zone1_voltage_drop_v=repeller-grid1,
                          nominal_energy_per_charge_v=repeller-(repeller-grid1)*release/d1)
    state = derive_three_zone_state(source, outer, math.log(((grid1-intermediate)/d2)/(intermediate/d3)))
    return 1e6*source.time_scale_s_per_mm_sqrt_v*exact_accelerator_normalized_time(source, state, release, 0)


def _pulse_plan(pulse: dict, global_rows: list[dict], guide: dict, component: dict, frontend: dict) -> dict:
    _keys(pulse, {"policy_id", "seed"}, "pulse")
    seed = pulse["seed"]
    _keys(seed, {"method", "candidate_steps_per_rf_period", "envelope_padding_rf_periods"}, "pulse seed")
    if pulse["policy_id"] != "detector_blind_actual_occupancy_v1" or seed["method"] != "source_ballistic_arrival_envelope_v1":
        raise ValueError("unsupported explicit pulse policy")
    steps = seed["candidate_steps_per_rf_period"]
    if type(steps) is not int or steps <= 0:
        raise ValueError("candidate_steps_per_rf_period must be a positive integer")
    padding = _number(seed["envelope_padding_rf_periods"], "RF padding", positive=True)
    period = 1e6 / guide["drive"]["frequency_hz"]
    slow = frontend["slow_axis"]
    index = "xyz".index(slow)
    axis_center = (frontend["accelerator_local_region"]["axis_center_mm"] if component["variant_id"] == "three_zone"
                   else component["transform"]["translation_mm"])
    axis = float(axis_center[index])
    arrivals, guide_arrivals = [], []
    times, positions, speeds = [], [], []
    guide_x = frontend["guide_exit_center_mm"][slow]
    for row in global_rows:
        time, x, vx = (float(row[k]) for k in ("instrument_time_us", f"position_{slow}_mm", f"velocity_{slow}_m_s"))
        if vx <= 0 or axis < x or guide_x < x:
            raise ValueError("all source particles must have future ballistic positive slow-axis guide/OA crossings")
        arrivals.append(time + 1000 * (axis - x) / vx)
        guide_arrivals.append(time + 1000 * (guide_x - x) / vx)
        times.append(time)
        positions.append(x)
        speeds.append(vx)
    mean_root = (axis - sum(x - v*t/1000 for x, v, t in zip(positions, speeds, times))/len(times))*1000/(sum(speeds)/len(times))
    start, stop = min(arrivals)-padding*period, max(arrivals)+padding*period
    step = period/steps
    candidates = [start + k*step for k in range(math.floor((stop-start)/step)+1)]
    duration, unavailable = None, None
    try:
        duration = _nominal_extraction_duration(frontend, global_rows[0])
    except (ValueError, ArithmeticError) as exc:
        unavailable = str(exc)
    return dict(**pulse, scope="predicted_constant_velocity_seed__not_actual_occupancy_or_selected_pulse",
                particle_count=len(global_rows), rf_period_us=period, slow_axis=slow, oa_axis_coordinate_mm=axis,
                predicted_arrival_min_us=min(arrivals), predicted_arrival_max_us=max(arrivals),
                predicted_centroid_axis_time_us=mean_root, candidate_start_us=start, candidate_stop_us=stop,
                candidate_step_us=step, candidate_times_us=candidates,
                predicted_nominal_extraction_duration_us=duration, extraction_duration_unavailable_reason=unavailable,
                extraction_duration_provider_variant=component["variant_id"],
                extraction_duration_scope="provider_uniform_field_theory__nominal_sideport_center_zero_main_velocity_first_source_species__display_schedule_only",
                source_birth_time_range_us=[min(times), max(times)],
                predicted_guide_exit_time_range_us=[min(guide_arrivals), max(guide_arrivals)])


def extraction_shared_times(prepared: dict, pulse_time_us: float) -> list[float]:
    """Freeze a bounded automatic display schedule over the full native horizon.

    33 whole-horizon, 17 capture-envelope and 17 fast-extraction samples are
    display-policy constants, independent of solver step size or qualification.
    Predicted landmarks do not replace compulsory actual native exit records.
    """
    pulse_time_us = _number(pulse_time_us, "actual pulse time")
    plan, numerics = prepared["pulse_plan"], prepared["numerics"]
    start = plan["source_birth_time_range_us"][0]
    stop = plan["source_birth_time_range_us"][1] + numerics["maximum_flight_us"]
    values = [*plan["source_birth_time_range_us"], *plan["predicted_guide_exit_time_range_us"],
              plan["predicted_arrival_min_us"], plan["predicted_arrival_max_us"], pulse_time_us]

    def interval(low: float, high: float, count: int) -> None:
        values.extend(low+(high-low)*k/(count-1) for k in range(count))

    interval(start, stop, 33)
    interval(plan["candidate_start_us"], plan["candidate_stop_us"], 17)
    duration = plan["predicted_nominal_extraction_duration_us"]
    if duration is not None:
        interval(pulse_time_us-duration, pulse_time_us+2*duration, 17)
        values.append(pulse_time_us+duration)
    # Existing authored RF cadence supplies local phase landmarks; no new RF policy.
    values.extend(pulse_time_us+k*plan["rf_period_us"] for k in (-1, 0, 1))
    return sorted({float(value) for value in values if start <= value <= stop})


def _csv_text(columns: list[str], rows: list[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _physical_geometry(frontend: dict, guide: dict) -> dict:
    """Project the actual PA geometry, without a source realization or drive.

    The source envelope is retained because it participates in PA extent
    construction. Particle identities, velocities, clocks and operating volts
    do not define an electrostatic response basis. GEM SHA is also bound
    separately, so this projection never substitutes for compiled geometry.
    """
    local = frontend["accelerator_local_region"]
    return {
        "native_frame_id": frontend["native_frame_id"],
        "electrodes": frontend["electrodes"],
        "rod_array": guide["rod_array"],
        "guide_registration": frontend["guide_registration"],
        "source_envelope_bounds_mm": guide["source_envelope_bounds_mm"],
        "canonical_electrodes": local["canonical_electrodes"],
        "accelerator_transform": local["accelerator_component"]["transform"],
        "accelerator_bounds_mm": local["actual_bounds_mm"],
        "accelerator_planes_z_mm": local["planes"],
        "ring_z_mm": local["ring_z_mm"],
        "port": local["port"],
        "guide_exit_center_mm": frontend["guide_exit_center_mm"],
        "source_exit_center_mm": frontend["source_exit_center_mm"],
        "junction_enclosure": frontend["junction_enclosure"],
        "instance_bounds_mm": frontend["instance_bounds_mm"],
        "instance_origin_mm": frontend["instance_origin_mm"],
        "dimensions": frontend["dimensions"],
    }


def prepare_local_frontend(request_path: Path, output_directory: Path | None, repo_root: Path, workspace_root: Path) -> dict:
    """Validate/compile in memory, or freeze into an already owned run directory."""
    repo, workspace = Path(repo_root).resolve(strict=True), Path(workspace_root).resolve(strict=True)
    request_path = Path(request_path).resolve(strict=True)
    request = _load(request_path)
    _keys(request, {"schema_version", "role", "output_frame_id", "source", "accelerator_component", "registration", "connection", "numerics", "pulse", "diagnostics"}, "request")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["role"] != ROLE:
        raise ValueError("unsupported local frontend request")
    if request["output_frame_id"] != "mrtof_global_cartesian":
        raise ValueError("local frontend must compile directly in the MR solver frame")
    numerics = request["numerics"]
    _keys(numerics, {"cell_mm_xyz", "refine_policy", "maximum_step_us", "rf_steps_per_period", "maximum_flight_us", "trajectory_sample_interval_us", "trajectory_quality"}, "numerics")
    _keys(numerics["cell_mm_xyz"], set("xyz"), "cell_mm_xyz")
    for value in numerics["cell_mm_xyz"].values():
        _number(value, "cell pitch", positive=True)
    for key in ("maximum_step_us", "rf_steps_per_period", "maximum_flight_us", "trajectory_sample_interval_us"):
        _number(numerics[key], key, positive=True)
    if type(numerics["rf_steps_per_period"]) is not int or numerics["refine_policy"] != "official_defaults":
        raise ValueError("explicit integer RF steps and official_defaults refine policy required")
    if type(numerics["trajectory_quality"]) is not int or not 1 <= numerics["trajectory_quality"] <= 500:
        raise ValueError("trajectory_quality must be an explicit integer within local policy 1..500")
    if request["diagnostics"] != {"policy_id": "automatic_full_population_v1"}:
        raise ValueError("automatic full-population diagnostics required")
    _keys(request["connection"], {"rod_end_to_side_wall_gap_mm"}, "connection")
    gap = _number(request["connection"]["rod_end_to_side_wall_gap_mm"], "rod end gap", positive=True)
    paths, model, spec, raw_rows = _source_inputs(request["source"], workspace)
    guide = export_guide_contract(model, {k: request["source"][k] for k in SOURCE_NAMES[1:]})
    declared = RigidTransform.from_contract(request["registration"]["guide_to_solver"])
    connection = {"spatial_registration": {"rotation_upstream_to_downstream": [list(r) for r in declared.rotation],
                                           "translation_mm": list(declared.translation_mm)}, "connector": {"length_mm": gap}}
    component = request["accelerator_component"]
    gem, frontend = compile_frontend(guide, {}, connection, cell_mm_xyz=numerics["cell_mm_xyz"], accelerator_component=component,
                                     target_solver_frame=request["output_frame_id"])
    registration, source_connection = _registration(request["registration"], guide, component, frontend)
    _, global_rows = materialize(paths["release_csv"], source_connection)
    pulse = _pulse_plan(request["pulse"], global_rows, guide, component, frontend)
    region = frontend["accelerator_local_region"]
    model_basis = frontend["pa_plus_solution_model"]
    builder_paths = [Path(__file__).resolve(), repo / "projects/dual_pressure_rectilinear_ion_processor/analysis/guide_interface.py",
                     repo / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runtime/single_flight_frontend.py"]
    physical = dict(geometry=_physical_geometry(frontend, guide),
                    gem=hashlib.sha256(gem.encode("utf-8")).hexdigest().upper(), basis_namespace=model_basis, mesh=numerics["cell_mm_xyz"],
                    grid_phase=frontend["instance_origin_mm"], surface="none", refine_policy="official_defaults",
                    builder_identity=[file_record(path) for path in builder_paths],
                    scope="physical_builder_inputs_only__native_identity_and_public_cache_key_added_by_executor")
    result = dict(schema_version=1, role="rf_oatof_local_frontend_preparation", status="validated", particle_count=len(raw_rows),
                  input_records={name: file_record(path) for name, path in paths.items()}, output_records={},
                  frontend_contract=frontend, guide_contract=guide, registration=registration, numerics=numerics,
                  pulse_plan=pulse, cache_physical_inputs=physical, source_clock=dict(SOURCE_CLOCK))
    if output_directory is None:
        return result
    output = Path(output_directory).resolve()
    inputs = output / "inputs"
    # All scientific checks precede the first write. Public caller owns admission/lifecycle.
    inputs.mkdir(parents=True, exist_ok=True)
    documents = {"guide_contract.json": guide, "frontend_contract.json": frontend, "accelerator_component.json": component,
                 "pa_plus_solution_model.json": model_basis, "numerics.json": numerics,
                 "registration.json": registration, "pulse_plan.json": pulse, "cache_physical_inputs.json": physical,
                 "source_clock.json": SOURCE_CLOCK,
                 "on_voltages.json": region["operating_voltages_v"], "off_voltages.json": region["off_voltages_v"],
                 "source_identity.json": {"provider_project_id": guide["provider_project_id"], "source_inputs": result["input_records"],
                                          "particle_count": len(raw_rows), "sampling": "complete_frozen_population__no_resampling",
                                          "native_clock_projection": SOURCE_CLOCK},
                 "diagnostics_plan.json": dict(**request["diagnostics"], scope="actual_native_snapshots_and_losses_required__seed_times_are_predictions",
                                               source_birth_time_range_us=pulse["source_birth_time_range_us"],
                                               predicted_guide_exit_time_range_us=pulse["predicted_guide_exit_time_range_us"],
                                               oa_exit_center_solver_mm=registration["oa_exit_center_solver_mm"])}
    for name, value in documents.items():
        (inputs / name).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    for name, source in {"request.json": request_path, "resolved_model.json": paths["resolved_model"],
                         "source_spec.json": paths["source_spec"], "release_raw.csv": paths["release_csv"],
                         "producer_manifest.json": paths["producer_manifest"]}.items():
        target = inputs / name
        if source != target:
            shutil.copyfile(source, target)
        if file_sha256(target) != file_sha256(source):
            raise ValueError(f"frozen input changed: {name}")
    texts = {"frontend.gem": gem, "frontend.pa+": render_pa_plus_solution_model(model_basis),
             "release_global.csv": _csv_text(GLOBAL_COLUMNS, global_rows), "source.fly2": render_restart_fly2(global_rows)}
    for name, text in texts.items():
        (inputs / name).write_text(text, encoding="utf-8", newline="\n")
    result.update(status="prepared", output_directory=str(output),
                  output_records={path.name: file_record(path) for path in sorted(inputs.iterdir()) if path.is_file()})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only and args.output_directory is not None:
        parser.error("validate-only cannot write an output directory")
    if not args.validate_only and args.output_directory is None:
        parser.error("preparation requires an output directory")
    result = prepare_local_frontend(args.request, args.output_directory, args.repo_root, args.workspace_root)
    print(json.dumps({k: result[k] for k in ("role", "status", "particle_count")} | {"output_directory": result.get("output_directory")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
