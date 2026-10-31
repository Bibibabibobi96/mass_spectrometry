"""Execute one prepared oa-TOF candidate workflow without promoting it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import warnings

from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion
from pathlib import Path
from contextlib import ExitStack
from typing import Any, Callable

from common.contracts.particle_count_policy import validate_standard_particle_count


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.file_identity import FileIdentityGuard, guarded_file_identity
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


from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_stage_execution import execute_candidate_stage, _powershell


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
            cwd=Path(env.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY", str(REPO_ROOT))),
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
        diagnostic_log = str(log_path)
        persistent = env.get("MASS_SPECTROMETRY_RUN_DIRECTORY")
        execution = env.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY")
        if persistent and execution:
            from common.paths.workspace_paths import project_run_path
            diagnostic_log = project_run_path(log_path, execution, persistent)
        raise RuntimeError(f"command failed with exit code {process.returncode}; log={diagnostic_log}")





def _run_managed_stage_command(
    command: list[str], log_path: Path, plan: dict[str, Any], receipt_path: Path,
    role: str, environment: dict[str, str] | None = None,
) -> None:
    """Carry actual native receipts and canonical persistent paths to the owner."""
    writer = plan.get("writer_completion")
    native_command, native_environment = _native_stage_execution_view(command, environment, plan)
    from common.paths.workspace_paths import project_native_run_path
    native_log = Path(project_native_run_path(log_path))
    failure = None
    try:
        _run_command(native_command, native_log, native_environment)
    except BaseException as error:
        failure = error
    try:
        append_native_stage_completion(
            writer, receipt_path, role=role, run_id=plan["run_id"],
            context_sha256=plan["context_sha256"], original_failure=failure,
        )
    except BaseException as error:
        failure = error
    observed = [] if writer is None else [operation for operation in writer["operations"]
        if operation.get("resource_release_id") == receipt_path.stem]
    # This permits editing only our JSON after actual native exit. It does not
    # declare host release/capacity/publication complete; the public owner still
    # validates those independent facts and retains protection when unknown.
    if observed and all(item.get("observation", {}).get("exit_confirmed") is True for item in observed):
        try:
            _persist_native_json_paths(plan)
        except BaseException as secondary:
            if failure is None:
                failure = secondary
            else:
                failure.add_note(f"Native JSON path closeout also failed: {secondary}")
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
    if stage_id == "comsol_candidate":
        # The delivery closure remains complete provenance. These four actual
        # implementations are independent reuse dependencies within this stage.
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import candidate_comsol_source_phases
        phases = candidate_comsol_source_phases(runtime_plan["execution_source_closure"])
        phase_root = inputs / "stage_contexts/comsol_candidate/phases"
        phase_paths = {}
        for phase_id, identity in phases.items():
            path = phase_root / f"{phase_id}.json"
            write_json_atomic(path, identity)
            phase_paths[phase_id] = path
        runtime_plan["comsol_phase_inputs"] = {name: str(path) for name, path in phase_paths.items()}
        # The native adapter reads the resolved values and the exact frozen ION,
        # never the provenance-only `inputs` paths or the design diff report.
        resolved = load_json(Path(candidate["candidate_resolved_geometry.json"]["path"]))
        resolved_values = {key: value for key, value in resolved.items() if key != "inputs"}
        resolved_identity = phase_root / "resolved_values.json"
        write_json_atomic(resolved_identity, resolved_values)
        solver_identity = phase_root / "solver_settings.json"
        write_json_atomic(solver_identity, resolved["comsol_runtime"])
        return {"inputs": {"comsol_native_resolved": resolved_identity,
                           "comsol_native_source": inputs / "oatof_candidate_N100.ion"},
                "source": {"comsol_native_implementation": phase_paths["native"]},
                "solver": {"comsol_native_solver": solver_identity}}
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
    provenance: set[str],
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
    phase_root = run_root / "inputs/stage_contexts/comsol_candidate/phases"
    for phase_id in ("native", "export", "analysis", "sync"):
        phase_path = phase_root / f"{phase_id}.json"
        if phase_path.is_file():
            name = f"comsol_phase_{phase_id}"
            config["inputs"][name] = str(phase_path)
            config["input_sha256"][name] = sha256(phase_path)
    for stage_id in sorted(provenance):
        name = f"stage_reuse_{stage_id}_provenance"
        path = run_root / "inputs/stage_contexts" / stage_id / "reuse_provenance.json"
        config["inputs"][name] = str(path)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _bind_provenance_hash(run_root: Path, stage_id: str, owner_root: Path) -> None:
    """Bind the actual per-stage proof and its explicit original manifest."""
    config_path = run_root / "run_config.json"
    config = load_json(config_path)
    name = f"stage_reuse_{stage_id}_provenance"
    path = Path(config["inputs"][name])
    config["input_sha256"][name] = sha256(path)
    source_name = f"stage_reuse_{stage_id}_source_manifest"
    source = owner_root / "run_manifest.json"
    config["inputs"][source_name] = str(source)
    config["input_sha256"][source_name] = sha256(source)
    config.setdefault("provenance", {}).setdefault("stage_reuse", {})[stage_id] = file_record(path)
    write_json_atomic(config_path, config)


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
            and name.startswith("stage_reuse_") and name.endswith("_provenance")
            and not path.exists()
        ):
            continue
        expected = hashes.get(name)
        if not expected or not path.is_file() or sha256(path) != str(expected).upper():
            raise RuntimeError(f"frozen candidate run input changed: {name}")


def _verify_identity_descriptor(path: Path, actual: Path, label: str, guard: FileIdentityGuard | None = None) -> None:
    record = load_json(path)["records"][0]
    if guard is not None:
        guard.assert_matches(actual, expected_bytes=record["bytes"], expected_sha256=record["sha256"])
        return
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


def _bound_stage_file(parent: Path, manifest: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    """Verify a small original witness against its original manifest binding."""
    path = path.resolve(strict=True)
    if not path.is_relative_to(parent):
        raise ValueError(f"original {label} is outside its original owner")
    records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
    matches = [record for record in records if Path(str(record.get("path", ""))).resolve() == path]
    if not matches or len({(item.get("bytes"), item.get("sha256")) for item in matches}) != 1:
        raise ValueError(f"original {label} is not uniquely manifest-bound")
    verify_record(f"original {label}", matches[0])
    return matches[0]



def _resolve_reuse_stage_owner(parent: Path, stage_id: str) -> dict[str, Any]:
    """Resolve one explicitly frozen stage owner without recursive discovery.

    An inherited child is evidence, not a new producer of its parent's MPH/PA.
    New named proofs bind their original manifest as an explicit input; an old
    single proof may use only its own manifest-bound execution request's exact
    reuse_parent. Neither branch guesses an artifact root or scans for a run ID.
    """
    parent = parent.resolve(strict=True)
    manifest_path = parent / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest = load_json(manifest_path)
    config = load_json(parent / "run_config.json")
    config_record = manifest.get("run_config", {})
    if Path(str(config_record.get("path", ""))).resolve() != parent / "run_config.json":
        raise ValueError("Reuse source config is not bound by its actual manifest")
    verify_record("reuse source config", config_record)
    if (manifest.get("project") != "single_reflection_oa_tof_mass_analyzer"
            or manifest.get("run_id") != parent.name or config.get("run_id") != parent.name
            or config.get("mode") != "design_candidate"):
        raise ValueError("Stage reuse requires this explicit completed Candidate owner")
    receipt_stage_id = stage_id
    receipt = parent / "stage_receipts" / f"{stage_id}.json"
    if stage_id == "comsol_candidate" and not receipt.is_file() and (parent / "stage_receipts/comsol_native.json").is_file():
        receipt_stage_id = "comsol_native"
        receipt = parent / "stage_receipts/comsol_native.json"
    if receipt.is_file():
        _bound_stage_file(parent, manifest, receipt, f"original {stage_id} receipt")
        return {"run_directory": str(parent), "manifest_record": file_record(manifest_path), "receipt_stage_id":receipt_stage_id}
    _bound_stage_file(parent, manifest, parent / "summary.json", "inherited summary")
    summaries = [item for item in load_json(parent / "summary.json").get("stages", [])
                 if item.get("stage_id") == stage_id]
    inherited_success = len(summaries) == 1 and summaries[0].get("status") == "success" and summaries[0].get("execution") == "reused"
    partial_comsol = (stage_id == "comsol_candidate" and len(summaries) == 1
        and summaries[0].get("status") == "failed"
        and isinstance(config.get("provenance", {}).get("comsol_phases"), dict))
    if not inherited_success and not partial_comsol:
        raise ValueError(f"{stage_id} has neither an original receipt nor confirmed inherited native success")
    inputs = config.get("inputs", {})
    named = f"stage_reuse_{stage_id}_provenance"
    proof_name = named if named in inputs else "stage_reuse_provenance"
    if proof_name not in inputs:
        raise ValueError(f"{stage_id} inherited owner proof is missing; select its explicit original owner")
    proof_path = Path(inputs[proof_name]).resolve(strict=True)
    _bound_stage_file(parent, manifest, proof_path, f"{stage_id} inherited proof")
    proof = load_json(proof_path)
    if (proof.get("schema_version") != 1 or proof.get("role") != "stage_reuse_provenance"
            or proof.get("project") != config.get("project") or proof.get("run_id") != parent.name):
        raise ValueError("Inherited stage proof does not belong to this Candidate child")
    allowed_ids = {stage_id, "comsol_native"} if stage_id == "comsol_candidate" else {stage_id}
    stages = [item for item in proof.get("reused_stages", []) if item.get("stage_id") in allowed_ids]
    if len(stages) != 1:
        raise ValueError(f"Inherited proof must cover exactly one {stage_id} record")
    owner_name = f"stage_reuse_{stage_id}_source_manifest"
    if owner_name in inputs:
        source_manifest = Path(inputs[owner_name]).resolve(strict=True)
        bound = manifest.get("inputs", {}).get(owner_name, {})
        if Path(str(bound.get("path", ""))).resolve() != source_manifest:
            raise ValueError("Named source manifest is not this child's declared frozen input")
        verify_record(f"{stage_id} explicit source manifest", bound)
    elif proof_name == "stage_reuse_provenance":
        request_path = Path(inputs.get("execution_request", "")).resolve(strict=True)
        _bound_stage_file(parent, manifest, request_path, "original inherited execution request")
        explicit = load_json(request_path).get("payload", {}).get("reuse_parent")
        if not isinstance(explicit, str) or not Path(explicit).is_absolute():
            raise ValueError("Old inherited proof lacks an explicit original source; no root guessing is permitted")
        source_manifest = Path(explicit).resolve(strict=True) / "run_manifest.json"
    else:
        raise ValueError("Named stage proof lacks its explicit source manifest")
    record = file_record(source_manifest)
    if (source_manifest.name != "run_manifest.json" or source_manifest.parent.name != proof.get("parent_run_id")
            or record["bytes"] != proof.get("parent_manifest", {}).get("bytes")
            or record["sha256"].upper() != str(proof.get("parent_manifest", {}).get("sha256", "")).upper()):
        raise ValueError("Inherited stage's actual source manifest differs from its original proof")
    source = source_manifest.parent
    require_completed_terminal_publication(source_manifest)
    receipt_stage_id = stages[0]["stage_id"]
    source_receipt = source / "stage_receipts" / f"{receipt_stage_id}.json"
    if not source_receipt.is_file():
        raise ValueError("Inherited proof must flatten to an original receipt owner; recursive lookup is not supported")
    source_manifest_json = load_json(source_manifest)
    receipt_record = _bound_stage_file(source, source_manifest_json, source_receipt, f"{stage_id} original receipt")
    expected = stages[0].get("receipt", {})
    if (receipt_record["bytes"] != expected.get("bytes")
            or receipt_record["sha256"].upper() != str(expected.get("sha256", "")).upper()
            or (source / str(expected.get("path", ""))).resolve() != source_receipt):
        raise ValueError("Inherited stage receipt differs from its manifest-bound proof")
    return {"run_directory": str(source), "manifest_record": record,
            "inherited_via": file_record(manifest_path), "proof_record": file_record(proof_path), "receipt_stage_id":receipt_stage_id}


def _verify_reused_output(path: Path, record: dict[str, Any], label: str, guard: FileIdentityGuard | None = None) -> None:
    if guard is not None:
        guard.assert_matches(path, expected_bytes=record["bytes"], expected_sha256=record["sha256"])
        return
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
    reuse_guard_stack = ExitStack()
    identity_guards: dict[Path, FileIdentityGuard] = {}
    runtime_plan["_identity_guards"] = identity_guards
    runtime_plan["_model_guard_stack"] = reuse_guard_stack
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
        reuse_set = set(REUSABLE_STAGES[:REUSABLE_STAGES.index(reuse_through)+1]) if reuse_through else set()
        reuse_stage_owners: dict[str, dict[str, Any]] = {}
        contexts: dict[str, dict[str, dict[str, Path]]] = {}
        cad_model_path: Path | None = None
        contexts["comsol_candidate"] = _stage_context(
            run_root, runtime_plan, "comsol_candidate", simion_exe
        )
        runtime_plan["comsol_native_context"] = contexts["comsol_candidate"]
        contexts["simion_candidate"] = _stage_context(
            run_root, runtime_plan, "simion_candidate", simion_exe
        )
        _declare_context_inputs(
            run_root,
            contexts,
            provenance=reuse_set,
        )
        refresh_candidate_provisional_manifest(run_root)
        _verify_frozen_run_inputs(
            run_root,
            allow_pending_provenance=reuse_set,
        )
        if reuse_through is not None:
            current_stage = "comsol_candidate"
            boundary = REUSABLE_STAGES.index(reuse_through)
            reuse_set = set(REUSABLE_STAGES[: boundary + 1])
            parent_root = Path(reuse_parent).resolve(strict=True)
            reuse_stage_owners = {stage_id: _resolve_reuse_stage_owner(parent_root, stage_id)
                                  for stage_id in sorted(reuse_set)}
            frozen_owners = runtime_plan.get("reuse_stage_owners")
            if frozen_owners is not None and frozen_owners != reuse_stage_owners:
                raise ValueError("Reuse source owners changed after the frozen request; do not search another source")
            native_owner = Path(reuse_stage_owners["comsol_candidate"]["run_directory"])
            model_receipt = load_json(native_owner / "stage_receipts" / (reuse_stage_owners["comsol_candidate"].get("receipt_stage_id", "comsol_candidate")+".json"))
            model_record = model_receipt["outputs"]["model"]
            model_path = (native_owner / model_record["path"]).resolve(strict=True)
            identity_guards[model_path] = reuse_guard_stack.enter_context(guarded_file_identity(
                model_path, expected_bytes=model_record["bytes"], expected_sha256=model_record["sha256"]))
            if "cad_candidate" in reuse_set:
                parent_cad_receipt = load_json(
                    Path(reuse_stage_owners["cad_candidate"]["run_directory"]) / "stage_receipts" / "cad_candidate.json"
                )
                parent_mph_identity_record = parent_cad_receipt["context"]["inputs"][
                    "cad_candidate_input_002"
                ]
                parent_mph_identity = load_json(
                    Path(reuse_stage_owners["cad_candidate"]["run_directory"]) / parent_mph_identity_record["path"]
                )["records"][0]
                contexts["cad_candidate"] = _stage_context(
                    run_root,
                    runtime_plan,
                    "cad_candidate",
                    simion_exe,
                    cad_model=parent_mph_identity,
                )
                _declare_context_inputs(run_root, contexts, provenance=reuse_set)
                refresh_candidate_provisional_manifest(run_root)
            for stage_id in sorted(reuse_set):
                owner_root = Path(reuse_stage_owners[stage_id]["run_directory"])
                provenance = validate_and_write_stage_reuse(
                    run_root, parent_run_root=owner_root,
                    project="single_reflection_oa_tof_mass_analyzer",
                    stage_contexts={reuse_stage_owners[stage_id].get("receipt_stage_id",stage_id): contexts[stage_id]},
                    allow_provisional_manifest=True, identity_guards=identity_guards,
                    provenance_input_name=f"stage_reuse_{stage_id}_provenance",
                )
                _bind_provenance_hash(run_root, stage_id, owner_root)
                stage_evidence, stage_records = _reused_evidence(owner_root, provenance)
                receipt_id = reuse_stage_owners[stage_id].get("receipt_stage_id", stage_id)
                if receipt_id != stage_id:
                    stage_evidence = {stage_id:stage_evidence[receipt_id]}
                    stage_records = {stage_id:stage_records[receipt_id]}
                reused.update(stage_evidence)
                reused_records.update(stage_records)
            refresh_candidate_provisional_manifest(run_root)
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
                _declare_context_inputs(run_root, contexts, provenance=reuse_set)
                refresh_candidate_provisional_manifest(run_root)

        for stage in stages[1:]:
            current_stage = stage["stage_id"]
            runtime_plan["stage_results_so_far"] = results
            _verify_frozen_run_inputs(run_root)
            if current_stage in reuse_set:
                evidence = reused[current_stage]
                analysis_execution = None
                phase_execution = None
                if current_stage == "comsol_candidate":
                    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_reused_comsol_phases
                    disposition = runtime_plan.get("comsol_disposition")
                    if disposition is None:
                        disposition = _comsol_reuse_disposition(Path(reuse_parent), runtime_plan["execution_source_closure"], run_root.parents[3])
                    from common.contracts.verify_run_manifest import record_path
                    evidence = dict(evidence)
                    for phase, original in disposition["origins"].items():
                        for name, record in original["outputs"].items():
                            if name in {"model", "build_report", "analysis_request", "analysis_receipt", "analysis_contract", "sync_report"}:
                                evidence[name] = str(record_path(record, base_dir=Path(original["owner_directory"])))
                                reused_records[current_stage][name] = record
                    evidence, phase_execution = execute_reused_comsol_phases(stage, runtime_plan, evidence,
                        reused_records[current_stage], disposition, runtime=sys.modules[__name__])
                    analysis_execution = phase_execution["analysis"]
                    reused[current_stage] = evidence
                    _publish_comsol_phase_sources(run_root, runtime_plan, evidence, phase_execution, disposition["origins"])
                    refresh_candidate_provisional_manifest(run_root)
                results.append(
                    {
                        "stage_id": current_stage,
                        "status": "success",
                        "execution": "reused",
                        "reused_from_run_id": Path(reuse_stage_owners[current_stage]["run_directory"]).name,
                        "inherited_via_run_id": Path(reuse_parent).name,
                        "analysis_execution": analysis_execution,
                        "phase_execution": phase_execution,
                        "native_execution": "reused",
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
                            f"{reused_stage}.{name}", identity_guards.get(Path(reused[reused_stage][name]).resolve()),
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
                        "comsol_candidate.model", identity_guards.get(cad_model_path.resolve()),
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
                    "Candidate MPH", identity_guards.get(Path(stage_for_execution["model_path"]).resolve()),
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
                    "Candidate MPH", identity_guards.get(Path(stage_for_execution["model_path"]).resolve()),
                )
            if (
                current_stage == "cad_candidate"
                and "comsol_candidate" in reuse_set
            ):
                _verify_reused_output(
                    Path(stage_for_execution["model_path"]),
                    reused_records["comsol_candidate"]["model"],
                    "comsol_candidate.model", identity_guards.get(Path(stage_for_execution["model_path"]).resolve()),
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
                    cad_model=({"bytes":identity_guards[cad_model_path.resolve()].bytes_count,
                                "sha256":identity_guards[cad_model_path.resolve()].sha256}
                               if cad_model_path.resolve() in identity_guards else cad_model_path),
                )
                _declare_context_inputs(
                    run_root,
                    contexts,
                    provenance=reuse_set,
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
            if current_stage == "comsol_candidate":
                _publish_comsol_phase_sources(run_root, runtime_plan, evidence,
                    dict.fromkeys(("native", "export", "analysis", "sync"), "executed"))
            if current_stage in REUSABLE_STAGES:
                _verify_frozen_run_inputs(run_root)
                update_candidate_progress(run_root, results, stages)
                write_stage_receipt(
                    run_root,
                    project="single_reflection_oa_tof_mass_analyzer",
                    stage_id=current_stage,
                    context=contexts[current_stage],
                    outputs=_receipt_outputs(evidence),
                    allow_provisional_manifest=True, identity_guards=identity_guards,
                )
                refresh_candidate_provisional_manifest(run_root)
        _verify_frozen_run_inputs(run_root)
        current_stage = stages[-1]["stage_id"]
        summary, _ = finalize_candidate_run(run_root, "success", results, publish=initialized_config_path is None, identity_guards=identity_guards)
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
                                           publish=initialized_config_path is None, identity_guards=identity_guards)
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
                                           publish=initialized_config_path is None, identity_guards=identity_guards)
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
                                           publish=initialized_config_path is None, identity_guards=identity_guards)
        error = CandidateWorkflowError(str(exc), run_root)
        for note in getattr(exc, "__notes__", []):
            error.add_note(note)
        error.summary = summary
        raise error from exc

    finally:
        reuse_guard_stack.close()


def _prepare_execution_request(
    plan_path: Path, simion_exe: str, reuse_parent: Path | None, reuse_through: str | None,
    pa_producer_handoffs: list[tuple[Path, Path]] | None = None,
) -> dict[str, Any]:
    """Read the frozen plan and reserve disk from its explicit authorities."""
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import candidate_native_execution_relative_paths
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
    source_references = []
    reuse_stage_owners = {}
    comsol_disposition = None
    native_input_paths = []
    reused_stages = set(REUSABLE_STAGES[:REUSABLE_STAGES.index(reuse_through)+1]) if reuse_through else set()
    if reuse_parent is not None:
        parent = reuse_parent.resolve(strict=True)
        parent_manifest = parent / "run_manifest.json"
        require_completed_terminal_publication(parent_manifest)
        # Actual original capacity owner pins the explicit source, including a
        # different artifact root. It is not this child's writable scope.
        source_references.append({"manifest_record": file_record(parent_manifest),
                                  "protected_paths": [str(parent)]})
        for stage_id in sorted(reused_stages):
            owner = _resolve_reuse_stage_owner(parent, stage_id)
            reuse_stage_owners[stage_id] = owner
            if all(item["manifest_record"]["path"] != owner["manifest_record"]["path"]
                   for item in source_references):
                source_references.append({"manifest_record": owner["manifest_record"],
                                          "protected_paths": [owner["run_directory"]]})
    if reuse_parent is not None and "comsol_candidate" in reused_stages:
        comsol_disposition = _comsol_reuse_disposition(reuse_parent.resolve(strict=True), closure, run_root.parents[3])
        for original in comsol_disposition["origins"].values():
            record = original["manifest_record"]
            if all(item["manifest_record"]["path"] != record["path"] for item in source_references):
                source_references.append({"manifest_record":record, "protected_paths":[original["owner_directory"]]})
        native = comsol_disposition["origins"]["native"]
        if comsol_disposition["export"] == "executed":
            native_input_paths.extend(native["outputs"][name]["path"] for name in ("model","saved_context"))
        elif comsol_disposition["sync"] == "executed" or "cad_candidate" not in reused_stages:
            native_input_paths.append(native["outputs"]["model"]["path"])
    if native_input_paths and comsol_disposition["origins"]["native"]["outputs"]["model"]["bytes"] > capacity["comsol_bytes"]:
        raise ValueError("Reused model exceeds this request's COMSOL temporary/recovery reservation; explicitly re-evaluate the runtime budget")
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
            **({"expected_execution_relative_paths": candidate_native_execution_relative_paths(
                    closure, code_relative_root=code_root.relative_to(plan_path.parent),
                    model_relative_path=Path(next(stage["model_path"] for stage in plan["stages"]
                        if stage["stage_id"] == "comsol_candidate")).relative_to(run_root))}
               if reused_stages != set(REUSABLE_STAGES) or native_input_paths else {}),
            "retention_reason": "Candidate MPH, CAD and private SIMION delivery remain available for explicit structural review; no promotion is authorized.",
        },
        "capacity": {
            "committed_new_bytes": (
                (0 if "simion_candidate" in reused_stages else sum_component_commitments([component_plan]))
                + (capacity["comsol_bytes"] if "comsol_candidate" not in reused_stages or native_input_paths else 0)
                + (0 if "cad_candidate" in reused_stages else capacity["cad_bytes"])
                + capacity["evidence_bytes"]),
            "source_references": source_references,
            "commitment_inputs": [file_record(path) for path in (plan_path, template_path, runtime_path, resolved_path)]
                + (handoff_plan["source_records"] if handoff_plan else []),
            "protected_paths": sorted(set(protected)),
            "protected_cache_keys": sorted(cache_keys),
        },
        "prepared": {
            "module": "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow",
            "function": "execute_prepared_run", "import_root": str(code_root), "entrypoint": file_record(entrypoint),
            **({"native_input_paths": sorted(set(native_input_paths))} if native_input_paths else {}),
        },
        "payload": {"plan": file_record(plan_path), "run_config_template": file_record(template_path),
                    "simion_executable": file_record(Path(simion_exe).resolve(strict=True)),
                    "component_pa_plan": component_plan,
                    "pa_producer_handoffs": handoff_plan,
                    "reuse_parent": str(reuse_parent.resolve()) if reuse_parent else None,
                    "reuse_through": reuse_through, "reuse_stage_owners": reuse_stage_owners,
                    "comsol_disposition": comsol_disposition},
    }


def execute_prepared_run(
    run_config_path: Path, capacity_session_path: Path,
    execution_request_path: Path, completion_path: Path,
) -> None:
    """Execute the admitted root; the public owner alone publishes its terminal state."""
    run_config_path = Path(run_config_path).resolve(strict=True)
    request_document = load_json(Path(execution_request_path))
    if request_document["package"]["mode"] == "candidate_comsol_postprocess":
        return execute_prepared_postprocess(Path(run_config_path), Path(capacity_session_path),
                                            Path(execution_request_path), Path(completion_path))
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
                               "reuse_stage_owners": payload.get("reuse_stage_owners"),
                               "comsol_disposition": payload.get("comsol_disposition"),
                               "source_execution_context": session.get("source_execution_context"),
                               "context_sha256": sha256(execution_request_path).lower(),
                               "writer_completion": writer_completion},
        )
    except BaseException as error:
        summary = getattr(error, "summary", None)
        exception = {"type": type(error).__name__, "message": str(error), "notes": list(getattr(error, "__notes__", []))}
        if summary is None:
            # No stage result is invented when preparation itself failed.
            summary = {"schema_version": 1, "role": "oa_tof_candidate_run_summary", "status": "failed",
                       "failure_stage": "preparation", "candidate_decision": "no_candidate_decision",
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
            or package["mode"] not in {"design_candidate", "candidate_comsol_postprocess"} or expected != run_root):
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
    return _invoke_candidate_owner_request(request, pa_handoff_output)


def _invoke_candidate_owner_request(request: dict, pa_handoff_output: Path | None = None) -> tuple[Path, dict]:
    run_root = Path(request["package"]["artifact_project_root"]) / "runs" / request["package"]["run_id"]
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


def run_candidate_postprocess(parent: Path, run_id: str) -> tuple[Path, dict]:
    """Original Candidate CLI's explicit new-child postprocessing action."""
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import prepare_postprocess_request
    return _invoke_candidate_owner_request(prepare_postprocess_request(parent, run_id))


