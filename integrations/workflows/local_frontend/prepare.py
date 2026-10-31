"""Compile a manifest-bound IP guide/OA frontend without a downstream analyzer.

This preparation boundary performs no source generation, particle selection,
native discovery, field solving, capacity admission, or run publication.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.artifact_naming import validate_run_id
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.rigid_transform import RigidTransform
from common.integration.resolve_assembly import derive_assembly_scope
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import require_completed_terminal_publication
from common.ion_release.release import validate_release_spec
from integrations.runtime.single_flight_electrode_contract import render_pa_plus_solution_model
from integrations.runtime.single_flight_frontend import compile_frontend
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS, SOURCE_COLUMNS, transform_source_rows
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract, export_guide_assembly_interface
from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
from projects.orthogonal_accelerator.analysis.accelerator_time_focus import time_to_fixed_plane_s
from projects.orthogonal_accelerator.analysis.three_zone_ideal_theory import (
    AffineSource, OuterGeometry, derive_three_zone_state, exact_accelerator_normalized_time,
)

ROLE = "instrument_assembly_local_frontend_request"
SOURCE_NAMES = ("producer_manifest", "resolved_model", "source_spec", "release_csv")
SOURCE_CLOCK = {"policy_id": "zero_local_launch_clock__program_restores_frozen_birth_time_v1",
                "source_clock": "instrument_time_us", "native_fly2_tob_us": 0,
                "program_birth_time_restore_required": True}
AUTOMATIC_PULSE_POLICY = "detector_blind_actual_occupancy_v1"
RF_DELAY_PULSE_POLICY = "detector_blind_actual_occupancy_rf_delay_v1"


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


def _producer_clock(records: dict, run: Path, model: dict) -> dict:
    """Bind the producer's declared clock files without authoring a second epoch."""
    paths, identities = {}, {}
    for name in ("clock_authority", "instrument_epoch"):
        relative = f"inputs/{name}.json"
        matches = [record for record in records.values()
                   if record_path(record, base_dir=run) == (run / relative).resolve()]
        if len(matches) != 1:
            raise ValueError(f"producer must declare one exact {relative} input")
        identities[name] = dict(matches[0])
        paths[name] = record_path(matches[0], base_dir=run)
    verify_record("producer clock_authority", identities["clock_authority"], base_dir=run)
    receipt = validate_clock_authority(paths["clock_authority"], run)
    contract = _load(paths["clock_authority"])
    if Path(contract["authority"]["path"]).as_posix() != "inputs/instrument_epoch.json":
        raise ValueError("clock authority must reference the declared run-relative inputs/instrument_epoch.json")
    # The public validator has already read and hashed the epoch. Bind its
    # result to the manifest without hashing the same source a second time.
    epoch_record = identities["instrument_epoch"]
    if (paths["instrument_epoch"].stat().st_size != epoch_record.get("bytes")
            or receipt["authority_sha256"] != str(epoch_record.get("sha256", "")).upper()):
        raise ValueError("instrument epoch identity differs from the producer manifest")
    epoch = _load(paths["instrument_epoch"])
    value = _number(epoch.get("instrument_time_us"), "instrument epoch")
    if value != _number(model["baseline"]["clock"]["epoch_us"], "resolved guide epoch"):
        raise ValueError("instrument epoch and resolved guide epoch differ")
    if value != 0:
        raise ValueError("local frontend requires the supported zero instrument epoch")
    return dict(paths=paths, records=identities, clock_epoch_id=receipt["clock_epoch_id"])


def _source_inputs(request: dict, workspace: Path) -> tuple[dict, dict, dict, list, dict]:
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
        # The bytes were checked by _input_path. Bind that same identity to the
        # producer record without reading the closed source payload again.
        if (matches[0].get("bytes") != request[name]["bytes"]
                or str(matches[0].get("sha256", "")).upper() != str(request[name]["sha256"]).upper()):
            raise ValueError(f"{name} identity differs from the producer manifest")
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
    return paths, model, spec, rows, manifest


