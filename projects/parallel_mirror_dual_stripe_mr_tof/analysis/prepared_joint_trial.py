"""MR physical preparation consumed by the root prepared-joint workflow."""
from __future__ import annotations

import json
from decimal import Decimal
from functools import partial
import re
from common.paths.workspace_paths import project_native_run_path

from pathlib import Path
import shutil
import subprocess
import sys
from itertools import zip_longest
from typing import Any

from common.contracts.frozen_inputs import freeze_file
from common.contracts.component_particle_state import load_component_particle_state_csv
from common.contracts.verify_run_manifest import record_path, verify_record, verified_successful_run_reference
from common.contracts.write_run_manifest import file_record
from common.integration.resolve_assembly import derive_assembly_scope
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import (
    RUNTIME_LUA, materialize_measured_source_slice, materialize_centroid_probe,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import (
    ION_PROCESSOR, validate_execution_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding, native_response_operator
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection, resolve_ip_mr_transform
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import _lua, collision_workbench_layout, render_measured_operating_point
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import resolve_trajectory_recording
from common.simion.native_completion import parse_fly_completed_line
from common.simion.scientific_event_io import iter_csv_rows
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events


verified_preparation_reference = partial(
    verified_successful_run_reference,
    project="instrument_assembly", mode="accelerator_interface_preparation",
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def compile_memory_consumer_crops(contract: dict[str, Any], reference: dict[str, Any],
                                  binding: dict[str, Any]) -> dict[str, Any]:
    """Project frozen stored-x authority into in-memory views of full solved mirrors."""
    targets = contract["simion"]["numerical_profiles"]["native_static_field"]["target_layout"]["windows"]
    reference_windows = reference["field_binding"]["refinement_windows"]
    if len(targets) != len(reference_windows):
        raise ValueError("Frozen MR window policy order differs from its reference")
    available = {window["name"]: window for window in binding["refinement_windows"]}
    crops = {}
    for reference_window, target in zip(reference_windows, targets):
        if "stored_xmax_mm" not in target:
            continue
        name = reference_window["name"]
        if name not in {"positive_integer_grid_a", "negative_integer_grid_a"}:
            raise ValueError("In-memory crop is restricted to mirror field windows")
        level = available[name]
        grid = level["grid"]
        if grid["pitch_mm"][0] != target["pitch_mm"][0]:
            raise ValueError("Memory consumer x pitch differs from the frozen window policy")
        xmax, origin, pitch = (Decimal(str(value)) for value in (
            target["stored_xmax_mm"], grid["origin_mm"][0], grid["pitch_mm"][0]))
        points = (xmax-origin)/pitch
        if origin != 0 or points != points.to_integral_value():
            raise ValueError("Stored mirror x limit must align with its x-mirror grid")
        source_dimensions = list(grid["dimensions"])
        dimensions = [int(points)+1, *source_dimensions[1:]]
        if not 1 < dimensions[0] <= source_dimensions[0]:
            raise ValueError("Mirror consumer crop exceeds the source grid")
        active_xmax = max(Decimal(str(abs(value))) for value in level["active_box_mm"][0])
        if active_xmax+pitch > xmax:
            raise ValueError("Mirror consumer crop lacks the existing gradient halo")
        crops[name] = dict(source_dimensions=source_dimensions, consumer_dimensions=dimensions,
                           start_grid=[0, 0, 0], width_grid=[value-1 for value in dimensions])
    return crops


def validate_candidate_binding(binding: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Keep the actual IP operator fixed while allowing only four P/S coordinates."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority, PS_GROUPS
    collision_workbench_layout(binding)
    if baseline.get("collision_overlay") and not binding.get("collision_overlay"):
        raise ValueError("Candidate cannot silently remove the prepared collision overlay")
    if binding.get("collision_overlay"):
        # The public loader verifies the complete overlay and its original four
        # instances. Compare only its source field operator, not collision pitch.
        source = load_binding(Path(binding["source_descriptor_path"]))
        baseline_source = (load_binding(Path(baseline["source_descriptor_path"]))
                           if baseline.get("collision_overlay") else baseline)
        return validate_candidate_binding(source, baseline_source)
    roles = ["global_fallback", "native_corridor", "ion_processor_collision", "detector"]
    if (binding.get("accelerator_provider") != ION_PROCESSOR
            or [r["role"] for r in binding["instances"]] != roles
            or binding["geometry"] != baseline["geometry"]
            or binding["authority"].get("assembly") != baseline["authority"].get("assembly")):
        raise ValueError("Candidate field must retain the prepared IP replacement geometry and four roles")
    values = binding["authority"]["analyzer_electrode_voltages_v"]
    candidate = {key: values[ids[0]-1] for key, ids in PS_GROUPS.items()}
    if binding["authority"] != candidate_authority(baseline["authority"], candidate):
        raise ValueError("Candidate field changed fixed non-P/S or IP15 voltage authority")
    if native_response_operator(binding, baseline["authority"]) != native_response_operator(baseline, baseline["authority"]):
        raise ValueError("Candidate field changed the prepared actual numerical IP operator")
    if (binding["instances"][0]["pa_path"] != binding["sources"]["scalar_pa"]
            or binding["instances"][0]["origin_mm"] != binding["grid"]["origin_mm"]):
        raise ValueError("Candidate global collision instance must reuse its new scalar parent")
    return candidate


def _native_projection(binding: dict[str, Any]) -> dict[str, Any]:
    def level(item):
        grid = item["grid"]
        return dict(mode="native_static_pa", scalar_pa=item["sources"]["scalar_pa"],
                    origin_mm=grid["origin_mm"], pitch_mm=grid["pitch_mm"], dimensions=grid["dimensions"], symmetry="x")
    result = level(binding)
    result.update(accelerator_provider=ION_PROCESSOR, assembly_scope="full_c0_ion_processor_replacement",
                  analyzer_voltages_v=binding["authority"]["analyzer_electrode_voltages_v"],
                  collision_pa_path=binding["instances"][1]["pa_path"],
                  collision_geometry_pa_paths=[item["pa_path"] for item in binding["instances"]
                                               if item["role"] in ("ion_processor_collision", "detector")],
                  refinement_windows=[dict(level(item), name=item["name"], active_box_mm=item["active_box_mm"])
                                      for item in binding["refinement_windows"]])
    if binding.get("collision_overlay"):
        result["collision_overlay"] = collision_workbench_layout(binding)["priority"]["collision_overlay"]
    return result


def _prepared_assembly(prepared_run: Path, parent: dict, manifest: dict) -> tuple[dict, dict, dict]:
    """Inherit only the current parent and range already frozen by preparation."""
    sources = {}
    for name in ("composition_plan", "accelerator_request"):
        record = parent["inputs"].get(name)
        if record is None:
            raise ValueError("Prepared joint execution requires the current frozen parent plan and matching request")
        path = verified_preparation_reference(prepared_run, "inputs/" + name + ".json", manifest=manifest)
        if record_path(record, base_dir=prepared_run) != path.resolve():
            raise ValueError("Prepared assembly input differs from its canonical frozen path: " + name)
        sources[name] = (path, record)
    request = _read(sources["accelerator_request"][0])
    if request.get("schema_version") != 3 or request.get("role") != "mrtof_ion_processor_matching_request":
        raise ValueError("Prepared joint execution requires the current schema-3 matching request")
    plan = derive_assembly_scope(_read(sources["composition_plan"][0]), local_scope=request.get("local_scope"))
    connection = resolve_ip_mr_connection(plan)
    return plan, connection, sources


def _continuation_waveforms(predecessor_manifest: Path) -> tuple[Path, dict[str, Any]]:
    """Resolve the predecessor's manifest-bound small helper for the new run."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation import _bound_parent_input
    manifest_path = predecessor_manifest.resolve()
    manifest = _read(manifest_path)
    config_record = manifest["run_config"]
    verify_record("continuation run configuration", config_record)
    config_path = Path(config_record["path"]).resolve()
    if config_path != manifest_path.parent / "run_config.json":
        raise ValueError("Continuation manifest run configuration is not its own")
    config = _read(config_path)
    if config.get("project") != "instrument_assembly" or config.get("mode") != "prepared_joint":
        raise ValueError("Continuation predecessor is not a prepared-joint run")
    trial_record = _bound_parent_input(parent_inputs=config.get("inputs") or {}, manifest=manifest,
                                       role="prepared_joint_trial")
    trial = _read(Path(trial_record["path"]))
    waveform = trial["voltage_waveforms"]
    verify_record("continuation flight waveform", waveform)
    return Path(waveform["path"]).resolve(), {"manifest": str(manifest_path),
                                              "prepared_joint_trial": trial_record,
                                              "voltage_waveforms": waveform}


def prepare_trial(prepared_run: Path, contract_path: Path, run_directory: Path,
                  reference_flight_run: Path | None = None, *,
                  field_binding_path: Path | None = None, source_mode: str = "measured_population",
                  continuation_predecessor_manifest: Path | None = None) -> dict[str, Any]:
    """Verify sealed small inputs and field metadata; never rehash or copy PA payloads."""
    if source_mode not in {"measured_population", "centroid_probe"}:
        raise ValueError("Unsupported prepared source mode")
    if source_mode == "centroid_probe" and reference_flight_run is not None:
        raise ValueError("Constructed probe is not the original population equivalence cohort")
    prepared_manifest = _read(prepared_run / "run_manifest.json")
    receipt_path = verified_preparation_reference(prepared_run, "results/accelerator_interface_preparation.json", manifest=prepared_manifest)
    parent = _read(receipt_path)
    if (parent.get("selected_provider") != ION_PROCESSOR
            or parent.get("status") != "workbench_ready_no_joint_flight"):
        raise ValueError("A completed measured joint workbench preparation is required")
    joint = parent["joint_workbench_binding"]
    if not joint["field_assembly_verified"] or not joint["measured_source_matches_workpoint"]:
        raise ValueError("Joint source/field identity is unverified")
    plan, connection, assembly_sources = _prepared_assembly(prepared_run, parent, prepared_manifest)
    expected_contract_record = parent["inputs"]["reference_trajectory"]
    verify_record("prepared trajectory contract", expected_contract_record)
    expected_contract = _read(Path(expected_contract_record["path"]))
    contract = _read(contract_path)
    recording = resolve_trajectory_recording(contract)
    if recording is None:
        raise ValueError("Joint flight requires explicit solver_review trajectory recording")
    execution = validate_execution_contract(expected_contract, contract, allow_controller_budget=True)
    reference_profile = execution["reference_profile"]
    trajectory_profile = execution["selected_profile"]
    step_change = execution["numerical_change"]
    budget_change = execution["execution_budget_change"]
    results, inputs = run_directory / "results", run_directory / "inputs"
    results.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    assembly_records = {}
    for name, (path, record) in assembly_sources.items():
        target = inputs / ("parent_composition_plan.json" if name == "composition_plan" else "accelerator_request.json")
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(path, target)
        verify_record("frozen prepared assembly " + name, {**record, "path": str(target)})
        assembly_records[name] = dict(record, path=str(target.resolve()), source_path=str(path.resolve()))
    contract_copy = inputs / "trajectory_contract.json"
    freeze_file(contract_path, contract_copy)
    reference_materialization = joint["reference_materialization"]
    verified_preparation_reference(prepared_run, Path(reference_materialization["path"]).relative_to(prepared_run).as_posix(), manifest=prepared_manifest)
    reference_materialization_copy = inputs / "reference_materialization.json"
    freeze_file(Path(reference_materialization["path"]), reference_materialization_copy)
    source = prepared_run / "results/joint_workbench/measured_source"
    source_receipt_path = verified_preparation_reference(prepared_run, "results/joint_workbench/measured_source/source_receipt.json", manifest=prepared_manifest)
    source_receipt = _read(source_receipt_path)
    historical_source_receipt = inputs / "prepared_source_receipt.json"
    freeze_file(source_receipt_path, historical_source_receipt)
    source_copy = results / "measured_source"
    source_copy.mkdir()
    for path in sorted(source.iterdir()):
        if path.is_file():
            verified_preparation_reference(prepared_run, path.relative_to(prepared_run).as_posix(), manifest=prepared_manifest)
            if path.name not in {"source_runtime.lua", "source_receipt.json"}:
                freeze_file(path, source_copy / path.name)
    # Canonical CSV/clock/ordinal projection remain byte-identical; executable
    # adapters are frozen from current code, never the obsolete sealed helper.
    (source_copy / "source_runtime.lua").write_text(RUNTIME_LUA, encoding="utf-8", newline="\n")
    runtime_implementation = inputs / "measured_source_implementation.py"
    freeze_file(Path(__file__).with_name("measured_component_source.py"), runtime_implementation)
    current_source_receipt = dict(source_receipt)
    current_source_receipt["inputs"] = dict(source_receipt["inputs"],
        prepared_source_receipt=file_record(historical_source_receipt),
        runtime_implementation=file_record(runtime_implementation))
    current_source_receipt["outputs"] = {path.stem: file_record(path)
        for path in sorted(source_copy.iterdir())}
    _write(source_copy / "source_receipt.json", current_source_receipt)
    mother_source_copy = source_copy
    if source_mode == "centroid_probe":
        source_copy = results / "centroid_probe"
        source_receipt = materialize_centroid_probe(mother_source_copy, source_copy)
    rows = load_component_particle_state_csv(source_copy / "component_particle_state.csv").rows
    source_id, target_id = connection["upstream"]["instance_id"], connection["downstream"]["instance_id"]
    registration = resolve_ip_mr_transform(plan, connection).to_contract()
    if any(row["source_component_id"] != source_id or row["target_component_id"] != target_id
           or row["frame_id"] != registration["to_frame_id"] for row in rows):
        raise ValueError("Prepared measured source differs from the inherited assembly connection or frame")
    peak = contract.get("peak_analysis")
    if peak is not None:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import validate_measured_peak_source_reference
        validate_measured_peak_source_reference(peak, contract_path.parent, source_receipt,
                                                {int(row["particle_id"]): row for row in rows})
    binding_path = verified_preparation_reference(prepared_run, "results/joint_workbench/static_field_binding.json", manifest=prepared_manifest)
    binding = load_binding(binding_path)
    if binding.get("accelerator_provider") != ION_PROCESSOR:
        raise ValueError("IP replacement field identity required")
    assembly = binding["authority"].get("assembly", {})
    if (binding["geometry"]["frame_id"] != registration["to_frame_id"]
            or assembly.get("ion_processor_registration") != registration):
        raise ValueError("Prepared field geometry or registration differs from the inherited assembly poses")
    if field_binding_path is not None:
        candidate = load_binding(field_binding_path)
        validate_candidate_binding(candidate, binding)
        binding_path = Path(freeze_file(field_binding_path, inputs / "candidate_field_binding.json")["path"])
        binding = candidate
    layout = collision_workbench_layout(binding)
    memory_crops = compile_memory_consumer_crops(contract, _read(reference_materialization_copy), binding)
    guard_paths = [item["pa_path"] for item in binding["instances"]]
    for level in [binding, *binding["refinement_windows"]]:
        guard_paths.append(level["sources"]["scalar_pa"])
        if level["sources"].get("surface"):
            guard_paths.append(level["sources"]["surface"])
    runtime = prepared_run / "results/joint_workbench/runtime"
    # Capture every executable companion as a small frozen input before dispatch.
    frozen_runtime = inputs / "prepared_runtime"
    frozen_runtime.mkdir()
    for path in sorted(runtime.glob("joint.*")):
        if path.name in {"joint.operating_point.lua", "joint.lua", "joint.source_runtime.lua",
                         "joint.scalar_field_adapter.lua", "joint.priority.lua", "joint.voltage_waveforms.lua"}:
            continue
        verified_preparation_reference(prepared_run, path.relative_to(prepared_run).as_posix(), manifest=prepared_manifest)
        freeze_file(path, frozen_runtime / path.name)
    current_program = Path(__file__).parents[1] / "simion/mrtof_candidate.lua"
    program_record = freeze_file(current_program, frozen_runtime / "joint.lua")
    waveform_source, waveform_provenance = (Path(__file__).parents[3] / "common/simion/voltage_waveforms.lua", None)
    if continuation_predecessor_manifest is not None:
        waveform_source, waveform_provenance = _continuation_waveforms(continuation_predecessor_manifest)
    waveforms_record = freeze_file(waveform_source,
                                  frozen_runtime / "joint.voltage_waveforms.lua")
    if waveform_provenance is not None:
        waveforms_record["continuation_source"] = waveform_provenance
    source_runtime_record = freeze_file(source_copy / "source_runtime.lua", frozen_runtime / "joint.source_runtime.lua")
    science_writer_record = freeze_file(Path(__file__).resolve().parents[3] / "common/simion/scientific_event_csv.lua", frozen_runtime / "joint.scientific_event_csv.lua")
    freeze_file(Path(__file__).parents[1] / "simion/scalar_field_adapter.lua",
                frozen_runtime / "joint.scalar_field_adapter.lua")
    reference = runtime / "mr_reference.operating_point.lua"
    verified_preparation_reference(prepared_run, reference.relative_to(prepared_run).as_posix(), manifest=prepared_manifest)
    freeze_file(reference, frozen_runtime / reference.name)
    (frozen_runtime / "joint.priority.lua").write_text("return " + _lua(layout["priority"]) + "\n",
                                                      encoding="utf-8", newline="\n")
    reference_numerics = joint["numerics"]
    if any(reference_numerics[name] != reference_profile[name]
           for name in ("trajectory_quality", "maximum_step_us")):
        raise ValueError("Prepared JSON numerics differ from its default trajectory profile")
    numerics = dict(reference_numerics, trajectory_quality=trajectory_profile["trajectory_quality"],
                    maximum_step_us=trajectory_profile["maximum_step_us"])
    freeze_file(Path(__file__).parents[3] / "common/paths/native_run_path.lua", frozen_runtime / "native_run_path.lua")
    sidecar = render_measured_operating_point(frozen_runtime / reference.name, source_copy,
        _native_projection(binding), numerics=numerics, field_assets_verified=True, source_identity_verified=True,
        native_path_projection=True)
    sidecar = sidecar.replace("\nreturn t\n", "\nlocal crops="+_lua(memory_crops)+"\n"
        "for _,window in ipairs(t.static_field.refinement_windows) do\n"
        "  window.memory_consumer_crop=crops[window.name]\nend\nreturn t\n")
    (frozen_runtime / "joint.operating_point.lua").write_text(sidecar, encoding="utf-8", newline="\n")
    launcher = Path(__file__).parents[1] / "simion/run_iob_flight.lua"
    freeze_file(launcher, inputs / launcher.name)
    effective_launcher = inputs / launcher.name
    projection = freeze_file(Path(__file__).parents[3] / "common/paths/native_run_path.lua", inputs / "native_run_path.lua")
    if field_binding_path is not None:
        builder = Path(__file__).parents[1] / "simion/build_native_corridor_iob.lua"
        freeze_file(builder, inputs / builder.name)
        effective_launcher = inputs / "build_and_run_prepared_iob.lua"
        effective_launcher.write_text("local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\\\])'))\n"
            "local native_path=assert(loadfile(directory..'native_run_path.lua'))()\nlocal saved_arg=arg\nlocal iob=assert(arg[1])\n"
            "arg={'--measured-source',iob:gsub('%.iob$','.workbench_build.lua'),directory..'native_run_path.lua'}\n"
            "dofile(native_path("+_lua(str(inputs / builder.name))+ "))\narg=saved_arg\n"
            "dofile(native_path("+_lua(str(inputs / launcher.name))+ "))\n", encoding="utf-8", newline="\n")
    identifiers = [int(row["particle_id"]) for row in rows]
    topology = "five" if len(layout["roles"]) == 5 else "four"
    result = dict(schema_version=1, role="mrtof_prepared_joint_trial", parent_prepared_run=str(prepared_run.resolve()),
                  measured_source_directory=str(source_copy.resolve()), expected_particle_ids=identifiers,
                  mother_particle_count=source_receipt["counts"]["source"], launched_particle_count=len(rows),
                  solver_epoch_instrument_time_us=source_receipt["solver_epoch_instrument_time_us"],
                  trajectory_contract=file_record(contract_copy), trajectory_recording=recording,
                  controller_contract_provenance=dict(
                      prepared_reference_trajectory_contract=dict(expected_contract_record),
                      consumed_execution_contract=file_record(contract_copy), execution_budget_change=budget_change,
                      analysis_change=execution["analysis_change"],
                      numerical_change=step_change, prepared_reference_numerics=reference_numerics,
                      selected_trajectory_profile=dict(trajectory_profile)),
                  trajectory_profile=dict(trajectory_profile),
                  reference_materialization=file_record(reference_materialization_copy),
                  source_receipt=file_record(source_copy / "source_receipt.json"),
                  flight_program=program_record,
                  source_runtime=source_runtime_record,
                  scientific_event_writer=science_writer_record,
                  voltage_waveforms=waveforms_record,
                  field_consumer_adapter=file_record(frozen_runtime / "joint.scalar_field_adapter.lua"),
                  memory_consumer_crops=memory_crops,
                  operating_point=file_record(frozen_runtime / "joint.operating_point.lua"),
                  parent_preparation=file_record(receipt_path), field_binding=file_record(binding_path),
                  parent_composition_plan=assembly_records["composition_plan"],
                  assembly_request=assembly_records["accelerator_request"], assembly_scope=plan["scope"],
                  guard_paths=sorted(set(guard_paths)), protected_paths=[str(prepared_run.resolve()), joint["field_run"], joint["source_run"]],
                  numerics=numerics, frozen_runtime_directory=str(frozen_runtime.resolve()), launcher=str(effective_launcher.resolve()),
                  native_path_projection=projection, source_mode=source_mode, mother_source_directory=str(mother_source_copy.resolve()),
                  candidate_iob_rebuild=field_binding_path is not None,
                  prism_voltages_v=[binding["authority"]["analyzer_electrode_voltages_v"][i] for i in (15,16)],
                  stripe_biases_v=[binding["authority"]["analyzer_electrode_voltages_v"][i] for i in (10,12)],
                  energy_target_acceptance="not_declared", six_dimensional_match_qualified=False,
                  time_focus_qualified=False)
    result["dispatch_request"] = dict(
        solver="SIMION", field_kind="electrostatic", particle_count=len(rows), independent_particles=True,
        frontend_grid_profile_id=f"mrtof_ip_replacement_static_{topology}_instances",
        oatof_numerical_profile_id=None, trajectory_quality_profile_id=trajectory_profile["profile_id"],
        time_integration_profile_id="mrtof_candidate_adaptive_time_step",
        frontend_cell_mm_xyz=binding["grid"]["pitch_mm"], accelerator_overlay_cell_mm_xyz=None,
        reflectron_cell_mm=None, trajectory_quality=numerics["trajectory_quality"],
        rf_steps_per_period=None, accelerator_field_profile_id="measured_ip_handoff_static_replacement",
        frontend_pa0_sha256=binding["records"]["scalar_pa"]["sha256"],
        accelerator_overlay_pa0_sha256=None, reflectron_pa0_sha256=None,
        case_input_sha256=result["operating_point"]["sha256"],
        workload_topology_id=f"mrtof_ip_measured_{topology}_instances_full_flight",
        field_loading_policy_id=(f"native_static_pa__{topology}_read_only_collision_instances"
                                 + ("__memory_mirror_x_crop" if memory_crops else "")))
    result["trajectory_equivalence_reference"] = None
    result["protected_paths"] += sorted({str(Path(item["manifest"]).parent)
                                           for item in [binding, *binding["refinement_windows"], *binding["instances"]]})
    if reference_flight_run is not None:
        result["trajectory_equivalence_reference"] = freeze_equivalence_reference(
            reference_flight_run, result, inputs)
    reference=result.get("trajectory_equivalence_reference")
    if reference is not None and reference.get("scientific_event_output") is not None:
        result["protected_paths"].append(reference["source_run"])
        result["guard_paths"].extend(reference["scientific_event_output"][key] for key in ("events_path","trajectory_path") if reference["scientific_event_output"].get(key))
    _write(results / "simion_dispatch_request.json", result["dispatch_request"])
    _write(results / "prepared_joint_trial.json", result)
    return result


def freeze_equivalence_reference(reference_run: Path, preparation: dict[str, Any],
                                  inputs: Path) -> dict[str, Any]:
    """Bind a completed batch from a fully verified interrupted flight, without PA reads."""
    subprocess.run([sys.executable, "-m", "common.contracts.verify_run_manifest",
                    str(reference_run / "run_manifest.json"), "--require-status", "interrupted"],
                   cwd=Path(__file__).resolve().parents[3], timeout=60,
                   check=True, capture_output=True, text=True, encoding="utf-8")
    manifest = _read(reference_run / "run_manifest.json")
    # Historical MR runs remain read-only comparison evidence. New executions
    # have exactly the assembly owner/mode; no old public execution branch exists.
    if (manifest.get("project"), manifest.get("mode")) not in {
        ("instrument_assembly", "prepared_joint"),
        ("parallel_mirror_dual_stripe_mr_tof", "two_prism_joint_measured_trial"),
    }:
        raise ValueError("Equivalence reference owner/mode differs from a prepared joint flight")
    outputs = {record_path(record, base_dir=reference_run): record for record in manifest["outputs"]}

    def published_output(relative: str) -> Path:
        path = (reference_run / relative).resolve()
        if path not in outputs:
            raise ValueError("Equivalence manifest does not bind " + relative)
        return path  # The complete public verifier above already verified bytes.

    prior_path = published_output("results/prepared_joint_trial.json")
    prior = _read(prior_path)
    for name in ("expected_particle_ids", "mother_particle_count", "launched_particle_count",
                 "solver_epoch_instrument_time_us", "numerics"):
        if prior[name] != preparation[name]:
            raise ValueError("Equivalence reference differs in "+name)
    for name in ("parent_preparation", "field_binding", "trajectory_contract"):
        if prior[name]["sha256"] != preparation[name]["sha256"]:
            raise ValueError("Equivalence reference differs in frozen "+name)
    for name in ("component_particle_state.csv", "source_census.csv", "source_states.lua",
                 "source_projection.lua", "source.fly2", "clock_authority.json"):
        prior_source = Path(prior["measured_source_directory"]) / name
        published_output(prior_source.relative_to(reference_run).as_posix())
        if file_record(prior_source)["sha256"] != file_record(Path(preparation["measured_source_directory"]) / name)["sha256"]:
            raise ValueError("Equivalence reference differs in measured source "+name)
    log = published_output("logs/joint_flight_batch_001.log")
    completions, terminal_ids, clean_exit = [], [], False
    with log.open(encoding="utf-8-sig") as handle:
        for line in handle:
            completion = parse_fly_completed_line(line)
            if completion:
                completions.append(completion.splats)
            if line.startswith("MRTOF_EVENT terminal "):
                terminal_ids.append(int(re.search(r"\bion=(\d+)", line)[1]))
            if line.startswith("IOB_FLIGHT: PASS "):
                clean_exit = True
            if line.lower().startswith("error,"):
                raise ValueError("Equivalence reference batch reported a solver error")
    reference_science=None
    batch_receipt=(reference_run/"results/batches/batch_001/batch_receipt.json").resolve()
    if batch_receipt in outputs:
        batch=_read(batch_receipt)
        if "scientific_event_output" in batch:
            reference_science=dict(batch["scientific_event_output"])
            for key,record_key in (("events_path","events_record"),("trajectory_path","trajectory_record")):
                if not reference_science.get(key): continue
                path=Path(reference_science[key]).resolve()
                if path not in outputs: raise ValueError("Equivalence scientific output is not manifest-bound")
                reference_science[record_key]=dict(outputs[path],path=str(path))
            actual,_,_=read_scientific_events(log,scientific_event_output=reference_science)
            terminal_ids=[int(row["ion"]) for row in actual if row["kind"]=="terminal"]
    if (len(completions) != 1 or not clean_exit or completions[0] != len(terminal_ids)
            or terminal_ids != preparation["expected_particle_ids"][:completions[0]]):
        raise ValueError("Equivalence reference lacks one naturally completed exact source prefix")
    frozen_log = inputs / "trajectory_equivalence_reference.log"
    frozen_manifest = inputs / "trajectory_equivalence_reference_manifest.json"
    freeze_file(log, frozen_log)
    freeze_file(reference_run / "run_manifest.json", frozen_manifest)
    return dict(reference_log=file_record(frozen_log), reference_manifest=file_record(frozen_manifest),
                source_run=str(reference_run.resolve()),scientific_event_output=reference_science,
                original_particle_ids=terminal_ids, completed_particle_count=len(terminal_ids),
                source_and_field_identity_verified=True, reference_status="interrupted")


def compare_trajectory_representation(preparation_path: Path, log_path: Path,
                                       output_path: Path, *, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    """Require exact event/sample text for the frozen prefix, retaining the whole new wave."""
    preparation = _read(preparation_path)
    reference = preparation["trajectory_equivalence_reference"]
    if not reference:
        raise ValueError("An explicit trajectory equivalence reference is required")
    verify_record("trajectory equivalence baseline", reference["reference_log"])
    verify_record("trajectory equivalence baseline manifest", reference["reference_manifest"])
    identifiers = set(reference["original_particle_ids"])
    def selected_lines(path: Path):
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if line.startswith(("MRTOF_EVENT ", "MRTOF_TRAJECTORY ")):
                    match = re.search(r"\bion=(\d+)", line)
                    if match and int(match[1]) in identifiers:
                        yield line.rstrip("\r\n")
    current_science=_read(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else None
    reference_science=reference.get("scientific_event_output")
    def selected_records(path,science):
        events,_,_=read_scientific_events(path,scientific_event_output=science)
        for event in events:
            if int(event["ion"]) in identifiers: yield ("event",event)
        if science is not None:
            columns=("ion","phase","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us")
            if not science.get("trajectory_path"): raise ValueError("equivalence requires explicit complete trajectory output")
            samples=iter_csv_rows(Path(science["trajectory_path"]),columns,exact_header=columns,expected_record=science.get("trajectory_record"))
        else:
            def legacy_samples():
                with path.open(encoding="utf-8-sig") as source:
                    for line in source:
                        if line.startswith("MRTOF_TRAJECTORY "): yield dict(token.split("=",1) for token in line.split()[1:])
            samples=legacy_samples()
        for sample in samples:
            if int(sample["ion"]) in identifiers:
                yield ("trajectory",{key:value if key=="phase" else float(value) for key,value in sample.items()})
    structured = current_science is not None or reference_science is not None
    baseline_rows=selected_records(Path(reference["reference_log"]["path"]),reference_science) if structured else selected_lines(Path(reference["reference_log"]["path"]))
    current_rows=selected_records(log_path,current_science) if structured else selected_lines(log_path)
    mismatches, lines = [], 0
    for index, (baseline, current) in enumerate(zip_longest(baseline_rows,current_rows), 1):
        lines = index
        if baseline != current and len(mismatches) < 10:
            mismatches.append(dict(selected_line=index, reference=baseline, current=current))
    result = dict(schema_version=1, role="mrtof_field_consumer_trajectory_equivalence",
                  status="pass" if not mismatches and lines else "fail", compared_line_count=lines,
                  original_particle_ids=reference["original_particle_ids"],
                  scope="complete_event_and_trajectory_fields_of_manifest_bound_completed_prefix" if structured else "complete_event_and_trajectory_text_of_manifest_bound_completed_prefix",
                  physical_matching_qualified=False, numerical_representation_only=True,
                  reference=reference, new_log=file_record(log_path), first_mismatches=mismatches)
    _write(output_path, result)
    if result["status"] != "pass":
        raise ValueError("Memory consumer trajectory representation differs from its full-field reference")
    return result


def materialize_batch(preparation_path: Path, ordinal_min: int, ordinal_max: int,
                      output_directory: Path) -> dict[str, Any]:
    preparation = _read(preparation_path)
    source = output_directory / "measured_source"
    source_batch = materialize_measured_source_slice(Path(preparation["measured_source_directory"]),
                                                    source, ordinal_min, ordinal_max)
    runtime = Path(preparation["frozen_runtime_directory"])
    for path in runtime.glob("joint.*"):
        if preparation.get("candidate_iob_rebuild") and path.name == "joint.iob":
            continue
        shutil.copyfile(path, output_directory / path.name)
    runtime_projection = bool(preparation.get("native_path_projection"))
    if runtime_projection:
        shutil.copyfile(runtime / "native_run_path.lua", output_directory / "native_run_path.lua")
    original = runtime / "joint.operating_point.lua"
    # Only the observation switch and scheduler-local source projection change.
    interval = preparation["trajectory_recording"].get("interval_us")
    interval_lua = "nil" if interval is None else repr(interval)
    scientific_event_output = dict(events_path=str((output_directory / "events.csv").resolve()),
        trajectory_path=str((output_directory / "trajectory.csv").resolve()),
        csv_writer_path=preparation["scientific_event_writer"]["path"], environment_required=False,
        events_environment_variable="MRTOF_SCIENTIFIC_EVENTS_PATH",trajectory_environment_variable="MRTOF_SCIENTIFIC_TRAJECTORY_PATH")
    sidecar_prefix = (
        "local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\\\])'))\n"
        "local native_path=assert(loadfile(directory..'native_run_path.lua'))()\n"
        if runtime_projection else "")
    original_lua = ("native_path("+_lua(str(original.resolve()))+")" if runtime_projection else
                    json.dumps(project_native_run_path(str(original.resolve())).replace("\\", "/")))
    scientific_projection = (
        "for _,key in ipairs({'events_path','trajectory_path','csv_writer_path'}) do "
        "t.scientific_event_output[key]=native_path(t.scientific_event_output[key]) end\n"
        if runtime_projection else "")
    sidecar = (sidecar_prefix+"local t=assert(loadfile("+original_lua+"))()\n"
               "t.scientific_event_output="+_lua({key: project_native_run_path(value) if not runtime_projection and key in {"events_path", "trajectory_path", "csv_writer_path"} else value for key, value in scientific_event_output.items()})+"\n"
               "t.measured_source_directory="+("native_path("+_lua(str(source.resolve()))+")" if runtime_projection else json.dumps(project_native_run_path(str(source.resolve())).replace("\\", "/")))+"\n"
               "t.trajectory_recording_enabled=true\n"
               "t.trajectory_recording_mode="+json.dumps(preparation["trajectory_recording"]["mode"])+"\n"
               "t.trajectory_recording_interval_us="+interval_lua+"\n"+scientific_projection+"return t\n")
    (output_directory / "joint.operating_point.lua").write_text(sidecar, encoding="utf-8", newline="\n")
    shutil.copyfile(source / "source.fly2", output_directory / "joint.fly2")
    if preparation.get("candidate_iob_rebuild"):
        verify_record("candidate field binding", preparation["field_binding"])
        binding = load_binding(Path(preparation["field_binding"]["path"]))
        layout = collision_workbench_layout(binding)
        build = dict(schema_version=1, role="mrtof_measured_source_workbench_build",
            seed=layout["seed"],
            paths=[item["pa_path"] for item in binding["instances"]],
            origins=[item["origin_mm"] for item in binding["instances"]],
            output=str((output_directory / "joint.iob").resolve()), program=str((output_directory / "joint.lua").resolve()),
            # wb:save writes its seed's same-stem FLY2; the builder must copy
            # this independent measured source back after saving the IOB.
            fly2=str((source / "source.fly2").resolve()),
            operating=str((output_directory / "joint.operating_point.lua").resolve()),
            priority=str((output_directory / "joint.priority.lua").resolve()))
        (output_directory / "joint.workbench_build.lua").write_text("return "+_lua(build)+"\n", encoding="utf-8", newline="\n")
    result = dict(source_batch, iob=str((output_directory / "joint.iob").resolve()), scientific_event_output=scientific_event_output)
    _write(output_directory / "batch_receipt.json", result)
    return result


def analyze_centroid_probe(preparation_path: Path, log_path: Path, output_directory: Path, *, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    """Project genuine N1 events for the existing controller's measured-source branch.

    This does not impersonate an OA trial or evaluate any field potential,
    clean-action target, acceptance tolerance or population qualification.
    """
    import csv
    import math
    from common.contracts.particle_physics import kinetic_energy_ev
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import read_scientific_events
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
        ProjectPhaseSpaceState, observation_from_simion_events, prism_handoff_residuals,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _prism_handoff_event_prefix, _static_field_receipt
    preparation = _read(preparation_path)
    if preparation.get("source_mode") != "centroid_probe" or preparation["expected_particle_ids"] != [1]:
        raise ValueError("Independent constructed centroid probe required")
    for key in ("source_receipt", "reference_materialization", "field_binding", "trajectory_contract", "operating_point"):
        verify_record(key, preparation[key])
    source_receipt_path = Path(preparation["source_receipt"]["path"])
    source_receipt = _read(source_receipt_path)
    if source_receipt.get("role") != "mrtof_measured_exit_centroid_probe_source":
        raise ValueError("Probe source identity differs")
    source_directory = Path(preparation["measured_source_directory"])
    for record in source_receipt["outputs"].values():
        verify_record("probe source output", record)
    row, = load_component_particle_state_csv(source_directory / "component_particle_state.csv").rows
    source = ProjectPhaseSpaceState(tuple(float(row[f"position_{a}_mm"]) for a in "xyz"),
                                   tuple(float(row[f"velocity_{a}_m_s"])/1000 for a in "xyz"))
    science = _read(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else None
    events, finished, _ = read_scientific_events(log_path,scientific_event_output=science)
    terminals = [event for event in events if event["kind"] == "terminal"]
    completions = [completion.splats for completion in finished]
    if len(terminals) != 1 or completions != [1] or any(int(e["ion"]) != 1 for e in events):
        raise ValueError("Probe event population or natural completion does not close")
    reference = _read(Path(preparation["reference_materialization"]["path"]))
    target_keys = ("target_positive_mirror_turn_y_mm", "target_low_field_tangent_ratio_vy_over_vz",
                   "target_nominal_injection_angle_degrees", "p2_low_field_reference_section",
                   "target_drift_period_ratio", "target_slow_turn_y_mm")
    targets = {key: reference[key] for key in target_keys if key in reference}
    stage = dict(status="incomplete", particle_id=1)
    try:
        measured = observation_from_simion_events(_prism_handoff_event_prefix(events), source, ion_number=1)
        residuals = dict(prism_handoff_residuals(measured,
            target_positive_mirror_turn_y_mm=targets["target_positive_mirror_turn_y_mm"],
            target_tangent_ratio_vy_over_vz=targets["target_low_field_tangent_ratio_vy_over_vz"]))
        stage.update(status="observed", residuals=residuals,
            p2_low_field_reference_state=dict(position_mm=measured.p2_shield_low_field_reference.position_mm,
                                            velocity_mm_per_us=measured.p2_shield_low_field_reference.velocity_mm_per_us),
            positive_mirror_turn_state=dict(position_mm=measured.positive_mirror_turn.position_mm,
                                           velocity_mm_per_us=measured.positive_mirror_turn.velocity_mm_per_us))
    except ValueError as error:
        stage["reason"] = str(error)
    binding = load_binding(Path(preparation["field_binding"]["path"]))
    field_receipt=_static_field_receipt(binding,Path(preparation["field_binding"]["path"]))
    values=binding["authority"]["analyzer_electrode_voltages_v"]
    ip_values=sorted([item for item in binding["authority"]["component_voltages_v"]
                      if item["component_namespace"]=="ion_processor"],key=lambda item:item["component_electrode_id"])
    if len(values)!=20 or [item["component_electrode_id"] for item in ip_values] != list(range(1,16)):
        raise ValueError("Live measured field projection requires actual twenty analyzer and fifteen IP voltages")
    field_projection=dict(schema_version=1,role="mrtof_measured_centroid_live_field_projection",
        binding_record=preparation["field_binding"],normalized_binding=binding,
        native_operator=native_response_operator(binding,binding["authority"]),
        analyzer_electrode_voltages_v=values,ion_processor_component_voltages_v15=ip_values,
        scope="manifest_bound_historical_metadata_only__not_authorization_to_Fly_retired_fields")
    materialization = dict(role="mrtof_measured_centroid_probe_materialization", schema_version=1,
        source_projection="measured_exit_centroid", source_cohort=source_receipt["cohort"],
        stripe_biases_v=preparation["stripe_biases_v"], prism_voltages_v=preparation["prism_voltages_v"],
        source_center_state=dict(position_mm=source.position_mm, velocity_mm_per_us=source.velocity_mm_per_us,
                                 instrument_time_us=float(row["instrument_time_us"]),
                                 mass_amu=float(row["mass_amu"]), charge_state=int(row["charge_state"]),
                                 kinetic_energy_eV=float(row["kinetic_energy_eV"])),
        field_binding=field_receipt, source_receipt=preparation["source_receipt"], **targets)
    observation = dict(role="mrtof_measured_centroid_probe_observation", schema_version=1,
        status="probe_observed", prism_voltages_v=preparation["prism_voltages_v"],
        center_particle_prism_handoff_validation=stage, residuals=stage.get("residuals", {}),
        events=events, terminal=terminals[0], physical_potential_evaluated=False,
        full_population_qualified=False)
    output_directory.mkdir(parents=True, exist_ok=False)
    with (output_directory / "probe_event_states.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["event", "instrument_time_us", *[f"{a}_mm" for a in "xyz"],
                  *[f"v{a}_mm_us" for a in "xyz"], "Ex_eV", "Ey_eV", "Ez_eV", "K_eV", "signed_angle_yz_degrees"]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        mass = float(row["mass_amu"])
        for event in events:
            if not all(k in event for k in fields[2:8]):
                continue
            velocity = [float(event[f"v{a}_mm_us"])*1000 for a in "xyz"]
            axes = {f"E{a}_eV": kinetic_energy_ev(mass, *(velocity[i] if i == j else 0 for i in range(3)))
                    for j,a in enumerate("xyz")}
            writer.writerow(dict(event=event["kind"], instrument_time_us=event["t_us"],
                **{key: event[key] for key in fields[2:8]}, **axes, K_eV=kinetic_energy_ev(mass, *velocity),
                signed_angle_yz_degrees=math.degrees(math.atan2(velocity[1],velocity[2]))))
    _write(output_directory / "two_prism_trial_observation.json", observation)
    _write(output_directory / "measured_probe_materialization.json", materialization)
    result = dict(schema_version=1, role="mrtof_measured_exit_centroid_controller_projection",
        observation=observation, materialization=materialization,
        field_authority_projection=field_projection,
        frozen_problem=dict(source_center_projection=dict(role="measured_exit_centroid", cohort=source_receipt["cohort"],
            state=materialization["source_center_state"], mother_source_receipt=source_receipt["inputs"]["mother_source_receipt"]),
            targets=targets, static_field_problem=native_response_operator(binding,binding["authority"])),
        inputs=dict(preparation=file_record(preparation_path), log=file_record(log_path),
                    source_receipt=file_record(source_receipt_path)),
        qualification="constructed_probe_observation_only", physical_potential_evaluated=False,
        outputs={p.stem: file_record(p) for p in sorted(output_directory.iterdir())})
    _write(output_directory / "controller_projection.json", result)
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--prepared-run", type=Path, required=True)
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--run-directory", type=Path, required=True)
    prepare.add_argument("--equivalence-reference-run", type=Path)
    prepare.add_argument("--field-binding", type=Path)
    prepare.add_argument("--source-mode", choices=("measured_population", "centroid_probe"), default="measured_population")
    prepare.add_argument("--continuation-predecessor-manifest", type=Path)
    analyze = sub.add_parser("analyze-probe")
    analyze.add_argument("--preparation", type=Path, required=True)
    analyze.add_argument("--log", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--scientific-event-receipt", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        destination = _read(args.run_directory / "run_config.json")
        if (destination.get("project") != "instrument_assembly"
                or destination.get("mode") != "prepared_joint"
                or destination.get("run_id") != args.run_directory.resolve().name):
            raise ValueError("destination requires instrument_assembly prepared_joint identity matching its directory")
        prepare_trial(args.prepared_run,args.contract,args.run_directory,args.equivalence_reference_run,
                      field_binding_path=args.field_binding,source_mode=args.source_mode,
                      continuation_predecessor_manifest=args.continuation_predecessor_manifest)
    else:
        analyze_centroid_probe(args.preparation,args.log,args.output,scientific_event_receipt=args.scientific_event_receipt)


if __name__ == "__main__":
    main()
