"""Managed five-species oa-TOF study over explicit scientific and Formal inputs.

The analysis mathematics remains in :mod:`single_reflection_mass_spectrum`.
This module owns study order, cohort construction, native-unit authentication,
and sealed-parent selection. The existing execution owner owns all lifecycle.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from msplatform.contracts.particle_count_policy import load_particle_count_policy
from msplatform.execution.context import ExecutionContext, load_environment
from msplatform.execution.owner import resume_finalization as resume_owner_finalization
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_session import RunSession
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, record_path, verify_record
from msplatform.ion_release.dotnet_gaussian_box_ion11 import (
    _serialized_ion_source, generate_ion_source, validate_ion_source,
)
from msplatform.workflows.single_reflection_mass_spectrum import analyze_mass_spectrum, load_mode

PROJECT = "single_reflection_oa_tof_mass_analyzer"
MODE = "mass_spectrum_candidate"
ACTION = "oa_tof_mass_spectrum"
OUTPUT_NAMES = (
    "mass_spectrum_particles.csv", "mass_spectrum_summary.csv",
    "mass_peak_shape_comparison.csv", "mass_spectrum_metrics.json",
    "mass_spectrum_comparison.png", "mass_detector_landing_comparison.png",
)
RETRACE_RESOURCES = (
    "load_oatof_contract.m",
    "oatof_paths.m",
    "configure_oatof_segmented_output.m",
    "oatof_extract_detector_arrivals.m",
    "oatof_detector_arrival_reducer.m",
    "workspace_paths.m",
    "resolve_path_identity.m",
)
RETRACE_ENVIRONMENT = {
    "OATOF_ACCELERATOR_HMAX_MM": "1",
    "OATOF_REUSE_EXISTING_FIELD": "1",
    "OATOF_FINE_TSTEP_NS": "0.2",
    "OATOF_DRIFT_TSTEP_NS": "50",
    "OATOF_SEGMENTED_OUTPUT": "1",
    "OATOF_USE_PARTICLE_STOP_TIME": "0",
    "OATOF_CLEAR_PARTICLE_SOLUTION_DATA": "0",
    "OATOF_APPLY_PARTICLE_PROPERTIES": "1",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def _completion_api():
    from msplatform.backends.simion import native_completion
    return native_completion


def _source_arguments(mode: dict[str, Any], contract: dict[str, Any], species: Mapping[str, Any],
                      particle_count: int) -> dict[str, Any]:
    source = contract["particle_source"]
    experiment = mode["particle_source"]
    return dict(
        particle_count=particle_count, mass_amu=float(species["mass_amu"]),
        charge=int(species["charge_state"]),
        energy_mean_ev=float(experiment["initial_energy_mean_ev"]),
        energy_std_ev=float(experiment["initial_energy_sigma_ev"]),
        half_width_xyz_mm=tuple(float(source[name]) / 2 for name in ("size_x_mm", "size_y_mm", "size_z_mm")),
        center_xyz_mm=tuple(float(source[name]) for name in ("center_x_mm", "center_y_mm", "center_z_mm")),
        seed=int(experiment["shared_seed"]),
    )


def build_source_cohort(mode_path: Path, geometry_path: Path, policy_path: Path,
                        ion_dir: Path, log_dir: Path) -> dict[str, Any]:
    """Build the unchanged per-species parents, prefixes, and mixed ION order."""
    mode = load_mode(mode_path)
    contract = _json(geometry_path)
    policy = load_particle_count_policy(policy_path=policy_path)
    statistical = int(policy["statistical_count"])
    functional = int(policy["functional_check_count"])
    if int(policy["default_particle_count"]) not in policy["standard_particle_counts"]:
        raise ValueError("Particle-count policy default is not a named standard")
    ion_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    individual, parents, provenance = [], [], []
    combined: list[str] = []
    for species in mode["species"]:
        species_id = str(species["species_id"])
        count = int(species["particle_count"])
        if count not in (functional, statistical):
            raise ValueError(f"Mass-spectrum particle count lacks a named source policy: {count}")
        parent = ion_dir / f"{species_id}__n1000_parent.ion"
        arguments = _source_arguments(mode, contract, species, statistical)
        parent.write_bytes(_serialized_ion_source(generate_ion_source(**arguments)))
        lines = parent.read_text(encoding="ascii").splitlines()
        if len(lines) != statistical:
            raise ValueError("Generated N=1000 parent ION row count is incorrect")
        selected = ion_dir / f"{species_id}.ion"
        selected.write_bytes(_serialized_ion_source(lines[:count]))
        if count == statistical and selected.read_bytes() != parent.read_bytes():
            raise ValueError("N=1000 species source differs from its generated parent")
        report_path = log_dir / f"{species_id}__n1000_parent_validation.json"
        validation = validate_ion_source(source_path=parent, **arguments)
        validation.update(species_id=species_id, consumed_source_path=str(selected),
                          consumed_source_sha256=file_record(selected, "required_evidence")["sha256"])
        report_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
        if selected.read_text(encoding="ascii").splitlines() != lines[:count]:
            raise ValueError("N=100 source is not the validated prefix of its N=1000 parent")
        individual.append(selected)
        parents.append(parent)
        provenance.append(validation)
        combined.extend(selected.read_text(encoding="ascii").splitlines())
    mixed = ion_dir / "wide_mz_combined.ion"
    mixed.write_bytes(_serialized_ion_source(combined))
    expected = sum(int(item["particle_count"]) for item in mode["species"])
    if len(combined) != expected:
        raise ValueError("Combined ION row count is incorrect")
    return dict(mode=mode, individual=individual, parents=parents, mixed=mixed,
                provenance=provenance, total_particles=expected)


def mass_spectrum_max_tof_us(mode_path: Path, reference_mass_amu: float) -> float:
    """Retain the established five-species diagnostic observation horizon."""
    mode = _json(mode_path)
    masses = [float(species["mass_amu"]) for species in mode["species"]]
    if not masses or min(masses) <= 0 or reference_mass_amu <= 0:
        raise ValueError("Masses used for TOF scaling must be positive")
    return float(math.ceil(90.0 * math.sqrt(max(masses) / reference_mass_amu)))


def _freeze_code(session: RunSession, task_script: Path | None, resolved: Path) -> tuple[dict[str, Any], Path | None, Path]:
    """Freeze installed origins and the selected backend retrace task."""
    from importlib.resources import files
    from msplatform.backends.comsol.resources import native_resource_path
    from msplatform.execution.inputs import enumerate_python_sources, freeze_file, freeze_python_package

    provider = Path(str(files("msplatform"))).resolve()
    source_root = provider.parent
    selected = enumerate_python_sources(
        source_root, package_roots=("msplatform",),
        resource_suffixes=(".json", ".ps1", ".lua", ".m", ".gem", ".iob"),
        require_python_source=True,
    )
    code_root = session.input_dir / "code"
    package = freeze_python_package(source_root, code_root, relative_paths=selected)
    def code_inputs():
        for index, entry in enumerate(package["files"]):
            path = session.declare_file(Path(entry["path"]), "required_evidence")
            yield f"study_code_{index:04d}", file_record(path, "required_evidence")
    session.add_inputs(code_inputs())
    task_target = None
    if task_script is not None:
        if task_script.resolve() != native_resource_path("run_fixed_particle_retrace.m").resolve():
            raise ValueError("COMSOL retrace task must be the installed backend implementation")
        task_target = session.declare_file(
            code_root / "src/msplatform/backends/comsol/matlab/run_fixed_particle_retrace.m", "required_evidence")
        task_target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(task_script, task_target)
        task_record = file_record(task_target, "required_evidence")
        package["files"].append(dict(
            relative_path="src/msplatform/backends/comsol/matlab/run_fixed_particle_retrace.m",
            path=str(task_target), sha256=task_record["sha256"]))
        session.add_input("comsol_task", task_record)
        for index, relative in enumerate(RETRACE_RESOURCES):
            source = native_resource_path(relative)
            target = session.declare_file(
                code_root / f"src/msplatform/backends/comsol/matlab/{relative}", "required_evidence")
            target.parent.mkdir(parents=True, exist_ok=True)
            freeze_file(source, target)
            record = file_record(target, "required_evidence")
            package["files"].append(dict(
                relative_path=f"src/msplatform/backends/comsol/matlab/{relative}",
                path=str(target), sha256=record["sha256"]))
            session.add_input(f"comsol_support_{index}", record)
    geometry_target = session.declare_file(
        code_root / f"projects/{PROJECT}/config/resolved_geometry.json", "required_evidence")
    geometry_target.parent.mkdir(parents=True, exist_ok=True)
    freeze_file(resolved, geometry_target)
    geometry_record = file_record(geometry_target, "required_evidence")
    package["files"].append(dict(
        relative_path=f"projects/{PROJECT}/config/resolved_geometry.json",
        path=str(geometry_target), sha256=geometry_record["sha256"]))
    session.add_input("frozen_geometry", geometry_record)
    inventory_path = session.declare_file(session.input_dir / "code_inventory.json", "required_evidence")
    write_json_atomic(inventory_path, package)
    session.add_input("code_inventory", file_record(inventory_path, "required_evidence"))
    return package, task_target, geometry_target


def _frozen_guards(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bind current files to their original inventory, never to altered bytes."""
    guards = []
    for row in package["files"]:
        path = Path(row["path"])
        if not path.is_file():
            raise RuntimeError(f"Frozen Python dependency is missing: {path}")
        record = file_record(path, "required_evidence")
        if record["sha256"] != str(row["sha256"]).upper():
            raise RuntimeError(f"Frozen Python dependency hash differs: {path}")
        guards.append(record)
    return guards