def _registration(request: dict, guide: dict, component: dict, frontend: dict) -> tuple[dict, RigidTransform]:
    _keys(request, {"source_to_common", "guide_to_solver"}, "registration")
    source = RigidTransform.from_contract(request["source_to_common"])
    common = RigidTransform.from_contract(request["guide_to_solver"])
    if source.to_contract() != guide["coordinate_transform"] or common.from_frame_id != source.to_frame_id:
        raise ValueError("source/common guide transform differs from provider")
    if common.to_frame_id != "mrtof_global_cartesian":
        raise ValueError("guide destination must be mrtof_global_cartesian")
    # Compose the two authoritative rigid transforms; no propagation or clock shift.
    combined = source.then(common)
    pose = (frontend["accelerator_local_region"]["axis_center_mm"] if component["variant_id"] == "three_zone"
            else component["transform"]["translation_mm"])
    exit_center = [pose[0], pose[1], frontend["accelerator_local_region"]["planes"]["exit"]]
    mr = RigidTransform.identity(common.to_frame_id)
    return dict(source_to_common=source.to_contract(), guide_to_solver=common.to_contract(),
                source_to_solver=combined.to_contract(), observer_to_mr=mr.to_contract(),
                oa_exit_center_solver_mm=exit_center, target_exit_center_mr_mm=exit_center), combined


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
    delayed = isinstance(pulse, dict) and pulse.get("policy_id") == RF_DELAY_PULSE_POLICY
    _keys(pulse, {"policy_id", "seed"} | ({"delay_rf_periods"} if delayed else set()), "pulse")
    if delayed and (type(pulse["delay_rf_periods"]) is not int or pulse["delay_rf_periods"] < 0):
        raise ValueError("delay_rf_periods must be a nonnegative integer")
    seed = pulse["seed"]
    _keys(seed, {"method", "candidate_steps_per_rf_period", "envelope_padding_rf_periods"}, "pulse seed")
    if pulse["policy_id"] not in {AUTOMATIC_PULSE_POLICY, RF_DELAY_PULSE_POLICY} or seed["method"] != "source_ballistic_arrival_envelope_v1":
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


