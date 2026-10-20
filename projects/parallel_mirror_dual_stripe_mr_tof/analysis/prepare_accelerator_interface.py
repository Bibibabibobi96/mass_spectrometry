"""Freeze a selected accelerator interface for review without executing a solver."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record

PROJECT = "parallel_mirror_dual_stripe_mr_tof"
ION_PROCESSOR = "dual_pressure_rectilinear_ion_processor"
REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "projects" / PROJECT / "config"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def freeze_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one explicitly selected file; freeze raw input identity before use."""
    if destination.exists():
        raise FileExistsError(destination)
    before = file_record(source.resolve())
    shutil.copyfile(source, destination)
    verify_record("frozen accelerator interface input", {**before, "path": str(destination)})
    verify_record("unchanged accelerator interface source", before)
    return {**file_record(destination.resolve()), "source_path": str(source.resolve())}


def verified_reference(run: Path, relative: str, *, required_status: str = "success") -> Path:
    """Verify the exact consumed record, without loading historical field payloads."""
    manifest = _read(run / "run_manifest.json")
    if (required_status not in {"success", "interrupted"}
            or manifest.get("project") != PROJECT or manifest.get("status") != required_status):
        raise ValueError(f"reference must be an MR run with status {required_status}")
    verify_record("reference run config", manifest["run_config"], base_dir=run)
    config = _read(record_path(manifest["run_config"], base_dir=run))
    desired = (run / relative).resolve()
    # Preparation runs freeze file records in their manifest-bound run config.
    # A normalized dependency projection can also have a path; it describes the
    # dependency and is not a second file record with byte/hash authority.
    config_records = [record for record in config.get("inputs", {}).values()
                      if isinstance(record, dict) and {"path", "bytes", "sha256"} <= record.keys()]
    records = [*manifest.get("inputs", {}).values(), *config_records, *manifest["outputs"]]
    matches = [r for r in records if record_path(r, base_dir=run) == desired]
    if not matches:
        raise ValueError(f"reference manifest does not bind {relative}")
    for record in matches:
        verify_record("consumed MR reference", record, base_dir=run)
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


