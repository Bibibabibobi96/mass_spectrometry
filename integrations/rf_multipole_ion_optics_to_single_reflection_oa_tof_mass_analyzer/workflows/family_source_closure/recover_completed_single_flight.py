"""Recover completed SIMION single-flight logs without a second solver dispatch.

The recovery output is a new run.  The failed solver run is immutable evidence;
all physical inputs and raw logs remain there and are hash-bound into the new
analysis-only child and its family parent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import record_path, verify_record


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
CHILD_MODE = "rf_to_oatof_simion_single_flight_analysis_recovery"
PARENT_MODE = "multipole_family_source_closure_analysis_recovery"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()


def _arguments(plan: dict[str, Any]) -> dict[str, str]:
    steps = plan.get("execution_steps")
    if not isinstance(steps, list) or len(steps) != 1:
        raise ContractError("failed parent composition plan must contain one step")
    result: dict[str, str] = {}
    for item in steps[0].get("arguments", []):
        if not isinstance(item, str) or "=" not in item:
            raise ContractError("failed parent composition argument is invalid")
        name, value = item.split("=", 1)
        if not name or name in result:
            raise ContractError("failed parent composition argument is duplicated")
        result[name] = value
    return result


def _gap_label(value: Any) -> str:
    try:
        gap = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ContractError("failed parent connector gap is invalid") from exc
    if not gap.is_finite() or gap < 0:
        raise ContractError("failed parent connector gap is invalid")
    text = format(gap, "f").rstrip("0").rstrip(".") or "0"
    return text.replace(".", "p")


def _verify_manifest(path: Path, *, status: str, mode: str | None = None) -> dict[str, Any]:
    manifest = _load(path)
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != status:
        raise ContractError(f"recovery source manifest identity/status differs: {path}")
    if mode is not None and manifest.get("mode") != mode:
        raise ContractError(f"recovery source manifest mode differs: {path}")
    try:
        verify_record("recovery source run_config", manifest["run_config"], base_dir=path.parent)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"recovery source input {name}", record, base_dir=path.parent)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"recovery source output {index}", record, base_dir=path.parent)
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("recovery source manifest record identity differs") from exc
    return manifest


def _find_failed_child(parent_dir: Path, plan: dict[str, Any], resolved: dict[str, Any]) -> Path:
    arguments = _arguments(plan)
    try:
        particle_count = int(arguments["pre_pulse_source_state_count"])
        stamp = parent_dir.name[:15]
    except (KeyError, ValueError) as exc:
        raise ContractError("failed parent cannot derive its single-flight child identity") from exc
    expected = f"{stamp}__sim__simion__rf-oatof-single-flight-gap{_gap_label(resolved['connector']['length_mm'])}__n{particle_count}"
    candidates = [parent_dir.parent / expected]
    if parent_dir.name.endswith("__r01"):
        candidates.append(parent_dir.parent / (expected + "__r01"))
    matches = [path for path in candidates if (path / "run_manifest.json").is_file()]
    if len(matches) != 1:
        raise ContractError("failed parent does not resolve exactly one completed single-flight child")
    return matches[0]


def _run(command: list[str], *, repo_root: Path, failure: str) -> None:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if completed.returncode:
        detail = (completed.stdout + completed.stderr).strip()
        raise ContractError(f"{failure}: {detail}")


def _write_manifest(*, repo_root: Path, run_dir: Path, outputs: list[Path]) -> Path:
    manifest = run_dir / "run_manifest.json"
    _run(
        [
            sys.executable, "-m", "common.contracts.write_run_manifest",
            "--run-config", str(run_dir / "run_config.json"), "--manifest", str(manifest),
            "--status", "success", "--software", f"Python {sys.version_info.major}.{sys.version_info.minor}",
            *sum((["--output", str(path)] for path in outputs), []),
        ], repo_root=repo_root, failure="recovery manifest publication failed",
    )
    return manifest


def recover(*, repo_root: Path, campaign_path: Path, failed_parent_dir: Path, recovery_parent_dir: Path) -> tuple[Path, Path]:
    failed_parent_manifest_path = failed_parent_dir / "run_manifest.json"
    _verify_manifest(
        failed_parent_manifest_path, status="failed", mode="multipole_family_source_closure"
    )
    parent_summary = _load(failed_parent_dir / "summary.json")
    plan = _load(failed_parent_dir / "composition_plan.json")
    resolved = _load(failed_parent_dir / "resolved_connection.json")
    args = _arguments(plan)
    campaign = _load(campaign_path)
    experiments = [row for row in campaign.get("experiments", []) if row.get("experiment_id") == args.get("experiment_id")]
    if len(experiments) != 1 or parent_summary.get("campaign_id") != campaign.get("campaign_id"):
        raise ContractError("failed parent campaign/experiment identity differs")
    if (
        args.get("campaign_path") != campaign_path.relative_to(repo_root).as_posix()
        or args.get("campaign_sha256", "").upper() != repository_text_sha256(campaign_path)
        or args.get("campaign_id") != campaign.get("campaign_id")
        or args.get("experiment_row_sha256", "").upper() != _sha(experiments[0])
    ):
        raise ContractError("failed parent frozen campaign identity differs")
    if parent_summary.get("experiment_id") != args["experiment_id"]:
        raise ContractError("failed parent summary experiment identity differs")
    child_dir = _find_failed_child(failed_parent_dir, plan, resolved)
    child_manifest_path = child_dir / "run_manifest.json"
    child_manifest = _verify_manifest(
        child_manifest_path, status="failed", mode="rf_to_oatof_simion_single_flight"
    )
    config_path = record_path(child_manifest["run_config"], base_dir=child_dir)
    config = _load(config_path)
    inputs = config.get("inputs")
    parameters = config.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        raise ContractError("failed child run configuration is incomplete")
    required = (
        "resolved_population_contract", "oatof_resolved_geometry", "initial_global_state",
        "particle_row_map", "pre_pulse_restart_validation", "upstream_resolved_design",
        "frontend_contract", "resolved_connection",
    )
    if any(not isinstance(inputs.get(key), str) or not Path(inputs[key]).is_file() for key in required):
        raise ContractError("failed child frozen analysis inputs are incomplete")
    logs = sorted((child_dir / "logs").glob("simion__batch*.stdout.log"))
    if len(logs) != 1 or not logs[0].is_file() or "Fly completed." not in logs[0].read_text(encoding="utf-8", errors="replace"):
        raise ContractError("failed child has no completed SIMION raw log eligible for finalization")
    validation = _load(Path(inputs["pre_pulse_restart_validation"]))
    tolerances = validation.get("tolerances", {})
    recovery_child_dir = recovery_parent_dir.parent / (child_dir.name + "__r01")
    if recovery_child_dir.exists() or recovery_parent_dir.exists():
        raise ContractError("recovery targets already exist and may not be overwritten")
    results = recovery_child_dir / "results"
    results.mkdir(parents=True)
    checkpoints = results / "single_flight_particle_checkpoints.csv"
    summary = recovery_child_dir / "summary.json"
    analysis = [
        sys.executable, "-m", "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight",
        "--mass-amu", "100", "--resolved-population-contract", inputs["resolved_population_contract"],
        "--resolved-population-contract-sha256", file_sha256(Path(inputs["resolved_population_contract"])),
        "--geometry", inputs["oatof_resolved_geometry"], "--clock-basis", str(parameters["clock_basis"]),
        "--initial-global-state", inputs["initial_global_state"], "--particle-row-map", inputs["particle_row_map"],
        "--initial-global-state-sha256", file_sha256(Path(inputs["initial_global_state"])),
        "--checkpoints", str(checkpoints), "--summary", str(summary), "--pulse-time-us", str(parameters["pulse_time_us"]),
        "--restart-position-tolerance-mm", str(tolerances["position_rowwise_abs_tolerance_mm"]),
        "--restart-velocity-tolerance-m-per-s", str(tolerances["velocity_rowwise_abs_tolerance_m_per_s"]),
        "--restart-clock-tolerance-us", str(tolerances["clock_abs_tolerance_us"]),
        "--restart-energy-tolerance-eV", str(tolerances["energy_abs_tolerance_eV"]),
        "--restart-validation-contract-sha256", file_sha256(Path(inputs["pre_pulse_restart_validation"])),
        "--configuration", inputs["configuration"], "--source-region-diagnostic-profile-id", str(parameters["source_region_diagnostic_profile_id"]),
        "--log", str(logs[0]), "--batch-particle-count", str(parameters["launched_particle_count"]),
    ]
    _run(analysis, repo_root=repo_root, failure="completed single-flight analysis recovery failed")
    spatial = results / "single_flight_spatial_six_panel.png"
    spatial_meta = results / "single_flight_spatial_six_panel_metadata.json"
    phase = results / "single_flight_accelerator_pre_pulse_phase_space.png"
    phase_meta = results / "single_flight_accelerator_pre_pulse_phase_space_metadata.json"
    phase_data = results / "single_flight_accelerator_pre_pulse_phase_space.csv"
    evolution = results / "single_flight_accelerator_checkpoint_evolution.png"
    evolution_meta = results / "single_flight_accelerator_checkpoint_evolution_metadata.json"
    evolution_data = results / "single_flight_accelerator_checkpoint_evolution.csv"
    _run([
        sys.executable, "-m", "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel",
        "--initial", inputs["initial_global_state"], "--checkpoints", str(checkpoints), "--upstream", inputs["upstream_resolved_design"],
        "--frontend", inputs["frontend_contract"], "--oatof", inputs["oatof_resolved_geometry"], "--output", str(spatial),
        "--metadata", str(spatial_meta), "--phase-space-output", str(phase), "--phase-space-metadata", str(phase_meta),
        "--phase-space-data", str(phase_data), "--evolution-output", str(evolution), "--evolution-metadata", str(evolution_meta), "--evolution-data", str(evolution_data),
    ], repo_root=repo_root, failure="completed single-flight diagnostic recovery failed")
    recovery_receipt = {
        "schema_version": 1, "role": "rf_oatof_completed_single_flight_analysis_recovery_receipt",
        "status": "success", "solver_reexecuted": False, "source_failed_child_manifest_sha256": file_sha256(child_manifest_path),
        "source_failed_parent_manifest_sha256": file_sha256(failed_parent_manifest_path),
        "raw_log": {"path": str(logs[0]), "sha256": file_sha256(logs[0])},
        "campaign": {"path": campaign_path.relative_to(repo_root).as_posix(), "sha256": repository_text_sha256(campaign_path), "experiment_id": args["experiment_id"]},
    }
    receipt = results / "completed_single_flight_analysis_recovery_receipt.json"
    receipt.write_text(json.dumps(recovery_receipt, indent=2) + "\n", encoding="utf-8")
    child_config = {
        "schema_version": 2, "run_id": recovery_child_dir.name, "project": INTEGRATION_ID, "mode": CHILD_MODE,
        "project_root": str(repo_root.parent), "inputs": {"failed_child_manifest": str(child_manifest_path), "failed_parent_manifest": str(failed_parent_manifest_path), "raw_log": str(logs[0]), "initial_global_state": inputs["initial_global_state"], "resolved_population_contract": inputs["resolved_population_contract"], "oatof_resolved_geometry": inputs["oatof_resolved_geometry"]},
        "parameters": {"recovery_source_run_id": child_dir.name, "connection_profile_id": parameters["connection_profile_id"], "source_branch_id": parameters["source_branch_id"], "launched_particle_count": parameters["launched_particle_count"]},
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}, "formal_gate_passed": False,
    }
    (recovery_child_dir / "run_config.json").write_text(json.dumps(child_config, indent=2) + "\n", encoding="utf-8")
    child_manifest_out = _write_manifest(repo_root=repo_root, run_dir=recovery_child_dir, outputs=[checkpoints, summary, spatial, spatial_meta, phase, phase_meta, phase_data, evolution, evolution_meta, evolution_data, receipt])
    recovery_parent_dir.mkdir(parents=True)
    parent_summary = {"schema_version": 1, "role": "integration_family_source_closure_summary", "status": "success", "execution_strategy": "simion_single_flight", "campaign_id": campaign["campaign_id"], "experiment_id": args["experiment_id"], "census": _load(summary).get("census"), "claim_status": "FUNCTIONAL_SCREEN_ONLY", "recovery": recovery_receipt, "formal_gate_passed": False}
    (recovery_parent_dir / "summary.json").write_text(json.dumps(parent_summary, indent=2) + "\n", encoding="utf-8")
    parent_config = {"schema_version": 2, "run_id": recovery_parent_dir.name, "project": INTEGRATION_ID, "mode": PARENT_MODE, "project_root": str(repo_root.parent), "inputs": {"campaign": str(campaign_path), "failed_parent_manifest": str(failed_parent_manifest_path), "recovered_child_manifest": str(child_manifest_out), "recovery_receipt": str(receipt)}, "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None}, "formal_gate_passed": False}
    (recovery_parent_dir / "run_config.json").write_text(json.dumps(parent_config, indent=2) + "\n", encoding="utf-8")
    parent_manifest_out = _write_manifest(repo_root=repo_root, run_dir=recovery_parent_dir, outputs=[recovery_parent_dir / "summary.json"])
    return child_manifest_out, parent_manifest_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--failed-parent-run-dir", required=True, type=Path)
    parser.add_argument("--recovery-parent-run-dir", required=True, type=Path)
    args = parser.parse_args()
    child, parent = recover(repo_root=args.repo_root.resolve(), campaign_path=args.campaign.resolve(), failed_parent_dir=args.failed_parent_run_dir.resolve(), recovery_parent_dir=args.recovery_parent_run_dir.resolve())
    print(f"COMPLETED_SINGLE_FLIGHT_FINALIZE=PASS CHILD={child} PARENT={parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