def _selected_input(manifest: dict[str, Any], config: dict[str, Any], source: Path,
                    name: str) -> dict[str, Any]:
    record = manifest.get("inputs", {}).get(name)
    if not isinstance(record, dict):
        raise ValueError(f"Parent manifest lacks consumed input: {name}")
    path = record_path(record, base_dir=source)
    declared = config.get("inputs", {}).get(name)
    if not isinstance(declared, str):
        raise ValueError(f"Parent config lacks consumed input: {name}")
    declared_path = Path(declared)
    if not declared_path.is_absolute():
        declared_path = source / declared_path
    if declared_path.resolve() != path or not path.is_relative_to(source / "inputs"):
        raise ValueError(f"Parent input binding differs: {name}")
    verify_record(name, record, base_dir=source)
    return {**record, "path": str(path)}


def _selected_output(manifest: dict[str, Any], source: Path, relative: str) -> dict[str, Any]:
    path = source / relative
    matches = [row for row in manifest.get("outputs", [])
               if record_path(row, base_dir=source) == path]
    if len(matches) != 1:
        raise ValueError(f"Parent manifest lacks a unique consumed output: {relative}")
    verify_record(relative, matches[0], base_dir=source)
    return {**matches[0], "path": str(path)}


def _source_owner(source: Path, consumer_artifact_root: Path,
                  stopped_receipt: Path | None) -> tuple[dict[str, Any], dict[str, Any], Path]:
    from msplatform.execution.capacity_ledger import load_capacity_ledger
    from msplatform.execution.retention import file_record as retention_record
    from msplatform.execution.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
    from msplatform.io.manifest_records import require_completed_terminal_publication

    source = source.resolve(strict=True)
    manifest_path = source / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest_record = retention_record(manifest_path)
    stopped_record = retention_record(stopped_receipt.resolve(strict=True)) if stopped_receipt else None
    owner = resolve_consumed_run_capacity_owner(
        manifest_record, consumer_artifact_root=consumer_artifact_root,
        stopped_receipt_record=stopped_record)
    manifest = _json(manifest_path)
    config = _json(source / "run_config.json")
    if (manifest.get("project") != PROJECT or manifest.get("mode") != MODE
            or config.get("role") not in (None, "oa_tof_mass_spectrum_run_config")):
        raise ValueError("Source is not an oa-TOF mass-spectrum parent")
    root = Path(owner["artifact_root"])
    ledger = load_capacity_ledger(root)
    entries = [] if ledger is None else [item for item in ledger["objects"]
        if item.get("path") == source.relative_to(root).as_posix()]
    if (len(entries) != 1 or entries[0].get("status") != "ready"
            or entries[0].get("class") not in ("light_evidence", "rebuildable_payload")):
        raise ValueError("Source writing is not sealed")
    if manifest["status"] not in ("success", "failed", "checkpoint"):
        raise ValueError("Source lacks sufficient sealed terminal evidence")
    return manifest_record, {"manifest": manifest, "config": config}, root


