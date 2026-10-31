"""Three-arm reflectron voltage study on an immutable source and a new owned run.

The public Python CLI resolves science; its private PowerShell adapter owns all
native processes, the shared SIMION batch phase, capacity and publication.
"""
from __future__ import annotations

import argparse
import math
import re
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from common.analysis.peak_metrics import compute_peak_metrics
from common.contracts.frozen_inputs import freeze_file
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan
from common.simion.native_completion import require_one_fly_completion
from common.simion.particle_batching import batch_plan_from_dispatch, plan_single_wave_batches
from common.simion.resource_scheduler import plan_simion_dispatch, prepare_fixed_partition_dispatch
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import derive_candidate_source_closure, freeze_candidate_source_closure
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_contract, resolve_contract_documents
from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import compile_component_pa_plan
from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import prepare as prepare_consumers
from projects.single_reflection_oa_tof_mass_analyzer.analysis.optimize_reflectron_ring_voltages import _load_basis, optimize, render_lua_profile
from projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics import analyze_simion_log, read_ion_table
from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import render_program

PROJECT = "single_reflection_oa_tof_mass_analyzer"
MODULE = "projects.single_reflection_oa_tof_mass_analyzer.workflows.reflectron_voltage_compensation.run_compensation"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
RELATIVE = f"projects/{PROJECT}/workflows/reflectron_voltage_compensation"
LABELS = ("baseline", "compensated", "ideal_reflectron")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _manifest(run: Path) -> dict[str, Any]:
    require_completed_terminal_publication(run / "run_manifest.json")
    value = _load(run / "run_manifest.json")
    if value.get("role") != "simulation_run_manifest" or value.get("project") != PROJECT or value.get("status") not in {"success", "failed", "interrupted"}:
        raise ValueError("compensation source must be a terminal project run")
    verify_record("source run configuration", value["run_config"], base_dir=run)
    return value


