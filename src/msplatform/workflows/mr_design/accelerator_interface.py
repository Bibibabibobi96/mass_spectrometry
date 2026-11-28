"""Publish prepare-only accelerator/MR proposals through an explicit Store."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import partial
from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from msplatform.assembly.accelerator_interface import (
    CONFIG, ION_PROCESSOR, MODE, PROJECT, build_interface_proposal, load_selection,
)
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.owner import run_managed_stage, standalone_native_store
from msplatform.execution.retention import verify_record
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, verified_successful_run_reference
from msplatform.results.mr_reference import verified_reference
from msplatform.workflows.mr_design.execution_contract import validate_execution_contract


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _package_source(relative: str) -> Path:
    parts = Path(relative).parts
    if parts[:2] != ("src", "msplatform") or ".." in parts:
        raise ValueError(f"dependency must name an installed package source: {relative}")
    return Path(str(files("msplatform").joinpath(*parts[2:]))).resolve(strict=True)


def _source_paths(reference_mr_run: Path, provider: str | None) -> tuple[str, dict[str, Path]]:
    selected, selection = load_selection(CONFIG / "accelerator_interfaces.json", provider)
    sources = {
        "accelerator_selection": CONFIG / "accelerator_interfaces.json",
        "accelerator_dependency": _package_source(selection["dependency_contract"]),
        "reference_manifest": reference_mr_run / "run_manifest.json",
        "reference_trajectory": verified_reference(reference_mr_run, "simion/trajectory_contract.json"),
        "reference_provider": verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json"),
    }
    if selected != ION_PROCESSOR:
        sources["accelerator_request"] = _package_source(selection["request_contract"])
    return selected, sources


verified_preparation_reference = partial(
    verified_successful_run_reference,
    project="instrument_assembly", mode=MODE,
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


@contextmanager
def _guard_sources(reference_mr_run: Path, provider: str | None) -> Iterator[tuple[str, dict[str, Path], dict[str, dict[str, Any]]]]:
    reference_mr_run = reference_mr_run.resolve(strict=True)
    manifest_path = reference_mr_run / "run_manifest.json"
    manifest_record = file_record(manifest_path, "required_evidence")
    manifest = _read(manifest_path)
    if manifest.get("project") != PROJECT or manifest.get("status") != "success" or not isinstance(manifest.get("mode"), str):
        raise ValueError("reference must be a successful, explicitly identified MR run")
    with ExitStack() as stack:
        stack.enter_context(guard_historical_run(
            manifest_record, expected_project=PROJECT, expected_mode=manifest["mode"]))
        selected, sources = _source_paths(reference_mr_run, provider)
        records = {name: file_record(path, "required_evidence") for name, path in sources.items()}
        for name, path in sources.items():
            if name != "reference_manifest":
                record = records[name]
                stack.enter_context(guarded_file_identity(path, expected_bytes=record["bytes"],
                    expected_sha256=record["sha256"]))
        yield selected, sources, records
        for name, record in records.items():
            verify_record("original accelerator interface source " + name, record)


def _prepare_action(session, *, sources: Mapping[str, Path], selected: str) -> dict[str, Any]:
    output = session.declare_file(
        session.result_dir / "accelerator_interface_preparation.json", "required_evidence")
    if output.exists():
        raise FileExistsError("interface preparation already exists")
    frozen = {}
    for name, source in sources.items():
        destination = session.declare_file(session.input_dir / (name + source.suffix), "required_evidence")
        record = freeze_file(source, destination, retention_role="required_evidence")
        session.add_input(name, record)
        frozen[name] = record
    receipt = build_interface_proposal(frozen=frozen, selected=selected)
    _write(output, receipt)
    return dict(status="success", summary=dict(
        role="mrtof_accelerator_interface_run_summary",
        qualification="interface_preparation_only_not_joint_simulation", preparation=receipt),
        output_paths=[output], required_output_paths=[output],
        retention_preserve_paths=[], manifest_extra_fields={})


def prepare_interface(context: ExecutionContext, *, reference_mr_run: Path,
                      artifact_store: Any, run_id: str, committed_new_bytes: int,
                      retention: Mapping[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Publish an explicit energy/frame proposal through the supplied Store.

    The MR reference and selected package inputs are authenticated and held
    read-only before a run is admitted. No solver, source sampling, continuous
    flight, legacy capacity owner, or implicit Store selection is performed.
    """
    if not isinstance(context, ExecutionContext) or artifact_store is None:
        raise TypeError("prepare_interface requires an explicit ExecutionContext and ArtifactStore")
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError("committed_new_bytes must be a positive integer")
    reference_mr_run = Path(reference_mr_run)
    with _guard_sources(reference_mr_run, provider) as (selected, sources, records):
        authorities = [records[name] for name in sources]
        with standalone_native_store(artifact_store, task_key="accelerator-interface:" + run_id,
                                     budget=committed_new_bytes) as scope:
            result = run_managed_stage(context, artifact_store=artifact_store,
                descriptor=dict(project="instrument_assembly", mode=MODE, software=["Python 3.11"]),
                run_id=run_id, payload=dict(accelerator_provider=selected,
                    reference_mr_run=str(reference_mr_run.resolve()), solver_execution="none",
                    qualification="interface_preparation_only_not_joint_simulation"),
                committed_new_bytes=committed_new_bytes, commitment_inputs=authorities,
                retention=dict(retention), expected_operation_ids=[], operation_dependencies={},
                action=partial(_prepare_action, sources=sources, selected=selected),
                action_record=file_record(Path(__file__).resolve(), "required_evidence"),
                completion_api=no_particle_batch_completion_api)
            if result.get("status") != "success":
                raise RuntimeError("accelerator interface preparation failed: " + str(result.get("status")))
        artifact_store.inspect_run(scope["parent_run_id"])
        with guard_historical_run(result["manifest"], expected_project="instrument_assembly",
                                  expected_mode=MODE) as published:
            receipt_record = published.output("results/accelerator_interface_preparation.json")
            receipt = _read(Path(receipt_record["path"]))
            if (receipt.get("selected_provider") != selected
                    or receipt.get("solver_executed") is not False
                    or receipt.get("joint_simulation_executed") is not False):
                raise ValueError("published accelerator interface proposal differs from its request")
        return dict(result, store_run_id=scope["parent_run_id"],
                    store_run_path=str(scope["published_path"]), preparation=receipt)