def execute_prepared_postprocess(config_path: Path, session_path: Path, request_path: Path, completion_path: Path) -> None:
    """Use the initialized public package; publish only actual small child outputs."""
    import shutil
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import _rewrite_paths
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
    from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.candidate_comsol_stage import execute_saved_postprocess
    root = config_path.resolve().parent
    request = load_json(request_path)
    initial = load_json(config_path)
    payload = request["payload"]
    verify_record("frozen postprocess selection", payload["postprocess_selection"])
    selected = load_json(Path(payload["postprocess_selection"]["path"]))
    session = load_json(session_path)
    source_paths = [path for lease in session.get("source_protection_leases", [])
                    if lease.get("status") == "active" for path in lease.get("protected_paths", [])]
    if str(root) not in session["protected_paths"] or selected["parent"] not in [*session["protected_paths"], *source_paths]:
        raise ValueError("Postprocessing source and child must be protected by the admitted public session")
    closure = payload["execution_source_closure"]
    verify_candidate_source_closure(closure)
    source_code = Path(closure["code_root"])
    child_code = root / "inputs/code"
    shutil.copytree(source_code, child_code)
    closure = _rewrite_paths(closure, source_code, child_code)
    verify_candidate_source_closure(closure)
    selected_path = root / "inputs/postprocess_source_selection.json"
    write_json_atomic(selected_path, selected)
    config = dict(initial)
    config["inputs"] = dict(initial["inputs"], postprocess_source_selection=str(selected_path))
    config["execution_source_closure"] = closure
    config["provenance"] = {"source_reference": selected["source_reference"], "science_reference": selected["science_reference"], "model_record": selected["model_record"]}
    config["parameters"] = dict(initial.get("parameters", {}), scope="comsol_postprocessing_only")
    write_json_atomic(config_path, config)
    writer = {"operations": [], "resource_releases": []}
    failure = None
    evidence = {}
    source_verified = False
    start = time.monotonic()
    try:
        refreshed = select_postprocess_parent(Path(selected["parent"]), Path(session["artifact_root"]))
        if refreshed != selected:
            raise ValueError("Protected parent evidence changed after admission")
        source_verified = True
        evidence = execute_saved_postprocess(selected, root, closure,
            {"run_id": root.name, "run_root": str(root), "context_sha256": sha256(request_path).lower(), "writer_completion": writer,
             "source_execution_context": session.get("source_execution_context"), "postprocess_evidence": evidence},
            runtime=sys.modules[__name__])
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error), "notes": list(getattr(error, "__notes__", []))}
    status = "failed" if failure else "success"
    recovery_parent = root if evidence.get("detector_exports_ready") is True else Path(selected["parent"])
    recovery_action = (f'"{sys.executable}" -m projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate '
                       f'--postprocess-from "{recovery_parent}" --run-id <NEW_RUN_ID>') if failure else "none"
    if evidence.get("writer_completion_unconfirmed"):
        recovery_action = "inspect_original_writer_completion; retain current protections"
    summary = {"schema_version": 1, "role": "oa_tof_candidate_postprocess_summary", "run_id": root.name,
        "status": status, "execution_status": status, "data_validity": "unknown" if failure else "valid",
        "source_identity_verified": source_verified,
        "scientific_result": "not_evaluated_whole_candidate", "scope": "comsol_postprocessing_only",
        "candidate_decision": "not_evaluated_postprocess_scope", "promotion_authorized": False,
        "performance_claim_allowed": False, "parent_model_saved": False,
        "native_field_solve_count": 0, "native_particle_solve_count": 0,
        "failure_stage": "postprocessing" if failure else None,
        "failure_reason": failure["message"] if failure else None,
        "recovery_action": recovery_action,
        "recovery_requires_terminal_publication": bool(failure and evidence.get("detector_exports_ready")),
        "resume_finalization_command": (f'"{sys.executable}" -m projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate '
                                        f'--resume-finalization "{root}"'),
        "evidence": evidence, "elapsed_seconds": time.monotonic()-start}
    outputs = sorted(str(path) for path in root.rglob("*") if path.is_file()
                     and not path.is_relative_to(root / "inputs") and path.name not in {"run_config.json", "run_manifest.json"})
    write_json_atomic(completion_path, {"schema_version": 1, "role": "run_artifact_workflow_completion",
        "run_id": root.name, "project": PROJECT_ROOT.name,
        "execution_request": file_record(request_path), "run_config": file_record(config_path),
        "status": status, "summary": summary, "output_paths": outputs,
        "required_output_paths": [evidence["analysis_receipt"]] if evidence.get("analysis_receipt") else [],
        "retention_preserve_paths": [], "manifest_extra_fields": {"lifecycle_state": "terminal", "promotion_authorized": False,
            "postprocess_source_reference": selected["source_reference"], "scope": "comsol_postprocessing_only"},
        "writer_completion": writer, "exception": failure})