def resolve_pulse_decision(prepared: dict, recommendation: dict) -> dict:
    """Bind the applied pulse to this run's recommendation and authored RF delay.

    The existing 32-ULP serialization rule only associates a recorded candidate
    with the derived target; it never snaps the applied time to that candidate.
    Missing or unsupported target records are explicit stopped decisions.
    """
    plan, numerics = prepared["pulse_plan"], prepared["numerics"]
    policy = plan["policy_id"]
    if policy not in {AUTOMATIC_PULSE_POLICY, RF_DELAY_PULSE_POLICY}:
        raise ValueError("unsupported pulse decision policy")
    if recommendation.get("status") != "selected" or recommendation.get("selection_uses_future_terminal_outcome") is not False:
        raise ValueError("pulse decision requires a same-run detector-blind recommendation")
    recommended = _number(recommendation["selected_time_us"], "recommended pulse time")
    period = _number(plan["rf_period_us"], "RF period", positive=True)
    delay = plan["delay_rf_periods"] if policy == RF_DELAY_PULSE_POLICY else 0
    if type(delay) is not int or delay < 0:
        raise ValueError("delay_rf_periods must be a nonnegative integer")
    try:
        delay_us = _number(delay * period, "RF delay")
        # Preserve the existing automatic pulse exactly, including its float bits.
        actual = recommended if policy == AUTOMATIC_PULSE_POLICY else _number(recommended + delay_us, "actual pulse time")
    except OverflowError as exc:
        raise ValueError("RF delay exceeds the finite pulse horizon") from exc
    low = _number(plan["source_birth_time_range_us"][0], "first birth time")
    high = (_number(plan["source_birth_time_range_us"][1], "last birth time")
            + _number(numerics["maximum_flight_us"], "maximum particle age", positive=True))
    if not low <= recommended <= actual <= high:
        raise ValueError("recommended or actual pulse is outside the complete frozen birth/age horizon")
    matches = []
    for candidate in recommendation["candidates"]:
        time = _number(candidate["candidate_time_us"], "recorded candidate time")
        if abs(time - actual) <= 32 * max(math.ulp(time), math.ulp(actual)):
            matches.append(candidate)
    if len(matches) > 1:
        raise ValueError("multiple recorded candidates match the derived pulse target")
    target = matches[0] if matches else None
    occupancy = dict(status="missing_recorded_candidate", candidate_time_us=None,
                     candidate_minus_actual_us=None, exact_time_match=False,
                     pulse_eligible_count=None, eligible_ids=[], unsupported_ids=[])
    status = "target_snapshot_missing"
    if target is not None:
        eligible, unsupported = target["eligible_ids"], target["unsupported_ids"]
        if (not isinstance(eligible, list) or not isinstance(unsupported, list)
                or any(type(ion) is not int or ion <= 0 for ion in [*eligible, *unsupported])
                or len(set(eligible)) != len(eligible) or len(set(unsupported)) != len(unsupported)
                or set(eligible) & set(unsupported)
                or type(target["pulse_eligible_count"]) is not int or target["pulse_eligible_count"] != len(eligible)):
            raise ValueError("recorded target occupancy identities or count differ")
        occupancy.update(status="unsupported_recorded_candidate" if unsupported else "recorded_candidate",
                         candidate_time_us=target["candidate_time_us"],
                         candidate_minus_actual_us=target["candidate_time_us"] - actual,
                         exact_time_match=target["candidate_time_us"] == actual,
                         pulse_eligible_count=len(eligible), eligible_ids=eligible, unsupported_ids=unsupported)
        status = "target_snapshot_unsupported" if unsupported else "ready"
    return dict(schema_version=1, role="rf_oatof_local_frontend_pulse_decision", status=status,
                recommendation_policy_id=AUTOMATIC_PULSE_POLICY, applied_policy_id=policy,
                recommendation_time_us=recommended, actual_pulse_time_us=actual,
                delay_rf_periods=delay, rf_period_us=period, delay_us=delay_us,
                horizon_us=[low, high], same_rf_phase_by_integer_cycles=True,
                actual_time_derivation=("recommendation_time_us" if policy == AUTOMATIC_PULSE_POLICY
                                        else "recommendation_time_us + delay_rf_periods * rf_period_us"),
                target_match_rule="recorded_candidate_within_32_serialization_ulps__no_time_snapping",
                target_occupancy=occupancy, selection_uses_future_terminal_outcome=False,
                source_population_changed=False)


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


