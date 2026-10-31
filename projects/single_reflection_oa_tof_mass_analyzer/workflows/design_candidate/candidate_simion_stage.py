"""Frozen SIMION Candidate construction and scientific completion checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json, sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import frozen_source_path, verify_candidate_source_closure

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

def execute_simion_stage(stage: dict[str, Any], plan: dict[str, Any], simion_exe: str, *, runtime: Any) -> dict[str, Any]:
    """Execute the declared frozen SIMION stage using owner-managed processes."""
    from .candidate_stage_execution import _powershell, _require_pass_report
    _run_managed_stage_command = runtime._run_managed_stage_command
    closure = plan.get("execution_source_closure")
    if closure is not None:
        verify_candidate_source_closure(closure)
    run_root = Path(plan["run_root"])
    logs = run_root / "logs"
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
        "-CapacitySessionPath", plan["capacity_session_path"],
        "-ComponentPlanPath", plan["component_plan_path"],
        "-CompletionPath", str(logs / "simion_build_completion.json"),
        "-ContextSha256", plan["context_sha256"],
        "-ParticleCount", "100",
    ]
    if plan.get("producer_handoff_path"):
        arguments.extend(["-ProducerHandoffPath", plan["producer_handoff_path"]])
    _run_managed_stage_command(
        _powershell(
            frozen_source_path(closure, "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1"), arguments
        ),
        logs / "simion_build.log",
        plan, logs / "simion_build_completion.json", "oatof_component_build_completion",
    )
    iob = Path(stage["output_dir"]) / "oatof_ideal_grounded.iob"
    runtime_report = Path(stage["output_dir"]) / "build_logs" / "canonical_iob_verification.txt"
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
    _run_managed_stage_command(
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
                "-RuntimeReceiptPath", str(Path(stage["output_dir"]) / "simion_runtime_receipt.json"),
                "-CapacitySessionPath", plan["capacity_session_path"],
                "-CompletionPath", str(logs / "simion_flight_completion.json"),
                "-ContextSha256", plan["context_sha256"],
                "-RunId", plan["run_id"],
                "-PythonExe", closure["runtime"]["python_executable"],
            ],
        ),
        logs / "simion_transport_launcher.log",
        plan, logs / "simion_flight_completion.json", "oatof_candidate_flight_process_result",
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
