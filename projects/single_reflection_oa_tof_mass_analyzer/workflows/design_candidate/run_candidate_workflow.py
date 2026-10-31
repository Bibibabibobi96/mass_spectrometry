"""Execute one prepared oa-TOF candidate workflow without promoting it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Callable

from common.contracts.particle_count_policy import validate_standard_particle_count
from .candidate_stage_execution import _powershell


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.contracts.stage_reuse import validate_and_write_stage_reuse, write_stage_receipt
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import (
    finalize_candidate_run,
    refresh_candidate_provisional_manifest,
    start_candidate_run,
    update_candidate_progress,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path, verify_candidate_source_closure
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
    freeze_pa_producer_handoffs, plan_pa_producer_handoffs, validate_artifact_capacity,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import compile_component_pa_plan, sum_component_commitments


from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_stage_execution import execute_candidate_stage


StageExecutor = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]
# A long candidate stage is evidence to inspect, never proof that a healthy
# external solver should be killed.  The runner records one warning and waits
# for its admitted child to complete naturally.
STAGE_PROCESS_WARNING_S = 4 * 60 * 60
CAD_PYTHON_PREFLIGHT_TIMEOUT_S = 30
REUSABLE_STAGES = ("comsol_candidate", "simion_candidate", "cad_candidate")
STAGE_SOURCE_PREFIXES = {
    "comsol_candidate": (
        "common/comsol/",
        "projects/single_reflection_oa_tof_mass_analyzer/comsol/",
        "projects/single_reflection_oa_tof_mass_analyzer/analysis/analyze_comsol_detector_events.py",
        "projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis.py",
        "projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py",
        "projects/single_reflection_oa_tof_mass_analyzer/load_oatof_contract.m",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_assert_formal_write_authorized.m",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_stage_execution.py",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py",
    ),
    "simion_candidate": (
        "projects/single_reflection_oa_tof_mass_analyzer/simion/",
        "common/ion_release/dotnet_gaussian_box_ion11.py",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_stage_execution.py",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_simion_stage.py",
    ),
    "cad_candidate": (
        "common/comsol/",
        "common/solidworks/",
        "projects/single_reflection_oa_tof_mass_analyzer/cad/",
        "projects/single_reflection_oa_tof_mass_analyzer/load_oatof_contract.m",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_assert_formal_write_authorized.m",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_cad_sync.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_stage_execution.py",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_cad_stage.py",
    ),
}


class CandidateWorkflowError(RuntimeError):
    def __init__(self, message: str, run_root: Path):
        super().__init__(message)
        self.run_root = run_root


class CandidateWorkflowInterrupted(KeyboardInterrupt):
    def __init__(self, run_root: Path):
        super().__init__(f"candidate workflow interrupted: {run_root}")
        self.run_root = run_root


class CandidateWorkflowTimedOut(TimeoutError):
    def __init__(self, run_root: Path):
        super().__init__(f"candidate workflow timed out: {run_root}")
        self.run_root = run_root


class StageTimedOut(TimeoutError):
    pass




def _run_command(command: list[str], log_path: Path, environment: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(environment or {})
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        started = time.monotonic()
        warned = False
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if not warned and elapsed > STAGE_PROCESS_WARNING_S:
                    message = (
                        f"CANDIDATE_STAGE_WARNING elapsed_seconds={elapsed:.3f} "
                        f"warning_seconds={STAGE_PROCESS_WARNING_S}; continuing pid={process.pid}"
                    )
                    print(message, file=log, flush=True)
                    warnings.warn(message, RuntimeWarning, stacklevel=2)
                    warned = True
                time.sleep(1)
        except KeyboardInterrupt:
            # The user may cancel the Python coordinator, but its already
            # admitted solver remains a healthy process until it ends itself.
            print("CANDIDATE_STAGE_WAITING_FOR_NATURAL_COMPLETION", file=log, flush=True)
            process.wait()
            raise
    if process.returncode != 0:
        raise RuntimeError(f"command failed with exit code {process.returncode}; log={log_path}")




def _run_managed_stage_command(
    command: list[str], log_path: Path, plan: dict[str, Any], receipt_path: Path,
    role: str, environment: dict[str, str] | None = None,
) -> None:
    """Carry the actual native and host-owner receipts across the PS boundary."""
    writer = plan.get("writer_completion")
    failure = None
    try:
        _run_command(command, log_path, environment)
    except BaseException as error:
        failure = error
    try:
        if writer is not None:
            release_id = receipt_path.stem
            if not receipt_path.is_file():
                writer["operations"].append({"operation_id": release_id,
                    "observation": {"exit_confirmed": False, "returncode": None},
                    "resource_release_id": release_id})
            else:
                receipt = load_json(receipt_path)
                if receipt.get("schema_version") != 1 or receipt.get("role") != role or receipt.get("run_id") != plan["run_id"]:
                    raise RuntimeError(f"native completion identity differs: {receipt_path}")
                if role in {"oatof_component_build_completion", "oatof_candidate_flight_process_result"} and receipt.get("context_sha256") != plan["context_sha256"]:
                    raise RuntimeError(f"native completion scientific context differs: {receipt_path}")
                if role == "oatof_candidate_flight_process_result":
                    operations = [{"operation_id": "flight", "observation": {
                        "exit_confirmed": receipt.get("native_exit_confirmed", False),
                        "returncode": receipt.get("native_returncode")},
                        "managed_process_completion": receipt.get("managed_process_completion")}]
                else:
                    operations = receipt["operations"]
                for operation in operations:
                    observation = operation["observation"]
                    if role in {"oatof_component_build_completion", "oatof_candidate_flight_process_result"}:
                        managed = operation.get("managed_process_completion") or {}
                        if (managed.get("schema_version") != 1
                                or managed.get("role") != "repository_managed_python_completion"
                                or type(managed.get("exit_code")) is not int
                                or any(managed.get(key) is not True for key in (
                                    "ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed",
                                    "stdout_drained", "stderr_drained"))
                                or type(managed.get("worker_process_id")) is not int
                                or managed["worker_process_id"] <= 0
                                or type(managed.get("worker_started_at_utc_ticks")) is not int
                                or managed["worker_started_at_utc_ticks"] <= 0):
                            raise RuntimeError(f"managed writer completion is unconfirmed: {operation['operation_id']}")
                        if managed["exit_code"] and failure is None:
                            failure = RuntimeError(f"managed writer failed ({managed['exit_code']}): {operation['operation_id']}")
                    writer["operations"].append({
                        "operation_id": f"{release_id}.{operation['operation_id']}",
                        "observation": {key: observation.get(key) for key in ("exit_confirmed", "returncode")},
                        "resource_release_id": release_id,
                    })
                if operations:
                    writer["resource_releases"].append({"release_id": release_id, "completion_receipt": receipt})
    except BaseException as receipt_error:
        if writer is not None:
            writer["operations"].append({"operation_id": receipt_path.stem + ".unconfirmed",
                "observation": {"exit_confirmed": False, "returncode": None},
                "resource_release_id": receipt_path.stem})
        if failure is None:
            raise
        failure.add_note(f"Native completion validation also failed: {receipt_error}")
    if failure is not None:
        raise failure






def _verify_frozen_cad_python(closure: dict[str, Any], log_path: Path) -> str:
    """Fail before commercial stages when the frozen SolidWorks COM bridge is unavailable."""
    runtime = closure.get("runtime", {})
    python_executable = Path(str(runtime.get("python_executable", ""))).resolve()
    if not python_executable.is_file():
        raise RuntimeError(f"candidate CAD Python runtime is unavailable: {python_executable}")
    try:
        result = subprocess.run(
            [str(python_executable), "-c", "import pythoncom; import win32com.client; print('PYWIN32=PASS')"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CAD_PYTHON_PREFLIGHT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"candidate CAD Python runtime preflight timed out after {CAD_PYTHON_PREFLIGHT_TIMEOUT_S}s"
        ) from error
    output = (result.stdout or "") + (result.stderr or "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8", newline="\n")
    if result.returncode != 0:
        detail = output.strip() or "no diagnostic output"
        raise RuntimeError(
            "candidate CAD Python runtime preflight failed: frozen runtime cannot import "
            f"pythoncom and win32com.client; python={python_executable}; detail={detail}"
        )
    return str(python_executable)




def _ps_arguments(values: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in values.items():
        result.extend([f"-{key}", str(value)])
    return result


def execute_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str) -> dict[str, Any]:
    stage_id = stage["stage_id"]
    if stage_id in {"comsol_candidate", "simion_candidate", "cad_candidate"}:
        if stage_id == "simion_candidate" and stage.get("status") == "blocked_requires_explicit_nonformal_template":
            raise RuntimeError("candidate SIMION stage is blocked until an explicit non-Formal template is frozen")
        return execute_candidate_stage(stage, plan, simion_exe, runtime=sys.modules[__name__])
    closure = plan.get("execution_source_closure")
    if closure is not None:
        verify_candidate_source_closure(closure)
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
    if stage_id == "static_inputs":
        if closure is None:
            raise RuntimeError("candidate source closure is required")
        output = Path(stage["pending_output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        command = _powershell(
            frozen_source_path(closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1"),
            _ps_arguments(stage["arguments"]),
        )
        _run_command(command, logs / "static_inputs.log")
        if not output.is_file():
            raise RuntimeError(f"candidate particle table was not generated: {output}")
        return {"particle_table": str(output)}
    if stage_id == "structural_acceptance":
        evidence = {item["stage_id"]: item.get("evidence", {}) for item in plan["stage_results_so_far"]}
        required = {
            "static_inputs": ("particle_table",),
            "comsol_candidate": ("model", "sync_report", "analysis_request", "analysis_receipt"),
            "simion_candidate": (
                "iob", "ion_n100", "stage_summary", "runtime_report",
                "transport_summary", "particle_csv", "transport_diagnostics",
            ),
            "cad_candidate": ("cad_report",),
        }
        for source_stage, keys in required.items():
            for key in keys:
                path = Path(evidence.get(source_stage, {}).get(key, ""))
                if not path.is_file():
                    raise RuntimeError(f"cross-stage evidence is missing: {source_stage}.{key}")
        comsol_ion = Path(evidence["static_inputs"]["particle_table"])
        simion_ion = Path(evidence["simion_candidate"]["ion_n100"])
        validate_standard_particle_count(
            sum(1 for line in comsol_ion.read_text(encoding="utf-8").splitlines() if line.strip())
        )
        if sha256(comsol_ion).lower() != sha256(simion_ion).lower():
            raise RuntimeError("COMSOL and SIMION candidate N=100 particle tables differ")
        transport = load_json(Path(evidence["simion_candidate"]["transport_summary"]))
        if (
            transport.get("status") != "success"
            or transport.get("ion", {}).get("sha256", "").lower() != sha256(simion_ion).lower()
            or any(transport.get(key) != 100 for key in ("emitted", "crossed", "hit"))
            or transport.get("particle_csv", {}).get("sha256", "").lower()
            != sha256(Path(evidence["simion_candidate"]["particle_csv"])).lower()
        ):
            raise RuntimeError("SIMION candidate transport evidence is incomplete or changed")
        output_dir = Path(stage["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        acceptance = {
            "schema_version": 1,
            "role": "oa_tof_candidate_acceptance",
            "status": "success",
            "scope": stage["acceptance_scope"],
            "performance_claim_allowed": bool(stage["performance_claim_allowed"]),
            "formal_modified": False,
            "promotion_authorized": False,
            "shared_particle_table_sha256": sha256(comsol_ion),
            "simion_transport_particles": 100,
            "simion_transport_evidence_only": True,
            "comsol_simion_particle_level_comparison": "not_run",
            "evidence": evidence,
        }
        path = output_dir / "candidate_acceptance.json"
        path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"acceptance": str(path), "scope": acceptance["scope"]}
    return execute_candidate_stage(stage, plan, simion_exe, runtime=sys.modules[__name__])


def _write_identity(path: Path, stage_id: str, category: str, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "role": "oa_tof_candidate_stage_identity",
        "stage_id": stage_id,
        "category": category,
        "records": sorted(records, key=lambda item: item["name"]),
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _identity_record(name: str, path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {"name": name, "bytes": resolved.stat().st_size, "sha256": sha256(resolved)}


def _stage_source_paths(closure: dict[str, Any], stage_id: str) -> list[Path]:
    prefixes = STAGE_SOURCE_PREFIXES[stage_id]
    paths = []
    code_root = Path(closure["code_root"])
    for source in closure.get("sources", []):
        source_id = str(source.get("source_id", ""))
        if any(source_id == prefix or source_id.startswith(prefix) for prefix in prefixes):
            paths.append(code_root / source_id)
    if not paths:
        raise RuntimeError(f"candidate source closure has no sources for {stage_id}")
    return paths


def _stage_context(
    run_root: Path,
    runtime_plan: dict[str, Any],
    stage_id: str,
    simion_exe: str,
    *,
    cad_model: Path | dict[str, Any] | None = None,
) -> dict[str, dict[str, Path]]:
    inputs = run_root / "inputs"
    candidate = runtime_plan["candidate_inputs"]
    names = {
        "comsol_candidate": (
            "candidate_baseline.json",
            "candidate_resolved_geometry.json",
            "candidate_solver_numerics.json",
            "candidate_diff.json",
        ),
        "simion_candidate": (
            "candidate_baseline.json",
            "candidate_resolved_geometry.json",
            "candidate_solver_numerics.json",
            "candidate_simion_template_source_iob",
            "candidate_simion_template_source_con",
            "candidate_simion_template_registration_manifest",
        ),
        "cad_candidate": (
            "candidate_resolved_geometry.json",
            "candidate_solver_numerics.json",
        ),
    }[stage_id]
    input_paths = [Path(candidate[name]["path"]) for name in names]
    particle_table = inputs / "oatof_candidate_N100.ion"
    if stage_id in {"comsol_candidate", "simion_candidate"}:
        input_paths.append(particle_table)
    if stage_id == "cad_candidate":
        if cad_model is None:
            raise RuntimeError("CAD stage context requires the actual Candidate MPH identity")
        if isinstance(cad_model, dict):
            model_record = {
                "name": "candidate_mph",
                "bytes": cad_model["bytes"],
                "sha256": str(cad_model["sha256"]).upper(),
            }
        else:
            model_record = _identity_record("candidate_mph", cad_model)
        model_identity = inputs / "stage_contexts" / stage_id / "candidate_mph.json"
        _write_identity(model_identity, stage_id, "inputs", [model_record])
        input_paths.append(model_identity)

    solver_paths = [Path(candidate["candidate_solver_numerics.json"]["path"])]
    closure = runtime_plan["execution_source_closure"]
    if stage_id == "simion_candidate":
        identity = inputs / "stage_contexts" / stage_id / "simion_executable.json"
        _write_identity(
            identity,
            stage_id,
            "solver",
            [_identity_record("simion_executable", Path(simion_exe))],
        )
        solver_paths.append(identity)
    if stage_id == "cad_candidate":
        identity = inputs / "stage_contexts" / stage_id / "python_executable.json"
        _write_identity(
            identity,
            stage_id,
            "solver",
            [
                _identity_record(
                    "python_executable",
                    Path(closure["runtime"]["python_executable"]),
                )
            ],
        )
        solver_paths.append(identity)
    source_paths = _stage_source_paths(closure, stage_id)
    return {
        "inputs": {
            f"{stage_id}_input_{index:03d}": path
            for index, path in enumerate(input_paths)
        },
        "source": {
            f"{stage_id}_source_{index:03d}": path
            for index, path in enumerate(source_paths)
        },
        "solver": {
            f"{stage_id}_solver_{index:03d}": path
            for index, path in enumerate(solver_paths)
        },
    }


def _declare_context_inputs(
    run_root: Path,
    contexts: dict[str, dict[str, dict[str, Path]]],
    *,
    provenance: bool,
) -> None:
    config_path = run_root / "run_config.json"
    config = load_json(config_path)
    particle_table = run_root / "inputs" / "oatof_candidate_N100.ion"
    config["inputs"]["candidate_particle_table"] = str(particle_table.resolve())
    config["input_sha256"]["candidate_particle_table"] = sha256(particle_table)
    for context in contexts.values():
        for entries in context.values():
            for name, path in entries.items():
                config["inputs"][name] = str(path.resolve())
                config["input_sha256"][name] = sha256(path)
    if provenance:
        path = run_root / "inputs" / "stage_reuse_provenance.json"
        config["inputs"]["stage_reuse_provenance"] = str(path)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _bind_provenance_hash(run_root: Path) -> None:
    config_path = run_root / "run_config.json"
    config = load_json(config_path)
    path = run_root / "inputs" / "stage_reuse_provenance.json"
    config["input_sha256"]["stage_reuse_provenance"] = sha256(path)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _verify_frozen_run_inputs(
    run_root: Path,
    *,
    allow_pending_provenance: bool = False,
) -> None:
    config = load_json(run_root / "run_config.json")
    inputs = config.get("inputs", {})
    hashes = config.get("input_sha256", {})
    for name, value in inputs.items():
        path = Path(value)
        if (
            allow_pending_provenance
            and name == "stage_reuse_provenance"
            and not path.exists()
        ):
            continue
        expected = hashes.get(name)
        if not expected or not path.is_file() or sha256(path) != str(expected).upper():
            raise RuntimeError(f"frozen candidate run input changed: {name}")


def _verify_identity_descriptor(path: Path, actual: Path, label: str) -> None:
    record = load_json(path)["records"][0]
    if (
        not actual.is_file()
        or actual.stat().st_size != record["bytes"]
        or sha256(actual) != str(record["sha256"]).upper()
    ):
        raise RuntimeError(f"{label} differs from its frozen identity descriptor")


def _receipt_outputs(evidence: dict[str, Any]) -> dict[str, Path]:
    return {
        name: Path(value)
        for name, value in evidence.items()
        if isinstance(value, str) and Path(value).is_file()
    }


def _reused_evidence(
    parent_root: Path,
    provenance_path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict[str, Any]]]]:
    provenance = load_json(provenance_path)
    evidence: dict[str, dict[str, str]] = {}
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for stage in provenance["reused_stages"]:
        evidence[stage["stage_id"]] = {
            name: str(parent_root / record["path"])
            for name, record in stage["outputs"].items()
        }
        records[stage["stage_id"]] = stage["outputs"]
    return evidence, records


def _verify_reused_output(path: Path, record: dict[str, Any], label: str) -> None:
    if (
        not path.is_file()
        or path.stat().st_size != record["bytes"]
        or sha256(path) != str(record["sha256"]).upper()
    ):
        raise RuntimeError(f"reused {label} changed after provenance validation")


def _remaining_results(stages: list[dict[str, Any]], completed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done = {item["stage_id"] for item in completed}
    return completed + [
        {"stage_id": stage["stage_id"], "status": "blocked"} for stage in stages if stage["stage_id"] not in done
    ]


def _failure_results(
    stages: list[dict[str, Any]],
    completed: list[dict[str, Any]],
    stage_id: str,
    *,
    status: str,
    error: str,
    failure_class: str | None = None,
) -> list[dict[str, Any]]:
    kept = [item for item in completed if item.get("stage_id") != stage_id]
    failure = {"stage_id": stage_id, "status": status, "error": error}
    if failure_class:
        failure["failure_class"] = failure_class
    declared = [item["stage_id"] for item in stages]
    if stage_id not in declared:
        stage_id = next(
            identifier for identifier in declared if identifier not in {
                item.get("stage_id") for item in kept
            }
        )
        failure["stage_id"] = stage_id
    prefix = []
    for identifier in declared:
        match = next((item for item in kept if item.get("stage_id") == identifier), None)
        if match is not None:
            prefix.append(match)
            continue
        if identifier == stage_id:
            prefix.append(failure)
            break
        prefix.append({"stage_id": identifier, "status": "blocked"})
    return _remaining_results(stages, prefix)


def _execute_candidate_stages(
    plan_path: Path,
    simion_exe: str,
    stage_executor: StageExecutor = execute_stage,
    *,
    reuse_parent: Path | None = None,
    reuse_through: str | None = None,
    initialized_config_path: Path | None = None,
    execution_context: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if (reuse_parent is None) != (reuse_through is None):
        raise ValueError("reuse_parent and reuse_through must be supplied together")
    if reuse_through is not None and reuse_through not in REUSABLE_STAGES:
        raise ValueError(f"unsupported reuse boundary: {reuse_through}")
    prepared_plan = load_json(Path(plan_path).resolve())
    if prepared_plan.get("status") != "EXECUTION_READY":
        raise ValueError(
            "candidate plan is not execution-ready: "
            f"{prepared_plan.get('status', 'missing status')}"
        )
    run_root = start_candidate_run(plan_path, initialized_config_path=initialized_config_path)
    runtime_plan_path = run_root / "candidate_workflow_plan.json"
    runtime_plan = load_json(runtime_plan_path)
    if execution_context is not None:
        runtime_plan.update(execution_context)
        component_path = run_root / "inputs" / "component_pa_plan.json"
        write_json_atomic(component_path, execution_context["component_pa_plan"])
        runtime_plan["component_plan_path"] = str(component_path)
        config_path = run_root / "run_config.json"
        config = load_json(config_path)
        config["inputs"]["component_pa_plan"] = str(component_path)
        config["input_sha256"]["component_pa_plan"] = sha256(component_path)
        if handoff_plan := execution_context.get("pa_producer_handoffs"):
            bound = freeze_pa_producer_handoffs(run_root, handoff_plan,
                expected_cache_keys={item["cache_key"] for item in execution_context["component_pa_plan"]["components"] if item["cacheable"]},
                capacity_session=load_json(Path(execution_context["capacity_session_path"])))
            config["pa_producer_handoffs"] = {key: bound[key] for key in ("path", "exists", "bytes", "sha256")}
            runtime_plan["producer_handoff_path"] = bound["path"]
            for index, record in enumerate(bound["frozen_input_records"]):
                name = f"pa_producer_handoff_{index}"
                config["inputs"][name] = record["path"]
                config["input_sha256"][name] = record["sha256"]
        write_json_atomic(config_path, config)
        refresh_candidate_provisional_manifest(run_root)
    stages = runtime_plan["stages"]
    results: list[dict[str, Any]] = []
    current_stage = "orchestration"
    try:
        static_stage = stages[0]
        if static_stage["stage_id"] != "static_inputs":
            raise RuntimeError("candidate workflow must begin with static_inputs")
        current_stage = "static_inputs"
        runtime_plan["stage_results_so_far"] = results
        static_evidence = stage_executor(static_stage, runtime_plan, simion_exe)
        results.append(
            {
                "stage_id": "static_inputs",
                "status": "success",
                "execution": "executed",
                "evidence": static_evidence,
            }
        )
        reused: dict[str, dict[str, str]] = {}
        reused_records: dict[str, dict[str, dict[str, Any]]] = {}
        reuse_set: set[str] = set()
        contexts: dict[str, dict[str, dict[str, Path]]] = {}
        cad_model_path: Path | None = None
        contexts["comsol_candidate"] = _stage_context(
            run_root, runtime_plan, "comsol_candidate", simion_exe
        )
        contexts["simion_candidate"] = _stage_context(
            run_root, runtime_plan, "simion_candidate", simion_exe
        )
        _declare_context_inputs(
            run_root,
            contexts,
            provenance=reuse_parent is not None,
        )
        refresh_candidate_provisional_manifest(run_root)
        _verify_frozen_run_inputs(
            run_root,
            allow_pending_provenance=reuse_parent is not None,
        )
        if reuse_through is not None:
            current_stage = "comsol_candidate"
            boundary = REUSABLE_STAGES.index(reuse_through)
            reuse_set = set(REUSABLE_STAGES[: boundary + 1])
            parent_root = Path(reuse_parent).resolve(strict=True)
            if "cad_candidate" in reuse_set:
                parent_cad_receipt = load_json(
                    parent_root / "stage_receipts" / "cad_candidate.json"
                )
                parent_mph_identity_record = parent_cad_receipt["context"]["inputs"][
                    "cad_candidate_input_002"
                ]
                parent_mph_identity = load_json(
                    parent_root / parent_mph_identity_record["path"]
                )["records"][0]
                contexts["cad_candidate"] = _stage_context(
                    run_root,
                    runtime_plan,
                    "cad_candidate",
                    simion_exe,
                    cad_model=parent_mph_identity,
                )
                _declare_context_inputs(run_root, contexts, provenance=True)
                refresh_candidate_provisional_manifest(run_root)
            provenance = validate_and_write_stage_reuse(
                run_root,
                parent_run_root=parent_root,
                project="single_reflection_oa_tof_mass_analyzer",
                stage_contexts={
                    stage_id: contexts[stage_id]
                    for stage_id in REUSABLE_STAGES
                    if stage_id in reuse_set
                },
                allow_provisional_manifest=True,
            )
            _bind_provenance_hash(run_root)
            refresh_candidate_provisional_manifest(run_root)
            reused, reused_records = _reused_evidence(parent_root, provenance)
            if "comsol_candidate" in reuse_set:
                cad_model_path = Path(reused["comsol_candidate"]["model"])
            if "cad_candidate" not in contexts:
                contexts["cad_candidate"] = _stage_context(
                    run_root,
                    runtime_plan,
                    "cad_candidate",
                    simion_exe,
                    cad_model=reused_records["comsol_candidate"]["model"],
                )
                _declare_context_inputs(run_root, contexts, provenance=True)
                refresh_candidate_provisional_manifest(run_root)

        for stage in stages[1:]:
            current_stage = stage["stage_id"]
            runtime_plan["stage_results_so_far"] = results
            _verify_frozen_run_inputs(run_root)
            if current_stage in reuse_set:
                evidence = reused[current_stage]
                results.append(
                    {
                        "stage_id": current_stage,
                        "status": "success",
                        "execution": "reused",
                        "reused_from_run_id": Path(reuse_parent).name,
                        "evidence": evidence,
                    }
                )
                continue
            if current_stage == "structural_acceptance":
                for reused_stage, output_records in reused_records.items():
                    for name, record in output_records.items():
                        _verify_reused_output(
                            Path(reused[reused_stage][name]),
                            record,
                            f"{reused_stage}.{name}",
                        )
            stage_for_execution = dict(stage)
            if current_stage == "cad_candidate":
                if cad_model_path is None:
                    raise RuntimeError(
                        "CAD stage has no verified COMSOL model evidence"
                    )
                stage_for_execution["model_path"] = str(cad_model_path)
                if "comsol_candidate" in reuse_set and cad_model_path is not None:
                    _verify_reused_output(
                        cad_model_path,
                        reused_records["comsol_candidate"]["model"],
                        "comsol_candidate.model",
                    )
            if current_stage == "simion_candidate":
                _verify_identity_descriptor(
                    next(
                        path
                        for path in contexts["simion_candidate"]["solver"].values()
                        if path.name == "simion_executable.json"
                    ),
                    Path(simion_exe),
                    "SIMION executable",
                )
            if current_stage == "cad_candidate":
                _verify_identity_descriptor(
                    next(
                        path
                        for path in contexts["cad_candidate"]["inputs"].values()
                        if path.name == "candidate_mph.json"
                    ),
                    Path(stage_for_execution["model_path"]),
                    "Candidate MPH",
                )
                _verify_identity_descriptor(
                    next(
                        path
                        for path in contexts["cad_candidate"]["solver"].values()
                        if path.name == "python_executable.json"
                    ),
                    Path(runtime_plan["execution_source_closure"]["runtime"]["python_executable"]),
                    "CAD Python executable",
                )
            evidence = stage_executor(stage_for_execution, runtime_plan, simion_exe)
            if current_stage == "cad_candidate":
                _verify_identity_descriptor(
                    next(
                        path
                        for path in contexts["cad_candidate"]["inputs"].values()
                        if path.name == "candidate_mph.json"
                    ),
                    Path(stage_for_execution["model_path"]),
                    "Candidate MPH",
                )
            if (
                current_stage == "cad_candidate"
                and "comsol_candidate" in reuse_set
            ):
                _verify_reused_output(
                    Path(stage_for_execution["model_path"]),
                    reused_records["comsol_candidate"]["model"],
                    "comsol_candidate.model",
                )
            if current_stage == "comsol_candidate" and "model" in evidence:
                cad_model_path = Path(evidence["model"]).resolve(strict=True)
            elif current_stage == "comsol_candidate":
                raise RuntimeError(
                    "COMSOL stage did not return model evidence for CAD"
                )
            if (
                current_stage == "comsol_candidate"
                and "cad_candidate" not in contexts
            ):
                contexts["cad_candidate"] = _stage_context(
                    run_root,
                    runtime_plan,
                    "cad_candidate",
                    simion_exe,
                    cad_model=cad_model_path,
                )
                _declare_context_inputs(
                    run_root,
                    contexts,
                    provenance=reuse_parent is not None,
                )
                refresh_candidate_provisional_manifest(run_root)
            results.append(
                {
                    "stage_id": current_stage,
                    "status": "success",
                    "execution": "executed",
                    "evidence": evidence,
                }
            )
            if current_stage in REUSABLE_STAGES:
                _verify_frozen_run_inputs(run_root)
                update_candidate_progress(run_root, results, stages)
                write_stage_receipt(
                    run_root,
                    project="single_reflection_oa_tof_mass_analyzer",
                    stage_id=current_stage,
                    context=contexts[current_stage],
                    outputs=_receipt_outputs(evidence),
                    allow_provisional_manifest=True,
                )
                refresh_candidate_provisional_manifest(run_root)
        _verify_frozen_run_inputs(run_root)
        current_stage = stages[-1]["stage_id"]
        summary, _ = finalize_candidate_run(run_root, "success", results, publish=initialized_config_path is None)
        return run_root, summary
    except KeyboardInterrupt as exc:
        interrupted = _failure_results(
            stages,
            results,
            current_stage,
            status="interrupted",
            error=str(exc),
        )
        summary, _ = finalize_candidate_run(run_root, "interrupted", interrupted, current_stage,
                                           publish=initialized_config_path is None)
        error = CandidateWorkflowInterrupted(run_root)
        error.summary = summary
        raise error from exc
    except StageTimedOut as exc:
        failed = _failure_results(
            stages,
            results,
            current_stage,
            status="failed",
            error=str(exc),
            failure_class="timeout",
        )
        summary, _ = finalize_candidate_run(run_root, "failed", failed, current_stage,
                                           publish=initialized_config_path is None)
        error = CandidateWorkflowTimedOut(run_root)
        error.summary = summary
        raise error from exc
    except Exception as exc:
        failed = _failure_results(
            stages,
            results,
            current_stage,
            status="failed",
            error=str(exc),
        )
        summary, _ = finalize_candidate_run(run_root, "failed", failed, current_stage,
                                           publish=initialized_config_path is None)
        error = CandidateWorkflowError(str(exc), run_root)
        error.summary = summary
        raise error from exc


def _prepare_execution_request(
    plan_path: Path, simion_exe: str, reuse_parent: Path | None, reuse_through: str | None,
    pa_producer_handoffs: list[tuple[Path, Path]] | None = None,
) -> dict[str, Any]:
    """Read the frozen plan and reserve disk from its explicit authorities."""
    plan_path = plan_path.resolve(strict=True)
    plan = load_json(plan_path)
    if plan.get("status") != "EXECUTION_READY":
        raise ValueError(f"candidate plan is not execution-ready: {plan.get('status')}")
    if (reuse_parent is None) != (reuse_through is None) or (
        reuse_through is not None and reuse_through not in REUSABLE_STAGES
    ):
        raise ValueError("candidate reuse requires a parent and a declared stage boundary")
    closure = plan["execution_source_closure"]
    verify_candidate_source_closure(closure)
    for name, record in plan["candidate_inputs"].items():
        path = Path(record["path"])
        if not path.is_file() or sha256(path) != str(record["sha256"]).upper():
            raise ValueError(f"planned candidate input changed before admission: {name}")
    code_root = Path(closure["code_root"]).resolve(strict=True)
    resolved_path = Path(plan["candidate_inputs"]["candidate_resolved_geometry.json"]["path"])
    runtime_path = Path(plan["candidate_inputs"]["candidate_runtime.json"]["path"])
    capacity = validate_artifact_capacity(load_json(runtime_path))
    if capacity != plan.get("artifact_capacity"):
        raise ValueError("candidate disk commitment differs from its frozen runtime contract")
    component_plan = compile_component_pa_plan(
        load_json(resolved_path), repository_root=code_root, simion_exe=Path(simion_exe).resolve(strict=True),
    )
    template_path = plan_path.parent / "run_config.template.json"
    run_root = Path(plan["run_root"]).resolve()
    cache_keys = {item["cache_key"] for item in component_plan["components"] if item["cacheable"]}
    handoff_plan = plan_pa_producer_handoffs(pa_producer_handoffs, expected_cache_keys=cache_keys,
        artifact_root=run_root.parents[3]) if pa_producer_handoffs else None
    protected = [str(plan_path.parent)]
    if reuse_parent is not None:
        # The existing reuse validator later proves each exact consumed file.
        # Protect the explicit predecessor before admission can reclaim it.
        protected.append(str(reuse_parent.resolve(strict=True)))
    if handoff_plan:
        protected.extend(handoff_plan["protected_paths"])
    entrypoint = Path(frozen_source_path(closure,
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py"))
    return {
        "schema_version": 1, "role": "run_artifact_workflow_request",
        "repository_root": str(REPO_ROOT), "python_executable": closure["runtime"]["python_executable"],
        "package": {
            "project": "single_reflection_oa_tof_mass_analyzer", "run_id": plan["run_id"],
            "mode": "design_candidate", "artifact_project_root": str(run_root.parent.parent),
            "software": ["COMSOL", "SIMION", "SolidWorks"], "retention_class": "solver_review",
            "retention_reason": "Candidate MPH, CAD and private SIMION delivery remain available for explicit structural review; no promotion is authorized.",
        },
        "capacity": {
            "committed_new_bytes": sum_component_commitments([component_plan]) + sum(
                capacity[key] for key in ("comsol_bytes", "cad_bytes", "evidence_bytes")),
            "commitment_inputs": [file_record(path) for path in (plan_path, template_path, runtime_path, resolved_path)]
                + (handoff_plan["source_records"] if handoff_plan else []),
            "protected_paths": sorted(set(protected)),
            "protected_cache_keys": sorted(cache_keys),
        },
        "prepared": {
            "module": "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow",
            "function": "execute_prepared_run", "import_root": str(code_root), "entrypoint": file_record(entrypoint),
        },
        "payload": {"plan": file_record(plan_path), "run_config_template": file_record(template_path),
                    "simion_executable": file_record(Path(simion_exe).resolve(strict=True)),
                    "component_pa_plan": component_plan,
                    "pa_producer_handoffs": handoff_plan,
                    "reuse_parent": str(reuse_parent.resolve()) if reuse_parent else None,
                    "reuse_through": reuse_through},
    }


def execute_prepared_run(
    run_config_path: Path, capacity_session_path: Path,
    execution_request_path: Path, completion_path: Path,
) -> None:
    """Execute the admitted root; the public owner alone publishes its terminal state."""
    run_config_path = Path(run_config_path).resolve(strict=True)
    run_root = run_config_path.parent
    execution_request_path = Path(execution_request_path).resolve(strict=True)
    request = load_json(execution_request_path)
    initial = load_json(run_config_path)
    require_completed_terminal_publication(run_root / "run_manifest.json")
    manifest = load_json(run_root / "run_manifest.json")
    if (execution_request_path != run_root / "inputs" / "execution_request.json"
            or manifest.get("status") != "checkpoint" or manifest.get("run_id") != run_root.name
            or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("project") != "single_reflection_oa_tof_mass_analyzer"
            or Path(manifest["run_config"]["path"]).resolve() != run_config_path
            or request["package"]["run_id"] != run_root.name
            or initial.get("inputs") != {"execution_request": str(execution_request_path)}):
        raise ValueError("candidate public package checkpoint differs")
    verify_record("initialized run config", manifest["run_config"])
    verify_record("execution request", manifest["inputs"]["execution_request"])
    summary_record = [record for record in manifest["outputs"]
                      if Path(record["path"]).resolve() == run_root / "summary.json"]
    if len(summary_record) != 1:
        raise ValueError("candidate initialization summary is not uniquely manifest-bound")
    verify_record("initialized summary", summary_record[0])
    initial_summary = load_json(run_root / "summary.json")
    if initial_summary.get("role") != "run_package_initialization_summary" or initial_summary.get("status") != "checkpoint":
        raise ValueError("candidate initialization summary differs")
    session = load_json(Path(capacity_session_path).resolve(strict=True))
    if (session.get("schema_version") != 1 or session.get("role") != "artifact_workflow_capacity_session" or session.get("status") != "active"
            or not session.get("lease_id")
            or run_root not in {Path(value).resolve() for value in session.get("protected_paths", [])}
            or Path(session["artifact_root"]).resolve() != Path(initial["capacity_ledger_lifecycle"]["artifact_root"]).resolve()):
        raise ValueError("candidate root is not protected by the admitted capacity session")
    payload = request["payload"]
    for name in ("plan", "run_config_template", "simion_executable"):
        verify_record(name, payload[name])
    writer_completion: dict[str, Any] = {"operations": [], "resource_releases": []}
    summary = None
    exception = None
    try:
        _, summary = _execute_candidate_stages(
            Path(payload["plan"]["path"]), payload["simion_executable"]["path"],
            reuse_parent=Path(payload["reuse_parent"]) if payload["reuse_parent"] else None,
            reuse_through=payload["reuse_through"], initialized_config_path=run_config_path,
            execution_context={"capacity_session_path": str(capacity_session_path),
                               "component_pa_plan": payload["component_pa_plan"],
                               "pa_producer_handoffs": payload.get("pa_producer_handoffs"),
                               "context_sha256": sha256(execution_request_path).lower(),
                               "writer_completion": writer_completion},
        )
    except BaseException as error:
        summary = getattr(error, "summary", None)
        exception = {"type": type(error).__name__, "message": str(error), "notes": list(getattr(error, "__notes__", []))}
        if summary is None:
            # No stage result is invented when preparation itself failed.
            summary = {"schema_version": 1, "role": "oa_tof_candidate_run_summary", "status": "failed",
                       "failure_stage": "preparation", "candidate_decision": "candidate_rejected",
                       "promotion_authorized": False, "performance_claim_allowed": False, "stages": []}
    summary = dict(summary, run_id=run_root.name)
    if load_json(run_root / "run_manifest.json").get("lifecycle_state") == "provisional":
        refresh_candidate_provisional_manifest(run_root, checkpoint=True)
    outputs = sorted(path for path in run_root.rglob("*") if path.is_file()
                     and not path.is_relative_to(run_root / "inputs")
                     and path.name not in {"run_config.json", "run_manifest.json"})
    required = [Path(value) for stage in summary.get("stages", [])
                for value in stage.get("evidence", {}).values()
                if isinstance(value, str) and Path(value).is_file()]
    write_json_atomic(Path(completion_path), {
        "schema_version": 1, "role": "run_artifact_workflow_completion",
        "run_id": run_root.name, "project": "single_reflection_oa_tof_mass_analyzer",
        "execution_request": file_record(execution_request_path), "run_config": file_record(run_config_path),
        "status": summary["status"], "summary": summary,
        "output_paths": [str(path) for path in outputs], "required_output_paths": [str(path) for path in required],
        "retention_preserve_paths": [],
        "manifest_extra_fields": {"lifecycle_state": "terminal", "promotion_authorized": False,
                                  "execution_source_closure": load_json(run_config_path).get("execution_source_closure", {})},
        "writer_completion": writer_completion, "exception": exception,
    })


def resume_candidate_finalization(run_root: Path, owner_result: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Resume only the existing public owner's publication, without executing stages."""
    run_root = Path(run_root).resolve(strict=True)
    request_path = run_root / "inputs" / "execution_request.json"
    request = load_json(request_path)
    package = request["package"]
    expected = Path(package["artifact_project_root"]).resolve() / "runs" / package["run_id"]
    if (package["project"] != "single_reflection_oa_tof_mass_analyzer"
            or package["mode"] != "design_candidate" or expected != run_root):
        raise ValueError("finalization request is not this candidate run")
    result_path = (Path(owner_result).resolve(strict=True) if owner_result else
                   run_root.parent.parent / "scratch" / "workflow_results" / run_root.name / "result.json")
    result_path = result_path.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="oatof_candidate_finalize_") as directory:
        log_path = Path(directory) / "owner.log"
        try:
            _run_command(_powershell(str(REPO_ROOT / "common/contracts/run_artifact_workflow.ps1"),
                                     ["-RequestPath", str(request_path), "-ResultPath", str(result_path),
                                      "-ResumeFinalization"]), log_path)
        except RuntimeError as exc:
            details = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else str(exc)
            raise CandidateWorkflowError(f"finalization failed: {details}; result: {result_path}", run_root) from exc
    result = load_json(result_path)
    if not (result.get("terminal_published") and result.get("capacity_finalized") and result.get("lease_released")):
        raise CandidateWorkflowError(f"public lifecycle owner remains incomplete: {result}; result: {result_path}", run_root)
    return run_root, load_json(run_root / "summary.json")


