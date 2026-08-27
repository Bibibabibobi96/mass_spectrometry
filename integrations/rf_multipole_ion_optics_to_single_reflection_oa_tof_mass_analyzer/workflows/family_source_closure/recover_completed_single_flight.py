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

from common.contracts.file_identity import file_sha256
from common.contracts.artifact_naming import validate_run_id
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


def _verify_manifest(
    path: Path, *, status: str | tuple[str, ...], mode: str | None = None
) -> dict[str, Any]:
    manifest = _load(path)
    allowed_statuses = (status,) if isinstance(status, str) else status
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") not in allowed_statuses
    ):
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
        count_text = arguments.get("pre_pulse_source_state_count")
        if count_text is None:
            count_text = arguments["terminal_handoff_continued_particle_count"]
        particle_count = int(count_text)
        stamp = parent_dir.name[:15]
    except (KeyError, ValueError) as exc:
        raise ContractError("failed parent cannot derive its single-flight child identity") from exc
    expected = f"{stamp}__sim__simion__rf-oatof-single-flight-gap{_gap_label(resolved['connector']['length_mm'])}__n{particle_count}"
    candidates = [
        parent_dir.parent / (expected + "__r01")
        if parent_dir.name.endswith("__r01")
        else parent_dir.parent / expected
    ]
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


def _frozen_input_path(
    inputs: dict[str, Any], name: str, *, child_dir: Path,
) -> Path:
    """Resolve a frozen input after a temporary short execution path is removed."""

    value = inputs.get(name)
    if isinstance(value, str) and Path(value).is_file():
        return Path(value)
    filenames = {
        "resolved_population_contract": "resolved_population_contract.json",
        "oatof_resolved_geometry": "oatof_resolved_geometry.json",
        "initial_global_state": "single_flight_initial_global_state.csv",
        "particle_row_map": "single_flight_particle_row_map.csv",
        "pre_pulse_restart_validation": "canonical_pulse_restart_target_state_validation.json",
        "upstream_resolved_design": "upstream_resolved_design.json",
        "frontend_contract": "single_flight_frontend_contract.json",
        "resolved_connection": "resolved_connection.json",
        "configuration": "simion_single_flight.json",
        "simion_execution_batch_plan": "simion_execution_batch_plan.json",
    }
    retained = child_dir / "inputs" / filenames.get(name, "")
    if not retained.is_file():
        raise ContractError(f"failed child frozen analysis input is missing: {name}")
    return retained


def _completed_batch_logs(
    *, child_dir: Path, inputs: dict[str, Any], launched_count: int,
) -> tuple[list[Path], list[int]]:
    """Recover every completed wave, preserving its frozen ID offset/count."""

    logs = sorted((child_dir / "logs").glob("simion__batch*.stdout.log"))
    if not logs or any(
        not log.is_file() or "Fly completed." not in log.read_text(
            encoding="utf-8", errors="replace",
        )
        for log in logs
    ):
        raise ContractError("failed child has no completed SIMION raw log eligible for finalization")
    plan_path = _frozen_input_path(
        inputs, "simion_execution_batch_plan", child_dir=child_dir,
    )
    plan = _load(plan_path)
    batches = plan.get("batches")
    if (
        not isinstance(batches, list)
        or len(batches) != len(logs)
        or sum(int(batch["count"]) for batch in batches) != launched_count
    ):
        raise ContractError("failed child batch plan differs from completed logs")
    return logs, [int(batch["count"]) for batch in batches]


def _recovery_child_dir(recovery_parent_dir: Path, particle_count: int) -> Path:
    """Give analysis recovery its own valid, immutable child identity."""

    identity = validate_run_id(recovery_parent_dir.name)
    retry = f"__r{identity['retry']}" if identity.get("retry") else ""
    run_id = (
        f"{identity['stamp']}__analysis__simion__recovered-single-flight"
        f"__n{particle_count}{retry}"
    )
    validate_run_id(run_id)
    return recovery_parent_dir.parent / run_id


