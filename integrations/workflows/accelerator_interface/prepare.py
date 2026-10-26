"""Prepare and bind accelerator/MR interfaces from frozen component providers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from typing import Any

from jsonschema import Draft202012Validator

from common.contracts.file_identity import file_sha256
from common.contracts.frozen_inputs import freeze_file
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from common.integration.resolve_assembly import derive_assembly_scope
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import (
    CONFIG, ION_PROCESSOR, REPO, verified_reference, validate_execution_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import (
    _lua, collision_workbench_layout, freeze_field_reference, prepare_interface_field_audit,
    project_provider_voltages, render_measured_operating_point,
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def verified_preparation_reference(run: Path, relative: str, *, manifest: dict[str, Any] | None = None) -> Path:
    """Consume the unique manifest record of a successful assembly preparation."""
    if manifest is None:
        manifest = _read(run / "run_manifest.json")
    if (manifest.get("project") != "instrument_assembly"
            or manifest.get("mode") != "accelerator_interface_preparation"
            or manifest.get("status") != "success"):
        raise ValueError("preparation must be a successful instrument_assembly accelerator_interface_preparation run")
    desired = (run / relative).resolve()
    matches = [record for record in [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
               if record_path(record, base_dir=run) == desired]
    if len(matches) != 1:
        raise ValueError("preparation manifest must bind exactly one record for " + relative)
    verify_record("consumed accelerator preparation", matches[0], base_dir=run)
    return desired


def load_selection(path: Path, provider: str | None) -> tuple[str, dict[str, Any]]:
    """Resolve the explicit provider choice; no fallback for unknown providers."""
    registry = _read(path)
    if (registry.get("schema_version") != 1
            or registry.get("role") != "mrtof_accelerator_interface_selection"
            or registry.get("execution_scope") != "interface_preparation_only"
            or set(registry.get("providers", {})) != {"orthogonal_accelerator", ION_PROCESSOR}):
        raise ValueError("unsupported accelerator selection contract")
    selected = provider if provider is not None else registry["default_provider"]
    if selected not in registry["providers"]:
        raise ValueError(f"unknown accelerator provider: {selected}")
    return selected, registry["providers"][selected]

def _resolve_ip_matching(*, source_run: Path, results: Path, inputs: Path,
                        frozen: dict[str, Any]) -> dict[str, Any]:
    """Consume the declared IP export API from the frozen package namespace."""
    dependency = _read(Path(frozen["accelerator_dependency"]["path"]))
    expected = "projects/dual_pressure_rectilinear_ion_processor/analysis/component_exit.py"
    if (dependency.get("api_version") != 2
            or dependency.get("provider_project_id") != ION_PROCESSOR
            or dependency.get("execution_scope") != "prepare_only_no_solver"
            or dependency.get("provider_callable") != "export_component_exit"
            or dependency.get("provider_module") != expected):
        raise ValueError("unsupported ion processor provider API")
    from projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit import export_component_exit
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection, resolve_matching_request
    request = _read(Path(frozen['accelerator_request']['path']))
    plan = derive_assembly_scope(_read(Path(frozen['composition_plan']['path'])), local_scope=request.get('local_scope'))
    connection = resolve_ip_mr_connection(plan)
    export_component_exit(source_run, results / "ion_processor_exit",
        source_instance_id=connection["upstream"]["instance_id"],
        target_instance_id=connection["downstream"]["instance_id"])
    return resolve_matching_request(
        component_receipt=results / "ion_processor_exit/component_exit_receipt.json",
        trajectory_contract=Path(frozen["reference_trajectory"]["path"]),
        accelerator_provider_receipt=Path(frozen["reference_provider"]["path"]),
        request_path=Path(frozen["accelerator_request"]["path"]),
        plan_path=Path(frozen["composition_plan"]["path"]), composition_plan=plan, connection=connection)

def prepare_joint_flight(*, reference_run: Path,
                        interface_results: Path, frozen_inputs: Path, lua_executable: Path,
                        matching: dict[str, Any]) -> dict[str, Any]:
    """Prepare the candidate assembly and field plan without a flight runtime."""
    from integrations.workflows.accelerator_interface.geometry import prepare_ion_processor_assembly

    output = interface_results / "joint_flight"
    output.mkdir(exist_ok=False)
    references = freeze_field_reference(reference_run, frozen_inputs, compiler_contract=matching["inputs"]["trajectory_contract"])
    resolved = matching["resolved"]
    resolved["field_assembly_reference"] = references
    source_model = matching["source_model_path"]
    source = matching["source_model"]
    references["provider_voltage_projection"] = project_provider_voltages(source, resolved, frozen_inputs, lua_executable)
    assembly_request = frozen_inputs / "matching_assembly_request.json"
    _write(assembly_request, resolved)
    trajectory_path = frozen_inputs / "reference_trajectory.json"
    prepared_geometry = prepare_ion_processor_assembly(
        source, _read(trajectory_path), resolved, connection=matching["connection"],
        input_paths=[source_model, trajectory_path, assembly_request], output_directory=output / "assembly")
    assembly = prepared_geometry["report"]
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
    prepare_handoff(matching, assembly["composition_plan"], interface_results / "mrtof_handoff")
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import validate_configs, derive_native_timing
    seed_config = prepared_geometry["seed_configs"]
    seed_config["source_profile"] = "functional"
    seed_config["native_timing"] = derive_native_timing(seed_config["baseline"])
    validate_configs(seed_config)
    seed_directory = Path(assembly["source_config_paths"]["baseline"]).parent
    _write(seed_directory / "component_matching_derivation.json", {
        "schema_version": 1, "role": "ion_processor_mrtof_matching_derivation",
        "source_model": file_record(source_model), "matching_request": file_record(assembly_request),
        "energy_seed": assembly["energy_seed"], "geometry_changes": assembly["geometry_changes"],
        "qualification": "configuration_validated_only_not_flight_or_energy_match",
    })
    _write(output / "provider_execution_recipe.json", {
        "schema_version": 1, "role": "ion_processor_standalone_candidate_execution_recipe",
        "entrypoint": str(REPO / "projects/dual_pressure_rectilinear_ion_processor/simion/run_functional.ps1"),
        "configuration_directory": str(seed_directory), "source_profile": "functional",
        "requires_new_run_id": True, "reuse_old_native_field": False,
        "configuration_validation": "PASS", "execution_performed": False,
        "execution_scope": "fresh standalone IP Refine and N100 flight before later joint replay",
        "dispatch": "existing_repository_resource_scheduler_automatic_concurrency",
    })
    plan_path = Path(assembly["field_plan_path"])
    receipt = {
        "schema_version": 1, "role": "mrtof_joint_flight_preparation", "status": "prepared_not_flight_validated",
        "accelerator_provider": "dual_pressure_rectilinear_ion_processor", "coupling_mode": "state_handoff",
        "solver_executed": False,
        "assembly": assembly,
        "reference_materialization": references["reference_materialization"], "numerics": references["numerics"],
        "field_plan": file_record(plan_path),
        "required_before_flight": [
            "Run the new standalone IP operating point and verify measured exit energy and time focus.",
            "Replace historical handoff states with the newly measured source; do not rescale the existing CSV.",
            "Build/refine every new parent/local/collision field and seal identities, then bind those assets.",
            "Verify geometry clearances, field support/transition, actual IOB priorities and source initialization.",
        ],
    }
    _write(output / "joint_preparation_receipt.json", receipt)
    return receipt

def _joint_binding_inputs(*, design_run: Path, field_run: Path, source_run: Path) -> dict[str, Any]:
    """Validate the current assembly and sealed physical inputs before any output."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding

    design_manifest = _read(design_run / "run_manifest.json")
    design_path = verified_preparation_reference(design_run, "results/joint_flight/joint_preparation_receipt.json", manifest=design_manifest)
    design = _read(design_path)
    assembly = design["assembly"]
    assembly_path = Path(assembly["assembly_geometry_path"])
    verified_preparation_reference(design_run, assembly_path.relative_to(design_run).as_posix(), manifest=design_manifest)
    request_path = verified_preparation_reference(design_run, "inputs/accelerator_request.json", manifest=design_manifest)
    plan_path = verified_preparation_reference(design_run, "inputs/composition_plan.json", manifest=design_manifest)
    request = _read(request_path)
    Draft202012Validator(_read(CONFIG / "ion_processor_matching_request.schema.json")).validate(request)
    plan = derive_assembly_scope(_read(plan_path), local_scope=request.get("local_scope"))
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection, resolve_ip_mr_transform
    connection = resolve_ip_mr_connection(plan)
    registration = resolve_ip_mr_transform(plan, connection).to_contract()
    if (assembly["composition_plan"] != plan
            or assembly["assembly_coordinate_transform"] != registration):
        raise ValueError("Current design scope or actual registration differs from its frozen parent plan")
    actual_path = source_run / "inputs/resolved_model.json"
    actual = _read(actual_path)
    # Fields bind the built configuration, not a particular release sampler.
    # Actual states and their complete mother cohort come from the IP export.
    for name in ("baseline", "native_operating_point", "numerics", "coordinate_transform"):
        expected_path = Path(assembly["source_config_paths"][name])
        verified_preparation_reference(design_run, expected_path.relative_to(design_run).as_posix(), manifest=design_manifest)
        if actual[name] != _read(expected_path):
            raise ValueError("measured IP run differs from prepared design: " + name)
    expected_source = Path(assembly["source_config_paths"]["source"])
    verified_preparation_reference(design_run, expected_source.relative_to(design_run).as_posix(), manifest=design_manifest)
    if actual["source"]["species"] != _read(expected_source)["species"]:
        raise ValueError("measured IP species differs from prepared design")
    binding_path = verified_reference(field_run, "results/field_binding.json")
    binding = load_binding(binding_path)
    # Instance names select a current consumer, not the physical field operator.
    design_geometry = _read(assembly_path)
    if (binding.get("accelerator_provider") != ION_PROCESSOR
            or {k: v for k, v in binding["geometry"].items() if k != "ion_processor_instance_id"}
            != {k: v for k, v in design_geometry.items() if k != "ion_processor_instance_id"}):
        raise ValueError("Sealed field CSG differs from the current prepared IP replacement geometry")
    if (binding["geometry"]["frame_id"] != registration["to_frame_id"]
            or binding["authority"]["assembly"]["ion_processor_registration"] != registration):
        raise ValueError("Sealed field actual registration differs from the current assembly pose")
    matching_path = Path(assembly["input_identities"][-1]["path"])
    verified_preparation_reference(design_run, matching_path.relative_to(design_run).as_posix(), manifest=design_manifest)
    projection = _read(matching_path)["field_assembly_reference"]["provider_voltage_projection"]
    expected_ip = [dict(component_namespace="ion_processor", component_electrode_id=index + 1, voltage_v=value)
                   for index, value in enumerate(projection["values_v15"])]
    expected_ip.append(dict(component_namespace="detector", component_electrode_id=25, voltage_v=0))
    field_point = binding["authority"]["assembly"]
    if (len(projection["values_v15"]) != 15
            or projection["basis"] != "post_extraction_pulse_held_rf_zero"
            or field_point["post_extraction_state"] != "pulse_held_rf_zero"
            or binding["authority"]["component_voltages_v"] != expected_ip
            or field_point["native_operating_point"] != projection["evaluated_native_operating_point"]
            or actual["native_operating_point"] != projection["evaluated_native_operating_point"]
            or actual["baseline"]["electric"]["lift_v"] != projection["evaluated_baseline_lift_v"]):
        raise ValueError("Sealed field IP voltages or post-extraction workpoint differ from the current design")
    return dict(design=design, design_path=design_path, design_manifest=design_manifest, binding=binding,
                binding_path=binding_path, actual_path=actual_path, connection=connection)