def _native_stage_execution_view(command: list[str], environment: dict[str, str] | None,
                                 plan: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Transport only this owner's actual native paths through its public view."""
    from common.paths.workspace_paths import project_native_run_path
    persistent = os.environ.get("MASS_SPECTROMETRY_RUN_DIRECTORY")
    if persistent and Path(persistent).resolve() != Path(plan["run_root"]).resolve():
        raise ValueError("Native stage does not belong to the active public run context")
    native_environment = {key: project_native_run_path(value) for key, value in (environment or {}).items()}
    # Only explicitly declared, admitted source inputs may acquire a source
    # execution spelling. External tools and unrelated paths are not searched.
    from common.paths.workspace_paths import project_run_path
    context = plan.get("source_execution_context")
    for key in ("OATOF_CANDIDATE_MODEL_PATH", "OATOF_COMSOL_MODEL_PATH"):
        if key not in (environment or {}):
            continue
        model = Path(environment[key])
        if model.resolve().is_relative_to(Path(plan["run_root"]).resolve()):
            continue
        if (not isinstance(context, dict) or context.get("role") != "run_source_execution_context"
                or Path(context.get("child_run_directory", "")).resolve() != Path(plan["run_root"]).resolve()
                or str(context.get("request_sha256", "")).lower() != str(plan.get("context_sha256", "")).lower()):
            raise ValueError("Native saved-model consumption lacks its admitted source execution context")
        matches = [source for source in context["sources"] if str(model.resolve()) in source["input_paths"]]
        if len(matches) != 1:
            raise ValueError("Native saved model is not one uniquely declared source input")
        source = matches[0]
        native_environment[key] = project_run_path(model, source["target_directory"], source["execution_directory"])
    original_config = (environment or {}).get("OATOF_CANDIDATE_RUN_CONFIG_PATH")
    if original_config and Path(original_config).is_file():
        # Only the execution view of actual inputs changes. The owner config,
        # capacity metadata and scientific values remain the frozen authority.
        document = load_json(Path(original_config))
        document["inputs"] = {key: project_native_run_path(value)
                              for key, value in document.get("inputs", {}).items()}
        projected_config = Path(plan["run_root"]) / "inputs/native_run_config.json"
        write_json_atomic(projected_config, document)
        native_environment["OATOF_CANDIDATE_RUN_CONFIG_PATH"] = project_native_run_path(projected_config)
    return [project_native_run_path(value) for value in command], native_environment



def _persist_native_json_paths(plan: dict[str, Any]) -> None:
    """Normalize stopped-writer JSON references, never a model or parent input."""
    from common.paths.workspace_paths import project_run_path
    root = Path(plan["run_root"])
    execution = os.environ.get("MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY")
    if not execution or execution == str(root):
        return
    def canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        if isinstance(value, str):
            return project_run_path(value, execution, root)
        return value
    paths = [*root.glob("comsol/*.mph.postprocess.json"), *root.glob("results/*.analysis_request.json")]
    paths += [root / "results/cold_postprocess_result.json", root / "inputs/native_run_config.json"]
    for path in paths:
        if path.is_file():
            document = load_json(path)
            normalized = canonical(document)
            if normalized != document:
                write_json_atomic(path, normalized)



def _comsol_phase_sources(parent: Path) -> dict[str, dict[str, Any]]:
    """Read four explicit, flat owners from this Candidate's bound provenance.

    A successor never recursively discovers another run. A local phase is
    covered by this manifest; an inherited phase has its original manifest as
    an explicit input. The original owner's records remain its records.
    """
    from common.contracts.verify_run_manifest import record_path
    parent = parent.resolve(strict=True)
    manifest_path = parent / 'run_manifest.json'
    require_completed_terminal_publication(manifest_path)
    manifest = load_json(manifest_path)
    config_path = parent / 'run_config.json'
    verify_record('phase source config', manifest['run_config'], base_dir=parent)
    config = load_json(config_path)
    phases = config.get('provenance', {}).get('comsol_phases')
    if not isinstance(phases, dict) or set(phases) != {'native','export','analysis','sync'}:
        raise ValueError('Original COMSOL owner lacks comparable native/export phase facts. The current field generator requires explicit Electrostatics initialization; request the necessary new native stage rather than accepting an unproved old implementation. Sufficient sealed detector CSV remains usable with --postprocess-from without COMSOL.')
    result = {}
    for phase, item in phases.items():
        implementation_name = 'comsol_phase_' + phase
        implementation = manifest['inputs'].get(implementation_name)
        if implementation is None or config['inputs'].get(implementation_name) != str(record_path(implementation, base_dir=parent)):
            raise ValueError(f'{phase} implementation is not bound by its source manifest/config')
        verify_record(phase+' implementation', implementation, base_dir=parent)
        owner_input = item.get('owner_manifest_input')
        if owner_input is None:
            owner = parent
            owner_manifest = manifest
            owner_record = file_record(manifest_path)
        else:
            if owner_input != 'comsol_' + phase + '_source_manifest':
                raise ValueError('COMSOL phase has an unrecognized owner input')
            owner_record = manifest['inputs'].get(owner_input)
            if owner_record is None or config['inputs'].get(owner_input) != str(record_path(owner_record, base_dir=parent)):
                raise ValueError('COMSOL original owner is not an explicit bound source input')
            verify_record(phase+' original owner manifest', owner_record, base_dir=parent)
            owner_path = record_path(owner_record, base_dir=parent)
            require_completed_terminal_publication(owner_path)
            owner = owner_path.parent
            owner_manifest = load_json(owner_path)
        if owner_manifest.get('project') != 'single_reflection_oa_tof_mass_analyzer' or owner_manifest.get('run_id') != owner.name:
            raise ValueError('COMSOL phase original owner differs')
        outputs = item.get('outputs')
        pending = item.get('status') == 'pending' and phase != 'native'
        if not isinstance(outputs, dict) or (not outputs and not pending):
            raise ValueError('COMSOL phase lacks its actual output records')
        required_outputs = {'native':{'model','build_report'}, 'export':{'analysis_request','raw_events'},
                            'analysis':{'analysis_receipt','analysis_contract'}, 'sync':{'sync_report'}}
        if not pending and not required_outputs[phase] <= outputs.keys():
            raise ValueError('COMSOL '+phase+' does not retain its complete actual output contract')
        bound = [*owner_manifest.get('inputs', {}).values(), *owner_manifest.get('outputs', [])]
        for name, record in outputs.items():
            path = record_path(record, base_dir=owner)
            if not path.is_relative_to(owner):
                raise ValueError('Phase output must belong to its explicitly named actual owner')
            matches = [row for row in bound if record_path(row, base_dir=owner) == path]
            if len(matches) != 1 or any(str(matches[0][key]).upper() != str(record[key]).upper() for key in ('bytes','sha256')):
                raise ValueError(f'COMSOL {phase}.{name} is not bound by its actual owner')
            # Model content is checked by the one active FileIdentityGuard in
            # the engine. This metadata admission does not reread the MPH.
            if name != 'model':
                verify_record(phase+'.'+name, record, base_dir=owner)
            outputs[name] = dict(record, path=str(path))
        if phase == 'export' and not pending:
            request = load_json(Path(outputs['analysis_request']['path']))
            if (request.get('role') != 'oatof_comsol_detector_events_analysis_request'
                    or Path(request.get('raw_events_csv','')).resolve() != Path(outputs['raw_events']['path'])):
                raise ValueError('COMSOL export request does not bind the actual owner CSV')
        result[phase] = {'owner_directory':str(owner), 'manifest_record':owner_record,
            'implementation':load_json(record_path(implementation, base_dir=parent)),
            'status':'pending' if pending else 'success', 'outputs':outputs}
    return result


def _publish_comsol_phase_sources(run_root: Path, runtime_plan: dict, evidence: dict,
                                  execution: dict, inherited: dict | None = None) -> None:
    """Bind actual local outputs or original owners into existing provenance."""
    from common.contracts.verify_run_manifest import record_path
    config_path = run_root / 'run_config.json'
    config = load_json(config_path)
    names = {'native':('model','build_report'), 'export':('analysis_request',),
             'analysis':('analysis_receipt','analysis_contract'), 'sync':('sync_report',)}
    phases = {}
    for phase, keys in names.items():
        if execution[phase] == 'pending':
            phases[phase] = {'status':'pending', 'owner_manifest_input':None, 'outputs':{}}
            continue
        if execution[phase] == 'reused' and inherited is not None:
            original = inherited[phase]
            if original.get('status', 'success') != 'success':
                raise ValueError('A pending phase cannot be published as reused success')
            input_name = 'comsol_' + phase + '_source_manifest'
            record = original['manifest_record']
            config['inputs'][input_name] = str(record_path(record, base_dir=Path(original['owner_directory'])))
            config['input_sha256'][input_name] = record['sha256']
            phases[phase] = {'owner_manifest_input':input_name, 'outputs':original['outputs']}
        else:
            native_receipt = run_root / 'stage_receipts/comsol_native.json'
            native_records = load_json(native_receipt)['outputs'] if phase == 'native' and native_receipt.is_file() else {}
            outputs = {name:(native_records[name] if name in native_records else file_record(Path(evidence[name]))) for name in keys}
            if phase == 'native':
                context = Path(evidence['model'] + '.postprocess.json')
                if context.is_file():
                    outputs['saved_context'] = native_records.get('saved_context') or file_record(context)
            if phase == 'export':
                request = load_json(Path(evidence['analysis_request']))
                outputs['raw_events'] = file_record(Path(request['raw_events_csv']))
                context = Path(evidence['model'] + '.postprocess.json')
                if context.is_file() and context.is_relative_to(run_root):
                    outputs['saved_context'] = file_record(context)
            phases[phase] = {'owner_manifest_input':None, 'outputs':outputs}
    config.setdefault('provenance', {})['comsol_phases'] = phases
    write_json_atomic(config_path, config)


def _comsol_reuse_disposition(parent: Path, closure: dict, artifact_root: Path) -> dict:
    """Freeze actual required post-solve operations before capacity admission."""
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import candidate_comsol_source_phases
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import select_postprocess_parent
    origins = _comsol_phase_sources(parent)
    current = candidate_comsol_source_phases(closure)
    if origins['native']['implementation'] != current['native']:
        raise ValueError('COMSOL native scientific inputs/implementation changed; request the necessary new native stage')
    disposition = {phase:('reused' if origins[phase]['status'] == 'success' and current[phase] == origins[phase]['implementation'] else 'executed')
                   for phase in ('native','export','analysis','sync')}
    disposition['origins'] = origins
    disposition['analysis_source_owner'] = origins['export']['owner_directory']
    if disposition['export'] == 'reused':
        disposition['csv_selection'] = _comsol_csv_selection(origins)
    if disposition['export'] == 'executed':
        native = origins['native']
        context = native['outputs'].get('saved_context')
        if context is None:
            raise ValueError('Changed COMSOL exporter requires the original bound saved-solution context; CSV reanalysis remains available via --postprocess-from')
        selected = select_postprocess_parent(Path(native['owner_directory']), artifact_root)
        selected.update(exports=None, model_record=native['outputs']['model'], context_record=context,
                        parent=native['owner_directory'])
        disposition['cold_selection'] = selected
        disposition['analysis'] = 'executed'
    return disposition


def _record_candidate_native_completion(stage: dict, plan: dict) -> bool:
    """Publish only proven raw-save completion after the actual writer stopped.

    A failed extraction/plot wrapper can still have completed the unique native
    save prefix. The bound sidecar, original inputs and actual public writer
    facts are all required. No PASS is inferred from a model filename alone.
    """
    import math
    root = Path(plan['run_root'])
    model = Path(stage['model_path'])
    context_path = Path(str(model)+'.postprocess.json')
    if not context_path.is_file() or not model.is_file():
        return False
    writer = plan.get('writer_completion')
    operations = [] if not isinstance(writer, dict) else [row for row in writer['operations']
        if row.get('resource_release_id') == 'comsol_build_completion']
    if not operations or any(row.get('observation', {}).get('exit_confirmed') is not True for row in operations):
        return False
    closure = plan['execution_source_closure']
    verify_candidate_source_closure(closure)
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import project_comsol_native_implementation
    project_comsol_native_implementation(closure)
    writer_path = root/'logs/native_save_writer_facts.json'
    write_json_atomic(writer_path, writer)
    validator = frozen_source_path(closure, 'common/contracts/run_artifact_workflow.ps1')
    script = ". '"+validator.replace("'", "''")+"'; Assert-WorkflowWriterCompletion (Get-Content -Raw -Encoding UTF8 '"+str(writer_path).replace("'", "''")+"'|ConvertFrom-Json -AsHashtable)"
    _run_command(['pwsh','-NoProfile','-NonInteractive','-Command',script], root/'logs/native_save_writer_validation.log')
    config = load_json(root/'run_config.json')
    context = load_json(context_path)
    if (context.get('schema_version'),context.get('role'),context.get('solution_tag'),context.get('dataset_tag'),context.get('native_particle_solve_count')) != (1,'oatof_saved_particle_solution','sol2','pdset1',1):
        raise ValueError('Raw-save context does not prove the frozen native solve/save prefix')
    save_state = context.get('model_save_state')
    if not isinstance(save_state,str) or save_state not in {'raw_complete','gui_update_complete'}:
        config.setdefault('provenance', {})['model_save_completion'] = {
            'state':save_state,'status':'unknown','data_validity':'unknown',
            'context_record':file_record(context_path)}
        write_json_atomic(root/'run_config.json',config)
        raise ValueError('MODEL_SAVE_COMPLETION_UNKNOWN: GUI same-path update is unfinished or its completion evidence is missing; do not claim a raw/native saved asset. Sufficient sealed CSV may be analyzed separately; otherwise inspect the original saved/recovery model before another native request.')
    count = plan['run_instance']['particle_count']
    if type(count) is not int or count != 100 or context.get('particle_count') != count:
        raise ValueError('Raw-save population differs from the frozen Candidate request')
    times = context.get('solution_times_s')
    if not isinstance(times,list) or len(times)<2 or any(type(value) not in (int,float) or not math.isfinite(value) for value in times) or any(right<left for left,right in zip(times,times[1:])) or times[-1]<=times[0]:
        raise ValueError('Raw-save solution times are incomplete')
    if context.get('saved_model_bytes') != model.stat().st_size:
        raise ValueError('Raw-save context does not bind the actual persisted model size')
    for field, key in (('contract_path','candidate_resolved_geometry.json'),('source_path','candidate_particle_table')):
        if Path(context.get(field,'')).resolve() != Path(config['inputs'][key]).resolve():
            raise ValueError('Raw-save input differs from the frozen '+field)
    native_context = plan['comsol_native_context']
    model = model.resolve(strict=True)
    if not model.is_relative_to(root.resolve()):
        raise ValueError('A producer may establish identity only for its own saved model')
    guards = plan['_identity_guards']
    if model not in guards:
        guards[model] = plan['_model_guard_stack'].enter_context(guarded_file_identity(model))
    if guards[model].bytes_count != context['saved_model_bytes']:
        raise ValueError('Protected raw-save identity differs from its saved context')
    native_fact = {'stage_id':'comsol_native','status':'success','execution':'executed',
        'evidence':{'model':str(model),'saved_context':str(context_path)},
        'scope':'raw native solution saved; export, analysis and sync remain separate'}
    update_candidate_progress(root, [*plan.get('stage_results_so_far', []), native_fact], plan['stages'])
    receipt = write_stage_receipt(root, project='single_reflection_oa_tof_mass_analyzer',
        stage_id='comsol_native', context=native_context,
        outputs={'model':model, 'saved_context':context_path,
                 'build_completion':root/'logs/comsol_build_completion.json'}, allow_provisional_manifest=True, identity_guards=guards)
    config = load_json(root/'run_config.json')
    config.setdefault('provenance', {})['comsol_native_completion'] = file_record(receipt)
    write_json_atomic(root/'run_config.json',config)
    _publish_comsol_phase_sources(root,plan,
        {'model':str(model),'build_report':str(Path(stage['report_path']))},
        {'native':'executed','export':'pending','analysis':'pending','sync':'pending'})
    refresh_candidate_provisional_manifest(root)
    return True


def _comsol_csv_selection(origins: dict) -> dict:
    """Project sufficient existing events with their flat original science owner."""
    from common.contracts.verify_run_manifest import record_path
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import validate_artifact_capacity
    science = origins['native']
    science_manifest = load_json(Path(science['manifest_record']['path']))
    root = Path(science['owner_directory'])
    config_record = science_manifest['run_config']
    verify_record('original phase science config',config_record,base_dir=root)
    config = load_json(record_path(config_record,base_dir=root))
    def original_input(name):
        value = config['inputs'].get(name)
        if not isinstance(value,str) or not Path(value).is_absolute():
            raise ValueError('Original phase science lacks frozen '+name)
        record = science_manifest.get('inputs',{}).get(name)
        if record is None or record_path(record,base_dir=root)!=Path(value).resolve():
            raise ValueError('Original phase scientific input is not its declared manifest binding: '+name)
        verify_record(name,record,base_dir=root)
        return dict(record,path=value)
    inputs={'contract_path':original_input('candidate_resolved_geometry.json'),
            'source_path':original_input('candidate_particle_table')}
    budget=original_input('candidate_runtime.json')
    capacity=validate_artifact_capacity(load_json(Path(budget['path'])))
    exporter=origins['export']
    if exporter['status']!='success' or not {'analysis_request','raw_events'}<=exporter['outputs'].keys():
        raise ValueError('Original phase event export is not complete')
    return {'science_reference':{'manifest_record':science['manifest_record']},
        'export_source_reference':{'manifest_record':exporter['manifest_record']},
        'source_reference':{'manifest_record':science['manifest_record']},
        'source_references':[{'manifest_record':owner['manifest_record'],'protected_paths':[owner['owner_directory']]}
                            for owner in (science,exporter)],
        'inputs':inputs,'budget_record':budget,
        'exports':{'request':exporter['outputs']['analysis_request'],'events':exporter['outputs']['raw_events']},
        'new_bytes':capacity['evidence_bytes'],'native_runtime_bytes':0,
        'scope':'comsol_postprocessing_only','parent':science['owner_directory']}


def _freeze_comsol_postprocess_selection(run_root: Path, selection: dict) -> None:
    """Keep the existing recovery input shape for a normal post-solve consumer."""
    path=run_root/'inputs/postprocess_source_selection.json'
    if path.exists() and load_json(path)!=selection:
        raise ValueError('Normal post-solve source selection differs from its frozen request')
    write_json_atomic(path,selection)
    config=load_json(run_root/'run_config.json')
    config['inputs']['postprocess_source_selection']=str(path)
    config['input_sha256']['postprocess_source_selection']=sha256(path)
    config.setdefault('provenance',{})['science_reference']=selection['science_reference']
    write_json_atomic(run_root/'run_config.json',config)