def _source_region_diagnostic_profile_id(
    parameters: dict[str, Any], configuration_path: Path,
) -> str | None:
    """Use the frozen explicit profile, or the sole frozen default profile."""

    explicit = parameters.get("source_region_diagnostic_profile_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    profiles = _load(configuration_path).get("source_region_diagnostic_profiles")
    if not isinstance(profiles, list) or len(profiles) != 1:
        return None
    profile_id = profiles[0].get("profile_id") if isinstance(profiles[0], dict) else None
    return profile_id if isinstance(profile_id, str) and profile_id else None


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
        failed_parent_manifest_path, status=("failed", "interrupted"),
        mode="multipole_family_source_closure"
    )
    parent_summary = _load(failed_parent_dir / "summary.json")
    plan = _load(failed_parent_dir / "composition_plan.json")
    resolved = _load(failed_parent_dir / "resolved_connection.json")
    args = _arguments(plan)
    frozen_campaign_path = failed_parent_dir / args["frozen_campaign_experiment_filename"]
    frozen_campaign = _load(frozen_campaign_path)
    if file_sha256(frozen_campaign_path) != args["frozen_campaign_experiment_sha256"]:
        raise ContractError("failed parent frozen campaign experiment identity differs")
    campaign = frozen_campaign.get("campaign")
    experiment = frozen_campaign.get("experiment")
    campaign_source = frozen_campaign.get("campaign_source")
    if not isinstance(campaign, dict) or not isinstance(experiment, dict) or not isinstance(campaign_source, dict):
        raise ContractError("failed parent frozen campaign experiment is incomplete")
    if parent_summary.get("campaign_id") != campaign.get("campaign_id"):
        raise ContractError("failed parent campaign identity differs")
    if (
        args.get("campaign_path") != campaign_source.get("path")
        or args.get("campaign_sha256", "").upper() != campaign_source.get("sha256")
        or args.get("campaign_id") != campaign.get("campaign_id")
        or args.get("experiment_id") != experiment.get("experiment_id")
        or args.get("experiment_row_sha256", "").upper()
        != frozen_campaign.get("experiment_row_sha256")
    ):
        raise ContractError("failed parent frozen campaign identity differs")
    if parent_summary.get("experiment_id") != args["experiment_id"]:
        raise ContractError("failed parent summary experiment identity differs")
    child_dir = _find_failed_child(failed_parent_dir, plan, resolved)
    child_manifest_path = child_dir / "run_manifest.json"
    child_manifest = _verify_manifest(
        child_manifest_path, status=("failed", "interrupted", "success"),
        mode="rf_to_oatof_simion_single_flight"
    )
    config_path = record_path(child_manifest["run_config"], base_dir=child_dir)
    config = _load(config_path)
    inputs = config.get("inputs")
    parameters = config.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        raise ContractError("failed child run configuration is incomplete")
    required = (
        "resolved_population_contract", "oatof_resolved_geometry", "initial_global_state",
        "particle_row_map", "upstream_resolved_design", "frontend_contract",
        "resolved_connection", "configuration",
    )
    frozen_inputs = {
        name: _frozen_input_path(inputs, name, child_dir=child_dir)
        for name in required
    }
    population = _load(frozen_inputs["resolved_population_contract"])
    source_release_mode = population.get("source_release_mode")
    if source_release_mode not in {
        "continuous_frontend", "continuous_frontend_handoff", "pre_pulse_restart",
    }:
        raise ContractError("failed child source-release mode is unsupported")
    if source_release_mode == "pre_pulse_restart":
        frozen_inputs["pre_pulse_restart_validation"] = _frozen_input_path(
            inputs, "pre_pulse_restart_validation", child_dir=child_dir,
        )
    launched_count = int(parameters["launched_particle_count"])
    logs, batch_counts = _completed_batch_logs(
        child_dir=child_dir, inputs=inputs, launched_count=launched_count,
    )
    recovery_child_dir = _recovery_child_dir(
        recovery_parent_dir, launched_count,
    )
    if recovery_child_dir.exists() or recovery_parent_dir.exists():
        raise ContractError("recovery targets already exist and may not be overwritten")
    results = recovery_child_dir / "results"
    results.mkdir(parents=True)
    checkpoints = results / "single_flight_particle_checkpoints.csv"
    summary = recovery_child_dir / "summary.json"
    analysis = [
        sys.executable, "-m", "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight",
        "--resolved-population-contract", str(frozen_inputs["resolved_population_contract"]),
        "--resolved-population-contract-sha256", file_sha256(frozen_inputs["resolved_population_contract"]),
        "--geometry", str(frozen_inputs["oatof_resolved_geometry"]), "--clock-basis", str(parameters["clock_basis"]),
        "--initial-global-state", str(frozen_inputs["initial_global_state"]), "--particle-row-map", str(frozen_inputs["particle_row_map"]),
        "--initial-global-state-sha256", file_sha256(frozen_inputs["initial_global_state"]),
        "--checkpoints", str(checkpoints), "--summary", str(summary), "--pulse-time-us", str(parameters["pulse_time_us"]),
        "--configuration", str(frozen_inputs["configuration"]),
    ]
    for log, batch_count in zip(logs, batch_counts, strict=True):
        analysis.extend(["--log", str(log), "--batch-particle-count", str(batch_count)])
    if source_release_mode == "pre_pulse_restart":
        tolerances = _load(frozen_inputs["pre_pulse_restart_validation"]).get("tolerances", {})
        analysis.extend([
            "--restart-position-tolerance-mm", str(tolerances["position_rowwise_abs_tolerance_mm"]),
            "--restart-velocity-tolerance-m-per-s", str(tolerances["velocity_rowwise_abs_tolerance_m_per_s"]),
            "--restart-clock-tolerance-us", str(tolerances["clock_abs_tolerance_us"]),
            "--restart-energy-tolerance-eV", str(tolerances["energy_rowwise_abs_tolerance_eV"]),
            "--restart-validation-contract-sha256", file_sha256(frozen_inputs["pre_pulse_restart_validation"]),
        ])
    profile_id = _source_region_diagnostic_profile_id(
        parameters, frozen_inputs["configuration"],
    )
    if profile_id is not None:
        analysis.extend(["--source-region-diagnostic-profile-id", profile_id])
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
        "--initial", str(frozen_inputs["initial_global_state"]), "--checkpoints", str(checkpoints), "--upstream", str(frozen_inputs["upstream_resolved_design"]),
        "--frontend", str(frozen_inputs["frontend_contract"]), "--oatof", str(frozen_inputs["oatof_resolved_geometry"]), "--output", str(spatial),
        "--metadata", str(spatial_meta), "--phase-space-output", str(phase), "--phase-space-metadata", str(phase_meta),
        "--phase-space-data", str(phase_data), "--evolution-output", str(evolution), "--evolution-metadata", str(evolution_meta), "--evolution-data", str(evolution_data),
    ], repo_root=repo_root, failure="completed single-flight diagnostic recovery failed")
    recovery_receipt = {
        "schema_version": 1, "role": "rf_oatof_completed_single_flight_analysis_recovery_receipt",
        "status": "success", "solver_reexecuted": False, "source_failed_child_manifest_sha256": file_sha256(child_manifest_path),
        "source_failed_parent_manifest_sha256": file_sha256(failed_parent_manifest_path),
        "raw_logs": [
            {"path": str(log), "sha256": file_sha256(log), "particle_count": count}
            for log, count in zip(logs, batch_counts, strict=True)
        ],
        "campaign": {
            "path": campaign_source["path"],
            "sha256": campaign_source["sha256"],
            "experiment_id": args["experiment_id"],
            "frozen_parent_experiment": str(frozen_campaign_path),
            "frozen_parent_experiment_sha256": file_sha256(frozen_campaign_path),
        },
        "source_region_diagnostic_profile_id": profile_id,
    }
    receipt = results / "completed_single_flight_analysis_recovery_receipt.json"
    receipt.write_text(json.dumps(recovery_receipt, indent=2) + "\n", encoding="utf-8")
    child_config = {
        "schema_version": 2, "run_id": recovery_child_dir.name, "project": INTEGRATION_ID, "mode": CHILD_MODE,
        "project_root": str(repo_root.parent), "inputs": {"failed_child_manifest": str(child_manifest_path), "failed_parent_manifest": str(failed_parent_manifest_path), "raw_logs": [str(log) for log in logs], "initial_global_state": str(frozen_inputs["initial_global_state"]), "resolved_population_contract": str(frozen_inputs["resolved_population_contract"]), "oatof_resolved_geometry": str(frozen_inputs["oatof_resolved_geometry"])},
        "parameters": {"recovery_source_run_id": child_dir.name, "connection_profile_id": parameters["connection_profile_id"], "source_branch_id": parameters["source_branch_id"], "source_release_mode": source_release_mode, "launched_particle_count": parameters["launched_particle_count"]},
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