def bind_joint_workbench(*, design_run: Path, field_run: Path, source_run: Path,
                         handoff_receipt: Path, energy_comparison: dict[str, Any],
                         output_directory: Path, execution_contract: dict[str, Any] | None = None,
                         _verified_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind measured states to matching sealed physical fields, without Refine or Fly.

    Readiness means asset/configuration identity only. Energy acceptance, full
    phase-space matching and time focus remain explicitly unqualified.
    """
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_measured_source

    if output_directory.exists():
        raise FileExistsError(output_directory)
    verified = _verified_inputs if _verified_inputs is not None else _joint_binding_inputs(
        design_run=design_run, field_run=field_run, source_run=source_run)
    design, design_path = verified["design"], verified["design_path"]
    design_manifest = verified["design_manifest"]
    binding, binding_path, actual_path = verified["binding"], verified["binding_path"], verified["actual_path"]
    layout = collision_workbench_layout(binding)
    handoff = _read(handoff_receipt)
    if handoff["connection"] != verified["connection"]:
        raise ValueError("Measured source instances differ from the current design connection")
    component_path = Path(handoff["inputs"]["component_receipt"]["path"])
    if Path(_read(component_path)["source_run"]).resolve() != source_run.resolve():
        raise ValueError("new handoff does not originate from selected measured IP run")
    comparison_component = energy_comparison["inputs"]["component_receipt"]
    verify_record("energy comparison measured component", comparison_component)
    if Path(comparison_component["path"]).resolve() != component_path.resolve():
        raise ValueError("energy comparison refers to a different measured source")
    if (energy_comparison.get("role") != "mrtof_measured_exit_energy_comparison"
            or energy_comparison.get("centroid_match_accepted") is not None):
        raise ValueError("binding requires characterized energy without invented acceptance")
    output_directory.mkdir(parents=True)
    source = materialize_measured_source(handoff_receipt, output_directory / "measured_source")
    runtime = output_directory / "runtime"
    runtime.mkdir()
    # Keep pristine Program/FLY2 inputs distinct from IOB output companions:
    # Workbench save may write same-basename companions before the final copy.
    for source_name, target_name in {
        "mrtof_candidate.lua": "mrtof_candidate.lua", "mirror_cycle_counter.lua": "mrtof_candidate.mirror_cycle_counter.lua",
        "scalar_field_adapter.lua": "mrtof_candidate.scalar_field_adapter.lua", "build_native_corridor_iob.lua": "build_workbench.lua",
    }.items():
        freeze_file(REPO / "projects/parallel_mirror_dual_stripe_mr_tof/simion" / source_name, runtime / target_name)
    freeze_file(REPO / "common/simion/voltage_waveforms.lua", runtime / "mrtof_candidate.voltage_waveforms.lua")
    shutil.copyfile(output_directory / "measured_source/source_runtime.lua", runtime / "mrtof_candidate.source_runtime.lua")
    reference_path = design_run / "inputs/reference_operating_point.lua"
    verified_preparation_reference(design_run, reference_path.relative_to(design_run).as_posix(), manifest=design_manifest)
    reference = runtime / "mr_reference.operating_point.lua"
    reference_record = freeze_file(reference_path, reference)
    materialization = design["reference_materialization"]
    verified_preparation_reference(design_run, Path(materialization["path"]).relative_to(design_run).as_posix(), manifest=design_manifest)
    materialization_record = freeze_file(Path(materialization["path"]), output_directory / "reference_materialization.json")
    numerics = dict(design["numerics"])
    if execution_contract is not None:
        if any(numerics[name] != execution_contract["reference_profile"][name]
               for name in ("trajectory_quality", "maximum_step_us")):
            raise ValueError("Prepared JSON numerics differ from its reference trajectory profile")
        numerics.update({name: execution_contract["selected_profile"][name]
                         for name in ("trajectory_quality", "maximum_step_us")})
    def field_projection(level: dict[str, Any]) -> dict[str, Any]:
        grid = level["grid"]
        return dict(mode="native_static_pa", scalar_pa=level["sources"]["scalar_pa"],
                    origin_mm=grid["origin_mm"], pitch_mm=grid["pitch_mm"], dimensions=grid["dimensions"], symmetry="x")
    native = field_projection(binding)
    native.update(accelerator_provider="dual_pressure_rectilinear_ion_processor",
                  assembly_scope="full_c0_ion_processor_replacement",
                  analyzer_voltages_v=binding["authority"]["analyzer_electrode_voltages_v"],
                  collision_pa_path=binding["instances"][1]["pa_path"], refinement_windows=[])
    for level in binding["refinement_windows"]:
        native["refinement_windows"].append(dict(field_projection(level), name=level["name"], active_box_mm=level["active_box_mm"]))
    if "collision_overlay" in layout["priority"]:
        native["collision_overlay"] = layout["priority"]["collision_overlay"]
    (runtime / "joint.operating_point.lua").write_text(render_measured_operating_point(
        reference, output_directory / "measured_source", native, numerics=numerics, field_assets_verified=True,
        source_identity_verified=True), encoding="utf-8", newline="\n")
    priority = layout["priority"]
    (runtime / "joint.priority.lua").write_text("return " + _lua(priority) + "\n", encoding="utf-8", newline="\n")
    # SIMION must load each seed slot under a distinct filename before the
    # builder replaces its PA. Share the one frozen payload through private
    # run-local hard links, leaving the dependency snapshot unchanged.
    seed = runtime / Path(layout["seed"]).name
    shutil.copyfile(layout["seed"], seed)
    placeholder = REPO / "common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0"
    for index in range(1, len(binding["instances"]) + 1):
        os.link(placeholder, runtime / f"iob_seed_placeholder_{index:02d}.pa0")
    build = dict(schema_version=1, role="mrtof_measured_source_workbench_build",
                 seed=str(seed),
                 paths=[item["pa_path"] for item in binding["instances"]],
                 origins=[item["origin_mm"] for item in binding["instances"]],
                 output=str(runtime / "joint.iob"), program=str(runtime / "mrtof_candidate.lua"),
                 fly2=str(output_directory / "measured_source/source.fly2"), operating=str(runtime / "joint.operating_point.lua"),
                 priority=str(runtime / "joint.priority.lua"))
    (runtime / "workbench_build.lua").write_text("return " + _lua(build) + "\n", encoding="utf-8", newline="\n")
    _write(output_directory / "energy_comparison.json", energy_comparison)
    freeze_file(binding_path, output_directory / "static_field_binding.json")
    interface_audit = prepare_interface_field_audit(source_run=source_run, handoff=handoff,
        source_directory=output_directory / "measured_source", binding=binding, native=native,
        runtime=runtime, output=output_directory)
    receipt = dict(schema_version=1, role="mrtof_joint_workbench_binding", status="assets_bound_iob_pending",
                   accelerator_provider="dual_pressure_rectilinear_ion_processor",
                   field_assembly_verified=True, measured_source_matches_workpoint=True,
                   source_workpoint_check="prepared_and_measured_provider_configuration_identity",
                   energy_target_acceptance="not_declared", six_dimensional_match_qualified=False,
                   time_focus_qualified=False, joint_simulation_executed=False, gui_executed=False,
                   field_run=str(field_run.resolve()), source_run=str(source_run.resolve()),
                   measured_source=source, workbench_build_contract=build,
                   guard_paths=sorted({item["pa_path"] for item in binding["instances"]}
                       | {level["sources"]["scalar_pa"] for level in [binding,*binding["refinement_windows"]]}),
                   interface_field_audit=interface_audit,
                   execution_contract_provenance=execution_contract,
                   numerics=numerics, reference_materialization=materialization_record,
                   inputs={"design_receipt": file_record(design_path), "field_binding": file_record(binding_path),
                           "source_resolved_model": file_record(actual_path), "handoff_receipt": file_record(handoff_receipt),
                           "reference_operating_point": reference_record},
                   builder_arguments=["--measured-source", str(runtime / "workbench_build.lua")])
    _write(output_directory / "joint_binding_receipt.json", receipt)
    return receipt

def prepare_interface(*, source_run: Path | None, reference_mr_run: Path,
                      run_directory: Path, provider: str | None = None,
                      lua_executable: Path | None = None,
                      matching_request_path: Path | None = None) -> dict[str, Any]:
    """Prepare OA requirements or measured IP states; never propagate particles."""
    inputs, results = run_directory / "inputs", run_directory / "results"
    if (results / "accelerator_interface_preparation.json").exists():
        raise FileExistsError("interface preparation already exists")
    selected, selection = load_selection(CONFIG / "accelerator_interfaces.json", provider)
    if matching_request_path is not None and selected != ION_PROCESSOR:
        raise ValueError("explicit IP matching request requires the ion processor provider")
    if selected == ION_PROCESSOR and matching_request_path is None:
        raise ValueError("IP preparation requires an explicit MatchingRequestPath")
    if selected == ION_PROCESSOR and source_run is None:
        raise ValueError("ion processor selection requires its explicit source run")
    if selected == ION_PROCESSOR and lua_executable is None:
        raise ValueError("ion processor preparation requires an explicit plain Lua interpreter")
    frozen: dict[str, Any] = {}
    sources = {
        "accelerator_selection": CONFIG / "accelerator_interfaces.json",
        "accelerator_dependency": REPO / selection["dependency_contract"],
        "accelerator_request": (matching_request_path.resolve() if matching_request_path is not None
                                else REPO / selection["request_contract"]),
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
    }
    for name, source in sources.items():
        frozen[name] = freeze_file(source, inputs / (name + source.suffix))
    if selected == ION_PROCESSOR:
        request = _read(Path(frozen["accelerator_request"]["path"]))
        plan_path = Path(request["composition_plan"]["path"])
        if not plan_path.is_absolute():
            plan_path = matching_request_path.resolve().parent / plan_path
        frozen["composition_plan"] = freeze_file(plan_path, inputs / "composition_plan.json")
    trajectory = _read(Path(frozen["reference_trajectory"]["path"]))
    old_provider = _read(Path(frozen["reference_provider"]["path"]))
    target = {
        "axial_energy_per_charge_v": old_provider["mrtof_projection"]["target_axial_energy_per_charge_v"],
        "energy_definition": "exit_axial_kinetic_energy_per_charge",
        "project_y_mm": trajectory["accelerator"]["focus_y_anchor"]["project_y_mm"],
        "frame_id": trajectory["coordinate_system"]["frame_id"],
        "source": "manifest_bound_frozen_reference_not_live_candidate_defaults",
    }
    handoff = None
    joint = None
    if selected == ION_PROCESSOR:
        matching = _resolve_ip_matching(source_run=source_run, results=results, inputs=inputs, frozen=frozen)
        joint = prepare_joint_flight(reference_run=reference_mr_run,
                                     interface_results=results, frozen_inputs=inputs, lua_executable=lua_executable,
                                     matching=matching)
        handoff = _read(results / "mrtof_handoff/handoff_receipt.json")
        bound_paths = {Path(record["path"]).resolve() for record in frozen.values()}
        for path in sorted(inputs.iterdir()):
            if path.is_file() and path.name != "code_inventory.json" and path.resolve() not in bound_paths:
                frozen["joint_" + path.stem] = {**file_record(path.resolve()), "source_path": str(path.resolve())}
    receipt = {
        "schema_version": 1, "role": "mrtof_accelerator_interface_preparation",
        "status": "prepared", "selected_provider": selected,
        "solver_executed": False, "joint_simulation_executed": False,
        "reference_requirements": target,
        "inputs": frozen, "handoff": handoff, "joint_preparation": joint,
        "limitations": [
            "Reference energy is an MR matching demand; component poses come only from the explicit frozen assembly recipe.",
            "IP voltage, geometry and timing may change to meet the demand; existing measured baseline is not rescaled or overwritten.",
            "Prepared IP runtime requires new verified fields and a newly measured matching source; no joint field or time-focus qualification is claimed.",
            "The original OA path remains available and its default is unchanged.",
        ],
    }
    _write(results / "accelerator_interface_preparation.json", receipt)
    return receipt

def finalize_interface(*, source_run: Path, reference_mr_run: Path, design_run: Path,
                       field_run: Path, run_directory: Path, contract_path: Path | None = None) -> dict[str, Any]:
    """Bind one measured replacement design; the public launcher builds IOB only."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import compare_measured_exit_energy

    inputs, results = run_directory / "inputs", run_directory / "results"
    design_manifest = _read(design_run / "run_manifest.json")
    design_receipt = _read(verified_preparation_reference(design_run, "results/accelerator_interface_preparation.json", manifest=design_manifest))
    if (design_receipt.get("selected_provider") != ION_PROCESSOR
            or design_receipt["inputs"]["reference_manifest"]["sha256"].lower()
            != file_sha256(reference_mr_run / "run_manifest.json").lower()):
        raise ValueError("finalization reference operating point differs from prepared design")
    # Validate before freezing/exporting any new execution inputs. Reuse the
    # same verified field observation in this finalization's binding step.
    verified = _joint_binding_inputs(design_run=design_run, field_run=field_run, source_run=source_run)
    selected = ION_PROCESSOR
    frozen = {}
    sources = {
        "accelerator_selection": verified_preparation_reference(design_run, "inputs/accelerator_selection.json", manifest=design_manifest),
        "accelerator_dependency": verified_preparation_reference(design_run, "inputs/accelerator_dependency.json", manifest=design_manifest),
        "accelerator_request": verified_preparation_reference(design_run, "inputs/accelerator_request.json", manifest=design_manifest),
        "composition_plan": verified_preparation_reference(design_run, "inputs/composition_plan.json", manifest=design_manifest),
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
        "design_manifest": design_run / "run_manifest.json", "field_manifest": field_run / "run_manifest.json",
    }
    for name, path in sources.items():
        frozen[name] = freeze_file(path, inputs / (name + path.suffix))
    execution = None
    if contract_path is not None:
        execution = validate_execution_contract(_read(Path(frozen["reference_trajectory"]["path"])), _read(contract_path),
                                                allow_controller_budget=True)
        frozen["historical_reference_trajectory"] = frozen["reference_trajectory"]
        frozen["reference_trajectory"] = freeze_file(contract_path, inputs / "execution_trajectory.json")
        if execution["native_refine_change"] is not None:
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import native_numerics_match
            field_binding = verified["binding"]
            if not native_numerics_match(field_binding, Path(frozen["reference_trajectory"]["path"])):
                raise ValueError("new native field Refine numerics differ from the selected execution contract")
    matching = _resolve_ip_matching(source_run=source_run, results=results, inputs=inputs, frozen=frozen)
    design_plan = design_receipt["joint_preparation"]["assembly"]["composition_plan"]
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import prepare_handoff
    prepare_handoff(matching, design_plan, results / "mrtof_handoff")
    energy = compare_measured_exit_energy(results / "ion_processor_exit/component_exit_receipt.json", reference_mr_run)
    binding = bind_joint_workbench(
        design_run=design_run, field_run=field_run, source_run=source_run,
        handoff_receipt=results / "mrtof_handoff/handoff_receipt.json", energy_comparison=energy,
        output_directory=results / "joint_workbench", execution_contract=execution, _verified_inputs=verified)
    receipt = dict(schema_version=1, role="mrtof_accelerator_interface_preparation", status="bound_iob_pending",
                   selected_provider=selected, preparation_stage="finalize_joint_workbench",
                   solver_executed=False, joint_simulation_executed=False, inputs=frozen,
                   joint_workbench_binding=binding,
                   execution_contract_provenance=execution,
                   limitations=["Energy comparison has no declared acceptance tolerance.",
                                "Six-dimensional source matching and time focus are unqualified.",
                                "Workbench construction does not propagate particles or qualify joint performance."])
    _write(results / "accelerator_interface_preparation.json", receipt)
    return receipt

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--reference-mr-run", type=Path, required=True)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--provider", choices=("orthogonal_accelerator", ION_PROCESSOR))
    parser.add_argument("--lua-executable", type=Path)
    parser.add_argument("--finalize-joint-workbench", action="store_true")
    parser.add_argument("--prepared-interface-run", type=Path)
    parser.add_argument("--joint-field-run", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--matching-request", type=Path)
    args = parser.parse_args()
    destination = _read(args.run_directory / "run_config.json")
    if (destination.get("project") != "instrument_assembly"
            or destination.get("mode") != "accelerator_interface_preparation"
            or destination.get("run_id") != args.run_directory.resolve().name):
        raise ValueError("destination requires instrument_assembly accelerator_interface_preparation identity matching its directory")
    if args.finalize_joint_workbench:
        if args.matching_request is not None:
            parser.error("finalization consumes the matching request frozen by its design run")
        if args.provider != ION_PROCESSOR or not all((args.source_run, args.prepared_interface_run, args.joint_field_run)):
            parser.error("finalization requires explicit IP provider, new source, design and field run")
        result = finalize_interface(source_run=args.source_run, reference_mr_run=args.reference_mr_run,
                                    design_run=args.prepared_interface_run, field_run=args.joint_field_run,
                                    run_directory=args.run_directory, contract_path=args.contract)
    else:
        if args.prepared_interface_run or args.joint_field_run or args.contract:
            parser.error("design/field runs require --finalize-joint-workbench")
        result = prepare_interface(source_run=args.source_run, reference_mr_run=args.reference_mr_run,
                               run_directory=args.run_directory, provider=args.provider,
                               lua_executable=args.lua_executable,
                               matching_request_path=args.matching_request)
    print(f"ACCELERATOR_INTERFACE=PREPARED PROVIDER={result['selected_provider']} SOLVER_EXECUTED=False")


if __name__ == "__main__":
    main()
