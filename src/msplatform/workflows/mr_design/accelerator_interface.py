"""Publish prepare-only accelerator/MR proposals through an explicit Store."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from functools import partial
from importlib.resources import files
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterator, Mapping

from msplatform.analysis.mr_observations import parse_events
from msplatform.analysis.particle_census import partition_cohort
from msplatform.assembly.ip_mr_connection import validate_component_exit_binding
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.particle_state import load_component_particle_state_csv
from msplatform.assembly.accelerator_interface import (
    CONFIG, ION_PROCESSOR, MODE, PROJECT, build_interface_proposal, load_selection,
)
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.owner import run_managed_stage, standalone_native_store
from msplatform.execution.retention import verify_record
from msplatform.io.file_identity import file_sha256, guarded_file_identity
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


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "bytes": path.stat().st_size}


def _bound_file(identity: dict[str, Any], relative_to: Path) -> Path:
    path = Path(identity["path"])
    if not path.is_absolute():
        path = relative_to / path
    if file_sha256(path).lower() != identity["sha256"].lower():
        raise ValueError(f"Bound source SHA-256 differs: {path}")
    if path.stat().st_size != identity["bytes"]:
        raise ValueError(f"Bound source byte count differs: {path}")
    return path


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean": statistics.fmean(values),
            "population_sigma": statistics.pstdev(values),
            "minimum": min(values), "maximum": max(values)}


def _exit_distributions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    energy, velocity = {}, {}
    for axis in "xyz":
        velocity[axis] = _distribution([row[f"velocity_{axis}_m_s"] for row in rows])
        values = [kinetic_energy_ev(row["mass_amu"], *(
            row[f"velocity_{other}_m_s"] if other == axis else 0.0 for other in "xyz"
        )) / abs(row["charge_state"]) for row in rows]
        energy[axis] = _distribution(values)
    total = [kinetic_energy_ev(row["mass_amu"], *(
        row[f"velocity_{axis}_m_s"] for axis in "xyz"
    )) / abs(row["charge_state"]) for row in rows]
    return {"statistic_basis": "unweighted_recorded_exit_particles_no_recentring_or_filtering",
            "energy_unit": "eV_per_abs_charge_state", "velocity_unit": "m_s",
            "directional_energy": energy, "total_energy": _distribution(total), "velocity": velocity}


def _reference_exit(reference_mr_run: Path) -> tuple[float, dict[str, Any], dict[str, Any]]:
    """Read the exact manifest projection without consuming PA payloads."""
    provider_path = verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json")
    source_path = verified_reference(reference_mr_run, "simion/bunch_source_receipt.json")
    log_path = verified_reference(reference_mr_run, "logs/native_two_prism_flight.log")
    provider, source = _read(provider_path), _read(source_path)
    state_path = _bound_file(source["state_table"], source_path.parent)
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    by_id = {int(row["particle_id"]): row for row in source_rows}
    expected = set(source["expected_particle_ids"])
    if len(by_id) != len(source_rows) or set(by_id) != expected or len(expected) != source["particle_count"]:
        raise ValueError("Reference OA complete source IDs do not close")
    exits = [event for event in parse_events(log_path.read_text(encoding="utf-8-sig"))
             if event["kind"] == "accelerator_geometric_exit"]
    if len(exits) != len(expected) or {int(event["ion"]) for event in exits} != expected:
        raise ValueError("Reference OA geometric-exit IDs do not close")
    rows = []
    for event in exits:
        particle = by_id[int(event["ion"])]
        if event["z_mm"] != 0 or event["vz_mm_us"] >= 0:
            raise ValueError("Reference OA exit must be at geometric z=0 toward negative z")
        row = {"mass_amu": float(particle["mass_th"]), "charge_state": particle["charge_e"]}
        charge = float(row["charge_state"])
        if not charge.is_integer() or charge == 0 or row["mass_amu"] <= 0:
            raise ValueError("Reference OA species is invalid")
        row["charge_state"] = int(charge)
        row.update({f"velocity_{axis}_m_s": event[f"v{axis}_mm_us"] * 1000 for axis in "xyz"})
        rows.append(row)
    target = _finite(provider["mrtof_projection"]["target_axial_energy_per_charge_v"], "MR axial target")
    if target <= 0:
        raise ValueError("MR axial target must be positive")
    source_energy = _distribution([float(row["kinetic_energy_ev"]) / abs(float(row["charge_e"])) for row in source_rows])
    reference = {"counts": {"source": len(expected), "geometric_exit": len(rows)},
                 "surface": "accelerator_geometric_exit_z0_not_PA_safe_exit",
                 "source_release_total_energy_per_charge": source_energy,
                 "source_release_distribution": source.get("release_energy_distribution"),
                 "exit": _exit_distributions(rows)}
    identities = {name: _identity(path) for name, path in (
        ("reference_provider", provider_path), ("reference_source", source_path),
        ("reference_source_states", state_path), ("reference_log", log_path),
        ("reference_manifest", reference_mr_run / "run_manifest.json"))}
    return target, reference, identities


def compare_measured_exit_energy(component_receipt_path: Path, reference_mr_run: Path) -> dict[str, Any]:
    """Compare a measured IP exit to the frozen MR target and actual OA cohort.

    No source vector is changed. Reference and IP distributions use eV/|q|;
    all mother IDs and losses are retained. A centroid residual and empirical
    spread are evidence, not an invented acceptance tolerance or performance
    PASS. This function reads only manifest/receipt-bound light evidence.
    """
    component = _read(component_receipt_path)
    validate_component_exit_binding(component)
    for record in component["inputs"].values():
        _bound_file(record, component_receipt_path.parent)
    state_path = _bound_file(component["outputs"]["component_states"], component_receipt_path.parent)
    census_path = _bound_file(component["outputs"]["mother_census"], component_receipt_path.parent)
    table = load_component_particle_state_csv(state_path)
    rows, validation = table.rows, table.report
    with census_path.open(encoding="utf-8-sig", newline="") as handle:
        census = list(csv.DictReader(handle))
    ids = {row["particle_id"] for row in rows}
    partition = partition_cohort([int(row["particle_id"]) for row in census],
        [(int(row["particle_id"]), row["transfer_status"]) for row in census],
        categories=("transferred", "not_transferred"), relative_weights=None)
    transferred = set(partition["particle_ids_by_category"]["transferred"])
    lost = set(partition["particle_ids_by_category"]["not_transferred"])
    if (ids != transferred or ids != set(component["transferred_particle_ids"])
            or lost != set(component.get("not_transferred_particle_ids", component.get("lost_particle_ids", [])))
            or component["counts"] != {"source": len(census), "transferred": len(rows), "not_transferred": len(lost)}):
        raise ValueError("IP complete mother census and energy cohort do not close")
    if (validation["frame_ids"] != [component["frame_id"]]
            or validation["clock_epoch_ids"] != [component["clock_epoch_id"]]
            or any(row["velocity_z_m_s"] >= 0
                   or row["source_component_id"] != component["source_instance_id"]
                   or row["target_component_id"] != component["target_instance_id"]
                   or row["state_event"] != "extraction_exit" for row in rows)):
        raise ValueError("IP measured exit frame, clock or negative-z direction differs")
    target, reference, identities = _reference_exit(reference_mr_run)
    measured = _exit_distributions(rows)
    axial = measured["directional_energy"]["z"]
    ref_axial = reference["exit"]["directional_energy"]["z"]
    residual = axial["mean"] - target
    sigma = ref_axial["population_sigma"]
    return {"schema_version": 1, "role": "mrtof_measured_exit_energy_comparison",
            "status": "characterized_without_acceptance_tolerance", "qualification": "energy_distribution_comparison_only",
            "energy_unit": "eV_per_abs_charge_state", "target_axial_energy_per_charge_v": target,
            "target_basis": "historical_OA_provider_axial_design_seed_not_unique_IP_or_total_energy_target",
            "ip_counts": component["counts"], "ip_transferred_particle_ids": sorted(ids), "ip_not_transferred_particle_ids": sorted(lost),
            "ip_exit": measured, "reference_oa": reference,
            "centroid_residual_to_target": residual,
            "centroid_residual_to_reference_oa_mean": axial["mean"]-ref_axial["mean"],
            "total_energy_centroid_difference_to_reference_oa": measured["total_energy"]["mean"]-reference["exit"]["total_energy"]["mean"],
            "directional_energy_centroid_difference_to_reference_oa": {
                axis: measured["directional_energy"][axis]["mean"]-reference["exit"]["directional_energy"][axis]["mean"]
                for axis in "xyz"},
            "nominal_total_energy_target": {
                "status": "undefined_no_explicit_same_surface_total_energy_target", "value": None,
                "reason": "Do not add historical axial seed to OA release Ey: release and exit are distinct potential/reference surfaces."},
            "electrostatic_energy_reference": {
                "invariant": "K_per_abs_charge_plus_charge_sign_times_potential",
                "positive_ion_form": "K/q + phi = constant_in_static_electrostatic_transport",
                "potential_difference_compensated": False,
                "comparison_basis": "raw_measured_kinetic_energies_at_OA_geometric_z0_and_IP_recorded_exit_z0",
                "required_for_downstream_comparison": "Determine potentials and signed directions at the same Prism design/reference surface before interpreting kinetic-energy differences."},
            "centroid_residual_in_reference_population_sigma": residual/sigma if sigma > 0 else None,
            "centroid_match_accepted": None,
            "matching_criterion": "Report axial and total-energy differences only. Evaluate subsequent Prism design using K/q+phi and signed direction at its specified surface; no tolerance or acceptance is assigned.",
            "caveats": [
                "Reference population sigma is empirical beam dispersion, not a centroid acceptance tolerance or numerical error bound.",
                "Deterministic finite cohorts do not justify an IID sigma/sqrt(N) confidence test or tolerance.",
                "Old provider 0.05 eV residual tolerances validate its own controlled extraction, not a replacement IP centroid or full beam.",
                "Small IP slow-axis energy is intentional; its difference from OA Ey is descriptive and is not a mismatch or failure criterion.",
                "Prism voltages and geometry may redistribute y/z momentum and direction, subject to electrostatic energy conservation and physical acceptance; arbitrary independent components are not implied.",
                "Matching mean Ez does not qualify emittance, time focus, prism transport or detector performance.",
                "All transferred ions enter the distributions; upstream non-transfers remain in the full mother census.",
            ],
            "inputs": {**identities, "component_receipt": _identity(component_receipt_path),
                       "component_states": _identity(state_path), "mother_census": _identity(census_path)}}