def select_analysis_source(source: Path, consumer_artifact_root: Path,
                           stopped_receipt: Path | None = None) -> dict[str, Any]:
    """Select only sufficient sealed small records; never consult live Formal."""
    manifest_record, selected, _ = _source_owner(source, consumer_artifact_root, stopped_receipt)
    manifest, config = selected["manifest"], selected["config"]
    inputs = {name: _selected_input(manifest, config, source, name)
              for name in ("mode_config", "resolved_geometry")}
    mode = _json(Path(inputs["mode_config"]["path"]))
    species = mode.get("species")
    if (mode.get("schema_version") != 1 or mode.get("mode") != MODE
            or mode.get("role") != "oa_tof_candidate_mass_spectrum_mode"
            or not isinstance(species, list) or len(species) < 3):
        raise ValueError("Parent mass-spectrum species are missing")
    ids = [item.get("species_id") for item in species]
    if (any(not isinstance(value, str) or not value or Path(value).name != value
            or "/" in value or "\\" in value or value in (".", "..") for value in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("Parent species identifiers are invalid or duplicated")
    counts = [item.get("particle_count") for item in species]
    if any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("Parent emitted counts are invalid")
    exports = {"simion_csv": _selected_output(manifest, source, "results/simion_particles.csv"),
               "simion_summary": _selected_output(manifest, source, "results/simion_summary.json")}
    if _json(Path(exports["simion_summary"]["path"])).get("Hit") != sum(counts):
        raise ValueError("Parent SIMION full-mother detection requirement is not satisfied")
    from msplatform.backends.comsol.oatof_retrace import verify_completed_species
    for item, count in zip(species, counts, strict=True):
        name = item["species_id"]
        exports[f"comsol_{name}"] = _selected_output(manifest, source, f"comsol/{name}.csv")
        report = _selected_output(manifest, source, f"logs/{name}.report.txt")
        completion = _selected_output(manifest, source, f"logs/{name}.comsol_completion.json")
        verify_completed_species(run_id=config["run_id"], particle_count=count,
            csv_path=Path(exports[f"comsol_{name}"]["path"]), report_path=Path(report["path"]),
            completion_path=Path(completion["path"]))
        exports[f"report_{name}"] = report
        exports[f"completion_{name}"] = completion
    return dict(manifest_record=manifest_record, run_id=config["run_id"],
        source_directory=str(source), inputs=inputs, exports=exports,
        execution=config.get("execution", {}),
        particle_source_provenance=config.get("particle_source_provenance", []))


def select_partial_source(source: Path, consumer_artifact_root: Path,
                          stopped_receipt: Path | None = None) -> dict[str, Any]:
    """Select complete species only; missing units remain explicit new work."""
    manifest_record, selected, _ = _source_owner(source, consumer_artifact_root, stopped_receipt)
    manifest, config = selected["manifest"], selected["config"]
    inputs = {name: _selected_input(manifest, config, source, name)
              for name in ("mode_config", "resolved_geometry")}
    mode = _json(Path(inputs["mode_config"]["path"]))
    completed = {}
    from msplatform.backends.comsol.oatof_retrace import completion_successful, load_launcher_completion
    for item in mode["species"]:
        name, count = item["species_id"], int(item["particle_count"])
        paths = dict(csv=source / f"comsol/{name}.csv", report=source / f"logs/{name}.report.txt",
                     completion=source / f"logs/{name}.comsol_completion.json")
        if not all(path.is_file() for path in paths.values()):
            continue
        try:
            records = {key: _selected_output(manifest, source,
                str(path.relative_to(source).as_posix())) for key, path in paths.items()}
            receipt = load_launcher_completion(paths["completion"], run_id=config["run_id"])
        except (ValueError, FileNotFoundError) as error:
            raise ValueError(f"Partial parent has an unauthenticated species unit: {name}") from error
        expected = f"DETECTED={count}/{count}"
        if (not completion_successful(receipt)
                or expected not in paths["report"].read_text(encoding="utf-8-sig").splitlines()):
            continue
        completed[name] = dict(records=records, verified={"receipt": receipt})
    return dict(manifest_record=manifest_record, run_id=config["run_id"],
        source_directory=str(source), inputs=inputs, completed=completed)


def _declare_sources(session: RunSession, cohort: Mapping[str, Any]) -> None:
    for path in [*cohort["individual"], *cohort["parents"], cohort["mixed"]]:
        session.declare_file(path, "solver_native_binary")
    for path in session.log_dir.glob("*__n1000_parent_validation.json"):
        session.declare_file(path, "required_evidence")


def _analysis_outputs(session: RunSession, mode_path: Path, geometry_path: Path,
                      comsol_dir: Path, simion_csv: Path) -> list[Path]:
    analyze_mass_spectrum(mode_path, comsol_dir, simion_csv, session.result_dir, geometry_path)
    outputs = [session.declare_file(session.result_dir / name, "required_evidence") for name in OUTPUT_NAMES]
    return outputs


def _run_action(session: RunSession, *, requested: dict[str, Path], original: dict[str, Any],
                stage: dict[str, Any], partial_parent: dict[str, Any] | None) -> dict[str, Any]:
    from msplatform.backends.comsol import oatof_retrace
    from msplatform.backends.simion.mass_spectrum import run_mixed_species_fly
    from msplatform.execution.inputs import freeze_file

    frozen = {}
    for name in ("mode_config", "resolved_geometry", "particle_count_policy"):
        source = requested[name]
        verify_record(f"requested {name}", original[name])
        target = session.declare_file(session.input_dir / f"{name}.json", "required_evidence")
        record = dict(freeze_file(source, target), retention_role="required_evidence")
        if record["sha256"] != original[name]["sha256"]:
            raise ValueError(f"Requested scientific input changed before freezing: {name}")
        session.add_input(name, record)
        frozen[name] = target
    package, task, frozen_geometry = _freeze_code(session, requested["comsol_task"], frozen["resolved_geometry"])
    guards = _frozen_guards(package)
    guards += [file_record(frozen[name], "required_evidence") for name in (
        "mode_config", "resolved_geometry", "particle_count_policy")]
    formal_model_record = file_record(requested["formal_mph"], "required_evidence")
    session.add_input("formal_comsol_mph", formal_model_record)
    formal_manifest_record = file_record(requested["formal_asset_manifest"], "required_evidence")
    session.add_input("formal_asset_manifest", formal_manifest_record)
    ion_dir = session.run_dir / "ions"
    comsol_dir = session.run_dir / "comsol"
    comsol_dir.mkdir(exist_ok=True)
    cohort = build_source_cohort(frozen["mode_config"], frozen["resolved_geometry"],
        frozen["particle_count_policy"], ion_dir, session.log_dir)
    _declare_sources(session, cohort)
    native_completion = {}
    scientific_failures = {}
    reused_outputs: list[Path] = []
    launcher = session.input_dir / "code/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1"
    try:
        for index, species in enumerate(cohort["mode"]["species"]):
            name, count = str(species["species_id"]), int(species["particle_count"])
            csv_path = session.declare_file(comsol_dir / f"{name}.csv", "required_evidence")
            session.declare_file(comsol_dir / f"{name}_fixedN{count}_selected_release_from_data_file.txt",
                                 "required_evidence")
            report = session.declare_file(session.log_dir / f"{name}.report.txt", "required_evidence")
            completion_path = session.declare_file(
                session.log_dir / f"{name}.comsol_completion.json", "required_evidence")
            reused = partial_parent and partial_parent["completed"].get(name)
            if reused:
                for key, target in (("csv", csv_path), ("report", report), ("completion", completion_path)):
                    record = freeze_file(Path(reused["records"][key]["path"]), target)
                    if record["sha256"] != reused["records"][key]["sha256"]:
                        raise ValueError(f"Reused COMSOL {name} identity changed")
                oatof_retrace.verify_completed_species(run_id=partial_parent["run_id"],
                    particle_count=count, csv_path=csv_path, report_path=report,
                    completion_path=completion_path)
                native_completion[name] = {"reused_from": partial_parent["run_id"]}
                reused_outputs.extend((csv_path, report, completion_path))
                continue
            environment = dict(RETRACE_ENVIRONMENT, OATOF_CONTRACT_PATH=str(frozen_geometry))
            from msplatform.execution.processes import ProcessExecutionError
            try:
                oatof_retrace.run_species_retrace(session,
                    operation_id=f"comsol-{name}", run_id=session.run_id, launcher=launcher,
                    task_script=task, source_model=requested["formal_mph"],
                    ion_table=cohort["individual"][index], output_csv=csv_path,
                    report_path=report, completion_path=completion_path, runtime_dir=comsol_dir,
                    results_dir=session.result_dir, scientific_environment=environment,
                    limits=stage["limits"], immutable_input_records=tuple(guards + [formal_model_record]))
            except ProcessExecutionError as failure:
                completion = oatof_retrace.load_launcher_completion(completion_path, run_id=session.run_id)
                report_lines = report.read_text(encoding="utf-8-sig").splitlines()
                if "STATUS=FAIL" not in report_lines:
                    raise
                import csv
                with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                detected = sum(row.get("Hit", "").strip().lower() in {"1", "true", "yes"} for row in rows)
                if len(rows) != count or detected == count:
                    raise
                for evidence in (csv_path, report, completion_path):
                    verify_record(f"COMSOL scientific negative {name}", file_record(evidence, "required_evidence"))
                native_completion[name] = {"receipt": completion,
                    "scientific_failure": "not_all_particles_detected", "detected": detected, "total": count}
                scientific_failures[name] = failure
                continue
            native_completion[name] = oatof_retrace.verify_completed_species(
                run_id=session.run_id, particle_count=count, csv_path=csv_path,
                report_path=report, completion_path=completion_path)
        simion_csv = session.declare_file(session.result_dir / "simion_particles.csv", "required_evidence")
        simion_summary = session.declare_file(session.result_dir / "simion_summary.json", "required_evidence")
        runtime_receipt = session.declare_file(
            session.input_dir / "formal_simion_runtime_receipt.json", "required_evidence")
        reference_mass = float(_json(frozen["resolved_geometry"])["validation_target"]["mass_amu"])
        run_mixed_species_fly(session, operation_id="simion-mixed-species",
            simion_executable=requested["simion_executable"],
            artifact_project_root=requested["artifact_project_root"], project_id=PROJECT,
            combined_ion=cohort["mixed"], total_particles=cohort["total_particles"],
            max_tof_us=mass_spectrum_max_tof_us(frozen["mode_config"], reference_mass),
            output_csv=simion_csv, summary_path=simion_summary, runtime_receipt=runtime_receipt,
            limits=stage["limits"], immutable_input_records=guards)
        analysis = [] if scientific_failures else _analysis_outputs(
            session, frozen["mode_config"], frozen_geometry, comsol_dir, simion_csv)
        config = _json(session.run_config)
        config.update(role="oa_tof_mass_spectrum_run_config", species=cohort["mode"]["species"],
            particle_source_provenance=cohort["provenance"], native_completion=native_completion,
            execution=dict(simion="one mixed-species fly",
                comsol="one particle-tracing solve per species; formal electrostatic solution reused",
                resumed_after_comsol=partial_parent is not None, reanalyze_only=False,
                particle_count_contract="repository_standard_with_n100_prefix_of_n1000",
                simion_max_tof_us=mass_spectrum_max_tof_us(frozen["mode_config"], reference_mass)))
        write_json_atomic(session.run_config, config)
        metrics = {} if scientific_failures else _json(session.result_dir / "mass_spectrum_metrics.json")
        outputs = [*analysis, simion_csv, simion_summary, cohort["mixed"],
            *cohort["individual"], *cohort["parents"], *reused_outputs]
        outputs += [comsol_dir / f"{item['species_id']}.csv" for item in cohort["mode"]["species"]]
        outputs += [session.log_dir / f"{item['species_id']}.report.txt" for item in cohort["mode"]["species"]]
        outputs += [session.log_dir / f"{item['species_id']}.comsol_completion.json" for item in cohort["mode"]["species"]]
        outputs += list(session.log_dir.glob("*__n1000_parent_validation.json"))
        outputs = [session.canonical_path(path) for path in dict.fromkeys(outputs)]
        return dict(status="failed" if scientific_failures else "success",
            summary=dict(metrics, execution_status="completed",
            data_validity="valid", scientific_result="candidate_diagnostic", formal_gate_passed=False,
            scientific_failures=sorted(scientific_failures)),
            output_paths=outputs, required_output_paths=analysis,
            retention_preserve_paths=[], manifest_extra_fields={})
    except Exception as primary:
        primary.failure_output_paths = [Path(path) for path in session.file_roles
            if Path(path).is_file() and Path(path).is_relative_to(session.artifact_run_dir)]
        raise


def validate_formal_inputs(*, project_config: Path, formal_assets: Path, formal_mph: Path,
                           formal_asset_manifest: Path, baseline: Path, formal_mode: Path,
                           solver_numerics: Path, resolved_geometry: Path) -> None:
    """Authenticate the selected release and reproduce its frozen resolved bytes."""
    from msplatform.backends.simion.tof_geometry import resolve_oatof_contract_documents
    from msplatform.components.single_reflection_oa_tof.geometry_contract import serialized

    if _json(project_config).get("lifecycle_status") == "formal_revalidation_pending":
        raise ValueError("FORMAL_REVALIDATION_REQUIRED")
    assets = _json(formal_assets)
    model = file_record(formal_mph, "solver_native_binary")
    if (assets.get("role") != "oa_tof_formal_model_and_cad_asset_identity"
            or model["sha256"] != str(assets["comsol"]["sha256"]).upper()
            or _json(formal_asset_manifest).get("release_id") != assets.get("release_id")):
        raise ValueError("Selected Formal asset identity differs")
    documents = [_json(path) for path in (baseline, formal_mode, solver_numerics)]
    published = _json(resolved_geometry)
    identity = dict(published["inputs"])
    for key, path in (("baseline", baseline), ("mode", formal_mode),
                      ("solver_numerics", solver_numerics)):
        if file_record(path, "required_evidence")["sha256"] != str(identity[key + "_sha256"]).upper():
            raise ValueError(f"Resolved geometry {key} authority differs")
    expected = serialized(resolve_oatof_contract_documents(
        *documents, input_identity=identity))
    if resolved_geometry.read_text(encoding="utf-8") != expected:
        raise ValueError("STALE=config/resolved_geometry.json")


def _requested_paths(mode_config: Path, resolved_geometry: Path, particle_count_policy: Path,
                     formal_mph: Path, formal_asset_manifest: Path, comsol_task: Path,
                     simion_executable: Path, artifact_project_root: Path,
                     project_config: Path, formal_assets: Path, baseline: Path,
                     formal_mode: Path, solver_numerics: Path) -> dict[str, Path]:
    paths = dict(mode_config=mode_config, resolved_geometry=resolved_geometry,
        particle_count_policy=particle_count_policy, formal_mph=formal_mph,
        formal_asset_manifest=formal_asset_manifest, comsol_task=comsol_task,
        simion_executable=simion_executable, artifact_project_root=artifact_project_root,
        project_config=project_config, formal_assets=formal_assets, baseline=baseline,
        formal_mode=formal_mode, solver_numerics=solver_numerics)
    for name, path in paths.items():
        if name != "artifact_project_root" and not path.is_file():
            raise FileNotFoundError(f"Required mass-spectrum input is absent: {name}: {path}")
    validate_formal_inputs(project_config=project_config, formal_assets=formal_assets,
        formal_mph=formal_mph, formal_asset_manifest=formal_asset_manifest,
        baseline=baseline, formal_mode=formal_mode, solver_numerics=solver_numerics,
        resolved_geometry=resolved_geometry)
    return paths


def run(context: ExecutionContext, *, run_id: str, mode_config: Path, resolved_geometry: Path,
        particle_count_policy: Path, formal_mph: Path, formal_asset_manifest: Path,
        comsol_task: Path, simion_executable: Path, artifact_project_root: Path,
        project_config: Path, formal_assets: Path, baseline: Path, formal_mode: Path,
        solver_numerics: Path, partial_parent: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a new normal or authenticated partial-successor mass-spectrum study."""
    from functools import partial
    requested = _requested_paths(mode_config, resolved_geometry, particle_count_policy,
        formal_mph, formal_asset_manifest, comsol_task, simion_executable, artifact_project_root,
        project_config, formal_assets, baseline, formal_mode, solver_numerics)
    original = {name: file_record(path, "required_evidence") for name, path in requested.items()
                if name not in ("simion_executable", "artifact_project_root")}
    load_mode(mode_config)
    _json(resolved_geometry)
    load_particle_count_policy(policy_path=particle_count_policy)
    stage, policy_record = read_stage_policy(context, ACTION)
    mode = load_mode(mode_config)
    ids = [f"comsol-{item['species_id']}" for item in mode["species"]
           if not partial_parent or item["species_id"] not in partial_parent["completed"]]
    ids.append("simion-mixed-species")
    dependencies = {name: [] for name in ids}
    source_references, protected = [], []
    if partial_parent:
        source_references = [dict(manifest_record=partial_parent["manifest_record"],
            protected_paths=[partial_parent["source_directory"]])]
        protected.append(Path(partial_parent["source_directory"]))
    result = run_managed_stage(context,
        descriptor=dict(project=PROJECT, mode=MODE,
                        software=["COMSOL 6.4", "SIMION 2020", "Python 3.11"]),
        run_id=run_id, payload=dict(lifecycle_stage="prepared", analysis_only=False,
            formal_gate_passed=False, resumed_after_comsol=partial_parent is not None),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record, *original.values()], retention=stage["artifact_retention"],
        expected_operation_ids=ids, operation_dependencies=dependencies,
        action=partial(_run_action, requested=requested, original=original,
                       stage=stage, partial_parent=partial_parent),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        source_references=source_references, protected_paths=protected,
        use_short_execution_path=True, completion_api=_completion_api)
    return result


def _analysis_action(session: RunSession, *, selection: dict[str, Any],
                     stage: dict[str, Any]) -> dict[str, Any]:
    from msplatform.execution.inputs import freeze_file
    mode = session.declare_file(session.input_dir / "mass_spectrum.json", "required_evidence")
    geometry = session.declare_file(session.input_dir / "resolved_geometry.json", "required_evidence")
    try:
        for name, target in (("mode_config", mode), ("resolved_geometry", geometry)):
            record = dict(freeze_file(Path(selection["inputs"][name]["path"]), target),
                          retention_role="required_evidence")
            if record["sha256"] != selection["inputs"][name]["sha256"]:
                raise ValueError(f"Parent {name} changed before analysis")
            session.add_input(name, record)
        package, _, _ = _freeze_code(session, None, geometry)
        worker_selection = dict(selection, frozen_mode=str(mode), frozen_geometry=str(geometry))
        selection_path = session.declare_file(session.input_dir / "source_selection.json", "required_evidence")
        write_json_atomic(selection_path, worker_selection)
        selection_record = file_record(selection_path, "required_evidence")
        session.add_input("source_selection", selection_record)
        guards = _frozen_guards(package)
        guards += [selection_record, *selection["exports"].values()]
        outputs = [session.declare_file(session.result_dir / name, "required_evidence")
                   for name in OUTPUT_NAMES]
        bootstrap = ("import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];"
                     "runpy.run_module('msplatform.workflows.single_reflection_mass_spectrum_worker',"
                     "run_name='__main__')")
        for record in guards:
            try:
                verify_record("Frozen Python dependency", dict(record))
            except AssertionError as error:
                if not Path(record["path"]).is_file():
                    raise RuntimeError(f"Frozen Python dependency is missing: {record['path']}") from error
                raise RuntimeError(f"Frozen Python dependency hash differs: {record['path']}") from error
        from msplatform.execution.processes import ProcessExecutionError
        try:
            receipt = session.run_process("python-analysis", executable=session.context.python_executable,
                arguments=["-I", "-B", "-c", bootstrap, str(session.input_dir / "code"),
                           "mass-spectrum-analysis", "--selection", str(selection_path),
                           "--output", str(session.result_dir), "--code-root", str(session.input_dir / "code")],
                role="GATE", stage="postprocess", limits=stage["limits"],
                immutable_input_records=guards)
        except ProcessExecutionError as error:
            if error.observed_process_exit_confirmed:
                stderr = session.log_dir / "operation_0001.stderr.log"
                detail = stderr.read_text(encoding="utf-8", errors="replace")[-4000:] if stderr.is_file() else str(error)
                raise RuntimeError("Mass-spectrum reanalysis failed: " + detail) from error
            raise
        if receipt["observation"]["exit_code"] != 0:
            raise RuntimeError("Mass-spectrum reanalysis failed; see analysis stderr")
        config = _json(session.run_config)
        config["parameters"].update(lifecycle_stage="complete", simulation_calls=0,
            solver_native_calls=0, pa_materializations=0, parent_run_id=selection["run_id"])
        write_json_atomic(session.run_config, config)
        return dict(status="success", summary=dict(role="oa_tof_candidate_mass_spectrum_analysis",
            analysis_only=True, parent_run_id=selection["run_id"], solver_native_calls=0,
            pa_materializations=0, formal_gate_passed=False, resolution_claim_allowed=False,
            native_path_preparation={"calls": 1 if session.package.get("execution_alias") else 0}),
            output_paths=outputs, required_output_paths=outputs,
            retention_preserve_paths=[], manifest_extra_fields={})
    except Exception as primary:
        primary.failure_output_paths = [Path(path) for path in session.file_roles
            if Path(path).is_file() and Path(path).is_relative_to(session.artifact_run_dir)]
        raise


def analyze(context: ExecutionContext, *, run_id: str, selection: dict[str, Any],
            committed_new_bytes: int) -> dict[str, Any]:
    """Create a zero-native successor from sufficient sealed scientific records."""
    from functools import partial
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError("AnalysisNewBytes must be a positive integer")
    stage, policy_record = read_stage_policy(context, ACTION)
    protected = [Path(row["path"]) for row in selection["exports"].values()]
    result = run_managed_stage(context,
        descriptor=dict(project=PROJECT, mode="mass_spectrum_analysis", software=["Python 3.11"]),
        run_id=run_id, payload=dict(lifecycle_stage="prepared", analysis_only=True,
            parent_run_id=selection["run_id"], formal_gate_passed=False),
        committed_new_bytes=committed_new_bytes,
        commitment_inputs=[policy_record, selection["manifest_record"]],
        retention=stage["artifact_retention"], expected_operation_ids=["python-analysis"],
        operation_dependencies={},
        action=partial(_analysis_action, selection=selection, stage=stage),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        source_references=[dict(manifest_record=selection["manifest_record"],
                                protected_paths=list(map(str, protected)))],
        protected_paths=protected, use_short_execution_path=True, completion_api=_completion_api)
    return result


def resume_finalization(context: ExecutionContext, *, run_id: str,
                        result_path: Path | None = None) -> dict[str, Any]:
    """Resume only the existing public owner; never import scientific inputs."""
    selected = result_path or (context.workspace / "artifacts/projects" / PROJECT /
        "scratch/workflow_results" / run_id / "result.json")
    result = _json(selected)
    if Path(result.get("run_directory", "")).name != run_id:
        raise ValueError("Finalization Result run identity differs")
    return resume_owner_finalization(context, selected, completion_api=_completion_api)


def _context(arguments: argparse.Namespace) -> ExecutionContext:
    return load_environment(arguments.execution_environment, workspace=arguments.workspace,
                            profile=arguments.engineering_profile)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "resume", "analyze", "resume-finalization"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--execution-environment", type=Path, required=True)
    parser.add_argument("--engineering-profile", required=True)
    parser.add_argument("--mode-config", type=Path)
    parser.add_argument("--resolved-geometry", type=Path)
    parser.add_argument("--particle-count-policy", type=Path)
    parser.add_argument("--formal-mph", type=Path)
    parser.add_argument("--formal-asset-manifest", type=Path)
    parser.add_argument("--comsol-task", type=Path)
    parser.add_argument("--simion-executable", type=Path)
    parser.add_argument("--artifact-project-root", type=Path)
    parser.add_argument("--project-config", type=Path)
    parser.add_argument("--formal-assets", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--formal-mode", type=Path)
    parser.add_argument("--solver-numerics", type=Path)
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--stopped-receipt", type=Path)
    parser.add_argument("--analysis-new-bytes", type=int)
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    context = _context(args)
    if args.action == "resume-finalization":
        result = resume_finalization(context, run_id=args.run_id, result_path=args.result_path)
    elif args.action == "analyze":
        if args.source_run is None or args.analysis_new_bytes is None:
            parser.error("analysis requires --source-run and --analysis-new-bytes")
        selection = select_analysis_source(args.source_run, context.workspace / "artifacts",
                                           args.stopped_receipt)
        result = analyze(context, run_id=args.run_id, selection=selection,
                         committed_new_bytes=args.analysis_new_bytes)
    else:
        required = ("mode_config", "resolved_geometry", "particle_count_policy", "formal_mph",
                    "formal_asset_manifest", "comsol_task", "simion_executable", "artifact_project_root",
                    "project_config", "formal_assets", "baseline", "formal_mode", "solver_numerics")
        if any(getattr(args, name) is None for name in required):
            parser.error("normal/partial execution requires every explicit scientific and Formal input")
        values = {name: getattr(args, name) for name in required}
        parent = None
        if args.action == "resume":
            if args.source_run is None:
                parser.error("partial resume requires --source-run and a distinct new --run-id")
            if args.source_run.resolve().name == args.run_id:
                parser.error("partial resume requires a distinct new --run-id")
            parent = select_partial_source(args.source_run, context.workspace / "artifacts",
                                           args.stopped_receipt)
        result = run(context, run_id=args.run_id, **values, partial_parent=parent)
    print(json.dumps(dict(status=result["status"], run_directory=result["run_directory"]),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