def _bound(manifest: dict[str, Any], run: Path, path: Path, *, verify: bool = True) -> dict[str, Any]:
    matches = [r for r in [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
               if isinstance(r, dict) and record_path(r, base_dir=run) == path.resolve()]
    identities = {(r.get("bytes"), str(r.get("sha256")).upper()) for r in matches}
    if not matches or len(identities) != 1:
        raise ValueError(f"source manifest does not uniquely bind consumed file: {path}")
    result = {**matches[0], "path": str(path.resolve())}
    if verify:
        verify_record("compensation consumed source", result)
    return result


def inspect_source(case: Path, executable: Path, trajectory_quality: int, regularization: float,
                   predecessor: Path | None = None, particle_count: int = 1000, numerics_path: Path | None = None) -> dict[str, Any]:
    particle_count = validate_standard_particle_count(particle_count)
    case = case.resolve()
    contract_path = case / "contracts/candidate_resolved_geometry.json"
    # Fail before any native grant, without guessing a latest run or Formal.
    contract = _load(contract_path)
    source_run = next((p for p in (case, *case.parents) if (p / "run_manifest.json").is_file()), None)
    if source_run is None:
        raise ValueError("case-dir requires its explicit terminal run manifest")
    manifest = _manifest(source_run)
    contract_record = _bound(manifest, source_run, contract_path)
    source = case / f"simion/oatof_comsol_524amu_gaussian_N{particle_count}.ion"
    source_record = _bound(manifest, source_run, source)
    lines = [line for line in source.read_text(encoding="ascii").splitlines() if line.strip()]
    if len(lines) != particle_count:
        raise ValueError("voltage compensation requires its complete frozen source at the declared standard count")
    source_table = read_ion_table(source)
    if (source_table["Ion"].tolist() != list(range(1, particle_count+1))
            or not all(math.isfinite(float(value)) for line in lines for value in line.split(","))):
        raise ValueError("source IDs or finite native source state differ")
    if not (source_table["MassAmu"].eq(524.0).all() and source_table["ChargeState"].eq(1).all()):
        raise ValueError("voltage compensation retains its 524 Da singly positive source domain")
    if type(trajectory_quality) is not int or not math.isfinite(regularization) or regularization < 0:
        raise ValueError("trajectory quality must be an integer and regularization finite/nonnegative")
    runtime_receipt_path = case / "simion/simion_runtime_receipt.json"
    runtime_receipt_record = _bound(manifest, source_run, runtime_receipt_path)
    runtime_receipt = _load(runtime_receipt_path)
    if (runtime_receipt.get("role") != "oatof_simion_private_runtime" or runtime_receipt.get("status") != "verified"
            or runtime_receipt.get("canonical_iob_verified") is not True):
        raise ValueError("source runtime lacks verified canonical IOB evidence; run the existing delivery prepare")
    geometry_record = _bound(manifest, source_run, case / "simion/resolved_geometry.json")
    if _load(Path(geometry_record["path"])) != contract:
        raise ValueError("source runtime geometry differs from the consumed resolved contract")
    build_record = _bound(manifest, source_run, case / "logs/build_completion.json")
    build = _load(Path(build_record["path"]))
    operations = build.get("operations")
    if (build.get("role") != "oatof_component_build_completion" or build.get("exception") is not None
            or not isinstance(operations, list) or not operations
            or any(op.get("observation", {}).get("exit_confirmed") is not True
                   or op.get("observation", {}).get("returncode") != 0 for op in operations)):
        raise ValueError("source build has missing or unknown producer completion")
    records = []
    runtime_metadata = {"oatof_ideal_grounded.iob", "oatof_ideal_grounded.con", "oatof_ideal_grounded.fly2",
                        "oatof_resolved.lua", f"oatof_comsol_524amu_gaussian_N{particle_count}.ion"}
    for path in sorted((case / "simion").glob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(case / "simion").as_posix()
        # These are regenerated privately from the consumed resolved contract.
        if relative in {"oatof_ideal_grounded.lua", "reflectron_voltage_profile.lua"}:
            continue
        pa = ".pa" in path.name.lower()
        if not pa and relative not in runtime_metadata:
            continue
        record = _bound(manifest, source_run, path, verify=not pa)
        if pa:
            proofs = [r for r in runtime_receipt.get("files", []) if record_path(r, base_dir=source_run) == path.resolve()]
            if not proofs or any((r.get("bytes"), str(r.get("sha256")).upper()) !=
                                 (record["bytes"], str(record["sha256"]).upper()) for r in proofs):
                raise ValueError("source PA differs from its verified runtime receipt")
        records.append({"relative_path": relative, "pa": pa, "record": record})
    required = {"oatof_ideal_grounded.iob", "oatof_ideal_grounded.con", "oatof_ideal_grounded.fly2", "oatof_resolved.lua", "reflectron.pa0", "accelerator.pa0", "flight_tube_ground.pa0", "detector_ground.pa0", f"oatof_comsol_524amu_gaussian_N{particle_count}.ion"}
    if not required.issubset({r["relative_path"] for r in records}) or not any(r["pa"] for r in records):
        raise ValueError("source lacks the actual workbench, fixed ION or published PA family")
    producer = None
    if numerics_path is not None:
        if particle_count not in (100, 1000):
            raise ValueError("the existing field producer supports only N=100 or N=1000")
        baseline = _bound(manifest, source_run, case / "contracts/candidate_baseline.json")
        frozen_mode = manifest.get("inputs", {}).get("mode")
        if not isinstance(frozen_mode, dict):
            raise ValueError("source manifest lacks its frozen science mode input")
        mode_path = record_path(frozen_mode, base_dir=source_run)
        mode_record = _bound(manifest, source_run, mode_path)
        if str(mode_record["sha256"]).upper() != str(contract["inputs"]["mode_sha256"]).upper():
            raise ValueError("explicit numerics require the source case's frozen science mode")
        numerics = file_record(numerics_path.resolve())
        if not numerics["exists"]:
            raise FileNotFoundError(numerics_path)
        resolved = resolve_contract_documents(_load(Path(baseline["path"])), _load(mode_path), _load(numerics_path),
            input_identity={**contract["inputs"], "solver_numerics_sha256": numerics["sha256"]})
        _require_same_physics(contract, resolved)
        component_plan = compile_component_pa_plan(resolved, repository_root=REPO_ROOT, simion_exe=executable)
        fly2 = case / "simion/oatof_ideal_grounded.fly2"
        seeds = re.findall(r"(?m)^seed\((\d+)\)", fly2.read_text(encoding="utf-8-sig"))
        if len(seeds) != 1:
            raise ValueError("source GUI definition lacks its unique preserved run seed")
        producer = {"numerics": numerics, "baseline": baseline, "science_mode": mode_record,
                    "template_iob": _bound(manifest, source_run, case / "simion/oatof_ideal_grounded.iob"),
                    "template_con": _bound(manifest, source_run, case / "simion/oatof_ideal_grounded.con"),
                    "source_gui_seed": int(seeds[0]), "resolved_contract": resolved, "component_plan": component_plan}
    native_family = any(re.search(r"\.pa(?:[1-9][0-9]*|#)$", r["relative_path"], re.IGNORECASE) for r in records)
    if native_family and predecessor is None and producer is None:
        raise ValueError("published native PA family cannot be reopened, even after a full private copy; "
                         "restore a manifest-bound standalone provider through the existing project producer "
                         "(docs/tools/SIMION_REFERENCE.md#长pa输入路径)")
    previous = None
    if predecessor is not None:
        predecessor = predecessor.resolve()
        if predecessor.name != "run_manifest.json":
            raise ValueError("resume-from requires an explicit parent run_manifest.json")
        previous = _manifest(predecessor.parent)
        if previous.get("mode") != "reflectron_voltage_compensation":
            raise ValueError("resume-from is not a compensation owner run")
        previous = file_record(predecessor)
    return {"schema_version": 1, "role": "reflectron_voltage_compensation_plan", "case_dir": str(case),
            "source_run": str(source_run), "source_manifest": file_record(source_run / "run_manifest.json"),
            "contract": contract_record, "source": source_record, "runtime_receipt": runtime_receipt_record, "runtime_geometry": geometry_record,
            "build_completion": build_record, "runtime_files": records if producer is None else [], "producer": producer,
            "simion_executable": file_record(executable.resolve()), "trajectory_quality": trajectory_quality,
            "regularization": regularization, "particle_count": particle_count,
            "birth_time_range_us": [float(source_table["TobUs"].min()), float(source_table["TobUs"].max())],
            "maximum_electrode": 4 + int(contract["rings"]["stage1_count"]) + int(contract["rings"]["stage2_count"]),
            "maximum_x_mm": float(contract["geometry_mm"]["L_stage1"]) + float(contract["geometry_mm"]["L_stage2"]),
            "predecessor_manifest": previous,
            "native_source_representation": "same_owner_project_producer" if producer is not None else "published_native_family" if native_family else "standalone",
            "native_source_status": "supported" if producer is not None else "blocked_requires_manifest_bound_standalone_provider" if native_family else "blocked_requires_explicit_project_producer",
            "protected_cache_keys": [c["cache_key"] for c in producer["component_plan"]["components"] if c["cacheable"]] if producer else [],
            "committed_new_bytes": producer["component_plan"]["committed_new_bytes"] if producer else sum(r["record"]["bytes"] for r in records) + 256 * 1024**2}


def _require_same_physics(source: dict[str, Any], actual: dict[str, Any]) -> None:
    keys = ("geometry_mm", "geometry_derivation", "particle_source", "electrodes_V", "rings", "coordinate_convention")
    if any(source[key] != actual[key] for key in keys):
        raise ValueError("numerical override changes the source case's physical definition")


def _freeze_producer(run: Path, producer: dict[str, Any]) -> None:
    for name, filename in (("baseline", "candidate_baseline.json"), ("science_mode", "candidate_science_mode.json"),
                           ("numerics", "candidate_solver_numerics.json"), ("template_iob", "source_template.iob"),
                           ("template_con", "source_template.con")):
        verify_record("explicit producer input", producer[name])
        freeze_file(Path(producer[name]["path"]), run / "inputs" / filename)
    resolved = resolve_contract(run / "inputs/candidate_baseline.json", run / "inputs/candidate_science_mode.json",
                                run / "inputs/candidate_solver_numerics.json")
    _require_same_physics(_load(run / "inputs/source_case_resolved_geometry.json"), resolved)
    components = compile_component_pa_plan(resolved, repository_root=run / "inputs/code",
                                           simion_exe=Path(_plan(run)["simion_executable"]["path"]))
    if components != producer["component_plan"]:
        raise ValueError("frozen field producer differs from its admitted component plan")
    _write_json(run / "inputs/candidate_resolved_geometry.json", resolved)
    _write_json(run / "inputs/component_pa_plan.json", components)


def producer_specification(run: Path, capacity_session: Path, context_sha256: str) -> dict[str, Any]:
    plan = _plan(run)
    if not plan.get("producer"):
        raise ValueError("native preparation requires explicit solver numerics and the existing project producer")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", context_sha256 or ""):
        raise ValueError("field producer requires its actual frozen owner context identity")
    session = _load(capacity_session)
    if (session.get("role") != "artifact_workflow_capacity_session" or session.get("status") != "active"
            or run.resolve() not in {Path(p).resolve() for p in session.get("protected_paths", [])}
            or not {k.lower() for k in plan["protected_cache_keys"]}.issubset(
                {k.lower() for k in session.get("protected_cache_keys", [])})):
        raise ValueError("field producer must use this owner's active protected capacity session")
    prepared = run / "inputs/producer_text"
    if not prepared.exists():
        prepare_consumers(run / "inputs/candidate_resolved_geometry.json", prepared,
                          particle_source_seed=plan["producer"]["source_gui_seed"])
    parameters = {"SimionExe": plan["simion_executable"]["path"], "OutputDir": str(run / "simion"),
        "ArtifactProjectRoot": str(run.parents[1]), "TemplateIob": str(run / "inputs/source_template.iob"),
        "RunId": run.name, "ContractPath": str(run / "inputs/candidate_resolved_geometry.json"),
        "CandidateBaselinePath": str(run / "inputs/candidate_baseline.json"),
        "CandidateTextDir": str(prepared / "simion"), "ParticleSeed": str(plan["producer"]["source_gui_seed"]),
        "CapacitySessionPath": str(capacity_session.resolve()), "ComponentPlanPath": str(run / "inputs/component_pa_plan.json"),
        "CompletionPath": str(run / "results/field_provider_completion.json"), "ContextSha256": context_sha256,
        "ParticleCount": plan["particle_count"], "SourceIonPath": str(run / "inputs/source.ion"),
        "DeferRunFinalization": True}
    return {"name": "field_provider", "script_path": str(run / "inputs/code" / f"projects/{PROJECT}/simion/workbench/build_formal_delivery.ps1"),
            "parameters": parameters, "completion_path": parameters["CompletionPath"], "context_sha256": context_sha256,
            "environment": {"OATOF_REFLECTRON_VOLTAGE_COMPENSATION": "0"}}


def _field_binding(plan: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    """Bind scientific coefficients, not transport-sensitive private controllers."""
    components = []
    actual = {c["role"]: c for c in runtime["components"]}
    for expected in plan["producer"]["component_plan"]["components"]:
        item = actual[expected["role"]]
        if expected["cacheable"]:
            asset = item["asset"]
            if (asset["cache_key"] != expected["cache_key"] or asset["response_ids"] != expected["response_ids"]
                    or asset.get("published_native_members_opened") is not False):
                raise ValueError("runtime is not the declared safely reconstructed standalone field")
            components.append({"role": expected["role"], "cache_key": asset["cache_key"],
                "source_raw": asset["source_raw"], "source_responses": asset["source_responses"]})
        else:
            if item["source"] != "fresh_frozen_fractional_gem":
                raise ValueError("fractional ground must remain the existing fresh project producer")
            components.append({"role": expected["role"], "identity": expected["identity"],
                               "operating_voltages_v": expected["operating_voltages_v"]})
    return {"schema_version": 1, "role": "reflectron_compensation_field_binding", "components": components}


def producer_completion(run: Path, context_sha256: str) -> dict[str, Any]:
    """Carry the original producer's native/managed facts to the same PS owner."""
    writer: dict[str, Any] = {"operations": [], "resource_releases": []}
    result: dict[str, Any] = {"writers_stopped": False, "writer_completion": writer, "failure_reason": None,
                              "runtime_prepared": False, "iob_ready": False, "control_binding": None}
    path = run / "results/field_provider_completion.json"
    try:
        append_native_stage_completion(writer, path, role="oatof_component_build_completion", run_id=run.name,
                                       context_sha256=context_sha256, powershell_owner=True)
    except BaseException as error:
        result["failure_reason"] = f"{type(error).__name__}: {error}"
    result["writers_stopped"] = bool(writer["operations"]) and all(
        op["observation"].get("exit_confirmed") is True and type(op["observation"].get("returncode")) is int
        and type(op["observation"].get("process_id")) is int
        and type(op["observation"].get("process_started_at_utc_ticks")) is int for op in writer["operations"])
    if not result["writers_stopped"] or result["failure_reason"]:
        return result
    try:
        report = _load(path)
        if report.get("exception") is not None or any(op["observation"]["returncode"] != 0 for op in writer["operations"]):
            raise ValueError("field producer reported an actual native or preparation failure")
        plan = _plan(run)
        runtime_path = run / "simion/simion_runtime_receipt.json"
        runtime = _load(runtime_path)
        if (runtime.get("role") != "oatof_simion_private_runtime" or runtime.get("status") != "verified"
                or runtime.get("run_id") != run.name or runtime.get("context_sha256") != context_sha256
                or runtime.get("canonical_iob_verified") is not True or runtime.get("published_native_members_opened") is not False):
            raise ValueError("field producer did not verify the actual private runtime")
        iob = run / "simion/oatof_ideal_grounded.iob"
        ion = run / f"simion/oatof_comsol_524amu_gaussian_N{plan['particle_count']}.ion"
        source = runtime.get("source_ion") or {}
        if (runtime.get("source_ion_reused") is not True or Path(source.get("path", "")).resolve() != ion.resolve()
                or source.get("bytes") != plan["source"]["bytes"]
                or str(source.get("sha256")).upper() != str(plan["source"]["sha256"]).upper()
                or Path(runtime["iob"]["path"]).resolve() != iob.resolve() or not iob.is_file()
                or not iob.with_suffix(".lua").is_file() or not ion.is_file()
                or ion.stat().st_size != plan["source"]["bytes"]):
            raise ValueError("IOB or reused original ION binding differs from its actual runtime")
        binding = _field_binding(plan, runtime)
        if plan.get("predecessor_manifest"):
            parent = Path(plan["predecessor_manifest"]["path"]).parent
            _bound(_manifest(parent), parent, parent / "results/field_binding.json")
            if _load(parent / "results/field_binding.json") != binding:
                raise ValueError("actual standalone or fractional field source differs from reused completed units")
        _write_json(run / "results/field_binding.json", binding)
        for name in ("oatof_ideal_grounded.lua", "reflectron_voltage_profile.lua"):
            frozen = run / "inputs" / name
            target = run / "simion" / name
            if frozen.exists():
                if target.exists() and frozen.read_bytes() != target.read_bytes():
                    raise ValueError("producer Program/profile differs from the frozen Fly controls")
                if not target.exists():
                    shutil.copyfile(frozen, target)
        result.update(runtime_prepared=True, iob_ready=True, control_binding={"iob_path": str(iob),
            "program_path": str(iob.with_suffix(".lua")), "source_ion_path": str(run / "inputs/source.ion")})
        _write_json(run / "results/runtime_materialization.json", {"schema_version": 1,
            "role": "reflectron_compensation_runtime_materialization", "kind": "existing_project_producer", "count": 1,
            "runtime_receipt": file_record(runtime_path), "iob_ready": True})
    except BaseException as error:
        result["failure_reason"] = f"{type(error).__name__}: {error}"
    return result


def _plan(run: Path) -> dict[str, Any]:
    return _load(run / "inputs/compensation_plan.json")


def freeze_inputs(run: Path) -> dict[str, Any]:
    plan = _plan(run)
    verify_record("source manifest", plan["source_manifest"])
    for name, destination in (("contract", "candidate_resolved_geometry.json"), ("source", "source.ion"),
                              ("runtime_receipt", "source_runtime_receipt.json"), ("runtime_geometry", "source_runtime_geometry.json"),
                              ("build_completion", "source_build_completion.json")):
        verify_record(name, plan[name])
        freeze_file(Path(plan[name]["path"]), run / "inputs" / ("source_case_resolved_geometry.json" if name == "contract" and plan.get("producer") else destination))
    freeze_file(Path(plan["source_manifest"]["path"]), run / "inputs/source_manifest.json")
    closure = freeze_candidate_source_closure(run / "inputs/code", run.parents[1], Path(sys.executable),
        extra_source_ids=(f"{RELATIVE}/run_compensation.py", f"{RELATIVE}/execute_compensation.ps1",
            "common/simion/batch_continuation.py", "common/simion/particle_batching.py", "common/simion/resource_scheduler.py",
            "common/simion/resource_profile.py", "common/contracts/schemas/simion_batch_continuation.schema.json",
            f"projects/{PROJECT}/analysis/optimize_reflectron_ring_voltages.py",
            f"projects/{PROJECT}/simion/reflectron/export_axis_basis.lua"))
    if plan.get("producer"):
        _freeze_producer(run, plan["producer"])
    _write_json(run / "inputs/source_closure.json", closure)
    basis = run / "results/axis_basis.csv"
    predecessor = plan.get("predecessor_manifest")
    if predecessor:
        verify_record("predecessor manifest", predecessor)
        parent = Path(predecessor["path"]).parent
        manifest = _manifest(parent)
        _bound(manifest, parent, parent / "inputs/compensation_plan.json")
        _bound(manifest, parent, parent / "inputs/source_closure.json")
        evidence = run / "inputs/predecessor_source_closure"
        derived = derive_candidate_source_closure(parent / "run_manifest.json", parent / "inputs/source_closure.json", evidence / "code")
        _write_json(evidence / "source_closure.json", derived["closure"])
        _write_json(evidence / "derivation.json", derived["derivation"])
        previous = _load(parent / "inputs/compensation_plan.json")
        # The basis depends on the published response family and exporter,
        # not on compensation strength, plotting or native Fly controls.
        if _basis_identity(plan) != _basis_identity(previous):
            raise ValueError("compensation PA basis inputs differ from explicit predecessor")
        previous_export = evidence / "code" / f"projects/{PROJECT}/simion/reflectron/export_axis_basis.lua"
        current_export = run / "inputs/code" / f"projects/{PROJECT}/simion/reflectron/export_axis_basis.lua"
        if previous_export.resolve().read_bytes() != current_export.read_bytes():
            raise ValueError("axis basis exporter differs from predecessor")
        source_basis = parent / "results/axis_basis.csv"
        if source_basis.is_file():
            _bound(manifest, parent, source_basis)
            freeze_file(source_basis, basis)
    return {"basis_export_required": not basis.is_file(), "frozen_code_root": str(run / "inputs/code"),
            "source_closure_path": str(run / "inputs/source_closure.json")}


def _basis_identity(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("producer"):
        component = next(c for c in plan["producer"]["component_plan"]["components"] if c["role"] == "reflectron")
        return {"field": component["identity"], "maximum_electrode": plan["maximum_electrode"],
                "maximum_x_mm": plan["maximum_x_mm"], "simion_executable_sha256": plan["simion_executable"]["sha256"]}
    return {"fields": [(r["relative_path"], r["record"]["bytes"], str(r["record"]["sha256"]).upper())
                       for r in plan["runtime_files"] if re.fullmatch(r"reflectron\.pa[1-9][0-9]*", r["relative_path"])],
            "maximum_electrode": plan["maximum_electrode"], "maximum_x_mm": plan["maximum_x_mm"],
            "simion_executable_sha256": plan["simion_executable"]["sha256"]}



def export_specification(run: Path) -> dict[str, Any]:
    plan = _plan(run)
    return {"name": "reflectron_axis_basis", "file_path": plan["simion_executable"]["path"],
            "argument_list": ["--nogui", "--noprompt", "lua", str(run / "inputs/code" / f"projects/{PROJECT}/simion/reflectron/export_axis_basis.lua"),
                              str(run / "simion/reflectron"), str(plan["maximum_electrode"]),
                              str(run / "results/axis_basis.csv"), format(plan["maximum_x_mm"], ".17g")],
            "working_directory": str(run / "simion"), "stdout_path": str(run / "logs/basis_export.stdout.log"),
            "stderr_path": str(run / "logs/basis_export.stderr.log")}



def _scientific_identity(run: Path, plan: dict[str, Any]) -> dict[str, Any]:
    # Actual generated numerical inputs, rather than the orchestration bytes.
    metadata = ([{key: c[key] for key in ("role", "identity", "operating_voltages_v")}
                 for c in plan["producer"]["component_plan"]["components"]] if plan.get("producer") else
                [[r["relative_path"], r["record"]["bytes"], str(r["record"]["sha256"]).upper()] for r in plan["runtime_files"]])
    return {"runtime": metadata, "source_sha256": plan["source"]["sha256"],
            "program_sha256": file_record(run / "inputs/oatof_ideal_grounded.lua")["sha256"],
            "profile_sha256": file_record(run / "inputs/reflectron_voltage_profile.lua")["sha256"],
            "simion_executable_sha256": plan["simion_executable"]["sha256"],
            "trajectory_quality": plan["trajectory_quality"], "modes": list(LABELS),
            "iob_builder_sha256": file_record(run / "inputs/code" / f"projects/{PROJECT}/simion/workbench/build_formal_iob.lua")["sha256"],
            "native_assembly_sha256": file_record(run / "inputs/code/common/simion/assemble_native_fast_adjust_family.lua")["sha256"] if plan.get("producer") else None}


def fit_and_plan(run: Path) -> dict[str, Any]:
    plan = _plan(run)
    contract = _load(run / "inputs/candidate_resolved_geometry.json")
    x, basis = _load_basis(run / "results/axis_basis.csv")
    fit = optimize(x, basis, stage1_count=int(contract["rings"]["stage1_count"]),
        stage2_count=int(contract["rings"]["stage2_count"]),
        stage1_length_mm=float(contract["geometry_mm"]["L_stage1"]), stage2_length_mm=float(contract["geometry_mm"]["L_stage2"]),
        midgrid_voltage_v=float(contract["electrodes_V"]["midgrid"]), backplate_voltage_v=float(contract["electrodes_V"]["backplate"]),
        regularization=plan["regularization"])
    _write_json(run / "results/monotone_voltage_fit.json", fit)
    for name, text in (("reflectron_voltage_profile.lua", render_lua_profile(fit)), ("oatof_ideal_grounded.lua", render_program(contract))):
        (run / "inputs" / name).write_text(text, encoding="utf-8", newline="\n")
        if (run / "results/runtime_materialization.json").exists():
            shutil.copyfile(run / "inputs" / name, run / "simion" / name)
    identity = _scientific_identity(run, plan)
    _write_json(run / "inputs/flight_identity.json", identity)
    parent = Path(plan["predecessor_manifest"]["path"]).parent if plan.get("predecessor_manifest") else None
    if parent:
        manifest = _manifest(parent)
        _bound(manifest, parent, parent / "inputs/flight_identity.json")
        if _load(parent / "inputs/flight_identity.json") != identity:
            raise ValueError("actual compensation Fly inputs differ from predecessor")
    results = []
    for label in LABELS:
        request = {"solver": "SIMION", "field_kind": "electrostatic", "particle_count": plan["particle_count"],
                   "independent_particles": True, "trajectory_quality_profile_id": f"tqual_{plan['trajectory_quality']}"}
        dispatch = plan_simion_dispatch(request, [])
        reuse = []
        partition_path = parent / f"results/{label}.batch_plan.json" if parent else None
        has_prior_partition = partition_path is not None and partition_path.is_file()
        if parent and not has_prior_partition and any((parent / "results/native_batch_completion").glob(f"{label}__*.json")):
            raise ValueError("predecessor has native completion without its frozen particle partition")
        if has_prior_partition:
            _bound(manifest, parent, partition_path)
            partition = _load(partition_path)
            if sum(batch["count"] for batch in partition["batches"]) < plan["particle_count"]:
                # A replan callback can fail after the formal first unit exits.
                # Keep that prefix exactly; only the never-dispatched remainder
                # is newly partitioned by the existing public particle planner.
                prior_batches = partition["batches"]
                full = plan_single_wave_batches(plan["particle_count"], math.ceil(plan["particle_count"]/prior_batches[0]["count"]))
                if prior_batches != full["batches"][:len(prior_batches)]:
                    raise ValueError("partial predecessor units cannot be preserved as a complete partition")
                partition = dict(full, coverage="complete_population")
            units = []
            for batch in partition["batches"]:
                stem = f"{label}__{batch['index']:04d}"
                log = parent / f"logs/simion__batch__{stem}.stdout.log"
                receipt = parent / f"results/native_batch_completion/{stem}.json"
                complete = False
                if receipt.is_file():
                    _bound(manifest, parent, receipt)
                    fact = _load(receipt)
                    complete = (fact.get("role") == "reflectron_compensation_batch_completion" and fact.get("natural_exit") is True
                                and fact.get("exit_code") == 0 and fact.get("label") == label and fact.get("batch") == batch)
                    if not complete:
                        raise ValueError("predecessor completion fact differs from its frozen partition")
                units.append(WholeUnitReplayUnit(stem, (log, receipt), complete))
            replay = build_whole_unit_replay_plan(predecessor_run_dir=parent, output_dir=run / f"results/continuation/{label}", units=units)
            by_key = {u["key"]: u for u in replay["units"]}
            missing = []
            for batch in partition["batches"]:
                stem = f"{label}__{batch['index']:04d}"
                if by_key[stem]["action"] == "reuse":
                    log = parent / f"logs/simion__batch__{stem}.stdout.log"
                    with log.open(encoding="utf-8-sig") as stream:
                        if require_one_fly_completion(stream).splats != batch["count"]:
                            raise ValueError("predecessor completed splats differ from original complete unit")
                    for relative in (f"logs/simion__batch__{stem}.stdout.log", f"results/native_batch_completion/{stem}.json"):
                        destination = run / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(parent / relative, destination)
                    reuse.append(batch["index"])
                else:
                    missing.append(batch["index"])
            _write_json(run / f"results/{label}.batch_plan.json", partition)
            if missing:
                dispatch = prepare_fixed_partition_dispatch(dispatch, partition, missing)
            else:
                dispatch["waves"][0].update(batches=partition["batches"], batch_count=len(partition["batches"]),
                                             particle_count=plan["particle_count"], coverage="complete_population")
        _write_json(run / f"results/{label}.dispatch_plan.json", dispatch)
        _write_json(run / f"results/{label}.reuse.json", {"reused_batch_indices": reuse})
        results.append({"label": label, "reused_batch_indices": reuse, "all_reused": has_prior_partition and len(reuse) == len(partition["batches"]),
                        "dispatch_plan": str(run / f"results/{label}.dispatch_plan.json")})
    native_required = any(not m["all_reused"] for m in results)
    if native_required and (not plan.get("producer") or plan.get("native_source_status", "supported") != "supported"):
        raise ValueError("missing whole units require a manifest-bound standalone field provider; "
                         "published native family copies cannot be used for recovery Fly")
    return {"modes": results, "native_fly_required": native_required}


def materialize_batches(run: Path, label: str, dispatch_path: Path | None = None) -> dict[str, Any]:
    if label not in LABELS:
        raise ValueError("unknown compensation arm")
    plan = _plan(run)
    dispatch = _load(dispatch_path or run / f"results/{label}.dispatch_plan.json")
    partition = batch_plan_from_dispatch(dispatch)
    _write_json(run / f"results/{label}.batch_plan.json", partition)
    reused = _load(run / f"results/{label}.reuse.json")["reused_batch_indices"]
    lines = (run / "inputs/source.ion").read_text(encoding="ascii").splitlines()
    lines = [line for line in lines if line.strip()]
    result = []
    for batch in partition["batches"]:
        index = batch["index"]
        stem = f"{label}__{index:04d}"
        ion = run / f"inputs/batch_sources/{stem}.ion"
        ion.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(lines[batch["particle_id_min"]-1:batch["particle_id_max"]]) + "\n"
        if ion.exists() and ion.read_text(encoding="ascii") != text:
            raise ValueError("frozen batch interval changed after dispatch observation")
        if not ion.exists():
            ion.write_text(text, encoding="ascii", newline="\n")
        # SIMION 2020 requires at least 100 preallocated ion-list slots. This
        # capacity does not change the actual rows in the selected batch ION.
        arguments = ["--default-num-particles", str(max(100, batch["count"])), "--nogui", "fly", "--trajectory-quality", str(plan["trajectory_quality"]),
            "--retain-trajectories", "0", "--particles", str(ion), "--adjustable", f"trajectory_quality={plan['trajectory_quality']}",
            "--adjustable", "ideal_accel_enable=0", "--adjustable", f"ideal_refl_stage1_enable={int(label == 'ideal_reflectron')}",
            "--adjustable", f"ideal_refl_stage2_enable={int(label == 'ideal_reflectron')}", "--adjustable", "trajectory_log_enable=1",
            str(run / "simion/oatof_ideal_grounded.iob")]
        result.append({"batch": batch, "reused": index in reused, "name": stem,
            "file_path": plan["simion_executable"]["path"], "argument_list": arguments, "working_directory": str(run / "simion"),
            "stdout_path": str(run / f"logs/simion__batch__{stem}.stdout.log"), "stderr_path": str(run / f"logs/simion__batch__{stem}.stderr.log"),
            "environment": {"OATOF_REFLECTRON_VOLTAGE_COMPENSATION": str(int(label == "compensated"))}, "ion": str(ion)})
    _write_json(run / f"results/{label}.batches.json", {"batches": result})
    return {"batches": result}


def complete_batch(run: Path, label: str, index: int, process: dict[str, Any]) -> dict[str, Any]:
    case = next(c for c in _load(run / f"results/{label}.batches.json")["batches"] if c["batch"]["index"] == index)
    if process.get("completed") is not True or process.get("exit_code") != 0:
        raise ValueError("native process has no successful natural exit")
    with Path(case["stdout_path"]).open(encoding="utf-8-sig") as stream:
        completion = require_one_fly_completion(stream)
    if completion.splats != case["batch"]["count"]:
        raise ValueError("native completed census differs from whole batch")
    fact = {"schema_version": 1, "role": "reflectron_compensation_batch_completion", "label": label, "batch": case["batch"],
            "natural_exit": True, "exit_code": 0, "native_elapsed_seconds": completion.elapsed_seconds,
            "stdout_relative_path": str(Path(case["stdout_path"]).relative_to(run)), "process": process}
    _write_json(run / f"results/native_batch_completion/{case['name']}.json", fact)
    return fact


def analyze(run: Path) -> dict[str, Any]:
    fit = _load(run / "results/monotone_voltage_fit.json")
    plan = _plan(run)
    modes = {}
    for label in LABELS:
        frames, diagnostics = [], []
        for case in _load(run / f"results/{label}.batches.json")["batches"]:
            fact = _load(run / f"results/native_batch_completion/{case['name']}.json")
            if fact.get("batch") != case["batch"] or fact.get("natural_exit") is not True or fact.get("exit_code") != 0:
                raise ValueError("analysis requires a complete native unit")
            particles, diagnostic = analyze_simion_log(Path(case["stdout_path"]), Path(case["ion"]), mode=label,
                distribution=f"fixedN{plan['particle_count']}_frozen_source", detector_radius_mm=40.0, allow_incomplete_census=False)
            particles["Ion"] += case["batch"]["simion_particle_id_offset"]
            frames.append(particles)
            diagnostics.append(diagnostic)
        particles = pd.concat(frames, ignore_index=True).sort_values("Ion")
        if particles["Ion"].tolist() != list(range(1, plan["particle_count"]+1)):
            raise ValueError("merged compensation mother population is not exactly the original frozen population")
        destination = run / f"results/{label}_particles.csv"
        particles.to_csv(destination, index=False)
        metrics, _ = compute_peak_metrics(particles.loc[particles["Hit"], "TofUs"].to_numpy(dtype=float), 524.0)
        modes[label] = {"label": label, "particle_csv": str(destination), "emitted": len(particles),
                        "crossed": sum(d["Crossed"] for d in diagnostics), "hit": int(particles["Hit"].sum()),
                        "batches": diagnostics, "canonical_peak_metrics": metrics}
    baseline, compensated, ideal = (modes[label]["canonical_peak_metrics"].get("mass_resolution") for label in LABELS)
    supported = all(value is not None and math.isfinite(float(value)) for value in (baseline, compensated, ideal)) and baseline > 0 and ideal > 0
    summary = {"schema_version": 1, "role": "oatof_reflectron_voltage_compensation_closed_loop_receipt", "status": "success",
        "execution_status": "completed", "data_validity": "valid", "scientific_result":
            ("resolution_gain" if compensated > baseline else "no_resolution_gain") if supported else "INCONCLUSIVE",
        "particle_count": plan["particle_count"],
        "field_preparation": _load(run / "results/runtime_materialization.json") if (run / "results/runtime_materialization.json").is_file() else {"kind": "not_required", "count": 0}, "fixed_endpoints_V": fit["fixed_endpoints_V"],
        "monotone_constraints_verified": True, "field_fit": fit["fit"], "modes": modes,
        "resolution_gain_ratio": compensated / baseline if supported else None,
        "remaining_gap_ratio_to_ideal_reflectron": (ideal-compensated)/ideal if supported else None,
        "qualification": "study_only; no geometry, grid, step or resolution qualification promoted",
        "source_record": plan["source"], "birth_time_range_us": plan.get("birth_time_range_us"),
        "source_start": "frozen same-N native ION in source workbench frame; birth times unchanged",
        "trajectory_scope": "source birth to the existing detector observation; no state restart",
        "field_scope": "existing four-instance PA package; compensation toggles process-local fixed-geometry ring voltages; ideal arm uses existing ideal reflectron controls"}
    _write_json(run / "results/compensation_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--simion-exe", type=Path, default=Path(r"C:\Program Files\SIMION-2020\simion.exe"))
    parser.add_argument("--trajectory-quality", type=int, default=8)
    parser.add_argument("--regularization", type=float, default=1e-4)
    parser.add_argument("--particle-count", type=int, choices=(100, 1000, 5000), default=1000,
                        help="consume an already frozen same-N parent ION; never resample")
    parser.add_argument("--numerics-path", type=Path, help="explicit solver numerics for same-owner safe field preparation; never changes Formal defaults")
    parser.add_argument("--run-id")
    parser.add_argument("--resume-from", type=Path, help="explicit terminal parent manifest; creates a new run and reuses complete units")
    parser.add_argument("--resume-finalization", action="store_true", help="finish the original small Result without Fly")
    parser.add_argument("--result-path", type=Path)
    parser.add_argument("--action", choices=("inspect", "freeze", "producer-spec", "producer-complete", "export-spec", "fit", "materialize-batches", "complete-batch", "analyze"), help=argparse.SUPPRESS)
    parser.add_argument("--run", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--label", choices=LABELS, help=argparse.SUPPRESS)
    parser.add_argument("--dispatch-plan", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--process-record", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--capacity-session", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--context-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.resume_finalization:
        run_options = {"--case-dir", "--simion-exe", "--trajectory-quality", "--regularization",
                       "--particle-count", "--numerics-path", "--resume-from", "--action"}
        if any(argument.split("=", 1)[0] in run_options for argument in sys.argv[1:]):
            parser.error("--resume-finalization accepts only the existing --run-id and --result-path")
    if args.action:
        if args.action == "inspect":
            result = inspect_source(args.case_dir, args.simion_exe, args.trajectory_quality, args.regularization, args.resume_from, args.particle_count, args.numerics_path)
        else:
            run = args.run.resolve()
            functions = {"freeze": freeze_inputs, "export-spec": export_specification, "fit": fit_and_plan, "analyze": analyze}
            if args.action == "producer-spec":
                result = producer_specification(run, args.capacity_session, args.context_sha256)
            elif args.action == "producer-complete":
                result = producer_completion(run, args.context_sha256)
            elif args.action == "materialize-batches":
                result = materialize_batches(run, args.label, args.dispatch_plan)
            elif args.action == "complete-batch":
                result = complete_batch(run, args.label, args.index, _load(args.process_record))
            else:
                result = functions[args.action](run)
        print(json.dumps(result, ensure_ascii=False))
        return
    if not args.resume_finalization:
        if args.case_dir is None:
            parser.error("--case-dir is required")
        # Cheap path/error feedback only. The adapter resolves and freezes the
        # actual source plan exactly once before capacity/native admission.
        _load(args.case_dir.resolve() / "contracts/candidate_resolved_geometry.json")
    elif not args.run_id:
        parser.error("--resume-finalization requires the original --run-id")
    command = ["pwsh", "-NoLogo", "-NoProfile", "-File", str(Path(__file__).with_name("execute_compensation.ps1")),
               "-PythonExe", sys.executable]
    if args.resume_finalization:
        command += ["-ResumeFinalization", "-RunId", args.run_id]
        if args.result_path is not None:
            command += ["-ResultPath", str(args.result_path)]
    else:
        command += ["-SimionExe", str(args.simion_exe), "-TrajectoryQuality", str(args.trajectory_quality),
                    "-Regularization", str(args.regularization), "-ParticleCount", str(args.particle_count)]
        for name, value in (("CaseDirectory", args.case_dir), ("RunId", args.run_id),
                            ("ContinuationPredecessorManifestPath", args.resume_from),
                            ("ResultPath", args.result_path), ("NumericsPath", args.numerics_path)):
            if value is not None:
                command += ["-"+name, str(value)]
    # The public PowerShell owner applies the declared native/resource budget;
    # a Python transport deadline must not kill its healthy solver children.
    subprocess.run(command, cwd=REPO_ROOT, timeout=None, check=True)


if __name__ == "__main__":
    main()
