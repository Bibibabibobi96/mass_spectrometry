"""Execute one prepared oa-TOF candidate workflow without promoting it."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.stage_reuse import validate_and_write_stage_reuse, write_stage_receipt
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_run_lifecycle import (
    finalize_candidate_run,
    refresh_candidate_provisional_manifest,
    start_candidate_run,
    update_candidate_progress,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path, verify_candidate_source_closure


StageExecutor = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]
STAGE_PROCESS_TIMEOUT_S = 4 * 60 * 60
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
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",
    ),
    "simion_candidate": (
        "projects/single_reflection_oa_tof_mass_analyzer/simion/",
        "projects/single_reflection_oa_tof_mass_analyzer/analysis/generate_ion_source.py",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1",
        "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",
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
        "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",
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


def _powershell(entrypoint: str, arguments: list[str]) -> list[str]:
    # The shared COMSOL launcher uses ProcessStartInfo.ArgumentList, which is
    # unavailable under Windows PowerShell 5.1.  Keep integrated commercial
    # workflows on the repository's PowerShell 7 runtime.
    return ["pwsh.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", entrypoint, *arguments]


def _run_command(command: list[str], log_path: Path, environment: dict[str, str] | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(environment or {})
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=STAGE_PROCESS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as error:
            raise StageTimedOut(f"command exceeded {STAGE_PROCESS_TIMEOUT_S}s; log={log_path}") from error
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}; log={log_path}")


def _ps_arguments(values: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in values.items():
        result.extend([f"-{key}", str(value)])
    return result


def _require_pass_report(path: Path) -> None:
    if not path.is_file() or "STATUS=PASS" not in path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"required PASS report is missing or failed: {path}")


def _report_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if value:
                return value
    raise RuntimeError(f"required {key} record is missing from {path}")


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


def _nonformal_template(stage: dict[str, Any], plan: dict[str, Any]) -> Path:
    if stage.get("status") == "blocked_requires_explicit_nonformal_template":
        raise RuntimeError("candidate SIMION stage is blocked until an explicit non-Formal template is frozen")
    record = stage.get("template_input")
    if not isinstance(record, dict):
        raise RuntimeError("candidate SIMION template input is missing")
    run_inputs = (Path(plan["run_root"]) / "inputs").resolve()
    if record.get("role") != "oa_tof_candidate_simion_layout_template":
        raise RuntimeError("candidate SIMION template has an unsupported role")
    files = record.get("files")
    if not isinstance(files, dict) or set(files) != {"iob", "con"}:
        raise RuntimeError("candidate SIMION template requires frozen IOB and CON records")
    verified: dict[str, Path] = {}
    for suffix, item in files.items():
        path = Path(item.get("path", "")).resolve() if isinstance(item, dict) else Path()
        if not path.is_file() or run_inputs not in path.parents:
            raise RuntimeError("candidate SIMION template must be a frozen run input")
        if sha256(path).lower() != str(item.get("sha256", "")).lower():
            raise RuntimeError("candidate SIMION template changed after freezing")
        prohibited = {"formal", "archive", "history"}
        if prohibited.intersection(part.lower() for part in path.parts):
            raise RuntimeError(
                "candidate SIMION template must not reference a Formal, archive, or history path"
            )
        if path.suffix.lower() != f".{suffix}":
            raise RuntimeError("candidate SIMION template file suffix is invalid")
        verified[suffix] = path
    if verified["iob"].with_suffix(".con").name != verified["con"].name or verified["iob"].parent != verified["con"].parent:
        raise RuntimeError("candidate SIMION IOB and CON template bundle names do not match")
    registration_run_id = str(record.get("registration_run_id", ""))
    registration_record = record.get("registration_manifest", {})
    registration_manifest = Path(str(registration_record.get("path", ""))).resolve()
    registration_sha = str(registration_record.get("sha256", ""))
    registration_document = load_json(registration_manifest)
    if (
        not registration_manifest.is_file()
        or run_inputs not in registration_manifest.parents
        or not registration_sha
        or sha256(registration_manifest).lower() != registration_sha.lower()
        or registration_document.get("run_id") != registration_run_id
        or registration_document.get("status") != "success"
    ):
        raise RuntimeError("candidate SIMION template registration evidence changed after preparation")
    return verified["iob"]


def execute_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str) -> dict[str, Any]:
    stage_id = stage["stage_id"]
    if stage_id == "simion_candidate" and stage.get("status") == "blocked_requires_explicit_nonformal_template":
        raise RuntimeError("candidate SIMION stage is blocked until an explicit non-Formal template is frozen")
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

    if stage_id == "comsol_candidate":
        if closure is None:
            raise RuntimeError("candidate source closure is required")
        _verify_frozen_cad_python(closure, logs / "cad_python_preflight.log")
        environment = {key: str(value) for key, value in stage["environment"].items()}
        build_report = Path(stage["report_path"])
        build_command = _powershell(
            frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
            [
                "-TaskScript",
                frozen_source_path(
                    closure,
                    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m",
                ),
                "-ReportPath",
                str(build_report),
            ],
        )
        _run_command(build_command, logs / "comsol_build_launcher.log", environment)
        _require_pass_report(build_report)
        analysis_request = Path(_report_value(build_report, "PYTHON_ANALYSIS_REQUEST"))
        if not analysis_request.is_file():
            raise RuntimeError(f"COMSOL detector-event analysis request is missing: {analysis_request}")
        _run_command(
            [
                str(Path(closure["runtime"]["python_executable"]).resolve()),
                "-m",
                "projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events",
                "--request",
                str(analysis_request),
            ],
            logs / "comsol_detector_event_analysis.log",
        )
        request_document = load_json(analysis_request)
        analysis_output = Path(request_document["analysis_output_dir"])
        analysis_receipt = analysis_output / "analysis_receipt.json"
        if not analysis_receipt.is_file():
            raise RuntimeError(f"COMSOL detector-event Python analysis receipt is missing: {analysis_receipt}")
        sync_report = logs / "comsol_sync.txt"
        sync_environment = {
            "OATOF_COMSOL_MODEL_PATH": stage["model_path"],
            "OATOF_CONTRACT_PATH": stage["contract_path"],
        }
        sync_command = _powershell(
            frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
            [
                "-TaskScript",
                frozen_source_path(
                    closure,
                    "projects/single_reflection_oa_tof_mass_analyzer/comsol/verify_oatof_comsol_sync.m",
                ),
                "-ReportPath",
                str(sync_report),
            ],
        )
        _run_command(sync_command, logs / "comsol_sync_launcher.log", sync_environment)
        _require_pass_report(sync_report)
        return {
            "model": stage["model_path"], "build_report": str(build_report),
            "sync_report": str(sync_report), "analysis_request": str(analysis_request),
            "analysis_receipt": str(analysis_receipt),
        }

    if stage_id == "simion_candidate":
        template = _nonformal_template(stage, plan)
        if closure is None:
            raise RuntimeError("candidate source closure is required")
        artifact_project_root = run_root.resolve().parent.parent
        arguments = [
            "-OutputDir",
            stage["output_dir"],
            "-ArtifactProjectRoot",
            str(artifact_project_root),
            "-RunId",
            plan["run_id"],
            "-ContractPath",
            stage["contract_path"],
            "-CandidateBaselinePath",
            stage["baseline_path"],
            "-CandidateTextDir",
            stage["text_dir"],
            "-SimionExe",
            simion_exe,
            "-DeferRunFinalization",
            "-TemplateIob",
            str(template),
            "-ParticleSeed",
            str(plan.get("run_instance", {}).get("particle_source_seed", "")),
        ]
        _run_command(
            _powershell(
                frozen_source_path(closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1"), arguments
            ),
            logs / "simion_build.log",
        )
        iob = Path(stage["output_dir"]) / "oatof_ideal_grounded.iob"
        verify = frozen_source_path(
            closure,
            "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/verify_iob_runtime_contract.ps1",
        )
        _run_command(
            _powershell(verify, ["-IobPath", str(iob), "-SimionExe", simion_exe]),
            logs / "simion_runtime_verify.log",
        )
        runtime_report = logs / "simion_runtime_verify.log"
        _require_pass_report(runtime_report)
        summary = Path(stage["output_dir"]) / "stage_summary.json"
        if load_json(summary).get("status") != "success":
            raise RuntimeError("SIMION candidate stage summary did not pass")
        ion_n100 = Path(stage["output_dir"]) / "oatof_comsol_524amu_gaussian_N100.ion"
        if not ion_n100.is_file():
            raise RuntimeError(f"SIMION candidate N=100 particle table is missing: {ion_n100}")
        particle_count = sum(1 for line in ion_n100.read_text(encoding="utf-8").splitlines() if line.strip())
        validate_standard_particle_count(particle_count)
        if particle_count != 100:
            raise RuntimeError("oa-TOF candidate workflow requires the N=100 functional tier")
        resolved_contract = load_json(Path(stage["contract_path"]))
        detector_radius_mm = resolved_contract["simion_detector_marker"]["active_radius_mm"]
        particle_csv = run_root / "results" / "simion_particles.csv"
        diagnostics = run_root / "results" / "simion_transport_diagnostics.json"
        transport_summary = run_root / "results" / "simion_transport_summary.json"
        transport = frozen_source_path(
            closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_n100_transport.ps1"
        )
        analyzer = frozen_source_path(
            closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1"
        )
        _run_command(
            _powershell(
                transport,
                [
                    "-SimionExe", simion_exe,
                    "-IobPath", str(iob),
                    "-IonPath", str(ion_n100),
                    "-LogPath", str(logs / "simion_n100.log"),
                    "-ErrorPath", str(logs / "simion_n100.stderr.log"),
                    "-DiagnosticsPath", str(diagnostics),
                    "-ParticleCsv", str(particle_csv),
                    "-SummaryPath", str(transport_summary),
                    "-AnalyzerScript", analyzer,
                    "-ResolvedContractPath", stage["contract_path"],
                    "-ExpectedParticleCount", "100",
                    "-ExpectedTrajectoryQuality", "8",
                    "-DetectorRadiusMm", str(detector_radius_mm),
                ],
            ),
            logs / "simion_transport_launcher.log",
        )
        transport_record = load_json(transport_summary)
        if (
            transport_record.get("status") != "success"
            or transport_record.get("expected_particle_count") != 100
            or transport_record.get("trajectory_quality") != 8
            or any(transport_record.get(key) != 100 for key in ("emitted", "crossed", "hit"))
        ):
            raise RuntimeError("SIMION candidate N=100 transport summary did not pass")
        return {
            "iob": str(iob),
            "ion_n100": str(ion_n100),
            "stage_summary": str(summary),
            "runtime_report": str(runtime_report),
            "transport_summary": str(transport_summary),
            "particle_csv": str(particle_csv),
            "transport_diagnostics": str(diagnostics),
        }

    if stage_id == "cad_candidate":
        if closure is None:
            raise RuntimeError("candidate source closure is required")
        report = logs / "cad_build.txt"
        environment = {
            "OATOF_CANDIDATE_MODEL_PATH": stage["model_path"],
            "OATOF_CANDIDATE_CAD_DIR": stage["output_dir"],
            "OATOF_CANDIDATE_PYTHON_EXECUTABLE": str(
                Path(closure["runtime"]["python_executable"]).resolve()
            ),
        }
        command = _powershell(
            frozen_source_path(closure, "common/comsol/run_comsol_r2025b.ps1"),
            [
                "-TaskScript",
                frozen_source_path(
                    closure,
                    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_cad_sync.m",
                ),
                "-ReportPath",
                str(report),
            ],
        )
        _run_command(command, logs / "cad_launcher.log", environment)
        _require_pass_report(report)
        cad_report = Path(stage["output_dir"]) / "oaTOF_solidworks_export_report.json"
        if not cad_report.is_file():
            raise RuntimeError(f"candidate CAD report is missing: {cad_report}")
        return {"report": str(report), "cad_report": str(cad_report)}

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

    raise ValueError(f"unsupported candidate workflow stage: {stage_id}")


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


def run_candidate_workflow(
    plan_path: Path,
    simion_exe: str,
    stage_executor: StageExecutor = execute_stage,
    *,
    reuse_parent: Path | None = None,
    reuse_through: str | None = None,
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
    run_root = start_candidate_run(plan_path)
    runtime_plan_path = run_root / "candidate_workflow_plan.json"
    runtime_plan = load_json(runtime_plan_path)
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
        summary, _ = finalize_candidate_run(run_root, "success", results)
        return run_root, summary
    except KeyboardInterrupt as exc:
        interrupted = _failure_results(
            stages,
            results,
            current_stage,
            status="interrupted",
            error=str(exc),
        )
        finalize_candidate_run(run_root, "interrupted", interrupted, current_stage)
        raise CandidateWorkflowInterrupted(run_root) from exc
    except StageTimedOut as exc:
        failed = _failure_results(
            stages,
            results,
            current_stage,
            status="failed",
            error=str(exc),
            failure_class="timeout",
        )
        finalize_candidate_run(run_root, "failed", failed, current_stage)
        raise CandidateWorkflowTimedOut(run_root) from exc
    except Exception as exc:
        failed = _failure_results(
            stages,
            results,
            current_stage,
            status="failed",
            error=str(exc),
        )
        finalize_candidate_run(run_root, "failed", failed, current_stage)
        raise CandidateWorkflowError(str(exc), run_root) from exc