def prepare_local_frontend(request_path: Path, output_directory: Path | None, workspace_root: Path, *, run_id: str | None = None) -> dict:
    """Validate/compile in memory, or freeze into an already owned run directory."""
    workspace = Path(workspace_root).resolve(strict=True)
    request_path = Path(request_path).resolve(strict=True)
    request = _load(request_path)
    _keys(request, {"schema_version", "role", "source", "accelerator_component", "composition_plan", "numerics", "pulse", "diagnostics"}
          | ({"local_scope"} if "local_scope" in request else set())
          | ({"verify_saved_workbench_replay"} if "verify_saved_workbench_replay" in request else set()), "request")
    if type(request.get("verify_saved_workbench_replay", False)) is not bool:
        raise ValueError("verify_saved_workbench_replay must be a boolean")
    request = {**request, "verify_saved_workbench_replay": request.get("verify_saved_workbench_replay", False)}
    if type(request["schema_version"]) is not int or request["schema_version"] != 3 or request["role"] != ROLE:
        raise ValueError("unsupported local frontend request")
    if output_directory is not None:
        if run_id is None:
            raise ValueError("writing a prepared run requires run_id")
        validate_run_id(run_id)
    parent_record = request["composition_plan"]
    if (not isinstance(parent_record, dict) or not {"path", "bytes", "sha256"} <= set(parent_record)
            or set(parent_record) - {"path", "bytes", "sha256", "exists"}):
        raise ValueError("composition_plan requires one explicit file record")
    parent_path = record_path(parent_record, base_dir=request_path.parent)
    frozen_parent = None
    if output_directory is not None:
        inputs = Path(output_directory).resolve() / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        frozen_parent = inputs / "parent_composition_plan.json"
        if frozen_parent.exists():
            raise ValueError("refuse to overwrite frozen local parent composition plan")
        shutil.copyfile(parent_path, frozen_parent)
        verify_record("frozen local parent composition plan", {**parent_record, "path": str(frozen_parent)})
    else:
        verify_record("local parent composition plan", {**parent_record, "path": str(parent_path)})
    plan = derive_assembly_scope(_load(frozen_parent or parent_path), local_scope=request.get("local_scope"))
    recipe = plan["recipe"]
    if recipe["assembly_frame_id"] != "mrtof_global_cartesian":
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
    paths, model, spec, raw_rows, manifest = _source_inputs(request["source"], workspace)
    clock = _producer_clock(manifest["inputs"], paths["producer_manifest"].parent, model)
    guide = export_guide_contract(model, {k: request["source"][k] for k in SOURCE_NAMES[1:]})
    component = copy.deepcopy(request["accelerator_component"])
    if "transform" in component:
        raise ValueError("accelerator placement belongs only to the frozen composition plan")
    selected = set(plan["scope"]["instance_ids"])
    edges = [edge for edge in recipe["connections"] if edge["connection_id"] in plan["scope"]["connection_ids"]]
    if len(selected) != 2 or len(edges) != 1:
        raise ValueError("local frontend selected scope requires exactly one guide and one OA connection")
    edge = edges[0]
    upstream_id, downstream_id = edge["upstream"]["instance_id"], edge["downstream"]["instance_id"]
    if (upstream_id == downstream_id or {upstream_id, downstream_id} != selected
            or plan["components"][upstream_id]["project_id"] != "dual_pressure_rectilinear_ion_processor"
            or plan["components"][downstream_id]["project_id"] != "orthogonal_accelerator"
            or edge["upstream"]["port_id"] != "guide_exit" or edge["downstream"]["port_id"] != "side_entry"
            or edge["coupling_mode"] != "monolithic_joint_solve"):
        raise ValueError("local frontend requires the selected IP guide_exit to OA side_entry joint solve")
    components = {
        upstream_id: export_guide_assembly_interface(guide),
        downstream_id: resolve_assembly_interface(component["requirements"], geometry_profile_id=component["geometry_profile_id"]),
    }
    for instance_id, interface in components.items():
        if plan["components"][instance_id] != interface:
            raise ValueError(f"{instance_id}: resolved provider interface differs from frozen parent composition")
    if plan["integration_id"] != "instrument_assembly":
        raise ValueError("local frontend assembly owner must be instrument_assembly")
    poses = {item["instance_id"]: item["transform"] for item in plan["recipe"]["instances"]}
    declared = RigidTransform.from_contract(poses[upstream_id])
    # Layout compilation has validated this direct pose. Transport its declared
    # numbers unchanged; re-exporting a transform needlessly changes JSON types
    # and can invalidate an otherwise identical native-field cache identity.
    component["transform"] = {key: poses[downstream_id][key] for key in ("rotation", "translation_mm")}
    gap = next(check["gap_mm"] for check in plan["connection_checks"] if check["connection_id"] == edge["connection_id"])
    connection = {"spatial_registration": {"rotation_upstream_to_downstream": [list(r) for r in declared.rotation],
                                           "translation_mm": list(declared.translation_mm)}, "connector": {"length_mm": gap}}
    gem, frontend = compile_frontend(guide, connection, cell_mm_xyz=numerics["cell_mm_xyz"], accelerator_component=component,
                                     target_solver_frame=recipe["assembly_frame_id"])
    registration, source_transform = _registration(
        {"source_to_common": guide["coordinate_transform"], "guide_to_solver": poses[upstream_id]}, guide, component, frontend,
    )
    global_rows = transform_source_rows(raw_rows, source_transform)
    pulse = _pulse_plan(request["pulse"], global_rows, guide, component, frontend)
    region = frontend["accelerator_local_region"]
    model_basis = frontend["pa_plus_solution_model"]
    physical = dict(geometry=_physical_geometry(frontend, guide),
                    gem=hashlib.sha256(gem.encode("utf-8")).hexdigest().upper(), basis_namespace=model_basis, mesh=numerics["cell_mm_xyz"],
                    grid_phase=frontend["instance_origin_mm"], surface="none", refine_policy="official_defaults",
                    scope="physical_builder_inputs_only__native_identity_and_public_cache_key_added_by_executor")
    result = dict(schema_version=1, role="instrument_assembly_local_frontend_preparation", status="validated", particle_count=len(raw_rows),
                  default_replay_requested=request["verify_saved_workbench_replay"],
                  input_records={name: dict(path=str(path), exists=True, bytes=request["source"][name]["bytes"],
                                            sha256=request["source"][name]["sha256"].upper()) for name, path in paths.items()} | clock["records"]
                  | {"composition_plan": dict(parent_record, path=str(frozen_parent or parent_path), source_path=str(parent_path))},
                  frontend_contract=frontend, guide_contract=guide, assembly_plan=plan, registration=registration, numerics=numerics,
                  pulse_plan=pulse, cache_physical_inputs=physical)
    if output_directory is None:
        return result
    output = Path(output_directory).resolve()
    inputs = output / "inputs"
    documents = {"request.json": request, "guide_contract.json": guide, "frontend_contract.json": frontend,
                 "composition_plan.json": plan,
                 "numerics.json": numerics,
                 "registration.json": registration, "pulse_plan.json": pulse, "cache_physical_inputs.json": physical,
                 "on_voltages.json": region["operating_voltages_v"], "off_voltages.json": region["off_voltages_v"],
                 "source_identity.json": {"provider_project_id": guide["provider_project_id"], "source_inputs": result["input_records"],
                                          "particle_count": len(raw_rows), "sampling": "complete_frozen_population__no_resampling",
                                          "clock_epoch_id": clock["clock_epoch_id"],
                                          "native_clock_projection": SOURCE_CLOCK}}
    payloads = {name: (json.dumps(value, indent=2, allow_nan=False)+"\n").encode("utf-8") for name, value in documents.items()}
    identity = dict(schema_version=2, integration_id=plan["integration_id"], workflow_id="local_frontend", run_id=run_id,
                    composition_plan=dict(path="composition_plan.json", sha256=hashlib.sha256(payloads["composition_plan.json"]).hexdigest().upper()))
    validate_schema(identity, "integration_artifact_identity.schema.json")
    payloads["integration_identity.json"] = (json.dumps(identity, indent=2)+"\n").encode("utf-8")
    # Parent evidence is already frozen; all scientific checks precede derived outputs.
    inputs.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (inputs / name).write_bytes(payload)
    paths.update(clock["paths"])
    for name, source_name in {"resolved_model.json": "resolved_model", "source_spec.json": "source_spec",
                              "release_raw.csv": "release_csv", "producer_manifest.json": "producer_manifest",
                              "clock_authority.json": "clock_authority", "instrument_epoch.json": "instrument_epoch"}.items():
        source = paths[source_name]
        target = inputs / name
        if source != target:
            shutil.copyfile(source, target)
        verify_record(f"frozen {name}", {**result["input_records"][source_name], "path": str(target)})
    texts = {"frontend.gem": gem, "frontend.pa+": render_pa_plus_solution_model(model_basis),
             "release_global.csv": _csv_text(GLOBAL_COLUMNS, global_rows)}
    for name, text in texts.items():
        (inputs / name).write_text(text, encoding="utf-8", newline="\n")
    result.update(status="prepared", output_directory=str(output))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only and args.output_directory is not None:
        parser.error("validate-only cannot write an output directory")
    if not args.validate_only and args.output_directory is None:
        parser.error("preparation requires an output directory")
    if args.validate_only and args.run_id is not None:
        parser.error("validate-only does not create a run identity")
    if not args.validate_only and args.run_id is None:
        parser.error("preparation requires the managed run ID")
    result = prepare_local_frontend(args.request, args.output_directory, args.workspace_root, run_id=args.run_id)
    print(json.dumps({k: result[k] for k in ("role", "status", "particle_count")} | {"output_directory": result.get("output_directory")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