def _prepare_ip_handoff(*, source_run: Path, results: Path, inputs: Path,
                        frozen: dict[str, Any]) -> dict[str, Any]:
    """Freeze the declared producer and materialize one measured state handoff."""
    selected = ION_PROCESSOR
    dependency = _read(Path(frozen["accelerator_dependency"]["path"]))
    if (dependency.get("api_version") != 1 or dependency.get("provider_project_id") != selected
            or dependency.get("execution_scope") != "prepare_only_no_solver"
            or dependency.get("provider_callable") != "export_component_exit"):
        raise ValueError("unsupported ion processor provider API")
    provider_source = (REPO / dependency["provider_module"]).resolve()
    expected = REPO / "projects" / selected / "analysis" / "component_exit.py"
    if provider_source != expected.resolve():
        raise ValueError("provider module is outside the declared component boundary")
    for name, source in {
        "provider_implementation": provider_source,
        "component_state_schema": REPO / dependency["state_schema"],
        "matching_request_schema": CONFIG / "ion_processor_matching_request.schema.json",
    }.items():
        frozen[name] = freeze_file(source, inputs / (name + source.suffix))
    for index, relative in enumerate(dependency["provider_support_modules"]):
        support = (REPO / relative).resolve()
        if support.parent != expected.parent.resolve() or support.suffix != ".py":
            raise ValueError("provider support module is outside its declared boundary")
        frozen[f"provider_support_{index}"] = freeze_file(support, inputs / f"provider_support_{index}.py")
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ion_processor_handoff
    frozen["receiver_implementation"] = freeze_file(
        Path(ion_processor_handoff.__file__), inputs / "receiver_implementation.py")
    name = "_frozen_ion_processor_provider_" + file_sha256(provider_source).lower()
    spec = importlib.util.spec_from_file_location(name, frozen["provider_implementation"]["path"])
    if spec is None or spec.loader is None:
        raise ValueError("cannot load frozen provider implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.export_component_exit(source_run, results / "ion_processor_exit")
    handoff = ion_processor_handoff.prepare_handoff(
        component_receipt=results / "ion_processor_exit" / "component_exit_receipt.json",
        trajectory_contract=Path(frozen["reference_trajectory"]["path"]),
        accelerator_provider_receipt=Path(frozen["reference_provider"]["path"]),
        request_path=Path(frozen["accelerator_request"]["path"]),
        output_directory=results / "mrtof_handoff")
    return handoff


def _verify_frozen_inputs(frozen: dict[str, Any]) -> None:
    for record in frozen.values():
        verify_record("unchanged frozen dependency", record)
        verify_record("unchanged source dependency", {**record, "path": record["source_path"]})


def validate_execution_contract(reference: dict[str, Any], contract: dict[str, Any], *,
                                allow_controller_budget: bool = False) -> dict[str, Any]:
    """Allow observation changes and one selected integration bound, never physics."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import resolve_trajectory_profile

    expected = json.loads(json.dumps(reference))
    scientific = json.loads(json.dumps(contract))
    expected["simion"].pop("trajectory_recording", None)
    scientific["simion"].pop("trajectory_recording", None)
    previous = resolve_trajectory_profile(expected)
    current = resolve_trajectory_profile(scientific)
    profile_id = previous["profile_id"]
    if current["profile_id"] != profile_id:
        raise ValueError("Prepared joint trial must retain its selected trajectory profile")
    if current["trajectory_quality"] != previous["trajectory_quality"]:
        raise ValueError("Prepared joint timestep comparison must retain trajectory quality")
    selected = scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"]
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        raise ValueError("Selected maximum_step_us must be a numeric integration bound")
    change = None
    if current["maximum_step_us"] != previous["maximum_step_us"]:
        change = dict(change_kind="selected_trajectory_maximum_step_only", profile_id=profile_id,
                      maximum_step_us=dict(previous=previous["maximum_step_us"], current=current["maximum_step_us"]))
    scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"] = (
        expected["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"])
    budget = None
    if scientific != expected:
        if not allow_controller_budget:
            raise ValueError("Finalization contract changes more than the selected trajectory step")
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import assert_bounded_controller_resume
        budget = assert_bounded_controller_resume(expected, scientific, None, budget_only=True)
    return dict(reference_profile=previous, selected_profile=current, numerical_change=change,
                execution_budget_change=budget)


def prepare_interface(*, source_run: Path | None, reference_mr_run: Path,
                      run_directory: Path, provider: str | None = None,
                      lua_executable: Path | None = None) -> dict[str, Any]:
    """Prepare OA requirements or measured IP states; never propagate particles."""
    inputs, results = run_directory / "inputs", run_directory / "results"
    if (results / "accelerator_interface_preparation.json").exists():
        raise FileExistsError("interface preparation already exists")
    selected, selection = load_selection(CONFIG / "accelerator_interfaces.json", provider)
    if selected == ION_PROCESSOR and source_run is None:
        raise ValueError("ion processor selection requires its explicit source run")
    if selected == ION_PROCESSOR and lua_executable is None:
        raise ValueError("ion processor preparation requires an explicit plain Lua interpreter")
    frozen: dict[str, Any] = {}
    sources = {
        "accelerator_selection": CONFIG / "accelerator_interfaces.json",
        "accelerator_dependency": REPO / selection["dependency_contract"],
        "accelerator_request": REPO / selection["request_contract"],
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
        "preparation_implementation": Path(__file__),
    }
    for name, source in sources.items():
        frozen[name] = freeze_file(source, inputs / (name + source.suffix))
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
        handoff = _prepare_ip_handoff(source_run=source_run, results=results, inputs=inputs, frozen=frozen)
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import prepare_joint_flight
        dependency = _read(Path(frozen["accelerator_dependency"]["path"]))
        for index, relative in enumerate(dependency["consumer_preparation_modules"]):
            implementation = (REPO / relative).resolve()
            if implementation.parent != Path(__file__).resolve().parent or implementation.suffix != ".py":
                raise ValueError("consumer implementation is outside its declared project boundary")
            frozen[f"joint_implementation_{index}"] = freeze_file(implementation, inputs / f"joint_implementation_{index}.py")
        joint = prepare_joint_flight(source_run=source_run, reference_run=reference_mr_run,
                                     interface_results=results, frozen_inputs=inputs, lua_executable=lua_executable)
        bound_paths = {Path(record["path"]).resolve() for record in frozen.values()}
        for path in sorted(inputs.iterdir()):
            if path.is_file() and path.resolve() not in bound_paths:
                frozen["joint_" + path.stem] = {**file_record(path.resolve()), "source_path": str(path.resolve())}
        _verify_frozen_inputs(frozen)
    receipt = {
        "schema_version": 1, "role": "mrtof_accelerator_interface_preparation",
        "status": "prepared", "selected_provider": selected,
        "solver_executed": False, "joint_simulation_executed": False,
        "joint_ip_adapter_ready": joint is not None, "reference_requirements": target,
        "inputs": frozen, "handoff": handoff, "joint_preparation": joint,
        "limitations": [
            "Reference energy and pose are initial MR matching demands; a different MR operating point requires new explicit input.",
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
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import bind_joint_workbench

    inputs, results = run_directory / "inputs", run_directory / "results"
    design_receipt = _read(verified_reference(design_run, "results/accelerator_interface_preparation.json"))
    if (design_receipt.get("selected_provider") != ION_PROCESSOR
            or design_receipt["inputs"]["reference_manifest"]["sha256"].lower()
            != file_sha256(reference_mr_run / "run_manifest.json").lower()):
        raise ValueError("finalization reference operating point differs from prepared design")
    selected, selection = load_selection(CONFIG / "accelerator_interfaces.json", ION_PROCESSOR)
    frozen = {}
    sources = {
        "accelerator_selection": CONFIG / "accelerator_interfaces.json",
        "accelerator_dependency": REPO / selection["dependency_contract"],
        "accelerator_request": REPO / selection["request_contract"],
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
        "design_manifest": design_run / "run_manifest.json", "field_manifest": field_run / "run_manifest.json",
        "preparation_implementation": Path(__file__),
        "binding_implementation": Path(__file__).with_name("joint_flight_preparation.py"),
        "field_binding_implementation": Path(__file__).with_name("static_field_binding.py"),
    }
    for name, path in sources.items():
        frozen[name] = freeze_file(path, inputs / (name + path.suffix))
    execution = None
    if contract_path is not None:
        execution = validate_execution_contract(_read(Path(frozen["reference_trajectory"]["path"])), _read(contract_path),
                                                allow_controller_budget=True)
        frozen["historical_reference_trajectory"] = frozen["reference_trajectory"]
        frozen["reference_trajectory"] = freeze_file(contract_path, inputs / "execution_trajectory.json")
    _prepare_ip_handoff(source_run=source_run, results=results, inputs=inputs, frozen=frozen)
    energy = compare_measured_exit_energy(results / "ion_processor_exit/component_exit_receipt.json", reference_mr_run)
    binding = bind_joint_workbench(
        design_run=design_run, field_run=field_run, source_run=source_run,
        handoff_receipt=results / "mrtof_handoff/handoff_receipt.json", energy_comparison=energy,
        output_directory=results / "joint_workbench", execution_contract=execution)
    _verify_frozen_inputs(frozen)
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
    args = parser.parse_args()
    if args.finalize_joint_workbench:
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
                               lua_executable=args.lua_executable)
    print(f"ACCELERATOR_INTERFACE=PREPARED PROVIDER={result['selected_provider']} SOLVER_EXECUTED=False")


if __name__ == "__main__":
    main()