def run_candidate_workflow(
    plan_path: Path, simion_exe: str, stage_executor: StageExecutor = execute_stage, *,
    reuse_parent: Path | None = None, reuse_through: str | None = None,
    pa_handoff_output: Path | None = None, pa_producer_handoffs: list[tuple[Path, Path]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if stage_executor is not execute_stage:
        if pa_handoff_output is not None or pa_producer_handoffs:
            raise ValueError("PA producer handoff requires the public lifecycle owner")
        # Explicit injected executors exercise the existing scientific engine
        # without launching commercial tools; production always uses the owner.
        return _execute_candidate_stages(plan_path, simion_exe, stage_executor,
                                         reuse_parent=reuse_parent, reuse_through=reuse_through)
    request = _prepare_execution_request(plan_path, simion_exe, reuse_parent, reuse_through, pa_producer_handoffs)
    run_root = Path(request["package"]["artifact_project_root"]) / "runs" / request["package"]["run_id"]
    if pa_handoff_output is not None:
        pa_handoff_output = pa_handoff_output.resolve()
        if pa_handoff_output.exists() or pa_handoff_output.is_relative_to(run_root.parent):
            raise ValueError("PA handoff output must be a new path outside the candidate runs directory")
        request["package"]["retention_reason"] += " Explicit PA producer handoff retains the actual public owner Result."
    with tempfile.TemporaryDirectory(prefix="oatof_candidate_owner_") as directory:
        request_path = Path(directory) / "request.json"
        result_path = (pa_handoff_output if pa_handoff_output is not None else
                       run_root.parent.parent / "scratch" / "workflow_results" / run_root.name / "result.json")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.exists():
            raise ValueError(f"Workflow Result already exists: {result_path}")
        write_json_atomic(request_path, request)
        failure = None
        try:
            _run_command(_powershell(str(REPO_ROOT / "common/contracts/run_artifact_workflow.ps1"),
                                     ["-RequestPath", str(request_path), "-ResultPath", str(result_path)]),
                         Path(directory) / "owner.log")
        except BaseException as error:
            failure = error
        if not result_path.is_file():
            raise CandidateWorkflowError(f"public lifecycle owner did not return completion: {failure}; result: {result_path}", run_root) from failure
        result = load_json(result_path)
        if not (result.get("terminal_published") and result.get("capacity_finalized") and result.get("lease_released")):
            raise CandidateWorkflowError(f"public lifecycle owner remains incomplete: {result}; result: {result_path}", run_root) from failure
        summary = load_json(run_root / "summary.json")
        if summary["status"] == "interrupted":
            raise CandidateWorkflowInterrupted(run_root) from failure
        if summary["status"] != "success" or failure is not None:
            raise CandidateWorkflowError(str(result.get("exception") or failure), run_root) from failure
        return run_root, summary
