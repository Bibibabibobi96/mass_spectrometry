"""Prepare and bind accelerator/MR interfaces from frozen component providers."""
from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path
from importlib.resources import files
from typing import Any

from msplatform.execution.inputs import freeze_file
from msplatform.execution.retention import verify_record
from msplatform.io.manifest_records import verified_successful_run_reference
from msplatform.results.mr_reference import verified_reference
from msplatform.workflows.mr_design.execution_contract import validate_execution_contract

PROJECT = "multi_reflection_tof"
ION_PROCESSOR = "ion_processor"

CONFIG = Path(str(files(f"msplatform.components.{PROJECT}"))).resolve() / "config"


def _package_source(relative: str) -> Path:
    parts = Path(relative).parts
    if parts[:2] != ("src", "msplatform") or ".." in parts:
        raise ValueError(f"dependency must name an installed package source: {relative}")
    return Path(str(files("msplatform").joinpath(*parts[2:]))).resolve(strict=True)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


verified_preparation_reference = partial(
    verified_successful_run_reference,
    project="instrument_assembly", mode="accelerator_interface_preparation",
)


def preflight_joint_analysis(design_run: Path, source_run: Path, contract_path: Path) -> None:
    """Validate the selected analysis and measured source before a new field solve."""
    from msplatform.contracts.particle_state import load_component_particle_state_csv
    from msplatform.results.component_exit_history import validate_component_exit_binding
    from msplatform.results.historical_joint_source import validate_measured_peak_source_reference

    design_run, source_run, contract_path = map(Path, (design_run, source_run, contract_path))
    reference = verified_preparation_reference(design_run, "inputs/reference_trajectory.json")
    receipt_path = verified_preparation_reference(design_run, "results/ion_processor_exit/component_exit_receipt.json")
    state_path = verified_preparation_reference(design_run, "results/ion_processor_exit/component_particle_state.csv")
    receipt = _read(receipt_path)
    validate_component_exit_binding(receipt)
    if Path(receipt["source_run"]).resolve() != source_run.resolve():
        raise ValueError("Design measured source differs from the selected IP run")
    verify_record("design measured states", receipt["outputs"]["component_states"], base_dir=receipt_path.parent)
    from msplatform.io.manifest_records import record_path
    if record_path(receipt["outputs"]["component_states"], base_dir=receipt_path.parent).resolve() != state_path.resolve():
        raise ValueError("Design measured state identity differs")
    table = load_component_particle_state_csv(state_path)
    if table.report["clock_epoch_ids"] != [receipt["clock_epoch_id"]]:
        raise ValueError("Design measured state clock differs")
    contract = _read(contract_path)
    validate_execution_contract(_read(reference), contract, allow_controller_budget=True)
    peak = contract.get("peak_analysis")
    if peak is not None:
        validate_measured_peak_source_reference(peak, contract_path.parent, receipt,
            {int(row["particle_id"]): row for row in table.rows})


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

def prepare_interface(*, reference_mr_run: Path,
                      run_directory: Path, provider: str | None = None) -> dict[str, Any]:
    """Publish a provider proposal from the frozen MR requirement, without a source or flight."""
    inputs, results = run_directory / "inputs", run_directory / "results"
    if (results / "accelerator_interface_preparation.json").exists():
        raise FileExistsError("interface preparation already exists")
    selected, selection = load_selection(CONFIG / "accelerator_interfaces.json", provider)
    frozen: dict[str, Any] = {}
    sources = {
        "accelerator_selection": CONFIG / "accelerator_interfaces.json",
        "accelerator_dependency": _package_source(selection["dependency_contract"]),
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
    }
    if selected != ION_PROCESSOR:
        sources["accelerator_request"] = _package_source(selection["request_contract"])
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
    receipt = {
        "schema_version": 1, "role": "mrtof_accelerator_interface_preparation",
        "status": "prepared", "selected_provider": selected,
        "solver_executed": False, "joint_simulation_executed": False,
        "reference_requirements": target,
        "inputs": frozen,
        "next_action": "author_original_birth_simulation_recipe",
        "limitations": [
            "Reference energy is an MR matching demand; component poses come only from the explicit frozen assembly recipe.",
            "The demand is a proposal; author physical geometry, drive and original births explicitly in the public Assembly and SimulationRecipe.",
            "No component source, field, flight or time-focus qualification is produced.",
        ],
    }
    _write(results / "accelerator_interface_preparation.json", receipt)
    return receipt

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-mr-run", type=Path, required=True)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--provider", choices=("orthogonal_accelerator", ION_PROCESSOR))
    args = parser.parse_args()
    destination = _read(args.run_directory / "run_config.json")
    if (destination.get("project") != "instrument_assembly"
            or destination.get("mode") != "accelerator_interface_preparation"
            or destination.get("run_id") != args.run_directory.resolve().name):
        raise ValueError("destination requires instrument_assembly accelerator_interface_preparation identity matching its directory")
    result = prepare_interface(reference_mr_run=args.reference_mr_run,
                               run_directory=args.run_directory, provider=args.provider)
    print(f"ACCELERATOR_INTERFACE=PREPARED PROVIDER={result['selected_provider']} SOLVER_EXECUTED=False")


if __name__ == "__main__":
    main()
